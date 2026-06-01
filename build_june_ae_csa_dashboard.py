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
TEAM_TARGET = 275
PRODUCT_GOALS = [
    ("PSA", 200),
    ("Billing/Odin", 40),
    ("Payments", 25),
    ("Cyberprotect", 10),
]

KNOWN_AES = {
    "Andy Whisenant",
    "Connor Flynn",
    "Husam Zalmiyar",
    "Jake Borah",
    "Jake Mitchell",
    "Jamie Butler",
    "Jaylin Bender",
    "Patrick Davies",
}
KNOWN_CSAS = {"Ingrid Beard", "Justin Lee"}
NAME_ALIASES = {
    "Andrew Whisenant": "Andy Whisenant",
}
EXCLUDED_REPS = {
    "Davis" + " Herndon",
}
ROLE_GROUPS = {
    "SDRs": "SDR",
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
        name = normalize_name(user.get("Name") or "")
        role = (user.get("UserRole") or {}).get("Name") or ""
        if name and role in ROLE_GROUPS and name not in EXCLUDED_REPS:
            members[name] = ROLE_GROUPS[role]
    for name in KNOWN_AES:
        if name not in EXCLUDED_REPS:
            members.setdefault(name, "AE")
    for name in KNOWN_CSAS:
        if name not in EXCLUDED_REPS:
            members.setdefault(name, "CSA")
    return members


def normalize_name(name):
    return NAME_ALIASES.get((name or "").strip(), (name or "").strip())


def fetch_opportunities(base, headers):
    query = f"""
        SELECT Id, Name, Amount, StageName, Product_Type__c, CreatedDate,
               CloseDate, Account.Name, Owner.Name, Owner.UserRole.Name,
               CreatedBy.Name, SDR_Influence__c
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
                "Owner": normalize_name(owner.get("Name") or "Unknown"),
                "OwnerRole": owner_role,
                "CreatedBy": normalize_name(created_by.get("Name") or ""),
                "SDR_Influence__c": record.get("SDR_Influence__c") or "",
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


def product_bucket(product):
    value = (product or "").strip().lower()
    if "psa" in value:
        return "PSA"
    if "billing" in value or "odin" in value:
        return "Billing/Odin"
    if "payment" in value:
        return "Payments"
    if "cyber" in value:
        return "Cyberprotect"
    return "Other"


def initials(name):
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "?"


def opp_detail_rows(opps, empty_text):
    if not opps:
        return f'<div class="opp-empty">{escape(empty_text)}</div>'
    rows = []
    for opp in sorted(opps, key=lambda o: (o.get("CreatedDateET", ""), o.get("Name", ""))):
        rows.append(
            f"""
            <div class="opp-detail-row">
              <div>
                <div class="opp-name">{escape(opp.get('Name') or 'Unnamed Opportunity')}</div>
                <div class="opp-meta">{escape(opp.get('Account') or 'No account')} · {escape(opp.get('Product_Type__c') or 'Unspecified')}</div>
              </div>
              <div class="opp-stage">{escape(opp.get('StageName') or 'No stage')}</div>
              <div class="opp-amount">{money(opp.get('Amount') or 0)}</div>
            </div>"""
        )
    return "\n".join(rows)


def build_rows(by_rep, rep_groups, weekly_totals, opps_by_rep):
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
            <tr class="summary-row">
              <td class="rep-cell first-cell">
                <button class="expand-btn" aria-label="Expand {escape(rep)} opportunity details">+</button>
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
        rows.append(
            f"""
            <tr class="details-row">
              <td colspan="7">
                <div class="opp-detail-panel">
                  <div class="opp-detail-title">{escape(rep)} · Opportunities Created</div>
                  {opp_detail_rows(opps_by_rep.get(rep, []), 'No opportunities created in June.')}
                </div>
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


def build_product_goal_cards(product_totals):
    cards = []
    for label, goal in PRODUCT_GOALS:
        metrics = product_totals.get(label, {"count": 0, "amount": 0})
        count = metrics["count"]
        pct = min(count / goal * 100, 100) if goal else 0
        remaining = max(goal - count, 0)
        cards.append(
            f"""
            <section class="product-goal-card">
              <div class="product-goal-top">
                <div>
                  <div class="product-goal-label">{escape(label)}</div>
                  <div class="product-goal-mrr">{money(metrics['amount'])} MRR</div>
                </div>
                <div class="product-goal-count">{count}<span> / {goal}</span></div>
              </div>
              <div class="product-goal-track"><span style="width:{pct:.1f}%"></span></div>
              <div class="product-goal-meta"><span>{pct:.1f}% to goal</span><span>{remaining} remaining</span></div>
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


def clean_sdr_name(value):
    name = normalize_name(value)
    if not name or name.lower() == "none":
        return ""
    return name


def build_sdr_rows(by_sdr, sdr_weekly_totals, sdr_opps_by_rep):
    rows = []
    ordered_sdrs = sorted(
        by_sdr,
        key=lambda sdr: (-sum(v["amount"] for v in by_sdr[sdr].values()), sdr),
    )
    for sdr in ordered_sdrs:
        total_count = sum(v["count"] for v in by_sdr[sdr].values())
        total_amount = sum(v["amount"] for v in by_sdr[sdr].values())
        cells = []
        for week_id, label, _, _ in WEEKS:
            metrics = by_sdr[sdr].get(week_id, {"count": 0, "amount": 0})
            pct = (
                (metrics["amount"] / sdr_weekly_totals[week_id]["amount"] * 100)
                if sdr_weekly_totals[week_id]["amount"]
                else 0
            )
            cells.append(
                f"""
                <td class="week-cell">
                  <div class="cell-count">{metrics['count']}</div>
                  <div class="cell-mrr">{money(metrics['amount'])}</div>
                  <div class="cell-bar sdr"><span style="width:{min(pct, 100):.1f}%"></span></div>
                </td>"""
            )
        rows.append(
            f"""
            <tr class="summary-row">
              <td class="rep-cell first-cell">
                <button class="expand-btn" aria-label="Expand {escape(sdr)} opportunity details">+</button>
                <div class="avatar sdr">{escape(initials(sdr))}</div>
                <div>
                  <div class="rep-name">{escape(sdr)}</div>
                  <div class="rep-group sdr">SDR</div>
                </div>
              </td>
              {''.join(cells)}
              <td class="total-cell">
                <div class="total-count">{total_count}</div>
                <div class="total-mrr">{money(total_amount)}</div>
              </td>
            </tr>"""
        )
        rows.append(
            f"""
            <tr class="details-row">
              <td colspan="7">
                <div class="opp-detail-panel sdr">
                  <div class="opp-detail-title">{escape(sdr)} · Influenced Opportunities</div>
                  {opp_detail_rows(sdr_opps_by_rep.get(sdr, []), 'No SDR-influenced opportunities created in June.')}
                </div>
              </td>
            </tr>"""
        )
    if not rows:
        return '<tr><td colspan="7" class="empty-table">No SDR-influenced opportunities created in June.</td></tr>'
    return "\n".join(rows)


def build_html(opps, members):
    generated_at = datetime.now(ET)
    enriched = []
    by_rep = defaultdict(lambda: defaultdict(lambda: {"count": 0, "amount": 0}))
    rep_groups = {}
    weekly_totals = {week_id: {"count": 0, "amount": 0} for week_id, _, _, _ in WEEKS}
    product_totals = {label: {"count": 0, "amount": 0} for label, _ in PRODUCT_GOALS}
    group_totals = {"AE": {"count": 0, "amount": 0}, "CSA": {"count": 0, "amount": 0}}
    opps_by_week_rep = defaultdict(lambda: defaultdict(list))
    opps_by_rep = defaultdict(list)
    by_sdr = defaultdict(lambda: defaultdict(lambda: {"count": 0, "amount": 0}))
    sdr_weekly_totals = {week_id: {"count": 0, "amount": 0} for week_id, _, _, _ in WEEKS}
    sdr_enriched = []
    sdr_opps_by_rep = defaultdict(list)

    for rep, group in members.items():
        if group in {"AE", "CSA"}:
            rep_groups[rep] = group
            _ = by_rep[rep]
        elif group == "SDR":
            _ = by_sdr[rep]

    for opp in opps:
        date_text = created_date_et(opp["CreatedDate"])
        week_id = week_for_date(date_text)
        sdr = clean_sdr_name(opp.get("SDR_Influence__c"))
        if week_id and sdr:
            sdr_opp = {**opp, "CreatedDateET": date_text, "Week": week_id, "SDR": sdr}
            sdr_enriched.append(sdr_opp)
            by_sdr[sdr][week_id]["count"] += 1
            by_sdr[sdr][week_id]["amount"] += opp["Amount"]
            sdr_weekly_totals[week_id]["count"] += 1
            sdr_weekly_totals[week_id]["amount"] += opp["Amount"]
            sdr_opps_by_rep[sdr].append(sdr_opp)

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
        bucket = product_bucket(opp.get("Product_Type__c"))
        if bucket in product_totals:
            product_totals[bucket]["count"] += 1
            product_totals[bucket]["amount"] += opp["Amount"]
        group_totals[group]["count"] += 1
        group_totals[group]["amount"] += opp["Amount"]
        opps_by_week_rep[week_id][rep].append(opp)
        opps_by_rep[rep].append(opp)

    DATA_FILE.write_text(json.dumps({"ae_csa": enriched, "sdr_influenced": sdr_enriched}, indent=2), encoding="utf-8")

    total_count = len(enriched)
    total_mrr = sum(opp["Amount"] for opp in enriched)
    sdr_total_count = len(sdr_enriched)
    sdr_total_mrr = sum(opp["Amount"] for opp in sdr_enriched)
    target_pct = min(total_count / TEAM_TARGET * 100, 100) if TEAM_TARGET else 0
    remaining = max(TEAM_TARGET - total_count, 0)
    table_headers = "".join(
        f'<th><div>{escape(week_id)}</div><span>{escape(label)}</span></th>' for week_id, label, _, _ in WEEKS
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sales Opportunities Created</title>
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
.target-card {{ grid-column:span 2; }}
.target-top {{ display:flex; align-items:baseline; justify-content:space-between; gap:12px; }}
.target-value {{ font-size:34px; font-weight:850; }}
.target-value span {{ color:var(--muted); font-size:18px; }}
.target-track {{ height:12px; background:#edf2f7; border-radius:999px; overflow:hidden; margin-top:14px; }}
.target-track span {{ display:block; height:100%; background:linear-gradient(90deg,var(--green),var(--blue)); border-radius:999px; }}
.target-meta {{ display:flex; justify-content:space-between; color:var(--muted); font-size:12px; font-weight:750; margin-top:8px; }}
.product-goals {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:-4px 0 18px; }}
.product-goal-card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); padding:15px; }}
.product-goal-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }}
.product-goal-label {{ color:var(--muted); font-size:11px; font-weight:850; text-transform:uppercase; letter-spacing:.08em; }}
.product-goal-mrr {{ color:var(--green); font-size:12px; font-weight:800; margin-top:6px; }}
.product-goal-count {{ font-size:26px; font-weight:850; text-align:right; }}
.product-goal-count span {{ color:var(--muted); font-size:14px; }}
.product-goal-track {{ height:8px; background:#edf2f7; border-radius:999px; overflow:hidden; margin-top:13px; }}
.product-goal-track span {{ display:block; height:100%; background:linear-gradient(90deg,var(--blue),var(--green)); border-radius:999px; }}
.product-goal-meta {{ display:flex; justify-content:space-between; color:var(--muted); font-size:11px; font-weight:750; margin-top:7px; }}
.weeks {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin-bottom:18px; }}
.week-card {{ padding:16px; min-height:134px; }}
.week-name {{ color:var(--blue); font-weight:850; font-size:13px; text-transform:uppercase; letter-spacing:.08em; }}
.week-range {{ color:var(--muted); font-size:12px; margin-top:3px; }}
.week-count {{ margin-top:14px; font-size:30px; font-weight:850; }}
.week-mrr {{ color:var(--green); font-size:14px; font-weight:800; }}
.week-track, .cell-bar {{ height:6px; background:#edf2f7; border-radius:999px; overflow:hidden; margin-top:12px; }}
.week-track span, .cell-bar span {{ display:block; height:100%; background:linear-gradient(90deg,var(--green),var(--teal)); border-radius:999px; }}
.cell-bar.sdr span {{ background:linear-gradient(90deg,#f59e0b,#2563eb); }}
.table-wrap {{ overflow:auto; }}
.table-wrap.sdr-section {{ margin-top:18px; }}
table {{ width:100%; border-collapse:separate; border-spacing:0; min-width:1080px; }}
th, td {{ border-bottom:1px solid var(--line); padding:13px 14px; vertical-align:middle; }}
th {{ position:sticky; top:0; background:#fbfdff; color:var(--muted); font-size:12px; font-weight:850; text-align:right; text-transform:uppercase; letter-spacing:.06em; z-index:1; }}
th:first-child {{ text-align:left; left:0; z-index:2; }}
th span {{ display:block; font-weight:700; text-transform:none; letter-spacing:0; margin-top:2px; }}
td:first-child {{ position:sticky; left:0; background:var(--panel); z-index:1; }}
tr:last-child td {{ border-bottom:0; }}
.summary-row {{ cursor:pointer; }}
.summary-row:hover td {{ background:#fbfdff; }}
.details-row {{ display:none; }}
.details-row.open {{ display:table-row; }}
.details-row td:first-child {{ position:static; background:#fbfdff; }}
.rep-cell {{ display:flex; align-items:center; gap:10px; min-width:230px; }}
.first-cell {{ min-width:265px; }}
.expand-btn {{ width:24px; height:24px; flex:0 0 24px; border:1px solid var(--line); border-radius:6px; background:#fff; color:var(--muted); font-weight:900; line-height:1; cursor:pointer; }}
.summary-row.open .expand-btn {{ color:var(--green); border-color:#bbf7d0; background:#f0fdf4; }}
.avatar {{ width:34px; height:34px; border-radius:8px; display:grid; place-items:center; background:#e7f7ef; color:#087344; font-size:12px; font-weight:850; }}
.avatar.sdr {{ background:#fff7ed; color:#9a3412; }}
.rep-name {{ font-weight:800; }}
.rep-group {{ display:inline-flex; margin-top:4px; padding:2px 7px; border-radius:999px; font-size:10px; font-weight:850; letter-spacing:.06em; }}
.rep-group.ae {{ color:#1d4ed8; background:#dbeafe; }}
.rep-group.csa {{ color:#0f766e; background:#ccfbf1; }}
.rep-group.sdr {{ color:#9a3412; background:#ffedd5; }}
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
.section-title {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin:26px 0 10px; }}
.section-title h2 {{ margin:0; font-size:20px; }}
.section-title p {{ margin:4px 0 0; color:var(--muted); font-size:13px; }}
.section-totals {{ color:var(--muted); font-size:13px; font-weight:800; text-align:right; white-space:nowrap; }}
.section-totals strong {{ color:var(--ink); }}
.empty-table {{ color:var(--muted); font-size:13px; padding:22px; text-align:left; }}
.opp-detail-panel {{ padding:14px 18px 16px 58px; background:#fbfdff; }}
.opp-detail-panel.sdr {{ background:#fffaf3; }}
.opp-detail-title {{ font-size:12px; font-weight:850; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; margin-bottom:10px; }}
.opp-detail-row {{ display:grid; grid-template-columns:minmax(220px,1fr) minmax(170px,220px) 90px; gap:14px; align-items:center; padding:10px 0; border-top:1px solid #edf2f7; }}
.opp-name {{ font-weight:850; color:var(--ink); }}
.opp-meta {{ color:var(--muted); font-size:12px; margin-top:2px; }}
.opp-stage {{ justify-self:start; color:#334155; background:#eef2ff; border:1px solid #dbe4ff; border-radius:999px; padding:4px 9px; font-size:11px; font-weight:850; }}
.opp-amount {{ text-align:right; color:var(--green); font-weight:850; }}
.opp-empty {{ color:var(--muted); font-size:13px; padding:10px 0; border-top:1px solid #edf2f7; }}
@media (max-width:1100px) {{
  .shell {{ padding:18px; }}
  .topbar {{ display:block; }}
  .stamp {{ text-align:left; margin-top:12px; }}
  .kpis {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .target-card {{ grid-column:span 2; }}
  .product-goals {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .weeks, .details {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .section-title {{ display:block; }}
  .section-totals {{ text-align:left; margin-top:8px; }}
}}
@media (max-width:640px) {{
  h1 {{ font-size:26px; }}
  .kpis, .product-goals, .weeks, .details {{ grid-template-columns:1fr; }}
  .target-card {{ grid-column:span 1; }}
  .opp-detail-row {{ grid-template-columns:1fr; gap:6px; }}
  .opp-amount {{ text-align:left; }}
}}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div>
      <div class="eyebrow">June 2026 Pipeline Creation</div>
      <h1>Sales Opportunities Created</h1>
      <div class="subtitle">Quantity and MRR by owner, split across all five June calendar weeks.</div>
    </div>
    <div class="stamp">
      Refreshed {generated_at.strftime('%b %-d, %Y %-I:%M %p ET')}<br>
      Salesforce CreatedDate, Owner, Amount
    </div>
  </header>

  <section class="kpis">
    <div class="kpi target-card">
      <div class="kpi-label">Team Target Pace</div>
      <div class="target-top">
        <div class="target-value">{total_count}<span> / {TEAM_TARGET}</span></div>
        <div class="kpi-sub">{target_pct:.1f}% to target</div>
      </div>
      <div class="target-track"><span style="width:{target_pct:.1f}%"></span></div>
      <div class="target-meta"><span>{remaining} opps remaining</span><span>June target</span></div>
    </div>
    <div class="kpi"><div class="kpi-label">SDR Opportunities Influenced</div><div class="kpi-val">{sdr_total_count}</div><div class="kpi-sub">{money(sdr_total_mrr)} MRR influenced</div></div>
    <div class="kpi"><div class="kpi-label">Total MRR</div><div class="kpi-val">{money(total_mrr)}</div><div class="kpi-sub">Sum of Salesforce Amount</div></div>
    <div class="kpi"><div class="kpi-label">AE Created</div><div class="kpi-val">{group_totals['AE']['count']}</div><div class="kpi-sub">{money(group_totals['AE']['amount'])} MRR</div></div>
    <div class="kpi"><div class="kpi-label">CSA Created</div><div class="kpi-val">{group_totals['CSA']['count']}</div><div class="kpi-sub">{money(group_totals['CSA']['amount'])} MRR</div></div>
  </section>

  <section class="product-goals">
    {build_product_goal_cards(product_totals)}
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
        {build_rows(by_rep, rep_groups, weekly_totals, opps_by_rep)}
      </tbody>
    </table>
  </section>

  <section class="details">
    {build_rep_breakdown(opps_by_week_rep)}
  </section>

  <section class="section-title">
    <div>
      <h2>SDR Influenced Opportunities</h2>
      <p>June-created opportunities with SDR Influence populated, grouped by SDR.</p>
    </div>
    <div class="section-totals"><strong>{sdr_total_count}</strong> opps · <strong>{money(sdr_total_mrr)}</strong> MRR</div>
  </section>

  <section class="table-wrap sdr-section">
    <table>
      <thead>
        <tr><th>SDR</th>{table_headers}<th>Total</th></tr>
      </thead>
      <tbody>
        {build_sdr_rows(by_sdr, sdr_weekly_totals, sdr_opps_by_rep)}
      </tbody>
    </table>
  </section>
</main>
<script>
document.querySelectorAll('.summary-row').forEach((row) => {{
  row.addEventListener('click', (event) => {{
    const next = row.nextElementSibling;
    if (!next || !next.classList.contains('details-row')) return;
    const open = next.classList.toggle('open');
    row.classList.toggle('open', open);
    const btn = row.querySelector('.expand-btn');
    if (btn) btn.textContent = open ? '-' : '+';
  }});
}});
</script>
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
