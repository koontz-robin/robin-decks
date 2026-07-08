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

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
HTML_FILE = WORKSPACE / "sales-product-targets-july-q3.html"
JULY_OPPS_FILE = WORKSPACE / "sf_july_opps.json"
LIBRARY_FILE = WORKSPACE / "DECKS-LIBRARY.md"
ET = ZoneInfo("America/New_York")

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


def load_metrics():
    opps = json.loads(JULY_OPPS_FILE.read_text(encoding="utf-8"))
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


def build_html():
    metrics, rows, opp_count = load_metrics()
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
table {{ width:100%; border-collapse:collapse; min-width:980px; font-size:12px; }}
th,td {{ padding:11px 12px; border-bottom:1px solid rgba(255,255,255,.07); border-left:1px solid rgba(255,255,255,.045); text-align:right; white-space:nowrap; }}
th {{ background:#0c1322; color:#8d97bd; font-size:10px; font-weight:900; text-transform:uppercase; letter-spacing:1.1px; }}
th:first-child,td:first-child {{ text-align:left; border-left:0; }}
td:first-child {{ color:#fff; }}
td strong {{ color:#fff; }}
td span {{ display:block; margin-top:3px; color:var(--soft); font-size:10px; }}
.empty {{ color:var(--muted); text-align:center; }}
.note {{ margin-top:18px; color:var(--soft); font-size:12px; line-height:1.5; }}
@media(max-width:1100px) {{ .topbar {{ display:block; }} .brand {{ margin-bottom:14px; }} .stamp {{ text-align:left; }} .kpis,.cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
@media(max-width:740px) {{ .shell {{ padding:22px 16px 36px; }} h1 {{ font-size:32px; }} .kpis,.cards,.pipeline {{ grid-template-columns:1fr; }} }}
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
    build_html()
    update_library()
    if os.environ.get("NO_PUBLISH") == "1":
        print("NO_PUBLISH=1 set; skipping publish.")
        return
    publish([HTML_FILE, LIBRARY_FILE, Path(__file__)])
    print(f"Published https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")


if __name__ == "__main__":
    main()
