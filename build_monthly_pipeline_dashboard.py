#!/usr/bin/env python3
"""Build Monthly Opportunities Created Dashboard."""
import requests, json
from collections import defaultdict, Counter
from datetime import datetime, timezone

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

r = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={"grant_type":"client_credentials","client_id":SF_CLIENT_ID,"client_secret":SF_CLIENT_SECRET})
at, iu = r.json()["access_token"], r.json()["instance_url"]

now = datetime.now(timezone.utc)
month_start = f"{now.year}-{now.month:02d}-01T00:00:00Z"
month_name = now.strftime("%B %Y")

soql = f"""SELECT Id, Lead_Direction__c, Product_Type__c, Marketing_Sub_source__c,
           Owner.Name, Amount, StageName, CreatedDate, Name,
           Account.Name, Account.Industry
FROM Opportunity
WHERE CreatedDate >= {month_start}
AND IsDeleted = false"""

resp = requests.get(f"{iu}/services/data/v59.0/query", headers={"Authorization": f"Bearer {at}"}, params={"q": soql})
opps = resp.json().get('records', [])
nxt = resp.json().get('nextRecordsUrl')
while nxt:
    resp = requests.get(iu + nxt, headers={"Authorization": f"Bearer {at}"})
    opps.extend(resp.json().get('records', []))
    nxt = resp.json().get('nextRecordsUrl')

def classify_ld(v):
    if not v: return 'Other'
    v = v.strip()
    if 'marketing' in v.lower(): return 'Marketing Generated'
    if 'sales' in v.lower(): return 'Sales Generated'
    if 'channel' in v.lower() or 'partner' in v.lower(): return 'Channel Generated'
    return 'Other'

def normalize_product(p):
    if not p: return 'Other'
    if p in ('PSA','PSA 2.0'): return 'PSA 2.0'
    return p

total = len(opps)
sg_opps = [o for o in opps if classify_ld(o.get('Lead_Direction__c'))=='Sales Generated']
mg_opps = [o for o in opps if classify_ld(o.get('Lead_Direction__c'))=='Marketing Generated']
cg_opps = [o for o in opps if classify_ld(o.get('Lead_Direction__c'))=='Channel Generated']
other_opps = [o for o in opps if classify_ld(o.get('Lead_Direction__c'))=='Other']

total_mrr = sum(float(o.get('Amount') or 0) for o in opps)
sg_mrr = sum(float(o.get('Amount') or 0) for o in sg_opps)
mg_mrr = sum(float(o.get('Amount') or 0) for o in mg_opps)

# Product breakdown
by_product = Counter(normalize_product(o.get('Product_Type__c')) for o in opps)
PRODUCT_COLORS = {'PSA 2.0':'#38bdf8','Billing':'#22c55e','Payments AR':'#a78bfa','Cyber Protect':'#f97316','Billing Add-on':'#fbbf24','CommerceHub':'#2dd4bf','Other':'#64748b'}

# Vertical classification (MSP vs Integrator)
def classify_vertical(o):
    industry = ((o.get('Account') or {}).get('Industry') or '').lower()
    if 'msp' in industry: return 'MSP'
    if any(x in industry for x in ['integrator','ucaas','voip','av ','home auto','structured','iot','m2m','clec','telecom']): return 'Integrator'
    return 'Other'

msp_opps = [o for o in opps if classify_vertical(o) == 'MSP']
int_opps = [o for o in opps if classify_vertical(o) == 'Integrator']
oth_v_opps = [o for o in opps if classify_vertical(o) == 'Other']
msp_mrr = sum(float(o.get('Amount') or 0) for o in msp_opps)
int_mrr = sum(float(o.get('Amount') or 0) for o in int_opps)
oth_v_mrr = sum(float(o.get('Amount') or 0) for o in oth_v_opps)

# MG subsource
mg_subsource = Counter(o.get('Marketing_Sub_source__c') or 'Not Set' for o in mg_opps)

# By rep (all opps)
by_rep = Counter((o.get('Owner') or {}).get('Name','Unknown') for o in opps)
# By rep breakdown: SG vs MG
rep_sg = Counter((o.get('Owner') or {}).get('Name','Unknown') for o in sg_opps)
rep_mg = Counter((o.get('Owner') or {}).get('Name','Unknown') for o in mg_opps)
all_reps = sorted(by_rep.keys(), key=lambda x: -by_rep[x])

date_str = now.strftime('%B %d, %Y — %I:%M %p UTC')

# ── HTML ──────────────────────────────────────────────────────────────────────

def pct_bar(pct, color, height='8px'):
    return f'<div style="background:#1a2438;border-radius:4px;height:{height};overflow:hidden;margin-top:4px"><div style="height:100%;width:{min(pct,100):.1f}%;background:{color};border-radius:4px;transition:width .3s"></div></div>'

# Section 1: Lead Direction KPIs
ld_section = f'''
<div class="section-label">Lead Direction — {month_name}</div>
<div class="ld-grid">
  <div class="ld-card" style="--accent:#38bdf8">
    <div class="ld-label">Sales Generated</div>
    <div class="ld-val">{len(sg_opps)}</div>
    <div class="ld-sub">${sg_mrr:,.0f} pipeline &nbsp;·&nbsp; {round(len(sg_opps)/total*100) if total else 0}% of total</div>
    {pct_bar(len(sg_opps)/total*100 if total else 0, '#38bdf8', '10px')}
  </div>
  <div class="ld-card" style="--accent:#a78bfa">
    <div class="ld-label">Marketing Generated</div>
    <div class="ld-val">{len(mg_opps)}</div>
    <div class="ld-sub">${mg_mrr:,.0f} pipeline &nbsp;·&nbsp; {round(len(mg_opps)/total*100) if total else 0}% of total</div>
    {pct_bar(len(mg_opps)/total*100 if total else 0, '#a78bfa', '10px')}
  </div>
  <div class="ld-card" style="--accent:#2dd4bf">
    <div class="ld-label">Channel Generated</div>
    <div class="ld-val">{len(cg_opps)}</div>
    <div class="ld-sub">{round(len(cg_opps)/total*100) if total else 0}% of total</div>
    {pct_bar(len(cg_opps)/total*100 if total else 0, '#2dd4bf', '10px')}
  </div>
  <div class="ld-card" style="--accent:#fbbf24">
    <div class="ld-label">Total Opps Created</div>
    <div class="ld-val">{total}</div>
    <div class="ld-sub">${total_mrr:,.0f} total pipeline</div>
    {pct_bar(100, '#fbbf24', '10px')}
  </div>
</div>'''

# Section 2: By Product
product_rows = ''
for prod, count in sorted(by_product.items(), key=lambda x: -x[1]):
    col = PRODUCT_COLORS.get(prod, '#64748b')
    pct = round(count/total*100) if total else 0
    prod_opps = [o for o in opps if normalize_product(o.get('Product_Type__c')) == prod]
    prod_mrr = sum(float(o.get('Amount') or 0) for o in prod_opps)
    sg_n = sum(1 for o in prod_opps if classify_ld(o.get('Lead_Direction__c'))=='Sales Generated')
    mg_n = sum(1 for o in prod_opps if classify_ld(o.get('Lead_Direction__c'))=='Marketing Generated')
    product_rows += f'''<div class="prod-row">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <span style="font-size:13px;font-weight:700;color:#e2e8f0">{prod}</span>
    <div style="display:flex;gap:16px;align-items:center">
      <span style="font-size:11px;color:#64748b">SG: <strong style="color:#38bdf8">{sg_n}</strong></span>
      <span style="font-size:11px;color:#64748b">MG: <strong style="color:#a78bfa">{mg_n}</strong></span>
      <span style="font-size:12px;color:#64748b">${prod_mrr:,.0f}</span>
      <span style="font-size:18px;font-weight:800;color:{col}">{count}</span>
    </div>
  </div>
  {pct_bar(pct, col, '8px')}
  <div style="font-size:10px;color:#475569;margin-top:3px">{pct}% of total opps</div>
</div>'''

product_section = f'''
<div class="section-label">By Product</div>
<div class="card">{product_rows}</div>'''

# Section 3: MG Subsource
ss_rows = ''
mg_total = len(mg_opps) or 1
for ss, count in sorted(mg_subsource.items(), key=lambda x: -x[1]):
    pct = round(count/mg_total*100)
    ss_opps = [o for o in mg_opps if (o.get('Marketing_Sub_source__c') or 'Not Set') == ss]
    ss_mrr = sum(float(o.get('Amount') or 0) for o in ss_opps)
    ss_rows += f'''<div class="prod-row">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <span style="font-size:13px;font-weight:600;color:#e2e8f0">{ss}</span>
    <div style="display:flex;gap:16px;align-items:center">
      <span style="font-size:12px;color:#64748b">${ss_mrr:,.0f}</span>
      <span style="font-size:18px;font-weight:800;color:#a78bfa">{count}</span>
    </div>
  </div>
  {pct_bar(pct, '#a78bfa', '6px')}
  <div style="font-size:10px;color:#475569;margin-top:3px">{pct}% of MG opps</div>
</div>'''

subsource_section = f'''
<div class="section-label">Marketing Generated — By Sub-Source</div>
<div class="card">{ss_rows}</div>'''

# Section 4: By Rep
rep_rows = ''
for rep_name in all_reps:
    total_rep = by_rep[rep_name]
    sg_n = rep_sg.get(rep_name, 0)
    mg_n = rep_mg.get(rep_name, 0)
    rep_opps_list = [o for o in opps if (o.get('Owner') or {}).get('Name') == rep_name]
    rep_mrr = sum(float(o.get('Amount') or 0) for o in rep_opps_list)
    sg_pct = round(sg_n/total_rep*100) if total_rep else 0
    mg_pct = round(mg_n/total_rep*100) if total_rep else 0
    rep_rows += f'''<div class="rep-row">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
    <span style="font-size:14px;font-weight:700;color:#e2e8f0">{rep_name}</span>
    <div style="display:flex;gap:20px;align-items:center">
      <span style="font-size:11px;color:#64748b">${rep_mrr:,.0f} pipeline</span>
      <span style="font-size:11px;padding:2px 8px;border-radius:4px;background:#38bdf822;color:#38bdf8">SG: {sg_n}</span>
      <span style="font-size:11px;padding:2px 8px;border-radius:4px;background:#a78bfa22;color:#a78bfa">MG: {mg_n}</span>
      <span style="font-size:20px;font-weight:800;color:#f8fafc">{total_rep}</span>
    </div>
  </div>
  <div style="display:flex;gap:2px;height:8px;border-radius:4px;overflow:hidden">
    <div style="width:{sg_pct}%;background:#38bdf8;transition:width .3s"></div>
    <div style="width:{mg_pct}%;background:#a78bfa;transition:width .3s"></div>
    <div style="flex:1;background:#1a2438"></div>
  </div>
</div>'''

rep_section = f'''
<div class="section-label">By Rep — Opportunities Created</div>
<div class="card">{rep_rows}</div>'''

# Section 5: Vertical Split (MSP vs Integrator)
def vertical_product_rows():
    rows = ''
    PRODUCT_ORDER = ['PSA 2.0', 'Billing', 'Payments AR', 'Cyber Protect', 'Other']
    for prod in PRODUCT_ORDER:
        prod_all = [o for o in opps if normalize_product(o.get('Product_Type__c')) == prod]
        if not prod_all: continue
        p_msp = sum(1 for o in prod_all if classify_vertical(o) == 'MSP')
        p_int = sum(1 for o in prod_all if classify_vertical(o) == 'Integrator')
        p_oth = sum(1 for o in prod_all if classify_vertical(o) == 'Other')
        p_total = len(prod_all)
        p_msp_pct = round(p_msp/p_total*100) if p_total else 0
        p_int_pct = round(p_int/p_total*100) if p_total else 0
        col = PRODUCT_COLORS.get(prod, '#64748b')
        rows += f'''<div class="prod-row">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <span style="font-size:13px;font-weight:700;color:#e2e8f0">{prod}</span>
    <div style="display:flex;gap:16px;align-items:center">
      <span style="font-size:11px;color:#64748b">MSP: <strong style="color:#f5a623">{p_msp}</strong></span>
      <span style="font-size:11px;color:#64748b">Integrator: <strong style="color:#38bdf8">{p_int}</strong></span>
      <span style="font-size:18px;font-weight:800;color:{col}">{p_total}</span>
    </div>
  </div>
  <div style="display:flex;gap:2px;height:8px;border-radius:4px;overflow:hidden">
    <div style="width:{p_msp_pct}%;background:#f5a623"></div>
    <div style="width:{p_int_pct}%;background:#38bdf8"></div>
    <div style="flex:1;background:#1a2438"></div>
  </div>
  <div style="display:flex;gap:16px;margin-top:3px">
    <span style="font-size:10px;color:#475569">MSP {p_msp_pct}%</span>
    <span style="font-size:10px;color:#475569">Integrator {p_int_pct}%</span>
  </div>
</div>'''
    return rows

msp_pct_total = round(len(msp_opps)/total*100) if total else 0
int_pct_total = round(len(int_opps)/total*100) if total else 0
oth_v_pct_total = round(len(oth_v_opps)/total*100) if total else 0

vertical_section = f'''
<div class="section-label">Vertical Split — MSP vs Integrator</div>
<div class="ld-grid" style="grid-template-columns:repeat(3,1fr)">
  <div class="ld-card" style="--accent:#f5a623">
    <div class="ld-label">MSP</div>
    <div class="ld-val">{len(msp_opps)}</div>
    <div class="ld-sub">${msp_mrr:,.0f} pipeline &nbsp;·&nbsp; {msp_pct_total}% of total</div>
    {pct_bar(msp_pct_total, '#f5a623', '10px')}
  </div>
  <div class="ld-card" style="--accent:#38bdf8">
    <div class="ld-label">Integrator</div>
    <div class="ld-val">{len(int_opps)}</div>
    <div class="ld-sub">${int_mrr:,.0f} pipeline &nbsp;·&nbsp; {int_pct_total}% of total</div>
    {pct_bar(int_pct_total, '#38bdf8', '10px')}
  </div>
  <div class="ld-card" style="--accent:#64748b">
    <div class="ld-label">Other</div>
    <div class="ld-val">{len(oth_v_opps)}</div>
    <div class="ld-sub">${oth_v_mrr:,.0f} pipeline &nbsp;·&nbsp; {oth_v_pct_total}% of total</div>
    {pct_bar(oth_v_pct_total, '#64748b', '10px')}
  </div>
</div>
<div class="card" style="margin-top:14px">{vertical_product_rows()}</div>'''

HTML = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Monthly Pipeline Dashboard — {month_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e2e8f0}}
header{{background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);border-bottom:1px solid #334155;padding:20px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
header h1{{font-size:1.5rem;font-weight:700;color:#f8fafc}}
header h1 span{{color:#38bdf8}}
.updated{{font-size:.72rem;color:#64748b;margin-top:4px}}
.container{{max-width:1100px;margin:0 auto;padding:28px 24px;display:flex;flex-direction:column;gap:0}}
.section-label{{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin-bottom:12px;margin-top:28px;padding-bottom:6px;border-bottom:1px solid #1e293b}}
.ld-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}
.ld-card{{background:#1e293b;border:1px solid #334155;border-top:3px solid var(--accent,#38bdf8);border-radius:10px;padding:18px}}
.ld-label{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#64748b;margin-bottom:6px}}
.ld-val{{font-size:38px;font-weight:800;color:#f8fafc;line-height:1}}
.ld-sub{{font-size:11px;color:#64748b;margin-top:4px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:20px;display:flex;flex-direction:column;gap:16px}}
.prod-row{{padding-bottom:12px;border-bottom:1px solid #1a2438}}
.prod-row:last-child{{padding-bottom:0;border-bottom:none}}
.rep-row{{padding-bottom:14px;border-bottom:1px solid #1a2438}}
.rep-row:last-child{{padding-bottom:0;border-bottom:none}}
.footer{{text-align:center;padding:20px;font-size:.72rem;color:#475569;border-top:1px solid #1e293b;margin-top:28px}}
@media(max-width:700px){{.ld-grid{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<header>
  <div>
    <h1>Pipeline <span>Created This Month</span></h1>
    <div class="updated">{month_name} · Last updated: {date_str} · Salesforce live data</div>
  </div>
</header>
<div class="container">
  {ld_section}
  {vertical_section}
  {product_section}
  {subsource_section}
  {rep_section}
  <div class="footer">Rev.io Internal · Robin 🦸🏻‍♂️ · {date_str}</div>
</div>
</body></html>"""

with open('/home/openclaw/.openclaw/workspace/monthly-pipeline-dashboard.html', 'w') as f:
    f.write(HTML)

print(f"Built! {total} opps | SG:{len(sg_opps)} MG:{len(mg_opps)} CG:{len(cg_opps)} | ${total_mrr:,.0f} pipeline")
print(f"Products: {dict(by_product.most_common())}")
print(f"MG subsource: {dict(mg_subsource.most_common())}")
