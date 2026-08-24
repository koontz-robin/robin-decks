#!/usr/bin/env python3
"""Build and publish Q3 ICP Pipeline analysis dashboard from Salesforce report 00OPX00000A6Bkb2AF."""

import json
import os
import shutil
import statistics
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from build_forecast_targets import sf_auth  # reuses existing Salesforce auth setup; avoids duplicating credentials here.

WORKSPACE = Path('/home/openclaw/.openclaw/workspace')
REPORT_ID = '00OPX00000A6Bkb2AF'
REPORT_URL = f'https://rev-io.lightning.force.com/lightning/r/Report/{REPORT_ID}/view'
HTML_FILE = WORKSPACE / 'q3-icp-pipeline-analysis.html'
DATA_FILE = WORKSPACE / 'q3_icp_pipeline_analysis.json'
LIBRARY_FILE = WORKSPACE / 'DECKS-LIBRARY.md'
ET = ZoneInfo('America/New_York')

STAGE_ORDER = [
    '',
    '1- Discovery Scheduled',
    '2 - Discovery Completed',
    '3 - Initial Product Demo',
    '4 - Proposal Sent',
    '5 - Product / Contract Validated',
    '6 - Verbal Commit',
    'Closed Won',
    'Closed Lost',
]
OPEN_STAGES = set(STAGE_ORDER[:-2])
CLOSED_WON = 'Closed Won'
CLOSED_LOST = 'Closed Lost'

DETAIL_KEYS = {
    'FULL_NAME': 'owner',
    'OPPORTUNITY_NAME': 'opportunity',
    'ACCOUNT_NAME': 'account',
    'EMPLOYEES': 'employees',
    'Account.PSA_Platform__c': 'psa_platform',
    'AMOUNT': 'amount',
    'INDUSTRY': 'industry',
    'CLOSE_DATE': 'close_date',
    'NEXT_STEP': 'next_step',
    'AGE': 'age',
    'Opportunity.Loss_Reason__c': 'loss_reason',
    'Opportunity.Reason_Lost_Detail__c': 'reason_lost_detail',
    'Opportunity.Missing_Features__c': 'missing_features',
}


def money(value):
    return f"${float(value or 0):,.0f}"


def pct(value, denom):
    return (float(value or 0) / float(denom or 0) * 100) if denom else 0.0


def clean_label(value):
    if value in (None, '', '-', 'None'):
        return ''
    return str(value).strip()


def raw_cell_value(cell):
    value = cell.get('value')
    if isinstance(value, dict) and 'amount' in value:
        return float(value.get('amount') or 0)
    if isinstance(value, list):
        return [clean_label(x) for x in value if clean_label(x)]
    return value


def fetch_report(base, headers):
    url = f'{base}/services/data/v59.0/analytics/reports/{REPORT_ID}'
    response = requests.get(url, headers=headers, params={'includeDetails': 'true'}, timeout=60)
    if not response.ok:
        raise RuntimeError(f'Salesforce report fetch failed: {response.status_code} {response.text[:500]}')
    return response.json()


def sf_query(base, headers, query):
    url = f'{base}/services/data/v59.0/query'
    params = {'q': query.strip()}
    records = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if not response.ok:
            raise RuntimeError(f'Salesforce query failed: {response.status_code} {response.text[:500]}')
        payload = response.json()
        records.extend(payload.get('records') or [])
        if payload.get('done', True):
            return records
        url = base + payload['nextRecordsUrl']
        params = {}


def enrich_from_opportunities(base, headers, rows):
    """Pull full text fields from Opportunity records.

    The Analytics API report detail rows can truncate long textarea values, so use
    the report for row scope and then hydrate the loss fields directly from SF.
    """
    ids = sorted({r.get('opportunity_id') for r in rows if str(r.get('opportunity_id', '')).startswith('006')})
    if not ids:
        return rows
    quoted = ",".join(f"'{i}'" for i in ids)
    query = f"""
        SELECT Id, StageName, Loss_Reason__c, Reason_Lost_Detail__c, Missing_Features__c, NextStep
        FROM Opportunity
        WHERE Id IN ({quoted})
    """
    by_id = {r['Id']: r for r in sf_query(base, headers, query)}
    for row in rows:
        rec = by_id.get(row.get('opportunity_id'))
        if not rec:
            continue
        row['stage'] = rec.get('StageName') or row.get('stage') or ''
        row['loss_reason'] = clean_label(rec.get('Loss_Reason__c')) or row.get('loss_reason') or ''
        row['reason_lost_detail'] = clean_label(rec.get('Reason_Lost_Detail__c')) or row.get('reason_lost_detail') or ''
        row['next_step'] = clean_label(rec.get('NextStep')) or row.get('next_step') or ''
        features = clean_label(rec.get('Missing_Features__c'))
        if features:
            row['missing_features'] = [x.strip() for x in features.replace(';', ',').split(',') if x.strip()]
    return rows


def parse_report(report):
    detail_columns = report['reportMetadata']['detailColumns']
    groupings = report.get('groupingsDown', {}).get('groupings', [])
    stage_by_key = {str(i): g.get('label') or g.get('value') or 'Unspecified' for i, g in enumerate(groupings)}
    column_info = report.get('reportExtendedMetadata', {}).get('detailColumnInfo', {})

    rows = []
    seen = set()
    for fact_key, fact in report.get('factMap', {}).items():
        if not fact_key.endswith('!T') or fact_key == 'T!T':
            continue
        stage_key = fact_key.split('!')[0]
        stage = stage_by_key.get(stage_key, 'Unspecified')
        for row in fact.get('rows') or []:
            rec = {'stage': stage}
            opportunity_id = ''
            account_id = ''
            for column, cell in zip(detail_columns, row.get('dataCells') or []):
                key = DETAIL_KEYS.get(column, column)
                value = raw_cell_value(cell)
                label = clean_label(cell.get('label'))
                if column in {'OPPORTUNITY_NAME', 'ACCOUNT_NAME'}:
                    rec[key] = label or clean_label(value)
                    if column == 'OPPORTUNITY_NAME':
                        opportunity_id = clean_label(cell.get('recordId') or value)
                    if column == 'ACCOUNT_NAME':
                        account_id = clean_label(cell.get('recordId') or value)
                elif column == 'AMOUNT':
                    rec[key] = float(value or 0)
                elif column in {'EMPLOYEES', 'AGE'}:
                    rec[key] = int(float(value or 0)) if value not in (None, '') else 0
                elif column == 'Opportunity.Missing_Features__c':
                    if isinstance(value, list):
                        rec[key] = value
                    else:
                        rec[key] = [x.strip() for x in str(label or value or '').replace(';', ',').split(',') if x.strip() and x.strip() != '-']
                else:
                    rec[key] = label or clean_label(value)
            rec['opportunity_id'] = opportunity_id
            rec['account_id'] = account_id
            dedupe = (opportunity_id, rec.get('stage'), rec.get('amount'))
            if dedupe not in seen:
                seen.add(dedupe)
                rows.append(rec)

    return rows, detail_columns, column_info


def bucket_employee_count(n):
    n = int(n or 0)
    if n < 25: return '10–24'
    if n < 50: return '25–49'
    if n < 100: return '50–99'
    if n < 250: return '100–249'
    return '250+'


def loss_theme(row):
    reason = (row.get('loss_reason') or '').lower()
    detail = (row.get('reason_lost_detail') or '').lower()
    features = ' '.join(row.get('missing_features') or []).lower()
    text = f'{reason} {detail} {features}'
    if 'no show' in text or 'reschedul' in text or 'get back' in text:
        return 'Sales process / no-show'
    if 'software missing' in text or 'integration' in text or 'feature' in text or 'print' in text or 'billing' in text:
        return 'Product / integration gap'
    if 'contract' in text or '2027' in text:
        return 'Incumbent contract timing'
    if 'not the right time' in text or 'priority' in text or 'q1' in text or 'summit' in text:
        return 'Timing / priority'
    if 'no business issue' in text or 'exploratory' in text or 'purpose driven' in text:
        return 'Weak pain / no business issue'
    if 'not right customer' in text or 'jira' in text:
        return 'ICP / customer fit'
    return row.get('loss_reason') or 'Unspecified'


def summarize(rows, report):
    open_rows = [r for r in rows if r['stage'] not in {CLOSED_WON, CLOSED_LOST}]
    won_rows = [r for r in rows if r['stage'] == CLOSED_WON]
    lost_rows = [r for r in rows if r['stage'] == CLOSED_LOST]
    closed_rows = won_rows + lost_rows
    total_amount = sum(r['amount'] for r in rows)
    open_amount = sum(r['amount'] for r in open_rows)
    won_amount = sum(r['amount'] for r in won_rows)
    lost_amount = sum(r['amount'] for r in lost_rows)
    ages = [r['age'] for r in rows if r.get('age')]

    def rollup(key, source=None):
        source = source or rows
        out = defaultdict(lambda: {'count': 0, 'amount': 0.0})
        for r in source:
            label = r.get(key) or 'Unspecified'
            out[label]['count'] += 1
            out[label]['amount'] += r['amount']
        return sorted(([{'label': k, **v} for k, v in out.items()]), key=lambda x: (-x['amount'], x['label']))

    features = Counter()
    for r in lost_rows:
        for f in r.get('missing_features') or []:
            features[f] += 1
    if not features:
        for r in rows:
            for f in r.get('missing_features') or []:
                features[f] += 1

    summary = {
        'generated_at_et': datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z'),
        'report_id': REPORT_ID,
        'report_name': report.get('reportMetadata', {}).get('name'),
        'report_url': REPORT_URL,
        'filters': report.get('reportMetadata', {}).get('reportFilters') or [],
        'standard_filters': report.get('reportMetadata', {}).get('standardFilters') or [],
        'total_count': len(rows),
        'total_amount': total_amount,
        'open_count': len(open_rows),
        'open_amount': open_amount,
        'won_count': len(won_rows),
        'won_amount': won_amount,
        'lost_count': len(lost_rows),
        'lost_amount': lost_amount,
        'win_rate_count': pct(len(won_rows), len(closed_rows)),
        'win_rate_amount': pct(won_amount, won_amount + lost_amount),
        'avg_age': statistics.mean(ages) if ages else 0,
        'median_age': statistics.median(ages) if ages else 0,
        'stage': rollup('stage'),
        'open_stage': rollup('stage', open_rows),
        'owner': rollup('owner'),
        'open_owner': rollup('owner', open_rows),
        'platform': rollup('psa_platform'),
        'industry': rollup('industry'),
        'employee_bucket': [],
        'loss_reason': rollup('loss_reason', lost_rows),
        'loss_theme': [],
        'stage_detail': [],
        'closed_lost_detail': [],
        'missing_features': [{'label': k, 'count': v} for k, v in features.most_common()],
    }
    theme = defaultdict(lambda: {'count': 0, 'amount': 0.0})
    for r in lost_rows:
        t = loss_theme(r)
        r['loss_theme'] = t
        theme[t]['count'] += 1
        theme[t]['amount'] += r['amount']
    summary['loss_theme'] = sorted(([{'label': k, **v} for k, v in theme.items()]), key=lambda x: (-x['amount'], x['label']))
    for stage_item in summary['stage']:
        stage_rows = [r for r in rows if r['stage'] == stage_item['label']]
        top_owner = Counter(r.get('owner') or 'Unspecified' for r in stage_rows).most_common(1)
        top_platform = Counter(r.get('psa_platform') or 'Unspecified' for r in stage_rows).most_common(1)
        summary['stage_detail'].append({
            **stage_item,
            'top_owner': top_owner[0][0] if top_owner else '—',
            'top_platform': top_platform[0][0] if top_platform else '—',
            'avg_age': statistics.mean([r['age'] for r in stage_rows if r.get('age')]) if any(r.get('age') for r in stage_rows) else 0,
        })
    summary['closed_lost_detail'] = sorted(lost_rows, key=lambda r: (loss_theme(r), r.get('loss_reason') or '', -r.get('amount', 0), r.get('opportunity') or ''))
    emp = defaultdict(lambda: {'count': 0, 'amount': 0.0})
    for r in rows:
        b = bucket_employee_count(r.get('employees'))
        emp[b]['count'] += 1
        emp[b]['amount'] += r['amount']
    order = ['10–24', '25–49', '50–99', '100–249', '250+']
    summary['employee_bucket'] = [{'label': b, **emp[b]} for b in order if emp[b]['count']]
    return summary


def css_bar(items, amount_key='amount', label_suffix=''):
    if not items:
        return '<div class="muted">No data</div>'
    maxv = max(float(i.get(amount_key) or 0) for i in items) or 1
    chunks = []
    for item in items:
        value = float(item.get(amount_key) or 0)
        width = max(4, value / maxv * 100)
        right = money(value) if amount_key == 'amount' else f"{int(value)}{label_suffix}"
        sub = f"{item.get('count', 0)} opps" if 'count' in item and amount_key == 'amount' else ''
        chunks.append(f'''
        <div class="bar-row">
          <div class="bar-label" title="{escape(str(item['label']))}">{escape(str(item['label']))}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%"></div></div>
          <div class="bar-value"><strong>{right}</strong><span>{sub}</span></div>
        </div>''')
    return '\n'.join(chunks)


def metric(label, value, sub=''):
    return f'<div class="metric"><div class="metric-label">{escape(label)}</div><div class="metric-value">{escape(value)}</div><div class="metric-sub">{escape(sub)}</div></div>'


def render_filters(summary):
    labels = []
    for f in summary['filters']:
        col = f.get('column', '')
        op = f.get('operator', '')
        val = f.get('value', '')
        labels.append(f'<span>{escape(col)} {escape(op)} <b>{escape(val)}</b></span>')
    return ''.join(labels)


def render_table(rows):
    ordered = sorted(rows, key=lambda r: (r['stage'] == CLOSED_LOST, r['stage'] == CLOSED_WON, r.get('close_date') or '', -r['amount']))
    trs = []
    for r in ordered:
        opp_url = f"https://rev-io.lightning.force.com/lightning/r/Opportunity/{r['opportunity_id']}/view" if r.get('opportunity_id', '').startswith('006') else '#'
        features = ', '.join(r.get('missing_features') or [])
        next_step = r.get('next_step') or r.get('reason_lost_detail') or ''
        trs.append(f'''
        <tr data-stage="{escape(r['stage'])}" data-owner="{escape(r.get('owner',''))}" data-platform="{escape(r.get('psa_platform',''))}">
          <td><span class="pill stage-{escape(r['stage'].lower().replace(' ', '-').replace('/', '-'))}">{escape(r['stage'] or 'Unspecified')}</span></td>
          <td><a href="{opp_url}" target="_blank">{escape(r.get('opportunity') or '')}</a><div class="subtle">{escape(r.get('account') or '')}</div></td>
          <td>{escape(r.get('owner') or '')}</td>
          <td>{escape(r.get('psa_platform') or '—')}</td>
          <td>{int(r.get('employees') or 0):,}</td>
          <td>{money(r.get('amount'))}</td>
          <td>{escape(r.get('close_date') or '')}</td>
          <td>{int(r.get('age') or 0)}</td>
          <td>{escape(next_step[:220])}</td>
          <td>{escape(features or r.get('loss_reason') or '')}</td>
        </tr>''')
    return '\n'.join(trs)


def render_stage_breakdown(summary):
    rows = []
    for item in summary['stage_detail']:
        label = item['label']
        pill_class = label.lower().replace(' ', '-').replace('/', '-')
        rows.append(f'''
        <tr>
          <td><span class="pill stage-{escape(pill_class)}">{escape(label)}</span></td>
          <td>{item['count']}</td>
          <td>{money(item['amount'])}</td>
          <td>{pct(item['amount'], summary['total_amount']):.1f}%</td>
          <td>{escape(item['top_owner'])}</td>
          <td>{escape(item['top_platform'])}</td>
          <td>{item['avg_age']:.0f}d</td>
        </tr>''')
    return '\n'.join(rows)


def render_closed_lost_deep_dive(summary):
    groups = defaultdict(list)
    for row in summary['closed_lost_detail']:
        groups[row.get('loss_theme') or loss_theme(row)].append(row)
    sections = []
    for theme in [x['label'] for x in summary['loss_theme']]:
        items = groups.get(theme) or []
        amount = sum(r['amount'] for r in items)
        sections.append(f'''
        <div class="loss-group">
          <div class="loss-group-head">
            <div><strong>{escape(theme)}</strong><span>{len(items)} opps • {money(amount)}</span></div>
            <div>{pct(amount, summary['lost_amount']):.0f}% of lost $</div>
          </div>
          {''.join(render_lost_card(r) for r in items)}
        </div>''')
    return '\n'.join(sections)


def render_lost_card(r):
    opp_url = f"https://rev-io.lightning.force.com/lightning/r/Opportunity/{r['opportunity_id']}/view" if r.get('opportunity_id', '').startswith('006') else '#'
    features = ', '.join(r.get('missing_features') or [])
    return f'''
    <div class="lost-card">
      <div class="lost-title">
        <a href="{opp_url}" target="_blank">{escape(r.get('opportunity') or '')}</a>
        <span>{money(r.get('amount'))}</span>
      </div>
      <div class="lost-meta">{escape(r.get('owner') or '')} • {escape(r.get('psa_platform') or 'No PSA captured')} • {escape(r.get('industry') or '')}</div>
      <div class="lost-reason"><b>{escape(r.get('loss_reason') or 'No loss reason')}</b>{' • ' + escape(features) if features else ''}</div>
      <div class="lost-detail">{escape(r.get('reason_lost_detail') or 'No reason-lost detail captured')}</div>
    </div>'''


def build_html(rows, summary):
    open_gap = summary['open_amount']
    closed_decision_amount = summary['won_amount'] + summary['lost_amount']
    biggest_open_owner = summary['open_owner'][0] if summary['open_owner'] else {'label':'—','amount':0,'count':0}
    biggest_platform = summary['platform'][0] if summary['platform'] else {'label':'—','amount':0,'count':0}
    filters_html = render_filters(summary)
    html = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Q3 ICP Pipeline Analysis</title>
<style>
:root {{ --bg:#061522; --panel:#0d2234; --panel2:#102b42; --text:#f5fbff; --muted:#9fb5c5; --line:#1d4059; --green:#50ff8a; --teal:#2ee6be; --blue:#55b8ff; --purple:#9b7cff; --red:#ff5d74; --gold:#eace9b; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: radial-gradient(circle at top left, rgba(80,255,138,.16), transparent 32rem), radial-gradient(circle at top right, rgba(85,184,255,.14), transparent 30rem), var(--bg); color:var(--text); }}
a {{ color:var(--green); text-decoration:none; }}
.wrapper {{ max-width:1480px; margin:0 auto; padding:32px; }}
.hero {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-start; margin-bottom:22px; }}
.eyebrow {{ color:var(--green); font-weight:800; letter-spacing:.16em; text-transform:uppercase; font-size:12px; }}
h1 {{ font-size:44px; line-height:1; margin:10px 0 10px; letter-spacing:-.045em; }}
.lede {{ color:#c7d6e0; max-width:860px; font-size:16px; line-height:1.55; }}
.source {{ text-align:right; color:var(--muted); font-size:13px; min-width:280px; }}
.metrics {{ display:grid; grid-template-columns: repeat(6, 1fr); gap:14px; margin:22px 0; }}
.metric {{ background:linear-gradient(180deg, rgba(255,255,255,.07), rgba(255,255,255,.03)); border:1px solid var(--line); border-radius:18px; padding:18px; min-height:114px; box-shadow:0 20px 50px rgba(0,0,0,.18); }}
.metric-label {{ color:var(--muted); font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }}
.metric-value {{ font-size:30px; font-weight:900; margin-top:10px; letter-spacing:-.04em; }}
.metric-sub {{ color:var(--muted); font-size:13px; margin-top:8px; }}
.grid {{ display:grid; grid-template-columns: 1.25fr 1fr 1fr; gap:18px; margin:18px 0; }}
.grid.two {{ grid-template-columns: 1fr 1fr; }}
.card {{ background:rgba(13,34,52,.88); border:1px solid var(--line); border-radius:22px; padding:20px; box-shadow:0 22px 60px rgba(0,0,0,.22); overflow:hidden; }}
.card h2 {{ margin:0 0 14px; font-size:20px; letter-spacing:-.02em; }}
.card h3 {{ margin:18px 0 10px; color:#d9f3ff; font-size:15px; }}
.callout {{ border-left:4px solid var(--green); padding:12px 14px; background:rgba(80,255,138,.08); border-radius:12px; color:#dfffea; line-height:1.45; }}
.bar-row {{ display:grid; grid-template-columns: 170px 1fr 92px; align-items:center; gap:10px; margin:11px 0; }}
.bar-label {{ color:#dcebf3; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.bar-track {{ height:12px; background:#092033; border-radius:999px; overflow:hidden; border:1px solid #183a52; }}
.bar-fill {{ height:100%; border-radius:999px; background:linear-gradient(90deg,var(--green),var(--teal),var(--blue)); box-shadow:0 0 18px rgba(80,255,138,.25); }}
.bar-value {{ font-size:12px; color:var(--muted); text-align:right; }}
.bar-value strong {{ display:block; color:var(--text); font-size:13px; }}
.funnel {{ display:grid; grid-template-columns: repeat(5, 1fr); gap:10px; margin-top:10px; }}
.stage-box {{ background:#081d2d; border:1px solid var(--line); border-radius:16px; padding:14px; min-height:120px; }}
.stage-box .name {{ color:#cfe6f2; font-weight:800; font-size:13px; min-height:34px; }}
.stage-box .amt {{ font-size:24px; font-weight:900; margin-top:10px; }}
.stage-box .cnt {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.filters {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }}
.filters span {{ background:#071c2c; border:1px solid var(--line); color:#bdd0dc; border-radius:999px; padding:7px 10px; font-size:11px; }}
.table-wrap {{ overflow:auto; border:1px solid var(--line); border-radius:18px; max-height:760px; }}
table {{ border-collapse:collapse; width:100%; min-width:1300px; background:#071a29; }}
th,td {{ padding:11px 12px; border-bottom:1px solid #14364f; text-align:left; vertical-align:top; font-size:12px; }}
th {{ position:sticky; top:0; background:#0c263a; color:#b9d2e0; z-index:2; text-transform:uppercase; letter-spacing:.06em; font-size:11px; }}
.subtle {{ color:var(--muted); font-size:11px; margin-top:3px; }}
.pill {{ display:inline-flex; border-radius:999px; padding:5px 8px; font-size:11px; font-weight:800; background:#17334a; color:#d9f1ff; white-space:nowrap; }}
.stage-closed-won {{ background:rgba(80,255,138,.14); color:var(--green); }}
.stage-closed-lost {{ background:rgba(255,93,116,.16); color:#ff9bad; }}
.muted {{ color:var(--muted); }}
.feature-list {{ display:flex; flex-wrap:wrap; gap:8px; }}
.feature-list span {{ border:1px solid #35536b; background:#0b2032; border-radius:999px; padding:8px 10px; color:#d9eaf2; font-size:12px; }}
.loss-group {{ border:1px solid #21445d; border-radius:18px; background:#081d2d; margin:14px 0; overflow:hidden; }}
.loss-group-head {{ display:flex; justify-content:space-between; gap:18px; padding:14px 16px; background:linear-gradient(90deg,rgba(255,93,116,.14),rgba(85,184,255,.06)); color:#f4fbff; align-items:center; }}
.loss-group-head span {{ display:block; color:var(--muted); font-size:12px; margin-top:3px; }}
.lost-card {{ padding:14px 16px; border-top:1px solid #173950; }}
.lost-title {{ display:flex; justify-content:space-between; gap:16px; font-weight:900; }}
.lost-title span {{ color:var(--gold); }}
.lost-meta {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.lost-reason {{ color:#ffe2e7; font-size:13px; margin-top:9px; }}
.lost-detail {{ color:#dcebf3; font-size:13px; line-height:1.45; margin-top:7px; }}
@media (max-width:1100px) {{ .metrics {{ grid-template-columns:repeat(2,1fr); }} .grid,.grid.two {{ grid-template-columns:1fr; }} .hero {{ flex-direction:column; }} .source {{ text-align:left; }} .funnel {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="wrapper">
  <section class="hero">
    <div>
      <div class="eyebrow">Rev.io Sales • Q3 2026 ICP Pipeline</div>
      <h1>ICP pipeline is thin, heavily early-stage, and loss-heavy.</h1>
      <div class="lede">Detailed analysis of the Salesforce “ICP Pipeline” report: New Deal PSA / PSA Web opportunities, MSP/Integrator vertical filter, MSP UCaaS/VoIP + MSP No Voice industries, and accounts with 10+ employees. Built straight from report <a href="{REPORT_URL}" target="_blank">{REPORT_ID}</a>.</div>
    </div>
    <div class="source">
      Generated {escape(summary['generated_at_et'])}<br>
      Source report: <a href="{REPORT_URL}" target="_blank">ICP Pipeline</a><br>
      <span>{summary['total_count']} detailed rows • {money(summary['total_amount'])} total report amount</span>
    </div>
  </section>

  <section class="metrics">
    {metric('Total ICP opps', f"{summary['total_count']:,}", f"{money(summary['total_amount'])} total amount")}
    {metric('Open ICP pipeline', money(summary['open_amount']), f"{summary['open_count']} active opps")}
    {metric('Closed won', money(summary['won_amount']), f"{summary['won_count']} won • {summary['win_rate_count']:.0f}% count win rate")}
    {metric('Closed lost', money(summary['lost_amount']), f"{summary['lost_count']} lost • {summary['win_rate_amount']:.0f}% amount win rate")}
    {metric('Avg / median age', f"{summary['avg_age']:.0f} / {summary['median_age']:.0f}d", 'All report rows')}
    {metric('Largest open owner', escape(biggest_open_owner['label']), f"{money(biggest_open_owner['amount'])} • {biggest_open_owner['count']} opps")}
  </section>

  <section class="grid">
    <div class="card">
      <h2>Stage funnel</h2>
      <div class="funnel">
        {''.join(f'''<div class="stage-box"><div class="name">{escape(x['label'])}</div><div class="amt">{money(x['amount'])}</div><div class="cnt">{x['count']} opps</div></div>''' for x in summary['stage'])}
      </div>
      <h3>Open-stage amount</h3>
      {css_bar(summary['open_stage'])}
    </div>
    <div class="card">
      <h2>Executive readout</h2>
      <div class="callout">
        Open Q3 ICP pipeline is <b>{money(open_gap)}</b> across <b>{summary['open_count']} active opps</b>, while closed decisions already total <b>{money(closed_decision_amount)}</b>. Closed-lost outweighs closed-won by <b>{money(summary['lost_amount'] - summary['won_amount'])}</b>, so the dashboard should be used less as “how much pipeline exists?” and more as “where is ICP conversion breaking?” — tiny sample size, big Bat-Signal.
      </div>
      <h3>Owner concentration</h3>
      {css_bar(summary['open_owner'])}
    </div>
    <div class="card">
      <h2>PSA platform mix</h2>
      <div class="callout">Top platform by total amount: <b>{escape(biggest_platform['label'])}</b> with <b>{money(biggest_platform['amount'])}</b> across <b>{biggest_platform['count']}</b> opps.</div>
      <h3>All rows by platform</h3>
      {css_bar(summary['platform'])}
    </div>
  </section>

  <section class="card" style="margin-top:18px;">
    <h2>Opportunity stage breakdown</h2>
    <div class="table-wrap" style="max-height:none;"><table style="min-width:900px;">
      <thead><tr><th>Stage</th><th>Opps</th><th>Amount</th><th>% of $</th><th>Top owner</th><th>Top PSA platform</th><th>Avg age</th></tr></thead>
      <tbody>{render_stage_breakdown(summary)}</tbody>
    </table></div>
  </section>

  <section class="grid two">
    <div class="card"><h2>Industry split</h2>{css_bar(summary['industry'])}</div>
    <div class="card"><h2>Employee-size bands</h2>{css_bar(summary['employee_bucket'])}</div>
  </section>

  <section class="grid two">
    <div class="card"><h2>Closed-lost reasons</h2>{css_bar(summary['loss_reason'])}</div>
    <div class="card"><h2>Closed-lost themes</h2>{css_bar(summary['loss_theme'])}</div>
  </section>

  <section class="card" style="margin-top:18px;">
    <h2>Closed-lost deep dive: reason lost detail + loss reason</h2>
    <div class="callout">Grouped by inferred theme from the actual Loss Reason and Reason Lost Detail fields. This separates “real product gap” losses from no-shows, weak pain, timing, contract lock-in, and ICP fit issues — because throwing all red dots into one bucket is how dashboards become expensive wallpaper.</div>
    {render_closed_lost_deep_dive(summary)}
  </section>

  <section class="grid two">
    <div class="card"><h2>Missing features captured</h2><div class="feature-list">{''.join(f'<span>{escape(x["label"])} × {x["count"]}</span>' for x in summary['missing_features']) or '<span>No missing features captured in report rows</span>'}</div></div>
    <div class="card"><h2>Loss reason by amount</h2>{css_bar(summary['loss_reason'])}</div>
  </section>

  <section class="card">
    <h2>Report filters applied</h2>
    <div class="filters">{filters_html}</div>
  </section>

  <section class="card" style="margin-top:18px;">
    <h2>Opportunity detail</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Stage</th><th>Opportunity / Account</th><th>Owner</th><th>PSA</th><th>Emp.</th><th>Amount</th><th>Close</th><th>Age</th><th>Next Step / Loss Detail</th><th>Features / Loss Reason</th></tr></thead>
      <tbody>{render_table(rows)}</tbody>
    </table></div>
  </section>
</div>
</body>
</html>'''
    HTML_FILE.write_text(html, encoding='utf-8')


def update_library():
    entry = '- Q3 ICP Pipeline Analysis — detailed Salesforce ICP pipeline dashboard: stage funnel, owner/platform/industry splits, size bands, closed-lost analysis, and opportunity detail. URL: https://koontz-robin.github.io/robin-decks/q3-icp-pipeline-analysis.html\n'
    text = LIBRARY_FILE.read_text(encoding='utf-8') if LIBRARY_FILE.exists() else '# Decks Library\n\n'
    if 'q3-icp-pipeline-analysis.html' not in text:
        marker = '## Dashboards\n'
        if marker in text:
            text = text.replace(marker, marker + entry, 1)
        else:
            text += '\n' + entry
        LIBRARY_FILE.write_text(text, encoding='utf-8')


def publish(files):
    subprocess.run(['git', 'fetch', 'robin-decks', 'master'], cwd=WORKSPACE, check=True)
    tmp_parent = Path(tempfile.mkdtemp(prefix='q3-icp-publish.'))
    worktree = tmp_parent / 'worktree'
    try:
        subprocess.run(['git', 'worktree', 'add', str(worktree), 'robin-decks/master'], cwd=WORKSPACE, check=True)
        for path in files:
            shutil.copy2(path, worktree / path.name)
        subprocess.run(['git', 'config', 'user.name', 'Robin'], cwd=worktree, check=True)
        subprocess.run(['git', 'config', 'user.email', 'robin.bot@rev.io'], cwd=worktree, check=True)
        subprocess.run(['git', 'add', *[p.name for p in files]], cwd=worktree, check=True)
        diff = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=worktree)
        if diff.returncode == 0:
            print('No publish changes.')
            return
        stamp = datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')
        subprocess.run(['git', 'commit', '-m', f'add q3 icp pipeline analysis dashboard ({stamp})'], cwd=worktree, check=True)
        subprocess.run(['git', 'push', 'robin-decks', 'HEAD:master'], cwd=worktree, check=True)
    finally:
        subprocess.run(['git', 'worktree', 'remove', '--force', str(worktree)], cwd=WORKSPACE, check=False)
        shutil.rmtree(tmp_parent, ignore_errors=True)


def main():
    print('Authenticating to Salesforce...')
    base, headers = sf_auth()
    print('Fetching ICP Pipeline report...')
    report = fetch_report(base, headers)
    rows, detail_columns, column_info = parse_report(report)
    rows = enrich_from_opportunities(base, headers, rows)
    summary = summarize(rows, report)
    payload = {'summary': summary, 'rows': rows, 'detail_columns': detail_columns, 'column_info': column_info}
    DATA_FILE.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    build_html(rows, summary)
    update_library()
    print(f'Built {HTML_FILE.name} with {len(rows)} rows / {money(summary["total_amount"])}')
    if os.environ.get('NO_PUBLISH') == '1':
        print('NO_PUBLISH=1; skipping publish')
    else:
        publish([HTML_FILE, DATA_FILE, LIBRARY_FILE, Path(__file__)])
        print(f'Published https://koontz-robin.github.io/robin-decks/{HTML_FILE.name}')


if __name__ == '__main__':
    main()
