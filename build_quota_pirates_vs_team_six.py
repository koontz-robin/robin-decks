#!/usr/bin/env python3
"""Build Quota Pirates vs Sales Team Six competition dashboard from Salesforce."""
from __future__ import annotations
import json, os, subprocess, tempfile, shutil
from datetime import date, datetime, timedelta, time, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from refresh_monday_team_activity_dashboard import sf_auth, sf_query, normalize_name

ROOT=Path('/home/openclaw/.openclaw/workspace')
OUT=ROOT/'quota-pirates-vs-sales-team-six.html'
DATA=ROOT/'quota_pirates_vs_sales_team_six.json'
ET=ZoneInfo('America/New_York')
TEAMS={
 'Quota Pirates':['Joe Abarno','Andy Whisenant','Jaylin Bender'],
 'Sales Team Six':['Connor Flynn','Jamie Butler','Patrick Davies','Jake Borah'],
}
ALIASES={'Joseph Abarno':'Joe Abarno','Andrew Whisenant':'Andy Whisenant'}
ROSTER={n for members in TEAMS.values() for n in members}

def norm(n): return ALIASES.get(normalize_name(n),normalize_name(n))
def iso_utc(d): return datetime.combine(d,time.min,ET).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def money(v): return f'${v:,.0f}'
def names_sql(): return ', '.join("'"+n.replace("'","\\'")+"'" for n in sorted(ROSTER|set(ALIASES)))
def product_key(text):
 text=(text or '').lower()
 if 'psa' in text: return 'New Rev.io'
 if 'billing' in text or 'odin' in text: return 'Classic Rev.io'
 return None
def mrr_splits(o):
 out={}
 for li in ((o.get('OpportunityLineItems') or {}).get('records') or []):
  amount=li.get('TotalPrice')
  if amount is None: amount=float(li.get('Quantity') or 0)*float(li.get('UnitPrice') or 0)
  p=li.get('Product2') or {}; key=product_key(f"{p.get('Family','')} {p.get('Name','')}")
  if key and amount: out[key]=out.get(key,0.0)+float(amount)
 if out: return out
 key=product_key(o.get('Product_Type__c'))
 return {key:float(o.get('Amount') or 0)} if key else {}

def build():
 now=datetime.now(ET); today=now.date(); end=today+timedelta(days=1)
 periods={'month':(today.replace(day=1),end),'quarter':(date(today.year,10,1),end)}
 base,headers=sf_auth()
 result={'generated_at_et':now.isoformat(),'teams':TEAMS,'periods':{}}
 for key,(start,stop) in periods.items():
  reps={n:{'mrr':0.0,'deals':0,'discovery_set':0,'discovery_complete':0,'demos':0} for n in ROSTER}
  opps=sf_query(base,headers,f"""SELECT Id, Name, Amount, Product_Type__c, CloseDate, Owner.Name,
    (SELECT Id, Quantity, UnitPrice, TotalPrice, Product2.Name, Product2.Family FROM OpportunityLineItems)
    FROM Opportunity WHERE IsDeleted=false AND StageName='Closed Won' AND CloseDate >= {start} AND CloseDate < {stop}
    AND Owner.Name IN ({names_sql()})""")
  for o in opps:
   n=norm((o.get('Owner') or {}).get('Name')); splits=mrr_splits(o)
   if n in reps and splits: reps[n]['mrr']+=sum(splits.values()); reps[n]['deals']+=1
  set_events=sf_query(base,headers,f"""SELECT Id, Subject, Date_Appt_Was_Set__c, Owner.Name FROM Event WHERE IsDeleted=false
    AND Date_Appt_Was_Set__c >= {start} AND Date_Appt_Was_Set__c < {stop}
    AND Type='1-Discovery Call' AND Owner.Name IN ({names_sql()})""")
  for x in set_events:
   subject=(x.get('Subject') or '').lower(); n=norm((x.get('Owner') or {}).get('Name'))
   if n in reps and 'cancel' not in subject and 'internal' not in subject: reps[n]['discovery_set']+=1
  events=sf_query(base,headers,f"""SELECT Id, Subject, Type, Owner.Name FROM Event WHERE IsDeleted=false
    AND ActivityDate >= {start} AND ActivityDate < {stop} AND LastModifiedDate < {iso_utc(stop)}
    AND Appointment_Status__c='Completed' AND Type IN ('1-Discovery Call','2-Initial DEMO')
    AND Owner.Name IN ({names_sql()})""")
  for x in events:
   subject=(x.get('Subject') or '').lower(); n=norm((x.get('Owner') or {}).get('Name'))
   if n in reps and 'cancel' not in subject and 'internal' not in subject:
    reps[n]['discovery_complete' if x.get('Type')=='1-Discovery Call' else 'demos']+=1
  teams={}
  for team,members in TEAMS.items():
   teams[team]={k:sum(reps[n][k] for n in members) for k in ('mrr','deals','discovery_set','discovery_complete','demos')}
  score={t:0 for t in TEAMS}
  for metric in ('mrr','discovery_set','discovery_complete','demos'):
   vals={t:teams[t][metric] for t in TEAMS}; high=max(vals.values())
   if high:
    winners=[t for t,v in vals.items() if v==high]
    for t in winners: score[t]+=1/len(winners)
  result['periods'][key]={'start':start.isoformat(),'through':today.isoformat(),'reps':reps,'team_totals':teams,'score':score}
 DATA.write_text(json.dumps(result,indent=2)+'\n')
 render(result)
 return result

def render(d):
 js=json.dumps(d,separators=(',',':')).replace('</','<\\/')
 html=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Quota Pirates vs Sales Team Six</title><style>
:root{{--ink:#f7fbff;--muted:#9fb2c7;--navy:#06111f;--panel:#0c1d30;--line:#1c3852;--cyan:#35d5f5;--gold:#ffc857;--red:#ff667d;--green:#7ef0b2}}*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);background:radial-gradient(circle at 20% -10%,#183e5c 0,transparent 35%),radial-gradient(circle at 90% 5%,#3b263e 0,transparent 28%),var(--navy);font:15px/1.45 Inter,system-ui,sans-serif}}main{{max-width:1450px;margin:auto;padding:28px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:22px}}.eyebrow{{color:var(--cyan);font-size:12px;font-weight:900;letter-spacing:.15em;text-transform:uppercase}}h1{{font-size:clamp(32px,5vw,62px);line-height:.95;margin:9px 0}}.sub,.stamp{{color:var(--muted)}}.tabs{{display:flex;gap:9px;margin:22px 0}}button{{border:1px solid var(--line);background:#0b1a2b;color:var(--muted);padding:10px 17px;border-radius:999px;font-weight:900;cursor:pointer}}button.active{{background:var(--cyan);color:#06111f;border-color:var(--cyan)}}.period{{display:none}}.period.active{{display:block}}.arena{{display:grid;grid-template-columns:1fr 160px 1fr;gap:16px;align-items:stretch}}.team,.versus,.metric,.tablewrap,.leaderboard{{background:linear-gradient(145deg,rgba(18,43,67,.96),rgba(8,24,40,.96));border:1px solid var(--line);border-radius:18px}}.team{{padding:24px;position:relative;overflow:hidden}}.team:before{{content:'';position:absolute;inset:0 0 auto;height:5px;background:var(--gold)}}.team.six:before{{background:var(--cyan)}}.team h2{{font-size:27px;margin:3px 0}}.score{{font-size:54px;font-weight:950;color:var(--gold);line-height:1;margin:20px 0 6px}}.six .score{{color:var(--cyan)}}.scorelabel{{color:var(--muted);font-size:12px;text-transform:uppercase;font-weight:850}}.versus{{display:grid;place-items:center;text-align:center;font-weight:950;font-size:27px;color:var(--muted)}}.metricgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}}.metric{{padding:18px}}.metric span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;font-weight:850;letter-spacing:.08em}}.metric strong{{display:block;font-size:28px;margin-top:7px}}.metric .compare{{display:flex;justify-content:space-between;gap:10px;margin-top:9px;font-size:13px}}.metric .winner{{color:var(--green);font-weight:900}}.lower{{display:grid;grid-template-columns:1.4fr .8fr;gap:16px}}.tablewrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:720px}}th,td{{padding:14px 17px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}}.teamrow td{{background:#122a42;font-weight:900;color:var(--cyan)}}.leaderboard{{padding:20px}}.leaderboard h3{{margin:0 0 14px}}.lead{{display:flex;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid var(--line)}}.lead span{{color:var(--muted)}}.lead strong{{text-align:right}}.note{{color:var(--muted);font-size:12px;margin-top:14px}}@media(max-width:850px){{main{{padding:17px}}header{{display:block}}.stamp{{margin-top:12px}}.arena{{grid-template-columns:1fr}}.versus{{min-height:65px}}.metricgrid{{grid-template-columns:1fr 1fr}}.lower{{grid-template-columns:1fr}}}}@media(max-width:500px){{.metricgrid{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div><div class="eyebrow">Rev.io · Q4 Sales Competition</div><h1>Quota Pirates <span style="color:var(--muted)">vs</span><br>Sales Team Six</h1><div class="sub">MRR and funnel execution. Four categories. One leaderboard.</div></div><div class="stamp">Salesforce refreshed {escape(datetime.fromisoformat(d['generated_at_et']).strftime('%b %d, %Y · %I:%M %p ET'))}</div></header><nav class="tabs"><button class="active" data-period="month">This Month</button><button data-period="quarter">Q4 Quarter</button></nav><div id="app"></div><p class="note">MRR sold combines New Rev.io and Classic Rev.io closed-won line-item MRR, with Opportunity Amount used only when no classified line items exist. Discovery Set uses Salesforce’s appointment-set date. Discovery Complete and Demos Ran use completed events by activity date. Competition score awards one point per category; tied categories split the point.</p></main><script id="data" type="application/json">{js}</script><script>
const D=JSON.parse(document.getElementById('data').textContent),teams=['Quota Pirates','Sales Team Six'],metrics=[['mrr','MRR Sold'],['discovery_set','Discovery Set'],['discovery_complete','Discovery Complete'],['demos','Demos Ran']];const money=n=>'$'+Math.round(n).toLocaleString();
function render(k){{const p=D.periods[k],a=p.team_totals[teams[0]],b=p.team_totals[teams[1]],fmt=(m,v)=>m==='mrr'?money(v):v.toLocaleString();const cards=metrics.map(([m,l])=>{{const hi=Math.max(a[m],b[m]);return `<article class="metric"><span>${{l}}</span><strong>${{fmt(m,a[m]+b[m])}} total</strong><div class="compare"><b class="${{a[m]===hi&&hi?'winner':''}}">Pirates ${{fmt(m,a[m])}}</b><b class="${{b[m]===hi&&hi?'winner':''}}">Team Six ${{fmt(m,b[m])}}</b></div></article>`}}).join('');let rows='';for(const t of teams){{rows+=`<tr class="teamrow"><td colspan="6">${{t}}</td></tr>`;for(const n of D.teams[t]){{const r=p.reps[n];rows+=`<tr><td><strong>${{n}}</strong></td><td>${{money(r.mrr)}}</td><td>${{r.deals}}</td><td>${{r.discovery_set}}</td><td>${{r.discovery_complete}}</td><td>${{r.demos}}</td></tr>`}}}}const leads=metrics.map(([m,l])=>{{const all=Object.entries(p.reps).sort((x,y)=>y[1][m]-x[1][m]),v=all[0][1][m],w=all.filter(x=>x[1][m]===v).map(x=>x[0]).join(' / ');return `<div class="lead"><span>${{l}}</span><strong>${{w}}<br>${{fmt(m,v)}}</strong></div>`}}).join('');document.getElementById('app').innerHTML=`<section class="period active"><div class="arena"><article class="team"><div class="eyebrow">Quota Pirates</div><h2>🏴‍☠️ Pirates</h2><div class="score">${{money(a.mrr)}}</div><div class="scorelabel">MRR sold</div></article><div class="versus">VS</div><article class="team six"><div class="eyebrow">Sales Team Six</div><h2>⚡ Team Six</h2><div class="score">${{money(b.mrr)}}</div><div class="scorelabel">MRR sold</div></article></div><div class="metricgrid">${{cards}}</div><div class="lower"><div class="tablewrap"><table><thead><tr><th>Rep</th><th>MRR</th><th>Wins</th><th>Disco Set</th><th>Disco Complete</th><th>Demos</th></tr></thead><tbody>${{rows}}</tbody></table></div><aside class="leaderboard"><h3>Individual Leaders</h3>${{leads}}</aside></div></section>`}}
document.querySelectorAll('button[data-period]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));render(b.dataset.period);location.hash=b.dataset.period}});render(location.hash==='#quarter'?'quarter':'month');
</script></body></html>'''
 OUT.write_text(html)

if __name__=='__main__':
 d=build(); print(f"Wrote {OUT.name} with {sum(len(v) for v in TEAMS.values())} reps; refreshed {d['generated_at_et']}")
