# Canonical observation contract

Status: ACTIVE
Schema: `CanonicalObservation@v1`
Module: `scripts/lib/canonical_observation.py`
Origin: audit `cc-truth-v1-20260902T202759Z`
Authority: READ_ONLY_ADVISORY metadata. No financial calculation, no broker authority, no scheduler.

## The defect this closes

`/api/v2/overview` builds one payload from four stores. Before this contract it emitted the
**value** from one store and the **freshness metadata** from another with nothing checking that
they described the same moment. The audit measured the result:

| field | store | age at capture |
|---|---|---|
| `portfolio_value` | `portfolio_snapshot.json` | 3.3 s |
| `data_as_of` | `holdings.json` | correct (oldest contributing row) |
| `periods` | `performance_history.json` | **7.4 days** |
| `pipeline_status` | `_freshness.json` | **meaningless** |

The page was not showing stale data. It was showing **fresh values wearing stale metadata**.

Two independent defects produced the `Data: fresh` label, and they concealed each other:

1. **The value was a constant.** `portfolio_orchestrator.py` wrote `"status": "fresh"` with no
   branch that could write anything else. A file that stopped moving in August read `fresh`
   in September.
2. **The file it read had been stranded.** Producers run under `cd $PROJ` and wrote the checkout
   tree; the served API reads `persistent-state`. Separate inodes. `_freshness.json`,
   `performance_history.json` and `portfolio_news.json` diverged; `holdings.json` did not.

**Fixing either one alone looks like it worked.** Root synchronization leaves a literal that
cannot express staleness. Replacing the literal leaves it computing staleness from a file nothing
updates. Both are fixed here, and `tests/test_canonical_observation.py` pins both.

## The contract

Anything that emits a value emits an `ObservationEnvelope` with it, so the number and its date
cannot be recombined wrongly:

| field | meaning |
|---|---|
| `dataset` | logical store name |
| `source_identity` | the resolved path actually read |
| `account_scope` | which accounts the value covers |
| `provider_timestamp` | the producer's own stamp, verbatim |
| `observed_at` / `received_at` / `normalized_at` | three clocks, never collapsed |
| `business_date` | trading date the value belongs to |
| `market_session` | PRE_MARKET / REGULAR / AFTER_HOURS / CLOSED / WEEKEND |
| `timezone_label` | zone the timestamps are normalized to (UTC) |
| `freshness` | `{status, age_seconds, age_hours, threshold_hours, reason, precision}` |
| `quality` | OK / DEGRADED / MISSING / UNPARSABLE |
| `entitlement` | INTERNAL |
| `sequence` | monotonic version when the producer supplies one |
| `source_hash` | SHA-256 of the bytes read |
| `calculation_version` / `contract_version` | so a consumer can refuse an unknown shape |
| `fallback` | NONE / FALLBACK_USED / SOURCE_MISSING |
| `trace_id` | one id binds a whole observation set |

## Fail-closed freshness

`compute_freshness` has **no input that yields FRESH by default**:

| input | verdict |
|---|---|
| missing / empty | UNKNOWN |
| unparsable | UNKNOWN |
| future beyond 120 s | UNKNOWN (clock fault, not freshness) |
| no agreed threshold for the dataset | UNKNOWN |
| older than the threshold | STALE |
| real timestamp within a real threshold | FRESH |

A surface is only as fresh as its **oldest** contributing dataset — `worst_status()`, following
AGENTS.md 9.1 ("a 27-day-old $500 makes the block 27 days old"). UNKNOWN outranks STALE: an
unknown age cannot be argued down into a stale one.

### Date-only inputs

`data_as_of` is emitted date-only with no time and no zone. Against a 36 h threshold, midnight
versus 16:45 is a **16.75 h swing** — enough to flip the verdict alone. The envelope marks these
`precision: "date_only"` rather than silently assuming midnight is an instant.

## One write, every reader

`write_state_json()` writes one in-memory object to every state root a reader may use, served copy
first, deduped by realpath, and never lets a second destination break the first. It wraps the
existing `portfolio_state_write_targets()`; it is not a new storage layer.

This is the same fix `portfolio_stops.save_risk_state` already applied to `risk_management.json`
on 2026-08-28. That docstring predicted this recurrence — *"a cron-level fix leaves the next
caller free to reintroduce it"* — and three files were left behind. Fixing it at the resolution
layer rather than in cron is deliberate: a `cd` fix protects one caller, this protects the next one.

## Position-count contract

Overview reported 14, risk reported 15. **Neither was wrong.** They count different populations,
and two unlabeled integers cannot say so, which forces a consumer to read one as a contradiction
of the other. `/api/v2/overview` now publishes `position_counts` with every scope named:

| scope | rule |
|---|---|
| `overview.non_cash_over_100` | `holdings.json` rows, not cash, `market_value > 100` |
| `holdings.all_rows` | every row including cash |
| `holdings.non_cash` | not cash, no value floor |
| `risk.risk_included` | `risk_management.json` positions where not `risk_excluded` — the same rule `/api/v2/risk` uses |

plus `agree`, `distinct_values` and `scope_definitions`. The legacy scalar `position_count` is
unchanged for existing callers.

## A GET is a read

`get_portfolio_snapshot(write_on_miss=False)` recomputes in memory and publishes nothing. The
overview handler previously wrote `portfolio_snapshot.json` on every cache miss, so the snapshot
was refreshed by whoever happened to browse rather than on a schedule, and a plain `GET` mutated a
store. The parameter is keyword-only and defaults to `True`, so the four other callers keep their
exact current behaviour.

**Known consequence:** with overview no longer publishing, the 45 s snapshot cache is refreshed
only by the remaining callers. Overview recomputes in memory when none of them has published
recently. The correct end state is a scheduled publisher; that is a separate, non-additive change
and is recorded in `RISKS_AND_ROLLBACK.md` rather than smuggled in here.

## Backward compatibility

Every pre-existing `/api/v2/overview` key keeps its name and type. New keys are additive:
`observation`, `position_counts`, `pipeline_status_source`, `pipeline_status_reported`.
`pipeline_status` keeps its name but is now **computed**; the file's own claim stays visible as
`pipeline_status_reported` so a consumer can compare them.

## Diagnostics

`envelope_diagnostics()` reports source path, root kind, age, threshold, reason, quality, fallback
and a truncated content hash. It contains **no account identifier, credential, token or holding** —
`tests/test_canonical_observation.py::test_diagnostics_expose_path_age_version_and_fallback_only`
asserts that.
