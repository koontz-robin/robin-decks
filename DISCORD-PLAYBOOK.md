# Discord Team Collaboration Pattern — Replication Guide for AI Agents

This document describes how Rev.io's AI agents (Robin for Sales, Marvin for Channel) are deployed to serve their respective teams via Discord. Use this as a reference to replicate the pattern for any team.

---

## What This Pattern Does

An AI agent runs 24/7 and serves a team through a dedicated Discord server. The agent:
- Responds to on-demand questions and requests in real time
- Posts automated reports, dashboards, and alerts on a schedule
- Grades, analyzes, and summarizes work (calls, pipeline, activity)
- Delivers proactive intelligence without being asked
- Maintains memory across sessions via daily backup to GitHub

---

## Architecture

```
Human Team
    ↕ Discord (messages, files, voice)
AI Agent (OpenClaw runtime)
    ↕ Salesforce (CRM data)
    ↕ Outreach (call recordings, sequences)
    ↕ Notion (notes, knowledge base)
    ↕ GitHub Pages (published dashboards)
    ↕ Email (Microsoft Graph API)
```

---

## Discord Setup

### Bot Configuration (openclaw.json)
```json
{
  "channels": {
    "discord": {
      "token": "BOT_TOKEN",
      "guildId": "SERVER_ID",
      "defaultChannel": "DEFAULT_CHANNEL_ID",
      "dmPolicy": "allowlist",
      "dmAllowFrom": ["USER_ID_1", "USER_ID_2"]
    }
  }
}
```

### Required Bot Permissions
- Send Messages
- Read Message History
- Attach Files
- Embed Links
- Add Reactions
- Create Public Threads
- Send Messages in Threads
- Manage Channels (optional — for creating new channels)

### Channel Structure (Sales Team Example)
```
#general            — primary hub, all requests, ad-hoc analysis
#forecasts          — daily pipeline dashboard links
#meeting-scorecards — auto-graded call scorecards with threads
#prospecting        — daily new account drops
#alerts             — time-sensitive notifications
```

---

## Giving a Team Access

1. Create a Discord server (or use existing)
2. Invite the bot via OAuth2 URL (discord.com/developers → your app → OAuth2 → URL Generator)
3. Generate a server invite link (Server Settings → Invites → Create Invite → No Expiry)
4. Share invite link with team members
5. Configure channel permissions per role if access control is needed
6. Configure `dmAllowFrom` in openclaw.json with specific user IDs for DM access

To find a Discord user ID: right-click username → Copy User ID (Developer Mode must be enabled in Discord settings).

---

## Automations Pattern

Each automation follows this structure:
1. **Trigger** — cron schedule or on-demand request
2. **Data source** — SF, Outreach, external API, or file
3. **Processing** — Python script builds output (HTML dashboard, scorecard, report)
4. **Delivery** — pushed to GitHub Pages + posted to Discord channel

### Cron Schedule Convention
All crons run via `openclaw cron add`. Schedules in ET:
- Daily ops: `0 11 * * 1-5` (7 AM ET Mon-Fri)
- Recurring checks: `*/30 * * * *` (every 30 min)
- End of day: `0 23 * * *` (11 PM ET daily)

### GitHub Pages Delivery Pattern
Dashboards are HTML files hosted on GitHub Pages via SSH push:
```bash
GIT_SSH_COMMAND="ssh -i /path/to/id_ed25519 -o StrictHostKeyChecking=no" \
  git push origin master
```
Viewable at: `https://htmlpreview.github.io/?https://github.com/ORG/REPO/blob/master/file.html`

---

## Memory and Continuity

The agent writes daily notes and backs up memory to GitHub nightly:
- **Session notes:** `memory/YYYY-MM-DD.md` — thorough daily summary of key conversations, decisions, and tasks
- **Long-term memory:** `MEMORY.md` — curated facts, preferences, credentials, ongoing context
- **Backup:** Both pushed to a private GitHub repo (`robin-brain`) at 11 PM ET every day

This ensures context survives session restarts and the agent can reconstruct what happened.

---

## Key Integration Points

### Salesforce
- Auth: `client_credentials` flow (no refresh token required)
- Endpoint: `https://YOUR_INSTANCE.my.salesforce.com/services/oauth2/token`
- Common queries: pipeline, events, tasks, accounts, opportunities
- Required custom fields: `Forecast_Status__c`, `Lead_Direction__c`, `Product_Type__c`

### Outreach (Kaia Call Recordings)
- Auth: OAuth2 with refresh token
- Key endpoint: `GET /api/v2/kaiaRecordings`
- Filter by: `format=meeting`, `state=ENDED`, match to SF event type
- Transcript: fetch from `transcriptUrl` field → JSON utterances

### Notion
- Auth: Integration token (read-write)
- Use: Store call scorecards, meeting notes, KPI trackers
- Key: match rep names to Notion user IDs for tagging

### Email (Microsoft Graph)
- Auth: OAuth2 public client with refresh token
- Scopes: `Mail.Read`, `Mail.Send`, `Mail.ReadWrite`, `Calendars.Read`
- Forward target inbox emails to agent's mailbox for monitoring

---

## Replication Checklist

To replicate this pattern for a new team:

- [ ] Create Discord server and bot application
- [ ] Configure openclaw.json with bot token, guild ID, channel IDs
- [ ] Invite team members and configure permissions
- [ ] Connect data sources (CRM, communication platform, etc.)
- [ ] Define the team's core automations (what do they need daily?)
- [ ] Set up GitHub repo for dashboard hosting
- [ ] Configure Notion integration if note/scorecard storage is needed
- [ ] Set up daily memory backup cron
- [ ] Write MEMORY.md with team context (names, roles, tools, preferences)
- [ ] Give the agent a name and personality appropriate for the team

---

## What Works Well

- **Threads for long responses** — keeps channels readable
- **Always-on crons** — team gets value without asking
- **GitHub Pages for dashboards** — one shareable URL, always current
- **Daily memory writes** — agent doesn't lose context between sessions
- **Proactive > reactive** — the most valued automations are ones the team didn't know they wanted until they had them

---

*Built by Robin · Rev.io · April 2026*
