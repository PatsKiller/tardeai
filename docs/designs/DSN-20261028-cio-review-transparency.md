---
id: DSN-20261028-cio-review-transparency
title: CIO review transparency — wire the conflict ledger producer and surface one authoritative state
status: PROPOSED
approval: "Operator 2026-10-28 (this session): 'i approve, I'll take your recommendation on the flag' — conflict-resolver is learn-class via r1_class_admission. This design FOLDS INTO the existing W8 'Conflict Engine PR' (docs/ops/W8_WRITERS_20261024.md §Conflict-resolver addendum); it does not fork it."
source: docs/audits/CIO_REVIEW_DECISION_AUTHORITY_RCA_2026-10-28.md
supersedes: none (wraps W8 conflict-resolver addendum + W10 engine, not a new program)
phases:
  - id: DSN-20261028-cio-review-transparency-P1
    title: Build the W8 conflict-resolver shadow declaration (registry + allowlist + health), propose-only
    status: PROPOSED
    tasks:
      - id: DSN-20261028-cio-review-transparency-P1-T1
        title: Fold into W8 spec; freeze the exact runner argv/lock/env/receipt/timeout from code
        status: IN_PROGRESS
        areas: [docs/designs/DSN-20261028-cio-review-transparency.md]
      - id: DSN-20261028-cio-review-transparency-P1-T2
        title: Registry row + allowlist entry + health contract (SHADOW dry-run, live_arg null) — one [shared-infra] PR
        status: PROPOSED
        areas: [config/lane_registry.json, config/n8n_run_allowlist.json, config/n8n_health_contracts.json]
      - id: DSN-20261028-cio-review-transparency-P1-T3
        title: Shadow admission; operator reviews the 2-trading-day ledger, then operator-controlled live flip
        status: PROPOSED
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

# CIO review transparency — design of record (folded into W8)

## 0 · What this is, and the discovery that re-scoped it

The Watch screen shows several decision states side by side with no precedence, and every card says "conflict ledger not
yet produced". The root cause is that the §28.10 conflict engine has no scheduled producer. Full evidence:
`docs/audits/CIO_REVIEW_DECISION_AUTHORITY_RCA_2026-10-28.md`.

**Discovery (recorded honestly):** the producer's lane declaration was already spec'd on 2026-10-24 by the existing W8
workstream — `docs/ops/W8_WRITERS_20261024.md` §"Conflict-resolver addendum", verbatim intent:

> "The separate W8 Conflict Engine PR will declare `conflict-resolver`, every 15 minutes in the market session plus
> 07:30 and 16:20 ET, receipt `data/runtime/conflict-resolver_last.json`, write-free dry run, ledger-only/no-notification
> shadow for two trading days with comparison report, then operator-controlled live flip and watchdog coverage."

This design therefore **does not invent a new program**. It is the W8 conflict-resolver lane declaration, taken up because
it was spec'd but never claimed or built (no registry row, allowlist entry, health contract, packet or PR exists today).
W10 owns `scripts/lib/conflicts/**` (engine + ledger + API + CIO memory) — that tree is **not** touched here. W8 owns the
lane registry / allowlist / health / scheduling — this PR is exactly that, propose-only.

## 1 · The class decision (operator-approved 2026-10-28)

`scripts/conflict_resolver.py` writes two things in shadow mode: `data/conflicts/conflict_events.jsonl` (the append-only
ledger via `ConflictLedger.reconcile(apply=True)`) and CIO memory (`conflicts/cio.py::memory_writer` → shared research
spine, silo `cio`). No model, broker, sender or ingest. Class is **`learn`**, admitted only through
`lane_dispatch.r1_class_admission` (§23.18). This is the operator's adopted flag decision.

The gate requires: `R1_STATUS` ACTIVE; `dispatch_eligible` (no forbidden token, not a daemon); a dispatcher row at
`stage ∈ {shadow, canary, cutover}`; non-empty `dry_run_arg` (`--dry-run`); `output_signal` = `LaneRunReceipt@v1`
(`data/runtime/conflict-resolver_last.json`, already written by the runner); no broker credential in `env_names`.

## 2 · Frozen runner parameters (from code, not the 4-day-old "not frozen" note)

The W8 addendum said the exact argv/lock/env/receipt/timeout were "not frozen yet" (pending a W10 handoff). The runner is
now on main; its exact contract is determinable:

- **argv** — `scripts/conflict_resolver.py --dry-run --state-root <persistent-state>` (dry_run_arg); shadow is `--shadow`.
  `--dry-run` / `--shadow` are mutually exclusive and required; `--state-root` is required; `--input-file` optional.
- **lock** — `data/conflicts/conflict_resolver.lock` (`flock LOCK_EX`), held only in shadow mode.
- **env** — bounded: no broker, sender, model, or secret; it imports read-only projections only.
- **receipt** — `data/runtime/conflict-resolver_last.json` via `write_lane_receipt("conflict-resolver", …)`.
- **timeout** — to be measured on the dry-run/shadow fire (the runner reports `duration_seconds`); no guess is recorded.

## 3 · Cadence (W8 spec, adopted verbatim)

Every 15 minutes in the market session, plus 07:30 ET and 16:20 ET. Shadow is dry-run (write-free); the two-trading-day
shadow is ledger-only with a comparison report; live is the operator-controlled flip. Not `*/15` blindly — the 07:30 and
16:20 ET slots are part of the accepted spec.

## 4 · Health contract (fields the P1-T2 row must fill)

`config/n8n_health_contracts.json`, owner `cio`, class `learn`, non-operative DRAFT until the operator reviews (a worker
never marks a new health row REVIEWED — W8 rule). Healthy = `data/runtime/conflict-resolver_last.json` `ok_at` within 2×
cadence and the ledger exists; degraded = receipt stale beyond 2× cadence; failed = beyond 3× or non-empty `error`.

## 5 · The operator/§17 gates (propose and stop; none are done by this design)

1. **Rulebook ratification.** `config/conflict_rulebook.json` is `status: PROPOSED, approval: null, live disabled`. The
   engine must not judge live until the operator ratifies the rulebook (operator act, §28.10).
2. **Store + writer grant.** `config/data_source_authority.json` already carries `conflict_ledger` and
   `conflict_rule_proposals` as `proposed` domains (`approval: null`). Row promotion is the operator's §7A/§26.6 grant.
3. **Dispatcher-row admission.** §23.11: the reviewed registry-row + allowlist PR (P1-T2) is the §9.3/§17 decision; the
   operator's digest approval / merge is the grant.
4. **Shadow → live.** §23.12: shadow writes the ledger (dry-run first), the operator reviews the two-trading-day report,
   then the operator-controlled live flip.
5. **Legacy flag retirement** (P1-T4, OI-118) only after the engine is live.

## 6 · P2 — the unified freshness / authority block (display only; additive)

Every CIO-driven card exposes, from data already present: last reviewed, freshness/age, evidence age, confidence,
authoritative state, reviewed by, trigger, next review, sources, conflicts, what must change. The single rendered state is
the engine's `headline()`; other authorities render as conflicts/gates, never parallel truths. No logic change.

## 7 · What does not change

`MBI_BEHAVIOR = 0` throughout. No broker/secret/sender/guard path. The Ask lifecycle lanes stay under
`DSN-20261026-ask-hourly`. `scripts/lib/conflicts/**` (W10's tree) is read, never edited here.

## 8 · Closeout / evidence

- P1 done when `conflict_events.jsonl` is produced on schedule from the served release (a natural fire, quoted) and the
  card no longer renders "conflict ledger not yet produced".
- P2 done when the Watch card shows the authoritative-state block with a `[VERIFIED]` runtime screenshot.
- Overlapping OPEN_ITEMS cited: OI-118 (the transition), OI-010, OI-019, OI-032, OI-033, OI-064.
