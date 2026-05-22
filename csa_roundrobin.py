"""
csa_roundrobin.py — CSA Round Robin assignment monitor
Runs every 15 minutes via cron. Checks SF for new Closed Won opps, assigns CSAs
in round-robin order, and posts to #csa Discord channel directly via Discord API.
"""
import json, os, requests, urllib.request
from datetime import datetime, timezone

WORKSPACE       = '/home/openclaw/.openclaw/workspace'
STATE_FILE      = f'{WORKSPACE}/csa_rr_state.json'
DISCORD_CHANNEL = '1491795254104297732'  # #csa
OPENCLAW_CONFIG = os.path.expanduser('~/.openclaw/openclaw.json')
DISCORD_API_BASE = 'https://discord.com/api/v10'
CSA_ROTATION    = ['Ingrid', 'Justin']

SF_INSTANCE    = "https://rev-io.my.salesforce.com"
SF_CLIENT_ID   = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N"
SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E"

# ── State ─────────────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "last_checked_ids": [],
        "next_csa_index": 1,   # 0=Ingrid, 1=Justin — Justin is next after backfill
        "last_close_date": "2026-05-21"
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# ── Discord ───────────────────────────────────────────────────────────────────

def get_discord_token():
    with open(OPENCLAW_CONFIG) as f:
        cfg = json.load(f)
    return cfg['channels']['discord']['token']

def send_discord_message(text):
    token = get_discord_token()
    url   = f'{DISCORD_API_BASE}/channels/{DISCORD_CHANNEL}/messages'
    payload = json.dumps({'content': text}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={
            'Authorization': f'Bot {token}',
            'Content-Type': 'application/json',
            'User-Agent': 'DiscordBot (https://github.com/koontz-robin/robin-bot, 1.0)',
        },
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status in (200, 201)

# ── Salesforce ────────────────────────────────────────────────────────────────

def sf_auth():
    r = requests.post(f"{SF_INSTANCE}/services/oauth2/token", data={
        "grant_type": "client_credentials",
        "client_id": SF_CLIENT_ID,
        "client_secret": SF_CLIENT_SECRET,
    })
    r.raise_for_status()
    nt = r.json()
    return nt['instance_url'], {"Authorization": f"Bearer {nt['access_token']}"}

def fetch_new_closed_won(base, headers, since_date, known_ids):
    query = f"""
    SELECT Id, Name, StageName, Amount, CloseDate, Account.Name, Owner.Name, Product_Type__c, CreatedDate
    FROM Opportunity
    WHERE StageName = 'Closed Won'
      AND Type = 'New Opportunity'
      AND CloseDate >= {since_date}
    ORDER BY CloseDate ASC, CreatedDate ASC
    """
    resp = requests.get(f"{base}/services/data/v59.0/query", headers=headers, params={"q": query})
    resp.raise_for_status()
    data = resp.json()
    return [r for r in data.get('records', []) if r['Id'] not in known_ids]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    state = load_state()
    print(f"🔍 Checking SF for new Closed Won opps since {state['last_close_date']}...")

    base, headers = sf_auth()
    new_opps = fetch_new_closed_won(base, headers, state['last_close_date'], state['last_checked_ids'])

    if not new_opps:
        print("✅ No new Closed Won opps. Nothing to post.")
        return

    print(f"Found {len(new_opps)} new opp(s). Assigning CSAs...")

    for opp in new_opps:
        csa       = CSA_ROTATION[state['next_csa_index'] % len(CSA_ROTATION)]
        acct      = opp['Account']['Name']
        ae        = opp['Owner']['Name']
        close_date = opp['CloseDate']
        product   = opp.get('Product_Type__c') or 'N/A'
        amount    = opp.get('Amount') or 0

        msg = (
            f"🎉 **New Deal Closed — CSA Assigned**\n"
            f"📋 **Account:** {acct}\n"
            f"👤 **CSA:** {csa}\n"
            f"💼 **AE:** {ae}\n"
            f"📦 **Product:** {product}\n"
            f"💰 **Amount:** ${amount:,.0f}\n"
            f"📅 **Close Date:** {close_date}"
        )

        ok = send_discord_message(msg)
        if ok:
            print(f"✅ Posted: {acct} → {csa}")
        else:
            print(f"❌ Discord post failed for {acct}")

        state['last_checked_ids'].append(opp['Id'])
        state['next_csa_index'] = (state['next_csa_index'] + 1) % len(CSA_ROTATION)
        if opp['CloseDate'] > state['last_close_date']:
            state['last_close_date'] = opp['CloseDate']

    # Keep id list from growing unbounded
    state['last_checked_ids'] = state['last_checked_ids'][-500:]
    save_state(state)

    next_csa = CSA_ROTATION[state['next_csa_index'] % len(CSA_ROTATION)]
    print(f"✅ Done. Next up: {next_csa}")

if __name__ == '__main__':
    main()
