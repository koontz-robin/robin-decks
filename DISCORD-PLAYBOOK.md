# Discord as Your AI Sales Team Hub — A Replication Playbook

This document explains how Rev.io's sales team uses Discord as the primary collaboration surface between AI agents (Robin, Marvin) and the human team. Use this as a blueprint to replicate the setup for any sales org.

---

## Why Discord Over Slack or Teams?

- **Real-time, always-on** — agents post scorecards, dashboards, and alerts the moment they're ready
- **Bots as first-class citizens** — Discord's bot API is mature, well-documented, and free at scale
- **File attachments** — PowerPoints, audio files, HTML previews all work natively
- **Threads** — every call scorecard gets its own thread for discussion without cluttering the channel
- **Mobile-first** — the team reads and responds from their phones

---

## Channel Architecture

Start simple. Add channels as the team adopts each capability.

```
📁 Management / Intel
  #general          — main hub, direct agent access, ad-hoc requests
  #forecasts         — daily forecast drops, pipeline updates
  #alerts            — time-sensitive notifications (deals at risk, key emails)

📁 Coaching
  #meeting-scorecards — auto-graded discovery call scorecards
  #call-blitz        — live blitz standings and results

📁 Prospecting
  #prospecting       — daily net-new MSP account drops
  #re-engagement     — Apollo 2 / closed-lost re-engagement alerts
```

---

## Agent Setup (OpenClaw)

### What you need
- [OpenClaw](https://openclaw.ai) installed on a server/VM
- A Discord bot application (discord.com/developers/applications)
- Salesforce connected app credentials (client_credentials flow)
- Outreach OAuth tokens (for call grading)
- Anthropic API key (for Claude-powered grading)

### Bot permissions required
In the Discord Developer Portal, your bot needs:
- `Send Messages`
- `Read Message History`
- `Attach Files`
- `Embed Links`
- `Add Reactions`
- `Create Public Threads`
- `Send Messages in Threads`
- `Manage Channels` (optional — allows Robin to create channels)

### openclaw.json key settings
```json
{
  "channels": {
    "discord": {
      "token": "YOUR_BOT_TOKEN",
      "guildId": "YOUR_SERVER_ID",
      "defaultChannel": "YOUR_GENERAL_CHANNEL_ID"
    }
  }
}
```

---

## Automations Running Daily

### 1. Daily Forecast Dashboard (7 AM ET)
**What it does:** Pulls live Salesforce pipeline, rebuilds the forecast HTML deck, pushes to GitHub Pages.

**Key components:**
- `refresh_forecast.py` — SF auth, pipeline query, HTML build, git push
- Cron: `0 11 * * 1-5` (UTC)
- Output: HTML dashboard with worst/likely/best scenarios, per-product Q2 tracking, marketing attribution

**SF fields required:**
- `Forecast_Status__c` (custom) — tags opps as Worst Case / Most Likely / Best Case
- `Lead_Direction__c` (custom) — Marketing Generated vs Sales Generated
- `Product_Type__c` (custom) — product line per opp

**Scenario math:**
```
Worst  = March CW + Worst-tagged open opps
Likely = March CW + Worst + Most Likely-tagged
Best   = March CW + Worst + Most Likely + Best-tagged
```

---

### 2. Discovery Call Auto-Grader (every 30 min)
**What it does:** Polls Outreach Kaia for completed meetings. Matches to SF event type `1-Discovery Call`. Grades transcript with Claude against the BEACON rubric. Posts scorecard to Discord + Notion.

**Key components:**
- `grade_discovery_calls.py`
- Outreach Kaia API: `kaiaRecordings` endpoint
- State file: `grader-state.json` (tracks already-graded IDs)
- Scoring: 6 categories, 100 pts — Approach, Company Story, Qualifying, Talk Time, Summarize & Make Sick, Next Steps

**BEACON Rubric weights:**
| Category | Points |
|---|---|
| The Approach | 20 |
| Company Story | 10 |
| Qualifying / Needs Assessment | 30 |
| Talk Time Ratio | 15 |
| Summarize & Make Sick | 15 |
| Next Steps / Setting the Demo | 10 |

**Discord output:** Summary card with thread containing full scorecard. Tagged to rep if Notion user ID is known.

**Notion output:** Creates page in Sales Meeting Coaching DB with all scores, coaching points, Robin's Take.

---

### 3. Daily Sales Activity Scorecard (9 AM ET, Mon-Fri)
**What it does:** Pulls week-to-date SF activity for every rep. Scores calls, emails, contacts, meetings, opps sourced. Sends HTML email to management team.

**Key components:**
- `scorecard.py`
- SF event/task queries by rep
- Cron: `0 14 * * 1,2,3,4,5` (UTC)

**Scoring logic:**
- SDRs: Calls (1pt) + Emails (1pt, capped 100) + Contacts (2pt) + Opps Sourced (10pt)
- AEs: Calls + Emails + Contacts + Meetings (20pt, completed events)
- Weekly target: 500 pts

---

### 4. Daily MSP Prospector (7 AM ET)
**What it does:** Picks a random city from a priority list. Finds 5 MSPs not in Salesforce (deduped by domain). Posts to Discord with company info.

**Key components:**
- `skills/msp-prospector/scripts/prospect_msps.py`
- Brave Search API for discovery
- SF Account.Website dedup check

---

### 5. AE Capacity Dashboard (7 AM ET)
**What it does:** Pulls completed prospect meetings (Discovery, Demo, Follow-up, Pricing/Negotiation) for active AEs. Shows MTD vs projected. Published to GitHub Pages.

**Key components:**
- Built into `refresh_forecast.py` as `refresh_ae_capacity()`
- Event types: `1-Discovery Call`, `2-Initial DEMO`, `3-Follow Up DEMO / Meeting`, `4-Pricing / Negotiation Call`
- Filter: `Appointment_Status__c = 'Completed'`
- Totals pulled from all users (no AE filter) to match SF report
- Per-AE breakdown uses 7 active AEs only

---

## GitHub Pages Setup

All dashboards publish to a public GitHub repo via SSH push.

```bash
# Push pattern used in all scripts
GIT_SSH_COMMAND="ssh -i /path/to/id_ed25519 -o StrictHostKeyChecking=no" \
  git push origin master
```

View via htmlpreview.github.io:
```
https://htmlpreview.github.io/?https://github.com/YOUR_ORG/YOUR_REPO/blob/master/dashboard.html
```

---

## Notion Integration

Used for call scorecard storage and historic trend tracking.

**DB: Sales Meeting Coaching**
- Properties: Meeting Title, Prospect/Account, Meeting Date, Sales Rep (People), Overall Score, Approach, Company Story, Qualifying, Talk Time, Summarize, Next Steps, Top Coaching Point, Robin's Take, Recording URL
- Token type: Integration with read-write access
- Reps tagged via Notion user IDs matched to SF owner names

---

## Key Principles That Make It Work

1. **Agents respond in the channel they're messaged** — no need to go to a separate tool
2. **Everything links back to GitHub Pages** — one URL per dashboard, always current
3. **Live SF data, not exports** — dashboards rebuild from source every day
4. **Scoring is objective** — BEACON rubric removes subjectivity from call feedback
5. **Discord threads keep channels clean** — full scorecards in threads, summaries in channel
6. **Daily end-of-day summary** — agent writes a thorough daily note before backup, so context survives session restarts

---

## Files to Replicate

| File | Purpose |
|---|---|
| `refresh_forecast.py` | Forecast + AE capacity daily refresh |
| `build_forecast_april.py` | Current month forecast builder |
| `grade_discovery_calls.py` | Outreach Kaia call grader |
| `scorecard.py` | Daily activity scorecard emailer |
| `skills/msp-prospector/` | Daily prospecting automation |
| `grader-state.json` | Tracks graded call IDs |
| `apollo2_accounts.json` | Re-engagement target account list |
| `build_q2_apollo2.py` | Re-engagement tracker builder |

---

## What to Customize Per Org

- Product names and quotas in forecast builder
- BEACON rubric weights (adjust per coaching philosophy)
- AE list and roles
- Scorecard recipients and scoring weights
- Discord channel IDs
- Notion database IDs and property names
- GitHub repo for dashboard hosting

---

*Built by Robin for Rev.io Sales — April 2026*
