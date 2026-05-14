#!/usr/bin/env python3
"""
Fetch all scorecard data from Notion Sales Meeting Coaching DB
and write /tmp/coaching_summaries.json for build_coaching_dashboard.py
"""

import json
import requests
from collections import defaultdict

NOTION_TOKEN = "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"
NOTION_DB_ID = "333a59b7-e7b2-8062-8068-fc0116ff82f7"

# Reverse map Notion user ID → rep name
REP_NOTION_IDS = {
    "Connor Flynn":     "2aed872b-594c-8122-843b-00026718f719",
    "Davis Herndon":    "2bed872b-594c-8153-84bd-0002be71650f",
    "Husam Zalmiyar":   "2aed872b-594c-817f-a77f-00024ab1c62d",
    "Ingrid Beard":     "2bed872b-594c-817f-bd06-000298f4426f",
    "Jake Borah":       "2afd872b-594c-81ad-ba10-00026220028a",
    "Jake Mitchell":    "2bed872b-594c-8146-bec8-00027f20933b",
    "Jaylin Bender":    "2aed872b-594c-81a4-a920-00022ae85160",
    "Justin Lee":       "2aed872b-594c-813e-a455-00027973e56a",
    "Patrick Davies":   "2bed872b-594c-8199-a38b-0002beb8d93e",
    "Patrick Dahlstrom":"2a3d872b-594c-815f-9544-00029998456f",
    "Andrew Whisenant": "2a3d872b-594c-813d-9397-0002de289b31",
    "Andy Whisenant":   "2a3d872b-594c-813d-9397-0002de289b31",
    "Jamie Butler":     "2a3d872b-594c-81cd-9cd2-0002a6efd08e",
    "Joseph Abarno":    "2a3d872b-594c-8136-969c-0002c8328dc1",
    "Nassim Filoso":    "2bed872b-594c-8191-90b5-00022057fec4",
    "Olivia Sandefur":  "2b6d872b-594c-81e7-a3c6-0002c20dd9a5",
}
NOTION_ID_TO_REP = {v: k for k, v in REP_NOTION_IDS.items() if k not in ("Andy Whisenant",)}

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def get_prop_number(props, key):
    p = props.get(key, {})
    return p.get("number") or 0

def get_prop_text(props, key):
    p = props.get(key, {})
    rt = p.get("rich_text", [])
    if rt:
        return "".join(t.get("plain_text","") for t in rt)
    return ""

def get_prop_title(props, key):
    p = props.get(key, {})
    rt = p.get("title", [])
    if rt:
        return "".join(t.get("plain_text","") for t in rt)
    return ""

def get_prop_date(props, key):
    p = props.get(key, {})
    d = p.get("date", {})
    return (d or {}).get("start", "")

def get_prop_people(props, key):
    p = props.get(key, {})
    people = p.get("people", [])
    names = []
    for person in people:
        uid = person.get("id","")
        name = NOTION_ID_TO_REP.get(uid) or person.get("name","Unknown")
        names.append(name)
    return names

# Fetch all pages from Notion DB
def fetch_all_pages():
    pages = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=headers,
            json=payload
        )
        r.raise_for_status()
        data = r.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages

print("Fetching Notion scorecards...")
pages = fetch_all_pages()
print(f"  Total records: {len(pages)}")

# Group by rep
rep_records = defaultdict(list)
for page in pages:
    props = page.get("properties", {})
    reps = get_prop_people(props, "Sales Rep")
    if not reps:
        continue
    rep = reps[0]

    record = {
        "title": get_prop_title(props, "Meeting Title"),
        "account": get_prop_text(props, "Prospect / Account"),
        "date": get_prop_date(props, "Meeting Date"),
        "score": get_prop_number(props, "Overall Score"),
        "approach": get_prop_number(props, "Approach"),
        "company_story": get_prop_number(props, "Company Story"),
        "qualifying": get_prop_number(props, "Qualifying"),
        "summarize": get_prop_number(props, "Summarize"),
        "next_steps": get_prop_number(props, "Next Steps"),
        "coaching": get_prop_text(props, "Top Coaching Point"),
    }
    if record["score"] > 0:
        rep_records[rep].append(record)

# Build summaries
summaries = {}
for rep, records in rep_records.items():
    if not records:
        continue

    # Sort by date descending
    records_sorted = sorted(records, key=lambda r: r["date"] or "", reverse=True)

    scores = [r["score"] for r in records if r["score"] > 0]
    avg_score = round(sum(scores) / len(scores)) if scores else 0

    # Category averages (only over records that have non-zero values for that category)
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

    # Recent calls (last 4)
    recent_calls = [
        {"account": r["account"] or r["title"], "title": r["title"], "score": r["score"]}
        for r in records_sorted[:4]
    ]

    # Top 3 coaching points: unique from most recent coaching notes
    seen = set()
    coaching_pts = []
    for r in records_sorted:
        pt = (r.get("coaching") or "").strip()
        if pt and pt not in seen:
            seen.add(pt)
            coaching_pts.append(pt)
        if len(coaching_pts) >= 5:
            break

    top_3 = "\n".join(f"{i+1}. {pt}" for i, pt in enumerate(coaching_pts[:5]))

    summaries[rep] = {
        "avg_score": avg_score,
        "call_count": len(records),
        "cat_avgs": cat_avgs,
        "recent_calls": recent_calls,
        "top_3": top_3,
    }
    print(f"  {rep}: {len(records)} calls, avg {avg_score}, cats={cat_avgs}")

with open("/tmp/coaching_summaries.json", "w") as f:
    json.dump(summaries, f, indent=2)

print(f"\n✅ Wrote /tmp/coaching_summaries.json with {len(summaries)} reps")
