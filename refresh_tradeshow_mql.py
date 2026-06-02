#!/usr/bin/env python3
"""Refresh and publish the Tradeshow MQL dashboard."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
HTML_FILE = WORKSPACE / "tradeshow-mql.html"
CONTACTS_FILE = WORKSPACE / "tradeshow_contacts.json"
OPPS_FILE = WORKSPACE / "tradeshow_opps.json"
HISTORY_FILE = WORKSPACE / "tradeshow_contact_status_history.json"
REBUILD_SCRIPT = WORKSPACE / "rebuild_tradeshow_final.py"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

ET = ZoneInfo("America/New_York")
YEAR_START_DATE = "2026-01-01"
YEAR_START_DT = "2026-01-01T00:00:00Z"


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


def write_json(path, records):
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def fetch_contacts(base, headers):
    query = f"""
        SELECT Id, FirstName, LastName, Email, Account.Name,
               MArketing_Lead_Source__c, Marketing_Sub_source__c, Owner.Name,
               CreatedDate, Most_Recent_Conversion__c, Tradeshow_Status__c,
               Contact_Status__c, Contact_Stage__c,
               (
                 SELECT Id, Name, StageName, Amount, CloseDate, CreatedDate,
                        Owner.Name, Product_Type__c
                 FROM Opportunities
                 WHERE CreatedDate >= {YEAR_START_DT}
               )
        FROM Contact
        WHERE MArketing_Lead_Source__c = 'Tradeshow'
        ORDER BY Most_Recent_Conversion__c DESC NULLS LAST, CreatedDate DESC
    """
    return sf_query(base, headers, query)


def fetch_opportunities(base, headers):
    query = f"""
        SELECT Id, Name, StageName, Amount, CloseDate, CreatedDate,
               Account.Name, Owner.Name, Marketing_Sub_source__c, Product_Type__c
        FROM Opportunity
        WHERE Marketing_Source__c = 'Tradeshow'
          AND CreatedDate >= {YEAR_START_DT}
        ORDER BY CreatedDate DESC
    """
    return sf_query(base, headers, query)


def publish(files):
    subprocess.run(["git", "fetch", "robin-decks", "master"], cwd=WORKSPACE, check=True)
    tmp_parent = Path(tempfile.mkdtemp(prefix="tradeshow-mql-"))
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
        subprocess.run(["git", "commit", "-m", f"refresh tradeshow MQL dashboard ({stamp})"], cwd=worktree, check=True)
        subprocess.run(["git", "push", "robin-decks", "HEAD:master"], cwd=worktree, check=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=WORKSPACE, check=False)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    print("Authenticating to Salesforce...")
    base, headers = sf_auth()
    print("Fetching tradeshow contacts...")
    contacts = fetch_contacts(base, headers)
    print(f"Fetched {len(contacts):,} contacts.")
    print("Fetching tradeshow opportunities...")
    opportunities = fetch_opportunities(base, headers)
    print(f"Fetched {len(opportunities):,} opportunities.")
    write_json(CONTACTS_FILE, contacts)
    write_json(OPPS_FILE, opportunities)

    print("Rebuilding dashboard...")
    subprocess.run([sys.executable, str(REBUILD_SCRIPT)], cwd=WORKSPACE, check=True)

    if os.environ.get("NO_PUBLISH") == "1":
        print("NO_PUBLISH=1 set; skipping GitHub Pages publish.")
        return

    publish([HTML_FILE, CONTACTS_FILE, OPPS_FILE, REBUILD_SCRIPT, Path(__file__)])
    print(f"Published https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
