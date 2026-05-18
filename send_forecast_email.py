#!/usr/bin/env python3
"""
send_forecast_email.py — Refresh forecast and send to Evan, Brent, CC Ryan
Run by cron every Monday at 11 AM ET
"""
import json, requests, subprocess, sys, os

WORKSPACE = '/home/openclaw/.openclaw/workspace'
TOKEN_FILE = f'{WORKSPACE}/email-tokens.json'
TENANT = "ad233ca3-255e-4697-90c0-5bf96200d3ae"
APP_ID  = "0bda3b19-e713-4103-be0d-2bf057af5cba"
FORECAST_URL = "https://koontz-robin.github.io/robin-decks/forecast.html"

# ── Step 1: Refresh forecast ──────────────────────────────────────────────────
print("🔄 Refreshing forecast...")
result = subprocess.run([sys.executable, f'{WORKSPACE}/refresh_forecast.py'],
                        capture_output=True, text=True, cwd=WORKSPACE)
if result.returncode != 0:
    print(f"❌ Refresh failed:\n{result.stderr}")
    sys.exit(1)
print(result.stdout.strip())

# Parse CW and pipeline from output
import re
cw_match  = re.search(r'CW:\s*\$([\d,]+)', result.stdout)
pip_match = re.search(r'Pipeline:\s*\$([\d,]+)', result.stdout)
opp_match = re.search(r'(\d+)\s+open opps', result.stdout)
cw_val  = f"${cw_match.group(1)}"   if cw_match  else "see dashboard"
pip_val = f"${pip_match.group(1)}"  if pip_match else "see dashboard"
opp_val = opp_match.group(1)        if opp_match else "—"

# ── Step 2: Load + refresh token ─────────────────────────────────────────────
with open(TOKEN_FILE) as f:
    tokens = json.load(f)

# Try refresh if we have a refresh_token
if 'refresh_token' in tokens:
    r = requests.post(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
        data={
            "client_id": APP_ID,
            "grant_type": "refresh_token",
            "refresh_token": tokens['refresh_token'],
            "scope": "Mail.Send Mail.ReadWrite offline_access",
        }
    )
    if r.ok:
        tokens.update(r.json())
        with open(TOKEN_FILE, 'w') as f:
            json.dump(tokens, f, indent=2)

access_token = tokens.get('access_token')
if not access_token:
    print("❌ No access token — re-auth needed")
    sys.exit(1)

# ── Step 3: Send email ────────────────────────────────────────────────────────
from datetime import datetime
date_str = datetime.now().strftime("%B %d, %Y")

body_html = f"""
<div style="font-family:'Segoe UI',sans-serif;font-size:14px;color:#1e293b;max-width:600px;line-height:1.6">
  <p>Evan, Brent —</p>
  <br>
  <p>Here's the updated May forecast as of {date_str}:</p>
  <br>
  <p><a href="{FORECAST_URL}" style="background:#6366F1;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block">View May Forecast →</a></p>
  <br>
  <table style="font-size:13px;color:#64748b;border-collapse:collapse">
    <tr><td style="padding:3px 16px 3px 0">Closed Won</td><td style="font-weight:600;color:#1e293b">{cw_val}</td></tr>
    <tr><td style="padding:3px 16px 3px 0">Open Pipeline</td><td style="font-weight:600;color:#1e293b">{pip_val}</td></tr>
    <tr><td style="padding:3px 16px 3px 0">Open Opps</td><td style="font-weight:600;color:#1e293b">{opp_val}</td></tr>
  </table>
  <br>
  <p style="color:#94a3b8;font-size:12px">— Robin 🦸🏻‍♂️</p>
</div>
"""

email_payload = {
    "message": {
        "subject": f"May 2026 Forecast — {date_str}",
        "body": {"contentType": "HTML", "content": body_html},
        "toRecipients": [
            {"emailAddress": {"address": "evanr@rev.io"}},
            {"emailAddress": {"address": "brentm@rev.io"}},
        ],
        "ccRecipients": [
            {"emailAddress": {"address": "ryank@rev.io"}},
        ],
    }
}

r = requests.post(
    "https://graph.microsoft.com/v1.0/me/sendMail",
    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    json=email_payload
)

if r.status_code == 202:
    print(f"✅ Forecast email sent → evanr@rev.io, brentm@rev.io (CC: ryank@rev.io)")
else:
    print(f"❌ Email failed: {r.status_code} {r.text[:300]}")
    sys.exit(1)
