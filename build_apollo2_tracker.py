#!/usr/bin/env python3
"""Rebuild Q2 Apollo 2 Re-engagement Tracker from Salesforce."""
import requests, json
from collections import defaultdict
from datetime import datetime, timezone

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

r = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={"grant_type":"client_credentials","client_id":SF_CLIENT_ID,"client_secret":SF_CLIENT_SECRET})
at, iu = r.json()["access_token"], r.json()["instance_url"]

with open('/home/openclaw/.openclaw/workspace/apollo2_accounts.json') as f:
    accts = json.load(f)

# Fetch all PSA opps for these accounts (any time, not just Q1)
sf_ids = [a['sf_id'] for a in accts if a.get('sf_id')]

# Query in batches of 50 to avoid SOQL length limits
opp_by_acct = {}
batch_size = 50
for i in range(0, len(sf_ids), batch_size):
    batch = sf_ids[i:i+batch_size]
    id_list = "','".join(batch)
    soql = f"SELECT AccountId, Id, StageName, CloseDate, Amount, Loss_Reason__c, CreatedDate FROM Opportunity WHERE AccountId IN ('{id_list}') AND Product_Type__c IN ('PSA 2.0','PSA') AND IsDeleted = false ORDER BY CreatedDate DESC"
    qresp = requests.get(f"{iu}/services/data/v59.0/query", headers={"Authorization": f"Bearer {at}"}, params={"q": soql})
    rdata = qresp.json()
    records = rdata.get('records', []) if isinstance(rdata, dict) else []
    for o in records:
        aid = o['AccountId']
        if aid not in opp_by_acct:
            opp_by_acct[aid] = []
        opp_by_acct[aid].append(o)

CLOSED_LOST_STAGES = {'Closed Lost','10 - Closed Lost','Closed - No Decision','Closed Lost - No Decision'}
ACTIVE_STAGES = {'1- Discovery Scheduled','2 - Discovery Completed','3 - Initial Product Demo','4 - Proposal Sent','5 - Product / Contract Validated','6 - Verbal Commit'}

def get_status(opps):
    """Get best current status across all opps."""
    if not opps: return 'not_contacted', None, None, None
    # Sort by created desc
    sorted_opps = sorted(opps, key=lambda x: x.get('CreatedDate',''), reverse=True)
    # Check for won
    won = [o for o in sorted_opps if o['StageName'] == 'Closed Won']
    if won:
        return 'won', won[0]['StageName'], won[0].get('CloseDate'), won[0].get('Loss_Reason__c')
    # Check for active
    active = [o for o in sorted_opps if o['StageName'] in ACTIVE_STAGES]
    if active:
        return 'active', active[0]['StageName'], active[0].get('CloseDate'), None
    # Check for lost
    lost = [o for o in sorted_opps if o['StageName'] in CLOSED_LOST_STAGES]
    if lost:
        return 'lost', lost[0]['StageName'], lost[0].get('CloseDate'), lost[0].get('Loss_Reason__c')
    # Has opp but not in known stage
    o = sorted_opps[0]
    return 'active', o['StageName'], o.get('CloseDate'), None

# Build rows
rows = []
for a in accts:
    opps = opp_by_acct.get(a['sf_id'], [])
    status_key, stage, close_date, loss_reason = get_status(opps)
    # Most recent opp amount
    amount = 0
    if opps:
        sorted_opps = sorted(opps, key=lambda x: x.get('CreatedDate',''), reverse=True)
        amount = sorted_opps[0].get('Amount') or a['mrr']
    rows.append({
        'name': a['name'],
        'mrr': a['mrr'],
        'owner': a['owner'],
        'features': a.get('features', []),
        'sf_id': a['sf_id'],
        'status_key': status_key,
        'stage': stage or '—',
        'close_date': close_date or '',
        'loss_reason': loss_reason or '',
        'amount': amount or a['mrr'],
    })

# Sort: won first, then active, then lost, then not_contacted; within each by MRR desc
STATUS_ORDER = {'won':0,'active':1,'lost':2,'not_contacted':3}
rows.sort(key=lambda x: (STATUS_ORDER[x['status_key']], -x['mrr']))

# Stats
won_count = sum(1 for r in rows if r['status_key']=='won')
active_count = sum(1 for r in rows if r['status_key']=='active')
lost_count = sum(1 for r in rows if r['status_key']=='lost')
contacted_count = won_count + active_count + lost_count
not_contacted = sum(1 for r in rows if r['status_key']=='not_contacted')
won_mrr = sum(r['mrr'] for r in rows if r['status_key']=='won')
active_mrr = sum(r['mrr'] for r in rows if r['status_key']=='active')
total_mrr = sum(r['mrr'] for r in rows)

# Q2 targets
TARGET_CONTACTED = 73
TARGET_OPPS = 45
TARGET_CLOSED = 12
TARGET_MRR = 12000

opps_created = won_count + active_count + lost_count  # all accounts with any opp
pct_contacted = min(round(contacted_count / TARGET_CONTACTED * 100, 1), 100)
pct_opps = min(round(opps_created / TARGET_OPPS * 100, 1), 100)
pct_closed = min(round(won_count / TARGET_CLOSED * 100, 1), 100)
pct_mrr = min(round(won_mrr / TARGET_MRR * 100, 1), 100)

def funnel_card(label, val, target, pct, color, fmt='n'):
    val_str = f'${val:,}' if fmt == '$' else str(val)
    tgt_str = f'${target:,}' if fmt == '$' else str(target)
    return f'''<div class="funnel-card" style="border-top:3px solid {color}">
  <div class="f-label">{label}</div>
  <div class="f-val" style="color:{color}">{val_str}</div>
  <div style="height:14px;background:rgba(255,255,255,0.06);border-radius:6px;margin-top:10px;overflow:hidden"><div style="height:100%;width:{pct}%;background:{color};border-radius:6px;box-shadow:0 0 8px {color}88"></div></div>
  <div style="font-size:10px;color:#475569;margin-top:5px">{val_str} of {tgt_str} target &nbsp;·&nbsp; <strong style="color:{color}">{pct}%</strong></div>
</div>'''

funnel_html = (
    funnel_card('Accounts Touched', contacted_count, TARGET_CONTACTED, pct_contacted, '#f5a623') +
    funnel_card('Opps Created', opps_created, TARGET_OPPS, pct_opps, '#38bdf8') +
    funnel_card('Closed Won', won_count, TARGET_CLOSED, pct_closed, '#3DC570') +
    funnel_card('Revenue Recaptured', won_mrr, TARGET_MRR, pct_mrr, '#3DC570', '$')
)

def status_badge(r):
    sk = r['status_key']
    stage = r['stage']
    if sk == 'won':
        return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;background:#3DC57022;color:#3DC570">Closed Won</span>'
    elif sk == 'active':
        # Simplify stage labels
        lmap = {'1- Discovery Scheduled':'Opp Created','2 - Discovery Completed':'Discovery','3 - Initial Product Demo':'Demo / Proposal','4 - Proposal Sent':'Demo / Proposal','5 - Product / Contract Validated':'Validated','6 - Verbal Commit':'Verbal Commit'}
        lbl = lmap.get(stage, stage)
        return f'<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;background:#a78bfa22;color:#a78bfa">{lbl}</span>'
    elif sk == 'lost':
        return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;background:#f8717122;color:#f87171">Closed Lost</span>'
    else:
        return '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;background:#47556922;color:#475569">Not Contacted</span>'

def stage_badge(r):
    sk = r['status_key']
    stage = r['stage']
    if sk == 'won':
        return '<span style="font-size:10px;font-weight:600;padding:2px 7px;border-radius:4px;background:#3DC57022;color:#3DC570">Closed Won</span>'
    elif sk == 'active':
        return f'<span style="font-size:10px;font-weight:600;padding:2px 7px;border-radius:4px;background:#a78bfa22;color:#a78bfa">{stage}</span>'
    elif sk == 'lost':
        return f'<span style="font-size:10px;font-weight:600;padding:2px 7px;border-radius:4px;background:#f8717122;color:#f87171">Closed Lost</span>'
    else:
        return '<span style="font-size:10px;color:#475569">No opp</span>'

def date_cell(r):
    cd = r['close_date']
    if not cd: return '<span style="color:#64748b;font-size:11px">—</span>'
    try:
        dt = datetime.fromisoformat(cd)
        today = datetime.now(timezone.utc).date()
        d = dt.date() if hasattr(dt, 'date') else dt
        if d > today:
            return f'<span style="color:#64748b;font-size:11px">📅 {cd} (upcoming)</span>'
        return f'<span style="color:#64748b;font-size:11px">{cd}</span>'
    except:
        return f'<span style="color:#64748b;font-size:11px">{cd}</span>'

table_rows = ''
for r in rows:
    features_html = ', '.join(r['features'][:4]) if r['features'] else '—'
    table_rows += f'''<tr>
<td style="font-weight:600;color:#e2e8f0">{r['name']}</td>
<td style="color:#3DC570;font-weight:700">${r['mrr']:,}</td>
<td style="color:#64748b">{r['owner']}</td>
<td style="color:#475569;font-size:10px">{features_html}</td>
<td style="text-align:center">{len(opp_by_acct.get(r['sf_id'],[]))}</td>
<td style="text-align:center">{date_cell(r)}</td>
<td style="text-align:center">{stage_badge(r)}</td>
<td style="text-align:center;font-size:10px;color:#f87171">{r['loss_reason']}</td>
<td style="text-align:center">{status_badge(r)}</td>
</tr>\n'''

date_str = datetime.now(timezone.utc).strftime('%B %d, %Y')

HTML = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Q2 Apollo 2 — Re-engagement Tracker</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e2e8f0}}
header{{background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);border-bottom:1px solid #334155;padding:20px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
header h1{{font-size:1.4rem;font-weight:700;color:#f8fafc}}
header h1 span{{color:#3DC570}}
.updated{{font-size:.72rem;color:#64748b;margin-top:4px}}
.container{{max-width:1400px;margin:0 auto;padding:24px}}
.kpi-row{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:24px}}
.kpi{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:14px 18px;flex:1;min-width:110px;position:relative;overflow:hidden}}
.kpi::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--accent,#38bdf8)}}
.kpi.green{{--accent:#3DC570}}.kpi.purple{{--accent:#a78bfa}}.kpi.red{{--accent:#f87171}}.kpi.blue{{--accent:#38bdf8}}.kpi.grey{{--accent:#475569}}
.kpi-label{{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;margin-bottom:4px}}
.kpi-val{{font-size:24px;font-weight:800;color:#f8fafc;line-height:1}}
.kpi-sub{{font-size:10px;color:#64748b;margin-top:2px}}
.search-bar{{margin-bottom:12px}}
.search-bar input{{background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:8px 14px;border-radius:6px;font-size:13px;width:320px;outline:none}}
.search-bar input:focus{{border-color:#3DC570}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
thead{{background:#0f172a}}
th{{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;padding:8px 12px;text-align:left;border-bottom:1px solid #334155;white-space:nowrap}}
td{{padding:8px 12px;border-bottom:1px solid #1a2438;vertical-align:middle}}
tr:hover td{{background:rgba(61,197,112,.02)}}
.footer{{text-align:center;padding:20px;font-size:.72rem;color:#475569;border-top:1px solid #1e293b;margin-top:8px}}
.note{{text-align:center;color:#475569;font-size:.72rem;margin-top:12px}}
.funnel-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}}
.funnel-card{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:16px 18px}}
.f-label{{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;margin-bottom:6px}}
.f-val{{font-size:28px;font-weight:800;line-height:1}}
.section-title{{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#475569;margin-bottom:12px;padding-bottom:6px;border-bottom:1px solid #1e293b}}
</style></head><body>
<header>
  <div>
    <h1>Q2 Apollo 2 <span>Re-engagement Tracker</span></h1>
    <div class="updated">Last updated: {date_str} · {len(rows)} accounts · Salesforce live data</div>
  </div>
</header>
<div class="container">
  <div class="kpi-row">
    <div class="kpi green"><div class="kpi-label">Closed Won</div><div class="kpi-val" style="color:#3DC570">{won_count}</div><div class="kpi-sub">${won_mrr:,} MRR recaptured</div></div>
    <div class="kpi purple"><div class="kpi-label">Active Opps</div><div class="kpi-val" style="color:#a78bfa">{active_count}</div><div class="kpi-sub">${active_mrr:,} in pipeline</div></div>
    <div class="kpi red"><div class="kpi-label">Closed Lost</div><div class="kpi-val" style="color:#f87171">{lost_count}</div></div>
    <div class="kpi blue"><div class="kpi-label">Total Contacted</div><div class="kpi-val">{contacted_count}</div><div class="kpi-sub">of {len(rows)} accounts</div></div>
    <div class="kpi grey"><div class="kpi-label">Not Yet Contacted</div><div class="kpi-val">{not_contacted}</div></div>
    <div class="kpi green"><div class="kpi-label">Total MRR Pool</div><div class="kpi-val" style="color:#3DC570">${total_mrr:,}</div><div class="kpi-sub">at risk / available</div></div>
  </div>
  <div class="section-title">Q2 Goal Progress — Target: June 30</div>
  <div class="funnel-row">{funnel_html}</div>
  <div class="search-bar"><input type="text" id="search" placeholder="Search accounts, owners, features..." oninput="filterTable()"/></div>
  <table>
    <thead><tr>
      <th>Account</th><th>MRR</th><th>Owner</th><th>Features Needed</th>
      <th>Total Opps</th><th>Last Close Date</th><th>SF Stage</th><th>Loss Reason</th><th>Status</th>
    </tr></thead>
    <tbody id="tableBody">{table_rows}</tbody>
  </table>
  <p class="note">Q2 targets: 73 contacted · 45 opps created · 12 closed · $12K MRR recaptured by June 30 · Source: Salesforce · {date_str}</p>
</div>
<div class="footer">Rev.io Internal · Robin 🦸🏻‍♂️ · Q2 Apollo 2 Re-engagement · {date_str}</div>
<script>
function filterTable(){{var q=document.getElementById('search').value.toLowerCase();var rows=document.getElementById('tableBody').getElementsByTagName('tr');for(var i=0;i<rows.length;i++){{rows[i].style.display=rows[i].textContent.toLowerCase().includes(q)?'':'none';}}}}
</script>
</body></html>"""

with open('/home/openclaw/.openclaw/workspace/q2-reengagement-tracker.html', 'w') as f:
    f.write(HTML)
print(f"Built! {len(rows)} accounts | Won: {won_count} (${won_mrr:,}) | Active: {active_count} | Lost: {lost_count} | Not contacted: {not_contacted}")
