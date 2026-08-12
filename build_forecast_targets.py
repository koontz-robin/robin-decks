#!/usr/bin/env python3
"""Build and publish the current month / quarter Forecast Targets page."""

import json
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
HTML_FILE = WORKSPACE / "forecast-targets.html"
DATA_FILE = WORKSPACE / "sf_forecast_targets_q3_2026.json"
LIBRARY_FILE = WORKSPACE / "DECKS-LIBRARY.md"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

ET = ZoneInfo("America/New_York")
NOW = datetime.now(ET)
CURRENT_MONTH = NOW.strftime("%B")
CURRENT_YEAR = NOW.year
CURRENT_MONTH_START = date(CURRENT_YEAR, NOW.month, 1)
CURRENT_MONTH_END = date(CURRENT_YEAR, NOW.month, 31)
QUARTER_LABEL = "Q3 2026"
QUARTER_START = date(2026, 7, 1)
QUARTER_END = date(2026, 9, 30)

PRODUCTS = [
    ("PSA", "PSA", "#50ff8a"),
    ("Billing", "Billing / Odin", "#2ee6be"),
    ("Payments", "Payments", "#9b7cff"),
    ("Cyber", "Cyber Protect", "#ff5d74"),
    ("CommerceHub", "CommerceHub", "#eace9b"),
]

MONTHLY_QUOTAS = {
    "August": {"PSA": 46000, "Billing": 12383, "Payments": 10540, "Cyber": 4500, "CommerceHub": 1667},
}
DEFAULT_MONTH_QUOTAS = {"PSA": 30000, "Billing": 13368, "Payments": 10540, "Cyber": 4500, "CommerceHub": 1667}
QUARTER_QUOTAS = {"PSA": 138000, "Billing": 42104, "Payments": 30740, "Cyber": 33702, "CommerceHub": 0}
MONTH_TARGETS = MONTHLY_QUOTAS.get(CURRENT_MONTH, DEFAULT_MONTH_QUOTAS)

ROLE_GROUPS = {
    "SDRs": "SDR",
    "MSP Sales": "MSP Sales",
    "Integrator Sales": "Integrator Sales",
    "CSA": "CSA",
}
NAME_ALIASES = {"Andrew Whisenant": "Andy Whisenant"}


def money(value):
    return f"${float(value or 0):,.0f}"


def pct(actual, target):
    return (float(actual or 0) / float(target) * 100) if target else 0


def normalize_name(value):
    return NAME_ALIASES.get((value or "").strip(), (value or "").strip())


def product_key(value):
    text = (value or "").strip().lower()
    if "psa" in text:
        return "PSA"
    if "billing" in text or "odin" in text:
        return "Billing"
    if "payment" in text:
        return "Payments"
    if "cyber" in text:
        return "Cyber"
    if "commerce" in text:
        return "CommerceHub"
    return "Other"


def product_from_line(line_item):
    product = line_item.get("Product2") or {}
    return product_key(f"{product.get('Family') or ''} {product.get('Name') or ''}")


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


def fetch_opportunities(base, headers):
    query = f"""
        SELECT Id, Name, StageName, Amount, Product_Type__c, Probability,
               CloseDate, Forecast_Status__c, Account.Name, AccountId,
               Owner.Name, Owner.UserRole.Name, SDR_Influence__c,
               (SELECT Id, Quantity, UnitPrice, TotalPrice, Product2.Name, Product2.Family
                FROM OpportunityLineItems)
        FROM Opportunity
        WHERE CloseDate >= {QUARTER_START.isoformat()}
          AND CloseDate <= {QUARTER_END.isoformat()}
          AND StageName != 'Closed Lost'
          AND IsDeleted = false
        ORDER BY CloseDate ASC, Amount DESC NULLS LAST
    """
    records = sf_query(base, headers, query)
    flattened = []
    for record in records:
        account = record.get("Account") or {}
        owner = record.get("Owner") or {}
        flattened.append(
            {
                "Id": record.get("Id") or "",
                "Name": record.get("Name") or "",
                "StageName": record.get("StageName") or "",
                "Amount": float(record.get("Amount") or 0),
                "Product_Type__c": record.get("Product_Type__c") or "",
                "Probability": float(record.get("Probability") or 0),
                "CloseDate": record.get("CloseDate") or "",
                "Forecast_Status__c": record.get("Forecast_Status__c") or "Unspecified",
                "Account": account.get("Name") or "",
                "AccountId": record.get("AccountId") or "",
                "Owner": normalize_name(owner.get("Name") or "Unknown"),
                "OwnerRole": (owner.get("UserRole") or {}).get("Name") or "",
                "SDR_Influence__c": normalize_name(record.get("SDR_Influence__c") or ""),
                "OpportunityLineItems": record.get("OpportunityLineItems") or {"records": []},
            }
        )
    DATA_FILE.write_text(json.dumps(flattened, indent=2), encoding="utf-8")
    return flattened


def booking_splits(opp):
    splits = defaultdict(float)
    for line_item in ((opp.get("OpportunityLineItems") or {}).get("records") or []):
        amount = line_item.get("TotalPrice")
        if amount is None:
            amount = float(line_item.get("Quantity") or 0) * float(line_item.get("UnitPrice") or 0)
        if amount:
            splits[product_from_line(line_item)] += float(amount)
    if splits:
        return splits.items()
    return [(product_key(opp.get("Product_Type__c")), float(opp.get("Amount") or 0))]


def empty_bucket():
    return {"closed": 0.0, "open": 0.0, "weighted": 0.0, "closed_count": 0, "open_count": 0}


def empty_status_bucket():
    return {"count": 0, "amount": 0.0, "weighted": 0.0}


def is_current_month(opp):
    close = date.fromisoformat(opp["CloseDate"][:10])
    return CURRENT_MONTH_START <= close <= CURRENT_MONTH_END


def team_for_opp(opp):
    role = opp.get("OwnerRole") or ""
    if role in ROLE_GROUPS:
        return ROLE_GROUPS[role]
    product = product_key(opp.get("Product_Type__c"))
    if product == "PSA":
        return "PSA Team"
    if product == "Billing":
        return "Billing Team"
    return "Other"


def add_opp_to_bucket(bucket, opp, amount):
    if opp["StageName"] == "Closed Won":
        bucket["closed"] += amount
        bucket["closed_count"] += 1
    else:
        bucket["open"] += amount
        bucket["weighted"] += amount * (opp["Probability"] / 100)
        bucket["open_count"] += 1


def build_metrics(opps):
    month = {key: empty_bucket() for key, _, _ in PRODUCTS}
    quarter = {key: empty_bucket() for key, _, _ in PRODUCTS}
    month_team = defaultdict(lambda: {key: empty_bucket() for key, _, _ in PRODUCTS})
    quarter_team = defaultdict(lambda: {key: empty_bucket() for key, _, _ in PRODUCTS})
    forecast_status = {key: defaultdict(empty_status_bucket) for key, _, _ in PRODUCTS}
    detail = []

    for opp in opps:
        team = team_for_opp(opp)
        month_scope = is_current_month(opp)
        for key, amount in booking_splits(opp):
            if key not in quarter:
                continue
            add_opp_to_bucket(quarter[key], opp, amount)
            add_opp_to_bucket(quarter_team[team][key], opp, amount)
            if month_scope:
                add_opp_to_bucket(month[key], opp, amount)
                add_opp_to_bucket(month_team[team][key], opp, amount)
            if opp["StageName"] != "Closed Won":
                status = opp.get("Forecast_Status__c") or "Unspecified"
                forecast_status[key][status]["count"] += 1
                forecast_status[key][status]["amount"] += amount
                forecast_status[key][status]["weighted"] += amount * (opp["Probability"] / 100)
            detail.append(
                {
                    "scope": "Month" if month_scope else "Quarter",
                    "product": key,
                    "team": team,
                    "account": opp.get("Account") or opp.get("Name"),
                    "name": opp.get("Name") or "",
                    "stage": opp.get("StageName") or "",
                    "amount": amount,
                    "weighted": amount * (opp["Probability"] / 100) if opp["StageName"] != "Closed Won" else amount,
                    "owner": opp.get("Owner") or "",
                    "close": opp.get("CloseDate") or "",
                }
            )
    detail.sort(key=lambda row: (row["close"], row["product"], -row["amount"]))
    return month, quarter, month_team, quarter_team, forecast_status, detail


def card(product, label, color, month, quarter):
    month_target = MONTH_TARGETS.get(product, 0)
    month_closed = month[product]["closed"]
    month_remaining = max(month_target - month_closed, 0)
    return f"""
    <section class="target-card" style="--accent:{color}">
      <div class="card-head">
        <div><div class="eyebrow">Product Line</div><h2>{escape(label)}</h2></div>
        <div class="pill">{month[product]['closed_count']} won MTD</div>
      </div>
      <div class="metric-row"><span>{escape(CURRENT_MONTH)} Target</span><strong>{money(month_target)}</strong></div>
      <div class="bar-wrap">
        <div class="bar-label"><span>{escape(CURRENT_MONTH)} Closed Won</span><b>{pct(month_closed, month_target):.1f}%</b></div>
        <div class="bar"><i style="width:{min(pct(month_closed, month_target), 100):.1f}%"></i></div>
        <div class="bar-foot"><span>{money(month_closed)} / {money(month_target)}</span><span>{money(month_remaining)} left</span></div>
      </div>
      <div class="pipeline">
        <div><b>{money(month_closed)}</b><span>Closed Won MTD</span></div>
        <div><b>{money(month[product]['open'])}</b><span>Open Month Pipeline</span></div>
        <div><b>{money(month[product]['weighted'])}</b><span>Weighted Month</span></div>
      </div>
    </section>"""


def product_rows(month, quarter):
    rows = []
    for key, label, _ in PRODUCTS:
        rows.append(
            f"""
            <tr>
              <td><strong>{escape(label)}</strong><span>{month[key]['closed_count']} won MTD · {month[key]['open_count']} open MTD</span></td>
              <td>{money(MONTH_TARGETS.get(key, 0))}</td>
              <td>{money(month[key]['closed'])}</td>
              <td>{pct(month[key]['closed'], MONTH_TARGETS.get(key, 0)):.1f}%</td>
              <td>{money(month[key]['open'])}</td>
              <td>{money(month[key]['weighted'])}</td>
              <td>{money(QUARTER_QUOTAS.get(key, 0))}</td>
              <td>{money(quarter[key]['closed'])}</td>
              <td>{pct(quarter[key]['closed'], QUARTER_QUOTAS.get(key, 0)):.1f}%</td>
              <td>{money(quarter[key]['open'])}</td>
            </tr>"""
        )
    return "\n".join(rows)


def team_rows(groups, title):
    rows = []
    for team, products in sorted(groups.items()):
        for key, label, _ in PRODUCTS:
            values = products[key]
            if not any(values.values()):
                continue
            rows.append(
                f"""
                <tr>
                  <td><strong>{escape(team)}</strong><span>{escape(title)}</span></td>
                  <td>{escape(label)}</td>
                  <td>{money(values['closed'])}</td>
                  <td>{values['closed_count']}</td>
                  <td>{money(values['open'])}</td>
                  <td>{money(values['weighted'])}</td>
                  <td>{values['open_count']}</td>
                </tr>"""
            )
    if not rows:
        return '<tr><td colspan="7" class="empty">No team activity found.</td></tr>'
    return "\n".join(rows)


def status_rows(forecast_status):
    rows = []
    for key, label, _ in PRODUCTS:
        for status, values in sorted(forecast_status[key].items()):
            rows.append(
                f"""
                <tr>
                  <td><strong>{escape(label)}</strong></td>
                  <td>{escape(status)}</td>
                  <td>{values['count']}</td>
                  <td>{money(values['amount'])}</td>
                  <td>{money(values['weighted'])}</td>
                </tr>"""
            )
    if not rows:
        return '<tr><td colspan="5" class="empty">No open forecast pipeline found.</td></tr>'
    return "\n".join(rows)


def detail_rows(detail):
    rows = []
    for row in detail:
        rows.append(
            f"""
            <tr>
              <td>{escape(row['scope'])}</td>
              <td>{escape(row['product'])}</td>
              <td><strong>{escape(row['account'])}</strong><span>{escape(row['name'])}</span></td>
              <td>{money(row['amount'])}</td>
              <td>{escape(row['stage'])}</td>
              <td>{escape(row['team'])}</td>
              <td>{escape(row['owner'])}</td>
              <td>{escape(row['close'])}</td>
            </tr>"""
        )
    return "\n".join(rows) or '<tr><td colspan="8" class="empty">No forecast opportunities found.</td></tr>'


def build_html(opps):
    month, quarter, month_team, quarter_team, forecast_status, detail = build_metrics(opps)
    generated = datetime.now(ET)
    total_month_target = sum(MONTH_TARGETS.values())
    total_quarter_target = sum(QUARTER_QUOTAS.values())
    total_month_closed = sum(month[key]["closed"] for key, _, _ in PRODUCTS)
    total_quarter_closed = sum(quarter[key]["closed"] for key, _, _ in PRODUCTS)
    total_month_open = sum(month[key]["open"] for key, _, _ in PRODUCTS)
    total_quarter_open = sum(quarter[key]["open"] for key, _, _ in PRODUCTS)
    cards = "\n".join(card(key, label, color, month, quarter) for key, label, color in PRODUCTS)

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Forecast Targets</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#f6f8fb; --panel:#ffffff; --panel2:#f0f5f8; --line:#dbe3ee; --text:#172033; --muted:#64748b; --soft:#94a3b8; --cyan:#0891b2; --green:#20b26b; --pink:#e11d48; --violet:#6d5dfc; --gold:#b7791f; --shadow:0 18px 48px rgba(15,23,42,.08); }}
* {{ box-sizing:border-box; }}
body {{ margin:0; color:var(--text); font-family:Inter,system-ui,sans-serif; background:linear-gradient(180deg,#eef7f3 0,#f6f8fb 360px,#ffffff 100%); }}
.shell {{ max-width:1600px; margin:0 auto; padding:28px 30px 44px; }}
.topbar {{ display:flex; justify-content:space-between; align-items:flex-start; gap:28px; padding-bottom:22px; }}
.brand {{ width:118px; height:auto; filter:drop-shadow(0 8px 18px rgba(15,23,42,.14)); }}
.eyebrow {{ color:var(--green); font-size:11px; font-weight:900; letter-spacing:2px; text-transform:uppercase; }}
h1 {{ margin:8px 0 0; max-width:900px; font-size:44px; line-height:1.02; letter-spacing:0; }}
.subhead {{ max-width:900px; margin-top:10px; color:var(--muted); line-height:1.45; font-size:14px; }}
.stamp {{ margin-top:8px; color:var(--muted); font-size:12px; line-height:1.5; text-align:right; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:6px 0 18px; }}
.kpi,.target-card,.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); }}
.kpi {{ padding:17px; border-top:3px solid var(--accent,var(--violet)); }}
.kpi span {{ display:block; color:var(--muted); font-size:10px; font-weight:900; letter-spacing:1.3px; text-transform:uppercase; }}
.kpi strong {{ display:block; margin-top:8px; font-size:30px; line-height:1; }}
.kpi em {{ display:block; margin-top:6px; color:var(--muted); font-size:12px; font-style:normal; }}
.cards {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; }}
.target-card {{ padding:16px; border-top:4px solid var(--accent); }}
.card-head {{ display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }}
h2 {{ margin:5px 0 0; font-size:20px; letter-spacing:0; }}
.pill {{ border:1px solid color-mix(in srgb, var(--accent) 38%, transparent); color:var(--accent); background:color-mix(in srgb, var(--accent) 10%, transparent); border-radius:999px; padding:5px 8px; font-size:10px; font-weight:900; white-space:nowrap; }}
.metric-row {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin:18px 0 13px; padding-bottom:12px; border-bottom:1px solid var(--line); }}
.metric-row span {{ color:var(--muted); font-size:12px; font-weight:800; }}
.metric-row strong {{ color:var(--accent); font-size:26px; }}
.bar-wrap {{ margin-top:14px; }}
.bar-wrap.quarter {{ opacity:.94; }}
.bar-label,.bar-foot {{ display:flex; justify-content:space-between; gap:10px; align-items:center; }}
.bar-label span {{ color:var(--muted); font-size:10px; font-weight:900; letter-spacing:1.2px; text-transform:uppercase; }}
.bar-label b {{ color:var(--accent); font-size:12px; }}
.bar {{ height:8px; margin-top:7px; border-radius:999px; overflow:hidden; background:#e5edf3; }}
.bar i {{ display:block; height:100%; border-radius:999px; background:linear-gradient(90deg,var(--accent),#172033); }}
.bar-foot {{ margin-top:6px; color:var(--muted); font-size:11px; font-weight:700; }}
.pipeline {{ display:grid; grid-template-columns:1fr; gap:7px; margin-top:15px; }}
.pipeline div {{ padding:9px; border:1px solid var(--line); border-radius:8px; background:var(--panel2); }}
.pipeline b {{ display:block; color:var(--text); font-size:16px; }}
.pipeline span {{ display:block; margin-top:3px; color:var(--muted); font-size:10px; font-weight:800; line-height:1.25; text-transform:uppercase; letter-spacing:.8px; }}
.section-head {{ display:flex; justify-content:space-between; align-items:flex-end; gap:16px; margin:24px 0 10px; }}
.section-head h2 {{ margin:0; font-size:22px; }}
.section-head p {{ margin:5px 0 0; color:var(--muted); font-size:13px; }}
.panel {{ overflow:auto; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
table {{ width:100%; border-collapse:collapse; min-width:980px; font-size:12px; }}
th,td {{ padding:11px 12px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
th {{ background:#edf4f0; color:var(--muted); font-size:10px; font-weight:900; text-transform:uppercase; letter-spacing:1.1px; }}
th:first-child,td:first-child {{ text-align:left; }}
td:first-child,td strong {{ color:var(--text); }}
td span {{ display:block; margin-top:3px; color:var(--muted); font-size:10px; }}
.empty {{ color:var(--muted); text-align:center; }}
.note {{ margin-top:18px; color:var(--muted); font-size:12px; line-height:1.5; }}
@media(max-width:1300px) {{ .cards {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }}
@media(max-width:1000px) {{ .topbar {{ display:block; }} .brand {{ margin-bottom:14px; }} .stamp {{ text-align:left; }} .kpis,.two {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
@media(max-width:740px) {{ .shell {{ padding:22px 16px 36px; }} h1 {{ font-size:34px; }} .kpis,.cards,.two {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div>
      <img class="brand" src="revio-logo-white.png" alt="Rev.io">
      <div class="eyebrow">Forecast Targets</div>
      <h1>Forecast Targets</h1>
      <p class="subhead">Current month and {escape(QUARTER_LABEL)} target attainment, broken out by product line and team contribution. Actuals are closed-won MRR; pipeline excludes closed-lost opportunities and uses Salesforce probability for weighted forecast.</p>
    </div>
    <div class="stamp">Refreshed {generated.strftime('%b %-d, %Y %-I:%M %p ET')}<br>Source: Salesforce opportunities · {len(opps)} Q3 forecast records</div>
  </header>

  <section class="kpis">
    <div class="kpi" style="--accent:var(--green)"><span>{escape(CURRENT_MONTH)} Target</span><strong>{money(total_month_target)}</strong><em>All tracked product lines</em></div>
    <div class="kpi" style="--accent:var(--cyan)"><span>{escape(CURRENT_MONTH)} Closed Won</span><strong>{money(total_month_closed)}</strong><em>{pct(total_month_closed,total_month_target):.1f}% attainment · {money(total_month_open)} open</em></div>
    <div class="kpi" style="--accent:var(--violet)"><span>{escape(QUARTER_LABEL)} Target</span><strong>{money(total_quarter_target)}</strong><em>July through September</em></div>
    <div class="kpi" style="--accent:var(--pink)"><span>{escape(QUARTER_LABEL)} Closed Won</span><strong>{money(total_quarter_closed)}</strong><em>{pct(total_quarter_closed,total_quarter_target):.1f}% attainment · {money(total_quarter_open)} open</em></div>
  </section>

  <section class="cards">{cards}</section>

  <section class="section-head"><div><h2>Product Line Targets</h2><p>Month and quarter target attainment by product line.</p></div></section>
  <section class="panel">
    <table>
      <thead><tr><th>Product</th><th>Month Target</th><th>Month Won</th><th>Month Attain.</th><th>Month Open</th><th>Month Weighted</th><th>Qtr Target</th><th>Qtr Won</th><th>Qtr Attain.</th><th>Qtr Open</th></tr></thead>
      <tbody>{product_rows(month, quarter)}</tbody>
    </table>
  </section>

  <section class="section-head"><div><h2>Team Contribution</h2><p>Closed-won and open forecast dollars grouped by Salesforce owner role/team and product line.</p></div></section>
  <section class="two">
    <div class="panel">
      <table>
        <thead><tr><th>Team</th><th>Product</th><th>Closed Won</th><th>Won Opps</th><th>Open Pipeline</th><th>Weighted</th><th>Open Opps</th></tr></thead>
        <tbody>{team_rows(month_team, CURRENT_MONTH)}</tbody>
      </table>
    </div>
    <div class="panel">
      <table>
        <thead><tr><th>Team</th><th>Product</th><th>Closed Won</th><th>Won Opps</th><th>Open Pipeline</th><th>Weighted</th><th>Open Opps</th></tr></thead>
        <tbody>{team_rows(quarter_team, QUARTER_LABEL)}</tbody>
      </table>
    </div>
  </section>

  <section class="section-head"><div><h2>Open Forecast by Status</h2><p>Open Q3 pipeline by product line and Salesforce forecast status.</p></div></section>
  <section class="panel">
    <table>
      <thead><tr><th>Product</th><th>Forecast Status</th><th>Open Opps</th><th>Open Pipeline</th><th>Weighted</th></tr></thead>
      <tbody>{status_rows(forecast_status)}</tbody>
    </table>
  </section>

  <section class="section-head"><div><h2>Forecast Detail</h2><p>Q3 opportunities included in this view.</p></div></section>
  <section class="panel">
    <table>
      <thead><tr><th>Scope</th><th>Product</th><th>Account / Opportunity</th><th>MRR</th><th>Stage</th><th>Team</th><th>Owner</th><th>Close Date</th></tr></thead>
      <tbody>{detail_rows(detail)}</tbody>
    </table>
  </section>
  <p class="note">Target source: product-line quota constants used by the live Rev.io forecast dashboard. CommerceHub has an August target and no Q3 target in the current forecast configuration. Closed-won records are split by opportunity line items when available.</p>
</main>
</body>
</html>
"""
    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"Built {HTML_FILE.name}: {money(total_month_closed)} month won, {money(total_quarter_closed)} quarter won.")


def update_library():
    if not LIBRARY_FILE.exists():
        return
    row = "| Forecast Targets | forecast-targets.html | https://koontz-robin.github.io/robin-decks/forecast-targets.html | On demand |"
    text = LIBRARY_FILE.read_text(encoding="utf-8")
    if "forecast-targets.html" in text:
        return
    text = text.rstrip() + "\n" + row + "\n"
    LIBRARY_FILE.write_text(text, encoding="utf-8")


def publish(files):
    subprocess.run(["git", "fetch", "robin-decks", "master"], cwd=WORKSPACE, check=True)
    tmp_parent = Path(tempfile.mkdtemp(prefix="forecast-targets-publish."))
    worktree = tmp_parent / "worktree"
    try:
        subprocess.run(["git", "worktree", "add", str(worktree), "robin-decks/master"], cwd=WORKSPACE, check=True)
        for path in files:
            shutil.copy2(path, worktree / path.name)
        subprocess.run(["git", "config", "user.name", "Robin"], cwd=worktree, check=True)
        subprocess.run(["git", "config", "user.email", "robin@rev.io"], cwd=worktree, check=True)
        subprocess.run(["git", "add", *[path.name for path in files]], cwd=worktree, check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree)
        if diff.returncode == 0:
            print("No page changes to publish.")
            return
        stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
        subprocess.run(["git", "commit", "-m", f"add forecast targets page ({stamp})"], cwd=worktree, check=True)
        subprocess.run(["git", "push", "robin-decks", "HEAD:master"], cwd=worktree, check=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=WORKSPACE, check=False)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    print("Authenticating to Salesforce...")
    base, headers = sf_auth()
    print(f"Fetching {QUARTER_LABEL} forecast opportunities...")
    opps = fetch_opportunities(base, headers)
    print(f"Fetched {len(opps)} opportunities.")
    build_html(opps)
    update_library()
    if os.environ.get("NO_PUBLISH") == "1":
        print("NO_PUBLISH=1 set; skipping publish.")
        return
    publish([HTML_FILE, DATA_FILE, LIBRARY_FILE, Path(__file__)])
    print(f"Published https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")


if __name__ == "__main__":
    main()
