#!/usr/bin/env python3
import ast, json, re, time, html, subprocess, os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import requests

ROOT = Path('/home/openclaw/.openclaw/workspace')
OUT_JSON = ROOT / 'tigerpaw_migration_interest_from_notion.json'
OUT_CSV = ROOT / 'tigerpaw_migration_interest_from_notion.csv'
OUT_HTML = ROOT / 'tigerpaw-migration-interest.html'
NOTION_DB_ID = '2aea59b7e7b2808fb396e0da46e7029b'
NOTION_VERSION = '2022-06-28'
TOKEN_SOURCE = ROOT / 'fetch_notion_coaching_v2.py'

ACCOUNT_NAMES = '''Favorite Office Automation
Phone & Data Works
Bri-Tech Inc.
Tele Link Communications
Sky Communications, Inc.
BlueWire Communications
E Z Tel Inc
David Carroll Associates, Inc.
Paramount Security Partners, LLC
Communication Innovators
Communication Resources
TIPS Resources
Empire Communication Systems Inc
North American Telecommunications Group
Accent Voice
M D Communications
Digitel Systems Inc.
Memory Lane Computers
MicroMed
Raytec Systems
Madrona Digital
MPS Works
streamWrite Connect
E & H Integrated Systems
Strategic Communications, LLC
Eastern DataComm
Watson Communications Corp.
Network Datacom Solutions
Tri-Tec Communications
Peak Communication
American Business Phones
Techoptics, Inc
Rel Comm
Richmond Security
Omidi Enterprises
Ameritel Voice and Data
BCS Voice and Data
Doing Things Simply
The Phone Experts - Communications Ltd.
Triware Technologies Incorporated
Datapro Solutions
Tele-Plus Corporation
Communication Service Solutions
Professional Security Innovations
Dividia
Carrier SI
MAPS Security
Environmental & Safety Support
Tidal Communications LLC
Telephone Communications Inc
Brothers Lazer Svc
Telewire Inc.
Dominion Design & Integration
A-Z Printers Plus
TRM
IntelesysOne
Area Wide Communications, LLC
TDS-Phone
ASAP Security Services
Teleco Wilmington
Peerless Energy Systems
Parallel Synergistic Consulting
Hardwire Telecom
Augusta Communications
America's Phone Guys
Metropolitan Telephone
AVSi
IET Labs (3rd DB)
Xpedient Communications
Digital Telecommunications
Moseley Electronics, LLC
Harris Computer
Phones Plus.biz, Inc.
New England Communications
Voxcom Solutions Inc
Genie Innovations, Inc.
Audio-Video Corporation
Commercial Refrigeration Systems, Inc.
Unique Communications
Telecom Unlimited
Valley Lock & Security
Mid South Telecom Inc
Chortek
MAC'S HEATING LTD.
B. Moyer Radio Communications LLC
Technology System Consultants
Grennan Communications
Computer World Inc
IMC Facility Management
Thomas Electronics Inc
Accurate Security Pros, Inc.
United Security Communications, Inc.
Nutec Systems, Inc
Infrastructure Technology Solutions'''.splitlines()

ACCOUNT_NAMES = list(dict.fromkeys([x.strip() for x in ACCOUNT_NAMES if x.strip()]))


def load_token():
    tree = ast.parse(TOKEN_SOURCE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'NOTION_TOKEN':
                    return ast.literal_eval(node.value)
    raise RuntimeError('NOTION_TOKEN not found')

TOKEN = load_token()
HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Notion-Version': NOTION_VERSION, 'Content-Type': 'application/json'}


def request(method, url, **kwargs):
    for attempt in range(5):
        r = requests.request(method, url, headers=HEADERS, timeout=60, **kwargs)
        if r.status_code == 429:
            time.sleep(float(r.headers.get('Retry-After', '1')) + 0.25)
            continue
        if 500 <= r.status_code < 600:
            time.sleep(1 + attempt)
            continue
        if not r.ok:
            raise RuntimeError(f'{method} {url} -> {r.status_code}: {r.text[:500]}')
        return r.json()
    raise RuntimeError(f'{method} {url} failed after retries')


def rich(items):
    return ''.join(i.get('plain_text','') for i in (items or []))


def prop_text(prop):
    if not prop: return ''
    typ = prop.get('type')
    val = prop.get(typ)
    if typ == 'title': return rich(val)
    if typ == 'rich_text': return rich(val)
    if typ == 'select': return (val or {}).get('name','')
    if typ == 'status': return (val or {}).get('name','')
    if typ == 'multi_select': return ', '.join(x.get('name','') for x in val or [])
    if typ == 'people': return ', '.join(x.get('name','') for x in val or [])
    if typ == 'date': return (val or {}).get('start','')
    if typ == 'url': return val or ''
    return ''


def norm(s):
    s = s.lower().replace('&',' and ')
    s = re.sub(r'\b(incorporated|inc|llc|ltd|limited|corp|corporation|company|communications|communication|systems|system|technologies|technology|services|service)\b', ' ', s)
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def name_match(account, title):
    a = norm(account); t = norm(title)
    if not a or not t:
        return False
    # Exact-ish normalized containment only when the account string is substantive.
    if len(a) >= 5 and re.search(r'(^| )' + re.escape(a) + r'($| )', t):
        return True
    # Avoid reverse containment like account "Professional Security Innovations" matching title "f".
    stop = {
        'and','the','of','inc','llc','ltd','corp','corporation','company','co','communications','communication',
        'systems','system','technologies','technology','services','service','solutions','consulting','security',
        'voice','data','phone','telecom','telephone','integrated','integration','group'
    }
    toks = [x for x in a.split() if len(x) > 2 and x not in stop]
    tt = set(t.split())
    if not toks:
        return False
    if len(toks) == 1:
        return toks[0] in tt
    # Require the leading distinctive token plus at least one other distinctive token.
    return toks[0] in tt and sum(1 for x in toks if x in tt) >= 2


def fetch_pages():
    pages=[]; cursor=None
    while True:
        body={'page_size':100}
        if cursor: body['start_cursor']=cursor
        data=request('POST', f'https://api.notion.com/v1/databases/{NOTION_DB_ID}/query', json=body)
        pages.extend(data.get('results',[]))
        if not data.get('has_more'): return pages
        cursor=data.get('next_cursor')


def block_text(block):
    typ = block.get('type')
    val = block.get(typ) or {}
    parts=[]
    for key in ('rich_text','caption'):
        if key in val: parts.append(rich(val.get(key)))
    if typ == 'child_database': parts.append(val.get('title',''))
    if typ == 'child_page': parts.append(val.get('title',''))
    return '\n'.join(p for p in parts if p)


def fetch_block_children(block_id, depth=0, max_blocks=120):
    # Bounded pull: enough for notes/summary/transcript signals without getting stuck in giant nested transcripts.
    if depth > 1:
        return ''
    out=[]; cursor=None; seen=0
    while seen < max_blocks:
        url=f'https://api.notion.com/v1/blocks/{block_id}/children?page_size=100'
        if cursor: url += f'&start_cursor={cursor}'
        data=request('GET', url)
        for b in data.get('results',[]):
            seen += 1
            txt=block_text(b)
            if txt: out.append(txt)
            if b.get('has_children') and seen < max_blocks:
                out.append(fetch_block_children(b['id'], depth+1, max_blocks=40))
            if seen >= max_blocks:
                break
        if not data.get('has_more') or seen >= max_blocks: break
        cursor=data.get('next_cursor')
    return '\n'.join(x for x in out if x)


def parse_dt(s):
    if not s: return ''
    try: return datetime.fromisoformat(s.replace('Z','+00:00'))
    except Exception: return ''


def classify(text, sf_status=''):
    t = re.sub(r'\s+', ' ', (text or '')).lower()
    # strongest negatives first
    neg_patterns = [
        r'\bdo(?:es)? not want to migrate\b', r'\bnot interested\b', r'\bno interest\b',
        r'\bdoesn[’\']?t want to migrate\b', r'\bdon[’\']?t want to migrate\b',
        r'\bdeclined\b.*\bmigrat', r'\bstay(?:ing)? on (?:tigerpaw|unleashed|current)',
        r'\bno plan(?:s)? to migrate\b', r'\bnot looking to migrate\b', r'\bdo not migrate\b'
    ]
    if any(re.search(p, t) for p in neg_patterns):
        return 'do not want to migrate', 'negative language in latest CBR/notes'
    asap_patterns = [
        r'\bwant(?:s)? to migrate asap\b', r'\basap\b.{0,80}\bmigrat', r'\bmigrat.{0,80}\basap\b',
        r'\bas soon as possible\b.{0,80}\bmigrat', r'\bmigrat.{0,80}\bas soon as possible\b',
        r'\bready to migrate\b', r'\bmigration pending\b', r'\bstart migration\b',
        r'\bmove forward\b.{0,80}\bmigrat', r'\bpriority\b.{0,80}\bmigrat',
        r'\bimmediate\b.{0,80}\bmigrat'
    ]
    if any(re.search(p, t) for p in asap_patterns):
        return 'want to migrate asap', 'urgent/ready language in latest CBR/notes'
    want_patterns = [
        r'\bwant(?:s)? to migrate\b', r'\binterested in migrat', r'\bopen to migrat',
        r'\bplan(?:s|ning)? to migrate\b', r'\bmigration demo\b', r'\bmigration plan\b',
        r'\brevio migration\b', r'\bnew platform demo\b', r'\bdiscuss(?:ed)? .*migrat',
        r'\breview .*migrat', r'\bschedule(?:d)? .*demo\b', r'\bdemo .*new rev\.io platform\b'
    ]
    if any(re.search(p, t) for p in want_patterns):
        return 'want to migrate / timeline unknown', 'migration interest or demo language; no firm urgent timeline'
    # SF status direct if present in text/status. Check negatives before "want to migrate"
    # because statuses like "Do not want to migrate" contain that substring. Tiny goblin, sharp teeth.
    s=(sf_status or '').lower()
    if 'do not' in s or 'not want' in s: return 'do not want to migrate', 'Salesforce web migration status'
    if 'asap' in s: return 'want to migrate asap', 'Salesforce web migration status'
    if 'want to migrate' in s: return 'want to migrate / timeline unknown', 'Salesforce web migration status'
    return 'unknown / needs review', 'no clear migration-intent signal found'


def excerpt_for(text):
    t = re.sub(r'\s+', ' ', text or '').strip()
    idxs=[]
    for kw in ['migrat', 'new platform', 'demo', 'asap', 'not interested', 'no interest', 'tigerpaw']:
        i=t.lower().find(kw)
        if i>=0: idxs.append(i)
    i=min(idxs) if idxs else 0
    start=max(0,i-90); end=min(len(t),i+210)
    return (('…' if start else '') + t[start:end] + ('…' if end < len(t) else ''))[:360]


def get_sf_account_data():
    import sys
    sys.path.insert(0, str(ROOT))
    from build_forecast_targets import sf_auth, sf_query
    base,h=sf_auth()
    mapping={}
    for i in range(0,len(ACCOUNT_NAMES),80):
        vals=','.join("'"+n.replace("'","\\'")+"'" for n in ACCOUNT_NAMES[i:i+80])
        q=f"SELECT Name, TigerPaw_Account_Status__c, Web_Migration__c, Web_Migration_Status_Details__c FROM Account WHERE Name IN ({vals})"
        for r in sf_query(base,h,q):
            mapping[r['Name']]={
                'psa_account_status':r.get('TigerPaw_Account_Status__c') or '',
                'web_migration':r.get('Web_Migration__c') or '',
                'web_details':r.get('Web_Migration_Status_Details__c') or ''
            }
    return mapping


def infer_tigerpaw_status(text, sf_psa_status=''):
    """Infer Tigerpaw hosting/on-prem status from Notion text; use SF PSA Account Status as fallback."""
    t = re.sub(r'\s+', ' ', (text or '')).lower()
    one_patterns = [
        r'\btigerpaw one\b', r'\btp one\b', r'\bon[- ]?prem(?:ise|ises)?\b',
        r'\bon prem\b', r'\bself[- ]?hosted\b', r'\blocal server\b', r'\bserver[- ]based\b'
    ]
    unleashed_patterns = [
        r'\bunleashed\b', r'\bhosted version\b', r'\bhosted tigerpaw\b',
        r'\btigerpaw hosted\b', r'\bcloud hosted\b', r'\bcloud version\b'
    ]
    one = any(re.search(p, t) for p in one_patterns)
    unleashed = any(re.search(p, t) for p in unleashed_patterns)
    if one and not unleashed:
        return 'Active - Tigerpaw One', 'Notion notes indicate on-prem / Tigerpaw One'
    if unleashed and not one:
        return 'Active - Unleashed', 'Notion notes indicate hosted / Unleashed'
    s = sf_psa_status or ''
    if s in ('Active - Tigerpaw One', 'Active - Unleashed'):
        return s, 'Salesforce PSA Account Status fallback'
    return s or 'Unknown', 'No clear hosting signal in latest Notion notes'


def main():
    pages=fetch_pages()
    meta=[]
    for p in pages:
        props=p['properties']
        title=prop_text(props.get('Meeting Series'))
        stage=prop_text(props.get('Stage'))
        owner=prop_text(props.get('Owner'))
        summary=prop_text(props.get('Last Meeting Summary'))
        product=prop_text(props.get('Product Line'))
        date=prop_text(props.get('Series Start Date')) or p.get('created_time','')
        meta.append({'id':p['id'],'url':p.get('url',''),'title':title,'stage':stage,'owner':owner,'summary':summary,'product':product,'date':date,'last_edited':p.get('last_edited_time','')})
    sf_web=get_sf_account_data()
    rows=[]
    body_cache={}
    for acct in ACCOUNT_NAMES:
        matches=[m for m in meta if name_match(acct, m['title'])]
        # Prefer CBR/client business review records; otherwise latest matched customer record.
        cbr=[m for m in matches if re.search(r'\b(cbr|client business review)\b', m['title']+' '+m['summary'], re.I)]
        candidates=cbr or matches
        candidates.sort(key=lambda m: parse_dt(m['date']) or parse_dt(m['last_edited']) or datetime.min, reverse=True)
        chosen=candidates[0] if candidates else None
        full=''
        interest_text=''
        if chosen:
            page_body = body_cache.get(chosen['id'])
            if page_body is None:
                page_body = fetch_block_children(chosen['id'])
                body_cache[chosen['id']] = page_body
            # Use concise Notion metadata for migration intent. Full page bodies often include reusable
            # agenda/prompt templates that mention migration/demo generically and create false positives.
            interest_text='\n'.join([chosen.get('title',''), chosen.get('summary',''), chosen.get('product','')])
            # Use full body only for deployment/hosting inference, where on-prem/Unleashed mentions may live in notes.
            full='\n'.join([interest_text, page_body])
        sf=sf_web.get(acct,{})
        # add sf migration status as fallback/context only, notion text dominates if any signal.
        status, reason=classify(interest_text, sf.get('web_migration',''))
        inferred_psa_status, inferred_psa_reason = infer_tigerpaw_status(full, sf.get('psa_account_status',''))
        rows.append({
            'account': acct,
            'migration_interest': status,
            'reason': reason,
            'latest_notion_record': chosen['title'] if chosen else '',
            'record_date': (chosen or {}).get('date',''),
            'notion_stage': (chosen or {}).get('stage',''),
            'owner': (chosen or {}).get('owner',''),
            'notion_url': (chosen or {}).get('url',''),
            'evidence': excerpt_for(full) if full else '',
            'psa_account_status': sf.get('psa_account_status',''),
            'notion_inferred_tigerpaw_status': inferred_psa_status,
            'notion_inferred_tigerpaw_reason': inferred_psa_reason,
            'sf_web_migration_status': sf.get('web_migration',''),
            'sf_web_migration_details': sf.get('web_details',''),
            'matched_records': len(matches),
            'used_cbr_record': bool(cbr),
        })
    OUT_JSON.write_text(json.dumps(rows, indent=2), encoding='utf-8')
    import csv
    with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    counts=defaultdict(int)
    for r in rows: counts[r['migration_interest']]+=1
    generated=datetime.now().strftime('%Y-%m-%d %H:%M')
    def esc(x): return html.escape(str(x or ''))
    table=''.join(
        f"<tr class='{esc(r['migration_interest'].split()[0])}'><td>{esc(r['account'])}</td><td><strong>{esc(r['migration_interest'])}</strong></td><td>{esc(r['latest_notion_record'])}</td><td>{esc(r['record_date'][:10])}</td><td>{esc(r['notion_stage'])}</td><td>{esc(r['owner'])}</td><td>{esc(r['psa_account_status'])}</td><td>{esc(r['notion_inferred_tigerpaw_status'])}<br><small>{esc(r['notion_inferred_tigerpaw_reason'])}</small></td><td>{esc(r['evidence'])}</td><td>{('<a href='+esc(r['notion_url'])+' target=_blank>Open</a>') if r['notion_url'] else '—'}</td><td>{esc(r['sf_web_migration_status'])}</td></tr>"
        for r in rows
    )
    cards=''.join(f"<div class='card'><div>{esc(k)}</div><b>{v}</b></div>" for k,v in sorted(counts.items()))
    OUT_HTML.write_text(f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Tigerpaw Migration Interest</title><style>
    body{{margin:0;font-family:Inter,Arial,sans-serif;background:#071322;color:#eaf4ff}} .wrap{{padding:28px;max-width:1600px;margin:auto}} h1{{margin:0 0 8px;font-size:30px}} .sub{{color:#9fb4c8;margin-bottom:20px}} .cards{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}} .card{{background:#0d2036;border:1px solid #1e3c5d;border-radius:14px;padding:14px 18px;min-width:190px;color:#9fb4c8}} .card b{{display:block;color:#50ff8a;font-size:28px;margin-top:6px}} table{{border-collapse:separate;border-spacing:0;width:100%;background:#081a2c;border:1px solid #1e3c5d;border-radius:16px;overflow:hidden}} th,td{{padding:10px 12px;border-bottom:1px solid #17324f;text-align:left;vertical-align:top;font-size:13px}} th{{position:sticky;top:0;background:#102640;color:#bfe6ff;z-index:1}} tr:hover{{background:#0e2540}} a{{color:#50ff8a}} strong{{color:#fff}} .note{{background:#102640;border-left:4px solid #50ff8a;padding:12px 14px;border-radius:8px;margin:14px 0;color:#cbd8e6}} .unknown strong{{color:#fbbf24}}
    </style></head><body><div class='wrap'><h1>Tigerpaw → Rev.io PSA Migration Interest</h1><div class='sub'>Generated {generated}. Source: 94 Salesforce accounts with non-blank PSA Account Status, cross-referenced to Notion Sales Meetings by customer name. CBR records preferred when present; otherwise latest matched meeting record used.</div><div class='cards'>{cards}</div><div class='note'>Classification buckets requested: want to migrate asap, want to migrate / timeline unknown, do not want to migrate. “Unknown / needs review” means I found the account but the latest Notion text did not clearly say one of those three things.</div><table><thead><tr><th>Account</th><th>Migration interest</th><th>Latest Notion record used</th><th>Date</th><th>Stage</th><th>Owner</th><th>PSA Account Status</th><th>Inferred Tigerpaw Status</th><th>Evidence</th><th>Notion</th><th>SF Web Migration Status</th></tr></thead><tbody>{table}</tbody></table></div></body></html>""", encoding='utf-8')
    print(json.dumps({'rows':len(rows),'counts':dict(counts),'html':str(OUT_HTML),'csv':str(OUT_CSV)}, indent=2))

if __name__ == '__main__':
    main()
