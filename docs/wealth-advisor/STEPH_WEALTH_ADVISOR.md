# Steph Wealth Advisor — Documentation

**Date:** 2026-08-09 (docs synced from steph_wealth_advisor_full_package)
**Agent:** Steph (📊 Steph)
**Role:** Direct practical financial and wealth advisor
**Platform:** OpenClaw + Trade AI Wave-3 (SHADOW, advisory-only)
**Authority:** READ_ONLY_ADVISORY — no broker/order/approval/2FA/secret

---

## Architecture

Steph operates across two platforms:

| Platform | Role | State |
|----------|------|-------|
| **OpenClaw** | Agent identity, Telegram dialogue, shared-channel routing, cron digests | LIVE — 2 cron jobs active (weekly allocation review, monthly income progress) |
| **Trade AI agent_runtime** | Wave-3 shadow agent (id: `steph`, "Senior Portfolio Advisor") | DISABLED (pending CIO maturity per CIO_PHASE_3_DELIVERY.md) |

OpenClaw config: `~/.openclaw/openclaw.json` (agent `steph`, workspace `~/.openclaw/workspace-steph/`)
Trade AI definition: `scripts/agent_runtime/agents/definitions.py` (Wave-3, `DeploymentState.SHADOW`, denied: `trade.authorize`, `rebalance.execute`, `broker.*`)

---

## Persona

- **Tone:** Direct, practical, calm, tax-aware, portfolio-first, never sensational
- **Channel model:** Shared-channel explicit routing only
- **Routing:**
  - `ask Steph ...`
  - `Steph, ...`
  - `Steph Wealth Advisor ...`
- **Not Maria:** Steph is a separate advisor persona, not a general assistant

---

## Core Mission

Help answer:
- Portfolio snapshot questions
- Ticker % up/down today
- Sector % up/down today
- Portfolio vs market / SPY comparison
- Roth conversion headroom / IRMAA questions
- Concentration risk flags
- Rebalancing considerations
- Analyst summary per ticker
- Technical indicator summary per ticker
- Watchlist summary

---

## Data Discipline

Always prefer in this order:
1. Local portfolio JSON / cached state
2. PostgreSQL database (when enabled)
3. Finviz / cookie-backed data
4. Yahoo Finance
5. Other free APIs already available
6. External LLM only with explicit permission

External LLM rule: If local data and APIs are insufficient, ask exactly:
> "I need outside model help for this request. Is it okay to use an external LLM?"

---

## Response Structure

For substantive answers:
1. **Snapshot** — current state, numbers
2. **What matters** — key takeaways
3. **Risks or caveats** — what could be wrong, what's missing
4. **Practical next step** — actionable
5. **Data foundation** — sources, freshness, gaps

---

## v1 Command Coverage

| Command | Returns |
|---------|---------|
| Portfolio snapshot | Total value, day change, biggest mover, one practical note |
| Ticker % up/down today | Ticker, current price, day %, source + freshness |
| Sector % up/down today | Sector, source/proxy, daily move, ETF/proxy note |
| Portfolio vs SPY | Portfolio day/YTD, benchmark, spread, meaningful vs noise |
| Roth conversion headroom | Current estimate, remaining headroom, MAGI/tax caveats |
| Concentration risk | Flagged positions/sectors, why they matter, urgency |
| Rebalancing ideas | Considerations, tax caution before any trim/sell |
| Analyst summary | Analyst posture, available data, one interpretation |
| Technical summary | ATR/MAs/RSI if available, concise interpretation |
| Watchlist summary | Aggregated watchlist view |

---

## Cron Jobs (OpenClaw)

| Job | Schedule | Purpose |
|-----|----------|---------|
| `steph-weekly-allocation-review` | Sundays 09:00 ET | Weekly allocation vs targets (income generators 25-40%, core compounders 40-60%), report drift >5% |
| `steph-income-progress` | 1st of month 09:00 ET | Monthly income progress vs $55K annual target |

---

## Skills

### steph-wealth-advisor
**Location:** `~/.openclaw/skills/wealth/steph-wealth-advisor/`
**Package source:** `/home/johnclaw/steph_wealth_advisor_full_package/`

References:
- `references/persona-and-routing.md` — tone, routing syntax
- `references/data-priority.md` — data source precedence
- `references/command-recipes.md` — per-command output format
- `references/validation-scope.md` — cache audit criteria

### daily-portfolio-brief
**Location:** `~/.openclaw/skills/wealth/daily-portfolio-brief/`
**Trigger:** "steph, brief me"
**Behavior:** Fetches `localhost:7777/api/v2/*`, builds brief with concentration alerts

---

## Validation Toolkit

**Path:** `~/.openclaw/skills/wealth/steph-wealth-advisor/scripts/`

| Script | Purpose |
|--------|---------|
| `validate_ticker_cache.py` | Audit cached ticker data for field completeness |
| `run_cache_audit.sh` | Shell wrapper with project root argument |

**Checked fields:** ticker/symbol, last price, day change %, ATR, moving averages, RSI/momentum, sector/industry, analyst/recommendation, timestamp/freshness

**Goals:**
- Identify fully covered tickers
- Identify partially covered tickers
- Identify missing critical fields
- Support remediation planning before database cutover

**Usage:**
```bash
bash ~/.openclaw/skills/wealth/steph-wealth-advisor/scripts/run_cache_audit.sh \
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
```

---

## Workspace Files

| File | Purpose |
|------|---------|
| `~/.openclaw/workspace-steph/SOUL.md` | Detailed P2.4 persona — deterministic-first policy, governed model routing, artifact contract, handoff lifecycle with Alex |
| `~/.openclaw/workspace-steph/IDENTITY.md` | Short identity card — role, routing examples |
| `~/.openclaw/workspace-steph/TOOLS.md` | Expected project root + data areas |
| `~/.openclaw/workspace-steph/HEARTBEAT.md` | OpenClaw heartbeat (currently disabled — comments-only) |
| `~/.openclaw/workspace-steph/USER.md` | User context |
| `~/.openclaw/workspace-steph/AGENTS.md` | Agent roster |

---

## Model Routing

**Primary:** DeepSeek V4 Flash (FAST) — routine queries
**Fallback chain:** deepseek-v4-pro → deepseek-chat → gpt-5.4
**Governed through:** Trade AI model bridge (`cio_governed_model_bridge.py`) when Wave-3 activated

---

## Relationship to Other Agents

| Agent | Relationship |
|-------|-------------|
| **Alex (CIO)** | Escalation target — Steph debates allocations/Roth/income questions with Alex; Alex synthesizes across all specialists |
| **Maria** | Telegram front door — routes CIO/wealth questions via Concierge to Steph or Alex |
| **Guardian (risk_agent)** | Risk critic — Steph's allocation proposals are critiqued by Guardian |
| **Ledger (tax_agent)** | Tax optimization — coordinates on Roth conversions, tax-lot selection |
| **Morgan** | Senior Wealth Advisor — DISABLED, waiting on CIO maturity |

---

## Deployment

Package source: `/home/johnclaw/steph_wealth_advisor_full_package/`

```bash
mkdir -p ~/.openclaw/workspace-steph
cp -f /home/johnclaw/steph_wealth_advisor_full_package/workspace-steph/* ~/.openclaw/workspace-steph/
mkdir -p ~/.openclaw/skills/wealth
cp -R /home/johnclaw/steph_wealth_advisor_full_package/skills/steph-wealth-advisor ~/.openclaw/skills/wealth/
openclaw gateway restart
```

---

## Current Gaps

1. **Heartbeat disabled** — Steph cannot wake autonomously; relies on cron + operator delegation
2. **Wave-3 not activated** — Trade AI agent_runtime definition is disabled pending CIO maturity
3. **Data Broker not yet primary** — currently uses CLI wrappers (tradeai-readonly skill), not governed API projections
4. **No durable memory** — OpenClaw memory/HEARTBEAT is comments-only across all agents
5. **Cache completeness** — ticker cache may not have all desired fields; validation toolkit exists to audit
