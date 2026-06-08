#!/usr/bin/env python3
"""Build the AE Capacity Dashboard from refreshed Salesforce data."""

import json
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
DATA_FILE = Path("/tmp/ae_capacity_data.json")
HTML_FILE = WORKSPACE / "ae-capacity-dashboard.html"
ET = ZoneInfo("America/New_York")

MONTH_ORDER = ["jan", "feb", "mar", "apr", "may", "jun"]
MONTH_COLORS = {
    "jan": "#38bdf8",
    "feb": "#a78bfa",
    "mar": "#34d399",
    "apr": "#f97316",
    "may": "#ec4899",
    "jun": "#facc15",
}


def biz_rate(month):
    return month["total"] / (month["biz_done"] * month["aes"]) if month["biz_done"] and month["aes"] else 0


def final_rate(month):
    return month["total"] / (month["biz"] * month["aes"]) if month["biz"] and month["aes"] else 0


def trend_icon(current, previous):
    if previous == 0 and current > 0:
        return '<span class="trend up">▲</span>'
    if previous == 0:
        return '<span class="trend flat">—</span>'
    if current > previous * 1.05:
        return '<span class="trend up">▲</span>'
    if current < previous * 0.95:
        return '<span class="trend down">▼</span>'
    return '<span class="trend flat">—</span>'


def card_html(key, month):
    color = MONTH_COLORS[key]
    rate = biz_rate(month) if month["status"] == "current" else final_rate(month)
    label = f"{month['label']} 2026"
    status = "MTD" if month["status"] == "current" else "Final"
    projection = ""
    if month["status"] == "current":
        projection = (
            f'<div class="projection">Projected: <strong style="color:{color}">{month["projected"]}</strong>'
            f' · {month["biz_remain"]} biz days left</div>'
        )
    return f"""
<div class="card" style="--accent:{color}">
  <div class="month-label">{escape(label)} — {status}</div>
  <div class="meetings-val">{month["total"]}</div>
  <div class="meetings-label">prospect meetings</div>
  <div class="ae-badge">
    <div class="ae-num">{month["aes"]}</div>
    <div class="ae-text">AE roster<br>only</div>
  </div>
  <div class="rate">{rate:.2f} mtgs/AE/day</div>
  {projection}
</div>"""


def rep_rows(data):
    rows = []
    months = data["months"]
    for rep in data["ae_roster"]:
        counts = [months[key]["by_rep"].get(rep, 0) for key in MONTH_ORDER]
        trend = trend_icon(counts[-1], counts[-2])
        cells = []
        for key, count in zip(MONTH_ORDER, counts):
            cells.append(
                f'<td style="text-align:center;color:{MONTH_COLORS[key]};font-weight:700">{count}</td>'
            )
        rows.append(
            f"""
<tr>
  <td class="rep-name">{escape(rep)}</td>
  {''.join(cells)}
  <td style="text-align:center">{trend}</td>
</tr>"""
        )
    return "\n".join(rows)


def chart_rows(data):
    months = data["months"]
    max_value = max(months[key]["projected"] for key in MONTH_ORDER) or 1
    rows = []
    for key in MONTH_ORDER:
        month = months[key]
        actual_pct = month["total"] / max_value * 100
        projected_extra = max(month["projected"] - month["total"], 0)
        projected_pct = projected_extra / max_value * 100
        projected = ""
        if month["status"] == "current" and projected_extra:
            projected = f'<div class="bar-projected" style="width:{projected_pct:.1f}%">→ {month["projected"]}</div>'
        rows.append(
            f"""
<div class="bar-row">
  <div class="bar-month">{escape(month["label"])} 2026</div>
  <div class="bar-track">
    <div class="bar-actual" style="background:{MONTH_COLORS[key]};width:{actual_pct:.1f}%">{month["total"]}</div>
    {projected}
  </div>
  <div class="bar-stat">{final_rate(month) if month["status"] != "current" else biz_rate(month):.2f} / AE / day</div>
</div>"""
        )
    return "\n".join(rows)


def main():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    generated_at = datetime.now(ET)
    month_headers = "".join(
        f'<th style="color:{MONTH_COLORS[key]}">{data["months"][key]["label"]}</th>' for key in MONTH_ORDER
    )
    cards = "\n".join(card_html(key, data["months"][key]) for key in MONTH_ORDER)
    june = data["months"]["jun"]
    may = data["months"]["may"]

    css = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #000; font-family: 'Segoe UI', system-ui, sans-serif; color: #e2e8f0; min-height: 100vh; padding: 40px 48px; }
h1 { font-size: 26px; font-weight: 700; color: #fff; margin-bottom: 6px; }
.subtitle { font-size: 14px; color: #94a3b8; margin-bottom: 32px; }
.grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 18px; margin-bottom: 28px; }
.card { background: #1e293b; border-radius: 12px; padding: 22px 20px; position: relative; overflow: hidden; min-width: 0; }
.card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px; background: var(--accent); }
.month-label { font-size: 11px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; color: #64748b; margin-bottom: 14px; white-space: nowrap; }
.meetings-val { font-size: 54px; font-weight: 800; line-height: 1; margin-bottom: 4px; color: var(--accent); }
.meetings-label { font-size: 13px; color: #94a3b8; margin-bottom: 18px; }
.ae-badge { display: inline-flex; align-items: center; gap: 8px; background: #0f172a; border-radius: 8px; padding: 8px 12px; }
.ae-num { font-size: 21px; font-weight: 700; color: #fff; }
.ae-text { font-size: 12px; color: #64748b; line-height: 1.25; }
.rate { font-size: 13px; color: #94a3b8; margin-top: 14px; }
.projection { font-size: 12px; color: #94a3b8; margin-top: 6px; line-height: 1.35; }
.summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-bottom: 28px; }
.summary-card { background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 16px 18px; }
.summary-label { color: #64748b; font-size: 11px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px; }
.summary-value { color: #fff; font-size: 24px; font-weight: 800; }
.summary-sub { color: #94a3b8; font-size: 12px; margin-top: 4px; }
.chart-section, .rep-table { background: #1e293b; border-radius: 12px; padding: 22px 20px; margin-bottom: 28px; }
.section-title { color: #64748b; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 18px; }
.bar-row { display: grid; grid-template-columns: 92px minmax(0, 1fr) 110px; gap: 14px; align-items: center; margin-bottom: 13px; }
.bar-month { color: #94a3b8; font-size: 12px; font-weight: 700; }
.bar-track { height: 30px; background: #0f172a; border-radius: 6px; overflow: hidden; display: flex; }
.bar-actual, .bar-projected { height: 100%; min-width: 34px; display: flex; align-items: center; padding-left: 10px; color: #0f172a; font-size: 12px; font-weight: 800; }
.bar-projected { background: #fde68a; color: #422006; opacity: .72; }
.bar-stat { color: #94a3b8; font-size: 12px; text-align: right; }
.rep-table { overflow: hidden; padding: 0; }
.rep-table table { width: 100%; border-collapse: collapse; }
.rep-table th { font-size: 10px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #64748b; padding: 11px 12px; text-align: center; background: #0f172a; }
.rep-table th:first-child { text-align: left; }
.rep-table td { border-bottom: 1px solid #0f172a; padding: 9px 12px; font-size: 13px; }
.rep-table tr:last-child td { border-bottom: none; }
.rep-name { color: #e2e8f0; font-weight: 700; }
.trend.up { color: #34d399; } .trend.down { color: #f87171; } .trend.flat { color: #64748b; }
.footer { margin-top: 30px; font-size: 11px; color: #475569; text-align: center; letter-spacing: 1px; }
@media (max-width: 1300px) { .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) { body { padding: 24px 18px; } .grid, .summary { grid-template-columns: 1fr; } .bar-row { grid-template-columns: 1fr; } .bar-stat { text-align:left; } }
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AE Capacity Dashboard</title>
<style>{css}</style>
</head>
<body>
<h1>AE Capacity Dashboard</h1>
<div class="subtitle">Prospect meetings completed by month · Seven-AE roster only · Refreshed {generated_at.strftime('%B %-d, %Y %-I:%M %p ET')}</div>

<div class="grid">
{cards}
</div>

<div class="summary">
  <div class="summary-card">
    <div class="summary-label">Final May</div>
    <div class="summary-value">{may["total"]} meetings</div>
    <div class="summary-sub">{final_rate(may):.2f} meetings / AE / day</div>
  </div>
  <div class="summary-card">
    <div class="summary-label">June MTD</div>
    <div class="summary-value">{june["total"]} meetings</div>
    <div class="summary-sub">{biz_rate(june):.2f} meetings / AE / day through {june["biz_done"]} biz days</div>
  </div>
  <div class="summary-card">
    <div class="summary-label">June Projection</div>
    <div class="summary-value">{june["projected"]} meetings</div>
    <div class="summary-sub">{june["biz_remain"]} business days remaining</div>
  </div>
</div>

<div class="chart-section">
  <div class="section-title">Monthly Comparison</div>
  {chart_rows(data)}
</div>

<div class="rep-table">
  <table>
    <thead><tr>
      <th>AE</th>
      {month_headers}
      <th>Jun vs May</th>
    </tr></thead>
    <tbody>
      {rep_rows(data)}
    </tbody>
  </table>
</div>

<div class="footer">REV.IO SALES INTELLIGENCE · SEVEN ACCOUNT EXECUTIVES ONLY · SALESFORCE COMPLETED PROSPECT MEETINGS</div>
</body>
</html>
"""
    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"Built {HTML_FILE.name}: {len(html):,} chars")


if __name__ == "__main__":
    main()
