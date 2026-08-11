# Phase P5 — Lightweight wake traces

**Authority:** READ_ONLY_ADVISORY  
**Branch:** `feature/advisory-desk-v1`  
**Code:** `scripts/lib/cio_wake_traces.py`  
**Log:** `data/cio/cio_wake_traces.jsonl`  
**CLI:** `scripts/cio_wake_traces_cli.py` · `/cio traces [n]`

## Why

Operators need “**why did it wake / what did it think**” without Datadog, LangSmith, or a new fleet. Traces are **append-only JSONL**, **fail-soft** (never crash a wake), and **zero LLM** to query.

## File & schema

One row per open / update / close. List merges by `wake_id` (last-write-wins).

| Field | Meaning |
|---|---|
| `trace_id` | Stable id (`tr_<wake_id>`) |
| `wake_id` | Wake job id or synthetic `situation:…` / `hb_…` |
| `ts` | Last row timestamp (ISO UTC) |
| `source` | `situation.raised` \| `OPERATOR_MESSAGE` \| `GOAL_DUE` \| `EVENT_BUS` \| `heartbeat` \| `other` |
| `situation_type` | S0–S8 when known |
| `agent_id` | e.g. `alex` |
| `plan_id` | Linked plan if any |
| `thesis_version` | Nullable (P3 if present) |
| `llm` | `invoked` \| `blocked_cap` \| `blocked_provider` \| `template` \| `skipped_non_material` \| `skipped_dedup` \| `pending` |
| `model_id` | Nullable model id from bridge |
| `duration_ms` | Enrich / cycle duration when known |
| `outcome` | `ok` \| `error` \| `deferred` \| `open` |
| `error_class` | Short class/string (no stack spam) |
| `flags` | `{enrich_on, notify_on}` snapshot |

## Emit points

1. **Wake enqueue** (`CIOWakeJobStore.enqueue`) → `open`  
2. **Situation plan** (`cio_situation_detector`) → `open` with synthetic wake id  
3. **Plan enrichment** (`enrich_plan`) → `close` with final `llm=`  
4. **Telegram converse** reply → `close` outcome (llm kept from enrich)  
5. **Heartbeat no-op** (no changes / no plans) → one-shot `skipped_non_material`

## Diagnose COST_CAP_EXCEEDED

```bash
# Recent cap blocks
.venv/bin/python scripts/cio_wake_traces_cli.py --llm blocked_cap -n 20

# Or Telegram / local commands
.venv/bin/python scripts/cio_commands.py traces 15 llm=blocked_cap
# /cio traces 15 llm=blocked_cap
```

| Signal | Meaning |
|---|---|
| `llm=blocked_cap` + `outcome=deferred` | Process/hour/global cap — narrative used **template** |
| `llm=blocked_provider` | Bridge/provider/JSON validation failed → template |
| `llm=invoked` | Governed bridge returned validated narrative |
| `llm=skipped_non_material` | Heartbeat / non-material source — no LLM budget spent |
| silent missing row | Trace write failed **or** path not run; wake still proceeds (fail-soft) |

Cross-check: `data/cio/cio_llm_enrich_log.jsonl` and process `daily_cost_cap_usd` on `alex_cio_synthesis` / `advisory_desk_opinion`.

## Operator commands

```bash
.venv/bin/python scripts/cio_wake_traces_cli.py -n 10
.venv/bin/python scripts/cio_wake_traces_cli.py --plan plan_xxx --json
.venv/bin/python scripts/cio_commands.py traces 10
```

## Tests

```bash
.venv/bin/python -m pytest tests/test_cio_wake_traces_p5.py -q
```

## Non-goals

No OpenTelemetry collectors, cloud APM, WhatsApp (P4), Mem0/LangGraph, mass Telegram notify, or CC page.
