#!/usr/bin/env python3
"""
PSA Onboarding Tracker
- RTS section (existing)
- Canceled accounts section (new)
"""

import requests, json, subprocess, os
from datetime import datetime, timedelta
from collections import defaultdict, Counter

NOTION_TOKEN = "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"
SALES_UPDATES_FILE = "/home/openclaw/.openclaw/workspace/sales_updates.json"
PSA_DB_ID = "dba0a0aac29e42d7ac7e968e0245f4c4"
REPO_PATH = "/tmp/robin-decks"
SSH_KEY = "/home/openclaw/.openclaw/ssh/id_ed25519"
OUTPUT_FILE = f"{REPO_PATH}/psa-onboarding-tracker.html"

SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"
SF_INSTANCE = "https://rev-io.my.salesforce.com"

notion_headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

today = datetime.now().date()
today_str = datetime.now().strftime("%B %d, %Y")

# Load sales updates from local JSON
try:
    with open(SALES_UPDATES_FILE) as f:
        _raw = json.load(f)
    sales_updates = {k: v for k, v in _raw.items() if k != "_note"}
except Exception:
    sales_updates = {}


def sf_auth():
    r = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={
        "grant_type": "client_credentials",
        "client_id": SF_CLIENT_ID, "client_secret": SF_CLIENT_SECRET,
    })
    d = r.json()
    return d["access_token"], d["instance_url"]


def sf_get_churn_data(client_names):
    """Look up Churn_Reason__c and Churn_Reason_Detail__c for a list of account names."""
    try:
        at, iurl = sf_auth()
        sf_headers = {"Authorization": f"Bearer {at}"}
        churn_map = {}
        # Batch query — look up all accounts by name
        for name in client_names:
            safe = name.replace("'", "\\'")[:35]
            r = requests.get(f"{iurl}/services/data/v57.0/query",
                headers=sf_headers,
                params={"q": f"SELECT Id, Name, Churn_Reason__c, Churn_Reason_Detail__c FROM Account WHERE Name LIKE '%{safe}%' LIMIT 3"})
            if r.ok:
                records = r.json().get("records", [])
                if records:
                    rec = records[0]
                    churn_map[name] = {
                        "churn_reason": rec.get("Churn_Reason__c") or "",
                        "churn_detail": rec.get("Churn_Reason_Detail__c") or "",
                    }
        return churn_map
    except Exception as e:
        print(f"  SF churn lookup error: {e}")
        return {}


def mrr_fmt(m): return f"${m:,.0f}" if m else "—"


def business_days(start_str):
    if not start_str: return 0
    try:
        start = datetime.fromisoformat(start_str).date()
        d, count = start, 0
        while d < today:
            if d.weekday() < 5: count += 1
            d += timedelta(days=1)
        return count
    except: return 0


def days_since(date_str):
    if not date_str: return None
    try: return (today - datetime.fromisoformat(date_str).date()).days
    except: return None


def status_color(s):
    s = s.lower()
    if "ghost" in s: return "#a78bfa"
    if "function" in s: return "#38bdf8"
    if "bandwidth" in s: return "#fbbf24"
    if "unable" in s: return "#f97316"
    if "client" in s: return "#f97316"
    if "hold" in s: return "#64748b"
    if "cancel" in s: return "#f87171"
    return "#94a3b8"


def days_color(d):
    if d >= 21: return "#f87171"
    if d >= 10: return "#fbbf24"
    return "#34d399"


# ── Pull RTS clients ──────────────────────────────────────────────────────────
def pull_rts_clients():
    """Pull all active RTS clients from Notion + enrich with SF activity."""
    # ── 1. Fetch RTS pages from Notion ────────────────────────────────────
    pages, has_more, cursor = [], True, None
    while has_more:
        body = {
            "page_size": 100,
            "filter": {"property": "IsRTS", "number": {"equals": 1}},
        }
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{PSA_DB_ID}/query",
                          headers=notion_headers, json=body)
        if not r.ok:
            print(f"  Notion error: {r.text[:200]}")
            break
        data = r.json()
        pages.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        cursor = data.get("next_cursor")

    print(f"  Notion RTS clients: {len(pages)}")

    clients = []
    for p in pages:
        props = p.get("properties", {})
        name = "".join(t.get("plain_text", "") for t in (props.get("Client") or {}).get("title", []))
        status = ((props.get("Status") or {}).get("status") or {}).get("name", "")
        sales_rep = ((props.get("Sales Rep") or {}).get("select") or {}).get("name", "")
        sa = ((props.get("Solutions Analyst") or {}).get("select") or {}).get("name", "")
        fees = (props.get("Fees (MRR)") or {}).get("number") or 0
        date_sold = ((props.get("Date Sold") or {}).get("date") or {}).get("start", "")
        rts_start_raw = ((props.get("RTSStart") or {}).get("date") or {}).get("start", "")
        rts_start = rts_start_raw[:10] if rts_start_raw else ""
        rts_notes = "".join(t.get("plain_text", "") for t in (props.get("RTS Notes") or {}).get("rich_text", []))
        sales_notes = "".join(t.get("plain_text", "") for t in (props.get("Notes") or {}).get("rich_text", []))
        notion_url = f"https://www.notion.so/{p['id'].replace('-', '')}"

        # Calculate days in RTS
        days_rts = 0
        if rts_start:
            try:
                days_rts = (today - datetime.fromisoformat(rts_start).date()).days
            except Exception:
                pass

        clients.append({
            "name": name,
            "status": status,
            "sales_rep": sales_rep,
            "sa": sa,
            "mrr": fees,
            "date_sold": date_sold[:10] if date_sold else "",
            "rts_start": rts_start,
            "days_rts": days_rts,
            "rts_notes": rts_notes,
            "sales_notes": sales_notes,
            "url": notion_url,
            "sf_activity": [],
        })

    # ── 2. Enrich with Salesforce activity ────────────────────────────────
    try:
        at, iurl = sf_auth()
        sf_headers = {"Authorization": f"Bearer {at}"}
        cutoff = (today - timedelta(days=90)).isoformat()

        for c in clients:
            safe_name = c["name"].replace("'", "\\'")[:40]
            # Find Account by name
            r = requests.get(f"{iurl}/services/data/v57.0/query", headers=sf_headers,
                             params={"q": f"SELECT Id FROM Account WHERE Name LIKE '%{safe_name}%' LIMIT 1"})
            if not r.ok:
                continue
            records = r.json().get("records", [])
            if not records:
                continue
            acct_id = records[0]["Id"]

            # Pull recent tasks/activities
            ta = requests.get(f"{iurl}/services/data/v57.0/query", headers=sf_headers,
                              params={"q": (
                                  f"SELECT ActivityDate, Type, Subject, Owner.Name FROM Task "
                                  f"WHERE WhatId = '{acct_id}' AND ActivityDate >= {cutoff} "
                                  f"ORDER BY ActivityDate DESC LIMIT 20"
                              )})
            if ta.ok:
                acts = []
                for a in ta.json().get("records", []):
                    owner_name = (a.get("Owner") or {}).get("Name", "") if isinstance(a.get("Owner"), dict) else ""
                    acts.append({
                        "date": a.get("ActivityDate", ""),
                        "type": a.get("Type", "Task"),
                        "subject": a.get("Subject", ""),
                        "owner": owner_name,
                    })
                c["sf_activity"] = acts
    except Exception as e:
        print(f"  SF activity enrichment error: {e}")

    return clients


# ── Pull Canceled clients ────────────────────────────────────────────────────
def pull_canceled_clients():
    r = requests.post(f"https://api.notion.com/v1/databases/{PSA_DB_ID}/query",
        headers=notion_headers,
        json={"page_size": 100, "filter": {"property": "IsCanceled", "number": {"equals": 1}}})
    pages = r.json().get("results", [])
    clients = []
    for p in pages:
        props = p.get("properties", {})
        name = "".join(t.get("plain_text","") for t in (props.get("Client") or {}).get("title",[]))
        status = ((props.get("Status") or {}).get("status") or {}).get("name","")
        sales_rep = ((props.get("Sales Rep") or {}).get("select") or {}).get("name","")
        sa = ((props.get("Solutions Analyst") or {}).get("select") or {}).get("name","")
        fees = (props.get("Fees (MRR)") or {}).get("number") or 0
        date_sold = ((props.get("Date Sold") or {}).get("date") or {}).get("start","")
        date_canceled = ((props.get("DateCanceled") or {}).get("date") or {}).get("start","")
        onboard_type = ((props.get("Onboarding Type") or {}).get("select") or {}).get("name","")
        rts_notes = "".join(t.get("plain_text","") for t in (props.get("RTS Notes") or {}).get("rich_text",[]))
        notion_url = f"https://www.notion.so/{p['id'].replace('-','')}"
        clients.append({
            "name": name, "status": status, "sales_rep": sales_rep, "sa": sa,
            "mrr": fees, "date_sold": date_sold[:10] if date_sold else "",
            "date_canceled": date_canceled[:10] if date_canceled else "",
            "onboard_type": onboard_type, "notes": rts_notes, "url": notion_url,
        })
    # Filter to 2026 only
    clients = [c for c in clients if (c.get("date_canceled","") or "").startswith("2026")]

    # Enrich with SF churn data
    print(f"  Looking up SF churn data for {len(clients)} canceled accounts...")
    churn_map = sf_get_churn_data([c["name"] for c in clients])
    for c in clients:
        sf_data = churn_map.get(c["name"], {})
        c["churn_reason"] = sf_data.get("churn_reason", "")
        c["churn_detail"] = sf_data.get("churn_detail", "")

    return sorted(clients, key=lambda x: x.get("date_canceled","") or "", reverse=True)


# ── Build HTML sections ──────────────────────────────────────────────────────
def build_rts_section(clients):
    """Build the RTS table with SLA alerts."""
    for c in clients:
        bdays = business_days(c.get("rts_start",""))
        c["bdays_rts"] = bdays
        activity = c.get("sf_activity", [])
        outbound = [a for a in activity if "[In]" not in a.get("subject","")]
        last_act_days = days_since(max((a["date"] for a in outbound), default=None)) if outbound else None
        c["last_act_days"] = last_act_days
        last_act_date = max((a["date"] for a in outbound), default=None) if outbound else None
        c["last_act_date"] = last_act_date

        alerts = []
        is_rts = "rts" in c.get("status","").lower()
        is_hold = "hold" in c.get("status","").lower()
        if is_rts:
            if not outbound:
                alerts.append(("🚨","NO CONTACT","#f87171","Sales has not made contact since RTS — 24hr SLA violated"))
            elif bdays > 5:
                alerts.append(("⚠️","CANCEL RISK","#fbbf24",f"{bdays} biz days without resolution — should be canceled or timeline documented"))
            if last_act_days is not None and last_act_days > 3:
                alerts.append(("⚠️",f"STALE {last_act_days}d","#fbbf24",f"Last outbound contact was {last_act_days} days ago"))
        if is_hold:
            if last_act_days is not None and last_act_days > 3:
                alerts.append(("🚨",f"OVERDUE {last_act_days}d","#f87171",f"On Hold: SA should contact every 2-3 days — last contact {last_act_days}d ago"))
            elif last_act_days is None:
                alerts.append(("🚨","NO CONTACT","#f87171","On Hold: No outbound contact logged"))
        c["alerts"] = alerts

    clients_sorted = sorted(clients, key=lambda x: (
        0 if x["alerts"] and "NO CONTACT" in x["alerts"][0][1] else
        1 if x["alerts"] and "CANCEL" in x["alerts"][0][1] else
        2 if x["alerts"] else 3,
        -int(x.get("days_rts") or 0)
    ))

    no_contact = sum(1 for c in clients if any("NO CONTACT" in a[1] for a in c.get("alerts",[])))
    cancel_risk = sum(1 for c in clients if any("CANCEL" in a[1] for a in c.get("alerts",[])))
    total_mrr = sum(c["mrr"] for c in clients)

    by_rep = defaultdict(lambda: {"clients": 0, "mrr": 0})
    for c in clients:
        by_rep[c["sales_rep"] or "Unassigned"]["clients"] += 1
        by_rep[c["sales_rep"] or "Unassigned"]["mrr"] += c["mrr"]
    rep_cards = "".join(
        f'<div style="background:#0a0f1a;border-radius:8px;padding:12px 14px;min-width:140px">'
        f'<div style="font-size:10px;color:#475569;font-weight:700;letter-spacing:1px;margin-bottom:4px;text-transform:uppercase">{rep}</div>'
        f'<div style="font-size:22px;font-weight:800;color:#f87171">{d["clients"]}</div>'
        f'<div style="font-size:11px;color:#64748b;margin-top:2px">{mrr_fmt(d["mrr"])} at risk</div></div>'
        for rep, d in sorted(by_rep.items(), key=lambda x: -x[1]["mrr"])
    )

    rows = ""
    for c in clients_sorted:
        d_rts = int(c.get("days_rts") or 0)
        bdays = c.get("bdays_rts", 0)
        dc = days_color(d_rts)
        sc = status_color(c.get("status",""))
        notes = (c["rts_notes"][:70]+"…" if len(c.get("rts_notes","")) > 70 else c.get("rts_notes","")) if c.get("rts_notes") else "—"
        # Sales Notes — from Notion "Notes" field, fallback to sales_updates.json
        sn_notion = (c.get("sales_notes") or "").strip()
        su = sales_updates.get(c["name"], {})
        su_text = (su.get("text") or "").strip()
        su_date = (su.get("date") or "").strip()
        su_author = (su.get("author") or "").strip()
        if sn_notion:
            sn_display = sn_notion[:120] + ("…" if len(sn_notion) > 120 else "")
            sales_update_cell = f'<td style="font-size:12px;color:#e2e8f0;max-width:220px;border-left:2px solid #1e3a5f">{sn_display}</td>'
        elif su_text:
            su_attribution = f'<div style="font-size:10px;color:#475569;margin-top:2px">{su_date} · {su_author}</div>' if (su_date or su_author) else ""
            sales_update_cell = f'<td style="font-size:12px;color:#e2e8f0;max-width:220px;border-left:2px solid #1e3a5f">{su_text}{su_attribution}</td>'
        else:
            sales_update_cell = '<td style="font-size:12px;color:#334155;font-style:italic;border-left:2px solid #1e3a5f">—</td>'
        activity = [a for a in c.get("sf_activity",[]) if "[In]" not in a.get("subject","")]
        last_date = c.get("last_act_date","")
        last_days = c.get("last_act_days")
        last_display = f'{last_date}<br><span style="font-size:11px;color:#475569">({last_days}d ago)</span>' if last_date else '<span style="color:#f87171">Never</span>'
        row_id = c["name"].replace(" ","_").replace(",","").replace(".","").replace("/","")

        alert_badges = "".join(
            f'<span title="{tip}" style="font-size:10px;font-weight:700;color:{color};background:#0a0f1a;padding:2px 6px;border-radius:8px;margin-left:4px;cursor:help">{emoji} {label}</span>'
            for emoji,label,color,tip in c.get("alerts",[])
        )
        act_rows = "".join(
            f'<tr style="border-bottom:1px solid #0f172a">'
            f'<td style="padding:6px 10px;font-size:12px;color:#64748b">{a["date"]}</td>'
            f'<td style="padding:6px 10px;font-size:12px;color:#38bdf8">{a["type"]}</td>'
            f'<td style="padding:6px 10px;font-size:12px;color:#94a3b8">{a["subject"].replace("[Outreach] [Email] [Out] ","")[:60]}</td>'
            f'<td style="padding:6px 10px;font-size:12px;color:#475569">{a["owner"]}</td></tr>'
            for a in activity[:12]
        ) or '<tr><td colspan="4" style="padding:10px;color:#f87171;font-size:12px;text-align:center">⚠️ No outbound SF activity logged since RTS start</td></tr>'

        rows += (
            f'<tr onclick="toggle(\'{row_id}\')" style="cursor:pointer;border-bottom:1px solid #0f172a" class="cr">'
            f'<td><a href="{c["url"]}" target="_blank" onclick="event.stopPropagation()" style="color:#e2e8f0;text-decoration:none;font-weight:600">{c["name"]}</a>{alert_badges} <span style="color:#475569;font-size:10px">▶</span></td>'
            f'<td style="color:{sc};font-size:12px;font-weight:600">{c.get("status","—")}</td>'
            f'<td>{c["sales_rep"] or "—"}</td><td>{c["sa"] or "—"}</td>'
            f'<td>{mrr_fmt(c["mrr"])}</td><td>{c["date_sold"] or "—"}</td>'
            f'<td>{c["rts_start"] or "—"}</td>'
            f'<td style="color:{dc};font-weight:700">{d_rts}d <span style="font-size:10px;color:#475569">({bdays}bd)</span></td>'
            f'<td style="font-size:12px">{last_display}</td>'
            f'{sales_update_cell}'
            f'<td style="color:#64748b;font-size:12px">{notes}</td>'
            f'</tr>'
            f'<tr id="a_{row_id}" style="display:none"><td colspan="11" style="padding:0 12px 12px 24px">'
            f'<div style="background:#0a0f1a;border-radius:8px;overflow:hidden"><table style="width:100%;border-collapse:collapse">'
            f'<thead><tr style="background:#1e293b"><th style="padding:6px 10px;font-size:10px;color:#475569;text-align:left;text-transform:uppercase">Date</th>'
            f'<th style="padding:6px 10px;font-size:10px;color:#475569;text-align:left;text-transform:uppercase">Type</th>'
            f'<th style="padding:6px 10px;font-size:10px;color:#475569;text-align:left;text-transform:uppercase">Subject</th>'
            f'<th style="padding:6px 10px;font-size:10px;color:#475569;text-align:left;text-transform:uppercase">Owner</th></tr></thead>'
            f'<tbody>{act_rows}</tbody></table></div></td></tr>'
        )

    return {
        "total_mrr": total_mrr,
        "total": len(clients),
        "no_contact": no_contact,
        "cancel_risk": cancel_risk,
        "critical": sum(1 for c in clients if int(c.get("days_rts") or 0) >= 21),
        "rep_cards": rep_cards,
        "rows": rows,
    }


def build_canceled_section(clients):
    """Build the canceled accounts table grouped by month (2026 only)."""
    total_mrr = sum(c["mrr"] for c in clients)
    by_reason = Counter(c["status"] for c in clients)

    reason_pills = "".join(
        f'<div style="background:#0a0f1a;border-radius:8px;padding:10px 14px;min-width:140px">'
        f'<div style="font-size:10px;color:#475569;font-weight:700;letter-spacing:1px;margin-bottom:4px;text-transform:uppercase">{reason.replace("Canceled - ","")}</div>'
        f'<div style="font-size:22px;font-weight:800;color:#f87171">{cnt}</div></div>'
        for reason, cnt in sorted(by_reason.items(), key=lambda x: -x[1])
    )

    # Group by month
    by_month = defaultdict(list)
    for c in clients:
        dc = c.get("date_canceled","")
        if dc:
            try:
                month_key = datetime.fromisoformat(dc).strftime("%Y-%m")
                month_label = datetime.fromisoformat(dc).strftime("%B %Y")
            except:
                month_key = "Unknown"
                month_label = "Unknown"
        else:
            month_key = "Unknown"
            month_label = "Unknown"
        by_month[month_key].append((month_label, c))

    rows = ""
    for month_key in sorted(by_month.keys(), reverse=True):
        month_clients = by_month[month_key]
        month_label = month_clients[0][0]
        month_mrr = sum(c["mrr"] for _, c in month_clients)

        # Month header row
        rows += (
            f'<tr style="background:#0f172a">'
            f'<td colspan="9" style="padding:10px 12px;font-size:12px;font-weight:700;color:#94a3b8;letter-spacing:1px;text-transform:uppercase">'
            f'{month_label} &nbsp;·&nbsp; {len(month_clients)} accounts &nbsp;·&nbsp; {mrr_fmt(month_mrr)} lost MRR'
            f'</td></tr>'
        )

        for _, c in sorted(month_clients, key=lambda x: x[1].get("date_canceled",""), reverse=True):
            sc = status_color(c["status"])
            notes = (c["notes"][:70]+"…" if len(c.get("notes","")) > 70 else c.get("notes","")) if c.get("notes") else "—"
            churn_reason = c.get("churn_reason","") or "—"
            churn_detail = (c.get("churn_detail","") or "")[:80]
            if len(c.get("churn_detail","") or "") > 80:
                churn_detail += "…"
            if not churn_detail:
                churn_detail = "—"
            safe_id = c["name"].replace(" ","_").replace(",","").replace(".","").replace("/","").replace("'","")
            rows += (
                f'<tr style="border-bottom:1px solid #0f172a">'
                f'<td><a href="{c["url"]}" target="_blank" style="color:#e2e8f0;text-decoration:none;font-weight:600">{c["name"]}</a></td>'
                f'<td style="color:{sc};font-size:12px;font-weight:600">{c["status"].replace("Canceled - ","")}</td>'
                f'<td>{c["sales_rep"] or "—"}</td><td>{c["sa"] or "—"}</td>'
                f'<td>{mrr_fmt(c["mrr"])}</td>'
                f'<td>{c["date_sold"] or "—"}</td>'
                f'<td>{c["date_canceled"] or "—"}</td>'
                f'<td style="color:#64748b;font-size:12px">{c["onboard_type"] or "—"}</td>'
                f'<td style="color:#f97316;font-size:12px;font-weight:600">{churn_reason}</td>'
                f'<td style="color:#64748b;font-size:12px;max-width:200px">{churn_detail}</td>'
                f'<td style="text-align:center">'
                f'<input type="checkbox" id="cb_{safe_id}" onchange="saveClawback(\'{safe_id}\')" '
                f'style="width:16px;height:16px;cursor:pointer;accent-color:#f87171">'
                f'</td>'
                f'<td>'
                f'<input type="date" id="dt_{safe_id}" onchange="saveClawback(\'{safe_id}\')" '
                f'style="background:#0f172a;border:1px solid #1e293b;color:#94a3b8;padding:4px 8px;border-radius:4px;font-size:12px;width:130px">'
                f'</td>'
                f'</tr>'
            )

    # ── By-rep breakdown ──────────────────────────────────────────────────
    by_rep = defaultdict(lambda: {"count": 0, "mrr": 0, "reasons": Counter()})
    for c in clients:
        rep = c["sales_rep"] or "Unassigned"
        by_rep[rep]["count"] += 1
        by_rep[rep]["mrr"] += c["mrr"]
        reason = c["status"].replace("Canceled - ", "") if c["status"] else "Unknown"
        by_rep[rep]["reasons"][reason] += 1

    rep_rows = ""
    for rep, d in sorted(by_rep.items(), key=lambda x: -x[1]["count"]):
        top_reasons = ", ".join(f'{r} ({n})' for r, n in d["reasons"].most_common(3))
        rep_rows += (
            f'<tr style="border-bottom:1px solid #0f172a">'
            f'<td style="color:#e2e8f0;font-weight:600">{rep}</td>'
            f'<td style="color:#f87171;font-weight:700;text-align:center">{d["count"]}</td>'
            f'<td style="text-align:center">{mrr_fmt(d["mrr"])}</td>'
            f'<td style="color:#64748b;font-size:12px">{top_reasons}</td>'
            f'</tr>'
        )

    rep_stats_html = (
        f'<div class="sec" style="margin-top:20px">'
        f'<div class="sec-title">Cancellations by Sales Rep (2026)</div>'
        f'<table><thead><tr>'
        f'<th>Sales Rep</th><th style="text-align:center">Cancellations</th>'
        f'<th style="text-align:center">MRR Lost</th><th>Top Reasons</th>'
        f'</tr></thead><tbody>{rep_rows}</tbody></table></div>'
    )

    return {"total_mrr": total_mrr, "total": len(clients), "reason_pills": reason_pills, "rows": rows, "rep_stats": rep_stats_html}


# ── Assemble full page ──────────────────────────────────────────────────────
rts_clients = pull_rts_clients()
canceled_clients = pull_canceled_clients()
rts = build_rts_section(rts_clients)
can = build_canceled_section(canceled_clients)

roe_html = (
    '<div style="background:#0a0f1a;border:1px solid #1e3a5f;border-radius:10px;padding:16px 20px;margin-bottom:20px">'
    '<div style="font-size:11px;font-weight:700;color:#38bdf8;letter-spacing:2px;text-transform:uppercase;margin-bottom:10px">📋 Rules of Engagement</div>'
    '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;font-size:12px;color:#94a3b8;line-height:1.5">'
    '<div><span style="color:#fbbf24;font-weight:700">Off Track:</span> SA escalates within 24hrs.</div>'
    '<div><span style="color:#64748b;font-weight:700">On Hold:</span> SA contacts every 2-3 days. 3 no-responses → RTS.</div>'
    '<div><span style="color:#f87171;font-weight:700">RTS:</span> Sales engages in <strong style="color:#fff">24hrs</strong>. Timeline in <strong style="color:#fff">5 biz days</strong> or canceled.</div>'
    '<div><span style="color:#a78bfa;font-weight:700">Cancel:</span> Requires specific documented reason. No "Other."</div>'
    '</div></div>'
)

css = """*{margin:0;padding:0;box-sizing:border-box}
body{background:#000;font-family:'Segoe UI',system-ui,sans-serif;color:#e2e8f0;min-height:100vh;padding:36px 48px}
h1{font-size:26px;font-weight:700;color:#fff;margin-bottom:4px}
.sub{font-size:13px;color:#475569;margin-bottom:20px}
.kpi-row{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}
.kpi{background:#1e293b;border-radius:10px;padding:18px 18px;flex:1;min-width:140px;position:relative;overflow:hidden}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;background:var(--accent)}
.kpi-l{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:6px}
.kpi-v{font-size:42px;font-weight:800;line-height:1;color:var(--accent)}
.kpi-s{font-size:11px;color:#475569;margin-top:4px}
.sec{background:#1e293b;border-radius:10px;padding:20px;margin-bottom:20px}
.sec-title{font-size:12px;font-weight:700;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px}
.pill-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:0}
.divider{border:none;border-top:2px solid #1e3a5f;margin:28px 0}
table{width:100%;border-collapse:collapse}
thead th{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#475569;padding:7px 10px;text-align:left;border-bottom:1px solid #0f172a}
.cr:hover{background:#0f172a55}
tbody td{padding:9px 10px;font-size:13px;color:#94a3b8;vertical-align:middle}
.footer{font-size:11px;color:#334155;margin-top:24px;text-align:center}"""

html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PSA Onboarding Tracker</title>
<style>{css}</style>
</head><body>
<div style="position:relative">
  <img src="https://raw.githubusercontent.com/koontz-robin/robin-decks/master/revio-logo.png" style="position:absolute;top:0;right:0;height:44px;opacity:0.95" alt="rev.io">
  <h1>PSA Onboarding Tracker</h1>
  <p class="sub">Return to Sales · Cancellations · {today_str}</p>
</div>

{roe_html}

<!-- ═══ RTS SECTION ═══ -->
<div style="font-size:14px;font-weight:700;color:#f87171;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;padding-bottom:6px;border-bottom:2px solid #f87171">
  🔴 Return to Sales — {rts['total']} Accounts
</div>

<div class="kpi-row">
  <div class="kpi" style="--accent:#f87171"><div class="kpi-l">Clients in RTS</div><div class="kpi-v">{rts['total']}</div><div class="kpi-s">Active RTS accounts</div></div>
  <div class="kpi" style="--accent:#fbbf24"><div class="kpi-l">MRR at Risk</div><div class="kpi-v" style="font-size:32px">{mrr_fmt(rts['total_mrr'])}</div><div class="kpi-s">Monthly recurring</div></div>
  <div class="kpi" style="--accent:#f87171"><div class="kpi-l">🚨 No Contact</div><div class="kpi-v">{rts['no_contact']}</div><div class="kpi-s">24hr SLA violated</div></div>
  <div class="kpi" style="--accent:#fbbf24"><div class="kpi-l">⚠️ Cancel Risk</div><div class="kpi-v">{rts['cancel_risk']}</div><div class="kpi-s">&gt;5 biz days no resolution</div></div>
  <div class="kpi" style="--accent:#94a3b8"><div class="kpi-l">Critical (&gt;20d)</div><div class="kpi-v">{rts['critical']}</div><div class="kpi-s">Calendar days in RTS</div></div>
</div>

<div class="sec"><div class="sec-title">By Sales Rep</div><div class="pill-row">{rts['rep_cards']}</div></div>

<div class="sec">
  <div class="sec-title">All RTS Clients — sorted by urgency · click to expand SF activity</div>
  <table><thead><tr>
    <th>Client</th><th>Status</th><th>Sales Rep</th><th>SA</th>
    <th>MRR</th><th>Date Sold</th><th>RTS Start</th><th>Days RTS</th><th>Last SF Outreach</th><th style="color:#38bdf8;min-width:160px">Sales Notes</th><th>Notes</th>
  </tr></thead><tbody>{rts['rows']}</tbody></table>
</div>

<hr class="divider">

<!-- ═══ CANCELED SECTION ═══ -->
<div style="font-size:14px;font-weight:700;color:#94a3b8;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;padding-bottom:6px;border-bottom:2px solid #334155">
  ✗ Canceled Accounts — {can['total']} Total · {mrr_fmt(can['total_mrr'])} Lost MRR
</div>

<div class="sec"><div class="sec-title">Cancellation Reasons</div><div class="pill-row">{can['reason_pills']}</div></div>

<div class="sec">
  <div class="sec-title">All Canceled Accounts — sorted by cancel date</div>
  <table><thead><tr>
    <th>Client</th><th>Reason</th><th>Sales Rep</th><th>SA</th>
    <th>MRR</th><th>Date Sold</th><th>Date Canceled</th><th>Onboard Type</th><th>Churn Reason (SF)</th><th>Churn Detail (SF)</th>
    <th style="text-align:center">Clawback</th><th>Clawback Date</th>
  </tr></thead><tbody>{can['rows']}</tbody></table>
</div>

{can['rep_stats']}

<div class="footer">Rev.io PSA · Onboarding Tracker · Robin auto-refresh every 30 min · {today_str}</div>
<script>
function toggle(id){{var r=document.getElementById('a_'+id);if(r){{r.style.display=r.style.display==='none'?'table-row':'none';}}}}

function saveClawback(id) {{
  var cb = document.getElementById('cb_' + id);
  var dt = document.getElementById('dt_' + id);
  if (cb) localStorage.setItem('cb_' + id, cb.checked ? '1' : '0');
  if (dt) localStorage.setItem('dt_' + id, dt.value || '');
}}

function loadClawbacks() {{
  document.querySelectorAll('[id^="cb_"]').forEach(function(cb) {{
    var id = cb.id.replace('cb_', '');
    var saved = localStorage.getItem('cb_' + id);
    if (saved === '1') cb.checked = true;
    var dt = document.getElementById('dt_' + id);
    var savedDate = localStorage.getItem('dt_' + id);
    if (dt && savedDate) dt.value = savedDate;
  }});
}}

document.addEventListener('DOMContentLoaded', loadClawbacks);
</script>
</body></html>"""

with open(OUTPUT_FILE, "w") as f:
    f.write(html)
print(f"Built: {len(html):,} chars")

# Push to GitHub
env = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no"}
subprocess.run(["git", "add", "psa-onboarding-tracker.html"], cwd=REPO_PATH)
diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_PATH)
if diff.returncode != 0:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    subprocess.run(["git", "commit", "-m", f"PSA Onboarding Tracker - {now_str}"], cwd=REPO_PATH)
    subprocess.run(["git", "push", "origin", "master"], cwd=REPO_PATH, env=env)
    print("✅ Pushed to GitHub")
