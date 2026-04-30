#!/usr/bin/env python3
"""
Client Business Review (CBR) Auto-Grader
- Polls Outreach Kaia for new "Client Business Review" meetings > 20 min
- Grades each transcript against the CBR rubric using Claude
- Posts scorecard to Discord #meeting-scorecards
- Updates SF Rapport_Bio__c with personal details
- Logs competitor mentions to Notion
"""

import json
import os
import re
import requests
import anthropic
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────────────
OUTREACH_CLIENT_ID     = "mWU~jYqsr3dE-TYMAyu9a5DocFAt3k5bxEhsE6WUXqDI"
OUTREACH_CLIENT_SECRET = "&t|jA1vH$E;'|gDGy>[O@$q@gH-<q;y;(cIZp~&5hFA"
OUTREACH_TOKEN_FILE    = "/home/openclaw/.openclaw/workspace/outreach_tokens.json"
DISCORD_CHANNEL_ID     = "1488240821626077246"  # #meeting-scorecards
STATE_FILE             = "/home/openclaw/.openclaw/workspace/cbr-grader-state.json"
MIN_DURATION_SECONDS   = 20 * 60  # 20 minutes

CBR_RUBRIC = """
You are grading a Rev.io Client Business Review (CBR) call. Score 0-100.

## SCORING CATEGORIES

### 1. THE APPROACH (15 pts)
- Warm-up and rapport building (NOT about decision-making process — this is an existing client)
- Set a clear agenda for the call
- Confirmed all key stakeholders are present
- Created a collaborative, positive tone to open

Score 13-15: Strong warm-up, clear agenda shared, right people confirmed, positive tone set
Score 9-12: Some warm-up, loose agenda, most elements present
Score 5-8: Jumped into content without agenda or rapport, client not fully engaged
Score 0-4: No warm-up, no agenda, call felt abrupt or transactional

### 2. REV.IO STATE OF THE UNION (20 pts)
- Delivered the scripted State of the Union presentation — following the deck earns full credit here
- Covered Rev.io product updates or new features relevant to the client
- Referenced account-specific data where available (usage, tickets, billing, milestones)
- Tie-downs are encouraged but NOT required — presentation is scripted so following it correctly earns full credit

Score 18-20: Delivered the SotU presentation with energy, covered product updates, referenced their account
Score 13-17: SotU covered but missing specifics or low energy delivery
Score 8-12: Basic check-in with no structure, skipped parts of the presentation
Score 0-7: State of the Union not delivered — went straight to other topics

### 3. UNDERSTANDING CURRENT CLIENT INITIATIVES (25 pts)
- Asked open-ended questions about what's changed in their business since last touch
- Uncovered new goals, priorities, pain points, or growth plans
- Explored how Rev.io fits into their current strategic direction
- Asked about team changes, acquisitions, new service lines

Score 22-25: Multiple open-ended questions, surfaced meaningful business context and changes
Score 16-21: Asked some initiative questions, got partial picture
Score 9-15: Surface-level check-in, accepted vague answers
Score 0-8: No initiative discovery — missed the opportunity entirely

### 4. UPSELL OPPORTUNITY DISCOVERY (30 pts)
This is the highest-weighted category — scored by COUNTING specific qualifying questions asked from the approved lists below.

**SCORING: Count how many of the following specific questions (or close equivalents) were asked:**

**Cyber Protection Questions:**
- Who do you use for RMM (Remote Monitoring Management)?
- Who do you use for EDR (Endpoint Detection & Response)?
- Who does your Cloud Backup Storage?
- Are you passing RMM cost through to your end customer?
- What is your tech-to-endpoint ratio?
- How do you patch Windows or Third-Party Apps today? How long does that take?
- Do you have vulnerability visibility and patch compliance per client?
- Where do tickets pile up (patching, slow PCs, remote access, monitoring)?
- How many tools do you use for remote support, monitoring, patching, and reporting?
- Have you had any security incidents in the last 12 months?
- How do you investigate endpoint alerts today? Who owns the response?
- Do clients ask for EDR, cyber insurance controls, or compliance evidence?
- If a bad endpoint is found, how fast can you isolate it and confirm cleanup?

**Billing Add-On Questions:**
- Have your customers requested additional functionality in the bill center portal?
- Have your customers requested multiple portal users (different logins)?
- Do you have multi-location (parent/child) accounts?
- Do you have an internal sales team, or do you sell through the channel with agents?
- How are you calculating agent commissions today? Is that a manual process?
- Do you use QB Online or NetSuite? If yes, how are you getting billing info into it each month?
- Do you currently use ConnectWise?
- Do you have any additional reporting or analytic tools you use today? Have you seen our analytics dashboard?
- Do you currently have resellers? Have they asked for assistance billing for services they resell?
- Who do you use to process your CC/ACH payments today?
- When is the last time you looked at the rates you currently pay?
- Would you be interested in a side-by-side analysis displaying potential monthly savings?
- Do you use any software like bill.com to handle vendor payments?
- Do you receive any monthly kickback based on the amount of spend each month?

**SCORING SCALE:**
- 10+ qualifying questions asked → 30 pts (FULL CREDIT)
- 7-9 questions → 22 pts
- 4-6 questions → 14 pts
- 1-3 questions → 6 pts
- 0 questions → 0 pts

In the scorecard, explicitly state:
"Qualifying questions asked: X/27 | Questions counted: [list the ones that were asked]"

### 5. NEXT STEPS / SUMMARIZING ACTION ITEMS (10 pts)
- Summarized all action items discussed on the call
- Each action item has a clear owner and timeline
- Client confirmed agreement on next steps
- Follow-up meeting or demo booked if applicable

Score 9-10: Full summary of action items with owners and dates, client confirmed, next meeting set
Score 6-8: Some action items captured, not all have owners/dates
Score 3-5: Vague "I'll follow up" without specific commitments
Score 0-2: No action items summarized, call ended without clear next steps

## GRADE THRESHOLDS
🟢 90-100 = Elite | 🔵 80-89 = Strong | 🟡 65-79 = Solid | 🟠 50-64 = Needs Work | 🔴 <50 = Coaching Required
"""

REP_DISCORD_IDS = {
    "Jamie Butler":    None,
    "Jaylin Bender":   None,
    "Andy Whisenant":  None,
    "Jake Borah":      None,
    "Patrick Davies":  None,
    "Connor Flynn":    None,
    "Husam Zalmiyar":  None,
    "Ingrid Beard":    None,
    "Justin Lee":      None,
}


def get_outreach_token():
    with open(OUTREACH_TOKEN_FILE) as f:
        tokens = json.load(f)
    r = requests.post("https://api.outreach.io/oauth/token", data={
        "client_id": OUTREACH_CLIENT_ID,
        "client_secret": OUTREACH_CLIENT_SECRET,
        "redirect_uri": "https://localhost",
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    })
    if r.ok:
        tokens.update(r.json())
        with open(OUTREACH_TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    return tokens["access_token"]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"graded_ids": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_new_cbr_calls(at, already_graded):
    headers = {"Authorization": f"Bearer {at}"}
    r = requests.get(
        "https://api.outreach.io/api/v2/kaiaRecordings"
        "?filter[format]=meeting&page[size]=50&sort=-createdAt"
        "&fields[kaiaRecording]=title,startTime,endTime,format,state,mediaDurationSeconds,botInMeetingSeconds,transcriptUrl",
        headers=headers
    )
    r.raise_for_status()
    recordings = r.json().get("data", [])

    new_calls = []
    for rec in recordings:
        rid = rec["id"]
        attrs = rec.get("attributes", {})
        if rid in already_graded:
            continue
        if attrs.get("state") != "ENDED":
            continue

        title = attrs.get("title") or ""
        # Match "Client Business Review" in title
        if "client business review" not in title.lower() and "cbr" not in title.lower():
            continue

        duration = int(attrs.get("mediaDurationSeconds") or attrs.get("botInMeetingSeconds") or 0)
        if duration < MIN_DURATION_SECONDS:
            print(f"  Skipping {title[:50]} — only {duration//60} min")
            continue

        new_calls.append(rec)

    return new_calls


def fetch_transcript(at, rec_id):
    headers = {"Authorization": f"Bearer {at}"}
    r = requests.get(
        f"https://api.outreach.io/api/v2/kaiaRecordings/{rec_id}"
        "?fields[kaiaRecording]=title,startTime,transcriptUrl",
        headers=headers
    )
    r.raise_for_status()
    attrs = r.json()["data"]["attributes"]
    transcript_url = attrs.get("transcriptUrl")
    if not transcript_url:
        return None, None
    t = requests.get(transcript_url)
    t.raise_for_status()
    if not t.text.strip():
        print(f"  Transcript URL returned empty body — still processing, will retry next run.")
        return None, None
    try:
        return t.json(), attrs.get("title")
    except Exception as e:
        print(f"  Transcript URL returned non-JSON (len={len(t.text)}) — {e}")
        return None, None


def format_transcript(transcript_json):
    utterances = transcript_json.get("utterances", [])
    lines, prev_speaker = [], None
    for u in utterances:
        speaker = u.get("speaker", {}).get("displayName", "Unknown")
        text = u.get("text", "").strip()
        if not text:
            continue
        if speaker != prev_speaker:
            lines.append(f"\n{speaker}: {text}")
            prev_speaker = speaker
        else:
            lines[-1] += f" {text}"
    return "\n".join(lines).strip()


def grade_call(transcript_text, title, duration_seconds):
    client = anthropic.Anthropic()
    duration_min = duration_seconds // 60

    prompt = f"""You are grading a Rev.io Client Business Review (CBR) call. Call: "{title}" | Duration: {duration_min} minutes

{CBR_RUBRIC}

## TRANSCRIPT
{transcript_text[:40000]}

## YOUR TASK
Grade this call and respond in EXACTLY this format:

# 📋 CBR Grade: [Rep Name] — [Client/Account] — [Date]

## Overall Score: XX/100 — [GRADE]

---

## Scorecard

### 1. The Approach — XX/15
**What they did well:** ...
**What was missing:** ...
**Key moment:** "..."

### 2. Rev.io State of the Union — XX/20
**What they did well:** ...
**What was missing:** ...
**Key moment:** "..."

### 3. Current Client Initiatives — XX/25
**What they did well:** ...
**What was missing:** ...
**Key moment:** "..."

### 4. Upsell Opportunity Discovery — XX/30
**Qualifying questions asked:** X/27
**Questions counted:** [list each one asked]
**What they did well:** ...
**What was missing:** ...

### 5. Next Steps / Action Items — XX/10
**Action items documented:** [list them]
**What they did well:** ...
**What was missing:** ...

---

## Top 3 Coaching Points
1. ...
2. ...
3. ...

## What to Reinforce
- ...

## Robin's Take
[1-2 sentence honest overall read]

Be direct. Cite what actually happened on the call."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2200,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


def get_discord_token():
    with open("/home/openclaw/.openclaw/openclaw.json") as f:
        raw = f.read()
    tokens = re.findall(r'[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}', raw)
    return tokens[0] if tokens else None


def get_rep_mention(scorecard_text):
    match = re.search(r'CBR Grade:\s*([^—\n]+)', scorecard_text)
    if not match:
        return None, None
    rep_name = match.group(1).strip()
    for name, discord_id in REP_DISCORD_IDS.items():
        if name.lower() in rep_name.lower() or rep_name.lower() in name.lower():
            if discord_id:
                return name, f"<@{discord_id}>"
            else:
                return name, f"@{rep_name}"
    return rep_name, f"@{rep_name}"


def grade_color(score):
    if score >= 90: return 0x22c55e
    elif score >= 80: return 0x3b82f6
    elif score >= 65: return 0xeab308
    elif score >= 50: return 0xf97316
    else: return 0xef4444


def grade_label(score):
    if score >= 90: return "🟢 Elite"
    elif score >= 80: return "🔵 Strong"
    elif score >= 65: return "🟡 Solid"
    elif score >= 50: return "🟠 Needs Work"
    else: return "🔴 Coaching Required"


def parse_scorecard(scorecard_text):
    score_match = re.search(r'Overall Score:\s*(\d+)/100', scorecard_text)
    score = int(score_match.group(1)) if score_match else 0

    header_match = re.search(r'CBR Grade:\s*([^—\n]+?)(?:\s*—\s*([^—\n]+?))?(?:\s*—\s*([^\n]+))?\s*$', scorecard_text, re.MULTILINE)
    rep = header_match.group(1).strip() if header_match else "Unknown Rep"
    account = header_match.group(2).strip() if header_match and header_match.group(2) else "Unknown Account"

    cats = {}
    for cat, pts in [("The Approach", 15), ("State of the Union", 20), ("Current Client", 25), ("Upsell", 30), ("Next Steps", 10)]:
        m = re.search(rf'{cat}[^—\n]*—\s*(\d+)/{pts}', scorecard_text)
        cats[cat] = f"{m.group(1)}/{pts}" if m else f"?/{pts}"

    # Extract upsell question count
    q_match = re.search(r'Qualifying questions asked:\s*(\d+)', scorecard_text, re.I)
    q_count = q_match.group(1) if q_match else "?"
    psa = q_count  # repurpose for display
    cyber = "—"
    addon = q_count

    coaching_match = re.search(r'Top 3 Coaching Points\s*\n1\.\s*(.+)', scorecard_text)
    coaching = coaching_match.group(1).strip() if coaching_match else ""

    return score, rep, account, cats, coaching, psa, cyber, addon


def post_to_notion(scorecard_text, title, start_time=None):
    """Push CBR scorecard to the Sales Meeting Coaching Notion DB."""
    NOTION_TOKEN = "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"
    NOTION_DB_ID = "333a59b7e7b280628068fc0116ff82f7"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    score, rep, account, cats, coaching, psa, cyber, addon = parse_scorecard(scorecard_text)
    take_match = re.search(r"Robin's Take\s*\n(.+?)(?:\n|$)", scorecard_text)
    robins_take = take_match.group(1).strip() if take_match else ""

    # Map CBR categories to Notion fields:
    # Approach → Approach | SotU → Company Story | Initiatives → Qualifying
    # Upsell → Summarize | Next Steps → Next Steps
    def extract_score(cat, pts):
        m = re.search(rf'{cat}[^—\n]*—\s*(\d+)/{pts}', scorecard_text)
        return int(m.group(1)) if m else None

    approach_score  = extract_score("The Approach", 15)
    sotu_score      = extract_score("State of the Union", 20)
    init_score      = extract_score("Current Client", 25)
    upsell_score    = extract_score("Upsell", 30)
    nextsteps_score = extract_score("Next Steps", 10)

    meeting_date = (start_time or "")[:10] or None

    REP_NOTION_IDS = {
        "Ingrid Beard": "2aed872b-594c-817f-a77f-00024ab1c62d",
        "Justin Lee":   "2aed872b-594c-817f-a77f-00024ab1c62d",
    }

    props = {
        "Meeting Title": {"title": [{"text": {"content": title[:200]}}]},
        "Prospect / Account": {"rich_text": [{"text": {"content": account[:200]}}]},
        "Overall Score": {"number": score},
        "Approach": {"number": approach_score},
        "Company Story": {"number": sotu_score},    # State of the Union
        "Qualifying": {"number": init_score},         # Client Initiatives
        "Summarize": {"number": upsell_score},        # Upsell Discovery
        "Next Steps": {"number": nextsteps_score},
        "Top Coaching Point": {"rich_text": [{"text": {"content": coaching[:1000]}}]},
        "Robin's Take": {"rich_text": [{"text": {"content": (robins_take + f" [CBR — Qualifying Qs: {addon}/27]")[:1000]}}]},
    }
    if meeting_date:
        props["Meeting Date"] = {"date": {"start": meeting_date}}

    notion_uid = REP_NOTION_IDS.get(rep)
    if notion_uid:
        props["Sales Rep"] = {"people": [{"id": notion_uid}]}

    r = requests.post("https://api.notion.com/v1/pages",
        headers=headers,
        json={"parent": {"database_id": NOTION_DB_ID}, "properties": props})
    if r.ok:
        print(f"  ✅ Notion page created")
        return True
    else:
        print(f"  ⚠️  Notion failed: {r.status_code} {r.text[:100]}")
        return False


def post_to_discord(scorecard_text, title, duration_seconds):
    bot_token = get_discord_token()
    if not bot_token:
        return False

    disc_headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    rep_name, rep_mention = get_rep_mention(scorecard_text)
    score, rep, account, cats, coaching, psa, cyber, addon = parse_scorecard(scorecard_text)
    duration_min = duration_seconds // 60

    embed = {
        "color": grade_color(score),
        "title": f"📋 {account}",
        "description": f"**Rep:** {rep_mention or rep}  •  **Duration:** {duration_min} min  •  *Client Business Review*",
        "fields": [
            {"name": "Overall Score", "value": f"**{score}/100** — {grade_label(score)}", "inline": False},
            {"name": "The Approach", "value": cats.get("The Approach", "?"), "inline": True},
            {"name": "State of the Union", "value": cats.get("State of the Union", "?"), "inline": True},
            {"name": "Client Initiatives", "value": cats.get("Current Client", "?"), "inline": True},
            {"name": "Upsell Discovery", "value": cats.get("Upsell", "?"), "inline": True},
            {"name": "Next Steps", "value": cats.get("Next Steps", "?"), "inline": True},
            {"name": "📊 Qualifying Questions", "value": f"Asked: {addon}/27 (need 10+ for full credit)", "inline": False},
        ],
        "footer": {"text": "Click thread for full CBR breakdown & coaching notes"}
    }
    if coaching:
        embed["fields"].append({"name": "🔑 Top Coaching Point", "value": coaching, "inline": False})

    msg = requests.post(
        f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages",
        headers=disc_headers, json={"embeds": [embed]}
    )
    msg.raise_for_status()
    message_id = msg.json()["id"]

    thread_name = f"{rep} — {account} (CBR)"[:100]
    thread = requests.post(
        f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages/{message_id}/threads",
        headers=disc_headers,
        json={"name": thread_name, "auto_archive_duration": 1440}
    )
    thread_id = thread.json()["id"]

    chunks, current = [], ""
    for line in scorecard_text.split("\n"):
        if len(current) + len(line) + 1 > 1900:
            chunks.append(current); current = line + "\n"
        else:
            current += line + "\n"
    if current:
        chunks.append(current)

    for chunk in chunks:
        requests.post(
            f"https://discord.com/api/v10/channels/{thread_id}/messages",
            headers=disc_headers, json={"content": chunk}
        )

    print(f"  ✅ CBR scorecard posted")
    return True


def main():
    print(f"=== CBR Grader {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")

    state = load_state()
    already_graded = set(state.get("graded_ids", []))

    at = get_outreach_token()
    new_calls = fetch_new_cbr_calls(at, already_graded)
    print(f"Found {len(new_calls)} new CBR call(s) to grade")

    if not new_calls:
        print("Nothing to grade.")
        return

    for rec in new_calls:
        rid = rec["id"]
        attrs = rec.get("attributes", {})
        title = attrs.get("title", "Unknown")
        duration = int(attrs.get("mediaDurationSeconds") or attrs.get("botInMeetingSeconds") or 0)

        print(f"\nGrading CBR: {title} ({duration//60} min)...")

        try:
            transcript_json, _ = fetch_transcript(at, rid)
            if not transcript_json:
                print(f"  No transcript, skipping.")
                continue

            transcript_text = format_transcript(transcript_json)
            if len(transcript_text) < 500:
                print(f"  Transcript too short, skipping.")
                continue

            print(f"  Transcript: {len(transcript_text)} chars, grading...")
            scorecard = grade_call(transcript_text, title, duration)

            print(f"  Posting to Discord...")
            post_to_discord(scorecard, title, duration)

            print(f"  Posting to Notion...")
            start_time = attrs.get("startTime")
            post_to_notion(scorecard, title, start_time=start_time)

            already_graded.add(rid)
            state["graded_ids"] = list(already_graded)
            save_state(state)

        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
