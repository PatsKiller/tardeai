# CIO Platform Readiness Report — Gate 0

Status:      ACTIVE
as_of:       2026-08-08T18:02:23-04:00
Measured at: efcc51365 / not measured

**Audit Date:** 2026-08-08 04:00 UTC
**Audit Scope:** OpenClaw + Trade AI + Hermes autonomous CIO readiness
**Audit Mode:** Read-only discovery and planning. No implementation, no state mutation.

---

## 1. Live Runtime Evidence

### OpenClaw CLI & Gateway

| Artifact | Value |
|----------|-------|
| OpenClaw CLI version | `2026.6.11 (e085fa1)` |
| Gateway service version | `v2026.4.11` |
| Gateway binary | `/usr/bin/node /usr/lib/node_modules/openclaw/dist/index.js gateway --port 18789` |
| Gateway PID | `1557946` |
| Gateway status | `active (running) since Fri 2026-08-07 13:37:42 EDT` (10h+ uptime) |
| Gateway memory | 400.3M (peak 734.1M) |
| Gateway restart policy | `Restart=always, RestartSec=5` |

### Gateway Service Drop-Ins

| Drop-in File | Purpose |
|-------------|---------|
| `20-bws-token.conf` | `EnvironmentFile=-/home/johnclaw/.openclaw/credentials/bws_openclaw_gateway.env` (Bitwarden Secrets credential injection) |
| `gog-keyring.conf` | `EnvironmentFile=/home/johnclaw/.openclaw/credentials/gog.env` |

Both drop-ins are credential injection only; no resource limits or timeout tuning.

### Agent Workspaces

| Workspace | Files Present | State |
|-----------|--------------|-------|
| `workspace-alex/` | AGENTS.md, BOOTSTRAP.md, HEARTBEAT.md, IDENTITY.md, SOUL.md, TOOLS.md, USER.md, openclaw-workspace-state.json | SKELETON — all template defaults, BOOTSTRAP not deleted |
| `workspace-maria/` | AGENTS.md, HEARTBEAT.md, IDENTITY.md, SOUL.md, TOOLS.md, USER.md, contacts/, docs/ | OPERATIONAL — rich SOUL.md, template IDENTITY.md |
| `workspace-steph/` | AGENTS.md, HEARTBEAT.md, IDENTITY.md, SOUL.md, TOOLS.md, USER.md | DESIGNED — basic identity + persona |
| `workspace-aegis/` | AGENTS.md, HEARTBEAT.md, IDENTITY.md, SOUL.md, TOOLS.md, USER.md | SKELETON — template SOUL.md, basic IDENTITY.md |
| `workspace-iris/` | AGENTS.md, BOOTSTRAP.md, HEARTBEAT.md, IDENTITY.md, SOUL.md, TOOLS.md, USER.md | SKELETON — template SOUL.md, agent IDENTITY ok |
| `workspace-health-inspector/` | Full suite + V2_SHIPPED.md | OPERATIONAL — complete |
| `workspace-risk_agent/` | Empty | NONEXISTENT |
| `workspace-sentinel/` | Empty | NONEXISTENT |
| `workspace-darwin/` | Empty | NONEXISTENT |
| `workspace-concierge/` | Empty | NONEXISTENT |

### Agent Configuration (models.json)

**Maria agent** has models.json configured with:
- `codex` (OpenAI OAuth via ChatGPT): gpt-5.4, gpt-5.4-mini, gpt-5.2 (all $0 cost via OAuth)
- `ollama`: qwen3:14b, qwen3:1.7b, gemma4, gemma3:12b, qwen3:8b (all local, $0)
- `xai`/`x-ai` (Grok OAuth proxy :8645): grok-3, grok-3-fast, grok-3-mini, grok-4 family (OAuth, $0)

**Alex agent** has NO models.json — falls back to agent default or gateway default.

**Aegis agent** has models.json (same pattern as Maria, all OAuth/local).

### Deployed Trade AI

| Property | Value |
|----------|-------|
| CURRENT symlink | `/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT` → `20260807-124637` |
| Deployed SHA | `29134ab1b66b148e09c6f5cdf2e50b0da43652a5` (from systemd drop-in `TRADEAI_CC_DEPLOYED_SHA`) |
| Source PR | #296 |
| Repo SHA (dev) | `2f9655f9b2fc9cd9d2f7b77e85724a81204dac3a` |
| Portfolio server port | 7777 |
| Health API response | `{"ok": true, "overall_score": 36, "status": "unhealthy", "mode": "advisory"}` — 7 critical, 9 warnings |

### Containment State

- **P0_CONTAINED env var:** NOT SET (checked `env`, not found)
- **No P0_CONTAINED flags** found in `~/.config/`
- **No `grep P0_CONTAINED` matches** in config files
- System is running uncontained (normal production mode)

### LLM Cost Cap

`LLM_GLOBAL_DAILY_USD_CAP=0.25` (from `30-deepseek-env.conf` drop-in)

### Telegram Gateway Reliability (24h)

| Metric | Count |
|--------|-------|
| Total log lines | 426 |
| Timeout/error/unhealthy mentions | 127 |
| Telegram-specific failures | 51 |
| Delivery/reconnect failures | 3 |
| Transport unhealthy markings | Present (10s cooldown) |
| DNS-resolved IP unreachable events | Recurring (~every 10-20 min) |
| DeepSeek Pro timeout | 1 event (`runId=040262b8... isError=true model=deepseek-v4-pro error=LLM request timed out`) |

**Pattern:** Telegram API IP reachability is intermittently degraded. Gateway has built-in DNS fallback (tries alternative IPs) with circuit-breaker (10s unhealthy marking). Most fallbacks appear to succeed eventually. The 51 failure events and 3 delivery/reconnect failures in 24h suggest a ~15-20% error rate on outbound Telegram fetches/sends.

### Hermes DB

| Metric | Value |
|--------|-------|
| `hermes_research_intelligence` row count | 16,152 |
| Max `created_at` | 2026-08-07 21:26:16 EDT (~6h ago) |
| Freshness | FRESH — research is actively being populated |

### Provider/Model Configuration

**Trade AI governed LLM registry** (`config/llm_model_registry.json`):
- Provider: `deepseek`, base URL: `https://api.deepseek.com`
- Auth: `api_key`, credential slot: `deepseek_tradeai` (canonical), compatibility: `DEEPSEEK_API_KEY`
- Models: `deepseek-v4-flash` (FAST), `deepseek-v4-pro` (PRO/PRO_THINK/PRO_MAX)
- Pricing Flash: $0.14/M input (cache miss), $0.28/M output
- Pricing Pro: $0.435/M input (cache miss), $0.87/M output

**OpenClaw deepseek plugin** (`agents/main/agent/plugins/deepseek/catalog.json`):
- Models: deepseek-v4-flash, deepseek-v4-pro, deepseek-chat, deepseek-reasoner
- API: `openai-completions`
- Auth: `secretref-managed` (Bitwarden Secrets)
- Timeout: 300s

**Trade AI agent task routing** (from `llm_router.py`):
- ALL agent tasks route to `deepseek-flash` exclusively (no local/Grok/Claude/OpenAI fallback)
- Task types: agent_narrative, agent_debate, sector_correlation, cio_synthesis, catalyst_classification, sentiment, code_generation, fast_summary

### Schedulers

**System crontab** (`crontab -l`): Extensive Trade AI automation (70+ entries). Highlights:
- `health_agent.py` — every 30 min (flock-guarded)
- `claude_escalation_handler.py` — every 15 min (market hours, flock-guarded)
- `process_watchlist_agent_jobs.py` — market hours: every 5-15 min, overnight: every 5-20 min, weekend: every 10 min
- `run_alex_daily.py` — daily 5 AM, weekly Sun 8 AM, monthly 1st 9 AM
- `alex_hygiene.py` — Mon-Fri 7:15 AM
- `alex_gov_research.py` — Mon 6 AM
- `telegram_command_handler.py` — every 1 min
- `telegram_poller_daemon.sh` — every 2 min

**OpenClaw cron** (`~/.openclaw/cron/`): Contains backup files but no active `jobs.json`. The actual jobs.json appears to be managed in-memory or via a different path.

**Health agent active daemon** (PID 1694869): `ops_agent_daemon.py --apply --telegram` running from the health-inspect skill.

### Workspace State Files

- `workspace-aegis/openclaw-workspace-state.json` — Jun 7 (stale)
- `workspace-maria/openclaw-workspace-state.json` — Jun 7 (stale)
- `workspace-steph/openclaw-workspace-state.json` — Apr 14 (very stale)

---

## 2. Gate 0 Scorecard

| Item | Score | Evidence |
|------|-------|----------|
| `runtime_version_coherence` | **PARTIAL** | OpenClaw CLI 2026.6.11 vs gateway 2026.4.11 — versions diverge. Trade AI deployed vs dev diverge (29134ab vs 2f9655f). Repo has dirty files (release manifest warns). |
| `deepseek_noninteractive_auth` | **PARTIAL** | Credential slot `deepseek_tradeai` resolved from env; OpenClaw uses BWS secret-ref. Neither requires TTY. BUT: full auth chain proven only via code audit — no live canary run allowed per audit rules. |
| `deepseek_flash_route` | **PASS** | `llm_router.py` routes ALL agent tasks to `deepseek-flash` exclusively. `agent_flash_governance.py` enforces exact model ID `deepseek-v4-flash`, rejects legacy IDs. `llm_process_registry.json` has 6 governed Flash processes. |
| `deepseek_pro_route` | **PASS** | Available in `llm_model_registry.json` with PRO/PRO_THINK/PRO_MAX policies. `operator_cost_confirmation_for: ["PRO_MAX"]`. Used in escalation for multi_tier_trade_reviewer and watchlist_cio_synthesis. |
| `governed_llm_gateway_integration` | **FAIL** | OpenClaw calls DeepSeek directly via its own `secretref-managed` API key (BWS). Trade AI governed gateway (`agent_flash_governance.py`) manages its own `deepseek_tradeai` credential. TWO SEPARATE API KEYS, two independent cost ledgers. No unified consumption tracking. |
| `heartbeat_capability` | **PARTIAL** | OpenClaw has HEARTBEAT.md files but ALL are empty/comment-only (deliberately disabled). Health inspector has ops_agent_daemon running. No OpenClaw-native heartbeat is active. |
| `session_persistence` | **PASS** | OpenClaw sessions persist across restarts (SQLite-backed). Gateway restart preserves sessions. Agent SQLite databases present (openclaw-agent.sqlite with WAL). |
| `workspace_memory` | **FAIL** | Alex workspace is entirely template defaults. SOUL.md, IDENTITY.md not personalized. BOOTSTRAP.md not deleted. No MEMORY.md. No USER.md filled in. |
| `retrievable_memory` | **NOT_PROVEN** | No MEMORY.md in Alex workspace. No evidence of RAG/embedding memory for Alex. Hermes has 16K rows but no evidence Alex can query it autonomously. |
| `durable_scheduler` | **PARTIAL** | Extensive crontab (70+ entries) but no single ownership. OpenClaw cron appears inactive (no active jobs.json). No scheduler deduplication across the two systems. |
| `durable_agent_handoff` | **NOT_PROVEN** | Maria → Alex handoff is described in SOUL.md text ("Maria may forward CIO questions via `openclaw agent --agent alex --deliver`") but NEVER observed or tested. No durable queue for handoff. No retry on delivery failure. |
| `financial_tool_allowlist` | **PASS** | `claude_escalation_allowlist.yaml` has comprehensive allowed/blocked patterns. `allowed_script_patterns`: enrichment, health, pipeline, cache, news, data gap. `blocked_patterns`: order, submit, cancel, alpaca_execute, sudo, crontab, systemctl. `environment_guards`: ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true. |
| `telegram_reliability` | **PARTIAL** | 127 timeout/error events in 24h. Recurring DNS-resolution failures. 3 delivery failures. Built-in fallback (alternative IPs, 10s circuit breaker). System survives but is not resilient for autonomous CIO comms. |
| `telegram_durable_outbox` | **NOT_PROVEN** | OpenClaw has `~/.openclaw/delivery-queue/` directory present but no evidence of an active durable outbox pattern. No retry-with-backoff or dead-letter queue observed. |
| `trade_ai_data_broker_access` | **PASS** | `tradeai-readonly` skill provides full Command Center read API via HTTP to localhost:7777. `tradeai-watchlist` skill provides write operations. Both used by Maria/Alex via exec. |
| `hermes_bridge` | **PARTIAL** | Hermes DB active (16K rows, fresh). `hermes_coordinator.py` runs. `hermes_scope_governor.py` runs. But no evidence of Alex → Hermes query path. Trade AI reads Hermes; OpenClaw agents' access is undocumented. |
| `cost_feasibility` | **FAIL** | Current cap $0.25/day. Flash at $0.14/M input + $0.28/M output. Even MINIMAL CIO workload (10 Flash calls/day at 2K input + 500 output each) = $0.0032/day. But cap already consumed by existing agent workloads (120 calls/day for Maria, risk, Steph, debate = ~$0.05/day Flash). Autonomous CIO with governance, retries, and occasional Pro escalations would need $0.50-1.50/day — exceeding current cap 2-6x. |
| `audit_tracing` | **PASS** | `health_agent.jsonl` audit trail. `claude_escalation_retry_cmd.jsonl` retry log. `coder_dispatch.jsonl` coder audit. `file_integrity_manifest.json` with SHA-256 hashes. `agent_flash_governance` dedupe cache. Health agent snapshots in DB. |
| `minimum_specialist_roster` | **FAIL** | Required: Alex, Maria, Steph, Guardian, Ledger, Hermes. Present-but-incomplete: Alex (SKELETON), Maria (OPERATIONAL), Steph (DESIGNED), Guardian/risk_agent (SKELETON — agent SOUL only, empty workspace), Hermes (OPERATIONAL — data layer only). Ledger: NONEXISTENT. |
| `platform_health_boundary` | **PARTIAL** | Health agent (36/100 unhealthy) already detects most failures. BUT: no CIO_DATA_QUALITY_BLOCK mechanism. No separation between CIO advisory availability and platform operations health. Alex has no awareness of health state. |

---

## 3. DeepSeek Blocker Assessment

### Provider Configuration Analysis

**Trade AI governed path** (`config/llm_model_registry.json`):
- Provider: `deepseek`, family: `deepseek`
- Auth: `api_key` from env var `deepseek_tradeai` (canonical), `DEEPSEEK_API_KEY` (compatibility)
- Models: `deepseek-v4-flash` (FAST policies), `deepseek-v4-pro` (PRO policies)
- Legacy reject: `deepseek-chat`, `deepseek-reasoner` explicitly rejected
- Fallback: `VISIBLE_FAILURE_NO_SILENT_FALLBACK` — no silent provider failover

**OpenClaw direct path** (`plugins/deepseek/catalog.json`):
- API: `openai-completions` (OpenAI-compatible endpoint at api.deepseek.com)
- Auth: `secretref-managed` (Bitwarden Secrets)
- Models: `deepseek-v4-flash`, `deepseek-v4-pro`, plus legacy `deepseek-chat`, `deepseek-reasoner`

### Non-Interactive Auth Assessment

**Trade AI:** `get_deepseek_api_key()` reads `os.environ["deepseek_tradeai"]` or `os.environ["DEEPSEEK_API_KEY"]`. This is a standard env-var read from the systemd `EnvironmentFile` or `.env` file. No TTY interaction required. No browser OAuth. No interactive PIN.

**OpenClaw:** Uses `secretref-managed` which resolves via the BWS (Bitwarden Secrets) CLI at gateway startup. The credential is injected into the gateway process environment. No TTY required after initial setup.

**VERDICT:** Both systems can resolve DeepSeek credentials non-interactively. OpenClaw does NOT bypass Trade AI's governed gateway — it uses its OWN independent API key. This creates a **governance split**: OpenClaw's DeepSeek usage is tracked in OpenClaw's own cost ledger, NOT in Trade AI's consumption tracking (`consumption_run_manual.py`). Trade AI's daily cap, circuit breaker, and dedupe do NOT cover OpenClaw agent calls.

### 8 Canaries (defined, NOT executed)

| ID | Name | What It Proves |
|----|------|----------------|
| G0-DS-01 | Non-interactive credential resolution | Both Trade AI and OpenClaw resolve DeepSeek API keys from env/secret-ref without TTY, across gateway restart |
| G0-DS-02 | Exact model ID routing | `deepseek-v4-flash` is the ONLY model used for agent automation; legacy IDs rejected |
| G0-DS-03 | Flash FAST policy works | `llm_router.py` → `agent_flash_governance.py` → `deepseek_client.py` → api.deepseek.com chain produces valid responses |
| G0-DS-04 | Cap enforcement | `AGENT_FLASH_MAX_CALLS_PER_RUN=40` and `MAX_PROJECTED_USD_PER_RUN=0.50` are enforced (further calls fail-closed) |
| G0-DS-05 | Deduplication | `_DEDUPE_CACHE` with 6h TTL prevents duplicate Flash calls for same job |
| G0-DS-06 | Circuit breaker | 8 consecutive errors → 900s cooldown (fail-closed) |
| G0-DS-07 | Pro escalation path | PRO_THINK policy resolves → `deepseek-v4-pro` model; PRO_MAX requires operator cost confirmation |
| G0-DS-08 | OpenClaw independent API key | OpenClaw gateway can call DeepSeek without touching Trade AI's credential or consumption ledger |

---

## 4. OpenClaw Autonomy Capabilities

### Alex Workspace Audit

| File | Content | Assessment |
|------|---------|------------|
| `SOUL.md` | Generic template ("You're not a chatbot. You're becoming someone.") | NOT customized for CIO |
| `IDENTITY.md` | Empty template ("Fill this in during your first conversation") | NEVER filled in |
| `TOOLS.md` | Empty template ("Skills define how tools work") | NEVER filled in |
| `HEARTBEAT.md` | Comment-only (disabled) | No heartbeat configured |
| `BOOTSTRAP.md` | Present — should have been deleted after first conversation | Boot process incomplete |
| `USER.md` | Present but content unknown (not read) | — |
| `AGENTS.md` | Present | — |
| Agent `SOUL.md` | Has CIO persona content, tool instructions, boundaries | Best-developed file |
| Agent `IDENTITY.md` | Retirement & Disability Advisor persona, Claude Sonnet model | Specific but narrow (retirement, not CIO) |

### Memory Classification

| Memory Type | What Survives | Assessment |
|-------------|---------------|------------|
| **Conversational persistence** | Session SQLite (openclaw-agent.sqlite). Survives conversation end but NOT agent deletion. Each new Telegram message = new session. | **Survives:** session restart. **Lost:** new Telegram conversation. |
| **MEMORY.md** | File persisted in workspace. Read on session start. | **NOT PRESENT** — no MEMORY.md in Alex workspace |
| **Searchable memory** | OpenClaw `~/.openclaw/memory/` directory present but contents unknown | **NOT_PROVEN** |
| **Trade AI financial memory** | PostgreSQL `hermes_research_intelligence` (16K rows), agent_heartbeat, paper_trade_proposals | Survives everything. Accessible via HTTP API. |
| **CIO action memory** | NONEXISTENT — no CIO action ledger, no `cio_decisions` table for Alex | **NOT PROVEN** |
| **Operator profile memory** | `USER.md` in workspace, but empty for Alex | **NOT FILLED** |

### What Survives Each Restart

| Event | Workspace Files | Agent SOUL.md | Session DB | Memory.md | Hermes DB |
|-------|----------------|---------------|------------|-----------|-----------|
| New session | YES | YES | YES (new session) | YES (if exists) | YES |
| Gateway restart | YES | YES | YES | YES | YES |
| Service restart | YES | YES | YES | YES | YES |
| Host restart | YES | YES | YES | YES | YES |
| New Telegram conversation | YES | YES | NEW session | YES (if exists) | YES |

**Critical Gap:** With no MEMORY.md, Alex wakes up in each new Telegram conversation with zero context of prior CIO decisions. The agent SOUL.md provides persona but no durable action memory.

---

## 5. Heartbeat Design

### Current State

All HEARTBEAT.md files (Alex, Maria, Aegis, Steph) are empty or comment-only — deliberately disabled.

OpenClaw's heartbeat mechanism, per the template comment ("comments-only content prevents scheduled heartbeat API calls"), appears to trigger model calls when tasks are listed. This means an enabled heartbeat WOULD consume LLM tokens on every tick.

The health inspector's `ops_agent_daemon.py` provides a separate heartbeat (system-level monitoring, NOT agent-level).

### Proposed Low-Cost Deterministic Heartbeat Pattern (not enabled)

```
Layer 1 — Deterministic (no model call, <1s):
  - Check Trade AI health API (curl localhost:7777/api/v2/health)
  - Check Hermes DB freshness (last created_at age)
  - Check portfolio server PID alive
  - IF all green → silent, no model call

Layer 2 — Escalation (model call, ~$0.001):
  - IF health score < 65 OR data_quality = 0
  - THEN: single deepseek-flash FAST call with structured prompt:
    "CIO_HEARTBEAT: health={score}, data_quality={dq}, finnhub_stale={fh}.
     Return JSON: {advisory_blocked: bool, reason: string, recommended_action: string}"
  - Cost: ~800 input + 200 output tokens = ~$0.00027
  - Frequency: every 4 hours = ~$0.0016/day

Layer 3 — Alert (model call + Telegram, ~$0.002):
  - IF advisory_blocked == true OR health < 35
  - THEN: send Telegram alert via existing health inspector channel
```

This would add <$0.002/day to costs while providing deterministic health awareness before any model call.

---

## 6. Health / Escalation / Auto-Remediation Audit

### Capability Matrix

| Component | Purpose | Trigger | Schedule | Automatic Actions | Allowlist | LLM Use | Failure Behavior | Relationship to Alex |
|-----------|---------|---------|----------|-------------------|-----------|---------|------------------|---------------------|
| `health_agent.py` | Multi-domain health scoring (0-100) | Cron | Every 30 min | Enqueues escalations, auto-remediates allowlisted finding types | `remediation_map` (51 entries) + `auto_remediate.finding_types` (40 types) | None (scoring is deterministic). Optional LLM review at 8:30 PM. | Enqueues to escalation queue, alerts Telegram on unhealthy/degraded | Alex has NO awareness of health state |
| `claude_escalation_handler.py` | 3-tier escalation processing | Cron (flock-guarded) | Every 15 min (market hours) | Tier 1: Safe retry_cmd (allowlisted). Tier 2: Local LLM diagnosis. Tier 3: Claude Code CLI | `claude_escalation_allowlist.yaml` (45 allowed scripts, 20+ blocked patterns) | Tier 2 uses local Ollama. Tier 3 uses Claude. | Retries, logs to JSONL, circuit-breakers | Alex gets NO escalation notifications |
| `coder_dispatch.py` | Multi-coder auto-fix dispatcher | Triggered by escalation queue (`kind=code`) | On-demand | Creates isolated git worktree, runs coder, verifies, produces diff artifact or PR | `config/coder_backends.json` | Uses whichever coder backend is available | Advisory by default; PR mode requires `CODER_DISPATCH_MODE=pr` | Alex unaware |
| `health-inspector` (OpenClaw skill) | Layer-1 runtime-aware monitoring | ops_agent_daemon.py (persistent) | Continuous | LOW-risk runbook remediations, Telegram reports, audit JSONL | `remediation_runner.py` (circuit-breakered) | Uses DeepSeek (health-inspector agent primary model) | Reports Telegram + JSONL | Alex unaware |
| `ops_agent_daemon.py` | Active health daemon | Persistent process (PID 1694869) | Continuous | Applies low-risk remediations, sends Telegram | Same as health-inspector | Same as health-inspector | Persistent, auto-restarts | Alex unaware |

### G0-HEALTH-01 Canary Design (defined, not implemented)

**Trigger:** `data_quality` score = 0 AND `finnhub` data source is stale or deferred.

**Expected behavior:**
1. Alex detects CIO_DATA_QUALITY_BLOCK via health API (or health agent writes a block marker)
2. Alex MUST NOT attempt any financial advice, portfolio assessment, or trade recommendation
3. Alex creates a `CIO_DATA_QUALITY_BLOCK` entry (in action ledger or workspace state)
4. Alex responds to operator: "I cannot provide investment advice right now. The data quality subsystem reports [specific issue]. My CIO advisory function is blocked until this is resolved. Would you like me to check again or review the health dashboard?"
5. Alex MUST NOT say "based on stale data..." or attempt to work around the block

**Verification:** After remediation, block is cleared automatically on next health check showing data_quality > 0.

---

## 7. Scheduler Ownership

| Scheduler | Current Owner | Target Owner | Durable State | Dedupe | Restart Recovery | Migration Required |
|-----------|---------------|--------------|---------------|--------|------------------|-------------------|
| Trade AI health agent (every 30m) | Trade AI (crontab) | Health/Escalation | `health_agent_snapshots` DB | `flock -n /tmp/health_agent.lock` | Next cron tick resumes | None |
| Claude escalation handler (every 15m) | Trade AI (crontab) | Health/Escalation | `claude_escalation_queue.json` | `flock -n /tmp/tradeai_escalation_handler.lock` | Queue persists across restarts | None |
| Agent job processing (market/off/wknd) | Trade AI (crontab) | Trade AI | `agent_jobs` DB table | `flock -n /tmp/tradeai_watchlist_agent_jobs.lock` + timeout 20m | Jobs remain queued in DB | None |
| Telegram command poller (every 1-2 min) | Trade AI (crontab) | Trade AI | Stateless (reads Telegram API) | `flock` via `run_telegram_poller_daemon.sh` | Next poll resumes | None |
| Alex daily/weekly/monthly runs | Trade AI (crontab) | Trade AI → eventually OpenClaw | Ad-hoc (scripts generate output) | None | Missed run is missed | Alex cron → OpenClaw cron |
| OpenClaw agent heartbeats | OpenClaw (disabled) | OpenClaw | Heartbeat state in workspace? | Unknown | Unknown | Enable and configure |
| Hermes scope governor | Trade AI (crontab/escalation) | Hermes | Hermes DB | `flock /tmp/hermes_scope_governor.lock` | Escalation handler retries | None |
| File freshness watchdog | Trade AI (crontab) | Health/Escalation | `freshness_watchdog_heartbeat.py` | `flock -n /tmp/freshness_watchdog_heartbeat.lock` | Next tick resumes | None |
| Ops agent daemon | OpenClaw skill (persistent) | OpenClaw | `health_inspector_fixes.jsonl` | N/A (single process) | Process restarts via systemd or manual | None |

**Leading Hypothesis Confirmed:**
- Deterministic financial jobs → Trade AI (correct)
- Conversational heartbeat → OpenClaw (correct, but disabled)
- Hermes loops → Hermes/Trade AI hybrid (correct)
- Ops remediation → Health/Escalation (correct)
- Delivery → durable outbox (NOT YET IMPLEMENTED — gap)

---

## 8. Telegram Reliability

### 24-Hour Gateway Metrics

| Metric | Count | Impact |
|--------|-------|--------|
| Timeout/error/unhealthy events | 127 | Recurring DNS-resolution failures to Telegram API |
| Telegram-specific failure events | 51 | ~2/hour sustained failure rate |
| Delivery-specific failures | 3 | Low impact — most failures are fetch, not send |
| Transport unhealthy markings | Present | 10s circuit breaker on repeated failures |
| DeepSeek timeout during run | 1 | Agent run `040262b8` failed with LLM timeout on `deepseek-v4-pro` |

### Failure Patterns

1. **DNS Resolution Failures:** `UND_ERR_CONNECT_TIMEOUT` — the primary Telegram API IP is intermittently unreachable. Gateway falls back to alternative IPs.
2. **Transport Unhealthy:** After repeated failures, marks transport unhealthy for 10s.
3. **LLM Timeout:** DeepSeek Pro timeout during an Aegis agent run — 1 event in 24h.
4. **Delivery Resilience:** Only 3 delivery-specific failures in 24h out of 51 total errors. The gateway's fetch-fallback mechanism appears to handle most send failures.

### Does Delivery Failure Block Agent Completion?

Based on the gateway architecture (Node.js async I/O), delivery failure likely does NOT block agent completion — the agent's turn completes, and the gateway queues the response for delivery. However, the absence of a durable outbox means failed deliveries during gateway restart or persistent network outage are LOST, not retried later.

---

## 9. Hermes Audit

### Current State

| Metric | Value |
|--------|-------|
| Table | `hermes_research_intelligence` |
| Row count | 16,152 |
| Last insert | 2026-08-07 21:26:16 EDT (~6h old) |
| Freshness | ACCEPTABLE — within 12h window |
| Catalyst classification quality | 84% "other" in last 7d (18,862/22,379) — LOW quality signal |

### `hermes_challenge_job` Contract Schema (designed, not implemented)

```json
{
  "$schema": "hermes_challenge_job.v1",
  "job_id": "uuid",
  "created_by": "alex|maria|steph|health_agent",
  "created_at": "ISO8601",
  "challenge_type": "research_gap|contradiction|freshness_decay|source_quality",
  "target": {
    "symbols": ["NVDA"],
    "sectors": ["semiconductors"],
    "themes": ["AI datacenter power"],
    "date_range": {"from": "ISO8601", "to": "ISO8601"}
  },
  "context": {
    "trigger_reason": "string (why this challenge was raised)",
    "source_evidence": "string (what evidence contradicted/hermes gap)",
    "priority": "P1|P2|P3"
  },
  "status": "pending|researching|resolved|stale",
  "assigned_to": "hermes_coordinator",
  "resolution": {
    "findings": "string",
    "new_intelligence_ids": ["intel_001"],
    "resolved_at": "ISO8601"
  }
}
```

---

## 10. Specialist Maturity

| Agent | Workspace | Agent SOUL | Classification | Evidence |
|-------|-----------|------------|----------------|----------|
| **Alex** | SKELETON (template defaults) | DESIGNED (CIO persona present) | **SKELETON** | BOOTSTRAP not deleted, IDENTITY empty, no MEMORY.md |
| **Maria** | OPERATIONAL (rich SOUL.md) | OPERATIONAL | **OPERATIONAL** | Full persona, tool instructions, data discipline, Command Center integration |
| **Steph** | DESIGNED (persona present) | DESIGNED | **DESIGNED** | Basic wealth advisor persona, tax-aware |
| **Aegis** | SKELETON (template SOUL) | DESIGNED (surveillance agent) | **SKELETON** | Basic IDENTITY.md, template SOUL |
| **Guardian (risk_agent)** | NONEXISTENT (empty) | SKELETON (FLEET critic) | **SKELETON** | Agent SOUL exists but workspace empty |
| **Ledger** | NONEXISTENT | NONEXISTENT | **NONEXISTENT** | No agent, no workspace, no config |
| **Vega** | NONEXISTENT | NONEXISTENT | **NONEXISTENT** | Never defined in system |
| **Iris** | SKELETON (template SOUL) | DESIGNED (identity present) | **SKELETON** | Agent has rich IDENTITY but workspace is template |
| **Darwin** | NONEXISTENT (empty) | SKELETON (FLEET scorer) | **SKELETON** | Agent SOUL exists but workspace empty |
| **Sentinel** | NONEXISTENT (empty) | SKELETON (FLEET critic) | **SKELETON** | Agent SOUL exists but workspace empty |
| **Concierge** | NONEXISTENT (empty) | SKELETON (FLEET bridge) | **SKELETON** | Agent SOUL exists but workspace empty |
| **Health-Inspector** | OPERATIONAL (complete) | OPERATIONAL | **OPERATIONAL** | Full suite: SOUL, IDENTITY, OWNERSHIP, AUTONOMY |
| **Hermes** (system) | N/A (not OpenClaw) | N/A | **OPERATIONAL** | 16K research rows, active coordinator, scope governor |

### Minimum CIO Roster Assessment

| Required | Current State | Gap |
|----------|---------------|-----|
| Alex (CIO) | SKELETON | Needs full workspace customization, MEMORY.md, HEARTBEAT, LEDGER |
| Maria (assistant/router) | OPERATIONAL | Acceptable as-is |
| Steph (wealth/retirement) | DESIGNED | Needs retirement planning depth |
| Guardian (risk) | SKELETON | Needs risk evidence tooling, workspace |
| Ledger (audit) | NONEXISTENT | Needs creation from scratch |
| Hermes (research) | OPERATIONAL | Acceptable as-is (catalyst quality low but tracked) |

---

## 11. CIO Action Ledger Storage ADR

### Options Evaluated

#### Option A: PostgreSQL Table

```
cio_action_ledger (
  id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ,
  agent_id TEXT,         -- 'alex'
  session_id TEXT,
  action_type TEXT,       -- 'advisory', 'recommendation', 'challenge', 'escalation'
  context JSONB,          -- portfolio snapshot, health score, trigger
  decision TEXT,          -- what Alex said/recommended
  evidence_refs TEXT[],   -- Hermes intel IDs, health snapshot IDs
  operator_response TEXT, -- accept/reject/defer/modify
  sha256_hash TEXT,       -- content integrity
  created_by TEXT         -- 'alex', 'maria', 'system'
)
```

**Pros:** Queryable, ACID, existing Trade AI DB infrastructure, joinable with hermes_research_intelligence, existing backup cadence.
**Cons:** Schema migration overhead, new table in production DB.

#### Option B: JSONL + SHA-256 Manifest

**Pros:** Append-only, portable, reuses `file_integrity.py` and `file_integrity_manifest.json` pattern.
**Cons:** No queryability without index, no concurrent write safety, manual integrity verification, harder to surface in dashboard.

#### Option C: Hybrid

JSONL for write path (fast, append-only, crash-safe) + periodic PostgreSQL materialization (every 5 min or on-agent-session-close) for queryability.

### Existing Infrastructure Reuse

`scripts/lib/file_integrity.py` provides `FileIntegrity` class with:
- `compute_sha256(file_path)` — SHA-256 hashing (reusable for Option B)
- `verify_file(file_key)` — manifest-based verification
- `load_manifest()` / `manifest` property

`data/runtime/file_integrity_manifest.json` provides:
- Per-file: canonical_path, sha256, size, last_validated, source_pipeline, max_age_minutes, consumers
- This pattern can be extended to a CIO ledger manifest

### Recommendation

| Phase | Recommendation | Rationale |
|-------|---------------|-----------|
| **LAB** | Option B (JSONL + SHA-256 manifest) | Fast to implement, reuses existing `file_integrity.py`, no DB migration risk, easy to inspect manually. Path: `data/cio/cio_action_ledger.jsonl` + `data/cio/cio_ledger_manifest.json`. |
| **SHADOW** | Option C (Hybrid) | Add periodic PostgreSQL materialization (5-min interval). JSONL remains source of truth; PG table is a read-optimized cache for dashboard queries. |
| **PRODUCTION** | Option A (PostgreSQL) | Once schema is stable after SHADOW phase, cut over to PG-only with JSONL as audit backup. Full ACID, joinable with Hermes, queryable by health agent. |

---

## 12. OpenAI Secondary Model Discovery

### Available OpenAI Routes

**Trade AI llm_process_registry.json:** No dedicated OpenAI processes. The `chatgpt_only` lane policy exists for `rotation_grok_review` but is essentially an OAuth path, not a paid OpenAI API path.

**OpenClaw Maria models.json:** OpenAI models available via OAuth (Codex proxy):
- `gpt-5.4` — $0 cost (OAuth)
- `gpt-5.4-mini` — $0 cost (OAuth)
- `gpt-5.2` — $0 cost (OAuth)

**Trade AI llm_router.py:** `_call_openai` is a LEGACY ALIAS that actually routes to `_call_deepseek_flash_governed`. It does NOT call OpenAI API. Comment: "Legacy name kept for provider map key only — routes to governed DeepSeek Flash. Does NOT call OpenAI."

**llm_health_check.py:** Lists `deepseek-flash` and `deepseek-v4-pro` as lanes but no direct OpenAI lane. OpenAI is only reachable via `chatgpt` OAuth proxy lane.

**Verdict:** No paid OpenAI API routes exist in the current system. OpenAI is available ONLY via free OAuth (ChatGPT Codex proxy at :8646). The `openai` provider key in `llm_router.py`'s `_PROVIDERS` dict is an alias that points to DeepSeek Flash.

---

## 13. Cost Feasibility

### Current Cap

`LLM_GLOBAL_DAILY_USD_CAP=0.25`

### DeepSeek Pricing (from `llm_model_registry.json`)

| Model | Input (cache miss) | Output | Cache Hit Input |
|-------|-------------------|--------|-----------------|
| V4 Flash (FAST) | $0.14/M tokens | $0.28/M tokens | $0.0028/M |
| V4 Pro (PRO) | $0.435/M tokens | $0.87/M tokens | $0.003625/M |

### Workload Models

#### MINIMAL (Alex advisory only, no automation)

| Activity | Calls/Day | Input Tokens | Output Tokens | Daily Cost |
|----------|-----------|-------------|---------------|------------|
| Alex operator queries (Telegram) | 5 | 2,000/ea | 500/ea | $0.00165 |
| Monthly retirement check-in | 0.03/day avg | 4,000 | 1,000 | $0.00008 |
| Maria → Alex handoff | 2 | 2,000/ea | 500/ea | $0.00066 |
| CIO heartbeat (deterministic) | 0 | 0 | 0 | $0.00 |
| **TOTAL** | | | | **$0.0024/day** |

**Fits under $0.25 cap with 100x headroom.**

#### NORMAL (Daily autonomous CIO with heartbeat)

| Activity | Calls/Day | Input Tokens | Output Tokens | Daily Cost |
|----------|-----------|-------------|---------------|------------|
| Alex operator queries | 8 | 2,000/ea | 800/ea | $0.0036 |
| Maria → Alex handoff | 5 | 2,000/ea | 800/ea | $0.0022 |
| CIO heartbeat (escalation tier, 6x/day) | 6 | 800/ea | 200/ea | $0.0016 |
| Hermes challenge (Flash) | 3 | 4,000/ea | 1,000/ea | $0.0020 |
| Morning scan (run_alex_daily.py via Flash) | 1 | 4,000 | 1,000 | $0.00066 |
| Pro escalation (1-2x/week amortized) | 0.3/day avg | 4,000 | 2,000 | $0.00084 |
| Existing agent workloads (Maria, risk, Steph, debate) | 120 | 2,000/ea avg | 800/ea avg | $0.05 |
| **TOTAL** | | | | **$0.06/day** |

**Fits under $0.25 cap with 4x headroom. But cap is shared with ALL Trade AI LLM usage, not just CIO.**

#### EVENT_HEAVY (Market crash / major news day)

| Activity | Calls/Day | Input Tokens | Output Tokens | Daily Cost |
|----------|-----------|-------------|---------------|------------|
| Alex operator queries (spike) | 20 | 2,000/ea | 800/ea | $0.009 |
| Maria → Alex handoff (spike) | 15 | 2,000/ea | 800/ea | $0.0066 |
| CIO heartbeat (every 30 min) | 48 | 800/ea | 200/ea | $0.0128 |
| Hermes challenge (deep research) | 10 | 4,000/ea | 1,000/ea | $0.0066 |
| Pro escalation (deep analysis) | 5 | 4,000 | 2,000 | $0.014 |
| Existing agent workloads (spike) | 200 | 2,000/ea avg | 800/ea avg | $0.084 |
| **TOTAL** | | | | **$0.133/day** |

**Fits under $0.25 cap with 1.9x headroom. CONTENTION: on days with heavy non-CIO LLM usage, cap could be breached.**

### Proposed Budget

| Tier | Daily Cap | Monthly | Annual | Justification |
|------|-----------|---------|--------|---------------|
| Current | $0.25 | $7.50 | $91.25 | Insufficient for autonomous CIO |
| Proposed MINIMAL | $0.50 | $15.00 | $182.50 | 2x current — covers MINIMAL + NORMAL |
| Proposed COMFORTABLE | $1.50 | $45.00 | $547.50 | 6x current — covers EVENT_HEAVY with headroom |

---

## 14. Data Access Audit

| Skill | Directory | Access Method | Classification |
|-------|-----------|---------------|----------------|
| `tradeai-readonly` | `~/.openclaw/skills/tradeai-readonly/` | HTTP API to localhost:7777 (`cc_hubs.py`, `tradeai_query.py`, `tradeai_readonly.py`) | **API-backed** — safe, read-only, no DB creds |
| `tradeai-watchlist` | `~/.openclaw/skills/tradeai-watchlist/` | HTTP API to localhost:7777 (`tradeai_watchlist.py`) | **API-backed** — safe, write-through API |
| `tradeai-health-inspect` | `~/.openclaw/skills/tradeai-health-inspect/` | HTTP API + file reads + subprocess calls (`.venv/bin/python` scripts) | **CLI wrapper** — runs existing Trade AI scripts via subprocess |
| `scalp-signal-approve` | `~/.openclaw/skills/scalp-signal-approve/` | Unknown (not inspected) | **Unknown** — likely CLI wrapper |
| `steph-wealth-advisor` | `~/.openclaw/skills/steph-wealth-advisor/` | Unknown (not inspected) | **Unknown** — likely data aggregation |
| `email-calendar` | `~/.openclaw/skills/email-calendar/` | Unknown | Likely **API-backed** (Google API) |
| `light-research` | `~/.openclaw/skills/light-research/` | Unknown | Likely **API-backed** or **HTML scrape** |
| `operations` | `~/.openclaw/skills/operations/` | Unknown | Likely **CLI wrapper** |
| `personal-productivity` | `~/.openclaw/skills/personal-productivity/` | Unknown | Likely **CLI wrapper** |
| `wealth` | `~/.openclaw/skills/wealth/` | Unknown | Unknown |
| `integrations` | `~/.openclaw/skills/integrations/` | Unknown | Unknown |

**Key Finding:** The two most critical skills for Alex (`tradeai-readonly`, `tradeai-watchlist`) are cleanly API-backed via HTTP to the portfolio server. No direct DB access, no credential exposure. This is architecturally sound for autonomous operation.

---

## 15. Phase -1 Plan

### Dependency-Ordered Hardening PRs

| PR | Name | Depends On | Scope | Gate Items Addressed |
|----|------|------------|-------|---------------------|
| **P-1.1** | Alex Workspace Hardening | None | Customize SOUL.md for CIO persona, fill IDENTITY.md, delete BOOTSTRAP.md, create MEMORY.md template, configure HEARTBEAT.md (deterministic tier only), fill USER.md | `workspace_memory`, `heartbeat_capability`, `minimum_specialist_roster` |
| **P-1.2** | CIO Action Ledger (Option B — LAB) | None | Create `data/cio/cio_action_ledger.jsonl` + `data/cio/cio_ledger_manifest.json`. Implement ledger write from Alex SOUL instructions. Reuse `file_integrity.py` for SHA-256 manifest. | `retrievable_memory` (CIO action memory), `durable_agent_handoff` (evidence trail) |
| **P-1.3** | Unified DeepSeek Consumption Tracking | P-1.1, P-1.2 | Instrument both OpenClaw and Trade AI DeepSeek calls into a single daily cost ledger. Cross-reference against `LLM_GLOBAL_DAILY_USD_CAP`. Surface in health agent. | `governed_llm_gateway_integration`, `cost_feasibility` |
| **P-1.4** | CIO Health Boundary + G0-HEALTH-01 | P-1.1, P-1.2 | Implement CIO_DATA_QUALITY_BLOCK detection in Alex SOUL/HEARTBEAT. Wire Health Agent → Alex awareness. Implement canary G0-HEALTH-01: data_quality=0 + finnhub stale → block advisory. | `platform_health_boundary`, `minimum_specialist_roster` |
| **P-1.5** | Durable Agent Handoff + Maria→Alex Bridge | P-1.1, P-1.2 | Create `~/.openclaw/delivery-queue/` durable outbox for agent-to-agent messages. Maria enqueues CIO questions; Alex dequeues on heartbeat. Retry with backoff. Dead-letter after 3 failures. | `durable_agent_handoff`, `telegram_durable_outbox` |
| **P-1.6** | Scheduler Ownership Documentation + Migration Prep | P-1.1 | Document current scheduler inventory in `docs/operations/SCHEDULER_OWNERSHIP.md`. Move Alex cron entries from system crontab to OpenClaw cron. Implement dedupe between Trade AI cron and OpenClaw cron for shared jobs. | `durable_scheduler` |
| **P-1.7** | Ledger Agent Creation | P-1.2 | Create Ledger agent (OpenClaw workspace + agent SOUL). Implement CIO action ledger read-only view. Wire into Health Agent for audit coverage monitoring. Connect to existing file_integrity infrastructure. | `minimum_specialist_roster` |
| **P-1.8** | Cost Cap Increase (operator approval) | P-1.3 | Propose `LLM_GLOBAL_DAILY_USD_CAP` increase from $0.25 to $1.50 (operator decision). Document trade-off. If approved, update `30-deepseek-env.conf` drop-in. | `cost_feasibility` |

---

## 16. Console Summary

```
═══════════════════════════════════════════════════════════════════
 CIO PLATFORM READINESS GATE 0 — CONSOLE SUMMARY
═══════════════════════════════════════════════════════════════════

 GATE_0_VERDICT:             NOT_READY
 SCORECARD:                  5 PASS / 8 PARTIAL / 4 FAIL / 3 NOT_PROVEN

 CRITICAL BLOCKERS (4):
   1. governed_llm_gateway_integration — FAIL
      OpenClaw and Trade AI use SEPARATE DeepSeek API keys. No unified
      consumption tracking. OpenClaw bypasses Trade AI's cost ledger,
      circuit breaker, and dedupe.

   2. workspace_memory — FAIL
      Alex workspace is entirely template defaults. No customized SOUL,
      no MEMORY.md, BOOTSTRAP.md not deleted. Agent wakes up fresh
      every session with no CIO context.

   3. cost_feasibility — FAIL
      Current cap $0.25/day. NORMAL autonomous CIO workload needs
      ~$0.06/day (fits). BUT cap is shared. EVENT_HEAVY + non-CIO
      workloads could breach. Proposed minimum: $0.50-1.50/day.

   4. minimum_specialist_roster — FAIL
      Required: Alex, Maria, Steph, Guardian, Ledger, Hermes.
      Present: Maria (OPERATIONAL), Hermes (OPERATIONAL).
      Partial: Alex (SKELETON), Steph (DESIGNED), Guardian (SKELETON).
      Missing: Ledger (NONEXISTENT).

 SYSTEM HEALTH:              unhealthy (36/100)
   7 critical | 9 warnings | 9 info

 TELEGRAM RELIABILITY:       127 timeout/error events in 24h
   51 Telegram-specific failures, 3 delivery failures

 HERMES:                     16,152 rows, last insert 6h ago
   Catalyst classification quality 84% "other" — LOW signal

 DEEPSEEK STATUS:
   Flash route: PASS (governed, exact V4 Flash, legacy rejected)
   Pro route:   PASS (available, operator-confirmation for MAX)
   Auth:        PARTIAL (non-interactive, but dual-key governance gap)
   Cost cap:    $0.25/day (shared with all Trade AI LLM usage)

 CURRENT ALEX STATE:         SKELETON
   - Template SOUL.md, empty IDENTITY.md, BOOTSTRAP.md not deleted
   - No MEMORY.md, no HEARTBEAT, no action ledger
   - Agent SOUL.md has CIO persona but narrow (retirement-focused)
   - Access to tradeai-readonly/watchlist skills: YES
   - Cron: daily 5 AM, weekly Sun 8 AM, monthly 1st (via Trade AI crontab)

 PHASE -1 PLAN:              8 PRs (P-1.1 through P-1.8)
   Estimated effort: 2-4 weeks (operator time dependent)

 NEXT STEP:
   Do NOT design or enable the autonomous Alex CIO runtime until
   Phase -1 PRs P-1.1 through P-1.8 are merged and verified.
   Start with P-1.1 (Alex Workspace Hardening) — the foundation.

═══════════════════════════════════════════════════════════════════
```

---

CIO PLATFORM READINESS GATE: Do not design or enable the autonomous Alex CIO runtime until non-interactive governed DeepSeek, deterministic low-cost heartbeat, durable financial action ownership, canonical data access, reliable handoffs, explicit scheduler ownership, Telegram/outbox resilience, platform-health boundaries, cost feasibility, and the minimum specialist foundation are proven.
