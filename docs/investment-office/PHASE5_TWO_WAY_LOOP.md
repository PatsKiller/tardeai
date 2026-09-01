# Phase 5 — Mature the two-way Watch / Defense / Rotation / Re-Entry loop

Status:      HISTORICAL
as_of:       2026-08-13T20:51:51-04:00
Measured at: efcc51365 / not measured

> Goal (from the convergence prompt): complete the institutional idea lifecycle so
> the office finds replacements and future opportunities without operator
> scavenger hunts. Everything stays `READ_ONLY_ADVISORY` — no execution authority.

## 1. Scope

Phase 5 matures the loop that Phase 3–4 wired and that the earlier two-way
curation track (`scripts/lib/two_way_curation.py`, migration
`2026-08-13_two_way_curation.sql`) already foundations. Two directions:

```
FORWARD  CIO/Advisory/Defense/Rotation/Re-Entry → staging firewall
         → governed directive/promote path → Watch Intelligence
         → research / review / trigger state → proposal-eligible advisory state

REVERSE  operator disposition · trade/paper outcome · re-entry outcome
         · Hermes research quality · options evidence · missed opportunity
         · thesis outcome → scored learning inputs → Watch ranking / calibration
```

## 2. Foundation already in place

| Concern | Where | State |
| --- | --- | --- |
| Forward staging firewall (CIO/Advisory/Defense) | `cio_/advisory_/defense_directive_hits_staging` + `drain_curation_sources` | **live** |
| Governed promote path (no bulk bypass) | `drain_curation_sources` → `promote_directive_lead` governor + `auto_apply_gate` | **live** |
| Reverse edge: trade outcome | `write_realized_outcome` (realized_outcome + thesis_win) | **live** |
| Reverse edge: options outcome | `write_options_edge` + `fold_options_to_underlying` | **live** |
| Reverse edge: Hermes research | `write_hermes_research` + `hermes_research_score_from_action` | **live** |
| Provenance audit | `curation_loop_audit` + `audit()` on every fold | **live** |
| Scorer reverse factors | `hermes_watchlist_scorer._f_hermes_research/_f_options_edge/_f_thesis_outcome` | **live** |

## 3. Gap analysis (requirements → status)

1. **Preserve source provenance** — SATISFIED. `SOURCES` now covers
   `cio/advisory/defense/rotation/reentry`; `rotation` and `reentry` are first-class
   with their own staging tables, `SURFACED_BY`, `DESK_PROMOTION_TIER`, drain
   inclusion, and pure mappers `rotation_signal_to_feedback` / `reentry_signal_to_feedback`
   (§4c).
2. **Bulk staging must not bypass promotion governance** — SATISFIED (single
   governor brain; `auto_apply_gate` requires trusted tier + non-divergent +
   hit-rate floor).
3. **Lock/contention under full promote load** — SATISFIED. `drain_curation_sources`
   uses `FOR UPDATE SKIP LOCKED` (atomic per-row claim), savepoint-isolates each
   promote (a lock-timeout abort is contained to one lead), marks a staging row
   `drained` only on a terminal outcome (errors are retried, never dropped), and
   `promote_directive_lead` is now a single transaction per promote (§4f).
4. **Do not inflate reverse-learning weights before calibration** — SATISFIED.
   `calibrate_reverse_weight` / `calibrate_reverse_weights` gate every reverse factor
   by `n / n_min`, so effective weight can never exceed the base (§4).
5. **Label proxy vs realized distinctly** — SATISFIED. `evidence_class_for` +
   the `options_edge` `evidence_class` detail field label each reverse signal
   `realized` vs `proxy` (§4).
6. **Add sample-size/reliability fields to reverse factors** — SATISFIED. `*_n`
   columns + `_reverse_reliability` metadata on the scorer intel card (§4b).
7. **"Desk suggestions" → Alex opportunity queue** — SATISFIED. A single
   deterministic, hash-pinned digest (`scripts/lib/cio_opportunity_queue.py`) fed by
   staged/undrained curation; the CIO event detector wakes Alex (`OPPORTUNITY_QUEUE`)
   on material new opportunities (§4d).
8. **Sector opportunity behavior** — NOT ADDRESSED (see §6).

## 4. Delivered — reverse-factor reliability, calibration, sample-size `n`, and scorer wiring

### 4a. Pure reliability gate (`scripts/lib/two_way_curation.py`, increment 1)

- `evidence_class_for(factor, *, override)` — labels a reverse factor `realized`
  (graded against an outcome) vs `proxy` (IV rank / queue edge / research intent).
  Unknown factors default to `proxy` (fail-safe: never assume an unclassified
  signal is realized).
- `reverse_factor_reliability(factor, n, *, evidence_class)` — reliability ramps
  linearly `n / n_min` capped at 1.0; `n` of `None/0/negative` → 0.0 (drop the
  factor, never fabricate a neutral). Returns `trusted = (n >= n_min)` and a
  distinct `label` embedding the evidence class.
- `calibrated_reverse_weight(base, factor, n, *)` — `effective = base * reliability`,
  so effective weight can **never exceed** the configured base.
- `calibrate_reverse_weights(base_weights, sample_sizes, *)` — applies the gate to
  a whole reverse-weight map and reports `all_trusted`.
- `REVERSE_FACTORS = ("thesis_outcome", "options_edge", "hermes_research")` — the
  single source of truth the scorer reads.

`n_min` defaults: `thesis_outcome=3`, `options_edge=5`, `hermes_research=5`.

### 4b. Sample-size `n` persistence + scorer wiring (increment 2 — this change)

- **Schema** (`migrations/2026-08-13_two_way_reliability_n.sql`, additive):
  `watchlist_items.thesis_outcome_n`, `options_edge_n`, `hermes_research_n` INTEGER.
- **Writers** now accept and persist `n` (and `evidence_class` for options):
  - `write_realized_outcome(..., n=)` → `thesis_outcome_n`
  - `write_options_edge(..., n=, evidence_class=)` → `options_edge_n` + `evidence_class` in detail
  - `write_hermes_research(..., n=)` → `hermes_research_n`
  Each uses `COALESCE(%s, <col>)` so a missing `n` preserves the prior sample count
  (never an accidental zero-out). `symbol` remains the last positional param; `score`
  stays first in the research writer (back-compat).
- **Callers aggregate `n` per symbol**:
  - `hermes_outcome_grader.writeback_trade_outcomes` / `writeback_hermes_research`
    now group by symbol and pass `n = len(verdicts)`, latest-graded wins.
  - `options_pipeline.validation.fold_options_to_underlying` threads `n` (closed
    outcomes = realized, approval-queue = proxy) + `evidence_class` into
    `write_options_edge`.
- **Scorer** (`hermes_watchlist_scorer.score_symbol`) reliability-gates every reverse
  factor before blending: `eff_weight = base * reliability`; a factor at `n=0`/unknown
  is damped to zero and dropped from the blend/coverage, a below-`n_min` factor is
  partially damped, an `n≥n_min` factor is full weight. Emits `_reverse_reliability`
  metadata (reliability / n / n_min / evidence_class / trusted) on the intel card.
  `_BASE_SELECT` + the off-hours select now fetch the three `_n` columns.

Canaries:
- `tests/test_two_way_reliability.py` (13 tests) — pure gate: ramp linearity,
  never-exceeds-one, None/negative/invalid → 0, unknown-factor default, evidence-class
  defaults + override, realized-vs-proxy label distinction, weight-never-inflated,
  full-weight-at-n_min, zero-below-min, map calibration, missing-sample → drop,
  all-trusted.
- `tests/test_two_way_curation.py` (+10 tests) — `n` persistence on all three writers
  (param slot + symbol-last invariant), per-symbol aggregation in both writebacks,
  scorer damp-below-n_min / full-at-n_min / missing-n → zero, and the fold path
  passing `n` + `evidence_class` (closed = realized).

```bash
python3 -m pytest tests/test_two_way_reliability.py tests/test_two_way_curation.py -q
```

### 4c. `rotation` / `reentry` first-class sources (increment 3 — this change)

- **Taxonomy** (`scripts/lib/two_way_curation.py`): `SOURCES` → 5 sources;
  `STAGING_TABLE`, `SURFACED_BY`, `DESK_PROMOTION_TIER` each gain `rotation` +
  `reentry` (both `trusted`, matching the other desks). `drain_curation_sources`
  now iterates `SOURCES` (no hardcoded tuple), so the app role drains all five
  sources through the same governed `promote_directive_lead` path.
- **Pure mappers** (no I/O):
  - `rotation_signal_to_feedback(signal)` — sector RS ladder entry → `sector`
    feedback (sector/name, optional `etf`, `rs_score`); requires a sector name.
  - `reentry_signal_to_feedback(row)` — re-entry decision-desk row → `ticker`
    feedback; only `READY TO REVIEW` / `NEAR ENTRY` / `OVERSOLD REVIEW` emit
    (WAIT/STALE/MISSING/WASH BLOCK/CURRENTLY HELD never mint a lead).
- **Schema** (`migrations/2026-08-13_two_way_curation_sources.sql`, additive):
  `rotation_directive_hits_staging` + `reentry_directive_hits_staging` (mirror the
  existing desk staging tables; partial undrained indexes included).
- **Provenance allowlist** (`scripts/directive_promotion.py`): `_SURFACED_BY_ALLOWED`
  gains `rotation` + `reentry` so hits surface honestly instead of collapsing to
  `hermes`.
- **Emission** (`scripts/ops/emit_and_drain_desk_curation.py`): `_emit_rotation`
  (reads `state/data_broker/rotation_ladders.json`, top-3 leading sectors ≥ RS 50)
  and `_emit_reentry` (reads `data/runtime/reentry_decision_desk_latest.json`) feed
  the cron `desk-emit` path alongside advisory/defense; `_kpis` + preview report the
  new sources.
- **Snapshot** (`scripts/lib/data_broker/reentry_decision_desk.py`):
  `build_decision_desk` now persists `data/runtime/reentry_decision_desk_latest.json`
  (fail-soft), so the cron emit doesn't re-run the heavy desk per tick.
- **Health surfaces**: `watch_directives_monitor.py` + `api_v2._two_way_curation_health`
  + `_watch_directives` now report `rotation`/`reentry` staging, active directives,
  hits, and staged suggestions.

Canaries (`tests/test_two_way_curation.py`, +10):
- mapper shape/gating for rotation + reentry (sector/etf/rs, ready/near/oversold
  emit, non-actionable/missing-symbol never emit, source taxonomy present)
- emit stages to the correct per-source tables
- `drain_curation_sources` iteration count updated to `len(SOURCES)`.

### 4d. Desk suggestions → Alex opportunity queue (increment 4 — this change)

One Alex-consumable surface instead of a page the operator watches all day.

- **Pure queue** (`scripts/lib/cio_opportunity_queue.py`, no I/O at import):
  - `normalize_opportunity(raw)` — canonical `opportunity` envelope; drops rows with
    no symbol, unknown source, or non-actionable verdict/state (fail-closed: thin
    rows never mint a lead).
  - `opportunity_key(...)` — deterministic SHA-256 dedup key (source+symbol+label+verdict).
  - `build_opportunity_queue(rows)` — normalize → dedupe (latest `surfaced_at` wins) →
    rank (reentry > rotation > advisory > cio > defense, rs_score desc) → hash-pinned
    `digest`. `material` is True only with ≥ 2 distinct desk sources (a single-source
    trickle never pages the CIO).
  - `material_new_opportunities(digest, prev)` — digest changed AND non-empty.
  - `fetch_desk_suggestions(executor)` / `build_queue_from_executor(executor)` — the
    live DB reader, fail-soft, separated from the pure logic.
- **Wake wiring** (`scripts/lib/cio_event_detector.py`): new injected
  `opportunity_source` callable + `_check_opportunity_queue` step. Creates ONE
  `OPPORTUNITY_QUEUE` wake (idempotent on the queue digest) carrying
  `context.opportunity_digest / count / distinct_sources / by_source / top` so Alex's
  synthesis sees the actual candidates. `run_cio_event_detector_once` wires a
  fail-soft default source (`build_queue_from_executor(_default_executor)`).
- **Constants**: `OPPORTUNITY_QUEUE` added to `cio_wake_jobs.TRIGGER_TYPES` /
  `WAKE_REASON_CODES` / `PRIORITY_MAP`; `cio_run.VALID_TRIGGER_TYPES`; dispatcher
  `_map_wake_to_run_trigger` → `OPPORTUNITY_QUEUE`; run worker
  `resolve_run_budget` → `material_event` and `_classify_run_purpose` →
  `WATCH_OR_CATALYST_REVIEW`.
- **Run context thread**: `CIORunStore.create_run` + projection now carry `context`
  (dispatcher passes `wake.context`); `CIORunWorker._cio_synthesis` exposes
  `opportunity_queue` to Alex when present.
- **Health surface** (`api_v2._two_way_curation_health`): new `opportunity_queue`
  block (digest / count / material / by_source / top) — the read-only digest Alex and
  the operator both consume.

Canaries (`tests/test_cio_opportunity_queue.py`, 23 tests):
- normalize happy/skip paths (unknown source, missing symbol, non-actionable
  verdict/state, rs_score parse), key determinism.
- queue dedupe/rank/digest-determinism, `material` threshold (≥2 sources).
- `material_new_opportunities` truth table; `fetch_desk_suggestions` shape + fail-soft.
- detector wake-on-material / idempotency-per-digest / skip-non-material /
  skip-on-source-raise / skip-when-absent.
- constants + dispatcher/run-worker mapping canaries.

```bash
python3 -m pytest tests/test_cio_opportunity_queue.py -q
```

### 4e. Sector-opportunity synthesis (increment 5 — this change)

Alex's "Sector X is improving…" statement, built as a pure, dry-testable synthesis
that composes existing read models (never re-reads raw files or calls a model).

- **Pure module** (`scripts/lib/cio_sector_opportunity.py`, no I/O at import):
  - `canonical_sector(...)` — 11-sector GICS normalization with alias tolerance
    (Communication Services → Communications, Consumer Cyclical → Discretionary, …);
    unknown names pass through title-cased, never silently collapsed.
  - `classify_state(rs20, slope)` — exact replica of
    `sector_momentum_engine.classify` (LEADING / WEAKENING / LAGGING / IMPROVING).
  - `normalize_sector_row(...)` / `normalize_candidate(...)` — canonical envelopes
    accepting both the momentum-engine shape (`state`) and the rotation-ladder shape
    (`rs_score`), deriving `state` when absent.
  - `classify_candidate_readiness(...)` — WATCH_READY / NEEDS_RESEARCH / TOO_EXTENDED
    (RSI ≥ 70 or price ≥ 1.03·VWAP ⇒ too extended; `researched`/research-score ⇒ ready;
    else needs research), with an explicit `readiness` override.
  - `deployment_recommendation(...)` — fail-closed: over-target or no capital ⇒
    NO_DEPLOYMENT; ready candidate + capital ⇒ STAGED_DEPLOYMENT; else RESEARCH_FIRST.
  - `build_sector_opportunity(...)` — the full acceptance-shape envelope
    (exposure % / target % / capital $ / candidate counts / recommendation / rendered
    statement) with a hash-pinned `opportunity_key` for idempotent dedup.
  - `synthesize_sector_opportunities(...)` — orders LEADING before IMPROVING, filters
    non-opportunity sectors by default, and produces a deterministic digest.
  - `fetch_sector_opportunity_inputs(executor)` / `build_synthesis_from_executor(...)`
    — fail-soft live reader separated from the pure logic.
- **Read surface** (`api_v2.py`):
  - New endpoint `GET /api/v2/cio/sector-opportunities` (READ_ONLY_ADVISORY) returning
    the synthesis + deployable capital (`redeploy_capital_book.build_opportunity_set`).
  - `sector_opportunities` compact block added to `_two_way_curation_health` (digest /
    count / opportunity_count / per-sector statement).
  - `_sector_target_map()` reads `config/rotation_sector_targets.json` themes and keeps
    only names that canonicalize to a real GICS sector (thematic sleeves are skipped).

Canaries (`tests/test_cio_sector_opportunity.py`, 29 tests): alias normalization,
`classify_state` replication, row/candidate normalization (momentum + rotation-ladder
shapes), readiness truth table (override / RSI / VWAP / researched / research-score /
default / unknown), recommendation truth table, acceptance-shape envelope + statement,
`opportunity_key` determinism, ordering/filtering/digest, target lookup, and the
fail-soft executor reader.

```bash
python3 -m pytest tests/test_cio_sector_opportunity.py -q
```

### 4f. Lock/contention remediation under full promote load (increment 6 — this change)

Three concrete defects fixed, each dry-proven, plus a deterministic benchmark.

- **Atomic claim** (`drain_curation_sources`): the undrained SELECT is now
  `SELECT … WHERE drained=false ORDER BY proposed_at LIMIT %s FOR UPDATE SKIP LOCKED`.
  Each staging row is locked-and-claimed by exactly one drainer, so N concurrent
  workers can no longer double-promote the same row (the source of row-lock
  contention on the shared `watchlist_items` / `watch_directive_hits` hot rows).
- **No data loss on contention**: a row is marked `drained=true` only when its promote
  reached a terminal outcome (`PROMOTED` / `MONITORED_NO_QUALIFY` /
  `REGISTERED_NO_TECH` / `STAGED_FOR_REVIEW`, via `TERMINAL_PROMOTE_STATUSES`). An
  `ERROR` (lock-timeout / contention) or a failed directive mint leaves the row
  `drained=false` for the next cycle (`curation_retry` / `curation_errors` counters) —
  previously a contention error still drained the row and silently dropped the lead.
- **Savepoint isolation**: each promote runs inside `SAVEPOINT sp_{source}_{id}` and is
  released on success or `ROLLBACK TO SAVEPOINT` on failure. This clears the aborted
  transaction (`InFailedSqlTransaction`) a lock timeout leaves behind, so one contended
  lead no longer poisons the whole batch.
- **Single transaction per promote** (`directive_promotion.promote_directive_lead`): the
  persistence helpers no longer commit; the promote commits once at the end (own
  connection) or defers to the caller (shared `conn`, e.g. the desk-drain batch). This
  collapses the previous ~5 commits/symbol into one — the actual lock-hold window under
  load. `commit=None` auto-selects: own-conn → single commit + rollback-on-error; shared
  conn → defer to caller.

Benchmark + canaries:
- `scripts/ops/benchmark_drain_contention.py` — a deterministic contention model
  (legacy vs fixed) plus a dry statement census of the real drain. Fixed: 0
  double-claims, 0 dropped leads, 1.0 commits/item (vs legacy ~0.75 double-claim rate,
  ~5% drop rate, ~4.76 commits/item).
- `tests/test_drain_contention.py` (11 tests) — SKIP-LOCKED claim emitted; terminal
  marks drained; ERROR leaves undrained + retry; savepoint rollback on error (and on a
  raised exception); success releases without rollback; unresolved directive leaves
  undrained; promote defers commit on shared conn / commits exactly once when asked;
  benchmark fixed-policy superiority.

```bash
python3 -m pytest tests/test_drain_contention.py -q
python3 scripts/ops/benchmark_drain_contention.py
```

## 5. Next increments

Phase 5 is complete. All eight gap-analysis items are SATISFIED (§3): provenance,
governed promote, reverse-factor calibration, proxy/realized labeling, sample-size
persistence, the Alex opportunity queue, sector-opportunity synthesis, and the
lock/contention remediation (§4f). Remaining work is cross-phase (Checkpoint 5 organic
loop + a live `n` backfill — see §8).

## 6. Required sector opportunity behavior (Checkpoint 5 target)

SATISFIED by increment 5 (§4e). When Rotation/Defense detects a material sector shift,
Alex can now state:

> Sector X is improving. Current portfolio exposure = Y%. Policy/target posture =
> Z%. Potential incremental capital = $A. Best current candidates = B/C/D. B is
> Watch READY, C needs research, D is too extended. I recommend no deployment /
> staged deployment / research first.

The synthesis is a read-only advisory projection: it ranks LEADING/IMPROVING sectors,
computes exposure vs target, attaches deployable capital, classifies candidates by
readiness, and emits a deterministic recommendation — never mutating or executing.

## 7. Checkpoint 5

Prove one full **organic** loop — no synthetic shortcut counts:

```
sector/defense or CIO event → staged Watch idea → research → Watch state change
→ Alex decision → operator disposition → reverse evidence recorded
```

## 8. Known gaps (honest, not hidden)

- ~~The reliability gate + `n` persistence are wired; the gate is only as good as the
  `n` writers produce — a backfill is not yet run, so existing rows have `_n = NULL`
  (damped to zero) until the outcome graders / options fold run and populate them.~~
  **RESOLVED.** `migrations/2026-08-13_two_way_reliability_n.sql` was applied (the
  `thesis_outcome_n` / `options_edge_n` / `hermes_research_n` columns were missing
  from `watchlist_items` — the additive migration had never been run), and the
  one-shot `scripts/reverse_factor_backfill.py` backfill folded the sample sizes from
  their canonical sources (`hermes_outcome_ledger` trades/research rows; closed
  options paper outcomes + approval-queue/IV proxy). Result: 71 thesis-outcome, 641
  hermes-research, and 159 options-edge symbols backfilled. Logic lives in
  `scripts/lib/cio_reverse_factor_backfill.py` (pure derivation + injectable executor,
  dry-tested in `tests/test_cio_reverse_factor_backfill.py`).
- The `rotation` emit reads `rotation_ladders.json` only when the ladder snapshot is
  present; `reentry` emit reads `reentry_decision_desk_latest.json` (written by the
  re-entry decision desk). Both fail-soft with a clear "missing snapshot" result so
  the cron never blocks on absent producer output.
- The Alex opportunity queue is wired and wakes on material new opportunities, and the
  sector-opportunity synthesis (§4e) is delivered as a read-only advisory projection.
  The lock/contention remediation (§4f) is delivered and dry-proven; it has not yet been
  exercised under a real multi-process promote load against the live DB.
- Checkpoint 5 (organic loop) has not been run; it requires live data flow.
