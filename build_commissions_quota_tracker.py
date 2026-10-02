#!/usr/bin/env python3
"""Build the first commissions/quota tracker view from live Salesforce data."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from build_2026_psa_team_tracker import sf_auth, sf_query

ROOT = Path(__file__).resolve().parent
YEAR = 2026
ET = ZoneInfo("America/New_York")
HTML_PATH = ROOT / "commissions-quota-tracker.html"
JSON_PATH = ROOT / "commissions_quota_tracker.json"
SF_BASE = "https://rev-io.my.salesforce.com"


def money(value):
    return f"${float(value or 0):,.0f}"


def main():
    base, headers = sf_auth()
    users = sf_query(base, headers, """
        SELECT Id, Name, Title, UserRole.Name
        FROM User
        WHERE IsActive = true
          AND UserRole.Name IN ('MSP Sales', 'Integrator Sales')
        ORDER BY Name
    """)
    reps = []
    for user in users:
        role = ((user.get("UserRole") or {}).get("Name") or "").replace(" Sales", "")
        reps.append({"id": user.get("Id"), "name": user.get("Name"), "title": user.get("Title") or "Account Executive", "team": role})
    names = [r["name"] for r in reps]
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
    grouped = defaultdict(list)
    for opp in opps:
        owner = (opp.get("Owner") or {}).get("Name") or "Unassigned"
        grouped[owner].append({
            "id": opp.get("Id"),
            "name": opp.get("Name") or "Untitled opportunity",
            "account": (opp.get("Account") or {}).get("Name") or "—",
            "amount": float(opp.get("Amount") or 0),
            "close_date": opp.get("CloseDate") or "",
            "product": opp.get("Product_Type__c") or "—",
            "type": opp.get("Type") or "—",
        })
    generated = datetime.now(ET)
    payload = {"generated_at_et": generated.isoformat(), "year": YEAR, "reps": []}
    for rep in reps:
        wins = grouped.get(rep["name"], [])
        payload["reps"].append({**rep, "opportunity_count": len(wins), "closed_won": sum(x["amount"] for x in wins), "opportunities": wins})
    JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n")

    rep_rows = []
    for i, rep in enumerate(payload["reps"]):
        detail_rows = "".join(
            f'''<tr><td><a href="{SF_BASE}/{escape(o['id'])}" target="_blank" rel="noopener">{escape(o['name'])}</a><span>{escape(o['account'])}</span></td><td>{escape(o['product'])}</td><td>{escape(o['type'])}</td><td>{escape(o['close_date'])}</td><td class="money">{money(o['amount'])}</td></tr>'''
            for o in rep["opportunities"]
        ) or '<tr><td colspan="5" class="empty">No Closed Won opportunities in 2026.</td></tr>'
        rep_rows.append(f'''
        <section class="rep-card" data-name="{escape(rep['name'].lower())}">
          <button class="rep-summary" type="button" aria-expanded="false" aria-controls="rep-{i}">
            <span class="chevron">›</span><span class="identity"><strong>{escape(rep['name'])}</strong><small>{escape(rep['team'])} · {escape(rep['title'])}</small></span>
            <span class="metric"><small>Closed Won</small><strong>{money(rep['closed_won'])}</strong></span>
            <span class="metric"><small>Opportunities</small><strong>{rep['opportunity_count']}</strong></span>
          </button>
          <div class="details" id="rep-{i}" hidden><div class="table-wrap"><table><thead><tr><th>Opportunity / Account</th><th>Product</th><th>Type</th><th>Close date</th><th>Amount</th></tr></thead><tbody>{detail_rows}</tbody></table></div></div>
        </section>''')

    total = sum(r["closed_won"] for r in payload["reps"])
    count = sum(r["opportunity_count"] for r in payload["reps"])
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AE Commissions & Quota Tracker</title>
<style>
:root{{--navy:#07192d;--panel:#0d2742;--line:#24445f;--cyan:#3ee0d0;--blue:#65a9ff;--text:#f3f8fd;--muted:#9eb1c5;--green:#72e6a2}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 85% 0,#123e62 0,transparent 35%),var(--navy);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}main{{max-width:1180px;margin:auto;padding:48px 24px 72px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:28px}}.eyebrow{{color:var(--cyan);font-size:12px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}}h1{{font-size:clamp(32px,5vw,54px);margin:8px 0 6px;letter-spacing:-.04em}}.sub{{color:var(--muted);margin:0}}.totals{{display:flex;gap:12px}}.pill{{padding:14px 18px;background:#ffffff0b;border:1px solid var(--line);border-radius:14px}}.pill small,.metric small{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}}.pill strong{{font-size:20px}}.toolbar{{display:flex;gap:10px;margin-bottom:14px}}button,input{{font:inherit}}.toolbar button{{background:#112f4e;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px 13px;cursor:pointer}}.rep-card{{border:1px solid var(--line);border-radius:14px;background:#0b223a;margin:10px 0;overflow:hidden;box-shadow:0 10px 30px #0002}}.rep-summary{{width:100%;display:grid;grid-template-columns:24px 1fr 170px 130px;gap:16px;align-items:center;text-align:left;background:none;color:inherit;border:0;padding:18px 20px;cursor:pointer}}.rep-summary:hover{{background:#ffffff08}}.chevron{{font-size:28px;color:var(--cyan);transition:.2s}}.rep-summary[aria-expanded=true] .chevron{{transform:rotate(90deg)}}.identity strong{{display:block;font-size:17px}}.identity small{{color:var(--muted)}}.metric strong{{font-size:17px}}.details{{border-top:1px solid var(--line);background:#061a2d;padding:8px 18px 18px}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:14px}}th{{color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-size:10px;text-align:left;padding:13px 10px;border-bottom:1px solid var(--line)}}td{{padding:12px 10px;border-bottom:1px solid #193650}}td a{{color:var(--text);font-weight:700;text-decoration:none}}td a:hover{{color:var(--cyan)}}td span{{display:block;color:var(--muted);font-size:12px;margin-top:2px}}.money{{text-align:right;font-weight:800;color:var(--green)}}th:last-child{{text-align:right}}.empty{{color:var(--muted);text-align:center;padding:24px}}footer{{color:var(--muted);font-size:12px;margin-top:18px}}@media(max-width:720px){{header{{display:block}}.totals{{margin-top:18px}}.rep-summary{{grid-template-columns:20px 1fr 90px}}.rep-summary .metric:last-child{{display:none}}main{{padding:28px 14px}}}}
</style></head><body><main><header><div><div class="eyebrow">Rev.io · Sales Compensation</div><h1>AE Commissions & Quota Tracker</h1><p class="sub">2026 Closed Won foundation · Expand a rep to inspect every opportunity.</p></div><div class="totals"><div class="pill"><small>Active AEs</small><strong>{len(reps)}</strong></div><div class="pill"><small>Closed Won</small><strong>{money(total)}</strong></div><div class="pill"><small>Wins</small><strong>{count}</strong></div></div></header><div class="toolbar"><button id="expand">Expand all</button><button id="collapse">Collapse all</button></div>{''.join(rep_rows)}<footer>Salesforce snapshot refreshed {generated.strftime('%b %-d, %Y at %-I:%M %p ET')} · Amount shown is the Opportunity Amount and is not yet a calculated commission payout.</footer></main>
<script>const cards=[...document.querySelectorAll('.rep-summary')];function setRow(b,open){{b.setAttribute('aria-expanded',open);document.getElementById(b.getAttribute('aria-controls')).hidden=!open}}cards.forEach(b=>b.addEventListener('click',()=>setRow(b,b.getAttribute('aria-expanded')!=='true')));document.getElementById('expand').onclick=()=>cards.forEach(b=>setRow(b,true));document.getElementById('collapse').onclick=()=>cards.forEach(b=>setRow(b,false));</script></body></html>'''
    HTML_PATH.write_text(html)
    print(f"Built {HTML_PATH.name}: {len(reps)} AEs, {count} wins, {money(total)}")

if __name__ == "__main__":
    main()
