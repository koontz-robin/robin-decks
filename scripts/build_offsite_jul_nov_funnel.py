#!/usr/bin/env python3
import ast
import json
from collections import defaultdict
from pathlib import Path
import requests

WORKSPACE=Path('/home/openclaw/.openclaw/workspace')
OUT=WORKSPACE/'leadership_offsite_jul_nov_funnel.json'
SF_INSTANCE='https://rev-io.my.salesforce.com'
# Reuse the existing Salesforce app credentials without duplicating secrets.
refresh_tree=ast.parse((WORKSPACE/'refresh_forecast.py').read_text())
refresh_values={}
for node in refresh_tree.body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
        if node.targets[0].id in {'SF_CLIENT_ID','SF_CLIENT_SECRET'}:
            refresh_values[node.targets[0].id]=ast.literal_eval(node.value)
SF_CLIENT_ID=refresh_values['SF_CLIENT_ID']
SF_CLIENT_SECRET=refresh_values['SF_CLIENT_SECRET']
START='2026-07-01T00:00:00Z'
END='2026-12-01T00:00:00Z'
STAGES=[
 ('1- Discovery Scheduled','Stage 1 · Discovery Scheduled'),
 ('2 - Discovery Completed','Stage 2 · Discovery Completed'),
 ('3 - Initial Product Demo','Stage 3 · Initial Product Demo'),
 ('4 - Proposal Sent','Stage 4 · Proposal Sent'),
 ('5 - Product / Contract Validated','Stage 5 · Product / Contract Validated'),
 ('6 - Verbal Commit','Stage 6 · Verbal Commit'),
 ('Closed Won','Closed Won'),
]
RANK={name:i+1 for i,(name,_) in enumerate(STAGES)}

def query(base,headers,soql):
    rows=[]; url=f'{base}/services/data/v59.0/query'; params={'q':soql}
    while True:
        r=requests.get(url,headers=headers,params=params,timeout=60); r.raise_for_status(); data=r.json()
        rows.extend(data.get('records',[]))
        if data.get('done',True): return rows
        url=base+data['nextRecordsUrl']; params={}

a=requests.post(f'{SF_INSTANCE}/services/oauth2/token',data={'grant_type':'client_credentials','client_id':SF_CLIENT_ID,'client_secret':SF_CLIENT_SECRET},timeout=30)
a.raise_for_status(); auth=a.json(); base=auth['instance_url']; headers={'Authorization':f"Bearer {auth['access_token']}"}
opps=query(base,headers,f"""
SELECT Id, Name, CreatedDate, StageName, Amount, Type, Product_Type__c,
       Account.Name, Account.NumberOfEmployees
FROM Opportunity
WHERE CreatedDate >= {START} AND CreatedDate < {END}
  AND Product_Type__c = 'PSA 2.0'
  AND IsDeleted = false
ORDER BY CreatedDate
""")
ids=[o['Id'] for o in opps]
history=[]
for i in range(0,len(ids),150):
    batch=','.join("'%s'"%x for x in ids[i:i+150])
    history += query(base,headers,f"""
SELECT OpportunityId, OldValue, NewValue, CreatedDate
FROM OpportunityFieldHistory
WHERE Field = 'StageName' AND OpportunityId IN ({batch})
ORDER BY CreatedDate
""")
by_opp=defaultdict(list)
for h in history: by_opp[h['OpportunityId']].append(h)

def max_rank(o):
    values=[o.get('StageName')]
    for h in by_opp[o['Id']]: values += [h.get('OldValue'),h.get('NewValue')]
    # Every created opportunity enters the funnel at Stage 1 even if its stage
    # history was not retained before it later closed lost.
    return max(1, max([RANK.get(str(v),0) for v in values] or [1]))

def is_icp(o):
    employees=(o.get('Account') or {}).get('NumberOfEmployees')
    amount=o.get('Amount')
    return employees is not None and employees >= 10 and amount is not None and amount >= 1000

def summarize(rows):
    ranks=[max_rank(o) for o in rows]
    reached=[sum(r>=n for r in ranks) for n in range(1,len(STAGES)+1)]
    transitions=[]
    for i in range(len(STAGES)-1):
        transitions.append({
            'from':STAGES[i][1], 'to':STAGES[i+1][1],
            'from_count':reached[i], 'to_count':reached[i+1],
            'conversion_pct':round(reached[i+1]/reached[i]*100,1) if reached[i] else None,
        })
    won=sum(o.get('StageName')=='Closed Won' for o in rows)
    lost=sum(o.get('StageName')=='Closed Lost' for o in rows)
    war_room_rows=[o for o in rows if max_rank(o) >= 3]
    war_room_won=sum(o.get('StageName')=='Closed Won' for o in war_room_rows)
    war_room_lost=sum(o.get('StageName')=='Closed Lost' for o in war_room_rows)
    return {'opportunities':len(rows),'reached_counts':reached,'transitions':transitions,'closed_won':won,'closed_lost':lost,
            'decision_win_rate_pct':round(won/(won+lost)*100,1) if won+lost else None,
            'war_room_closed_won':war_room_won,'war_room_closed_lost':war_room_lost,
            'war_room_decision_win_rate_pct':round(war_room_won/(war_room_won+war_room_lost)*100,1) if war_room_won+war_room_lost else None}

type_counts={}
for o in opps:
    key=o.get('Type') or 'Blank'
    type_counts[key]=type_counts.get(key,0)+1
new_deals=[o for o in opps if o.get('Type') == 'New Opportunity']
expansions=[o for o in opps if o.get('Type') == 'Add-On / Expansion']
icp_opps=[o for o in opps if is_icp(o)]
payload={'window':{'start':'2026-07-01','end_exclusive':'2026-12-01','label':'July–November 2026'},
         'definition':{'all_new_revio':"Product_Type__c = 'PSA 2.0'",'icp':'NumberOfEmployees >= 10 and Amount >= $1,000',
                       'new_deal':"Type = 'New Opportunity'",'expansion':"Type = 'Add-On / Expansion'",
                       'conversion':'Opportunities reaching next stage divided by opportunities reaching prior stage; highest stage reached uses OpportunityFieldHistory.'},
         'opportunity_type_counts':type_counts,
         'all_new_revio':summarize(opps),
         'icp':summarize(icp_opps),
         'all_new_revio_by_type':{'new_deal':summarize(new_deals),'expansion':summarize(expansions)},
         'icp_by_type':{'new_deal':summarize([o for o in new_deals if is_icp(o)]),'expansion':summarize([o for o in expansions if is_icp(o)])}}
OUT.write_text(json.dumps(payload,indent=2)+'\n')
print(json.dumps(payload,indent=2))
