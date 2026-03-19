import json
from collections import defaultdict
from datetime import datetime, timezone

with open('/home/openclaw/.openclaw/workspace/sf_march_opps.json') as f:
    raw_opps = json.load(f)

# Separate Q1 closed won (Jan-Mar) from open March pipeline — these must NEVER mix
# Q1 closed won → used ONLY for the Q1 attainment section at the top
# March open pipeline → used ONLY for the forecast scenarios below
q1_closed_opps = [o for o in raw_opps if o.get('StageName') == 'Closed Won'
                  and o.get('CloseDate','') >= '2026-01-01'
                  and o.get('CloseDate','') <= '2026-03-31']
q1_closed_by_product = defaultdict(int)
for o in q1_closed_opps:
    p = o.get('Product_Type__c') or 'None'
    if p == 'PSA': p = 'PSA 2.0'
    q1_closed_by_product[p] += o.get('Amount') or 0
q1_total_closed = sum(q1_closed_by_product.values())

# Keep only March 2026 close-date opps + any explicitly overridden opp IDs (may have non-March dates)
_override_ids = set()  # populated after manager_scenario_overrides is defined — see filter below
opps = raw_opps  # full list; filtered after overrides defined

stage_order = {
    'Closed Won': 7, '6 - Verbal Commit': 6,
    '5 - Product / Contract Validated': 5, '4 - Proposal Sent': 4,
    '3 - Initial Product Demo': 3, '2 - Discovery Completed': 2,
    '1- Discovery Scheduled': 1,
}
stage_labels = {
    'Closed Won': 'Closed Won', '6 - Verbal Commit': 'Verbal Commit',
    '5 - Product / Contract Validated': 'Validated', '4 - Proposal Sent': 'Proposal',
    '3 - Initial Product Demo': 'Demo', '2 - Discovery Completed': 'Discovery',
    '1- Discovery Scheduled': 'Scheduled',
}
stage_css = {
    'Closed Won': 'won', '6 - Verbal Commit': 's6',
    '5 - Product / Contract Validated': 's5', '4 - Proposal Sent': 's4',
    '3 - Initial Product Demo': 's3', '2 - Discovery Completed': 's2',
    '1- Discovery Scheduled': 's1',
}
product_order = ['PSA 2.0', 'Billing', 'Payments AR', 'Cyber Protect', 'Odin', 'None']
product_labels = {'PSA 2.0': 'PSA', 'Billing': 'Billing', 'Payments AR': 'Payments', 'Cyber Protect': 'Cyber Protect', 'Odin': 'Odin', 'None': 'Untagged'}
product_quotas = {'PSA 2.0': (25, 25000), 'Billing': (5, 14252), 'Payments AR': (20, 9660), 'Cyber Protect': (0, 3750), 'Odin': (0, 0), 'None': (0, 0)}

# Manager-inputted scenario overrides from weekly forecast deck
manager_scenarios = {
    'PSA 2.0':       {'worst': 7590,  'likely': 11625, 'best': 18845},
    'Billing':       {'worst': 3000,  'likely': 7700,  'best': 12950},
    'Payments AR':   {'worst': 3219,  'likely': 3513,  'best': 4163},
    'Cyber Protect': {'worst': 0,     'likely': 1440,  'best': 3503},
    'Odin':          {'worst': 0,     'likely': 0,     'best': 0},
    'None':          {'worst': 0,     'likely': 0,     'best': 0},
}
# Opp-level scenario overrides from manager's forecast deck (SF Opp Id → scenario)
# PSA unmatched: NAS $800, Phoenix Loss $500, Core Security $755, BSN $500, Imagine Audio $605 (not found in SF)
manager_scenario_overrides = {
    # === PSA ===
    # WORST CASE
    '006PX00000WMzC5YAL': 'WORST CASE',   # Larrys Lock & Safe ($920)
    '006PX00000XBMmzYAH': 'WORST CASE',   # Defcon Security Solutions ($500)
    '006PX00000XOyCvYAL': 'WORST CASE',   # Protection Systems ($875)
    '006PX00000XCOl7YAH': 'WORST CASE',   # Levines Lights ($575)
    '006PX00000W5hI1YAJ': 'WORST CASE',   # NAS Sign Company ($800) — Feb close date
    '006PX00000WJNrLYAX': 'WORST CASE',   # Phoenix Loss Prevention ($500)
    # MOST LIKELY
    '006PX00000XEHHKYA5': 'MOST LIKELY',  # Kazar Security ($500)
    '006PX00000X0meMYAR': 'MOST LIKELY',  # LimaTech - PSA ($500)
    '006PX00000XYw50YAD': 'MOST LIKELY',  # Lubbock Audio Visual ($605)
    '006PX00000XfnrNYAR': 'MOST LIKELY',  # Piedmont Security Systems 3 ($1175)
    # BEST CASE
    '006PX00000XfYifYAF': 'BEST CASE',    # Lifestyle Electronics ($2595)
    '006PX00000WQY6rYAH': 'BEST CASE',    # Compsys - PSA ($2800)
    '006PX00000VFF9lYAH': 'BEST CASE',    # Tricom Technology Solutions ($1220)

    # === BILLING ===
    # WORST CASE
    '006PX00000X5JbhYAF': 'WORST CASE',   # Telpeer ($540)
    '006PX00000TwynuYAB': 'WORST CASE',   # Southern Telecom ($1,500)
    '006PX00000VfedxYAB': 'WORST CASE',   # Preferred Tel ($1,000)
    # MOST LIKELY
    '006PX00000XZVYzYAP': 'MOST LIKELY',  # Voysis IP Solutions ($3,700) — per deck
    '006PX00000WhicsYAB': 'MOST LIKELY',  # IPRO Media ($500)
    '006PX00000XNBivYAH': 'MOST LIKELY',  # Limatech - Billing ($500)
    # BEST CASE
    '006PX00000W4cDxYAJ': 'BEST CASE',    # Maryland Telephone ($3,250)
    '006PX00000XJgTaYAL': 'BEST CASE',    # Devera Technologies ($500)
    '006PX00000WQmJVYA1': 'BEST CASE',    # Compsys - Billing ($1,500)

    # === PAYMENTS ===
    # WORST CASE
    '006PX00000X0pSXYAZ': 'WORST CASE',   # Kloud 7 ($539)
    '006PX00000X2PybYAF': 'WORST CASE',   # Kellsec Security Solutions ($50)
    # MOST LIKELY
    '006PX00000X2Ws1YAF': 'MOST LIKELY',  # RunCentral ($50)
    '006PX00000WbqZuYAJ': 'MOST LIKELY',  # Ahoy Telecom ($194)
    '006PX00000XiPSlYAN': 'MOST LIKELY',  # POS Innovation ($50)
    # BEST CASE
    '006PX00000XAz5dYAD': 'BEST CASE',    # Remote Technology ($50)
    '006PX00000XFsDBYA1': 'BEST CASE',    # Shinntek Solutions ($50)
    '006PX00000Vr6dKYAR': 'BEST CASE',    # Double Eagle Voice & Data ($50)

    # === CYBER PROTECT ===
    # MOST LIKELY
    '006PX00000WjObdYAF': 'MOST LIKELY',  # Positive Technologies Inc ($1,440)
    # BEST CASE
    '006PX00000WNaWcYAL': 'BEST CASE',    # Diversified Digital Group ($1,662)
    '006PX00000Xcd3rYAB': 'BEST CASE',    # Centra IP Networks - Cyber ($400)
}

# PSA unmatched deals — still not findable in SF:
#   Worst: Piedmont Security $750 (separate from $1175 ML deal — searching for SF ID)
#   Likely: BSN $500, Core Security $755
#   Best: Imagine Audio $605
# Payments: Numhub $500 (Best Case) not in SF
# NAS ($800) and Phoenix Loss ($500) are now tagged directly via SF IDs
scenario_adjustments = {
    'PSA 2.0':     {'worst': 750, 'likely': 1255, 'best': 605},
    'Payments AR': {'best': 500},
}

product_colors = {'PSA 2.0': '#00ff88', 'Billing': '#00e5ff', 'Payments AR': '#00ff88', 'Cyber Protect': '#ff6b35', 'Odin': '#bf5af2', 'None': '#64748b'}

# Filter to March 2026 opps only, but always include explicitly overridden IDs (e.g. NAS with Feb close)
opps = [o for o in raw_opps if (o.get('CloseDate','').startswith('2026-03') or o.get('Id') in manager_scenario_overrides)]

by_product = defaultdict(list)
for o in opps:
    # Skip Closed Lost unless explicitly called out in the manager's deck
    if o.get('StageName') == 'Closed Lost' and o.get('Id') not in manager_scenario_overrides:
        continue
    # Handle both nested (Account.Name) and flattened (AccountName) SF field formats
    if 'AccountName' in o and 'Account' not in o:
        o['Account'] = {'Name': o.get('AccountName', '?')}
    if 'OwnerName' in o and 'Owner' not in o:
        o['Owner'] = {'Name': o.get('OwnerName', '?')}
    p = o.get('Product_Type__c') or 'None'
    if p == 'PSA': p = 'PSA 2.0'
    by_product[p].append(o)

def calc(items):
    s3plus = [o for o in items if stage_order.get(o.get('StageName',''), 0) >= 3]
    s4plus = [o for o in items if stage_order.get(o.get('StageName',''), 0) >= 4]
    total_s3 = sum(o.get('Amount') or 0 for o in s3plus)
    total_s4 = sum(o.get('Amount') or 0 for o in s4plus)
    worst = total_s3 * 0.20
    likely = max(worst, total_s4 * 0.55 + (total_s3 - total_s4) * 0.15)
    best = total_s3 * 0.75
    return round(worst), round(likely), round(best)

summary = {}
for p in product_order:
    items = by_product.get(p, [])

    opp_list = sorted([{
        'acct': (o.get('Account') or {}).get('Name','?'),
        'amt': o.get('Amount') or 0,
        'stage': o.get('StageName',''),
        'stage_num': stage_order.get(o.get('StageName',''), 1),
        'prob': o.get('Probability') or 0,
        'owner': (o.get('Owner') or {}).get('Name','?'),
        'manager_scenario': manager_scenario_overrides.get(o.get('Id',''))
    } for o in items], key=lambda x: -x['stage_num'])

    closed_amt = sum(o.get('Amount') or 0 for o in items if o.get('StageName') == 'Closed Won')

    # Calculate scenario totals from tagged opps so the math always reconciles:
    # Worst = Closed Won + WORST CASE tagged deals
    # Likely = Worst + MOST LIKELY tagged deals
    # Best   = Likely + BEST CASE tagged deals
    worst_tagged  = sum(o['amt'] for o in opp_list if o.get('manager_scenario') == 'WORST CASE')
    likely_tagged = sum(o['amt'] for o in opp_list if o.get('manager_scenario') == 'MOST LIKELY')
    best_tagged   = sum(o['amt'] for o in opp_list if o.get('manager_scenario') == 'BEST CASE')

    adj = scenario_adjustments.get(p, {})
    # Billing uses deck total directly — manager's $3,000 worst doesn't include closed won
    use_deck_totals = {'Billing'}
    has_tags = (worst_tagged + likely_tagged + best_tagged) > 0
    if has_tags and p not in use_deck_totals:
        worst  = closed_amt + worst_tagged  + adj.get('worst',  0)
        likely = worst      + likely_tagged + adj.get('likely', 0)
        best   = likely     + best_tagged   + adj.get('best',   0)
    else:
        # Use manager-submitted deck totals directly
        calc_worst, calc_likely, calc_best = calc(items)
        ms = manager_scenarios.get(p, {})
        worst  = ms.get('worst',  calc_worst)
        likely = ms.get('likely', calc_likely)
        best   = ms.get('best',   calc_best)

    summary[p] = {
        'count': len(items),
        'total': sum(o.get('Amount') or 0 for o in items),
        'closed': closed_amt,
        'worst': worst, 'likely': likely, 'best': best,
        'opps': opp_list
    }

def scenario_tag(stage_num, manager_scenario=None):
    # Only tag deals explicitly called out in the manager's deck
    if manager_scenario == 'BEST CASE':
        return ('BEST CASE', '#00ff88', 'rgba(0,255,136,0.06)', 'rgba(0,255,136,0.15)')
    elif manager_scenario == 'MOST LIKELY':
        return ('MOST LIKELY', '#ffd700', 'rgba(255,215,0,0.05)', 'rgba(255,215,0,0.15)')
    elif manager_scenario == 'WORST CASE':
        return ('WORST CASE', '#ff4444', 'rgba(255,68,68,0.05)', 'rgba(255,68,68,0.15)')
    return (None, None, None, None)

def opp_rows(opps):
    rows = ''
    for o in opps:
        stage = o['stage']
        css = stage_css.get(stage, 's1')
        lbl = stage_labels.get(stage, stage)
        bar_w = min(100, int(o['prob']))
        tag_label, tag_color, row_bg, tag_bg = scenario_tag(o['stage_num'], o.get('manager_scenario'))
        scenario_badge = f'<span style="font-size:9px;font-weight:700;padding:1px 6px;border-radius:4px;background:{tag_bg};color:{tag_color};letter-spacing:0.5px;margin-left:6px">{tag_label}</span>' if tag_label else ''
        row_style = f'background:{row_bg}' if row_bg else ''
        rows += f"""<tr style="{row_style}">
          <td>{o['acct']}{scenario_badge}</td>
          <td style="color:{tag_color or '#8ab89a'};font-weight:700">${o['amt']:,.0f}</td>
          <td><span class="stage-pill {css}">{lbl}</span></td>
          <td>{o['owner']}</td>
          <td><div class="pct-wrap">{int(o['prob'])}%<div class="pct-track"><div class="pct-fill" style="width:{bar_w}%;background:{tag_color or 'var(--green)'}"></div></div></div></td>
        </tr>"""
    return rows

def product_section(pid, idx):
    p = summary[pid]
    if p['count'] == 0:
        return ''
    color = product_colors[pid]
    label = product_labels[pid]
    q_opps, q_rev = product_quotas[pid]
    att_pct = (p['closed'] / q_rev * 100) if q_rev > 0 else 0
    rows_html = opp_rows(p['opps'])
    return f"""
<div class="product-section" id="prod-{idx}">
  <div class="prod-header">
    <div class="prod-title">
      <div class="prod-dot" style="background:{color};box-shadow:0 0 8px {color}"></div>
      <h2 style="color:{color};text-shadow:0 0 20px {color}66">{label}</h2>
      <div class="live-dot"></div>
    </div>
    <div class="prod-meta">
      <span class="meta-chip">Pipeline: <strong>${p['total']:,.0f}</strong></span>
      <span class="meta-chip">{p['count']} opps</span>
      {f'<span class="meta-chip quota">Quota: ${q_rev:,}</span>' if q_rev > 0 else ''}
    </div>
  </div>

  <div class="scenarios-row">
    <div class="scenario worst">
      <div class="s-label">WORST CASE</div>
      <div class="s-val">${p['worst']:,.0f}</div>
    </div>
    <div class="scenario likely">
      <div class="s-label">MOST LIKELY</div>
      <div class="s-val">${p['likely']:,.0f}</div>
    </div>
    <div class="scenario best">
      <div class="s-label">BEST CASE</div>
      <div class="s-val">${p['best']:,.0f}</div>
    </div>
    <div class="scenario closed">
      <div class="s-label">CLOSED WON</div>
      <div class="s-val">${p['closed']:,.0f}</div>
      <div class="s-sub">{f'{att_pct:.0f}% of quota' if q_rev > 0 else 'New product'}</div>
    </div>
  </div>

  {f'''<div class="quota-bar-wrap">
    <div class="quota-bar-header">
      <span class="quota-bar-label">QUOTA ATTAINMENT</span>
      <span class="quota-bar-vals">
        <strong style="color:{color};font-size:18px">{att_pct:.1f}%</strong>
        <span style="color:#555;font-size:12px"> &nbsp;·&nbsp; ${p["closed"]:,.0f} / ${q_rev:,} target</span>
      </span>
    </div>
    <div class="quota-track">
      <div class="quota-fill" style="width:{min(att_pct,100):.1f}%;background:{color};box-shadow:0 0 10px {color}88"></div>
      <div class="quota-likely-marker" style="left:{min(p["likely"]/q_rev*100,100):.1f}%" title="Most Likely"></div>
    </div>
    <div class="quota-bar-footer">
      <span style="color:#555;font-size:11px">
        🔴 Worst: <strong style="color:#ff6666">{p["worst"]/q_rev*100:.1f}%</strong>
        &nbsp;·&nbsp; 🟡 Most Likely: <strong style="color:#ffd700">{p["likely"]/q_rev*100:.1f}%</strong>
        &nbsp;·&nbsp; 🟢 Best Case: <strong style="color:#00ff88">{min(p["best"]/q_rev*100,100):.1f}%</strong>
        &nbsp;·&nbsp; Target: ${q_rev:,}
      </span>
    </div>
  </div>''' if q_rev > 0 else ''}

  <div class="opp-toggle" onclick="toggle('{pid}')">
    <span id="toggle-label-{pid}">▶ Show all {p['count']} opportunities</span>
    <span class="toggle-amt">${p['total']:,.0f} total</span>
  </div>
  <div id="opps-{pid}" class="opp-list" style="display:none">
    <table class="opp-table">
      <thead><tr><th>Account</th><th>Amount</th><th>Stage</th><th>Owner</th><th>Prob</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</div>"""

total_worst = sum(summary[p]['worst'] for p in product_order)
total_likely = sum(summary[p]['likely'] for p in product_order)
total_best = sum(summary[p]['best'] for p in product_order)
total_pipeline = sum(summary[p]['total'] - summary[p]['closed'] for p in product_order)
total_closed = sum(summary[p]['closed'] for p in product_order)  # March Closed Won only (for summary bar)
total_opps = sum(summary[p]['count'] for p in product_order)
total_q1_target = sum(product_quotas[p][1] for p in product_order if product_quotas[p][1] > 0)
# Q1 attainment uses q1_total_closed (Jan-Mar all Closed Won) — completely separate from March forecast
q1_attainment_pct = (q1_total_closed / total_q1_target * 100) if total_q1_target > 0 else 0
q1_remaining = max(total_q1_target - q1_total_closed, 0)
q1_likely_pct = min(total_likely / total_q1_target * 100, 100) if total_q1_target > 0 else 0
q1_bar_color = '#00ff88' if q1_attainment_pct >= 80 else ('#ffd700' if q1_attainment_pct >= 50 else '#ff4444')
date_str = datetime.now(timezone.utc).strftime('%B %d, %Y')

sections = ''.join(product_section(p, i) for i, p in enumerate(product_order))

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rev.io Forecast — March 2026</title>
<style>
  :root {{
    --green: #00ff88;
    --cyan: #00e5ff;
    --bg: #020408;
    --surface: #060d14;
    --border: #0a2a1a;
    --border2: #0d1f2d;
    --text: #c8f0dc;
    --muted: #2a5a3a;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,monospace; background:var(--bg); color:var(--text); }}

  /* GRID LINES */
  body::before {{
    content:'';
    position:fixed; top:0; left:0; right:0; bottom:0;
    background-image:
      linear-gradient(rgba(0,255,136,0.10) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,255,136,0.10) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events:none; z-index:0;
  }}

  .container {{ max-width:1100px; margin:0 auto; padding:24px 32px; position:relative; z-index:1; }}
  .header {{ position:relative; }}

  /* HEADER */
  .header {{ border-bottom:1px solid var(--border); padding-bottom:16px; margin-bottom:20px; }}
  .header-top {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }}
  .logo {{ display:flex; align-items:center; gap:10px; }}
  .logo-dot {{ width:10px; height:10px; background:var(--green); border-radius:50%; box-shadow:0 0 12px var(--green); animation:pulse 2s infinite; }}
  .logo-text {{ font-size:11px; font-weight:700; letter-spacing:3px; text-transform:uppercase; color:var(--green); }}
  .header-date {{ font-size:11px; color:var(--muted); letter-spacing:1px; }}
  h1 {{ font-size:36px; font-weight:900; color:#fff; letter-spacing:-1px; margin-bottom:4px; }}
  h1 span {{ color:var(--green); text-shadow:0 0 30px var(--green); }}
  .header-sub {{ font-size:13px; color:var(--muted); }}

  /* Q1 PROGRESS CELL */
  .q1-progress-cell {{ background:var(--surface); border:1px solid rgba(0,255,136,0.25); border-radius:10px; padding:16px 22px; margin-bottom:12px; display:flex; align-items:center; gap:24px; }}
  .q1-left {{ flex:0 0 auto; }}
  .q1-label {{ font-size:9px; font-weight:700; letter-spacing:2px; text-transform:uppercase; color:var(--muted); margin-bottom:4px; }}
  .q1-pct {{ font-size:36px; font-weight:900; line-height:1; }}
  .q1-sub {{ font-size:11px; color:#5a8a6a; margin-top:3px; }}
  .q1-center {{ flex:1; }}
  .q1-bar-track {{ height:8px; background:rgba(0,255,136,0.06); border-radius:6px; position:relative; overflow:visible; margin-bottom:8px; }}
  .q1-bar-fill {{ height:100%; border-radius:6px; transition:width 0.6s ease; }}
  .q1-likely-marker {{ position:absolute; top:-4px; width:2px; height:16px; background:#ffd700; border-radius:2px; box-shadow:0 0 6px #ffd700; }}
  .q1-bar-labels {{ display:flex; justify-content:space-between; font-size:10px; color:#5a8a6a; }}
  .q1-right {{ flex:0 0 auto; text-align:right; }}
  .q1-stat {{ margin-bottom:6px; }}
  .q1-stat-label {{ font-size:9px; letter-spacing:1.5px; text-transform:uppercase; color:var(--muted); }}
  .q1-stat-val {{ font-size:14px; font-weight:700; }}

  /* SUMMARY BAR */
  .summary-bar {{ display:grid; grid-template-columns:repeat(6,1fr); gap:8px; margin-bottom:20px; }}
  .sum-item {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px; text-align:center; }}
  .sum-item.highlight {{ border-color:var(--green); background:rgba(0,255,136,0.04); }}
  .sum-label {{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:1.5px; color:var(--muted); margin-bottom:4px; }}
  .sum-val {{ font-size:18px; font-weight:900; color:#fff; }}
  .sum-val.green {{ color:var(--green); text-shadow:0 0 15px var(--green)66; }}
  .sum-val.yellow {{ color:#ffd700; }}
  .sum-val.red {{ color:#ff4444; }}

  /* PRODUCT CARDS */
  .product-section {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; margin-bottom:10px; overflow:hidden; }}
  .prod-header {{ display:flex; align-items:center; justify-content:space-between; padding:14px 18px; border-bottom:1px solid var(--border); }}
  .prod-title {{ display:flex; align-items:center; gap:10px; }}
  .prod-dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
  .prod-title h2 {{ font-size:18px; font-weight:800; letter-spacing:-0.5px; }}
  .live-dot {{ width:6px; height:6px; background:var(--green); border-radius:50%; box-shadow:0 0 6px var(--green); animation:pulse 2s infinite; }}
  .prod-meta {{ display:flex; gap:8px; align-items:center; }}
  .meta-chip {{ background:rgba(0,255,136,0.06); border:1px solid var(--border); color:#5a8a6a; font-size:11px; padding:3px 10px; border-radius:20px; }}
  .meta-chip strong {{ color:#aad4bb; }}
  .meta-chip.quota {{ border-color:rgba(0,255,136,0.2); color:var(--green); }}

  /* SCENARIOS */
  .scenarios-row {{ display:grid; grid-template-columns:repeat(4,1fr); gap:0; border-bottom:1px solid var(--border); }}
  .scenario {{ padding:12px 18px; border-right:1px solid var(--border); }}
  .scenario:last-child {{ border-right:none; }}
  .s-label {{ font-size:9px; font-weight:700; letter-spacing:2px; text-transform:uppercase; margin-bottom:4px; }}
  .scenario.worst .s-label {{ color:#ff4444; }}
  .scenario.likely .s-label {{ color:#ffd700; }}
  .scenario.best .s-label {{ color:var(--green); }}
  .scenario.closed .s-label {{ color:var(--cyan); }}
  .s-val {{ font-size:22px; font-weight:900; color:#fff; margin-bottom:2px; }}
  .scenario.worst .s-val {{ color:#ff6666; }}
  .scenario.likely .s-val {{ color:#ffd700; }}
  .scenario.best .s-val {{ color:var(--green); text-shadow:0 0 15px var(--green)44; }}
  .scenario.closed .s-val {{ color:var(--cyan); }}
  .s-sub {{ font-size:10px; color:var(--muted); }}

  /* TOGGLE */
  .opp-toggle {{ display:flex; justify-content:space-between; align-items:center; padding:8px 18px; cursor:pointer; font-size:12px; color:var(--muted); transition:background 0.15s; user-select:none; }}
  .opp-toggle:hover {{ background:rgba(0,255,136,0.03); color:var(--green); }}
  .toggle-amt {{ font-size:11px; }}

  /* TABLE */
  .opp-list {{ border-top:1px solid var(--border); }}
  .opp-table {{ width:100%; border-collapse:collapse; }}
  .opp-table thead {{ background:#030a06; }}
  .opp-table th {{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:1.5px; color:var(--muted); padding:7px 14px; text-align:left; }}
  .opp-table td {{ font-size:12px; padding:6px 14px; border-bottom:1px solid rgba(0,255,136,0.04); color:#8ab89a; }}
  .opp-table td:first-child {{ color:#c8f0dc; font-weight:600; }}
  .opp-table td:nth-child(3) {{ font-weight:700; color:#fff; }}
  .opp-table tr:last-child td {{ border-bottom:none; }}
  .opp-table tr:hover td {{ background:rgba(0,255,136,0.02); }}

  /* STAGE PILLS */
  .stage-pill {{ font-size:9px; font-weight:700; padding:2px 7px; border-radius:8px; text-transform:uppercase; letter-spacing:0.5px; }}
  .s1 {{ background:rgba(100,116,139,0.15); color:#64748b; border:1px solid rgba(100,116,139,0.2); }}
  .s2 {{ background:rgba(0,229,255,0.08); color:#00b4cc; border:1px solid rgba(0,229,255,0.15); }}
  .s3 {{ background:rgba(191,90,242,0.1); color:#bf5af2; border:1px solid rgba(191,90,242,0.2); }}
  .s4 {{ background:rgba(255,215,0,0.08); color:#ffd700; border:1px solid rgba(255,215,0,0.2); }}
  .s5 {{ background:rgba(255,107,53,0.1); color:#ff6b35; border:1px solid rgba(255,107,53,0.2); }}
  .s6 {{ background:rgba(0,255,136,0.1); color:var(--green); border:1px solid rgba(0,255,136,0.25); }}
  .won {{ background:rgba(0,255,136,0.2); color:var(--green); border:1px solid rgba(0,255,136,0.4); }}

  /* PROB BAR */
  .pct-wrap {{ display:flex; align-items:center; gap:6px; font-size:11px; color:var(--muted); }}
  .pct-track {{ flex:1; height:3px; background:rgba(0,255,136,0.08); border-radius:2px; }}
  .pct-fill {{ height:100%; border-radius:2px; background:var(--green); box-shadow:0 0 4px var(--green)66; }}

  /* QUOTA BAR */
  .quota-bar-wrap {{ padding:12px 18px; border-bottom:1px solid var(--border); }}
  .quota-bar-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:7px; }}
  .quota-bar-label {{ font-size:9px; font-weight:700; letter-spacing:2px; text-transform:uppercase; color:var(--muted); }}
  .quota-bar-vals {{ font-size:12px; }}
  .quota-track {{ height:6px; background:rgba(0,255,136,0.06); border-radius:4px; position:relative; overflow:visible; }}
  .quota-fill {{ height:100%; border-radius:4px; transition:width 0.5s ease; }}
  .quota-likely-marker {{ position:absolute; top:-3px; width:2px; height:12px; background:#ffd700; border-radius:2px; box-shadow:0 0 6px #ffd700; }}
  .quota-bar-footer {{ margin-top:5px; }}

  /* FOOTER */
  .footer {{ text-align:center; padding:20px; font-size:10px; color:#1a3a2a; letter-spacing:1px; border-top:1px solid var(--border); margin-top:8px; }}

  @keyframes pulse {{ 0%,100%{{opacity:1}}50%{{opacity:0.4}} }}

  /* SCANLINE EFFECT */
  .scanline {{ position:fixed; top:0; left:0; right:0; bottom:0; background:repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px); pointer-events:none; z-index:0; }}
</style>
</head>
<body>
<div class="scanline"></div>
<div class="container">

  <div class="header">
    <div class="header-top">
      <div class="logo">
        <div class="logo-dot"></div>
        <div class="logo-text">Rev.io · Sales Intelligence</div>
      </div>
      <div class="header-date">GENERATED {date_str.upper()} · LIVE SALESFORCE DATA</div>
      <img src="https://raw.githubusercontent.com/koontz-robin/robin-decks/master/execute.png" style="position:absolute;top:24px;right:32px;height:56px;opacity:0.9;border-radius:8px;z-index:10;" alt="Execute">
    </div>
    <h1>March 2026 <span>Forecast</span></h1>
    <div class="header-sub">{total_opps} open opportunities · Pulled live from Salesforce · Manager-submitted scenarios</div>
  </div>

  <div class="q1-progress-cell">
    <div class="q1-left">
      <div class="q1-label">Q1 Attainment</div>
      <div class="q1-pct" style="color:{q1_bar_color};text-shadow:0 0 20px {q1_bar_color}66">{q1_attainment_pct:.1f}%</div>
      <div class="q1-sub">${q1_total_closed:,.0f} of ${total_q1_target:,} target</div>
    </div>
    <div class="q1-center">
      <div class="q1-bar-track">
        <div class="q1-bar-fill" style="width:{min(q1_attainment_pct,100):.1f}%;background:{q1_bar_color};box-shadow:0 0 10px {q1_bar_color}88"></div>
        <div class="q1-likely-marker" style="left:{q1_likely_pct:.1f}%" title="Most Likely scenario"></div>
      </div>
      <div class="q1-bar-labels">
        <span>$0</span>
        <span style="color:#ffd700">🟡 Most Likely: ${total_likely:,.0f} ({q1_likely_pct:.1f}%)</span>
        <span>${total_q1_target:,}</span>
      </div>
    </div>
    <div class="q1-right">
      <div class="q1-stat">
        <div class="q1-stat-label">Remaining to Target</div>
        <div class="q1-stat-val" style="color:#ff6666">${q1_remaining:,.0f}</div>
      </div>
      <div class="q1-stat">
        <div class="q1-stat-label">Best Case</div>
        <div class="q1-stat-val" style="color:var(--green)">${total_best:,.0f} ({min(total_best/total_q1_target*100,100):.1f}%)</div>
      </div>
    </div>
  </div>

  <div class="summary-bar">
    <div class="sum-item"><div class="sum-label">Total Pipeline</div><div class="sum-val">${total_pipeline:,.0f}</div></div>
    <div class="sum-item"><div class="sum-label">Open Opps</div><div class="sum-val">{total_opps}</div></div>
    <div class="sum-item"><div class="sum-label">Closed Won</div><div class="sum-val">${total_closed:,.0f}</div></div>
    <div class="sum-item highlight"><div class="sum-label">Worst Case</div><div class="sum-val red">${total_worst:,.0f}</div></div>
    <div class="sum-item highlight"><div class="sum-label">Most Likely</div><div class="sum-val yellow">${total_likely:,.0f}</div></div>
    <div class="sum-item highlight"><div class="sum-label">Best Case</div><div class="sum-val green">${total_best:,.0f}</div></div>
  </div>

  {sections}

  <div class="footer">REV.IO SALES INTELLIGENCE · ROBIN 🦸🏻‍♂️ · CONFIDENTIAL</div>
</div>

<script>
function toggle(pid) {{
  const el = document.getElementById('opps-' + pid);
  const lbl = document.getElementById('toggle-label-' + pid);
  const count = el.querySelectorAll('tbody tr').length;
  if (el.style.display === 'none') {{
    el.style.display = 'block';
    lbl.textContent = '▼ Hide opportunities (' + count + ')';
  }} else {{
    el.style.display = 'none';
    lbl.textContent = '▶ Show all ' + count + ' opportunities';
  }}
}}
</script>
</body>
</html>"""

with open('/home/openclaw/.openclaw/workspace/forecast-march-2026.html', 'w') as f:
    f.write(html)

print(f'Done! Worst: ${total_worst:,.0f} | Likely: ${total_likely:,.0f} | Best: ${total_best:,.0f}')
