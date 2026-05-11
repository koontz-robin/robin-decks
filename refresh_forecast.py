"""
refresh_forecast.py — Daily forecast dashboard refresh
Fetches current-month opps from Salesforce, rebuilds forecast.html, pushes to GitHub.
Run by cron daily at 8am ET on weekdays.
"""
import json, subprocess, sys, os, re
from datetime import datetime, timezone
import requests

WORKSPACE = '/home/openclaw/.openclaw/workspace'
SF_TOKEN_FILE = f'{WORKSPACE}/sf-tokens.json'
OPP_FILE = f'{WORKSPACE}/sf_may_opps.json'  # overwritten each run
FORECAST_HTML = f'{WORKSPACE}/forecast.html'

SF_INSTANCE = "https://rev-io.my.salesforce.com"

# ── Step 1: Authenticate via refresh token ───────────────────────────────────
print("🔐 Authenticating to Salesforce...")
with open(SF_TOKEN_FILE) as f:
    t = json.load(f)

r = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={
    "grant_type": "refresh_token",
    "refresh_token": t["refresh_token"],
    "client_id": t["client_id"],
    "client_secret": t["client_secret"],
})
r.raise_for_status()
nt = r.json()
nt["refresh_token"] = t["refresh_token"]
nt["client_id"] = t["client_id"]
nt["client_secret"] = t["client_secret"]
with open(SF_TOKEN_FILE, 'w') as f:
    json.dump(nt, f, indent=2)

BASE = nt['instance_url']
HEADERS = {"Authorization": f"Bearer {nt['access_token']}"}
print(f"✅ Authenticated. Instance: {BASE}")

# ── Step 2: Determine current month window ───────────────────────────────────
now = datetime.now(timezone.utc)
month_start = now.strftime('%Y-%m-01')
# Last day of current month
import calendar
last_day = calendar.monthrange(now.year, now.month)[1]
month_end = now.strftime(f'%Y-%m-{last_day:02d}')
print(f"📅 Fetching opps for {month_start} → {month_end}")

# ── Step 3: Fetch opps from Salesforce ───────────────────────────────────────
query = f"""
SELECT Id, Name, StageName, Amount, Product_Type__c, Probability,
       CloseDate, Forecast_Status__c,
       Account.Name, Owner.Name
FROM Opportunity
WHERE CloseDate >= {month_start}
  AND CloseDate <= {month_end}
  AND StageName != 'Closed Lost'
ORDER BY Amount DESC NULLS LAST
LIMIT 500
"""

all_records = []
url = f"{BASE}/services/data/v59.0/query"
params = {"q": query.strip()}
while True:
    resp = requests.get(url, params=params, headers=HEADERS)
    if not resp.ok:
        print(f"❌ SF query failed: {resp.status_code} {resp.text[:200]}")
        sys.exit(1)
    data = resp.json()
    records = data.get('records', [])
    all_records.extend(records)
    print(f"  Fetched {len(records)} records (total: {len(all_records)})")
    if data.get('done', True):
        break
    url = BASE + data['nextRecordsUrl']
    params = {}

print(f"✅ Total opps fetched: {len(all_records)}")

# Flatten Account/Owner sub-objects
for rec in all_records:
    if isinstance(rec.get('Account'), dict):
        rec['Account'] = rec['Account'].get('Name', '')
    if isinstance(rec.get('Owner'), dict):
        rec['Owner'] = rec['Owner'].get('Name', '')

# Save to opp file (update month name dynamically)
month_name = now.strftime('%B').lower()
opp_file_path = f'{WORKSPACE}/sf_{month_name}_opps.json'
with open(opp_file_path, 'w') as f:
    json.dump(all_records, f, indent=2)
print(f"💾 Saved to {opp_file_path}")

# ── Step 4: Patch forecast.html with fresh May data ─────────────────────────
print("🔨 Patching forecast.html with fresh data...")
result = subprocess.run([sys.executable, f'{WORKSPACE}/patch_may_forecast.py'], capture_output=True, text=True)
if result.returncode != 0:
    print(f"❌ Patch failed:\n{result.stderr}")
    sys.exit(1)
print(f"✅ {result.stdout.strip()}")

# ── Step 5: Push to GitHub ────────────────────────────────────────────────────
print("🚀 Pushing to GitHub...")
commit_msg = f"forecast.html — auto-refresh {now.strftime('%Y-%m-%d')}"
cmds = [
    f"cd {WORKSPACE} && git add forecast.html {opp_file_path}",
    f"cd {WORKSPACE} && git diff --cached --quiet || git commit -m '{commit_msg}'",
    f"cd {WORKSPACE} && git push robin-decks HEAD:master",
]
for cmd in cmds:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0 and 'nothing to commit' not in r.stdout + r.stderr:
        print(f"❌ Git error: {r.stderr}")
        sys.exit(1)
    if r.stdout.strip():
        print(f"  {r.stdout.strip()}")

print("✅ Done — forecast.html pushed to GitHub Pages")
print(f"🔗 https://koontz-robin.github.io/robin-decks/forecast.html")
