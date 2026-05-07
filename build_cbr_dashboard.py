#!/usr/bin/env python3
"""
CBR Dashboard — Client Business Review tracker
Groups all client accounts by Account Owner → Account Type
Shows last completed CBR event date per account.
"""

import requests, json, re
from datetime import datetime, timedelta
from collections import defaultdict

SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
SF_INSTANCE = "https://rev-io.my.salesforce.com"
REPO_PATH = "/tmp/robin-decks"
OUTPUT_FILE = f"{REPO_PATH}/cbr-dashboard.html"

CLIENT_TYPES = [
    "Rev.io PSA Client",
    "Rev.io Billing Client",
    "TigerPaw Client",
    "Rev.io Odin Client",
    "Client",
    "Channel Client",
]

today = datetime.now().date()
today_str = datetime.now().strftime("%B %d, %Y")


def sf_auth():
    r = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={
        "grant_type": "client_credentials",
        "client_id": SF_CLIENT_ID,
        "client_secret": SF_CLIENT_SECRET,
    })
    d = r.json()
    return d["access_token"], d["instance_url"]


def sf_query_all(hdrs, iurl, soql):
    """Paginate through all SF query results."""
    results = []
    url = f"{iurl}/services/data/v57.0/query"
    params = {"q": soql}
    while True:
        r = requests.get(url, headers=hdrs, params=params)
        if not r.ok:
            print(f"  SF query error: {r.text[:200]}")
            break
        data = r.json()
        results.extend(data.get("records", []))
        if data.get("done", True):
            break
        url = iurl + data["nextRecordsUrl"]
        params = {}
    return results


def days_since(date_str):
    if not date_str:
        return None
    try:
        return (today - datetime.fromisoformat(date_str[:10]).date()).days
    except:
        return None


def cbr_badge(days):
    """Color badge based on days since last CBR."""
    if days is None:
        return "#f87171", "Never"
    if days <= 90:
        return "#34d399", f"{days}d ago"
    if days <= 180:
        return "#fbbf24", f"{days}d ago"
    return "#f87171", f"{days}d ago"


def type_sort_key(t):
    order = {
        "Rev.io PSA Client": 0,
        "Rev.io Billing Client": 1,
        "Rev.io Odin Client": 2,
        "TigerPaw Client": 3,
        "Client": 4,
        "Channel Client": 5,
    }
    return order.get(t, 99)


def type_color(t):
    colors = {
        "Rev.io PSA Client": "#38bdf8",
        "Rev.io Billing Client": "#a78bfa",
        "Rev.io Odin Client": "#34d399",
        "TigerPaw Client": "#fbbf24",
        "Client": "#94a3b8",
        "Channel Client": "#f97316",
    }
    return colors.get(t, "#64748b")


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("Authenticating with Salesforce...")
    at, iurl = sf_auth()
    hdrs = {"Authorization": f"Bearer {at}"}

    # 1. Pull all client accounts
    print("Pulling client accounts...")
    types_in = "(" + ",".join(f"'{t}'" for t in CLIENT_TYPES) + ")"
    accounts_raw = sf_query_all(hdrs, iurl,
        f"SELECT Id, Name, Type, Owner.Name, OwnerId FROM Account "
        f"WHERE Type IN {types_in} ORDER BY Name")
    print(f"  {len(accounts_raw)} accounts loaded")

    # Build account map: Id -> dict
    acct_map = {}
    for a in accounts_raw:
        owner_name = (a.get("Owner") or {}).get("Name", "Unassigned")
        acct_map[a["Id"]] = {
            "id": a["Id"],
            "name": a["Name"],
            "type": a.get("Type", ""),
            "owner": owner_name,
            "last_cbr": None,
            "last_cbr_subject": "",
        }

    # 2. Pull all CBR Events (linked to accounts via WhatId)
    print("Pulling CBR Events...")
    events = sf_query_all(hdrs, iurl,
        "SELECT Id, Subject, ActivityDate, WhatId, OwnerId FROM Event "
        "WHERE Subject LIKE '%Business Review%' AND WhatId != null "
        "ORDER BY ActivityDate DESC")
    print(f"  {len(events)} CBR events with account link")

    for ev in events:
        acct_id = ev.get("WhatId")
        if acct_id in acct_map:
            date = ev.get("ActivityDate", "")
            if not acct_map[acct_id]["last_cbr"] or date > acct_map[acct_id]["last_cbr"]:
                acct_map[acct_id]["last_cbr"] = date
                acct_map[acct_id]["last_cbr_subject"] = ev.get("Subject", "")

    # 3. Pull CBR Tasks with WhoId → Contact → Account
    # Strategy: get unique WhoIds from tasks, batch lookup contacts
    print("Pulling completed CBR Tasks...")
    tasks = sf_query_all(hdrs, iurl,
        "SELECT Id, Subject, ActivityDate, WhoId FROM Task "
        "WHERE Subject LIKE '%Business Review%' AND Status = 'Completed' "
        "AND WhoId != null ORDER BY ActivityDate DESC")
    print(f"  {len(tasks)} completed CBR tasks with contact")

    # Get unique WhoIds
    who_ids = list({t["WhoId"] for t in tasks if t.get("WhoId")})
    print(f"  {len(who_ids)} unique contacts to resolve...")

    # Batch contacts in chunks of 200
    who_to_acct = {}
    for i in range(0, len(who_ids), 200):
        chunk = who_ids[i:i+200]
        ids_in = "(" + ",".join(f"'{w}'" for w in chunk) + ")"
        contacts = sf_query_all(hdrs, iurl,
            f"SELECT Id, AccountId FROM Contact WHERE Id IN {ids_in} AND AccountId != null")
        for c in contacts:
            who_to_acct[c["Id"]] = c["AccountId"]

    print(f"  Resolved {len(who_to_acct)} contacts to accounts")

    for task in tasks:
        who_id = task.get("WhoId")
        acct_id = who_to_acct.get(who_id)
        if acct_id and acct_id in acct_map:
            date = task.get("ActivityDate", "")
            if not acct_map[acct_id]["last_cbr"] or date > acct_map[acct_id]["last_cbr"]:
                acct_map[acct_id]["last_cbr"] = date
                acct_map[acct_id]["last_cbr_subject"] = task.get("Subject", "")

    # 4. Group by owner → type
    owner_groups = defaultdict(lambda: defaultdict(list))
    for acct in acct_map.values():
        owner_groups[acct["owner"]][acct["type"]].append(acct)

    # Sort owners by total account count desc
    owners_sorted = sorted(owner_groups.keys(),
        key=lambda o: sum(len(v) for v in owner_groups[o].values()), reverse=True)

    # 5. Summary stats
    total = len(acct_map)
    never = sum(1 for a in acct_map.values() if not a["last_cbr"])
    overdue = sum(1 for a in acct_map.values() if a["last_cbr"] and days_since(a["last_cbr"]) > 180)
    ok = total - never - overdue
    avg_days = None
    days_list = [days_since(a["last_cbr"]) for a in acct_map.values() if a["last_cbr"]]
    if days_list:
        avg_days = round(sum(days_list) / len(days_list))

    # ── Build HTML ─────────────────────────────────────────────────────────
    print("Building HTML...")

    # Type legend
    type_pills = "".join(
        f'<span style="background:#0f172a;border:1px solid {type_color(t)};color:{type_color(t)};'
        f'font-size:10px;font-weight:700;padding:3px 8px;border-radius:10px;margin-right:6px">{t}</span>'
        for t in CLIENT_TYPES
    )

    # Summary cards
    summary_cards = f"""
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px">
  <div style="background:#0a0f1a;border:1px solid #1e3a5f;border-radius:10px;padding:16px 20px">
    <div style="font-size:10px;font-weight:700;color:#475569;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px">Total Clients</div>
    <div style="font-size:32px;font-weight:800;color:#e2e8f0">{total}</div>
    <div style="font-size:11px;color:#64748b;margin-top:4px">{len(owners_sorted)} account owners</div>
  </div>
  <div style="background:#0a0f1a;border:1px solid #1e3a5f;border-radius:10px;padding:16px 20px">
    <div style="font-size:10px;font-weight:700;color:#475569;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px">CBR Complete ✅</div>
    <div style="font-size:32px;font-weight:800;color:#34d399">{ok}</div>
    <div style="font-size:11px;color:#64748b;margin-top:4px">last CBR ≤ 180 days</div>
  </div>
  <div style="background:#0a0f1a;border:1px solid #1e3a5f;border-radius:10px;padding:16px 20px">
    <div style="font-size:10px;font-weight:700;color:#475569;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px">Overdue ⚠️</div>
    <div style="font-size:32px;font-weight:800;color:#fbbf24">{overdue}</div>
    <div style="font-size:11px;color:#64748b;margin-top:4px">&gt; 180 days since CBR</div>
  </div>
  <div style="background:#0a0f1a;border:1px solid #1e3a5f;border-radius:10px;padding:16px 20px">
    <div style="font-size:10px;font-weight:700;color:#475569;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px">Never Had CBR ❌</div>
    <div style="font-size:32px;font-weight:800;color:#f87171">{never}</div>
    <div style="font-size:11px;color:#64748b;margin-top:4px">no completed review on record</div>
  </div>
</div>"""

    # Owner sections
    owner_html = ""
    for owner in owners_sorted:
        type_dict = owner_groups[owner]
        owner_total = sum(len(v) for v in type_dict.values())
        owner_never = sum(1 for t in type_dict.values() for a in t if not a["last_cbr"])
        owner_overdue = sum(1 for t in type_dict.values() for a in t
                            if a["last_cbr"] and days_since(a["last_cbr"]) > 180)
        owner_ok = owner_total - owner_never - owner_overdue

        # Stats pills
        stats = (
            f'<span style="font-size:11px;color:#94a3b8;margin-left:12px">{owner_total} clients</span>'
            f'<span style="font-size:11px;background:#14532d;color:#34d399;padding:2px 8px;border-radius:8px;margin-left:8px">{owner_ok} current</span>'
        )
        if owner_overdue:
            stats += f'<span style="font-size:11px;background:#451a03;color:#fbbf24;padding:2px 8px;border-radius:8px;margin-left:4px">{owner_overdue} overdue</span>'
        if owner_never:
            stats += f'<span style="font-size:11px;background:#2d0a0a;color:#f87171;padding:2px 8px;border-radius:8px;margin-left:4px">{owner_never} never</span>'

        type_sections = ""
        for atype in sorted(type_dict.keys(), key=type_sort_key):
            accounts = sorted(type_dict[atype], key=lambda a: a["last_cbr"] or "0000", reverse=True)
            tc = type_color(atype)
            count = len(accounts)
            t_never = sum(1 for a in accounts if not a["last_cbr"])
            t_overdue = sum(1 for a in accounts if a["last_cbr"] and days_since(a["last_cbr"]) > 180)

            rows = ""
            for acct in accounts:
                d = days_since(acct["last_cbr"])
                color, label = cbr_badge(d)
                date_display = acct["last_cbr"] or "—"
                subj = acct.get("last_cbr_subject", "")
                # Clean up Outreach prefix from subject
                subj = re.sub(r'^\[Outreach\]\s*\[Email\]\s*\[(?:Out|In)\]\s*', '', subj)
                subj = subj[:60] + "…" if len(subj) > 60 else subj

                rows += (
                    f'<tr style="border-bottom:1px solid #0f172a">'
                    f'<td style="padding:8px 12px;font-size:13px;color:#e2e8f0;font-weight:500">{acct["name"]}</td>'
                    f'<td style="padding:8px 12px;font-size:12px;color:#64748b">{date_display}</td>'
                    f'<td style="padding:8px 12px"><span style="font-size:11px;font-weight:700;color:{color};'
                    f'background:#0a0f1a;padding:2px 8px;border-radius:8px">{label}</span></td>'
                    f'<td style="padding:8px 12px;font-size:11px;color:#475569;max-width:300px">{subj}</td>'
                    f'</tr>'
                )

            type_stat = ""
            if t_overdue:
                type_stat += f' <span style="font-size:10px;color:#fbbf24">{t_overdue} overdue</span>'
            if t_never:
                type_stat += f' <span style="font-size:10px;color:#f87171">{t_never} never</span>'

            type_sections += f"""
<div style="margin-bottom:20px">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
    <span style="background:#0f172a;border:1px solid {tc};color:{tc};font-size:10px;font-weight:700;
      padding:3px 10px;border-radius:10px">{atype}</span>
    <span style="font-size:11px;color:#475569">{count} accounts{type_stat}</span>
  </div>
  <div style="background:#070c18;border-radius:8px;overflow:hidden">
  <table style="width:100%;border-collapse:collapse">
  <thead><tr style="background:#1e293b">
    <th style="padding:6px 12px;font-size:10px;color:#475569;text-align:left;text-transform:uppercase">Client</th>
    <th style="padding:6px 12px;font-size:10px;color:#475569;text-align:left;text-transform:uppercase">Last CBR</th>
    <th style="padding:6px 12px;font-size:10px;color:#475569;text-align:left;text-transform:uppercase">Status</th>
    <th style="padding:6px 12px;font-size:10px;color:#475569;text-align:left;text-transform:uppercase">Subject</th>
  </tr></thead>
  <tbody>{rows}</tbody>
  </table>
  </div>
</div>"""

        owner_html += f"""
<div style="background:#0d1424;border:1px solid #1e3a5f;border-radius:12px;padding:20px 24px;margin-bottom:24px">
  <div style="display:flex;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px">
    <div style="font-size:16px;font-weight:700;color:#e2e8f0">{owner}</div>
    {stats}
  </div>
  {type_sections}
</div>"""

    # Full page
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CBR Dashboard — Rev.io</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ background:#020817; color:#e2e8f0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; padding:24px }}
  table {{ width:100%; border-collapse:collapse }}
  th {{ font-weight:600 }}
  tr:hover td {{ background:rgba(255,255,255,0.02) }}
  @media(max-width:768px) {{ body {{ padding:12px }} }}
</style>
</head>
<body>
<div style="max-width:1200px;margin:0 auto">

<!-- Header -->
<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px;flex-wrap:wrap;gap:12px">
  <div>
    <div style="font-size:10px;font-weight:700;color:#38bdf8;letter-spacing:3px;text-transform:uppercase;margin-bottom:6px">Rev.io</div>
    <div style="font-size:28px;font-weight:800;color:#e2e8f0">Client Business Review Tracker</div>
    <div style="font-size:13px;color:#64748b;margin-top:4px">Last completed CBR per client — grouped by account owner &amp; type</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:11px;color:#475569">Updated {today_str}</div>
    <div style="font-size:11px;color:#475569;margin-top:2px">Source: Salesforce Events &amp; Tasks</div>
  </div>
</div>

<!-- Legend -->
<div style="margin-bottom:16px;display:flex;align-items:center;flex-wrap:wrap;gap:6px">
  <span style="font-size:10px;color:#475569;margin-right:4px;font-weight:700">ACCOUNT TYPES:</span>
  {type_pills}
</div>

<!-- CBR Status Legend -->
<div style="margin-bottom:24px;display:flex;align-items:center;gap:16px;font-size:11px;color:#64748b">
  <span><span style="color:#34d399;font-weight:700">●</span> Current (≤ 90 days)</span>
  <span><span style="color:#fbbf24;font-weight:700">●</span> Aging (91–180 days)</span>
  <span><span style="color:#f87171;font-weight:700">●</span> Overdue (&gt; 180 days)</span>
  <span><span style="color:#f87171;font-weight:700">●</span> Never</span>
</div>

<!-- Summary -->
{summary_cards}

<!-- Owner sections -->
{owner_html}

</div>
</body>
</html>"""

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)
    print(f"Built: {len(html):,} chars → {OUTPUT_FILE}")

    # Git push
    import subprocess
    cmds = [
        f"cd {REPO_PATH} && git add cbr-dashboard.html",
        f'cd {REPO_PATH} && git commit -m "CBR Dashboard — {today_str}"',
        f"cd {REPO_PATH} && git push",
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  git error: {result.stderr[:200]}")
        else:
            print(f"  {result.stdout.strip() or result.stderr.strip()}")
    print("✅ Pushed to GitHub")


if __name__ == "__main__":
    main()
