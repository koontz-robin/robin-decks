#!/usr/bin/env python3
"""Build 2026 New + Classic Rev.io pipeline source performance dashboard."""
from collections import Counter
from datetime import datetime, timezone
from math import ceil
from zoneinfo import ZoneInfo
from html import escape
from pathlib import Path
import re
from build_september_update_deck import sf_auth, sf_query, source

ROOT = Path(__file__).parent
OUT = ROOT / "pipeline-source-performance-dashboard.html"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"]
REPS = {1: 12, 2: 11, 3: 9, 4: 7, 5: 7, 6: 7, 7: 7, 8: 7, 9: 7, 10: 8}
SDR_HEADCOUNT = {1: 5, 2: 4, 3: 6, 4: 6, 5: 6, 6: 6, 7: 5, 8: 6, 9: 6, 10: 5}
ALLOWED = {"PSA", "PSA 2.0", "Billing", "Billing Add-on", "Odin"}
SOURCE_ORDER = ["Sales", "Tradeshow", "Website", "Paid Media", "SEO", "Email", "Rev.io Summit", "Referral", "Webinar", "Partner/Channel", "Phone"]
EXCLUDED_OWNERS = {"justinlee", "ingridbeard", "jakobchampion", "katerrastephensongreenwood"}


def owner_key(x):
    owner = x.get("Owner") or {}
    name = owner.get("Name") if isinstance(owner, dict) else str(owner)
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def pct(n, d):
    return 100 * n / d if d else None


def fmt_pct(v):
    return "—" if v is None else f"{v:.1f}%"


def td_pct(v, kind="share"):
    if v is None:
        return '<td class="na">—</td>'
    scale = min(v / (70 if kind == "share" else 50), 1)
    hue = 187 if kind == "share" else 151
    return f'<td style="--heat:{scale:.3f};--hue:{hue}">{v:.1f}%</td>'


def main():
    base, headers = sf_auth()
    fields = "Id,Name,Amount,CreatedDate,CloseDate,StageName,Product_Type__c,Marketing_Source__c,SDR_Influence__c,Owner.Name"
    all_opps = sf_query(base, headers, f"SELECT {fields} FROM Opportunity WHERE (CreatedDate>=2026-01-01T00:00:00Z AND CreatedDate<2026-11-01T00:00:00Z) OR (CloseDate>=2026-01-01 AND CloseDate<2026-11-01) ORDER BY CreatedDate")
    opps = [x for x in all_opps if (x.get("Product_Type__c") or "") in ALLOWED and owner_key(x) not in EXCLUDED_OWNERS]

    created = {m: [x for x in opps if (x.get("CreatedDate") or "").startswith(f"2026-{m:02d}")] for m in range(1, 11)}
    decided = {m: [x for x in opps if x.get("StageName") in ("Closed Won", "Closed Lost") and (x.get("CloseDate") or "").startswith(f"2026-{m:02d}")] for m in range(1, 11)}

    totals = [len(created[m]) for m in range(1, 11)]
    avgs = [totals[m-1] / REPS[m] for m in range(1, 11)]
    ytd_total = sum(totals)
    weighted_reps = sum(REPS.values())
    avg_per_rep_month = ytd_total / weighted_reps

    source_counts = {s: [sum(source(x) == s for x in created[m]) for m in range(1, 11)] for s in SOURCE_ORDER}
    source_shares = {s: [pct(source_counts[s][m-1], totals[m-1]) for m in range(1, 11)] for s in SOURCE_ORDER}
    source_avg_shares = {s: sum(v for v in source_shares[s] if v is not None) / len([v for v in source_shares[s] if v is not None]) for s in SOURCE_ORDER}
    sales_created = [[x for x in created[m] if source(x) == "Sales"] for m in range(1, 11)]
    sdr_influenced = [
        [x for x in month_rows if str(x.get("SDR_Influence__c") or "").strip().lower() not in ("", "none")]
        for month_rows in sales_created
    ]
    sdr_rates = [pct(len(influenced), len(sales)) for influenced, sales in zip(sdr_influenced, sales_created)]
    sdr_opps_per_rep = [len(sdr_influenced[m-1]) / SDR_HEADCOUNT[m] for m in range(1, 11)]
    total_sdr_months = sum(SDR_HEADCOUNT.values())
    ytd_sdr_opps_per_rep = sum(len(rows) for rows in sdr_influenced) / total_sdr_months
    ytd_sdr_influence_rate = sum(len(rows) for rows in sdr_influenced) / sum(len(rows) for rows in sales_created)

    win_rates, win_counts = {}, {}
    for s in SOURCE_ORDER:
        rates, counts = [], []
        for m in range(1, 11):
            rows = [x for x in decided[m] if source(x) == s]
            wins = sum(x.get("StageName") == "Closed Won" for x in rows)
            rates.append(pct(wins, len(rows)))
            counts.append((wins, len(rows)))
        win_rates[s], win_counts[s] = rates, counts

    overall_decisions = sum(len(decided[m]) for m in range(1, 11))
    overall_wins = sum(sum(x.get("StageName") == "Closed Won" for x in decided[m]) for m in range(1, 11))
    overall_wr = pct(overall_wins, overall_decisions)

    # Q4 creation target: round the Jan-Sep full-month productivity baseline up
    # to a clear operating target of 21 opportunities per AE. Assume the
    # October team size (8 AEs) continues through November and December.
    full_month_ae_months = sum(REPS[m] for m in range(1, 10))
    full_month_opps = sum(totals[:9])
    baseline_per_ae = full_month_opps / full_month_ae_months
    # Calculate Q4 MRR targets from the established deal targets using the
    # agreed $1,038 planning MRR per closed deal.
    average_deal_size = 1038
    booking_targets = {10: 11, 11: 17, 12: 24}
    q4_mrr_targets = {m: booking_targets[m] * average_deal_size for m in (10, 11, 12)}
    q4_reps = {10: 8, 11: 8, 12: 8}
    q4_win_rate = (overall_wr or 0) / 100
    target_mix = {"Sales": .60, "Tradeshow": .20, "Website": .12, "Other": .08}
    q4_targets = {}
    target_per_ae = {}
    for m in (10, 11, 12):
        target_opps = ceil(booking_targets[m] / q4_win_rate)
        target_per_ae[m] = ceil(target_opps / q4_reps[m])
        q4_targets[m] = {
            "opps": target_opps,
            "wins": booking_targets[m],
            "bookings": q4_mrr_targets[m],
            "mix": {k: round(target_opps * v) for k, v in target_mix.items()},
        }
    october_pace = totals[9] / 15 * 31
    october_gap = max(q4_targets[10]["opps"] - totals[9], 0)

    # Payments targets: average 2026 Closed Won Payments opportunity amount
    # through the last complete month, multiplied by Ryan's monthly win targets.
    payments_won = [
        x for x in all_opps
        if x.get("StageName") == "Closed Won"
        and x.get("Product_Type__c") in ("Payments AR", "Payments AP")
        and "2026-01-01" <= (x.get("CloseDate") or "") < "2026-10-01"
    ]
    payments_average_opp = (
        sum(float(x.get("Amount") or 0) for x in payments_won) / len(payments_won)
        if payments_won else 0
    )
    payments_win_targets = {10: 8, 11: 10, 12: 12}
    payments_targets = {m: payments_average_opp * payments_win_targets[m] for m in (10, 11, 12)}

    # Tigerpaw migration plan: 50 Q4 closes with supplied monthly MRR targets.
    tp_migration_targets = {10: 12, 11: 17, 12: 21}
    tp_uplift_targets = {10: 2496, 11: 3536, 12: 4368}

    # 2027 capacity plan from the supplied monthly booking targets. Required
    # opportunity volume uses the filtered historical decision win rate;
    # required AEs use filtered Jan-Sep opportunities per AE-month.
    bookings_2027 = [16, 17, 18, 18, 19, 19, 20, 20, 21, 21, 22, 22]
    mrr_targets_2027 = [15072, 17489, 20466, 21600, 23228, 24396, 26560, 28125, 29978, 31574, 34760, 35200]
    implied_deal_size_2027 = [round(mrr / bookings) for mrr, bookings in zip(mrr_targets_2027, bookings_2027)]
    months_2027 = [datetime(2027, m, 1).strftime("%b") for m in range(1, 13)]
    planning_win_rate = (overall_wr or 0) / 100
    opps_2027 = [ceil(b / planning_win_rate) for b in bookings_2027]
    aes_2027 = [ceil(o / baseline_per_ae) for o in opps_2027]
    source_plan_2027 = {s: [] for s in ("Sales", "Tradeshow", "Website", "Other")}
    for total in opps_2027:
        sales = round(total * target_mix["Sales"])
        tradeshow = round(total * target_mix["Tradeshow"])
        website = round(total * target_mix["Website"])
        other = total - sales - tradeshow - website
        for s, value in (("Sales", sales), ("Tradeshow", tradeshow), ("Website", website), ("Other", other)):
            source_plan_2027[s].append(value)
    planning_sdr_influence_rate = .70
    planning_sdr_opps_per_rep = 12
    sdr_influenced_opps_2027 = [ceil(v * planning_sdr_influence_rate) for v in source_plan_2027["Sales"]]
    sdrs_2027 = [ceil(v / planning_sdr_opps_per_rep) for v in sdr_influenced_opps_2027]
    annual_bookings_2027 = sum(bookings_2027)
    annual_opps_2027 = sum(opps_2027)
    annual_mrr_2027 = sum(mrr_targets_2027)

    plan_rows = [
        ("MRR target", [f'${v/1000:.1f}K' for v in mrr_targets_2027], f'${annual_mrr_2027/1000:.1f}K'),
        ("Booking target", bookings_2027, sum(bookings_2027)),
        ("Implied avg deal", [f'${v:,}' for v in implied_deal_size_2027], f'${annual_mrr_2027/annual_bookings_2027:,.0f}'),
        ("Required opportunities", opps_2027, sum(opps_2027)),
        ("Required AEs", aes_2027, max(aes_2027)),
        ("Required SDRs", sdrs_2027, max(sdrs_2027)),
        ("Sales-sourced opps", source_plan_2027["Sales"], sum(source_plan_2027["Sales"])),
        ("SDR-influenced Sales opps", sdr_influenced_opps_2027, sum(sdr_influenced_opps_2027)),
        ("Tradeshow opps", source_plan_2027["Tradeshow"], sum(source_plan_2027["Tradeshow"])),
        ("Website opps", source_plan_2027["Website"], sum(source_plan_2027["Website"])),
        ("Other-source opps", source_plan_2027["Other"], sum(source_plan_2027["Other"])),
    ]
    plan_rows_2027 = "".join(
        f'<tr><th>{label}</th>' + "".join(f'<td>{v}</td>' for v in values) + f'<td class="avg">{annual if isinstance(annual, str) else f"{annual:,}"}</td></tr>'
        for label, values, annual in plan_rows
    )

    top_volume = max(SOURCE_ORDER, key=lambda s: sum(source_counts[s]))
    meaningful = [s for s in SOURCE_ORDER if sum(n for _, n in win_counts[s]) >= 20]
    top_win = max(meaningful, key=lambda s: pct(sum(w for w, _ in win_counts[s]), sum(n for _, n in win_counts[s])) or 0)

    target_cards = "".join(
        f'<div class="target-card {"live" if m == 10 else ""}"><div class="target-month">{datetime(2026,m,1).strftime("%B")}{" MTD" if m == 10 else ""}</div><div class="target-main"><strong>${q4_targets[m]["bookings"]:,.0f}</strong><span>MRR target</span></div><div class="target-grid"><div><b>{q4_targets[m]["wins"]}</b><small>bookings needed</small></div><div><b>{q4_targets[m]["opps"]}</b><small>opps required</small></div><div><b>{target_per_ae[m]}</b><small>opps / AE</small></div><div><b>{q4_reps[m]}</b><small>AEs</small></div></div>' + (f'<div class="pace"><b>{totals[9]}</b> created • <b>{october_gap}</b> remaining • pacing to <b>{october_pace:.0f}</b></div>' if m == 10 else '<div class="pace plan">Full-month operating target</div>') + '</div>'
        for m in (10, 11, 12)
    )

    payments_cards = "".join(
        f'<div class="mini-target"><span>{datetime(2026,m,1).strftime("%B")}</span><strong>${payments_targets[m]:,.0f}</strong><small>{payments_win_targets[m]} Payments wins × ${payments_average_opp:,.0f} average</small></div>'
        for m in (10, 11, 12)
    )
    tp_cards = "".join(
        f'<div class="mini-target"><span>{datetime(2026,m,1).strftime("%B")}</span><strong>{tp_migration_targets[m]}</strong><small>migrations closed</small><em>${tp_uplift_targets[m]:,.0f} uplift</em></div>'
        for m in (10, 11, 12)
    )

    monthly_cards = "".join(
        f'<div class="month-card {"current" if m == 10 else ""}"><span>{MONTHS[m-1]}{" MTD" if m == 10 else ""}</span><strong>{totals[m-1]}</strong><em>{REPS[m]} AEs</em><b>{avgs[m-1]:.1f} <small>opps / AE</small></b></div>'
        for m in range(1, 11)
    )

    share_rows = "".join(
        f'<tr><th>{escape(s)}</th>' + "".join(
            f'<td style="--heat:{min((share or 0)/70,1):.3f};--hue:187">{share:.1f}%<small class="cell-count">{count} opps</small></td>'
            for share, count in zip(source_shares[s], source_counts[s])
        ) + f'<td class="avg">{source_avg_shares[s]:.1f}%<small>{sum(source_counts[s])} YTD</small></td></tr>'
        for s in SOURCE_ORDER
    )
    sdr_rows = "".join([
        '<tr><th>Sales-generated opportunities</th>' + ''.join(f'<td>{len(rows)}</td>' for rows in sales_created) + f'<td class="avg">{sum(len(rows) for rows in sales_created):,}</td></tr>',
        '<tr><th>With SDR influence</th>' + ''.join(f'<td>{len(rows)}</td>' for rows in sdr_influenced) + f'<td class="avg">{sum(len(rows) for rows in sdr_influenced):,}</td></tr>',
        '<tr><th>SDR headcount</th>' + ''.join(f'<td>{SDR_HEADCOUNT[m]}</td>' for m in range(1, 11)) + f'<td class="avg">{total_sdr_months} SDR-months</td></tr>',
        '<tr><th>Influenced opps per SDR</th>' + ''.join(f'<td>{value:.1f}</td>' for value in sdr_opps_per_rep) + f'<td class="avg">{ytd_sdr_opps_per_rep:.1f}</td></tr>',
        '<tr><th>SDR-influenced percentage</th>' + ''.join(td_pct(rate, "win") for rate in sdr_rates) + f'<td class="avg">{fmt_pct(pct(sum(len(rows) for rows in sdr_influenced), sum(len(rows) for rows in sales_created)))}</td></tr>',
    ])

    win_rows = "".join(
        f'<tr><th>{escape(s)}</th>' + "".join(td_pct(v, "win") for v in win_rates[s]) +
        (lambda w, n: f'<td class="avg" title="{w} wins / {n} decisions">{fmt_pct(pct(w,n))}<small>{w}/{n}</small></td>')(
            sum(w for w, _ in win_counts[s]), sum(n for _, n in win_counts[s])) + '</tr>'
        for s in SOURCE_ORDER
    )

    max_total = max(totals)
    bars = "".join(
        f'<div class="bar-col"><div class="bar-value">{avgs[i]:.1f}</div><div class="bar" style="height:{44 + avgs[i]/max(avgs)*120:.0f}px"><i style="height:{totals[i]/max_total*100:.0f}%"></i></div><span>{MONTHS[i]}</span></div>'
        for i in range(10)
    )

    html = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rev.io Pipeline Source Performance</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Montserrat:wght@700;800;900&display=swap');
:root{{--bg:#071525;--card:#0e2338;--card2:#102a42;--line:rgba(255,255,255,.08);--text:#f3f8fc;--muted:#8195aa;--cyan:#24d2ef;--green:#42dca0;--gold:#f2bb5b}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 88% 2%,#103452 0,transparent 26%),var(--bg);color:var(--text);font-family:Inter,Arial,sans-serif}}.wrap{{max-width:1600px;margin:auto;padding:34px 36px 64px}}header{{display:flex;justify-content:space-between;gap:30px;align-items:flex-end;border-bottom:1px solid var(--line);padding-bottom:22px}}.kicker{{font:800 11px Montserrat;letter-spacing:2.4px;color:var(--cyan);text-transform:uppercase}}h1{{font:900 31px Montserrat;margin:7px 0 5px}}header p,.footnote{{color:var(--muted);margin:0;font-size:12px}}.stamp{{text-align:right;color:var(--muted);font-size:11px;line-height:1.7}}.stamp strong{{color:#fff}}.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}}.kpi,.panel,.month-card{{background:linear-gradient(145deg,var(--card2),var(--card));border:1px solid var(--line);border-radius:12px}}.kpi{{padding:17px 19px}}.kpi span{{font:700 9px Montserrat;letter-spacing:1.1px;color:var(--muted);text-transform:uppercase}}.kpi strong{{display:block;font:900 28px Montserrat;color:var(--cyan);margin:5px 0 2px}}.kpi em{{font-size:11px;color:var(--muted);font-style:normal}}h2{{font:800 15px Montserrat;margin:0 0 13px}}.targets{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:12px}}.target-card{{background:linear-gradient(145deg,#12304a,#0d2034);border:1px solid var(--line);border-radius:13px;padding:17px 18px}}.target-card.live{{border-color:rgba(36,210,239,.48);box-shadow:inset 0 0 24px rgba(36,210,239,.045)}}.target-month{{font:800 10px Montserrat;letter-spacing:1.4px;color:var(--cyan);text-transform:uppercase}}.target-main{{display:flex;align-items:baseline;gap:9px;margin:7px 0 11px}}.target-main strong{{font:900 35px Montserrat;color:#fff}}.target-main span{{font-size:11px;color:var(--muted)}}.target-grid{{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:10px 0}}.target-grid div{{text-align:center;border-right:1px solid var(--line)}}.target-grid div:last-child{{border:0}}.target-grid b{{display:block;font:800 16px Montserrat;color:var(--green)}}.target-grid small{{color:var(--muted);font-size:8px;text-transform:uppercase}}.pace{{margin-top:9px;color:#91a7b9;font-size:9px;text-align:center}}.pace b{{color:var(--gold)}}.pace.plan{{color:#627b91}}.method{{color:var(--muted);font-size:10px;line-height:1.55;margin-top:9px}}.comp-targets{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}}.comp-panel{{background:linear-gradient(145deg,var(--card2),var(--card));border:1px solid var(--line);border-radius:12px;padding:17px 18px}}.comp-panel h2{{margin-bottom:4px}}.comp-panel>p{{margin:0 0 12px;color:var(--muted);font-size:9px;line-height:1.45}}.mini-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.mini-target{{background:rgba(255,255,255,.035);border:1px solid var(--line);border-radius:9px;padding:11px;text-align:center}}.mini-target span{{display:block;color:var(--muted);font:700 8px Montserrat;text-transform:uppercase}}.mini-target strong{{display:block;color:var(--green);font:900 20px Montserrat;margin:5px 0 2px}}.mini-target small{{display:block;color:var(--muted);font-size:8px}}.mini-target em{{display:block;color:var(--cyan);font:700 9px Montserrat;margin-top:5px;font-style:normal}}.levers{{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:12px}}.lever{{background:rgba(255,255,255,.025);border:1px solid var(--line);border-radius:10px;padding:13px 14px;position:relative}}.lever-num{{position:absolute;right:11px;top:9px;font:900 22px Montserrat;color:rgba(36,210,239,.16)}}.lever strong{{display:block;font:800 11px Montserrat;color:#fff;margin-bottom:6px;padding-right:20px}}.lever p{{margin:0;color:var(--muted);font-size:9px;line-height:1.5}}.lever b{{color:var(--cyan)}}.section-label{{display:flex;align-items:center;gap:10px;margin:24px 0 10px}}.section-label span{{font:800 10px Montserrat;letter-spacing:1.2px;color:var(--cyan);text-transform:uppercase;white-space:nowrap}}.section-label i{{height:1px;background:var(--line);width:100%}}.months{{display:grid;grid-template-columns:repeat(10,1fr);gap:8px}}.month-card{{padding:13px 12px}}.month-card.current{{border-color:rgba(36,210,239,.45)}}.month-card span{{font:800 9px Montserrat;color:var(--muted);text-transform:uppercase}}.month-card strong{{display:block;font:900 22px Montserrat;color:#fff;margin-top:7px}}.month-card em{{display:block;color:var(--muted);font-style:normal;font-size:10px}}.month-card b{{display:block;color:var(--green);font:800 15px Montserrat;margin-top:9px;padding-top:8px;border-top:1px solid var(--line)}}.month-card small{{font:600 8px Inter;color:var(--muted)}}.panel{{padding:17px 18px;margin-top:12px}}.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:9px}}table{{width:100%;border-collapse:collapse;table-layout:fixed;min-width:1160px}}th,td{{padding:10px 6px;text-align:center;border-right:1px solid rgba(255,255,255,.045);border-bottom:1px solid rgba(255,255,255,.055);font-size:11px}}thead th{{background:#17364e;color:#94a8bc;font:700 9px Montserrat;text-transform:uppercase}}th:first-child{{text-align:left;padding-left:13px;width:145px}}tbody th{{color:#e9f0f6;font-size:11px}}td{{background:hsla(var(--hue),80%,50%,calc(var(--heat)*.22));color:#dbeaf3;font-weight:700}}td.avg{{background:#17364e;color:var(--cyan);font-weight:800}}td small.cell-count,td.avg small{{display:block;color:var(--muted);font-weight:600;font-size:8px;margin-top:2px}}td.na{{color:#445a6d;background:transparent}}.legend{{display:flex;justify-content:space-between;color:var(--muted);font-size:10px;margin:8px 2px 0}}.bars{{height:220px;display:flex;align-items:flex-end;gap:12px;padding:12px 8px 0}}.bar-col{{flex:1;text-align:center}}.bar{{height:170px;max-width:70px;margin:auto;background:rgba(255,255,255,.035);border-radius:7px 7px 2px 2px;display:flex;align-items:flex-end;overflow:hidden}}.bar i{{display:block;width:100%;background:linear-gradient(#28d7f2,#2877b7);border-radius:7px 7px 0 0}}.bar-value{{font:800 11px Montserrat;color:var(--green);margin-bottom:5px}}.bar-col span{{font:700 9px Montserrat;color:var(--muted);display:block;margin-top:6px}}.definition{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}}.definition div{{padding:12px 14px;background:rgba(255,255,255,.025);border:1px solid var(--line);border-radius:9px;color:var(--muted);font-size:11px;line-height:1.55}}.definition strong{{color:#fff}}.tabbar{{display:flex;gap:8px;margin:18px 0 4px;padding:5px;background:#0b1d30;border:1px solid var(--line);border-radius:11px;width:max-content}}.tabbtn{{border:0;background:transparent;color:var(--muted);font:800 10px Montserrat;letter-spacing:.7px;padding:10px 16px;border-radius:7px;cursor:pointer}}.tabbtn.active{{background:#173d58;color:var(--cyan);box-shadow:inset 0 0 0 1px rgba(36,210,239,.2)}}.tab-pane{{display:none}}.tab-pane.active{{display:block}}.plan-hero{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}}.plan-kpi{{background:linear-gradient(145deg,#12314b,#0e2236);border:1px solid var(--line);border-radius:12px;padding:17px}}.plan-kpi span{{display:block;font:700 9px Montserrat;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}}.plan-kpi strong{{display:block;font:900 28px Montserrat;color:var(--cyan);margin:6px 0 2px}}.plan-kpi em{{font-size:10px;color:var(--muted);font-style:normal}}.plan-notes{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}}.plan-note{{background:rgba(255,255,255,.025);border:1px solid var(--line);border-radius:10px;padding:14px;color:var(--muted);font-size:10px;line-height:1.55}}.plan-note strong{{display:block;color:#fff;font:800 11px Montserrat;margin-bottom:5px}}footer{{margin-top:18px;color:#62798f;font-size:10px;text-align:right}}@media(max-width:900px){{.kpis{{grid-template-columns:1fr 1fr}}.plan-hero{{grid-template-columns:1fr 1fr}}.plan-notes{{grid-template-columns:1fr}}.targets{{grid-template-columns:1fr}}.comp-targets{{grid-template-columns:1fr}}.levers{{grid-template-columns:1fr}}.months{{grid-template-columns:repeat(2,1fr)}}header{{display:block}}.stamp{{text-align:left;margin-top:12px}}.definition{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap"><header><div><div class="kicker">Rev.io Sales Intelligence</div><h1>Pipeline Source Performance</h1><p>New Rev.io + Classic Rev.io opportunities • January–October 2026</p></div><div class="stamp"><strong>October MTD through {datetime.now(ZoneInfo('America/New_York')).strftime('%B %d').replace(' 0', ' ')}</strong><br>Live Salesforce snapshot • Created and Close Date analysis</div></header><div class="tabbar"><button class="tabbtn" data-tab="tab-2026" onclick="showTab('tab-2026')">2026 Performance + Q4</button><button class="tabbtn active" data-tab="tab-2027" onclick="showTab('tab-2027')">2027 Targets</button></div>
<section id="tab-2027" class="tab-pane active"><div class="section-label"><span>2027 annual operating plan</span><i></i></div><div class="plan-hero"><div class="plan-kpi"><span>Annual booking target</span><strong>{annual_bookings_2027}</strong><em>${annual_mrr_2027/1000:.1f}K supplied annual MRR target</em></div><div class="plan-kpi"><span>Required opportunities</span><strong>{annual_opps_2027:,}</strong><em>Based on {overall_wr:.1f}% historical decision win rate</em></div><div class="plan-kpi"><span>AE productivity assumption</span><strong>{baseline_per_ae:.1f}</strong><em>Opportunities per AE-month</em></div><div class="plan-kpi"><span>Peak sales capacity</span><strong>{max(aes_2027)} AEs · {max(sdrs_2027)} SDRs</strong><em>Fully productive headcount required by year end</em></div></div><div class="panel"><h2>Monthly Bookings, Opportunity Requirements, and AE Capacity</h2><div class="table-wrap"><table><thead><tr><th>2027 Plan</th>{''.join(f'<th>{m}</th>' for m in months_2027)}<th>Annual</th></tr></thead><tbody>{plan_rows_2027}</tbody></table></div><div class="legend"><span>Opportunity requirement = bookings ÷ filtered historical decision win rate</span><span>AE requirement = opportunities ÷ {baseline_per_ae:.1f} historical opps per AE-month</span></div></div><div class="plan-notes"><div class="plan-note"><strong>Capacity ramp</strong>Start with <b>{aes_2027[0]} AEs and {sdrs_2027[0]} SDRs</b> in January and build to <b>{max(aes_2027)} AEs and {max(sdrs_2027)} SDRs</b> by year end. Hire 60–90 days before the capacity is required.</div><div class="plan-note"><strong>Source + SDR plan</strong>Maintain a 60% Sales / 20% Tradeshow / 12% Website / 8% Other mix. Plan for SDR influence on {planning_sdr_influence_rate*100:.0f}% of Sales-generated opportunities—up from the {ytd_sdr_influence_rate*100:.1f}% historical baseline—at a target of {planning_sdr_opps_per_rep} influenced opportunities per SDR-month, up from the {ytd_sdr_opps_per_rep:.1f} historical baseline.</div><div class="plan-note"><strong>Conversion safeguard</strong>The plan assumes the current {overall_wr:.1f}% decision win rate. Every one-point improvement lowers required annual opportunity volume and AE capacity.</div></div><div class="definition"><div><strong>2027 booking targets:</strong> 16, 17, 18, 18, 19, 19, 20, 20, 21, 21, 22, and 22 from January through December.</div><div><strong>MRR targets:</strong> Monthly targets rise from $15,072 in January to $35,200 in December, implying average deal size growth from ${implied_deal_size_2027[0]:,} to ${implied_deal_size_2027[-1]:,}.</div><div><strong>Same filters:</strong> New Rev.io + Classic Rev.io only, with Justin Lee, Ingrid Beard, Jakob Champion, and Katerra Stephenson-Greenwood excluded.</div></div><footer>2027 plan generated from the filtered 2026 performance baseline</footer></section>
<section id="tab-2026" class="tab-pane"><div class="section-label"><span>Q4 MRR targets & sales capacity</span><i></i></div><div class="targets">{target_cards}</div><div class="comp-targets"><section class="comp-panel"><h2>Payments MRR Targets</h2><p>Baseline: ${payments_average_opp:,.0f} average Closed Won Payments opportunity amount across {len(payments_won)} wins from January–September 2026. Targets use 8 wins in October, 10 in November, and 12 in December.</p><div class="mini-grid">{payments_cards}</div></section><section class="comp-panel"><h2>Tigerpaw Migration Targets</h2><p>Q4 goal: 50 migrations closed with a combined $10,400 MRR target across October through December.</p><div class="mini-grid">{tp_cards}</div></section></div><div class="levers"><div class="lever"><span class="lever-num">01</span><strong>AE Opportunity Floor</strong><p>Hold each AE to <b>17 → 19 → 21 created opportunities</b> per month—roughly 4–5 per week, with the strongest push in November and December.</p></div><div class="lever"><span class="lever-num">02</span><strong>Protect Website Leads</strong><p>Use a <b>five-minute response SLA</b>, same-day discovery booking, and escalation for untouched inbound leads.</p></div><div class="lever"><span class="lever-num">03</span><strong>Improve Tradeshow Conversion</strong><p>Prioritize accounts before events, pre-book meetings, and complete structured follow-up within <b>24 hours</b>.</p></div><div class="lever"><span class="lever-num">04</span><strong>Increase Targeted AE Prospecting</strong><p>Give every AE named accounts, protected prospecting blocks, and a goal of <b>10–12 Sales-sourced opportunities</b> monthly.</p></div></div>
<div class="kpis"><div class="kpi"><span>YTD opportunities created</span><strong>{ytd_total:,}</strong><em>New + Classic Rev.io</em></div><div class="kpi"><span>Average opportunities / AE-month</span><strong>{avg_per_rep_month:.1f}</strong><em>{weighted_reps} cumulative AE-months</em></div><div class="kpi"><span>Largest source</span><strong>{top_volume}</strong><em>{sum(source_counts[top_volume]):,} created • {sum(source_counts[top_volume])/ytd_total*100:.1f}% YTD</em></div><div class="kpi"><span>Overall decision win rate</span><strong>{overall_wr:.1f}%</strong><em>{overall_wins} wins / {overall_decisions} decisions</em></div></div>
<div class="section-label"><span>Monthly AE productivity</span><i></i></div><div class="months">{monthly_cards}</div>
<div class="panel"><h2>Opportunities Created per AE</h2><div class="bars">{bars}</div></div>
<div class="section-label"><span>Where opportunities come from</span><i></i></div><div class="panel"><h2>Source Share of Monthly Opportunities Created</h2><div class="table-wrap"><table><thead><tr><th>Marketing Source</th>{''.join(f'<th>{m}{"*" if m=="Oct" else ""}</th>' for m in MONTHS)}<th>Monthly Avg</th></tr></thead><tbody>{share_rows}</tbody></table></div><div class="legend"><span>Darker cells represent a larger share of the month</span><span>Each monthly column totals 100%</span></div></div>
<div class="section-label"><span>SDR influence on Sales-generated pipeline</span><i></i></div><div class="panel"><h2>Sales-Generated Opportunities with SDR Influence</h2><div class="table-wrap"><table><thead><tr><th>Metric</th>{''.join(f'<th>{m}{"*" if m=="Oct" else ""}</th>' for m in MONTHS)}<th>YTD</th></tr></thead><tbody>{sdr_rows}</tbody></table></div><div class="legend"><span>SDR influenced = SDR_Influence__c is populated and is not “None”</span><span>Denominator: Sales-generated New + Classic Rev.io opportunities</span></div></div>
<div class="section-label"><span>How each source converts</span><i></i></div><div class="panel"><h2>Decision Win Rate by Source and Close Month</h2><div class="table-wrap"><table><thead><tr><th>Marketing Source</th>{''.join(f'<th>{m}{"*" if m=="Oct" else ""}</th>' for m in MONTHS)}<th>YTD Win Rate</th></tr></thead><tbody>{win_rows}</tbody></table></div><div class="legend"><span>Win rate = Closed Won ÷ (Closed Won + Closed Lost)</span><span>YTD cells show wins / total decisions</span></div></div>
<div class="definition"><div><strong>Included products:</strong> PSA, PSA 2.0, Billing, Billing Add-on, and Odin. These represent New Rev.io and Classic Rev.io.</div><div><strong>Owner exclusions:</strong> Justin Lee, Ingrid Beard, Jakob Champion, and Katerra Stephenson-Greenwood are excluded from every metric and target calculation.</div><div><strong>Important:</strong> October is partial. Small-source percentages can swing sharply because their opportunity and decision counts are low.</div></div><footer>Generated {datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M UTC')} • Source: Salesforce</footer></section></div><script>function showTab(id){{document.querySelectorAll('.tab-pane').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('.tabbtn').forEach(x=>x.classList.toggle('active',x.dataset.tab===id));history.replaceState(null,'','#'+id)}}if(location.hash==='#tab-2026')showTab('tab-2026');</script></body></html>'''
    OUT.write_text(html)
    print(f"Wrote {OUT.name} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
