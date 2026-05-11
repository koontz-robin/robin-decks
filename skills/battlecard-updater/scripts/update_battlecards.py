#!/usr/bin/env python3
"""
Battle Card Updater — ADDITIVE MODE
- Reads existing battle-cards.html
- Injects/updates "Field Intelligence" section into existing competitor tabs
- Adds new tabs for competitors not yet in the page
- Never removes or overwrites existing content
"""

import requests, json, os, re, subprocess
from datetime import datetime, timezone
from collections import defaultdict

NOTION_TOKEN = "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"
COMPETITOR_DB_ID = "6182cc09f1e34d03973e23247a25d069"
REPO_PATH = "/tmp/robin-decks"
SSH_KEY = "/home/openclaw/.openclaw/ssh/id_ed25519"
OUTPUT_FILE = f"{REPO_PATH}/battle-cards.html"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
}

# Map competitor names to existing tab IDs in the HTML
COMP_TO_TAB_ID = {
    "ConnectWise": "connectwise",
    "Autotask": "autotask",
    "Halo PSA": "halo",
    "Halo": "halo",
    "Syncro": "syncro",
    "Superops": "superops",
}


def pull_notion_data():
    all_pages = []
    has_more, cursor = True, None
    while has_more:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{COMPETITOR_DB_ID}/query",
                          headers=NOTION_HEADERS, json=body)
        r.raise_for_status()
        data = r.json()
        all_pages.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")

    print(f"Pulled {len(all_pages)} mentions from Notion")

    by_comp = defaultdict(lambda: {"positive": [], "negative": [], "neutral": []})
    for p in all_pages:
        props = p.get("properties", {})
        comp_sel = (props.get("Competitor") or {}).get("select") or {}
        comp = comp_sel.get("name", "")
        if not comp or comp == "Other":
            continue
        sent = ((props.get("Sentiment") or {}).get("select") or {}).get("name","Neutral").lower()
        context = "".join(t.get("plain_text","") for t in (props.get("Context") or {}).get("rich_text",[]))
        mention = "".join(t.get("plain_text","") for t in (props.get("Mention") or {}).get("title",[]))
        date = ((props.get("Meeting Date") or {}).get("date") or {}).get("start","")
        if context:
            by_comp[comp][sent].append({
                "mention": mention, "context": context,
                "date": date[:10] if date else "",
            })
    return dict(by_comp)


def distill_field_intel(comp, field_data):
    """Use Claude to distill raw mentions into 2-3 high-signal insights per competitor."""
    try:
        import anthropic
        all_mentions = []
        for sentiment, items in field_data.items():
            for item in items:
                all_mentions.append(f"[{sentiment.upper()}] {item['context']}")

        if not all_mentions:
            return {"pain_points": [], "strengths": []}

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content": f"""You are curating a competitive battle card for {comp} based on real prospect quotes from sales discovery calls.

Raw mentions from prospects:
{chr(10).join(all_mentions[:15])}

Extract the TOP 2-3 most actionable pain points (things prospects dislike or struggle with) and the TOP 1-2 genuine strengths (things prospects actually appreciate).

Rules:
- Only include SIGNIFICANT, RECURRING themes — not one-off mentions
- Each point should be a crisp 1-sentence insight that a sales rep can USE in a conversation
- Do NOT include generic complaints like "it's expensive" unless it's specific
- Do NOT include anything about Rev.io itself
- No individual names

Respond in JSON only:
{{"pain_points": ["...", "..."], "strengths": ["...", "..."]}}

If there's not enough signal for a category, return an empty list for it."""}]
        )
        import json, re
        text = msg.content[0].text.strip()
        text = re.sub(r'```(?:json)?', '', text).strip().rstrip('`').strip()
        return json.loads(text)
    except Exception as e:
        print(f"  ⚠️  Distill failed for {comp}: {e}")
        # Fallback: just return top items
        return {
            "pain_points": [item["context"][:120] for item in sorted(field_data.get("negative",[]), key=lambda x: len(x["context"]), reverse=True)[:2]],
            "strengths": [item["context"][:120] for item in sorted(field_data.get("positive",[]), key=lambda x: len(x["context"]), reverse=True)[:1]],
        }


def build_field_intel_block(comp, field_data, now):
    """Build the HTML block for field intelligence. Used for injection."""
    total = sum(len(v) for v in field_data.values())
    if total == 0:
        return ""

    print(f"    Distilling {total} mentions for {comp}...")
    intel = distill_field_intel(comp, field_data)
    pain_points = intel.get("pain_points", [])
    strengths = intel.get("strengths", [])

    if not pain_points and not strengths:
        return ""

    neg_html = ""
    for pt in pain_points:
        neg_html += f'''<div style="background:#1a0808;border-left:3px solid #ff4466;padding:10px 12px;border-radius:4px;margin-bottom:8px">
          <div style="font-size:13px;color:#e2e8f0">{pt}</div>
        </div>'''

    pos_html = ""
    for pt in strengths:
        pos_html += f'''<div style="background:#081a08;border-left:3px solid #00ff88;padding:10px 12px;border-radius:4px;margin-bottom:8px">
          <div style="font-size:13px;color:#e2e8f0">{pt}</div>
        </div>'''

    return f'''
<!-- FIELD_INTEL_START:{comp} updated:{now} -->
<div class="section-title">🎙️ Field Intelligence — What Prospects Say ({total} raw mentions)</div>
{f'<div style="margin-bottom:8px"><div style="font-size:11px;color:#ff4466;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Key Pain Points</div>{neg_html}</div>' if neg_html else ""}
{f'<div><div style="font-size:11px;color:#00ff88;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Genuine Strengths</div>{pos_html}</div>' if pos_html else ""}
<!-- FIELD_INTEL_END:{comp} -->'''


def build_new_tab_section(comp, field_data, now):
    """Build a complete new section for a competitor not yet in the page."""
    tab_id = comp.lower().replace(" ", "-").replace("/", "-")
    field_block = build_field_intel_block(comp, field_data, now)
    total = sum(len(v) for v in field_data.values())

    return tab_id, f'''
  <div id="{tab_id}" class="section">
    <h2 style="font-size:18px;color:#e2e8f0;margin-bottom:4px">{comp} <span style="font-size:11px;color:#ffcc00;background:#1a1400;border:1px solid #ffcc00;padding:2px 8px;border-radius:10px;margin-left:8px">🎙️ {total} field mentions</span></h2>
    <p style="color:#94a3b8;font-size:12px;margin-bottom:20px">Field intelligence only — no static battle card yet</p>
    {field_block}
  </div>
'''


def inject_into_existing(html, tab_id, comp, field_block):
    """Inject or replace field intel block inside an existing section."""
    pattern = re.compile(
        rf'(<!-- FIELD_INTEL_START:{re.escape(comp)}.*?<!-- FIELD_INTEL_END:{re.escape(comp)} -->)',
        re.DOTALL
    )
    if pattern.search(html):
        # Replace existing block
        html = pattern.sub(field_block, html)
        print(f"  ↺ Updated field intel for {comp}")
    else:
        # Inject after the EXACT section opening div — must be class="section"
        section_pattern = re.compile(
            rf'(<div\s+(?:id="{re.escape(tab_id)}"\s+class="section"|class="section[^"]*"\s+id="{re.escape(tab_id)}")>)',
        )
        m = section_pattern.search(html)
        if not m:
            # Also try without class requirement
            m = re.search(rf'<div\s+id="{re.escape(tab_id)}"[^>]*class="section[^"]*"', html)
        if m:
            insert_after = m.end()
            html = html[:insert_after] + "\n" + field_block + html[insert_after:]
            print(f"  ✅ Injected field intel into {comp} tab")
        else:
            print(f"  ⚠️  Could not find section #{tab_id} for {comp}")
    return html


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== Battle Card Updater {now} ===")

    # Ensure repo is up to date
    env = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no"}
    if not os.path.exists(REPO_PATH):
        subprocess.run(["git", "clone", "git@github.com:koontz-robin/robin-decks.git", REPO_PATH],
                       env=env, check=True)
    else:
        subprocess.run(["git", "pull", "origin", "master"], cwd=REPO_PATH, env=env)

    with open(OUTPUT_FILE, "r") as f:
        html = f.read()

    notion_data = pull_notion_data()

    new_tabs_html = ""
    new_sections_html = ""

    for comp, field_data in notion_data.items():
        total = sum(len(v) for v in field_data.values())
        if total < 2:
            print(f"  ⏭️  {comp}: only {total} mention(s), skipping (need 2+)")
            continue

        field_block = build_field_intel_block(comp, field_data, now)
        if not field_block:
            continue

        # Check if this competitor already has a tab
        tab_id = COMP_TO_TAB_ID.get(comp)
        if not tab_id:
            # Try fuzzy match on existing IDs
            gen_id = comp.lower().replace(" ", "-").replace("/", "-")
            if f'id="{gen_id}"' in html:
                tab_id = gen_id

        if tab_id and f'id="{tab_id}"' in html:
            html = inject_into_existing(html, tab_id, comp, field_block)
        else:
            # New competitor — build new tab
            tab_id, section = build_new_tab_section(comp, field_data, now)
            new_tabs_html += f'<button class="nav-tab" onclick="showTab(\'{tab_id}\', this)">{comp}</button>\n'
            new_sections_html += section
            print(f"  ➕ New tab for {comp}")

    # Inject new tabs before closing </div> of nav-tabs
    if new_tabs_html:
        html = html.replace("</div>\n<main>", f"{new_tabs_html}</div>\n<main>", 1)

    # Inject new sections before </main>
    if new_sections_html:
        html = html.replace("</main>", new_sections_html + "\n</main>", 1)

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)

    # Push to GitHub
    subprocess.run(["git", "add", "battle-cards.html"], cwd=REPO_PATH, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_PATH)
    if diff.returncode == 0:
        print("No changes to push.")
        return

    subprocess.run(["git", "commit", "-m", f"Battle cards field intel update - {now}"],
                   cwd=REPO_PATH, check=True)
    subprocess.run(["git", "push", "origin", "master"], cwd=REPO_PATH, env=env, check=True)
    print(f"\n✅ Battle cards updated and pushed!")
    print(f"URL: https://htmlpreview.github.io/?https://github.com/koontz-robin/robin-decks/blob/master/battle-cards.html")


if __name__ == "__main__":
    main()
