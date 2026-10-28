---
id: DSN-20261028-cio-review-transparency
title: CIO review transparency — wire the conflict ledger producer and surface one authoritative state
status: PROPOSED
approval: "Operator 2026-10-28 (this session): 'i approve, I'll take your recommendation on the flag' — conflict-resolver is learn-class, admitted through r1_class_admission. Design approval still gates build (§28.3b); the §17 grants for the new store/writer and dispatcher-row admission land at the reviewed PR."
source: docs/audits/CIO_REVIEW_DECISION_AUTHORITY_RCA_2026-10-28.md
phases:
  - id: DSN-20261028-cio-review-transparency-P1
    title: Admit the conflict-resolver producer and retire the legacy flag path
    status: PROPOSED
    tasks:
      - id: DSN-20261028-cio-review-transparency-P1-T1
        title: Design of record (this file) — pin class, cadence, health contract, §17 gates
        status: IN_PROGRESS
        areas: [docs/designs/DSN-20261028-cio-review-transparency.md]
      - id: DSN-20261028-cio-review-transparency-P1-T2
        title: Registry row + allowlist entry + health contract + onboarding checklist (one PR)
        status: PROPOSED
        areas: [config/lane_registry.json, config/n8n_run_allowlist.json, config/n8n_health_contracts.json]
      - id: DSN-20261028-cio-review-transparency-P1-T3
        title: Shadow admission; operator reviews the 2-trading-day ledger, then canary and cutover
        status: PROPOSED
        areas: [scripts/conflict_resolver.py]
        owner: OPERATOR
      - id: DSN-20261028-cio-review-transparency-P1-T4
        title: Retire legacy watch_prospects.conflicts_for flag path once the engine is live (OI-118)
        status: PROPOSED
        areas: [scripts/lib/data_broker/watch_prospects.py]
  - id: DSN-20261028-cio-review-transparency-P2
    title: Unified freshness / authority block on CIO-driven cards
    status: PROPOSED
    tasks:
      - id: DSN-20261028-cio-review-transparency-P2-T1
        title: Card contract + display (Last reviewed / freshness / evidence age / authoritative state / reviewed by / trigger / next review / sources / conflicts / what must change)
        status: PROPOSED
        areas: [apps/command-center-v3/src/components, apps/command-center-v3/src/pages/WatchMyList.tsx, scripts/lib/site_payload_reads.py]
---

# CIO review transparency — design of record

## 0 · What this is, and what it is not

The Watch screen shows several decision states side by side (`DETERMINISTIC_FAIL`, `NEAR_ENTRY`, `WATCH`, legacy
flags) with no stated precedence, and every card says "conflict ledger not yet produced". The root cause is **not a
UI bug**: the §28.10 conflict engine is fully built but has no scheduled producer, and the Ask-the-CIO refresh lanes
are registered but not admitted. Full evidence: `docs/audits/CIO_REVIEW_DECISION_AUTHORITY_RCA_2026-10-28.md`.

This design covers exactly two things:

1. **P1 — wire the producer.** Admit `scripts/conflict_resolver.py` as a scheduled n8n dispatcher lane so
   `data/conflicts/conflict_events.jsonl` is produced, §28.10 goes live, and the legacy flag path can retire.
2. **P2 — make it legible.** Surface one authoritative state per subject with its freshness and authority metadata.

It does **not** re-design the Ask lifecycle. The `cio-ask-lifecycle` (hourly) and `cio-ask-material-events` (*/5) lanes
that would re-attempt and expire blocked reviews are **already** owned by `DSN-20261026-ask-hourly` P1-T4 ("Native n8n
schedules, admission and business health"). This design references them; it does not fork them.

## 1 · The class decision (operator-approved 2026-10-28)

`scripts/conflict_resolver.py` writes two things in shadow mode:

- `data/conflicts/conflict_events.jsonl` — the append-only conflict ledger (`ConflictLedger.reconcile(apply=True)`).
- CIO memory — `scripts/lib/conflicts/cio.py::memory_writer` upserts a `kind="conflict"` contribution into the shared
  research spine (`cross_asset.security_research_spine.upsert_research_memory`, silo `cio`), the NO-SILOS path.

It calls **no model, no broker, no sender, no ingest**. Its dispatcher class is therefore **`learn`** (memory/learning
writer), and it enters only through `lane_dispatch.r1_class_admission` (§23.18). This is the flag decision the operator
adopted: **conflict-resolver = learn-class via `r1_class_admission`**, not plain §23.25 cutover.

The admission gate requires, and this design must satisfy at build (P1-T2):

- `R1_STATUS` ACTIVE (it is);
- `dispatch_eligible` — no forbidden token, not a daemon (`--shadow`/`--dry-run` are one-shot, no `--loop`/`--watch`);
- a dispatcher row (`scheduler.expression = "dispatcher"`, **never** the workflow id `tradeai-dispatcher`) at
  `stage ∈ {shadow, canary, cutover}`;
- a non-empty `dry_run_arg` (`--dry-run`);
- `output_signal` = `LaneRunReceipt@v1` — `conflict_resolver.py` already writes
  `data/runtime/conflict-resolver_last.json` via `write_lane_receipt("conflict-resolver", …)`, which matches;
- no broker credential in `env_names` (none).

## 2 · Cadence (proposed, to confirm against input freshness)

The engine is deterministic and free. Its inputs are the projections it reads in `collect_inputs`:
`compose_universe` (Watch), `reentry_rows` (re-entry desk), `get_prospects` (CIO prospect shadow), and
`stances_for_symbols`/`security_inputs_for` (CIO truth). Those producers refresh on sub-hourly to daily clocks.

Proposed cadence: **`*/15 * * * *` (every 15 min, America/New_York, market days plus a light off-hours pass)** — cheap,
and it keeps the conflict ledger within a card's staleness window. Exact slot(s) are confirmed in P1-T2 against the
input producers' own `as_of`, so the resolver never runs far ahead of the inputs it reconciles.

## 3 · Health contract (fields the P1-T2 row must fill)

`config/n8n_health_contracts.json`, `REVIEWED` (no `UNKNOWN`), owner `cio`:

- **purpose** — reconcile the six decision authorities under the §28.10 rulebook into one ledger.
- **connects_to** — `watch_intelligence`, `reentry_decision_desk`, `cio_prospect`, `cio_truth`, `conflict ledger`.
- **healthy** — `data/runtime/conflict-resolver_last.json` `ok_at` within 2× cadence **and** the ledger exists.
- **degraded** — receipt stale beyond 2× cadence; **failed** — beyond 3×, or a non-empty `error`.
- **baseline** — dry-run report row count / duration; **alerting** — host fan-in, P2 (not P0/P1).
- **remediation** — re-fire; on repeated failure the §23.24 remediation path.

## 4 · The §17 gates (propose and stop; none are done by this design)

1. **New store + writer.** `data/conflicts/conflict_events.jsonl` is a new durable store written by a new producer.
   §26.6 / §7A: the writer is operator-approved; its registry row (a `conflict` domain) carries the operator's grant.
2. **Dispatcher-row admission.** §23.11: the reviewed registry-row + allowlist PR is the §9.3/§17 decision. P1-T2 opens
   that PR; the operator's digest approval / merge is the grant.
3. **Shadow → canary → cutover.** §23.12: shadow fires `--shadow` (writes the ledger + CIO memory, sends nothing), the
   operator reviews the two-trading-day shadow report, then canary and cutover under a `cron` grant naming the lane.
4. **Legacy flag retirement.** P1-T4 removes `watch_prospects.conflicts_for` from the card path **only after** the
   engine is live (OI-118; §28.11 transition).

## 5 · P2 — the unified freshness / authority block (display only)

Every CIO-driven card exposes, from data already present (`as_of`, `source`, `review_lifecycle`, expiry, `next_review`):

```
Last reviewed · Freshness (age) · Evidence age · Confidence · Authoritative state ·
Reviewed by · Review trigger · Next scheduled review · Evidence sources · Conflicts · What must change
```

The single rendered state is the §28.10 engine's ranked verdict (`headline()`); the other authorities render as
**conflicts / gates**, never as parallel truths. This is the Q10 contract from the RCA report; it changes no logic.

## 6 · What does not change

`MBI_BEHAVIOR = 0` throughout — reconciliation and display of advisory states; nothing sizes, orders, or stops. No
broker, secret, sender, or guard path is touched. The Ask lifecycle lanes stay under `DSN-20261026-ask-hourly`.

## 7 · Closeout / evidence

- P1 done when `conflict_events.jsonl` is produced on schedule from the served release (a natural fire, quoted), and
  the card no longer renders "conflict ledger not yet produced".
- P2 done when the Watch card shows the authoritative-state block with a `[VERIFIED]` runtime screenshot.
- Overlapping OPEN_ITEMS cited, not re-opened: OI-118 (the transition), OI-010, OI-019, OI-032, OI-033, OI-064.
