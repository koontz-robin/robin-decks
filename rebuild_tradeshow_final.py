import json, re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / 'tradeshow_contacts.json') as f:
    contacts = json.load(f)

def effective_status(c):
    """Opp creation = SQL conversion"""
    has_opp = c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0
    sf_status = c.get('Contact_Status__c') or 'Unknown'
    if has_opp and sf_status not in ('SQL', 'Disqualified'):
        return 'SQL'
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

# Global counts
status_counts = defaultdict(int)
for c in contacts:
    status_counts[effective_status(c)] += 1

total = len(contacts)
with_opps = [c for c in contacts if c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0]
total_with_opps = len(with_opps)

# Use tradeshow_opps.json (Opp.Marketing_Sub_source__c query) for CW/pipeline
# This reflects new post-show bookings only, not pre-existing contact-linked deals
with open(BASE_DIR / 'tradeshow_opps.json') as _f:
    sourced_opps = json.load(_f)
total_cw = sum(o.get('Amount') or 0 for o in sourced_opps if o.get('StageName') == 'Closed Won')
total_pipeline = sum(o.get('Amount') or 0 for o in sourced_opps if o.get('StageName') not in ('Closed Won', 'Closed Lost'))
conv_rate = round(total_with_opps / total * 100, 1) if total else 0

# Donut data
funnel = [(s, c, status_counts.get(s, 0)) for s, c in status_defs if status_counts.get(s, 0) > 0]

# By-event data
by_event = defaultdict(lambda: defaultdict(int))
for c in contacts:
    ev = c.get('Marketing_Sub_source__c') or 'Unknown'
    by_event[ev][effective_status(c)] += 1
events_sorted = sorted(by_event.items(), key=lambda x: -sum(x[1].values()))

# Rep data
rep_data = defaultdict(lambda: {'total': 0, 'sql': 0, 'mql': 0, 'disq': 0, 'unknown': 0,
                                  'with_opp': 0, 'cw_amt': 0, 'pipeline': 0})
for c in contacts:
    owner = (c.get('Owner') or {}).get('Name', 'Unknown')
    es = effective_status(c)
    rep_data[owner]['total'] += 1
    key_map = {'SQL': 'sql', 'MQL': 'mql', 'Disqualified': 'disq'}
    rep_data[owner][key_map.get(es, 'unknown')] += 1
    has_opp = c.get('Opportunities') and c['Opportunities'].get('totalSize', 0) > 0
    if has_opp:
        rep_data[owner]['with_opp'] += 1
        for o in (c['Opportunities'].get('records') or []):
            amt = o.get('Amount') or 0
            stage = o.get('StageName', '')
            if stage == 'Closed Won':
                rep_data[owner]['cw_amt'] += amt
            elif stage != 'Closed Lost':
                rep_data[owner]['pipeline'] += amt

reps = sorted(rep_data.items(), key=lambda x: -x[1]['total'])

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

def status_pill(s):
    colors = {'SQL': '#00ff88', 'MQL': '#00e5ff', 'Disqualified': '#ff4444', 'Unknown': '#555'}
    bg_colors = {'SQL': 'rgba(0,255,136,0.12)', 'MQL': 'rgba(0,229,255,0.1)', 'Disqualified': 'rgba(255,68,68,0.12)', 'Unknown': 'rgba(80,80,80,0.1)'}
    col = colors.get(s, '#888')
    bg = bg_colors.get(s, 'rgba(80,80,80,0.1)')
    return f'<span style="font-size:9px;font-weight:700;padding:1px 6px;border-radius:8px;background:{bg};color:{col}">{s}</span>'

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

    # Status badges
    badges = ''
    for s, col in status_defs:
        cnt = ev_counts.get(s, 0)
        if cnt:
            bg_map = {'SQL': 'rgba(0,255,136,0.12)', 'MQL': 'rgba(0,229,255,0.1)', 'Disqualified': 'rgba(255,68,68,0.12)', 'Unknown': 'rgba(80,80,80,0.1)'}
            badges += f'<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;background:{bg_map.get(s,"rgba(80,80,80,0.1)")};color:{col};margin-right:4px">{s}: {cnt}</span>'

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
      {badges}
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

# Rep table rows
def rep_rows_html():
    rows = ''
    for rep, d in reps:
        conv = round(d['with_opp'] / d['total'] * 100) if d['total'] else 0
        conv_color = '#00ff88' if conv >= 30 else ('#ffd700' if conv >= 15 else '#ff4444')
        t = d['total']
        bar = f'''<div style="display:flex;height:8px;border-radius:4px;overflow:hidden;width:120px;background:#0a0a0a">
          <div style="width:{d['sql']/t*100:.0f}%;background:#00ff88"></div>
          <div style="width:{d['mql']/t*100:.0f}%;background:#00e5ff"></div>
          <div style="width:{d['disq']/t*100:.0f}%;background:#ff4444"></div>
          <div style="width:{d['unknown']/t*100:.0f}%;background:#333"></div>
        </div>
        <div style="font-size:9px;color:#3a6a4a;margin-top:2px">
          <span style="color:#00ff88">{d['sql']} SQL</span> · <span style="color:#00e5ff">{d['mql']} MQL</span>{f" · <span style='color:#ff4444'>{d['disq']} DQ</span>" if d['disq'] else ""}
        </div>'''
        rows += f'''<tr>
          <td style="font-weight:600;color:#c8f0dc">{rep}</td>
          <td style="text-align:center;font-weight:700">{d['total']}</td>
          <td>{bar}</td>
          <td style="text-align:center;color:{conv_color};font-weight:700">{conv}%</td>
          <td style="text-align:center;color:#00e5ff">{d['with_opp']}</td>
          <td style="text-align:center;color:#ffd700">{'$'+f"{d['pipeline']:,.0f}" if d['pipeline'] else '—'}</td>
          <td style="text-align:center;color:#00ff88;font-weight:700">{'$'+f"{d['cw_amt']:,.0f}" if d['cw_amt'] else '—'}</td>
        </tr>\n'''
    return rows

# JS data
labels_js     = json.dumps([l for l,_,v in funnel])
values_js     = json.dumps([v for _,_,v in funnel])
colors_js     = json.dumps([c for _,c,_ in funnel])
ev_labels_js  = json.dumps([e for e,_ in events_sorted])
ev_totals_js  = json.dumps([sum(d.values()) for _,d in events_sorted])
ev_ds = [{'label': s, 'color': col, 'data': [by_event[ev].get(s, 0) for ev,_ in events_sorted]}
         for s, col in status_defs if any(by_event[ev].get(s, 0) for ev,_ in events_sorted)]
ev_ds_js      = json.dumps(ev_ds)
rep_names_js  = json.dumps([r for r,_ in reps])
rep_totals_js = json.dumps([d['total'] for _,d in reps])
rep_sqls_js   = json.dumps([d['sql'] for _,d in reps])

status_chips_html = ''
for s, col in status_defs:
    cnt = status_counts.get(s, 0)
    if cnt:
        bg_map = {'SQL': 'rgba(0,255,136,0.06)', 'MQL': 'rgba(0,229,255,0.06)', 'Disqualified': 'rgba(255,68,68,0.06)', 'Partner': 'rgba(191,90,242,0.08)', 'Potential Referral/Partner': 'rgba(168,85,247,0.08)', 'Client': 'rgba(255,215,0,0.08)', 'Unknown': 'rgba(80,80,80,0.06)'}
        status_chips_html += f'<div class="status-chip" style="border-color:{col}40;background:{bg_map.get(s,"")}"><div class="sc-label" style="color:{col}">{s}</div><div class="sc-val" style="color:{col}">{cnt}</div><div class="sc-pct">{round(cnt/total*100)}% of leads</div></div>\n'

date_str = datetime.now(timezone.utc).strftime('%B %d, %Y')
legend_rows = ''.join(f'<div class="legend-row"><div class="legend-dot" style="background:{col}"></div><div class="legend-label">{lbl}</div><div class="legend-bar-wrap"><div class="legend-bar" style="width:{round(val/total*100)}%;background:{col}"></div></div><div class="legend-val">{val}</div><div class="legend-pct" style="color:{col}">{round(val/total*100)}%</div></div>\n' for lbl,col,val in funnel)
ev_legend = ''.join(f'<div style="display:flex;align-items:center;gap:6px"><div style="width:10px;height:10px;border-radius:2px;background:{col}"></div><span style="font-size:11px;color:#c8f0dc;font-weight:600">{s}</span></div>' for s,col in status_defs if status_counts.get(s,0))
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
  .owner-table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:20px}
  .owner-table{width:100%;border-collapse:collapse}
  .owner-table th{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);padding:8px 14px;text-align:left;background:#030a06}
  .owner-table th:not(:first-child){text-align:center}
  .owner-table td{font-size:12px;padding:7px 14px;border-bottom:1px solid rgba(0,255,136,.04);color:#8ab89a}
  .owner-table tr:last-child td{border-bottom:none}
  .owner-table tr:hover td{background:rgba(0,255,136,.02)}
  .event-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:8px;overflow:hidden}
  .event-header{display:flex;align-items:center;justify-content:space-between;padding:12px 18px;cursor:pointer;gap:12px}
  .event-header:hover{background:rgba(0,255,136,.02)}
  .event-title{display:flex;align-items:center;gap:12px;flex-shrink:0}
  .event-name{font-size:15px;font-weight:800;color:#fff}
  .event-count{font-size:11px;color:var(--muted);background:rgba(0,255,136,.06);border:1px solid var(--border);padding:2px 8px;border-radius:10px}
  .event-stats{display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex:1;justify-content:flex-end}
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
    <div class="header-sub">2026 YTD · {total} contacts · {len(by_event)} events · Opp creation = SQL conversion</div>
  </div>

  <div class="summary-bar">
    <div class="sum-item"><div class="sum-label">Total Contacts</div><div class="sum-val">{total}</div></div>
    <div class="sum-item"><div class="sum-label">Events</div><div class="sum-val">{len(by_event)}</div></div>
    <div class="sum-item hl"><div class="sum-label">MQL → SQL Rate</div><div class="sum-val green">{conv_rate}%</div><div class="note">opp created = SQL</div></div>
    <div class="sum-item"><div class="sum-label">SQLs (w/ Opp)</div><div class="sum-val cyan">{total_with_opps}</div></div>
    <div class="sum-item"><div class="sum-label">Active Pipeline</div><div class="sum-val yellow">${total_pipeline:,.0f}</div></div>
    <div class="sum-item hl"><div class="sum-label">Closed Won</div><div class="sum-val green">${total_cw:,.0f}</div></div>
  </div>

  <div class="status-row">{status_chips_html}</div>

  <div class="section-title">Tradeshow MQL Status Breakdown</div>
  <div class="status-graph-card">
    <div class="status-graph-head">
      <div>
        <div class="status-graph-title">Status Mix by Contact Count</div>
        <div class="status-graph-note">Bars are scaled to the largest status segment; percentages are of all {total} tradeshow contacts.</div>
      </div>
      <div class="status-graph-note">Opp created = SQL</div>
    </div>
    {status_graph_rows}
  </div>

  <div class="section-title">Contact Status Breakdown</div>
  <div class="chart-card">
    <div class="chart-row">
      <div class="chart-inner">
        <canvas id="statusChart" width="280" height="280"></canvas>
        <div class="donut-center"><div class="donut-total">{total}</div><div class="donut-label">contacts</div></div>
      </div>
      <div class="chart-legend">
        <div style="font-size:10px;color:#3a7a5a;margin-bottom:12px;font-style:italic">✦ Opp created = auto-promoted to SQL</div>
        {legend_rows}
      </div>
    </div>
  </div>

  <div class="section-title">Contact Status by Event</div>
  <div class="chart-card" style="padding:20px 24px">
    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:14px">{ev_legend}</div>
    <canvas id="eventChart"></canvas>
  </div>

  <div class="section-title">MQL → SQL Conversion by Rep</div>
  <div class="chart-card" style="padding:20px 24px">
    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:6px"><div style="width:10px;height:10px;border-radius:2px;background:#00ff88"></div><span style="font-size:11px;color:#c8f0dc;font-weight:600">SQL (opp created)</span></div>
      <div style="display:flex;align-items:center;gap:6px"><div style="width:10px;height:10px;border-radius:2px;background:rgba(0,229,255,0.25)"></div><span style="font-size:11px;color:#c8f0dc;font-weight:600">Total leads</span></div>
    </div>
    <canvas id="repChart"></canvas>
    <div style="margin-top:20px">
      <div class="owner-table-wrap" style="margin-bottom:0">
        <table class="owner-table">
          <thead><tr><th>Rep</th><th>Leads</th><th>Status Mix</th><th>SQL %</th><th>Opps</th><th>Pipeline</th><th>CW</th></tr></thead>
          <tbody>{rep_rows_html()}</tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="section-title">By Event — {len(by_event)} events ({total} contacts)</div>
  {events_html}

  <div class="footer">REV.IO SALES INTELLIGENCE · ROBIN 🦸🏻‍♂️ · CONFIDENTIAL · Opp creation = SQL conversion</div>
</div>
<script>
(function(){{
  var ctx=document.getElementById('statusChart').getContext('2d');
  var labels={labels_js};var values={values_js};var colors={colors_js};
  var cx=140,cy=140,outerR=125,innerR=80,a=-Math.PI/2;
  values.forEach(function(v,i){{
    var s=(v/values.reduce(function(a,b){{return a+b}},0))*2*Math.PI;
    ctx.beginPath();ctx.moveTo(cx,cy);ctx.arc(cx,cy,outerR,a,a+s);ctx.closePath();ctx.fillStyle=colors[i];ctx.fill();a+=s;
  }});
  ctx.beginPath();ctx.arc(cx,cy,innerR,0,2*Math.PI);ctx.fillStyle='#060d14';ctx.fill();
  ctx.beginPath();ctx.arc(cx,cy,innerR,0,2*Math.PI);ctx.strokeStyle='rgba(0,255,136,0.15)';ctx.lineWidth=1;ctx.stroke();
}})();

(function(){{
  var labels={ev_labels_js};var totals={ev_totals_js};var datasets={ev_ds_js};
  var canvas=document.getElementById('eventChart');var ctx=canvas.getContext('2d');
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
}})();

(function(){{
  var repNames={rep_names_js};var totals={rep_totals_js};var sqls={rep_sqls_js};
  var canvas=document.getElementById('repChart');var ctx=canvas.getContext('2d');
  var n=repNames.length,barH=20,gap=8,groupGap=6,labelW=140;
  var pad={{t:8,r:70,b:8,l:labelW}},chartW=700;
  var rowH=barH*2+groupGap,chartH=n*(rowH+gap)+pad.t+pad.b;
  canvas.width=chartW;canvas.height=chartH;canvas.style.width='100%';canvas.style.maxWidth=chartW+'px';
  var maxVal=Math.max.apply(null,totals),availW=chartW-pad.l-pad.r;
  ctx.font='600 11px Segoe UI,system-ui';ctx.textBaseline='middle';
  repNames.forEach(function(rep,i){{
    var baseY=pad.t+i*(rowH+gap);
    ctx.fillStyle='#c8f0dc';ctx.textAlign='right';ctx.fillText(rep,labelW-8,baseY+rowH/2);
    var tw=(totals[i]/maxVal)*availW;
    ctx.fillStyle='rgba(0,229,255,0.2)';ctx.beginPath();ctx.roundRect(pad.l,baseY,tw,barH,3);ctx.fill();
    ctx.fillStyle='#888';ctx.textAlign='left';ctx.font='600 10px Segoe UI';
    ctx.fillText(totals[i]+' leads',pad.l+tw+5,baseY+barH/2);
    var sw=(sqls[i]/maxVal)*availW;
    if(sw>0){{
      ctx.fillStyle='#00ff88';ctx.beginPath();ctx.roundRect(pad.l,baseY+barH+groupGap,sw,barH,3);ctx.fill();
      ctx.fillStyle='#fff';ctx.font='700 10px Segoe UI';
      ctx.fillText(sqls[i]+' SQL ('+Math.round(sqls[i]/totals[i]*100)+'%)',pad.l+sw+5,baseY+barH+groupGap+barH/2);
    }}else{{
      ctx.fillStyle='#555';ctx.font='600 10px Segoe UI';ctx.fillText('0 SQL',pad.l+5,baseY+barH+groupGap+barH/2);
    }}
    ctx.font='600 11px Segoe UI,system-ui';
  }});
}})();

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
