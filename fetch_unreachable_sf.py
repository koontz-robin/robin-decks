import requests, json
from collections import Counter

with open('/home/openclaw/.openclaw/workspace/sf-tokens.json') as f:
    t = json.load(f)

# Refresh token
r = requests.post("https://login.salesforce.com/services/oauth2/token", data={
    "grant_type": "refresh_token", "refresh_token": t["refresh_token"],
    "client_id": "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N",
    "client_secret": "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E",
})
nt = r.json(); nt["refresh_token"] = t["refresh_token"]
with open('/home/openclaw/.openclaw/workspace/sf-tokens.json', 'w') as f:
    json.dump(nt, f)
BASE = nt['instance_url']
HEADERS = {"Authorization": f"Bearer {nt['access_token']}"}

with open('/home/openclaw/.openclaw/workspace/billing_msp_scan_results.json') as f:
    scan = json.load(f)

errors = scan.get('errors', [])
print(f"Querying {len(errors)} unreachable companies in SF...")

results = []
for h in errors:
    name = h['name']
    clean = name.replace(', LLC','').replace(', Inc.','').replace(', Inc','').replace(' LLC','').replace(' Inc','').replace(', dba','').strip()
    # Also try first part before dba
    short = clean.split(' dba ')[0].strip() if ' dba ' in clean.lower() else clean

    q = f"""SELECT Id, Name, Website, PSA_Platform__c, Current_Platform__c,
           RMM_Platform__c, Billing_Platform__c, Owner.Name
    FROM Account
    WHERE Name = '{short.replace("'","''")}' OR Name = '{clean.replace("'","''")}' OR Name = '{name.replace("'","''")}' OR Website LIKE '%{h.get("url","").replace("https://","").replace("http://","").split("/")[0].strip()}%'
    LIMIT 3"""

    r = requests.get(f"{BASE}/services/data/v59.0/query", params={"q": q}, headers=HEADERS)
    if r.status_code == 200:
        recs = r.json().get('records', [])
        if recs:
            results.append({'scan': h, 'sf': recs[0]})
            print(f"  ✓ {name} → {recs[0]['Name']} | PSA: {recs[0].get('PSA_Platform__c') or '—'}")
        else:
            results.append({'scan': h, 'sf': None})
            print(f"  ✗ {name} — not in SF")
    else:
        results.append({'scan': h, 'sf': None})
        print(f"  ✗ {name} — query error")

matched = sum(1 for r in results if r['sf'])
print(f"\nMatched: {matched}/{len(results)}")
psa_vals = Counter(r['sf'].get('PSA_Platform__c') or '—' for r in results if r['sf'])
print("PSA breakdown:", dict(psa_vals))

with open('/home/openclaw/.openclaw/workspace/billing_msp_unreachable_matched.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Saved.")
