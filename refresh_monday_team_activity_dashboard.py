#!/usr/bin/env python3
"""Refresh Monday team activity dashboard.

Focused Monday-morning scorecard: last completed Monday-Sunday week vs the
prior Monday-Sunday week across the sales motion Ryan asked to inspect.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

WORKSPACE = Path(os.environ.get("ROBIN_WORKSPACE", "/home/openclaw/.openclaw/workspace"))
HTML_FILE = WORKSPACE / "monday-team-activity-dashboard.html"
DATA_FILE = WORKSPACE / "monday_team_activity_dashboard.json"

SF_INSTANCE = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
ET = ZoneInfo("America/New_York")

NAME_ALIASES = {"Andrew Whisenant": "Andy Whisenant"}
EXCLUDED_REPS = {
    "Ardit Berdyna", "Blaine Villafuerte", "Cam Sharpe", "Davis Herndon",
    "Jake Mitchell", "Matt Salin", "Olivia Sandefur", "Reid Doster", "Usman Zahoor",
}
ROLE_GROUPS = {"SDRs": "SDR", "MSP Sales": "AE", "Integrator Sales": "AE", "CSA": "CSA"}
KNOWN_AES = {"Andy Whisenant", "Connor Flynn", "Husam Zalmiyar", "Jake Borah", "Jamie Butler", "Jaylin Bender", "Patrick Davies"}
KNOWN_CSAS = {"Ingrid Beard", "Justin Lee"}
CBR_TYPES = ["Client Business Review", "(CSA) Client Business Review", "AM - Client Business Review", "PSA AM - Client Business Review"]
DEMO_TYPES = ["Initial Product Demo", "Product Demo", "Demo"]
MQL_EXCLUDED_SOURCES = {"", "none", "sales", "sdr", "outbound", "partner", "partner/channel", "channel", "referral", "customer referral", "tradeshow"}


def normalize_name(name: str | None) -> str:
    clean = (name or "").strip()
    return NAME_ALIASES.get(clean, clean)


def sf_auth():
    r = requests.post(
        f"{SF_INSTANCE}/services/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": SF_CLIENT_ID, "client_secret": SF_CLIENT_SECRET},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()
    return token["instance_url"], {"Authorization": f"Bearer {token['access_token']}"}


def sf_query(base, headers, query):
    url = f"{base}/services/data/v59.0/query"
    params = {"q": query.strip()}
    records = []
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Salesforce query failed: {r.status_code} {r.text[:1000]}\nSOQL:\n{query}")
        data = r.json()
        records.extend(data.get("records", []))
        if data.get("done", True):
            return records
        url = base + data["nextRecordsUrl"]
        params = {}


def week_windows(now_et: datetime):
    today = now_et.date()
    this_monday = today - timedelta(days=today.weekday())
    # Sunday-night refresh should include the week that just ended Sunday.
    # Monday and later use the previous completed Monday-Sunday week.
    if today.weekday() == 6:
        last_start = this_monday
        last_end = this_monday + timedelta(days=7)
    else:
        last_start = this_monday - timedelta(days=7)
        last_end = this_monday
    prior_start = last_start - timedelta(days=7)
    prior_end = last_start
    return {
        "last": (datetime.combine(last_start, time.min, ET), datetime.combine(last_end, time.min, ET)),
        "prior": (datetime.combine(prior_start, time.min, ET), datetime.combine(prior_end, time.min, ET)),
    }


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sf_date(dt: datetime) -> str:
    return dt.date().isoformat()


def parse_sf_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(ET)


def period_for_dt(dt: datetime, windows):
    for key, (start, end) in windows.items():
        if start <= dt < end:
            return key
    return None


def format_window(start, end):
    return f"{start.strftime('%b %-d')} - {(end - timedelta(days=1)).strftime('%b %-d, %Y')}"


def soql_list(values):
    return ", ".join("'" + str(v).replace("'", "\\'") + "'" for v in values)


def amount(rec):
    try:
        return float(rec.get("Amount") or 0)
    except Exception:
        return 0.0


def get_team_members(base, headers):
    users = sf_query(base, headers, f"""
        SELECT Name, UserRole.Name
        FROM User
        WHERE IsActive = true AND UserRole.Name IN ({soql_list(ROLE_GROUPS)})
        ORDER BY Name
    """)
    reps = {}
    for u in users:
        role = ((u.get("UserRole") or {}).get("Name") or "").strip()
        name = normalize_name(u.get("Name"))
        if name and name not in EXCLUDED_REPS:
            reps[name] = ROLE_GROUPS.get(role, "Other")
    for name in KNOWN_AES:
        if name not in EXCLUDED_REPS:
            reps.setdefault(name, "AE")
    for name in KNOWN_CSAS:
        if name not in EXCLUDED_REPS:
            reps.setdefault(name, "CSA")
    return reps


def empty_periods(value=0):
    return {"last": value, "prior": value}


def empty_rep(role=""):
    return {
        "role": role,
        "discovery_set": empty_periods(),
        "cbrs_set": empty_periods(),
        "initial_demos_ran": empty_periods(),
        "sdr_sourced_opps": empty_periods(),
        "sdr_sourced_mrr": empty_periods(0.0),
        "mqls_converted": empty_periods(),
        "mql_converted_mrr": empty_periods(0.0),
        "tradeshow_leads_converted": empty_periods(),
        "tradeshow_converted_mrr": empty_periods(0.0),
        "booked_mrr": empty_periods(0.0),
        "booked_count": empty_periods(),
    }


def add_metric(bucket, key, period, count=1, mrr_key=None, mrr=0.0):
    bucket[key][period] += count
    if mrr_key:
        bucket[mrr_key][period] += mrr


def source_norm(value):
    return (value or "").strip().lower()


def is_mql_source(value):
    return source_norm(value) not in MQL_EXCLUDED_SOURCES


def is_tradeshow_source(value):
    return source_norm(value) == "tradeshow"


def product_label(value):
    raw = (value or "Unspecified").strip() or "Unspecified"
    low = raw.lower()
    if "psa" in low:
        return "PSA"
    if "billing" in low or "odin" in low:
        return "Billing / Odin"
    if "payment" in low or "ar" in low:
        return "Payments AR"
    if "cyber" in low:
        return "Cyber Protect"
    if "commerce" in low:
        return "CommerceHub"
    return raw


def build_payload():
    now_et = datetime.now(ET)
    windows = week_windows(now_et)
    range_start, range_end = windows["prior"][0], windows["last"][1]
    base, headers = sf_auth()
    reps = get_team_members(base, headers)
    metrics = {rep: empty_rep(role) for rep, role in reps.items()}
    product_mrr = defaultdict(lambda: {"last": {"mrr": 0.0, "count": 0}, "prior": {"mrr": 0.0, "count": 0}})
    conversion_detail = {"mql": [], "tradeshow": [], "sdr": [], "booked": []}

    # Discovery meetings SET: task created during the week.
    discovery_tasks = sf_query(base, headers, f"""
        SELECT Id, Subject, CreatedDate, Owner.Name
        FROM Task
        WHERE IsDeleted = false
          AND CreatedDate >= {iso_utc(range_start)}
          AND CreatedDate < {iso_utc(range_end)}
          AND (Subject LIKE '%Discovery Meeting%' OR Subject LIKE '%Discovery Call%')
    """)
    for task in discovery_tasks:
        rep = normalize_name((task.get("Owner") or {}).get("Name"))
        if rep not in metrics:
            continue
        period = period_for_dt(parse_sf_datetime(task["CreatedDate"]), windows)
        if period:
            add_metric(metrics[rep], "discovery_set", period)

    # CBRs SET: CBR events created during the week (not just completed).
    cbr_events = sf_query(base, headers, f"""
        SELECT Id, Subject, Type, CreatedDate, ActivityDate, Owner.Name, What.Name
        FROM Event
        WHERE IsDeleted = false
          AND CreatedDate >= {iso_utc(range_start)}
          AND CreatedDate < {iso_utc(range_end)}
          AND Type IN ({soql_list(CBR_TYPES)})
    """)
    for ev in cbr_events:
        rep = normalize_name((ev.get("Owner") or {}).get("Name"))
        if rep not in metrics:
            continue
        period = period_for_dt(parse_sf_datetime(ev["CreatedDate"]), windows)
        if period:
            add_metric(metrics[rep], "cbrs_set", period)

    # Initial demos RAN: demo events with ActivityDate during the week and completed when status exists.
    demo_events = sf_query(base, headers, f"""
        SELECT Id, Subject, Type, ActivityDate, Appointment_Status__c, Owner.Name, What.Name
        FROM Event
        WHERE IsDeleted = false
          AND ActivityDate >= {sf_date(range_start)}
          AND ActivityDate < {sf_date(range_end)}
          AND (Type IN ({soql_list(DEMO_TYPES)}) OR Subject LIKE '%Initial%Demo%' OR Subject LIKE '%Product Demo%')
    """)
    for ev in demo_events:
        rep = normalize_name((ev.get("Owner") or {}).get("Name"))
        if rep not in metrics:
            continue
        status = (ev.get("Appointment_Status__c") or "").strip().lower()
        subject = (ev.get("Subject") or "").lower()
        if "cancel" in subject or "internal" in subject:
            continue
        if status and status not in {"completed", "complete", "held", "ran"}:
            continue
        dt = datetime.fromisoformat(ev["ActivityDate"]).replace(tzinfo=ET)
        period = period_for_dt(dt, windows)
        if period:
            add_metric(metrics[rep], "initial_demos_ran", period)

    # Opportunity-created conversions: SDR sourced, MQL converted, Tradeshow converted.
    opps_created = sf_query(base, headers, f"""
        SELECT Id, Name, Amount, CreatedDate, StageName, Product_Type__c, Marketing_Source__c,
               Marketing_Sub_source__c, SDR_Influence__c, Owner.Name, Account.Name
        FROM Opportunity
        WHERE IsDeleted = false
          AND CreatedDate >= {iso_utc(range_start)}
          AND CreatedDate < {iso_utc(range_end)}
    """)
    for opp in opps_created:
        created_dt = parse_sf_datetime(opp["CreatedDate"])
        period = period_for_dt(created_dt, windows)
        if not period:
            continue
        mrr = amount(opp)
        owner = normalize_name((opp.get("Owner") or {}).get("Name"))
        opp_name = opp.get("Name") or "Opportunity"
        account_name = (opp.get("Account") or {}).get("Name") or ""
        source = opp.get("Marketing_Source__c") or ""
        subsource = opp.get("Marketing_Sub_source__c") or ""
        sdr = normalize_name(opp.get("SDR_Influence__c"))
        if sdr and sdr.lower() != "none":
            if sdr not in metrics:
                metrics[sdr] = empty_rep("SDR")
            add_metric(metrics[sdr], "sdr_sourced_opps", period, mrr_key="sdr_sourced_mrr", mrr=mrr)
            if period == "last":
                conversion_detail["sdr"].append({"rep": sdr, "opp": opp_name, "account": account_name, "mrr": mrr, "date": created_dt.strftime("%a %-m/%-d")})
        if owner in metrics and is_tradeshow_source(source):
            add_metric(metrics[owner], "tradeshow_leads_converted", period, mrr_key="tradeshow_converted_mrr", mrr=mrr)
            if period == "last":
                conversion_detail["tradeshow"].append({"rep": owner, "opp": opp_name, "account": account_name, "source": subsource or source, "mrr": mrr, "date": created_dt.strftime("%a %-m/%-d")})
        elif owner in metrics and is_mql_source(source):
            add_metric(metrics[owner], "mqls_converted", period, mrr_key="mql_converted_mrr", mrr=mrr)
            if period == "last":
                conversion_detail["mql"].append({"rep": owner, "opp": opp_name, "account": account_name, "source": subsource or source, "mrr": mrr, "date": created_dt.strftime("%a %-m/%-d")})

    # Booked MRR by product: closed-won opps by close date.
    opps_closed = sf_query(base, headers, f"""
        SELECT Id, Name, Amount, CloseDate, Product_Type__c, Owner.Name, Account.Name
        FROM Opportunity
        WHERE IsDeleted = false
          AND StageName = 'Closed Won'
          AND CloseDate >= {sf_date(range_start)}
          AND CloseDate < {sf_date(range_end)}
    """)
    for opp in opps_closed:
        dt = datetime.fromisoformat(opp["CloseDate"]).replace(tzinfo=ET)
        period = period_for_dt(dt, windows)
        if not period:
            continue
        mrr = amount(opp)
        owner = normalize_name((opp.get("Owner") or {}).get("Name"))
        product = product_label(opp.get("Product_Type__c"))
        product_mrr[product][period]["mrr"] += mrr
        product_mrr[product][period]["count"] += 1
        if owner in metrics:
            add_metric(metrics[owner], "booked_count", period, mrr_key="booked_mrr", mrr=mrr)
        if period == "last":
            conversion_detail["booked"].append({"rep": owner, "opp": opp.get("Name") or "Opportunity", "account": (opp.get("Account") or {}).get("Name") or "", "product": product, "mrr": mrr, "date": dt.strftime("%a %-m/%-d")})

    totals = empty_rep("Total")
    for repdata in metrics.values():
        for key, val in repdata.items():
            if key == "role":
                continue
            for period in ("last", "prior"):
                totals[key][period] += val[period]

    product_rows = dict(sorted(product_mrr.items(), key=lambda kv: (-kv[1]["last"]["mrr"], kv[0])))
    for key in conversion_detail:
        conversion_detail[key] = sorted(conversion_detail[key], key=lambda x: (-x.get("mrr", 0), x.get("rep", "")))[:12]

    return {
        "generated_at_et": now_et.strftime("%b %-d, %Y %-I:%M %p ET"),
        "windows": {k: format_window(v[0], v[1]) for k, v in windows.items()},
        "definitions": {
            "discovery_set": "Tasks created with Discovery Meeting/Call in the subject.",
            "cbrs_set": "CBR-type Events created during the week.",
            "initial_demos_ran": "Demo Events with ActivityDate in-week, completed/held when appointment status is present.",
            "sdr_sourced_opps": "Opportunities created with SDR_Influence__c populated and not None.",
            "mqls_converted": "Marketing-sourced opportunities created, excluding tradeshow, sales/outbound, partner/channel, and referral sources.",
            "tradeshow_leads_converted": "Opportunities created with Marketing_Source__c = Tradeshow.",
            "booked_mrr": "Closed-won Opportunity Amount by CloseDate, grouped by Product_Type__c.",
        },
        "metrics": metrics,
        "totals": totals,
        "product_mrr": product_rows,
        "conversion_detail": conversion_detail,
    }


def fmt_int(v):
    return f"{int(v):,}"


def money(v):
    return f"${float(v):,.0f}"


def pct_delta(last, prior):
    if prior == 0:
        return "+100%" if last else "0%"
    return f"{((last - prior) / prior) * 100:+.0f}%"


def signed(last, prior, money_flag=False):
    diff = last - prior
    if money_flag:
        return ("+" if diff >= 0 else "") + money(diff)
    return ("+" if diff >= 0 else "") + fmt_int(diff)


def metric_card(label, key, totals, money_flag=False, subkey=None):
    source = totals[key] if subkey is None else totals[subkey]
    last = source["last"]
    prior = source["prior"]
    main = money(last) if money_flag else fmt_int(last)
    prior_txt = money(prior) if money_flag else fmt_int(prior)
    cls = "up" if last >= prior else "down"
    return f'''<div class="metric-card">
      <div class="metric-label">{escape(label)}</div>
      <div class="metric-value">{main}</div>
      <div class="metric-compare"><span class="{cls}">{escape(signed(last, prior, money_flag))}</span> vs prior · {escape(pct_delta(last, prior))}</div>
      <div class="metric-prior">Prior week: {prior_txt}</div>
    </div>'''


def team_metric_specs(totals):
    return [
        ("Discovery Meetings Set", "discovery_set", False, "Top-of-funnel meetings created"),
        ("CBRs Set", "cbrs_set", False, "Customer business reviews scheduled"),
        ("Initial Demos Ran", "initial_demos_ran", False, "Demo meetings completed/held"),
        ("SDR-Sourced Opps", "sdr_sourced_opps", False, f"{money(totals['sdr_sourced_mrr']['last'])} sourced MRR"),
        ("MQLs Converted", "mqls_converted", False, f"{money(totals['mql_converted_mrr']['last'])} converted MRR"),
        ("Tradeshow Leads Converted", "tradeshow_leads_converted", False, f"{money(totals['tradeshow_converted_mrr']['last'])} converted MRR"),
        ("Booked MRR", "booked_mrr", True, f"{fmt_int(totals['booked_count']['last'])} closed-won deals"),
        ("Booked Deals", "booked_count", False, "Closed-won opportunity count"),
    ]


def build_difference_rows(totals, positive=True):
    rows = []
    for label, key, money_flag, note in team_metric_specs(totals):
        last = totals[key]["last"]
        prior = totals[key]["prior"]
        diff = last - prior
        if positive and diff < 0:
            continue
        if not positive and diff >= 0:
            continue
        cls = "good" if diff >= 0 else "bad"
        rows.append(f'''<tr>
          <td><strong>{escape(label)}</strong><span>{escape(note)}</span></td>
          <td>{money(last) if money_flag else fmt_int(last)}</td>
          <td>{money(prior) if money_flag else fmt_int(prior)}</td>
          <td><span class="{cls}">{escape(signed(last, prior, money_flag))}</span><small>{escape(pct_delta(last, prior))}</small></td>
        </tr>''')
    tone = "positive movement" if positive else "negative movement"
    return "\n".join(rows) or f'<tr><td colspan="4" class="empty">No {tone} vs prior week.</td></tr>'


def build_team_summary_rows(totals):
    rows = []
    for label, key, money_flag, note in team_metric_specs(totals):
        last = totals[key]["last"]
        prior = totals[key]["prior"]
        cls = "good" if last >= prior else "bad"
        rows.append(f'''<tr>
          <td><strong>{escape(label)}</strong><span>{escape(note)}</span></td>
          <td>{money(last) if money_flag else fmt_int(last)}</td>
          <td>{money(prior) if money_flag else fmt_int(prior)}</td>
          <td><span class="{cls}">{escape(signed(last, prior, money_flag))}</span><small>{escape(pct_delta(last, prior))}</small></td>
        </tr>''')
    return "\n".join(rows)


def build_product_rows(product_mrr):
    rows = []
    for product, p in product_mrr.items():
        rows.append(f'''<tr>
          <td><strong>{escape(product)}</strong></td>
          <td>{money(p['last']['mrr'])}<small>{fmt_int(p['last']['count'])} deals</small></td>
          <td>{money(p['prior']['mrr'])}<small>{fmt_int(p['prior']['count'])} deals</small></td>
          <td><span class="{'good' if p['last']['mrr'] >= p['prior']['mrr'] else 'bad'}">{escape(signed(p['last']['mrr'], p['prior']['mrr'], True))}</span></td>
        </tr>''')
    return "\n".join(rows) or '<tr><td colspan="4" class="empty">No booked MRR in either week.</td></tr>'


def build_detail_rows(items, kind):
    rows = []
    for item in items:
        meta = item.get("product") or item.get("source") or ""
        rows.append(f'''<tr>
          <td><strong>{escape(item.get('rep') or '')}</strong><span>{escape(item.get('date') or '')}</span></td>
          <td>{escape(item.get('account') or '')}<span>{escape(item.get('opp') or '')}</span></td>
          <td>{escape(meta)}</td>
          <td>{money(item.get('mrr') or 0)}</td>
        </tr>''')
    return "\n".join(rows) or f'<tr><td colspan="4" class="empty">No {escape(kind)} last week.</td></tr>'


def build_html(payload):
    t = payload["totals"]
    cards = "\n".join([
        metric_card("Discovery Meetings Set", "discovery_set", t),
        metric_card("CBRs Set", "cbrs_set", t),
        metric_card("Initial Demos Ran", "initial_demos_ran", t),
        metric_card("SDR-Sourced Opps", "sdr_sourced_opps", t),
        metric_card("MQLs Converted", "mqls_converted", t),
        metric_card("Tradeshow Leads Converted", "tradeshow_leads_converted", t),
        metric_card("Booked MRR", "booked_mrr", t, True),
        metric_card("Booked Deals", "booked_count", t),
    ])
    positive_rows = build_difference_rows(t, positive=True)
    negative_rows = build_difference_rows(t, positive=False)
    team_summary_rows = build_team_summary_rows(t)
    product_rows = build_product_rows(payload["product_mrr"])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Monday Team Activity Dashboard</title>
<style>
:root {{ --cyan:#34bde5; --cyan-soft:#7fd9ef; --teal:#4fd1c5; --lime:#c6f178; --gold:#eace9b; --danger:#ff6b6b; --bg:#0a141f; --bg-deep:#060e18; --surface:rgba(15,27,42,.78); --border:rgba(255,255,255,.12); --text:#f5f9ff; --muted:#8ea3b9; --mid:#b9c7d6; }}
*{{box-sizing:border-box}} body{{margin:0;font-family:Roboto,Segoe UI,system-ui,sans-serif;background:radial-gradient(900px 420px at 18% -8%,rgba(79,209,197,.30),transparent 64%),radial-gradient(760px 420px at 82% 0%,rgba(52,189,229,.24),transparent 62%),linear-gradient(180deg,#0a141f 0%,#08111b 46%,#060e18 100%);color:var(--text)}}
body:before{{content:'';position:fixed;inset:-14% -10% 55% -10%;background:radial-gradient(55% 45% at 20% 30%,rgba(79,209,197,.35),transparent 65%),radial-gradient(45% 35% at 78% 22%,rgba(52,189,229,.34),transparent 65%);filter:blur(46px);opacity:.75;pointer-events:none}} .container{{max-width:min(1560px,calc(100vw - 32px));margin:0 auto;padding:18px 16px 28px;position:relative;z-index:1}}
.header{{border-bottom:1px solid var(--border);padding:20px 0 22px;margin-bottom:22px;position:relative}} .header-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-right:154px}} .logo{{display:flex;align-items:center;gap:10px}} .logo-dot{{width:9px;height:9px;background:var(--cyan);border-radius:50%;box-shadow:0 0 0 3px rgba(52,189,229,.2),0 0 12px rgba(52,189,229,.85)}} .logo-text{{font-size:11px;font-weight:600;letter-spacing:.22em;text-transform:uppercase;color:var(--cyan-soft)}} .header-date{{font-size:11px;color:var(--muted);letter-spacing:.14em;text-transform:uppercase}} .revio-header-logo{{position:absolute;top:0;right:0;width:132px}} h1{{font-size:clamp(42px,5vw,72px);font-weight:300;color:#fff;letter-spacing:-.03em;line-height:.98;margin:0 0 10px}} h1 span{{color:var(--cyan-soft);font-family:Georgia,serif;font-style:italic;font-weight:500}} .header-sub{{font-size:14px;color:var(--mid);max-width:980px;line-height:1.45}}
.metric-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}} .metric-card{{background:rgba(255,255,255,.035);border:1px solid var(--border);border-radius:16px;padding:16px;box-shadow:0 22px 60px -48px #000;backdrop-filter:blur(12px)}} .metric-label{{font-size:9px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin-bottom:7px}} .metric-value{{font-size:30px;font-weight:850;line-height:1;color:#fff}} .metric-compare{{margin-top:8px;font-size:12px;color:var(--mid)}} .metric-compare .up,.good{{color:var(--lime)}} .metric-compare .down,.bad{{color:var(--danger)}} .metric-prior{{margin-top:4px;font-size:11px;color:var(--muted)}}
.panel-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} .focus-panel{{border-color:rgba(198,241,120,.22)}} .watch-panel{{border-color:rgba(255,107,107,.24)}} .panel{{background:var(--surface);border:1px solid var(--border);border-radius:16px;margin-bottom:14px;overflow:hidden;box-shadow:0 22px 60px -48px #000;backdrop-filter:blur(12px)}} .panel-head{{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;padding:16px 18px;border-bottom:1px solid var(--border)}} h2{{margin:0;font-size:20px;font-weight:650;color:#fff}} .panel-note{{font-size:12px;color:var(--muted);max-width:720px;line-height:1.4}} table{{width:100%;border-collapse:collapse}} th{{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.16em;color:var(--muted);padding:10px 14px;text-align:left;background:rgba(6,14,24,.55)}} td{{font-size:13px;padding:10px 14px;border-top:1px solid rgba(255,255,255,.06);color:var(--mid);vertical-align:top}} td:first-child{{color:#fff}} td strong{{display:block;color:#fff}} td span, td small{{display:block;color:var(--muted);font-size:10px;margin-top:3px}} td small{{color:var(--cyan-soft)}} .empty{{text-align:center;color:var(--muted);padding:24px}} .definitions{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:14px 18px}} .def{{font-size:12px;color:var(--mid);line-height:1.35;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:10px}} .def strong{{color:#fff}} .footer{{text-align:center;padding:18px;font-size:10px;color:var(--muted);letter-spacing:.14em;border-top:1px solid var(--border);margin-top:8px}}
@media(max-width:1000px){{.metric-grid,.panel-grid,.definitions{{grid-template-columns:1fr 1fr}}.panel{{overflow-x:auto}}table{{min-width:900px}}.header-top{{padding-right:0;display:block}}.revio-header-logo{{position:relative;width:108px;margin-top:10px}}}} @media(max-width:680px){{.metric-grid,.panel-grid,.definitions{{grid-template-columns:1fr}}}}
</style></head><body><div class="container"><header class="header"><div class="header-top"><div class="logo"><span class="logo-dot"></span><span class="logo-text">Rev.io Sales Team</span></div><div class="header-date">Generated {escape(payload['generated_at_et'])}</div></div><img class="revio-header-logo" src="https://7091219.fs1.hubspotusercontent-na1.net/hubfs/7091219/email-assets/logo-revio-white.png" alt="Rev.io"><h1>Monday Sales <span>Motion</span></h1><p class="header-sub">Last week ({escape(payload['windows']['last'])}) vs prior week ({escape(payload['windows']['prior'])}) across meeting creation, demos run, sourced/converted opportunities, and booked MRR by product.</p></header>
<div class="metric-grid">{cards}</div>
<div class="panel-grid"><section class="panel focus-panel"><div class="panel-head"><h2>Positive movement</h2><div class="panel-note">Metrics up or flat vs the prior week — easier to scan for what improved.</div></div><table><thead><tr><th>Metric</th><th>Last Week</th><th>Prior Week</th><th>Difference</th></tr></thead><tbody>{positive_rows}</tbody></table></section><section class="panel watch-panel"><div class="panel-head"><h2>Watch list</h2><div class="panel-note">Metrics down vs the prior week — the Monday coaching queue, minus the detective corkboard chaos.</div></div><table><thead><tr><th>Metric</th><th>Last Week</th><th>Prior Week</th><th>Difference</th></tr></thead><tbody>{negative_rows}</tbody></table></section></div>
<section class="panel"><div class="panel-head"><h2>Team metric scorecard</h2><div class="panel-note">Team-level view only: last week, prior week, and variance. No rep-by-rep difference pileup.</div></div><table><thead><tr><th>Metric</th><th>Last Week</th><th>Prior Week</th><th>Difference</th></tr></thead><tbody>{team_summary_rows}</tbody></table></section>
<section class="panel"><div class="panel-head"><h2>MRR booked by product</h2><div class="panel-note">Closed-won Opportunity Amount by CloseDate and Product Type.</div></div><table><thead><tr><th>Product</th><th>Last Week</th><th>Prior Week</th><th>Delta</th></tr></thead><tbody>{product_rows}</tbody></table></section>
<section class="panel"><div class="panel-head"><h2>Metric definitions</h2><div class="panel-note">So nobody has to decode the Batcomputer during the team meeting.</div></div><div class="definitions">{''.join(f'<div class="def"><strong>{escape(k.replace("_", " ").title())}:</strong> {escape(v)}</div>' for k, v in payload['definitions'].items())}</div></section>
<div class="footer">SOURCE: SALESFORCE TASKS, EVENTS, AND OPPORTUNITIES · AUTO-REFRESHES SUNDAY NIGHT ET</div></div></body></html>'''


def publish(paths):
    tmp_parent = Path(tempfile.mkdtemp(prefix="monday-activity-publish."))
    worktree = tmp_parent / "repo"
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = "ssh -i /home/openclaw/.openclaw/ssh/id_ed25519 -o StrictHostKeyChecking=no"
    try:
        subprocess.run(["git", "clone", "git@github.com:koontz-robin/robin-decks.git", str(worktree)], check=True, env=env)
        subprocess.run(["git", "config", "user.name", "Robin"], cwd=worktree, check=True, env=env)
        subprocess.run(["git", "config", "user.email", "robin.bot@rev.io"], cwd=worktree, check=True, env=env)
        for path in paths:
            shutil.copy2(path, worktree / Path(path).name)
        subprocess.run(["git", "add"] + [Path(p).name for p in paths], cwd=worktree, check=True, env=env)
        status = subprocess.run(["git", "status", "--short"], cwd=worktree, text=True, capture_output=True, check=True, env=env).stdout.strip()
        if status:
            subprocess.run(["git", "commit", "-m", "Focus Monday dashboard on team meeting metrics"], cwd=worktree, check=True, env=env)
            subprocess.run(["git", "push", "origin", "master"], cwd=worktree, check=True, env=env)
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    payload = build_payload()
    DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HTML_FILE.write_text(build_html(payload), encoding="utf-8")
    if os.environ.get("NO_PUBLISH") != "1":
        publish([HTML_FILE, DATA_FILE, Path(__file__).resolve()])
    print(f"Built {HTML_FILE}")
    print(f"URL: https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}")


if __name__ == "__main__":
    main()
