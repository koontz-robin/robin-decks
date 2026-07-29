#!/usr/bin/env python3
"""Build a report of Q3 2025 PSA Web closed-won clients that failed onboarding."""

import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from build_rep_activity_report import sf_auth, sf_query

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
HTML_FILE = WORKSPACE / "psa-web-q3-2025-failed-onboarding.html"
CSV_FILE = WORKSPACE / "psa_web_q3_2025_failed_onboarding.csv"
JSON_FILE = WORKSPACE / "psa_web_q3_2025_failed_onboarding.json"
ET = ZoneInfo("America/New_York")

PSA_DB_ID = "dba0a0aac29e42d7ac7e968e0245f4c4"
NOTION_TOKEN = "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"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

START_DATE = "2025-07-01"
END_DATE = "2025-09-30"


def money(value):
    return f"${float(value or 0):,.0f}"


def clean(value):
    return (value or "").strip()


def norm_name(value):
    text = clean(value).lower()
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"\b(incorporated|inc|llc|ltd|corp|corporation|company|co)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def sf_url(object_id):
    if not object_id:
        return ""
    object_name = "Opportunity" if object_id.startswith("006") else "Account"
    return f"https://rev-io.lightning.force.com/lightning/r/{object_name}/{object_id}/view"


def notion_text(prop):
    return "".join(t.get("plain_text", "") for t in (prop or {}).get("rich_text", []))


def notion_title(prop):
    return "".join(t.get("plain_text", "") for t in (prop or {}).get("title", []))


def notion_select(prop):
    return ((prop or {}).get("select") or {}).get("name", "")


def notion_status(prop):
    return ((prop or {}).get("status") or {}).get("name", "")


def notion_date(prop):
    return (((prop or {}).get("date") or {}).get("start") or "")[:10]


def failed_status(status, is_canceled):
    text = status.lower()
    return (
        is_canceled
        or text.startswith("canceled")
        or "cancel" in text
        or "unable" in text
        or "ghost" in text
    )


def fetch_closed_won_psa_web_clients(base, headers):
    query = f"""
        SELECT Id, Name, Amount, CloseDate, CreatedDate, Product_Type__c,
               Type, Lead_Direction__c, Opportunity_Source__c, Owner.Name,
               AccountId, Account.Name, Account.Tigerpaw__c,
               Account.TigerPaw_Type__c, Account.TigerPaw_Account_Status__c,
               Account.Churn_Reason__c, Account.Churn_Reason_Detail__c
        FROM Opportunity
        WHERE StageName = 'Closed Won'
          AND IsDeleted = false
          AND CloseDate >= {START_DATE}
          AND CloseDate <= {END_DATE}
          AND Product_Type__c IN ('PSA', 'PSA Web', 'PSA 2.0')
        ORDER BY CloseDate ASC, Account.Name ASC
    """
    records = sf_query(base, headers, query)
    client_map = {}
    for opp in records:
        account = opp.get("Account") or {}
        is_tigerpaw = bool(account.get("Tigerpaw__c")) if isinstance(account, dict) else False
        if is_tigerpaw:
            continue
        account_id = opp.get("AccountId") or ""
        key = account_id or norm_name((account or {}).get("Name") or opp.get("Name"))
        row = client_map.setdefault(
            key,
            {
                "account_id": account_id,
                "account": clean((account or {}).get("Name") or opp.get("Name")),
                "account_url": sf_url(account_id),
                "account_psa_status": clean((account or {}).get("TigerPaw_Account_Status__c")),
                "account_psa_type": clean((account or {}).get("TigerPaw_Type__c")),
                "account_churn_reason": clean((account or {}).get("Churn_Reason__c")),
                "account_churn_detail": clean((account or {}).get("Churn_Reason_Detail__c")),
                "opps": [],
                "closed_won_mrr": 0.0,
                "first_close_date": opp.get("CloseDate") or "",
                "last_close_date": opp.get("CloseDate") or "",
                "owners": set(),
                "products": set(),
            },
        )
        amount = float(opp.get("Amount") or 0)
        owner = clean(((opp.get("Owner") or {}).get("Name") if isinstance(opp.get("Owner"), dict) else ""))
        product = clean(opp.get("Product_Type__c"))
        row["closed_won_mrr"] += amount
        row["first_close_date"] = min(row["first_close_date"], opp.get("CloseDate") or row["first_close_date"])
        row["last_close_date"] = max(row["last_close_date"], opp.get("CloseDate") or row["last_close_date"])
        if owner:
            row["owners"].add(owner)
        if product:
            row["products"].add(product)
        row["opps"].append(
            {
                "id": opp.get("Id") or "",
                "name": clean(opp.get("Name")),
                "amount": amount,
                "close_date": opp.get("CloseDate") or "",
                "product_type": product,
                "owner": owner,
                "url": sf_url(opp.get("Id") or ""),
            }
        )
    for row in client_map.values():
        row["owners"] = sorted(row["owners"])
        row["products"] = sorted(row["products"])
        row["opps"].sort(key=lambda item: (item["close_date"], item["name"]))
    return sorted(client_map.values(), key=lambda row: (row["first_close_date"], row["account"]))


def fetch_onboarding_pages():
    pages = []
    has_more = True
    cursor = None
    while has_more:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        response = requests.post(
            f"https://api.notion.com/v1/databases/{PSA_DB_ID}/query",
            headers=NOTION_HEADERS,
            json=body,
            timeout=60,
        )
        if not response.ok:
            raise RuntimeError(f"Notion query failed: {response.status_code} {response.text[:500]}")
        payload = response.json()
        pages.extend(payload.get("results", []))
        has_more = payload.get("has_more", False)
        cursor = payload.get("next_cursor")
    rows = []
    status_counts = defaultdict(int)
    for page in pages:
        props = page.get("properties", {})
        name = notion_title(props.get("Client"))
        status = notion_status(props.get("Status"))
        is_canceled = (props.get("IsCanceled") or {}).get("number") == 1
        if status:
            status_counts[status] += 1
        rows.append(
            {
                "name": name,
                "norm": norm_name(name),
                "status": status,
                "is_canceled": is_canceled,
                "is_failed": failed_status(status, is_canceled),
                "sales_rep": notion_select(props.get("Sales Rep")),
                "solutions_analyst": notion_select(props.get("Solutions Analyst")),
                "fees_mrr": (props.get("Fees (MRR)") or {}).get("number") or 0,
                "date_sold": notion_date(props.get("Date Sold")),
                "date_canceled": notion_date(props.get("CancelRequestDate")) or notion_date(props.get("DateCanceled")),
                "onboarding_type": notion_select(props.get("Onboarding Type")),
                "notes": notion_text(props.get("Notes")),
                "rts_notes": notion_text(props.get("RTS Notes")),
                "url": f"https://www.notion.so/{page['id'].replace('-', '')}",
            }
        )
    return rows, dict(status_counts)


def match_onboarding(client, onboarding_rows):
    candidates = []
    names = {norm_name(client["account"])}
    for opp in client["opps"]:
        names.add(norm_name(opp["name"].replace(" - PSA", "").replace(" PSA", "")))
    for row in onboarding_rows:
        if row["norm"] in names:
            candidates.append(row)
            continue
        for name in names:
            if row["norm"] and name and (row["norm"] in name or name in row["norm"]):
                candidates.append(row)
                break
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            0 if row["is_failed"] else 1,
            row.get("date_canceled") or "9999-99-99",
            row.get("date_sold") or "9999-99-99",
        )
    )
    return candidates[0]


def build_rows(clients, onboarding_rows):
    rows = []
    matched_count = 0
    for client in clients:
        onboarding = match_onboarding(client, onboarding_rows)
        if onboarding:
            matched_count += 1
        if not onboarding or not onboarding["is_failed"]:
            continue
        notes = clean(onboarding.get("notes")) or clean(onboarding.get("rts_notes"))
        rows.append(
            {
                "client": client["account"],
                "closed_won_mrr": client["closed_won_mrr"],
                "first_close_date": client["first_close_date"],
                "last_close_date": client["last_close_date"],
                "opp_count": len(client["opps"]),
                "opportunity_names": "; ".join(opp["name"] for opp in client["opps"]),
                "opportunity_urls": "; ".join(opp["url"] for opp in client["opps"]),
                "owners": "; ".join(client["owners"]),
                "product_types": "; ".join(client["products"]),
                "sf_account_status": client["account_psa_status"],
                "sf_churn_reason": client["account_churn_reason"],
                "sf_churn_detail": client["account_churn_detail"],
                "onboarding_client_name": onboarding["name"],
                "onboarding_status": onboarding["status"],
                "onboarding_sales_rep": onboarding["sales_rep"],
                "solutions_analyst": onboarding["solutions_analyst"],
                "onboarding_mrr": onboarding["fees_mrr"],
                "date_sold_onboarding": onboarding["date_sold"],
                "date_canceled": onboarding["date_canceled"],
                "onboarding_type": onboarding["onboarding_type"],
                "notion_url": onboarding["url"],
                "notes": notes,
                "sf_account_url": client["account_url"],
            }
        )
    rows.sort(key=lambda row: (row["date_canceled"] or "9999-99-99", row["first_close_date"], row["client"]))
    return rows, matched_count


def write_csv(rows):
    fieldnames = [
        "client",
        "closed_won_mrr",
        "first_close_date",
        "last_close_date",
        "opp_count",
        "opportunity_names",
        "owners",
        "product_types",
        "sf_account_status",
        "sf_churn_reason",
        "sf_churn_detail",
        "onboarding_status",
        "onboarding_sales_rep",
        "solutions_analyst",
        "onboarding_mrr",
        "date_sold_onboarding",
        "date_canceled",
        "onboarding_type",
        "notes",
        "sf_account_url",
        "notion_url",
        "opportunity_urls",
    ]
    with CSV_FILE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def build_html(rows, total_clients, matched_count, status_counts):
    generated = datetime.now(ET)
    total_failed_mrr = sum(row["closed_won_mrr"] for row in rows)
    total_onboarding_mrr = sum(float(row.get("onboarding_mrr") or 0) for row in rows)
    by_status = defaultdict(lambda: {"count": 0, "mrr": 0.0})
    by_rep = defaultdict(lambda: {"count": 0, "mrr": 0.0})
    for row in rows:
        by_status[row["onboarding_status"] or "Unknown"]["count"] += 1
        by_status[row["onboarding_status"] or "Unknown"]["mrr"] += row["closed_won_mrr"]
        by_rep[row["owners"] or "Unknown"]["count"] += 1
        by_rep[row["owners"] or "Unknown"]["mrr"] += row["closed_won_mrr"]

    status_cards = "\n".join(
        f'<div class="chip"><span>{escape(status)}</span><strong>{vals["count"]}</strong><em>{money(vals["mrr"])}</em></div>'
        for status, vals in sorted(by_status.items(), key=lambda item: (-item[1]["count"], item[0]))
    )
    rep_rows = "\n".join(
        f"<tr><td>{escape(rep)}</td><td>{vals['count']}</td><td>{money(vals['mrr'])}</td></tr>"
        for rep, vals in sorted(by_rep.items(), key=lambda item: (-item[1]["mrr"], item[0]))
    )
    detail_rows = "\n".join(
        f"""
        <tr>
          <td><a href="{escape(row['sf_account_url'])}">{escape(row['client'])}</a><span>{escape(row['opportunity_names'])}</span></td>
          <td>{money(row['closed_won_mrr'])}</td>
          <td>{escape(row['first_close_date'])}</td>
          <td>{escape(row['owners'])}</td>
          <td>{escape(row['onboarding_status'] or 'Unknown')}<span>{escape(row['date_canceled'] or 'No cancel date')}</span></td>
          <td>{escape(row['solutions_analyst'] or 'Unassigned')}</td>
          <td>{escape(row['sf_churn_reason'] or '—')}<span>{escape(row['sf_churn_detail'] or '')}</span></td>
          <td><a href="{escape(row['notion_url'])}">Notion</a></td>
        </tr>"""
        for row in rows
    ) or '<tr><td colspan="8" class="empty">No failed-onboarding clients matched this filter.</td></tr>'

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Q3 2025 PSA Web Failed Onboarding Report</title>
<style>
:root {{ --bg:#06100d; --panel:#0d1714; --panel2:#111f1b; --line:#244137; --text:#f4fff9; --muted:#9ab5a9; --soft:#6f887c; --green:#4ade80; --cyan:#22d3ee; --red:#fb7185; --gold:#fbbf24; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; min-height:100vh; background:linear-gradient(135deg,#06100d 0%,#111827 54%,#10251f 100%); color:var(--text); font-family:Inter,Arial,sans-serif; }}
.shell {{ max-width:1440px; margin:0 auto; padding:28px; }}
.top {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-start; margin-bottom:22px; }}
.eyebrow {{ color:var(--green); font-size:11px; font-weight:900; letter-spacing:2px; text-transform:uppercase; }}
h1 {{ margin:8px 0 10px; font-size:40px; line-height:1.05; letter-spacing:0; }}
.sub {{ max-width:840px; color:var(--muted); font-size:14px; line-height:1.45; }}
.actions {{ display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end; }}
.btn {{ color:#06100d; background:var(--green); text-decoration:none; font-weight:900; border-radius:8px; padding:10px 12px; font-size:12px; }}
.btn.secondary {{ background:#dff7eb; }}
.stamp {{ margin-top:10px; text-align:right; color:var(--soft); font-size:12px; line-height:1.4; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:16px; }}
.kpi,.panel,.chip {{ background:linear-gradient(180deg,rgba(17,31,27,.98),rgba(13,23,20,.98)); border:1px solid var(--line); border-radius:10px; box-shadow:0 22px 52px rgba(0,0,0,.28); }}
.kpi {{ padding:16px; border-top:3px solid var(--accent,var(--green)); }}
.kpi span,.chip span {{ display:block; color:var(--muted); font-size:10px; font-weight:900; letter-spacing:1.2px; text-transform:uppercase; }}
.kpi strong {{ display:block; margin-top:8px; font-size:30px; line-height:1; }}
.kpi em,.chip em {{ display:block; color:var(--soft); font-style:normal; font-size:12px; margin-top:5px; }}
.chips {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin:0 0 16px; }}
.chip {{ padding:12px; }}
.chip strong {{ display:block; color:var(--red); font-size:24px; margin-top:5px; }}
.grid {{ display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:14px; align-items:start; }}
.panel {{ overflow:auto; }}
.panel h2 {{ margin:0; padding:14px; font-size:15px; border-bottom:1px solid var(--line); }}
table {{ width:100%; border-collapse:collapse; min-width:1060px; font-size:12px; }}
.side table {{ min-width:0; }}
th,td {{ padding:11px 12px; border-bottom:1px solid rgba(255,255,255,.07); text-align:right; white-space:nowrap; vertical-align:top; }}
th {{ color:var(--muted); background:#13231f; font-size:10px; letter-spacing:1px; text-transform:uppercase; }}
th:first-child,td:first-child {{ text-align:left; }}
td:first-child {{ font-weight:800; color:#fff; }}
td span {{ display:block; margin-top:3px; color:var(--soft); font-size:10px; font-weight:500; max-width:360px; white-space:normal; line-height:1.3; }}
a {{ color:#8ef7c0; }}
.empty {{ text-align:center; color:var(--muted); }}
.note {{ color:var(--soft); font-size:12px; line-height:1.5; margin-top:14px; }}
@media(max-width:1000px) {{ .top,.grid {{ display:block; }} .actions {{ justify-content:flex-start; margin-top:14px; }} .stamp {{ text-align:left; }} .kpis,.chips {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .side {{ margin-top:14px; }} }}
@media(max-width:640px) {{ .shell {{ padding:18px; }} h1 {{ font-size:30px; }} .kpis,.chips {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main class="shell">
  <header class="top">
    <div>
      <div class="eyebrow">Rev.io PSA Web</div>
      <h1>Q3 2025 Closed-Won Clients That Did Not Make It Through Onboarding</h1>
      <div class="sub">Closed-won Salesforce opportunities from {START_DATE} through {END_DATE}, limited to PSA-family product types and non-Tigerpaw accounts, matched to PSA onboarding records marked canceled, unable, or ghosted.</div>
    </div>
    <div>
      <div class="actions">
        <a class="btn" href="{CSV_FILE.name}">Download CSV</a>
        <a class="btn secondary" href="{JSON_FILE.name}">Download JSON</a>
      </div>
      <div class="stamp">Generated {generated.strftime('%b %-d, %Y %-I:%M %p ET')}<br>Source: Salesforce + PSA onboarding Notion DB</div>
    </div>
  </header>
  <section class="kpis">
    <div class="kpi" style="--accent:var(--cyan)"><span>Q3 2025 PSA Web Clients</span><strong>{total_clients}</strong><em>Closed won, non-Tigerpaw</em></div>
    <div class="kpi" style="--accent:var(--green)"><span>Matched To Onboarding</span><strong>{matched_count}</strong><em>Found by account/client name</em></div>
    <div class="kpi" style="--accent:var(--red)"><span>Failed Onboarding</span><strong>{len(rows)}</strong><em>Canceled / unable / ghosted</em></div>
    <div class="kpi" style="--accent:var(--gold)"><span>Closed-Won MRR</span><strong>{money(total_failed_mrr)}</strong><em>{money(total_onboarding_mrr)} in onboarding MRR fields</em></div>
  </section>
  <section class="chips">{status_cards}</section>
  <section class="grid">
    <div class="panel">
      <h2>Client Detail</h2>
      <table>
        <thead><tr><th>Client / Opportunity</th><th>Closed-Won MRR</th><th>Close Date</th><th>Owner</th><th>Onboarding Result</th><th>SA</th><th>SF Churn Reason</th><th>Record</th></tr></thead>
        <tbody>{detail_rows}</tbody>
      </table>
    </div>
    <div class="panel side">
      <h2>Closed-Won MRR by Owner</h2>
      <table>
        <thead><tr><th>Owner</th><th>Clients</th><th>MRR</th></tr></thead>
        <tbody>{rep_rows}</tbody>
      </table>
      <p class="note">Full notes, opportunity URLs, Notion URLs, and churn-detail fields are included in the CSV export.</p>
    </div>
  </section>
</main>
</body>
</html>
"""
    HTML_FILE.write_text(html, encoding="utf-8")
    JSON_FILE.write_text(
        json.dumps(
            {
                "generated_at": generated.isoformat(),
                "filter": {
                    "close_date_start": START_DATE,
                    "close_date_end": END_DATE,
                    "stage": "Closed Won",
                    "product_types": ["PSA", "PSA Web", "PSA 2.0"],
                    "psa_web_rule": "Account.Tigerpaw__c = false",
                    "failed_onboarding_rule": "Notion IsCanceled=1 OR Status contains cancel/unable/ghost",
                },
                "source_closed_won_clients": total_clients,
                "matched_onboarding_clients": matched_count,
                "failed_onboarding_clients": len(rows),
                "failed_closed_won_mrr": total_failed_mrr,
                "onboarding_status_counts_all_pages": status_counts,
                "rows": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def publish(files):
    subprocess.run(["git", "fetch", "robin-decks", "master"], cwd=WORKSPACE, check=True)
    tmp_parent = Path(tempfile.mkdtemp(prefix="psa-web-q3-failed-"))
    worktree = tmp_parent / "worktree"
    try:
        subprocess.run(["git", "worktree", "add", str(worktree), "robin-decks/master"], cwd=WORKSPACE, check=True)
        for path in files:
            shutil.copy2(path, worktree / path.name)
        subprocess.run(["git", "add", *[path.name for path in files]], cwd=worktree, check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree)
        if diff.returncode == 0:
            print("No report changes to publish.")
            return None
        stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
        subprocess.run(["git", "commit", "-m", f"add Q3 2025 PSA Web failed onboarding report ({stamp})"], cwd=worktree, check=True)
        subprocess.run(["git", "push", "robin-decks", "HEAD:master"], cwd=worktree, check=True)
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=worktree, text=True).strip()
        return commit
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=WORKSPACE, check=False)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    print("Authenticating to Salesforce...")
    base, headers = sf_auth()
    print("Fetching Q3 2025 closed-won PSA-family opportunities...")
    clients = fetch_closed_won_psa_web_clients(base, headers)
    print(f"Closed-won PSA Web clients after non-Tigerpaw filter: {len(clients)}")
    print("Fetching PSA onboarding records from Notion...")
    onboarding_rows, status_counts = fetch_onboarding_pages()
    print(f"Onboarding records scanned: {len(onboarding_rows)}")
    rows, matched_count = build_rows(clients, onboarding_rows)
    print(f"Matched onboarding records: {matched_count}")
    print(f"Failed onboarding clients: {len(rows)}")
    print(f"Failed closed-won MRR: {money(sum(row['closed_won_mrr'] for row in rows))}")
    write_csv(rows)
    build_html(rows, len(clients), matched_count, status_counts)
    if os.environ.get("NO_PUBLISH") == "1":
        print("NO_PUBLISH=1 set; skipping publish.")
        return
    commit = publish([HTML_FILE, CSV_FILE, JSON_FILE, Path(__file__)])
    if commit:
        print(f"Published commit {commit}")
    print(f"Report: https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")
    print(f"CSV: https://koontz-robin.github.io/robin-decks/{CSV_FILE.name}")


if __name__ == "__main__":
    main()
