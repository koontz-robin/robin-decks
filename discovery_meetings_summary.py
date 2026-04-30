#!/usr/bin/env python3
"""
Daily Discovery Meetings Set Summary
- Runs at 5PM ET (21:00 UTC) Mon-Fri
- Queries SF Tasks with Subject LIKE '%Discovery Meeting Set%' created today
- Fetches account employee count to flag small accounts (<5 employees)
- Posts formatted summary to Discord #general channel
"""

import json
import os
import requests
import urllib.parse
from datetime import datetime, timezone, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
SF_CLIENT_ID     = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
SF_INSTANCE      = "https://rev-io.my.salesforce.com"

DISCORD_CHANNEL_ID = "1486771241649045576"   # #general in Rev.io Sales Leadership

# Load Discord token from openclaw.json
def get_discord_token():
    config_path = "/home/openclaw/.openclaw/openclaw.json"
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        return cfg["channels"]["discord"]["token"]
    except Exception as e:
        print(f"Failed to load Discord token: {e}")
        return None

# ── Salesforce ────────────────────────────────────────────────────────────────
def sf_auth():
    resp = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={
        "grant_type": "client_credentials",
        "client_id": SF_CLIENT_ID,
        "client_secret": SF_CLIENT_SECRET,
    })
    if not resp.ok:
        raise RuntimeError(f"SF auth failed: {resp.status_code} {resp.text[:200]}")
    d = resp.json()
    return d["access_token"], d["instance_url"]

def sf_query(token, instance_url, soql):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        instance_url + "/services/data/v59.0/query",
        headers=headers,
        params={"q": soql}
    )
    if not r.ok:
        print(f"SF query failed: {r.status_code} {r.text[:300]}")
        return []
    data = r.json()
    records = data.get("records", [])
    # Handle pagination
    next_url = data.get("nextRecordsUrl")
    while next_url:
        r2 = requests.get(instance_url + next_url, headers=headers)
        if not r2.ok:
            break
        data2 = r2.json()
        records += data2.get("records", [])
        next_url = data2.get("nextRecordsUrl")
    return records

def fetch_today_discovery_meetings(token, instance_url):
    """Fetch Tasks with Subject containing 'Discovery Meeting' created today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    soql = f"""
        SELECT Id, Subject, Description, ActivityDate, CreatedDate,
               Owner.Name,
               Who.Name, Who.Type,
               What.Name, What.Type,
               Account.Name, Account.NumberOfEmployees, Account.Industry,
               Account.BillingCity, Account.BillingState
        FROM Task
        WHERE Subject LIKE '%Discovery Meeting%'
          AND CreatedDate >= {today}T00:00:00Z
          AND CreatedDate <= {today}T23:59:59Z
        ORDER BY CreatedDate ASC
    """.strip()

    print(f"Querying SF for Discovery Meeting tasks created on {today}...")
    records = sf_query(token, instance_url, soql)
    print(f"  Found {len(records)} task(s)")
    return records

# ── Discord ───────────────────────────────────────────────────────────────────
def post_discord(token, channel_id, message):
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json"
    }
    payload = {"content": message}
    r = requests.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers=headers,
        json=payload
    )
    if r.ok:
        print(f"  ✅ Posted to Discord channel {channel_id}")
    else:
        print(f"  ❌ Discord post failed: {r.status_code} {r.text[:200]}")
    return r.ok

def post_discord_chunked(token, channel_id, message):
    """Post a message, chunking at 2000 chars if needed."""
    if len(message) <= 1950:
        return post_discord(token, channel_id, message)

    # Split on newlines
    lines = message.split("\n")
    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 1900:
            if current:
                chunks.append(current.rstrip())
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip())

    success = True
    for chunk in chunks:
        ok = post_discord(token, channel_id, chunk)
        if not ok:
            success = False
    return success

# ── Format ────────────────────────────────────────────────────────────────────
def format_summary(records):
    """Format the discovery meetings summary for Discord."""
    today_str = datetime.now(timezone.utc).strftime("%B %-d, %Y")
    dow = datetime.now(timezone.utc).strftime("%A")

    header = f"📅 **Discovery Meetings Set — {dow}, {today_str}**\n"
    header += f"{'─' * 42}\n"

    if not records:
        return header + "\n_No Discovery Meetings Set logged today._\n"

    lines = [header]
    small_account_flags = []

    for i, rec in enumerate(records, 1):
        rep = (rec.get("Owner") or {}).get("Name") or "Unknown Rep"

        # Contact or lead
        who = rec.get("Who") or {}
        contact_name = who.get("Name") or "—"

        # Account
        acct = rec.get("Account") or {}
        acct_name = acct.get("Name") or (rec.get("What") or {}).get("Name") or "—"
        employees = acct.get("NumberOfEmployees")
        industry = acct.get("Industry") or "—"
        city = acct.get("BillingCity") or ""
        state = acct.get("BillingState") or ""
        location = f"{city}, {state}".strip(", ") if (city or state) else "—"

        # Description / notes
        notes = (rec.get("Description") or "").strip()
        notes_preview = notes[:120] + "…" if len(notes) > 120 else notes

        # Activity date
        activity_date = rec.get("ActivityDate") or "TBD"

        # Employee flag
        flag = ""
        if employees is not None and employees < 5:
            flag = " ⚠️ <5 employees"
            small_account_flags.append(acct_name)

        emp_str = f"{employees:,}" if employees else "?"

        lines.append(
            f"\n**{i}. {acct_name}**{flag}\n"
            f"   👤 Contact: {contact_name}\n"
            f"   🏢 Size: {emp_str} employees · {industry} · {location}\n"
            f"   📅 Meeting Date: {activity_date}\n"
            f"   💼 Rep: {rep}\n"
        )
        if notes_preview:
            lines.append(f"   📝 Notes: {notes_preview}\n")

    # Summary line
    total = len(records)
    small = len(small_account_flags)

    lines.append(f"\n{'─' * 42}")
    lines.append(f"**Total: {total} meeting{'s' if total != 1 else ''} set today** 🎯")
    if small:
        acct_list = ", ".join(small_account_flags[:5])
        lines.append(f"⚠️  **{small} small account{'s' if small != 1 else ''} (<5 employees):** {acct_list}")

    return "\n".join(lines)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"=== Discovery Meetings Summary {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")

    discord_token = get_discord_token()
    if not discord_token:
        print("ERROR: No Discord token found. Aborting.")
        return

    try:
        sf_token, sf_url = sf_auth()
        print("SF auth OK")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return

    records = fetch_today_discovery_meetings(sf_token, sf_url)

    summary = format_summary(records)
    print("\n--- Summary Preview ---")
    print(summary)
    print("----------------------")

    post_discord_chunked(discord_token, DISCORD_CHANNEL_ID, summary)

if __name__ == "__main__":
    main()
