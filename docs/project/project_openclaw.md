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
| **Maria** (Telegram) | `xai/grok-4` (OAuth proxy `:8645`) | `chatgpt/gpt-5.4` → `claude-cli/claude-sonnet-4-6` → `ollama/qwen3:8b` |
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
- Stop-outs: `stops-today` for triggered stops (alerts `stop_triggered` + risk `TRIGGERED` rows)
- **Full CC mirror:** `tradeai_readonly.py help` — hub commands `home`, `trading`, `risk-hub`, `hermes-hub`, `options-hub`, `health-hub`, etc. map 1:1 to Command Center v3 pages

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

## Cron Jobs

**OpenClaw cron** (`~/.openclaw/cron/jobs.json`):
- aegis-evening-surveillance (disabled, schedule errors)
- steph-weekly-allocation-review (disabled)
- steph-income-progress (disabled)
- Claude plan reminders: 24th at 9AM "lower plan in a week", last day at 9AM "lower plan today" (enabled)

**System crontab** (TradeAI):
- Event detector, event router, gov research, social scalp scanner (every 15 min / weekday morning / Sunday)

## Security

**Doctor results:**
- 1 Critical: Telegram group commands lack sender allowlist
- 3 Warnings: Reverse proxy headers not trusted, ineffective deny commands, potential multi-user setup
- Plugins: 56/56 loaded
- Memory search: disabled

**Exec approvals:** `~/.openclaw/exec-approvals.json` with allowlist for gog calendar/Gmail ops

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
