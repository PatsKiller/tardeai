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
| Schedule | crontab + `config/systemd/tradeai-health-agent.{service,timer}` | Cron every 30 min; coder-dispatch advisory every 3h weekdays |

## Health score

Five categories, each scored from 100 down by penalties (critical −40, warning −15, info −5), then a
weighted overall. Weights/penalties/thresholds live in `config/health_agent_policy.json`.

| Category | Weight | Signals |
|---|---|---|
| Data Quality | 0.25 | holdings/risk/dividends/news/CIO/agent-job freshness + open data gaps |
| Execution Health | 0.25 | pipeline failures, stuck agent jobs, critical execution escalations, orphaned stops |
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

## Extending

- **New health check** → add a collector in `health_agent.py` (`collect_*`), return findings; the scorer
  and dashboard pick them up automatically.
- **New coder backend** → add an entry to `config/coder_backends.json` (`cli_agent` or `http_diff`) and,
  optionally, slot it into `routing`. No code change needed.
- **New safe retry** → add the finding-type → command mapping in `health_agent_policy.json`
  `remediation_map` and allowlist the script in `claude_escalation_allowlist.yaml`.
- **Tune scoring** → edit weights/penalties/thresholds in `health_agent_policy.json` (or the DB
  `config_documents` key `health_agent_policy` for hot reload).
