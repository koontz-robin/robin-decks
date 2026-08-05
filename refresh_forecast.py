"""
refresh_forecast.py — Daily forecast dashboard refresh
Fetches current-month opps from Salesforce, rebuilds forecast.html, pushes to GitHub.
Run by cron daily at 8am ET on weekdays.
"""
import json, subprocess, sys, os, re, shutil, tempfile
from datetime import datetime, timezone
from pathlib import Path
import requests

WORKSPACE = '/home/openclaw/.openclaw/workspace'
SF_TOKEN_FILE = f'{WORKSPACE}/sf-tokens.json'
OPP_FILE = f'{WORKSPACE}/sf_may_opps.json'  # overwritten each run
FORECAST_HTML = f'{WORKSPACE}/forecast.html'

SF_INSTANCE = "https://rev-io.my.salesforce.com"

SF_CLIENT_ID     = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

# ── Step 1: Authenticate via client credentials ──────────────────────────────
print("🔐 Authenticating to Salesforce...")
r = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={
    "grant_type": "client_credentials",
    "client_id": SF_CLIENT_ID,
    "client_secret": SF_CLIENT_SECRET,
})
r.raise_for_status()
nt = r.json()

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
       CloseDate, Forecast_Status__c, Loss_Reason__c, Reason_Lost_Detail__c,
       Account.Name, Owner.Name,
       (SELECT Id, Quantity, UnitPrice, TotalPrice, Product2.Name, Product2.Family
        FROM OpportunityLineItems)
FROM Opportunity
WHERE CloseDate >= {month_start}
  AND CloseDate <= {month_end}
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
    all_records.extend(data.get('records', []))
    print(f"  Fetched {len(data.get('records',[]))} records (total: {len(all_records)})")
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

# ── Step 4: Patch forecast.html with fresh current-month data ───────────────
print("🔨 Patching forecast.html with fresh data...")
result = subprocess.run([sys.executable, f'{WORKSPACE}/patch_may_forecast.py'], capture_output=True, text=True)
if result.returncode != 0:
    print(f"❌ Patch failed:\n{result.stderr}")
    sys.exit(1)
print(f"✅ {result.stdout.strip()}")

# ── Step 5: Push to GitHub ────────────────────────────────────────────────────
print("🚀 Pushing to GitHub...")
commit_msg = f"forecast.html — auto-refresh {now.strftime('%Y-%m-%d')}"
tmp_parent = Path(tempfile.mkdtemp(prefix="forecast-publish."))
worktree = tmp_parent / "worktree"
try:
    cmds = [
        ["git", "fetch", "robin-decks", "master"],
        ["git", "worktree", "add", str(worktree), "robin-decks/master"],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌ Git error: {r.stderr}")
            sys.exit(1)
        if r.stdout.strip():
            print(f"  {r.stdout.strip()}")

    for path in [Path(FORECAST_HTML), Path(opp_file_path)]:
        shutil.copy2(path, worktree / path.name)

    cmds = [
        ["git", "config", "user.name", "Robin"],
        ["git", "config", "user.email", "robin@rev.io"],
        ["git", "add", Path(FORECAST_HTML).name, Path(opp_file_path).name],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, cwd=worktree, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌ Git error: {r.stderr}")
            sys.exit(1)

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree)
    if diff.returncode == 0:
        print("  No publish changes")
    else:
        cmds = [
            ["git", "commit", "-m", commit_msg],
            ["git", "push", "robin-decks", "HEAD:master"],
        ]
        for cmd in cmds:
            r = subprocess.run(cmd, cwd=worktree, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"❌ Git error: {r.stderr}")
                sys.exit(1)
            if r.stdout.strip():
                print(f"  {r.stdout.strip()}")
finally:
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=WORKSPACE, check=False)
    shutil.rmtree(tmp_parent, ignore_errors=True)

print("✅ Done — forecast.html pushed to GitHub Pages")
print(f"🔗 https://koontz-robin.github.io/robin-decks/forecast.html")
