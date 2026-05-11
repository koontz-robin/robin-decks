#!/usr/bin/env python3
"""Check Rev.io PSA Documentation Center release notes for new releases.

Outputs human-readable log followed by a marker line `---JSON---` and a JSON payload:
{
  "checked_at": "...Z",
  "new_count": 0,
  "new_releases": [{"version", "title", "url", "summary"}],
  "total_seen": 0
}
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE = "https://help.psarev.io"
NEWS_URL = f"{BASE}/en/news"
ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state.json"
UA = "OpenClaw psa-release-monitor/1.0"


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_items(page: str):
    items = []
    for m in re.finditer(r'<a class="news-item-v3" href="([^"]+)"', page):
        start = m.end()
        end = page.find("</a>", start)
        chunk = page[start:end if end != -1 else start + 20000]
        tm = re.search(r'font-semibold">(.*?)</div>', chunk, flags=re.S)
        if not tm:
            continue
        title = strip_tags(tm.group(1))
        vm = re.search(r"(\d{1,2}\.\d{1,2}\.\d{2})", title)
        version = vm.group(1) if vm else title
        items.append({
            "version": version,
            "title": title,
            "url": urljoin(BASE, html.unescape(m.group(1))),
        })
    return items


def extract_summary(detail_html: str) -> str:
    # Prefer the first substantive bullet under New Features / Updates / Bug Fixes.
    for li in re.findall(r'<li\b[^>]*>(.*?)</li>', detail_html, flags=re.S | re.I):
        text = strip_tags(li)
        if len(text) > 40:
            return text[:260].rstrip() + ("…" if len(text) > 260 else "")
    # Fallback to first paragraph.
    for p in re.findall(r'<p\b[^>]*>(.*?)</p>', detail_html, flags=re.S | re.I):
        text = strip_tags(p)
        if len(text) > 40 and "Check out the latest updates" not in text:
            return text[:260].rstrip() + ("…" if len(text) > 260 else "")
    return "New Rev.io PSA release notes are available."


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_state(state):
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp.replace(STATE_PATH)


def main() -> int:
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    state = load_state()
    seen = set(state.get("seen_releases", []))

    page = fetch(NEWS_URL)
    releases = parse_items(page)
    current_versions = [r["version"] for r in releases]
    # The site is reverse-chronological. Treat only releases appearing before the
    # first already-seen release as new; older backfill pages may not be present
    # in historical state and should not alert as "new".
    first_seen_index = next((i for i, r in enumerate(releases) if r["version"] in seen), None)
    if not seen:
        new = []  # initial baseline: do not spam the channel with all history
    elif first_seen_index is None:
        new = [r for r in releases if r["version"] not in seen]
    else:
        new = [r for r in releases[:first_seen_index] if r["version"] not in seen]

    for r in new:
        try:
            r["summary"] = extract_summary(fetch(r["url"]))
        except Exception as exc:
            r["summary"] = f"New Rev.io PSA release notes are available. (Summary fetch failed: {exc})"

    # Mark all currently listed releases as seen after a successful fetch/parse.
    if current_versions:
        save_state({"last_checked": checked_at, "seen_releases": current_versions})

    print(f"Checked {NEWS_URL} at {checked_at}")
    print(f"Found {len(releases)} releases; {len(new)} new")
    print("---JSON---")
    print(json.dumps({
        "checked_at": checked_at,
        "new_count": len(new),
        "new_releases": new,
        "total_seen": len(current_versions),
        "source": NEWS_URL,
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("---JSON---")
        print(json.dumps({"error": str(exc), "new_count": 0, "new_releases": []}))
        raise
