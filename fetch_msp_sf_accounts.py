import requests, json
from collections import Counter

with open('/home/openclaw/.openclaw/workspace/sf-tokens.json') as f:
    t = json.load(f)
BASE = t['instance_url']
HEADERS = {"Authorization": f"Bearer {t['access_token']}"}

with open('/home/openclaw/.openclaw/workspace/billing_msp_scan_results.json') as f:
    scan = json.load(f)

hits = scan.get('hits', [])
names = [h['name'] for h in hits]

results = []
batch_size = 10
for i in range(0, len(names), batch_size):
    batch = names[i:i+batch_size]
    clauses = []
    for n in batch:
        safe = n.replace("'", "\\'")
        # Use first 3 words for fuzzy match
        words = n.split()[:3]
        word_clause = " OR ".join(f"Name LIKE '%{w}%'" for w in words if len(w) > 3)
        if word_clause:
            clauses.append(f"({word_clause})")
    if not clauses:
        continue
    where = " OR ".join(clauses)
    q = f"""SELECT Id, Name, Website, PSA_Platform__c, Current_Platform__c,
           RMM_Platform__c, Billing_Platform__c, TigerPaw_Type__c,
           Current_Systems__c, Owner.Name, Type
    FROM Account
    WHERE {where}
    LIMIT 50"""
    r = requests.get(f"{BASE}/services/data/v59.0/query", params={"q": q}, headers=HEADERS)
    if r.status_code == 200:
        recs = r.json().get('records', [])
        results.extend(recs)
        print(f"Batch {i//batch_size+1}: {len(recs)} records")
    else:
        print(f"Batch {i//batch_size+1} error: {r.text[:100]}")

# Deduplicate by Id
seen = set()
unique = []
for r in results:
    if r['Id'] not in seen:
        seen.add(r['Id'])
        unique.append(r)

print(f"\nTotal unique SF matches: {len(unique)}")
psa_vals = Counter(r.get('PSA_Platform__c') or '—' for r in unique)
print("PSA_Platform__c values:", dict(psa_vals))

with open('/home/openclaw/.openclaw/workspace/billing_msp_sf_accounts.json', 'w') as f:
    json.dump(unique, f, indent=2)
print("Saved to billing_msp_sf_accounts.json")
