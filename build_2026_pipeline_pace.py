#!/usr/bin/env python3
"""Build and publish the 2026 month-over-month pipeline pace dashboard."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
HTML_FILE = WORKSPACE / "2026-pipeline-pace.html"
DATA_FILE = WORKSPACE / "sf_2026_pipeline_pace.json"
LIBRARY_FILE = WORKSPACE / "DECKS-LIBRARY.md"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

ET = ZoneInfo("America/New_York")
YEAR = 2026
MONTHS = [
    ("2026-01", "January"),
    ("2026-02", "February"),
    ("2026-03", "March"),
    ("2026-04", "April"),
    ("2026-05", "May"),
    ("2026-06", "June"),
    ("2026-07", "July"),
    ("2026-08", "August"),
    ("2026-09", "September"),
    ("2026-10", "October"),
    ("2026-11", "November"),
    ("2026-12", "December"),
]
PRODUCTS = ["PSA 2.0", "Billing / Odin", "Payments AR", "Cyber Protect", "Other / Not Set"]
SOURCES = [
    "Sales",
    "Tradeshow",
    "Website",
    "Paid Media",
    "Email",
    "SEO",
    "Rev.io Summit",
    "Referral",
    "Partner / Channel",
    "Phone",
    "Other / Not Set",
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


def fetch_created_opps(base, headers):
    query = f"""
        SELECT Id, Name, Amount, StageName, CreatedDate, CloseDate,
               Product_Type__c, Lead_Direction__c, LeadSource, Opportunity_Source__c,
               Marketing_Source__c, Marketing_Sub_source__c,
               Account.Name, Owner.Name
        FROM Opportunity
        WHERE CreatedDate >= {YEAR}-01-01T00:00:00Z
          AND CreatedDate < {YEAR + 1}-01-01T00:00:00Z
          AND IsDeleted = false
        ORDER BY CreatedDate ASC
    """
    return sf_query(base, headers, query)


def fetch_closed_won(base, headers):
    query = f"""
        SELECT Id, Amount, CloseDate, Product_Type__c
        FROM Opportunity
        WHERE StageName = 'Closed Won'
          AND CloseDate >= {YEAR}-01-01
          AND CloseDate <= {YEAR}-12-31
          AND IsDeleted = false
        ORDER BY CloseDate ASC
    """
    return sf_query(base, headers, query)


def money(value):
    return f"${value:,.0f}"


def compact_money(value):
    value = float(value or 0)
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"


def month_key_from_created(value):
    return (value or "")[:7]


def product_bucket(value):
    text = (value or "").strip().lower()
    if "psa" in text:
        return "PSA 2.0"
    if "billing" in text or "odin" in text:
        return "Billing / Odin"
    if "payment" in text:
        return "Payments AR"
    if "cyber" in text:
        return "Cyber Protect"
    return "Other / Not Set"


def canonical_source(value):
    text = (value or "").strip()
    lower = text.lower()
    if not text or lower in {"blank", "-none-", "none", "not set"}:
        return ""
    if "trade" in lower or "show" in lower:
        return "Tradeshow"
    if "website" in lower or "web" in lower or "request demo" in lower or "contact us" in lower:
        return "Website"
    if "paid" in lower or "ppc" in lower or "media" in lower or "facebook" in lower or "google ads" in lower:
        return "Paid Media"
    if "email" in lower:
        return "Email"
    if "seo" in lower or "organic" in lower:
        return "SEO"
    if "summit" in lower:
        return "Rev.io Summit"
    if "referral" in lower:
        return "Referral"
    if "partner" in lower or "channel" in lower:
        return "Partner / Channel"
    if "phone" in lower:
        return "Phone"
    if "sales" in lower:
        return "Sales"
    return ""


def source_bucket(marketing_source, opportunity_source, lead_source, lead_direction, subsource):
    for value in (marketing_source, opportunity_source, lead_source, subsource):
        bucket = canonical_source(value)
        if bucket:
            return bucket
    source = (subsource or "").strip()
    lower = source.lower()
    lead = (lead_direction or "").strip().lower()
    if "trade" in lower or "show" in lower:
        return "Tradeshow"
    if "website" in lower or "web" in lower:
        return "Website"
    if "paid" in lower or "ppc" in lower or "media" in lower:
        return "Paid Media"
    if "email" in lower:
        return "Email"
    if "seo" in lower or "organic" in lower:
        return "SEO"
    if "summit" in lower:
        return "Rev.io Summit"
    if "partner" in lower or "channel" in lower:
        return "Partner / Channel"
    if "sales" in lead:
        return "Sales"
    if "channel" in lead or "partner" in lead:
        return "Partner / Channel"
    return "Other / Not Set"


def empty_months():
    return {
        key: {
            "label": label,
            "created_count": 0,
            "created_amount": 0.0,
            "won_count": 0,
            "won_amount": 0.0,
        }
        for key, label in MONTHS
    }


def summarize(created, closed_won):
    months = empty_months()
    product = {name: {key: {"count": 0, "amount": 0.0} for key, _ in MONTHS} for name in PRODUCTS}
    source = {name: {key: 0 for key, _ in MONTHS} for name in SOURCES}
    created_records = []

    for opp in created:
        key = month_key_from_created(opp.get("CreatedDate"))
        if key not in months:
            continue
        amount = float(opp.get("Amount") or 0)
        months[key]["created_count"] += 1
        months[key]["created_amount"] += amount
        product_name = product_bucket(opp.get("Product_Type__c"))
        product[product_name][key]["count"] += 1
        product[product_name][key]["amount"] += amount
        source_name = source_bucket(
            opp.get("Marketing_Source__c"),
            opp.get("Opportunity_Source__c"),
            opp.get("LeadSource"),
            opp.get("Lead_Direction__c"),
            opp.get("Marketing_Sub_source__c"),
        )
        source[source_name][key] += 1
        created_records.append(
            {
                "id": opp.get("Id"),
                "name": opp.get("Name"),
                "amount": amount,
                "stage": opp.get("StageName"),
                "created_date": opp.get("CreatedDate"),
                "close_date": opp.get("CloseDate"),
                "product": product_name,
                "source": source_name,
                "marketing_source": opp.get("Marketing_Source__c"),
                "opportunity_source": opp.get("Opportunity_Source__c"),
                "lead_source": opp.get("LeadSource"),
                "marketing_sub_source": opp.get("Marketing_Sub_source__c"),
                "owner": (opp.get("Owner") or {}).get("Name") if isinstance(opp.get("Owner"), dict) else None,
                "account": (opp.get("Account") or {}).get("Name") if isinstance(opp.get("Account"), dict) else None,
            }
        )

    for opp in closed_won:
        key = (opp.get("CloseDate") or "")[:7]
        if key not in months:
            continue
        months[key]["won_count"] += 1
        months[key]["won_amount"] += float(opp.get("Amount") or 0)

    return months, product, source, created_records


def status_for_month(month_key, current_month):
    if month_key < current_month:
        return "Final"
    if month_key == current_month:
        return "MTD"
    return "Upcoming"


def build_month_cards(months):
    current_month = datetime.now(ET).strftime("%Y-%m")
    max_amount = max((m["created_amount"] for m in months.values()), default=0) or 1
    cards = []
    for key, label in MONTHS:
        metrics = months[key]
        status = status_for_month(key, current_month)
        win_rate = (metrics["won_count"] / metrics["created_count"] * 100) if metrics["created_count"] else 0
        pct = metrics["created_amount"] / max_amount * 100
        delta = ""
        prior_keys = [month for month, _ in MONTHS if month < key]
        if prior_keys and metrics["created_count"]:
            prev = months[prior_keys[-1]]
            diff = metrics["created_amount"] - prev["created_amount"]
            sign = "+" if diff >= 0 else "-"
            delta = f'<div class="delta {"" if diff >= 0 else "down"}">{sign}{compact_money(abs(diff))} vs prior month</div>'
        elif status == "Upcoming":
            delta = '<div class="delta muted">No 2026 data yet</div>'
        cards.append(
            f"""
            <section class="month-card {status.lower()}">
              <div class="month-top">
                <div>
                  <div class="month-label">{escape(label)}</div>
                  <div class="month-status">{escape(status)}</div>
                </div>
                <div class="month-value">{compact_money(metrics['created_amount'])}</div>
              </div>
              <div class="month-meta">{metrics['created_count']} opps created</div>
              <div class="month-track"><span style="width:{pct:.1f}%"></span></div>
              <div class="won-block">
                <span>Won MRR</span>
                <strong>{compact_money(metrics['won_amount'])}</strong>
                <em>{win_rate:.0f}% win rate</em>
              </div>
              {delta}
            </section>"""
        )
    return "\n".join(cards)


def build_product_table(product):
    header = "".join(f"<th>{label[:3]}</th><th>MRR</th>" for _, label in MONTHS)
    rows = []
    colors = {
        "PSA 2.0": "#00d4f0",
        "Billing / Odin": "#3ddc97",
        "Payments AR": "#f5a623",
        "Cyber Protect": "#a78bfa",
        "Other / Not Set": "#94a3b8",
    }
    for name in PRODUCTS:
        cells = []
        for key, _ in MONTHS:
            metrics = product[name][key]
            cells.append(f"<td>{metrics['count']}</td><td class=\"muted\">{compact_money(metrics['amount'])}</td>")
        rows.append(
            f"""
            <tr>
              <td class="row-name" style="color:{colors[name]}">{escape(name)}</td>
              {''.join(cells)}
            </tr>"""
        )
    return f"""
    <div class="table-shell">
      <table>
        <thead><tr><th>Product</th>{header}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>"""


def build_source_table(source):
    header = "".join(f"<th>{label[:3]}</th>" for _, label in MONTHS)
    rows = []
    for name in SOURCES:
        total = sum(source[name].values())
        cells = "".join(f"<td>{source[name][key]}</td>" for key, _ in MONTHS)
        rows.append(
            f"""
            <tr>
              <td class="row-name">{escape(name)}<span>{total:,}</span></td>
              {cells}
            </tr>"""
        )
    return f"""
    <div class="table-shell source-table">
      <table>
        <thead><tr><th>Source</th>{header}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>"""


def build_html(months, product, source):
    generated_at = datetime.now(ET)
    actual_months = [key for key, _ in MONTHS if months[key]["created_count"]]
    total_created = sum(months[key]["created_count"] for key, _ in MONTHS)
    total_pipeline = sum(months[key]["created_amount"] for key, _ in MONTHS)
    total_won = sum(months[key]["won_amount"] for key, _ in MONTHS)
    current_month = datetime.now(ET).strftime("%Y-%m")
    ytd_months = [key for key, _ in MONTHS if key <= current_month]
    avg_monthly_pipeline = total_pipeline / max(len([k for k in ytd_months if months[k]["created_count"]]), 1)
    run_rate = avg_monthly_pipeline * 12
    best_month = max(actual_months or ["2026-01"], key=lambda key: months[key]["created_amount"])
    best_month_label = months[best_month]["label"]

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>2026 Pipeline Pace</title>
<link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700;800&family=Montserrat:wght@700;800;900&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#0a1628;
  --panel:#0f2339;
  --panel2:#132540;
  --ink:#ffffff;
  --muted:rgba(255,255,255,.48);
  --faint:rgba(255,255,255,.08);
  --teal:#00d4f0;
  --green:#3ddc97;
  --gold:#f5a623;
  --red:#ff5c5c;
  --purple:#a78bfa;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0;
  background:
    radial-gradient(circle at top left, rgba(0,212,240,.14), transparent 34rem),
    radial-gradient(circle at bottom right, rgba(61,220,151,.10), transparent 30rem),
    var(--bg);
  color:var(--ink);
  font-family:'Open Sans', Arial, sans-serif;
}}
.stripe {{ height:4px; background:linear-gradient(90deg,var(--teal),var(--green)); }}
.shell {{ max-width:1680px; margin:0 auto; padding:26px 34px 38px; }}
.topbar {{ display:flex; justify-content:space-between; align-items:flex-end; gap:24px; margin-bottom:20px; }}
.eyebrow {{ color:var(--teal); font-size:11px; font-weight:800; letter-spacing:2px; text-transform:uppercase; }}
h1 {{ margin:6px 0 0; font-family:Montserrat, sans-serif; font-size:38px; line-height:1.05; letter-spacing:0; }}
.subtitle {{ color:var(--muted); font-size:14px; margin-top:8px; }}
.stamp {{ text-align:right; color:rgba(255,255,255,.32); font-size:12px; line-height:1.5; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:16px; }}
.kpi, .month-card, .table-shell, .insight {{
  background:rgba(15,35,57,.94);
  border:1px solid rgba(255,255,255,.08);
  border-radius:8px;
  box-shadow:0 18px 50px rgba(0,0,0,.24);
}}
.kpi {{ padding:16px; position:relative; overflow:hidden; }}
.kpi:before {{ content:""; position:absolute; left:0; right:0; top:0; height:3px; background:var(--accent,var(--teal)); }}
.kpi-label {{ color:var(--muted); font-size:10px; font-weight:800; letter-spacing:1.5px; text-transform:uppercase; }}
.kpi-value {{ margin-top:8px; font-family:Montserrat, sans-serif; font-size:32px; font-weight:900; }}
.kpi-sub {{ color:rgba(255,255,255,.36); font-size:12px; margin-top:4px; }}
.month-grid {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; margin-bottom:20px; }}
.month-card {{ padding:15px; min-height:172px; }}
.month-card.mtd {{ border-color:rgba(0,212,240,.28); }}
.month-card.upcoming {{ opacity:.64; }}
.month-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }}
.month-label {{ font-size:12px; font-weight:900; letter-spacing:1.2px; text-transform:uppercase; color:rgba(255,255,255,.72); }}
.month-status {{ margin-top:4px; display:inline-flex; padding:2px 8px; border-radius:999px; background:rgba(0,212,240,.09); color:var(--teal); font-size:9px; font-weight:900; letter-spacing:1px; text-transform:uppercase; }}
.month-value {{ font-family:Montserrat, sans-serif; font-size:24px; font-weight:900; color:var(--teal); text-align:right; }}
.month-meta {{ color:rgba(255,255,255,.45); font-size:12px; margin-top:8px; }}
.month-track {{ height:7px; background:rgba(255,255,255,.07); border-radius:999px; overflow:hidden; margin-top:11px; }}
.month-track span {{ display:block; height:100%; border-radius:999px; background:linear-gradient(90deg,var(--teal),var(--green)); }}
.won-block {{ margin-top:11px; padding-top:10px; border-top:1px solid rgba(255,255,255,.07); display:grid; grid-template-columns:1fr auto; gap:2px 8px; align-items:baseline; }}
.won-block span {{ color:rgba(255,255,255,.38); font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:1px; }}
.won-block strong {{ color:var(--green); font-family:Montserrat, sans-serif; font-size:15px; }}
.won-block em {{ grid-column:1 / -1; color:rgba(255,255,255,.32); font-size:10px; font-style:normal; }}
.delta {{ margin-top:8px; color:var(--green); font-size:11px; font-weight:800; }}
.delta.down {{ color:var(--red); }}
.delta.muted {{ color:rgba(255,255,255,.28); }}
.section-head {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin:22px 0 10px; }}
.section-head h2 {{ margin:0; font-family:Montserrat, sans-serif; font-size:20px; letter-spacing:0; }}
.section-head p {{ margin:4px 0 0; color:var(--muted); font-size:13px; }}
.table-shell {{ overflow:auto; }}
table {{ width:100%; min-width:1320px; border-collapse:collapse; font-size:11px; }}
th {{ background:rgba(0,212,240,.08); color:rgba(255,255,255,.58); font-size:10px; font-weight:900; text-transform:uppercase; letter-spacing:1.2px; }}
th, td {{ padding:9px 10px; text-align:center; border-bottom:1px solid rgba(255,255,255,.06); border-left:1px solid rgba(255,255,255,.04); }}
th:first-child, td:first-child {{ position:sticky; left:0; z-index:2; text-align:left; border-left:0; background:#0f2339; }}
th:first-child {{ background:#102842; color:var(--teal); }}
.row-name {{ min-width:150px; font-weight:900; color:#fff; }}
.row-name span {{ display:block; margin-top:2px; color:rgba(255,255,255,.35); font-size:9px; font-weight:800; letter-spacing:1px; text-transform:uppercase; }}
.muted {{ color:rgba(255,255,255,.48); }}
.source-table table {{ min-width:1040px; }}
.insight {{ margin-top:20px; padding:17px 20px; display:flex; justify-content:space-between; gap:18px; align-items:center; }}
.insight-text {{ color:rgba(255,255,255,.68); font-size:13px; line-height:1.5; }}
.insight-text strong {{ color:var(--green); }}
.insight-stats {{ display:flex; gap:0; flex-shrink:0; }}
.stat {{ padding:0 18px; border-left:1px solid rgba(255,255,255,.08); text-align:center; }}
.stat-value {{ font-family:Montserrat, sans-serif; font-size:22px; font-weight:900; color:var(--teal); }}
.stat-label {{ color:rgba(255,255,255,.32); font-size:9px; font-weight:800; letter-spacing:1px; text-transform:uppercase; margin-top:3px; }}
@media (max-width:1180px) {{
  .shell {{ padding:20px; }}
  .topbar {{ display:block; }}
  .stamp {{ text-align:left; margin-top:12px; }}
  .kpis {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .month-grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
  .insight {{ display:block; }}
  .insight-stats {{ margin-top:14px; }}
}}
@media (max-width:680px) {{
  h1 {{ font-size:29px; }}
  .kpis, .month-grid {{ grid-template-columns:1fr; }}
  .insight-stats {{ display:grid; grid-template-columns:1fr; gap:12px; }}
  .stat {{ border-left:0; padding:0; text-align:left; }}
}}
</style>
</head>
<body>
<div class="stripe"></div>
<main class="shell">
  <header class="topbar">
    <div>
      <div class="eyebrow">Pipeline Trends</div>
      <h1>2026 Pipeline Pace</h1>
      <div class="subtitle">Month-over-month opportunities created, pipeline MRR, won MRR, product mix, and source mix through 2026.</div>
    </div>
    <div class="stamp">
      Refreshed {generated_at.strftime('%b %-d, %Y %-I:%M %p ET')}<br>
      Source: Salesforce Opportunity CreatedDate and CloseDate
    </div>
  </header>

  <section class="kpis">
    <div class="kpi" style="--accent:var(--teal)"><div class="kpi-label">YTD Pipeline Created</div><div class="kpi-value">{compact_money(total_pipeline)}</div><div class="kpi-sub">{total_created:,} opportunities created</div></div>
    <div class="kpi" style="--accent:var(--green)"><div class="kpi-label">YTD Closed Won MRR</div><div class="kpi-value">{compact_money(total_won)}</div><div class="kpi-sub">Closed-won in calendar 2026</div></div>
    <div class="kpi" style="--accent:var(--gold)"><div class="kpi-label">Current Run Rate</div><div class="kpi-value">{compact_money(run_rate)}</div><div class="kpi-sub">Annualized from active 2026 months</div></div>
    <div class="kpi" style="--accent:var(--purple)"><div class="kpi-label">Best Created Month</div><div class="kpi-value">{escape(best_month_label)}</div><div class="kpi-sub">{compact_money(months[best_month]['created_amount'])} pipeline created</div></div>
  </section>

  <section class="month-grid">
    {build_month_cards(months)}
  </section>

  <section class="section-head">
    <div>
      <h2>Pipeline by Product</h2>
      <p>Opportunity count and created MRR by product for each 2026 month.</p>
    </div>
  </section>
  {build_product_table(product)}

  <section class="section-head">
    <div>
      <h2>Pipeline by Marketing Source</h2>
      <p>Opportunity count by source bucket, using marketing sub-source where populated and lead direction as fallback.</p>
    </div>
  </section>
  {build_source_table(source)}

  <section class="insight">
    <div class="insight-text">
      The page is the standalone version of slide 5 from the May update deck, extended across all 12 months of 2026.
      <strong>Future months stay visible</strong> so the team can watch pace fill in as the year progresses.
    </div>
    <div class="insight-stats">
      <div class="stat"><div class="stat-value">{compact_money(avg_monthly_pipeline)}</div><div class="stat-label">Avg Active Month</div></div>
      <div class="stat"><div class="stat-value">{len(actual_months)}</div><div class="stat-label">Months With Data</div></div>
      <div class="stat"><div class="stat-value">{compact_money(total_pipeline)}</div><div class="stat-label">YTD Created</div></div>
    </div>
  </section>
</main>
</body>
</html>
"""
    HTML_FILE.write_text(html, encoding="utf-8")


def update_library():
    row = (
        "| 2026 Pipeline Pace | 2026-pipeline-pace.html | "
        "https://koontz-robin.github.io/robin-decks/2026-pipeline-pace.html | On demand |"
    )
    text = LIBRARY_FILE.read_text(encoding="utf-8")
    if "2026-pipeline-pace.html" in text:
        return
    anchor = "| Monthly Pipeline Dashboard | monthly-pipeline-dashboard.html | https://koontz-robin.github.io/robin-decks/monthly-pipeline-dashboard.html | On demand |"
    text = text.replace(anchor, f"{anchor}\n{row}")
    LIBRARY_FILE.write_text(text, encoding="utf-8")


def publish(files):
    subprocess.run(["git", "fetch", "robin-decks", "master"], cwd=WORKSPACE, check=True)
    tmp_parent = Path(tempfile.mkdtemp(prefix="pipeline-pace-"))
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
        subprocess.run(["git", "commit", "-m", f"add 2026 pipeline pace dashboard ({stamp})"], cwd=worktree, check=True)
        subprocess.run(["git", "push", "robin-decks", "HEAD:master"], cwd=worktree, check=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=WORKSPACE, check=False)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    print("Authenticating to Salesforce...")
    base, headers = sf_auth()
    print("Fetching 2026 created opportunities...")
    created = fetch_created_opps(base, headers)
    print(f"Fetched {len(created):,} created opportunities.")
    print("Fetching 2026 closed-won opportunities...")
    closed_won = fetch_closed_won(base, headers)
    print(f"Fetched {len(closed_won):,} closed-won opportunities.")
    months, product, source, created_records = summarize(created, closed_won)
    DATA_FILE.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(ET).isoformat(),
                "months": months,
                "product": product,
                "source": source,
                "created_opportunities": created_records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    build_html(months, product, source)
    update_library()
    print(f"Built {HTML_FILE.name}: {sum(m['created_count'] for m in months.values()):,} created opps, {money(sum(m['created_amount'] for m in months.values()))} pipeline.")
    if os.environ.get("NO_PUBLISH") == "1":
        print("NO_PUBLISH=1 set; skipping GitHub Pages publish.")
        return
    publish([HTML_FILE, DATA_FILE, LIBRARY_FILE, Path(__file__)])
    print(f"Published https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
