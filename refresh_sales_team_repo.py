#!/usr/bin/env python3
"""Daily refresh runner for the Sales Team Repo dashboards.

Refreshes the data-backed dashboards linked from sales-hub-index.html:
- forecast.html
- ae-capacity-dashboard.html
- psa-onboarding-tracker.html
- rep-coaching-dashboard.html

Static/internal enablement pages and the external Apollo 3 dashboard are checked
for reachability but not rebuilt.
"""

from __future__ import annotations

import calendar
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
LOG_DIR = WORKSPACE / "logs"
ET = ZoneInfo("America/New_York")

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"


def log(message: str) -> None:
    stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / "sales-team-repo-refresh.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(cmd: list[str], *, cwd: Path = WORKSPACE, env: dict[str, str] | None = None) -> str:
    log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout.strip():
        log(result.stdout.strip())
    if result.stderr.strip():
        log(f"stderr: {result.stderr.strip()}")
    if result.returncode:
        raise RuntimeError(f"{' '.join(cmd)} exited {result.returncode}")
    return result.stdout


def sf_auth() -> tuple[str, str]:
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
    payload = response.json()
    return payload["access_token"], payload["instance_url"]


def sf_query(instance: str, token: str, query: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{instance}/services/data/v59.0/query"
    params = {"q": query.strip()}
    records: list[dict] = []
    while True:
        response = requests.get(url, params=params, headers=headers, timeout=60)
        response.raise_for_status()
        payload = response.json()
        records.extend(payload.get("records", []))
        if payload.get("done", True):
            return records
        url = f"{instance}{payload['nextRecordsUrl']}"
        params = {}


def refresh_forecast() -> list[Path]:
    log("Refreshing forecast dashboard data")
    token, instance = sf_auth()
    now = datetime.now(ET)
    last_day = calendar.monthrange(now.year, now.month)[1]
    month_start = now.strftime("%Y-%m-01")
    month_end = now.strftime(f"%Y-%m-{last_day:02d}")
    month_slug = now.strftime("%B").lower()
    opp_file = WORKSPACE / f"sf_{month_slug}_opps.json"

    query = f"""
        SELECT Id, Name, StageName, Amount, Product_Type__c, Probability,
               CloseDate, Forecast_Status__c, Account.Name, Owner.Name,
               (SELECT Id, Quantity, UnitPrice, TotalPrice, Product2.Name, Product2.Family
                FROM OpportunityLineItems)
        FROM Opportunity
        WHERE CloseDate >= {month_start}
          AND CloseDate <= {month_end}
          AND StageName != 'Closed Lost'
        ORDER BY Amount DESC NULLS LAST
        LIMIT 500
    """
    records = sf_query(instance, token, query)
    for record in records:
        if isinstance(record.get("Account"), dict):
            record["Account"] = record["Account"].get("Name", "")
        if isinstance(record.get("Owner"), dict):
            record["Owner"] = record["Owner"].get("Name", "")

    opp_file.write_text(json.dumps(records, indent=2), encoding="utf-8")
    log(f"Wrote {opp_file.name} with {len(records)} opportunity records")
    run([sys.executable, str(WORKSPACE / "patch_may_forecast.py")])
    return [WORKSPACE / "forecast.html", opp_file]


def refresh_ae_capacity() -> list[Path]:
    log("Refreshing AE capacity dashboard")
    run([sys.executable, str(WORKSPACE / "refresh_ae_capacity.py")])
    return [WORKSPACE / "ae-capacity-dashboard.html"]


def refresh_rep_coaching() -> list[Path]:
    log("Refreshing rep coaching dashboard")
    run([sys.executable, str(WORKSPACE / "fetch_notion_coaching_v2.py")])
    run([sys.executable, str(WORKSPACE / "fetch_cbr_coaching.py")])
    run([sys.executable, str(WORKSPACE / "build_coaching_dashboard.py")])
    return [WORKSPACE / "rep-coaching-dashboard.html"]


def refresh_psa_onboarding() -> None:
    log("Refreshing PSA onboarding tracker")
    run([sys.executable, str(WORKSPACE / "build_psa_onboarding_tracker.py")])


def publish(files: list[Path]) -> None:
    existing = [path for path in files if path.exists()]
    if not existing:
        log("No files to publish")
        return

    log(f"Publishing {', '.join(path.name for path in existing)}")
    run(["git", "fetch", "robin-decks", "master"])
    tmp_parent = Path(tempfile.mkdtemp(prefix="sales-team-repo-publish."))
    worktree = tmp_parent / "worktree"
    try:
        run(["git", "worktree", "add", str(worktree), "robin-decks/master"])
        for path in existing:
            shutil.copy2(path, worktree / path.name)
        run(["git", "config", "user.name", "Robin"], cwd=worktree)
        run(["git", "config", "user.email", "robin@rev.io"], cwd=worktree)
        run(["git", "add", *[path.name for path in existing]], cwd=worktree)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree)
        if diff.returncode == 0:
            log("No publish changes")
            return
        stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
        run(["git", "commit", "-m", f"refresh sales team repo dashboards ({stamp})"], cwd=worktree)
        run(["git", "push", "robin-decks", "HEAD:master"], cwd=worktree)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=WORKSPACE, check=False)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def check_urls() -> None:
    urls = [
        "https://koontz-robin.github.io/robin-decks/battle-cards.html",
        "https://koontz-robin.github.io/robin-decks/demo-guide.html",
        "https://koontz-robin.github.io/robin-decks/beacon.html",
        "https://tony-kaylee.github.io/apollo3-reengagement-dashboard/",
    ]
    for url in urls:
        try:
            request = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(request, timeout=15) as response:
                log(f"Reachability OK: {url} ({response.status})")
        except Exception as exc:
            log(f"Reachability warning: {url} ({exc})")


def main() -> int:
    os.chdir(WORKSPACE)
    log("Starting Sales Team Repo refresh")
    publish_files: list[Path] = []
    errors: list[str] = []

    for label, task in [
        ("forecast", refresh_forecast),
        ("ae_capacity", refresh_ae_capacity),
        ("rep_coaching", refresh_rep_coaching),
    ]:
        try:
            publish_files.extend(task())
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            log(f"ERROR {label}: {exc}")

    try:
        publish(publish_files)
    except Exception as exc:
        errors.append(f"publish: {exc}")
        log(f"ERROR publish: {exc}")

    try:
        refresh_psa_onboarding()
    except Exception as exc:
        errors.append(f"psa_onboarding: {exc}")
        log(f"ERROR psa_onboarding: {exc}")

    check_urls()
    if errors:
        log("Completed with errors: " + "; ".join(errors))
        return 1
    log("Sales Team Repo refresh completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
