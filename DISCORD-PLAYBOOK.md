# Setting Up an AI Bot for Your Team in Discord

This document explains how to give your entire team access to an AI agent through Discord — the same way Rev.io's sales and channel teams use Robin and Marvin today. Use this as a blueprint to replicate the setup for any team.

---

## Why Discord?

- **Always-on access** — the bot is available 24/7, responds in real time, and works from any device
- **No new tools** — if your team already uses Discord, there's nothing new to install or learn
- **Bots as first-class citizens** — Discord's bot API is mature, well-documented, and free at scale
- **File attachments** — the bot can send documents, images, audio files, and links natively
- **Threads** — keeps detailed responses organized without cluttering the main channel
- **Mobile-first** — team members can ask questions and get answers from their phones

---

## Step 1 — Create a Discord Server

If you don't have one already:

1. Open Discord → click the **+** icon in the left sidebar
2. Select **Create My Own** → **For a club or community** (or just "For me and my friends")
3. Give it a name (e.g. "Acme AI Hub" or your team name)
4. You now have a server — you'll see a default **#general** channel

---

## Step 2 — Set Up Your AI Bot

Your AI bot runs on **OpenClaw** — an agent runtime that connects Claude/GPT to your tools and channels.

### What you need
- [OpenClaw](https://openclaw.ai) installed on a server, VM, or local machine
- A Discord bot application (free at discord.com/developers)

### Create the Discord bot
1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → give it a name (this becomes the bot's name)
3. Click **Bot** in the left sidebar → **Add Bot**
4. Under **Token**, click **Reset Token** and copy it — this is your bot token
5. Scroll down and enable:
   - **Server Members Intent**
   - **Message Content Intent**
6. Go to **OAuth2 → URL Generator**:
   - Scopes: check `bot`
   - Bot Permissions: check `Send Messages`, `Read Message History`, `Attach Files`, `Embed Links`, `Add Reactions`, `Create Public Threads`, `Send Messages in Threads`
7. Copy the generated URL, open it in a browser, and select your server to invite the bot

### Connect to OpenClaw
In your `openclaw.json` config file:
```json
{
  "channels": {
    "discord": {
      "token": "YOUR_BOT_TOKEN",
      "guildId": "YOUR_SERVER_ID",
      "defaultChannel": "YOUR_CHANNEL_ID"
    }
  }
}
```

To find your server ID and channel ID: enable Developer Mode in Discord (Settings → Advanced → Developer Mode), then right-click your server or channel and select **Copy ID**.

---

## Step 3 — Set Up Your Channels

Start simple. Add channels as the team adopts each capability.

A good starting structure:

```
#general         — main hub, everyone can ask the bot anything
#alerts          — bot posts proactive updates and notifications
#reports         — automated reports and dashboards
```

You can add more specific channels later (e.g. `#coaching`, `#prospecting`, `#forecasts`) as you figure out what the team actually uses.

---

## Step 4 — Give Your Team Access

### Invite team members to the server
1. Click your server name → **Invite People**
2. Generate an invite link and share it with your team via Slack, email, or text
3. Set the invite to "Never expire" if you want a permanent link

### Set permissions so everyone can talk to the bot
By default everyone in the server can message in channels. If you want to restrict who can access certain channels:

1. Go to **Server Settings → Roles**
2. Create roles (e.g. "Sales Team", "Leadership") and assign them
3. On each channel → **Edit Channel → Permissions** → control which roles can read/write

### DM access (optional)
If you want team members to be able to DM the bot directly (not just in channels), configure OpenClaw's DM policy:

```json
{
  "channels": {
    "discord": {
      "dmPolicy": "open"  // or "allowlist" for specific users only
    }
  }
}
```

For `allowlist`, add trusted user IDs:
```json
{
  "dmAllowFrom": ["USER_ID_1", "USER_ID_2"]
}
```

To find a user's ID: right-click their name in Discord → **Copy User ID** (requires Developer Mode enabled).

---

## Step 5 — Tell Your Team How to Use It

The bot responds to messages in any channel it has access to. Basic usage:

- **Ask anything in #general** — "What's our pipeline this week?" / "Summarize this doc" / "Help me draft an email to..."
- **@mention the bot** — in channels with multiple people, mention the bot to get its attention: `@Robin can you...`
- **Upload files** — drop a PDF, spreadsheet, or transcript and ask the bot to analyze it
- **Request reports** — "Pull the latest forecast" / "Show me this week's activity scores"

The bot remembers context within a session. For tasks that need to persist (reminders, recurring reports), ask it to set up a cron job.

---

## Step 6 — Automate Proactive Updates

The real power is the bot posting to your team *without being asked*. Common patterns:

| Automation | Frequency | Channel |
|---|---|---|
| Daily briefing / status update | Every morning | #general or #alerts |
| Automated reports (pipeline, metrics) | Daily or weekly | #reports |
| Alerts on key events (deal closed, email received) | Real-time | #alerts |
| Coaching / feedback posts | After each qualifying event | #coaching |

To set up a recurring task, ask the bot: *"Post our pipeline summary to #reports every Monday at 9 AM."*

---

## Tips for Adoption

**Start with one power user.** Don't roll it out to the whole team at once. Have one person use it heavily for a week, figure out what's actually useful, then share those specific use cases with the team.

**Make the first value obvious.** The fastest way to get adoption is one thing that saves everyone 20 minutes. Figure out what that is for your team and lead with it.

**Use threads.** When the bot gives a long response, it creates a thread. Encourage the team to continue the conversation there so the main channel stays clean.

**Name the bot something memorable.** "Robin", "Marvin", "Atlas" — a name makes it feel like a teammate, not a tool. People talk to it differently.

**It gets smarter as you use it.** The bot builds memory over time. The more context you give it about your team, processes, and preferences, the better it gets.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Bot not responding | Check the bot token in openclaw.json, confirm Message Content Intent is enabled |
| Bot can't see messages | Confirm the channel allows the bot role to read messages |
| Can't DM the bot | Check dmPolicy in openclaw.json, confirm user is on allowlist if using allowlist mode |
| Bot not in server | Re-run the OAuth invite URL from the developer portal |

---

*Built by Robin for Rev.io — April 2026*
