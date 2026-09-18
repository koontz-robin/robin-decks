#!/usr/bin/env python3
"""Build the September sales update from the existing Salesforce exports.
The August deck is the presentation template; no source systems are mutated.
"""
import json, re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from html import escape
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
def product_cards(won,open_,quotas):
 out=[]
 for p in ['PSA','Billing / Odin','Payments','Cyber + CommerceHub + Other']:
  w=[x for x in won if prod(x)==p]; o=[x for x in open_ if prod(x)==p]; q=quotas[p]; pct=round(amount(w)/q*100) if q else 0
  out.append(f'<div class="prod-card"><div class="prod-name">{p}</div><div class="prod-row"><span class="prod-row-lbl">Won MRR</span><span class="prod-row-val green">{money(amount(w))}</span></div><div class="prod-row"><span class="prod-row-lbl">Open Pipeline</span><span class="prod-row-val teal">{money(amount(o))}</span></div><div class="prod-row"><span class="prod-row-lbl">Opportunities Won</span><span class="prod-row-val">{len(w)}</span></div><div class="prod-row"><span class="prod-row-lbl">Monthly Quota</span><span class="prod-row-val">{money(q)}</span></div><div class="quota-bar-wrap"><div class="quota-bar-bg"><div class="quota-bar-fill {'low' if pct<50 else 'mid'}" style="width:{min(pct,100)}%"></div></div><div class="quota-pct">{pct}% attained</div></div></div>')
 return '<div class="product-grid">'+''.join(out)+'</div>'

def main():
 aug,sep,jul=load('sf_august_opps.json'),load('sf_september_opps.json'),load('sf_july_opps.json')
 base=load('sf_june_deck_data.json')
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
 labels=['Cover + August Final','September Pipeline','Pipeline Trends','PSA Wins','Closed Lost','Efficiency']; ids=['slide-1','slide-2','slide-4','slide-6','slide-5','slide-3']
 script=f"const TOTAL=6;let cur=1;const SLIDE_IDS={json.dumps(ids)};const LABELS={json.dumps(labels)};function buildDots(){{let w=document.getElementById('nav-dots');for(let i=1;i<=TOTAL;i++){{let d=document.createElement('div');d.className='nav-dot';d.title=LABELS[i-1];d.onclick=()=>showSlide(i);w.appendChild(d)}}}}function showSlide(n){{cur=Math.max(1,Math.min(TOTAL,n));document.querySelectorAll('.slide').forEach(x=>x.classList.remove('active'));document.getElementById(SLIDE_IDS[cur-1]).classList.add('active');document.querySelectorAll('.nav-dot').forEach((x,i)=>x.classList.toggle('active',i===cur-1));document.getElementById('nav-counter').textContent=cur+' / '+TOTAL;document.getElementById('btn-prev').disabled=cur===1;document.getElementById('btn-next').disabled=cur===TOTAL}}function goSlide(d){{showSlide(cur+d)}}buildDots();showSlide(1);addEventListener('keydown',e=>{{if(e.key==='ArrowRight')goSlide(1);if(e.key==='ArrowLeft')goSlide(-1)}});"
 nav='<div class="nav-bar"><div class="nav-title">Rev.io Sales · September Update</div><div class="nav-controls"><button class="nav-btn" id="btn-prev" onclick="goSlide(-1)">← Prev</button><div class="nav-dots" id="nav-dots"></div><span class="nav-counter" id="nav-counter">1 / 6</span><button class="nav-btn" id="btn-next" onclick="goSlide(1)">Next →</button></div><img src="'+logo+'" class="nav-logo"></div>'
 html='<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rev.io Sales · September Update</title><style>'+style+'</style></head><body><div class="deck">'+''.join(s)+'</div>'+nav+'<script>'+script+'</script></body></html>'
 (R/'september-update-deck.html').write_text(html)
 print(json.dumps({'aug_final':{'wins':len(aw),'mrr':amount(aw)},'sep_mtd':{'wins':len(sw),'mrr':amount(sw),'open':len(so),'open_mrr':amount(so),'lost':len(sl)},'psa_ytd':{'wins':len(ps),'mrr':amount(ps)}},indent=2))
if __name__=='__main__': main()
