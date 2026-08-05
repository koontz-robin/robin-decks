#!/usr/bin/env python3
"""Build and publish the expiring competitor contracts dashboard.

Source: Salesforce report 00OPX000009VWxh2AG ("Expiring Contracts").
Rules:
- Accounts below 35 employees are included when the competitor contract date is
  within the next 6 months.
- Accounts with 35 or more employees are included when the date is within the
  next 8 months.
- Accounts expiring in October through December of the current year are also
  included.
- Accounts with open Salesforce opportunities are excluded.
- Accounts owned by Ardit Berdyna or Ryan Koontz are excluded.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests


WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
SOURCE_REPORT_ID = "00OPX000009VWxh2AG"
SOURCE_REPORT_URL = f"https://rev-io.lightning.force.com/lightning/r/Report/{SOURCE_REPORT_ID}/view"
HTML_FILE = WORKSPACE / "expiring-competitor-contracts-dashboard.html"
DATA_FILE = WORKSPACE / "expiring_competitor_contracts_dashboard.json"
PAGE_URL = "https://koontz-robin.github.io/robin-decks/expiring-competitor-contracts-dashboard.html"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
EXCLUDED_OWNERS = {"Ardit Berdyna", "Ryan Koontz"}
EMPLOYEE_THRESHOLD = 35


@dataclass(frozen=True)
class Row:
    account_id: str
    account_name: str
    owner: str
    competitor: str
    employees: int | None
    contract_end_date: date
    status: str
    segment: str
    window_months: int
    include_reason: str
    days_until: int
    source_group: str


def sf_auth() -> tuple[str, dict[str, str]]:
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
    payload = response.json()
    return payload["instance_url"], {"Authorization": f"Bearer {payload['access_token']}"}


def sf_query(base: str, headers: dict[str, str], query: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    url = f"{base}/services/data/v59.0/query"
    params = {"q": query.strip()}
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        rows.extend(payload.get("records") or [])
        if payload.get("done", True):
            return rows
        url = base + payload["nextRecordsUrl"]
        params = {}


def parse_date(value: Any, label: str | None = None) -> date | None:
    raw = str(value or "").strip()
    if raw and raw != "-":
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    label = (label or "").strip()
    for fmt in ("%m/%d/%Y", "%-m/%-d/%Y"):
        try:
            return datetime.strptime(label, fmt).date()
        except ValueError:
            continue
    return None


def parse_int(value: Any, label: str | None = None) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    raw = str(value if value not in (None, "") else label or "").strip().replace(",", "")
    if not raw or raw == "-":
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    month_lengths = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(start.day, month_lengths[month - 1]))


def window_for(employees: int | None) -> tuple[str, int]:
    if employees is None:
        return "Unknown size", 6
    if employees < EMPLOYEE_THRESHOLD:
        return f"<{EMPLOYEE_THRESHOLD} employees", 6
    return f"{EMPLOYEE_THRESHOLD}+ employees", 8


def is_october_december_current_year(contract_date: date, today: date) -> bool:
    return contract_date.year == today.year and 10 <= contract_date.month <= 12


def chunks(values: list[str], size: int = 100) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def open_opportunity_accounts(base: str, headers: dict[str, str], account_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    open_by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    clean_ids = sorted({account_id for account_id in account_ids if account_id})
    for batch in chunks(clean_ids):
        id_list = ",".join(f"'{account_id}'" for account_id in batch)
        records = sf_query(
            base,
            headers,
            f"""
            SELECT Id, Name, AccountId, StageName, Amount, CloseDate, Owner.Name
            FROM Opportunity
            WHERE IsClosed = false
              AND AccountId IN ({id_list})
            ORDER BY CloseDate ASC, Name ASC
            """,
        )
        for record in records:
            open_by_account[record.get("AccountId") or ""].append(record)
    return open_by_account


def fetch_report_rows(base: str, headers: dict[str, str], today: date) -> tuple[list[Row], dict[str, Any]]:
    response = requests.get(
        f"{base}/services/data/v59.0/analytics/reports/{SOURCE_REPORT_ID}",
        headers=headers,
        params={"includeDetails": "true"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    columns = payload.get("reportMetadata", {}).get("detailColumns") or []
    expected = ["Account.PSA_Platform__c", "USERS.NAME", "ACCOUNT.NAME", "EMPLOYEES", "DUE_DATE", "TYPE"]
    if columns[:6] != expected:
        raise RuntimeError(f"Unexpected report columns: {columns}")

    rows: list[Row] = []
    source_rows = 0
    skipped_past = 0
    skipped_outside_window = 0
    skipped_no_date = 0
    included_oct_dec = 0
    seen: set[tuple[str, date]] = set()

    for fact_key, fact in (payload.get("factMap") or {}).items():
        if not fact_key.endswith("!T"):
            continue
        for raw_row in fact.get("rows") or []:
            cells = raw_row.get("dataCells") or []
            if len(cells) < 6:
                continue
            source_rows += 1
            competitor = cells[0].get("label") or ""
            owner = cells[1].get("label") or ""
            account_name = cells[2].get("label") or ""
            account_id = cells[2].get("recordId") or cells[2].get("value") or ""
            employees = parse_int(cells[3].get("value"), cells[3].get("label"))
            contract_date = parse_date(cells[4].get("value"), cells[4].get("label"))
            status = cells[5].get("label") or ""
            if not contract_date:
                skipped_no_date += 1
                continue
            key = (account_id or account_name, contract_date)
            if key in seen:
                continue
            seen.add(key)
            days_until = (contract_date - today).days
            if days_until < 0:
                skipped_past += 1
                continue
            segment, window_months = window_for(employees)
            in_standard_window = contract_date <= add_months(today, window_months)
            in_oct_dec = is_october_december_current_year(contract_date, today)
            if not in_standard_window and not in_oct_dec:
                skipped_outside_window += 1
                continue
            include_reason = f"{window_months}-month size window"
            if in_oct_dec and not in_standard_window:
                include_reason = "Oct-Dec override"
                included_oct_dec += 1
            elif in_oct_dec:
                include_reason = f"{window_months}-month size window + Oct-Dec"
                included_oct_dec += 1
            rows.append(
                Row(
                    account_id=account_id,
                    account_name=account_name,
                    owner=owner or "Unassigned",
                    competitor=competitor or "Unknown",
                    employees=employees,
                    contract_end_date=contract_date,
                    status=status,
                    segment=segment,
                    window_months=window_months,
                    include_reason=include_reason,
                    days_until=days_until,
                    source_group=fact_key,
                )
            )

    oct_dec_start = date(today.year, 10, 1)
    oct_dec_end = date(today.year, 12, 31)
    direct_oct_dec_rows = sf_query(
        base,
        headers,
        f"""
        SELECT Id, Name, Owner.Name, PSA_Platform__c, NumberOfEmployees,
               Competitor_Contract_End_Date__c, Type
        FROM Account
        WHERE Competitor_Contract_End_Date__c >= {oct_dec_start.isoformat()}
          AND Competitor_Contract_End_Date__c <= {oct_dec_end.isoformat()}
          AND Type IN ('Cold Prospect', 'Warm Prospect')
        ORDER BY Competitor_Contract_End_Date__c ASC, Owner.Name ASC, Name ASC
        LIMIT 2000
        """,
    )
    direct_oct_dec_included = 0
    for account in direct_oct_dec_rows:
        contract_date = parse_date(account.get("Competitor_Contract_End_Date__c"))
        if not contract_date:
            continue
        key = (account.get("Id") or account.get("Name") or "", contract_date)
        if key in seen:
            continue
        seen.add(key)
        days_until = (contract_date - today).days
        if days_until < 0:
            continue
        employees = parse_int(account.get("NumberOfEmployees"))
        segment, window_months = window_for(employees)
        owner = (account.get("Owner") or {}).get("Name") or "Unassigned"
        rows.append(
            Row(
                account_id=account.get("Id") or "",
                account_name=account.get("Name") or "",
                owner=owner,
                competitor=account.get("PSA_Platform__c") or "Unknown",
                employees=employees,
                contract_end_date=contract_date,
                status=account.get("Type") or "",
                segment=segment,
                window_months=window_months,
                include_reason="Oct-Dec override",
                days_until=days_until,
                source_group="direct_oct_dec_account_query",
            )
        )
        direct_oct_dec_included += 1

    open_opps_by_account = open_opportunity_accounts(base, headers, [row.account_id for row in rows])
    rows_before_open_opp_filter = len(rows)
    rows = [row for row in rows if row.account_id not in open_opps_by_account]
    excluded_open_opp_rows = rows_before_open_opp_filter - len(rows)
    excluded_open_opp_accounts = len(open_opps_by_account)
    rows_before_owner_filter = len(rows)
    rows = [row for row in rows if row.owner not in EXCLUDED_OWNERS]
    excluded_owner_rows = rows_before_owner_filter - len(rows)

    metadata = {
        "source_report_id": SOURCE_REPORT_ID,
        "source_report_url": SOURCE_REPORT_URL,
        "source_rows": source_rows,
        "included_rows": len(rows),
        "skipped_no_date": skipped_no_date,
        "skipped_past": skipped_past,
        "skipped_outside_window": skipped_outside_window,
        "included_oct_dec": included_oct_dec,
        "direct_oct_dec_source_rows": len(direct_oct_dec_rows),
        "direct_oct_dec_included": direct_oct_dec_included,
        "excluded_open_opp_rows": excluded_open_opp_rows,
        "excluded_open_opp_accounts": excluded_open_opp_accounts,
        "excluded_owner_rows": excluded_owner_rows,
        "excluded_owners": sorted(EXCLUDED_OWNERS),
        "open_opportunity_accounts": {
            account_id: [
                {
                    "id": opp.get("Id"),
                    "name": opp.get("Name"),
                    "stage": opp.get("StageName"),
                    "amount": opp.get("Amount"),
                    "close_date": opp.get("CloseDate"),
                    "owner": (opp.get("Owner") or {}).get("Name"),
                }
                for opp in opps
            ]
            for account_id, opps in sorted(open_opps_by_account.items())
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of": today.isoformat(),
        "report_name": payload.get("reportName") or payload.get("attributes", {}).get("reportName") or "Expiring Contracts",
    }
    return rows, metadata


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def fmt_date(value: date) -> str:
    return value.strftime("%b %-d, %Y")


def fmt_int(value: int | None) -> str:
    return "Unknown" if value is None else f"{value:,}"


def urgency(days: int) -> str:
    if days <= 30:
        return "urgent"
    if days <= 90:
        return "soon"
    if days <= 180:
        return "watch"
    return "future"


def urgency_label(days: int) -> str:
    if days == 0:
        return '<span class="badge urgent">Today</span>'
    if days <= 30:
        return f'<span class="badge urgent">{days}d</span>'
    if days <= 90:
        return f'<span class="badge soon">{days}d</span>'
    if days <= 180:
        return f'<span class="badge watch">{days}d</span>'
    return f'<span class="badge future">{days}d</span>'


def segment_class(segment: str) -> str:
    if segment == f"<{EMPLOYEE_THRESHOLD} employees":
        return "small-segment"
    if segment == f"{EMPLOYEE_THRESHOLD}+ employees":
        return "large-segment"
    return "unknown-segment"


def row_to_dict(row: Row) -> dict[str, Any]:
    return {
        "account_id": row.account_id,
        "account_name": row.account_name,
        "owner": row.owner,
        "competitor": row.competitor,
        "employees": row.employees,
        "contract_end_date": row.contract_end_date.isoformat(),
        "status": row.status,
        "segment": row.segment,
        "window_months": row.window_months,
        "include_reason": row.include_reason,
        "days_until": row.days_until,
    }


def owner_section(owner: str, owner_rows: list[Row]) -> str:
    owner_rows = sorted(owner_rows, key=lambda row: (row.days_until, row.account_name))
    urgent_count = sum(1 for row in owner_rows if row.days_until <= 30)
    soon_count = sum(1 for row in owner_rows if 30 < row.days_until <= 90)
    small_count = sum(1 for row in owner_rows if row.segment == f"<{EMPLOYEE_THRESHOLD} employees")
    large_count = sum(1 for row in owner_rows if row.segment == f"{EMPLOYEE_THRESHOLD}+ employees")
    section_id = re.sub(r"[^a-z0-9]+", "-", owner.lower()).strip("-") or "unassigned"
    rows_html = []
    for row in owner_rows:
        link = f"https://rev-io.my.salesforce.com/{esc(row.account_id)}" if row.account_id else "#"
        size_note = f"{row.segment} / {row.include_reason}"
        rows_html.append(
            f"""
          <tr class="row-{urgency(row.days_until)}">
            <td>
              <a class="account-link" href="{link}" target="_blank">{esc(row.account_name)}</a>
              <div class="subtext">{esc(row.status or 'No status')}</div>
            </td>
            <td>{esc(row.competitor)}</td>
            <td>{fmt_int(row.employees)}</td>
            <td><span class="segment {segment_class(row.segment)}">{esc(size_note)}</span></td>
            <td>{fmt_date(row.contract_end_date)}</td>
            <td>{urgency_label(row.days_until)}</td>
          </tr>"""
        )
    return f"""
    <section class="owner-section" id="owner-{section_id}">
      <div class="owner-header">
        <div>
          <h2>{esc(owner)}</h2>
          <p>{len(owner_rows)} accounts · {small_count} below {EMPLOYEE_THRESHOLD} · {large_count} {EMPLOYEE_THRESHOLD}+</p>
        </div>
        <div class="owner-pills">
          <span>{urgent_count} next 30d</span>
          <span>{soon_count} next 90d</span>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Account</th>
              <th>Competitor</th>
              <th>Employees</th>
              <th>Rule</th>
              <th>Contract End</th>
              <th>Timing</th>
            </tr>
          </thead>
          <tbody>{''.join(rows_html)}</tbody>
        </table>
      </div>
    </section>"""


def render_html(rows: list[Row], metadata: dict[str, Any]) -> str:
    rows = sorted(rows, key=lambda row: (row.days_until, row.owner, row.account_name))
    by_owner: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        by_owner[row.owner].append(row)

    competitor_counts = Counter(row.competitor for row in rows)
    segment_counts = Counter(row.segment for row in rows)
    urgent_count = sum(1 for row in rows if row.days_until <= 30)
    soon_count = sum(1 for row in rows if 30 < row.days_until <= 90)
    small_count = segment_counts[f"<{EMPLOYEE_THRESHOLD} employees"]
    large_count = segment_counts[f"{EMPLOYEE_THRESHOLD}+ employees"]
    unknown_count = segment_counts["Unknown size"]
    oct_dec_count = metadata.get("included_oct_dec", 0) + metadata.get("direct_oct_dec_included", 0)
    top_competitors = competitor_counts.most_common(8)

    owners_sorted = sorted(
        by_owner,
        key=lambda owner: (
            min(row.days_until for row in by_owner[owner]),
            owner,
        ),
    )
    nav = " ".join(
        f'<a href="#owner-{re.sub(r"[^a-z0-9]+", "-", owner.lower()).strip("-") or "unassigned"}">{esc(owner.split()[0])}</a>'
        for owner in owners_sorted
    )
    sections = "".join(owner_section(owner, by_owner[owner]) for owner in owners_sorted)
    competitor_bars = "".join(
        f'<div class="bar-row"><span>{esc(name)}</span><b>{count}</b><i style="width:{(count / max(1, top_competitors[0][1])) * 100:.1f}%"></i></div>'
        for name, count in top_competitors
    )

    generated = datetime.now(timezone.utc).strftime("%b %-d, %Y %-I:%M %p UTC")
    as_of = date.fromisoformat(metadata["as_of"]).strftime("%b %-d, %Y")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Expiring Competitor Contracts</title>
<style>
:root {{
  --bg:#f6f7fb;
  --ink:#1d2433;
  --muted:#657086;
  --line:#d9deea;
  --panel:#ffffff;
  --panel2:#eef2f8;
  --blue:#2854a3;
  --cyan:#177e89;
  --gold:#b7791f;
  --red:#b42318;
  --green:#2f7d32;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size:14px; }}
a {{ color:var(--blue); }}
.shell {{ max-width:1480px; margin:0 auto; padding:22px; }}
header {{ display:grid; grid-template-columns:1.2fr .8fr; gap:18px; align-items:end; padding:22px 0 18px; border-bottom:1px solid var(--line); }}
.eyebrow {{ color:var(--cyan); text-transform:uppercase; font-size:12px; font-weight:800; letter-spacing:.08em; }}
h1 {{ margin:4px 0 8px; font-size:34px; line-height:1.06; letter-spacing:0; }}
.lede {{ max-width:840px; margin:0; color:var(--muted); font-size:15px; line-height:1.45; }}
.meta {{ text-align:right; color:var(--muted); font-size:12px; line-height:1.5; }}
.kpis {{ display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:10px; margin:18px 0; }}
.kpi {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }}
.kpi span {{ display:block; color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }}
.kpi b {{ display:block; font-size:28px; margin-top:4px; }}
.grid {{ display:grid; grid-template-columns:340px 1fr; gap:16px; align-items:start; }}
.side {{ position:sticky; top:12px; display:grid; gap:12px; }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }}
.panel h2 {{ margin:0 0 10px; font-size:15px; }}
.rule-list {{ display:grid; gap:8px; color:var(--muted); }}
.rule-list b {{ color:var(--ink); }}
.nav {{ display:flex; flex-wrap:wrap; gap:6px; }}
.nav a {{ text-decoration:none; border:1px solid var(--line); background:var(--panel2); color:var(--ink); border-radius:999px; padding:4px 9px; font-size:12px; font-weight:700; }}
.bar-row {{ position:relative; display:grid; grid-template-columns:1fr auto; gap:8px; padding:7px 0; border-bottom:1px solid #edf0f6; overflow:hidden; }}
.bar-row:last-child {{ border-bottom:0; }}
.bar-row span,.bar-row b {{ position:relative; z-index:1; }}
.bar-row i {{ position:absolute; left:0; bottom:4px; height:6px; border-radius:99px; background:rgba(23,126,137,.18); }}
.main {{ display:grid; gap:14px; }}
.owner-section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
.owner-header {{ display:flex; align-items:center; justify-content:space-between; gap:12px; padding:13px 15px; background:linear-gradient(180deg,#fff,#f7f9fd); border-bottom:1px solid var(--line); }}
.owner-header h2 {{ margin:0; font-size:18px; }}
.owner-header p {{ margin:2px 0 0; color:var(--muted); font-size:12px; }}
.owner-pills {{ display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; }}
.owner-pills span {{ border:1px solid var(--line); border-radius:99px; padding:3px 8px; color:var(--muted); font-size:12px; font-weight:700; background:#fff; }}
.table-wrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; min-width:880px; }}
th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); padding:9px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }}
td {{ padding:10px 12px; border-bottom:1px solid #edf0f6; vertical-align:middle; }}
tbody tr:last-child td {{ border-bottom:0; }}
.account-link {{ font-weight:800; text-decoration:none; }}
.subtext {{ color:var(--muted); font-size:12px; margin-top:2px; }}
.segment,.badge {{ display:inline-block; border-radius:99px; padding:3px 8px; font-size:12px; font-weight:800; white-space:nowrap; }}
.segment {{ background:#eef2f8; color:#334155; border:1px solid #d7deeb; }}
.small-segment {{ background:#e9f7f2; color:#116149; border-color:#b7e4d4; }}
.large-segment {{ background:#e9eefb; color:#24488f; border-color:#c3d0f3; }}
.unknown-segment {{ background:#fff7ed; color:#9a3412; border-color:#fed7aa; }}
.urgent {{ background:#fee4e2; color:var(--red); }}
.soon {{ background:#fef0c7; color:var(--gold); }}
.watch {{ background:#dcfae6; color:var(--green); }}
.future {{ background:#e0f2fe; color:#075985; }}
.row-urgent {{ box-shadow:inset 4px 0 0 var(--red); }}
.row-soon {{ box-shadow:inset 4px 0 0 var(--gold); }}
.row-watch {{ box-shadow:inset 4px 0 0 var(--green); }}
.row-future {{ box-shadow:inset 4px 0 0 #0284c7; }}
footer {{ color:var(--muted); font-size:12px; padding:18px 0 6px; }}
@media (max-width:980px) {{
  .shell {{ padding:14px; }}
  header,.grid {{ grid-template-columns:1fr; }}
  .meta {{ text-align:left; }}
  .kpis {{ grid-template-columns:repeat(2, minmax(0, 1fr)); }}
  .side {{ position:static; }}
}}
</style>
</head>
<body>
<div class="shell">
  <header>
    <div>
      <div class="eyebrow">Salesforce Contract Timing</div>
      <h1>Expiring Competitor Contracts</h1>
      <p class="lede">Accounts from Salesforce report {esc(SOURCE_REPORT_ID)} with competitor contracts inside the pursuit window, no open Salesforce opportunities, and not assigned to Ardit or Ryan: below {EMPLOYEE_THRESHOLD} employees gets a 6-month window; {EMPLOYEE_THRESHOLD}+ employees gets an 8-month window; October-December expirations are included as an additional year-end planning view. Sorted by owner and earliest contract end date.</p>
    </div>
    <div class="meta">
      Generated {esc(generated)}<br>
      As of {esc(as_of)}<br>
      <a href="{esc(SOURCE_REPORT_URL)}">Source Salesforce report</a>
    </div>
  </header>

  <section class="kpis">
    <div class="kpi"><span>Accounts In Window</span><b>{len(rows)}</b></div>
    <div class="kpi"><span>Next 30 Days</span><b>{urgent_count}</b></div>
    <div class="kpi"><span>31-90 Days</span><b>{soon_count}</b></div>
    <div class="kpi"><span>&lt;{EMPLOYEE_THRESHOLD} Employees</span><b>{small_count}</b></div>
    <div class="kpi"><span>Oct-Dec Expirations</span><b>{oct_dec_count}</b></div>
  </section>

  <div class="grid">
    <aside class="side">
      <section class="panel">
        <h2>Rules</h2>
        <div class="rule-list">
          <div><b>&lt;{EMPLOYEE_THRESHOLD} employees:</b> contract end date from today through {esc(fmt_date(add_months(date.fromisoformat(metadata["as_of"]), 6)))}</div>
          <div><b>{EMPLOYEE_THRESHOLD}+ employees:</b> contract end date from today through {esc(fmt_date(add_months(date.fromisoformat(metadata["as_of"]), 8)))}</div>
          <div><b>October-December:</b> included for the current year regardless of employee-size window. Current Oct-Dec count: {oct_dec_count}</div>
          <div><b>Open opportunities:</b> accounts with open Salesforce opportunities are excluded. Current exclusions: {metadata["excluded_open_opp_rows"]} rows across {metadata["excluded_open_opp_accounts"]} accounts</div>
          <div><b>Owner exclusions:</b> Ardit Berdyna and Ryan Koontz are excluded. Current excluded count: {metadata["excluded_owner_rows"]}</div>
          <div><b>Unknown employees:</b> included on the 6-month rule and counted separately. Current unknown count: {unknown_count}</div>
        </div>
      </section>
      <section class="panel">
        <h2>Top Competitors</h2>
        {competitor_bars or '<p class="subtext">No rows in window.</p>'}
      </section>
      <section class="panel">
        <h2>Owners</h2>
        <div class="nav">{nav}</div>
      </section>
    </aside>
    <main class="main">
      {sections or '<section class="owner-section"><div class="owner-header"><div><h2>No accounts in window</h2><p>The report returned no matching contract dates for the current rules.</p></div></div></section>'}
    </main>
  </div>
  <footer>
    Source report rows: {metadata["source_rows"]}. Direct Oct-Dec rows: {metadata["direct_oct_dec_source_rows"]}. Excluded with open opportunities: {metadata["excluded_open_opp_rows"]} rows / {metadata["excluded_open_opp_accounts"]} accounts. Excluded by owner: {metadata["excluded_owner_rows"]}. Skipped outside window: {metadata["skipped_outside_window"]}. Skipped past dates: {metadata["skipped_past"]}. Skipped missing dates: {metadata["skipped_no_date"]}.
  </footer>
</div>
</body>
</html>"""


def run(cmd: list[str], cwd: Path = WORKSPACE, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode:
        raise RuntimeError(f"{' '.join(cmd)} exited {result.returncode}")
    return result.stdout


def publish(files: list[Path]) -> str | None:
    tmp_parent = Path(tempfile.mkdtemp(prefix="expiring-contracts-publish."))
    worktree = tmp_parent / "worktree"
    env = os.environ.copy()
    ssh_key = Path("/home/openclaw/.openclaw/ssh/id_ed25519")
    if ssh_key.exists():
        env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key} -o StrictHostKeyChecking=no"
    try:
        run(["git", "fetch", "robin-decks", "master"], env=env)
        run(["git", "worktree", "add", str(worktree), "FETCH_HEAD"], env=env)
        for file in files:
            shutil.copy2(file, worktree / file.name)
        run(["git", "config", "user.name", "Robin"], cwd=worktree, env=env)
        run(["git", "config", "user.email", "robin@rev.io"], cwd=worktree, env=env)
        run(["git", "add", *[file.name for file in files]], cwd=worktree, env=env)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree, env=env)
        if diff.returncode == 0:
            print("No publish changes")
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        run(["git", "commit", "-m", f"refresh expiring competitor contracts dashboard ({stamp})"], cwd=worktree, env=env)
        run(["git", "push", "robin-decks", "HEAD:master"], cwd=worktree, env=env)
        return run(["git", "rev-parse", "--short", "HEAD"], cwd=worktree, env=env).strip()
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=WORKSPACE, env=env, check=False)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main() -> int:
    today = date.today()
    base, headers = sf_auth()
    rows, metadata = fetch_report_rows(base, headers, today)
    payload = {
        "metadata": metadata,
        "rows": [row_to_dict(row) for row in sorted(rows, key=lambda row: (row.days_until, row.owner, row.account_name))],
    }
    DATA_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    HTML_FILE.write_text(render_html(rows, metadata), encoding="utf-8")
    commit = publish([HTML_FILE, DATA_FILE])
    print(
        "Expiring competitor contracts dashboard refreshed: "
        f"{metadata['included_rows']} included from {metadata['source_rows']} source rows; "
        f"{metadata['direct_oct_dec_included']} direct Oct-Dec additions; "
        f"{metadata['excluded_open_opp_rows']} rows / {metadata['excluded_open_opp_accounts']} accounts excluded with open opps; "
        f"{metadata['excluded_owner_rows']} excluded by owner; "
        f"{metadata['skipped_outside_window']} outside window; {metadata['skipped_past']} past."
    )
    print(f"Dashboard: {PAGE_URL}")
    if commit:
        print(f"Published commit: {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
