#!/usr/bin/env python3
"""Build the weekly Salesforce-backed sales manager inspection dashboard.

The reporting window is always Monday 00:00 America/New_York through the next
Monday. Opportunities are included when created during that window or when
Closed Lost with a CloseDate in that window. Records matching both are fetched
once and carry both inspection labels.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path(__file__).resolve().parent
OUTPUT_FILE = WORKSPACE / "sales-manager-inspection-dashboard.html"
SF_INSTANCE = os.getenv("SF_INSTANCE", "https://rev-io.my.salesforce.com")
SF_CLIENT_ID = os.getenv("SF_CLIENT_ID", "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N")
SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET", "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E")
SF_API_VERSION = "v59.0"
ET = ZoneInfo("America/New_York")

TEAMS: dict[str, list[str]] = {
    "Cam Sharpe": ["Jamie Butler", "Connor Flynn", "Jake Borah", "Patrick Davies"],
    "Bryan Bettiol": ["Joseph Abarno", "Andy Whisenant", "Jaylin Bender", "Abbey McIntosh"],
    "Reid Doster": ["Ingrid Beard", "Justin Lee", "Jakob Champion", "Katerra Stephenson-Greenwood"],
}
# Salesforce has historically used the formal first name for Andy.
OWNER_ALIASES = {"Andrew Whisenant": "Andy Whisenant", "Andy Whisenant": "Andy Whisenant"}
FIELDS = [
    "Id", "Name", "Account.Name", "Owner.Name", "CreatedDate", "CloseDate",
    "Marketing_Source__c", "Marketing_Sub_source__c", "Product_Type__c", "NextStep",
    "StageName", "Amount", "Business_Issue__c", "Business_Issue_Details__c",
    "Business_Issues__c", "Problems__c", "Values__c", "Loss_Reason__c",
    "Reason_Lost_Detail__c",
]


def sf_auth() -> tuple[str, dict[str, str]]:
    response = requests.post(
        f"{SF_INSTANCE}/services/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": SF_CLIENT_ID, "client_secret": SF_CLIENT_SECRET},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["instance_url"], {"Authorization": f"Bearer {payload['access_token']}"}


def sf_query(base: str, headers: dict[str, str], soql: str) -> list[dict[str, Any]]:
    url, params = f"{base}/services/data/{SF_API_VERSION}/query", {"q": soql}
    rows: list[dict[str, Any]] = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if not response.ok:
            raise RuntimeError(f"Salesforce query failed ({response.status_code}): {response.text[:1200]}\n{soql}")
        payload = response.json()
        rows.extend(payload.get("records", []))
        if payload.get("done", True):
            return rows
        url, params = base + payload["nextRecordsUrl"], {}


def current_week(now: datetime | None = None) -> tuple[datetime, datetime]:
    now_et = (now or datetime.now(ET)).astimezone(ET)
    monday = now_et.date() - timedelta(days=now_et.weekday())
    start = datetime.combine(monday, time.min, tzinfo=ET)
    return start, start + timedelta(days=7)


def sf_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def quote_soql(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def fetch_opportunities(base: str, headers: dict[str, str], start: datetime, end: datetime) -> list[dict[str, Any]]:
    sf_owners = sorted({rep for reps in TEAMS.values() for rep in reps} | set(OWNER_ALIASES))
    owners = ", ".join(quote_soql(name) for name in sf_owners)
    selected = ", ".join(FIELDS)
    start_utc, end_utc = sf_datetime(start), sf_datetime(end)
    # Separate queries avoid mixed Date/DateTime edge cases and make the inclusion rule auditable.
    created_soql = f"""SELECT {selected} FROM Opportunity
        WHERE Owner.Name IN ({owners})
          AND CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
        ORDER BY Owner.Name, CreatedDate, Name"""
    lost_soql = f"""SELECT {selected} FROM Opportunity
        WHERE Owner.Name IN ({owners}) AND StageName = 'Closed Lost'
          AND CloseDate >= {start.date().isoformat()} AND CloseDate < {end.date().isoformat()}
        ORDER BY Owner.Name, CloseDate, Name"""
    combined: dict[str, dict[str, Any]] = {}
    for kind, records in (("created", sf_query(base, headers, created_soql)), ("lost", sf_query(base, headers, lost_soql))):
        for record in records:
            opp_id = record["Id"]
            if opp_id not in combined:
                combined[opp_id] = record
                combined[opp_id]["_matches"] = []
            if kind not in combined[opp_id]["_matches"]:
                combined[opp_id]["_matches"].append(kind)
    return list(combined.values())


def nested_name(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return str(value.get("Name") or "") if isinstance(value, dict) else ""


def amount(row: dict[str, Any]) -> Decimal:
    try:
        return Decimal(str(row.get("Amount") or 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def money(value: Decimal) -> str:
    return f"${value:,.0f}"


def text(value: Any, fallback: str = "Not provided") -> str:
    value = str(value).strip() if value is not None else ""
    return escape(value) if value else f'<span class="empty">{escape(fallback)}</span>'


def fmt_created(value: Any) -> str:
    if not value:
        return "Not provided"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(ET)
        return parsed.strftime("%b %-d, %Y · %-I:%M %p ET")
    except ValueError:
        return str(value)


def fmt_date(value: Any) -> str:
    if not value:
        return "Not provided"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%b %-d, %Y")
    except ValueError:
        return str(value)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    created = [r for r in rows if "created" in r["_matches"]]
    lost = [r for r in rows if "lost" in r["_matches"]]
    return {
        "total": len(rows), "amount": sum((amount(r) for r in rows), Decimal(0)),
        "created": len(created), "created_amount": sum((amount(r) for r in created), Decimal(0)),
        "lost": len(lost), "lost_amount": sum((amount(r) for r in lost), Decimal(0)),
    }


def metric(label: str, value: str, note: str, cls: str = "") -> str:
    return f'<div class="metric {cls}"><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></div>'


def opportunity_card(row: dict[str, Any], base: str) -> str:
    matches = row["_matches"]
    badges = "".join(
        '<span class="badge created">Created This Week</span>' if kind == "created" else '<span class="badge lost">Closed Lost This Week</span>'
        for kind in matches
    )
    account = nested_name(row, "Account") or "No account"
    link = f"{base}/{row['Id']}"
    loss = ""
    if "lost" in matches:
        loss = f'''<section class="loss-panel"><h4>Loss inspection</h4><div class="field-grid">
          <div><label>Loss reason</label><p>{text(row.get('Loss_Reason__c'))}</p></div>
          <div><label>Reason lost detail</label><p>{text(row.get('Reason_Lost_Detail__c'))}</p></div>
        </div></section>'''
    fields = [
        ("Marketing source", row.get("Marketing_Source__c")), ("Marketing sub-source", row.get("Marketing_Sub_source__c")),
        ("Product type", row.get("Product_Type__c")), ("Next step", row.get("NextStep")),
        ("Business issue", row.get("Business_Issue__c")), ("Business issue details", row.get("Business_Issue_Details__c")),
        ("Business issues", row.get("Business_Issues__c")), ("Problems", row.get("Problems__c")), ("Values", row.get("Values__c")),
    ]
    field_html = "".join(f'<div><label>{escape(label)}</label><p>{text(value)}</p></div>' for label, value in fields)
    return f'''<article class="opportunity">
      <div class="opp-head"><div><div class="badges">{badges}</div><h3><a href="{escape(link)}" target="_blank" rel="noopener">{text(row.get('Name'), 'Unnamed opportunity')}</a></h3><p class="account">{escape(account)} · {text(nested_name(row, 'Owner'), 'No owner')}</p></div><div class="amount">{money(amount(row))}</div></div>
      <div class="quick"><span><b>Stage</b>{text(row.get('StageName'))}</span><span><b>Created</b>{escape(fmt_created(row.get('CreatedDate')))}</span><span><b>Close date</b>{escape(fmt_date(row.get('CloseDate')))}</span><a class="sf-link" href="{escape(link)}" target="_blank" rel="noopener">Open in Salesforce ↗</a></div>
      <div class="field-grid">{field_html}</div>{loss}
    </article>'''


def render_rep(rep: str, rows: list[dict[str, Any]], base: str) -> str:
    summary = summarize(rows)
    cards = "".join(opportunity_card(row, base) for row in sorted(rows, key=lambda r: ("lost" not in r["_matches"], r.get("CreatedDate") or ""), reverse=True))
    if not cards:
        cards = '<div class="zero-state"><b>No matching opportunities this week.</b><span>This rep is intentionally included for complete team inspection.</span></div>'
    return f'''<details class="rep"><summary><div><span class="rep-name">{escape(rep)}</span><span class="rep-count">{summary['total']} unique opportunities · {money(summary['amount'])}</span></div><div class="summary-pills"><span class="created">{summary['created']} created · {money(summary['created_amount'])}</span><span class="lost">{summary['lost']} lost · {money(summary['lost_amount'])}</span></div></summary><div class="rep-body">{cards}</div></details>'''


def build_html(rows: list[dict[str, Any]], base: str, start: datetime, end: datetime, generated: datetime) -> str:
    by_rep: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        owner = OWNER_ALIASES.get(nested_name(row, "Owner"), nested_name(row, "Owner"))
        by_rep[owner].append(row)
    total = summarize(rows)
    teams_html = []
    for manager, reps in TEAMS.items():
        team_rows = [row for rep in reps for row in by_rep[rep]]
        team = summarize(team_rows)
        reps_html = "".join(render_rep(rep, by_rep[rep], base) for rep in reps)
        teams_html.append(f'''<details class="manager" open><summary><div><span class="eyebrow">Sales manager</span><h2>{escape(manager)}</h2><span class="manager-sub">{len(reps)} reps · {team['total']} unique opportunities · {money(team['amount'])}</span></div><div class="summary-pills"><span class="created">{team['created']} created · {money(team['created_amount'])}</span><span class="lost">{team['lost']} lost · {money(team['lost_amount'])}</span></div></summary><div class="team-body">{reps_html}</div></details>''')
    range_text = f"{start.strftime('%A, %B %-d, %Y at 12:00 AM ET')} – {end.strftime('%A, %B %-d, %Y at 12:00 AM ET')} (end exclusive)"
    generated_text = generated.astimezone(ET).strftime("%A, %B %-d, %Y at %-I:%M %p ET")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sales Manager Inspection · Rev.io</title>
<style>
:root{{--bg:#07101d;--panel:#0e1a2b;--panel2:#132238;--line:#263954;--text:#f4f7fb;--muted:#9eafc5;--green:#55e09b;--green2:#153c32;--red:#ff7b88;--red2:#48212b;--blue:#69b7ff;--shadow:0 18px 45px rgba(0,0,0,.25)}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 12% -15%,#12355a 0,transparent 35%),var(--bg);color:var(--text);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}a{{color:var(--blue)}}.wrap{{max-width:1440px;margin:auto;padding:38px 24px 72px}}header{{display:flex;justify-content:space-between;gap:28px;align-items:flex-start;margin-bottom:24px}}.brand{{display:inline-flex;align-items:center;gap:9px;color:var(--green);font-weight:800;letter-spacing:.13em;text-transform:uppercase;font-size:12px}}.brand i{{width:12px;height:12px;border-radius:3px;background:var(--green);box-shadow:0 0 22px rgba(85,224,155,.7)}}h1{{font-size:clamp(30px,5vw,54px);line-height:1.02;margin:12px 0}}.lede{{max-width:760px;color:var(--muted);font-size:17px}}.stamp{{min-width:315px;background:rgba(14,26,43,.8);border:1px solid var(--line);padding:16px 18px;border-radius:14px;color:var(--muted)}}.stamp b{{display:block;color:var(--text);margin-bottom:5px}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}}.metric{{background:linear-gradient(145deg,var(--panel2),var(--panel));border:1px solid var(--line);padding:18px;border-radius:15px;box-shadow:var(--shadow)}}.metric span,.metric small{{display:block;color:var(--muted)}}.metric strong{{display:block;font-size:28px;margin:4px 0}}.metric.created{{border-top:3px solid var(--green)}}.metric.lost{{border-top:3px solid var(--red)}}.legend{{display:flex;gap:10px;align-items:center;color:var(--muted);margin:8px 0 20px;flex-wrap:wrap}}.badge,.summary-pills span{{display:inline-flex;border-radius:999px;font-weight:750;font-size:12px;padding:5px 10px}}.created{{color:#8af0bb;background:var(--green2)}}.lost{{color:#ffabb3;background:var(--red2)}}details{{border:1px solid var(--line);border-radius:16px;background:rgba(14,26,43,.88)}}summary{{cursor:pointer;list-style:none}}summary::-webkit-details-marker{{display:none}}summary:focus-visible{{outline:3px solid var(--blue);outline-offset:3px}}.manager{{margin:16px 0;box-shadow:var(--shadow);overflow:hidden}}.manager>summary{{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:21px 24px;background:linear-gradient(100deg,#142941,#0e1a2b)}}.manager>summary:before,.rep>summary:before{{content:'›';font-size:26px;color:var(--green);transition:.15s;order:-1}}details[open]>summary:before{{transform:rotate(90deg)}}.manager h2{{margin:0;font-size:23px}}.eyebrow{{color:var(--green);font-size:10px;letter-spacing:.15em;text-transform:uppercase;font-weight:800}}.manager-sub,.rep-count{{display:block;color:var(--muted);font-size:13px}}.summary-pills{{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}}.team-body{{padding:14px;background:#0a1422}}.rep{{margin:10px 0;background:var(--panel)}}.rep>summary{{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:12px;padding:16px 18px}}.rep-name{{font-size:17px;font-weight:800}}.rep-body{{padding:0 16px 16px}}.opportunity{{border:1px solid var(--line);border-radius:14px;padding:18px;margin:12px 0;background:#101f32}}.opp-head{{display:flex;justify-content:space-between;gap:18px}}.badges{{display:flex;gap:7px;flex-wrap:wrap}}.opp-head h3{{font-size:18px;margin:9px 0 2px}}.opp-head h3 a{{color:var(--text);text-decoration:none}}.opp-head h3 a:hover{{color:var(--green)}}.account{{margin:0;color:var(--muted)}}.amount{{font-size:23px;font-weight:850;white-space:nowrap}}.quick{{display:grid;grid-template-columns:1fr 1.35fr 1fr auto;gap:10px;margin:16px 0}}.quick span,.sf-link{{border:1px solid var(--line);border-radius:10px;padding:10px 12px;color:var(--text);text-decoration:none}}.quick b{{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.09em}}.sf-link{{display:flex;align-items:center;color:var(--blue);font-weight:700}}.field-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:11px;overflow:hidden}}.field-grid>div{{background:#0d1929;padding:12px}}label{{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;font-weight:800}}p{{margin:4px 0;white-space:pre-wrap;overflow-wrap:anywhere}}.empty{{color:#71839a;font-style:italic}}.loss-panel{{margin-top:12px;padding:13px;border:1px solid #753845;border-radius:12px;background:#261720}}.loss-panel h4{{margin:0 0 9px;color:#ffabb3}}.loss-panel .field-grid{{grid-template-columns:1fr 2fr;border-color:#5b303a;background:#5b303a}}.loss-panel .field-grid>div{{background:#261720}}.zero-state{{padding:26px;text-align:center;border:1px dashed #314966;border-radius:12px;color:var(--muted)}}.zero-state b,.zero-state span{{display:block}}.zero-state b{{color:var(--text);margin-bottom:4px}}footer{{color:var(--muted);margin-top:22px;text-align:center}}@media(max-width:900px){{header{{display:block}}.stamp{{margin-top:18px;min-width:0}}.metrics{{grid-template-columns:repeat(2,1fr)}}.quick{{grid-template-columns:1fr 1fr}}.field-grid{{grid-template-columns:1fr 1fr}}}}@media(max-width:620px){{.wrap{{padding:24px 13px 50px}}.metrics,.quick,.field-grid,.loss-panel .field-grid{{grid-template-columns:1fr}}.manager>summary,.rep>summary{{align-items:flex-start}}.summary-pills{{justify-content:flex-start}}.manager>summary{{display:grid;grid-template-columns:auto 1fr}}.manager>summary .summary-pills{{grid-column:2}}.rep>summary{{grid-template-columns:auto 1fr}}.rep>summary .summary-pills{{grid-column:2}}.opp-head{{display:block}}.amount{{margin-top:12px}}}}
</style></head><body><main class="wrap"><header><div><div class="brand"><i></i> Rev.io Sales Operations</div><h1>Sales Manager Inspection</h1><p class="lede">Weekly inspection of every team opportunity created this week, plus every opportunity closed lost this week. Expand a manager, then a rep, to review the full Salesforce record context.</p></div><aside class="stamp"><b>Inspection window</b>{escape(range_text)}<br><br><b>Generated</b>{escape(generated_text)}<br>Source: live Salesforce Opportunity data</aside></header>
<section class="metrics" aria-label="Dashboard totals">{metric('Unique opportunities', str(total['total']), money(total['amount']) + ' total amount')}{metric('Created This Week', str(total['created']), money(total['created_amount']) + ' created amount', 'created')}{metric('Closed Lost This Week', str(total['lost']), money(total['lost_amount']) + ' lost amount', 'lost')}{metric('Sales team coverage', '12 reps', '3 managers · zero-row reps included')}</section>
<div class="legend"><b>Inclusion:</b><span class="badge created">Created This Week</span><span class="badge lost">Closed Lost This Week</span><span>An opportunity matching both is counted once in “Unique opportunities” and tagged twice.</span></div>{''.join(teams_html)}<footer>Direct Salesforce links open in a new tab · Amounts are Opportunity Amount · Week boundaries use America/New_York</footer></main></body></html>'''


def main() -> None:
    start, end = current_week()
    generated = datetime.now(ET)
    print(f"Inspection window: {start.isoformat()} through {end.isoformat()} (exclusive)")
    base, headers = sf_auth()
    rows = fetch_opportunities(base, headers, start, end)
    html = build_html(rows, base, start, end, generated)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    total = summarize(rows)
    print(json.dumps({"output": str(OUTPUT_FILE), "unique": total["total"], "created": total["created"], "closed_lost": total["lost"], "amount": str(total["amount"])}, indent=2))
    for manager, reps in TEAMS.items():
        print(manager + ": " + ", ".join(f"{rep}={sum(1 for r in rows if OWNER_ALIASES.get(nested_name(r, 'Owner'), nested_name(r, 'Owner')) == rep)}" for rep in reps))


if __name__ == "__main__":
    main()
