#!/usr/bin/env python3
"""Build the September sales update from the existing Salesforce exports.
The August deck is the presentation template; no source systems are mutated.
"""
import json, re
import requests
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from html import escape
from build_forecast_targets import sf_auth
R=Path(__file__).parent
ASOF='Sep 18'

def load(n): return json.loads((R/n).read_text())
def amount(xs): return sum(float(x.get('Amount') or 0) for x in xs)
def money(x): return '${:,.0f}'.format(x)
def prod(x):
 s=(x.get('Product_Type__c') or 'Other').lower()
 if 'psa' in s:return 'PSA'
 if 'billing' in s or 'odin' in s:return 'Billing / Odin'
 if 'payment' in s:return 'Payments'
 return 'Cyber + CommerceHub + Other'
def src(x):
 s=x.get('Marketing_Source__c') or x.get('Lead_Direction__c') or 'Unknown'
 return str(s)
def card(label,val,sub,color='teal'):
 return f'<div class="kpi-card {color}"><div class="kpi-label">{label}</div><div class="kpi-val {color}">{val}</div><div class="kpi-sub">{sub}</div></div>'
def header(tag,title): return f'<div class="top-stripe"></div><div class="slide-header"><div class="slide-header-left"><div class="slide-tag">{tag}</div><h2>{title}</h2></div><img src="https://7091219.fs1.hubspotusercontent-na1.net/hubfs/7091219/email-assets/logo-revio-white.png" alt="Rev.io"></div>'
def section(t): return f'<div class="section-hdr"><div class="section-lbl">{t}</div><div class="section-rule"></div></div>'

def sf_query(base, headers, soql):
 out=[]; url=f'{base}/services/data/v59.0/query'; params={'q':soql}
 while True:
  r=requests.get(url,headers=headers,params=params,timeout=60); r.raise_for_status(); payload=r.json()
  out.extend(payload.get('records') or [])
  if payload.get('done',True): return out
  url=base+payload['nextRecordsUrl']; params={}

def icp_metrics():
 """Ryan's ICP: New Rev.io PSA, MSP industry, no integrators, and 10+ employees OR $1K+ MRR."""
 base,headers=sf_auth()
 criteria="""Type='New Opportunity'
 AND Product_Type__c='PSA 2.0'
 AND (Account.Vertical__c!='Integrator' OR Account.Vertical__c=NULL)
 AND Account.Industry IN ('UCaaS / Voip','MSP','MSP - UCaaS / Voip','MSP - No Voice')
 AND (Account.NumberOfEmployees>=10 OR Amount>=1000)
 AND (Loss_Reason__c!='Discovery No Show' OR Loss_Reason__c=NULL)"""
 fields='Id,Name,CreatedDate,CloseDate,IsWon,Amount,Account.Name'
 created=sf_query(base,headers,f"SELECT {fields} FROM Opportunity WHERE CreatedDate>=2026-01-01T00:00:00Z AND CreatedDate<2027-01-01T00:00:00Z AND {criteria}")
 won=sf_query(base,headers,f"SELECT {fields} FROM Opportunity WHERE CloseDate>=2026-01-01 AND CloseDate<2027-01-01 AND IsWon=TRUE AND {criteria}")
 months=[]
 for m in range(1,10):
  key=f'2026-{m:02d}'; label=datetime(2026,m,1).strftime('%b')+(' MTD' if m==9 else '')
  c=[x for x in created if x.get('CreatedDate','').startswith(key)]
  w=[x for x in won if x.get('CloseDate','').startswith(key)]
  company=lambda x: ((x.get('Account') or {}).get('Name') or x.get('Name') or 'Unknown').strip()
  months.append({'key':key,'label':label,'created':len(c),'won':len(w),
   'created_companies':sorted({company(x) for x in c},key=str.lower),
   'won_companies':sorted({company(x) for x in w},key=str.lower)})
 return months
def product_cards(won,open_,quotas):
 out=[]
 for p in ['PSA','Billing / Odin','Payments','Cyber + CommerceHub + Other']:
  w=[x for x in won if prod(x)==p]; o=[x for x in open_ if prod(x)==p]; q=quotas[p]; pct=round(amount(w)/q*100) if q else 0
  out.append(f'<div class="prod-card"><div class="prod-name">{p}</div><div class="prod-row"><span class="prod-row-lbl">Won MRR</span><span class="prod-row-val green">{money(amount(w))}</span></div><div class="prod-row"><span class="prod-row-lbl">Open Pipeline</span><span class="prod-row-val teal">{money(amount(o))}</span></div><div class="prod-row"><span class="prod-row-lbl">Opportunities Won</span><span class="prod-row-val">{len(w)}</span></div><div class="prod-row"><span class="prod-row-lbl">Monthly Quota</span><span class="prod-row-val">{money(q)}</span></div><div class="quota-bar-wrap"><div class="quota-bar-bg"><div class="quota-bar-fill {'low' if pct<50 else 'mid'}" style="width:{min(pct,100)}%"></div></div><div class="quota-pct">{pct}% attained</div></div></div>')
 return '<div class="product-grid">'+''.join(out)+'</div>'

def main():
 aug,sep,jul=load('sf_august_opps.json'),load('sf_september_opps.json'),load('sf_july_opps.json')
 base=load('sf_june_deck_data.json')
 icp=icp_metrics()
 aw=[x for x in aug if x['StageName']=='Closed Won']; al=[x for x in aug if x['StageName']=='Closed Lost']
 sw=[x for x in sep if x['StageName']=='Closed Won']; sl=[x for x in sep if x['StageName']=='Closed Lost']; so=[x for x in sep if not x['StageName'].startswith('Closed')]
 quotas={'PSA':46000,'Billing / Odin':12383,'Payments':10540,'Cyber + CommerceHub + Other':6167}
 # Jan-Jun creation comes from the full export. Jul/Aug values are preserved from the August edition; Sep is a close-date-cohort proxy because current exports omit CreatedDate.
 created=base['created_2026_jan_jun']; months=[]
 for m in range(1,7):
  xs=[x for x in created if x.get('CreatedDate','').startswith(f'2026-{m:02}')]; months.append((datetime(2026,m,1).strftime('%b'),len(xs),amount(xs),'created'))
 months += [('Jul',168,219000,'created'),('Aug',sum(1 for x in aug),amount(aug),'close-date cohort'),('Sep MTD',len(sep),amount(sep),'close-date cohort')]
 # PSA through Sep 18, de-duplicated.
 psa={}
 for x in base['closed_won_2026_jan_jun']+jul+aug+sep:
  if x.get('StageName')=='Closed Won' and prod(x)=='PSA': psa[x['Id']]=x
 ps=list(psa.values())
 cycle=[]
 for x in base['closed_won_2026_jan_jun']:
  if prod(x)=='PSA' and x.get('CreatedDate') and x.get('CloseDate'):
   cycle.append((datetime.fromisoformat(x['CloseDate']).date()-datetime.fromisoformat(x['CreatedDate'].replace('Z','+00:00')).date()).days)
 loss_month=[]
 for m in range(1,7): loss_month.append((datetime(2026,m,1).strftime('%b'),sum(1 for x in base['closed_lost_2026_jan_jun'] if x.get('CloseDate','').startswith(f'2026-{m:02}'))))
 loss_month += [('Jul',sum(x['StageName']=='Closed Lost' for x in jul)),('Aug',len(al)),('Sep MTD',len(sl))]
 reasons=Counter(x.get('Loss_Reason__c') or 'Unknown' for x in sl)
 old=(R/'august-update-deck.html').read_text(); style=re.search(r'<style>(.*?)</style>',old,re.S).group(1)
 logo='https://7091219.fs1.hubspotusercontent-na1.net/hubfs/7091219/email-assets/logo-revio-white.png'
 s=[]
 # 1 cover + August final
 s.append(f'<div class="slide active" id="slide-1" style="justify-content:center;align-items:center;overflow:hidden"><div class="cover-inner" style="width:min(1240px,100%);padding:0 48px 58px"><div class="cover-top"><img src="{logo}" class="cover-logo"><div class="cover-tag">Sales Leadership Update · September 2026</div></div><div class="cover-title">Rev.io Sales <span>September Update</span></div>{section("Final August Pipeline Snapshot")}<div class="kpi-row" style="grid-template-columns:repeat(2,1fr)">{card("Opportunities Won",len(aw),"Final August count")}{card("Closed Won MRR",money(amount(aw)),"Final August result", "green")}</div>{section("August Product Results - Quota Attainment")}{product_cards(aw,[],quotas)}<div class="cover-date">Refreshed September 18, 2026 · Existing Salesforce exports · Rev.io Sales Leadership</div></div></div>')
 # 2 current pipeline
 war=[x for x in so if (x.get('Forecast_Status__c') or '').lower() in ('most likely','commit','best case')]
 s.append(f'<div class="slide" id="slide-2">{header("Current Month Snapshot","September Pipeline Snapshot")}<div class="slide-body"><div class="kpi-row">{card("Opportunities Won MTD",len(sw),"Closed-won count")}{card("Closed Won MRR",money(amount(sw)),"September MTD result","green")}{card("Open Pipeline",len(so),f"opps · {money(amount(so))} value","navy")}{card("War Room Opps",len(war),f"{money(amount(war))} value","orange")}</div>{section("September Product Results - Quota Attainment")}{product_cards(sw,so,quotas)}</div></div>')
 # 3 ICP creation and wins. Month cards open the complete company-name roster.
 max_icp=max(x['created'] for x in icp)
 icp_cards=''.join(f'''<button class="icp-month" onclick="openIcp('{x['key']}')">
  <div class="icp-month-name">{x['label']}</div>
  <div class="icp-bars"><div class="icp-bar created" style="height:{max(8,round(x['created']/max_icp*92))}px"><span>{x['created']}</span></div><div class="icp-bar won" style="height:{max(8,round(x['won']/max_icp*92))}px"><span>{x['won']}</span></div></div>
  <div class="icp-click">View companies</div></button>''' for x in icp)
 won_names=[]
 for x in icp:
  won_names += [f"<span><b>{x['label'].replace(' MTD','')}</b> · {escape(n)}</span>" for n in x['won_companies']]
 s.append(f'''<div class="slide" id="slide-icp">{header("Ideal Customer Profile","ICP Opportunities Created vs. Closed Won")}<div class="slide-body icp-body">
 <div class="icp-summary"><div><strong>{sum(x['created'] for x in icp)}</strong><span>ICP opportunities created</span></div><div><strong class="green">{sum(x['won'] for x in icp)}</strong><span>Closed Won</span></div><p>New Rev.io · MSP industry · no Integrators · 10+ employees <em>or</em> $1K+ opportunity</p></div>
 <div class="icp-legend"><span><i class="created"></i>Created</span><span><i class="won"></i>Closed Won</span><small>Click any month for every company name</small></div>
 <div class="icp-months">{icp_cards}</div>
 {section("Closed Won Companies")}
 <div class="icp-winners">{''.join(won_names)}</div></div></div>''')
 # 3 trends
 mhtml=''.join(f'<div class="prod-card"><div class="prod-name">{m}</div><div class="kpi-val teal" style="font-size:24px">{money(v/1000)}K</div><div class="kpi-sub">{n} opps · {note}</div></div>' for m,n,v,note in months)
 s.append(f'<div class="slide" id="slide-4">{header("Pipeline Creation","Pipeline Trends - Jan Through September MTD")}<div class="slide-body">{section("Monthly Pipeline")}<div class="product-grid" style="grid-template-columns:repeat(5,1fr)">{mhtml}</div><div class="insight-banner"><div class="insight-text"><strong>Method note:</strong> Jan–Jun are CreatedDate cohorts. July is retained from the prior Salesforce-built edition. The available Aug/Sep close-month exports omit CreatedDate, so those two cards are explicitly shown as close-date cohorts rather than silently presenting them as created pipeline.</div></div></div></div>')
 # 4 PSA
 byp=Counter(prod(x) for x in ps); avg=amount(ps)/len(ps) if ps else 0
 s.append(f'<div class="slide" id="slide-6">{header("PSA Closed Won","2026 PSA Win Profile")}<div class="slide-body"><div class="psa-six-kpis">{card("Closed Won PSA Opps",len(ps),"Jan 1 - Sep 18")}{card("Closed Won MRR",money(amount(ps)),"PSA family", "green")}{card("Avg Opportunity Size",money(avg),"MRR per won opportunity","navy")}{card("Avg Cycle Duration",f"{sum(cycle)/len(cycle):.1f}","days · Jan-Jun records with CreatedDate","orange")}</div>{section("PSA Wins by Close Month")}<div class="insight-banner"><div class="insight-text">August added <strong>{sum(prod(x)=='PSA' for x in aw)} PSA wins / {money(amount([x for x in aw if prod(x)=='PSA']))}</strong>; September MTD added <strong>{sum(prod(x)=='PSA' for x in sw)} / {money(amount([x for x in sw if prod(x)=='PSA']))}</strong>.</div></div></div></div>')
 # 5 losses
 vol=''.join(f'<div class="prod-card"><div class="prod-name">{m}</div><div class="kpi-val" style="color:#f5a623;font-size:28px">{n}</div><div class="kpi-sub">closed lost</div></div>' for m,n in loss_month)
 rows=''.join(f'<tr><td>{escape(k)}</td><td style="text-align:center">{v}</td><td style="text-align:center">{v/len(sl):.0%}</td></tr>' for k,v in reasons.most_common(8))
 s.append(f'<div class="slide" id="slide-5">{header("Closed Lost Analysis","Closed Lost Trends - Jan Through September MTD")}<div class="slide-body">{section("Closed Lost Volume")}<div class="product-grid" style="grid-template-columns:repeat(5,1fr)">{vol}</div>{section("September MTD Top Loss Reasons")}<table><thead><tr><th>Reason</th><th>Opps</th><th>Share</th></tr></thead><tbody>{rows}</tbody></table></div></div>')
 # 6 efficiency
 ytd_created=len(created)+168+len(aug)+len(sep); ytd_value=amount(created)+219000+amount(aug)+amount(sep)
 paid=[x for x in base['closed_won_2026_jan_jun']+jul+aug+sep if x.get('StageName')=='Closed Won' and amount([x])>0]; paid_ids={x['Id'] for x in paid}
 s.append(f'<div class="slide" id="slide-3">{header("Sales Velocity","2026 Sales Team Efficiency - Refreshed")}<div class="slide-body"><div class="kpi-row">{card("YTD Cohort Opps",ytd_created,f"{money(ytd_value)} value; see method note")}{card("YTD Closed Won MRR",money(amount(list({x["Id"]:x for x in base["closed_won_2026_jan_jun"]+jul+aug+sep if x.get("StageName")=="Closed Won"}.values()))),f"{len(paid_ids)} paid wins through Sep 18","green")}{card("Created→Paid Win Rate",f"{len(paid_ids)/ytd_created:.1%}","paid wins / blended cohort denominator","navy")}{card("Open September Pipeline",money(amount(so)),f"{len(so)} open September opps","orange")}</div>{section("September MTD Operating Snapshot")}<div class="product-grid">{card("Close-Date Cohort",len(sep),f"{money(amount(sep))} total value")}{card("Closed Won",len(sw),money(amount(sw)),"green")}{card("Closed Lost",len(sl),money(amount(sl)),"orange")}{card("Open",len(so),money(amount(so)),"teal")}</div><div class="insight-banner"><div class="insight-text">Efficiency refreshed through <strong>September 18, 2026</strong>. The denominator is labeled blended because Aug/Sep exports do not contain CreatedDate; no fabricated creation dates are used.</div></div></div></div>')
 labels=['Cover + August Final','September Pipeline','ICP Created vs. Won','Pipeline Trends','PSA Wins','Closed Lost','Efficiency']; ids=['slide-1','slide-2','slide-icp','slide-4','slide-6','slide-5','slide-3']
 icp_json=json.dumps({x['key']:x for x in icp})
 script=f"const TOTAL=7;let cur=1;const SLIDE_IDS={json.dumps(ids)};const LABELS={json.dumps(labels)};const ICP={icp_json};function buildDots(){{let w=document.getElementById('nav-dots');for(let i=1;i<=TOTAL;i++){{let d=document.createElement('div');d.className='nav-dot';d.title=LABELS[i-1];d.onclick=()=>showSlide(i);w.appendChild(d)}}}}function showSlide(n){{cur=Math.max(1,Math.min(TOTAL,n));document.querySelectorAll('.slide').forEach(x=>x.classList.remove('active'));document.getElementById(SLIDE_IDS[cur-1]).classList.add('active');document.querySelectorAll('.nav-dot').forEach((x,i)=>x.classList.toggle('active',i===cur-1));document.getElementById('nav-counter').textContent=cur+' / '+TOTAL;document.getElementById('btn-prev').disabled=cur===1;document.getElementById('btn-next').disabled=cur===TOTAL}}function goSlide(d){{showSlide(cur+d)}}function openIcp(k){{const x=ICP[k];document.getElementById('icp-modal-title').textContent=x.label+' ICP companies';document.getElementById('icp-created-list').innerHTML=x.created_companies.map(n=>'<li>'+esc(n)+'</li>').join('');document.getElementById('icp-won-list').innerHTML=x.won_companies.length?x.won_companies.map(n=>'<li>'+esc(n)+'</li>').join(''):'<li class=muted>None</li>';document.getElementById('icp-created-count').textContent=x.created+' opportunities · '+x.created_companies.length+' companies';document.getElementById('icp-won-count').textContent=x.won+' opportunities · '+x.won_companies.length+' companies';document.getElementById('icp-modal').classList.add('open')}}function closeIcp(){{document.getElementById('icp-modal').classList.remove('open')}}function esc(s){{return s.replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}}[c]))}}buildDots();showSlide(1);addEventListener('keydown',e=>{{if(e.key==='Escape')closeIcp();else if(e.key==='ArrowRight')goSlide(1);else if(e.key==='ArrowLeft')goSlide(-1)}});"
 nav='<div class="nav-bar"><div class="nav-title">Rev.io Sales · September Update</div><div class="nav-controls"><button class="nav-btn" id="btn-prev" onclick="goSlide(-1)">← Prev</button><div class="nav-dots" id="nav-dots"></div><span class="nav-counter" id="nav-counter">1 / 7</span><button class="nav-btn" id="btn-next" onclick="goSlide(1)">Next →</button></div><img src="'+logo+'" class="nav-logo"></div>'
 modal='<div class="icp-modal" id="icp-modal" onclick="if(event.target===this)closeIcp()"><div class="icp-modal-card"><button class="icp-close" onclick="closeIcp()">×</button><h3 id="icp-modal-title"></h3><div class="icp-modal-cols"><section><h4>Created</h4><small id="icp-created-count"></small><ol id="icp-created-list"></ol></section><section><h4>Closed Won</h4><small id="icp-won-count"></small><ol id="icp-won-list"></ol></section></div></div></div>'
 extra='''
.nav-dot{width:7px;height:7px;border-radius:50%;background:rgba(255,255,255,.18);cursor:pointer;transition:.15s}.nav-dot:hover{background:rgba(0,212,240,.6)}.nav-dot.active{background:#00d4f0;box-shadow:0 0 8px rgba(0,212,240,.55)}.icp-body{padding-top:16px!important}.icp-summary{display:grid;grid-template-columns:180px 150px 1fr;gap:14px;align-items:center}.icp-summary>div{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.08);padding:12px 16px;border-radius:10px}.icp-summary strong{display:block;font:800 34px Montserrat;color:#00d4f0}.icp-summary strong.green{color:#27e0a3}.icp-summary span{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,.58)}.icp-summary p{font-size:12px;color:rgba(255,255,255,.58);line-height:1.5}.icp-legend{display:flex;gap:18px;align-items:center;margin:12px 0 8px;font-size:11px;color:rgba(255,255,255,.7)}.icp-legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}.icp-legend .created{background:#00d4f0}.icp-legend .won{background:#27e0a3}.icp-legend small{margin-left:auto;color:rgba(255,255,255,.38)}.icp-months{display:grid;grid-template-columns:repeat(9,1fr);gap:8px;height:150px}.icp-month{border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.035);border-radius:9px;color:white;padding:8px 6px;cursor:pointer;display:flex;flex-direction:column;transition:.15s}.icp-month:hover{transform:translateY(-2px);border-color:rgba(0,212,240,.55);background:rgba(0,212,240,.08)}.icp-month-name{font:700 10px Montserrat;text-transform:uppercase}.icp-bars{height:96px;display:flex;align-items:flex-end;justify-content:center;gap:7px}.icp-bar{width:20px;border-radius:4px 4px 1px 1px;position:relative;min-height:8px}.icp-bar.created{background:linear-gradient(#00d4f0,#047e9d)}.icp-bar.won{background:linear-gradient(#27e0a3,#0d8764)}.icp-bar span{position:absolute;top:-15px;left:50%;transform:translateX(-50%);font:700 9px Montserrat}.icp-click{font-size:8px;color:rgba(255,255,255,.34);margin-top:5px}.icp-winners{display:flex;flex-wrap:wrap;gap:6px 8px;max-height:92px;overflow:auto}.icp-winners span{font-size:9px;color:rgba(255,255,255,.72);background:rgba(39,224,163,.08);border:1px solid rgba(39,224,163,.17);padding:5px 7px;border-radius:5px}.icp-winners b{color:#27e0a3}.icp-modal{position:fixed;inset:0;background:rgba(2,10,20,.86);z-index:100;display:none;align-items:center;justify-content:center;padding:40px}.icp-modal.open{display:flex}.icp-modal-card{width:min(980px,95vw);height:min(650px,82vh);background:#09192d;border:1px solid rgba(0,212,240,.35);border-radius:14px;padding:24px;position:relative;box-shadow:0 24px 80px #000}.icp-close{position:absolute;right:16px;top:12px;border:0;background:none;color:white;font-size:30px;cursor:pointer}.icp-modal h3{font:800 22px Montserrat;margin:0 0 18px;color:white}.icp-modal-cols{display:grid;grid-template-columns:1fr 1fr;gap:24px;height:calc(100% - 50px)}.icp-modal section{background:rgba(255,255,255,.035);border-radius:10px;padding:15px;overflow:hidden}.icp-modal h4{margin:0;color:#00d4f0;font:700 14px Montserrat}.icp-modal section+section h4{color:#27e0a3}.icp-modal small{color:rgba(255,255,255,.45)}.icp-modal ol{columns:2;column-gap:28px;height:calc(100% - 42px);overflow:auto;padding-left:22px}.icp-modal li{font-size:10px;line-height:1.55;color:rgba(255,255,255,.8);break-inside:avoid}.icp-modal li.muted{list-style:none;color:rgba(255,255,255,.35)}
'''
 html='<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rev.io Sales · September Update</title><style>'+style+extra+'</style></head><body><div class="deck">'+''.join(s)+'</div>'+nav+modal+'<script>'+script+'</script></body></html>'
 (R/'september-update-deck.html').write_text(html)
 print(json.dumps({'aug_final':{'wins':len(aw),'mrr':amount(aw)},'sep_mtd':{'wins':len(sw),'mrr':amount(sw),'open':len(so),'open_mrr':amount(so),'lost':len(sl)},'psa_ytd':{'wins':len(ps),'mrr':amount(ps)}},indent=2))
if __name__=='__main__': main()
