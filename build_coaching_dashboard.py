#!/usr/bin/env python3
"""Rebuild the Rep Coaching Dashboard from Notion scorecards."""
import json, subprocess, os
from datetime import datetime
from html import escape

REPO = os.path.dirname(os.path.abspath(__file__))

with open("/tmp/coaching_summaries.json") as f:
    data = json.load(f)

AES = {"Andrew Whisenant","Connor Flynn","Husam Zalmiyar","Jake Borah","Jamie Butler","Jaylin Bender","Patrick Davies"}
CSAS = {"Ingrid Beard","Justin Lee"}

PROFILE_LINKS = {
    "Jaylin Bender": "https://www.linkedin.com/in/jaylin-bender-384a771a1/",
    "Husam Zalmiyar": "https://www.linkedin.com/in/husam-zalmiyar-a22a0b278/",
    "Jake Borah": "https://www.linkedin.com/in/jakeborah/",
    "Patrick Davies": "https://www.linkedin.com/in/patrickdavies05/",
    "Jamie Butler": "https://www.linkedin.com/in/jamisonbutler/",
    "Andrew Whisenant": "https://www.linkedin.com/in/andywhisenant/",
    "Connor Flynn": "https://www.linkedin.com/in/connor-flynn-1635b6198/",
    "Justin Lee": "https://www.linkedin.com/in/justin-lee/",
    "Ingrid Beard": "https://www.linkedin.com/in/ingrid-beard-6967562b/",
}

PROFILE_IMAGES = {
    "Jaylin Bender": "rep-headshots/jaylin-bender.png",
    "Patrick Davies": "rep-headshots/patrick-davies.jpg",
    "Jamie Butler": "rep-headshots/jamie-butler.png",
    "Andrew Whisenant": "rep-headshots/andrew-whisenant.jpg",
    "Connor Flynn": "rep-headshots/connor-flynn.jpg",
}

today_str = datetime.now().strftime("%B %d, %Y")
total_calls = sum(d['call_count'] for d in data.values())
team_avg = (
    sum(d['avg_score'] * d['call_count'] for d in data.values()) / total_calls
    if total_calls else 0
)
try:
    with open(f"{REPO}/rep_ytd_monthly_averages.json") as f:
        ytd_activity = json.load(f)
except FileNotFoundError:
    ytd_activity = {"months": 0, "metrics": {}}

def score_color(s):
    if s >= 80: return "#10B981"
    if s >= 65: return "#818CF8"
    if s >= 50: return "#F59E0B"
    return "#F43F5E"

def grade_label(s):
    if s >= 90: return "Elite"
    if s >= 80: return "Strong"
    if s >= 65: return "Solid"
    if s >= 50: return "Building"
    return "Developing"

def initials(name):
    parts = [p for p in name.replace(".", " ").split() if p]
    return "".join(p[0] for p in parts[:2]).upper()

def profile_header(rep):
    link = PROFILE_LINKS.get(rep, "#")
    img = PROFILE_IMAGES.get(rep)
    safe_rep = escape(rep)
    if img:
        avatar = (
            f'<img class="rep-avatar" src="{img}" alt="{safe_rep} profile photo" '
            f'loading="lazy">'
        )
    else:
        avatar = f'<div class="rep-avatar initials" aria-hidden="true">{initials(rep)}</div>'
    return (
        f'<a class="rep-profile" href="{link}" target="_blank" rel="noopener">'
        f'{avatar}<span>{safe_rep}</span></a>'
    )

def compact_number(value):
    if value == 0:
        return "0"
    if abs(value - round(value)) < 0.05:
        return f"{value:.0f}"
    return f"{value:.1f}"

def compact_currency(value):
    if value == 0:
        return "$0"
    if abs(value) >= 1000:
        return f"${value/1000:.1f}K"
    return f"${value:,.0f}"

def rep_activity_metrics(rep):
    metrics = ytd_activity.get("metrics", {}).get(rep, {})
    items = [
        ("Discovery", compact_number(metrics.get("discovery_calls", 0))),
        ("Initial Demos", compact_number(metrics.get("initial_demos", 0))),
        ("Closed Won", compact_number(metrics.get("opps_closed_won", 0))),
        ("MRR Closed", compact_currency(metrics.get("mrr_closed", 0))),
    ]
    cells = "".join(
        f'<div class="activity-metric"><div>{value}</div><span>{label}</span></div>'
        for label, value in items
    )
    return (
        f'<div class="activity-block">'
        f'<div class="activity-label">2026 Monthly Avg</div>'
        f'<div class="activity-grid">{cells}</div>'
        f'</div>'
    )

def build_rep_card(rep, d, is_csa=False):
    avg = d["avg_score"]; sc = score_color(avg)
    cats = d["cat_avgs"]; top3 = d["top_3"]
    calls = d["recent_calls"]; n = d["call_count"]

    coaching_items = ""
    for line in top3.split("\n"):
        line = line.strip()
        if not line: continue
        clean = line.lstrip("123456789. -").strip()
        if clean:
            coaching_items += (
            f'<div style="background:#0F172A;border-left:3px solid {sc};'
            f'border-radius:4px;padding:10px 12px;margin-bottom:8px">'
            f'<div style="font-size:12px;color:#E2E8F0;line-height:1.5">{clean}</div></div>'
            )

    recent_html = ""
    for c in calls[:4]:
        cs = score_color(c["score"])
        recent_html += (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:5px 0;border-bottom:1px solid #1E293B">'
            f'<span style="font-size:12px;color:#94a3b8">{(c["account"] or c["title"])[:35]}</span>'
            f'<span style="font-size:12px;font-weight:700;color:{cs}">{c["score"]}</span></div>'
        )

    bars = ""
    if is_csa:
        cat_map = [
            ("Approach","approach",15),("State of Union","company_story",20),
            ("Client Init.","qualifying",25),("Upsell Disc.","summarize",30),("Next Steps","next_steps",10)
        ]
    else:
        cat_map = [
            ("Approach","approach",15),("Co. Story","company_story",15),
            ("Qualifying","qualifying",40),("Summarize","summarize",20),("Next Steps","next_steps",10)
        ]
    for label, key, max_pts in cat_map:
        val = cats.get(key, 0)
        pct = min(100, val/max_pts*100) if max_pts else 0
        bar_color = "#F43F5E" if pct < 50 else "#F59E0B" if pct < 70 else "#818CF8"
        bars += (
            f'<div style="margin-bottom:6px">'
            f'<div style="display:flex;justify-content:space-between;margin-bottom:2px">'
            f'<span style="font-size:11px;color:#64748B">{label}</span>'
            f'<span style="font-size:11px;color:#94A3B8">{val:.0f}/{max_pts}</span></div>'
            f'<div style="background:#111827;border-radius:3px;height:5px">'
            f'<div style="width:{pct:.0f}%;height:100%;background:{bar_color};border-radius:3px"></div>'
            f'</div></div>'
        )

    return (
        f'<div style="background:#0F172A;border-radius:12px;overflow:hidden;border:1px solid #1E293B">'
        f'<div style="background:#111827;padding:16px 20px;display:flex;justify-content:space-between;'
        f'align-items:center;border-bottom:2px solid {sc}">'
        f'<div>{profile_header(rep)}'
        f'<div style="font-size:11px;color:#64748B;margin-top:2px">{n} graded {"CBRs" if is_csa else "calls"} · {grade_label(avg)}</div></div>'
        f'<div style="text-align:right"><div style="font-size:36px;font-weight:800;color:{sc};line-height:1">{avg:.0f}</div>'
        f'<div style="font-size:10px;color:#64748B">avg score</div></div></div>'
        f'{rep_activity_metrics(rep)}'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0">'
        f'<div style="padding:16px 18px;border-right:1px solid #1E293B">'
        f'<div style="font-size:10px;font-weight:700;color:#64748B;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin-bottom:10px">Category Averages</div>{bars}</div>'
        f'<div style="padding:16px 18px">'
        f'<div style="font-size:10px;font-weight:700;color:#64748B;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin-bottom:10px">Recent Calls</div>{recent_html}</div></div>'
        f'<div style="padding:16px 20px;border-top:1px solid #1E293B">'
        f'<div style="font-size:10px;font-weight:700;color:#64748B;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin-bottom:10px">Top 3 1-on-1 Coaching Priorities</div>'
        f'{coaching_items}</div></div>'
    )

ae_cards = "".join(build_rep_card(r, data[r]) for r in sorted(AES, key=lambda x: data.get(x,{}).get("avg_score",999)) if r in data)
csa_cards = "".join(build_rep_card(r, data[r], is_csa=True) for r in sorted(CSAS, key=lambda x: data.get(x,{}).get("avg_score",999)) if r in data)
other_reps = {r for r in data if r not in AES and r not in CSAS}
other_cards = "".join(build_rep_card(r, data[r]) for r in sorted(other_reps, key=lambda x: data.get(x,{}).get("avg_score",999)))
if not csa_cards:
    csa_cards = '<div style="color:#64748B;text-align:center;padding:40px;font-size:14px">No CSA scorecards graded yet.</div>'
other_tab = '<button class="tab" onclick="showPanel(\'other\',this)">Other Reps</button>' if other_cards else ""
other_panel = f'<div id="other" class="panel"><div class="grid">{other_cards}</div></div>' if other_cards else ""

css = """@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');*{margin:0;padding:0;box-sizing:border-box}body{background:#0A0F1A;font-family:'Inter','Segoe UI',system-ui,sans-serif;color:#E2E8F0;min-height:100vh;font-size:14px;line-height:1.5}.page-header{background:linear-gradient(135deg,#0D1117 0%,#131929 100%);border-bottom:1px solid #1E293B;padding:20px 30px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}.page-title{display:flex;align-items:center;gap:16px}.page-title h1{font-size:20px;color:#E2E8F0;text-transform:uppercase;letter-spacing:2px}.page-title .sub{font-size:11px;color:#64748B;letter-spacing:1px;margin-top:2px}.badge{background:rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.4);color:#818CF8;padding:4px 12px;border-radius:20px;font-size:11px;text-transform:uppercase;letter-spacing:1px}.wrap{padding:30px;max-width:1440px;margin:0 auto}.tab-bar{display:flex;gap:6px;margin-bottom:24px;border-bottom:1px solid #1E293B;padding-bottom:12px;overflow-x:auto}.tab{background:transparent;border:1px solid #1E293B;color:#64748B;padding:6px 16px;border-radius:20px;cursor:pointer;font-size:12px;font-weight:600;letter-spacing:.3px;white-space:nowrap;text-transform:uppercase;transition:all .2s}.tab:hover{color:#E2E8F0;border-color:#6366F1}.tab.active{background:rgba(99,102,241,.15);color:#818CF8;border-color:#6366F1}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}.panel{display:none}.panel.active{display:block}.rep-profile{display:flex;align-items:center;gap:10px;color:#E2E8F0;text-decoration:none;font-size:16px;font-weight:700}.rep-profile:hover span{color:#818CF8}.rep-avatar{width:38px;height:38px;border-radius:50%;object-fit:cover;border:2px solid #334155;background:#0D1117;flex-shrink:0}.rep-avatar.initials{display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0D1117,#131929);color:#818CF8;font-size:12px;letter-spacing:.8px}.activity-block{padding:13px 20px 15px;border-bottom:1px solid #1E293B;background:rgba(99,102,241,.05)}.activity-label{font-size:10px;font-weight:700;color:#64748B;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:9px}.activity-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.activity-metric{background:#0D1117;border:1px solid #1E293B;border-radius:8px;padding:9px 8px;min-width:0}.activity-metric div{font-size:18px;font-weight:800;color:#E2E8F0;line-height:1;white-space:nowrap}.activity-metric span{display:block;margin-top:5px;font-size:9px;font-weight:700;letter-spacing:.7px;text-transform:uppercase;color:#64748B;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.footer{font-size:11px;color:#64748B;margin:28px 0 0;text-align:center}@media(max-width:900px){.grid{grid-template-columns:1fr}.page-header{position:static}}@media(max-width:520px){.wrap{padding:20px 16px}.page-header{padding:16px}.activity-grid{grid-template-columns:repeat(2,1fr)}}"""

html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Rep Coaching Dashboard</title><style>{css}</style></head><body>
<header class="page-header">
  <div class="page-title">
    <img src="https://koontz-robin.github.io/robin-decks/revio-logo.png" style="height:36px;opacity:0.95" alt="rev.io">
    <div>
      <h1>Rep Coaching Dashboard</h1>
      <div class="sub">AI-synthesized coaching priorities from {total_calls} graded calls · {today_str}</div>
    </div>
  </div>
  <div class="badge">Leadership 1-on-1s</div>
</header>
<main class="wrap">
<div style="display:flex;gap:16px;margin-bottom:28px;flex-wrap:wrap">
  <div style="background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:18px 20px;flex:1;min-width:130px;position:relative;overflow:hidden"><div style="position:absolute;top:0;left:0;right:0;height:3px;background:#6366F1"></div><div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748B;margin-bottom:6px">Reps Tracked</div><div style="font-size:42px;font-weight:800;color:#818CF8;line-height:1">{len(data)}</div></div>
  <div style="background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:18px 20px;flex:1;min-width:130px;position:relative;overflow:hidden"><div style="position:absolute;top:0;left:0;right:0;height:3px;background:#818CF8"></div><div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748B;margin-bottom:6px">Calls Graded</div><div style="font-size:42px;font-weight:800;color:#818CF8;line-height:1">{total_calls}</div></div>
  <div style="background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:18px 20px;flex:1;min-width:130px;position:relative;overflow:hidden"><div style="position:absolute;top:0;left:0;right:0;height:3px;background:#F59E0B"></div><div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748B;margin-bottom:6px">Team Avg Score</div><div style="font-size:42px;font-weight:800;color:#F59E0B;line-height:1">{team_avg:.0f}</div></div>
</div>
<div class="tab-bar">
  <button class="tab active" onclick="showPanel('ae',this)">Account Executives</button>
  <button class="tab" onclick="showPanel('csa',this)">Client Solutions Advisors</button>
  {other_tab}
</div>
<div id="ae" class="panel active"><div class="grid">{ae_cards}</div></div>
<div id="csa" class="panel"><div class="grid">{csa_cards}</div></div>
{other_panel}
<div class="footer">Rev.io Sales · Rep Coaching Dashboard · {today_str}</div>
</main>
<script>
function showPanel(id,btn){{
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
</script>
</body></html>"""

with open(f"{REPO}/rep-coaching-dashboard.html","w") as f:
    f.write(html)

print(f"Wrote {REPO}/rep-coaching-dashboard.html ({len(html):,} chars)")
