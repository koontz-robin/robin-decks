# MEMORY.md — Robin's Long-Term Memory

Last updated: 2026-05-04

---

## Who I Am
- Name: Robin
- Role: AI assistant to Ryan Koontz at Rev.io
- Email: robin.bot@rev.io (Microsoft 365 / Rev.io tenant)
- GitHub: commits as robin.bot@rev.io, pushes to koontz-robin/robin-decks

---

## Ryan Koontz
- Name: Ryan Koontz
- Role: VP Sales (or similar) at Rev.io
- Work email: ryank@rev.io
- Discord: ryan_koontz
- Timezone: US Eastern (ET)
- Prefers concise, direct communication — skip filler
- I send him a morning briefing, manage his forecast dashboard, grade discovery calls, etc.

---

## Key Contacts

| Name | Role | Email |
|---|---|---|
| Evan | President, Rev.io | evanr@rev.io |
| Brent | ELT member, Rev.io | brentm@rev.io |
| Cam Sharpe | MSP Sales Manager | cam.sharpe@rev.io |
| Bryan Bettiol | Sales Manager | bryanb@rev.io |
| Jay Sapirman | Sales Manager | jay.sapirman@rev.io |
| Reid D | Sales Manager | reidd@rev.io |
| Tony Mehner | (receives feature pipeline emails) | tony.mehner@rev.io |
| Brook Lee | (channel / partnerships) | — |
| Usman Zahoor | Channel team | — |
| Leslie Ingram | VP Product | — |
| Marsha Blobaum | PM, ticketing | — |

---

## Email Setup ✅
- Auth: OAuth2 via Entra (public client — NO secret on refresh)
- Tenant: ad233ca3-255e-4697-90c0-5bf96200d3ae
- App ID: 0bda3b19-e713-4103-be0d-2bf057af5cba
- Scopes: Mail.Read, Mail.Send, Mail.ReadWrite, Calendars.Read
- Token file: /home/openclaw/.openclaw/workspace/email-tokens.json
- API: Microsoft Graph /v1.0/me/sendMail
- Sign-off: "— Robin 🦸🏻‍♂️"
- **IMPORTANT**: Public client — do NOT send client_secret when refreshing token

---

## Salesforce
- Instance: standard SF org
- Auth: OAuth2 PKCE, tokens in sf-tokens.json
- Key custom field: Forecast_Status__c (Worst Case / Most Likely / Best Case)
- May opps: sf_may_opps.json | April opps: sf_april_opps.json

---

## Forecast Dashboard
- URL: https://koontz-robin.github.io/robin-decks/forecast.html
- Repo: git@github.com:koontz-robin/robin-decks.git (remote: robin-decks)
- Branch: push-q2-board → pushes to master
- Sent weekly to: evanr@rev.io, brentm@rev.io
- Opp tags come from SF Forecast_Status__c field
- Marketing influence: q2_reengagement_baseline.json (account name matching)
- May 2026 quotas: PSA $36,000 | Billing/Odin $10,252 | Payments $11,040 | Cyber+CommerceHub $7,434

---

## GitHub Pages
- Repo: koontz-robin/robin-decks
- Push protection blocks secrets in commit history — need to unblock via GitHub security UI when hitting it
- Pages URL pattern: https://koontz-robin.github.io/robin-decks/<filename>.html

---

## Recurring Tasks
- **Weekly forecast email**: Send forecast.html link to evanr@rev.io + brentm@rev.io
- **Daily forecast refresh**: Pull SF data, rebuild forecast.html, push to GitHub
- **Discovery call grading**: grade_discovery_calls.py — grades Kaia recordings via Outreach
- **CBR grading**: grade_cbr_calls.py
- **Scorecard**: scorecard.py (2pm daily — NOTE: file missing as of 2026-05-04, needs to be rebuilt)
