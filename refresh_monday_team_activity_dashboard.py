#!/usr/bin/env python3
"""Refresh Monday team activity dashboard.

Compares last full Monday-Sunday week to the prior Monday-Sunday week using
Salesforce Tasks, Events, Opportunities, and stage-history movement.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path(os.environ.get("ROBIN_WORKSPACE", "/home/openclaw/.openclaw/workspace"))
HTML_FILE = WORKSPACE / "monday-team-activity-dashboard.html"
DATA_FILE = WORKSPACE / "monday_team_activity_dashboard.json"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
ET = ZoneInfo("America/New_York")

NAME_ALIASES = {"Andrew Whisenant": "Andy Whisenant"}
EXCLUDED_REPS = {
    "Ardit Berdyna", "Blaine Villafuerte", "Cam Sharpe", "Davis Herndon",
    "Jake Mitchell", "Matt Salin", "Olivia Sandefur", "Reid Doster", "Usman Zahoor",
}
ROLE_GROUPS = {"SDRs": "SDR", "MSP Sales": "AE", "Integrator Sales": "AE", "CSA": "CSA"}
KNOWN_AES = {"Andy Whisenant", "Connor Flynn", "Husam Zalmiyar", "Jake Borah", "Jamie Butler", "Jaylin Bender", "Patrick Davies"}
KNOWN_CSAS = {"Ingrid Beard", "Justin Lee"}
STAGE_ORDER = {
    "Closed Lost": 0,
    "1- Discovery Scheduled": 1,
    "2 - Discovery Completed": 2,
    "3 - Initial Product Demo": 3,
    "4 - Proposal Sent": 4,
    "5 - Product / Contract Validated": 5,
    "6 - Verbal Commit": 6,
    "Closed Won": 7,
}


def normalize_name(name: str | None) -> str:
    clean = (name or "").strip()
    return NAME_ALIASES.get(clean, clean)


def sf_auth():
    r = requests.post(
        f"{SF_INSTANCE}/services/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": SF_CLIENT_ID, "client_secret": SF_CLIENT_SECRET},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()
    return token["instance_url"], {"Authorization": f"Bearer {token['access_token']}"}


def sf_query(base, headers, query):
    url = f"{base}/services/data/v59.0/query"
    params = {"q": query.strip()}
    records = []
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Salesforce query failed: {r.status_code} {r.text[:1000]}")
        data = r.json()
        records.extend(data.get("records", []))
        if data.get("done", True):
            return records
        url = base + data["nextRecordsUrl"]
        params = {}


def week_windows(now_et: datetime):
    today = now_et.date()
    this_monday = today - timedelta(days=today.weekday())
    # Sunday-night refresh should include the week that just ended Sunday.
    # Monday and later should use the previous completed Monday-Sunday week.
    if today.weekday() == 6:
        last_start = this_monday
        last_end = this_monday + timedelta(days=7)
    else:
        last_start = this_monday - timedelta(days=7)
        last_end = this_monday
    prior_start = last_start - timedelta(days=7)
    prior_end = last_start
    return {
        "last": (datetime.combine(last_start, time.min, ET), datetime.combine(last_end, time.min, ET)),
        "prior": (datetime.combine(prior_start, time.min, ET), datetime.combine(prior_end, time.min, ET)),
    }


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sf_date(dt: datetime) -> str:
    return dt.date().isoformat()


def period_for_dt(dt: datetime, windows):
    for key, (start, end) in windows.items():
        if start <= dt < end:
            return key
    return None


def get_team_members(base, headers):
    role_list = ", ".join(f"'{role}'" for role in ROLE_GROUPS)
    users = sf_query(base, headers, f"""
        SELECT Name, UserRole.Name
        FROM User
        WHERE IsActive = true AND UserRole.Name IN ({role_list})
        ORDER BY Name
    """)
    reps = {}
    for u in users:
        role = ((u.get("UserRole") or {}).get("Name") or "").strip()
        name = normalize_name(u.get("Name"))
        if name and name not in EXCLUDED_REPS:
            reps[name] = ROLE_GROUPS.get(role, "Other")
    for name in KNOWN_AES:
        if name not in EXCLUDED_REPS:
            reps.setdefault(name, "AE")
    for name in KNOWN_CSAS:
        if name not in EXCLUDED_REPS:
            reps.setdefault(name, "CSA")
    return reps


def classify_task(task):
    subtype = (task.get("TaskSubtype") or "").lower()
    subject = (task.get("Subject") or "").lower()
    typ = (task.get("Type") or "").lower()
    hay = " ".join([subtype, subject, typ])
    if "call" in hay:
        return "calls"
    if "email" in hay:
        return "emails"
    return "tasks"


def empty_rep(role=""):
    return {
        "role": role,
        "activities": {"last": 0, "prior": 0},
        "calls": {"last": 0, "prior": 0},
        "emails": {"last": 0, "prior": 0},
        "tasks": {"last": 0, "prior": 0},
        "meetings": {"last": 0, "prior": 0},
        "opps_created": {"last": 0, "prior": 0},
        "opps_created_mrr": {"last": 0.0, "prior": 0.0},
        "stage_advances": {"last": 0, "prior": 0},
        "stage_steps": {"last": 0, "prior": 0},
        "closed_won": {"last": 0, "prior": 0},
        "closed_won_mrr": {"last": 0.0, "prior": 0.0},
    }


def amount(rec):
    try:
        return float(rec.get("Amount") or 0)
    except Exception:
        return 0.0


def stage_delta(old, new):
    oi = STAGE_ORDER.get(str(old or ""))
    ni = STAGE_ORDER.get(str(new or ""))
    if oi is None or ni is None:
        return 1
    return max(0, ni - oi)


def build_payload():
    now_et = datetime.now(ET)
    windows = week_windows(now_et)
    range_start, range_end = windows["prior"][0], windows["last"][1]
    base, headers = sf_auth()
    reps = get_team_members(base, headers)
    metrics = {rep: empty_rep(role) for rep, role in reps.items()}

    tasks = sf_query(base, headers, f"""
        SELECT Id, Subject, Type, TaskSubtype, CreatedDate, Owner.Name
        FROM Task
        WHERE IsDeleted = false
          AND CreatedDate >= {iso_utc(range_start)}
          AND CreatedDate < {iso_utc(range_end)}
    """)
    for task in tasks:
        rep = normalize_name((task.get("Owner") or {}).get("Name"))
        if rep not in metrics:
            continue
        dt = datetime.strptime(task["CreatedDate"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(ET)
        period = period_for_dt(dt, windows)
        if not period:
            continue
        kind = classify_task(task)
        metrics[rep]["activities"][period] += 1
        metrics[rep][kind][period] += 1

    events = sf_query(base, headers, f"""
        SELECT Id, Subject, ActivityDate, StartDateTime, IsDeleted, Owner.Name
        FROM Event
        WHERE IsDeleted = false
          AND ActivityDate >= {sf_date(range_start)}
          AND ActivityDate < {sf_date(range_end)}
    """)
    for ev in events:
        rep = normalize_name((ev.get("Owner") or {}).get("Name"))
        if rep not in metrics:
            continue
        subj = (ev.get("Subject") or "").lower()
        if "cancel" in subj or "internal" in subj:
            continue
        dt = datetime.fromisoformat(ev["ActivityDate"]).replace(tzinfo=ET)
        period = period_for_dt(dt, windows)
        if not period:
            continue
        metrics[rep]["activities"][period] += 1
        metrics[rep]["meetings"][period] += 1

    opps_created = sf_query(base, headers, f"""
        SELECT Id, Name, Amount, CreatedDate, StageName, Product_Type__c, Owner.Name
        FROM Opportunity
        WHERE IsDeleted = false
          AND CreatedDate >= {iso_utc(range_start)}
          AND CreatedDate < {iso_utc(range_end)}
    """)
    for opp in opps_created:
        rep = normalize_name((opp.get("Owner") or {}).get("Name"))
        if rep not in metrics:
            continue
        dt = datetime.strptime(opp["CreatedDate"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(ET)
        period = period_for_dt(dt, windows)
        if not period:
            continue
        metrics[rep]["opps_created"][period] += 1
        metrics[rep]["opps_created_mrr"][period] += amount(opp)

    opps_closed = sf_query(base, headers, f"""
        SELECT Id, Name, Amount, CloseDate, StageName, Owner.Name
        FROM Opportunity
        WHERE IsDeleted = false
          AND StageName = 'Closed Won'
          AND CloseDate >= {sf_date(range_start)}
          AND CloseDate < {sf_date(range_end)}
    """)
    for opp in opps_closed:
        rep = normalize_name((opp.get("Owner") or {}).get("Name"))
        if rep not in metrics:
            continue
        dt = datetime.fromisoformat(opp["CloseDate"]).replace(tzinfo=ET)
        period = period_for_dt(dt, windows)
        if not period:
            continue
        metrics[rep]["closed_won"][period] += 1
        metrics[rep]["closed_won_mrr"][period] += amount(opp)

    history = sf_query(base, headers, f"""
        SELECT Id, OpportunityId, OldValue, NewValue, CreatedDate,
               Opportunity.Name, Opportunity.Owner.Name
        FROM OpportunityFieldHistory
        WHERE Field = 'StageName'
          AND CreatedDate >= {iso_utc(range_start)}
          AND CreatedDate < {iso_utc(range_end)}
    """)
    recent_moves = []
    for h in history:
        rep = normalize_name(((h.get("Opportunity") or {}).get("Owner") or {}).get("Name"))
        if rep not in metrics:
            continue
        dt = datetime.strptime(h["CreatedDate"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(ET)
        period = period_for_dt(dt, windows)
        if not period:
            continue
        delta = stage_delta(h.get("OldValue"), h.get("NewValue"))
        if delta <= 0:
            continue
        metrics[rep]["stage_advances"][period] += 1
        metrics[rep]["stage_steps"][period] += delta
        if period == "last":
            recent_moves.append({
                "rep": rep,
                "opp": (h.get("Opportunity") or {}).get("Name") or "Opportunity",
                "from": str(h.get("OldValue") or ""),
                "to": str(h.get("NewValue") or ""),
                "steps": delta,
                "date": dt.strftime("%a %-m/%-d %-I:%M %p"),
            })

    totals = empty_rep("Total")
    for repdata in metrics.values():
        for key, val in repdata.items():
            if key == "role":
                continue
            for period in ("last", "prior"):
                totals[key][period] += val[period]

    payload = {
        "generated_at_et": now_et.strftime("%b %-d, %Y %-I:%M %p ET"),
        "windows": {k: format_window(v[0], v[1]) for k, v in windows.items()},
        "metrics": metrics,
        "totals": totals,
        "recent_moves": sorted(recent_moves, key=lambda x: x["date"], reverse=True)[:18],
    }
    return payload


def format_window(start, end):
    return f"{start.strftime('%b %-d')} - {(end - timedelta(days=1)).strftime('%b %-d, %Y')}"


def fmt_int(v):
    return f"{int(v):,}"


def money(v):
    return f"${float(v):,.0f}"


def pct_delta(last, prior):
    if prior == 0:
        return "+100%" if last else "0%"
    return f"{((last - prior) / prior) * 100:+.0f}%"


def signed(last, prior, money_flag=False):
    diff = last - prior
    if money_flag:
        return ("+" if diff >= 0 else "") + money(diff)
    return ("+" if diff >= 0 else "") + fmt_int(diff)


def metric_card(label, key, totals, money_flag=False):
    last = totals[key]["last"]
    prior = totals[key]["prior"]
    main = money(last) if money_flag else fmt_int(last)
    prior_txt = money(prior) if money_flag else fmt_int(prior)
    cls = "up" if last >= prior else "down"
    return f'''<div class="metric-card">
      <div class="metric-label">{escape(label)}</div>
      <div class="metric-value">{main}</div>
      <div class="metric-compare"><span class="{cls}">{escape(signed(last, prior, money_flag))}</span> vs prior · {escape(pct_delta(last, prior))}</div>
      <div class="metric-prior">Prior week: {prior_txt}</div>
    </div>'''


def build_rep_rows(metrics):
    rows = []
    ordered = sorted(metrics.items(), key=lambda kv: (-(kv[1]["activities"]["last"] + kv[1]["opps_created"]["last"]*5 + kv[1]["stage_steps"]["last"]*2), kv[0]))
    for rep, m in ordered:
        if m["activities"]["last"] + m["activities"]["prior"] + m["opps_created"]["last"] + m["opps_created"]["prior"] + m["stage_steps"]["last"] + m["stage_steps"]["prior"] == 0:
            continue
        rows.append(f'''<tr>
          <td><strong>{escape(rep)}</strong><span>{escape(m['role'])}</span></td>
          <td>{fmt_int(m['activities']['last'])}<small>{signed(m['activities']['last'], m['activities']['prior'])}</small></td>
          <td>{fmt_int(m['calls']['last'])}<small>{signed(m['calls']['last'], m['calls']['prior'])}</small></td>
          <td>{fmt_int(m['emails']['last'])}<small>{signed(m['emails']['last'], m['emails']['prior'])}</small></td>
          <td>{fmt_int(m['meetings']['last'])}<small>{signed(m['meetings']['last'], m['meetings']['prior'])}</small></td>
          <td>{fmt_int(m['opps_created']['last'])}<small>{money(m['opps_created_mrr']['last'])}</small></td>
          <td>{fmt_int(m['stage_steps']['last'])}<small>{signed(m['stage_steps']['last'], m['stage_steps']['prior'])}</small></td>
          <td>{fmt_int(m['closed_won']['last'])}<small>{money(m['closed_won_mrr']['last'])}</small></td>
        </tr>''')
    return "\n".join(rows) or '<tr><td colspan="8" class="empty">No tracked activity in either week.</td></tr>'


def build_recent_rows(moves):
    rows=[]
    for mv in moves[:12]:
        rows.append(f"<tr><td>{escape(mv['rep'])}<span>{escape(mv['date'])}</span></td><td>{escape(mv['opp'])}</td><td>{escape(mv['from'])} → {escape(mv['to'])}</td><td>{fmt_int(mv['steps'])}</td></tr>")
    return "\n".join(rows) or '<tr><td colspan="4" class="empty">No forward stage movement last week.</td></tr>'


def build_html(payload):
    t = payload["totals"]
    cards = "\n".join([
        metric_card("Total Activities", "activities", t),
        metric_card("Calls", "calls", t),
        metric_card("Emails", "emails", t),
        metric_card("Meetings", "meetings", t),
        metric_card("New Opps", "opps_created", t),
        metric_card("New Opp MRR", "opps_created_mrr", t, True),
        metric_card("Stage Steps", "stage_steps", t),
        metric_card("Closed Won MRR", "closed_won_mrr", t, True),
    ])
    rep_rows = build_rep_rows(payload["metrics"])
    recent_rows = build_recent_rows(payload["recent_moves"])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Monday Team Activity Dashboard</title>
<style>
:root {{ --cyan:#34bde5; --cyan-soft:#7fd9ef; --teal:#4fd1c5; --lime:#c6f178; --gold:#eace9b; --danger:#ff6b6b; --bg:#0a141f; --bg-deep:#060e18; --surface:rgba(15,27,42,.78); --border:rgba(255,255,255,.12); --text:#f5f9ff; --muted:#8ea3b9; --mid:#b9c7d6; }}
*{{box-sizing:border-box}} body{{margin:0;font-family:Roboto,Segoe UI,system-ui,sans-serif;background:radial-gradient(900px 420px at 18% -8%,rgba(79,209,197,.30),transparent 64%),radial-gradient(760px 420px at 82% 0%,rgba(52,189,229,.24),transparent 62%),linear-gradient(180deg,#0a141f 0%,#08111b 46%,#060e18 100%);color:var(--text)}}
body:before{{content:'';position:fixed;inset:-14% -10% 55% -10%;background:radial-gradient(55% 45% at 20% 30%,rgba(79,209,197,.35),transparent 65%),radial-gradient(45% 35% at 78% 22%,rgba(52,189,229,.34),transparent 65%);filter:blur(46px);opacity:.75;pointer-events:none}} .container{{max-width:min(1500px,calc(100vw - 32px));margin:0 auto;padding:18px 16px 28px;position:relative;z-index:1}}
.header{{border-bottom:1px solid var(--border);padding:20px 0 22px;margin-bottom:22px;position:relative}} .header-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-right:154px}} .logo{{display:flex;align-items:center;gap:10px}} .logo-dot{{width:9px;height:9px;background:var(--cyan);border-radius:50%;box-shadow:0 0 0 3px rgba(52,189,229,.2),0 0 12px rgba(52,189,229,.85)}} .logo-text{{font-size:11px;font-weight:600;letter-spacing:.22em;text-transform:uppercase;color:var(--cyan-soft)}} .header-date{{font-size:11px;color:var(--muted);letter-spacing:.14em;text-transform:uppercase}} .revio-header-logo{{position:absolute;top:0;right:0;width:132px}} h1{{font-size:clamp(42px,5vw,72px);font-weight:300;color:#fff;letter-spacing:-.03em;line-height:.98;margin:0 0 10px}} h1 span{{color:var(--cyan-soft);font-family:Georgia,serif;font-style:italic;font-weight:500}} .header-sub{{font-size:14px;color:var(--mid)}}
.metric-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}} .metric-card{{background:rgba(255,255,255,.035);border:1px solid var(--border);border-radius:16px;padding:16px;box-shadow:0 22px 60px -48px #000;backdrop-filter:blur(12px)}} .metric-label{{font-size:9px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin-bottom:7px}} .metric-value{{font-size:30px;font-weight:850;line-height:1;color:#fff}} .metric-compare{{margin-top:8px;font-size:12px;color:var(--mid)}} .metric-compare .up{{color:var(--lime)}} .metric-compare .down{{color:var(--danger)}} .metric-prior{{margin-top:4px;font-size:11px;color:var(--muted)}}
.panel{{background:var(--surface);border:1px solid var(--border);border-radius:16px;margin-bottom:14px;overflow:hidden;box-shadow:0 22px 60px -48px #000;backdrop-filter:blur(12px)}} .panel-head{{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;padding:16px 18px;border-bottom:1px solid var(--border)}} h2{{margin:0;font-size:20px;font-weight:500}} .panel-note{{font-size:12px;color:var(--muted);max-width:620px;line-height:1.4}} table{{width:100%;border-collapse:collapse}} th{{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.16em;color:var(--muted);padding:10px 14px;text-align:left;background:rgba(6,14,24,.55)}} td{{font-size:13px;padding:10px 14px;border-top:1px solid rgba(255,255,255,.06);color:var(--mid);vertical-align:top}} td:first-child{{color:#fff}} td strong{{display:block;color:#fff}} td span, td small{{display:block;color:var(--muted);font-size:10px;margin-top:3px}} td small{{color:var(--cyan-soft)}} .empty{{text-align:center;color:var(--muted);padding:24px}} .footer{{text-align:center;padding:18px;font-size:10px;color:var(--muted);letter-spacing:.14em;border-top:1px solid var(--border);margin-top:8px}}
@media(max-width:900px){{.metric-grid{{grid-template-columns:1fr 1fr}}.panel{{overflow-x:auto}}table{{min-width:980px}}.header-top{{padding-right:0;display:block}}.revio-header-logo{{position:relative;width:108px;margin-top:10px}}}}
</style></head><body><div class="container"><header class="header"><div class="header-top"><div class="logo"><span class="logo-dot"></span><span class="logo-text">Rev.io Sales Activity</span></div><div class="header-date">Generated {escape(payload['generated_at_et'])}</div></div><img class="revio-header-logo" src="https://7091219.fs1.hubspotusercontent-na1.net/hubfs/7091219/email-assets/logo-revio-white.png" alt="Rev.io"><h1>Monday Team <span>Activity</span></h1><p class="header-sub">Last week ({escape(payload['windows']['last'])}) vs prior week ({escape(payload['windows']['prior'])}). Built for Monday morning sales-team review.</p></header>
<div class="metric-grid">{cards}</div>
<section class="panel"><div class="panel-head"><h2>Rep activity comparison</h2><div class="panel-note">Tasks/events are credited to activity owner. New opps, stage movement, and closed-won MRR are credited to opportunity owner.</div></div><table><thead><tr><th>Rep</th><th>Activities</th><th>Calls</th><th>Emails</th><th>Meetings</th><th>New Opps</th><th>Stage Steps</th><th>Closed Won</th></tr></thead><tbody>{rep_rows}</tbody></table></section>
<section class="panel"><div class="panel-head"><h2>Forward stage movement last week</h2><div class="panel-note">Most recent positive StageName moves, useful for deal inspection and manager coaching.</div></div><table><thead><tr><th>Rep</th><th>Opportunity</th><th>Move</th><th>Steps</th></tr></thead><tbody>{recent_rows}</tbody></table></section>
<div class="footer">SOURCE: SALESFORCE TASKS, EVENTS, OPPORTUNITIES, AND OPPORTUNITY FIELD HISTORY · AUTO-REFRESHES SUNDAY NIGHT ET</div></div></body></html>'''


def publish(paths):
    tmp_parent = Path(tempfile.mkdtemp(prefix="monday-activity-publish."))
    worktree = tmp_parent / "repo"
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = "ssh -i /home/openclaw/.openclaw/ssh/id_ed25519 -o StrictHostKeyChecking=no"
    subprocess.run(["git", "clone", "git@github.com:koontz-robin/robin-decks.git", str(worktree)], check=True, env=env)
    subprocess.run(["git", "config", "user.name", "Robin"], cwd=worktree, check=True, env=env)
    subprocess.run(["git", "config", "user.email", "robin.bot@rev.io"], cwd=worktree, check=True, env=env)
    for path in paths:
        shutil.copy2(path, worktree / Path(path).name)
    subprocess.run(["git", "add"] + [Path(p).name for p in paths], cwd=worktree, check=True, env=env)
    status = subprocess.run(["git", "status", "--short"], cwd=worktree, text=True, capture_output=True, check=True, env=env).stdout.strip()
    if status:
        subprocess.run(["git", "commit", "-m", "Refresh Monday team activity dashboard"], cwd=worktree, check=True, env=env)
        subprocess.run(["git", "push", "origin", "master"], cwd=worktree, check=True, env=env)
    shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    payload = build_payload()
    DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HTML_FILE.write_text(build_html(payload), encoding="utf-8")
    if os.environ.get("NO_PUBLISH") != "1":
        publish([HTML_FILE, DATA_FILE])
    print(f"Built {HTML_FILE}")
    print(f"URL: https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")


if __name__ == "__main__":
    main()
