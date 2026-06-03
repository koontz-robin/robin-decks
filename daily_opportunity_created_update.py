#!/usr/bin/env python3
"""Post a daily opportunities-created leaderboard update to Discord."""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
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


def build_message():
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    ae_csa = payload.get("ae_csa", [])
    sdr_influenced = payload.get("sdr_influenced", [])

    ae_csa_stats = summarize_rows(ae_csa, "Owner")
    sdr_stats = summarize_rows(sdr_influenced, "SDR")
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
    lead_sdr = sdr_ordered[0][0] if sdr_ordered else None

    lines = [
        "🔥 **Daily June Opportunity Creation Update**",
        f"Fresh pull as of **{generated}**: **{total_count}** AE/CSA-created opps for **{money(total_mrr)} MRR**.",
        f"That is **{pace_pct:.1f}%** of the 275-opportunity June target, with **{remaining}** to go.",
        "",
        "🏆 **AE/CSA leaderboard**",
        *(ae_csa_lines or ["No AE/CSA-created opps yet."]),
    ]
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
