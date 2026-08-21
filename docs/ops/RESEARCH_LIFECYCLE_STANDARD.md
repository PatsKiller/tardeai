# Research Algorithm and Re-Research Methodology

**Status:** Canonical standard for research lifecycle management  
**Authority:** READ_ONLY_ADVISORY  
**Date:** 2026-08-21  
**Owner (policy):** operator  
**Owner (code):** `scripts/research_scheduler.py` · `scripts/lib/hermes_research_queue.py` · `scripts/lib/hermes_research_policy.py` · `scripts/lib/hermes_research_fingerprint.py` · `scripts/lib/symbol_thesis_coverage.py` · `scripts/lib/hermes_librarian/freshness.py`

Research is **incremental, change-driven, and freshness-based**. It is not a full re-research of all content on every run. This minimizes compute cost, reduces processing time, and keeps research current without repeatedly analyzing unchanged information.

Related: `docs/RESEARCH_PRIORITIZATION.md` (who/when/which lane). This file is **whether to execute** a research pass. SLA “due” does not mean “re-analyze identical content.”

US overnight (22:00–06:00 ET): **deterministic jobs only**. If an LLM is required, **ChatGPT OAuth** — not gemma3-overnight. That model is installed but the China-night timer currently produces empty `RESULT: {}` during US daytime.

**Holdings denominator:** `scripts/lib/holdings_universe.py` (`held_equity_tickers`). Coverage and T0-HOLD call this function. CASH and unresolved CUSIPs are not thesis tickers. Snapshot: `data/cio/holdings_universe_latest.json`.

---

## Core principle

Research runs only when **one** of the following is true:

1. **New information detected**
   - A source has changed since the last research cycle.
   - New documents, records, or data were added.
   - Existing content was modified.
2. **Scheduled refresh of stale work**
   - A cadence job fires (nightly / holdings cycle / cold-floor).
   - The job evaluates only content that is **new**, **changed**, or **older than the freshness threshold**.
3. **Explicit user or system trigger**
   - Operator requests a refresh (Telegram NEED_DATA, `--apply` with force, desk action).
   - A workflow or event says prior research may be invalid (catalyst, thesis invalidation, zone/state change).

### What must not happen

- Previously researched content is **not** re-researched on every execution.
- Unchanged data **reuses** existing research from the store or cache.
- Identical content is **not** analyzed twice.
- A calendar SLA tick is **not** a license to burn tokens on a byte-identical source.

---

## Research index (required fields)

Every researchable source/symbol keeps an index row:

| Field | Meaning |
|-------|---------|
| `source_id` | Stable identifier (symbol, URL, document id, request fingerprint) |
| `last_modified_at` | Source mtime / as-of from the producer |
| `last_researched_at` | When research last **executed** (not skipped) |
| `content_hash` | Version of the source payload (not the prose restatement of the last answer) |
| `fresh_until` | Optional explicit expiry; else derive from class SLA |

Before initiating research:

1. Load the index row for `source_id`.
2. Compare current `content_hash` (or modification timestamp) to the stored value.
3. If **unchanged** and still inside freshness → **skip**, reuse stored output.
4. If **changed** or **past freshness** or **explicit trigger** → execute, then update the index.

---

## Nightly / cadence refresh

Process only:

- New content
- Changed content
- Content exceeding the freshness threshold

Skip all unchanged and still-valid records.

Class freshness (implemented in `symbol_thesis_coverage.py` `CLASS_SLA_DAYS` / `stale_days_for`):

| Class | Max age before forced refresh |
|-------|-------------------------------|
| Held, income-critical | 14d |
| Held, growth/core | 30d |
| Reentry READY/NEAR | 14d |
| Watchlist actionable | 45d |
| Held, index/bond | 90d |
| Hermes result reuse TTL (queue) | 2h–24h by priority (`hermes_research_policy.py`) |

A catalyst, earnings, dividend action, or operator NEED_DATA **short-circuits** the age gate (coverage does not mark STALE solely by calendar age; `coverage_reason` records the short-circuit). Held coverage SLA is **100%** `coverage_pct` **and** `fresh_pct` (`cio_held_thesis_coverage.py`). That target is **not currently met live** — the report measures the gap; it does not claim the book is fully covered.

---

## Decision log (required)

Every candidate must log exactly one of:

| Code | Meaning |
|------|---------|
| `RESEARCH_EXECUTED` | Research ran; index updated |
| `SKIP_UNCHANGED` | Hash/mtime match; reused store |
| `SKIP_FRESH` | Unchanged or equivalent work still inside TTL |
| `RESEARCH_TRIGGERED` | Operator/event force; ran even if hash matched |

Do not collapse skip into silence. Cost attribution (Phase A) depends on these codes.

---

## What is implemented vs gap `[VERIFIED]` / `[DOC-CLAIMED]`

| Piece | State | Evidence |
|-------|-------|----------|
| Request fingerprint (same *ask*) | **Implemented** | `hermes_research_fingerprint.py` `fp@v1` |
| Result TTL reuse | **Implemented** | `hermes_research_queue.py` → `try_reuse_completed_result` (`reused_fresh_result`) |
| In-flight duplicate | **Implemented** | queue `duplicate_in_flight` |
| Calendar SLA dispatcher | **Implemented** | `research_scheduler.py` `TIER_SLA` — *due set can still re-call lanes without a source-hash skip* |
| Output-prose fingerprint | **Implemented** | scheduler `_research_fingerprint` on recommendation+confidence (downstream *diff*, not skip-before-call) |
| Hours-window skip | **Partial** | `hermes_top20_external_intel.py` `FRESH_HOURS=12`; scheduler backfill `RESEARCH_BACKFILL_SKIP_FRESH_HOURS` |
| Thesis STALE by age | **Implemented** | `symbol_thesis_coverage.py` class SLAs via `stale_days_for`; `STALE_DAYS_DEFAULT=30` is fallback only |
| Librarian 30d archive | **Implemented** | `hermes_librarian/freshness.py` |
| Unified source **content_hash** index | **Gap** | No single store with source_id + last_modified + last_researched + hash |
| Unified skip log (`SKIP_UNCHANGED` / `SKIP_FRESH`) | **Gap** | Queue has reuse reasons; scheduler prints material-change; not one ledger |
| Thesis class SLAs 14/30/45/90d | **Implemented** | `CLASS_SLA_DAYS` in `symbol_thesis_coverage.py`; held report publishes `coverage_pct` **and** `fresh_pct` with SLA 100% (`held_n` = 22 via `holdings_universe`). **Not currently met live.** |

Until the unified index exists, **new** research producers must implement the index fields and skip codes. Do not add a lane that always re-runs.

---

## Ownership

| Concern | Module |
|---------|--------|
| Whether to enqueue vs reuse a Hermes *request* | `hermes_research_queue.py` + `hermes_research_policy.py` |
| Whether two requests are the same work | `hermes_research_fingerprint.py` |
| Which symbols are *due* this cycle | `research_scheduler.py` + `docs/RESEARCH_PRIORITIZATION.md` |
| Thesis CURRENT vs STALE | `symbol_thesis_coverage.py` / `cio_held_thesis_coverage.py` |
| Source-file freshness / archive | `hermes_librarian/freshness.py` |

Scheduler authors: **due ∩ (changed ∪ stale ∪ triggered)** is the execute set. `due` alone is not.

---

## Rollback / compatibility

This document does not flip flags or change defaults. Existing TTL reuse and fingerprints stay. The standard forbids new full-sweep research jobs.
