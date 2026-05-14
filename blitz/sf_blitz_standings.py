#!/usr/bin/env python3
"""
Call Blitz Standings Script
Pulls call activity from Salesforce for the blitz window (1:30 PM - 3:00 PM EST)
Posts standings to Discord channel #callblitz
"""

import json, sys, urllib.request, urllib.parse, subprocess, os, random
from datetime import datetime, timezone

# Baseball GIFs to rotate through (Giphy direct media URLs — embed reliably in Discord)
BASEBALL_GIFS = [
    "https://media.giphy.com/media/gxFJTfxbdvWiXdMBML/giphy.gif",  # Jose Siri MLB celebration
    "https://media.giphy.com/media/9SINi6n2Pyi8L9mUgI/giphy.gif",  # Baseball celebration
    "https://media.giphy.com/media/AdD3FhUGmBM9ut6tkJ/giphy.gif",  # MLB celebrate
    "https://media.giphy.com/media/l2SpUepuM4qgdzbeU/giphy.gif",  # Blue Jays home run bat flip
    "https://media.giphy.com/media/xT4uQoOdzH2fgUaBTG/giphy.gif",  # Home run bat flip
    "https://media.giphy.com/media/fxaTBgdsxE5wTBNsDQ/giphy.gif",  # MLB bat flip
    "https://media.giphy.com/media/z2sV2rxqw2dcZCZk5l/giphy.gif",  # Bautista bat flip
    "https://media.giphy.com/media/qkTWlCyvtrNbF6tLQe/giphy.gif",  # Tatis bat flip Padres
    "https://media.giphy.com/media/eNw9itCqqALFaoI3e8/giphy.gif",  # Home run bat flip
]

CHANNEL_ID = "1486423858318938123"
BLITZ_START_UTC = "2026-05-14T17:30:00Z"
BLITZ_END_UTC = "2026-05-14T19:00:00Z"
QUALIFIER_CALLS = 30

def get_sf_token():
    token_file = os.path.expanduser("~/.openclaw/workspace/sf-tokens.json")
    with open(token_file) as f:
        return json.load(f)

def sf_query(instance, token, soql):
    url = instance + "/services/data/v57.0/query?q=" + urllib.parse.quote(soql)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    resp = urllib.request.urlopen(req, timeout=15)
    return json.load(resp)

def refresh_token_if_needed(sf):
    """Try a test query; if 401 refresh token"""
    try:
        sf_query(sf["instance_url"], sf["access_token"], "SELECT Id FROM Task LIMIT 1")
        return sf
    except Exception:
        # Attempt refresh
        token_file = os.path.expanduser("~/.openclaw/workspace/sf-tokens.json")
        refresh_data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": sf["refresh_token"],
            "client_id": sf.get("client_id", "3MVG9n_HvETGhr3BmBadfXa4b_e4REMhOEHwRr.UJ0T60qMwEgBhGl2y8eWiicqb8D5j_F0hy9BQZJG6Aap7H"),
        }).encode()
        req = urllib.request.Request(
            "https://login.salesforce.com/services/oauth2/token",
            data=refresh_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        new_tokens = json.load(resp)
        sf["access_token"] = new_tokens["access_token"]
        with open(token_file, "w") as f:
            json.dump(sf, f, indent=2)
        return sf

def get_blitz_calls():
    sf = get_sf_token()
    sf = refresh_token_if_needed(sf)
    instance = sf["instance_url"]
    token = sf["access_token"]

    # Query calls created during the blitz window
    soql = (
        f"SELECT Owner.Name, Subject, Status, CreatedDate "
        f"FROM Task "
        f"WHERE Type = 'Call' "
        f"AND CreatedDate >= {BLITZ_START_UTC} "
        f"AND CreatedDate <= {BLITZ_END_UTC} "
        f"ORDER BY Owner.Name"
    )

    all_records = []
    url = instance + "/services/data/v57.0/query?q=" + urllib.parse.quote(soql)
    while url:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.load(resp)
        all_records.extend(data.get("records", []))
        next_url = data.get("nextRecordsUrl")
        url = (instance + next_url) if next_url else None

    # Aggregate by rep
    reps = {}
    for r in all_records:
        name = r.get("Owner", {}).get("Name", "Unknown")
        subj = r.get("Subject", "")
        if name not in reps:
            reps[name] = {"calls": 0, "contacts": 0, "meetings": 0}
        reps[name]["calls"] += 1
        if subj.startswith("Contact -"):
            reps[name]["contacts"] += 1
        if subj == "Contact - Discovery Meeting Set":
            reps[name]["meetings"] += 1

    return reps

def build_standings(reps, label):
    if not reps:
        return f"📊 **BLITZ STANDINGS — {label}**\n\nNo calls logged yet — phones up! 📞"

    # Sort: qualified first by meetings desc, then unqualified by calls desc
    qualified = [(n, d) for n, d in reps.items() if d["calls"] >= QUALIFIER_CALLS]
    unqualified = [(n, d) for n, d in reps.items() if d["calls"] < QUALIFIER_CALLS]
    qualified.sort(key=lambda x: (-x[1]["meetings"], -x[1]["calls"]))
    unqualified.sort(key=lambda x: (-x[1]["calls"], -x[1]["contacts"]))

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"📊 **BLITZ STANDINGS — {label}**", f"Qualifier: {QUALIFIER_CALLS}+ calls | Winner: most discovery meetings\n"]

    if qualified:
        lines.append("✅ **QUALIFIED**")
        for i, (name, d) in enumerate(qualified):
            medal = medals[i] if i < 3 else "  "
            lines.append(f"{medal} **{name}**: {d['calls']} calls | {d['contacts']} contacts | {d['meetings']} meetings")

    if unqualified:
        lines.append("\n⚠️ **WORKING TOWARD QUALIFIER**")
        for name, d in unqualified:
            needed = QUALIFIER_CALLS - d["calls"]
            lines.append(f"  {name}: {d['calls']} calls | {d['contacts']} contacts | {d['meetings']} meetings ({needed} calls to qualify)")

    gif = random.choice(BASEBALL_GIFS)
    lines.append(f"\n{gif}")
    return "\n".join(lines)

def build_final_standings(reps, label):
    msg = build_standings(reps, label)
    qualified = [(n, d) for n, d in reps.items() if d["calls"] >= QUALIFIER_CALLS]
    if qualified:
        qualified.sort(key=lambda x: (-x[1]["meetings"], -x[1]["calls"]))
        winner_name, winner_data = qualified[0]
        msg += f"\n\n🏆 **WINNER: {winner_name}** with {winner_data['meetings']} discovery meeting(s) set! 🎉"
    else:
        msg += "\n\n⚠️ No reps reached the 30-call qualifier."
    gif = random.choice(BASEBALL_GIFS)
    msg += f"\n\n{gif}"
    return msg

if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "UPDATE"
    is_final = sys.argv[2].lower() == "final" if len(sys.argv) > 2 else False

    try:
        reps = get_blitz_calls()
        if is_final:
            msg = build_final_standings(reps, label)
        else:
            msg = build_standings(reps, label)
    except Exception as e:
        msg = f"📊 **BLITZ STANDINGS — {label}**\n\n⚠️ Could not pull SF data: {e}\nPlease drop your stats manually: `[Name] Calls: X | Contacts: X | Meetings: X`"

    print(msg)
