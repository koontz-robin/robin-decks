#!/usr/bin/env python3
"""Build the first commissions/quota tracker view from live Salesforce data."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from difflib import SequenceMatcher
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from build_2026_psa_team_tracker import sf_auth, sf_query

ROOT = Path(__file__).resolve().parent
YEAR = 2026
ET = ZoneInfo("America/New_York")
HTML_PATH = ROOT / "commissions-quota-tracker.html"
JSON_PATH = ROOT / "commissions_quota_tracker.json"
SF_BASE = "https://rev-io.my.salesforce.com"
ONBOARDING_APIS = {
    "New Rev.io": "https://green-river-03f870c10.4.azurestaticapps.net/api/forecast?lob=psa",
    "Classic Rev.io": "https://green-river-03f870c10.4.azurestaticapps.net/api/forecast?lob=billing",
}
AE_ROSTER = [
    ("Jamie Butler", "Jamie Butler"),
    ("Connor Flynn", "Connor Flynn"),
    ("Andy Whisenant", "Andy Whisenant"),
    ("Jaylin Bender", "Jaylin Bender"),
    ("Jake Borah", "Jake Borah"),
    ("Patrick Davies", "Patrick Davies"),
    ("Abbey McIntosh", "Abbey McIntosh"),
    ("Joseph Abarno", "Joe Abarno"),
]


def money(value):
    return f"${float(value or 0):,.0f}"


def normalize_company(value):
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    value = re.sub(r"\[[^]]*]|\([^)]*(?:psa|web|guided|hybrid|self.?serve)[^)]*\)", " ", value)
    value = re.sub(r"\b(?:psa|web|guided|hybrid|self.?serve|new opportunity|add.?on|expansion)\b", " ", value)
    value = re.sub(r"\b(?:incorporated|corporation|company|limited|inc|corp|co|llc|ltd)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def fetch_onboarding_clients():
    clients = []
    sync_times = {}
    for lob, url in ONBOARDING_APIS.items():
        response = requests.get(url, timeout=90)
        response.raise_for_status()
        data = response.json()
        sync_times[lob] = data.get("latestSync")
        for client in data.get("statusClients") or []:
            clients.append({**client, "_lob": lob})
    return clients, sync_times


def match_onboarding(opp, clients):
    targets = {normalize_company(opp.get("account")), normalize_company(opp.get("name"))}
    targets.discard("")
    owner_aliases = {opp.get("rep"), "Andrew Whisenant" if opp.get("rep") == "Andy Whisenant" else None}
    owner_aliases.discard(None)
    close_date = date.fromisoformat(opp["close_date"])
    scored = []
    for client in clients:
        candidate = normalize_company(client.get("name"))
        if not candidate:
            continue
        name_score = max((SequenceMatcher(None, target, candidate).ratio() for target in targets), default=0)
        exact = candidate in targets
        rep_match = not client.get("salesRep") or client.get("salesRep") in owner_aliases
        sold_delta = 9999
        if client.get("dateSold"):
            try:
                sold_delta = abs((date.fromisoformat(client["dateSold"]) - close_date).days)
            except ValueError:
                pass
        if not exact:
            if name_score < 0.88 or not rep_match or (client.get("dateSold") and sold_delta > 45):
                continue
        score = name_score + (0.18 if exact else 0) + (0.08 if rep_match else -0.12) + (0.08 if sold_delta <= 14 else 0)
        scored.append((score, exact, -sold_delta, client))
    if not scored:
        return None, None
    scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    best = scored[0]
    if best[0] < 0.86:
        return None, None
    confidence = "Exact" if best[1] else "Fuzzy"
    return best[3], confidence


def main():
    base, headers = sf_auth()
    users = sf_query(base, headers, """
        SELECT Id, Name, Title, UserRole.Name
        FROM User
        WHERE IsActive = true
          AND UserRole.Name IN ('MSP Sales', 'Integrator Sales')
        ORDER BY Name
    """)
    users_by_name = {user.get("Name"): user for user in users}
    missing = [sf_name for sf_name, _ in AE_ROSTER if sf_name not in users_by_name]
    if missing:
        raise RuntimeError(f"Configured active AEs missing from Salesforce: {', '.join(missing)}")
    reps = []
    for sf_name, display_name in AE_ROSTER:
        user = users_by_name[sf_name]
        role = ((user.get("UserRole") or {}).get("Name") or "").replace(" Sales", "")
        title = "Strategic Account Executive" if display_name in {"Jamie Butler", "Joe Abarno"} else "Commercial Account Executive"
        reps.append({"id": user.get("Id"), "name": display_name, "sf_name": sf_name, "title": title, "team": role})
    names = [r["sf_name"] for r in reps]
    quoted = ", ".join("'" + n.replace("'", "\\'") + "'" for n in names)
    opps = sf_query(base, headers, f"""
        SELECT Id, Name, Amount, CloseDate, CreatedDate, Type, Product_Type__c,
               Account.Name, Owner.Name
        FROM Opportunity
        WHERE IsDeleted = false
          AND StageName = 'Closed Won'
          AND CloseDate >= {YEAR}-01-01
          AND CloseDate < {YEAR + 1}-01-01
          AND Owner.Name IN ({quoted})
        ORDER BY Owner.Name, CloseDate DESC, Amount DESC NULLS LAST
    """)
    onboarding_clients, onboarding_sync = fetch_onboarding_clients()
    grouped = defaultdict(list)
    onboarding_counts = defaultdict(int)
    for opp in opps:
        owner = (opp.get("Owner") or {}).get("Name") or "Unassigned"
        owner_display = "Joe Abarno" if owner == "Joseph Abarno" else owner
        detail = {
            "id": opp.get("Id"),
            "rep": owner_display,
            "name": opp.get("Name") or "Untitled opportunity",
            "account": (opp.get("Account") or {}).get("Name") or "—",
            "amount": float(opp.get("Amount") or 0),
            "close_date": opp.get("CloseDate") or "",
            "product": opp.get("Product_Type__c") or "—",
            "type": opp.get("Type") or "—",
        }
        client, match_confidence = match_onboarding(detail, onboarding_clients)
        source_status = (client or {}).get("status") or "Not found"
        status_lower = source_status.lower()
        if status_lower.startswith("activated"):
            commission_state = "Released"
        elif status_lower.startswith("cancelled") or status_lower.startswith("canceled"):
            commission_state = "Not payable"
        elif client:
            commission_state = "Pending"
        else:
            commission_state = "Unmatched"
        detail.update({
            "onboarding_status": source_status,
            "commission_state": commission_state,
            "activation_date": (client or {}).get("activationDate"),
            "canceled_date": (client or {}).get("dateCanceled"),
            "onboarding_name": (client or {}).get("name"),
            "onboarding_lob": (client or {}).get("_lob"),
            "onboarding_url": (client or {}).get("wrikeUrl") or (client or {}).get("notionUrl"),
            "onboarding_match": match_confidence,
        })
        onboarding_counts[commission_state] += 1
        grouped[owner].append(detail)
    generated = datetime.now(ET)
    payload = {"generated_at_et": generated.isoformat(), "onboarding_synced_at": onboarding_sync, "year": YEAR, "onboarding_summary": dict(onboarding_counts), "reps": []}
    for rep in reps:
        wins = grouped.get(rep["sf_name"], [])
        payload["reps"].append({**rep, "opportunity_count": len(wins), "closed_won": sum(x["amount"] for x in wins), "opportunities": wins})
    JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n")

    rep_rows = []
    state_order = {"Released": 0, "Pending": 1, "Not payable": 2, "Unmatched": 3}
    for i, rep in enumerate(payload["reps"]):
        status_groups = defaultdict(list)
        for opportunity in rep["opportunities"]:
            status_groups[opportunity["onboarding_status"]].append(opportunity)
        detail_parts = []
        for status, opportunities in sorted(
            status_groups.items(),
            key=lambda item: (state_order.get(item[1][0]["commission_state"], 9), item[0].lower()),
        ):
            commission_state = opportunities[0]["commission_state"]
            badge_class = commission_state.lower().replace(" ", "-")
            detail_parts.append(
                f'''<tr class="status-group"><td colspan="6"><span class="status-title">{escape(status)}</span><span class="status-count">{len(opportunities)} deal{'s' if len(opportunities) != 1 else ''}</span><span class="badge {badge_class}">{escape(commission_state)}</span></td></tr>'''
            )
            detail_parts.extend(
                f'''<tr class="deal-row"><td><a href="{SF_BASE}/{escape(o['id'])}" target="_blank" rel="noopener">{escape(o['name'])}</a><span>{escape(o['account'])}</span></td><td>{escape(o['product'])}</td><td>{escape(o['close_date'])}</td><td>{f'<a href="{escape(o["onboarding_url"])}" target="_blank" rel="noopener">{escape(o["onboarding_status"])}</a>' if o.get('onboarding_url') else escape(o['onboarding_status'])}<span>{escape(o.get('onboarding_name') or 'No onboarding match')}{' · ' + escape(o['onboarding_lob']) if o.get('onboarding_lob') else ''}</span></td><td><span class="badge {o['commission_state'].lower().replace(' ', '-')}">{escape(o['commission_state'])}</span></td><td class="money">{money(o['amount'])}</td></tr>'''
                for o in opportunities
            )
        detail_rows = "".join(detail_parts) or '<tr><td colspan="6" class="empty">No Closed Won opportunities in 2026.</td></tr>'
        rep_rows.append(f'''
        <section class="rep-card" data-name="{escape(rep['name'].lower())}">
          <button class="rep-summary" type="button" aria-expanded="false" aria-controls="rep-{i}">
            <span class="chevron">›</span><span class="identity"><strong>{escape(rep['name'])}</strong><small>{escape(rep['team'])} · {escape(rep['title'])}</small></span>
            <span class="metric"><small>Closed Won</small><strong>{money(rep['closed_won'])}</strong></span>
            <span class="metric"><small>Opportunities</small><strong>{rep['opportunity_count']}</strong></span>
          </button>
          <div class="details" id="rep-{i}" hidden><div class="table-wrap"><table><thead><tr><th>Opportunity / Account</th><th>Product</th><th>Close date</th><th>Onboarding status</th><th>Commission</th><th>Amount</th></tr></thead><tbody>{detail_rows}</tbody></table></div></div>
        </section>''')

    total = sum(r["closed_won"] for r in payload["reps"])
    count = sum(r["opportunity_count"] for r in payload["reps"])
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AE Commissions & Quota Tracker</title>
<style>
:root{{--navy:#07192d;--panel:#0d2742;--line:#24445f;--cyan:#3ee0d0;--blue:#65a9ff;--text:#f3f8fd;--muted:#9eb1c5;--green:#72e6a2}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 85% 0,#123e62 0,transparent 35%),var(--navy);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}main{{max-width:1180px;margin:auto;padding:48px 24px 72px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:28px}}.eyebrow{{color:var(--cyan);font-size:12px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}}h1{{font-size:clamp(32px,5vw,54px);margin:8px 0 6px;letter-spacing:-.04em}}.sub{{color:var(--muted);margin:0}}.totals{{display:flex;gap:12px}}.pill{{padding:14px 18px;background:#ffffff0b;border:1px solid var(--line);border-radius:14px}}.pill small,.metric small{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}}.pill strong{{font-size:20px}}.toolbar{{display:flex;gap:10px;margin-bottom:14px}}button,input{{font:inherit}}.toolbar button{{background:#112f4e;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px 13px;cursor:pointer}}.rep-card{{border:1px solid var(--line);border-radius:14px;background:#0b223a;margin:10px 0;overflow:hidden;box-shadow:0 10px 30px #0002}}.rep-summary{{width:100%;display:grid;grid-template-columns:24px 1fr 170px 130px;gap:16px;align-items:center;text-align:left;background:none;color:inherit;border:0;padding:18px 20px;cursor:pointer}}.rep-summary:hover{{background:#ffffff08}}.chevron{{font-size:28px;color:var(--cyan);transition:.2s}}.rep-summary[aria-expanded=true] .chevron{{transform:rotate(90deg)}}.identity strong{{display:block;font-size:17px}}.identity small{{color:var(--muted)}}.metric strong{{font-size:17px}}.details{{border-top:1px solid var(--line);background:#061a2d;padding:8px 18px 18px}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:14px}}th{{color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-size:10px;text-align:left;padding:13px 10px;border-bottom:1px solid var(--line)}}td{{padding:12px 10px;border-bottom:1px solid #193650}}td a{{color:var(--text);font-weight:700;text-decoration:none}}td a:hover{{color:var(--cyan)}}td span{{display:block;color:var(--muted);font-size:12px;margin-top:2px}}.status-group td{{background:#102d48;padding:10px 12px;border-top:2px solid #2c536f;border-bottom:1px solid #2c536f}}.status-group .status-title{{display:inline-block;color:var(--text);font-size:13px;font-weight:900;margin:0 10px 0 0}}.status-group .status-count{{display:inline-block;color:var(--muted);font-size:11px;margin:0 10px 0 0}}.status-group .badge{{vertical-align:middle}}.deal-row td:first-child{{padding-left:24px}}.badge{{display:inline-block;padding:5px 9px;border-radius:999px;background:#ffffff12;color:var(--text);font-weight:800;font-size:11px}}.badge.released{{background:#143d2b;color:#72e6a2}}.badge.not-payable{{background:#4a2027;color:#ff9ca8}}.badge.pending{{background:#3e3518;color:#f7d36c}}.badge.unmatched{{background:#27384a;color:#aac0d5}}.money{{text-align:right;font-weight:800;color:var(--green)}}th:last-child{{text-align:right}}.empty{{color:var(--muted);text-align:center;padding:24px}}footer{{color:var(--muted);font-size:12px;margin-top:18px}}@media(max-width:720px){{header{{display:block}}.totals{{margin-top:18px}}.rep-summary{{grid-template-columns:20px 1fr 90px}}.rep-summary .metric:last-child{{display:none}}main{{padding:28px 14px}}}}
</style></head><body><main><header><div><div class="eyebrow">Rev.io · Sales Compensation</div><h1>AE Commissions & Quota Tracker</h1><p class="sub">2026 Closed Won deals matched to PSA onboarding · Activated releases commission; Canceled does not.</p></div><div class="totals"><div class="pill"><small>Active AEs</small><strong>{len(reps)}</strong></div><div class="pill"><small>Closed Won</small><strong>{money(total)}</strong></div><div class="pill"><small>Wins</small><strong>{count}</strong></div></div></header><div class="toolbar"><button id="expand">Expand all</button><button id="collapse">Collapse all</button></div>{''.join(rep_rows)}<footer>Salesforce and PSA onboarding snapshot refreshed {generated.strftime('%b %-d, %Y at %-I:%M %p ET')} · Activated = released; Canceled/Cancelled = not payable; other matched statuses = pending.</footer></main>
<script>const cards=[...document.querySelectorAll('.rep-summary')];function setRow(b,open){{b.setAttribute('aria-expanded',open);document.getElementById(b.getAttribute('aria-controls')).hidden=!open}}cards.forEach(b=>b.addEventListener('click',()=>setRow(b,b.getAttribute('aria-expanded')!=='true')));document.getElementById('expand').onclick=()=>cards.forEach(b=>setRow(b,true));document.getElementById('collapse').onclick=()=>cards.forEach(b=>setRow(b,false));</script></body></html>'''
    HTML_PATH.write_text(html)
    print(f"Built {HTML_PATH.name}: {len(reps)} AEs, {count} wins, {money(total)}")

if __name__ == "__main__":
    main()
