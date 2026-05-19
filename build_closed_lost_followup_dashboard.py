"""
build_closed_lost_followup_dashboard.py
Fetches Closed Lost opps with Follow_up_date__c populated, builds HTML dashboard.
"""
import json, requests
from datetime import datetime, timezone, date
from collections import defaultdict

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
WORKSPACE = '/home/openclaw/.openclaw/workspace'

# Auth
r = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={
    "grant_type": "client_credentials",
    "client_id": SF_CLIENT_ID,
    "client_secret": SF_CLIENT_SECRET,
})
r.raise_for_status()
nt = r.json()
BASE = nt['instance_url']
HEADERS = {"Authorization": f"Bearer {nt['access_token']}"}

# Fetch opps
soql = """
SELECT Id, Name, Owner.Name, Account.Name, Amount, CloseDate,
       Follow_up_date__c, Product_Type__c
FROM Opportunity
WHERE StageName = 'Closed Lost'
  AND Follow_up_date__c != null
ORDER BY Owner.Name ASC, Follow_up_date__c ASC
LIMIT 500
"""

all_records = []
url = f"{BASE}/services/data/v59.0/query"
params = {"q": soql.strip()}
while True:
    resp = requests.get(url, params=params, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    all_records.extend(data.get('records', []))
    if data.get('done'):
        break
    url = BASE + data['nextRecordsUrl']
    params = {}

# Group by owner
by_owner = defaultdict(list)
for rec in all_records:
    owner = rec.get('Owner', {}).get('Name', 'Unknown')
    by_owner[owner].append(rec)

def earliest_date(accts):
    dates = [a.get('Follow_up_date__c') for a in accts if a.get('Follow_up_date__c')]
    return min(dates) if dates else '9999'

owners_sorted = sorted(by_owner.keys(), key=lambda o: earliest_date(by_owner[o]))

today = date.today()
now_str = datetime.now(timezone.utc).strftime('%B %d, %Y at %I:%M %p UTC')

def days_until(date_str):
    try:
        d = date.fromisoformat(date_str)
        return (d - today).days
    except:
        return None

def urgency_class(days):
    if days is None: return 'future'
    if days < 0: return 'past'
    if days <= 7: return 'urgent'
    if days <= 30: return 'soon'
    if days <= 90: return 'moderate'
    return 'future'

def urgency_label(days):
    if days is None: return ''
    if days < 0: return f'<span class="badge past-badge">{abs(days)}d overdue</span>'
    if days == 0: return '<span class="badge urgent-badge">Today!</span>'
    if days <= 7: return f'<span class="badge urgent-badge">{days}d</span>'
    if days <= 30: return f'<span class="badge soon-badge">{days}d</span>'
    if days <= 90: return f'<span class="badge moderate-badge">{days}d</span>'
    return f'<span class="badge future-badge">{days}d</span>'

def fmt_date(date_str):
    try:
        d = date.fromisoformat(date_str)
        return d.strftime('%b %d, %Y')
    except:
        return date_str or '—'

def fmt_amount(amt):
    if amt is None: return '—'
    try:
        return f"${amt:,.0f}"
    except:
        return str(amt)

# Build sections
sections_html = []
for owner in owners_sorted:
    accts = by_owner[owner]
    rows = []
    for a in accts:
        follow_date = a.get('Follow_up_date__c')
        days = days_until(follow_date) if follow_date else None
        urg = urgency_class(days)
        sf_id = a.get('Id', '')
        sf_link = f"https://rev-io.my.salesforce.com/{sf_id}" if sf_id else '#'
        account_name = a.get('Account', {}).get('Name') or '—' if a.get('Account') else '—'
        rows.append(f"""
        <tr class="row-{urg}">
          <td><a href="{sf_link}" target="_blank" class="opp-link">{a.get('Name','—')}</a></td>
          <td class="acct-cell">{account_name}</td>
          <td>{fmt_date(follow_date)}</td>
          <td>{urgency_label(days)}</td>
          <td>{a.get('Product_Type__c') or '—'}</td>
          <td class="amount">{fmt_amount(a.get('Amount'))}</td>
          <td>{fmt_date(a.get('CloseDate'))}</td>
        </tr>""")

    rows_html = '\n'.join(rows)
    count = len(accts)
    total_arr = sum(a.get('Amount') or 0 for a in accts)

    overdue_count = sum(1 for a in accts if (d := days_until(a.get('Follow_up_date__c') or '')) is not None and d < 0)
    urgent_count  = sum(1 for a in accts if (d := days_until(a.get('Follow_up_date__c') or '')) is not None and 0 <= d <= 7)
    soon_count    = sum(1 for a in accts if (d := days_until(a.get('Follow_up_date__c') or '')) is not None and 7 < d <= 30)

    pills = ''
    if overdue_count:
        pills += f'<span class="pill past-pill">⚠️ {overdue_count} overdue</span>'
    if urgent_count:
        pills += f'<span class="pill urgent-pill">🔴 {urgent_count} this week</span>'
    if soon_count:
        pills += f'<span class="pill soon-pill">🟡 {soon_count} this month</span>'

    sections_html.append(f"""
    <div class="owner-section" id="owner-{owner.replace(' ','-').replace('.','').lower()}">
      <div class="owner-header">
        <div class="owner-name">{owner}</div>
        <div class="owner-meta">
          <span class="count-badge">{count} opp{'s' if count != 1 else ''}</span>
          <span class="arr-badge">{fmt_amount(total_arr)} ARR</span>
          {pills}
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Opportunity</th>
            <th>Account</th>
            <th>Follow-up Date</th>
            <th>Time Until</th>
            <th>Product</th>
            <th>Amount</th>
            <th>Closed Lost</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>""")

all_sections = '\n'.join(sections_html)
total = len(all_records)
total_arr_all = sum(r.get('Amount') or 0 for r in all_records)

nav_links = ' '.join([
    f'<a href="#owner-{o.replace(" ","-").replace(".","").lower()}" class="nav-link">{o.split()[0]}</a>'
    for o in owners_sorted
])

overdue_total = sum(1 for r in all_records if (d := days_until(r.get('Follow_up_date__c') or '')) is not None and d < 0)
this_week_total = sum(1 for r in all_records if (d := days_until(r.get('Follow_up_date__c') or '')) is not None and 0 <= d <= 7)
this_month_total = sum(1 for r in all_records if (d := days_until(r.get('Follow_up_date__c') or '')) is not None and 7 < d <= 30)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Closed Lost Follow-up Dates — Rev.io</title>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #21263a;
    --border: #2e3452;
    --text: #e8eaf6;
    --text-muted: #8890b5;
    --accent: #6c8ef5;
    --urgent: #ef5350;
    --soon: #ffa726;
    --moderate: #66bb6a;
    --future: #42a5f5;
    --past: #ff7043;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }}
  .header {{
    background: linear-gradient(135deg, #1a1d27 0%, #1f2440 100%);
    border-bottom: 1px solid var(--border);
    padding: 24px 32px;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 2px 12px rgba(0,0,0,0.4);
  }}
  .header-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }}
  .title {{ font-size: 22px; font-weight: 700; color: #fff; }}
  .subtitle {{ font-size: 13px; color: var(--text-muted); margin-top: 2px; }}
  .stat-pills {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
  .stat-pill {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
  }}
  .stat-pill span {{ color: var(--text); }}
  .stat-pill.warn span {{ color: var(--past); }}
  .stat-pill.hot span {{ color: var(--urgent); }}
  .nav-bar {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 10px 32px;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }}
  .nav-link {{
    color: var(--text-muted);
    text-decoration: none;
    padding: 4px 12px;
    border-radius: 14px;
    font-size: 12px;
    font-weight: 500;
    border: 1px solid var(--border);
    transition: all 0.15s;
    white-space: nowrap;
  }}
  .nav-link:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .content {{ padding: 24px 32px; max-width: 1300px; }}
  .legend {{
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 24px;
    padding: 12px 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    align-items: center;
  }}
  .legend-title {{ font-size: 12px; font-weight: 600; color: var(--text-muted); margin-right: 4px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted); }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .owner-section {{
    margin-bottom: 32px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }}
  .owner-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    background: var(--surface2);
    border-bottom: 1px solid var(--border);
    gap: 12px;
    flex-wrap: wrap;
  }}
  .owner-name {{ font-size: 16px; font-weight: 700; color: #fff; }}
  .owner-meta {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .count-badge {{
    background: rgba(108,142,245,0.15);
    color: var(--accent);
    border: 1px solid rgba(108,142,245,0.3);
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 600;
  }}
  .arr-badge {{
    background: rgba(102,187,106,0.1);
    color: #81c784;
    border: 1px solid rgba(102,187,106,0.25);
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 600;
  }}
  .pill {{
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
  }}
  .past-pill {{ background: rgba(255,112,67,0.15); color: #ff8a65; border: 1px solid rgba(255,112,67,0.3); }}
  .urgent-pill {{ background: rgba(239,83,80,0.15); color: #ef9a9a; border: 1px solid rgba(239,83,80,0.3); }}
  .soon-pill {{ background: rgba(255,167,38,0.15); color: #ffcc80; border: 1px solid rgba(255,167,38,0.3); }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead tr {{ background: rgba(255,255,255,0.03); }}
  th {{
    text-align: left;
    padding: 10px 16px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  td {{
    padding: 10px 16px;
    border-bottom: 1px solid rgba(46,52,82,0.5);
    vertical-align: middle;
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover {{ background: rgba(255,255,255,0.03); }}
  .row-urgent {{ border-left: 3px solid var(--urgent); }}
  .row-soon {{ border-left: 3px solid var(--soon); }}
  .row-moderate {{ border-left: 3px solid var(--moderate); }}
  .row-future {{ border-left: 3px solid var(--future); }}
  .row-past {{ border-left: 3px solid var(--past); }}
  .opp-link {{ color: var(--accent); text-decoration: none; font-weight: 500; }}
  .opp-link:hover {{ text-decoration: underline; }}
  .acct-cell {{ color: var(--text-muted); font-size: 13px; }}
  .amount {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
  }}
  .urgent-badge {{ background: rgba(239,83,80,0.2); color: #ef5350; }}
  .soon-badge {{ background: rgba(255,167,38,0.2); color: #ffa726; }}
  .moderate-badge {{ background: rgba(102,187,106,0.2); color: #66bb6a; }}
  .future-badge {{ background: rgba(66,165,245,0.2); color: #42a5f5; }}
  .past-badge {{ background: rgba(255,112,67,0.2); color: #ff7043; }}
  .updated {{ font-size: 11px; color: var(--text-muted); margin-top: 4px; }}
  @media (max-width: 800px) {{
    .header, .nav-bar, .content {{ padding-left: 16px; padding-right: 16px; }}
    th:nth-child(5), td:nth-child(5),
    th:nth-child(7), td:nth-child(7) {{ display: none; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <div>
      <div class="title">♻️ Closed Lost — Follow-up Dates</div>
      <div class="subtitle">Re-engagement pipeline sorted by rep &amp; follow-up date, nearest first</div>
    </div>
    <div class="stat-pills">
      <div class="stat-pill">Total <span>{total}</span></div>
      <div class="stat-pill">ARR <span>{fmt_amount(total_arr_all)}</span></div>
      <div class="stat-pill warn">⚠️ Overdue <span>{overdue_total}</span></div>
      <div class="stat-pill hot">🔴 This week <span>{this_week_total}</span></div>
      <div class="stat-pill">🟡 This month <span>{this_month_total}</span></div>
    </div>
  </div>
  <div class="updated">Last refreshed: {now_str}</div>
</div>

<div class="nav-bar">
  {nav_links}
</div>

<div class="content">

  <div class="legend">
    <span class="legend-title">Follow-up timing:</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--past)"></span> Overdue</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--urgent)"></span> ≤7 days</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--soon)"></span> 8–30 days</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--moderate)"></span> 31–90 days</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--future)"></span> 90+ days</span>
  </div>

  {all_sections}

</div>
</body>
</html>"""

out = f'{WORKSPACE}/closed_lost_followup.html'
with open(out, 'w') as f:
    f.write(html)
print(f"Wrote {out} — {total} opps, {fmt_amount(total_arr_all)} ARR")
