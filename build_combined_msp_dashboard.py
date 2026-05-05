import json
from collections import Counter
from datetime import datetime, timezone

with open('/home/openclaw/.openclaw/workspace/billing_msp_matched.json') as f:
    matched = json.load(f)
with open('/home/openclaw/.openclaw/workspace/billing_msp_unreachable_matched.json') as f:
    unreachable = json.load(f)

def make_row(m):
    h = m['scan']
    sf = m['sf']
    return {
        'name': h['name'],
        'sf_name': sf['Name'] if sf else '—',
        'sf_id': sf['Id'] if sf else None,
        'url': (sf.get('Website') or h.get('url','')) if sf else h.get('url',''),
        'keywords': h.get('keywords', []),
        'psa': sf.get('PSA_Platform__c') or '—' if sf else '—',
        'rmm': sf.get('RMM_Platform__c') or '—' if sf else '—',
        'current': sf.get('Current_Platform__c') or '—' if sf else '—',
        'owner': (sf.get('Owner') or {}).get('Name','—') if sf else '—',
    }

rows = [make_row(m) for m in matched] + [make_row(m) for m in unreachable]
rows.sort(key=lambda x: (0 if x['psa'] not in ('—','',None,'N/A') else 1, x['name'].lower()))

psa_counts = Counter(r['psa'] for r in rows)
total = len(rows)
not_set = sum(v for k,v in psa_counts.items() if k in ('—','N/A'))

CHIP_COLORS = {
    'CONNECTWISE':'#ff6b35','AUTOTASK/DATTO/KASEYA':'#ffd700','SYNCRO':'#bf5af2',
    'ZENDESK':'#00e5ff','ZOHO':'#00e5ff','Rev.io Ticketing':'#00ff88',
    'INHOUSE / HOMEGROWN':'#ffd700','Salesforce Service Cloud':'#00b4cc',
    'HALO':'#a78bfa','SuperOps':'#a78bfa','FRESHDESK':'#38bdf8',
    'SPREADSHEETS':'#888','QUICKBOOKS':'#ffd700','—':'#444','N/A':'#444',
}

def badge(val):
    if val in ('—','',None,'N/A'):
        return '<span style="font-size:10px;color:#555;font-style:italic">Not set</span>'
    col = CHIP_COLORS.get(val,'#aaa')
    return f'<span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:6px;background:{col}22;color:{col};border:1px solid {col}44">{val}</span>'

def kw(kws):
    if not kws:
        return '<span style="font-size:9px;color:#3a6a4a;font-style:italic">Website unreachable</span>'
    return ''.join(f'<span style="font-size:9px;padding:1px 5px;border-radius:4px;background:rgba(0,229,255,0.08);color:#00b4cc;margin-right:3px">{k}</span>' for k in kws[:4])

def sflink(sf_id, sf_name):
    if not sf_id:
        return '<span style="color:#555;font-size:11px">Not in SF</span>'
    return f'<a href="https://rev-io.lightning.force.com/lightning/r/Account/{sf_id}/view" target="_blank" style="color:#c8f0dc;text-decoration:none;font-weight:600">{sf_name}</a>'

table_rows = ''
for r in rows:
    platforms = []
    for lbl, key in [('PSA','psa'),('RMM','rmm'),('Provisioning','current')]:
        val = r.get(key,'—')
        if val not in ('—','',None,'N/A'):
            platforms.append((lbl, val))
    plat_html = ''.join(f'<div style="margin-bottom:2px"><span style="font-size:9px;color:#3a6a4a;font-weight:700">{l}: </span>{badge(v)}</div>' for l,v in platforms) or badge('—')
    url_clean = (r['url'] or '').replace('https://','').replace('http://','').split('/')[0].strip().rstrip('.')
    url_html = f'<a href="https://{url_clean}" target="_blank" style="color:#00e5ff;font-size:11px;text-decoration:none">{url_clean}</a>' if url_clean else '—'
    table_rows += f'<tr><td style="color:#c8f0dc;font-weight:600">{r["name"]}<div style="margin-top:3px">{kw(r["keywords"])}</div></td><td>{url_html}</td><td>{sflink(r["sf_id"],r["sf_name"])}</td><td>{plat_html}</td><td style="font-size:11px;color:#5a8a6a">{r["owner"]}</td></tr>\n'

chips = ''
for psa, count in sorted(psa_counts.items(), key=lambda x: -x[1]):
    label = psa if psa not in ('—','',None) else 'Not set'
    col = CHIP_COLORS.get(psa,'#aaa')
    chips += f'<div style="background:#030a06;border:1px solid {col}40;border-radius:8px;padding:10px 14px;min-width:100px;text-align:center"><div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:{col};margin-bottom:4px">{label}</div><div style="font-size:22px;font-weight:900;color:#fff">{count}</div></div>'

date_str = datetime.now(timezone.utc).strftime('%B %d, %Y')
cw_n = psa_counts.get('CONNECTWISE',0)
at_n = psa_counts.get('AUTOTASK/DATTO/KASEYA',0)
rio_n = psa_counts.get('Rev.io Ticketing',0)

html = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Billing MSP Clients — Rev.io</title>
<style>
:root{--green:#00ff88;--cyan:#00e5ff;--bg:#020408;--surface:#060d14;--border:#0a2a1a;--text:#c8f0dc;--muted:#2a5a3a}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,monospace;background:var(--bg);color:var(--text)}
body::before{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(0,255,136,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,.08) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0}
.container{max-width:1200px;margin:0 auto;padding:24px 32px;position:relative;z-index:1}
.header{border-bottom:1px solid var(--border);padding-bottom:16px;margin-bottom:20px}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.logo-dot{width:10px;height:10px;background:var(--green);border-radius:50%;box-shadow:0 0 12px var(--green);animation:pulse 2s infinite}
.logo-text{font-size:11px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:var(--green)}
h1{font-size:28px;font-weight:900;color:#fff;margin-bottom:4px}
h1 span{color:var(--green);text-shadow:0 0 30px var(--green)}
.sub{font-size:13px;color:var(--muted)}
.summary-bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
.sum-item{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 16px;text-align:center;min-width:100px}
.sum-item.hl{border-color:var(--green);background:rgba(0,255,136,.04)}
.sum-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:4px}
.sum-val{font-size:22px;font-weight:900;color:#fff}
.sum-val.green{color:var(--green)}
.section-title{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:10px;margin-top:20px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:16px}
table{width:100%;border-collapse:collapse}
thead{background:#030a06}
th{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);padding:8px 14px;text-align:left}
td{font-size:12px;padding:8px 14px;border-bottom:1px solid rgba(0,255,136,.04);color:#8ab89a;vertical-align:top}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(0,255,136,.02)}
.footer{text-align:center;padding:20px;font-size:10px;color:#1a3a2a;border-top:1px solid var(--border);margin-top:8px}
input[type=text]{background:#030a06;border:1px solid var(--border);color:var(--text);padding:8px 14px;border-radius:6px;font-size:13px;width:320px;outline:none}
input[type=text]:focus{border-color:var(--green)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
</style></head><body>
<div class="container">""" + f"""
  <div class="header">
    <div class="logo"><div class="logo-dot"></div><div class="logo-text">Rev.io · Sales Intelligence</div></div>
    <h1>Billing Clients <span>MSP Intelligence</span></h1>
    <div class="sub">{total} billing customers with MSP/managed IT signals · PSA platform from Salesforce · {date_str}</div>
  </div>
  <div class="summary-bar">
    <div class="sum-item hl"><div class="sum-label">Total MSP Clients</div><div class="sum-val green">{total}</div></div>
    <div class="sum-item"><div class="sum-label">PSA Platform Known</div><div class="sum-val">{total-not_set}</div></div>
    <div class="sum-item"><div class="sum-label">ConnectWise</div><div class="sum-val" style="color:#ff6b35">{cw_n}</div></div>
    <div class="sum-item"><div class="sum-label">Autotask/Kaseya</div><div class="sum-val" style="color:#ffd700">{at_n}</div></div>
    <div class="sum-item hl"><div class="sum-label">Already Rev.io PSA</div><div class="sum-val green">{rio_n}</div></div>
    <div class="sum-item"><div class="sum-label">PSA Not Set</div><div class="sum-val">{not_set}</div></div>
  </div>
  <div class="section-title">PSA Platform Breakdown</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px">{chips}</div>
  <div class="section-title">All {total} MSP Billing Clients</div>
  <div style="margin-bottom:12px"><input type="text" id="search" placeholder="Search by name, PSA, keyword..." oninput="filterTable()"/></div>
  <div class="card">
    <table><thead><tr><th>Company</th><th>Website / Keywords</th><th>Salesforce Account</th><th>PSA / Platform</th><th>Owner</th></tr></thead>
    <tbody id="tableBody">{table_rows}</tbody></table>
  </div>
  <div class="footer">REV.IO SALES INTELLIGENCE · ROBIN 🦸🏻‍♂️ · {date_str.upper()}</div>
</div>
<script>
function filterTable(){{var q=document.getElementById('search').value.toLowerCase();var rows=document.getElementById('tableBody').getElementsByTagName('tr');for(var i=0;i<rows.length;i++){{rows[i].style.display=rows[i].textContent.toLowerCase().includes(q)?'':'none';}}}}
</script></body></html>"""

with open('/home/openclaw/.openclaw/workspace/billing-msp-clients.html','w') as f:
    f.write(html)
print(f"Done! {total} clients, CW:{cw_n}, AT:{at_n}, Rev.io PSA:{rio_n}, not set:{not_set}")
