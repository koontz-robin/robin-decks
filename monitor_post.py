#!/usr/bin/env python3
import json, requests, time, random
from datetime import datetime, timezone
from collections import defaultdict
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

SF_CLIENT_ID     = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
SF_INSTANCE      = "https://rev-io.my.salesforce.com"
CHANNEL_ID       = "1486423858318938123"
GIPHY_KEY        = "Zum3IsXqEn0LoQasRcZnFMi6g5TgbXKl"

with open('/home/openclaw/.openclaw/openclaw.json') as f:
    _cfg = json.load(f)
DISCORD_TOKEN = _cfg['channels']['discord']['token']

REPS = {
    "005PX000008w46fYAA": "Abbey McIntosh",
    "005PX000009dGu9YAE": "Abigail Marchese",
    "005PX00000B2djhYAB": "Blake Boatright",
    "005PX00000AoGqDYAV": "Emily Petraglia",
    "005PX00000B2bhuYAB": "Miguel Ocampo",
    "005PX00000B2dBpYAJ": "Ptah Robinson",
    "0056O00000DFarwQAD": "Andy Whisenant",
    "005PX000000AH61YAG": "Connor Flynn",
    "005PX000004gCgnYAE": "Davis Herndon",
    "005PX000004D6GbYAK": "Husam Zalmiyar",
    "005PX000000BXiDYAW": "Jake Borah",
    "005PX000002c1zdYAA": "Jamie Butler",
    "005PX000004D6QIYA0": "Jaylin Bender",
    "005PX000004D6QHYA0": "Joseph Abarno",
    "005PX000005fXd3YAE": "Patrick Davies",
    "0056O00000Bi7GZQAZ": "Ingrid Beard",
    "0051C000009eXIGQA2": "Justin Lee",
}

HYPE_GIFS = [
    "lets go celebration",
    "hype excited",
    "phone call hustle",
    "keep going motivation",
    "grind hustle",
    "fired up excited",
]

WINNER_GIFS = [
    "winner celebration",
    "champion trophy",
    "victory dance",
    "we did it celebration",
]

CALL_MINIMUM = 30

def get_gif(search_term):
    try:
        r = requests.get("https://api.giphy.com/v1/gifs/search", params={
            "api_key": GIPHY_KEY, "q": search_term, "limit": 10, "rating": "pg"
        }, timeout=5)
        results = r.json().get("data", [])
        if results:
            pick = random.choice(results[:5])
            return pick["images"]["original"]["url"]
    except Exception:
        pass
    return None

def sf_auth():
    r = requests.post(SF_INSTANCE + "/services/oauth2/token", data={
        "grant_type": "client_credentials",
        "client_id": SF_CLIENT_ID,
        "client_secret": SF_CLIENT_SECRET
    })
    return r.json()["access_token"]

def get_snapshot(sf_tok, window_start, window_end):
    headers = {"Authorization": "Bearer " + sf_tok}
    owner_ids = "','".join(REPS.keys())
    query = ("SELECT OwnerId, Subject, Type, CreatedDate FROM Task"
             " WHERE OwnerId IN ('" + owner_ids + "')"
             " AND CreatedDate >= " + window_start +
             " AND CreatedDate <= " + window_end +
             " AND IsDeleted = false")
    resp = requests.get(SF_INSTANCE + "/services/data/v59.0/query",
                        params={"q": query}, headers=headers)
    tasks = resp.json().get("records", [])
    scores = defaultdict(lambda: {"calls": 0, "contacts": 0, "meetings_set": 0})
    for t in tasks:
        uid = t.get("OwnerId")
        if uid not in REPS:
            continue
        name = REPS[uid]
        typ = (t.get("Type") or "").lower()
        subj = (t.get("Subject") or "").lower()
        if typ == "call":
            scores[name]["calls"] += 1
            if "contact" in subj and "discovery meeting set" in subj:
                scores[name]["meetings_set"] += 1
            elif "contact" in subj:
                scores[name]["contacts"] += 1
    return scores, len(tasks)

def post_discord(message):
    hdrs = {"Authorization": "Bot " + DISCORD_TOKEN, "Content-Type": "application/json"}
    r = requests.post("https://discord.com/api/v10/channels/" + CHANNEL_ID + "/messages",
                      headers=hdrs, json={"content": message})
    print("Discord: " + str(r.status_code), flush=True)

def shoutout_new_meetings(prev_scores, curr_scores):
    for name in curr_scores:
        prev = prev_scores.get(name, {}).get("meetings_set", 0)
        curr = curr_scores[name]["meetings_set"]
        for _ in range(curr - prev):
            gif_url = get_gif(random.choice(["celebration excited", "yes lets go", "hype celebration", "victory dance"]))
            msg = (
                "🚨 **MEETING SET ALERT** 🚨\n"
                "📞 **" + name + "** just booked a discovery meeting! "
                "That's what we're here for — LET'S GO! 🔥🎉"
            )
            if gif_url:
                msg += "\n" + gif_url
            post_discord(msg)
            time.sleep(1)

def build_msg(scores, et_label, is_final=False):
    ranked = sorted(scores.items(),
                    key=lambda x: x[1]["meetings_set"] * 100 + x[1]["contacts"] * 10 + x[1]["calls"],
                    reverse=True)
    active = [(n, s) for n, s in ranked if any(v > 0 for v in s.values())]

    gif_term = random.choice(WINNER_GIFS if is_final else HYPE_GIFS)
    gif_url = get_gif(gif_term)

    if is_final:
        label = "🏁 **FINAL STANDINGS — 1:30-3 PM Blitz** 🏁"
    else:
        hype_lines = [
            "⚡ Blitz check-in! How's everyone dialing?",
            "🔥 Mid-blitz update — who's on fire?",
            "📞 Standings board — keep those dials coming!",
            "💥 Time check — push push push!",
            "🚀 Leaderboard update — no letting up!",
        ]
        label = random.choice(hype_lines) + "\n📊 **" + et_label + " ET Standings**"

    lines = [label, "```"]
    lines.append("   " + "Rep".ljust(20) + "Calls".rjust(7) + "Contacts".rjust(10) + "Mtgs Set".rjust(10))
    lines.append("-" * 50)
    pfx = ["🥇", "🥈", "🥉"]
    if active:
        for i, (n, s) in enumerate(active):
            p = pfx[i] if i < 3 else "  "
            qual = " ✓" if s["calls"] >= CALL_MINIMUM else "  "
            lines.append(p + qual + " " + n.ljust(19) + str(s["calls"]).rjust(6) + str(s["contacts"]).rjust(10) + str(s["meetings_set"]).rjust(10))
    else:
        lines.append("  No activity yet — phones aren't going to dial themselves!")
    lines.append("")
    lines.append(f"  ✓ = qualifies ({CALL_MINIMUM}+ calls) | Win = most meetings set (contacts as tiebreaker)")
    lines.append("```")

    if is_final:
        qualified = [(n, s) for n, s in ranked if s["calls"] >= CALL_MINIMUM]
        if qualified:
            winner_name, winner_stats = sorted(qualified, key=lambda x: (x[1]["meetings_set"], x[1]["contacts"]), reverse=True)[0]
            lines.append("")
            lines.append("🏆 **WINNER: " + winner_name.upper() + "** 🏆")
            lines.append(str(winner_stats["meetings_set"]) + " meetings set | " + str(winner_stats["calls"]) + " calls")
            lines.append("CONGRATS " + winner_name + "!! That's how it's done! 🎉🎉🎉")
            gif_url = get_gif("winner champion celebration")
        else:
            lines.append("")
            lines.append(f"❌ **No winner declared** — nobody hit the {CALL_MINIMUM}-call minimum. Step it up! 💪")
            gif_url = get_gif(random.choice(["disappointed sad", "no winner"]))

    if gif_url:
        lines.append("")
        lines.append(gif_url)

    return "\n".join(lines)

def et_to_utc(h, m):
    now_et = datetime.now(ET)
    et_dt = now_et.replace(hour=h, minute=m, second=5, microsecond=0)
    return et_dt.astimezone(timezone.utc)

# Blitz window in ET
blitz_start_et = datetime.now(ET).replace(hour=13, minute=30, second=0, microsecond=0)
blitz_end_et   = datetime.now(ET).replace(hour=15, minute=0,  second=0, microsecond=0)
ws = blitz_start_et.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
we = blitz_end_et.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

checkpoints = [
    (13, 30, "1:30 PM", False),
    (13, 50, "1:50 PM", False),
    (14, 10, "2:10 PM", False),
    (14, 30, "2:30 PM", False),
    (14, 50, "2:50 PM", False),
    (15,  0, "3:00 PM", True),
]

prev_scores = {}
for et_h, et_m, et_l, final in checkpoints:
    tgt = et_to_utc(et_h, et_m)
    now = datetime.now(timezone.utc)
    wait = (tgt - now).total_seconds()
    if wait > 0:
        print("Waiting until " + et_l + " ET (" + str(int(wait)) + "s)...", flush=True)
        time.sleep(wait)
    sf_tok = sf_auth()
    scores, total = get_snapshot(sf_tok, ws, we)
    shoutout_new_meetings(prev_scores, scores)
    prev_scores = {n: dict(s) for n, s in scores.items()}
    msg = build_msg(scores, et_l, final)
    print("[" + et_l + "] tasks=" + str(total), flush=True)
    post_discord(msg)

print("DONE", flush=True)
