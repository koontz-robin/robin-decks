#!/usr/bin/env python3
"""Build a Closed Won PSA/Billing meeting-count report from Salesforce."""

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from build_rep_activity_report import sf_auth, sf_query

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
HTML_FILE = WORKSPACE / "closed-won-meetings-report.html"
CSV_FILE = WORKSPACE / "closed_won_meetings_report.csv"
DATA_FILE = WORKSPACE / "closed_won_meetings_report.json"
ET = ZoneInfo("America/New_York")

EXCLUDED_EVENT_TYPES = {"10 - Internal Meeting / Training"}


def chunked(items, size=150):
    items = list(items)
    for index in range(0, len(items), size):
        yield items[index : index + size]


def sf_quote(value):
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def parse_sf_datetime(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(ET)


def product_bucket(value):
    text = (value or "").strip()
    lower = text.lower()
    if "psa" in lower:
        return "PSA"
    if "billing" in lower:
        return "Billing"
    return text or "Other"


def display_vertical(value):
    return (value or "Unknown").strip() or "Unknown"


def fetch_opportunities(base, headers):
    query = """
        SELECT Id, Name, Amount, Product_Type__c, Type, CreatedDate, CloseDate,
               AccountId, Account.Name, Account.Vertical__c, Owner.Name
        FROM Opportunity
        WHERE StageName = 'Closed Won'
          AND IsDeleted = false
          AND (Product_Type__c LIKE '%PSA%' OR Product_Type__c LIKE '%Billing%')
        ORDER BY CloseDate DESC, Name ASC
    """
    return sf_query(base, headers, query)


def fetch_events(base, headers, field, ids, start_date, end_date):
    events = []
    for batch in chunked(ids):
        id_list = ", ".join(sf_quote(value) for value in batch)
        query = f"""
            SELECT Id, Subject, Type, ActivityDate, StartDateTime, WhatId,
                   Canceled_Meeting__c, Meeting_No_show__c
            FROM Event
            WHERE {field} IN ({id_list})
              AND ActivityDate >= {start_date}
              AND ActivityDate <= {end_date}
              AND Type != '10 - Internal Meeting / Training'
              AND (Canceled_Meeting__c = false OR Canceled_Meeting__c = null)
              AND (Meeting_No_show__c = false OR Meeting_No_show__c = null)
              AND IsDeleted = false
            ORDER BY ActivityDate ASC
        """
        events.extend(sf_query(base, headers, query))
    return events


def event_date(event):
    if event.get("ActivityDate"):
        return datetime.strptime(event["ActivityDate"], "%Y-%m-%d").date()
    if event.get("StartDateTime"):
        return parse_sf_datetime(event["StartDateTime"]).date()
    return None


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[("Vertical", row["vertical"])].append(row)
        groups[("Product", row["product_bucket"])].append(row)
        groups[("Vertical/Product", f'{row["vertical"]} / {row["product_bucket"]}')].append(row)

    summary = []
    for (group_type, group_name), group_rows in sorted(groups.items()):
        counts = [row["meeting_count"] for row in group_rows]
        summary.append(
            {
                "group_type": group_type,
                "group": group_name,
                "closed_won_opps": len(group_rows),
                "avg_meetings": round(mean(counts), 2) if counts else 0,
                "median_meetings": sorted(counts)[len(counts) // 2] if counts else 0,
                "zero_meeting_opps": sum(1 for count in counts if count == 0),
            }
        )
    return summary


def money(value):
    return f"${float(value or 0):,.0f}"


def build_html(payload):
    rows = payload["rows"]
    summary = payload["summary"]
    generated = payload["generated_at_et"]
    vertical_focus = [
        item
        for item in summary
        if item["group_type"] == "Vertical" and item["group"].lower() in {"msp", "integrator"}
    ]
    vertical_cards = "\n".join(
        f"""
        <div class="kpi">
          <div class="label">{escape(item["group"])}</div>
          <div class="value">{item["avg_meetings"]:.2f}</div>
          <div class="sub">{item["closed_won_opps"]:,} opps · {item["zero_meeting_opps"]:,} with 0 logged meetings</div>
        </div>
        """
        for item in vertical_focus
    )
    if not vertical_cards:
        vertical_cards = '<div class="empty">No MSP or Integrator vertical rows found.</div>'

    summary_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(item["group_type"])}</td>
          <td>{escape(item["group"])}</td>
          <td>{item["closed_won_opps"]:,}</td>
          <td>{item["avg_meetings"]:.2f}</td>
          <td>{item["median_meetings"]}</td>
          <td>{item["zero_meeting_opps"]:,}</td>
        </tr>
        """
        for item in summary
    )

    detail_rows = "\n".join(
        f"""
        <tr>
          <td><strong>{escape(row["opportunity_name"])}</strong><small>{escape(row["account_name"])}</small></td>
          <td>{escape(row["owner"])}</td>
          <td>{escape(row["vertical"])}</td>
          <td>{escape(row["product_type"])}</td>
          <td>{escape(row["close_date"])}</td>
          <td>{money(row["amount"])}</td>
          <td class="num">{row["meeting_count"]}</td>
          <td>{escape(row["meeting_type_breakdown"])}</td>
        </tr>
        """
        for row in rows
    )

    total_opps = len(rows)
    avg_all = mean([row["meeting_count"] for row in rows]) if rows else 0
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Closed Won Meetings Report</title>
  <style>
    :root {{ --ink:#17231c; --muted:#65736b; --line:#dce6df; --panel:#fff; --paper:#f8fbf8; --green:#1f8f4d; --blue:#2f6fed; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:var(--paper); }}
    header {{ padding:28px 32px 18px; background:#fff; border-bottom:1px solid var(--line); }}
    .eyebrow {{ color:var(--green); font-size:12px; font-weight:850; letter-spacing:.08em; text-transform:uppercase; }}
    h1 {{ margin:8px 0; font-size:32px; line-height:1.08; }}
    .subhead {{ max-width:1040px; margin:0; color:var(--muted); font-size:14px; line-height:1.45; }}
    main {{ padding:24px 32px 40px; }}
    .kpis {{ display:grid; grid-template-columns:repeat(3, minmax(180px, 1fr)); gap:12px; margin-bottom:22px; }}
    .kpi {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }}
    .label {{ color:var(--muted); font-size:11px; font-weight:850; letter-spacing:.06em; text-transform:uppercase; }}
    .value {{ margin-top:7px; font-size:30px; font-weight:900; line-height:1; }}
    .sub {{ margin-top:6px; color:var(--muted); font-size:12px; }}
    section {{ margin-top:22px; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    .section-head {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-end; padding:18px; border-bottom:1px solid var(--line); }}
    h2 {{ margin:0; font-size:19px; }}
    .note {{ color:var(--muted); font-size:12px; line-height:1.4; max-width:700px; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
    th, td {{ padding:11px 12px; text-align:left; border-bottom:1px solid #edf2ee; vertical-align:top; font-size:13px; }}
    thead th {{ color:var(--muted); background:#f6faf7; font-size:11px; font-weight:850; letter-spacing:.06em; text-transform:uppercase; }}
    td small {{ display:block; margin-top:2px; color:var(--muted); font-size:11px; }}
    tbody tr:last-child td {{ border-bottom:none; }}
    .num {{ font-size:18px; font-weight:900; color:var(--blue); }}
    .empty {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; color:var(--muted); }}
    footer {{ margin-top:16px; color:var(--muted); font-size:11px; line-height:1.5; }}
    @media (max-width: 860px) {{ header, main {{ padding-left:16px; padding-right:16px; }} .kpis {{ grid-template-columns:1fr; }} table {{ min-width:980px; }} section {{ overflow-x:auto; }} }}
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">Salesforce Closed Won Analysis</div>
    <h1>Closed Won Meetings Report</h1>
    <p class="subhead">All Closed Won opportunities whose Product Type contains PSA or Billing. Logged meetings per deal include all non-internal, non-canceled Salesforce Event records associated to the account during the opportunity's CreatedDate-to-CloseDate window, plus any Events logged directly on the opportunity. Generated {escape(generated)}.</p>
  </header>
  <main>
    <div class="kpis">
      <div class="kpi"><div class="label">Closed Won Opps</div><div class="value">{total_opps:,}</div><div class="sub">PSA or Billing product type</div></div>
      <div class="kpi"><div class="label">Avg Meetings / Opp</div><div class="value">{avg_all:.2f}</div><div class="sub">All included verticals</div></div>
      {vertical_cards}
    </div>

    <section>
      <div class="section-head"><h2>Averages</h2><div class="note">Grouped by Vertical, Product, and Vertical/Product.</div></div>
      <table>
        <thead><tr><th>Group Type</th><th>Group</th><th>Closed Won Opps</th><th>Avg Meetings</th><th>Median</th><th>0 Meeting Opps</th></tr></thead>
        <tbody>{summary_rows}</tbody>
      </table>
    </section>

    <section>
      <div class="section-head"><h2>Opportunity Detail</h2><div class="note">CSV export: closed_won_meetings_report.csv.</div></div>
      <table>
        <thead><tr><th>Opportunity</th><th>Owner</th><th>Vertical</th><th>Product</th><th>Close Date</th><th>Amount</th><th>Meetings</th><th>Meeting Types</th></tr></thead>
        <tbody>{detail_rows}</tbody>
      </table>
    </section>
    <footer>Excluded event types: {escape(", ".join(sorted(EXCLUDED_EVENT_TYPES)))}. Canceled meetings and no-shows are excluded.</footer>
  </main>
</body>
</html>
"""


def main():
    base, headers = sf_auth()
    opps = fetch_opportunities(base, headers)
    if not opps:
        raise RuntimeError("No Closed Won PSA/Billing opportunities found.")

    opp_by_id = {opp["Id"]: opp for opp in opps}
    account_ids = sorted({opp.get("AccountId") for opp in opps if opp.get("AccountId")})
    opp_ids = sorted(opp_by_id)
    start_date = min(parse_sf_datetime(opp["CreatedDate"]).date() for opp in opps).isoformat()
    end_date = max(opp["CloseDate"] for opp in opps)

    account_id_events = fetch_events(base, headers, "AccountId", account_ids, start_date, end_date)
    account_what_events = fetch_events(base, headers, "WhatId", account_ids, start_date, end_date)
    opportunity_events = fetch_events(base, headers, "WhatId", opp_ids, start_date, end_date)

    events_by_account = defaultdict(list)
    for event in account_id_events:
        events_by_account[event.get("AccountId")].append(event)
    for event in account_what_events:
        events_by_account[event.get("WhatId")].append(event)
    events_by_opp = defaultdict(list)
    for event in opportunity_events:
        events_by_opp[event.get("WhatId")].append(event)

    rows = []
    for opp in opps:
        created_date = parse_sf_datetime(opp["CreatedDate"]).date()
        close_date = datetime.strptime(opp["CloseDate"], "%Y-%m-%d").date()
        seen_event_ids = set()
        matched_events = []
        for event in events_by_account.get(opp.get("AccountId"), []) + events_by_opp.get(opp["Id"], []):
            current_date = event_date(event)
            if not current_date or not (created_date <= current_date <= close_date):
                continue
            if event["Id"] in seen_event_ids:
                continue
            seen_event_ids.add(event["Id"])
            matched_events.append(event)

        type_counts = Counter(event.get("Type") or "Unknown" for event in matched_events)
        account = opp.get("Account") or {}
        owner = opp.get("Owner") or {}
        rows.append(
            {
                "opportunity_id": opp["Id"],
                "opportunity_name": opp.get("Name") or "",
                "account_name": account.get("Name") or "",
                "owner": owner.get("Name") or "",
                "vertical": display_vertical(account.get("Vertical__c")),
                "product_type": opp.get("Product_Type__c") or "",
                "product_bucket": product_bucket(opp.get("Product_Type__c")),
                "amount": opp.get("Amount") or 0,
                "created_date": created_date.isoformat(),
                "close_date": opp["CloseDate"],
                "meeting_count": len(matched_events),
                "meeting_type_breakdown": "; ".join(f"{name}: {count}" for name, count in sorted(type_counts.items())),
            }
        )

    payload = {
        "generated_at_et": datetime.now(ET).strftime("%B %-d, %Y %-I:%M %p ET"),
        "excluded_event_types": sorted(EXCLUDED_EVENT_TYPES),
        "rows": rows,
        "summary": summarize(rows),
        "source_counts": {
            "opportunities": len(opps),
            "account_id_events_fetched": len(account_id_events),
            "account_what_events_fetched": len(account_what_events),
            "opportunity_events_fetched": len(opportunity_events),
        },
    }

    DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HTML_FILE.write_text(build_html(payload), encoding="utf-8")
    with CSV_FILE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Fetched {len(opps):,} Closed Won PSA/Billing opportunities.")
    print(
        f"Fetched {len(account_id_events):,} AccountId-linked meetings, "
        f"{len(account_what_events):,} account WhatId-linked meetings, and "
        f"{len(opportunity_events):,} opportunity-linked meetings."
    )
    print(f"Wrote {HTML_FILE}")
    print(f"Wrote {CSV_FILE}")
    print(f"Wrote {DATA_FILE}")


if __name__ == "__main__":
    main()
