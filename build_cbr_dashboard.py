#!/usr/bin/env python3
"""
CBR Dashboard — Client Business Review tracker
- Tabs per account owner
- Sub-tabs per product type
- PSA clients split: Tigerpaw__c=true → "Tigerpaw", false → "PSA Web"
- Excludes Channel Client + Usman Zahoor accounts
"""

import requests, json, re
from datetime import datetime, timedelta
from collections import defaultdict

SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
SF_INSTANCE = "https://rev-io.my.salesforce.com"
REPO_PATH = "/tmp/robin-decks"
OUTPUT_FILE = f"{REPO_PATH}/cbr-dashboard.html"
USMAN_ID = "005PX00000556I1YAI"

CLIENT_TYPES = [
    "Rev.io PSA Client",
    "TigerPaw Client",    # split via Tigerpaw__c checkbox same as PSA Client
    "Rev.io Billing Client",
    "Rev.io Odin Client",
    "Client",
    # "Channel Client" — excluded per Ryan
]

# Display labels (after Tigerpaw split)
TYPE_LABELS = {
    "PSA Web": "PSA Web",
    "Tigerpaw": "Tigerpaw",
    "Rev.io Billing Client": "Billing",
    "TigerPaw Client": "TigerPaw Client",
    "Rev.io Odin Client": "Odin",
    "Client": "Client",
}

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
    results = []
    url = f"{iurl}/services/data/v57.0/query"
    params = {"q": soql}
    while True:
        r = requests.get(url, headers=hdrs, params=params)
        if not r.ok:
            print(f"  SF error: {r.text[:200]}")
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
    if days is None:
        return "#f87171", "Never", "never"
    if days <= 90:
        return "#34d399", f"{days}d ago", "current"
    if days <= 180:
        return "#fbbf24", f"{days}d ago", "aging"
    return "#f87171", f"{days}d ago", "overdue"


def type_sort_key(t):
    order = {
        "PSA Web": 0,
        "Tigerpaw": 1,
        "Rev.io Billing Client": 2,
        "Rev.io Odin Client": 3,
        "TigerPaw Client": 4,
        "Client": 5,
    }
    return order.get(t, 99)


TYPE_COLORS = {
    "PSA Web": "#38bdf8",
    "Tigerpaw": "#fbbf24",
    "Rev.io Billing Client": "#a78bfa",
    "Rev.io Odin Client": "#34d399",
    "TigerPaw Client": "#fb923c",
    "Client": "#94a3b8",
}


def type_color(t):
    return TYPE_COLORS.get(t, "#64748b")


def clean_subject(s):
    s = re.sub(r'^\[Outreach\]\s*\[Email\]\s*\[(?:Out|In)\]\s*', '', s)
    return (s[:60] + "…") if len(s) > 60 else s


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("Authenticating...")
    at, iurl = sf_auth()
    hdrs = {"Authorization": f"Bearer {at}"}

    # 1. Pull client accounts (exclude Channel Client + Usman)
    print("Pulling client accounts...")
    types_in = "(" + ",".join(f"'{t}'" for t in CLIENT_TYPES) + ")"
    accounts_raw = sf_query_all(hdrs, iurl,
        f"SELECT Id, Name, Type, Tigerpaw__c, Rev_io_Payments__c, LastActivityDate, Owner.Name, OwnerId FROM Account "
        f"WHERE Type IN {types_in} AND OwnerId != '{USMAN_ID}' ORDER BY Name")
    print(f"  {len(accounts_raw)} accounts (excl. Usman + Channel Client)")

    acct_map = {}
    for a in accounts_raw:
        owner_name = (a.get("Owner") or {}).get("Name", "Unassigned")
        raw_type = a.get("Type", "")
        # Split PSA clients by Tigerpaw checkbox
        if raw_type in ("Rev.io PSA Client", "TigerPaw Client"):
            display_type = "Tigerpaw" if a.get("Tigerpaw__c") else "PSA Web"
        elif raw_type == "Client":
            display_type = "Rev.io Billing Client"  # legacy type, treat as Billing
        else:
            display_type = raw_type
        acct_map[a["Id"]] = {
            "id": a["Id"],
            "name": a["Name"],
            "raw_type": raw_type,
            "type": display_type,
            "owner": owner_name,
            "payments": bool(a.get("Rev_io_Payments__c")),
            "last_activity": (a.get("LastActivityDate") or "")[:10],
            "last_cbr": None,
            "last_cbr_subject": "",
            "last_cbr_owner": "",
            "won_opps": [],
        }

    # 2. CBR Events (WhatId = AccountId)
    print("Pulling CBR Events...")
    events = sf_query_all(hdrs, iurl,
        "SELECT Id, Subject, ActivityDate, WhatId, Owner.Name FROM Event "
        "WHERE Subject LIKE '%Business Review%' AND WhatId != null "
        "ORDER BY ActivityDate DESC")
    print(f"  {len(events)} events with account link")
    for ev in events:
        aid = ev.get("WhatId")
        if aid in acct_map:
            date = ev.get("ActivityDate", "")
            if not acct_map[aid]["last_cbr"] or date > acct_map[aid]["last_cbr"]:
                acct_map[aid]["last_cbr"] = date
                acct_map[aid]["last_cbr_subject"] = ev.get("Subject", "")
                acct_map[aid]["last_cbr_owner"] = (ev.get("Owner") or {}).get("Name", "")

    # Tasks excluded — Outreach email sequences, not actual CBR meetings

    # 3. Closed Won opportunities per account
    print("Pulling Closed Won opportunities...")
    acct_ids = list(acct_map.keys())
    won_map = defaultdict(list)
    for i in range(0, len(acct_ids), 500):
        chunk = acct_ids[i:i+500]
        ids_in = "(" + ",".join(f"'{a}'" for a in chunk) + ")"
        opps = sf_query_all(hdrs, iurl,
            f"SELECT Id, Name, Amount, CloseDate, Owner.Name, AccountId FROM Opportunity "
            f"WHERE StageName = 'Closed Won' AND AccountId IN {ids_in} "
            f"ORDER BY CloseDate DESC")
        for opp in opps:
            won_map[opp["AccountId"]].append({
                "name": opp.get("Name", ""),
                "amount": opp.get("Amount") or 0,
                "close_date": opp.get("CloseDate", ""),
                "owner": (opp.get("Owner") or {}).get("Name", ""),
            })
    for aid, opps in won_map.items():
        if aid in acct_map:
            acct_map[aid]["won_opps"] = opps
    print(f"  {sum(len(v) for v in won_map.values())} closed won opps across {len(won_map)} accounts")

    # 4. Group: owner → type → [accounts]
    owner_groups = defaultdict(lambda: defaultdict(list))
    for acct in acct_map.values():
        owner_groups[acct["owner"]][acct["type"]].append(acct)

    owners_sorted = sorted(owner_groups.keys(),
        key=lambda o: sum(len(v) for v in owner_groups[o].values()), reverse=True)

    # 5. Global stats
    total = len(acct_map)
    never = sum(1 for a in acct_map.values() if not a["last_cbr"])
    overdue = sum(1 for a in acct_map.values() if a["last_cbr"] and days_since(a["last_cbr"]) > 180)
    aging = sum(1 for a in acct_map.values() if a["last_cbr"] and 90 < days_since(a["last_cbr"]) <= 180)
    current = total - never - overdue - aging

    # ── HTML Build ─────────────────────────────────────────────────────────
    print("Building HTML...")

    # ── Owner tab buttons ──
    owner_tab_btns = ""
    for i, owner in enumerate(owners_sorted):
        cnt = sum(len(v) for v in owner_groups[owner].values())
        active = "active" if i == 0 else ""
        owner_tab_btns += (
            f'<button class="owner-tab {active}" data-owner="{i}" onclick="switchOwner({i})">'
            f'{owner} <span class="tab-count">{cnt}</span>'
            f'</button>'
        )

    # ── Owner panels ──
    owner_panels_html = ""
    for oi, owner in enumerate(owners_sorted):
        type_dict = owner_groups[owner]
        types_sorted = sorted(type_dict.keys(), key=type_sort_key)

        owner_total = sum(len(v) for v in type_dict.values())
        o_never   = sum(1 for t in type_dict.values() for a in t if not a["last_cbr"])
        o_overdue = sum(1 for t in type_dict.values() for a in t if a["last_cbr"] and days_since(a["last_cbr"]) > 180)
        o_aging   = sum(1 for t in type_dict.values() for a in t if a["last_cbr"] and 90 < days_since(a["last_cbr"]) <= 180)
        o_current = owner_total - o_never - o_overdue - o_aging

        # Product sub-tab buttons for this owner
        prod_tab_btns = ""
        for pi, ptype in enumerate(types_sorted):
            cnt = len(type_dict[ptype])
            label = TYPE_LABELS.get(ptype, ptype)
            color = type_color(ptype)
            active = "active" if pi == 0 else ""
            prod_tab_btns += (
                f'<button class="prod-tab {active}" data-owner="{oi}" data-prod="{pi}" '
                f'onclick="switchProd({oi},{pi})" '
                f'style="--tab-color:{color}">'
                f'{label} <span class="tab-count">{cnt}</span>'
                f'</button>'
            )

        # Product sub-panels
        prod_panels_html = ""
        for pi, ptype in enumerate(types_sorted):
            accounts = sorted(type_dict[ptype], key=lambda a: a["last_cbr"] or "0000", reverse=True)
            color = type_color(ptype)
            t_never   = sum(1 for a in accounts if not a["last_cbr"])
            t_overdue = sum(1 for a in accounts if a["last_cbr"] and days_since(a["last_cbr"]) > 180)
            t_aging   = sum(1 for a in accounts if a["last_cbr"] and 90 < days_since(a["last_cbr"]) <= 180)
            t_current = len(accounts) - t_never - t_overdue - t_aging

            rows = ""
            for acct in accounts:
                d = days_since(acct["last_cbr"])
                badge_color, badge_label, badge_class = cbr_badge(d)
                cbr_by = acct.get("last_cbr_owner", "")
                cbr_by_html = f'<div style="font-size:10px;color:#475569;margin-top:2px">{cbr_by}</div>' if cbr_by else ""
                # Closed Won opps
                won = acct.get("won_opps", [])
                if won:
                    won_lines = "".join(
                        f'<div style="font-size:11px;color:#94a3b8;white-space:nowrap">'
                        f'{o["close_date"][:7] if o["close_date"] else ""} &nbsp;'
                        f'<span style="color:#e2e8f0">{o["name"][:40] + "…" if len(o["name"]) > 40 else o["name"]}</span>'
                        f'&nbsp;<span style="color:#34d399;font-weight:700">${o["amount"]:,.0f}</span>'
                        f'&nbsp;<span style="color:#475569">{o["owner"]}</span>'
                        f'</div>'
                        for o in won[:3]
                    )
                    if len(won) > 3:
                        won_lines += f'<div style="font-size:10px;color:#475569">+{len(won)-3} more</div>'
                    won_cell = won_lines
                else:
                    won_cell = '<span style="color:#475569;font-size:11px">—</span>'
                payments_cell = (
                    '<td style="text-align:center;font-size:15px">✅</td>'
                    if acct.get("payments") else
                    '<td style="text-align:center;font-size:13px;color:#334155">—</td>'
                )
                last_act = acct.get("last_activity", "")
                last_act_days = days_since(last_act) if last_act else None
                if last_act_days is None:
                    act_html = '<span style="color:#475569;font-size:12px">—</span>'
                elif last_act_days <= 7:
                    act_html = f'<span style="font-size:12px;color:#34d399">{last_act}</span><div style="font-size:10px;color:#475569">{last_act_days}d ago</div>'
                elif last_act_days <= 30:
                    act_html = f'<span style="font-size:12px;color:#fbbf24">{last_act}</span><div style="font-size:10px;color:#475569">{last_act_days}d ago</div>'
                else:
                    act_html = f'<span style="font-size:12px;color:#f87171">{last_act}</span><div style="font-size:10px;color:#475569">{last_act_days}d ago</div>'
                rows += (
                    f'<tr class="acct-row {badge_class}">'
                    f'<td class="acct-name">{acct["name"]}</td>'
                    f'{payments_cell}'
                    f'<td class="acct-date">{acct["last_cbr"] or "—"}{cbr_by_html}</td>'
                    f'<td><span class="badge" style="color:{badge_color};border-color:{badge_color}20;background:{badge_color}12">'
                    f'{badge_label}</span></td>'
                    f'<td style="white-space:nowrap">{act_html}</td>'
                    f'<td class="acct-subject won-cell">{won_cell}</td>'
                    f'</tr>'
                )

            disp = "block" if pi == 0 else "none"
            prod_panels_html += f"""
<div class="prod-panel" data-owner="{oi}" data-prod="{pi}" style="display:{disp}">
  <div class="prod-stats">
    <span class="pstat green">{t_current} current</span>
    <span class="pstat yellow">{t_aging} aging</span>
    <span class="pstat red">{t_overdue} overdue</span>
    <span class="pstat dim">{t_never} never</span>
  </div>
  <div class="table-wrap">
  <table>
    <thead><tr>
      <th>Client</th><th style="text-align:center">Payments</th><th>Last CBR</th><th>Status</th><th>Last Activity</th><th>Closed Won Opportunities</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</div>"""

        disp = "block" if oi == 0 else "none"
        owner_panels_html += f"""
<div class="owner-panel" data-owner="{oi}" style="display:{disp}">
  <div class="owner-summary">
    <span class="ostat green">{o_current} current</span>
    <span class="ostat yellow">{o_aging} aging</span>
    <span class="ostat red">{o_overdue} overdue</span>
    <span class="ostat dim">{o_never} never</span>
  </div>
  <div class="prod-tabs">{prod_tab_btns}</div>
  {prod_panels_html}
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CBR Dashboard — Rev.io</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#020817;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px;min-height:100vh}}
.wrap{{max-width:1300px;margin:0 auto}}

/* Header */
.header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px;flex-wrap:wrap;gap:12px}}
.header-left .eyebrow{{font-size:10px;font-weight:700;color:#38bdf8;letter-spacing:3px;text-transform:uppercase;margin-bottom:6px}}
.header-left h1{{font-size:28px;font-weight:800;color:#e2e8f0}}
.header-left p{{font-size:13px;color:#64748b;margin-top:4px}}
.header-right{{font-size:11px;color:#475569;text-align:right}}

/* Summary cards */
.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:28px}}
.card{{background:#0a0f1a;border:1px solid #1e3a5f;border-radius:10px;padding:16px 20px}}
.card-label{{font-size:10px;font-weight:700;color:#475569;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px}}
.card-val{{font-size:32px;font-weight:800}}
.card-sub{{font-size:11px;color:#64748b;margin-top:4px}}

/* Legend */
.legend{{display:flex;align-items:center;gap:16px;font-size:11px;color:#64748b;margin-bottom:24px;flex-wrap:wrap}}

/* Owner tabs */
.owner-tabs{{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap;border-bottom:1px solid #1e3a5f;padding-bottom:0}}
.owner-tab{{background:transparent;border:none;border-bottom:2px solid transparent;color:#64748b;font-size:13px;
  font-weight:600;padding:10px 16px;cursor:pointer;transition:all .15s;white-space:nowrap;margin-bottom:-1px}}
.owner-tab:hover{{color:#94a3b8}}
.owner-tab.active{{color:#38bdf8;border-bottom-color:#38bdf8}}
.tab-count{{background:#1e293b;color:#64748b;font-size:10px;font-weight:700;padding:2px 6px;border-radius:8px;margin-left:6px}}
.owner-tab.active .tab-count{{background:#0c2a4a;color:#38bdf8}}

/* Owner panel */
.owner-panel{{background:#0d1424;border:1px solid #1e3a5f;border-radius:12px;padding:20px 24px}}
.owner-summary{{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}}

/* Product sub-tabs */
.prod-tabs{{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}}
.prod-tab{{background:#0a0f1a;border:1px solid #1e3a5f;border-radius:8px;color:#64748b;font-size:11px;
  font-weight:700;padding:6px 12px;cursor:pointer;transition:all .15s;white-space:nowrap}}
.prod-tab:hover{{border-color:var(--tab-color);color:var(--tab-color)}}
.prod-tab.active{{background:color-mix(in srgb,var(--tab-color) 10%,transparent);border-color:var(--tab-color);color:var(--tab-color)}}
.prod-tab.active .tab-count{{color:var(--tab-color)}}

/* Stats pills */
.pstat,.ostat{{font-size:11px;font-weight:600;padding:3px 10px;border-radius:8px}}
.pstat.green,.ostat.green{{background:#14532d20;color:#34d399;border:1px solid #14532d}}
.pstat.yellow,.ostat.yellow{{background:#451a0320;color:#fbbf24;border:1px solid #451a03}}
.pstat.red,.ostat.red{{background:#2d0a0a20;color:#f87171;border:1px solid #2d0a0a}}
.pstat.dim,.ostat.dim{{background:#1e293b20;color:#475569;border:1px solid #1e293b}}
.prod-stats{{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}}

/* Table */
.table-wrap{{background:#070c18;border-radius:8px;overflow:hidden;overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
thead tr{{background:#1e293b}}
th{{padding:8px 12px;font-size:10px;color:#475569;text-align:left;text-transform:uppercase;font-weight:700;white-space:nowrap}}
.acct-row td{{padding:9px 12px;border-bottom:1px solid #0f172a}}
.acct-row:last-child td{{border-bottom:none}}
.acct-row:hover td{{background:rgba(255,255,255,0.02)}}
.acct-name{{font-size:13px;color:#e2e8f0;font-weight:500;white-space:nowrap}}
.acct-date{{font-size:12px;color:#64748b;white-space:nowrap}}
.acct-subject{{font-size:11px;color:#475569;max-width:320px}}
.badge{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:8px;border:1px solid;white-space:nowrap}}

@media(max-width:768px){{
  body{{padding:12px}}
  .summary{{grid-template-columns:repeat(2,1fr)}}
  .card-val{{font-size:24px}}
}}
</style>
</head>
<body>
<div class="wrap">

<!-- Header -->
<div class="header">
  <div class="header-left">
    <div class="eyebrow">Rev.io</div>
    <h1>Client Business Review Tracker</h1>
    <p>Last completed CBR per client — by account owner &amp; product</p>
  </div>
  <div class="header-right">
    <div>Updated {today_str}</div>
    <div style="margin-top:2px">Source: Salesforce Events</div>
  </div>
</div>

<!-- Legend -->
<div class="legend">
  <span><span style="color:#34d399;font-weight:700">●</span> Current (≤ 90d)</span>
  <span><span style="color:#fbbf24;font-weight:700">●</span> Aging (91–180d)</span>
  <span><span style="color:#f87171;font-weight:700">●</span> Overdue (&gt; 180d)</span>
  <span><span style="color:#f87171;font-weight:700">●</span> Never</span>
  <span style="margin-left:8px;color:#475569">|</span>
  <span style="color:#475569"><em>Excludes Channel Client &amp; Usman Zahoor accounts</em></span>
</div>

<!-- Summary cards -->
<div class="summary">
  <div class="card">
    <div class="card-label">Total Clients</div>
    <div class="card-val" style="color:#e2e8f0">{total}</div>
    <div class="card-sub">{len(owners_sorted)} account owners</div>
  </div>
  <div class="card">
    <div class="card-label">Current ✅</div>
    <div class="card-val" style="color:#34d399">{current}</div>
    <div class="card-sub">CBR within 90 days</div>
  </div>
  <div class="card">
    <div class="card-label">Aging / Overdue ⚠️</div>
    <div class="card-val" style="color:#fbbf24">{aging + overdue}</div>
    <div class="card-sub">{aging} aging · {overdue} overdue</div>
  </div>
  <div class="card">
    <div class="card-label">Never Had CBR ❌</div>
    <div class="card-val" style="color:#f87171">{never}</div>
    <div class="card-sub">no completed review on record</div>
  </div>
</div>

<!-- Owner tabs -->
<div class="owner-tabs">{owner_tab_btns}</div>

<!-- Owner panels -->
{owner_panels_html}

</div>
<script>
function switchOwner(idx) {{
  document.querySelectorAll('.owner-tab').forEach((b,i) => b.classList.toggle('active', i===idx));
  document.querySelectorAll('.owner-panel').forEach(p => p.style.display = p.dataset.owner==idx ? 'block' : 'none');
}}
function switchProd(ownerIdx, prodIdx) {{
  document.querySelectorAll(`.prod-tab[data-owner="${{ownerIdx}}"]`).forEach((b,i) => b.classList.toggle('active', i===prodIdx));
  document.querySelectorAll(`.prod-panel[data-owner="${{ownerIdx}}"]`).forEach(p => p.style.display = p.dataset.prod==prodIdx ? 'block' : 'none');
}}
</script>
</body>
</html>"""

    with open(OUTPUT_FILE, "w") as f:
        f.write(html)
    print(f"Built: {len(html):,} chars")

    # Push via workspace git + robin-decks remote
    import subprocess, os, shutil
    SSH_KEY = "/home/openclaw/.openclaw/ssh/id_ed25519"
    env = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no"}

    ws = "/home/openclaw/.openclaw/workspace"
    shutil.copy(OUTPUT_FILE, f"{ws}/cbr-dashboard.html")
    for cmd in [
        f"cd {ws} && git add cbr-dashboard.html build_cbr_dashboard.py",
        f'cd {ws} && git commit -m "CBR Dashboard v2 — tabs, PSA split, excl Channel/Usman"',
        f"cd {ws} && git push robin-decks push-q2-board:master",
    ]:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
        out = (r.stdout + r.stderr).strip()
        print(f"  {out[:120]}")
    print("✅ Done")


if __name__ == "__main__":
    main()
