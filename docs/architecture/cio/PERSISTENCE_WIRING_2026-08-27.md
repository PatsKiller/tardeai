# Persistence wiring — implementation record

**Date:** 2026-08-27
**Releases:** `6124ee46` → `5bd09f37`, each promoted and verified live
**Companion:** `IDENTITY_AND_MEMORY_ADVISORY_2026-08-27.md`, whose Phase A this executes · **Sequel:** `LOOP_CLOSURE_2026-08-27.md`, which closes the learning loop the same evening

The advisory concluded the identity and memory layers were built and switched off, and that the work was **promotion and cutover, not construction**. This records what was wired, what it measured before and after, and what deliberately was not touched.

Every figure below was measured against live production state.

---

## What moved

| | before | after |
|---|---|---|
| registry entities | 383 | **10,279** (5,277 live + 5,002 superseded, retained by design) |
| entities CONFIRMED by a durable identifier | **17** | **5,014** |
| entities carrying their confirming identifier | 0 | **5,014 / 5,014** |
| lineage workflows with `subject_guid` | **0 / 97** | **58 / 97** |
| lineage `entity_type` | UNRESOLVED × 97 | SECURITY 58 · UNRESOLVED 39 |
| memory records with `subject_guid` | **0 / 441** | 428 single-entity + 8 multi |
| evidence domains AVAILABLE | 7 / 30 | **11** |
| CIO runs reaching synthesis | 1 of 55 in 17 days | gate now fed; 4 of 5 run purposes pass (see sequel) |

---

## 1. Identity — the CUSIP was arriving and being discarded

`schwab_adapter.py` read `instrument.symbol` off each position and dropped the rest. Schwab returns `instrument = {assetType, cusip, symbol, description}`, so a durable instrument identifier arrived on every sync and went in the bin — the file contained zero references to `cusip`.

**PR #551** captures it. **PR #554** stops it being discarded a second time one layer down: `resolve_identity_spine()` consumed `identifiers` to derive `security_guid` and never returned them, so a CONFIRMED entity carried the GUID and no evidence for it. The spine now returns the normalized identifiers plus `identity_basis` — which key produced the GUID — so a status can be audited and a GUID re-derived from the stored record.

Identifiers **accumulate rather than replace**. Two sources can reach the same entity carrying different ids (the GUID keys off the highest-priority one), and a plain `update()` let the later source erase the earlier one's.

### Sources of durable identifiers

`/v2/assets` **has no `cusip` field** — verified across all 14,281 active US equities. Absent from the schema, not empty. Alpaca cannot confirm an entity and should not be attempted again.

Schwab's `/marketdata/v1/instruments?projection=fundamental` returns `cusip`, `description` and `exchange` for symbols **never held**, which is the entire watch tail:

```
ABCL  00288U106  ABCELLERA BIOLOGICS
ACAD  004225108  ACADIA PHARMACEUTICA
ACLX  (none)     -> recorded as a miss, not invented
```

**PR #555** sweeps it. Final run: **4,997 identifiers from 5,244 symbols (95.3%), 247 misses, zero fetch failures** over ~75 minutes. The sweep writes evidence and nothing else — it does not mint and holds no authority over identity; `mint_identity_registry.py` folds the result in afterwards under the existing upgrade rules. A sweep can be re-run, inspected or discarded without touching identity.

### Registry scope

Widened from `status = 'active'` to every status except `removed`, plus three surfaces the watchlist table never covered:

| source | distinct | previously registered |
|---|---|---|
| holdings | 30 | yes |
| watchlist `active` + `researched` | 5,473 | `active` only (360) |
| `watchlist_symbol_master` | 5,261 | none |
| traded ever | 137 | **117 missing** |
| re-entry candidates | 57 | **43 missing** |
| watchlist `removed` | 7,198 | **excluded** |

A name we may re-enter tomorrow had no identity at all, and one minted at the moment of re-entry is the fragmentation the registry exists to prevent. `removed` stays out: 7,198 explicitly-dropped names would more than double the registry in bare ticker aliases.

---

## 2. Lineage — resolution moved to the write path

**PR #556.** Identity was stamped only when a producer passed an explicit `identity` payload to `record_cio_generation`, and the CIO arc never did. But **59 of 97 envelopes already carried a `subject_id`, and 58 resolve** — the data was there, the resolution step was not.

`_stamp_identity()` now runs inside `LineageStore.upsert_envelope`, so every envelope write passes one resolution point instead of each producer remembering to.

**Deliberately not done:** it never stamps `event_id` (that key derives from the event *kind*, known only to the caller — minting one under a generic kind produces join keys that silently fail to match), never touches `workflow_id` (which would rekey every consumer), and never overwrites a producer that declared its own `entity_type`.

Two defects surfaced:

- `resolve_entity` treated a declared `entity_type: UNRESOLVED` as **authoritative**, so a stale envelope kept reporting UNRESOLVED after the registry could resolve it. UNRESOLVED is the absence of an answer, not an answer. Without this fix `entity_type` stays 97/97 UNRESOLVED even with GUIDs attached.
- Resolution on the write path cost **~18 ms per envelope** against a 4.26 MB registry, growing with it. `identity_registry.load_cached()` keys the parse on `(mtime_ns, size)` — a mint is picked up on its next read and a stale read is impossible. **18.2 ms → 0.019 ms.**

Historical envelopes were re-stamped by `backfill_lineage_identity.py`. The store is append-only, so it **adds a version rather than editing one**: 1,142 → 1,200 rows, 0 removed.

---

## 3. Memory — anchored on the spine

**PR #558.** 441 live memory records carried `symbols` — ticker strings — and none carried a `subject_guid`, while a registry of 5,000+ GUID'd entities sat beside them.

A ticker is an alias. It is reassigned after a delisting, so two companies can collide on one memory key years apart, and a memory written before a symbol change becomes unfindable after it. Every downstream property — bitemporal history, promotion evidence, audit provenance — is keyed on the subject, so nothing else composes until this does.

Resolution happens in `_persist_record`, the chokepoint every durable memory write passes through.

`subject_guid` is set **only when the memory concerns exactly one entity**. A portfolio-wide observation has no single subject, and collapsing 135 symbols onto one GUID would manufacture a join between a broad note and an arbitrary security; those carry `subject_guids` and no `subject_guid`. An unregistered symbol is recorded under `unresolved_symbols` rather than dropped — a dropped symbol looks identical to an entity with no memories, and the gap stops being measurable.

**Memory is not an identity authority.** This reads the registry and never mints; with no registry the write proceeds unanchored rather than blocking or inventing.

---

## 4. The evidence gate — four unrelated wiring bugs

**PR #557.** 54 of 55 CIO runs blocked at `HEALTH_CHECK` on `EVIDENCE_GAP`, continuously from 2026-08-10. No run reached synthesis, so none produced a checkpoint.

**The fail-closed gate was correct every time.** The domains genuinely were unavailable:

| domain | cause |
|---|---|
| `health_data_quality` | `cio_wake_dispatch_entrypoint` built `CIORunWorker` **without `health_boundary`** |
| `operator_profile` | same call, store never passed |
| `watch_intelligence` | snapshot resolves `getattr(mod, "get_watch_intelligence")` — **the function never existed**; miss swallowed by `except (ImportError, AttributeError): pass` |
| `portfolio` | freshness stamped from `as_of`, a **date-only** field |

Both stores existed and construct cleanly; they were simply never passed. The `watch_intelligence` module exposed `list_watch_intelligence` and `project_watch_intelligence_for_cio` but never the name the snapshot asks for, while 25 live cards sat behind it.

`portfolio` is the subtle one. `as_of` is written by `portfolio_loader` as `date.today()`; a date parses to midnight, so against the 12-hour threshold the domain went stale **every day at noon** regardless of freshness — structurally incapable of passing.

### The fail-open trap

The snapshot's freshness check swallows a parse failure and leaves the domain `AVAILABLE`:

```python
try:
    as_of_dt = datetime.fromisoformat(evidence.as_of)
    ...
except (ValueError, TypeError):
    pass          # <- domain stays AVAILABLE
```

`generated_at` is written as `"%Y-%m-%d %H:%M:%S ET"`, which `fromisoformat` cannot read. Handing it through raw would have marked the domain **permanently fresh** — fail-open on a gate guarding account state. `_portfolio_as_of()` converts ET to an aware ISO-8601 stamp and falls back to the old date, which ages out and blocks, on anything unconvertible.

**Note:** freshness comes from the collector's `as_of` **dict key**, not from the registry's `freshness_timestamp_field`. That field is documentation; it was corrected to `generated_at` so the metadata stops contradicting the code.

`positions_as_of` is retained: repricing refreshes prices, not positions. `generated_at` advances on reprice alone, so the position-build date is kept rather than dropped — it reads `2026-07-17`, and `_canonical_reconcile` is 12 days behind. That gap is real, separate, and stays visible.

**The gate itself is untouched**, and a test asserts it: fixing producers is the repair; weakening the gate is not.

### Same defect elsewhere, not fixed

A guard test walks the whole `_EXTERNAL_ADAPTER_FUNCTIONS` mapping rather than the one broken symbol, and found:

- `analyst_detail` has no `get_analyst_detail()`
- `reentry_decision_desk` has no `get_reentry_decision_desk()`
- `catalyst_record.get_catalyst_record` exists but requires `(db_query, symbol)` the snapshot never passes

None is REQUIRED for the currently blocked run purposes. Writing wrappers for adapters whose data path is unverified would trade a visible gap for a plausible-looking empty one, so they are **named in the test**, not silently skipped — a new instance fails CI.

---

## 5. Liveness — monitoring absence of throughput

**PR #558.** The gate blocked for 17 continuous days and nothing raised an alarm. Every block was recorded faithfully; no monitor watched the record.

Parsing error logs would not have helped: **there was no error.** The gate was working correctly and saying so. A broken lane and an idle lane look identical from outside, because both emit nothing.

`PipelineLiveness@v1` measures what a lane **produced** against what it **attempted** in a rolling window:

| status | meaning |
|---|---|
| `STARVED` | work entered, nothing came out — the 17-day shape |
| `QUIET` | no work, no output — a quiet weekend, not a fault |
| `UNKNOWN` | source unreadable — never reported as healthy |
| `LIVE` | producing at or above its floor |

Without the QUIET/STARVED split the monitor fires on every idle window and gets muted, which is the same outcome as no monitor.

```
python scripts/pipeline_liveness_report.py [--json] [--fail-on-finding]
```

Read-only: writes nothing, sends nothing, holds no authority. `--fail-on-finding` exits 1 so cron or CI can gate on it. **Wiring it to an alert channel is a separate, explicit decision and is not done here.**

The memory probe counts `display_status: ADMITTED`, not `accepted`: 396 of 403 admissions are accepted while only 2 are ADMITTED, so counting `accepted` reports that lane healthy at a **0.5% promotion rate** — precisely the blindness the module exists to remove.

---

## Operational notes

- **`promote` without `prepare`** re-activates the previously prepared release and still prints `PROMOTE OK`. The only tell is the SHA. Always `prepare` then `promote`, then verify the live directory independently — never trust the script's own PASS line.
- **`mint_identity_registry.py --apply` writes production state**, resolved through `production_state_root()`, not the worktree. Pin `TRADEAI_IDENTITY_REGISTRY` for trial runs and snapshot the file first.
- **Verify additivity by diffing a byte snapshot.** Every registry change here was checked rather than asserted. Folding 4,997 swept identifiers in:

```
entities                     5,282 -> 10,279
GUIDs removed                0
security_guid moved          0
CONFIRMED downgraded         0
superseded GUIDs             5,002, all resolving forward, 0 dangling
```

An id written before the upgrade still resolves after it, in both directions — the lifecycle guarantee, exercised on 5,002 live upgrades rather than asserted in a test.

---

## What remains

1. ~~**The CIO arc never records a checkpoint.**~~ **RESOLVED the same evening, #560.** Each arc now finishes its own record rather than the two being merged: research settles its notification stage as NOT_REQUIRED with a recorded reason, and CIO runs persist the `OutcomeCheckpoint@v1` they never wrote. The predicate is untouched. Full record: `LOOP_CLOSURE_2026-08-27.md`.
2. **Bitemporal writers.** `MemoryFact@v2` defines `valid_from` / `valid_to` / `tx_from` / `tx_to`; live records carry `as_of` + `expires_at` and **0/441** carry the bitemporal pair.
3. **Promotion tiers.** The ladder is `CANDIDATE / ACTIVE / DISPUTED / EXPIRED / RETRACTED / SUPERSEDED`, with no `SUPPORTED` or `RATIFIED`. Live: 437 CANDIDATE, 2 ACTIVE.
4. **`memory_m2_v2` has zero non-test consumers.** It already carries `tstzrange` and `FORCE RLS`. The cutover delivers row-level locking and the audit partition together.

**The pattern worth naming:** every capability above already had an implementing module. The recurring failure in this codebase is building the contract and never wiring the caller — and each artifact passes its own tests, so nothing reports a problem. Four of the six fixes here were one-line or one-function wiring joints, not new systems.
