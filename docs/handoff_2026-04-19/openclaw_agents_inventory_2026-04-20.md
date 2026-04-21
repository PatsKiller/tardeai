# OpenClaw Installed Agents Inventory

**Date:** 2026-04-20
**Author:** Claude Opus 4.6
**Status:** Read-only discovery — no modifications made

---

## 1. Executive Summary

| Count | Status |
|-------|--------|
| **2 confirmed agents** | Maria (main/personal), Steph (wealth advisor) |
| **1 gateway service** | OpenClaw Gateway v2026.4.11 on port 18789 |
| **7 installed skills** | email-calendar, integrations, light-research, operations, personal-productivity, steph-wealth-advisor, wealth |
| **1 project-level agent stub** | `agents/openai.yaml` (Trade AI Reports interface definition — not a conversational agent) |

**Architecture:** OpenClaw is a Node.js gateway running as a user systemd service. It hosts agents that communicate via Telegram/WhatsApp. Agents are defined by workspace files (SOUL.md, IDENTITY.md, TOOLS.md, AGENTS.md) and use skills for specialized capabilities.

---

## 2. Agent Inventory Table

| Name | Role | Workspace | Config | Models | Memory | Status |
|------|------|-----------|--------|--------|--------|--------|
| **Maria** (main) | Personal assistant | `~/.openclaw/workspace/` | `openclaw.json` agent `id: "main"` | Default: ollama/qwen3:1.7b; Fallback: gpt-5.4-mini → claude-sonnet-4-6 | `~/.openclaw/workspace/memory/` (20+ files) | **Active** |
| **Steph** | Wealth advisor | `~/.openclaw/workspace-steph/` | `openclaw.json` agent `id: "steph"` + `agents/steph/agent/` | Codex gpt-5.4/5.4-mini/5.2; Ollama gemma4/qwen3:14b | None observed | **Active** |

---

## 3. Maria

### Exact role
Personal assistant. Helps John with organization, drafting, scheduling, light research, project coordination. Explicitly NOT a financial advisor or system administrator.

### Config files
- `~/.openclaw/openclaw.json` — agent list entry (id: "main", default workspace)
- `~/.openclaw/workspace/SOUL.md` — tone/character definition
- `~/.openclaw/workspace/IDENTITY.md` — name, emoji (🌿), role statement
- `~/.openclaw/workspace/AGENTS.md` — operating rules + Steph routing logic
- `~/.openclaw/workspace/TOOLS.md` — tool access (gog, portfolio read-only awareness)
- `~/.openclaw/workspace/USER.md` — John's profile and preferences
- `~/.openclaw/workspace/HEARTBEAT.md` — token efficiency rule
- `~/.openclaw/workspace/MEMORY.md` — seed memory note
- `~/.openclaw/workspace/BOOTSTRAP.md` — first-run personality setup

### Integrations
- **Google (gog):** Calendar, Gmail, Drive via `john@jwwhiting.com`
- **Telegram:** Primary interaction channel
- **WhatsApp:** Casual messages
- **Portfolio (read-only):** Can read `performance_history.json` and `holdings.json` — routes financial questions to Steph

### Memory/state
- `~/.openclaw/workspace/memory/` — 20+ timestamped markdown memory files (2026-04-14 through 2026-04-16)
- Memory is file-based, not DB-backed
- No Postgres connection

### What Maria should own vs not own
| Owns | Does NOT own |
|------|-------------|
| Calendar/scheduling | Financial advice |
| Email drafting | Portfolio decisions |
| Light research | Trading signals |
| Task/project coordination | System administration |
| Reminders | Technical operations |
| Steph routing (dispatch) | Wealth strategy |

---

## 4. Steph

### Exact role
Direct, practical wealth advisor. Answers portfolio questions, Roth strategy, concentration risk, rebalancing, analyst/technical summaries. Invoked only via explicit routing ("ask Steph..." or "Steph, ...").

### Config files
- `~/.openclaw/openclaw.json` — agent entry (id: "steph", workspace: workspace-steph, agentDir: agents/steph/agent)
- `~/.openclaw/agents/steph/agent/SOUL.md` — full financial profile, holdings, strategy context
- `~/.openclaw/agents/steph/agent/models.json` — model definitions (Codex gpt-5.4/5.2, Ollama gemma4/qwen3:14b)
- `~/.openclaw/agents/steph/agent/auth-profiles.json` — API keys (Anthropic, OpenAI, Ollama)
- `~/.openclaw/workspace-steph/SOUL.md` — persona definition (direct, tax-aware, portfolio-first)
- `~/.openclaw/workspace-steph/IDENTITY.md` — name and routing rules
- `~/.openclaw/workspace-steph/TOOLS.md` — portfolio data file paths
- `~/.openclaw/workspace-steph/AGENTS.md` — operating rules, scope, reliability rules
- `~/.openclaw/workspace-steph/USER.md` — (presumed, standard workspace file)
- `~/.openclaw/skills/steph-wealth-advisor/SKILL.md` — skill definition with data priority, response structure, file references

### Integrations
- **Portfolio JSON files:** Reads holdings.json, performance_history.json, enrichment cache, sector data, fund lookthrough, risk management, stops, technical snapshot
- **Dashboard:** http://192.168.50.16:7777/reports/command_center.html
- **Models:** Codex (gpt-5.4), Ollama (gemma4, qwen3:14b)
- **No direct Postgres access** — reads JSON state files only

### Memory/state
- No memory directory observed in workspace-steph
- Relies on SOUL.md hardcoded portfolio context (snapshot from April 2026)
- **No persistent memory layer** — Steph's knowledge is frozen in SOUL.md

### How Steph handles review/escalation
- **External model policy:** Only uses external LLM with explicit user permission
- **Data priority:** Local JSON → future Postgres → Finviz → Yahoo → external LLM (last resort)
- **Tax impact:** Always mentions before suggesting trims/sells
- **Uncertainty:** Explicitly states missing data, never fabricates

### What Steph should supervise in the future portfolio stack
- Portfolio health oversight (concentration, risk, stops)
- Roth conversion strategy validation
- Rebalancing review and approval
- New advisor-agent recommendation review (Steph could be the "senior advisor" that validates OpenClaw portfolio agent findings before they reach John)

---

## 5. Other Agents / Related Workflows

### OpenClaw Gateway
- **Service:** `openclaw-gateway.service` (user systemd)
- **Port:** 18789
- **Status:** Active (running 3+ days, 480MB memory)
- **Auth:** Token-based (`aa8123e6...`)
- **Bind:** LAN mode

### Installed Skills (7)
| Skill | Purpose |
|-------|---------|
| `email-calendar` | Google Calendar/Gmail integration |
| `integrations` | General connector utilities |
| `light-research` | Web research capability |
| `operations` | System operations (admin tasks) |
| `personal-productivity` | Task/project management |
| `steph-wealth-advisor` | Financial advisor skill (routes to Steph) |
| `wealth` | Wealth management utilities |

### MCP Servers
- `google-calendar` — Google Calendar MCP (HTTP transport)
- `google-drive` — Google Drive MCP (HTTP transport)

### Trade AI Project Agent Stub
- `~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/agents/openai.yaml` — Interface definition for "Trade AI Reports v10" (display name, icon). NOT a conversational agent — likely a legacy OpenAI Assistants or similar integration definition.

---

## 6. Architecture Fit Recommendation

### Where the portfolio-intelligence advisor-agent should fit

```
┌─────────────────────────────────────────────────────┐
│                  JOHN (Human)                        │
│         Telegram / WhatsApp / Gmail                  │
└─────────┬───────────────────────────────┬───────────┘
          │                               │
          ▼                               ▼
┌─────────────────┐           ┌───────────────────────┐
│   MARIA (🌿)    │           │   STEPH (📊)          │
│   Personal Asst │           │   Wealth Advisor      │
│   - Calendar    │──routes──▶│   - Portfolio Q&A     │
│   - Email       │           │   - Roth strategy     │
│   - Drafting    │           │   - Risk review       │
│   - Research    │           │   - Rebalancing       │
└─────────────────┘           └───────────┬───────────┘
                                          │ reviews/validates
                                          ▼
                              ┌───────────────────────┐
                              │  OPENCLAW PORTFOLIO   │
                              │  ADVISOR (NEW)        │
                              │  - Surveillance       │
                              │  - Observations       │
                              │  - Dividend tracking  │
                              │  - Signal monitoring  │
                              │  - Escalation         │
                              └───────────┬───────────┘
                                          │ reads/writes
                                          ▼
                              ┌───────────────────────┐
                              │   POSTGRES + JSON     │
                              │   (Trade AI / PI)     │
                              │   - 9 tables          │
                              │   - State files       │
                              │   - Pipeline output   │
                              └───────────────────────┘
```

### Recommended ownership

| Responsibility | Owner |
|----------------|-------|
| User interaction / conversation | Maria (routes to Steph/Portfolio agent) |
| Portfolio Q&A (on-demand answers) | Steph |
| Proactive surveillance (background monitoring) | **New portfolio agent** |
| Observation generation | **New portfolio agent** |
| Recommendation generation | **New portfolio agent** (validated by Steph) |
| User notification (email/Telegram alerts) | **New portfolio agent** (or Maria as delivery channel) |
| Recommendation review / approval | Steph (or direct to John) |
| Write-back to advisor memory | **New portfolio agent** |
| Write-back to operational state (stops, signals) | Pipeline only (agent proposes, human confirms) |

### Standalone agent vs sub-agent

**Recommend: standalone background process with Steph as validation layer.**

The new portfolio agent should:
- Run as its own timer/service (like the existing portfolio pipeline)
- Write directly to Postgres (observations, dividend history)
- Queue recommendations for Steph review (or direct to John for urgent)
- NOT route through the OpenClaw gateway for its background work (too heavy for surveillance loops)
- Optionally register with OpenClaw as a skill so Steph can query its observations ("what has the portfolio agent noticed this week?")

---

## 7. Risks / Conflicts

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Duplicate notifications** | HIGH | Maria owns casual messages. New agent owns portfolio alerts. Steph owns on-demand answers. Clear channel separation. |
| **Conflicting advice** | MEDIUM | New agent generates observations/recommendations. Steph validates before surfacing. Single source of truth: Postgres. |
| **Steph's SOUL.md gets stale** | HIGH | Steph's portfolio snapshot is hardcoded in SOUL.md (April 2026 data). As portfolio changes, Steph's built-in context drifts. Fix: Steph should read live data from JSON/Postgres, not rely on SOUL.md snapshot. |
| **Memory system fragmentation** | MEDIUM | Maria has file-based memory in workspace. New agent has Postgres. Steph has no persistent memory. Consider: shared memory layer accessible by all agents. |
| **Authority confusion** | LOW | Clear rule: new agent observes and proposes. Steph or John approves. Maria delivers messages. No agent acts autonomously on portfolio. |
| **Model cost collision** | LOW | Each agent has its own model config. New agent should default to Ollama (free) and only escalate to external with budget tracking. |

---

## 8. Recommended Next Design Constraints

When creating the new portfolio agent, follow these rules:

1. **Don't register as an OpenClaw conversational agent initially.** Run as a background service (like the existing pipelines). Register as a skill later for Steph to query.

2. **Don't send messages through Maria's channels.** Use a separate notification path (dedicated Telegram bot or Gmail) to avoid confusion about "who said this."

3. **Don't duplicate Steph's on-demand capability.** Steph answers when asked. The new agent watches continuously and escalates when warranted. Different operating modes.

4. **DO write to shared Postgres.** The new agent's observations should be queryable by Steph. Steph can answer "what has the advisor agent flagged this week?" by reading `advisor_observations`.

5. **DO respect the data priority hierarchy** already established for Steph: local JSON → Postgres → Finviz → Yahoo → external LLM.

6. **DO mark all output with provenance.** Every observation/recommendation must record which model, which data, which confidence level.

7. **DO keep Steph's SOUL.md portfolio context updatable.** Consider a nightly job that regenerates Steph's portfolio snapshot section from live data.

8. **DON'T auto-send Gmail without a validation period.** First 30 days: all notifications queued for human review. After: digests auto-send, urgent alerts auto-send.

9. **DO share the `.env` credential model.** Same DB_PASSWORD, same API keys as the pipeline. No separate credential stores.

10. **DO use the same dual-write pattern.** JSON remains operational source of truth. Postgres is the memory/analytical layer. Proven pattern, don't reinvent.

---

## 9. Appendix

### Key file paths discovered
```
~/.openclaw/openclaw.json                         — main OpenClaw config (agents, gateway, auth, models)
~/.openclaw/agents/steph/agent/SOUL.md            — Steph full system prompt with portfolio context
~/.openclaw/agents/steph/agent/models.json        — Steph model definitions
~/.openclaw/agents/steph/agent/auth-profiles.json — API keys (Anthropic, OpenAI, Ollama)
~/.openclaw/workspace/                            — Maria's workspace (SOUL, IDENTITY, TOOLS, AGENTS, USER, MEMORY, etc.)
~/.openclaw/workspace-steph/                      — Steph's workspace (SOUL, IDENTITY, TOOLS, AGENTS)
~/.openclaw/workspace/memory/                     — Maria's persistent memory (20+ timestamped files)
~/.openclaw/skills/steph-wealth-advisor/SKILL.md  — Steph skill definition
~/.config/systemd/user/openclaw-gateway.service   — Gateway systemd unit
```

### Commands used
```bash
find /home/johnclaw -maxdepth 3 -type d -name "*agent*" -o -name "*openclaw*" ...
cat ~/.openclaw/openclaw.json | python3 -m json.tool
cat ~/.openclaw/agents/steph/agent/SOUL.md
cat ~/.openclaw/workspace/SOUL.md
cat ~/.openclaw/workspace/AGENTS.md
cat ~/.openclaw/workspace/TOOLS.md
systemctl --user status openclaw-gateway
```

### Unresolved questions
- **Where does Steph persist conversation history?** No memory directory in workspace-steph. May rely on gateway session memory only.
- **Is the `wealth` skill separate from `steph-wealth-advisor`?** Two related skills — may overlap or `wealth` may be deprecated.
- **Does the gateway support background/scheduled agent runs?** Currently seems conversation-driven only. Background portfolio monitoring may need to run outside the gateway.
- **Token in auth-profiles.json** — the gateway token and API keys are stored in plain text. Consider if the new agent needs its own auth profile or shares existing ones.
