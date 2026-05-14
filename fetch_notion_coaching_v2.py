#!/usr/bin/env python3
"""
Fetch all scorecard data from Notion, re-parse category scores from page body text,
and write /tmp/coaching_summaries.json for build_coaching_dashboard.py
"""

import json, re, time, requests
from collections import defaultdict

NOTION_TOKEN = "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"
NOTION_DB_ID = "333a59b7-e7b2-8062-8068-fc0116ff82f7"

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
NOTION_ID_TO_REP = {}
for name, uid in REP_NOTION_IDS.items():
    if uid not in NOTION_ID_TO_REP:
        NOTION_ID_TO_REP[uid] = name

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def notion_get(url, retries=3):
    for attempt in range(retries):
        r = requests.get(url, headers=headers)
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", 1))
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait + 0.5)
            continue
        r.raise_for_status()
        return r.json()
    raise Exception(f"Failed after {retries} retries: {url}")

def notion_post(url, payload, retries=3):
    for attempt in range(retries):
        r = requests.post(url, headers=headers, json=payload)
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", 1))
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait + 0.5)
            continue
        r.raise_for_status()
        return r.json()
    raise Exception(f"Failed after {retries} retries")

def get_prop_number(props, key):
    return (props.get(key) or {}).get("number") or 0

def get_prop_text(props, key):
    rt = (props.get(key) or {}).get("rich_text", [])
    return "".join(t.get("plain_text","") for t in rt)

def get_prop_title(props, key):
    rt = (props.get(key) or {}).get("title", [])
    return "".join(t.get("plain_text","") for t in rt)

def get_prop_date(props, key):
    d = (props.get(key) or {}).get("date") or {}
    return d.get("start", "")

def get_prop_people(props, key):
    people = (props.get(key) or {}).get("people", [])
    return [NOTION_ID_TO_REP.get(p.get("id",""), p.get("name","Unknown")) for p in people]

def fetch_all_pages():
    pages, cursor = [], None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_post(f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query", payload)
        pages.extend(data.get("results", []))
        print(f"  Fetched {len(pages)} pages...")
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages

def fetch_page_text(page_id):
    """Fetch all block text content from a Notion page."""
    data = notion_get(f"https://api.notion.com/v1/blocks/{page_id}/children")
    blocks = data.get("results", [])
    parts = []
    for b in blocks:
        btype = b.get("type", "")
        content = b.get(btype, {})
        rt = content.get("rich_text", [])
        text = "".join(t.get("plain_text","") for t in rt)
        if text:
            parts.append(text)
    return "\n".join(parts)

def parse_category_scores(text):
    """Extract BEACON category scores from scorecard text."""
    cats = {}
    patterns = [
        ("approach",      r'The Approach\s*[—-]\s*(\d+)/\d+'),
        ("company_story", r'Company Story\s*[—-]\s*(\d+)/\d+'),
        ("qualifying",    r'Qualifying[^—\n]*[—-]\s*(\d+)/\d+'),
        ("summarize",     r'Summarize[^—\n]*[—-]\s*(\d+)/\d+'),
        ("next_steps",    r'Next Steps[^—\n]*[—-]\s*(\d+)/\d+'),
    ]
    for key, pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            cats[key] = int(m.group(1))
        else:
            cats[key] = 0
    return cats

def parse_top_coaching(text):
    """Extract top coaching priorities from scorecard text."""
    m = re.search(r'Top 3 Coaching[^\n]*\n(.*?)(?:\n##|\n---|\Z)', text, re.DOTALL)
    if not m:
        return ""
    section = m.group(1).strip()
    lines = [l.strip() for l in section.split("\n") if l.strip()]
    pts = []
    for line in lines:
        clean = re.sub(r'^[\d]+[\.\)]\s*', '', line).strip()
        if clean and not clean.startswith('#'):
            pts.append(clean)
        if len(pts) >= 5:
            break
    return "\n".join(f"{i+1}. {p}" for i, p in enumerate(pts))

# ── Main ──────────────────────────────────────────────────────────────────────
print("Fetching all Notion pages...")
pages = fetch_all_pages()
print(f"Total pages: {len(pages)}")

rep_records = defaultdict(list)
errors = 0

for i, page in enumerate(pages):
    props = page.get("properties", {})
    reps = get_prop_people(props, "Sales Rep")
    if not reps:
        continue
    rep = reps[0]

    # Base data from properties
    score = get_prop_number(props, "Overall Score")
    record = {
        "title":    get_prop_title(props, "Meeting Title"),
        "account":  get_prop_text(props, "Prospect / Account"),
        "date":     get_prop_date(props, "Meeting Date"),
        "score":    score,
        "coaching": get_prop_text(props, "Top Coaching Point"),
    }

    # Check if category data is missing — if so, fetch from page body
    approach = get_prop_number(props, "Approach")
    qualifying = get_prop_number(props, "Qualifying")
    needs_parse = (approach == 0 and qualifying == 0 and score > 0)

    if needs_parse:
        try:
            page_text = fetch_page_text(page["id"])
            cats = parse_category_scores(page_text)
            coaching_parsed = parse_top_coaching(page_text)
            if not record["coaching"] and coaching_parsed:
                record["coaching"] = coaching_parsed
        except Exception as e:
            cats = {"approach":0,"company_story":0,"qualifying":0,"summarize":0,"next_steps":0}
            errors += 1
        time.sleep(0.15)  # gentle rate limit
    else:
        cats = {
            "approach":      get_prop_number(props, "Approach"),
            "company_story": get_prop_number(props, "Company Story"),
            "qualifying":    get_prop_number(props, "Qualifying"),
            "summarize":     get_prop_number(props, "Summarize"),
            "next_steps":    get_prop_number(props, "Next Steps"),
        }

    record.update(cats)

    if score > 0:
        rep_records[rep].append(record)

    if (i+1) % 50 == 0:
        print(f"  Processed {i+1}/{len(pages)}...")

print(f"\nProcessed all pages. Errors: {errors}")

# Build summaries
summaries = {}
for rep, records in rep_records.items():
    if not records:
        continue

    records_sorted = sorted(records, key=lambda r: r.get("date","") or "", reverse=True)
    scores = [r["score"] for r in records if r["score"] > 0]
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

    # Collect unique coaching points from recent calls
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
        "avg_score": avg_score,
        "call_count": len(records),
        "cat_avgs": cat_avgs,
        "recent_calls": recent_calls,
        "top_3": top_3,
    }
    print(f"  {rep}: {len(records)} calls, avg {avg_score} | cats={cat_avgs}")

with open("/tmp/coaching_summaries.json", "w") as f:
    json.dump(summaries, f, indent=2)

print(f"\n✅ Done — {len(summaries)} reps written to /tmp/coaching_summaries.json")
