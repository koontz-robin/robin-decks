#!/usr/bin/env python3
"""Build stale recycled MQL contact report from Salesforce.

Base population comes from the accessible Salesforce report
"Recycled MQL for Payment Team". The private report ID Ryan linked is not
available to the API integration, but this public report reproduces the same
recycled MQL filters documented on 2026-05-26.
"""

import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path(os.environ.get("ROBIN_WORKSPACE", "/home/openclaw/.openclaw/workspace"))
HTML_FILE = WORKSPACE / "recycled-mql-stale-contacts.html"
CSV_FILE = WORKSPACE / "recycled_mql_stale_contacts_45d_2026-06-02.csv"
DATA_FILE = WORKSPACE / "sf_recycled_mql_stale_contacts_45d.json"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
SOURCE_REPORT_ID = "00OPX000006L6DR2A0"
ET = ZoneInfo("America/New_York")


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
            raise RuntimeError(f"Salesforce query failed: {response.status_code} {response.text[:800]}")
        payload = response.json()
        records.extend(payload.get("records", []))
        if payload.get("done", True):
            return records
        url = base + payload["nextRecordsUrl"]
        params = {}


def chunks(items, size=100):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def parse_sf_datetime(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")


def fmt_dt(value):
    dt = parse_sf_datetime(value)
    if not dt:
        return ""
    return dt.astimezone(ET).strftime("%Y-%m-%d %I:%M %p ET")


def get_report_rows(base, headers):
    url = f"{base}/services/data/v59.0/analytics/reports/{SOURCE_REPORT_ID}"
    response = requests.get(url, headers=headers, params={"includeDetails": "true"}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    columns = payload["reportMetadata"]["detailColumns"]
    rows_by_id = {}
    for fact in payload.get("factMap", {}).values():
        for row in fact.get("rows") or []:
            cells = row.get("dataCells") or []
            if not cells:
                continue
            contact_id = cells[0].get("recordId")
            if not contact_id or contact_id in rows_by_id:
                continue
            values = {}
            for column, cell in zip(columns, cells):
                value = cell.get("label")
                values[column] = "" if value == "-" else (value or "")
                if column == "ACCOUNT.NAME":
                    values["AccountId"] = cell.get("value") or ""
            values["ContactId"] = contact_id
            rows_by_id[contact_id] = values
    return rows_by_id


def get_contacts(base, headers, contact_ids):
    contacts = {}
    fields = """
        Id, Name, FirstName, LastName, Email, Phone, MobilePhone, Title,
        LastActivityDate, MArketing_Lead_Source__c, Marketing_Sub_source__c,
        Contact_Stage__c, Contact_Status__c, Recycled_Reason__c,
        Most_Recent_Conversion__c, Owner.Name, Account.Id, Account.Name
    """
    for batch in chunks(contact_ids):
        id_list = "(" + ",".join(f"'{contact_id}'" for contact_id in batch) + ")"
        query = f"SELECT {fields} FROM Contact WHERE Id IN {id_list}"
        for record in sf_query(base, headers, query):
            contacts[record["Id"]] = record
    return contacts


def get_tasks(base, headers, contact_ids):
    tasks_by_contact = defaultdict(list)
    fields = """
        Id, WhoId, Subject, Type, TaskSubtype, ActivityDate, CreatedDate,
        Status, CallDisposition, Call_Disposition2__c, Call_Sentiment__c,
        Owner.Name
    """
    for batch in chunks(contact_ids):
        id_list = "(" + ",".join(f"'{contact_id}'" for contact_id in batch) + ")"
        query = f"""
            SELECT {fields}
            FROM Task
            WHERE WhoId IN {id_list}
              AND Status = 'Completed'
            ORDER BY CreatedDate DESC
        """
        for task in sf_query(base, headers, query):
            tasks_by_contact[task["WhoId"]].append(task)
    return tasks_by_contact


def is_contact_or_response(task):
    subject = task.get("Subject") or ""
    disposition = task.get("CallDisposition") or task.get("Call_Disposition2__c") or ""
    is_contact_call = task.get("TaskSubtype") == "Call" and (
        subject.startswith("Contact -") or disposition.startswith("Contact -")
    )
    is_inbound_email_response = task.get("TaskSubtype") == "Email" and "[In]" in subject
    return is_contact_call or is_inbound_email_response


def activity_label(task):
    if not task:
        return ""
    subject = task.get("Subject") or ""
    if task.get("TaskSubtype") == "Email" and "[In]" in (task.get("Subject") or ""):
        return "Email response"
    if subject.startswith("Contact -"):
        return subject
    return task.get("CallDisposition") or subject or "Contact call"


def account_url(account_id):
    return f"https://rev-io.lightning.force.com/lightning/r/Account/{account_id}/view" if account_id else ""


def contact_url(contact_id):
    return f"https://rev-io.lightning.force.com/lightning/r/Contact/{contact_id}/view"


def build_rows_html(rows):
    body = []
    for row in rows:
        body.append(
            f"""
            <tr>
              <td><a href="{escape(row['Contact Link'])}">{escape(row['Contact'])}</a><small>{escape(row['Title'])}</small></td>
              <td><a href="{escape(row['Account Link'])}">{escape(row['Account'])}</a><small>{escape(row['Account Owner'])}</small></td>
              <td>{escape(row['Email'])}<small>{escape(row['Phone'])}</small></td>
              <td>{escape(row['Marketing Sub-source'])}<small>{escape(row['Contact Stage'])} / {escape(row['Contact Status'])}</small></td>
              <td><strong>{escape(row['Last Activity Date'])}</strong><small>{escape(row['Last Activity Subject'])}</small></td>
              <td>{escape(row['Last Contact/Response Result'])}<small>{escape(row['Activity Owner'])}</small></td>
            </tr>"""
        )
    return "\n".join(body)


def build_html(payload):
    rows_html = build_rows_html(payload["matching_rows"])
    by_owner = Counter(row["Account Owner"] or "Unknown" for row in payload["matching_rows"])
    owner_rows = "\n".join(
        f"<tr><td>{escape(owner)}</td><td>{count}</td></tr>" for owner, count in by_owner.most_common()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Recycled MQL Stale Contacts</title>
  <style>
    :root {{ --ink:#102018; --muted:#637064; --line:#d9e5dd; --green:#24a148; --paper:#fbfdf9; --panel:#fff; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:var(--paper); }}
    header {{ padding:28px 32px 18px; background:#fff; border-bottom:1px solid var(--line); }}
    .eyebrow {{ color:var(--green); font-size:12px; font-weight:850; letter-spacing:.08em; text-transform:uppercase; }}
    h1 {{ margin:8px 0; font-size:31px; line-height:1.08; letter-spacing:0; }}
    .subhead {{ color:var(--muted); margin:0; font-size:14px; line-height:1.45; max-width:980px; }}
    main {{ padding:24px 32px 36px; }}
    .kpis {{ display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:12px; margin-bottom:22px; }}
    .kpi {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }}
    .kpi-label {{ color:var(--muted); font-size:11px; font-weight:850; text-transform:uppercase; letter-spacing:.06em; }}
    .kpi-value {{ margin-top:7px; font-size:28px; line-height:1; font-weight:850; }}
    .kpi-sub {{ color:var(--muted); font-size:12px; margin-top:5px; }}
    section {{ margin-top:22px; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    .section-head {{ padding:18px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:16px; align-items:end; }}
    h2 {{ margin:0; font-size:19px; letter-spacing:0; }}
    .note {{ color:var(--muted); font-size:12px; line-height:1.4; max-width:620px; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
    th, td {{ text-align:left; padding:11px 13px; border-bottom:1px solid #edf2ee; vertical-align:top; font-size:13px; }}
    thead th {{ color:var(--muted); background:#f7faf7; font-size:11px; font-weight:850; text-transform:uppercase; letter-spacing:.06em; }}
    tbody tr:last-child td {{ border-bottom:none; }}
    a {{ color:#166534; text-decoration:none; font-weight:800; }}
    small {{ display:block; color:var(--muted); margin-top:3px; font-size:11px; line-height:1.35; }}
    .owner-table {{ max-width:520px; }}
    footer {{ margin-top:16px; color:var(--muted); font-size:11px; line-height:1.5; }}
    @media (max-width:800px) {{ header, main {{ padding-left:16px; padding-right:16px; }} .kpis {{ grid-template-columns:1fr 1fr; }} table {{ min-width:980px; }} section {{ overflow-x:auto; }} }}
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">Salesforce Recycled MQL Report</div>
    <h1>Stale Contacts with Last Contact or Email Response</h1>
    <p class="subhead">Generated {escape(payload['generated_at_et'])}. Stale cutoff: no completed task activity since {escape(payload['cutoff_label'])}. Base source: Salesforce report "{escape(payload['source_report_name'])}".</p>
  </header>
  <main>
    <div class="kpis">
      <div class="kpi"><div class="kpi-label">Base Contacts</div><div class="kpi-value">{payload['base_contacts']}</div><div class="kpi-sub">from source report</div></div>
      <div class="kpi"><div class="kpi-label">No Activity 45d</div><div class="kpi-value">{payload['stale_contacts']}</div><div class="kpi-sub">latest completed task before cutoff</div></div>
      <div class="kpi"><div class="kpi-label">Matching Contacts</div><div class="kpi-value">{payload['matching_contacts']}</div><div class="kpi-sub">last activity is contact/response</div></div>
      <div class="kpi"><div class="kpi-label">Accounts</div><div class="kpi-value">{payload['matching_accounts']}</div><div class="kpi-sub">unique accounts represented</div></div>
    </div>
    <section class="owner-table">
      <div class="section-head"><h2>Matches by Account Owner</h2></div>
      <table><thead><tr><th>Owner</th><th>Contacts</th></tr></thead><tbody>{owner_rows}</tbody></table>
    </section>
    <section>
      <div class="section-head">
        <h2>Matching Contacts</h2>
        <div class="note">Included only when the most recent completed task is either a call whose result starts with "Contact -" or an inbound Outreach email response.</div>
      </div>
      <table>
        <thead><tr><th>Contact</th><th>Account</th><th>Email / Phone</th><th>Source / Stage</th><th>Last Activity</th><th>Last Contact/Response</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </section>
    <footer>Private linked report ID 00OPX000009Bjvv2AC is not accessible to the API integration, so this uses the accessible public report ID {SOURCE_REPORT_ID} with the same recycled MQL base filters.</footer>
  </main>
</body>
</html>
"""


def main():
    now_et = datetime.now(ET)
    cutoff_start_et = datetime.combine((now_et - timedelta(days=45)).date(), time.min, ET)
    base, headers = sf_auth()
    report_rows = get_report_rows(base, headers)
    contact_ids = list(report_rows)
    contacts = get_contacts(base, headers, contact_ids)
    tasks_by_contact = get_tasks(base, headers, contact_ids)

    output_rows = []
    stale_count = 0
    for contact_id in contact_ids:
        tasks = tasks_by_contact.get(contact_id, [])
        if not tasks:
            continue
        latest_task = max(tasks, key=lambda task: task.get("CreatedDate") or "")
        latest_dt = parse_sf_datetime(latest_task.get("CreatedDate"))
        if not latest_dt or latest_dt.astimezone(ET) >= cutoff_start_et:
            continue
        stale_count += 1
        if not is_contact_or_response(latest_task):
            continue

        contact = contacts.get(contact_id, {})
        report_row = report_rows.get(contact_id, {})
        account = contact.get("Account") or {}
        owner = contact.get("Owner") or {}
        task_owner = latest_task.get("Owner") or {}
        account_id = account.get("Id") or report_row.get("AccountId") or ""
        row = {
            "Contact": contact.get("Name") or f"{report_row.get('FIRST_NAME', '')} {report_row.get('LAST_NAME', '')}".strip(),
            "Title": contact.get("Title") or "",
            "Account": account.get("Name") or report_row.get("ACCOUNT.NAME", ""),
            "Account Owner": owner.get("Name") or report_row.get("OWNER_FULL_NAME", ""),
            "Email": contact.get("Email") or report_row.get("EMAIL", ""),
            "Phone": contact.get("Phone") or contact.get("MobilePhone") or report_row.get("PHONE1", "") or report_row.get("PHONE3", ""),
            "Marketing Source": contact.get("MArketing_Lead_Source__c") or report_row.get("Contact.MArketing_Lead_Source__c", ""),
            "Marketing Sub-source": contact.get("Marketing_Sub_source__c") or report_row.get("Contact.Marketing_Sub_source__c", ""),
            "Contact Stage": contact.get("Contact_Stage__c") or report_row.get("Contact.Contact_Stage__c", ""),
            "Contact Status": contact.get("Contact_Status__c") or report_row.get("Contact.Contact_Status__c", ""),
            "Recycled Reason": contact.get("Recycled_Reason__c") or report_row.get("Contact.Recycled_Reason__c", ""),
            "Most Recent Conversion": contact.get("Most_Recent_Conversion__c") or "",
            "Last Activity Date": fmt_dt(latest_task.get("CreatedDate")),
            "Last Activity Subject": latest_task.get("Subject") or "",
            "Last Contact/Response Result": activity_label(latest_task),
            "Activity Owner": task_owner.get("Name") or "",
            "Contact Link": contact_url(contact_id),
            "Account Link": account_url(account_id),
        }
        output_rows.append(row)

    output_rows.sort(key=lambda row: (row["Account Owner"], row["Account"], row["Contact"]))
    fieldnames = [
        "Contact",
        "Title",
        "Account",
        "Account Owner",
        "Email",
        "Phone",
        "Marketing Source",
        "Marketing Sub-source",
        "Contact Stage",
        "Contact Status",
        "Recycled Reason",
        "Most Recent Conversion",
        "Last Activity Date",
        "Last Activity Subject",
        "Last Contact/Response Result",
        "Activity Owner",
        "Contact Link",
        "Account Link",
    ]
    with CSV_FILE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    payload = {
        "generated_at_et": now_et.strftime("%B %-d, %Y %-I:%M %p ET"),
        "cutoff_label": cutoff_start_et.strftime("%B %-d, %Y"),
        "source_report_id": SOURCE_REPORT_ID,
        "source_report_name": "Recycled MQL for Payment Team",
        "base_contacts": len(contact_ids),
        "stale_contacts": stale_count,
        "matching_contacts": len(output_rows),
        "matching_accounts": len({row["Account Link"] for row in output_rows if row["Account Link"]}),
        "matching_rows": output_rows,
    }
    DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HTML_FILE.write_text(build_html(payload), encoding="utf-8")
    print(f"Base contacts: {len(contact_ids)}")
    print(f"No activity in last 45 days: {stale_count}")
    print(f"Matching contacts: {len(output_rows)}")
    print(f"Wrote {HTML_FILE}")
    print(f"Wrote {CSV_FILE}")
    print(f"Wrote {DATA_FILE}")


if __name__ == "__main__":
    main()
