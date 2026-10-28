#!/usr/bin/env python3
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'q4-ae-target-dashboard.html'
DATA=ROOT/'q4_ae_target_dashboard.json'
MONTHS=['October','November','December']
TARGETS={'October':{'New Rev.io':55000,'Classic Rev.io':12368},'November':{'New Rev.io':30000,'Classic Rev.io':13368},'December':{'New Rev.io':30000,'Classic Rev.io':13368}}
ROSTER=['Jamie Butler','Joe Abarno','Andy Whisenant','Connor Flynn','Patrick Davies','Jake Borah','Jaylin Bender','Abbey McIntosh']
SF_NAMES={'Joseph Abarno':'Joe Abarno'}
QUOTAS={'Jamie Butler':24000,'Joe Abarno':24000,'Andy Whisenant':15000,'Connor Flynn':15000,'Patrick Davies':15000,'Jake Borah':15000,'Jaylin Bender':12000,'Abbey McIntosh':12000}

def money(v): return f'${v:,.0f}'
def product_key(text):
    text=(text or '').lower()
    if 'psa' in text: return 'New Rev.io'
    if 'billing' in text or 'odin' in text: return 'Classic Rev.io'
    return 'Other'
def splits(o):
    out=defaultdict(float)
    for li in ((o.get('OpportunityLineItems') or {}).get('records') or []):
        amount=li.get('TotalPrice')
        if amount is None: amount=(li.get('Quantity') or 0)*(li.get('UnitPrice') or 0)
        if not amount: continue
        p=li.get('Product2') or {}
        key=product_key(f"{p.get('Family','')} {p.get('Name','')}")
        if key!='Other': out[key]+=float(amount)
    if out: return out
    key=product_key(o.get('Product_Type__c'))
    if key!='Other': out[key]+=float(o.get('Amount') or 0)
    return out

actual=defaultdict(lambda:defaultdict(lambda:defaultdict(float)))
deals=[]
for month in MONTHS:
    opps=json.loads((ROOT/f'sf_{month.lower()}_opps.json').read_text())
    for o in opps:
        if o.get('StageName')!='Closed Won': continue
        rep=SF_NAMES.get(o.get('Owner'),o.get('Owner'))
        if rep not in ROSTER: continue
        for product,amount in splits(o).items():
            actual[rep][month][product]+=amount
            if amount:
                deals.append({'rep':rep,'month':month,'product':product,'amount':amount,'name':o.get('Name'),'account':o.get('Account'),'id':o.get('Id')})

def row(rep, period):
    months=MONTHS if period=='Quarter' else [period]
    new=sum(actual[rep][m]['New Rev.io'] for m in months)
    classic=sum(actual[rep][m]['Classic Rev.io'] for m in months)
    total=new+classic
    quota=QUOTAS[rep] if period=='Quarter' else None
    cells=f'<td class="money new">{money(new)}</td><td class="money classic">{money(classic)}</td><td class="money total">{money(total)}</td>'
    if period=='Quarter':
        pct=total/quota*100 if quota else 0
        cells+=f'<td class="money">{money(quota)}</td><td><div class="att"><span style="width:{min(pct,100):.1f}%"></span></div><b>{pct:.1f}%</b></td>'
    return f'<tr><td><strong>{rep}</strong></td>{cells}</tr>'

def panel(period):
    months=MONTHS if period=='Quarter' else [period]
    tn=sum(TARGETS[m]['New Rev.io'] for m in months); tc=sum(TARGETS[m]['Classic Rev.io'] for m in months)
    an=sum(actual[r][m]['New Rev.io'] for r in ROSTER for m in months); ac=sum(actual[r][m]['Classic Rev.io'] for r in ROSTER for m in months)
    cols='<th>AE</th><th>New Rev.io</th><th>Classic Rev.io</th><th>Total Closed</th>'
    if period=='Quarter': cols+='<th>Q4 AE Quota</th><th>Attainment</th>'
    return f'''<section class="panel" id="{period.lower()}">
      <div class="cards">
       <article><span>New Rev.io</span><strong>{money(an)}</strong><small>of {money(tn)} team target · {(an/tn*100 if tn else 0):.1f}%</small><div class="bar"><i style="width:{min(an/tn*100 if tn else 0,100):.1f}%"></i></div></article>
       <article><span>Classic Rev.io</span><strong>{money(ac)}</strong><small>of {money(tc)} team target · {(ac/tc*100 if tc else 0):.1f}%</small><div class="bar blue"><i style="width:{min(ac/tc*100 if tc else 0,100):.1f}%"></i></div></article>
       <article><span>Total AE Closed MRR</span><strong>{money(an+ac)}</strong><small>New + Classic · team target {money(tn+tc)}</small><div class="split"><b style="width:{an/(an+ac)*100 if an+ac else 0:.1f}%"></b></div></article>
      </div>
      <div class="tablewrap"><table><thead><tr>{cols}</tr></thead><tbody>{''.join(row(r,period) for r in ROSTER)}</tbody></table></div>
      <p class="note">Targets above are team targets. Rep-level product targets are not maintained in the current source; Q4 rep quota is shown only as the approved aggregate quota.</p>
    </section>'''

payload={'generated_at_et':datetime.now(ZoneInfo('America/New_York')).isoformat(),'targets':TARGETS,'rep_quotas':QUOTAS,'deals':deals,'actuals':{r:{m:dict(actual[r][m]) for m in MONTHS} for r in ROSTER}}
DATA.write_text(json.dumps(payload,indent=2)+'\n')
buttons=''.join(f'<button data-tab="{p.lower()}" class="{ "active" if p=="October" else ""}">{p if p!="Quarter" else "Q4 Total"}</button>' for p in MONTHS+['Quarter'])
html=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Q4 AE Target Dashboard</title><style>
:root{{--bg:#07111f;--panel:#0d1a2b;--line:#20334a;--text:#f4f7fb;--muted:#91a4bb;--green:#c6f178;--blue:#34bde5}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 85% 0,#17314a 0,transparent 32%),var(--bg);color:var(--text);font:15px Inter,system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:30px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:20px}}h1{{font-size:38px;margin:5px 0}}.eyebrow,.stamp,.note,small{{color:var(--muted)}}.tabs{{display:flex;gap:8px;margin:22px 0}}button{{background:#0c1929;border:1px solid var(--line);color:var(--muted);padding:11px 18px;border-radius:999px;font-weight:800;cursor:pointer}}button.active{{background:var(--green);color:#07111f;border-color:var(--green)}}.panel{{display:none}}.panel.active{{display:block}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}}article,.tablewrap{{background:linear-gradient(145deg,#101f32,#0a1625);border:1px solid var(--line);border-radius:16px}}article{{padding:22px}}article span{{display:block;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.08em;font-size:12px}}article strong{{display:block;font-size:35px;margin:8px 0}}.bar,.split{{height:7px;background:#1c2c40;border-radius:10px;margin-top:16px;overflow:hidden}}.bar i,.split b{{display:block;height:100%;background:var(--green)}}.bar.blue i{{background:var(--blue)}}.split b{{background:linear-gradient(90deg,var(--green),var(--blue))}}.tablewrap{{overflow:hidden}}table{{width:100%;border-collapse:collapse}}th,td{{padding:17px 20px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}td.money{{font-variant-numeric:tabular-nums;font-size:17px}}td.new{{color:var(--green)}}td.classic{{color:var(--blue)}}td.total{{font-weight:900}}.att{{display:inline-block;width:90px;height:6px;background:#1c2c40;border-radius:5px;margin-right:8px;vertical-align:middle;overflow:hidden}}.att span{{display:block;height:100%;background:var(--green)}}.note{{font-size:12px;margin:12px 4px}}footer{{margin-top:25px;color:var(--muted);font-size:12px}}@media(max-width:850px){{main{{padding:18px}}header{{display:block}}h1{{font-size:29px}}.cards{{grid-template-columns:1fr}}.tablewrap{{overflow:auto}}table{{min-width:850px}}}}
</style></head><body><main><header><div><div class="eyebrow">REV.IO · Q4 2026 FORECAST</div><h1>AE Targets & Closed MRR</h1><div class="stamp">Classic Rev.io + New Rev.io · rep-level accountability</div></div><div class="stamp">Salesforce refreshed {datetime.now(ZoneInfo('America/New_York')).strftime('%b %d, %Y · %I:%M %p ET')}</div></header><nav class="tabs">{buttons}</nav>{''.join(panel(p) for p in MONTHS+['Quarter'])}<footer>Closed MRR uses Salesforce line-item values where available and excludes Payments, migrations, and non-AE owners.</footer></main><script>const bs=[...document.querySelectorAll('button')],ps=[...document.querySelectorAll('.panel')];function show(x){{bs.forEach(b=>b.classList.toggle('active',b.dataset.tab===x));ps.forEach(p=>p.classList.toggle('active',p.id===x));location.hash=x}}bs.forEach(b=>b.onclick=()=>show(b.dataset.tab));show((location.hash||'#october').slice(1));</script></body></html>'''
OUT.write_text(html)
print(f'Wrote {OUT.name} and {DATA.name}; {len(deals)} valued AE product splits')
