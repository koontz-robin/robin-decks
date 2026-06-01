#!/usr/bin/env python3
"""
Discovery Call Auto-Grader
- Polls Outreach Kaia for new "Discovery Call" meetings > 20 min
- Grades each transcript against the BEACON methodology using Claude
- Posts scorecard to Discord #meeting-scorecards
"""

import json
import os
import time
import requests
import anthropic
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────────────
OUTREACH_CLIENT_ID     = "mWU~jYqsr3dE-TYMAyu9a5DocFAt3k5bxEhsE6WUXqDI"
OUTREACH_CLIENT_SECRET = "&t|jA1vH$E;'|gDGy>[O@$q@gH-<q;y;(cIZp~&5hFA"
OUTREACH_TOKEN_FILE    = "/home/openclaw/.openclaw/workspace/outreach_tokens.json"

DISCORD_BOT_TOKEN      = None  # loaded from openclaw.json
DISCORD_CHANNEL_ID     = "1488240821626077246"  # #meeting-scorecards in Rev.io Sales Team

STATE_FILE             = "/home/openclaw/.openclaw/workspace/grader-state.json"
MIN_DURATION_SECONDS   = 20 * 60  # 20 minutes

# Rep name → Discord user ID mapping (update as reps join the server)
REP_DISCORD_IDS = {
    "Jamie Butler":    None,  # jamiebutler_76724
    "Jaylin Bender":   None,  # jaylin.21
    "Andy Whisenant":  None,  # andy_whisenant_98852
    "Jake Borah":      None,  # jakeborah_06434
    "Patrick Davies":  None,  # patrickdavies005
    "Connor Flynn":    None,  # connorflynn_58046
    "Davis Herndon":   None,  # davis_95641
    "Husam Zalmiyar":  None,  # husam_zalmiyar_38788
}

BEACON_RUBRIC = """
You are grading a Rev.io sales discovery call against the BEACON methodology. Score 0-100.

## SCORING CATEGORIES

### 1. THE APPROACH (15 pts)
- Warm-up and rapport building — prospect felt comfortable and engaged
- Confirmed DM using MULTIPLE angles:
  - "Last time there was a change, you signed the paperwork?"
  - "Is there anyone else who would need to weigh in on a decision like this?"
  - "If this makes sense after the demo, are you in a position to move forward?"
  - Following up when others are mentioned: "Tell me about their role in the process"
- Set 3-part agenda: tell about Rev.io → learn about needs → if fit, schedule demo
Score 13-15: All elements — warm-up done, DM confirmed multiple ways, clean agenda
Score 9-12: Most elements — DM confirmed but only one method, or agenda missing one part
Score 5-8: DM asked once but not followed up, warm-up thin, agenda incomplete
Score 0-4: No warm-up, DM never confirmed, no agenda set

### 2. COMPANY STORY (15 pts)
- Delivered the Rev.io company story / scripted presentation with energy and confidence
- Covered the key content (Rev.io history, mission, what they do, client experience)
- Clean transition to the questionnaire
- Tie-downs are encouraged but NOT required — the presentation is scripted so following it correctly earns full credit

Score 13-15: Delivered with energy and confidence, covered the content, clean transition
Score 9-12: Covered the content but low energy or delivery felt flat
Score 5-8: Rushed through or skipped key parts of the presentation
Score 0-4: Largely skipped or left prospect confused about Rev.io

### 3. QUALIFYING / NEEDS ASSESSMENT (40 pts)

Score this section by COUNTING the following from the transcript and adding up:

**A. Open-Ended Questions Asked (15 pts)**
Count distinct open-ended discovery questions (not yes/no, not feature-related, not logistics):
- 8+ questions → 15 pts
- 6-7 questions → 12 pts
- 4-5 questions → 8 pts
- 2-3 questions → 4 pts
- 0-1 questions → 0 pts

**B. DBMs (Dominant Buying Motives) Uncovered (15 pts)**
Count clearly identified pain points or business problems the prospect acknowledged:
- 5+ DBMs → 15 pts
- 4 DBMs → 12 pts
- 3 DBMs → 9 pts
- 2 DBMs → 6 pts
- 1 DBM → 3 pts
- 0 DBMs → 0 pts

**C. Probed for Effect (10 pts)**
Did they ask quantifying questions: "How much does that cost you?", "What happens if you don't fix it?", "How long has this been going on?", "What does that mean for the business?"
- 3+ effect probes → 10 pts
- 2 effect probes → 6 pts
- 1 effect probe → 3 pts
- 0 → 0 pts

**In the scorecard output, explicitly state the counts:**
"Open-ended questions: X | DBMs uncovered: X | Effect probes: X"

Also note: did they uncover the Business Issue (why now)? Yes/No.

### 4. SUMMARIZE & MAKE SICK (20 pts)

Score based on whether the rep played back the prospect's reality, not whether they used a formal summary phrase. GIVE CREDIT for meaningful playback of key moments from the meeting — pains, goals, business facts, stakes, constraints, decision context, timeline, or impact — even if the rep never says "let me summarize" or "let me recap."

**Full credit (18-20 pts):** Rep clearly played back 3+ specific DBMs or key meeting moments, tied them to business facts or impact, and asked a confirming question OR earned clear prospect acknowledgement. Explicit summarizing language is helpful but NOT required.

**Strong (13-17 pts):** Rep played back 2+ specific DBMs or key meeting moments and recapped some business facts, stakes, or desired outcomes. Asked for confirmation OR prospect acknowledged without being prompted. No formal "summary" phrase required.

**Partial (7-12 pts):** Rep briefly played back at least one meaningful pain, goal, business fact, or key moment from the call, but the recap was thin/vague OR confirmation ask was missing. IMPORTANT: Give credit here for playback even if it is not introduced as a summary.

**Weak (4-6 pts):** Brief, partial playback — mentioned a problem, goal, or fact from the meeting but did not connect the dots, make the pain feel urgent, or ask for confirmation.

**None (0-3 pts):** No playback attempted whatsoever. Zero attempt to recap pain, goals, business facts, stakes, or decision context. Jumped directly to demo ask or next steps.

IMPORTANT: Reserve 0-3 ONLY for reps who skip playback entirely. Do NOT require magic words. If the rep restates meaningful parts of the prospect's situation in their own words, that counts as summarizing/making sick even without explicit summarizing language.

Key signals to look for:
- Did they play back key moments from the meeting in their own words?
- Did they recap specific facts (company size, current software, pain points, timeline, decision process, goals, constraints) — even briefly?
- Did they name DBMs, goals, or stakes back — even if not perfectly quantified?
- Did they make the current pain feel concrete by connecting it to impact, urgency, growth, risk, or cost?
- Did they ask "Does that sound accurate?" or "Is there anything I missed?"
- Did the prospect confirm or acknowledge?
- Did the prospect say "yeah, that's right" or otherwise confirm?

### 5. NEXT STEPS / SETTING THE DEMO (10 pts)
- Trial closed before asking for demo
- Connected demo ask to specific DBMs discovered
- Booked it LIVE with date/time confirmed
- Asked who else should be on the demo
Score 9-10: Trial close + booked live + stakeholders confirmed
Score 6-8: Demo booked but generic framing, missing stakeholder ask
Score 3-5: Weak close, "I'll send info" or no live booking
Score 0-2: No close, call ended without committed next step

## GRADE THRESHOLDS
- 🟢 90-100 = Elite
- 🔵 80-89 = Strong
- 🟡 65-79 = Solid
- 🟠 50-64 = Needs Work
- 🔴 <50 = Coaching Required

## SCORING DISCIPLINE — READ THIS
You MUST use the full 0-100 range. Do not cluster scores in the 50-60 range out of politeness or uncertainty.
- A call where the rep did nothing well should score in the 20s-30s.
- A call where the rep was average across the board should score in the 40s.
- A call where the rep did several things well but missed key elements should score in the 50s-60s.
- Only genuinely strong calls earn 70+.
- Be stingy with partial credit. If it wasn't clearly done, don't give credit for it.
- The Summarize & Make Sick section: give credit for meaningful playback. The rep does not need to say "let me summarize" or "here's what I heard." If they play back key pains, goals, business facts, stakes, timeline, or decision context from the meeting, award credit based on quality. Reserve 0-3 only for reps who skipped playback entirely and jumped straight to next steps.
"""


# ── Outreach Auth ────────────────────────────────────────────────────────────
def get_outreach_token():
    with open(OUTREACH_TOKEN_FILE) as f:
        tokens = json.load(f)
    # Use client creds from token file (authoritative); fall back to module-level constants
    client_id     = tokens.get("client_id") or OUTREACH_CLIENT_ID
    client_secret = tokens.get("client_secret") or OUTREACH_CLIENT_SECRET
    r = requests.post("https://api.outreach.io/oauth/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "https://openclaw.app/oauth/callback/outreach",
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    })
    if r.ok:
        new_tokens = r.json()
        # Preserve client creds that may not come back in the refresh response
        new_tokens.setdefault("client_id", client_id)
        new_tokens.setdefault("client_secret", client_secret)
        tokens.update(new_tokens)
        with open(OUTREACH_TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    return tokens["access_token"]


# ── State ─────────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"graded_ids": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Fetch new discovery calls ─────────────────────────────────────────────────
def get_sf_discovery_call_dates():
    """Pull SF event dates where Type = '1-Discovery Call' from last 7 days."""
    import urllib.parse
    SF_CLIENT_ID     = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
    SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
    SF_INSTANCE      = "https://rev-io.my.salesforce.com"

    resp = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={
        "grant_type": "client_credentials",
        "client_id": SF_CLIENT_ID,
        "client_secret": SF_CLIENT_SECRET,
    })
    if resp.status_code != 200:
        print(f"SF auth failed: {resp.status_code}")
        return set()

    sf_token = resp.json()["access_token"]
    sf_instance = resp.json()["instance_url"]
    sf_headers = {"Authorization": f"Bearer {sf_token}"}

    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d')

    q = f"SELECT Subject, ActivityDate, Owner.Name FROM Event WHERE ActivityDate >= {since} AND Type = '1-Discovery Call'"
    r = requests.get(sf_instance + "/services/data/v59.0/query?q=" + urllib.parse.quote(q), headers=sf_headers)
    events = r.json().get("records", [])

    # Return set of (date, subject_lower) tuples for matching
    sf_keys = set()
    for e in events:
        date = e.get("ActivityDate", "")
        subject = (e.get("Subject") or "").lower()
        owner = (e.get("Owner") or {}).get("Name", "")
        sf_keys.add((date, subject))

    print(f"  SF Discovery Call events (last 7 days): {len(sf_keys)}")
    return sf_keys


def fetch_new_discovery_calls(at, already_graded):
    headers = {"Authorization": f"Bearer {at}"}

    r = requests.get(
        "https://api.outreach.io/api/v2/kaiaRecordings"
        "?filter[format]=meeting&page[size]=50&sort=-createdAt"
        "&fields[kaiaRecording]=title,startTime,endTime,format,state,mediaDurationSeconds,botInMeetingSeconds,transcriptUrl",
        headers=headers
    )
    if r.status_code == 403:
        err = r.json().get("errors", [{}])[0].get("detail", r.text)
        print(f"  ⚠️  Outreach Kaia API access denied: {err}")
        print("  ACTION REQUIRED: Contact Outreach support to enable Kaia Recordings for this org.")
        return []
    r.raise_for_status()
    recordings = r.json().get("data", [])

    # Get SF events typed as Discovery Call for matching
    sf_discovery_keys = get_sf_discovery_call_dates()

    new_calls = []
    for rec in recordings:
        rid = rec["id"]
        attrs = rec.get("attributes", {})

        # Already graded?
        if rid in already_graded:
            continue

        # Must be ENDED
        if attrs.get("state") != "ENDED":
            continue

        # Must be > 20 min
        duration = int(attrs.get("mediaDurationSeconds") or attrs.get("botInMeetingSeconds") or 0)
        title = attrs.get("title") or ""

        if duration < MIN_DURATION_SECONDS:
            print(f"  Skipping {title[:50]} — only {duration//60} min")
            continue

        # Match against SF event type = '1-Discovery Call' by date + title
        start_date = (attrs.get("startTime") or "")[:10]
        title_lower = title.lower()

        # Check if SF has a discovery call event on this date with matching title
        sf_match = any(
            date == start_date and (title_lower in sf_title or sf_title in title_lower)
            for date, sf_title in sf_discovery_keys
        )

        # Fallback: still accept if title explicitly says "discovery call"
        title_match = "discovery call" in title_lower

        if not sf_match and not title_match:
            print(f"  Skipping {title[:60]} — not a SF Discovery Call event")
            continue

        new_calls.append(rec)

    return new_calls


# ── Fetch transcript ──────────────────────────────────────────────────────────
def fetch_transcript(at, rec_id):
    """Re-fetch the recording to get the hidden transcriptUrl field."""
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
    return t.json(), attrs.get("title")


def format_transcript(transcript_json):
    """Convert utterances JSON to readable text for grading."""
    utterances = transcript_json.get("utterances", [])
    lines = []
    prev_speaker = None
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


# ── Grade with Claude ─────────────────────────────────────────────────────────
def grade_call(transcript_text, title, duration_seconds):
    client = anthropic.Anthropic()

    duration_min = duration_seconds // 60
    prompt = f"""You are grading a Rev.io sales discovery call. Call title: "{title}" | Duration: {duration_min} minutes

{BEACON_RUBRIC}

## TRANSCRIPT
{transcript_text[:40000]}

## YOUR TASK
Grade this call and respond in EXACTLY this format:

# 📞 Discovery Call Grade: [Rep Name] — [Account] — [Date]

## Overall Score: XX/100 — [GRADE EMOJI + LABEL]
(IMPORTANT: Overall Score MUST equal the exact mathematical sum of your 5 category scores. Add them up: Approach + Company Story + Qualifying + Summarize + Next Steps = Overall Score. Do not pick a different number.)

---

## Scorecard

### 1. The Approach — XX/15
**What they did well:** ...
**What was missing:** ...
**DM Confirmation:** [how many ways did they confirm the DM? Quote the attempts]
**Key moment:** "[direct quote or close paraphrase from transcript]"

### 2. Company Story — XX/15
**What they did well:** ...
**What was missing:** ...

### 3. Qualifying / Needs Assessment — XX/40
**Counts:** Open-ended questions: X | DBMs uncovered: X | Effect probes: X | Business Issue identified: Yes/No
**What they did well:** ...
**What was missing:** ...
**Key moment:** "[direct quote or close paraphrase]"

### 4. Summarize & Make Sick — XX/20
**DBMs / key moments played back:** X (list them)
**Business facts recapped:** Yes/No (list key ones)
**Confirmation ask:** Yes/No — quote it if yes
**Prospect acknowledged:** Yes/No
**What they did well:** ...
**What was missing:** ...
**Key moment:** "[direct quote or close paraphrase]"

### 5. Next Steps / Setting the Demo — XX/10
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
[1-2 sentence honest overall read — direct, not harsh]

Be direct and specific. Always cite what actually happened on the call. Do not soften bad scores."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ── Discord Post ──────────────────────────────────────────────────────────────
def get_discord_token():
    with open("/home/openclaw/.openclaw/openclaw.json") as f:
        config = json.load(f)
    # Find discord bot token
    raw = json.dumps(config)
    import re
    tokens = re.findall(r'[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}', raw)
    if tokens:
        return tokens[0]
    return None


def get_rep_mention(scorecard_text):
    """Extract rep name from scorecard and return Discord mention if ID known."""
    import re
    # Scorecard header: "# 📞 Discovery Call Grade: Rep Name — Account — Date"
    match = re.search(r'Discovery Call Grade:\s*([^—\n]+)', scorecard_text)
    if not match:
        return None, None
    rep_name = match.group(1).strip()
    # Find closest match in REP_DISCORD_IDS
    for name, discord_id in REP_DISCORD_IDS.items():
        if name.lower() in rep_name.lower() or rep_name.lower() in name.lower():
            if discord_id:
                return name, f"<@{discord_id}>"
            else:
                return name, f"@{rep_name}"  # fallback text mention
    return rep_name, f"@{rep_name}"


def grade_color(score):
    if score >= 90: return 0x22c55e    # green
    elif score >= 80: return 0x3b82f6  # blue
    elif score >= 65: return 0xeab308  # yellow
    elif score >= 50: return 0xf97316  # orange
    else: return 0xef4444              # red

def grade_label(score):
    if score >= 90: return "🟢 Elite"
    elif score >= 80: return "🔵 Strong"
    elif score >= 65: return "🟡 Solid"
    elif score >= 50: return "🟠 Needs Work"
    else: return "🔴 Coaching Required"

def parse_scorecard(scorecard_text):
    """Extract key fields from scorecard text."""
    import re
    # Overall score
    score_match = re.search(r'Overall Score:\s*(\d+)/100', scorecard_text)
    score = int(score_match.group(1)) if score_match else 0

    # Rep name and account from header line
    header_match = re.search(r'Discovery Call Grade:\s*([^—\n]+?)(?:\s*—\s*([^—\n]+?))?(?:\s*—\s*([^\n]+))?\s*$', scorecard_text, re.MULTILINE)
    rep = header_match.group(1).strip() if header_match else "Unknown Rep"
    account = header_match.group(2).strip() if header_match and header_match.group(2) else "Unknown Account"

    # Category scores
    cats = {}
    cat_sum = 0
    for cat, pts in [("The Approach", 15), ("Company Story", 15), ("Qualifying", 40),
                     ("Summarize", 20), ("Next Steps", 10)]:
        m = re.search(rf'{cat}[^—\n]*—\s*(\d+)/{pts}', scorecard_text)
        if m:
            cats[cat] = f"{m.group(1)}/{pts}"
            cat_sum += int(m.group(1))
        else:
            cats[cat] = f"?/{pts}"

    # Always use the true category sum — never trust the model's stated overall score
    if cat_sum > 0:
        score = cat_sum

    # Top coaching point #1
    coaching_match = re.search(r'Top 3 Coaching Points\s*\n1\.\s*(.+)', scorecard_text)
    coaching = coaching_match.group(1).strip() if coaching_match else ""

    # Robin's Take
    take_match = re.search(r"Robin's Take\s*\n(.+?)(?:\n|$)", scorecard_text)
    take = take_match.group(1).strip() if take_match else ""

    return score, rep, account, cats, coaching, take


def discord_request(method, url, headers, json_payload=None, max_attempts=5):
    """Discord write helper with 429 retry handling."""
    for attempt in range(1, max_attempts + 1):
        r = requests.request(method, url, headers=headers, json=json_payload)
        if r.status_code != 429:
            r.raise_for_status()
            return r

        retry_after = 2.0
        try:
            body = r.json()
            retry_after = float(body.get("retry_after", retry_after))
        except Exception:
            retry_after = float(r.headers.get("Retry-After", retry_after))

        print(f"  Discord rate limited; retrying in {retry_after:.1f}s (attempt {attempt}/{max_attempts})")
        time.sleep(retry_after + 0.5)

    r.raise_for_status()


def send_discord_message(bot_token, channel_id, content=None, embeds=None):
    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    payload = {}
    if content: payload["content"] = content
    if embeds: payload["embeds"] = embeds
    r = discord_request("POST", f"https://discord.com/api/v10/channels/{channel_id}/messages",
                        headers, payload)
    return r.json()


def create_thread(bot_token, channel_id, message_id, thread_name):
    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    r = discord_request(
        "POST",
        f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/threads",
        headers,
        {"name": thread_name, "auto_archive_duration": 1440}
    )
    return r.json()


NOTION_TOKEN   = "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"
NOTION_DB_ID   = "333a59b7-e7b2-8062-8068-fc0116ff82f7"  # Sales Meeting Coaching

# Rep name → Notion user ID mapping
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
    "Andy Whisenant":   "2a3d872b-594c-813d-9397-0002de289b31",
    "Andrew Whisenant": "2a3d872b-594c-813d-9397-0002de289b31",
    "Jamie Butler":     "2a3d872b-594c-81cd-9cd2-0002a6efd08e",
    "Joseph Abarno":    "2a3d872b-594c-8136-969c-0002c8328dc1",
    "Nassim Filoso":    "2bed872b-594c-8191-90b5-00022057fec4",
    "Olivia Sandefur":  "2b6d872b-594c-81e7-a3c6-0002c20dd9a5",
}

def post_to_notion(scorecard_text, title, recording_url=None, start_time=None, recording_owner=None):
    """Push scorecard to Notion Sales Meeting Coaching database."""
    import re
    from datetime import datetime, timezone

    score, rep, account, cats, coaching, take = parse_scorecard(scorecard_text)

    # Prefer the Outreach recording host (actual meeting owner) over parsed scorecard text
    if recording_owner:
        rep = recording_owner

    def extract_num(cat_str):
        """Extract numeric score from '14/15' → 14"""
        try:
            return int(cat_str.split('/')[0])
        except:
            return 0

    meeting_date = start_time[:10] if start_time else datetime.now(timezone.utc).strftime('%Y-%m-%d')

    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Notion-Version': '2022-06-28',
        'Content-Type': 'application/json',
    }

    # Map BEACON categories to Notion properties
    # Use flexible regex (any /NN) to avoid max-pts mismatch breaking the match
    cat_scores = {}
    for cat in ["The Approach", "Company Story", "Qualifying", "Summarize", "Next Steps"]:
        m = re.search(rf'{re.escape(cat)}[^—\n]*[—-]\s*(\d+)/\d+', scorecard_text, re.IGNORECASE)
        if m:
            cat_scores[cat] = int(m.group(1))

    props = {
        "Meeting Title":     {"title": [{"text": {"content": title[:200]}}]},
        "Prospect / Account":{"rich_text": [{"text": {"content": account[:200]}}]},
        "Meeting Date":      {"date": {"start": meeting_date}},
        "Overall Score":     {"number": score},
        "Approach":          {"number": cat_scores.get("The Approach", 0)},
        "Company Story":     {"number": cat_scores.get("Company Story", 0)},
        "Qualifying":        {"number": cat_scores.get("Qualifying", 0)},
        "Summarize":         {"number": cat_scores.get("Summarize", 0)},
        "Next Steps":        {"number": cat_scores.get("Next Steps", 0)},
        "Top Coaching Point":{"rich_text": [{"text": {"content": coaching[:1900] if coaching else ""}}]},
        "Robin's Take":      {"rich_text": [{"text": {"content": take[:1900] if take else ""}}]},
    }

    if recording_url:
        props["Recording URL"] = {"url": recording_url}

    # Tag the Sales Rep if we know their Notion user ID
    notion_uid = REP_NOTION_IDS.get(rep)
    if notion_uid:
        props["Sales Rep"] = {"people": [{"id": notion_uid}]}

    payload = {"parent": {"database_id": NOTION_DB_ID}, "properties": props}

    # Add full scorecard as page content
    content_blocks = [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": [{"text": {"content": "Full Scorecard"}}]}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [{"text": {"content": scorecard_text[:1900]}}]}},
    ]
    if len(scorecard_text) > 1900:
        content_blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": scorecard_text[1900:3800]}}]}
        })

    payload["children"] = content_blocks

    r = requests.post('https://api.notion.com/v1/pages', headers=headers, json=payload)
    if r.status_code == 200:
        page = r.json()
        print(f"  ✅ Notion page created: {page.get('url','')}")
        return True
    else:
        print(f"  ❌ Notion failed: {r.status_code} {r.json()}")
        return False


COMPETITOR_MENTIONS_DB_ID = "6182cc09f1e34d03973e23247a25d069"
KNOWN_COMPETITORS = ["Halo PSA", "HaloPSA", "ConnectWise", "Field Pulse", "FieldPulse",
                     "Autotask", "Syncro", "SuperOps", "Kaseya", "Datto",
                     "ServiceTitan", "ServiceMax", "Alarm Biller", "Dice", "Acumatica",
                     "D-tools", "Sage", "Epicor", "One Vision"]

# NOT competitors — exclude from logging
EXCLUDED_COMPETITORS = {
    "netsapiens", "netsapiens inc",
    "quickbooks", "quickbooks online", "quickbooks desktop", "quickbooks enterprise",
    "tiger paw", "tigerpaw", "tiger paw psa",
    # Tax databases
    "avalara", "suretax", "ceretax", "taxjar", "vertex", "cch", "sovos",
    # CRM / marketing tools (not PSA competitors)
    "hubspot", "salesforce", "zoho", "pipedrive",
}


def extract_competitor_mentions(transcript_text, title, start_time):
    """Use Claude to extract competitor mentions from transcript and log to Notion."""
    client = anthropic.Anthropic()
    # Full list of tracked competitors from Notion select options
    TRACKED_COMPETITORS = [
        "Fieldpulse", "Fieldpoint", "Cornerstone", "Ipoint", "Housecall Pro", "Jobber",
        "Simpro", "Autotask", "Projx360", "Sedona", "Superops", "Syncro", "Halo",
        "Workhorse", "Sandybeaches", "Datagate", "Timleybill", "Costguard", "IDI",
        "Blulogix", "Onebill", "Halo PSA", "ConnectWise", "Field Pulse",
        "AlarmBiller", "Service Fusion", "Jetbuilt", "ServiceNow", "D-tools", "Monday"
    ]
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": f"""Read this sales call transcript and look for mentions of these specific competitor platforms that the PROSPECT is currently using or evaluating:

{chr(10).join('- ' + c for c in TRACKED_COMPETITORS)}

For each one found, extract:
- competitor: use the exact name from the list above (closest match)
- sentiment: Positive, Negative, or Neutral (prospect's view of that platform)
- mention: 8-word summary title of the intel
- context: specific competitive intelligence — missing features, pricing issues, support problems, what they like/dislike. NO individual people's names.

Do NOT include: QuickBooks, Netsapiens, Tiger Paw, tax databases (Avalara, Suretax, etc.), HubSpot, Salesforce, Google tools, DocuSign, payment processors.

If none of the tracked competitors are mentioned, respond with exactly: []

Call: "{title}"

TRANSCRIPT:
{transcript_text[:25000]}

Respond in raw JSON array only (no markdown, no code blocks):
[{{"competitor":"exact name from list","sentiment":"Positive|Negative|Neutral","mention":"8-word title","context":"competitive intel"}}]"""}]
    )
    result = msg.content[0].text.strip()
    try:
        import json
        mentions = json.loads(result)
        return mentions if isinstance(mentions, list) else []
    except:
        return []


def log_competitor_mentions(mentions, title, start_time, rep_name):
    """Log each competitor mention as a row in the Competitor Mentions Notion DB."""
    if not mentions:
        return 0

    NOTION_TOKEN = "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"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28",
               "Content-Type": "application/json"}

    # Map rep name to Notion user ID
    notion_uid = REP_NOTION_IDS.get(rep_name)

    # Normalize competitor name to known Notion select options
    # Map variations to exact Notion select option names
    NOTION_OPTIONS = [
        "Fieldpulse","Fieldpoint","Cornerstone","Ipoint","Housecall Pro","Jobber",
        "Simpro","Autotask","Projx360","Sedona","Superops","Syncro","Halo",
        "Workhorse","Sandybeaches","Datagate","Timleybill","Costguard","IDI",
        "Blulogix","Onebill","Halo PSA","ConnectWise","Other","Field Pulse",
        "AlarmBiller","Service Fusion","Jetbuilt","ServiceNow","D-tools","Monday"
    ]
    COMP_MAP = {
        "halo psa": "Halo PSA", "halopsa": "Halo PSA", "halo": "Halo",
        "connectwise": "ConnectWise", "connectwise manage": "ConnectWise", "connectwise psa": "ConnectWise",
        "field pulse": "Field Pulse", "fieldpulse": "Fieldpulse",
        "alarm biller": "AlarmBiller", "alarmbiller": "AlarmBiller",
        "service fusion": "Service Fusion",
        "d-tools": "D-tools", "dtools": "D-tools",
        "superops": "Superops", "super ops": "Superops",
        "housecall pro": "Housecall Pro",
        "projx360": "Projx360", "projects 360": "Projx360", "project 360": "Projx360",
    }

    logged = 0
    meeting_date = (start_time or "")[:10] or None

    for m in mentions:
        comp_raw = m.get("competitor","").strip()
        # Skip excluded non-competitors
        if comp_raw.lower() in EXCLUDED_COMPETITORS:
            print(f"  ⏭️  Skipping excluded: {comp_raw}")
            continue
        comp_lower = comp_raw.lower()
        comp_option = COMP_MAP.get(comp_lower)
        if not comp_option:
            # Try fuzzy match against Notion options
            for opt in NOTION_OPTIONS:
                if opt.lower() == comp_lower or opt.lower() in comp_lower or comp_lower in opt.lower():
                    comp_option = opt
                    break
        # Only log tracked competitors — skip anything else
        if not comp_option:
            print(f"  ⏭️  Not a tracked competitor, skipping: {comp_raw}")
            continue

        sentiment = m.get("sentiment","Neutral")
        if sentiment not in ["Positive","Negative","Neutral"]:
            sentiment = "Neutral"

        mention_text = m.get("mention","") or f"{comp_raw} mentioned in {title[:40]}"
        context_text = m.get("context","")

        props = {
            "Mention": {"title": [{"text": {"content": mention_text[:100]}}]},
            "Competitor": {"select": {"name": comp_option}},
            "Sentiment": {"select": {"name": sentiment}},
            "Context": {"rich_text": [{"text": {"content": context_text[:500]}}]},
        }
        if meeting_date:
            props["Meeting Date"] = {"date": {"start": meeting_date}}
        if notion_uid:
            props["Sales Rep"] = {"people": [{"id": notion_uid}]}

        r = requests.post("https://api.notion.com/v1/pages",
            headers=headers, json={"parent": {"database_id": COMPETITOR_MENTIONS_DB_ID}, "properties": props})
        if r.ok:
            print(f"  📊 Competitor logged: {comp_raw} ({sentiment})")
            logged += 1
        else:
            print(f"  ⚠️  Competitor log failed: {r.text[:100]}")

    return logged


def extract_rapport_info(transcript_text, title):
    """Use Claude to extract personal rapport/personalization details from transcript."""
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=500,
        messages=[{"role": "user", "content": f"""Read this sales call transcript and extract any personal rapport information about the PROSPECT (not the rep) that would be useful for future personalization.

Include things like:
- Family mentions (spouse, kids, pets)
- Hobbies or interests
- Sports teams they follow
- Vacation/travel plans or recent trips
- Where they're from or grew up
- Personal projects or side businesses
- Community involvement
- Anything memorable or personal they shared

Call: "{title}"

TRANSCRIPT:
{transcript_text[:20000]}

Respond with ONLY a concise 1-3 sentence summary of personal details worth remembering. If nothing personal was shared, respond with exactly: "No personal details shared."
Do not include business/company information — only personal rapport details."""}]
    )
    result = msg.content[0].text.strip()
    if result == "No personal details shared.":
        return None
    return result


def update_sf_personalization(title, rapport_text):
    """Find the contact from the call title/account in SF and update Rapport_Bio__c."""
    SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
    SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
    SF_INSTANCE = "https://rev-io.my.salesforce.com"

    r = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={
        "grant_type": "client_credentials",
        "client_id": SF_CLIENT_ID, "client_secret": SF_CLIENT_SECRET,
    })
    if not r.ok: return False
    d = r.json(); at, iurl = d["access_token"], d["instance_url"]
    sf_headers = {"Authorization": f"Bearer {at}", "Content-Type": "application/json"}

    # Extract account/company name from title
    # Title format: "(Discovery Call) CompanyName & Rev.io" or "Rep Name with CompanyName"
    import re
    account_name = None
    m = re.search(r'\(Discovery Call\)\s*(.+?)\s*(?:&|and)\s*Rev\.io', title, re.I)
    if m:
        account_name = m.group(1).strip()
    else:
        m2 = re.search(r'with\s+(.+?)\s*$', title, re.I)
        if m2:
            account_name = m2.group(1).strip()

    if not account_name:
        print(f"  ⚠️  Could not extract account name from title: {title}")
        return False

    # Find contacts at this account
    soql = f"SELECT Id, FirstName, LastName, Rapport_Bio__c FROM Contact WHERE Account.Name LIKE '%{account_name[:30]}%' LIMIT 5"
    r = requests.get(f"{iurl}/services/data/v57.0/query",
        headers=sf_headers, params={"q": soql})
    if not r.ok:
        print(f"  ⚠️  SF query failed: {r.text[:100]}")
        return False

    contacts = r.json().get("records", [])
    if not contacts:
        print(f"  ⚠️  No contacts found for account '{account_name}'")
        return False

    updated = 0
    for contact in contacts:
        cid = contact["Id"]
        existing = contact.get("Rapport_Bio__c") or ""
        # Append new info rather than overwrite
        new_value = f"{existing}\n[{title[:40]}] {rapport_text}".strip() if existing else f"[{title[:40]}] {rapport_text}"
        r = requests.patch(f"{iurl}/services/data/v57.0/sobjects/Contact/{cid}",
            headers=sf_headers, json={"Rapport_Bio__c": new_value})
        if r.ok or r.status_code == 204:
            name = f"{contact.get('FirstName','')} {contact.get('LastName','')}".strip()
            print(f"  ✅ Updated Rapport_Bio__c for {name}")
            updated += 1
        else:
            print(f"  ⚠️  Failed to update {cid}: {r.text[:100]}")

    return updated > 0


def post_to_discord(scorecard_text, title, duration_seconds):
    bot_token = get_discord_token()
    if not bot_token:
        print("ERROR: Could not find Discord bot token")
        return False

    headers_http = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    rep_name, rep_mention = get_rep_mention(scorecard_text)
    score, rep, account, cats, coaching, take = parse_scorecard(scorecard_text)
    duration_min = duration_seconds // 60

    # ── 1. Post summary embed card to channel ──
    embed = {
        "color": grade_color(score),
        "title": f"📞 {account}",
        "description": f"**Rep:** {rep_mention or rep}  •  **Duration:** {duration_min} min",
        "fields": [
            {"name": "Overall Score", "value": f"**{score}/100** — {grade_label(score)}", "inline": False},
            {"name": "The Approach", "value": cats.get("The Approach", "?"), "inline": True},
            {"name": "Company Story", "value": cats.get("Company Story", "?"), "inline": True},
            {"name": "Qualifying", "value": cats.get("Qualifying", "?"), "inline": True},
            {"name": "Summarize & Make Sick", "value": cats.get("Summarize", "?"), "inline": True},
            {"name": "Next Steps", "value": cats.get("Next Steps", "?"), "inline": True},
        ],
        "footer": {"text": "Click into the thread below for full BEACON breakdown & coaching notes"}
    }
    if coaching:
        embed["fields"].append({"name": "🔑 Top Coaching Point", "value": coaching, "inline": False})

    msg = send_discord_message(bot_token, DISCORD_CHANNEL_ID, embeds=[embed])
    message_id = msg["id"]
    print(f"  Summary card posted (msg {message_id})")

    # ── 2. Create thread off that message ──
    thread_name = f"{rep} — {account}"[:100]
    try:
        thread = create_thread(bot_token, DISCORD_CHANNEL_ID, message_id, thread_name)
        thread_id = thread["id"]
        print(f"  Thread created ({thread_id})")
    except requests.HTTPError as e:
        response = getattr(e, "response", None)
        if response is None or response.status_code != 429:
            raise
        # Fallback: Discord sometimes applies a separate short-lived thread-creation
        # limit. Don't block grading/Notion/state on that route; post the scorecard
        # as replies in-channel so the run can complete.
        print("  Thread creation still rate-limited; posting scorecard in channel instead")
        thread_id = DISCORD_CHANNEL_ID
        discord_request(
            "POST",
            f"https://discord.com/api/v10/channels/{thread_id}/messages",
            headers_http,
            {"content": f"Full BEACON breakdown for **{account}** (thread creation was rate-limited):"}
        )

    # ── 3. Post full scorecard in thread/channel (chunked) ──
    full_text = scorecard_text
    chunks = []
    current = ""
    for line in full_text.split("\n"):
        if len(current) + len(line) + 1 > 1900:
            chunks.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        chunks.append(current)

    for chunk in chunks:
        try:
            discord_request(
                "POST",
                f"https://discord.com/api/v10/channels/{thread_id}/messages",
                headers_http,
                {"content": chunk}
            )
        except requests.HTTPError as e:
            response = getattr(e, "response", None)
            detail = f"{response.status_code} {response.text[:200]}" if response is not None else str(e)
            print(f"  Thread post error: {detail}")
            return False

    print(f"  Full scorecard posted to thread ✅")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"=== Discovery Call Grader {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")

    state = load_state()
    already_graded = set(state.get("graded_ids", []))

    at = get_outreach_token()

    new_calls = fetch_new_discovery_calls(at, already_graded)
    print(f"Found {len(new_calls)} new discovery call(s) to grade")

    if not new_calls:
        print("Nothing to grade.")
        return

    for rec in new_calls:
        rid = rec["id"]
        attrs = rec.get("attributes", {})
        title = attrs.get("title", "Unknown")
        duration = int(attrs.get("mediaDurationSeconds") or attrs.get("botInMeetingSeconds") or 0)

        print(f"\nGrading: {title} ({duration//60} min)...")

        try:
            transcript_json, _ = fetch_transcript(at, rid)
            if not transcript_json:
                print(f"  No transcript available yet, skipping.")
                continue

            transcript_text = format_transcript(transcript_json)
            if len(transcript_text) < 500:
                print(f"  Transcript too short ({len(transcript_text)} chars), skipping.")
                continue

            print(f"  Transcript: {len(transcript_text)} chars, grading with Claude...")
            scorecard = grade_call(transcript_text, title, duration)

            print(f"  Posting to Discord...")
            success = post_to_discord(scorecard, title, duration)

            print(f"  Posting to Notion...")
            attrs = rec.get("attributes", {})
            recording_url = attrs.get("transcriptUrl") or None
            start_time = attrs.get("startTime") or None
            # Use the recording host (Outreach owner) as the rep name — not SF record owner
            host = attrs.get("host") or {}
            recording_owner = host.get("displayName") or None
            post_to_notion(scorecard, title, recording_url=recording_url, start_time=start_time, recording_owner=recording_owner)

            print(f"  Extracting rapport info for SF...")
            rapport = extract_rapport_info(transcript_text, title)
            if rapport:
                print(f"  Rapport found: {rapport[:80]}...")
                update_sf_personalization(title, rapport)
            else:
                print(f"  No personal details found in transcript.")

            print(f"  Extracting competitor mentions for Notion...")
            _, rep_name, _, _, _, _ = parse_scorecard(scorecard)
            start_time = attrs.get("startTime")
            competitor_mentions = extract_competitor_mentions(transcript_text, title, start_time)
            if competitor_mentions:
                logged = log_competitor_mentions(competitor_mentions, title, start_time, rep_name)
                print(f"  Logged {logged} competitor mention(s) to Notion.")
            else:
                print(f"  No competitor mentions found.")

            if success:
                print(f"  ✅ Posted!")
                already_graded.add(rid)
                state["graded_ids"] = list(already_graded)
                save_state(state)
            else:
                print(f"  ❌ Discord post failed")

        except Exception as e:
            print(f"  ERROR grading {title}: {e}")
            import traceback
            traceback.print_exc()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
