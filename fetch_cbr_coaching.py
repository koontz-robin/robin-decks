#!/usr/bin/env python3
"""
Fetch CBR scorecard data from Notion properties + Robin's Take for rep attribution.
Updates /tmp/coaching_summaries.json with CSA data.
"""

import json, re, time, requests
from collections import defaultdict

NOTION_TOKEN = "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"
NOTION_DB_ID = "333a59b7-e7b2-8062-8068-fc0116ff82f7"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def notion_post(url, payload):
    for _ in range(3):
        r = requests.post(url, headers=headers, json=payload)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 1)) + 0.5)
            continue
        r.raise_for_status()
        return r.json()

def get_num(props, key):
    return (props.get(key) or {}).get("number") or 0

def get_text(props, key):
    rt = (props.get(key) or {}).get("rich_text", [])
    return "".join(t.get("plain_text","") for t in rt)

def get_title(props, key):
    rt = (props.get(key) or {}).get("title", [])
    return "".join(t.get("plain_text","") for t in rt)

def get_date(props, key):
    return ((props.get(key) or {}).get("date") or {}).get("start", "")

def infer_rep(robins_take, top_coaching):
    """Identify rep from text mentions in Robin's Take or Top Coaching Point."""
    text = (robins_take + " " + top_coaching).lower()
    ingrid_count = len(re.findall(r'\bingrid\b', text))
    justin_count  = len(re.findall(r'\bjustin\b', text))
    if ingrid_count > justin_count:
        return "Ingrid Beard"
    if justin_count > ingrid_count:
        return "Justin Lee"
    # Tie — check for 'the rep', 'she', 'he' can't help, just flag unknown
    return None

# ── Fetch all CBR pages ──────────────────────────────────────────────────────
print("Fetching CBR records from Notion...")
pages, cursor = [], None
while True:
    payload = {
        "page_size": 100,
        "filter": {"property": "Meeting Title", "title": {"contains": "Client Business Review"}}
    }
    if cursor:
        payload["start_cursor"] = cursor
    data = notion_post(f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query", payload)
    pages.extend(data.get("results", []))
    if not data.get("has_more"):
        break
    cursor = data.get("next_cursor")

print(f"CBR records found: {len(pages)}")

rep_records = defaultdict(list)

for page in pages:
    props = page.get("properties", {})
    title       = get_title(props, "Meeting Title")
    account     = get_text(props, "Prospect / Account")
    date        = get_date(props, "Meeting Date")
    score       = get_num(props, "Overall Score")
    approach    = get_num(props, "Approach")
    sotu        = get_num(props, "Company Story")      # State of the Union
    initiatives = get_num(props, "Qualifying")          # Client Initiatives
    upsell      = get_num(props, "Summarize")           # Upsell Discovery
    next_steps  = get_num(props, "Next Steps")
    coaching    = get_text(props, "Top Coaching Point")
    robins_take = get_text(props, "Robin's Take")

    if score == 0:
        continue

    rep = infer_rep(robins_take, coaching)

    record = {
        "title":         title,
        "account":       account or title,
        "date":          date,
        "score":         score,
        "approach":      approach,
        "company_story": sotu,
        "qualifying":    initiatives,
        "summarize":     upsell,
        "next_steps":    next_steps,
        "coaching":      coaching,
    }
    rep_records[rep].append(record)
    print(f"  [{rep or 'UNKNOWN'}] {title[:50]} | {date} | score={score} | A={approach} SotU={sotu} Init={initiatives} Up={upsell} NS={next_steps}")

print(f"\nAttribution summary:")
for rep, recs in rep_records.items():
    print(f"  {rep}: {len(recs)} records")

# ── Update summaries ─────────────────────────────────────────────────────────
with open("/tmp/coaching_summaries.json") as f:
    summaries = json.load(f)

# Remove any existing CBR-based CSA entries to rebuild clean
for csa in ["Ingrid Beard", "Justin Lee"]:
    summaries.pop(csa, None)

for rep, records in rep_records.items():
    if not records or rep is None:
        continue

    records_sorted = sorted(records, key=lambda r: r.get("date","") or "", reverse=True)
    scores = [r["score"] for r in records]
    avg_score = round(sum(scores) / len(scores)) if scores else 0

    def cat_avg(key):
        vals = [r[key] for r in records if r.get(key, 0) > 0]
        return round(sum(vals) / len(vals), 1) if vals else 0

    cat_avgs = {
        "approach":      cat_avg("approach"),
        "company_story": cat_avg("company_story"),
        "qualifying":    cat_avg("qualifying"),
        "summarize":     cat_avg("summarize"),
        "next_steps":    cat_avg("next_steps"),
    }

    recent_calls = [
        {"account": r["account"] or r["title"], "title": r["title"], "score": r["score"]}
        for r in records_sorted[:4]
    ]

    seen, coaching_pts = set(), []
    for r in records_sorted:
        pt = (r.get("coaching") or "").strip()
        if pt and pt not in seen:
            seen.add(pt)
            coaching_pts.append(pt)
        if len(coaching_pts) >= 5:
            break

    top_3 = "\n".join(f"{i+1}. {pt}" for i, pt in enumerate(coaching_pts[:5]))

    summaries[rep] = {
        "avg_score":   avg_score,
        "call_count":  len(records),
        "cat_avgs":    cat_avgs,
        "recent_calls": recent_calls,
        "top_3":       top_3,
    }
    print(f"\n✅ {rep}: {len(records)} CBRs | avg={avg_score} | cats={cat_avgs}")

with open("/tmp/coaching_summaries.json", "w") as f:
    json.dump(summaries, f, indent=2)

print(f"\nUpdated /tmp/coaching_summaries.json — {len(summaries)} reps total")
print("Reps in file:", sorted(summaries.keys()))
