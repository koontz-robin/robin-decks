"""
patch_may_forecast.py — Patches the current-month tab + Q2 bar in forecast.html
with fresh SF data. Keeps all other tabs, formatting, and structure intact.
"""
import json, os, re
from collections import defaultdict
from datetime import datetime, timezone

WORKSPACE = '/home/openclaw/.openclaw/workspace'
now = datetime.now(timezone.utc)
TARGET_MONTH = os.environ.get('FORECAST_MONTH') or now.strftime('%B')
TARGET_MONTH = TARGET_MONTH[:1].upper() + TARGET_MONTH[1:].lower()
MONTH_SLUG = TARGET_MONTH.lower()
MONTH_ID = MONTH_SLUG
DATA_FILE = f'{WORKSPACE}/sf_{MONTH_SLUG}_opps.json'
FROZEN_MONTHS = {'May'}

if TARGET_MONTH in FROZEN_MONTHS and os.environ.get('ALLOW_FROZEN_MONTH_PATCH') != '1':
    raise SystemExit(f'{TARGET_MONTH} forecast data is locked; set ALLOW_FROZEN_MONTH_PATCH=1 to rebuild it intentionally.')

with open(DATA_FILE) as f:
    opps = json.load(f)
with open(f'{WORKSPACE}/sf_april_opps.json') as f:
    apr_opps = json.load(f)
with open(f'{WORKSPACE}/q2_reengagement_baseline.json') as f:
    mkt_accounts = {r['account_name'].lower() for r in json.load(f)}

PRODUCTS = ['PSA', 'Billing', 'Payments', 'Cyber', 'CommerceHub']
PROD_COLORS = {'PSA':'#00ff88','Billing':'#00e5ff','Payments':'#7c3aed','Cyber':'#ff6b35','CommerceHub':'#ffd700'}
PROD_LABELS = {'PSA':'PSA','Billing':'Billing / Odin','Payments':'Payments','Cyber':'Cyber Protect','CommerceHub':'CommerceHub'}
Q2_QUOTAS  = {'PSA':102000,'Billing':40988,'Payments':32620,'Cyber':13500,'CommerceHub':8801}
MONTHLY_QUOTAS = {
    'May':  {'PSA':36000,'Billing':10252,'Payments':11040,'Cyber':2478,'CommerceHub':2956},
    # June is the Q2 remainder after April quota + May quota, so product totals reconcile to Q2.
    'June': {'PSA':36000,'Billing':17368,'Payments':11040,'Cyber':6522,'CommerceHub':4178},
}
DEFAULT_MONTH_QUOTAS = {'PSA':30000,'Billing':13368,'Payments':10540,'Cyber':4500,'CommerceHub':1667}
TARGET_QUOTAS = MONTHLY_QUOTAS.get(TARGET_MONTH, DEFAULT_MONTH_QUOTAS)

STAGE_PILLS = {
    '1- Discovery Scheduled':           '<span class="stage-pill s1">Discovery Sched</span>',
    '2 - Discovery Completed':          '<span class="stage-pill s2">Discovery Done</span>',
    '3 - Initial Product Demo':         '<span class="stage-pill s3">Demo</span>',
    '4 - Proposal Sent':                '<span class="stage-pill s4">Proposal</span>',
    '5 - Product / Contract Validated': '<span class="stage-pill s5">Validated</span>',
    '6 - Verbal Commit':                '<span class="stage-pill s6">Verbal</span>',
}
FORECAST_COLORS = {
    'Worst Case':  ('#ff4444','rgba(255,68,68,0.05)','rgba(255,68,68,0.15)','WORST CASE'),
    'Most Likely': ('#ffd700','rgba(255,215,0,0.05)','rgba(255,215,0,0.15)','MOST LIKELY'),
    'Best Case':   ('#00ff88','rgba(0,255,136,0.06)','rgba(0,255,136,0.12)','BEST CASE'),
}

def prod_key(p):
    p = (p or '').strip()
    if 'PSA' in p: return 'PSA'
    if 'Billing' in p or 'Odin' in p: return 'Billing'
    if 'Payment' in p: return 'Payments'
    if 'Cyber' in p: return 'Cyber'
    if 'Commerce' in p: return 'CommerceHub'
    return 'Other'

def fmt(n): return f'${n:,.0f}'

buckets = defaultdict(lambda: {'opps':[],'closed':0.0})
for o in opps:
    p = prod_key(o.get('Product_Type__c',''))
    o['_mkt'] = (o.get('Account') or '').lower() in mkt_accounts
    if o.get('StageName') == 'Closed Won':
        buckets[p]['closed'] += (o.get('Amount') or 0)
    else:
        buckets[p]['opps'].append(o)

apr_cw = defaultdict(float)
for o in apr_opps:
    if o.get('StageName') == 'Closed Won':
        apr_cw[prod_key(o.get('Product_Type__c',''))] += (o.get('Amount') or 0)

def opp_row(o):
    fs = o.get('Forecast_Status__c','') or ''
    amt = o.get('Amount') or 0
    stage = o.get('StageName','')
    prob = int(o.get('Probability') or 0)
    acc = o.get('Account') or o.get('Name') or 'Unknown'
    owner = o.get('Owner') or ''
    pill = STAGE_PILLS.get(stage,'<span class="stage-pill">Other</span>')
    mkt_badge = '<span style="font-size:9px;font-weight:700;padding:1px 5px;border-radius:4px;background:rgba(168,85,247,0.15);color:#a855f7;letter-spacing:0.5px;margin-left:5px">🟣 MKT</span>' if o.get('_mkt') else ''
    if fs in FORECAST_COLORS:
        c,bg,bdg,lbl = FORECAST_COLORS[fs]
        badge = f'<span style="font-size:9px;font-weight:700;padding:1px 6px;border-radius:4px;background:{bdg};color:{c};letter-spacing:0.5px;margin-left:6px">{lbl}</span>'
        row_bg = f'background:{bg}'
    else:
        c,row_bg,badge = '#94a3b8','',''
    pct_bar = f'<div class="pct-wrap">{prob}%<div class="pct-track"><div class="pct-fill" style="width:{prob}%;background:{c}"></div></div></div>'
    return f'<tr style="{row_bg}"><td>{acc}{badge}{mkt_badge}</td><td style="color:{c};font-weight:700">{fmt(amt)}</td><td>{pill}</td><td>{owner}</td><td>{pct_bar}</td></tr>'

def build_month_tab():
    display = 'block' if TARGET_MONTH == now.strftime('%B') else 'none'
    lines = [f'<div id="tab-{TARGET_MONTH}" class="tab-content" style="display:{display}">']
    total_pipe = sum(o.get('Amount',0) or 0 for o in opps if o.get('StageName') != 'Closed Won')
    total_cw   = sum(buckets[p]['closed'] for p in PRODUCTS)
    open_count = sum(len(buckets[p]['opps']) for p in PRODUCTS)
    total_worst  = total_cw + sum(o.get('Amount',0) or 0 for p in PRODUCTS for o in buckets[p]['opps'] if o.get('Forecast_Status__c') == 'Worst Case')
    total_likely = total_cw + sum(o.get('Amount',0) or 0 for p in PRODUCTS for o in buckets[p]['opps'] if o.get('Forecast_Status__c') in ('Worst Case','Most Likely'))
    total_best   = total_cw + sum(o.get('Amount',0) or 0 for p in PRODUCTS for o in buckets[p]['opps'] if o.get('Forecast_Status__c') in ('Worst Case','Most Likely','Best Case'))
    lines.append(f'''    <div class="summary-bar">
      <div class="sum-item"><div class="sum-label">{TARGET_MONTH} Pipeline</div><div class="sum-val">{fmt(total_pipe)}</div></div>
      <div class="sum-item"><div class="sum-label">Open Opps</div><div class="sum-val">{open_count}</div></div>
      <div class="sum-item"><div class="sum-label">{TARGET_MONTH} CW</div><div class="sum-val">{fmt(total_cw)}</div></div>
      <div class="sum-item highlight"><div class="sum-label">Worst Case</div><div class="sum-val red">{fmt(total_worst)}</div></div>
      <div class="sum-item highlight"><div class="sum-label">Most Likely</div><div class="sum-val yellow">{fmt(total_likely)}</div></div>
      <div class="sum-item highlight"><div class="sum-label">Best Case</div><div class="sum-val green">{fmt(total_best)}</div></div>
    </div>''')

    for idx, p in enumerate(PRODUCTS):
        b = buckets[p]
        opp_list = sorted(b['opps'], key=lambda o: (
            ['Worst Case','Most Likely','Best Case',''].index(o.get('Forecast_Status__c','') if o.get('Forecast_Status__c','') in ['Worst Case','Most Likely','Best Case'] else ''),
            -(o.get('Amount') or 0)
        ))
        pipe  = sum(o.get('Amount',0) or 0 for o in opp_list)
        cw    = b['closed']
        tagged   = [o for o in opp_list if o.get('Forecast_Status__c')]
        mkt_opps = [o for o in opp_list if o.get('_mkt')]
        worst  = cw + sum(o.get('Amount',0) or 0 for o in opp_list if o.get('Forecast_Status__c') == 'Worst Case')
        likely = cw + sum(o.get('Amount',0) or 0 for o in opp_list if o.get('Forecast_Status__c') in ('Worst Case','Most Likely'))
        best   = cw + sum(o.get('Amount',0) or 0 for o in opp_list if o.get('Forecast_Status__c') in ('Worst Case','Most Likely','Best Case'))
        quota  = TARGET_QUOTAS[p]
        cw_pct     = min(cw/quota*100,100) if quota else 0
        likely_pct = min(likely/quota*100,100) if quota else 0
        worst_pct  = min(worst/quota*100,100) if quota else 0
        best_pct   = min(best/quota*100,100) if quota else 0
        c = PROD_COLORS[p]
        mkt_chip = f'<span class="meta-chip" style="border-color:rgba(168,85,247,0.3);color:#a855f7">🟣 {len(mkt_opps)} mktg</span>' if mkt_opps else ''
        lines.append(f'''
<div class="product-section" id="prod-{MONTH_ID}-{idx}">
  <div class="prod-header">
    <div class="prod-title">
      <div class="prod-dot" style="background:{c};box-shadow:0 0 8px {c}"></div>
      <h2 style="color:{c};text-shadow:0 0 20px {c}66">{PROD_LABELS[p]}</h2>
      <div class="live-dot"></div>
    </div>
    <div class="prod-meta">
      <span class="meta-chip">Pipeline: <strong>{fmt(pipe)}</strong></span>
      <span class="meta-chip">{len(opp_list)} opps</span>
      <span class="meta-chip">{len(tagged)} tagged</span>
      {mkt_chip}
      <span class="meta-chip quota">Quota: {fmt(quota)}</span>
    </div>
  </div>
  <div class="scenarios-row">
    <div class="scenario worst"><div class="s-label">WORST CASE</div><div class="s-val">{fmt(worst)}</div></div>
    <div class="scenario likely"><div class="s-label">MOST LIKELY</div><div class="s-val">{fmt(likely)}</div></div>
    <div class="scenario best"><div class="s-label">BEST CASE</div><div class="s-val">{fmt(best)}</div></div>
    <div class="scenario closed">
      <div class="s-label">{TARGET_MONTH.upper()} CLOSED WON</div>
      <div class="s-val">{fmt(cw)}</div>
      <div class="s-sub">{cw_pct:.1f}% of quota</div>
    </div>
  </div>
  <div class="quota-bar-wrap">
    <div class="quota-bar-header">
      <span class="quota-bar-label">{TARGET_MONTH.upper()} QUOTA ATTAINMENT</span>
      <span class="quota-bar-vals">
        <strong style="color:{c};font-size:18px">{cw_pct:.1f}%</strong>
        <span style="color:#555;font-size:12px"> &nbsp;·&nbsp; {fmt(cw)} / {fmt(quota)} target</span>
      </span>
    </div>
    <div class="quota-track">
      <div class="quota-fill" style="width:{cw_pct:.1f}%;background:{c};box-shadow:0 0 10px {c}88"></div>
      <div class="quota-likely-marker" style="left:{likely_pct:.1f}%" title="Most Likely"></div>
    </div>
    <div class="quota-bar-footer">
      <span style="color:#555;font-size:11px">
        🔴 Worst: <strong style="color:#ff6666">{worst_pct:.1f}%</strong>
        &nbsp;·&nbsp; 🟡 Most Likely: <strong style="color:#ffd700">{likely_pct:.1f}%</strong>
        &nbsp;·&nbsp; 🟢 Best Case: <strong style="color:#00ff88">{best_pct:.1f}%</strong>
        &nbsp;·&nbsp; Target: {fmt(quota)}
      </span>
    </div>
  </div>
  <div class="opp-toggle" onclick="toggle('{MONTH_ID}-{idx}')">
    <span id="toggle-label-{MONTH_ID}-{idx}">▶ Show all {len(opp_list)} opportunities</span>
    <span class="toggle-amt">{fmt(pipe)} total</span>
  </div>
  <div id="opps-{MONTH_ID}-{idx}" class="opp-list" style="display:none">
    <table class="opp-table">
      <thead><tr><th>Account</th><th>Amount</th><th>Stage</th><th>Owner</th><th>Prob</th></tr></thead>
      <tbody>{''.join(opp_row(o) for o in opp_list)}
</tbody>
    </table>
  </div>
</div>''')
    lines.append('  </div>\n')
    return '\n'.join(lines)

def build_q2_bar():
    may_cw = defaultdict(float)
    may_path = f'{WORKSPACE}/sf_may_opps.json'
    if os.path.exists(may_path) and MONTH_SLUG != 'may':
        with open(may_path) as f:
            for o in json.load(f):
                if o.get('StageName') == 'Closed Won':
                    may_cw[prod_key(o.get('Product_Type__c',''))] += (o.get('Amount') or 0)
    elif MONTH_SLUG == 'may':
        may_cw = {p: buckets[p]['closed'] for p in PRODUCTS}
    q2_cw = {p: apr_cw.get(p,0) + may_cw.get(p,0) + (buckets[p]['closed'] if MONTH_SLUG == 'june' else 0) for p in PRODUCTS}
    total_cw    = sum(q2_cw.values())
    total_quota = sum(Q2_QUOTAS.values())
    total_pct   = total_cw/total_quota*100 if total_quota else 0
    prods_html = ''
    for p in PRODUCTS:
        c = PROD_COLORS[p]; cw = q2_cw[p]; quota = Q2_QUOTAS[p]
        pct = min(cw/quota*100,100) if quota else 0
        prods_html += f'''<div class="q2-prod">
      <div class="q2-prod-label">{PROD_LABELS[p]}</div>
      <div class="q2-prod-bar-track">
        <div class="q2-prod-bar-fill" style="width:{pct:.1f}%;background:{c};box-shadow:0 0 6px {c}66"></div>
      </div>
      <div class="q2-prod-cw">{fmt(cw)}</div>
      <div class="q2-prod-target">/ {fmt(quota)}</div>
    </div>'''
    return f'''<div class="q2-bar-section">
    <div class="q2-bar-title">Q2 2026 CLOSED WON — {total_pct:.1f}% of {fmt(total_quota)} target ({fmt(total_cw)} closed)</div>
    <div class="q2-products">
      {prods_html}
    </div>
  </div>'''

with open(f'{WORKSPACE}/forecast.html') as f:
    html = f.read()

# Replace target month tab
tab_start = html.index(f'<div id="tab-{TARGET_MONTH}"')
next_tab = re.search(r'\n\s*<div id="tab-[A-Z][a-z]+"', html[tab_start + 1:])
pipeline_section = html.find('<!--\n  PIPELINE SOURCE SPLIT', tab_start)
if next_tab:
    tab_end = tab_start + 1 + next_tab.start()
elif pipeline_section != -1:
    tab_end = pipeline_section
else:
    tab_end = html.index('<div class="footer">', tab_start)
html = html[:tab_start] + build_month_tab() + '\n\n  ' + html[tab_end:]

# Replace Q2 bar
q2_start = html.index('<div class="q2-bar-section">')
depth, pos = 0, q2_start
while pos < len(html):
    if html[pos:pos+4] == '<div': depth += 1
    elif html[pos:pos+6] == '</div>':
        depth -= 1
        if depth == 0:
            q2_end = pos + 6
            break
    pos += 1
html = html[:q2_start] + build_q2_bar() + html[q2_end:]

date_str = now.strftime('%B %-d, %Y').upper()
html = re.sub(r'GENERATED [A-Z]+ \d+, \d{4}', f'GENERATED {date_str}', html)
html = re.sub(r"window\.addEventListener\('DOMContentLoaded', \(\) => switchTab\('[A-Z][a-z]+'\)\);",
              f"window.addEventListener('DOMContentLoaded', () => switchTab('{TARGET_MONTH}'));",
              html)
html = re.sub(r'id="btn-[A-Z][a-z]+" class="tab-btn active"', lambda m: m.group(0).replace(' active', ''), html)
html = html.replace(f'id="btn-{TARGET_MONTH}" class="tab-btn "', f'id="btn-{TARGET_MONTH}" class="tab-btn active "')
html = html.replace(f'id="btn-{TARGET_MONTH}" class="tab-btn"', f'id="btn-{TARGET_MONTH}" class="tab-btn active"')

with open(f'{WORKSPACE}/forecast.html','w') as f:
    f.write(html)

total_cw  = sum(buckets[p]['closed'] for p in PRODUCTS)
total_pipe = sum(o.get('Amount',0) or 0 for o in opps if o.get('StageName') != 'Closed Won')
print(f'{TARGET_MONTH} data patched — CW: {fmt(total_cw)} | Pipeline: {fmt(total_pipe)} | {sum(len(buckets[p]["opps"]) for p in PRODUCTS)} open opps')
