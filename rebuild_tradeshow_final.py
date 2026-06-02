import json, re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / 'tradeshow_contacts.json') as f:
    raw_contacts = json.load(f)

history_path = BASE_DIR / 'tradeshow_contact_status_history.json'
if history_path.exists():
    with open(history_path) as f:
        contact_status_history = json.load(f)
else:
    contact_status_history = []

YEAR_START = '2026-01-01'

mql_2026_contact_ids = {
    h.get('ContactId')
    for h in contact_status_history
    if h.get('Field') == 'Contact_Status__c'
    and h.get('NewValue') == 'MQL'
    and (h.get('CreatedDate') or '') >= YEAR_START
}
sql_from_mql_2026_contact_ids = {
    h.get('ContactId')
    for h in contact_status_history
    if h.get('Field') == 'Contact_Status__c'
    and h.get('OldValue') == 'MQL'
    and h.get('NewValue') == 'SQL'
    and (h.get('CreatedDate') or '') >= YEAR_START
}

def was_mql_in_2026(c):
    cid = c.get('Id')
    status = c.get('Contact_Status__c') or ''
    created_in_2026 = (c.get('CreatedDate') or '') >= YEAR_START
    converted_in_2026 = (c.get('Most_Recent_Conversion__c') or '') >= YEAR_START
    return (
        cid in mql_2026_contact_ids
        or cid in sql_from_mql_2026_contact_ids
        or converted_in_2026
        or (created_in_2026 and status in ('MQL', 'SQL', 'Disqualified'))
    )

contacts = [c for c in raw_contacts if was_mql_in_2026(c)]

def effective_status(c):
    """SQL only counts when Contact Status changed from MQL to SQL in 2026."""
    sf_status = c.get('Contact_Status__c') or 'Unknown'
    if c.get('Id') in sql_from_mql_2026_contact_ids:
        return 'SQL'
    if sf_status == 'SQL':
        return 'MQL'
    return sf_status

status_defs = [
    ('SQL',          '#00ff88'),
    ('MQL',          '#00e5ff'),
    ('Disqualified', '#ff4444'),
    ('Partner',      '#bf5af2'),
    ('Potential Referral/Partner', '#a855f7'),
    ('Client',       '#ffd700'),
    ('Unknown',      '#444'),
]

mql_status_defs = [
    ('Hot Lead',        '#00ff88'),
    ('Warm Lead',       '#00e5ff'),
    ('Cold Lead',       '#ffb000'),
    ('Partner Request', '#bf5af2'),
    ('Client Request',  '#ffd700'),
    ('Unknown',         '#444'),
]

# Global counts
status_counts = defaultdict(int)
mql_status_counts = defaultdict(int)
for c in contacts:
    status_counts[effective_status(c)] += 1
    mql_status_counts[c.get('Tradeshow_Status__c') or 'Unknown'] += 1

total = len(contacts)
with_opps = [c for c in contacts if c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0]
total_with_opps = len(with_opps)

# Use tradeshow_opps.json (Opp.Marketing_Sub_source__c query) for CW/pipeline
# This reflects new post-show bookings only, not pre-existing contact-linked deals
with open(BASE_DIR / 'tradeshow_opps.json') as _f:
    sourced_opps = json.load(_f)
total_cw = sum(o.get('Amount') or 0 for o in sourced_opps if o.get('StageName') == 'Closed Won')
total_pipeline = sum(o.get('Amount') or 0 for o in sourced_opps if o.get('StageName') not in ('Closed Won', 'Closed Lost'))
total_sql = status_counts.get('SQL', 0)
conv_rate = round(total_sql / total * 100, 1) if total else 0

# Status graph data
funnel = [(s, c, status_counts.get(s, 0)) for s, c in status_defs if status_counts.get(s, 0) > 0]

# Donut data
mql_status_funnel = [(s, c, mql_status_counts.get(s, 0)) for s, c in mql_status_defs if mql_status_counts.get(s, 0) > 0]

# By-event data
by_event = defaultdict(lambda: defaultdict(int))
mql_status_by_event = defaultdict(lambda: defaultdict(int))
for c in contacts:
    ev = c.get('Marketing_Sub_source__c') or 'Unknown'
    by_event[ev][effective_status(c)] += 1
    mql_status_by_event[ev][c.get('Tradeshow_Status__c') or 'Unknown'] += 1
events_sorted = sorted(by_event.items(), key=lambda x: -sum(x[1].values()))

stage_labels_map = {
    'Closed Won': 'Closed Won', '6 - Verbal Commit': 'Verbal Commit',
    '5 - Product / Contract Validated': 'Validated', '4 - Proposal Sent': 'Proposal',
    '3 - Initial Product Demo': 'Demo', '2 - Discovery Completed': 'Discovery',
    '1- Discovery Scheduled': 'Scheduled', 'Closed Lost': 'Lost',
}
stage_css_map = {
    'Closed Won': 'won', '6 - Verbal Commit': 's6', '5 - Product / Contract Validated': 's5',
    '4 - Proposal Sent': 's4', '3 - Initial Product Demo': 's3', '2 - Discovery Completed': 's2',
    '1- Discovery Scheduled': 's1', 'Closed Lost': 'lost',
}
status_bg_map = {
    'SQL': 'rgba(0,255,136,0.12)',
    'MQL': 'rgba(0,229,255,0.1)',
    'Disqualified': 'rgba(255,68,68,0.12)',
    'Partner': 'rgba(191,90,242,0.12)',
    'Potential Referral/Partner': 'rgba(168,85,247,0.12)',
    'Client': 'rgba(255,215,0,0.12)',
    'Unknown': 'rgba(80,80,80,0.1)',
}
status_color_map = dict(status_defs)

def status_pill(s):
    col = status_color_map.get(s, '#888')
    bg = status_bg_map.get(s, 'rgba(80,80,80,0.1)')
    return f'<span style="font-size:9px;font-weight:700;padding:1px 6px;border-radius:8px;background:{bg};color:{col}">{s}</span>'

def event_status_breakdown(ev_counts, total_count):
    segments = ''
    labels = ''
    for s, col in status_defs:
        cnt = ev_counts.get(s, 0)
        if not cnt:
            continue
        pct = cnt / total_count * 100 if total_count else 0
        segments += f'<div class="event-status-segment" style="width:{pct:.1f}%;background:{col}" title="{s}: {cnt} ({pct:.0f}%)"></div>'
        labels += f'<span class="event-status-label" style="color:{col};background:{status_bg_map.get(s,"rgba(80,80,80,0.1)")};border-color:{col}33">{s}: {cnt}</span>'
    return f'''<div class="event-status-breakdown">
      <div class="event-status-track">{segments}</div>
      <div class="event-status-labels">{labels}</div>
    </div>'''

def event_section(ev, ev_counts):
    n = sum(ev_counts.values())
    sql_n = ev_counts.get('SQL', 0)
    mql_n = ev_counts.get('MQL', 0)
    sql_rate = round(sql_n / n * 100) if n else 0
    safe_id = re.sub(r'[^a-zA-Z0-9]', '_', ev)

    # Get contacts for this event
    ev_contacts = [c for c in contacts if (c.get('Marketing_Sub_source__c') or 'Unknown') == ev]
    ev_opps = [c for c in ev_contacts if c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0]
    # Use sourced_opps (Opp.Marketing_Sub_source__c) for CW/pipeline — post-show new bookings only
    ev_sourced = [o for o in sourced_opps if (o.get('Marketing_Sub_source__c') or '') == ev]
    cw_amt = sum(o.get('Amount') or 0 for o in ev_sourced if o.get('StageName') == 'Closed Won')
    pipeline = sum(o.get('Amount') or 0 for o in ev_sourced if o.get('StageName') not in ('Closed Won', 'Closed Lost'))

    status_breakdown = event_status_breakdown(ev_counts, n)

    # Opp rows
    opp_rows = ''
    for c in sorted(ev_contacts, key=lambda x: -stage_labels_map.get((x.get('Opportunities') or {}).get('records', [{}])[0].get('StageName', '') if (x.get('Opportunities') or {}).get('totalSize', 0) > 0 else '', 0) if False else 0):
        if not (c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0):
            continue
        name = f"{c.get('FirstName') or ''} {c.get('LastName') or ''}".strip()
        acct = (c.get('Account') or {}).get('Name', '—')
        owner = (c.get('Owner') or {}).get('Name', '—')
        es = effective_status(c)
        for o in (c['Opportunities'].get('records') or []):
            stage = o.get('StageName', '')
            css = stage_css_map.get(stage, 's1')
            lbl = stage_labels_map.get(stage, stage)
            amt = o.get('Amount') or 0
            amt_col = '#00ff88' if stage == 'Closed Won' else ('#ff4444' if stage == 'Closed Lost' else '#ffd700')
            opp_rows += f'<tr><td>{name} {status_pill(es)}<div style="font-size:10px;color:#5a8a6a">{acct}</div></td><td style="color:{amt_col};font-weight:700">${amt:,.0f}</td><td><span class="stage-pill {css}">{lbl}</span></td><td style="font-size:11px;color:#5a8a6a">{owner}</td></tr>\n'

    # Contact rows
    contact_rows = ''
    for c in sorted(ev_contacts, key=lambda x: effective_status(x)):
        name = f"{c.get('FirstName') or ''} {c.get('LastName') or ''}".strip()
        acct = (c.get('Account') or {}).get('Name', '—')
        owner = (c.get('Owner') or {}).get('Name', '—')
        es = effective_status(c)
        contact_rows += f'<tr><td>{name}</td><td style="color:#5a8a6a">{acct}</td><td style="color:#5a8a6a;font-size:11px">{owner}</td><td>{status_pill(es)}</td></tr>\n'

    return f'''
<div class="event-card">
  <div class="event-header" onclick="toggle('{safe_id}')">
    <div class="event-title">
      <span class="event-name">{ev}</span>
      <span class="event-count">{n} contacts</span>
    </div>
    <div class="event-stats">
      {status_breakdown}
      <span class="conv-badge">{sql_rate}% → SQL</span>
      {f'<span class="cw-badge">${cw_amt:,.0f} CW</span>' if cw_amt > 0 else ''}
      {f'<span class="pipe-badge">${pipeline:,.0f} pipeline</span>' if pipeline > 0 else ''}
    </div>
    <span id="arrow-{safe_id}">▶</span>
  </div>
  <div id="body-{safe_id}" style="display:none">
    {f'''<div class="event-body">
      <div class="opp-table-wrap">
        <div class="opp-table-label">OPPORTUNITIES ({len(ev_opps)})</div>
        <table class="opp-table"><thead><tr><th>Contact / Account</th><th>Amount</th><th>Stage</th><th>Owner</th></tr></thead>
        <tbody>{opp_rows}</tbody></table>
      </div>''' if opp_rows else '<div class="event-body">'}
      <div class="contact-list">
        <div class="opp-table-label">ALL CONTACTS ({n})</div>
        <table class="opp-table"><thead><tr><th>Name</th><th>Account</th><th>Owner</th><th>Status</th></tr></thead>
        <tbody>{contact_rows}</tbody></table>
      </div>
    </div>
  </div>
</div>'''

# JS data
mql_labels_js = json.dumps([l for l,_,v in mql_status_funnel])
mql_values_js = json.dumps([v for _,_,v in mql_status_funnel])
mql_colors_js = json.dumps([c for _,c,_ in mql_status_funnel])
ev_labels_js  = json.dumps([e for e,_ in events_sorted])
stage_ev_totals_js = json.dumps([sum(by_event[e].values()) for e,_ in events_sorted])
stage_ev_ds = [{'label': s, 'color': col, 'data': [by_event[ev].get(s, 0) for ev,_ in events_sorted]}
         for s, col in status_defs if any(by_event[ev].get(s, 0) for ev,_ in events_sorted)]
stage_ev_ds_js = json.dumps(stage_ev_ds)
mql_ev_totals_js  = json.dumps([sum(mql_status_by_event[e].values()) for e,_ in events_sorted])
mql_ev_ds = [{'label': s, 'color': col, 'data': [mql_status_by_event[ev].get(s, 0) for ev,_ in events_sorted]}
         for s, col in mql_status_defs if any(mql_status_by_event[ev].get(s, 0) for ev,_ in events_sorted)]
mql_ev_ds_js = json.dumps(mql_ev_ds)
status_chips_html = ''
for s, col in status_defs:
    cnt = status_counts.get(s, 0)
    if cnt:
        bg_map = {'SQL': 'rgba(0,255,136,0.06)', 'MQL': 'rgba(0,229,255,0.06)', 'Disqualified': 'rgba(255,68,68,0.06)', 'Partner': 'rgba(191,90,242,0.08)', 'Potential Referral/Partner': 'rgba(168,85,247,0.08)', 'Client': 'rgba(255,215,0,0.08)', 'Unknown': 'rgba(80,80,80,0.06)'}
        status_chips_html += f'<div class="status-chip" style="border-color:{col}40;background:{bg_map.get(s,"")}"><div class="sc-label" style="color:{col}">{s}</div><div class="sc-val" style="color:{col}">{cnt}</div><div class="sc-pct">{round(cnt/total*100)}% of leads</div></div>\n'

date_str = datetime.now(timezone.utc).strftime('%B %d, %Y')
mql_legend_rows = ''.join(f'<div class="legend-row"><div class="legend-dot" style="background:{col}"></div><div class="legend-label">{lbl}</div><div class="legend-bar-wrap"><div class="legend-bar" style="width:{round(val/total*100)}%;background:{col}"></div></div><div class="legend-val">{val}</div><div class="legend-pct" style="color:{col}">{round(val/total*100)}%</div></div>\n' for lbl,col,val in mql_status_funnel)
ev_legend = ''.join(f'<div style="display:flex;align-items:center;gap:6px"><div style="width:10px;height:10px;border-radius:2px;background:{col}"></div><span style="font-size:11px;color:#c8f0dc;font-weight:600">{s}</span></div>' for s,col in mql_status_defs if mql_status_counts.get(s,0))
stage_ev_legend = ''.join(f'<div style="display:flex;align-items:center;gap:6px"><div style="width:10px;height:10px;border-radius:2px;background:{col}"></div><span style="font-size:11px;color:#c8f0dc;font-weight:600">{s}</span></div>' for s,col in status_defs if status_counts.get(s,0))
events_html = ''.join(event_section(ev, dict(d)) for ev, d in events_sorted)
status_graph_max = max((cnt for _, _, cnt in funnel), default=1)
status_graph_rows = ''.join(
    f'''<div class="status-graph-row">
      <div class="status-graph-label"><span class="legend-dot" style="background:{col}"></span>{lbl}</div>
      <div class="status-graph-track"><div class="status-graph-fill" style="width:{(val/status_graph_max*100 if status_graph_max else 0):.1f}%;background:{col};box-shadow:0 0 10px {col}66"></div></div>
      <div class="status-graph-value">{val}</div>
      <div class="status-graph-pct" style="color:{col}">{round(val/total*100)}%</div>
    </div>'''
    for lbl, col, val in funnel
)

CSS = """
  :root{--green:#00ff88;--cyan:#00e5ff;--bg:#020408;--surface:#060d14;--border:#0a2a1a;--text:#c8f0dc;--muted:#2a5a3a}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Segoe UI',system-ui,monospace;background:var(--bg);color:var(--text)}
  body::before{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(0,255,136,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,.08) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0}
  .scanline{position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.03) 2px,rgba(0,0,0,.03) 4px);pointer-events:none;z-index:0}
  .container{max-width:1100px;margin:0 auto;padding:24px 32px;position:relative;z-index:1}
  .header{border-bottom:1px solid var(--border);padding-bottom:16px;margin-bottom:20px}
  .header-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
  .logo{display:flex;align-items:center;gap:10px}
  .logo-dot{width:10px;height:10px;background:var(--green);border-radius:50%;box-shadow:0 0 12px var(--green);animation:pulse 2s infinite}
  .logo-text{font-size:11px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:var(--green)}
  .header-date{font-size:11px;color:var(--muted)}
  h1{font-size:32px;font-weight:900;color:#fff;letter-spacing:-1px;margin-bottom:4px}
  h1 span{color:var(--green);text-shadow:0 0 30px var(--green)}
  .header-sub{font-size:13px;color:var(--muted)}
  .summary-bar{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:20px}
  .sum-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center}
  .sum-item.hl{border-color:var(--green);background:rgba(0,255,136,.04)}
  .sum-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:4px}
  .sum-val{font-size:20px;font-weight:900;color:#fff}
  .sum-val.green{color:var(--green)}.sum-val.cyan{color:var(--cyan)}.sum-val.yellow{color:#ffd700}
  .note{font-size:10px;color:#3a7a5a;margin-top:3px}
  .status-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
  .status-chip{background:var(--surface);border:1px solid;border-radius:10px;padding:10px 16px;min-width:120px;text-align:center}
  .sc-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px}
  .sc-val{font-size:28px;font-weight:900;line-height:1}
  .sc-pct{font-size:10px;color:var(--muted);margin-top:3px}
  .section-title{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:10px;margin-top:20px}
  .chart-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px 24px;margin-bottom:20px}
  .status-graph-card{background:var(--surface);border:1px solid rgba(0,229,255,.25);border-radius:10px;padding:18px 20px;margin-bottom:20px}
  .status-graph-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:14px}
  .status-graph-title{font-size:12px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:var(--cyan)}
  .status-graph-note{font-size:11px;color:var(--muted)}
  .status-graph-row{display:grid;grid-template-columns:minmax(150px,210px) 1fr 54px 44px;gap:12px;align-items:center;margin-bottom:10px}
  .status-graph-row:last-child{margin-bottom:0}
  .status-graph-label{display:flex;align-items:center;gap:8px;font-size:12px;font-weight:700;color:#c8f0dc;min-width:0}
  .status-graph-track{height:13px;background:rgba(0,255,136,.06);border-radius:7px;overflow:hidden;border:1px solid rgba(255,255,255,.03)}
  .status-graph-fill{height:100%;border-radius:7px;min-width:2px}
  .status-graph-value{font-size:13px;font-weight:900;color:#fff;text-align:right}
  .status-graph-pct{font-size:12px;font-weight:800;text-align:right}
  .chart-row{display:flex;gap:32px;align-items:center;flex-wrap:wrap}
  .chart-inner{position:relative;flex-shrink:0}
  .donut-center{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center}
  .donut-total{font-size:36px;font-weight:900;color:#fff;line-height:1}
  .donut-label{font-size:11px;color:var(--muted);letter-spacing:1px;text-transform:uppercase;margin-top:3px}
  .chart-legend{flex:1;min-width:200px}
  .legend-row{display:flex;align-items:center;gap:8px;margin-bottom:10px}
  .legend-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
  .legend-label{font-size:12px;color:#c8f0dc;width:110px;flex-shrink:0}
  .legend-bar-wrap{flex:1;height:6px;background:rgba(0,255,136,.06);border-radius:3px;overflow:hidden}
  .legend-bar{height:100%;border-radius:3px}
  .legend-val{font-size:13px;font-weight:700;color:#fff;width:28px;text-align:right;flex-shrink:0}
  .legend-pct{font-size:11px;font-weight:700;width:36px;text-align:right;flex-shrink:0}
  .event-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:8px;overflow:hidden}
  .event-header{display:flex;align-items:center;justify-content:space-between;padding:12px 18px;cursor:pointer;gap:12px}
  .event-header:hover{background:rgba(0,255,136,.02)}
  .event-title{display:flex;align-items:center;gap:12px;flex-shrink:0}
  .event-name{font-size:15px;font-weight:800;color:#fff}
  .event-count{font-size:11px;color:var(--muted);background:rgba(0,255,136,.06);border:1px solid var(--border);padding:2px 8px;border-radius:10px}
  .event-stats{display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex:1;justify-content:flex-end}
  .event-status-breakdown{min-width:260px;max-width:390px;flex:1 1 300px}
  .event-status-track{display:flex;height:9px;background:rgba(0,255,136,.06);border:1px solid rgba(255,255,255,.03);border-radius:5px;overflow:hidden;margin-bottom:5px}
  .event-status-segment{height:100%;min-width:2px}
  .event-status-labels{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}
  .event-status-label{font-size:9px;font-weight:800;padding:1px 5px;border:1px solid;border-radius:8px;white-space:nowrap}
  .conv-badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;background:rgba(0,229,255,.1);color:var(--cyan);border:1px solid rgba(0,229,255,.2);white-space:nowrap}
  .cw-badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;background:rgba(0,255,136,.1);color:var(--green);border:1px solid rgba(0,255,136,.2);white-space:nowrap}
  .pipe-badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;background:rgba(255,215,0,.08);color:#ffd700;border:1px solid rgba(255,215,0,.2);white-space:nowrap}
  .event-body{border-top:1px solid var(--border)}
  .opp-table-wrap{padding:14px 18px;border-bottom:1px solid var(--border)}
  .contact-list{padding:14px 18px}
  .opp-table-label{font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
  .opp-table{width:100%;border-collapse:collapse}
  .opp-table th{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);padding:6px 10px;text-align:left}
  .opp-table td{font-size:12px;padding:5px 10px;border-bottom:1px solid rgba(0,255,136,.04);color:#8ab89a}
  .opp-table tr:last-child td{border-bottom:none}
  .stage-pill{font-size:9px;font-weight:700;padding:2px 7px;border-radius:8px;text-transform:uppercase;letter-spacing:.5px}
  .won{background:rgba(0,255,136,.2);color:var(--green);border:1px solid rgba(0,255,136,.4)}
  .lost{background:rgba(100,116,139,.15);color:#64748b;border:1px solid rgba(100,116,139,.2)}
  .s6{background:rgba(0,255,136,.1);color:var(--green);border:1px solid rgba(0,255,136,.25)}
  .s5{background:rgba(255,107,53,.1);color:#ff6b35;border:1px solid rgba(255,107,53,.2)}
  .s4{background:rgba(255,215,0,.08);color:#ffd700;border:1px solid rgba(255,215,0,.2)}
  .s3{background:rgba(191,90,242,.1);color:#bf5af2;border:1px solid rgba(191,90,242,.2)}
  .s2{background:rgba(0,229,255,.08);color:#00b4cc;border:1px solid rgba(0,229,255,.15)}
  .s1{background:rgba(100,116,139,.15);color:#64748b;border:1px solid rgba(100,116,139,.2)}
  .footer{text-align:center;padding:20px;font-size:10px;color:#1a3a2a;letter-spacing:1px;border-top:1px solid var(--border);margin-top:8px}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
"""

HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tradeshow MQL Dashboard — Rev.io 2026</title>
<style>{CSS}</style>
</head>
<body>
<div class="scanline"></div>
<div class="container">
  <div class="header">
    <div class="header-top">
      <div class="logo"><div class="logo-dot"></div><div class="logo-text">Rev.io · Sales Intelligence</div></div>
      <div class="header-date">GENERATED {date_str.upper()} · LIVE SALESFORCE DATA</div>
    </div>
    <h1>Tradeshow <span>MQL Dashboard</span></h1>
    <div class="header-sub">2026 YTD · {total} contacts added or updated to MQL · {len(by_event)} events · SQL = 2026 MQL → SQL status change</div>
  </div>

  <div class="summary-bar">
    <div class="sum-item"><div class="sum-label">Total Contacts</div><div class="sum-val">{total}</div></div>
    <div class="sum-item"><div class="sum-label">Events</div><div class="sum-val">{len(by_event)}</div></div>
    <div class="sum-item hl"><div class="sum-label">MQL → SQL Rate</div><div class="sum-val green">{conv_rate}%</div><div class="note">2026 status history</div></div>
    <div class="sum-item"><div class="sum-label">SQLs</div><div class="sum-val cyan">{total_sql}</div><div class="note">MQL → SQL in 2026</div></div>
    <div class="sum-item"><div class="sum-label">Active Pipeline</div><div class="sum-val yellow">${total_pipeline:,.0f}</div></div>
    <div class="sum-item hl"><div class="sum-label">Closed Won</div><div class="sum-val green">${total_cw:,.0f}</div></div>
  </div>

  <div class="status-row">{status_chips_html}</div>

  <div class="section-title">Contact Stage Breakdown</div>
  <div class="status-graph-card">
    <div class="status-graph-head">
      <div>
        <div class="status-graph-title">Contact Stage Mix by Contact Count</div>
        <div class="status-graph-note">Bars are scaled to the largest status segment; percentages are of all {total} contacts added or updated to MQL in 2026.</div>
      </div>
      <div class="status-graph-note">SQL = MQL → SQL in 2026</div>
    </div>
    {status_graph_rows}
  </div>

  <div class="section-title">MQL Status Breakdown</div>
  <div class="chart-card">
    <div class="chart-row">
      <div class="chart-inner">
        <canvas id="mqlStatusChart" width="280" height="280"></canvas>
        <div class="donut-center"><div class="donut-total">{total}</div><div class="donut-label">2026 MQLs</div></div>
      </div>
      <div class="chart-legend">
        <div style="font-size:10px;color:#3a7a5a;margin-bottom:12px;font-style:italic">Based on the Tradeshow Status field for contacts added or updated to MQL in 2026</div>
        {mql_legend_rows}
      </div>
    </div>
  </div>

  <div class="section-title">Contact Stage by Show</div>
  <div class="chart-card" style="padding:20px 24px">
    <div style="font-size:10px;color:#3a7a5a;margin-bottom:12px;font-style:italic">Uses Contact Status for the 2026 MQL cohort. SQL only counts when the contact changed from MQL to SQL in 2026.</div>
    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:14px">{stage_ev_legend}</div>
    <canvas id="contactStageEventChart"></canvas>
  </div>

  <div class="section-title">MQL Status by Event</div>
  <div class="chart-card" style="padding:20px 24px">
    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:14px">{ev_legend}</div>
    <canvas id="mqlEventChart"></canvas>
  </div>

  <div class="section-title">By Event — {len(by_event)} events ({total} contacts)</div>
  {events_html}

  <div class="footer">REV.IO SALES INTELLIGENCE · ROBIN 🦸🏻‍♂️ · CONFIDENTIAL · 2026 MQL COHORT · SQL = MQL → SQL STATUS HISTORY</div>
</div>
<script>
(function(){{
  var ctx=document.getElementById('mqlStatusChart').getContext('2d');
  var labels={mql_labels_js};var values={mql_values_js};var colors={mql_colors_js};
  var cx=140,cy=140,outerR=125,innerR=80,a=-Math.PI/2;
  values.forEach(function(v,i){{
    var s=(v/values.reduce(function(a,b){{return a+b}},0))*2*Math.PI;
    ctx.beginPath();ctx.moveTo(cx,cy);ctx.arc(cx,cy,outerR,a,a+s);ctx.closePath();ctx.fillStyle=colors[i];ctx.fill();a+=s;
  }});
  ctx.beginPath();ctx.arc(cx,cy,innerR,0,2*Math.PI);ctx.fillStyle='#060d14';ctx.fill();
  ctx.beginPath();ctx.arc(cx,cy,innerR,0,2*Math.PI);ctx.strokeStyle='rgba(0,255,136,0.15)';ctx.lineWidth=1;ctx.stroke();
}})();

function drawStackedEventChart(canvasId, labels, totals, datasets){{
  var canvas=document.getElementById(canvasId);var ctx=canvas.getContext('2d');
  var n=labels.length,barH=28,gap=10,labelW=155;
  var pad={{t:8,r:60,b:8,l:labelW}},chartW=700;
  var chartH=n*(barH+gap)+pad.t+pad.b;
  canvas.width=chartW;canvas.height=chartH;canvas.style.width='100%';canvas.style.maxWidth=chartW+'px';
  var maxVal=Math.max.apply(null,totals),availW=chartW-pad.l-pad.r;
  ctx.font='600 11px Segoe UI,system-ui';ctx.textBaseline='middle';
  labels.forEach(function(label,i){{
    var y=pad.t+i*(barH+gap);
    ctx.fillStyle='#c8f0dc';ctx.textAlign='right';ctx.fillText(label,labelW-8,y+barH/2);
    var x=pad.l;
    datasets.forEach(function(ds){{
      var val=ds.data[i];if(!val)return;
      var w=(val/maxVal)*availW;
      ctx.fillStyle=ds.color;ctx.beginPath();ctx.roundRect(x,y,w,barH,3);ctx.fill();x+=w;
    }});
    var tw=(totals[i]/maxVal)*availW;
    ctx.fillStyle='#888';ctx.textAlign='left';ctx.font='600 10px Segoe UI';
    ctx.fillText(totals[i],pad.l+tw+5,y+barH/2);ctx.font='600 11px Segoe UI,system-ui';
  }});
}}

drawStackedEventChart('contactStageEventChart', {ev_labels_js}, {stage_ev_totals_js}, {stage_ev_ds_js});
drawStackedEventChart('mqlEventChart', {ev_labels_js}, {mql_ev_totals_js}, {mql_ev_ds_js});

function toggle(id){{
  var b=document.getElementById('body-'+id);
  var a=document.getElementById('arrow-'+id);
  if(b.style.display==='none'){{b.style.display='block';a.textContent='▼';}}
  else{{b.style.display='none';a.textContent='▶';}}
}}
</script>
</body>
</html>"""

with open(BASE_DIR / 'tradeshow-mql.html', 'w') as f:
    f.write(HTML)
print(f"Done! Status counts: {dict(status_counts)}")
print(f"Conv rate: {conv_rate}% | Pipeline: ${total_pipeline:,.0f} | CW: ${total_cw:,.0f}")
