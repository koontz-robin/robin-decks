#!/usr/bin/env python3
"""Build the October Primus sales dashboard using the May deck's exact metric structure."""
import json, re
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
import requests
from build_forecast_targets import sf_auth

R = Path(__file__).parent
LOGO = 'https://7091219.fs1.hubspotusercontent-na1.net/hubfs/7091219/email-assets/logo-revio-white.png'
MONTHS = [(2026, m, datetime(2026,m,1).strftime('%B')) for m in range(1,11)]
SHORT = [datetime(2026,m,1).strftime('%b') for m in range(1,11)]


def amount(xs): return sum(float(x.get('Amount') or 0) for x in xs)
def money(x): return '${:,.0f}'.format(x)
def compact(x): return f'${x/1000:.0f}K' if abs(x)>=1000 else money(x)
def prod(x):
    s=(x.get('Product_Type__c') or 'Other').lower()
    if 'psa' in s: return 'New Rev.io'
    if 'billing' in s or 'odin' in s: return 'Billing / Odin'
    if 'payment' in s: return 'Payments AR'
    if 'cyber' in s or 'commerce' in s: return 'Cyber + CommerceHub + Other'
    return 'Other / Not Set'
def source(x):
    marketing_source=str(x.get('Marketing_Source__c') or '').strip()
    if not marketing_source or marketing_source.lower() in ('sales', 'sales generated'):
        return 'Sales'
    return marketing_source
def owner_name(x):
    owner=x.get('Owner') or ''
    return ((owner.get('Name') or '') if isinstance(owner,dict) else str(owner)).strip()
def card(label,val,sub,color='teal',extra=''):
    return f'<div class="kpi-card {color} {extra}"><div class="kpi-label">{label}</div><div class="kpi-val {color}">{val}</div><div class="kpi-sub">{sub}</div></div>'
def header(tag,title):
    return f'<div class="top-stripe"></div><div class="slide-header"><div class="slide-header-left"><div class="slide-tag">{tag}</div><h2>{title}</h2></div><img src="{LOGO}" alt="Rev.io"></div>'
def section(t): return f'<div class="section-hdr"><div class="section-lbl">{t}</div><div class="section-rule"></div></div>'

def sf_query(base,headers,soql):
    out=[]; url=f'{base}/services/data/v59.0/query'; params={'q':soql}
    while True:
        r=requests.get(url,headers=headers,params=params,timeout=60); r.raise_for_status(); p=r.json(); out += p.get('records') or []
        if p.get('done',True): return out
        url=base+p['nextRecordsUrl']; params={}

def product_cards(won,open_,quotas,show_open=True):
    out=[]
    for p in ['New Rev.io','Billing / Odin','Payments AR']:
        w=[x for x in won if prod(x)==p]; o=[x for x in open_ if prod(x)==p]; q=quotas[p]; pct=round(amount(w)/q*100) if q else 0
        openrow=f'<div class="prod-row"><span class="prod-row-lbl">Open Pipeline</span><span class="prod-row-val teal">{money(amount(o))}</span></div>' if show_open else ''
        out.append(f'<div class="prod-card"><div class="prod-name">{p}</div><div class="prod-row"><span class="prod-row-lbl">Won MRR</span><span class="prod-row-val green">{money(amount(w))}</span></div>{openrow}<div class="prod-row"><span class="prod-row-lbl">Opportunities Won</span><span class="prod-row-val">{len(w)}</span></div><div class="prod-row"><span class="prod-row-lbl">Monthly Quota</span><span class="prod-row-val">{money(q)}</span></div><div class="quota-bar-wrap"><div class="quota-bar-bg"><div class="quota-bar-fill {'low' if pct<50 else 'mid'}" style="width:{min(pct,100)}%"></div></div><div class="quota-pct">{pct}% attained</div></div></div>')
    return '<div class="product-grid">'+''.join(out)+'</div>'

def month_card(label,created,wins,current=False):
    return f'<div class="month-card"><div class="month-name {'current' if current else ''}">{label}</div><div class="month-pipe">{compact(amount(created))}</div><div class="month-sub">{len(created)} opps</div><div class="month-win"><small>Won MRR</small><strong>{money(amount(wins))}</strong><em>{len(wins)} won</em></div></div>'

def table(headers,rows):
    hs=''.join(f'<th>{escape(str(h))}</th>' for h in headers)
    rs=''.join('<tr>'+''.join(f'<td>{c}</td>' for c in row)+'</tr>' for row in rows)
    return f'<div class="data-table"><table><thead><tr>{hs}</tr></thead><tbody>{rs}</tbody></table></div>'

def main():
    base,headers=sf_auth()
    fields='Id,Name,Account.Name,CreatedDate,CloseDate,StageName,Amount,Renewal_Amount__c,Type,Product_Type__c,Probability,Forecast_Status__c,Loss_Reason__c,Marketing_Source__c,Lead_Direction__c,Owner.Name'
    opps=sf_query(base,headers,f"SELECT {fields} FROM Opportunity WHERE CreatedDate>=2026-01-01T00:00:00Z OR CloseDate>=2026-04-01 ORDER BY CreatedDate")
    created={m:[x for x in opps if (x.get('CreatedDate') or '').startswith(f'2026-{m:02d}')] for m in range(1,11)}
    won={m:[x for x in opps if x.get('StageName')=='Closed Won' and (x.get('CloseDate') or '').startswith(f'2026-{m:02d}')] for m in range(1,11)}
    lost={m:[x for x in opps if x.get('StageName')=='Closed Lost' and (x.get('CloseDate') or '').startswith(f'2026-{m:02d}')] for m in range(1,11)}
    # Use the dashboard's refreshed close-month exports for final/MTD outcomes;
    # use the live query above for true CreatedDate cohorts.
    for m,name in ((7,'july'),(8,'august'),(9,'september'),(10,'october')):
        close_month=json.loads((R/f'sf_{name}_opps.json').read_text())
        won[m]=[x for x in close_month if x.get('StageName')=='Closed Won']
        lost[m]=[x for x in close_month if x.get('StageName')=='Closed Lost']
        if m==10: oct_close=close_month
    sep_won=won[9]
    oct_won=won[10]; oct_lost=lost[10]; oct_open=[x for x in oct_close if x.get('StageName') not in ('Closed Won','Closed Lost')]
    excluded_products={'Cyber + CommerceHub + Other'}
    sep_report=[x for x in sep_won if prod(x) not in excluded_products]
    oct_report=[x for x in oct_won if prod(x) not in excluded_products]
    oct_open_report=[x for x in oct_open if prod(x) not in excluded_products]
    high=[x for x in oct_open_report if (x.get('Forecast_Status__c') or '') in ('Most Likely','Best Case','Worst Case')]
    quotas={'New Rev.io':50000,'Billing / Odin':12383,'Payments AR':10540,'Cyber + CommerceHub + Other':6167}
    style=re.search(r'<style>(.*?)</style>',(R/'may-update-deck.html').read_text(),re.S).group(1)
    extra='''
.expanded-snapshot .slide-body{padding:10px 34px 56px}.expanded-snapshot .product-grid{grid-template-columns:repeat(3,1fr);gap:18px}.expanded-snapshot .prod-card{padding:20px 22px}.expanded-snapshot .prod-name{font-size:13px;margin-bottom:12px}.expanded-snapshot .prod-row{font-size:13px;padding:6px 0}.expanded-snapshot .quota-bar-wrap{margin-top:11px}.expanded-snapshot .quota-bar-bg{height:8px}.expanded-snapshot .quota-pct{font-size:11px;margin-top:5px}.month-grid{display:grid;grid-template-columns:repeat(10,1fr);gap:7px;margin-bottom:16px}.month-card{background:#0f2339;border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:10px 10px}.month-name{font:700 10px Montserrat;letter-spacing:1.2px;text-transform:uppercase;color:rgba(255,255,255,.42)}.month-name.current{color:#00d4f0}.month-pipe{font:900 18px Montserrat;color:#00d4f0;margin-top:5px}.month-sub{font-size:10px;color:rgba(255,255,255,.42)}.month-win{margin-top:7px;padding-top:7px;border-top:1px solid rgba(255,255,255,.06)}.month-win small,.month-win em{display:block;font-size:9px;color:rgba(255,255,255,.35);font-style:normal}.month-win strong{display:block;font:800 14px Montserrat;color:#3ddc97}.data-table{background:#0f2339;border:1px solid rgba(255,255,255,.07);border-radius:10px;overflow:hidden;margin-bottom:14px}.data-table table{width:100%;border-collapse:collapse;font-size:9px}.data-table th{padding:6px 5px;background:rgba(0,212,240,.08);color:#00d4f0;text-transform:uppercase;letter-spacing:.7px}.data-table td{padding:5px 5px;border-top:1px solid rgba(255,255,255,.05);text-align:center}.data-table td:first-child,.data-table th:first-child{text-align:left}.trend-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.loss-num{font:900 24px Montserrat;color:#f5a623}.summary-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.summary-strip>div{background:#0f2339;border:1px solid rgba(255,255,255,.07);border-radius:9px;padding:10px;text-align:center}.summary-strip strong{display:block;font:900 20px Montserrat;color:#00d4f0}.summary-strip span{font-size:9px;color:rgba(255,255,255,.42);text-transform:uppercase;letter-spacing:.7px}.eff-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.eff-card{background:#0f2339;border:1px solid rgba(255,255,255,.08);border-radius:11px;padding:14px 16px}.eff-month{font:800 11px Montserrat;color:#00d4f0;text-transform:uppercase;letter-spacing:1px}.eff-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}.eff-stat strong{display:block;font:900 20px Montserrat;color:#fff}.eff-stat:nth-child(3) strong{color:#3ddc97}.eff-stat span{font-size:8px;color:rgba(255,255,255,.4);text-transform:uppercase}.month-total-strip{display:flex;gap:18px;align-items:center;margin:-3px 0 7px;padding:6px 12px;background:rgba(0,212,240,.045);border:1px solid rgba(0,212,240,.12);border-radius:8px}.month-total-strip span{font-size:9px;color:rgba(255,255,255,.42);text-transform:uppercase;letter-spacing:.6px}.month-total-strip strong{margin-left:5px;font:800 14px Montserrat;color:#fff}.month-total-strip .green{color:#3ddc97}.zoomed-pipeline .slide-body{padding:8px 14px 56px!important}.zoomed-pipeline .month-grid{grid-template-columns:repeat(4,1fr)}.zoomed-pipeline .trend-grid{grid-template-columns:1fr;gap:4px}.zoomed-pipeline .data-table{margin-bottom:4px}.zoomed-pipeline .data-table table{font-size:11px}.zoomed-pipeline .data-table th{padding:8px 4px;font-size:10px}.zoomed-pipeline .data-table td{padding:7px 4px}.zoomed-pipeline .month-card{padding:13px 11px}.zoomed-pipeline .month-pipe{font-size:23px}.zoomed-pipeline .month-name{font-size:11px}.zoomed-pipeline .month-sub{font-size:11px}.zoomed-pipeline .month-win strong{font-size:16px}.zoomed-pipeline .section-lbl{font-size:12px}.migration-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.migration-card{background:#0f2339;border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:18px}.migration-month{font:800 13px Montserrat;color:#00d4f0;text-transform:uppercase}.migration-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:15px}.migration-stat strong{display:block;font:900 27px Montserrat}.migration-stat.won strong{color:#3ddc97}.migration-stat.lost strong{color:#ff7474}.migration-stat.rate strong{color:#eace9b}.migration-stat span{font-size:8px;color:rgba(255,255,255,.4);text-transform:uppercase}.stage-flow{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.stage-box{background:#0f2339;border:1px solid rgba(0,212,240,.12);border-radius:9px;padding:12px;text-align:center}.stage-box strong{display:block;font:900 25px Montserrat;color:#00d4f0}.stage-box span{font-size:8px;color:rgba(255,255,255,.45);text-transform:uppercase}.wins-columns{display:grid;grid-template-columns:1fr 1fr;gap:12px}.wins-table table{font-size:9px}.wins-table th{padding:7px 6px}.wins-table td{padding:5px 6px}.wins-table .client{font-weight:700;color:#fff;max-width:210px}.wins-table .money{font-family:Montserrat;font-weight:800;color:#eace9b}.combined-tigerpaw .slide-body{padding:7px 22px 54px}.combined-tigerpaw .section-lbl{margin:4px 0 3px}.combined-tigerpaw .migration-card{padding:8px 10px}.combined-tigerpaw .migration-stats{margin-top:5px}.combined-tigerpaw .migration-stat strong{font-size:19px}.combined-tigerpaw .stage-box{padding:6px}.combined-tigerpaw .stage-box strong{font-size:18px}.combined-tigerpaw .wins-table{margin-bottom:0}.combined-tigerpaw .wins-table th{padding:4px 5px}.combined-tigerpaw .wins-table td{padding:2px 5px;font-size:8px}.combined-billing .slide-body{padding:6px 18px 52px}.combined-billing .summary-strip{gap:6px}.combined-billing .summary-strip>div{padding:5px}.combined-billing .summary-strip strong{font-size:16px}.combined-billing .section-lbl{margin:4px 0 3px}.combined-billing .billing-interest-col{gap:2px}.combined-billing .billing-interest-row{padding:2px 5px;min-height:15px}.combined-billing .billing-client{font-size:7.5px}.combined-billing .billing-date,.combined-billing .billing-stage{font-size:7px}.billing-interest-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.billing-interest-col{display:flex;flex-direction:column;gap:4px}.billing-interest-row{display:grid;grid-template-columns:1fr 92px 72px 104px;gap:6px;align-items:center;background:#0f2339;border:1px solid rgba(255,255,255,.06);border-radius:6px;padding:5px 7px;min-height:23px}.billing-client{font-size:9px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.billing-date{font-size:8px;color:rgba(255,255,255,.4)}.billing-stage{font-size:8px;font-weight:800;text-align:center;padding:3px 4px;border-radius:4px;background:rgba(0,212,240,.1);color:#00d4f0}.billing-stage.lost{background:rgba(255,92,92,.1);color:#ff7474}.billing-stage.won{background:rgba(61,220,151,.12);color:#3ddc97}.q4-grid{display:grid;grid-template-columns:1fr;gap:10px}.q4-card{background:#0f2339;border:1px solid rgba(255,255,255,.08);border-radius:11px;padding:10px 12px}.q4-card-head{display:flex;justify-content:space-between;align-items:end;margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,.08)}.q4-card-head strong{font:800 12px Montserrat;color:#00d4f0}.q4-card-head span{font:900 18px Montserrat;color:#3ddc97}.q4-row{display:grid;grid-template-columns:22px 1fr 90px 112px 92px 70px;gap:7px;align-items:center;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.045);font-size:8px}.q4-row:last-child{border-bottom:0}.q4-columns{color:rgba(255,255,255,.38);font-size:7px;font-weight:800;text-transform:uppercase;letter-spacing:.5px}.q4-rank{color:rgba(255,255,255,.35);font-weight:800}.q4-name{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.q4-owner{color:rgba(255,255,255,.42);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.q4-stage{color:#7dd3fc;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.q4-forecast{color:#c4b5fd;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.q4-mrr{text-align:right;font:800 10px Montserrat;color:#eace9b}
'''
    slides=[]
    slides.append(f'<div class="slide active expanded-snapshot" id="slide-1">{header("Prior Month + Current Month Snapshot","September Final and October MTD")}<div class="slide-body">{section("September Product Results — Quota Attainment")}<div class="month-total-strip"><span>Total won MRR <strong class="green">{money(amount(sep_report))}</strong></span><span>Total opportunities won <strong>{len(sep_report)}</strong></span><span>Total open pipeline <strong>$0</strong></span></div>{product_cards(sep_report,[],quotas)}{section("October Product Results — Quota Attainment")}<div class="month-total-strip"><span>Total won MRR <strong class="green">{money(amount(oct_report))}</strong></span><span>Total opportunities won <strong>{len(oct_report)}</strong></span><span>Total open pipeline <strong>{money(amount(oct_open_report))}</strong></span><span>Total open opps <strong>{len(oct_open_report)}</strong></span></div>{product_cards(oct_report,oct_open_report,quotas)}</div></div>')
    q4_stage3_plus={'3 - Initial Product Demo','4 - Proposal Sent','5 - Product / Contract Validated','6 - Verbal Commit'}
    q4_products={'New Rev.io','Billing / Odin'}
    q4_open=[x for x in opps if x.get('StageName') in q4_stage3_plus and prod(x) in q4_products and '2026-10-01' <= (x.get('CloseDate') or '') <= '2026-12-31']
    q4_groups=[('New Rev.io + Billing / Odin',q4_products)]
    q4_cards=[]
    for product_label,product_set in q4_groups:
        rows=sorted([x for x in q4_open if prod(x) in product_set],key=lambda x:float(x.get('Amount') or 0),reverse=True)
        if not rows: continue
        ranked=[]
        stage_names={'3 - Initial Product Demo':'Stage 3 - Demo','4 - Proposal Sent':'Stage 4 - Proposal','5 - Product / Contract Validated':'Stage 5 - Validated','6 - Verbal Commit':'Stage 6 - Verbal'}
        for rank,x in enumerate(rows[:12],1):
            account=x.get('Account') or {}; account_name=(account.get('Name') if isinstance(account,dict) else account) or x.get('Name') or 'Unknown'
            stage=stage_names.get(x.get('StageName'),x.get('StageName') or 'Unknown')
            forecast=x.get('Forecast_Status__c') or 'Not Categorized'
            ranked.append(f'<div class="q4-row"><span class="q4-rank">{rank}</span><span class="q4-name" title="{escape(account_name)}">{escape(account_name)}</span><span class="q4-owner">{escape(owner_name(x) or "Unassigned")}</span><span class="q4-stage">{escape(stage)}</span><span class="q4-forecast">{escape(forecast)}</span><span class="q4-mrr">{money(float(x.get("Amount") or 0))}</span></div>')
        columns='<div class="q4-row q4-columns"><span>#</span><span>Account</span><span>Owner</span><span>Stage</span><span>Forecast</span><span style="text-align:right">MRR</span></div>'
        q4_cards.append(f'<div class="q4-card">{columns}{"".join(ranked)}</div>')
    q4_total=amount(q4_open)
    slides.append(f'<div class="slide" id="slide-q4">{header("Q4 Pipeline","Open Pipeline Ranked by MRR and Product")}<div class="slide-body" style="padding:12px 34px 58px"><div class="month-total-strip"><span>Total Q4 open MRR <strong class="green">{money(q4_total)}</strong></span><span>Total open opportunities <strong>{len(q4_open)}</strong></span><span>Close dates <strong>Oct 1 – Dec 31</strong></span></div><div class="q4-grid">{"".join(q4_cards)}</div></div></div>')
    excluded_efficiency_owners={'justin lee','ingrid beard','katerra stephenson greenwood','jakob champion'}
    eff_cards=[]
    for m in range(1,11):
        created_new_revio=[x for x in created[m] if prod(x)=='New Rev.io' and owner_name(x).lower() not in excluded_efficiency_owners]
        won_new_revio=[x for x in won[m] if prod(x)=='New Rev.io' and owner_name(x).lower() not in excluded_efficiency_owners]
        c=len(created_new_revio); w=len(won_new_revio); rate=w/c*100 if c else 0; mrr=amount(won_new_revio); mrr_per=mrr/c if c else 0
        label='Oct MTD' if m==10 else datetime(2026,m,1).strftime('%B')
        eff_cards.append(f'<div class="eff-card"><div class="eff-month">{label}</div><div class="eff-stats"><div class="eff-stat"><strong>{c}</strong><span>Created</span></div><div class="eff-stat"><strong>{w}</strong><span>Won</span></div><div class="eff-stat"><strong>{rate:.1f}%</strong><span>Win rate</span></div><div class="eff-stat"><strong>{money(mrr_per)}</strong><span>Won MRR / created opp</span></div></div></div>')
    ytd_created=sum(len([x for x in created[m] if prod(x)=='New Rev.io' and owner_name(x).lower() not in excluded_efficiency_owners]) for m in range(1,11)); ytd_won=sum(len([x for x in won[m] if prod(x)=='New Rev.io' and owner_name(x).lower() not in excluded_efficiency_owners]) for m in range(1,11)); ytd_mrr=sum(amount([x for x in won[m] if prod(x)=='New Rev.io' and owner_name(x).lower() not in excluded_efficiency_owners]) for m in range(1,11))
    trend_months=range(7,11)
    cards=''.join(month_card(('Oct MTD' if m==10 else datetime(2026,m,1).strftime('%B')),created[m],won[m],m==10) for m in trend_months)
    products=['New Rev.io','Billing / Odin','Payments AR','Cyber + CommerceHub + Other','Other / Not Set']
    prow=[]
    for p in products:
        row=[f'<strong>{p}</strong>']
        for m in trend_months:
            xs=[x for x in created[m] if prod(x)==p]; row.append(f'{len(xs)} · {compact(amount(xs))}')
        prow.append(row)
    sources=sorted({source(x) for m in trend_months for x in created[m]},key=lambda s:-sum(source(x)==s for m in trend_months for x in created[m]))[:8]
    srows=[]
    for src in sources:
        srows.append([f'<strong>{escape(src)}</strong>']+[str(sum(source(x)==src for x in created[m])) for m in trend_months])
    monthheads=['Metric','Jul','Aug','Sep','Oct MTD']
    totalpipe=sum(amount(created[m]) for m in trend_months); peak=max((len(won[m]),m) for m in trend_months); top_prod=max(products,key=lambda p:sum(len([x for x in created[m] if prod(x)==p]) for m in trend_months))
    slides.append(f'<div class="slide zoomed-pipeline" id="slide-5">{header("Pipeline Creation","Pipeline Trends — July Through October MTD")}<div class="slide-body">{section("Monthly Pipeline Created")}<div class="month-grid">{cards}</div><div class="trend-grid"><div>{section("Pipeline by Product")}{table(monthheads,prow)}</div><div>{section("Pipeline by Source")}{table(monthheads,srows)}</div></div></div></div>')
    legacy=[x for x in opps if (x.get('Type') or '')=='Legacy Migration']
    migration_cards=[]
    migration_totals={'created':0,'won':0,'lost':0}
    for m in (8,9,10):
        cr=[x for x in legacy if (x.get('CreatedDate') or '').startswith(f'2026-{m:02d}')]
        mw=[x for x in legacy if x.get('StageName')=='Closed Won' and (x.get('CloseDate') or '').startswith(f'2026-{m:02d}')]
        ml=[x for x in legacy if x.get('StageName')=='Closed Lost' and (x.get('CloseDate') or '').startswith(f'2026-{m:02d}')]
        decisions=len(mw)+len(ml); rate=len(mw)/decisions*100 if decisions else 0
        migration_totals['created']+=len(cr); migration_totals['won']+=len(mw); migration_totals['lost']+=len(ml)
        label='October MTD' if m==10 else datetime(2026,m,1).strftime('%B')
        migration_cards.append(f'<div class="migration-card"><div class="migration-month">{label}</div><div class="migration-stats"><div class="migration-stat"><strong>{len(cr)}</strong><span>Created</span></div><div class="migration-stat won"><strong>{len(mw)}</strong><span>Won</span></div><div class="migration-stat lost"><strong>{len(ml)}</strong><span>Lost</span></div><div class="migration-stat rate"><strong>{rate:.0f}%</strong><span>Decision win rate</span></div></div></div>')
    legacy_open=[x for x in legacy if x.get('StageName') not in ('Closed Won','Closed Lost')]
    stage_order=['1- Discovery Scheduled','2 - Discovery Completed','3 - Initial Product Demo','4 - Proposal Sent','5 - Product / Contract Validated','6 - Verbal Commit']
    stage_labels=['Discovery Scheduled','Discovery Completed','Initial Demo','Proposal Sent','Validated','Verbal Commit']
    stage_html=''.join(f'<div class="stage-box"><strong>{sum(x.get("StageName")==stage for x in legacy_open)}</strong><span>{label}</span></div>' for stage,label in zip(stage_order,stage_labels))
    decision_total=migration_totals['won']+migration_totals['lost']; overall_rate=migration_totals['won']/decision_total*100 if decision_total else 0
    legacy_wins=sorted([x for x in legacy if x.get('StageName')=='Closed Won' and '2026-08-01' <= (x.get('CloseDate') or '') <= '2026-10-31'],key=lambda x:(x.get('CloseDate') or '',x.get('Name') or ''))
    def win_rows(rows):
        out=[]
        for x in rows:
            account=x.get('Account') or {}
            client=(account.get('Name') if isinstance(account,dict) else account) or x.get('Name') or 'Unknown'
            renewal=x.get('Renewal_Amount__c')
            out.append(f'<tr><td class="client">{escape(client)}</td><td>{escape(x.get("CloseDate") or "")}</td><td class="money">{money(renewal) if renewal is not None else "—"}</td></tr>')
        return ''.join(out)
    midpoint=(len(legacy_wins)+1)//2
    def wins_table(rows):
        return f'<div class="data-table wins-table"><table><thead><tr><th>Client</th><th>Won</th><th>Renewal</th></tr></thead><tbody>{win_rows(rows)}</tbody></table></div>'
    renewal_total=sum(float(x.get('Renewal_Amount__c') or 0) for x in legacy_wins)
    slides.append(f'<div class="slide combined-tigerpaw" id="slide-tigerpaw">{header("Legacy Migration Opportunity Type","Tigerpaw Migration Progress + Closed Won Clients")}<div class="slide-body">{section("Monthly Migration Progress")}<div class="migration-grid">{"".join(migration_cards)}</div>{section("Current Active Migration Funnel")}<div class="stage-flow">{stage_html}</div>{section(f"August–October Closed Won — {len(legacy_wins)} Clients · {money(renewal_total)} Renewal Amount")}<div class="wins-columns">{wins_table(legacy_wins[:midpoint])}{wins_table(legacy_wins[midpoint:])}</div></div></div>')
    billing_interest_raw=sf_query(base,headers,"SELECT Id,Name,CreatedDate,CloseDate,StageName,Account.Id,Account.Name,Account.PSA_Platform__c FROM Opportunity WHERE CreatedDate>=2025-07-01T00:00:00Z AND Product_Type__c IN ('PSA','PSA 2.0') AND Account.Type='Rev.io Billing Client' ORDER BY CreatedDate DESC")
    billing_interest={}
    for x in billing_interest_raw:
        account=x.get('Account') or {}; account_id=account.get('Id') or account.get('Name')
        if account_id not in billing_interest: billing_interest[account_id]=x
    sold_psa_billing_clients={
        'Blue Water Networks','All Serve Communications','Xact Communications','RyTel','JD Telecom','KeyCom',
        'Bullfrog Group LLC','FuseCloud Solutions','Trifecta Solutions','Losh Communications','Stratus Telecom',
        'Tailwinds Voice & Data','Avalora','Class 5 Technologies','Wyoming.com','Global Data Technologies',
        'Centra IP Networks','Virtual Guardians','Dialog Telecommunications, Inc.'
    }
    billing_wins_raw=sf_query(base,headers,"SELECT Id,Name,CreatedDate,CloseDate,StageName,Account.Id,Account.Name,Account.PSA_Platform__c FROM Opportunity WHERE CloseDate>=2025-07-01 AND Product_Type__c IN ('PSA','PSA 2.0') AND StageName='Closed Won' ORDER BY CloseDate")
    billing_wins=[x for x in billing_wins_raw if ((x.get('Account') or {}).get('Name') or '') in sold_psa_billing_clients]
    billing_combined=dict(billing_interest)
    for x in billing_wins:
        account=x.get('Account') or {}; account_id=account.get('Id') or account.get('Name')
        billing_combined[account_id]=x
    billing_clients=sorted(billing_combined.values(),key=lambda x:((x.get('CloseDate') or '9999-12-31'),((x.get('Account') or {}).get('Name') or '').lower()))
    stage_short={'1- Discovery Scheduled':'Discovery Scheduled','2 - Discovery Completed':'Discovery Completed','3 - Initial Product Demo':'Initial Demo','4 - Proposal Sent':'Proposal Sent','5 - Product / Contract Validated':'Validated','6 - Verbal Commit':'Verbal Commit','Closed Won':'Closed Won','Closed Lost':'Closed Lost'}
    rows=[]
    for x in billing_clients:
        account=x.get('Account') or {}; stage=x.get('StageName') or 'Other'; cls=' lost' if stage=='Closed Lost' else (' won' if stage=='Closed Won' else '')
        rows.append(f'<div class="billing-interest-row"><div class="billing-client" title="{escape(account.get("Name") or "Unknown")}">{escape(account.get("Name") or "Unknown")}</div><div class="billing-date">{escape(account.get("PSA_Platform__c") or "—")}</div><div class="billing-date">{escape(x.get("CloseDate") or "No date")}</div><div class="billing-stage{cls}">{escape(stage_short.get(stage,stage))}</div></div>')
    chunk=(len(rows)+2)//3
    columns=''.join(f'<div class="billing-interest-col">{"".join(rows[i:i+chunk])}</div>' for i in range(0,len(rows),chunk))
    open_interest=sum(x.get('StageName') not in ('Closed Won','Closed Lost') for x in billing_clients); lost_interest=sum(x.get('StageName')=='Closed Lost' for x in billing_clients); won_interest=sum(x.get('StageName')=='Closed Won' for x in billing_clients)
    slides.append(f'<div class="slide combined-billing" id="slide-billing-interest">{header("Billing Client Expansion","Billing Client New Rev.io Opportunities + Closed Won")}<div class="slide-body"><div class="summary-strip"><div><strong>{len(billing_clients)}</strong><span>Billing clients represented</span></div><div><strong>{open_interest}</strong><span>Currently open</span></div><div><strong>{won_interest} / {lost_interest}</strong><span>Won / Lost</span></div></div>{section("New Rev.io Opportunities — Sorted by Opportunity Close Date")}<div class="billing-interest-grid">{columns}</div></div></div>')
    loss_cards=''.join(f'<div class="month-card"><div class="month-name {'current' if m==10 else ''}">{"Oct MTD" if m==10 else datetime(2026,m,1).strftime("%B")}</div><div class="loss-num">{len(lost[m])}</div><div class="month-sub">closed lost</div></div>' for m in range(1,11))
    allreasons=Counter(x.get('Loss_Reason__c') or 'Unknown' for m in range(1,11) for x in lost[m])
    reasons=[r for r,_ in allreasons.most_common(9)]
    rrows=[]
    for r in reasons:
        vals=[sum((x.get('Loss_Reason__c') or 'Unknown')==r for x in lost[m]) for m in range(1,11)]
        rrows.append([f'<strong>{escape(r)}</strong>']+[str(v) for v in vals]+[f'{vals[-1]-vals[0]:+d}'])
    delta=len(lost[10])-len(lost[1]); pct=(delta/len(lost[1])*100) if lost[1] else 0
    slides.append(f'<div class="slide" id="slide-6">{header("Closed-Lost Analysis","Loss Reason Trends — January Through October MTD")}<div class="slide-body" style="padding:14px 40px 60px">{section("Closed Lost Volume")}<div class="month-grid">{loss_cards}</div>{section("Loss Reasons by Month")}{table(["Reason"]+SHORT[:-1]+["Oct MTD","Jan→Oct"],rrows)}<div class="summary-strip"><div><strong>{len(lost[1])}</strong><span>January losses</span></div><div><strong>{pct:+.0f}%</strong><span>Change through Oct MTD</span></div><div><strong>{escape((Counter(x.get('Loss_Reason__c') or 'Unknown' for x in lost[10]).most_common(1) or [('None',0)])[0][0])}</strong><span>Top October reason</span></div></div></div></div>')
    ids=['slide-1','slide-q4','slide-5','slide-6','slide-tigerpaw','slide-billing-interest']; labels=['September + October','Q4 Pipeline by Product','Pipeline Trends','Closed Lost','Tigerpaw Migration + Wins','Billing Client Opportunities + Wins']
    script=f"const TOTAL=6;let cur=1;const IDS={json.dumps(ids)},LABELS={json.dumps(labels)};function buildDots(){{let w=document.getElementById('nav-dots');for(let i=1;i<=TOTAL;i++){{let d=document.createElement('div');d.className='nav-dot';d.title=LABELS[i-1];d.onclick=()=>showSlide(i);w.appendChild(d)}}}}function showSlide(n){{cur=Math.max(1,Math.min(TOTAL,n));document.querySelectorAll('.slide').forEach(x=>x.classList.remove('active'));document.getElementById(IDS[cur-1]).classList.add('active');document.querySelectorAll('.nav-dot').forEach((x,i)=>x.classList.toggle('active',i===cur-1));document.getElementById('nav-counter').textContent=cur+' / '+TOTAL;document.getElementById('btn-prev').disabled=cur===1;document.getElementById('btn-next').disabled=cur===TOTAL}}function goSlide(d){{showSlide(cur+d)}}buildDots();showSlide(1);addEventListener('keydown',e=>{{if(e.key==='ArrowRight')goSlide(1);if(e.key==='ArrowLeft')goSlide(-1)}});"
    nav=f'<div class="nav-bar"><div class="nav-title">Primus Sales · October Progress</div><div class="nav-controls"><button class="nav-btn" id="btn-prev" onclick="goSlide(-1)">← Prev</button><div class="nav-dots" id="nav-dots"></div><span class="nav-counter" id="nav-counter">1 / 6</span><button class="nav-btn" id="btn-next" onclick="goSlide(1)">Next →</button></div><img src="{LOGO}" class="nav-logo"></div>'
    # Start with the May deck itself and patch its content in place. This keeps
    # the original document shell, visual system, and six-slide presentation
    # behavior instead of creating a parallel deck implementation.
    html=(R/'may-update-deck.html').read_text()
    html=re.sub(r'<title>.*?</title>', '<title>Primus Sales · October Progress</title>', html, count=1, flags=re.S)
    html=re.sub(r'<style>.*?</style>', '<style>'+style+extra+'</style>', html, count=1, flags=re.S)
    deck_start=html.index('<div class="deck">')
    nav_start=html.index('<!-- NAV BAR -->',deck_start)
    html=html[:deck_start]+'<div class="deck">'+''.join(slides)+'</div>\n'+html[nav_start:]
    nav_start=html.index('<div class="nav-bar">',deck_start)
    script_start=html.index('<script>',nav_start)
    script_end=html.index('</script>',script_start)+len('</script>')
    html=html[:nav_start]+nav+'<script>'+script+'</script>'+html[script_end:]
    (R/'primus-october-progress-dashboard.html').write_text(html)
    print(json.dumps({'september':{'created':len(created[9]),'won':len(sep_won),'mrr':amount(sep_won),'lost':len(lost[9])},'october':{'created':len(created[10]),'won':len(oct_won),'mrr':amount(oct_won),'open':len(oct_open),'open_mrr':amount(oct_open),'lost':len(oct_lost)}},indent=2))

if __name__=='__main__': main()
