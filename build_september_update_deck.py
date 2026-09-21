#!/usr/bin/env python3
"""Build the September sales update using the May deck's exact metric structure."""
import json, re
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
import requests
from build_forecast_targets import sf_auth

R = Path(__file__).parent
LOGO = 'https://7091219.fs1.hubspotusercontent-na1.net/hubfs/7091219/email-assets/logo-revio-white.png'
MONTHS = [(2026, m, datetime(2026,m,1).strftime('%B')) for m in range(4,10)]
SHORT = [datetime(2026,m,1).strftime('%b') for m in range(4,10)]


def amount(xs): return sum(float(x.get('Amount') or 0) for x in xs)
def money(x): return '${:,.0f}'.format(x)
def compact(x): return f'${x/1000:.0f}K' if abs(x)>=1000 else money(x)
def prod(x):
    s=(x.get('Product_Type__c') or 'Other').lower()
    if 'psa' in s: return 'New Rev.io'
    if 'billing' in s or 'odin' in s: return 'Billing / Odin'
    if 'payment' in s: return 'Payments AR'
    if 'cyber' in s or 'commerce' in s: return 'Cyber + CommerceHub + Other'
    return 'Other / Not Set'
def source(x): return str(x.get('Marketing_Source__c') or x.get('Lead_Direction__c') or 'Unknown')
def card(label,val,sub,color='teal',extra=''):
    return f'<div class="kpi-card {color} {extra}"><div class="kpi-label">{label}</div><div class="kpi-val {color}">{val}</div><div class="kpi-sub">{sub}</div></div>'
def header(tag,title):
    return f'<div class="top-stripe"></div><div class="slide-header"><div class="slide-header-left"><div class="slide-tag">{tag}</div><h2>{title}</h2></div><img src="{LOGO}" alt="Rev.io"></div>'
def section(t): return f'<div class="section-hdr"><div class="section-lbl">{t}</div><div class="section-rule"></div></div>'

def sf_query(base,headers,soql):
    out=[]; url=f'{base}/services/data/v59.0/query'; params={'q':soql}
    while True:
        r=requests.get(url,headers=headers,params=params,timeout=60); r.raise_for_status(); p=r.json(); out += p.get('records') or []
        if p.get('done',True): return out
        url=base+p['nextRecordsUrl']; params={}

def product_cards(won,open_,quotas,show_open=True):
    out=[]
    for p in ['New Rev.io','Billing / Odin','Payments AR','Cyber + CommerceHub + Other']:
        w=[x for x in won if prod(x)==p]; o=[x for x in open_ if prod(x)==p]; q=quotas[p]; pct=round(amount(w)/q*100) if q else 0
        openrow=f'<div class="prod-row"><span class="prod-row-lbl">Open Pipeline</span><span class="prod-row-val teal">{money(amount(o))}</span></div>' if show_open else ''
        out.append(f'<div class="prod-card"><div class="prod-name">{p}</div><div class="prod-row"><span class="prod-row-lbl">Won MRR</span><span class="prod-row-val green">{money(amount(w))}</span></div>{openrow}<div class="prod-row"><span class="prod-row-lbl">Deals Won</span><span class="prod-row-val">{len(w)}</span></div><div class="prod-row"><span class="prod-row-lbl">Monthly Quota</span><span class="prod-row-val">{money(q)}</span></div><div class="quota-bar-wrap"><div class="quota-bar-bg"><div class="quota-bar-fill {'low' if pct<50 else 'mid'}" style="width:{min(pct,100)}%"></div></div><div class="quota-pct">{pct}% attained</div></div></div>')
    return '<div class="product-grid">'+''.join(out)+'</div>'

def month_card(label,created,wins,current=False):
    return f'<div class="month-card"><div class="month-name {'current' if current else ''}">{label}</div><div class="month-pipe">{compact(amount(created))}</div><div class="month-sub">{len(created)} opps</div><div class="month-win"><small>Won MRR</small><strong>{money(amount(wins))}</strong><em>{len(wins)} won</em></div></div>'

def table(headers,rows):
    hs=''.join(f'<th>{escape(str(h))}</th>' for h in headers)
    rs=''.join('<tr>'+''.join(f'<td>{c}</td>' for c in row)+'</tr>' for row in rows)
    return f'<div class="data-table"><table><thead><tr>{hs}</tr></thead><tbody>{rs}</tbody></table></div>'

def main():
    base,headers=sf_auth()
    fields='Id,Name,CreatedDate,CloseDate,StageName,Amount,Product_Type__c,Probability,Forecast_Status__c,Loss_Reason__c,Marketing_Source__c,Lead_Direction__c'
    opps=sf_query(base,headers,f"SELECT {fields} FROM Opportunity WHERE CreatedDate>=2026-04-01T00:00:00Z OR CloseDate>=2026-04-01 ORDER BY CreatedDate")
    created={m:[x for x in opps if (x.get('CreatedDate') or '').startswith(f'2026-{m:02d}')] for m in range(4,10)}
    won={m:[x for x in opps if x.get('StageName')=='Closed Won' and (x.get('CloseDate') or '').startswith(f'2026-{m:02d}')] for m in range(4,10)}
    lost={m:[x for x in opps if x.get('StageName')=='Closed Lost' and (x.get('CloseDate') or '').startswith(f'2026-{m:02d}')] for m in range(4,10)}
    # Use the dashboard's refreshed close-month exports for final/MTD outcomes;
    # use the live query above for true CreatedDate cohorts.
    for m,name in ((7,'july'),(8,'august'),(9,'september')):
        close_month=json.loads((R/f'sf_{name}_opps.json').read_text())
        won[m]=[x for x in close_month if x.get('StageName')=='Closed Won']
        lost[m]=[x for x in close_month if x.get('StageName')=='Closed Lost']
        if m==9: sep_close=close_month
    sep_won=won[9]; sep_lost=lost[9]; sep_open=[x for x in sep_close if x.get('StageName') not in ('Closed Won','Closed Lost')]
    aug_won=won[8]
    high=[x for x in sep_open if (x.get('Forecast_Status__c') or '') in ('Most Likely','Best Case','Worst Case')]
    quotas={'New Rev.io':46000,'Billing / Odin':12383,'Payments AR':10540,'Cyber + CommerceHub + Other':6167}
    style=re.search(r'<style>(.*?)</style>',(R/'may-update-deck.html').read_text(),re.S).group(1)
    extra='''
.month-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:16px}.month-card{background:#0f2339;border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:12px 14px}.month-name{font:700 10px Montserrat;letter-spacing:1.2px;text-transform:uppercase;color:rgba(255,255,255,.42)}.month-name.current{color:#00d4f0}.month-pipe{font:900 22px Montserrat;color:#00d4f0;margin-top:5px}.month-sub{font-size:10px;color:rgba(255,255,255,.42)}.month-win{margin-top:7px;padding-top:7px;border-top:1px solid rgba(255,255,255,.06)}.month-win small,.month-win em{display:block;font-size:9px;color:rgba(255,255,255,.35);font-style:normal}.month-win strong{display:block;font:800 14px Montserrat;color:#3ddc97}.data-table{background:#0f2339;border:1px solid rgba(255,255,255,.07);border-radius:10px;overflow:hidden;margin-bottom:14px}.data-table table{width:100%;border-collapse:collapse;font-size:10px}.data-table th{padding:7px 9px;background:rgba(0,212,240,.08);color:#00d4f0;text-transform:uppercase;letter-spacing:.7px}.data-table td{padding:6px 9px;border-top:1px solid rgba(255,255,255,.05);text-align:center}.data-table td:first-child,.data-table th:first-child{text-align:left}.trend-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.loss-num{font:900 29px Montserrat;color:#f5a623}.summary-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.summary-strip>div{background:#0f2339;border:1px solid rgba(255,255,255,.07);border-radius:9px;padding:10px;text-align:center}.summary-strip strong{display:block;font:900 20px Montserrat;color:#00d4f0}.summary-strip span{font-size:9px;color:rgba(255,255,255,.42);text-transform:uppercase;letter-spacing:.7px}
'''
    slides=[]
    slides.append(f'<div class="slide active" id="slide-1">{header("Prior Month Snapshot","Final August Pipeline Snapshot")}<div class="slide-body"><div class="kpi-row april-final-row">{card("Deals Won",len(aug_won),"Final August count")}{card("Closed Won MRR",money(amount(aug_won)),"Final August result","green")}</div>{section("August Product Results — Quota Attainment")}{product_cards(aug_won,[],quotas,False)}</div></div>')
    slides.append(f'<div class="slide" id="slide-2"><div class="cover-inner"><div class="cover-top"><img src="{LOGO}" class="cover-logo"><div class="cover-tag">Sales Leadership Update · September 2026</div></div><div class="cover-title">Rev.io Sales<br><span>September Update</span></div><div class="cover-sub">Q3 2026 Progress · Pipeline · Team Performance</div><div class="cover-chips"><div class="cover-chip"><div class="chip-val green">{money(amount(sep_won))}</div><div class="chip-label">September Closed Won MRR</div></div><div class="cover-chip"><div class="chip-val teal">{compact(amount(sep_open))}</div><div class="chip-label">September Open Pipeline</div></div><div class="cover-chip"><div class="chip-val">{len(created[9])}</div><div class="chip-label">September Opps Created</div></div></div></div><div class="cover-date">September MTD · Refreshed September 21, 2026 · Rev.io Sales Leadership</div></div>')
    slides.append(f'<div class="slide" id="slide-3">{header("Current Month Snapshot","September Pipeline Snapshot")}<div class="slide-body"><div class="kpi-row">{card("Deals Won MTD",len(sep_won),"Closed-won count")}{card("Closed Won MRR",money(amount(sep_won)),"September MTD result","green")}{card("Open Pipeline",len(sep_open),f"opps · {money(amount(sep_open))} value","navy")}{card("Forecast Tagged",len(high),f"{money(amount(high))} value","orange")}</div>{section("September Product Results — Quota Attainment")}{product_cards(sep_won,sep_open,quotas)}</div></div>')
    slides.append(f'<div class="slide" id="slide-4">{header("Sales Velocity","2026 Sales Team Efficiency")}<div class="iframe-wrap"><iframe src="q2-board-slide-1-efficiency-branded.html" title="Sales Efficiency Dashboard" loading="lazy"></iframe></div></div>')
    cards=''.join(month_card(('Sep MTD' if m==9 else datetime(2026,m,1).strftime('%B')),created[m],won[m],m==9) for m in range(4,10))
    products=['New Rev.io','Billing / Odin','Payments AR','Cyber + CommerceHub + Other','Other / Not Set']
    prow=[]
    for p in products:
        row=[f'<strong>{p}</strong>']
        for m in range(4,10):
            xs=[x for x in created[m] if prod(x)==p]; row.append(f'{len(xs)} · {compact(amount(xs))}')
        prow.append(row)
    sources=sorted({source(x) for m in range(4,10) for x in created[m]},key=lambda s:-sum(source(x)==s for m in range(4,10) for x in created[m]))[:8]
    srows=[]
    for src in sources:
        srows.append([f'<strong>{escape(src)}</strong>']+[str(sum(source(x)==src for x in created[m])) for m in range(4,10)])
    monthheads=['Metric']+SHORT[:-1]+['Sep MTD']
    totalpipe=sum(amount(created[m]) for m in range(4,10)); peak=max((len(won[m]),m) for m in range(4,10)); top_prod=max(products,key=lambda p:sum(len([x for x in created[m] if prod(x)==p]) for m in range(4,10)))
    slides.append(f'<div class="slide" id="slide-5">{header("Pipeline Creation","Pipeline Trends — April Through September MTD")}<div class="slide-body" style="padding:14px 40px 60px">{section("Monthly Pipeline Created")}<div class="month-grid">{cards}</div><div class="trend-grid"><div>{section("Pipeline by Product")}{table(monthheads,prow)}</div><div>{section("Pipeline by Source")}{table(monthheads,srows)}</div></div><div class="summary-strip"><div><strong>{compact(totalpipe)}</strong><span>Total pipeline Apr–Sep</span></div><div><strong>{peak[0]}</strong><span>Peak monthly deals won</span></div><div><strong>{top_prod}</strong><span>Largest product bucket</span></div></div></div></div>')
    loss_cards=''.join(f'<div class="month-card"><div class="month-name {'current' if m==9 else ''}">{"Sep MTD" if m==9 else datetime(2026,m,1).strftime("%B")}</div><div class="loss-num">{len(lost[m])}</div><div class="month-sub">closed lost</div></div>' for m in range(4,10))
    allreasons=Counter(x.get('Loss_Reason__c') or 'Unknown' for m in range(4,10) for x in lost[m])
    reasons=[r for r,_ in allreasons.most_common(9)]
    rrows=[]
    for r in reasons:
        vals=[sum((x.get('Loss_Reason__c') or 'Unknown')==r for x in lost[m]) for m in range(4,10)]
        rrows.append([f'<strong>{escape(r)}</strong>']+[str(v) for v in vals]+[f'{vals[-1]-vals[0]:+d}'])
    delta=len(lost[9])-len(lost[4]); pct=(delta/len(lost[4])*100) if lost[4] else 0
    slides.append(f'<div class="slide" id="slide-6">{header("Closed-Lost Analysis","Loss Reason Trends — April Through September MTD")}<div class="slide-body" style="padding:14px 40px 60px">{section("Closed Lost Volume")}<div class="month-grid">{loss_cards}</div>{section("Loss Reasons by Month")}{table(["Reason"]+SHORT[:-1]+["Sep MTD","Apr→Sep"],rrows)}<div class="summary-strip"><div><strong>{len(lost[4])}</strong><span>April losses</span></div><div><strong>{pct:+.0f}%</strong><span>Change through Sep MTD</span></div><div><strong>{escape((Counter(x.get('Loss_Reason__c') or 'Unknown' for x in lost[9]).most_common(1) or [('None',0)])[0][0])}</strong><span>Top September reason</span></div></div></div></div>')
    ids=[f'slide-{i}' for i in range(1,7)]; labels=['August Final','September Update','September Pipeline','Efficiency','Pipeline Trends','Closed Lost']
    script=f"const TOTAL=6;let cur=1;const IDS={json.dumps(ids)},LABELS={json.dumps(labels)};function buildDots(){{let w=document.getElementById('nav-dots');for(let i=1;i<=TOTAL;i++){{let d=document.createElement('div');d.className='nav-dot';d.title=LABELS[i-1];d.onclick=()=>showSlide(i);w.appendChild(d)}}}}function showSlide(n){{cur=Math.max(1,Math.min(TOTAL,n));document.querySelectorAll('.slide').forEach(x=>x.classList.remove('active'));document.getElementById(IDS[cur-1]).classList.add('active');document.querySelectorAll('.nav-dot').forEach((x,i)=>x.classList.toggle('active',i===cur-1));document.getElementById('nav-counter').textContent=cur+' / '+TOTAL;document.getElementById('btn-prev').disabled=cur===1;document.getElementById('btn-next').disabled=cur===TOTAL}}function goSlide(d){{showSlide(cur+d)}}buildDots();showSlide(1);addEventListener('keydown',e=>{{if(e.key==='ArrowRight')goSlide(1);if(e.key==='ArrowLeft')goSlide(-1)}});"
    nav=f'<div class="nav-bar"><div class="nav-title">Rev.io Sales · September Update</div><div class="nav-controls"><button class="nav-btn" id="btn-prev" onclick="goSlide(-1)">← Prev</button><div class="nav-dots" id="nav-dots"></div><span class="nav-counter" id="nav-counter">1 / 6</span><button class="nav-btn" id="btn-next" onclick="goSlide(1)">Next →</button></div><img src="{LOGO}" class="nav-logo"></div>'
    html='<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rev.io Sales · September Update</title><style>'+style+extra+'</style></head><body><div class="deck">'+''.join(slides)+'</div>'+nav+'<script>'+script+'</script></body></html>'
    (R/'september-update-deck.html').write_text(html)
    print(json.dumps({'august':{'won':len(aug_won),'mrr':amount(aug_won)},'september':{'created':len(created[9]),'won':len(sep_won),'mrr':amount(sep_won),'open':len(sep_open),'open_mrr':amount(sep_open),'lost':len(sep_lost)}},indent=2))

if __name__=='__main__': main()
