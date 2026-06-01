#!/usr/bin/env python3
"""Build and publish the June AE/CSA opportunity creation dashboard."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
HTML_FILE = WORKSPACE / "june-ae-csa-opportunities.html"
DATA_FILE = WORKSPACE / "sf_june_ae_csa_opps.json"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

ET = ZoneInfo("America/New_York")
JUNE_START = "2026-06-01T04:00:00Z"
JULY_START = "2026-07-01T04:00:00Z"

KNOWN_AES = {
    "Andrew Whisenant",
    "Connor Flynn",
    "Davis Herndon",
    "Husam Zalmiyar",
    "Jake Borah",
    "Jake Mitchell",
    "Jamie Butler",
    "Jaylin Bender",
    "Patrick Davies",
}
KNOWN_CSAS = {"Ingrid Beard", "Justin Lee"}
ROLE_GROUPS = {
    "MSP Sales": "AE",
    "Integrator Sales": "AE",
    "CSA": "CSA",
}

WEEKS = [
    ("Week 1", "Jun 1-7", "2026-06-01", "2026-06-07"),
    ("Week 2", "Jun 8-14", "2026-06-08", "2026-06-14"),
    ("Week 3", "Jun 15-21", "2026-06-15", "2026-06-21"),
    ("Week 4", "Jun 22-28", "2026-06-22", "2026-06-28"),
    ("Week 5", "Jun 29-30", "2026-06-29", "2026-06-30"),
]


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
            raise RuntimeError(f"Salesforce query failed: {response.status_code} {response.text[:500]}")
        payload = response.json()
        records.extend(payload.get("records", []))
        if payload.get("done", True):
            return records
        url = base + payload["nextRecordsUrl"]
        params = {}


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
        name = user.get("Name") or ""
        role = (user.get("UserRole") or {}).get("Name") or ""
        if name and role in ROLE_GROUPS:
            members[name] = ROLE_GROUPS[role]
    for name in KNOWN_AES:
        members.setdefault(name, "AE")
    for name in KNOWN_CSAS:
        members.setdefault(name, "CSA")
    return members


def fetch_opportunities(base, headers):
    query = f"""
        SELECT Id, Name, Amount, StageName, Product_Type__c, CreatedDate,
               CloseDate, Account.Name, Owner.Name, Owner.UserRole.Name, CreatedBy.Name
        FROM Opportunity
        WHERE CreatedDate >= {JUNE_START}
          AND CreatedDate < {JULY_START}
          AND IsDeleted = false
        ORDER BY CreatedDate ASC
    """
    records = sf_query(base, headers, query)
    flattened = []
    for record in records:
        owner = record.get("Owner") or {}
        account = record.get("Account") or {}
        created_by = record.get("CreatedBy") or {}
        owner_role = (owner.get("UserRole") or {}).get("Name") or ""
        flattened.append(
            {
                "Id": record.get("Id"),
                "Name": record.get("Name") or "",
                "Amount": float(record.get("Amount") or 0),
                "StageName": record.get("StageName") or "",
                "Product_Type__c": record.get("Product_Type__c") or "Unspecified",
                "CreatedDate": record.get("CreatedDate") or "",
                "CloseDate": record.get("CloseDate") or "",
                "Account": account.get("Name") or "",
                "Owner": owner.get("Name") or "Unknown",
                "OwnerRole": owner_role,
                "CreatedBy": created_by.get("Name") or "",
            }
        )
    return flattened


def created_date_et(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(ET).date().isoformat()


def week_for_date(date_text):
    for week_id, label, start, end in WEEKS:
        if start <= date_text <= end:
            return week_id
    return None


def classify_rep(name, role, members):
    if name in members:
        return members[name]
    if role in ROLE_GROUPS:
        return ROLE_GROUPS[role]
    return None


def money(value):
    return f"${value:,.0f}"


def initials(name):
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "?"


def build_rows(by_rep, rep_groups, weekly_totals):
    rows = []
    ordered_reps = sorted(
        by_rep,
        key=lambda rep: (rep_groups.get(rep, "ZZZ"), -sum(v["amount"] for v in by_rep[rep].values()), rep),
    )
    for rep in ordered_reps:
        group = rep_groups.get(rep, "Other")
        total_count = sum(v["count"] for v in by_rep[rep].values())
        total_amount = sum(v["amount"] for v in by_rep[rep].values())
        cells = []
        for week_id, label, _, _ in WEEKS:
            metrics = by_rep[rep].get(week_id, {"count": 0, "amount": 0})
            pct = (metrics["amount"] / weekly_totals[week_id]["amount"] * 100) if weekly_totals[week_id]["amount"] else 0
            cells.append(
                f"""
                <td class="week-cell">
                  <div class="cell-count">{metrics['count']}</div>
                  <div class="cell-mrr">{money(metrics['amount'])}</div>
                  <div class="cell-bar"><span style="width:{min(pct, 100):.1f}%"></span></div>
                </td>"""
            )
        rows.append(
            f"""
            <tr>
              <td class="rep-cell">
                <div class="avatar">{escape(initials(rep))}</div>
                <div>
                  <div class="rep-name">{escape(rep)}</div>
                  <div class="rep-group {group.lower()}">{escape(group)}</div>
                </div>
              </td>
              {''.join(cells)}
              <td class="total-cell">
                <div class="total-count">{total_count}</div>
                <div class="total-mrr">{money(total_amount)}</div>
              </td>
            </tr>"""
        )
    return "\n".join(rows)


def build_week_cards(weekly_totals):
    cards = []
    max_amount = max((v["amount"] for v in weekly_totals.values()), default=0) or 1
    for week_id, label, _, _ in WEEKS:
        metrics = weekly_totals[week_id]
        pct = metrics["amount"] / max_amount * 100
        cards.append(
            f"""
            <section class="week-card">
              <div class="week-name">{escape(week_id)}</div>
              <div class="week-range">{escape(label)}</div>
              <div class="week-count">{metrics['count']}</div>
              <div class="week-mrr">{money(metrics['amount'])}</div>
              <div class="week-track"><span style="width:{pct:.1f}%"></span></div>
            </section>"""
        )
    return "\n".join(cards)


def build_rep_breakdown(opps_by_week_rep):
    sections = []
    for week_id, label, _, _ in WEEKS:
        rows = []
        reps = sorted(
            opps_by_week_rep[week_id],
            key=lambda rep: (-sum(o["Amount"] for o in opps_by_week_rep[week_id][rep]), rep),
        )
        for rep in reps:
            opps = opps_by_week_rep[week_id][rep]
            amount = sum(o["Amount"] for o in opps)
            rows.append(
                f"""
                <div class="detail-row">
                  <span>{escape(rep)}</span>
                  <strong>{len(opps)}</strong>
                  <strong>{money(amount)}</strong>
                </div>"""
            )
        if not rows:
            rows.append('<div class="empty-row">No AE/CSA opportunities created.</div>')
        sections.append(
            f"""
            <section class="detail-card">
              <h2>{escape(week_id)} <span>{escape(label)}</span></h2>
              <div class="detail-head"><span>Rep</span><span>Qty</span><span>MRR</span></div>
              {''.join(rows)}
            </section>"""
        )
    return "\n".join(sections)


def build_html(opps, members):
    generated_at = datetime.now(ET)
    enriched = []
    by_rep = defaultdict(lambda: defaultdict(lambda: {"count": 0, "amount": 0}))
    rep_groups = {}
    weekly_totals = {week_id: {"count": 0, "amount": 0} for week_id, _, _, _ in WEEKS}
    group_totals = {"AE": {"count": 0, "amount": 0}, "CSA": {"count": 0, "amount": 0}}
    opps_by_week_rep = defaultdict(lambda: defaultdict(list))

    for opp in opps:
        date_text = created_date_et(opp["CreatedDate"])
        week_id = week_for_date(date_text)
        group = classify_rep(opp["Owner"], opp["OwnerRole"], members)
        if not week_id or group not in {"AE", "CSA"}:
            continue
        opp = {**opp, "CreatedDateET": date_text, "Week": week_id, "Group": group}
        enriched.append(opp)
        rep = opp["Owner"]
        rep_groups[rep] = group
        by_rep[rep][week_id]["count"] += 1
        by_rep[rep][week_id]["amount"] += opp["Amount"]
        weekly_totals[week_id]["count"] += 1
        weekly_totals[week_id]["amount"] += opp["Amount"]
        group_totals[group]["count"] += 1
        group_totals[group]["amount"] += opp["Amount"]
        opps_by_week_rep[week_id][rep].append(opp)

    DATA_FILE.write_text(json.dumps(enriched, indent=2), encoding="utf-8")

    total_count = len(enriched)
    total_mrr = sum(opp["Amount"] for opp in enriched)
    table_headers = "".join(
        f'<th><div>{escape(week_id)}</div><span>{escape(label)}</span></th>' for week_id, label, _, _ in WEEKS
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>June AE/CSA Opportunity Creation</title>
<style>
:root {{
  --bg:#f6f8fb;
  --panel:#ffffff;
  --ink:#172033;
  --muted:#64748b;
  --line:#dbe3ee;
  --green:#20b26b;
  --blue:#2563eb;
  --teal:#0891b2;
  --gold:#b7791f;
  --shadow:0 18px 50px rgba(15,23,42,.08);
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  background:var(--bg);
  color:var(--ink);
  font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
.shell {{ max-width:1440px; margin:0 auto; padding:28px; }}
.topbar {{ display:flex; align-items:flex-end; justify-content:space-between; gap:24px; margin-bottom:22px; }}
.eyebrow {{ color:var(--green); font-size:12px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }}
h1 {{ margin:6px 0 0; font-size:34px; line-height:1.08; letter-spacing:0; }}
.subtitle {{ color:var(--muted); margin-top:8px; font-size:14px; }}
.stamp {{ text-align:right; color:var(--muted); font-size:12px; line-height:1.5; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:18px; }}
.kpi, .week-card, .detail-card, .table-wrap {{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:8px;
  box-shadow:var(--shadow);
}}
.kpi {{ padding:18px; }}
.kpi-label {{ color:var(--muted); font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }}
.kpi-val {{ margin-top:10px; font-size:32px; font-weight:850; }}
.kpi-sub {{ margin-top:4px; color:var(--muted); font-size:13px; }}
.weeks {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin-bottom:18px; }}
.week-card {{ padding:16px; min-height:134px; }}
.week-name {{ color:var(--blue); font-weight:850; font-size:13px; text-transform:uppercase; letter-spacing:.08em; }}
.week-range {{ color:var(--muted); font-size:12px; margin-top:3px; }}
.week-count {{ margin-top:14px; font-size:30px; font-weight:850; }}
.week-mrr {{ color:var(--green); font-size:14px; font-weight:800; }}
.week-track, .cell-bar {{ height:6px; background:#edf2f7; border-radius:999px; overflow:hidden; margin-top:12px; }}
.week-track span, .cell-bar span {{ display:block; height:100%; background:linear-gradient(90deg,var(--green),var(--teal)); border-radius:999px; }}
.table-wrap {{ overflow:auto; }}
table {{ width:100%; border-collapse:separate; border-spacing:0; min-width:1080px; }}
th, td {{ border-bottom:1px solid var(--line); padding:13px 14px; vertical-align:middle; }}
th {{ position:sticky; top:0; background:#fbfdff; color:var(--muted); font-size:12px; font-weight:850; text-align:right; text-transform:uppercase; letter-spacing:.06em; z-index:1; }}
th:first-child {{ text-align:left; left:0; z-index:2; }}
th span {{ display:block; font-weight:700; text-transform:none; letter-spacing:0; margin-top:2px; }}
td:first-child {{ position:sticky; left:0; background:var(--panel); z-index:1; }}
tr:last-child td {{ border-bottom:0; }}
.rep-cell {{ display:flex; align-items:center; gap:10px; min-width:230px; }}
.avatar {{ width:34px; height:34px; border-radius:8px; display:grid; place-items:center; background:#e7f7ef; color:#087344; font-size:12px; font-weight:850; }}
.rep-name {{ font-weight:800; }}
.rep-group {{ display:inline-flex; margin-top:4px; padding:2px 7px; border-radius:999px; font-size:10px; font-weight:850; letter-spacing:.06em; }}
.rep-group.ae {{ color:#1d4ed8; background:#dbeafe; }}
.rep-group.csa {{ color:#0f766e; background:#ccfbf1; }}
.week-cell, .total-cell {{ text-align:right; min-width:142px; }}
.cell-count, .total-count {{ font-size:18px; font-weight:850; }}
.cell-mrr, .total-mrr {{ color:var(--green); font-size:12px; font-weight:800; margin-top:2px; }}
.total-cell {{ background:#fbfdff; }}
.details {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin-top:18px; }}
.detail-card {{ padding:15px; }}
.detail-card h2 {{ margin:0 0 12px; font-size:15px; }}
.detail-card h2 span {{ display:block; color:var(--muted); font-size:12px; font-weight:700; margin-top:2px; }}
.detail-head, .detail-row {{ display:grid; grid-template-columns:minmax(0,1fr) 42px 82px; gap:8px; align-items:center; }}
.detail-head {{ color:var(--muted); font-size:10px; font-weight:850; text-transform:uppercase; letter-spacing:.08em; padding-bottom:7px; border-bottom:1px solid var(--line); }}
.detail-row {{ padding:8px 0; border-bottom:1px solid #edf2f7; font-size:12px; }}
.detail-row:last-child {{ border-bottom:0; }}
.detail-row span {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; }}
.detail-row strong {{ text-align:right; font-size:12px; }}
.empty-row {{ color:var(--muted); font-size:12px; padding:16px 0; }}
@media (max-width:1100px) {{
  .shell {{ padding:18px; }}
  .topbar {{ display:block; }}
  .stamp {{ text-align:left; margin-top:12px; }}
  .kpis {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .weeks, .details {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
}}
@media (max-width:640px) {{
  h1 {{ font-size:26px; }}
  .kpis, .weeks, .details {{ grid-template-columns:1fr; }}
}}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div>
      <div class="eyebrow">June 2026 Pipeline Creation</div>
      <h1>AE / CSA Opportunities Created</h1>
      <div class="subtitle">Quantity and MRR by owner, split across all five June calendar weeks.</div>
    </div>
    <div class="stamp">
      Refreshed {generated_at.strftime('%b %-d, %Y %-I:%M %p ET')}<br>
      Salesforce CreatedDate, Owner, Amount
    </div>
  </header>

  <section class="kpis">
    <div class="kpi"><div class="kpi-label">Total Opportunities</div><div class="kpi-val">{total_count}</div><div class="kpi-sub">AE + CSA owned opps created in June</div></div>
    <div class="kpi"><div class="kpi-label">Total MRR</div><div class="kpi-val">{money(total_mrr)}</div><div class="kpi-sub">Sum of Salesforce Amount</div></div>
    <div class="kpi"><div class="kpi-label">AE Created</div><div class="kpi-val">{group_totals['AE']['count']}</div><div class="kpi-sub">{money(group_totals['AE']['amount'])} MRR</div></div>
    <div class="kpi"><div class="kpi-label">CSA Created</div><div class="kpi-val">{group_totals['CSA']['count']}</div><div class="kpi-sub">{money(group_totals['CSA']['amount'])} MRR</div></div>
  </section>

  <section class="weeks">
    {build_week_cards(weekly_totals)}
  </section>

  <section class="table-wrap">
    <table>
      <thead>
        <tr><th>Owner</th>{table_headers}<th>Total</th></tr>
      </thead>
      <tbody>
        {build_rows(by_rep, rep_groups, weekly_totals)}
      </tbody>
    </table>
  </section>

  <section class="details">
    {build_rep_breakdown(opps_by_week_rep)}
  </section>
</main>
</body>
</html>
"""
    HTML_FILE.write_text(html, encoding="utf-8")
    return total_count, total_mrr


def publish(files):
    subprocess.run(["git", "fetch", "robin-decks", "master"], cwd=WORKSPACE, check=True)
    tmp_parent = Path(tempfile.mkdtemp(prefix="june-ae-csa-dashboard-"))
    worktree = tmp_parent / "worktree"
    try:
        subprocess.run(["git", "worktree", "add", str(worktree), "robin-decks/master"], cwd=WORKSPACE, check=True)
        for path in files:
            shutil.copy2(path, worktree / path.name)
        subprocess.run(["git", "add", *[path.name for path in files]], cwd=worktree, check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree)
        if diff.returncode == 0:
            print("No dashboard changes to publish.")
            return
        stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
        subprocess.run(["git", "commit", "-m", f"add June AE CSA opportunity dashboard ({stamp})"], cwd=worktree, check=True)
        subprocess.run(["git", "push", "robin-decks", "HEAD:master"], cwd=worktree, check=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=WORKSPACE, check=False)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    print("Authenticating to Salesforce...")
    base, headers = sf_auth()
    print("Fetching AE/CSA members...")
    members = get_team_members(base, headers)
    print("Fetching June-created opportunities...")
    opps = fetch_opportunities(base, headers)
    total_count, total_mrr = build_html(opps, members)
    print(f"Built {HTML_FILE.name}: {total_count} opps, {money(total_mrr)} MRR")
    if os.environ.get("NO_PUBLISH") == "1":
        print("NO_PUBLISH=1 set; skipping GitHub Pages publish.")
        return
    publish([HTML_FILE, DATA_FILE, Path(__file__)])
    print(f"Published https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
