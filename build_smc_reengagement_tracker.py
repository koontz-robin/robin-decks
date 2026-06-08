#!/usr/bin/env python3
"""Build the PSA Software Missing Capabilities re-engagement tracker."""

from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
OUTFILE = WORKSPACE / "smc-reengagement-tracker.html"
DATAFILE = WORKSPACE / "sf_smc_reengagement_accounts.json"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

START_DATE = "2025-07-01"

FEATURE_PATTERNS = [
    ("Project Management", r"project"),
    ("Job Costing", r"job cost|profitab"),
    ("Mobile App / GPS Tracking", r"mobile|gps|geo.?fenc|fleet"),
    ("Enhanced Ticket Views", r"ticket|freshdesk|screenconnect"),
    ("Knowledgebase", r"knowledge ?base|hudu"),
    ("Custom Fields / Reporting", r"report|custom field|rmr"),
    ("Sales Opportunities", r"sales pipeline|crm|lead|opportunit"),
    ("CPQ", r"cpq|quote|proposal|change order|vendor pricing|live pricing"),
    ("Progressive Billing", r"progressive billing|billing"),
    ("Subcontractors", r"subcontract"),
    ("SLAs", r"\bsla\b"),
    ("Co-Managed Support", r"co-managed|client ticket"),
    ("Zone Lists", r"zone"),
    ("Internationalization", r"international"),
    ("Integration - QuickBooks Desktop", r"quickbooks desktop|qb desktop"),
    ("Integration - Sage50", r"sage ?50|sage 300"),
    ("Integration - Netsuite", r"netsuite"),
    ("Integration - DTools", r"d.?tools"),
    ("Integration - Ninja RMM", r"ninja"),
    ("Integration - IT Glue", r"it glue"),
    ("Integration - Portal", r"portal"),
    ("Integration - CMS", r"central station|cms|rapid response|ucc|security central"),
    ("Integration - Zoho", r"zoho"),
    ("Integration - Hubspot", r"hubspot"),
    ("Integration - Xero", r"xero"),
    ("Integration - Acronis", r"acronis"),
]


def sf_auth() -> tuple[str, dict[str, str]]:
    resp = requests.post(
        f"{SF_INSTANCE}/services/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": SF_CLIENT_ID,
            "client_secret": SF_CLIENT_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["instance_url"], {"Authorization": f"Bearer {data['access_token']}"}


def sf_query_all(base: str, headers: dict[str, str], query: str) -> list[dict]:
    records: list[dict] = []
    url = f"{base}/services/data/v59.0/query"
    params = {"q": query.strip()}
    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"Salesforce query failed: {resp.status_code} {resp.text[:500]}\n{query}")
        data = resp.json()
        records.extend(data.get("records", []))
        next_url = data.get("nextRecordsUrl")
        url = f"{base}{next_url}" if next_url else ""
        params = {}
    return records


def chunks(values: list[str], size: int = 100) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def soql_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def clean_record(record: dict) -> dict:
    record = dict(record)
    record.pop("attributes", None)
    return record


def child_name(record: dict, key: str, default: str = "") -> str:
    value = record.get(key)
    return value.get("Name", default) if isinstance(value, dict) else default


def account_owner(record: dict) -> str:
    account = record.get("Account")
    if not isinstance(account, dict):
        return ""
    owner = account.get("Owner")
    return owner.get("Name", "") if isinstance(owner, dict) else ""


def account_name(record: dict) -> str:
    account = record.get("Account")
    return account.get("Name", "") if isinstance(account, dict) else record.get("Name", "")


def account_last_activity(record: dict) -> str:
    account = record.get("Account")
    return account.get("LastActivityDate") or "" if isinstance(account, dict) else ""


def fmt_money(value: float | int | None) -> str:
    return f"${(value or 0):,.0f}"


def parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    if "T" not in value:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")


def short_text(value: str, limit: int = 120) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def features_from_detail(detail: str) -> str:
    text = detail or ""
    found = [label for label, pattern in FEATURE_PATTERNS if re.search(pattern, text, re.I)]
    return ", ".join(found) if found else "-"


def stage_badge(stage: str) -> str:
    if not stage:
        return ""
    color = "#3DC570" if stage == "Closed Won" else "#f87171" if stage == "Closed Lost" else "#a78bfa"
    return f'<span style="font-size:10px;font-weight:600;padding:2px 7px;border-radius:4px;background:{color}22;color:{color}">{html.escape(stage)}</span>'


def status_badge(status: str) -> str:
    color = {
        "Closed Won": "#3DC570",
        "Active Opp": "#a78bfa",
        "Closed Lost": "#f87171",
        "Contacted": "#38bdf8",
        "Not Contacted": "#475569",
    }.get(status, "#475569")
    return f'<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;background:{color}22;color:{color}">{html.escape(status)}</span>'


def build_rows(accounts: list[dict]) -> str:
    rows = []
    for row in accounts:
        detail = row["reason_lost_detail"] or ""
        activity_color = "#3DC570" if row["recent_activity"] == "fresh" else "#f5a623" if row["recent_activity"] == "warm" else "#475569"
        rows.append(
            "<tr>"
            f'<td style="font-weight:600;color:#e2e8f0">{html.escape(row["account"])}</td>'
            f'<td style="color:#3DC570;font-weight:700">{fmt_money(row["mrr"])}</td>'
            f'<td style="color:#64748b">{html.escape(row["owner"])}</td>'
            f'<td style="color:#94a3b8;font-size:11px">{html.escape(row["account_owner"])}</td>'
            f'<td style="color:#475569;font-size:10px">{html.escape(row["features"])}</td>'
            f'<td style="color:#94a3b8;font-size:10px;max-width:220px;word-break:break-word" title="{html.escape(detail)}">{html.escape(short_text(detail)) if detail else "<span style=\"color:#334155\">-</span>"}</td>'
            f'<td style="text-align:center;color:#64748b;font-size:11px">{row["reeng_count"] or ""}</td>'
            f'<td style="text-align:center"><span style="color:#64748b;font-size:11px">{html.escape(row["last_close_date"])}</span></td>'
            f'<td style="text-align:center"><span style="color:{activity_color};font-size:11px;font-weight:600">{html.escape(row["last_activity"] or "-")}</span></td>'
            f'<td style="text-align:center">{stage_badge(row["stage"])}</td>'
            f'<td style="text-align:center">{status_badge(row["status"])}</td>'
            "</tr>"
        )
    return "\n".join(rows)


def build_html(accounts: list[dict]) -> str:
    now = datetime.now(timezone.utc)
    date_label = now.strftime("%B %-d, %Y")
    owner_counts = Counter(row["owner"] or "Unassigned" for row in accounts)
    total_accounts = len(accounts)
    closed_won = [row for row in accounts if row["status"] == "Closed Won"]
    active = [row for row in accounts if row["status"] == "Active Opp"]
    lost_again = [row for row in accounts if row["status"] == "Closed Lost"]
    contacted = [row for row in accounts if row["status"] == "Contacted"]
    not_contacted = [row for row in accounts if row["status"] == "Not Contacted"]
    total_pool = sum(row["mrr"] for row in accounts)
    won_mrr = sum(row["won_mrr"] for row in closed_won)
    active_mrr = sum(row["active_mrr"] for row in active)

    owner_tabs = [
        f'<div class="owner-tab active" onclick="filterByOwner(\'\')" id="tab-all">All <span class="tab-count">({total_accounts})</span></div>'
    ]
    for owner, count in owner_counts.most_common():
        safe_owner = html.escape(owner, quote=True)
        owner_tabs.append(
            f'<div class="owner-tab" onclick="filterByOwner(\'{safe_owner}\')">{html.escape(owner)} <span class="tab-count">({count})</span></div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PSA SMC Re-engagement Tracker</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e2e8f0}}
header{{background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);border-bottom:1px solid #334155;padding:20px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
header h1{{font-size:1.4rem;font-weight:700;color:#f8fafc}}
header h1 span{{color:#3DC570}}
.updated{{font-size:.72rem;color:#64748b;margin-top:4px}}
.container{{max-width:1800px;margin:0 auto;padding:24px}}
.kpi-row{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:24px}}
.kpi{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:14px 18px;flex:1;min-width:110px;position:relative;overflow:hidden}}
.kpi::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--accent,#38bdf8)}}
.kpi.green{{--accent:#3DC570}}.kpi.purple{{--accent:#a78bfa}}.kpi.red{{--accent:#f87171}}.kpi.blue{{--accent:#38bdf8}}.kpi.grey{{--accent:#475569}}.kpi.cyan{{--accent:#38bdf8}}.kpi.orange{{--accent:#f5a623}}
.kpi-label{{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;margin-bottom:4px}}
.kpi-val{{font-size:24px;font-weight:800;color:#f8fafc;line-height:1}}
.kpi-sub{{font-size:10px;color:#64748b;margin-top:2px}}
.search-bar{{margin-bottom:12px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
.search-bar input{{background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:8px 14px;border-radius:6px;font-size:13px;width:360px;outline:none}}
.search-bar input:focus{{border-color:#3DC570}}
.legend{{display:flex;gap:12px;align-items:center;font-size:10px;color:#475569;flex-wrap:wrap}}
.legend span{{display:flex;align-items:center;gap:4px}}
.dot{{width:8px;height:8px;border-radius:50%;display:inline-block}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
thead{{background:#0f172a}}
th{{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#64748b;padding:8px 12px;text-align:left;border-bottom:1px solid #334155;white-space:nowrap}}
td{{padding:8px 12px;border-bottom:1px solid #1a2438;vertical-align:middle}}
tr:hover td{{background:rgba(61,197,112,.02)}}
.footer{{text-align:center;padding:20px;font-size:.72rem;color:#475569;border-top:1px solid #1e293b;margin-top:8px}}
.note{{text-align:center;color:#475569;font-size:.72rem;margin-top:12px}}
.owner-tabs{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}}
.owner-tab{{background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:5px 12px;border-radius:20px;font-size:11px;font-weight:600;cursor:pointer;transition:all 0.15s;white-space:nowrap}}
.owner-tab:hover{{border-color:#3DC570;color:#3DC570}}
.owner-tab.active{{background:rgba(61,197,112,0.12);border-color:#3DC570;color:#3DC570}}
.owner-tab .tab-count{{font-size:10px;opacity:0.7;margin-left:3px}}
</style></head><body>
<header>
  <div>
    <h1>PSA <span>SMC Re-engagement Tracker</span></h1>
    <div class="updated">Last updated: {date_label} · {total_accounts} accounts · Software Missing Capabilities · Since July 2025 · Salesforce live data</div>
  </div>
</header>
<div class="container">
  <div class="kpi-row">
    <div class="kpi green"><div class="kpi-label">Closed Won</div><div class="kpi-val" style="color:#3DC570">{len(closed_won)}</div><div class="kpi-sub">{fmt_money(won_mrr)} MRR recaptured</div></div>
    <div class="kpi purple"><div class="kpi-label">Active Opps</div><div class="kpi-val" style="color:#a78bfa">{len(active)}</div><div class="kpi-sub">{fmt_money(active_mrr)} in pipeline</div></div>
    <div class="kpi red"><div class="kpi-label">Lost Again</div><div class="kpi-val" style="color:#f87171">{len(lost_again)}</div></div>
    <div class="kpi cyan"><div class="kpi-label">Contacted</div><div class="kpi-val" style="color:#38bdf8">{len(contacted)}</div><div class="kpi-sub">Recent activity, no opp yet</div></div>
    <div class="kpi grey"><div class="kpi-label">Not Yet Contacted</div><div class="kpi-val">{len(not_contacted)}</div></div>
    <div class="kpi orange"><div class="kpi-label">Total MRR Pool</div><div class="kpi-val" style="color:#f5a623">{fmt_money(total_pool)}</div><div class="kpi-sub">at risk / available</div></div>
  </div>
  <div class="owner-tabs">
  {"".join(owner_tabs)}
  </div>
  <div class="search-bar">
    <input type="text" id="search" placeholder="Search accounts, owners, features, detail..." oninput="filterTable()"/>
    <span id="rowCount" style="font-size:11px;color:#475569">{total_accounts} accounts</span>
    <div class="legend">
      <span>Last Activity:</span>
      <span><span class="dot" style="background:#3DC570"></span> &lt;7d</span>
      <span><span class="dot" style="background:#f5a623"></span> &lt;30d</span>
      <span><span class="dot" style="background:#64748b"></span> 30d+</span>
    </div>
  </div>
  <table>
    <thead><tr>
      <th>Account</th><th>MRR</th><th>Opp Owner</th><th>Acct Owner</th><th>Features Needed</th>
      <th>Reason Lost Detail</th>
      <th>Re-eng Opps</th><th>Last Close Date</th><th>Last Activity</th><th>SF Stage</th><th>Status</th>
    </tr></thead>
    <tbody id="tableBody">{build_rows(accounts)}</tbody>
  </table>
  <p class="note">Contacted = account activity after the first SMC loss with no re-engagement opportunity yet · Hover Reason Lost Detail for full text · {date_label}</p>
</div>
<div class="footer">Rev.io Internal · Robin · {date_label}</div>
<script>
var activeOwner = '';
function filterByOwner(owner) {{
  activeOwner = owner;
  var tabs = document.querySelectorAll('.owner-tab');
  for (var i = 0; i < tabs.length; i++) tabs[i].classList.remove('active');
  event.currentTarget.classList.add('active');
  filterTable();
}}
function filterTable(){{
  var q=document.getElementById('search').value.toLowerCase();
  var rows=document.getElementById('tableBody').getElementsByTagName('tr');
  var count=0;
  for(var i=0;i<rows.length;i++){{
    var cells=rows[i].querySelectorAll('td');
    var oppOwner=cells[2]?cells[2].textContent.trim():'';
    var ownerMatch=!activeOwner||oppOwner===activeOwner;
    var textMatch=rows[i].textContent.toLowerCase().includes(q);
    var show=ownerMatch&&textMatch;
    rows[i].style.display=show?'':'none';
    if(show) count++;
  }}
  document.getElementById('rowCount').textContent=count+' accounts';
}}
</script>
</body></html>"""


def main() -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    base, headers = sf_auth()
    lost_query = f"""
        SELECT Id, Name, Amount, CloseDate, CreatedDate, Product_Type__c,
               Loss_Reason__c, Reason_Lost_Detail__c, AccountId,
               Account.Name, Account.Owner.Name, Account.LastActivityDate, Owner.Name
        FROM Opportunity
        WHERE StageName = 'Closed Lost'
          AND CloseDate >= {START_DATE}
          AND CloseDate <= {today}
          AND Loss_Reason__c = 'Software Missing Capabilities'
          AND Product_Type__c IN ('PSA', 'PSA 2.0')
        ORDER BY Amount DESC NULLS LAST
    """
    lost_opps = [clean_record(r) for r in sf_query_all(base, headers, lost_query)]
    by_account: dict[str, list[dict]] = defaultdict(list)
    for opp in lost_opps:
        if opp.get("AccountId"):
            by_account[opp["AccountId"]].append(opp)

    account_ids = list(by_account.keys())
    related_by_account: dict[str, list[dict]] = defaultdict(list)
    for batch in chunks(account_ids):
        id_list = ",".join(soql_quote(value) for value in batch)
        related_query = f"""
            SELECT Id, Name, Amount, CloseDate, CreatedDate, StageName, IsWon, IsClosed,
                   Product_Type__c, AccountId, Owner.Name
            FROM Opportunity
            WHERE AccountId IN ({id_list})
              AND Product_Type__c IN ('PSA', 'PSA 2.0')
            ORDER BY CreatedDate ASC
        """
        for opp in sf_query_all(base, headers, related_query):
            related_by_account[opp["AccountId"]].append(clean_record(opp))

    contact_tasks_by_account: dict[str, list[dict]] = defaultdict(list)
    for batch in chunks(account_ids):
        id_list = ",".join(soql_quote(value) for value in batch)
        task_query = f"""
            SELECT Id, AccountId, Subject, ActivityDate, CreatedDate, Status
            FROM Task
            WHERE AccountId IN ({id_list})
              AND IsDeleted = false
              AND Status = 'Completed'
              AND Subject LIKE '%contact%'
            ORDER BY ActivityDate DESC NULLS LAST, CreatedDate DESC
        """
        for task in sf_query_all(base, headers, task_query):
            contact_tasks_by_account[task["AccountId"]].append(clean_record(task))

    rows: list[dict] = []
    for account_id, losts in by_account.items():
        baseline = min(losts, key=lambda row: parse_dt(row.get("CreatedDate")))
        display = max(losts, key=lambda row: row.get("Amount") or 0)
        baseline_created = parse_dt(baseline.get("CreatedDate"))
        initial_ids = {row["Id"] for row in losts}
        later_opps = [
            opp
            for opp in related_by_account.get(account_id, [])
            if opp.get("Id") not in initial_ids and parse_dt(opp.get("CreatedDate")) > baseline_created
        ]
        won_opps = [opp for opp in later_opps if opp.get("IsWon") or opp.get("StageName") == "Closed Won"]
        open_opps = [opp for opp in later_opps if not opp.get("IsClosed") and opp.get("StageName") != "Closed Lost"]
        closed_lost_opps = [opp for opp in later_opps if opp.get("StageName") == "Closed Lost"]
        if won_opps:
            status = "Closed Won"
            stage = "Closed Won"
            current = max(won_opps, key=lambda row: parse_dt(row.get("CloseDate")))
        elif open_opps:
            status = "Active Opp"
            current = max(open_opps, key=lambda row: parse_dt(row.get("CloseDate")))
            stage = current.get("StageName") or "Open"
        elif closed_lost_opps:
            status = "Closed Lost"
            current = max(closed_lost_opps, key=lambda row: parse_dt(row.get("CloseDate")))
            stage = "Closed Lost"
        else:
            contact_tasks = [
                task
                for task in contact_tasks_by_account.get(account_id, [])
                if (task.get("ActivityDate") or task.get("CreatedDate") or "") > baseline.get("CloseDate", "")
            ]
            status = "Contacted" if contact_tasks else "Not Contacted"
            current = {}
            stage = ""

        last_activity = account_last_activity(display)
        if last_activity:
            age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(last_activity).date()).days
            recent_activity = "fresh" if age <= 7 else "warm" if age <= 30 else "old"
        else:
            recent_activity = "old"

        detail = display.get("Reason_Lost_Detail__c") or ""
        rows.append(
            {
                "account": account_name(display),
                "mrr": display.get("Amount") or 0,
                "owner": child_name(display, "Owner") or "Unassigned",
                "account_owner": account_owner(display) or "Unassigned",
                "features": features_from_detail(detail),
                "reason_lost_detail": detail,
                "reeng_count": len(later_opps),
                "last_close_date": current.get("CloseDate") or "",
                "last_activity": last_activity,
                "recent_activity": recent_activity,
                "stage": stage,
                "status": status,
                "won_mrr": sum(opp.get("Amount") or 0 for opp in won_opps),
                "active_mrr": sum(opp.get("Amount") or 0 for opp in open_opps),
            }
        )

    rows.sort(key=lambda row: (row["mrr"], row["account"]), reverse=True)
    DATAFILE.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    OUTFILE.write_text(build_html(rows), encoding="utf-8")
    print(f"Built {OUTFILE.name}: {len(rows)} accounts from {len(lost_opps)} SMC closed-lost opps")


if __name__ == "__main__":
    main()
