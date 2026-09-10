# Phase 5 — Governed MVL circulation: investigation findings

Date (America/New_York): 2026-09-10 01:50. Campaign: Grok-closure.

## What exists (verified in `scripts/agent_runtime/`)

The governed MVL (Minimum Viable Loop) subsystem is mature and LAB-scoped:

- `runtime.py` — `MvlRuntime` durable shadow loop: `start → retrieve →
  invoke_tool (ToolPolicy budget) → reason (model budget) → create_artifact →
  record_review → record_score → complete`. With `RunPersistence`, every
  transition/counter/budget goes through a single authoritative store (never a
  silent journal fallback).
- `trigger_intake.py` — governed intake: bounded enqueue, lease
  (`FOR UPDATE SKIP LOCKED`), ack, expired-lease return, dedup by
  `(agent_id, trigger_kind, dedup_key)`, cursor table. In-memory + Postgres
  backends, with runtime-identity allowlist verification (no elevated role attrs).
- `trigger_sources.py` / `trigger_producer.py` — read-only source adapters that
  emit `TriggerCandidate` rows; fail closed (enqueue nothing) on missing
  tables/entitlements/DSN — never a fixture or synthetic seed.
- `sentinel.py` / `sentinel_pipeline.py` / `critics.py` — independent Sentinel
  critic; `agents/definitions.py` defines `darwin` with `max_model_calls=0`
  (the zero-model contract), plus sentinel/iris/reflection/argus/vigil/…
- `migrations/agentic_runtime/` — `0001_mvl` (schema + 8 tables) and `0002_roles`
  (least-privilege runtime roles), applied ONLY to an isolated LAB DB via
  `apply.sh` (prepare-only; refuses missing/production DSN).

## The bypass, characterized

The runtime chain above is correct and governed. The "live processors bypass the
governed intake" gap is a **production-wiring** gap, not a logic gap:

1. `agentic_runtime` is LAB-only and not yet applied to any production DB (the
   migrations explicitly refuse a production-looking DSN). Until it is applied
   under operator authority, no production consumer can lease `trigger_intake`.
2. Live cron jobs (the ~190-entry crontab) dispatch through their existing
   per-lane entrypoints, not through `MvlRuntime`/`Sentinel`/`trigger_intake`.

## What is required to close it (and why it is not yet closed)

- **Operator authority**: apply `migrations/agentic_runtime/0001_mvl.up.sql` +
  `0002_roles.up.sql` to the isolated `trade_ai_agentic_lab` DB with an
  out-of-band DSN (`apply.sh` refuses without it). This is the same class of
  native-authority gate as the Phase 1 `db-write` grant.
- **Live rewiring**: route the live cron entrypoints through the governed intake
  (lease → MvlRuntime → Sentinel → tool audit → Darwin score → ack). This is a
  multi-module integration that should be done as focused commits after the LAB
  schema is applied.

## Engineering done this session

The canonical loop's runtime pieces are already present and governed; this
session's Phase 2/3/4 work (governed research producer, durable settlement,
atomic inbound, governed commitment) lands the surrounding evidence spine that
the MVL circulation will write into. A full MVL live-wiring is the remaining
integration item and is blocked on the LAB migration apply (operator DSN), not
on missing code.
