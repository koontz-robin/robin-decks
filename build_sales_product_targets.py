#!/usr/bin/env python3
"""Build the July/Q3 product-line sales target tracker."""

import json
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
HTML_FILE = WORKSPACE / "sales-product-targets-july-q3.html"
JULY_OPPS_FILE = WORKSPACE / "sf_july_opps.json"
LIBRARY_FILE = WORKSPACE / "DECKS-LIBRARY.md"
ET = ZoneInfo("America/New_York")

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
JULY_START_DATE = "2026-07-01"
JULY_END_DATE = "2026-07-31"
JULY_START_UTC = "2026-07-01T04:00:00Z"
AUGUST_START_UTC = "2026-08-01T04:00:00Z"

PRODUCTS = [
    ("PSA", "PSA", "#50ff8a"),
    ("Billing", "Billing / Odin", "#2ee6be"),
    ("Cyber", "Cyber Protect", "#ff5d74"),
]

JULY_TARGETS = {
    "PSA": 42000,
    "Billing": 12368,
    "Cyber": 9967,
}

Q3_TARGETS = {
    "PSA": 138000,
    "Billing": 42104,
    "Cyber": 33702,
}


def money(value):
    return f"${float(value or 0):,.0f}"


def percent(actual, target):
    return (float(actual or 0) / target * 100) if target else 0


def product_key(value):
    text = (value or "").strip().lower()
    if "psa" in text:
        return "PSA"
    if "billing" in text or "odin" in text:
        return "Billing"
    if "cyber" in text:
        return "Cyber"
    if "payment" in text:
        return "Payments"
    if "commerce" in text:
        return "CommerceHub"
    return "Other"


def sf_quote(value):
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def chunked(values, size=150):
    values = [value for value in values if value]
    for index in range(0, len(values), size):
        yield values[index:index + size]


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


def normalize_name(name):
    return (name or "").strip()


def fetch_july_opportunities(base, headers):
    query = f"""
        SELECT Id, Name, StageName, Amount, Product_Type__c, Probability,
               CloseDate, CreatedDate, Forecast_Status__c, AccountId,
               Account.Name, Owner.Name, SDR_Influence__c,
               (SELECT Id, Quantity, UnitPrice, TotalPrice, Product2.Name, Product2.Family
                FROM OpportunityLineItems)
        FROM Opportunity
        WHERE CloseDate >= {JULY_START_DATE}
          AND CloseDate <= {JULY_END_DATE}
          AND StageName != 'Closed Lost'
          AND IsDeleted = false
        ORDER BY Amount DESC NULLS LAST
        LIMIT 500
    """
    records = sf_query(base, headers, query)
    for record in records:
        if isinstance(record.get("Account"), dict):
            record["Account"] = record["Account"].get("Name") or ""
        if isinstance(record.get("Owner"), dict):
            record["Owner"] = normalize_name(record["Owner"].get("Name") or "")
        record["SDR_Influence__c"] = normalize_name(record.get("SDR_Influence__c") or "")
    JULY_OPPS_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


def line_product_key(line_item):
    product = line_item.get("Product2") or {}
    return product_key(f"{product.get('Family') or ''} {product.get('Name') or ''}")


def booking_splits(opp):
    records = ((opp.get("OpportunityLineItems") or {}).get("records") or [])
    splits = defaultdict(float)
    for line_item in records:
        amount = line_item.get("TotalPrice")
        if amount is None:
            amount = (line_item.get("Quantity") or 0) * (line_item.get("UnitPrice") or 0)
        if amount:
            splits[line_product_key(line_item)] += float(amount)
    if splits:
        return splits.items()
    return [(product_key(opp.get("Product_Type__c")), float(opp.get("Amount") or 0))]


def fetch_billing_activity(base, headers, billing_opps):
    opp_ids = sorted({opp["Id"] for opp in billing_opps if opp.get("Id")})
    account_ids = sorted({opp["AccountId"] for opp in billing_opps if opp.get("AccountId")})

    def collect(object_name, fields, extra_where):
        records_by_id = {}
        filters = []
        for field_name, values in (("WhatId", opp_ids), ("AccountId", account_ids)):
            for batch in chunked(values):
                filters.append(f"{field_name} IN ({', '.join(sf_quote(value) for value in batch)})")
        for related_filter in filters:
            query = f"""
                SELECT {fields}
                FROM {object_name}
                WHERE CreatedDate >= {JULY_START_UTC}
                  AND CreatedDate < {AUGUST_START_UTC}
                  AND IsDeleted = false
                  AND {related_filter}
                  AND {extra_where}
                ORDER BY CreatedDate ASC
            """
            for record in sf_query(base, headers, query):
                records_by_id[record["Id"]] = record
        return list(records_by_id.values())

    meetings = collect(
        "Event",
        "Id, Subject, Type, CreatedDate, ActivityDate, StartDateTime, AccountId, WhatId, Owner.Name, "
        "Canceled_Meeting__c, Meeting_No_show__c",
        "Type != '10 - Internal Meeting / Training' "
        "AND (Canceled_Meeting__c = false OR Canceled_Meeting__c = null) "
        "AND (Meeting_No_show__c = false OR Meeting_No_show__c = null)",
    )
    calls = collect(
        "Task",
        "Id, Subject, Type, CreatedDate, ActivityDate, AccountId, WhatId, Owner.Name, CallDisposition",
        "Type = 'Call'",
    )
    return {"meetings": meetings, "calls": calls}


def activity_owner(record):
    owner = record.get("Owner") or {}
    return normalize_name(owner.get("Name") or "Unknown") if isinstance(owner, dict) else "Unknown"


def billing_line_for_activity(record, opp_by_id, products_by_account):
    opp = opp_by_id.get(record.get("WhatId") or "")
    if opp:
        return opp.get("Product_Type__c") or "Billing / Odin"
    products = products_by_account.get(record.get("AccountId") or "")
    if products:
        return " / ".join(sorted(products))
    return "Billing / Odin"


def empty_metric():
    return {"opps": 0, "closed": 0.0, "open": 0.0, "weighted": 0.0, "meetings": 0, "calls": 0}


def build_billing_metrics(opps, activity):
    billing_opps = [opp for opp in opps if product_key(opp.get("Product_Type__c")) == "Billing"]
    by_ae = defaultdict(empty_metric)
    by_sdr = defaultdict(empty_metric)
    by_line = defaultdict(empty_metric)
    opp_by_id = {opp["Id"]: opp for opp in billing_opps if opp.get("Id")}
    products_by_account = defaultdict(set)
    sdrs_by_account = defaultdict(set)

    for opp in billing_opps:
        amount = float(opp.get("Amount") or 0)
        is_closed = opp.get("StageName") == "Closed Won"
        probability = float(opp.get("Probability") or 0) / 100
        owner = normalize_name(opp.get("Owner") or "Unknown") or "Unknown"
        sdr = normalize_name(opp.get("SDR_Influence__c") or "")
        line = opp.get("Product_Type__c") or "Billing / Odin"
        account_id = opp.get("AccountId") or ""

        for bucket_name, bucket in ((owner, by_ae), (line, by_line)):
            bucket[bucket_name]["opps"] += 1
            if is_closed:
                bucket[bucket_name]["closed"] += amount
            else:
                bucket[bucket_name]["open"] += amount
                bucket[bucket_name]["weighted"] += amount * probability

        if sdr:
            by_sdr[sdr]["opps"] += 1
            if is_closed:
                by_sdr[sdr]["closed"] += amount
            else:
                by_sdr[sdr]["open"] += amount
                by_sdr[sdr]["weighted"] += amount * probability
            if account_id:
                sdrs_by_account[account_id].add(sdr)

        if account_id:
            products_by_account[account_id].add(line)

    for meeting in activity.get("meetings", []):
        owner = activity_owner(meeting)
        line = billing_line_for_activity(meeting, opp_by_id, products_by_account)
        by_ae[owner]["meetings"] += 1
        by_line[line]["meetings"] += 1
        for sdr in sorted(sdrs_by_account.get(meeting.get("AccountId") or "", [])):
            by_sdr[sdr]["meetings"] += 1

    for call in activity.get("calls", []):
        owner = activity_owner(call)
        line = billing_line_for_activity(call, opp_by_id, products_by_account)
        by_ae[owner]["calls"] += 1
        by_line[line]["calls"] += 1
        for sdr in sorted(sdrs_by_account.get(call.get("AccountId") or "", [])):
            by_sdr[sdr]["calls"] += 1

    return {
        "opps": billing_opps,
        "activity": activity,
        "by_ae": by_ae,
        "by_sdr": by_sdr,
        "by_line": by_line,
        "opp_count": len(billing_opps),
        "closed": sum(float(opp.get("Amount") or 0) for opp in billing_opps if opp.get("StageName") == "Closed Won"),
        "open": sum(float(opp.get("Amount") or 0) for opp in billing_opps if opp.get("StageName") != "Closed Won"),
        "meetings": len(activity.get("meetings", [])),
        "calls": len(activity.get("calls", [])),
    }


def load_metrics(opps):
    metrics = {
        key: {
            "closed": 0.0,
            "closed_count": 0,
            "open": 0.0,
            "open_count": 0,
            "weighted": 0.0,
        }
        for key, _, _ in PRODUCTS
    }
    rows = []

    for opp in opps:
        stage = opp.get("StageName") or ""
        if stage == "Closed Won":
            for key, amount in booking_splits(opp):
                if key not in metrics:
                    continue
                metrics[key]["closed"] += amount
                metrics[key]["closed_count"] += 1
                rows.append(
                    {
                        "product": key,
                        "account": opp.get("Account") or opp.get("Name") or "Unknown",
                        "name": opp.get("Name") or "",
                        "owner": opp.get("Owner") or "",
                        "amount": amount,
                        "close_date": opp.get("CloseDate") or "",
                    }
                )
        else:
            key = product_key(opp.get("Product_Type__c"))
            if key not in metrics:
                continue
            amount = float(opp.get("Amount") or 0)
            probability = float(opp.get("Probability") or 0) / 100
            metrics[key]["open"] += amount
            metrics[key]["open_count"] += 1
            metrics[key]["weighted"] += amount * probability

    rows.sort(key=lambda row: (row["product"], row["close_date"], -row["amount"]))
    return metrics, rows, len(opps)


def target_card(key, label, color, metrics):
    actual = metrics[key]["closed"]
    july_target = JULY_TARGETS[key]
    q3_target = Q3_TARGETS[key]
    july_pct = percent(actual, july_target)
    q3_pct = percent(actual, q3_target)
    remaining = max(july_target - actual, 0)
    return f"""
      <section class="target-card" style="--accent:{color}">
        <div class="card-head">
          <div>
            <div class="eyebrow">Product Line</div>
            <h2>{escape(label)}</h2>
          </div>
          <div class="pill">{metrics[key]['closed_count']} won</div>
        </div>
        <div class="metric-row">
          <span>July Closed Won MRR</span>
          <strong>{money(actual)}</strong>
        </div>
        <div class="bar-wrap">
          <div class="bar-label"><span>July Target</span><b>{july_pct:.1f}%</b></div>
          <div class="bar"><i style="width:{min(july_pct, 100):.1f}%"></i></div>
          <div class="bar-foot"><span>{money(actual)} / {money(july_target)}</span><span>{money(remaining)} left</span></div>
        </div>
        <div class="bar-wrap quarter">
          <div class="bar-label"><span>Q3 Target</span><b>{q3_pct:.1f}%</b></div>
          <div class="bar"><i style="width:{min(q3_pct, 100):.1f}%"></i></div>
          <div class="bar-foot"><span>{money(actual)} / {money(q3_target)}</span><span>Jul-Sep</span></div>
        </div>
        <div class="pipeline">
          <div><b>{money(metrics[key]['open'])}</b><span>Open July Pipeline</span></div>
          <div><b>{money(metrics[key]['weighted'])}</b><span>Weighted Pipeline</span></div>
          <div><b>{metrics[key]['open_count']}</b><span>Open Opps</span></div>
        </div>
      </section>"""


def summary_rows(metrics):
    rows = []
    for key, label, _ in PRODUCTS:
        actual = metrics[key]["closed"]
        rows.append(
            f"""
            <tr>
              <td><strong>{escape(label)}</strong><span>{metrics[key]['closed_count']} closed won · {metrics[key]['open_count']} open</span></td>
              <td>{money(JULY_TARGETS[key])}</td>
              <td>{money(actual)}</td>
              <td>{percent(actual, JULY_TARGETS[key]):.1f}%</td>
              <td>{money(Q3_TARGETS[key])}</td>
              <td>{percent(actual, Q3_TARGETS[key]):.1f}%</td>
              <td>{money(metrics[key]['open'])}</td>
            </tr>"""
        )
    return "\n".join(rows)


def closed_rows(rows):
    if not rows:
        return '<tr><td colspan="5" class="empty">No closed-won records found for these product lines.</td></tr>'
    label_map = {key: label for key, label, _ in PRODUCTS}
    return "\n".join(
        f"""
        <tr>
          <td>{escape(label_map[row['product']])}</td>
          <td><strong>{escape(row['account'])}</strong><span>{escape(row['name'])}</span></td>
          <td>{money(row['amount'])}</td>
          <td>{escape(row['owner'])}</td>
          <td>{escape(row['close_date'])}</td>
        </tr>"""
        for row in rows
    )


def billing_metric_rows(items, name_label):
    rows = []
    for name, values in sorted(
        items.items(),
        key=lambda item: (-(item[1]["closed"] + item[1]["open"]), -item[1]["opps"], item[0]),
    ):
        rows.append(
            f"""
            <tr>
              <td><strong>{escape(name)}</strong><span>{escape(name_label)}</span></td>
              <td>{values['opps']}</td>
              <td>{money(values['closed'])}</td>
              <td>{money(values['open'])}</td>
              <td>{money(values['weighted'])}</td>
              <td>{values['meetings']}</td>
              <td>{values['calls']}</td>
            </tr>"""
        )
    if not rows:
        return '<tr><td colspan="7" class="empty">No Billing/Odin activity found.</td></tr>'
    return "\n".join(rows)


def billing_activity_section(billing):
    return f"""
  <section class="section-head">
    <div><h2>Billing Product Line Activity</h2><p>Billing/Odin July opportunities plus July Salesforce meetings set and calls tied to those opportunities or accounts.</p></div>
  </section>
  <section class="billing-kpis">
    <div class="kpi" style="--accent:var(--cyan)"><span>Billing/Odin Opps</span><strong>{billing['opp_count']}</strong><em>{money(billing['closed'])} closed · {money(billing['open'])} open</em></div>
    <div class="kpi" style="--accent:var(--green)"><span>Meetings Set</span><strong>{billing['meetings']}</strong><em>non-internal, non-canceled Events</em></div>
    <div class="kpi" style="--accent:var(--violet)"><span>Billing Calls</span><strong>{billing['calls']}</strong><em>Salesforce call Tasks</em></div>
    <div class="kpi" style="--accent:var(--pink)"><span>Billing Pipeline</span><strong>{money(billing['open'])}</strong><em>{money(sum(v['weighted'] for v in billing['by_line'].values()))} weighted</em></div>
  </section>
  <section class="billing-grid">
    <div class="panel">
      <div class="mini-head">Billing Opportunities by Account Executive</div>
      <table class="activity-table">
        <thead><tr><th>Account Executive</th><th>Opps</th><th>Closed MRR</th><th>Open MRR</th><th>Weighted</th><th>Meetings</th><th>Calls</th></tr></thead>
        <tbody>{billing_metric_rows(billing['by_ae'], 'Owner / activity owner')}</tbody>
      </table>
    </div>
    <div class="panel">
      <div class="mini-head">Billing Opportunities by SDR</div>
      <table class="activity-table">
        <thead><tr><th>SDR</th><th>Opps</th><th>Closed MRR</th><th>Open MRR</th><th>Weighted</th><th>Meetings</th><th>Calls</th></tr></thead>
        <tbody>{billing_metric_rows(billing['by_sdr'], 'SDR Influence')}</tbody>
      </table>
    </div>
  </section>
  <section class="panel">
    <div class="mini-head">Billing Product Lines</div>
    <table class="activity-table">
      <thead><tr><th>Product Line</th><th>Opps</th><th>Closed MRR</th><th>Open MRR</th><th>Weighted</th><th>Meetings</th><th>Calls</th></tr></thead>
      <tbody>{billing_metric_rows(billing['by_line'], 'Product Type')}</tbody>
    </table>
  </section>"""


def build_html(opps, billing):
    metrics, rows, opp_count = load_metrics(opps)
    generated = datetime.now(ET)
    total_july_target = sum(JULY_TARGETS.values())
    total_q3_target = sum(Q3_TARGETS.values())
    total_actual = sum(metrics[key]["closed"] for key, _, _ in PRODUCTS)
    total_open = sum(metrics[key]["open"] for key, _, _ in PRODUCTS)
    cards = "\n".join(target_card(key, label, color, metrics) for key, label, color in PRODUCTS)

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>July and Q3 Product Sales Targets</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#02050b; --panel:#070b13; --panel2:#0c111c; --line:#1e2638; --text:#f4f7ff; --muted:#8d97bd; --soft:#58617f; --cyan:#2ee6be; --green:#50ff8a; --pink:#ff5d74; --violet:#7467ff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; min-height:100vh; color:var(--text); font-family:Inter,system-ui,sans-serif; background:radial-gradient(circle at 14% 0%,rgba(116,103,255,.34),transparent 430px),radial-gradient(circle at 88% 18%,rgba(46,230,190,.14),transparent 430px),linear-gradient(90deg,rgba(9,10,22,.98),rgba(2,8,9,.98) 58%,#020606),var(--bg); }}
body:before {{ content:""; position:fixed; inset:0; pointer-events:none; background:linear-gradient(rgba(255,255,255,.014) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.01) 1px,transparent 1px); background-size:92px 92px; opacity:.34; }}
.shell {{ position:relative; max-width:1500px; margin:0 auto; padding:26px 30px 44px; }}
.topbar {{ display:flex; justify-content:space-between; align-items:flex-start; gap:28px; padding-bottom:22px; }}
.brand {{ width:118px; height:auto; filter:drop-shadow(0 0 18px rgba(116,103,255,.28)); }}
.eyebrow {{ color:#9aa3cc; font-size:11px; font-weight:900; letter-spacing:2px; text-transform:uppercase; }}
h1 {{ margin:8px 0 0; max-width:900px; font-size:42px; line-height:1.02; letter-spacing:0; }}
.subhead {{ max-width:820px; margin-top:10px; color:var(--muted); line-height:1.45; font-size:14px; }}
.stamp {{ margin-top:8px; color:#737d9e; font-size:12px; line-height:1.5; text-align:right; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:6px 0 18px; }}
.kpi,.target-card,.panel {{ background:linear-gradient(180deg,rgba(12,17,28,.98),rgba(7,11,19,.99)); border:1px solid var(--line); border-radius:10px; box-shadow:0 22px 58px rgba(0,0,0,.42); }}
.kpi {{ padding:17px; border-top:3px solid var(--accent,var(--violet)); }}
.kpi span {{ display:block; color:var(--muted); font-size:10px; font-weight:900; letter-spacing:1.3px; text-transform:uppercase; }}
.kpi strong {{ display:block; margin-top:8px; font-size:30px; line-height:1; }}
.kpi em {{ display:block; margin-top:6px; color:var(--soft); font-size:12px; font-style:normal; }}
.cards {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }}
.target-card {{ padding:18px; border-top:4px solid var(--accent); }}
.card-head {{ display:flex; justify-content:space-between; gap:14px; align-items:flex-start; }}
h2 {{ margin:5px 0 0; font-size:24px; letter-spacing:0; }}
.pill {{ border:1px solid color-mix(in srgb, var(--accent) 38%, transparent); color:var(--accent); background:color-mix(in srgb, var(--accent) 12%, transparent); border-radius:999px; padding:5px 9px; font-size:10px; font-weight:900; text-transform:uppercase; letter-spacing:.9px; white-space:nowrap; }}
.metric-row {{ display:flex; justify-content:space-between; align-items:baseline; gap:18px; margin:22px 0 14px; padding-bottom:14px; border-bottom:1px solid rgba(255,255,255,.08); }}
.metric-row span {{ color:var(--muted); font-size:12px; font-weight:800; }}
.metric-row strong {{ color:var(--accent); font-size:30px; }}
.bar-wrap {{ margin-top:15px; }}
.bar-wrap.quarter {{ opacity:.9; }}
.bar-label,.bar-foot {{ display:flex; justify-content:space-between; gap:12px; align-items:center; }}
.bar-label span {{ color:var(--muted); font-size:10px; font-weight:900; letter-spacing:1.2px; text-transform:uppercase; }}
.bar-label b {{ color:var(--accent); font-size:12px; }}
.bar {{ height:8px; margin-top:7px; border-radius:999px; overflow:hidden; background:rgba(255,255,255,.08); }}
.bar i {{ display:block; height:100%; border-radius:999px; background:linear-gradient(90deg,var(--accent),#fff); }}
.bar-foot {{ margin-top:6px; color:var(--soft); font-size:11px; font-weight:700; }}
.pipeline {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:17px; }}
.pipeline div {{ padding:10px; border:1px solid rgba(255,255,255,.07); border-radius:8px; background:rgba(255,255,255,.025); min-height:68px; }}
.pipeline b {{ display:block; color:#fff; font-size:17px; }}
.pipeline span {{ display:block; margin-top:4px; color:var(--soft); font-size:10px; font-weight:800; line-height:1.25; text-transform:uppercase; letter-spacing:.8px; }}
.section-head {{ display:flex; justify-content:space-between; align-items:flex-end; gap:16px; margin:24px 0 10px; }}
.section-head h2 {{ margin:0; font-size:20px; }}
.section-head p {{ margin:5px 0 0; color:var(--muted); font-size:13px; }}
.panel {{ overflow:auto; }}
.billing-kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:0 0 14px; }}
.billing-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin-bottom:14px; }}
.mini-head {{ padding:13px 14px; border-bottom:1px solid rgba(255,255,255,.07); color:#fff; font-size:13px; font-weight:900; letter-spacing:.8px; text-transform:uppercase; }}
.activity-table {{ min-width:760px; }}
table {{ width:100%; border-collapse:collapse; min-width:980px; font-size:12px; }}
th,td {{ padding:11px 12px; border-bottom:1px solid rgba(255,255,255,.07); border-left:1px solid rgba(255,255,255,.045); text-align:right; white-space:nowrap; }}
th {{ background:#0c1322; color:#8d97bd; font-size:10px; font-weight:900; text-transform:uppercase; letter-spacing:1.1px; }}
th:first-child,td:first-child {{ text-align:left; border-left:0; }}
td:first-child {{ color:#fff; }}
td strong {{ color:#fff; }}
td span {{ display:block; margin-top:3px; color:var(--soft); font-size:10px; }}
.empty {{ color:var(--muted); text-align:center; }}
.note {{ margin-top:18px; color:var(--soft); font-size:12px; line-height:1.5; }}
@media(max-width:1100px) {{ .topbar {{ display:block; }} .brand {{ margin-bottom:14px; }} .stamp {{ text-align:left; }} .kpis,.cards,.billing-kpis,.billing-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
@media(max-width:740px) {{ .shell {{ padding:22px 16px 36px; }} h1 {{ font-size:32px; }} .kpis,.cards,.billing-kpis,.billing-grid,.pipeline {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div>
      <img class="brand" src="revio-logo-white.png" alt="Rev.io">
      <div class="eyebrow">Sales Targets</div>
      <h1>July and Q3 Product-Line Targets</h1>
      <p class="subhead">Closed-won MRR targets and current attainment for the requested product lines: PSA, Billing/Odin, and Cyber Protect. Q3 uses July through September targets; current Q3 actuals reflect July closed-won records in the Salesforce forecast export.</p>
    </div>
    <div class="stamp">Refreshed {generated.strftime('%b %-d, %Y %-I:%M %p ET')}<br>Source: Salesforce forecast export · {opp_count} July opportunities</div>
  </header>
  <section class="kpis">
    <div class="kpi" style="--accent:var(--green)"><span>July Target</span><strong>{money(total_july_target)}</strong><em>PSA + Billing/Odin + Cyber Protect</em></div>
    <div class="kpi" style="--accent:var(--cyan)"><span>July Actual</span><strong>{money(total_actual)}</strong><em>{percent(total_actual,total_july_target):.1f}% attainment</em></div>
    <div class="kpi" style="--accent:var(--violet)"><span>Q3 Target</span><strong>{money(total_q3_target)}</strong><em>July through September</em></div>
    <div class="kpi" style="--accent:var(--pink)"><span>Open July Pipeline</span><strong>{money(total_open)}</strong><em>Open MRR in these product lines</em></div>
  </section>
  <section class="cards">
    {cards}
  </section>
  <section class="section-head">
    <div><h2>Target Summary</h2><p>July and Q3 targets with current closed-won MRR attainment.</p></div>
  </section>
  <section class="panel">
    <table>
      <thead><tr><th>Product</th><th>July Target</th><th>July Actual</th><th>July Attainment</th><th>Q3 Target</th><th>Q3 Attainment</th><th>Open Pipeline</th></tr></thead>
      <tbody>{summary_rows(metrics)}</tbody>
    </table>
  </section>
  {billing_activity_section(billing)}
  <section class="section-head">
    <div><h2>Closed-Won Detail</h2><p>Closed-won July bookings included in the actuals above.</p></div>
  </section>
  <section class="panel">
    <table>
      <thead><tr><th>Product</th><th>Account / Opportunity</th><th>MRR</th><th>Owner</th><th>Close Date</th></tr></thead>
      <tbody>{closed_rows(rows)}</tbody>
    </table>
  </section>
  <p class="note">Target source: July and Q3 target values supplied on July 6, 2026. July Cyber Protect target combines CommerceHub/Cyber Protect under the Cyber Protect target bucket, matching the forecast configuration.</p>
</main>
</body>
</html>
"""
    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"Built {HTML_FILE.name}: {money(total_actual)} closed against {money(total_july_target)} July target.")


def update_library():
    row = (
        "| July/Q3 Product Sales Targets | sales-product-targets-july-q3.html | "
        "https://koontz-robin.github.io/robin-decks/sales-product-targets-july-q3.html | On demand |"
    )
    if not LIBRARY_FILE.exists():
        return
    text = LIBRARY_FILE.read_text(encoding="utf-8")
    if "sales-product-targets-july-q3.html" in text:
        return
    marker = "| 2026 Pipeline Pace | 2026-pipeline-pace.html | https://koontz-robin.github.io/robin-decks/2026-pipeline-pace.html | On demand |"
    if marker in text:
        text = text.replace(marker, f"{marker}\n{row}")
    else:
        text = text.rstrip() + "\n" + row + "\n"
    LIBRARY_FILE.write_text(text, encoding="utf-8")


def publish(files):
    subprocess.run(["git", "fetch", "robin-decks", "master"], cwd=WORKSPACE, check=True)
    tmp_parent = Path(tempfile.mkdtemp(prefix="sales-product-targets-"))
    worktree = tmp_parent / "worktree"
    try:
        subprocess.run(["git", "worktree", "add", str(worktree), "robin-decks/master"], cwd=WORKSPACE, check=True)
        for path in files:
            shutil.copy2(path, worktree / path.name)
        subprocess.run(["git", "add", *[path.name for path in files]], cwd=worktree, check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree)
        if diff.returncode == 0:
            print("No page changes to publish.")
            return
        stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
        subprocess.run(["git", "commit", "-m", f"add July Q3 product target page ({stamp})"], cwd=worktree, check=True)
        subprocess.run(["git", "push", "robin-decks", "HEAD:master"], cwd=worktree, check=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=WORKSPACE, check=False)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    print("Authenticating to Salesforce...")
    base, headers = sf_auth()
    print("Fetching current July opportunities...")
    opps = fetch_july_opportunities(base, headers)
    billing_opps = [opp for opp in opps if product_key(opp.get("Product_Type__c")) == "Billing"]
    print(f"Fetching Billing/Odin meetings and calls for {len(billing_opps)} July opportunities...")
    billing_activity = fetch_billing_activity(base, headers, billing_opps)
    print(
        f"Billing activity: {len(billing_activity['meetings'])} meetings set, "
        f"{len(billing_activity['calls'])} calls"
    )
    billing = build_billing_metrics(opps, billing_activity)
    build_html(opps, billing)
    update_library()
    if os.environ.get("NO_PUBLISH") == "1":
        print("NO_PUBLISH=1 set; skipping publish.")
        return
    publish([HTML_FILE, LIBRARY_FILE, Path(__file__)])
    print(f"Published https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")


if __name__ == "__main__":
    main()
