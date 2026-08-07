# Trade AI Health Inspection System

**Last Updated:** 2026-08-07
**Version:** v3.0 (multi-layered health inspection with file integrity)

---

## Architecture Overview

The Trade AI Health Inspection System is a **10-layer defense-in-depth architecture** that monitors, diagnoses, and remediates staleness, failure, and degradation across the entire Trade AI data pipeline ecosystem. Each layer operates independently but escalates findings upward when its autonomous capabilities are exhausted.

```
LAYER 9:  File Integrity Verification (SHA-256 hashes, canonical paths)
LAYER 8:  Cross-Source Validation (Schwab, yfinance, Finviz quote triangulation)
LAYER 7:  Agent Watchdog (heartbeat monitoring, hung agent detection)
LAYER 6:  Self-Learning Engine (threshold tuning, remediation ranking, pattern discovery)
LAYER 5:  Claude Escalation (code-level findings, escalation queue)
LAYER 4:  health_agent.py (30+ component monitoring, auto-retry, pipeline output scanning)
LAYER 3:  MVL Vigil Agent (Shadow agent review freshness)
LAYER 2:  Hermes Health Inspector (Pipeline liveness, producer cadence)
LAYER 1:  OpenClaw tradeai-health-inspector (15-inspection sweep, runtime-aware remediation)
LAYER 0:  Stale Fixes (manual patch scripts, runbook-driven recovery)
```

---

## Layer 0: Stale Fixes & Runbook Recovery

The foundation layer provides documented recovery procedures for known failure modes.

**Configuration:** `config/runbooks/staleness_recovery.json`

Each runbook entry specifies:
- Failure type and severity (LOW/MEDIUM/HIGH/CRITICAL)
- Diagnostic steps to confirm the issue
- Remediation command (idempotent, safe to execute)
- Circuit breaker parameters (max retries, cooldown period)
- Expected runtime and verification step

**Key scripts:**
- `scripts/patch_live_cache.py` — Patches the live `trade_ai_cache.json` directly, clearing stale flags
- `~/.openclaw/skills/tradeai-health-inspect/scripts/patch_live_cache.py` — Runtime-aware version that patches the cache in the correct (live) directory

---

## Layer 1: OpenClaw Health Inspector Agent

The primary autonomous health watchdog. Runs every 15 minutes via OpenClaw scheduling.

**Agent identity:**
- Agent ID: `tradeai-health-inspector`
- Primary model: `deepseek/deepseek-v4-flash`
- Fallback models: `deepseek/deepseek-v4-pro` → `claude-cli/claude-sonnet-4-6`
- Max runtime: 600 seconds
- Max cost per run: $0.50 USD

**Agent files:**
| File | Purpose |
|------|---------|
| `~/.openclaw/agents/tradeai-health-inspector/agent/SOUL.md` | Agent personality, inspection checklist, remediation protocol, self-learning protocol |
| `~/.openclaw/agents/tradeai-health-inspector/agent/IDENTITY.md` | Access scopes, model configuration, endpoint details |

**Access scopes (IDENTITY.md):**

*Read-Only:*
- Trade AI API (localhost:7777): `/api/v2/health`, `/api/v2/system-health`, `/api/v2/health/remediation`
- Trade AI PostgreSQL: read-only user, all tables
- Trade AI logs, state files, config
- Hermes research intelligence table

*Execute (Safe Remediation Only):*
- Scripts listed in `config/runbooks/staleness_recovery.json` with risk=LOW or MEDIUM
- Must respect timeout and circuit breaker constraints

*Denied:*
- All broker commands, trade execution
- Config modification, secrets access, file deletion, crontab modification

**Inspection Pipeline (`inspect_all.py`):**

The master orchestrator runs 8 modules in sequence:

1. `check_runtime_awareness.py` — **ALWAYS FIRST**: Discovers live server PID, directory, cache paths
2. `check_site_display.py` — Validates what frontend actually displays (journal.last_close_date, repricing stamps, P&L plausibility)
3. `check_data_accuracy.py` — Cross-validates quotes (Finviz vs Schwab vs yfinance), portfolio values, API consistency, Telegram alert freshness
4. `check_db_freshness.py` — Checks DB timestamp freshness for all 22+ producers
5. `check_file_freshness.py` — Checks state file mtimes
6. `check_api_health.py` — Hits `/api/v2/health` and `/api/v2/system-health`
7. `check_agent_pipeline.py` — Checks Hermes, MVL, and LLM governance
8. `learning_cycle.py` — Post-sweep self-learning: adjusts thresholds, reorders remediation priorities, discovers new failure patterns

**Skill Manifest (`~/.openclaw/skills/tradeai-health-inspect/SKILL.md`):**

Declares the skill for the OpenClaw agent, listing all sub-scripts and invocation method.

---

## Layer 2: Hermes Health Inspector

Pipeline liveness monitoring integrated with the Hermes research intelligence system. Tracks producer cadence, detects silent failures, and feeds findings into the escalation queue.

---

## Layer 3: MVL Vigil Agent

Monitors the freshness of the 5 MVL SHADOW agents (Sentinel, Darwin, Iris, Archimedes, Vigil). Ensures each agent is producing reviews within its expected cadence.

---

## Layer 4: health_agent.py & system_health_agent.py

The workhorse execution integrity layer.

### health_agent.py

Monitors 30+ components across these categories:
- Pipeline Core (trade_ai_orchestrator, auto_proposal_generator, rotation_autopilot, incubator_promoter, finviz_screener, news_ingestion)
- Trade Monitoring (unified_stop_supervisor, protection_advisor, stop_drift_alert, alpaca_reconciler)
- Data Pipeline (finviz_enrichment, price_db_sync, rag_indexer, indicator_engine)
- Agents (aegis_morning_brief, telegram_command_handler)
- Cleanup & Governance
- TCA, LLM Backtesting, ATM, Proposals, Intelligence
- Quote Refresh, Portfolio Repricing, Journal Ingest

**Auto-Remediation Allowlist:**
The `run_auto_remediation()` function executes allowlisted fix scripts immediately for portfolio-pricing findings without waiting for escalation. Extended to include file integrity checks as a prerequisite before any patching.

### system_health_agent.py

Execution Integrity Agent that runs every 5 minutes (weekdays) / 15 minutes (weekends).

**Capabilities:**
- Schedule-aware staleness detection (uses cron expressions to avoid false positives on weekends/holidays)
- Lock contention monitoring (detects stale locks, zombie processes)
- Output validity scanning (Traceback, error signature detection)
- Auto-retry with single-flight safety (safe_flock gate prevents parallel recovery runs)
- Agent staleness detection and auto-queue remediation
- Portfolio price freshness alerts (Finviz authoritative quote layer)
- Pipeline output monitoring (proposal rate, signal generation, ATM execution, screener data quality)
- Safe_flock event analysis (detects repeated lock skips, parses JSONL event log)
- Escalation queue management (writes unresolved issues to `claude_escalation_queue.json`)

**Recent extensions:**
- File integrity verification checks integrated into the health check pipeline
- Cross-checks that the live server is reading canonical state files, not stale copies from old release directories

---

## Layer 5: Claude Escalation

Code-level findings that exceed Layer 4's auto-remediation capabilities are written to `data/runtime/claude_escalation_queue.json`. A Claude Code agent picks up these items and performs deeper investigation, including log analysis, code fixes, and architectural recommendations.

**Escalation triggers:**
- Failed retries that exhaust the max retry budget
- Critical components down with no retry command available
- Enrichment-failed proposals stuck after 3+ attempts
- New failure patterns that lack runbook entries

---

## Layer 6: Self-Learning Engine

The `HealthLearningEngine` (`scripts/lib/health_learning_engine.py`) makes the health inspection system self-improving over time.

**Three learning dimensions:**

1. **Threshold Self-Tuning**
   - Analyzes actual pipeline cadence from `hermes_research_intelligence`
   - Calculates average gap and P95 gap between runs
   - Recommends threshold adjustments when actual cadence differs from configured threshold
   - Stages adjustments in DB with confidence scores
   - Guardrails: floor at 30 minutes, max 1 adjustment per producer per day

2. **Remediation Priority Learning**
   - Tracks success rate for each remediation type
   - Ranks remediation strategies by `success_rate * (1 - 1/(total_attempts + 1))`
   - Future sweeps try highest-success-remediation first

3. **Pattern Discovery**
   - Finds correlated failures that co-occur within 1 hour
   - Uses LLM (Claude CLI primary, DeepSeek fallback) to analyze co-occurrence patterns
   - LLM determines: causal relationship, root cause hypothesis, suggested remediation
   - New patterns are staged as P3 (informational) until confirmed over 3+ sweeps

**Learning cycle output:**
- Persisted to `data/runtime/health_learning_history.jsonl`
- Learning state in `hermes_research_intelligence` — zero context loss across restarts

---

## Layer 7: Agent Watchdog

### Agent Heartbeat (`scripts/lib/agent_heartbeat.py`)

Emits liveness signals that the watchdog monitors:
- `register()` — Inserts/updates agent record in `agent_heartbeat` table (UPSERT)
- `heartbeat()` — Updates `last_seen` timestamp (called every 30 seconds)
- `mark_done()` — Marks completion with optional error tracking

### Agent Watchdog (`scripts/agent_watchdog.py`)

Runs every 5 minutes via cron. Detects hung/dead agents:
- Queries `agent_heartbeat` for agents unseen for >15 minutes
- Checks if process PID still exists
- Marks agents as HUNG
- Writes escalation to `staleness_escalation_queue.json` and `claude_escalation_queue.json`
- Severity: P1 for 15-30 min hung, P0 for >30 min hung

---

## Layer 8: Cross-Source Data Validation

### Quote Validator (`scripts/lib/quote_validator.py`)

Cross-references cached Finviz quotes against Schwab API and yfinance:
- Spot-checks 10 random symbols (or up to 50 if <50 total)
- Reports discrepancies >2% (P1 if >5%, P2 otherwise)
- Detects live cache vs dev cache staleness

### Portfolio Validator (`scripts/lib/portfolio_validator.py`)

Compares displayed portfolio values against broker data:
- Reads `/api/v2/risk` for displayed total value and P&L
- Reads `/api/v2/brokers/schwab/accounts` for broker values
- Flags discrepancies >1% (P0 if >3%, P1 otherwise)
- Flags P&L differences >$100

### Site Validator (`scripts/lib/site_validator.py`)

Validates API endpoints and Telegram alert flow:
- Checks 5 endpoints: trade-ai/summary, risk, health, system-health, scanner
- Detects stale data flags in API responses
- Monitors Telegram alert log freshness (>60 min stale = P1)

### Multi-Source Quote Refresh (`scripts/lib/multi_source_quote_refresh.py`)

Refreshes quotes when Finviz is stale:
- Source priority: Schwab API → yfinance fallback
- Refreshes if cache is older than `max_age_min` (default 15 min)
- Merges refreshed quotes into existing cache
- Handles symbol discovery from DB if cache is empty

---

## Layer 9: File Integrity Verification

**See dedicated documentation:** [docs/integrity-system.md](./integrity-system.md)

The file integrity system ensures the health agent never silently patches stale files from old release directories. It uses SHA-256 hash verification, canonical path enforcement, and stale copy detection.

**Key Principle: NEVER silently patch integrity violations.**

- Hash mismatch on canonical file → P0 alert, do NOT patch
- Server reading non-canonical file → P0 alert, fix server config
- Multiple copies of critical files → P1 alert, recommend cleanup
- File simply stale (old timestamp, hash matches) → safe to trigger refresh pipeline

---

## Runtime Awareness (`scripts/lib/runtime_awareness.py`)

A foundational library used by multiple layers to discover the live server environment:

**Discovery steps:**
1. Find process listening on port 7777 (via `ss -tlnp`)
2. Extract command line and working directory (via `/proc/PID/cwd`, `/proc/PID/cmdline`)
3. Locate the live cache file (`data/runtime/trade_ai_cache.json`)
4. Check systemd services and failed services
5. Detect dev/live directory mismatch

**Resolution API:**
- `get_live_directory()` — Returns the directory the live server is running from
- `resolve_path(relative_path)` — Resolves a path relative to live directory first, then dev directory
- `is_live_serving()` — Checks if the live endpoint responds

**This is the ALWAYS-FIRST step in every inspection sweep.** All subsequent checks use runtime-aware path resolution to ensure they're inspecting the correct files.

---

## Deployment

### Prerequisites
- Python 3.10+
- PostgreSQL with Trade AI schema
- OpenClaw installed at `~/.openclaw`
- Server running on port 7777

### File Integrity Manifest Generation

After every deployment, regenerate the integrity manifest:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python scripts/generate_integrity_manifest.py
```

To see what would change without writing:

```bash
.venv/bin/python scripts/generate_integrity_manifest.py --dry-run
```

To add a new file to the manifest:

```bash
.venv/bin/python scripts/generate_integrity_manifest.py \
  --add my_new_key data/path/to/file.json \
  --add-source my_pipeline.py \
  --add-max-age 60
```

### Running a Manual Health Check

```bash
# Full integrity check (human-readable)
python scripts/check_file_integrity.py

# Machine-readable JSON
python scripts/check_file_integrity.py --json

# Full OpenClaw sweep
python ~/.openclaw/skills/tradeai-health-inspect/scripts/inspect_all.py

# System health agent dry run
python scripts/system_health_agent.py --verbose

# System health agent active mode
python scripts/system_health_agent.py --apply --verbose
```

### Agent Watchdog Cron

```
*/5 * * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/agent_watchdog.py >> logs/agent_watchdog.log 2>&1
```

---

## Runbook Reference

Runbooks are stored at:
- `config/runbooks/staleness_recovery.json` — Primary runbook for all known failure modes
- `docs/runbooks/` — Human-readable runbook documentation
- Each runbook entry maps failure type → diagnostic → remediation → verification

---

## Key Design Principles

1. **Runtime Awareness First**: Never assume which directory the live server is running from. Discover it.
2. **NEVER Silently Patch**: If file integrity is violated, escalate. Don't cover up corruption.
3. **Defense in Depth**: 10 independent layers, each with escalating authority and scope.
4. **Self-Improving**: Thresholds adapt, remediation priorities update, new patterns are discovered.
5. **Circuit Breakers**: Every remediation has a retry limit and cooldown to prevent infinite loops.
6. **Schedule-Aware Staleness**: Jobs that only run on weekdays are not flagged on weekends. Holiday-aware via `market_session.is_trading_day`.
7. **Single-Flight Recovery**: All remediation runs through `safe_flock.sh` to prevent parallel recovery processes.
