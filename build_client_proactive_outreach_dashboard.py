#!/usr/bin/env python3
"""Build the requested-client 2026 proactive outreach dashboard from live Salesforce.

Read-only. Outbound counts exclude inbound email tasks and inbound calls. Meetings are
reported separately and are not included in outbound-touch totals.
"""
from __future__ import annotations
import json, re, os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from build_2026_psa_team_tracker import sf_auth, sf_query

ROOT=Path(os.environ.get('ROBIN_WORKSPACE','/home/openclaw/.openclaw/workspace'))
JSON_PATH=ROOT/'client_proactive_outreach_2026.json'
HTML_PATH=ROOT/'client-proactive-outreach-2026.html'
YEAR_START='2026-01-01T00:00:00Z'; YEAR_END='2027-01-01T00:00:00Z'
CLIENTS='''CallTower
Skyswitch
BCM ONE C/O InvoiceIQ
Spectrotel
Valhelio Tech
Telesystem
Hunter Communications
Nuso LLC
Prestige Technology LLC
TPX Communications
Zultys Business Phone Solutions
Broadvoice
Tailwinds Voice & Data, Inc.
Crexendo Business Solutions
TouchTone
SpectrumVoIP
Mango Voice
Mango Voice, LLC
Cloudli Communications
Viirtue LLC (Apollo)
South Carolina Telecommunications Group Holdings, LLC
Estech Systems, Inc
NinjaOne, LLC (Sponsor)
XMission
Vocus Group Ltd.
WoltersKluwer (Sponsor)
PS Lightwave LLC Operating Account
CCI Network Services
Coeo Solutions, LLC.
Titanium Wireless
Clear Rate Communications
S-Net
PS Lightwave LLC
Xchange Telecom'''.splitlines()

# Curated against live Salesforce on 2026-09-15. Multiple requested labels may intentionally
# point to one account. Probable legal-name aliases are explicitly called out in match_note.
MATCHES={
'CallTower':(['0011500001HNQEXAA5'],'exact'), 'Skyswitch':(['0011500001nQiaxAAC'],'case-insensitive exact; reseller/test children excluded'),
'BCM ONE C/O InvoiceIQ':(['0011500001HNPjbAAH'],'matched to client account BCM One; InvoiceIQ is requester qualifier'),
'Spectrotel':(['0011500001HNPjiAAH'],'exact'), 'Valhelio Tech':(['0016O00003dmuaQQAQ'],'probable alias/typo: matched to Valhalla; validate before external use'),
'Telesystem':(['0011C000028IUmYQAW'],'exact client account; cold-prospect duplicate excluded'),
'Hunter Communications':(['0011500001HNQ2nAAH'],'exact'), 'Nuso LLC':(['0011500001HNQ50AAH'],'normalized exact (Nuso)'),
'Prestige Technology LLC':(['001PX000006p40BYAQ'],'exact; Salesforce record is a Cold Prospect'),
'TPX Communications':(['0011500001HNQ4cAAH'],'case-insensitive exact client; cold-prospect duplicates excluded'),
'Zultys Business Phone Solutions':(['0011C00002pcSOSQA2'],'matched to Zultys client'), 'Broadvoice':(['0011500001ZIG6jAAH'],'exact'),
'Tailwinds Voice & Data, Inc.':(['0011500001HNPyFAAX'],'normalized exact'), 'Crexendo Business Solutions':(['0011C000024KL7SQAW'],'exact'),
'TouchTone':(['0011500001HNQItAAP'],'matched to TouchTone Communications client; duplicates excluded'), 'SpectrumVoIP':(['0011500001HNPj2AAH'],'exact'),
'Mango Voice':(['0011C00001oM5BwQAK'],'exact'), 'Mango Voice, LLC':(['0011C00001oM5BwQAK'],'same Salesforce account as Mango Voice; duplicate requested label'),
'Cloudli Communications':(['0016O00003T3PXVQA3'],'exact'), 'Viirtue LLC (Apollo)':(['0016O00003QyGNZQA3'],'matched to Viirtue Inc (Apollo); Zeus account excluded'),
'South Carolina Telecommunications Group Holdings, LLC':(['0011C00002U2tRGQAZ'],'probable legal-name alias matched to SEGRA; validate before external use'),
'Estech Systems, Inc':(['0011500001HNQ4XAAX'],'normalized exact'), 'NinjaOne, LLC (Sponsor)':(['001PX00000c0yRKYAY'],'matched to NinjaOne partner prospect'),
'XMission':(['0011500001HNQBgAAP'],'exact'), 'Vocus Group Ltd.':(['0016O000034F1w8QAC'],'matched to Vocus Group client; cold-prospect duplicates excluded'),
'WoltersKluwer (Sponsor)':(['0011500001IIF7nAAH'],'matched to Wolters Kluwer partner; prospect duplicates excluded'),
'PS Lightwave LLC Operating Account':(['0011C00002i396YQAQ'],'matched to PS Lightwave client'), 'CCI Network Services':(['0011500001HNQNtAAP'],'exact'),
'Coeo Solutions, LLC.':(['0011500001HNQNmAAP'],'normalized exact'), 'Titanium Wireless':(['0011C000025b5oGQAQ'],'exact'),
'Clear Rate Communications':(['0011500001ecpJJAAY'],'exact'), 'S-Net':(['0011500001HNPlDAAX'],'matched to S-Net Communications client'),
'PS Lightwave LLC':(['0011C00002i396YQAQ'],'same Salesforce account as PS Lightwave LLC Operating Account; duplicate requested label'),
'Xchange Telecom':(['0011500001HNPjgAAH'],'matched to Xchange Telecom / Skywire Networks client')}

def chunks(xs,n=80):
 for i in range(0,len(xs),n): yield xs[i:i+n]
def quote(xs): return ','.join("'"+x.replace("'","\\'")+"'" for x in xs)
def flat_name(r,key): return ((r.get(key) or {}).get('Name') or '').strip()
def theme(subject):
 s=subject.lower()
 groups=[('Platform / PSA / demos',r'psa|new rev\.io|demo|platform|billing demo|discovery'),('International / currency',r'international|currency|canadian|xml'),('Payments / billing / support',r'payment|credit card|surcharge|billing|bill run|support|ssl|database|fee'),('CBR / QBR / partnership',r'cbr|qbr|business review|partnership|partner'),('Events / executive engagement',r'summit|dinner|advisory council|channelcon|onsite|rev\.io day'),('Follow-up / planning',r'follow.?up|meeting|agenda|questions|analysis')]
 for label,pat in groups:
  if re.search(pat,s): return label
 return 'Other outreach'
def outbound_kind(t):
 typ=(t.get('Type') or '').lower(); sub=(t.get('TaskSubtype') or '').lower(); subj=t.get('Subject') or ''; calltype=(t.get('CallType') or '').lower()
 if typ=='call' or sub=='call': return None if calltype=='inbound' else 'Call'
 if '[in]' in subj.lower() or subj.lower().startswith('automatic reply:'): return None
 if typ in ('email','hubspot email') or sub=='email' or '[out]' in subj.lower() or (t.get('Status')=='Sent'): return 'Email'
 if 'linkedin' in subj.lower() or 'linkedin' in typ: return 'LinkedIn'
 if any(x in subj.lower() for x in ('action item','follow up','follow-up','outreach')): return 'Other'
 return None

def main():
 base,h=sf_auth(); ids=sorted({x for c in CLIENTS for x in MATCHES[c][0]})
 accounts={}
 for ch in chunks(ids):
  for a in sf_query(base,h,f"SELECT Id,Name,Type,Owner.Name,Website FROM Account WHERE Id IN ({quote(ch)})"): accounts[a['Id']]=a
 contacts=[]; opps=[]
 for ch in chunks(ids):
  contacts+=sf_query(base,h,f"SELECT Id,Name,Title,Email,AccountId FROM Contact WHERE AccountId IN ({quote(ch)})")
  opps+=sf_query(base,h,f"SELECT Id,Name,AccountId FROM Opportunity WHERE AccountId IN ({quote(ch)})")
 acct_by_related={c['Id']:c['AccountId'] for c in contacts}; acct_by_related.update({o['Id']:o['AccountId'] for o in opps})
 for x in ids: acct_by_related[x]=x
 related=list(acct_by_related); tasks=[]; events=[]
 for ch in chunks(related,60):
  filt=f"(WhatId IN ({quote(ch)}) OR WhoId IN ({quote(ch)}))"
  tasks+=sf_query(base,h,f"SELECT Id,Subject,Type,TaskSubtype,Status,ActivityDate,CreatedDate,Owner.Name,WhoId,Who.Name,WhatId,What.Name,CallDisposition,CallType,Description FROM Task WHERE IsDeleted=false AND CreatedDate >= {YEAR_START} AND CreatedDate < {YEAR_END} AND {filt} ORDER BY CreatedDate")
  events+=sf_query(base,h,f"SELECT Id,Subject,Type,ActivityDate,StartDateTime,CreatedDate,Owner.Name,WhoId,Who.Name,WhatId,What.Name,Description,Appointment_Status__c FROM Event WHERE IsDeleted=false AND CreatedDate >= {YEAR_START} AND CreatedDate < {YEAR_END} AND {filt} ORDER BY CreatedDate")
 # A task/event can match both WhatId and WhoId across query chunks; dedupe by Salesforce ID.
 tasks=list({t['Id']:t for t in tasks}.values()); events=list({e['Id']:e for e in events}.values())
 def acct_id(r): return acct_by_related.get(r.get('WhatId')) or acct_by_related.get(r.get('WhoId'))
 byacct_tasks=defaultdict(list); byacct_events=defaultdict(list)
 for t in tasks:
  a=acct_id(t)
  if a and outbound_kind(t):
   t['_kind']=outbound_kind(t); byacct_tasks[a].append(t)
 for e in events:
  a=acct_id(e); status=(e.get('Appointment_Status__c') or '').lower()
  if a and not any(x in status for x in ('cancel','no show')): byacct_events[a].append(e)
 rows=[]
 for label in CLIENTS:
  mids,note=MATCHES[label]; ts=[]; es=[]
  for a in mids: ts+=byacct_tasks[a]; es+=byacct_events[a]
  people=Counter(flat_name(t,'Who') or 'No contact attached' for t in ts); owners=Counter(flat_name(t,'Owner') or 'Unknown' for t in ts)
  details=[]
  for t in ts:
   details.append({'date':t.get('CreatedDate','')[:10],'kind':t['_kind'],'subject':re.sub(r'^\[Outreach\]\s*\[Email\]\s*\[Out\]\s*','',t.get('Subject') or ''),'person':flat_name(t,'Who'),'owner':flat_name(t,'Owner'),'theme':theme(t.get('Subject') or ''),'disposition':t.get('CallDisposition') or ''})
  meetings=[{'date':(e.get('ActivityDate') or e.get('StartDateTime') or e.get('CreatedDate') or '')[:10],'subject':e.get('Subject') or '', 'type':e.get('Type') or '', 'person':flat_name(e,'Who'),'owner':flat_name(e,'Owner')} for e in es]
  kinds=Counter(t['_kind'] for t in ts); themes=Counter(d['theme'] for d in details)
  rows.append({'client':label,'salesforce_accounts':[{'id':a,'name':accounts.get(a,{}).get('Name','Missing'),'type':accounts.get(a,{}).get('Type',''),'owner':flat_name(accounts.get(a,{}),'Owner')} for a in mids], 'match_note':note,'match_status':'caution' if ('probable' in note or 'validate' in note) else ('duplicate' if 'duplicate requested' in note or 'same Salesforce' in note else 'matched'),'outbound_total':len(ts),'emails':kinds['Email'],'calls':kinds['Call'],'linkedin':kinds['LinkedIn'],'other':kinds['Other'],'meetings':len(es),'people_reached':[{'name':k,'count':v} for k,v in people.most_common()],'outreach_owners':[{'name':k,'count':v} for k,v in owners.most_common()],'themes':[{'name':k,'count':v} for k,v in themes.most_common()],'details':details,'meeting_details':meetings})
 payload={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'year':2026,'through_date':'2026-09-15','source':'Live Salesforce Account, Contact, Opportunity, Task, and Event records','methodology':{'outbound':'Task CreatedDate in 2026 linked to a matched Account, its Contacts, or Opportunities. Email requires outbound/sent evidence and excludes [In] and automatic replies. Calls exclude CallType=Inbound. Completed LinkedIn steps and clearly labeled proactive/follow-up tasks are included.','meetings':'Non-canceled/non-no-show Events created in 2026, reported separately from outbound touches.','deduplication':'Salesforce record IDs deduplicated; repeated requested labels remain separate and are flagged.'},'clients':rows}
 JSON_PATH.write_text(json.dumps(payload,indent=2),encoding='utf-8'); HTML_PATH.write_text(render(payload),encoding='utf-8')
 print(f'Wrote {JSON_PATH} and {HTML_PATH}; {len(rows)} labels, {sum(r["outbound_total"] for r in rows)} displayed touches')

def render(p):
 data=json.dumps(p).replace('</','<\\/')
 return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2026 Client Proactive Outreach</title><style>
:root{{--bg:#08101e;--panel:#111c30;--line:#263855;--txt:#eef4ff;--muted:#9eb0ca;--cyan:#44d7e8;--gold:#ffcb67;--red:#ff7f91}}*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(140deg,#07101d,#10172b);color:var(--txt);font:14px Inter,system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:28px}}h1{{font-size:34px;margin:4px 0}}.sub,.muted{{color:var(--muted)}}.kpis,.grid{{display:grid;gap:12px}}.kpis{{grid-template-columns:repeat(5,1fr);margin:22px 0}}.kpi,.card,.controls{{background:#111c30dd;border:1px solid var(--line);border-radius:14px;padding:16px}}.kpi b{{display:block;font-size:27px;color:var(--cyan)}}.controls{{display:flex;gap:10px;flex-wrap:wrap;position:sticky;top:0;z-index:3}}input,select{{background:#091426;color:white;border:1px solid #38506f;padding:10px;border-radius:8px;min-width:220px}}.grid{{grid-template-columns:repeat(auto-fit,minmax(360px,1fr));margin-top:14px}}.card h2{{margin:0 0 4px;font-size:20px}}.metrics{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}}.metrics b{{color:var(--gold)}}.pill{{display:inline-block;padding:3px 8px;border-radius:12px;background:#1b304a;margin:2px;font-size:12px}}.warn{{color:var(--red)}}details{{border-top:1px solid var(--line);margin-top:12px;padding-top:10px}}summary{{cursor:pointer;color:var(--cyan)}}table{{width:100%;border-collapse:collapse;margin-top:8px;font-size:12px}}th,td{{text-align:left;padding:7px;border-bottom:1px solid #24344c;vertical-align:top}}th{{color:#bcd0ea}}a{{color:var(--cyan)}}@media(max-width:800px){{.kpis{{grid-template-columns:1fr 1fr}}main{{padding:14px}}}}
</style></head><body><main><div class="muted">REV.IO SALESFORCE · THROUGH SEP 15, 2026</div><h1>Client Proactive Outreach</h1><p class="sub">Outbound emails, calls, LinkedIn/other touches and meetings for the requested client set. Inbound activities are excluded from outbound totals.</p><section class="kpis" id="kpis"></section><section class="controls"><input id="q" placeholder="Search client, person, owner, theme"><select id="status"><option value="">All match statuses</option><option>matched</option><option>caution</option><option>duplicate</option></select><select id="activity"><option value="">All activity levels</option><option value="yes">Has outbound activity</option><option value="no">No outbound activity</option></select></section><section class="grid" id="cards"></section><details class="card"><summary>Counting rules and data source</summary><p>{escape(p['methodology']['outbound'])}</p><p>{escape(p['methodology']['meetings'])}</p><p>{escape(p['methodology']['deduplication'])}</p></details></main><script>const D={data};const $=s=>document.querySelector(s);function pills(a){{return a.length?a.map(x=>`<span class="pill">${{x.name}} · ${{x.count}}</span>`).join(''):'<span class="muted">None logged</span>'}}function render(){{let q=$('#q').value.toLowerCase(),st=$('#status').value,ac=$('#activity').value;let rs=D.clients.filter(r=>{{let hay=JSON.stringify(r).toLowerCase();return(!q||hay.includes(q))&&(!st||r.match_status===st)&&(!ac||(ac==='yes'?r.outbound_total>0:r.outbound_total===0))}});let unique=[...new Set(rs.flatMap(r=>r.salesforce_accounts.map(a=>a.id)))];let uniqueRows=unique.map(id=>rs.find(r=>r.salesforce_accounts.some(a=>a.id===id)));let sums=k=>uniqueRows.reduce((n,r)=>n+r[k],0);$('#kpis').innerHTML=`<div class="kpi"><span>Requested labels</span><b>${{rs.length}}</b></div><div class="kpi"><span>Unique SF accounts</span><b>${{unique.length}}</b></div><div class="kpi"><span>Outbound touches</span><b>${{sums('outbound_total')}}</b></div><div class="kpi"><span>Calls</span><b>${{sums('calls')}}</b></div><div class="kpi"><span>Meetings</span><b>${{sums('meetings')}}</b></div>`;$('#cards').innerHTML=rs.map(r=>`<article class="card"><h2>${{r.client}}</h2><div class="muted">${{r.salesforce_accounts.map(a=>`<a target="_blank" href="https://rev-io.my.salesforce.com/${{a.id}}">${{a.name}}</a> · ${{a.type||'No type'}}</div>`).join('')}}<p class="${{r.match_status==='caution'?'warn':'muted'}}">${{r.match_note}}</p><div class="metrics"><span><b>${{r.outbound_total}}</b> outbound</span><span><b>${{r.emails}}</b> emails</span><span><b>${{r.calls}}</b> calls</span><span><b>${{r.linkedin+r.other}}</b> LinkedIn/other</span><span><b>${{r.meetings}}</b> meetings</span></div><b>People reached</b><div>${{pills(r.people_reached)}}</div><br><b>Rev.io owners</b><div>${{pills(r.outreach_owners)}}</div><br><b>Themes</b><div>${{pills(r.themes)}}</div><details><summary>Outbound timeline (${{r.details.length}})</summary><table><tr><th>Date</th><th>Type</th><th>Person</th><th>Owner</th><th>Subject / disposition</th></tr>${{r.details.map(x=>`<tr><td>${{x.date}}</td><td>${{x.kind}}</td><td>${{x.person||'—'}}</td><td>${{x.owner}}</td><td>${{x.subject}} ${{x.disposition?`<span class="muted">(${{x.disposition}})</span>`:''}}</td></tr>`).join('')}}</table></details><details><summary>Meetings (${{r.meeting_details.length}})</summary><table><tr><th>Date</th><th>Type</th><th>Person</th><th>Owner</th><th>Subject</th></tr>${{r.meeting_details.map(x=>`<tr><td>${{x.date}}</td><td>${{x.type}}</td><td>${{x.person||'—'}}</td><td>${{x.owner}}</td><td>${{x.subject}}</td></tr>`).join('')}}</table></details></article>`).join('')}}$('#q').addEventListener('input',render);$('#status').addEventListener('change',render);$('#activity').addEventListener('change',render);render();</script></body></html>'''
if __name__=='__main__': main()
