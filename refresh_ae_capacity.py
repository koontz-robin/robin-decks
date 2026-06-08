#!/usr/bin/env python3
"""Refresh AE capacity meeting data from Salesforce and rebuild the dashboard."""

import json
import subprocess
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
SF_INSTANCE = "https://rev-io.my.salesforce.com"
WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
DATA_FILE = Path("/tmp/ae_capacity_data.json")

AE_ROSTER = [
    "Jamie Butler",
    "Andy Whisenant",
    "Connor Flynn",
    "Jake Borah",
    "Husam Zalmiyar",
    "Patrick Davies",
    "Jaylin Bender",
]
NAME_ALIASES = {"Andrew Whisenant": "Andy Whisenant"}
QUERY_NAMES = sorted(set(AE_ROSTER) | set(NAME_ALIASES))
MONTHS = [
    ("jan", 2026, 1, "Jan"),
    ("feb", 2026, 2, "Feb"),
    ("mar", 2026, 3, "Mar"),
    ("apr", 2026, 4, "Apr"),
    ("may", 2026, 5, "May"),
    ("jun", 2026, 6, "Jun"),
]


def sf_auth():
    data = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": SF_CLIENT_ID,
            "client_secret": SF_CLIENT_SECRET,
        }
    ).encode()
    req = urllib.request.Request(
        f"{SF_INSTANCE}/services/oauth2/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read())
    return payload["access_token"], payload["instance_url"]


def soql(token, instance, query):
    encoded = urllib.parse.urlencode({"q": query})
    url = f"{instance}/services/data/v57.0/query?{encoded}"
    records = []
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = json.loads(response.read())
        records.extend(payload.get("records", []))
        next_url = payload.get("nextRecordsUrl")
        url = f"{instance}{next_url}" if next_url else None
    return records


def normalize_name(name):
    return NAME_ALIASES.get((name or "").strip(), (name or "").strip())


def month_bounds(year, month):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def biz_days(start, end):
    if end < start:
        return 0
    days = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


def get_month_data(token, instance, year, month, today):
    start, end = month_bounds(year, month)
    query_names = ", ".join(f"'{name}'" for name in QUERY_NAMES)
    query = f"""
        SELECT Id, ActivityDate, Owner.Name
        FROM Event
        WHERE ActivityDate >= {start.isoformat()}
          AND ActivityDate <= {end.isoformat()}
          AND IsDeleted = false
          AND Type IN (
            '1-Discovery Call',
            '2-Initial DEMO',
            '3-Follow Up DEMO / Meeting',
            '4-Pricing / Negotiation Call',
            'Tradeshow Meeting'
          )
          AND Appointment_Status__c = 'Completed'
          AND Owner.Name IN ({query_names})
    """
    by_rep = {rep: 0 for rep in AE_ROSTER}
    for record in soql(token, instance, query):
        owner = normalize_name((record.get("Owner") or {}).get("Name", ""))
        if owner in by_rep:
            by_rep[owner] += 1

    total = sum(by_rep.values())
    biz_total = biz_days(start, end)
    is_current = start <= today <= end
    if is_current:
        biz_done = biz_days(start, min(today, end))
        biz_remain = biz_days(today + timedelta(days=1), end)
        projected = round(total / max(biz_done, 1) * biz_total)
    else:
        biz_done = biz_total
        biz_remain = 0
        projected = total

    return {
        "total": total,
        "projected": projected,
        "biz": biz_total,
        "biz_done": biz_done,
        "biz_remain": biz_remain,
        "aes": len(AE_ROSTER),
        "by_rep": by_rep,
        "status": "current" if is_current else "final",
    }


def main():
    print("Authenticating with Salesforce...")
    token, instance = sf_auth()
    print("Salesforce auth OK")

    today = date.today()
    data = {
        "as_of": today.isoformat(),
        "ae_roster": AE_ROSTER,
        "months": {},
    }
    for key, year, month, label in MONTHS:
        print(f"Pulling {label} 2026 meetings...")
        data["months"][key] = get_month_data(token, instance, year, month, today)
        data["months"][key]["label"] = label
        data["months"][key]["year"] = year
        data["months"][key]["month"] = month

    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {DATA_FILE}")

    result = subprocess.run(
        ["python3", str(WORKSPACE / "build_ae_capacity.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print("STDERR:", result.stderr.strip())
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
