# CIO source clocks and Advisory Desk dependency clocks

Status: implemented 2026-10-02 (spec Phase 6 + Phase 7). READ_ONLY_ADVISORY — no source is
written, refreshed, or recomputed by either surface.

## The rule

A clock is the time the **source's own data** was produced. The time a projection was composed
is `composition_as_of` and is never a source clock. Freshness is decided against an explicit
`stale_after_seconds`:

| freshness | meaning |
|---|---|
| `FRESH` | `age_seconds <= stale_after_seconds` |
| `STALE` | older than the budget |
| `UNKNOWN` | the source exists but carries no trustworthy timestamp (missing, unparseable, or > 5 min in the future) |
| `UNAVAILABLE` | the source cannot be read (file absent, DB error) — CIO surface only |

A timestamp merely existing is no longer enough (the operator-evidence blocks still say
`OBSERVED`; that module is owned elsewhere).

## Phase 6 — `CIOSourceClocks@v1`

Module `scripts/lib/cio_source_clocks.py`; route `GET /api/v3/cio/source-clocks`
(`api_v3_cio.get_cio_source_clocks_v1`); UI `CioSourceClocksPanel` at the top of
CIO → Evidence & comms → Operator evidence.

| source | source_ref | clock field (source's own) | stale_after | excluded on purpose |
|---|---|---|---|---|
| portfolio_cash | `data/portfolios/state/holdings.json` | `positions_built_at` → `data_as_of` | 36h | `generated_at`, `last_repriced`, `updated_at`, `total_cash_written_at` (rewritten by every 15-min reprice) |
| decision | `data/cio/cio_investment_brief.json` | `as_of` (CIOInvestmentProduct@v1) | 26h | |
| research | `data/cio/security_research_spine.jsonl` | newest `as_of` in a 256 KB tail | 48h | |
| memory | `data/cio/memory_contexts.jsonl` | newest `committed_at` | 36h | |
| analyst_data | DB `yahoo_analyst_targets_history` | `max(snapshot_date)` (date precision) | 4d | |
| technicals | DB `indicator_confluence_cache` | `max(computed_at)` | 26h | `state/data_broker/indicator_snapshot.json computed_at` (re-projection time) |
| hermes_research | `data/cio/hermes_research_results.jsonl` | newest `completed_ts` | 48h | |
| outcome_belief | `data/cio/outcome_observations.jsonl` | newest row `source_as_of` | 48h | |

`source_version` is `bytes=…;mtime_ns=…` for files and `db_max=<ts>` for tables. Budgets can be
overridden per source with `CIO_SOURCE_CLOCK_STALE_S_<SOURCE>`. Composition measured live at
~40 ms (stat + bounded tails + two `max()` queries).

## Phase 7 — Advisory Desk dependency clocks

`GET /api/v3/advisory` → `dependency_clocks` (one entry per dependency) and `dependency_refresh`
(derived). Each clock: `name, source_as_of, producer, source_ref, clock_basis, age_seconds,
freshness, stale_after_seconds, refreshed_by_run_now, next_scheduled_run,
next_scheduled_run_reason`.

| clock | source | next run from |
|---|---|---|
| advisory_synthesis | opinions `generated_at` | `tradeai-advisory-shadow-session.timer` |
| technicals | `indicator_confluence_cache max(computed_at)` (row technicals `as_of` fallback); **never** `quote.price_as_of` or the snapshot projection time | lane `indicator-cache-refresh` |
| prices | holdings repricer clock (`last_repriced`), else newest watch quote | lane `portfolio-repricer` |
| watch_intelligence | newest CIO/Maria watch review `completed_at` | lane `watch-review-workers` |
| reentry | `reentry_decision_desk_latest.json` generated_at | none declared → null + reason |
| analyst_data | target snapshot dates of rows that **have** a target | none declared → null + reason |
| research | research-delta `evidence_as_of` + agent opinions | research-scheduler lanes + `governed-research-producer` |
| hermes_research | `hermes_external_research` evidence the desk consumed | none declared → null + reason |
| durable_memory | last admitted memory | lane `advisory-shadow-seed` (systemd) |

### Run-now refresh audit

`advisory_desk_schedule._execute_run` calls `build_advisory_desk(force=True, max_age_s=0)` (re-reads
inputs; runs no producer) and `enrich_advisory_with_opinions(include_synthesis=True)`. Only
`advisory_synthesis` has `refreshed_by_run_now: true`. The test
`test_run_now_audit_matches_execute_run_code_path` pins this against the `_execute_run` source.

`dependency_refresh.older_than_synthesis` lists each dependency older than the synthesis, e.g.
`technicals 42m older than synthesis`; `status` is `DEPENDENCIES_NOT_ALL_REFRESHED` whenever any
dependency is older or has no clock. `desk_freshness_state` is scoped
(`desk_freshness_scope: DESK_COMPOSITION_ONLY`) and never implies dependencies were refreshed.

## Findings recorded while building this

* `indicator_snapshot.json computed_at` is stamped on every re-projection; the underlying
  technicals were last computed at the 05:45 ET `indicator_cache_refresh` run.
* A target-less analyst block inherits the holdings date as `target_as_of`
  (`cio_advisory_provenance` fallback), which made analyst data look current.
* Evidence-item `as_of` values from DB rows are truncated to 19 characters, dropping the
  America/New_York offset; the desk clocks re-attach it.
* `systemctl --user show … --value` prints a formatted date, not microseconds, so
  `advisory_desk_schedule._systemd_next_iso` always falls back to the computed calendar.
  `cio_source_clocks._systemd_next_elapse` parses both forms.

Tests: `tests/test_cio_source_clocks_20261002.py`,
`tests/test_cio_advisory_dependency_clocks_20261002.py`,
`tests/test_cio_advisory_dependency_clocks.py`.
