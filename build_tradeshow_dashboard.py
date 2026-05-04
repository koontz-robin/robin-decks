import json
from collections import defaultdict
from datetime import datetime, timezone

with open('/home/openclaw/.openclaw/workspace/tradeshow_contacts.json') as f:
    contacts = json.load(f)

# ── Data processing ──────────────────────────────────────────────────────────

by_event = defaultdict(list)
for c in contacts:
    event = c.get('Marketing_Sub_source__c') or 'Unknown'
    by_event[event].append(c)

status_order = ['Hot Lead', 'Warm Lead', 'Partner Request', 'Cold Lead', 'None']
status_colors = {
    'Hot Lead':        ('#ff4444', 'rgba(255,68,68,0.15)'),
    'Warm Lead':       ('#ffd700', 'rgba(255,215,0,0.12)'),
    'Partner Request': ('#bf5af2', 'rgba(191,90,242,0.12)'),
    'Cold Lead':       ('#00e5ff', 'rgba(0,229,255,0.10)'),
    'None':            ('#555',    'rgba(100,100,100,0.08)'),
}

stage_order_map = {
    'Closed Won': 8, '6 - Verbal Commit': 7,
    '5 - Product / Contract Validated': 6, '4 - Proposal Sent': 5,
    '3 - Initial Product Demo': 4, '2 - Discovery Completed': 3,
    '1- Discovery Scheduled': 2, 'Closed Lost': 1,
}
stage_labels = {
    'Closed Won': 'Closed Won', '6 - Verbal Commit': 'Verbal Commit',
    '5 - Product / Contract Validated': 'Validated', '4 - Proposal Sent': 'Proposal',
    '3 - Initial Product Demo': 'Demo', '2 - Discovery Completed': 'Discovery',
    '1- Discovery Scheduled': 'Scheduled', 'Closed Lost': 'Lost',
}
stage_css = {
    'Closed Won': 'won', '6 - Verbal Commit': 's6',
    '5 - Product / Contract Validated': 's5', '4 - Proposal Sent': 's4',
    '3 - Initial Product Demo': 's3', '2 - Discovery Completed': 's2',
    '1- Discovery Scheduled': 's1', 'Closed Lost': 'lost',
}

# Global totals
total_contacts = len(contacts)
contacts_with_opps = [c for c in contacts if c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0]
total_with_opps = len(contacts_with_opps)
conversion_rate = round(total_with_opps / total_contacts * 100, 1) if total_contacts else 0

all_opps = []
for c in contacts_with_opps:
    for o in (c['Opportunities'].get('records') or []):
        all_opps.append(o)

closed_won_opps = [o for o in all_opps if o.get('StageName') == 'Closed Won']
closed_lost_opps = [o for o in all_opps if o.get('StageName') == 'Closed Lost']
active_opps = [o for o in all_opps if o.get('StageName') not in ('Closed Won', 'Closed Lost')]

total_cw = sum(o.get('Amount') or 0 for o in closed_won_opps)
total_pipeline = sum(o.get('Amount') or 0 for o in active_opps)

status_counts = defaultdict(int)
for c in contacts:
    s = c.get('Tradeshow_Status__c') or 'None'
    status_counts[s] += 1

# Owner conversion table
owner_data = defaultdict(lambda: {'total': 0, 'with_opp': 0, 'cw': 0, 'cw_amt': 0, 'pipeline': 0})
for c in contacts:
    owner = (c.get('Owner') or {}).get('Name', 'Unknown')
    owner_data[owner]['total'] += 1
    has_opp = c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0
    if has_opp:
        owner_data[owner]['with_opp'] += 1
        for o in (c['Opportunities'].get('records') or []):
            amt = o.get('Amount') or 0
            if o.get('StageName') == 'Closed Won':
                owner_data[owner]['cw'] += 1
                owner_data[owner]['cw_amt'] += amt
            elif o.get('StageName') != 'Closed Lost':
                owner_data[owner]['pipeline'] += amt

def status_badges(event_contacts):
    counts = defaultdict(int)
    for c in event_contacts:
        s = c.get('Tradeshow_Status__c') or 'None'
        counts[s] += 1
    badges = ''
    for s in status_order:
        if counts[s]:
            col, bg = status_colors.get(s, ('#aaa', 'rgba(150,150,150,0.1)'))
            badges += f'<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;background:{bg};color:{col};margin-right:4px;white-space:nowrap">{s}: {counts[s]}</span>'
    return badges

def opp_mini_rows(event_contacts):
    rows = ''
    for c in event_contacts:
        if not (c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0):
            continue
        name = f"{c.get('FirstName','') or ''} {c.get('LastName','') or ''}".strip()
        acct = (c.get('Account') or {}).get('Name', '—')
        owner = (c.get('Owner') or {}).get('Name', '—')
        for o in (c['Opportunities'].get('records') or []):
            stage = o.get('StageName', '')
            css = stage_css.get(stage, 's1')
            lbl = stage_labels.get(stage, stage)
            amt = o.get('Amount') or 0
            amt_color = '#00ff88' if stage == 'Closed Won' else ('#ff4444' if stage == 'Closed Lost' else '#ffd700')
            rows += f'''<tr>
              <td>{name}<div style="font-size:10px;color:#5a8a6a">{acct}</div></td>
              <td style="color:{amt_color};font-weight:700">${amt:,.0f}</td>
              <td><span class="stage-pill {css}">{lbl}</span></td>
              <td style="color:#5a8a6a;font-size:11px">{owner}</td>
            </tr>\n'''
    return rows

def event_section(event, event_contacts):
    n = len(event_contacts)
    with_opp = [c for c in event_contacts if c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0]
    conv = round(len(with_opp) / n * 100) if n else 0
    opps = []
    for c in with_opp:
        for o in (c['Opportunities'].get('records') or []):
            opps.append(o)
    cw_amt = sum(o.get('Amount') or 0 for o in opps if o.get('StageName') == 'Closed Won')
    pipe_amt = sum(o.get('Amount') or 0 for o in opps if o.get('StageName') not in ('Closed Won','Closed Lost'))
    mini_rows = opp_mini_rows(event_contacts)
    has_opps = bool(mini_rows.strip())

    safe_id = event.replace(' ','_').replace('/','_').replace("'",'')

    return f'''
<div class="event-card" id="ev-{safe_id}">
  <div class="event-header" onclick="toggleEvent('{safe_id}')">
    <div class="event-title">
      <span class="event-name">{event}</span>
      <span class="event-count">{n} contacts</span>
    </div>
    <div class="event-stats">
      {status_badges(event_contacts)}
      <span class="conv-badge" title="Opp conversion rate">{conv}% → opp</span>
      {f'<span class="cw-badge">${cw_amt:,.0f} CW</span>' if cw_amt > 0 else ''}
      {f'<span class="pipe-badge">${pipe_amt:,.0f} pipeline</span>' if pipe_amt > 0 else ''}
    </div>
    <span class="toggle-arrow" id="arrow-{safe_id}">▶</span>
  </div>
  <div class="event-body" id="body-{safe_id}" style="display:none">
    {"" if not has_opps else f'''<div class="opp-table-wrap">
      <div class="opp-table-label">OPPORTUNITIES</div>
      <table class="opp-table">
        <thead><tr><th>Contact / Account</th><th>Amount</th><th>Stage</th><th>Owner</th></tr></thead>
        <tbody>{mini_rows}</tbody>
      </table>
    </div>'''}
    <div class="contact-list">
      <div class="opp-table-label">ALL CONTACTS</div>
      <table class="opp-table">
        <thead><tr><th>Name</th><th>Account</th><th>Owner</th><th>Status</th></tr></thead>
        <tbody>{''.join(f"""<tr>
          <td>{(c.get('FirstName') or '')} {(c.get('LastName') or '')}</td>
          <td style="color:#5a8a6a">{(c.get('Account') or {}).get('Name','—')}</td>
          <td style="color:#5a8a6a;font-size:11px">{(c.get('Owner') or {{}}).get('Name','—')}</td>
          <td>{f'<span style="font-size:9px;font-weight:700;padding:1px 6px;border-radius:8px;background:{status_colors.get(c.get("Tradeshow_Status__c") or "None",("#aaa","rgba(150,150,150,0.1)"))[1]};color:{status_colors.get(c.get("Tradeshow_Status__c") or "None",("#aaa","rgba(150,150,150,0.1)"))[0]}">{c.get("Tradeshow_Status__c") or "—"}</span>'}</td>
        </tr>""" for c in sorted(event_contacts, key=lambda x: (x.get('Tradeshow_Status__c') or 'Z')))}
        </tbody>
      </table>
    </div>
  </div>
</div>'''

# Build owner table
owner_rows = ''
for owner, d in sorted(owner_data.items(), key=lambda x: -x[1]['total']):
    conv_pct = round(d['with_opp'] / d['total'] * 100) if d['total'] else 0
    conv_color = '#00ff88' if conv_pct >= 30 else ('#ffd700' if conv_pct >= 15 else '#ff4444')
    owner_rows += f'''<tr>
      <td style="font-weight:600;color:#c8f0dc">{owner}</td>
      <td style="text-align:center">{d['total']}</td>
      <td style="text-align:center;color:{conv_color};font-weight:700">{conv_pct}%</td>
      <td style="text-align:center;color:#00e5ff">{d['with_opp']}</td>
      <td style="text-align:center;color:#ffd700">${d['pipeline']:,.0f}</td>
      <td style="text-align:center;color:#00ff88;font-weight:700">${d['cw_amt']:,.0f}</td>
    </tr>\n'''

# Build event sections sorted by contact count
events_html = ''.join(event_section(ev, cts) for ev, cts in sorted(by_event.items(), key=lambda x: -len(x[1])))

# Status summary chips
status_chips = ''
for s in status_order:
    cnt = status_counts.get(s, 0)
    if cnt:
        col, bg = status_colors.get(s, ('#aaa', 'rgba(150,150,150,0.1)'))
        pct = round(cnt / total_contacts * 100)
        status_chips += f'<div class="status-chip" style="border-color:{col}40;background:{bg}"><div class="sc-label" style="color:{col}">{s}</div><div class="sc-val" style="color:{col}">{cnt}</div><div class="sc-pct">{pct}%</div></div>'

date_str = datetime.now(timezone.utc).strftime('%B %d, %Y')

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tradeshow MQL Dashboard — Rev.io 2026</title>
<style>
  :root {{
    --green: #00ff88; --cyan: #00e5ff; --bg: #020408; --surface: #060d14;
    --border: #0a2a1a; --text: #c8f0dc; --muted: #2a5a3a;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,monospace; background:var(--bg); color:var(--text); }}
  body::before {{ content:''; position:fixed; top:0; left:0; right:0; bottom:0;
    background-image: linear-gradient(rgba(0,255,136,0.08) 1px, transparent 1px),
      linear-gradient(90deg,rgba(0,255,136,0.08) 1px,transparent 1px);
    background-size:40px 40px; pointer-events:none; z-index:0; }}
  .scanline {{ position:fixed; top:0; left:0; right:0; bottom:0;
    background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.03) 2px,rgba(0,0,0,0.03) 4px);
    pointer-events:none; z-index:0; }}
  .container {{ max-width:1100px; margin:0 auto; padding:24px 32px; position:relative; z-index:1; }}

  /* Header */
  .header {{ border-bottom:1px solid var(--border); padding-bottom:16px; margin-bottom:20px; }}
  .header-top {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }}
  .logo {{ display:flex; align-items:center; gap:10px; }}
  .logo-dot {{ width:10px; height:10px; background:var(--green); border-radius:50%; box-shadow:0 0 12px var(--green); animation:pulse 2s infinite; }}
  .logo-text {{ font-size:11px; font-weight:700; letter-spacing:3px; text-transform:uppercase; color:var(--green); }}
  .header-date {{ font-size:11px; color:var(--muted); }}
  h1 {{ font-size:32px; font-weight:900; color:#fff; letter-spacing:-1px; margin-bottom:4px; }}
  h1 span {{ color:var(--green); text-shadow:0 0 30px var(--green); }}
  .header-sub {{ font-size:13px; color:var(--muted); }}

  /* Summary bar */
  .summary-bar {{ display:grid; grid-template-columns:repeat(6,1fr); gap:8px; margin-bottom:20px; }}
  .sum-item {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px; text-align:center; }}
  .sum-item.hl {{ border-color:var(--green); background:rgba(0,255,136,0.04); }}
  .sum-label {{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:1.5px; color:var(--muted); margin-bottom:4px; }}
  .sum-val {{ font-size:20px; font-weight:900; color:#fff; }}
  .sum-val.green {{ color:var(--green); }}
  .sum-val.yellow {{ color:#ffd700; }}
  .sum-val.cyan {{ color:var(--cyan); }}
  .sum-val.red {{ color:#ff4444; }}

  /* Status chips */
  .status-row {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:20px; }}
  .status-chip {{ background:var(--surface); border:1px solid; border-radius:10px; padding:10px 16px; min-width:110px; text-align:center; }}
  .sc-label {{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }}
  .sc-val {{ font-size:24px; font-weight:900; }}
  .sc-pct {{ font-size:11px; color:var(--muted); margin-top:2px; }}

  /* Owner table */
  .section-title {{ font-size:10px; font-weight:700; letter-spacing:2px; text-transform:uppercase; color:var(--muted); margin-bottom:8px; margin-top:20px; }}
  .owner-table-wrap {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; overflow:hidden; margin-bottom:20px; }}
  .owner-table {{ width:100%; border-collapse:collapse; }}
  .owner-table th {{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:1.5px; color:var(--muted); padding:8px 14px; text-align:left; background:#030a06; }}
  .owner-table th:not(:first-child) {{ text-align:center; }}
  .owner-table td {{ font-size:12px; padding:7px 14px; border-bottom:1px solid rgba(0,255,136,0.04); color:#8ab89a; }}
  .owner-table tr:last-child td {{ border-bottom:none; }}
  .owner-table tr:hover td {{ background:rgba(0,255,136,0.02); }}

  /* Event cards */
  .events-section {{ margin-top:8px; }}
  .event-card {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; margin-bottom:8px; overflow:hidden; }}
  .event-header {{ display:flex; align-items:center; justify-content:space-between; padding:12px 18px; cursor:pointer; gap:12px; }}
  .event-header:hover {{ background:rgba(0,255,136,0.02); }}
  .event-title {{ display:flex; align-items:center; gap:12px; flex-shrink:0; }}
  .event-name {{ font-size:15px; font-weight:800; color:#fff; }}
  .event-count {{ font-size:11px; color:var(--muted); background:rgba(0,255,136,0.06); border:1px solid var(--border); padding:2px 8px; border-radius:10px; }}
  .event-stats {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; flex:1; justify-content:flex-end; }}
  .conv-badge {{ font-size:10px; font-weight:700; padding:2px 8px; border-radius:10px; background:rgba(0,229,255,0.1); color:var(--cyan); border:1px solid rgba(0,229,255,0.2); white-space:nowrap; }}
  .cw-badge {{ font-size:10px; font-weight:700; padding:2px 8px; border-radius:10px; background:rgba(0,255,136,0.1); color:var(--green); border:1px solid rgba(0,255,136,0.2); white-space:nowrap; }}
  .pipe-badge {{ font-size:10px; font-weight:700; padding:2px 8px; border-radius:10px; background:rgba(255,215,0,0.08); color:#ffd700; border:1px solid rgba(255,215,0,0.2); white-space:nowrap; }}
  .toggle-arrow {{ color:var(--muted); font-size:12px; flex-shrink:0; }}
  .event-body {{ border-top:1px solid var(--border); }}
  .opp-table-wrap {{ padding:14px 18px; border-bottom:1px solid var(--border); }}
  .contact-list {{ padding:14px 18px; }}
  .opp-table-label {{ font-size:9px; font-weight:700; letter-spacing:2px; text-transform:uppercase; color:var(--muted); margin-bottom:8px; }}
  .opp-table {{ width:100%; border-collapse:collapse; }}
  .opp-table th {{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:1.5px; color:var(--muted); padding:6px 10px; text-align:left; }}
  .opp-table td {{ font-size:12px; padding:5px 10px; border-bottom:1px solid rgba(0,255,136,0.04); color:#8ab89a; }}
  .opp-table tr:last-child td {{ border-bottom:none; }}

  /* Stage pills */
  .stage-pill {{ font-size:9px; font-weight:700; padding:2px 7px; border-radius:8px; text-transform:uppercase; letter-spacing:0.5px; }}
  .won  {{ background:rgba(0,255,136,0.2); color:var(--green); border:1px solid rgba(0,255,136,0.4); }}
  .lost {{ background:rgba(100,116,139,0.15); color:#64748b; border:1px solid rgba(100,116,139,0.2); }}
  .s6   {{ background:rgba(0,255,136,0.1); color:var(--green); border:1px solid rgba(0,255,136,0.25); }}
  .s5   {{ background:rgba(255,107,53,0.1); color:#ff6b35; border:1px solid rgba(255,107,53,0.2); }}
  .s4   {{ background:rgba(255,215,0,0.08); color:#ffd700; border:1px solid rgba(255,215,0,0.2); }}
  .s3   {{ background:rgba(191,90,242,0.1); color:#bf5af2; border:1px solid rgba(191,90,242,0.2); }}
  .s2   {{ background:rgba(0,229,255,0.08); color:#00b4cc; border:1px solid rgba(0,229,255,0.15); }}
  .s1   {{ background:rgba(100,116,139,0.15); color:#64748b; border:1px solid rgba(100,116,139,0.2); }}

  .footer {{ text-align:center; padding:20px; font-size:10px; color:#1a3a2a; letter-spacing:1px; border-top:1px solid var(--border); margin-top:8px; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}}50%{{opacity:0.4}} }}
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
    </div>
    <h1>Tradeshow <span>MQL Dashboard</span></h1>
    <div class="header-sub">2026 YTD · {total_contacts} contacts · {len(by_event)} events · Tracking lead → opp → close conversion</div>
  </div>

  <div class="summary-bar">
    <div class="sum-item"><div class="sum-label">Total Contacts</div><div class="sum-val">{total_contacts}</div></div>
    <div class="sum-item"><div class="sum-label">Events</div><div class="sum-val">{len(by_event)}</div></div>
    <div class="sum-item hl"><div class="sum-label">Opp Conversion</div><div class="sum-val green">{conversion_rate}%</div></div>
    <div class="sum-item"><div class="sum-label">With Opps</div><div class="sum-val yellow">{total_with_opps}</div></div>
    <div class="sum-item"><div class="sum-label">Active Pipeline</div><div class="sum-val cyan">${total_pipeline:,.0f}</div></div>
    <div class="sum-item hl"><div class="sum-label">Closed Won</div><div class="sum-val green">${total_cw:,.0f}</div></div>
  </div>

  <div class="status-row">
    {status_chips}
  </div>

  <div class="section-title">Conversion by AE</div>
  <div class="owner-table-wrap">
    <table class="owner-table">
      <thead><tr>
        <th>AE</th>
        <th>Contacts</th>
        <th>Conv %</th>
        <th>With Opp</th>
        <th>Pipeline</th>
        <th>Closed Won</th>
      </tr></thead>
      <tbody>{owner_rows}</tbody>
    </table>
  </div>

  <div class="section-title">By Event — {len(by_event)} events</div>
  <div class="events-section">
    {events_html}
  </div>

  <div class="footer">REV.IO SALES INTELLIGENCE · ROBIN 🦸🏻‍♂️ · CONFIDENTIAL</div>
</div>

<script>
function toggleEvent(id) {{
  const body = document.getElementById('body-' + id);
  const arrow = document.getElementById('arrow-' + id);
  if (body.style.display === 'none') {{
    body.style.display = 'block';
    arrow.textContent = '▼';
  }} else {{
    body.style.display = 'none';
    arrow.textContent = '▶';
  }}
}}
</script>
</body>
</html>'''

with open('/home/openclaw/.openclaw/workspace/tradeshow-mql.html', 'w') as f:
    f.write(html)

print(f"Done! {total_contacts} contacts, {len(by_event)} events")
print(f"Conversion rate: {conversion_rate}%")
print(f"Pipeline: ${total_pipeline:,.0f} | CW: ${total_cw:,.0f}")
