#!/usr/bin/env python3
"""Post a daily opportunities-created leaderboard update to Discord."""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
DASHBOARD_SCRIPT = WORKSPACE / "build_june_ae_csa_dashboard.py"
DATA_FILE = WORKSPACE / "sf_june_ae_csa_opps.json"
CONFIG_FILE = Path("/home/openclaw/.openclaw/openclaw.json")

DISCORD_CHANNEL_ID = "1486771241649045576"  # #general in Rev.io Sales Leadership
DASHBOARD_URL = "https://koontz-robin.github.io/robin-decks/june-ae-csa-opportunities.html"
ET = ZoneInfo("America/New_York")


def money(value):
    return f"${value:,.0f}"


def plural(value, singular, plural_text=None):
    return singular if value == 1 else (plural_text or f"{singular}s")


def format_names(names):
    bold_names = [f"**{name}**" for name in names]
    if len(bold_names) <= 1:
        return "".join(bold_names)
    if len(bold_names) == 2:
        return " and ".join(bold_names)
    return f"{', '.join(bold_names[:-1])}, and {bold_names[-1]}"


def load_discord_token():
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return config["channels"]["discord"]["token"]


def post_discord(message):
    token = load_discord_token()
    response = requests.post(
        f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages",
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        json={"content": message},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Discord post failed: {response.status_code} {response.text[:500]}")
    return response.json().get("id")


def refresh_dashboard():
    subprocess.run([sys.executable, str(DASHBOARD_SCRIPT)], cwd=WORKSPACE, check=True)


def summarize_rows(rows, name_field):
    stats = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for row in rows:
        name = row.get(name_field) or row.get("Owner") or "Unknown"
        stats[name]["count"] += 1
        stats[name]["amount"] += float(row.get("Amount") or 0)
    return stats


def top_lines(stats, limit=3):
    ordered = sorted(stats.items(), key=lambda item: (-item[1]["count"], -item[1]["amount"], item[0]))
    lines = []
    for idx, (name, values) in enumerate(ordered[:limit], start=1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}[idx]
        lines.append(
            f"{medal} **{name}** — {values['count']} {plural(values['count'], 'opp')} / {money(values['amount'])} MRR"
        )
    return lines, ordered


def created_date(row):
    date_text = row.get("CreatedDateET")
    if date_text:
        return date_text[:10]

    created_at = row.get("CreatedDate")
    if not created_at:
        return ""
    normalized = created_at.replace("Z", "+00:00")
    if len(normalized) >= 5 and normalized[-5] in {"+", "-"} and normalized[-3] != ":":
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        return datetime.fromisoformat(normalized).astimezone(ET).date().isoformat()
    except ValueError:
        return ""


def build_message():
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    ae_csa = payload.get("ae_csa", [])
    sdr_influenced = payload.get("sdr_influenced", [])

    ae_csa_stats = summarize_rows(ae_csa, "Owner")
    sdr_stats = summarize_rows(sdr_influenced, "SDR")
    yesterday = datetime.now(ET).date() - timedelta(days=1)
    yesterday_rows = [row for row in ae_csa if created_date(row) == yesterday.isoformat()]
    yesterday_stats = summarize_rows(yesterday_rows, "Owner")
    yesterday_lines, yesterday_ordered = top_lines(yesterday_stats)
    ae_csa_lines, ae_csa_ordered = top_lines(ae_csa_stats)
    sdr_lines, sdr_ordered = top_lines(sdr_stats)

    total_count = len(ae_csa)
    total_mrr = sum(float(row.get("Amount") or 0) for row in ae_csa)
    sdr_count = len(sdr_influenced)
    sdr_mrr = sum(float(row.get("Amount") or 0) for row in sdr_influenced)
    pace_pct = total_count / 275 * 100
    remaining = max(275 - total_count, 0)

    generated = datetime.now(ET).strftime("%b %-d, %-I:%M %p ET")
    lead_name = ae_csa_ordered[0][0] if ae_csa_ordered else "the team"
    lead_count = ae_csa_ordered[0][1]["count"] if ae_csa_ordered else 0
    yesterday_lead_count = yesterday_ordered[0][1]["count"] if yesterday_ordered else 0
    yesterday_leaders = [
        name for name, values in yesterday_ordered if values["count"] == yesterday_lead_count
    ]
    lead_sdr = sdr_ordered[0][0] if sdr_ordered else None

    lines = [
        "🔥 **Daily June Opportunity Creation Update**",
        f"Fresh pull as of **{generated}**: **{total_count}** AE/CSA-created opps for **{money(total_mrr)} MRR**.",
        f"That is **{pace_pct:.1f}%** of the 275-opportunity June target, with **{remaining}** to go.",
        "",
        f"📣 **Yesterday's top opportunity creators ({yesterday.strftime('%b %-d')})**",
        *(yesterday_lines or ["No AE/CSA-created opps were logged yesterday."]),
    ]
    if yesterday_lead_count:
        leader_text = format_names(yesterday_leaders)
        lines.append(
            f"Big shoutout to {leader_text} for leading yesterday with **{yesterday_lead_count}** "
            f"{plural(yesterday_lead_count, 'opp')} created."
        )
    lines.extend(
        [
            "",
            "🏆 **AE/CSA leaderboard**",
            *(ae_csa_lines or ["No AE/CSA-created opps yet."]),
        ]
    )
    if lead_count:
        lines.append(f"Big shoutout to **{lead_name}** setting the pace at **{lead_count}** created opps.")
    lines.extend(
        [
            "",
            "🎯 **SDR influence leaderboard**",
            *(sdr_lines or ["No SDR-influenced opps yet."]),
        ]
    )
    if lead_sdr:
        lines.append(f"Love seeing **{lead_sdr}** driving influence at the top of the board.")
    lines.extend(
        [
            "",
            f"Full dashboard: <{DASHBOARD_URL}>",
            "Keep the pressure on. Every clean opp created now gives June more room to run.",
        ]
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print the message without posting to Discord.")
    parser.add_argument("--skip-refresh", action="store_true", help="Use the current local data file without rebuilding.")
    args = parser.parse_args()

    if not args.skip_refresh:
        refresh_dashboard()
    message = build_message()
    if args.dry_run:
        print(message)
        return
    message_id = post_discord(message)
    print(f"Posted opportunity dashboard update to Discord channel {DISCORD_CHANNEL_ID}: {message_id}")


if __name__ == "__main__":
    main()
