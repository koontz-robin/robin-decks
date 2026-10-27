#!/usr/bin/env python3
"""Build, publish, and optionally email the weekly Stage 3+ pipeline war room."""
from __future__ import annotations
import argparse, html, json, os, re, shutil, subprocess, sys, tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "weekly_pipeline_war_room_state.json"
OUTPUT = ROOT / "weekly-pipeline-war-room.html"
SOURCE = ROOT / "weekly_pipeline_war_room_data.json"
FORECAST_SCRIPT = ROOT / "refresh_forecast.py"
EMAIL_TOKENS = ROOT / "email-tokens.json"
URL = "https://koontz-robin.github.io/robin-decks/weekly-pipeline-war-room.html"
ET = ZoneInfo("America/New_York")
STAGES = ["3 - Initial Product Demo", "4 - Proposal Sent", "5 - Product / Contract Validated", "6 - Verbal Commit"]
STAGE_RANK = {stage: i + 3 for i, stage in enumerate(STAGES)}


def esc(value): return html.escape(str(value or "—"))
def money(value): return f"${float(value or 0):,.0f}"
def clean_record(r):
    out = {k: v for k, v in r.items() if k != "attributes"}
    for key in ("Account", "Owner"):
        if isinstance(out.get(key), dict): out[key] = out[key].get("Name", "")
    return out


def sf_credentials():
    text = FORECAST_SCRIPT.read_text()
    vals = {}
    for key in ("SF_INSTANCE", "SF_CLIENT_ID", "SF_CLIENT_SECRET"):
        m = re.search(rf'^{key}\s*=\s*["\']([^"\']+)', text, re.M)
        if not m: raise RuntimeError(f"Could not load {key} from refresh_forecast.py")
        vals[key] = m.group(1)
    return vals


def sf_session():
    c = sf_credentials()
    r = requests.post(f"{c['SF_INSTANCE']}/services/oauth2/token", data={
        "grant_type": "client_credentials", "client_id": c["SF_CLIENT_ID"], "client_secret": c["SF_CLIENT_SECRET"]
    }, timeout=30)
    r.raise_for_status(); token = r.json()
    return token["instance_url"], {"Authorization": f"Bearer {token['access_token']}"}


def query_all(base, headers, soql):
    records, url, params = [], f"{base}/services/data/v59.0/query", {"q": soql}
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=60); r.raise_for_status(); data = r.json()
        records.extend(clean_record(x) for x in data.get("records", []))
        if data.get("done", True): return records
        url, params = base + data["nextRecordsUrl"], {}


def fetch_current(base, headers):
    stages = ",".join("'" + s.replace("'", "\\'") + "'" for s in STAGES)
    return query_all(base, headers, f"""
SELECT Id, Name, Amount, StageName, CloseDate, CreatedDate, LastModifiedDate,
       Product_Type__c, Forecast_Status__c, NextStep, Account.Name, Owner.Name,
       Loss_Reason__c, Reason_Lost_Detail__c,
       Business_Issue__c, Business_Issue_Details__c, Business_Issues__c,
       Problems__c, Solutions__c, Values__c, Risk_Mitigation_Plan__c
FROM Opportunity
WHERE IsClosed = false AND StageName IN ({stages})
ORDER BY Product_Type__c, Amount DESC NULLS LAST
""".strip())


def fetch_prior_ids(base, headers, ids):
    if not ids: return {}
    found = []
    for start in range(0, len(ids), 150):
        batch = ids[start:start+150]
        id_list = ",".join(f"'{x}'" for x in batch)
        found.extend(query_all(base, headers, f"""
SELECT Id, Name, Amount, StageName, IsClosed, IsWon, CloseDate, LastModifiedDate,
       Product_Type__c, Forecast_Status__c, NextStep, Account.Name, Owner.Name,
       Loss_Reason__c, Reason_Lost_Detail__c
FROM Opportunity WHERE Id IN ({id_list})
""".strip()))
    return {x["Id"]: x for x in found}


def product_name(raw):
    """Apply dashboard display labels while preserving source values in snapshot data."""
    value = (raw or "Unspecified").strip()
    display_labels = {"PSA 2.0": "New Rev.io", "Billing": "Classic Rev.io"}
    return display_labels.get(value, value)


def removal_reason(current):
    if not current: return "Deleted or no longer accessible"
    stage = current.get("StageName") or "Unknown"
    if current.get("IsWon") or stage == "Closed Won": return "Closed Won"
    if current.get("IsClosed") or stage == "Closed Lost": return "Closed Lost"
    if stage not in STAGE_RANK: return f"Moved below Stage 3 ({stage})"
    return f"No longer in open Stage 3+ ({stage})"


def load_state():
    try: return json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError): return None


def row(opp, change=""):
    account = opp.get("Account") or "No account"
    name = opp.get("Name") or "Unnamed opportunity"
    detail_id = f"vp-{re.sub(r'[^a-zA-Z0-9_-]', '', opp.get('Id') or name)}"
    badge = f'<span class="change {change.lower()}">{esc(change)}</span>' if change else ""
    value_planner = [
        ("Business issue", opp.get("Business_Issue__c") or opp.get("Business_Issues__c")),
        ("Business issue detail", opp.get("Business_Issue_Details__c")),
        ("Problems", opp.get("Problems__c")),
        ("Solutions", opp.get("Solutions__c")),
        ("Value", opp.get("Values__c")),
        ("Risk / mitigation", opp.get("Risk_Mitigation_Plan__c")),
    ]
    planner_html = "".join(
        f'<div class="planner-field"><span>{esc(label)}</span><p>{esc(value or "Not entered")}</p></div>'
        for label, value in value_planner
    )
    return f"""<tr class="opp-row" data-target="{detail_id}" tabindex="0" role="button" aria-expanded="false"><td><strong>{esc(account)}</strong><small>{esc(name)}</small>{badge}<span class="expand-hint">Value planner <b>⌄</b></span></td>
<td>{esc(opp.get('Owner'))}</td><td><span class="stage s{STAGE_RANK.get(opp.get('StageName'),0)}">{esc(opp.get('StageName'))}</span></td>
<td class="num">{money(opp.get('Amount'))}</td><td>{esc(opp.get('CloseDate'))}</td><td>{esc(opp.get('Forecast_Status__c') or 'Not tagged')}</td><td>{esc(opp.get('NextStep') or '—')}</td></tr>
<tr class="planner-row" id="{detail_id}" hidden><td colspan="7"><div class="planner-grid">{planner_html}</div></td></tr>"""


def change_row(item, kind):
    o = item["current"] if kind == "Added" else item["previous"]
    cur = item.get("current") or {}
    reason = "Entered the open Stage 3+ war room" if kind == "Added" else item["removal_reason"]
    loss = cur.get("Loss_Reason__c") or ("Not closed lost" if kind == "Removed" else "—")
    detail = cur.get("Reason_Lost_Detail__c") or ("No reason-loss detail in Salesforce" if cur.get("StageName") == "Closed Lost" else "—")
    return f"""<tr><td><span class="change {kind.lower()}">{kind}</span><strong>{esc(o.get('Account') or 'No account')}</strong><small>{esc(o.get('Name'))}</small></td>
<td>{esc(product_name(o.get('Product_Type__c')))}</td><td>{esc(o.get('Owner'))}</td><td>{money(o.get('Amount'))}</td><td>{esc(reason)}</td><td><strong>{esc(loss)}</strong><small>{esc(detail)}</small></td></tr>"""


def render(payload):
    current, added, removed = payload["current"], payload["added"], payload["removed"]
    current_total = sum(float(x.get("Amount") or 0) for x in current)
    previous_total = float(payload.get("previous_total") or 0)
    if payload["baseline"]:
        wow_value = "—"
        wow_note = "Baseline week"
        wow_class = "flat"
    elif previous_total:
        wow_pct = ((current_total - previous_total) / previous_total) * 100
        wow_value = f"{wow_pct:+.1f}%"
        wow_note = f"vs. {money(previous_total)} last week"
        wow_class = "up" if wow_pct > 0 else "down" if wow_pct < 0 else "flat"
    else:
        wow_value = "+100.0%" if current_total else "0.0%"
        wow_note = "vs. $0 last week"
        wow_class = "up" if current_total else "flat"
    groups = defaultdict(list)
    for o in current: groups[product_name(o.get("Product_Type__c"))].append(o)
    sections = []
    for p, opps in sorted(groups.items(), key=lambda x: -sum(float(o.get("Amount") or 0) for o in x[1])):
        total = sum(float(o.get("Amount") or 0) for o in opps)
        rows = "".join(row(o) for o in sorted(opps, key=lambda x: -float(x.get("Amount") or 0)))
        sections.append(f'<section><div class="section-head"><div><h2>{esc(p)}</h2><p>{len(opps)} open opportunities · {money(total)} MRR</p></div></div><div class="table"><table><thead><tr><th>Account / Opportunity</th><th>Owner</th><th>Stage</th><th>MRR</th><th>Close</th><th>Forecast</th><th>Next step</th></tr></thead><tbody>{rows}</tbody></table></div></section>')
    if payload["baseline"]:
        changes = '<div class="empty">Baseline captured this week. Week-over-week additions and removals will begin with the next Monday run.</div>'
    else:
        cr = "".join(change_row(x, "Added") for x in added) + "".join(change_row(x, "Removed") for x in removed)
        changes = f'<div class="table"><table><thead><tr><th>Change / Opportunity</th><th>Product</th><th>Owner</th><th>MRR</th><th>Why it changed</th><th>Loss reason / detail</th></tr></thead><tbody>{cr or "<tr><td colspan=6>No changes from last week.</td></tr>"}</tbody></table></div>'
    generated = datetime.fromisoformat(payload["generated_at"]).astimezone(ET).strftime("%B %-d, %Y at %-I:%M %p ET")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Weekly Pipeline War Room</title><style>
:root{{--navy:#07152d;--panel:#102443;--line:#284161;--text:#edf5ff;--muted:#9cb0c9;--blue:#46a5ff;--green:#35d39a;--red:#ff6f7d;--gold:#ffc857}}*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(150deg,#061226,#0a1d38);color:var(--text);font:14px Inter,Segoe UI,sans-serif}}main{{max-width:1500px;margin:auto;padding:38px}}header{{display:flex;justify-content:space-between;gap:30px;align-items:end;margin-bottom:26px}}.eyebrow{{color:var(--blue);font-weight:800;text-transform:uppercase;letter-spacing:.15em;font-size:12px}}h1{{font-size:38px;margin:7px 0}}p{{color:var(--muted);margin:4px 0}}.war-room-total{{display:flex;align-items:end;gap:42px;padding:8px 0 28px;border-bottom:1px solid var(--line);margin-bottom:22px}}.total-label{{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.1em;font-weight:800}}.total-value{{display:block;font-size:52px;line-height:1;font-weight:850;margin-top:8px}}.wow-value{{display:block;font-size:28px;font-weight:850}}.wow-value.up{{color:var(--green)}}.wow-value.down{{color:var(--red)}}.wow-value.flat{{color:var(--muted)}}.wow-note{{display:block;color:var(--muted);margin-top:5px}}section{{background:rgba(16,36,67,.92);border:1px solid var(--line);border-radius:14px;margin:18px 0;overflow:hidden}}.section-head{{padding:20px 22px;border-bottom:1px solid var(--line)}}h2{{margin:0;font-size:21px}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:950px}}th,td{{padding:13px 16px;text-align:left;border-bottom:1px solid rgba(40,65,97,.65);vertical-align:top}}th{{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:.07em}}td small{{display:block;color:var(--muted);margin-top:5px;max-width:440px;white-space:normal}}.num{{font-weight:800}}.stage,.change{{display:inline-block;border-radius:999px;padding:4px 8px;font-size:11px;font-weight:800;white-space:nowrap}}.stage{{background:#183557;color:#baddff}}.change{{margin:0 8px 6px 0;text-transform:uppercase}}.added{{background:#123f35;color:var(--green)}}.removed{{background:#502630;color:#ffb7bf}}.empty{{padding:24px;color:var(--muted)}}.opp-row{{cursor:pointer}}.opp-row:hover,.opp-row:focus{{background:rgba(70,165,255,.08);outline:none}}.expand-hint{{display:block;color:var(--blue);font-size:11px;margin-top:8px;font-weight:800;text-transform:uppercase;letter-spacing:.05em}}.opp-row[aria-expanded="true"] .expand-hint b{{display:inline-block;transform:rotate(180deg)}}.planner-row td{{padding:0;background:#091a32}}.planner-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border-bottom:1px solid var(--line)}}.planner-field{{background:#0b203d;padding:18px 20px;min-height:105px}}.planner-field span{{display:block;color:var(--blue);font-size:11px;text-transform:uppercase;letter-spacing:.08em;font-weight:800;margin-bottom:8px}}.planner-field p{{color:var(--text);white-space:pre-wrap;line-height:1.5}}footer{{color:var(--muted);padding:20px 2px 40px}}@media(max-width:900px){{.planner-grid{{grid-template-columns:1fr}}}}@media(max-width:700px){{main{{padding:20px}}header{{display:block}}h1{{font-size:29px}}.war-room-total{{display:block}}.war-room-total>div+div{{margin-top:20px}}.total-value{{font-size:42px}}}}
</style></head><body><main><header><div><div class="eyebrow">Rev.io · Weekly Sales Inspection</div><h1>Pipeline War Room</h1><p>Every open opportunity at Stage 3 or later, grouped by product.</p></div><p>Updated {esc(generated)}</p></header>
<div class="war-room-total"><div><span class="total-label">Total war room value</span><strong class="total-value">{money(current_total)}</strong></div><div><span class="total-label">Week-over-week change</span><strong class="wow-value {wow_class}">{wow_value}</strong><span class="wow-note">{esc(wow_note)}</span></div></div>
<section><div class="section-head"><h2>Week-over-week war-room changes</h2><p>Additions entered Stage 3+; removals closed, regressed below Stage 3, or left the active set. Closed-lost records show Salesforce loss reason and detail.</p></div>{changes}</section>{''.join(sections)}<footer>Source: Salesforce Opportunity. Stage 3+ = Initial Product Demo, Proposal Sent, Product / Contract Validated, and Verbal Commit. Amount is shown as MRR.</footer></main><script>
document.querySelectorAll('.opp-row').forEach(row=>{{
  const toggle=()=>{{const detail=document.getElementById(row.dataset.target);const open=row.getAttribute('aria-expanded')==='true';row.setAttribute('aria-expanded',String(!open));detail.hidden=open;}};
  row.addEventListener('click',toggle);
  row.addEventListener('keydown',e=>{{if(e.key==='Enter'||e.key===' '){{e.preventDefault();toggle();}}}});
}});
</script></body></html>"""


def publish():
    tmp = Path(tempfile.mkdtemp(prefix="war-room-publish.")); wt = tmp / "worktree"
    try:
        for cmd in (["git","fetch","robin-decks","master"],["git","worktree","add",str(wt),"robin-decks/master"]):
            subprocess.run(cmd,cwd=ROOT,check=True,capture_output=True,text=True)
        publish_files = (OUTPUT, SOURCE, Path(__file__).resolve(), ROOT / "DECKS-LIBRARY.md")
        for f in publish_files: shutil.copy2(f, wt / f.name)
        subprocess.run(["git","add",*(f.name for f in publish_files)],cwd=wt,check=True)
        if subprocess.run(["git","diff","--cached","--quiet"],cwd=wt).returncode:
            subprocess.run(["git","config","user.name","Robin"],cwd=wt,check=True)
            subprocess.run(["git","config","user.email","robin.bot@rev.io"],cwd=wt,check=True)
            subprocess.run(["git","commit","-m",f"Weekly pipeline war room — {datetime.now(ET):%Y-%m-%d}"],cwd=wt,check=True,capture_output=True,text=True)
            subprocess.run(["git","push","robin-decks","HEAD:master"],cwd=wt,check=True,capture_output=True,text=True)
    finally:
        subprocess.run(["git","worktree","remove","--force",str(wt)],cwd=ROOT,capture_output=True); shutil.rmtree(tmp,ignore_errors=True)


def graph_token():
    t = json.loads(EMAIL_TOKENS.read_text())
    if t.get("refresh_token"):
        r = requests.post("https://login.microsoftonline.com/ad233ca3-255e-4697-90c0-5bf96200d3ae/oauth2/v2.0/token",data={"client_id":"0bda3b19-e713-4103-be0d-2bf057af5cba","grant_type":"refresh_token","refresh_token":t["refresh_token"],"scope":"Mail.Send Mail.ReadWrite offline_access"},timeout=30)
        r.raise_for_status(); t.update(r.json()); EMAIL_TOKENS.write_text(json.dumps(t,indent=2))
    return t["access_token"]


def send_email(payload):
    total = sum(float(x.get("Amount") or 0) for x in payload["current"])
    date = datetime.now(ET).strftime("%B %-d, %Y")
    baseline_note = "This is the initial baseline; weekly changes begin next Monday." if payload["baseline"] else f"{len(payload['added'])} added and {len(payload['removed'])} removed since last week."
    body = f'''<div style="font-family:Segoe UI,sans-serif;color:#1e293b;font-size:14px;line-height:1.55"><p>Brent —</p><p>Here is this week's Stage 3+ pipeline war room, broken down by product.</p><p><b>{len(payload['current'])} open opportunities · {money(total)} MRR</b><br>{esc(baseline_note)}</p><p><a href="{URL}" style="display:inline-block;background:#163a66;color:white;padding:11px 18px;border-radius:6px;text-decoration:none;font-weight:700">View Weekly Pipeline War Room →</a></p><p style="color:#64748b">The change section calls out every addition and removal. Closed-lost removals include Salesforce loss reason and reason-loss detail.</p><p>— Robin 🦸🏻‍♂️</p></div>'''
    msg={"message":{"subject":f"Weekly Pipeline War Room — {date}","body":{"contentType":"HTML","content":body},"toRecipients":[{"emailAddress":{"address":"brentm@rev.io"}}],"ccRecipients":[{"emailAddress":{"address":"ryank@rev.io"}}]}}
    r=requests.post("https://graph.microsoft.com/v1.0/me/sendMail",headers={"Authorization":f"Bearer {graph_token()}","Content-Type":"application/json"},json=msg,timeout=30)
    if r.status_code != 202: raise RuntimeError(f"Email failed: {r.status_code} {r.text[:300]}")


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--no-publish",action="store_true"); ap.add_argument("--no-send",action="store_true"); ap.add_argument("--baseline",action="store_true",help="Capture current pipeline without treating it as added")
    args=ap.parse_args(); now=datetime.now(ET); previous=load_state(); base,headers=sf_session(); current=fetch_current(base,headers)
    prev_records=(previous or {}).get("current",[]); prev_map={x["Id"]:x for x in prev_records}; cur_map={x["Id"]:x for x in current}
    baseline=args.baseline or previous is None
    added=[] if baseline else [{"current":cur_map[i]} for i in sorted(cur_map.keys()-prev_map.keys())]
    removed_ids=[] if baseline else sorted(prev_map.keys()-cur_map.keys()); removed_current=fetch_prior_ids(base,headers,removed_ids)
    removed=[{"previous":prev_map[i],"current":removed_current.get(i),"removal_reason":removal_reason(removed_current.get(i))} for i in removed_ids]
    previous_total=sum(float(x.get("Amount") or 0) for x in prev_records)
    payload={"generated_at":now.isoformat(),"baseline":baseline,"current":current,"added":added,"removed":removed,"previous_total":previous_total,"previous_generated_at":(previous or {}).get("generated_at")}
    OUTPUT.write_text(render(payload)); SOURCE.write_text(json.dumps(payload,indent=2))
    if not args.no_publish: publish()
    if not args.no_send: send_email(payload)
    # Advance the comparison snapshot only after all requested side effects succeed.
    STATE.write_text(json.dumps({"generated_at":payload["generated_at"],"current":current},indent=2))
    print(f"Built {OUTPUT.name}: {len(current)} open, {len(added)} added, {len(removed)} removed; baseline={baseline}; published={not args.no_publish}; emailed={not args.no_send}")

if __name__ == "__main__": main()
