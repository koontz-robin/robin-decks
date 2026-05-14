#!/usr/bin/env python3
"""Rebuild the Rep Coaching Dashboard from Notion scorecards."""
import json, subprocess, os
from datetime import datetime

REPO = "/tmp/robin-decks"
SSH_KEY = "/home/openclaw/.openclaw/ssh/id_ed25519"

with open("/tmp/coaching_summaries.json") as f:
    data = json.load(f)

data.pop("Joseph Abarno", None)

AES = {"Andrew Whisenant","Connor Flynn","Husam Zalmiyar","Jake Borah","Jamie Butler","Jaylin Bender","Patrick Davies"}
CSAS = {"Ingrid Beard","Justin Lee"}

today_str = datetime.now().strftime("%B %d, %Y")
total_calls = sum(d['call_count'] for d in data.values())
team_avg = sum(d['avg_score'] for d in data.values()) / len(data) if data else 0
coaching_req = sum(1 for d in data.values() if d['avg_score'] < 50)

def score_color(s):
    if s >= 80: return "#34d399"
    if s >= 65: return "#38bdf8"
    if s >= 50: return "#fbbf24"
    return "#f87171"

def grade_label(s):
    if s >= 90: return "🟢 Elite"
    if s >= 80: return "🔵 Strong"
    if s >= 65: return "🟡 Solid"
    if s >= 50: return "🟠 Needs Work"
    return "🔴 Coaching Required"

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
                f'<div style="background:#0f172a;border-left:3px solid {sc};'
                f'border-radius:4px;padding:10px 12px;margin-bottom:8px">'
                f'<div style="font-size:12px;color:#c8f0dc;line-height:1.5">{clean}</div></div>'
            )

    recent_html = ""
    for c in calls[:4]:
        cs = score_color(c["score"])
        recent_html += (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:5px 0;border-bottom:1px solid #1e293b">'
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
            ("Qualifying","qualifying",40),("Summarize","summarize",20),("Next Steps","next_steps",15)
        ]
    for label, key, max_pts in cat_map:
        val = cats.get(key, 0)
        pct = min(100, val/max_pts*100) if max_pts else 0
        bar_color = "#f87171" if pct < 50 else "#fbbf24" if pct < 70 else "#34d399"
        bars += (
            f'<div style="margin-bottom:6px">'
            f'<div style="display:flex;justify-content:space-between;margin-bottom:2px">'
            f'<span style="font-size:11px;color:#64748b">{label}</span>'
            f'<span style="font-size:11px;color:#94a3b8">{val:.0f}/{max_pts}</span></div>'
            f'<div style="background:#0f172a;border-radius:3px;height:5px">'
            f'<div style="width:{pct:.0f}%;height:100%;background:{bar_color};border-radius:3px"></div>'
            f'</div></div>'
        )

    return (
        f'<div style="background:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #0f172a">'
        f'<div style="background:#0f172a;padding:16px 20px;display:flex;justify-content:space-between;'
        f'align-items:center;border-bottom:2px solid {sc}">'
        f'<div><div style="font-size:16px;font-weight:700;color:#e2e8f0">{rep}</div>'
        f'<div style="font-size:11px;color:#64748b;margin-top:2px">{n} graded {"CBRs" if is_csa else "calls"} · {grade_label(avg)}</div></div>'
        f'<div style="text-align:right"><div style="font-size:36px;font-weight:800;color:{sc};line-height:1">{avg:.0f}</div>'
        f'<div style="font-size:10px;color:#64748b">avg score</div></div></div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0">'
        f'<div style="padding:16px 18px;border-right:1px solid #0f172a">'
        f'<div style="font-size:10px;font-weight:700;color:#64748b;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin-bottom:10px">Category Averages</div>{bars}</div>'
        f'<div style="padding:16px 18px">'
        f'<div style="font-size:10px;font-weight:700;color:#64748b;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin-bottom:10px">Recent Calls</div>{recent_html}</div></div>'
        f'<div style="padding:16px 20px;border-top:1px solid #0f172a">'
        f'<div style="font-size:10px;font-weight:700;color:#64748b;letter-spacing:1.5px;'
        f'text-transform:uppercase;margin-bottom:10px">🎯 Top 3 1-on-1 Coaching Priorities</div>'
        f'{coaching_items}</div></div>'
    )

ae_cards = "".join(build_rep_card(r, data[r]) for r in sorted(AES, key=lambda x: data.get(x,{}).get("avg_score",999)) if r in data)
csa_cards = "".join(build_rep_card(r, data[r], is_csa=True) for r in sorted(CSAS, key=lambda x: data.get(x,{}).get("avg_score",999)) if r in data)
if not csa_cards:
    csa_cards = '<div style="color:#64748b;text-align:center;padding:40px;font-size:14px">No CSA scorecards graded yet.</div>'

css = """*{margin:0;padding:0;box-sizing:border-box}body{background:#000;font-family:'Segoe UI',system-ui,sans-serif;color:#e2e8f0;min-height:100vh;padding:36px 48px}h1{font-size:26px;font-weight:700;color:#fff;margin-bottom:4px}.sub{font-size:13px;color:#475569;margin-bottom:24px}.tab-bar{display:flex;gap:8px;margin-bottom:24px;border-bottom:1px solid #1e293b;padding-bottom:0}.tab{background:transparent;border:1px solid #1e293b;border-bottom:none;color:#64748b;padding:10px 28px;border-radius:8px 8px 0 0;cursor:pointer;font-size:13px;font-weight:700;letter-spacing:0.5px;transition:all .2s;margin-bottom:-1px}.tab:hover{color:#e2e8f0;border-color:#38bdf8}.tab.active{background:#1e293b;color:#38bdf8;border-color:#38bdf8;border-bottom:2px solid #1e293b}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}.panel{display:none}.panel.active{display:block}@media(max-width:900px){.grid{grid-template-columns:1fr}}.footer{font-size:11px;color:#334155;margin-top:28px;text-align:center}"""

html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Rep Coaching Dashboard</title><style>{css}</style></head><body>
<div style="position:relative">
  <img src="https://raw.githubusercontent.com/koontz-robin/robin-decks/master/revio-logo.png" style="position:absolute;top:0;right:0;height:44px;opacity:0.95" alt="rev.io">
  <h1>Rep Coaching Dashboard</h1>
  <p class="sub">AI-synthesized coaching priorities from {total_calls} graded calls · {today_str} · For leadership 1-on-1 use</p>
</div>
<div style="display:flex;gap:16px;margin-bottom:28px;flex-wrap:wrap">
  <div style="background:#1e293b;border-radius:10px;padding:18px 20px;flex:1;min-width:130px;position:relative;overflow:hidden"><div style="position:absolute;top:0;left:0;right:0;height:3px;background:#38bdf8"></div><div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:6px">Reps Tracked</div><div style="font-size:42px;font-weight:800;color:#38bdf8;line-height:1">{len(data)}</div></div>
  <div style="background:#1e293b;border-radius:10px;padding:18px 20px;flex:1;min-width:130px;position:relative;overflow:hidden"><div style="position:absolute;top:0;left:0;right:0;height:3px;background:#34d399"></div><div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:6px">Calls Graded</div><div style="font-size:42px;font-weight:800;color:#34d399;line-height:1">{total_calls}</div></div>
  <div style="background:#1e293b;border-radius:10px;padding:18px 20px;flex:1;min-width:130px;position:relative;overflow:hidden"><div style="position:absolute;top:0;left:0;right:0;height:3px;background:#fbbf24"></div><div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:6px">Team Avg Score</div><div style="font-size:42px;font-weight:800;color:#fbbf24;line-height:1">{team_avg:.0f}</div></div>
  <div style="background:#1e293b;border-radius:10px;padding:18px 20px;flex:1;min-width:130px;position:relative;overflow:hidden"><div style="position:absolute;top:0;left:0;right:0;height:3px;background:#f87171"></div><div style="font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:6px">Coaching Required</div><div style="font-size:42px;font-weight:800;color:#f87171;line-height:1">{coaching_req}</div><div style="font-size:11px;color:#475569;margin-top:4px">avg &lt;50</div></div>
</div>
<div class="tab-bar">
  <button class="tab active" onclick="showPanel('ae',this)">Account Executives</button>
  <button class="tab" onclick="showPanel('csa',this)">Client Solutions Advisors</button>
</div>
<div id="ae" class="panel active"><div class="grid">{ae_cards}</div></div>
<div id="csa" class="panel"><div class="grid">{csa_cards}</div></div>
<div class="footer">Rev.io Sales · Rep Coaching Dashboard · {today_str}</div>
<script>
function showPanel(id,btn){{
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
</script>
</body></html>"""

os.makedirs(REPO, exist_ok=True)
with open(f"{REPO}/rep-coaching-dashboard.html","w") as f:
    f.write(html)

env = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no"}
subprocess.run(["git","config","user.email","robin@rev.io"], cwd=REPO)
subprocess.run(["git","config","user.name","Robin"], cwd=REPO)
subprocess.run(["git","add","rep-coaching-dashboard.html"], cwd=REPO)
diff = subprocess.run(["git","diff","--cached","--quiet"], cwd=REPO)
if diff.returncode != 0:
    subprocess.run(["git","commit","-m",f"Rep coaching dashboard refresh {today_str}"], cwd=REPO)
    subprocess.run(["git","push","origin","master"], cwd=REPO, env=env)
    print(f"Pushed: {len(html):,} chars")
else:
    print("No changes.")
