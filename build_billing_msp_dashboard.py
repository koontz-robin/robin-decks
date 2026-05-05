import json, re
from collections import defaultdict, Counter
from datetime import datetime, timezone

with open('/home/openclaw/.openclaw/workspace/billing_msp_scan_results.json') as f:
    scan = json.load(f)
with open('/home/openclaw/.openclaw/workspace/billing_msp_sf_accounts.json') as f:
    sf_accounts = json.load(f)

hits = scan.get('hits', [])

# Build SF lookup - more aggressive matching
sf_lookup = {}
for acc in sf_accounts:
    sf_lookup[acc['Name'].lower().strip()] = acc
    # Also index by first significant word
    words = [w for w in acc['Name'].lower().split() if len(w) > 4 and w not in ('communications','technology','technologies','solutions','networks','telecom','services')]
    for w in words[:2]:
        if w not in sf_lookup:
            sf_lookup[w] = acc

def find_sf(name):
    nl = name.lower().strip()
    if nl in sf_lookup:
        return sf_lookup[nl]
    # Try stripping common suffixes
    for suffix in [', llc', ', inc', ', inc.', ' llc', ' inc', ' corp', ', ltd']:
        stripped = nl.replace(suffix, '').strip()
        if stripped in sf_lookup:
            return sf_lookup[stripped]
    # Try first 2 significant words
    words = [w for w in nl.split() if len(w) > 4]
    for w in words[:2]:
        if w in sf_lookup:
            return sf_lookup[w]
    return None

# Build matched list
rows = []
for h in hits:
    sf = find_sf(h['name'])
    psa = sf.get('PSA_Platform__c') or '—' if sf else '—'
    current = sf.get('Current_Platform__c') or '—' if sf else '—'
    rmm = sf.get('RMM_Platform__c') or '—' if sf else '—'
    billing = sf.get('Billing_Platform__c') or '—' if sf else '—'
    owner = (sf.get('Owner') or {}).get('Name', '—') if sf else '—'
    sf_name = sf['Name'] if sf else '—'
    sf_id = sf['Id'] if sf else None
    website = sf.get('Website') or h.get('url','') if sf else h.get('url','')
    kw = h.get('keywords', [])
    rows.append({
        'name': h['name'],
        'sf_name': sf_name,
        'sf_id': sf_id,
        'url': website or h.get('url',''),
        'keywords': kw,
        'psa_platform': psa,
        'current_platform': current,
        'rmm_platform': rmm,
        'billing_platform': billing,
        'owner': owner,
    })

# Sort: PSA platform set first, then alpha
rows.sort(key=lambda x: (0 if x['psa_platform'] not in ('—','') else 1, x['name'].lower()))

psa_counts = Counter(r['psa_platform'] for r in rows)
total = len(rows)
sf_matched = sum(1 for r in rows if r['sf_id'])

def psa_badge(psa):
    if psa in ('—', '', None):
        return '<span style="font-size:10px;color:#555;font-style:italic">Not set</span>'
    colors = {
        'CONNECTWISE': '#ff6b35', 'AUTOTASK/DATTO/KASEYA': '#ffd700',
        'SYNCRO': '#bf5af2', 'ZENDESK': '#00e5ff', 'ZOHO': '#00e5ff',
        'Rev.io Ticketing': '#00ff88', 'INHOUSE / HOMEGROWN': '#ffd700',
        'Salesforce Service Cloud': '#00b4cc', 'E-AUTOMATE': '#ff6b35',
    }
    col = colors.get(psa, '#aaa')
    return f'<span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:6px;background:{col}22;color:{col};border:1px solid {col}44">{psa}</span>'

def kw_chips(kws):
    return ''.join(
        f'<span style="font-size:9px;padding:1px 5px;border-radius:4px;background:rgba(0,229,255,0.08);color:#00b4cc;margin-right:3px">{k}</span>'
        for k in kws[:4]
    )

def sf_link(sf_id, sf_name):
    if not sf_id:
        return f'<span style="color:#555;font-size:11px">Not found in SF</span>'
    url = f"https://rev-io.lightning.force.com/lightning/r/Account/{sf_id}/view"
    return f'<a href="{url}" target="_blank" style="color:#c8f0dc;text-decoration:none;font-weight:600">{sf_name}</a>'

# Table rows
table_rows = ''
for r in rows:
    platforms = []
    if r['psa_platform'] not in ('—',''):
        platforms.append(('PSA', r['psa_platform']))
    if r['rmm_platform'] not in ('—',''):
        platforms.append(('RMM', r['rmm_platform']))
    if r['current_platform'] not in ('—',''):
        platforms.append(('Platform', r['current_platform']))

    platform_html = ''.join(
        f'<div style="margin-bottom:2px"><span style="font-size:9px;color:#3a6a4a;font-weight:700">{lbl}: </span>{psa_badge(val)}</div>'
        for lbl, val in platforms
    ) or psa_badge('—')

    url_display = r['url'].replace('https://','').replace('http://','').rstrip('/')
    table_rows += f'''<tr>
      <td style="color:#c8f0dc;font-weight:600">{r["name"]}<div style="margin-top:3px">{kw_chips(r["keywords"])}</div></td>
      <td><a href="https://{url_display}" target="_blank" style="color:#00e5ff;font-size:11px;text-decoration:none">{url_display}</a></td>
      <td>{sf_link(r["sf_id"], r["sf_name"])}</td>
      <td>{platform_html}</td>
      <td style="font-size:11px;color:#5a8a6a">{r["owner"]}</td>
    </tr>\n'''

date_str = datetime.now(timezone.utc).strftime('%B %d, %Y')

# PSA breakdown chips
psa_chip_colors = {
    'CONNECTWISE': '#ff6b35', 'AUTOTASK/DATTO/KASEYA': '#ffd700',
    'SYNCRO': '#bf5af2', 'Rev.io Ticketing': '#00ff88',
    'ZENDESK': '#00e5ff', 'Not set': '#555',
}
psa_chips = ''
for psa, count in sorted(psa_counts.items(), key=lambda x: -x[1]):
    label = psa if psa not in ('—','',None) else 'Not set'
    col = psa_chip_colors.get(label, '#aaa')
    psa_chips += f'''<div style="background:#030a06;border:1px solid {col}40;border-radius:8px;padding:10px 14px;min-width:120px;text-align:center">
      <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:{col};margin-bottom:4px">{label}</div>
      <div style="font-size:24px;font-weight:900;color:#fff">{count}</div>
    </div>'''

HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Billing MSP Clients — Rev.io</title>
<style>
  :root{{--green:#00ff88;--cyan:#00e5ff;--bg:#020408;--surface:#060d14;--border:#0a2a1a;--text:#c8f0dc;--muted:#2a5a3a}}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:'Segoe UI',system-ui,monospace;background:var(--bg);color:var(--text)}}
  body::before{{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(0,255,136,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,.08) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0}}
  .scanline{{position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.03) 2px,rgba(0,0,0,.03) 4px);pointer-events:none;z-index:0}}
  .container{{max-width:1200px;margin:0 auto;padding:24px 32px;position:relative;z-index:1}}
  .header{{border-bottom:1px solid var(--border);padding-bottom:16px;margin-bottom:20px}}
  .header-top{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}}
  .logo{{display:flex;align-items:center;gap:10px}}
  .logo-dot{{width:10px;height:10px;background:var(--green);border-radius:50%;box-shadow:0 0 12px var(--green);animation:pulse 2s infinite}}
  .logo-text{{font-size:11px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:var(--green)}}
  .header-date{{font-size:11px;color:var(--muted)}}
  h1{{font-size:28px;font-weight:900;color:#fff;letter-spacing:-1px;margin-bottom:4px}}
  h1 span{{color:var(--green);text-shadow:0 0 30px var(--green)}}
  .header-sub{{font-size:13px;color:var(--muted)}}
  .summary-bar{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}}
  .sum-item{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 16px;text-align:center;min-width:100px}}
  .sum-item.hl{{border-color:var(--green);background:rgba(0,255,136,.04)}}
  .sum-label{{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:4px}}
  .sum-val{{font-size:22px;font-weight:900;color:#fff}}
  .sum-val.green{{color:var(--green)}}
  .section-title{{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:10px;margin-top:20px}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:16px}}
  .card-body{{padding:20px 24px}}
  .opp-table{{width:100%;border-collapse:collapse}}
  .opp-table thead{{background:#030a06}}
  .opp-table th{{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);padding:8px 14px;text-align:left}}
  .opp-table td{{font-size:12px;padding:8px 14px;border-bottom:1px solid rgba(0,255,136,.04);color:#8ab89a;vertical-align:top}}
  .opp-table tr:last-child td{{border-bottom:none}}
  .opp-table tr:hover td{{background:rgba(0,255,136,.02)}}
  .footer{{text-align:center;padding:20px;font-size:10px;color:#1a3a2a;letter-spacing:1px;border-top:1px solid var(--border);margin-top:8px}}
  input[type=text]{{background:#030a06;border:1px solid var(--border);color:var(--text);padding:8px 14px;border-radius:6px;font-size:13px;width:300px;outline:none}}
  input[type=text]:focus{{border-color:var(--green)}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
</style>
</head>
<body>
<div class="scanline"></div>
<div class="container">
  <div class="header">
    <div class="header-top">
      <div class="logo"><div class="logo-dot"></div><div class="logo-text">Rev.io · Sales Intelligence</div></div>
      <div class="header-date">GENERATED {date_str.upper()} · WEBSITE SCAN + SALESFORCE</div>
    </div>
    <h1>Billing Clients <span>MSP Intelligence</span></h1>
    <div class="header-sub">{total} billing customers with MSP/managed services signals on their website · PSA platform data from Salesforce</div>
  </div>

  <div class="summary-bar">
    <div class="sum-item hl"><div class="sum-label">MSP Billing Clients</div><div class="sum-val green">{total}</div></div>
    <div class="sum-item"><div class="sum-label">Matched in SF</div><div class="sum-val">{sf_matched}</div></div>
    <div class="sum-item"><div class="sum-label">PSA Platform Set</div><div class="sum-val">{sum(1 for r in rows if r["psa_platform"] not in ("—","",None))}</div></div>
    <div class="sum-item"><div class="sum-label">No PSA Set</div><div class="sum-val">{sum(1 for r in rows if r["psa_platform"] in ("—","",None))}</div></div>
  </div>

  <div class="section-title">PSA Platform Breakdown</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px">{psa_chips}</div>

  <div class="section-title">All {total} MSP Billing Clients</div>
  <div style="margin-bottom:12px">
    <input type="text" id="search" placeholder="Search accounts..." oninput="filterTable()" />
  </div>
  <div class="card">
    <table class="opp-table" id="mainTable">
      <thead><tr>
        <th>Company</th>
        <th>Website</th>
        <th>Salesforce Account</th>
        <th>PSA / Platform (SF)</th>
        <th>Owner</th>
      </tr></thead>
      <tbody id="tableBody">{table_rows}</tbody>
    </table>
  </div>

  <div class="footer">REV.IO SALES INTELLIGENCE · ROBIN 🦸🏻‍♂️ · BILLING MSP SCAN · {date_str.upper()}</div>
</div>
<script>
function filterTable() {{
  var q = document.getElementById('search').value.toLowerCase();
  var rows = document.getElementById('tableBody').getElementsByTagName('tr');
  for (var i = 0; i < rows.length; i++) {{
    rows[i].style.display = rows[i].textContent.toLowerCase().includes(q) ? '' : 'none';
  }}
}}
</script>
</body>
</html>"""

with open('/home/openclaw/.openclaw/workspace/billing-msp-clients.html', 'w') as f:
    f.write(HTML)
print(f"Done! {total} clients, {sf_matched} matched to SF")
print("PSA breakdown:", dict(psa_counts))
