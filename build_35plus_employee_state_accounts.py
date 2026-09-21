#!/usr/bin/env python3
from __future__ import annotations
import html, json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo
from build_jamie_psa_no_activity_dashboard import sf_auth, sf_query_all

ROOT=Path('/home/openclaw/.openclaw/workspace')
OUT=ROOT/'35plus-employee-state-accounts.html'
DATA=ROOT/'35plus_employee_state_accounts.json'
STATES=['RI','MA','CT','NJ','NY','FL','DE','GA','AL','MS','DC','SC','NC','TN','MD','VA','WV','KY','PA','OH','IN','NH','VT','MI','ME']
SF='https://rev-io.lightning.force.com/lightning/r/Account'

def c(v): return str(v or '').strip()
def e(v): return html.escape(c(v),quote=True)
def fetch():
    base,headers=sf_auth(); quoted=','.join(f"'{x}'" for x in STATES)
    q=f"""SELECT Id,Name,Type,BillingCity,BillingStateCode,NumberOfEmployees,Owner.Name,
    Account_Tiers__c,Industry,PSA_Platform__c,Billing_Platform__c,Website,Phone,LastActivityDate,CreatedDate
    FROM Account WHERE NumberOfEmployees >= 35 AND BillingStateCode IN ({quoted})
    ORDER BY BillingStateCode,NumberOfEmployees DESC,Name"""
    rows=[]
    for r in sf_query_all(base,headers,q):
        owner=r.get('Owner') or {}
        rows.append({'id':c(r.get('Id')),'account':c(r.get('Name')),'type':c(r.get('Type')),'city':c(r.get('BillingCity')),
        'state':c(r.get('BillingStateCode')),'employees':int(r.get('NumberOfEmployees') or 0),'owner':c(owner.get('Name')),
        'tier':c(r.get('Account_Tiers__c')),'industry':c(r.get('Industry')),'psa':c(r.get('PSA_Platform__c')),
        'billing':c(r.get('Billing_Platform__c')),'website':c(r.get('Website')),'phone':c(r.get('Phone')),
        'last_activity':c(r.get('LastActivityDate')),'created':c(r.get('CreatedDate'))[:10],
        'sf_url':f"{SF}/{c(r.get('Id'))}/view"})
    return rows

def options(values): return ''.join(f'<option value="{e(x)}">{e(x)}</option>' for x in values)
def chips(counter,limit=12): return ''.join(f'<span class="chip"><b>{e(k)}</b> {v:,}</span>' for k,v in counter.most_common(limit))
def table_rows(rows):
    out=[]
    for r in rows:
        website=r['website']; href=website if website.startswith(('http://','https://')) else ('https://'+website if website else '')
        web=f'<a href="{e(href)}" target="_blank" rel="noopener">{e(website)}</a>' if website else '<span class="muted">—</span>'
        search=' '.join(c(r[k]) for k in ['account','city','state','owner','tier','industry','psa','billing','website','phone','last_activity']).lower()
        out.append(f'''<tr data-state="{e(r['state'])}" data-owner="{e(r['owner'])}" data-search="{e(search)}">
<td><a class="acct" href="{e(r['sf_url'])}" target="_blank" rel="noopener">{e(r['account'])}</a><small>{e(r['type']) or 'No account type'}</small></td>
<td class="n">{r['employees']:,}</td><td>{e(r['city']) or '—'}, {e(r['state'])}</td><td>{e(r['owner']) or '—'}</td>
<td>{e(r['tier']) or '—'}</td><td>{e(r['industry']) or '—'}</td><td>{e(r['psa']) or '—'}</td><td>{e(r['billing']) or '—'}</td>
<td>{e(r['last_activity']) or '<span class="muted">Never</span>'}</td><td>{web}</td><td>{e(r['phone']) or '—'}</td></tr>''')
    return '\n'.join(out)

def build(rows):
    sc=Counter(r['state'] for r in rows); oc=Counter(r['owner'] or 'No owner' for r in rows); ic=Counter(r['industry'] or 'No industry' for r in rows)
    vals=[r['employees'] for r in rows]; generated=datetime.now(ZoneInfo('America/New_York')).strftime('%b %-d, %Y %-I:%M %p ET')
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>35+ Employee Accounts | Target States</title>
<style>:root{{--bg:#07111d;--panel:#0e1d2d;--line:#263b52;--text:#eef7ff;--muted:#91a5b8;--blue:#55b9ff;--green:#61dda5}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#163c64,#07111d 38%);color:var(--text);font-family:Inter,system-ui,sans-serif}}a{{color:var(--blue);text-decoration:none}}.wrap{{max-width:1800px;margin:auto;padding:30px}}header{{display:flex;justify-content:space-between;gap:20px}}h1{{margin:0;font-size:36px}}.lede,.stamp,.muted,small{{color:var(--muted)}}.lede{{max-width:1000px;line-height:1.5}}.stamp{{text-align:right;font-size:13px}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:22px 0}}.metric,.card{{background:rgba(14,29,45,.94);border:1px solid var(--line);border-radius:16px;padding:17px}}.label{{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}}.value{{font-size:32px;font-weight:850;margin-top:5px}}.cards{{display:grid;grid-template-columns:2fr 1.3fr 1.3fr;gap:14px}}.card h2{{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:0 0 12px}}.chips{{display:flex;flex-wrap:wrap;gap:8px}}.chip{{background:#091725;border:1px solid #284662;border-radius:999px;padding:7px 10px;font-size:12px}}.chip b{{color:var(--green)}}.controls{{display:grid;grid-template-columns:1fr 220px 260px 130px;gap:10px;margin:18px 0}}input,select,button{{background:#0a1724;color:var(--text);border:1px solid var(--line);border-radius:11px;padding:11px;font-size:14px}}button{{cursor:pointer}}.table{{overflow:auto;border:1px solid var(--line);border-radius:16px;background:#091521}}table{{width:100%;min-width:1550px;border-collapse:collapse}}th{{position:sticky;top:0;background:#11263a;color:#b9c9d7;text-align:left;padding:12px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;cursor:pointer}}td{{padding:12px;border-top:1px solid rgba(38,59,82,.7);font-size:13px;vertical-align:top}}tr:hover{{background:rgba(85,185,255,.08)}}.acct{{font-weight:800}}small{{display:block;margin-top:3px}}.n{{font-weight:850;font-variant-numeric:tabular-nums}}.hidden{{display:none}}#count{{color:var(--green);font-weight:800}}@media(max-width:1000px){{header{{display:block}}.stamp{{text-align:left}}.metrics,.cards,.controls{{grid-template-columns:1fr}}}}</style></head>
<body><main class="wrap"><header><div><h1>Accounts with 35+ Employees</h1><p class="lede">All Salesforce accounts with <b>35 or more employees</b> in RI, MA, CT, NJ, NY, FL, DE, GA, AL, MS, DC, SC, NC, TN, MD, VA, WV, KY, PA, OH, IN, NH, VT, MI, and ME. No owner or activity exclusions applied.</p></div><div class="stamp">Generated {e(generated)}<br>Source: Salesforce Account object</div></header>
<section class="metrics"><div class="metric"><div class="label">Matched accounts</div><div class="value">{len(rows):,}</div></div><div class="metric"><div class="label">States represented</div><div class="value">{len(sc):,}</div></div><div class="metric"><div class="label">Total employees</div><div class="value">{sum(vals):,}</div></div><div class="metric"><div class="label">Median employees</div><div class="value">{int(median(vals)) if vals else 0:,}</div></div><div class="metric"><div class="label">Largest account</div><div class="value">{max(vals) if vals else 0:,}</div></div></section>
<section class="cards"><div class="card"><h2>Accounts by state</h2><div class="chips">{chips(sc,30)}</div></div><div class="card"><h2>Top owners</h2><div class="chips">{chips(oc)}</div></div><div class="card"><h2>Top industries</h2><div class="chips">{chips(ic)}</div></div></section>
<section class="controls"><input id="q" type="search" placeholder="Search account, city, owner, industry, platform…"><select id="state"><option value="">All states</option>{options(sorted(sc))}</select><select id="owner"><option value="">All owners</option>{options(sorted(oc))}</select><button id="reset">Reset filters</button></section>
<p><span id="count">{len(rows):,}</span> accounts shown</p><section class="table"><table><thead><tr><th>Account</th><th>Employees</th><th>Location</th><th>Owner</th><th>Tier / Status</th><th>Industry</th><th>PSA Platform</th><th>Billing Platform</th><th>Last Activity</th><th>Website</th><th>Phone</th></tr></thead><tbody>{table_rows(rows)}</tbody></table></section></main>
<script>const rows=[...document.querySelectorAll('tbody tr')],q=document.querySelector('#q'),st=document.querySelector('#state'),ow=document.querySelector('#owner'),count=document.querySelector('#count');function apply(){{let n=0,s=q.value.toLowerCase().trim();rows.forEach(r=>{{let ok=(!s||r.dataset.search.includes(s))&&(!st.value||r.dataset.state===st.value)&&(!ow.value||r.dataset.owner===ow.value);r.classList.toggle('hidden',!ok);if(ok)n++}});count.textContent=n.toLocaleString()}}[q,st,ow].forEach(x=>x.addEventListener('input',apply));document.querySelector('#reset').onclick=()=>{{q.value='';st.value='';ow.value='';apply()}};document.querySelectorAll('th').forEach((h,i)=>h.onclick=()=>{{let b=document.querySelector('tbody'),a=[...b.children].sort((x,y)=>{{let xv=x.children[i].innerText.replace(/,/g,''),yv=y.children[i].innerText.replace(/,/g,''),xn=+xv,yn=+yv;return !isNaN(xn)&&!isNaN(yn)?yn-xn:xv.localeCompare(yv)}});a.forEach(r=>b.appendChild(r))}});</script></body></html>'''

def main():
    rows=fetch(); DATA.write_text(json.dumps(rows,indent=2),encoding='utf-8'); OUT.write_text(build(rows),encoding='utf-8'); print(f'{len(rows)} accounts'); print(OUT)
if __name__=='__main__': main()
