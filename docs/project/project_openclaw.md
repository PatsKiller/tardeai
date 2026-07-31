---
name: OpenClaw Setup Complete
description: Full OpenClaw installation details - version, agents, skills, channels, cron, security, workspace layout on ms01-openclaw
type: project
originSessionId: 9fa89957-9286-4128-b08d-7f960d9b6594
---
# OpenClaw Setup Documentation

## Installation

- **Version:** 2026.4.14 (2026.4.29 available)
- **CLI:** `/usr/bin/openclaw` (npm global package, 1.5GB at `/usr/lib/node_modules/openclaw/`)
- **Config:** `~/.openclaw/openclaw.json` (backups exist for pre-telegram-fix, known-good, pre-ollama-onboard)
- **Host:** ms01-openclaw (Ubuntu 24.04, 192.168.50.16)
- **Bash completions:** sourced in `.bashrc`

## Gateway Service

- **Systemd unit:** `openclaw-gateway.service` (user-level)
- **Port:** 18789, bound to LAN (192.168.50.16)
- **Restart:** always, 5s interval
- **Memory:** ~536M typical, ~764M peak
- **Auth:** token-based (aa8123e6...)

## Models (2026-07-09)

| Agent | Primary | Fallback chain |
|-------|---------|----------------|
| **Maria** (Telegram) | `claude-cli/claude-sonnet-4-6` (exec/tools) | `xai/grok-4` → `chatgpt/gpt-5.4` → `ollama/qwen3:8b` |
| **main** (default) | `claude-cli/claude-sonnet-4-6` | `chatgpt/gpt-5.4` → `ollama/qwen3:8b` |
| Specialists (Alex, Aegis, Iris, Steph) | `claude-cli/claude-sonnet-4-6` | `ollama/qwen3:8b` |

OAuth proxies: Grok `http://127.0.0.1:8645/v1`, ChatGPT `http://127.0.0.1:8646/v1` (free lanes).

Tool profile: `coding`

## Telegram routing (2026-07-09)

```json
"bindings": [{ "type": "route", "agentId": "maria", "match": { "channel": "telegram" } }]
```

All Telegram DMs route to **Maria** (not `main`). Portfolio questions: run
`python3 ~/.openclaw/skills/tradeai-readonly/scripts/tradeai_readonly.py portfolio-today` — never read
`SKILL.md` as data. `main` + `gpt-5.4` previously leaked garbled tool syntax to Telegram.

## Agents (6)

### 1. Maria (Personal Assistant) — **Telegram front door**
- Workspace: `~/.openclaw/workspace-maria/`
- Agent dir: `~/.openclaw/agents/maria/agent/`
- SOUL synced with `tradeai-readonly` + `tradeai-watchlist` skills
- Portfolio: `portfolio-today` for today's P&L + winners/losers
- Stop-outs: `stops-today` for triggered stops — labels **full close / partial close / monitor only**;
  includes account, realized journal P&L, day P&L
- **Full CC mirror:** `tradeai_readonly.py help` — hub commands map 1:1 to Command Center v3 pages
- **NL router:** `tradeai_query.py "<message>"` — deterministic routing (stops, portfolio, etc.); Maria must exec this, never stall on "one moment"
- **OAuth chat:** `tradeai-watchlist.py ask "..."` for free Grok/ChatGPT opinion — not for live CC/exec data

### 2. Main (default OpenClaw agent)
- Workspace: `~/.openclaw/workspace/`
- Files: SOUL.md, IDENTITY.md, USER.md, TOOLS.md, AGENTS.md, BOOTSTRAP.md, HEARTBEAT.md, MEMORY.md
- Not the Telegram DM handler (Maria is)

### 3. Steph (Wealth Advisor)
- Workspace: `~/.openclaw/workspace-steph/`
- Agent dir: `~/.openclaw/agents/steph/agent/`
- Role: Financial intelligence, portfolio analysis, tax optimization
- Personality: Sharp, direct, numbers-first
- SOUL.md includes portfolio summary (May 2026), financial constraints, holdings

### 4. Aegis (Portfolio Intelligence)
- Workspace: `~/.openclaw/workspace-aegis/`
- Role: Portfolio surveillance, intelligence synthesis, evening surveillance
- Features: Covered-call candidates, stop monitoring, social sentiment
- Architecture: Core overnight engine + chat layer

### 5. Alex (Retirement & Disability Advisor)
- Workspace: `~/.openclaw/workspace-alex/`
- Model: Claude Sonnet only (no fallback)
- Role: Retirement planning, disability optimization, Golden Window (ages 68.5-73), Roth conversions
- Key constraints: IRMAA limit $103K MAGI (MFS), bracket ceiling $94.3K

## Skills (14 installed)

**Personal Productivity:** next-step-checklist, summary-cleanup, daily-planner
**Light Research:** option-compare, source-action-extractor, research-summarizer
**Wealth Management:** steph-wealth-advisor
**Operations:** tradeai-safe-ops
**Email & Calendar:** follow-up-builder, meeting-prep-helper, email-draft-assistant
**Integrations:** gog (Google Calendar/Gmail/Drive), github

Deploy packages at: `~/openclaw_wave1_skills_deploy/`, `~/openclaw_batch3_skills_deploy/`
Skill dev repo: `~/openclaw-skills-john718/`

## Channels

### Telegram
- Bot: @bigjohn_openclaw_bot
- DM only, allowlist mode
- Approved IDs: tg:780672608, tg:8797974247
- Group policy: disabled

### WhatsApp
- Self-chat mode, single authorized number: +3473388380
- Session files stored in `~/.openclaw/credentials/`

## MCP Servers
- Google Calendar
- Google Drive

## Specialist delegation (Maria front door — 2026-07-31)

All Telegram DMs bind to **Maria** only. Steph, Aegis, Alex, and Iris are **not** separate Telegram bots; Maria delegates live questions via:

```bash
openclaw agent --agent <steph|aegis|alex|iris> \
  --message "<question>" \
  --deliver --reply-channel telegram --reply-to "tg:<sender-id>" --json
```

Maria's SOUL.md defines routing (income→Steph, surveillance→Aegis, CIO/retirement→Alex, research→Iris), confirm-first vs immediate delegation, and a hard rule against fabricating specialist opinions.

**Exec allowlist:** `~/.openclaw/exec-approvals.json` includes `/usr/bin/openclaw` for the `maria` agent.

Do **not** use `sessions_spawn` for specialists — it strips SOUL.md/IDENTITY.md; only `openclaw agent --agent …` preserves full persona.

## Cron Jobs

**OpenClaw cron** (`openclaw cron list` — live status **ok** as of 2026-07-31):

| Job | Agent | Schedule | Delivery |
|-----|-------|----------|----------|
| aegis-evening-surveillance | aegis | 8 PM weekdays | Telegram announce |
| steph-weekly-allocation-review | steph | Sunday 9 AM | Telegram announce |
| steph-income-progress | steph | 1st of month 9 AM | Telegram announce |
| Alex Monthly Retirement Check-in | alex | 1st of month 9 AM | Telegram announce |
| Iris Weekly Research Digest | iris | Sunday 9 AM | Telegram announce |
| Claude plan reminders | main | 24th + last day of month | systemEvent (no deliver) |

Previously documented as "disabled" — stale; verify with `openclaw cron list`.

**System crontab** (TradeAI):
- Event detector, event router, gov research, social scalp scanner (every 15 min / weekday morning / Sunday)

## Security

**Doctor results:**
- 1 Critical: Telegram group commands lack sender allowlist
- 3 Warnings: Reverse proxy headers not trusted, ineffective deny commands, potential multi-user setup
- Plugins: 56/56 loaded
- Memory search: disabled

**Exec approvals:** `~/.openclaw/exec-approvals.json` — `main` allowlist (gog calendar/Gmail); **`maria` allowlist includes `/usr/bin/openclaw`** for specialist delegation

## Related Directories

| Path | Purpose |
|------|---------|
| `~/.openclaw/` | Main installation & config |
| `~/openclaw-linux/` | Desktop starter package (scripts, docs, templates) |
| `~/openclaw-audit/` | Health check reports (doctor.txt, security_audit_deep.txt) |
| `~/openclaw-export/` | Export folder (empty) |
| `~/openclaw-ops/` | Operations snapshots |
| `~/openclaw-notes/` | Wave1 build specs and roadmaps |
| `~/openclaw-skills-john718/` | Skill dev git repo |

## Backups

- `~/backup_openclaw_20260416_2113.tar.gz` (1.2 MB)
- Multiple dated backups in `~/backups/`
- Config backups in `~/.openclaw/` (pre-telegram-fix, known-good, pre-ollama-onboard)

**Why:** Central reference for the full OpenClaw setup so future conversations don't need to re-discover the installation.
**How to apply:** Use when troubleshooting OpenClaw, adding agents/skills, or making config changes.
