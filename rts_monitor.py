#!/usr/bin/env python3
"""
rts_monitor.py
==============
Monitor the Rev.io PSA Clients Notion DB for clients entering RTS (Ready to Sign / Return to Sales) status.
When new RTS clients are detected (not previously alerted), post to Discord #rts-updates channel.

Runs every 30 min via cron. State is persisted in memory/rts_state.json.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
NOTION_TOKEN     = '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'
NOTION_DB_ID     = 'dba0a0aa-c29e-42d7-ac7e-968e0245f4c4'
WORKSPACE        = '/home/openclaw/.openclaw/workspace'
STATE_FILE       = f'{WORKSPACE}/memory/rts_state.json'
DISCORD_CHANNEL  = '1490762537648787507'  # #rts-updates in Rev.io Sales Leadership server
OPENCLAW_CONFIG  = os.path.expanduser('~/.openclaw/openclaw.json')

# Notion API version
NOTION_API_VER   = '2022-06-28'
NOTION_BASE      = 'https://api.notion.com/v1'
DISCORD_API_BASE = 'https://discord.com/api/v10'

# RTS status values to monitor
RTS_STATUSES = [
    'RTS - Business',
    'RTS - Client',
    'RTS - Client Bandwidth',
    'RTS - Functionality',
    'RTS - Ghosting',
]

# Status → emoji mapping
STATUS_EMOJI = {
    'RTS - Business':         '💼',
    'RTS - Client':           '👤',
    'RTS - Client Bandwidth': '⏰',
    'RTS - Functionality':    '🔧',
    'RTS - Ghosting':         '👻',
}

# ── Discord API ───────────────────────────────────────────────────────────────
_DISCORD_TOKEN = None

def _get_discord_token() -> str:
    global _DISCORD_TOKEN
    if _DISCORD_TOKEN:
        return _DISCORD_TOKEN
    with open(OPENCLAW_CONFIG) as f:
        cfg = json.load(f)
    _DISCORD_TOKEN = cfg['channels']['discord']['token']
    return _DISCORD_TOKEN


def send_discord_message(channel_id: str, text: str) -> bool:
    """Post a message to Discord directly via the Discord API."""
    token = _get_discord_token()
    url   = f'{DISCORD_API_BASE}/channels/{channel_id}/messages'
    payload = json.dumps({'content': text}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Authorization': f'Bot {token}',
            'Content-Type': 'application/json',
            'User-Agent': 'DiscordBot (https://github.com/koontz-robin/robin-bot, 1.0)',
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f'[discord] Error sending message: {e}')
        return False


# ── Notion helpers ────────────────────────────────────────────────────────────
def notion_request(method: str, path: str, body=None) -> dict:
    url = f'{NOTION_BASE}/{path}'
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Authorization': f'Bearer {NOTION_TOKEN}',
            'Notion-Version': NOTION_API_VER,
            'Content-Type': 'application/json',
        },
        method=method
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def get_rts_clients() -> list:
    """Query Notion for all clients in RTS status."""
    or_filters = [
        {'property': 'Status', 'status': {'equals': s}}
        for s in RTS_STATUSES
    ]
    body = {
        'filter': {'or': or_filters},
        'page_size': 100,
    }

    results = []
    has_more = True
    cursor = None
    while has_more:
        if cursor:
            body['start_cursor'] = cursor
        data = notion_request('POST', f'databases/{NOTION_DB_ID}/query', body)
        results.extend(data.get('results', []))
        has_more = data.get('has_more', False)
        cursor = data.get('next_cursor')

    return results


def parse_client(page: dict) -> dict:
    props = page['properties']

    name_parts = props.get('Client', {}).get('title', [])
    name = name_parts[0].get('plain_text', 'Unknown') if name_parts else 'Unknown'

    status_obj = props.get('Status', {}).get('status', {})
    status = status_obj.get('name', 'Unknown') if status_obj else 'Unknown'

    rts_start_obj = props.get('RTSStart', {}).get('date', {})
    rts_start = None
    if rts_start_obj:
        rts_start = rts_start_obj.get('start')

    sa_obj = props.get('Solutions Analyst', {}).get('select', {})
    solutions_analyst = sa_obj.get('name', '') if sa_obj else ''

    # Owner (people field)
    owner_list = props.get('Owner', {}).get('people', [])
    owner = owner_list[0].get('name', '') if owner_list else ''

    display_owner = solutions_analyst or owner or 'Unknown'

    rts_notes_parts = props.get('RTS Notes', {}).get('rich_text', [])
    rts_notes = rts_notes_parts[0].get('plain_text', '') if rts_notes_parts else ''

    return {
        'id': page['id'],
        'name': name,
        'status': status,
        'rts_start': rts_start,
        'owner': display_owner,
        'rts_notes': rts_notes,
        'page_url': page.get('url', ''),
    }


def format_rts_date(iso_str: str) -> str:
    """Format ISO datetime to 'Mon DD, YYYY'."""
    if not iso_str:
        return 'Unknown'
    try:
        # Handle timezone offset in string
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime('%b %-d, %Y')
    except Exception:
        return iso_str[:10]


def format_alert(client: dict) -> str:
    emoji = STATUS_EMOJI.get(client['status'], '🚨')
    date_str = format_rts_date(client['rts_start'])
    msg = (
        f"{emoji} **New RTS Client: {client['name']}**\n"
        f"Status: {client['status']}\n"
        f"Owner: {client['owner']} · RTS Since: {date_str}"
    )
    if client['rts_notes']:
        truncated = client['rts_notes'][:120]
        if len(client['rts_notes']) > 120:
            truncated += '…'
        msg += f"\nNotes: {truncated}"
    return msg


# ── State management ──────────────────────────────────────────────────────────
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'alerted_ids': {}, 'last_run': None, 'current_rts_count': 0}


def save_state(state: dict):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f'[rts_monitor] Starting — {datetime.now(timezone.utc).isoformat()}')

    state = load_state()
    alerted_ids = state.get('alerted_ids', {})

    # Fetch current RTS clients from Notion
    pages = get_rts_clients()
    clients = [parse_client(p) for p in pages]
    print(f'[rts_monitor] {len(clients)} RTS clients in Notion')

    # Find new ones
    new_clients = [c for c in clients if c['id'] not in alerted_ids]
    print(f'[rts_monitor] {len(new_clients)} new (not yet alerted)')

    # Alert each new client
    alerted_count = 0
    for client in new_clients:
        msg = format_alert(client)
        print(f'[rts_monitor] Alerting: {client["name"]} ({client["status"]})')
        ok = send_discord_message(DISCORD_CHANNEL, msg)
        if ok:
            alerted_ids[client['id']] = datetime.now(timezone.utc).isoformat()
            alerted_count += 1
            print(f'[rts_monitor] ✓ Sent alert for {client["name"]}')
        else:
            print(f'[rts_monitor] ✗ Failed to send alert for {client["name"]}')

    # Update state
    state['alerted_ids'] = alerted_ids
    state['last_run'] = datetime.now(timezone.utc).isoformat()
    state['current_rts_count'] = len(clients)
    save_state(state)

    print(f'[rts_monitor] Done. {alerted_count} new alerts sent. Total RTS: {len(clients)}')


if __name__ == '__main__':
    main()
