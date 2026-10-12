#!/usr/bin/env python3
"""Build and publish the 2026 Q4 Secret Santa sales contest dashboard."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from datetime import date, datetime, time, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from refresh_monday_team_activity_dashboard import (
    get_team_members,
    normalize_name,
    sf_auth,
    sf_query,
)

WORKSPACE = Path(os.environ.get("ROBIN_WORKSPACE", "/home/openclaw/.openclaw/workspace"))
HTML_FILE = WORKSPACE / "q4-secret-santa-contest.html"
DATA_FILE = WORKSPACE / "q4_secret_santa_contest.json"
LIBRARY_FILE = WORKSPACE / "DECKS-LIBRARY.md"
ET = ZoneInfo("America/New_York")
CONTEST_START = date(2026, 10, 1)
CONTEST_END = date(2026, 12, 17)


def iso_utc(d: date) -> str:
    return datetime.combine(d, time.min, ET).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def money(v):
    return f"${float(v or 0):,.0f}"


def build_payload():
    now_et = datetime.now(ET)
    through = min(now_et.date(), CONTEST_END)
    end_exclusive = min(now_et.date() + __import__("datetime").timedelta(days=1), CONTEST_END + __import__("datetime").timedelta(days=1))
    base, headers = sf_auth()
    roster = get_team_members(base, headers)
    people = {
        name: {
            "name": name, "role": role, "closed_won": 0, "closed_mrr": 0.0,
            "sdr_discoveries": 0, "sdr_wins": 0, "calls": 0,
        }
        for name, role in roster.items()
    }

    wins = sf_query(base, headers, f"""
        SELECT Id, Name, Amount, CloseDate, Owner.Name, SDR_Influence__c, Account.Name
        FROM Opportunity
        WHERE IsDeleted = false
          AND StageName = 'Closed Won'
          AND CloseDate >= {CONTEST_START.isoformat()}
          AND CloseDate < {end_exclusive.isoformat()}
    """)
    for opp in wins:
        owner = normalize_name((opp.get("Owner") or {}).get("Name"))
        amount = max(0.0, float(opp.get("Amount") or 0))
        if owner in people:
            people[owner]["closed_won"] += 1
            people[owner]["closed_mrr"] += amount
        sdr = normalize_name(opp.get("SDR_Influence__c"))
        if sdr in people and people[sdr]["role"] == "SDR":
            people[sdr]["sdr_wins"] += 1

    discoveries = sf_query(base, headers, f"""
        SELECT Id, ActivityDate, SDR_Influence__c
        FROM Event
        WHERE IsDeleted = false
          AND ActivityDate >= {CONTEST_START.isoformat()}
          AND ActivityDate < {end_exclusive.isoformat()}
          AND Type = '1-Discovery Call'
          AND SDR_Influence__c != null
          AND SDR_Influence__c != 'None'
    """)
    for event in discoveries:
        sdr = normalize_name(event.get("SDR_Influence__c"))
        if sdr in people and people[sdr]["role"] == "SDR":
            people[sdr]["sdr_discoveries"] += 1

    calls = sf_query(base, headers, f"""
        SELECT Owner.Name, COUNT(Id) total
        FROM Task
        WHERE IsDeleted = false
          AND CreatedDate >= {iso_utc(CONTEST_START)}
          AND CreatedDate < {iso_utc(end_exclusive)}
          AND Type = 'Call'
        GROUP BY Owner.Name
    """)
    for row in calls:
        owner = normalize_name(row.get("Name") or row.get("Owner.Name"))
        # Salesforce aggregate relationship fields can be flattened or nested.
        if not owner:
            owner = normalize_name((row.get("Owner") or {}).get("Name"))
        if owner in people:
            people[owner]["calls"] = int(row.get("total") or 0)

    for p in people.values():
        p["points_closed_won"] = p["closed_won"] * 5
        p["points_mrr"] = math.floor(p["closed_mrr"] / 1000) * 10
        p["points_discoveries"] = p["sdr_discoveries"] * 2
        p["points_sdr_wins"] = p["sdr_wins"] * 5
        p["points_calls"] = math.floor(p["calls"] / 500) * 10
        p["points"] = sum(p[k] for k in (
            "points_closed_won", "points_mrr", "points_discoveries",
            "points_sdr_wins", "points_calls",
        ))
        p["calls_to_next_bonus"] = 500 - (p["calls"] % 500) if p["calls"] % 500 else 500

    standings = sorted(people.values(), key=lambda p: (-p["points"], -p["closed_mrr"], -p["closed_won"], p["name"]))
    last_points = None
    rank = 0
    for idx, p in enumerate(standings, 1):
        if p["points"] != last_points:
            rank = idx
            last_points = p["points"]
        p["rank"] = rank

    # Lowest score picks first; deterministic alphabetical tie-break for equal scores.
    pick_order = sorted(standings, key=lambda p: (p["points"], p["closed_mrr"], p["closed_won"], p["name"]))
    for pick, p in enumerate(pick_order, 1):
        p["pick_order"] = pick

    total_days = (CONTEST_END - CONTEST_START).days + 1
    elapsed_days = max(0, min(total_days, (through - CONTEST_START).days + 1))
    return {
        "generated_at_et": now_et.strftime("%b %-d, %Y %-I:%M %p ET"),
        "contest": {
            "start": CONTEST_START.isoformat(), "end": CONTEST_END.isoformat(),
            "through": through.isoformat(), "elapsed_days": elapsed_days,
            "total_days": total_days, "percent_complete": round(elapsed_days / total_days * 100, 1),
        },
        "standings": standings,
        "pick_order": [p["name"] for p in pick_order],
        "totals": {
            "points": sum(p["points"] for p in standings),
            "closed_won": sum(p["closed_won"] for p in standings),
            "mrr": sum(p["closed_mrr"] for p in standings),
            "discoveries": sum(p["sdr_discoveries"] for p in standings),
            "sdr_wins": sum(p["sdr_wins"] for p in standings),
            "calls": sum(p["calls"] for p in standings),
        },
        "rules": [
            {"label": "Closed-won opportunity", "points": "5 pts each"},
            {"label": "Closed MRR", "points": "10 pts per full $1,000"},
            {"label": "Discovery meeting sourced (SDRs)", "points": "2 pts each"},
            {"label": "Closed-won opportunity sourced (SDRs)", "points": "5 pts each"},
            {"label": "Calls logged", "points": "10 pts per full 500"},
        ],
    }


def build_html(payload):
    standings = payload["standings"]
    totals = payload["totals"]
    contest = payload["contest"]
    leader_points = standings[0]["points"] if standings else 0
    podium = "".join(
        f'<div class="podium p{i}"><div class="medal">{["🥇","🥈","🥉"][i-1]}</div><div class="podium-name">{escape(p["name"])}</div><div class="podium-role">{escape(p["role"])}</div><div class="podium-points">{p["points"]} pts</div><div class="pick">Picks #{p["pick_order"]}</div></div>'
        for i, p in enumerate(standings[:3], 1)
    )
    rows = []
    for p in standings:
        gap = leader_points - p["points"]
        rows.append(f'''<tr>
          <td class="rank">#{p['rank']}</td>
          <td><strong>{escape(p['name'])}</strong><small>{escape(p['role'])}</small></td>
          <td class="points">{p['points']}</td>
          <td>{p['closed_won']}<small>{p['points_closed_won']} pts</small></td>
          <td>{money(p['closed_mrr'])}<small>{p['points_mrr']} pts</small></td>
          <td>{p['sdr_discoveries']}<small>{p['points_discoveries']} pts</small></td>
          <td>{p['sdr_wins']}<small>{p['points_sdr_wins']} pts</small></td>
          <td>{p['calls']:,}<small>{p['points_calls']} pts · {p['calls_to_next_bonus']:,} to bonus</small></td>
          <td class="pick-number">#{p['pick_order']}</td>
          <td>{'Leader' if gap == 0 else f'{gap} pts back'}</td>
        </tr>''')
    rule_cards = "".join(f'<div class="rule"><span>🎁</span><strong>{escape(r["points"])}</strong><small>{escape(r["label"])}</small></div>' for r in payload["rules"])
    pick_list = "".join(f'<li><span>{i}</span>{escape(name)}</li>' for i, name in enumerate(payload["pick_order"], 1))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Q4 Secret Santa Contest</title>
<style>
:root{{--pine:#062f26;--pine2:#0a4938;--red:#c62828;--red2:#8f151b;--gold:#f4cf73;--cream:#fff9e9;--ink:#16372f;--snow:#f7fbff;--muted:#6d7d76}}*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,Segoe UI,system-ui,sans-serif;background:radial-gradient(circle at 15% 5%,rgba(255,255,255,.16),transparent 24%),linear-gradient(145deg,#041e19,#083f31 55%,#5b1118);color:var(--cream);min-height:100vh}}body:before{{content:'❄   ·   ❅      ·   ❄   ·      ❅   ·   ❄      ·   ❅';position:fixed;inset:0;font-size:34px;line-height:110px;word-spacing:44px;color:rgba(255,255,255,.12);pointer-events:none;transform:rotate(-8deg) scale(1.2)}}.wrap{{position:relative;z-index:1;max-width:1580px;margin:auto;padding:22px}}.hero{{position:relative;overflow:hidden;background:linear-gradient(130deg,rgba(6,47,38,.96),rgba(10,73,56,.9));border:1px solid rgba(244,207,115,.45);border-radius:26px;padding:28px 30px;box-shadow:0 28px 80px rgba(0,0,0,.35)}}.lights{{position:absolute;left:0;right:0;top:0;height:12px;background:repeating-linear-gradient(90deg,#e43131 0 14px,#f4cf73 14px 28px,#fff 28px 42px,#2db56f 42px 56px);box-shadow:0 0 24px rgba(244,207,115,.7)}}.eyebrow{{color:var(--gold);font-size:11px;font-weight:800;letter-spacing:.22em;text-transform:uppercase}}h1{{font-family:Georgia,serif;font-size:clamp(42px,6vw,78px);line-height:.95;margin:13px 0 10px;font-weight:500}}h1 em{{color:var(--gold)}}.sub{{max-width:850px;color:#dce9e4;font-size:15px;line-height:1.55}}.progress-wrap{{margin-top:20px;display:flex;align-items:center;gap:14px}}.track{{height:10px;flex:1;max-width:650px;background:rgba(255,255,255,.12);border-radius:99px;overflow:hidden}}.bar{{height:100%;width:{contest['percent_complete']}%;background:linear-gradient(90deg,#dc3038,var(--gold));border-radius:99px}}.progress-label{{font-size:12px;color:#dce9e4}}.stats{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:14px 0}}.stat,.panel{{background:rgba(255,249,233,.97);color:var(--ink);border-radius:17px;border:1px solid rgba(244,207,115,.52);box-shadow:0 18px 50px rgba(0,0,0,.2)}}.stat{{padding:15px}}.stat strong{{font-size:25px;display:block}}.stat small{{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.12em;font-weight:800}}.rules{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:14px 0}}.rule{{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);border-radius:15px;padding:13px;min-height:92px}}.rule span{{font-size:20px;float:right}}.rule strong,.rule small{{display:block}}.rule strong{{color:var(--gold);font-size:17px;margin-bottom:6px}}.rule small{{color:#e4eee9;line-height:1.3}}.podiums{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:14px 0}}.podium{{text-align:center;border-radius:18px;padding:17px;background:linear-gradient(145deg,rgba(255,249,233,.98),rgba(244,207,115,.88));color:var(--ink);border:2px solid var(--gold)}}.p1{{transform:translateY(-4px);box-shadow:0 0 35px rgba(244,207,115,.32)}}.medal{{font-size:30px}}.podium-name{{font-weight:900;font-size:18px}}.podium-role{{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em}}.podium-points{{font-size:27px;font-weight:900;color:var(--red)}}.pick{{font-size:11px;font-weight:800;color:var(--pine2)}}.grid{{display:grid;grid-template-columns:minmax(0,4fr) minmax(250px,1fr);gap:14px}}.panel{{overflow:hidden}}.panel-head{{padding:15px 17px;background:linear-gradient(90deg,#f6ecd0,#fff9e9);border-bottom:1px solid #e6dcc4}}h2{{margin:0;font-family:Georgia,serif;font-size:22px}}.panel-note{{font-size:11px;color:var(--muted);margin-top:4px}}.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:1120px}}th{{font-size:9px;letter-spacing:.09em;text-transform:uppercase;text-align:left;color:#6d7d76;background:#f5f0e3;padding:10px}}td{{padding:11px 10px;border-top:1px solid #eee7d8;font-size:13px}}td strong,td small{{display:block}}td small{{font-size:10px;color:var(--muted);margin-top:2px}}.rank,.points,.pick-number{{font-weight:900}}.points{{font-size:20px;color:var(--red)}}.pick-number{{font-size:17px;color:var(--pine2)}}ol{{list-style:none;margin:0;padding:10px 16px 18px}}li{{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px dashed #ddd3bc;font-weight:700;font-size:13px}}li span{{width:25px;height:25px;border-radius:50%;display:grid;place-items:center;background:var(--red);color:white;font-size:11px}}.footer{{text-align:center;color:#d9e8e2;font-size:10px;letter-spacing:.1em;padding:18px}}@media(max-width:1050px){{.stats,.rules{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}}}@media(max-width:650px){{.wrap{{padding:10px}}.hero{{padding:24px 18px}}.podiums{{grid-template-columns:1fr}}.p1{{transform:none}}}}
</style></head><body><main class="wrap"><section class="hero"><div class="lights"></div><div class="eyebrow">Rev.io Sales · Q4 2026</div><h1>Secret Santa <em>Showdown</em> 🎄</h1><div class="sub">Earn points from October 1 through December 17. The twist: the leaderboard runs opposite the gift table—<strong>last place picks first, and the leader picks last.</strong></div><div class="progress-wrap"><div class="track"><div class="bar"></div></div><div class="progress-label">{contest['percent_complete']:.0f}% complete · Through {escape(contest['through'])}</div></div></section>
<section class="stats"><div class="stat"><strong>{totals['points']:,}</strong><small>Total points</small></div><div class="stat"><strong>{totals['closed_won']:,}</strong><small>Closed-won deals</small></div><div class="stat"><strong>{money(totals['mrr'])}</strong><small>Closed MRR</small></div><div class="stat"><strong>{totals['discoveries']:,}</strong><small>SDR discoveries</small></div><div class="stat"><strong>{totals['calls']:,}</strong><small>Calls logged</small></div></section>
<section class="rules">{rule_cards}</section><section class="podiums">{podium}</section>
<section class="grid"><div class="panel"><div class="panel-head"><h2>Leaderboard</h2><div class="panel-note">MRR and call bonuses award points only for each full threshold reached.</div></div><div class="table-wrap"><table><thead><tr><th>Rank</th><th>Teammate</th><th>Points</th><th>Closed Won</th><th>Closed MRR</th><th>SDR Discoveries</th><th>SDR-Sourced Wins</th><th>Calls</th><th>Pick</th><th>Gap</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></div><aside class="panel"><div class="panel-head"><h2>🎁 Gift Pick Order</h2><div class="panel-note">Lowest score picks first. Equal-score ties are ordered alphabetically.</div></div><ol>{pick_list}</ol></aside></section>
<div class="footer">SALESFORCE LIVE DATA · GENERATED {escape(payload['generated_at_et'])} · CONTEST ENDS DECEMBER 17, 2026</div></main></body></html>'''


def update_library():
    row = "| Q4 Secret Santa Contest | q4-secret-santa-contest.html | https://koontz-robin.github.io/robin-decks/q4-secret-santa-contest.html | On demand |"
    text = LIBRARY_FILE.read_text(encoding="utf-8")
    if "q4-secret-santa-contest.html" not in text:
        text = text.rstrip() + "\n" + row + "\n"
        LIBRARY_FILE.write_text(text, encoding="utf-8")


def publish(paths):
    tmp_parent = Path(tempfile.mkdtemp(prefix="secret-santa-publish."))
    repo = tmp_parent / "repo"
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = "ssh -i /home/openclaw/.openclaw/ssh/id_ed25519 -o StrictHostKeyChecking=no"
    try:
        subprocess.run(["git", "clone", "git@github.com:koontz-robin/robin-decks.git", str(repo)], check=True, env=env)
        subprocess.run(["git", "config", "user.name", "Robin"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "robin.bot@rev.io"], cwd=repo, check=True)
        for path in paths:
            shutil.copy2(path, repo / path.name)
        subprocess.run(["git", "add", *[p.name for p in paths]], cwd=repo, check=True)
        changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode != 0
        if changed:
            subprocess.run(["git", "commit", "-m", "Add Q4 Secret Santa contest dashboard"], cwd=repo, check=True)
            subprocess.run(["git", "push", "origin", "master"], cwd=repo, check=True, env=env)
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    payload = build_payload()
    DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HTML_FILE.write_text(build_html(payload), encoding="utf-8")
    update_library()
    if os.environ.get("NO_PUBLISH") != "1":
        publish([HTML_FILE, DATA_FILE, LIBRARY_FILE, Path(__file__).resolve()])
    print(f"Built {HTML_FILE}")
    print(f"URL: https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")


if __name__ == "__main__":
    main()
