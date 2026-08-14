#!/usr/bin/env python3
"""Build a PSA Web SWMC re-open stage report from the generated CSV."""

import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import escape
from pathlib import Path


WORKSPACE = Path("/home/openclaw/.openclaw/workspace")
SOURCE = WORKSPACE / "reports" / "psa_web_swmc_reopened_since_2025-07-01.csv"
OUTPUT = WORKSPACE / "psa-web-swmc-reopened-stage-report.html"

STAGE_ORDER = [
    "Closed Won",
    "1- Discovery Scheduled",
    "2 - Discovery Completed",
    "3 - Initial Product Demo",
    "Closed Lost",
]


def money(value):
    try:
        number = float(value or 0)
    except ValueError:
        number = 0
    return f"${number:,.0f}"


def label_stage(stage):
    if stage == "1- Discovery Scheduled":
        return "Discovery Scheduled"
    if stage == "2 - Discovery Completed":
        return "Discovery Completed"
    if stage == "3 - Initial Product Demo":
        return "Initial Product Demo"
    return stage or "No later opportunity"


def clean(text):
    return " ".join(str(text or "").split())


def days_between(start, end):
    if not start or not end:
        return ""
    try:
        start_dt = datetime.fromisoformat(start[:10])
        end_dt = datetime.fromisoformat(end[:10])
    except ValueError:
        return ""
    return str((end_dt - start_dt).days)


def within_last_days(value, days):
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return False
    today = datetime.now().date()
    return today - timedelta(days=days) <= dt <= today


def within_date_range(value, start_date, end_date):
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return False
    return start_date <= dt <= end_date


def load_rows():
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def account_level(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row["Later PSA Opp ID"]:
            grouped[row["Account"]].append(row)

    accounts = []
    for account, account_rows in grouped.items():
        account_rows.sort(key=lambda item: (item["Later PSA Created Date"], item["Later PSA Opp"]))
        first = account_rows[0]
        latest = account_rows[-1]
        accounts.append(
            {
                "account": account,
                "vertical": first["Vertical"] or "Unknown",
                "industry": first["Industry"] or "Unknown",
                "first_lost_date": first["First SWMC Close Date"],
                "first_owner": first["First SWMC Owner"],
                "first_amount": first["First SWMC Amount"],
                "first_detail": first["First SWMC Detail"],
                "account_url": first["Account URL"],
                "first_opp_url": first["First SWMC Opp URL"],
                "latest_stage": latest["Later PSA Stage"],
                "latest_stage_label": label_stage(latest["Later PSA Stage"]),
                "latest_created": latest["Later PSA Created Date"],
                "latest_close": latest["Later PSA Close Date"],
                "latest_amount": latest["Later PSA Amount"],
                "latest_opp": latest["Later PSA Opp"],
                "latest_opp_url": latest["Later PSA Opp URL"],
                "latest_loss_reason": latest["Later PSA Loss Reason"],
                "latest_loss_detail": latest["Later PSA Detail"],
                "later_count": len(account_rows),
                "days_to_latest": days_between(first["First SWMC Close Date"], latest["Later PSA Created Date"]),
                "later_rows": account_rows,
            }
        )
    accounts.sort(key=lambda item: (STAGE_ORDER.index(item["latest_stage"]) if item["latest_stage"] in STAGE_ORDER else 99, item["account"].lower()))
    return accounts


def render_link(url, text):
    if not url:
        return escape(text)
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(text)}</a>'


def stage_slug(stage):
    return stage.lower().replace(" ", "-").replace("/", "-")


def stage_nav(stage_groups, prefix=""):
    parts = []
    for stage in STAGE_ORDER:
        if stage in stage_groups:
            label = label_stage(stage)
            count = len(stage_groups[stage])
            slug = f"{prefix}{stage_slug(stage)}"
            parts.append(f'<a class="stage-pill" href="#{slug}"><span>{escape(label)}</span><strong>{count}</strong></a>')
    return "\n".join(parts)


def render_stage_table(stage, rows, prefix=""):
    slug = f"{prefix}{stage_slug(stage)}"
    body = []
    for row in rows:
        later_note = ""
        if row["later_count"] > 1:
            later_note = f'<div class="mini">{row["later_count"]} later opps total</div>'
        later_loss = ""
        if stage == "Closed Lost":
            loss_reason = escape(row["latest_loss_reason"] or "No loss reason captured")
            loss_detail_text = row["latest_loss_detail"] or "No second closed-lost detail captured"
            loss_detail = escape(loss_detail_text[:520])
            if len(loss_detail_text) > 520:
                loss_detail += "..."
            later_loss = f"""
                <div class="loss-detail">
                  <strong>Second loss reason:</strong> {loss_reason}
                  <div>{loss_detail}</div>
                </div>
            """
        detail = escape(row["first_detail"][:420])
        if len(row["first_detail"]) > 420:
            detail += "..."
        body.append(
            f"""
            <tr>
              <td>
                <strong>{render_link(row["account_url"], row["account"])}</strong>
                <div class="mini">{escape(row["vertical"])} / {escape(row["industry"])}</div>
              </td>
              <td>
                {escape(row["first_lost_date"])}
                <div class="mini">{escape(row["first_owner"])} / {money(row["first_amount"])}</div>
              </td>
              <td>
                <strong>{render_link(row["latest_opp_url"], row["latest_opp"])}</strong>
                <div class="mini">{escape(row["latest_created"])} / {money(row["latest_amount"])} / {escape(row["days_to_latest"])} days later</div>
                {later_note}
                {later_loss}
              </td>
              <td>{detail}</td>
            </tr>
            """
        )
    return f"""
      <section class="band" id="{slug}">
        <div class="section-head">
          <h2>{escape(label_stage(stage))}</h2>
          <p>{len(rows)} accounts with latest later opportunity in this stage.</p>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>First SWMC loss</th>
                <th>Latest later PSA opp</th>
                <th>Original missing-capability note</th>
              </tr>
            </thead>
            <tbody>{''.join(body)}</tbody>
          </table>
        </div>
      </section>
    """


def render_closed_lost_trends(rows, prefix=""):
    closed_lost_rows = [row for row in rows if row["Later PSA Stage"] == "Closed Lost"]
    if not closed_lost_rows:
        return ""

    month_counts = Counter((row["Later PSA Close Date"] or row["Later PSA Created Date"])[:7] for row in closed_lost_rows)
    reason_counts = Counter(row["Later PSA Loss Reason"] or "No loss reason captured" for row in closed_lost_rows)
    by_account = defaultdict(list)
    for row in closed_lost_rows:
        by_account[row["Account"]].append(row)

    third_loss_accounts = {
        account: sorted(account_rows, key=lambda item: (item["Later PSA Close Date"], item["Later PSA Created Date"]))
        for account, account_rows in by_account.items()
        if len(account_rows) >= 2
    }
    max_month = max(month_counts.values() or [1])
    max_reason = max(reason_counts.values() or [1])

    month_rows = []
    for month in sorted(month_counts):
        count = month_counts[month]
        width = max(8, round(count / max_month * 100))
        month_rows.append(
            f"""
            <div class="bar-row compact">
              <div class="bar-label">{escape(month)}</div>
              <div class="bar-track"><span style="width:{width}%"></span></div>
              <div class="bar-value">{count}</div>
            </div>
            """
        )

    reason_rows = []
    for reason, count in reason_counts.most_common():
        width = max(8, round(count / max_reason * 100))
        reason_rows.append(
            f"""
            <div class="bar-row compact">
              <div class="bar-label">{escape(reason)}</div>
              <div class="bar-track red"><span style="width:{width}%"></span></div>
              <div class="bar-value">{count}</div>
            </div>
            """
        )

    third_rows = []
    for account, account_rows in sorted(third_loss_accounts.items(), key=lambda item: item[0].lower()):
        first = account_rows[0]
        losses = "; ".join(
            f"{row['Later PSA Close Date']} - {row['Later PSA Loss Reason'] or 'No reason captured'}"
            for row in account_rows
        )
        third_rows.append(
            f"""
            <tr>
              <td><strong>{render_link(first["Account URL"], account)}</strong><div class="mini">{escape(first["Vertical"])} / {escape(first["Industry"])}</div></td>
              <td>{escape(str(len(account_rows)))}</td>
              <td>{escape(losses)}</td>
            </tr>
            """
        )

    return f"""
      <section class="band" id="{prefix}closed-lost-trends">
        <div class="section-head">
          <h2>Later Closed Lost Trend</h2>
          <p>{len(closed_lost_rows)} later Closed Lost opps across {len(by_account)} accounts; {len(third_loss_accounts)} accounts had a third lost PSA opportunity.</p>
        </div>
        <div class="split">
          <div class="chart">
            <h3>By close month</h3>
            {''.join(month_rows)}
          </div>
          <div class="chart">
            <h3>By second loss reason</h3>
            {''.join(reason_rows)}
          </div>
        </div>
        <div class="table-wrap extra-table">
          <table>
            <thead>
              <tr>
                <th>Account with 3rd lost PSA opp</th>
                <th>Later closed-lost count</th>
                <th>Later closed-lost sequence</th>
              </tr>
            </thead>
            <tbody>{''.join(third_rows)}</tbody>
          </table>
        </div>
      </section>
    """


def build_dashboard_view(rows, view_id, label, prefix, active=False):
    accounts = account_level(rows)
    stage_groups = defaultdict(list)
    for account in accounts:
        stage_groups[account["latest_stage"]].append(account)

    later_stage_counts = Counter(row["Later PSA Stage"] for row in rows if row["Later PSA Opp ID"])
    unique_accounts = len(accounts)
    later_opps = sum(int(bool(row["Later PSA Opp ID"])) for row in rows)
    later_closed_lost_opps = sum(1 for row in rows if row["Later PSA Stage"] == "Closed Lost")
    won_accounts = len(stage_groups.get("Closed Won", []))
    active_accounts = sum(len(stage_groups.get(stage, [])) for stage in STAGE_ORDER if stage not in {"Closed Lost", "Closed Won"})
    closed_lost_accounts = len(stage_groups.get("Closed Lost", []))
    max_stage_count = max(later_stage_counts.values() or [1])
    bar_rows = []
    for stage in STAGE_ORDER:
        count = later_stage_counts.get(stage, 0)
        if not count:
            continue
        width = max(8, round(count / max_stage_count * 100))
        bar_rows.append(
            f"""
            <div class="bar-row">
              <div class="bar-label">{escape(label_stage(stage))}</div>
              <div class="bar-track"><span style="width:{width}%"></span></div>
              <div class="bar-value">{count}</div>
            </div>
            """
        )

    stage_sections = "\n".join(render_stage_table(stage, stage_groups[stage], prefix) for stage in STAGE_ORDER if stage in stage_groups)
    closed_lost_trends = render_closed_lost_trends(rows, prefix)
    active_class = " active" if active else ""
    return f"""
  <section id="{view_id}" class="dashboard-view{active_class}">
    <section class="summary">
      <div class="metric"><strong>{unique_accounts}</strong><span>accounts reopened</span></div>
      <div class="metric"><strong>{later_opps}</strong><span>later PSA opportunities</span></div>
      <div class="metric"><strong>{won_accounts}</strong><span>latest stage Closed Won</span></div>
      <div class="metric"><strong>{active_accounts}</strong><span>latest stage still active</span></div>
    </section>
    <section class="band">
      <div class="view-label">{escape(label)}</div>
      <div class="chart">
        <div class="section-head">
          <h2>Later Opportunity Stage Breakdown</h2>
          <p>{closed_lost_accounts} accounts recycled again to Closed Lost.</p>
        </div>
        {''.join(bar_rows)}
      </div>
      <nav class="stage-nav" aria-label="{escape(label)} stage sections">
        <a class="stage-pill" href="#{prefix}closed-lost-trends"><span>Closed Lost Trends</span><strong>{later_closed_lost_opps}</strong></a>
        {stage_nav(stage_groups, prefix)}
      </nav>
    </section>
    {closed_lost_trends}
    <div id="{prefix}stage-sections">{stage_sections}</div>
  </section>
    """


def main():
    rows = load_rows()
    june_aug_start = datetime(2026, 6, 1).date()
    june_aug_end = datetime(2026, 8, 31).date()
    june_aug_rows = [
        row for row in rows
        if row["Later PSA Opp ID"] and within_date_range(row["Later PSA Created Date"], june_aug_start, june_aug_end)
    ]
    generated = datetime.now().strftime("%b %-d, %Y %-I:%M %p")
    all_view = build_dashboard_view(rows, "all-time", "All time · reopened after SWMC loss since July 1, 2025", "all-", active=True)
    june_aug_view = build_dashboard_view(june_aug_rows, "june-august", "June-August · later PSA created Jun 1-Aug 31, 2026", "junaug-")
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PSA Web SWMC Re-Opened Opportunities by Stage</title>
  <style>
    :root {{
      --ink: #18212f;
      --muted: #647084;
      --line: #d9e0ea;
      --paper: #f8fafc;
      --navy: #17324d;
      --teal: #0f766e;
      --green: #18804d;
      --amber: #b7791f;
      --red: #b42318;
      --white: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--paper);
    }}
    a {{ color: #0d5f9f; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .hero {{
      background: linear-gradient(135deg, #102a43 0%, #17324d 48%, #0f766e 100%);
      color: white;
      padding: 44px clamp(20px, 5vw, 72px) 36px;
    }}
    .hero-inner, .band {{ max-width: 1280px; margin: 0 auto; }}
    .eyebrow {{ color: #9ee2d7; font-size: 13px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ margin: 12px 0 10px; font-size: clamp(32px, 4.4vw, 62px); line-height: 1.02; letter-spacing: 0; }}
    .lede {{ max-width: 880px; margin: 0; color: #d8e7ef; font-size: 18px; line-height: 1.55; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 24px; }}
    .meta span {{ border: 1px solid rgba(255,255,255,.24); background: rgba(255,255,255,.08); padding: 8px 10px; border-radius: 6px; font-size: 13px; }}
    .summary {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; padding: 22px clamp(20px, 5vw, 72px); background: white; border-bottom: 1px solid var(--line); }}
    .metric {{ border-left: 4px solid var(--teal); padding: 4px 0 4px 14px; }}
    .metric strong {{ display: block; font-size: 28px; line-height: 1; }}
    .metric span {{ display: block; margin-top: 6px; color: var(--muted); font-size: 13px; }}
    .band {{ padding: 28px clamp(20px, 5vw, 72px); }}
    .tabs {{ display: flex; gap: 8px; padding: 18px clamp(20px, 5vw, 72px) 0; background: white; border-bottom: 1px solid var(--line); }}
    .tab {{ appearance: none; border: 1px solid var(--line); border-bottom: 0; background: #f8fafc; color: var(--muted); border-radius: 8px 8px 0 0; padding: 10px 14px; font: inherit; font-size: 13px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; cursor: pointer; }}
    .tab.active {{ background: var(--navy); border-color: var(--navy); color: white; }}
    .dashboard-view {{ display: none; }}
    .dashboard-view.active {{ display: block; }}
    .view-label {{ color: var(--muted); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; margin-bottom: 14px; }}
    .chart, .stage-nav, .table-wrap {{ background: white; border: 1px solid var(--line); border-radius: 8px; }}
    .chart {{ padding: 18px; }}
    .stage-nav {{ display: flex; flex-wrap: wrap; gap: 10px; padding: 14px; margin-top: 16px; }}
    .stage-pill {{ display: inline-flex; align-items: center; gap: 10px; color: var(--ink); border: 1px solid var(--line); border-radius: 999px; padding: 8px 12px; background: #fbfcfe; }}
    .stage-pill strong {{ color: var(--teal); }}
    .bar-row {{ display: grid; grid-template-columns: 190px minmax(120px, 1fr) 54px; align-items: center; gap: 14px; margin: 13px 0; }}
    .bar-label {{ font-weight: 700; font-size: 14px; }}
    .bar-track {{ height: 16px; background: #e9eef5; border-radius: 999px; overflow: hidden; }}
    .bar-row.compact {{ grid-template-columns: 170px minmax(120px, 1fr) 44px; }}
    .bar-track span {{ display: block; height: 100%; background: linear-gradient(90deg, var(--teal), #31a6a0); border-radius: inherit; }}
    .bar-track.red span {{ background: linear-gradient(90deg, var(--red), #e0695f); }}
    .bar-value {{ text-align: right; font-weight: 800; }}
    .section-head {{ display: flex; justify-content: space-between; align-items: end; gap: 18px; margin-bottom: 12px; }}
    h2 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    h3 {{ margin: 0 0 14px; font-size: 17px; letter-spacing: 0; }}
    .section-head p {{ margin: 0; color: var(--muted); }}
    .split {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    .extra-table {{ margin-top: 16px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{ text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); padding: 12px 14px; font-size: 13px; line-height: 1.45; }}
    th {{ background: #f2f6fa; color: #334155; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }}
    tr:last-child td {{ border-bottom: 0; }}
    .mini {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    .loss-detail {{ margin-top: 8px; padding: 8px 10px; border-left: 3px solid var(--red); background: #fff7f6; color: #5f1d17; border-radius: 4px; }}
    .loss-detail strong {{ display: block; margin-bottom: 3px; color: var(--red); }}
    .toolbar {{ display: flex; gap: 10px; margin: 16px 0 0; }}
    input {{ width: min(520px, 100%); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; font: inherit; }}
    @media (max-width: 760px) {{
      .summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .section-head {{ display: block; }}
      .split {{ grid-template-columns: 1fr; }}
      .bar-row {{ grid-template-columns: 1fr 52px; }}
      .bar-track {{ grid-column: 1 / -1; grid-row: 2; }}
    }}
  </style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <div class="eyebrow">Rev.io PSA Web</div>
      <h1>Software Missing Capabilities Re-Opened Opportunities</h1>
      <p class="lede">Accounts with a PSA-family opportunity closed lost for Software Missing Capabilities since July 1, 2025, then another PSA-family opportunity opened afterward. Grouped by the latest later opportunity stage.</p>
      <div class="meta">
        <span>Source: Salesforce Opportunity</span>
        <span>Products: PSA 2.0 / PSA</span>
        <span>Generated {escape(generated)}</span>
      </div>
    </div>
  </header>
  <nav class="tabs" aria-label="Date range">
    <button class="tab active" type="button" onclick="showView('all-time', this)">All Time</button>
    <button class="tab" type="button" onclick="showView('june-august', this)">June-August</button>
  </nav>
  <main>
    <section class="band" style="padding-top:18px;padding-bottom:0">
      <div class="toolbar">
        <input id="search" type="search" placeholder="Filter accounts, stages, industries, notes">
      </div>
    </section>
    {all_view}
    {june_aug_view}
  </main>
  <script>
    const search = document.getElementById('search');
    search.addEventListener('input', () => {{
      const term = search.value.trim().toLowerCase();
      document.querySelectorAll('tbody tr').forEach(row => {{
        row.style.display = !term || row.textContent.toLowerCase().includes(term) ? '' : 'none';
      }});
    }});
    function showView(id, btn) {{
      document.querySelectorAll('.dashboard-view').forEach(view => view.classList.toggle('active', view.id === id));
      document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
      btn.classList.add('active');
      search.value = '';
      document.querySelectorAll('tbody tr').forEach(row => row.style.display = '');
    }}
  </script>
</body>
</html>
"""
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    print(f"All-time accounts reopened: {len(account_level(rows))}")
    print(f"June-August accounts reopened: {len(account_level(june_aug_rows))}")


if __name__ == "__main__":
    main()
