#!/usr/bin/env python3
"""Build a Salesforce-backed rep activity report.

The report covers new opportunity creation and pipeline stage movement for the
current week, month, and quarter, grouped by opportunity owner.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path(os.environ.get("ROBIN_WORKSPACE", "/home/openclaw/.openclaw/workspace"))
HTML_FILE = WORKSPACE / "rep-activity-report.html"
DATA_FILE = WORKSPACE / "sf_rep_activity_report.json"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

ET = ZoneInfo("America/New_York")

NAME_ALIASES = {
    "Andrew Whisenant": "Andy Whisenant",
}
EXCLUDED_REPS = {
    "Davis" + " Herndon",
    "Jake Mitchell",
    "Ardit Berdyna",
    "Blaine Villafuerte",
    "Cam Sharpe",
    "Matt Salin",
    "Olivia Sandefur",
    "Reid Doster",
    "Usman Zahoor",
}
ROLE_GROUPS = {
    "SDRs": "SDR",
    "MSP Sales": "AE",
    "Integrator Sales": "AE",
    "CSA": "CSA",
}
KNOWN_AES = {
    "Andy Whisenant",
    "Connor Flynn",
    "Husam Zalmiyar",
    "Jake Borah",
    "Jamie Butler",
    "Jaylin Bender",
    "Patrick Davies",
}
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
STAGE_LABELS = {
    "1- Discovery Scheduled": "Scheduled",
    "2 - Discovery Completed": "Discovery",
    "3 - Initial Product Demo": "Demo",
    "4 - Proposal Sent": "Proposal",
    "5 - Product / Contract Validated": "Validated",
    "6 - Verbal Commit": "Verbal",
    "Closed Won": "Won",
    "Closed Lost": "Lost",
}


def normalize_name(name):
    cleaned = (name or "").strip()
    return NAME_ALIASES.get(cleaned, cleaned)


def sf_auth():
    response = requests.post(
        f"{SF_INSTANCE}/services/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": SF_CLIENT_ID,
            "client_secret": SF_CLIENT_SECRET,
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()
    return token["instance_url"], {"Authorization": f"Bearer {token['access_token']}"}


def sf_query(base, headers, query):
    url = f"{base}/services/data/v59.0/query"
    params = {"q": query.strip()}
    records = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if not response.ok:
            raise RuntimeError(f"Salesforce query failed: {response.status_code} {response.text[:800]}")
        payload = response.json()
        records.extend(payload.get("records", []))
        if payload.get("done", True):
            return records
        url = base + payload["nextRecordsUrl"]
        params = {}


def iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def period_windows(now_et):
    today = now_et.date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    quarter_month = ((today.month - 1) // 3) * 3 + 1
    quarter_start = today.replace(month=quarter_month, day=1)
    if quarter_month == 10:
        quarter_end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        quarter_end = today.replace(month=quarter_month + 3, day=1)
    windows = {
        "week": (
            datetime.combine(week_start, time.min, ET),
            datetime.combine(week_start + timedelta(days=7), time.min, ET),
        ),
        "month": (
            datetime.combine(month_start, time.min, ET),
            datetime.combine((month_start.replace(day=28) + timedelta(days=4)).replace(day=1), time.min, ET),
        ),
        "quarter": (
            datetime.combine(quarter_start, time.min, ET),
            datetime.combine(quarter_end, time.min, ET),
        ),
    }
    return windows


def period_for_date(dt_et, windows):
    periods = []
    for name, (start, end) in windows.items():
        if start <= dt_et < end:
            periods.append(name)
    return periods


def get_team_members(base, headers):
    role_list = ", ".join(f"'{role}'" for role in ROLE_GROUPS)
    query = f"""
        SELECT Name, UserRole.Name
        FROM User
        WHERE IsActive = true
          AND UserRole.Name IN ({role_list})
        ORDER BY Name
    """
    members = {}
    for user in sf_query(base, headers, query):
        role = (user.get("UserRole") or {}).get("Name") or ""
        name = normalize_name(user.get("Name"))
        if name and role in ROLE_GROUPS and name not in EXCLUDED_REPS:
            members[name] = ROLE_GROUPS[role]
    for name in KNOWN_AES:
        if name not in EXCLUDED_REPS:
            members.setdefault(name, "AE")
    for name in KNOWN_CSAS:
        if name not in EXCLUDED_REPS:
            members.setdefault(name, "CSA")
    return members


def is_included_rep(name, reps):
    return name in reps and reps.get(name) != "Other" and name not in EXCLUDED_REPS


def fetch_created_opps(base, headers, quarter_start_utc, quarter_end_utc):
    query = f"""
        SELECT Id, Name, Amount, StageName, CreatedDate, Product_Type__c,
               Account.Name, Owner.Name, Owner.UserRole.Name
        FROM Opportunity
        WHERE CreatedDate >= {quarter_start_utc}
          AND CreatedDate < {quarter_end_utc}
          AND IsDeleted = false
        ORDER BY CreatedDate ASC
    """
    return sf_query(base, headers, query)


def fetch_stage_history(base, headers, quarter_start_utc, quarter_end_utc):
    query = f"""
        SELECT Id, OpportunityId, OldValue, NewValue, CreatedDate,
               CreatedBy.Name, Opportunity.Name, Opportunity.Owner.Name,
               Opportunity.Owner.UserRole.Name
        FROM OpportunityFieldHistory
        WHERE Field = 'StageName'
          AND CreatedDate >= {quarter_start_utc}
          AND CreatedDate < {quarter_end_utc}
        ORDER BY CreatedDate ASC
    """
    return sf_query(base, headers, query)


def stage_step_delta(old_stage, new_stage):
    old_index = STAGE_ORDER.get(str(old_stage or ""))
    new_index = STAGE_ORDER.get(str(new_stage or ""))
    if old_index is None or new_index is None:
        return 1
    return abs(new_index - old_index) or 1


def initials(name):
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "?"


def money(value):
    return f"${value:,.0f}"


def fmt_int(value):
    return f"{value:,}"


def format_window(start, end):
    end_inclusive = end - timedelta(days=1)
    return f"{start.strftime('%b %-d')} - {end_inclusive.strftime('%b %-d, %Y')}"


def cell(value, sub=None):
    sub_html = f'<div class="cell-sub">{escape(sub)}</div>' if sub else ""
    return f'<td><div class="cell-main">{escape(str(value))}</div>{sub_html}</td>'


def build_created_rows(reps, created_metrics):
    rows = []
    ordered_reps = sorted(
        reps,
        key=lambda rep: (
            -created_metrics[rep]["quarter"]["count"],
            -created_metrics[rep]["month"]["count"],
            reps.get(rep, "ZZZ"),
            rep,
        ),
    )
    for rep in ordered_reps:
        if created_metrics[rep]["quarter"]["count"] == 0:
            continue
        rows.append(
            f"""
            <tr>
              <th scope="row">
                <span class="avatar">{escape(initials(rep))}</span>
                <span><strong>{escape(rep)}</strong><small>{escape(reps.get(rep, "Other"))}</small></span>
              </th>
              {cell(fmt_int(created_metrics[rep]["week"]["count"]), money(created_metrics[rep]["week"]["amount"]))}
              {cell(fmt_int(created_metrics[rep]["month"]["count"]), money(created_metrics[rep]["month"]["amount"]))}
              {cell(fmt_int(created_metrics[rep]["quarter"]["count"]), money(created_metrics[rep]["quarter"]["amount"]))}
            </tr>"""
        )
    return "\n".join(rows) or '<tr><td colspan="4" class="empty">No opportunities created in the current quarter.</td></tr>'


def build_movement_rows(reps, movement_metrics):
    rows = []
    ordered_reps = sorted(
        reps,
        key=lambda rep: (
            -movement_metrics[rep]["quarter"]["stage_steps"],
            -movement_metrics[rep]["quarter"]["unique_count"],
            reps.get(rep, "ZZZ"),
            rep,
        ),
    )
    for rep in ordered_reps:
        if movement_metrics[rep]["quarter"]["change_count"] == 0:
            continue
        rows.append(
            f"""
            <tr>
              <th scope="row">
                <span class="avatar">{escape(initials(rep))}</span>
                <span><strong>{escape(rep)}</strong><small>{escape(reps.get(rep, "Other"))}</small></span>
              </th>
              {cell(fmt_int(movement_metrics[rep]["week"]["unique_count"]), f'{fmt_int(movement_metrics[rep]["week"]["stage_steps"])} stage steps')}
              {cell(fmt_int(movement_metrics[rep]["month"]["unique_count"]), f'{fmt_int(movement_metrics[rep]["month"]["stage_steps"])} stage steps')}
              {cell(fmt_int(movement_metrics[rep]["quarter"]["unique_count"]), f'{fmt_int(movement_metrics[rep]["quarter"]["stage_steps"])} stage steps')}
            </tr>"""
        )
    return "\n".join(rows) or '<tr><td colspan="4" class="empty">No stage movement recorded in the current quarter.</td></tr>'


def build_recent_movement_rows(events):
    rows = []
    recent = sorted(events, key=lambda event: event["changed_at"], reverse=True)[:18]
    for event in recent:
        rows.append(
            f"""
            <tr>
              <td><strong>{escape(event["rep"])}</strong><small>{escape(event["changed_at_et"])}</small></td>
              <td>{escape(event["opp_name"])}</td>
              <td>{escape(STAGE_LABELS.get(event["old_stage"], event["old_stage"]))} -> {escape(STAGE_LABELS.get(event["new_stage"], event["new_stage"]))}</td>
              <td>{fmt_int(event["stage_steps"])}</td>
            </tr>"""
        )
    return "\n".join(rows) or '<tr><td colspan="4" class="empty">No recent movement.</td></tr>'


def build_html(payload):
    windows = payload["windows"]
    generated = payload["generated_at_et"]
    totals = payload["totals"]
    created_rows = build_created_rows(payload["reps"], payload["created_metrics"])
    movement_rows = build_movement_rows(payload["reps"], payload["movement_metrics"])
    recent_rows = build_recent_movement_rows(payload["movement_events"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rep Activity Report</title>
  <style>
    :root {{
      --ink:#13231b;
      --muted:#617064;
      --line:#dbe5dc;
      --paper:#fbfdf9;
      --panel:#ffffff;
      --green:#24a148;
      --blue:#2f6fed;
      --gold:#b7791f;
      --soft-green:#e8f6ed;
      --soft-blue:#eaf1ff;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0;
      font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color:var(--ink);
      background:var(--paper);
    }}
    header {{
      padding:28px 32px 18px;
      border-bottom:1px solid var(--line);
      background:#fff;
    }}
    .eyebrow {{
      color:var(--green);
      font-size:12px;
      font-weight:850;
      letter-spacing:.08em;
      text-transform:uppercase;
    }}
    h1 {{
      margin:8px 0 8px;
      font-size:32px;
      line-height:1.08;
      letter-spacing:0;
    }}
    .subhead {{
      margin:0;
      color:var(--muted);
      font-size:14px;
      line-height:1.45;
      max-width:960px;
    }}
    main {{ padding:24px 32px 36px; }}
    .kpis {{
      display:grid;
      grid-template-columns:repeat(3, minmax(160px, 1fr));
      gap:12px;
      margin-bottom:22px;
    }}
    .kpi {{
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:8px;
      padding:14px 16px;
    }}
    .kpi-label {{
      color:var(--muted);
      font-size:11px;
      font-weight:800;
      text-transform:uppercase;
      letter-spacing:.06em;
    }}
    .kpi-value {{
      margin-top:7px;
      font-size:28px;
      line-height:1;
      font-weight:850;
    }}
    .kpi-sub {{
      margin-top:5px;
      color:var(--muted);
      font-size:12px;
    }}
    section {{
      margin-top:22px;
      background:var(--panel);
      border:1px solid var(--line);
      border-radius:8px;
      overflow:hidden;
    }}
    .section-head {{
      display:flex;
      justify-content:space-between;
      gap:16px;
      align-items:flex-end;
      padding:18px 18px 14px;
      border-bottom:1px solid var(--line);
    }}
    h2 {{ margin:0; font-size:19px; letter-spacing:0; }}
    .section-note {{ color:var(--muted); font-size:12px; max-width:560px; line-height:1.4; }}
    table {{
      width:100%;
      border-collapse:collapse;
      table-layout:fixed;
    }}
    th, td {{
      padding:12px 14px;
      text-align:left;
      border-bottom:1px solid #edf2ee;
      vertical-align:middle;
    }}
    thead th {{
      color:var(--muted);
      font-size:11px;
      font-weight:850;
      text-transform:uppercase;
      letter-spacing:.06em;
      background:#f7faf7;
    }}
    tbody tr:last-child th, tbody tr:last-child td {{ border-bottom:none; }}
    tbody th {{
      display:flex;
      gap:10px;
      align-items:center;
      font-size:14px;
    }}
    tbody th small, td small {{
      display:block;
      color:var(--muted);
      font-size:11px;
      font-weight:700;
      margin-top:2px;
    }}
    .avatar {{
      width:32px;
      height:32px;
      border-radius:8px;
      display:inline-grid;
      place-items:center;
      background:var(--soft-green);
      color:#166534;
      font-size:11px;
      font-weight:900;
      flex:0 0 auto;
    }}
    .cell-main {{ font-size:18px; font-weight:850; }}
    .cell-sub {{ margin-top:3px; color:var(--muted); font-size:11px; font-weight:750; }}
    .movement tbody th .avatar {{ background:var(--soft-blue); color:#1d4ed8; }}
    .recent td {{ font-size:13px; }}
    .recent td:nth-child(4) {{ font-weight:850; }}
    .empty {{ color:var(--muted); text-align:center; padding:28px; }}
    footer {{
      color:var(--muted);
      font-size:11px;
      line-height:1.5;
      margin-top:16px;
    }}
    @media (max-width: 760px) {{
      header, main {{ padding-left:16px; padding-right:16px; }}
      .kpis {{ grid-template-columns:1fr 1fr; }}
      .section-head {{ display:block; }}
      .section-note {{ margin-top:8px; }}
      table {{ min-width:680px; }}
      section {{ overflow-x:auto; }}
      h1 {{ font-size:26px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">Live Salesforce Data</div>
    <h1>Rep Activity Report</h1>
    <p class="subhead">
      New opportunity creation and pipeline stage movement by opportunity owner.
      Generated {escape(generated)}. Week: {escape(windows["week"])}. Month: {escape(windows["month"])}. Quarter: {escape(windows["quarter"])}.
    </p>
  </header>
  <main>
    <div class="kpis">
      <div class="kpi"><div class="kpi-label">Week New Opps</div><div class="kpi-value">{fmt_int(totals["created"]["week"]["count"])}</div><div class="kpi-sub">{money(totals["created"]["week"]["amount"])} MRR</div></div>
      <div class="kpi"><div class="kpi-label">Month New Opps</div><div class="kpi-value">{fmt_int(totals["created"]["month"]["count"])}</div><div class="kpi-sub">{money(totals["created"]["month"]["amount"])} MRR</div></div>
      <div class="kpi"><div class="kpi-label">Quarter New Opps</div><div class="kpi-value">{fmt_int(totals["created"]["quarter"]["count"])}</div><div class="kpi-sub">{money(totals["created"]["quarter"]["amount"])} MRR</div></div>
      <div class="kpi"><div class="kpi-label">Week Stage Steps</div><div class="kpi-value">{fmt_int(totals["movement"]["week"]["stage_steps"])}</div><div class="kpi-sub">{fmt_int(totals["movement"]["week"]["unique_count"])} opps moved</div></div>
      <div class="kpi"><div class="kpi-label">Month Stage Steps</div><div class="kpi-value">{fmt_int(totals["movement"]["month"]["stage_steps"])}</div><div class="kpi-sub">{fmt_int(totals["movement"]["month"]["unique_count"])} opps moved</div></div>
      <div class="kpi"><div class="kpi-label">Quarter Stage Steps</div><div class="kpi-value">{fmt_int(totals["movement"]["quarter"]["stage_steps"])}</div><div class="kpi-sub">{fmt_int(totals["movement"]["quarter"]["unique_count"])} opps moved</div></div>
    </div>

    <section>
      <div class="section-head">
        <h2>New Opportunities by Rep</h2>
        <div class="section-note">Counts are opportunities created during each period. Subtext shows total MRR from Amount.</div>
      </div>
      <table>
        <thead><tr><th>Rep</th><th>Current Week</th><th>Current Month</th><th>Current Quarter</th></tr></thead>
        <tbody>{created_rows}</tbody>
      </table>
    </section>

    <section class="movement">
      <div class="section-head">
        <h2>Pipeline Stage Movement by Rep</h2>
        <div class="section-note">Main number is unique opportunities moved. Subtext is total ordered stage-step movement from OpportunityFieldHistory, credited to current opportunity owner.</div>
      </div>
      <table>
        <thead><tr><th>Rep</th><th>Current Week</th><th>Current Month</th><th>Current Quarter</th></tr></thead>
        <tbody>{movement_rows}</tbody>
      </table>
    </section>

    <section class="recent">
      <div class="section-head">
        <h2>Recent Stage Changes</h2>
        <div class="section-note">Latest StageName changes in the current quarter.</div>
      </div>
      <table>
        <thead><tr><th>Rep</th><th>Opportunity</th><th>Move</th><th>Steps</th></tr></thead>
        <tbody>{recent_rows}</tbody>
      </table>
    </section>
    <footer>
      Source: Salesforce Opportunity CreatedDate, Amount, Owner, and OpportunityFieldHistory StageName changes. Stage-step movement uses the Rev.io ordered sales stages; unknown stage transitions count as one step.
    </footer>
  </main>
</body>
</html>
"""


def main():
    now_et = datetime.now(ET)
    windows = period_windows(now_et)
    base, headers = sf_auth()
    reps = get_team_members(base, headers)

    quarter_start, quarter_end = windows["quarter"]
    created = fetch_created_opps(base, headers, iso_utc(quarter_start), iso_utc(quarter_end))
    history = fetch_stage_history(base, headers, iso_utc(quarter_start), iso_utc(quarter_end))

    created_metrics = defaultdict(lambda: defaultdict(lambda: {"count": 0, "amount": 0.0}))
    movement_sets = defaultdict(lambda: defaultdict(set))
    movement_metrics = defaultdict(lambda: defaultdict(lambda: {"unique_count": 0, "change_count": 0, "stage_steps": 0}))
    movement_events = []

    for rep in reps:
        for period in ("week", "month", "quarter"):
            created_metrics[rep][period]
            movement_metrics[rep][period]

    for opp in created:
        owner = normalize_name(((opp.get("Owner") or {}).get("Name") or "Unknown"))
        if not is_included_rep(owner, reps):
            continue
        created_at = datetime.strptime(opp["CreatedDate"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(ET)
        amount = float(opp.get("Amount") or 0)
        for period in period_for_date(created_at, windows):
            created_metrics[owner][period]["count"] += 1
            created_metrics[owner][period]["amount"] += amount

    for change in history:
        opp = change.get("Opportunity") or {}
        owner = normalize_name(((opp.get("Owner") or {}).get("Name") or "Unknown"))
        if not is_included_rep(owner, reps):
            continue
        changed_at = datetime.strptime(change["CreatedDate"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(ET)
        old_stage = str(change.get("OldValue") or "")
        new_stage = str(change.get("NewValue") or "")
        steps = stage_step_delta(old_stage, new_stage)
        for period in period_for_date(changed_at, windows):
            movement_sets[owner][period].add(change.get("OpportunityId"))
            movement_metrics[owner][period]["change_count"] += 1
            movement_metrics[owner][period]["stage_steps"] += steps
        movement_events.append(
            {
                "rep": owner,
                "opp_id": change.get("OpportunityId"),
                "opp_name": opp.get("Name") or "Unnamed Opportunity",
                "old_stage": old_stage,
                "new_stage": new_stage,
                "stage_steps": steps,
                "changed_at": changed_at.isoformat(),
                "changed_at_et": changed_at.strftime("%b %-d, %-I:%M %p ET"),
            }
        )

    for rep, periods in movement_sets.items():
        for period, opp_ids in periods.items():
            movement_metrics[rep][period]["unique_count"] = len(opp_ids)

    totals = {
        "created": defaultdict(lambda: {"count": 0, "amount": 0.0}),
        "movement": defaultdict(lambda: {"unique_count": 0, "change_count": 0, "stage_steps": 0}),
    }
    for period in ("week", "month", "quarter"):
        for rep in reps:
            totals["created"][period]["count"] += created_metrics[rep][period]["count"]
            totals["created"][period]["amount"] += created_metrics[rep][period]["amount"]
            totals["movement"][period]["change_count"] += movement_metrics[rep][period]["change_count"]
            totals["movement"][period]["stage_steps"] += movement_metrics[rep][period]["stage_steps"]
        quarter_period_sets = [movement_sets[rep][period] for rep in movement_sets]
        totals["movement"][period]["unique_count"] = len(set().union(*quarter_period_sets)) if quarter_period_sets else 0

    payload = {
        "generated_at_et": now_et.strftime("%B %-d, %Y %-I:%M %p ET"),
        "windows": {name: format_window(start, end) for name, (start, end) in windows.items()},
        "reps": dict(sorted(reps.items())),
        "created_metrics": {rep: dict(periods) for rep, periods in created_metrics.items()},
        "movement_metrics": {rep: dict(periods) for rep, periods in movement_metrics.items()},
        "movement_events": movement_events,
        "totals": {
            "created": dict(totals["created"]),
            "movement": dict(totals["movement"]),
        },
    }

    DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HTML_FILE.write_text(build_html(payload), encoding="utf-8")
    print(f"Fetched {len(created)} created opportunities and {len(history)} stage changes.")
    print(f"Wrote {HTML_FILE}")
    print(f"Wrote {DATA_FILE}")


if __name__ == "__main__":
    main()
