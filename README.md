# 🏭 AI Startup Factory v3

Fully autonomous micro-SaaS pipeline with human-in-the-loop approvals via Discord.

## Agents

| Agent | Role |
|-------|------|
| **Liam** | Reddit research → AI validation → GitHub repo mining → Reddit replies → Postiz social posting |
| **Kyle** | AI code generation (with reference repo context) → GitHub repo → Netlify deploy |
| **Nick** | Blog post + tweet thread + LinkedIn content → saves JSON to repo for your review |
| **Vera** | Discord gatekeeper — asks for your approval at every stage |

## Full Pipeline (event-driven)

```
[Liam triggered]
  → Scrapes Reddit, checks your existing repos for tool matches
  → Replies to Reddit threads where you already have a tool
  → Mines GitHub for reference code on new ideas
  → Validates ideas with AI scoring
  → Vera → Discord: "Approve this idea?" → You reply 'approve'
  → Saves to problems.json

[Kyle triggered by problems.json change]
  → Fetches reference repo code as context
  → AI generates full working code
  → Creates GitHub repo + pushes
  → Netlify CLI: creates site + deploys → gets live URL
  → Vera → Discord: "App is live at X. Approve for marketing?" → You reply 'approve'
  → Saves to app_database.json

[Nick triggered by app_database.json change]
  → AI writes blog post + tweet thread + LinkedIn post
  → Saves to marketing/{app}.json in repo (edit via GitHub UI if needed)
  → Vera → Discord: "Content ready at [GitHub link]. Approve?" → You reply 'approve'
  → Queues in marketing_queue.json

[Liam triggered by pipeline_state.json → idle]
  → Posts tweet thread + LinkedIn via Postiz
  → Posts natural Reddit reply with the Netlify URL
  → Sends confirmation to Discord
  → Sets state to idle → next search cycle begins
```

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `AI_API_KEY` | ezif.in API key |
| `NVIDIA_API_KEY` | NVIDIA NIM API key (fallback) |
| `GITHUB_TOKEN` | Auto-provided by Actions |
| `GITHUB_USERNAME` | Your GitHub username |
| `NETLIFY_AUTH_TOKEN` | Netlify personal access token |
| `REDDIT_CLIENT_ID` | Reddit app client ID |
| `REDDIT_CLIENT_SECRET` | Reddit app client secret |
| `REDDIT_USERNAME` | Reddit account username |
| `REDDIT_PASSWORD` | Reddit account password |
| `DISCORD_BOT_TOKEN` | Discord bot token |
| `DISCORD_APPROVAL_CHANNEL_ID` | Channel ID for approvals |
| `DISCORD_OWNER_USER_ID` | Your Discord user ID |
| `POSTIZ_API_KEY` | Postiz API key (add when ready) |
| `POSTIZ_BASE_URL` | Postiz base URL (add when ready) |
| `FACTORY_REPO_NAME` | This repo's name: `ai-startup-factory` |

## First-Time Setup

1. Run `bash setup.sh` on Termux
2. Add all secrets at `https://github.com/YOUR_USERNAME/ai-startup-factory/settings/secrets/actions`
3. Create a Discord bot at https://discord.com/developers/applications
   - Enable **Message Content Intent**
   - Invite bot to your server with `Send Messages` + `Read Message History` permissions
4. Run **Vera — Discord Test** workflow to verify the bot is connected
5. Run **Liam — Research & Post** workflow manually to kick off the first cycle

## Approval Flow (Discord)

- Liam finds idea → Vera pings you → reply **`approve`** to build it
- Kyle builds app → Vera pings you with live URL → check it, reply **`approve`** for marketing
- Nick creates content → Vera pings you with GitHub file link → edit if needed, reply **`approve`** to post

No reject option — just don't reply and it times out (5 min in dev, extend for production).

## Key Design Decisions

- **Event-driven not cron** — each stage triggers the next via file changes
- **One idea at a time** — quality over quantity, no parallel builds
- **AI fallback** — every AI call tries ezif.in first, falls back to NVIDIA NIM
- **Reference-informed builds** — Kyle fetches real open-source code before generating
- **Natural Reddit replies** — varied templates with minor imperfections, not promotional copy
- **You control every stage** — nothing ships without your Discord approval

