# Health Agent + Multi-Coder Auto-Fix

_Last updated: 2026-06-22_

A centralized, proactive health layer that sits **on top of** the existing fragmented monitors and turns
their scattered signals into a single score, proactive trend detection, and bounded auto-remediation —
including routing code-level defects to AI coders (Claude Code, Cursor, Grok, ChatGPT/Codex, …).

## Why

The system already had strong but fragmented monitors (`system_health_agent.py` execution-integrity,
`pipeline_watchdog.py`, stop/protection monitors, freshness monitors) and an escalation→LLM→Claude Code
loop (`claude_escalation_handler.py`). What was missing: a **single health score**, a **category
breakdown**, **predictive trends**, a **dashboard**, and a **multi-coder** (not just Claude Code) fix lane.
This adds exactly those, reusing the existing escalation queue rather than duplicating it.

## Components

| Piece | File | Role |
|---|---|---|
| Health Agent | `scripts/health_agent.py` | Aggregate → score (0–100) → trends → enqueue escalations → alert |
| Policy | `config/health_agent_policy.json` | Weights, penalties, thresholds, mode, remediation map (DB-overridable) |
| Coder dispatcher | `scripts/coder_dispatch.py` | Route a code-fix to one AI coder in a worktree → verify → PR/advisory diff |
| Backend registry | `config/coder_backends.json` | Every coder wired (available or dormant), routing map |
| API | `scripts/api_v2.py` | `/api/v2/health`, `/api/v2/health/history`, `/api/v2/health/coders` |
| Dashboard | `apps/command-center-v3/src/pages/HealthHub.tsx` | Score hero, categories, findings, trends, coders, history |
| Schedule | `scripts/install_health_agent_cron.sh` + `config/systemd/tradeai-health-agent.{service,timer}` | Cron every 30 min (`health_agent_cron.log`); coder-dispatch advisory every 3h weekdays |
| Execution integrity (cron liveness) | `scripts/system_health_agent.py` | Every 5 min weekdays — log freshness per registered cron, including portfolio repricer |

## Health score

Five categories, each scored from 100 down by penalties (critical −40, warning −15, info −5), then a
weighted overall. Weights/penalties/thresholds live in `config/health_agent_policy.json`.

| Category | Weight | Signals |
|---|---|---|
| Data Quality | 0.25 | holdings/risk/dividends/news/CIO/agent-job freshness + open data gaps + **portfolio Finviz price freshness** (market hours) |
| Execution Health | 0.25 | pipeline failures, stuck agent jobs, critical execution escalations, orphaned stops, **options proposal staleness/volume**, **options desk infra** (chain-snapshot retention + approval-queue backlog) |
| Intelligence Quality | 0.20 | local LLM reachability, ensemble failures, stale research backlog |
| Risk Protection | 0.20 | unprotected positions, stops in alert, recent P0/P1 SIEM |
| Retirement Planning | 0.10 | Golden Window present, dividend income consistency, calendar freshness |

Status bands: **healthy ≥ 85**, **degraded ≥ 65**, else **unhealthy**.

Outputs every run: DB table `health_agent_snapshots` (append-only history → trends + dashboard),
`data/portfolios/state/health_agent_status.json` (fast read), `logs/health_agent.jsonl` (audit trace).

## Proactive trends

On each run the agent compares the last `trend.lookback_runs` (default 3) snapshots. It flags an overall
drop ≥ `trend.drop_alert_points` (default 10) and any category declining monotonically across the window —
so a slow degradation escalates **before** it breaks.

## Remediation lanes (advisory by default)

1. **Safe retry** — data findings (e.g. `news_stale`, `data_gaps_open`) are enqueued with an allowlisted
   `retry_cmd` into `logs/claude_escalation_queue.json`. `claude_escalation_handler.py` (existing cron)
   runs them in tier-1. Allowlist: `config/claude_escalation_allowlist.yaml`.
2. **Local LLM diagnosis** — the existing handler's tier-2 (gemma3:4b) diagnoses fixable items.
3. **Multi-coder code fix** — findings tagged `needs_code_fix` (kind = code/single_file/multi_file/schema)
   are routed by `coder_dispatch.py` to an AI coder. **Worktree → verify → advisory diff or PR.**

All decisions are audited (DB `coder_dispatch_audit` + `logs/coder_dispatch.jsonl`) with a reasoning trace.
Bounded: `CODER_DISPATCH_MAX_PER_RUN` (default 2), `CODER_DISPATCH_DAILY_CAP` (default 6).

## Multi-coder dispatch — "what fits what"

The router picks **one** backend per problem: it walks the preference list for the problem's `kind` and
takes the first **available** (installed CLI / responding proxy) backend. Edit `routing` in
`config/coder_backends.json` to change it.

| Problem kind | Preferred order → active today |
|---|---|
| `multi_file` | Claude Code → Cursor → Codex → Aider |
| `single_file` | Cursor → Grok CLI → ChatGPT/Codex → Grok proxy → Claude Code |
| `schema` | Claude Code → Cursor |
| `ui` | Cursor → Claude Code |
| `_default` | Claude Code → Cursor → Grok → ChatGPT/Codex → Grok proxy → Codex → Aider |

Backends wired (every one is in the registry even if not installed — drop the binary in and it activates):
Claude Code (`claude`), Cursor (`cursor-agent`), Grok CLI (`grok`), ChatGPT/Codex proxy (:8646),
Grok proxy (:8645), Codex CLI (dormant: `npm i -g @openai/codex`), Aider (dormant: `pipx install aider-chat`).

### Apply model (locked with operator)

Isolated git **worktree → run verify gate → PR**. Never edits the working tree or `main` directly.
- **advisory** (default): saves a review diff to `logs/coder_dispatch_diffs/`, discards the branch.
- **pr**: pushes the branch and opens a PR via `gh`. Enable with `CODER_DISPATCH_MODE=pr`.

Verify gate: `py_compile` on every changed `.py`, plus an optional `test_cmd` from the registry/env.

## Usage

```bash
# Health Agent
.venv/bin/python scripts/health_agent.py                 # compute + persist + alert
.venv/bin/python scripts/health_agent.py --json          # print snapshot
.venv/bin/python scripts/health_agent.py --no-enqueue --no-alert

# Coder dispatch
.venv/bin/python scripts/coder_dispatch.py --list-backends
.venv/bin/python scripts/coder_dispatch.py --problem "Fix X in scripts/y.py" --kind single_file        # plan only
.venv/bin/python scripts/coder_dispatch.py --problem "..." --apply                                     # advisory diff
CODER_DISPATCH_MODE=pr .venv/bin/python scripts/coder_dispatch.py --from-queue --apply                  # open PRs
```

API: `GET /api/v2/health`, `GET /api/v2/health/history`, `GET /api/v2/health/coders`.
Dashboard: Command Center → **Health** hub (Overview / Coders / History; tooltips throughout).

## Safety

- Advisory by default for high-risk actions; code fixes never land on `main` without a PR + human merge.
- Bounded loops (per-run + daily caps); every decision audited with a reasoning trace.
- Free-lane LLM only for routine health work (Ollama / OAuth proxies); no metered calls.
- The verify gate must pass before any PR. Worktrees are isolated and auto-cleaned.

## Portfolio price monitoring (2026-06-22)

**Problem:** `holdings.json` file mtime stays fresh when SnapTrade sync runs, even if Finviz prices are
hours stale. Proposal `proactive_quote_refresh` is a different pipeline — it does not protect Command
Center portfolio cards.

**Fix (two layers):**

1. **`system_health_agent.py`** — registers cron liveness for:
   - `portfolio_repricer_intraday` → `logs/portfolio_repricer_intraday.log` (`*/15 9-16` + `5 9` ET)
   - `portfolio_repricer_postclose` → `logs/portfolio_repricer_postclose.log` (`10 16` ET)
   - `market_quotes_intraday` → `logs/market_data.log`
   - `snaptrade_sync` → positions/basis only (not prices)
   - During market hours: checks `finviz_quote_cache._meta.last_fetched` and `holdings.last_repriced`

2. **`health_agent.py`** — `portfolio_price_freshness` policy block flags stale cache/repriced timestamps
   and enqueues `portfolio_repricer.py` / `external_market_data_ingest.py --quotes` via remediation_map.

Install cron: `bash scripts/install_health_agent_cron.sh` (was comment-only in crontab before 2026-06-22).

## Options desk infra monitoring (2026-06-26)

**Problem:** `collect_proposal_maturity` watched options *output* (cache staleness, zero/ignored
proposals) but nothing watched the enterprise desk *infrastructure* — the vol-surface snapshot table
silently growing if retention regressed, or the operator approval queue backing up and blocking the
live path.

**Fix:** `collect_options_desk_health()` (`health_agent.py`, category `execution_health`) adds two
cheap DB-aggregate checks:

1. **Snapshot retention** — `options_chain_snapshots` oldest-row age vs
   `OPTIONS_SNAPSHOT_RETENTION_DAYS` (45) + `snapshot_grace_days` (7) → `options_snapshot_retention_stale`;
   row count vs `snapshot_row_warn` (50k) → `options_snapshot_table_bloat`.
2. **Approval queue** — **pending** count vs `approval_backlog_warn` (15) →
   `options_approval_backlog` (a genuine operator-review lag). Auto-gated **blocked** items
   (illiquid/earnings) aren't operator-actionable, so they get a separate softer info signal,
   `options_approval_blocked_pileup`, at `blocked_pileup_warn` (30) — not the warning. Pending
   past 24h `expires_at` → `options_approval_expired_pending`.

Thresholds live under the `options_desk` policy block. Findings carry `WHY` hints and route as
`refresh` (retention) / `review` (queue).

## Infra failure-class monitoring (2026-07-04)

**Problem (July 4 incident set):** four failure classes ran blind — (1) the scope governor died
every run for 6.5h (16MB `outcome_bus.json` re-parsed per symbol inside an open transaction →
PG `idle_in_transaction_session_timeout=120s` killed the connection); (2) decision-feeding
`watchlist_agent_jobs` (`full_analysis` etc.) were starved for 2+ days because the worker ordered
by symbol tier only, so a continuous `scheduled_research` stream on high-ranked symbols always won;
(3) the Finviz cookie expiry only surfaced as a suppressed Telegram digest line (`data_source_health`
had no consumer); (4) `tradeai-continuous.service` failed at boot (persistent-timer catch-up before
/home was ready) and nothing watched failed units.

**Fix:**

1. **SLA-aware job ordering** — `sql_request_type_sla_case()` in `lib/watchlist_priority.py`
   (canonical `TIME_SENSITIVE_REQUEST_TYPES`, shared with the `agent_jobs_stuck` check) prepends a
   decision-feeding-first class to the worker's ORDER BY. Background research still drains by
   symbol tier below it.
2. **Governor hardening** — mtime-cached bus feedback index (`hermes_scope_governor/outcome_bus.py`)
   + `conn.commit()` before the pure-Python decision loop (engine). Run time: ~6 min → ~1.3s.
   Remediation: `hermes_scope_governor_stale` / `_heartbeat_missing` / `_last_run_failed` →
   immediate `safe_flock` re-run (auto_remediate + remediation_map + both allowlists).
3. **`collect_data_source_health()`** (category `data_quality`) — consumes `data_source_health`
   staleness vs `max_stale_minutes`; weekend = info + `[weekend]` per house convention. When
   finviz is stale it live-validates the cookie (`credential_monitor.check_finviz`) →
   `finviz_cookie_expired` (critical, operator refreshes `FINVIZ_COOKIE`).
4. **`collect_failed_systemd_units()`** (category `execution_health`) — `systemctl --failed`
   filtered to trade-stack prefixes (`systemd_units.unit_prefixes`). Detection-only (restart
   needs sudo); finding carries the operator command.
5. **`collect_db_connection_health()`** (category `execution_health`) — counts PG
   `idle-in-transaction timeout` kills in the log tail (`db_connections` policy block); warns at
   10/3h so the next governor-style bug surfaces while it's one victim, not a fleet.

## Extending

- **New health check** → add a collector in `health_agent.py` (`collect_*`), return findings; the scorer
  and dashboard pick them up automatically.
- **New cron job** → add a row to `MONITORED_COMPONENTS` in `system_health_agent.py` with `schedule`,
  `log_file`, and `max_age_min`.
- **New coder backend** → add an entry to `config/coder_backends.json` (`cli_agent` or `http_diff`) and,
  optionally, slot it into `routing`. No code change needed.
- **New safe retry** → add the finding-type → command mapping in `health_agent_policy.json`
  `remediation_map` and allowlist the script in `claude_escalation_allowlist.yaml`.
- **Tune scoring** → edit weights/penalties/thresholds in `health_agent_policy.json` (or the DB
  `config_documents` key `health_agent_policy` for hot reload).
