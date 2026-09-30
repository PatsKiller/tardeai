# Cross-Asset Decision Intelligence — Executable Backlog

as_of: 2026-09-29  
Authority: `docs/CROSS_ASSET_DECISION_INTELLIGENCE_IMPLEMENTATION_PLAN.md`

## Tickets

### CADI-001
- **Title:** SymbolDecisionObject@v1 schema + validator
- **Purpose:** Canonical object with required field groups; refuse unknown authority.
- **Files:** `scripts/lib/cross_asset/__init__.py`, `scripts/lib/cross_asset/symbol_decision_object.py`
- **Changes:** dataclass/dict schema, `validate_symbol_decision()`, `new_symbol_decision()`
- **Tests:** `tests/test_cross_asset_symbol_decision_object_20260929.py`
- **Risk:** Low
- **Required reviewer:** Staff Eng (self) + CIO Ops on merge

### CADI-002
- **Title:** Append-only persistence ledger
- **Purpose:** Persist decisions to `data/cio/symbol_decisions.jsonl` without mutating callers on failure.
- **Files:** `scripts/lib/cross_asset/persistence.py`
- **Changes:** `append_symbol_decision()`, `load_latest_by_symbol()`
- **Tests:** same unit file (tmpdir)
- **Risk:** Low
- **Required reviewer:** Staff Eng

### CADI-003
- **Title:** Assemble from existing stores (best-effort)
- **Purpose:** Build object from symbol + optional Hermes result id / holdings / provenance dicts (no live DB required in unit tests).
- **Files:** `scripts/lib/cross_asset/assemble.py`
- **Changes:** `assemble_symbol_decision(symbol, *, provenance=, hermes_result=, holdings_row=, signal=, cio=)`
- **Tests:** fixture-based assemble for NFLX-like payload
- **Risk:** Medium (partial data honesty)
- **Required reviewer:** Staff Eng

### CADI-004
- **Title:** Expression router (shadow)
- **Purpose:** For Buy/Hold/Reentry/Sell, emit ExpressionCandidate list using strategy matrix; mark absent families unavailable.
- **Files:** `scripts/lib/cross_asset/expression_router.py`
- **Changes:** `route_expressions(signal_kind, position_state, options_hints=)`
- **Tests:** matrix coverage + collar unavailable
- **Risk:** Medium
- **Required reviewer:** Options desk owner + Staff Eng

### CADI-005
- **Title:** Shadow cycle CLI
- **Purpose:** One-shot evaluate symbols from a list; write ledger; never trade.
- **Files:** `scripts/ops/run_cross_asset_shadow_cycle.py`
- **Changes:** CLI `--symbols NFLX,AAPL --dry-run/--apply-ledger`
- **Tests:** dry-run path in unit test via import
- **Risk:** Low
- **Required reviewer:** Ops

### CADI-006
- **Title:** Missed-opportunity expression ledger
- **Purpose:** Record when chosen expression ≠ top-ranked shadow expression.
- **Files:** `scripts/lib/cross_asset/missed_opportunity_ledger.py`
- **Changes:** append to `data/cio/expression_missed_opportunities.jsonl`
- **Tests:** counterfactual fixture
- **Risk:** Low
- **Required reviewer:** Staff Eng

### CADI-007
- **Title:** Historical replay harness (30/60/90 scaffolding)
- **Purpose:** Replay signal JSONL windows; compute metrics stubs when price/chain archives absent (honest INSUFFICIENT_DATA).
- **Files:** `scripts/ops/run_cross_asset_historical_replay.py`
- **Changes:** window args; metrics JSON out
- **Tests:** empty archive → INSUFFICIENT_DATA metric path
- **Risk:** Medium
- **Required reviewer:** QA Lead

### CADI-008
- **Title:** Register hermetic gates
- **Purpose:** Add tests to `run_cio_hardening_ci.py` GATES.
- **Files:** `scripts/run_cio_hardening_ci.py`
- **Changes:** gate `cross_asset_decision_intel_20260929`
- **Tests:** gate registration presence test optional
- **Risk:** Low
- **Required reviewer:** Staff Eng

### CADI-009
- **Title:** Event hook stub (flag-gated)
- **Purpose:** `maybe_reevaluate_on_research_complete(symbol, result_id)` no-op unless `CROSS_ASSET_SHADOW=1`.
- **Files:** `scripts/lib/cross_asset/events.py`
- **Changes:** flag check + assemble+route+persist
- **Tests:** flag off → no write
- **Risk:** Medium
- **Required reviewer:** Staff Eng

### CADI-010
- **Title:** Docs — test plan + readiness (living)
- **Purpose:** Auditable trail through shadow and recommendation.
- **Files:** `docs/CROSS_ASSET_DECISION_INTELLIGENCE_TEST_PLAN.md`, `docs/CROSS_ASSET_DECISION_INTELLIGENCE_READINESS_REPORT.md`
- **Changes:** update after each phase
- **Tests:** n/a (doc)
- **Risk:** Low
- **Required reviewer:** CIO Ops Architect

### CADI-011 — DONE (hermetic)
- **Title:** Hermes complete → shared spine upsert
- **Purpose:** Organic producer: when Hermes stamps a completed result, append
  `SecurityResearchSpine` (gated by `CROSS_ASSET_SPINE` / `CROSS_ASSET_SHADOW`).
- **Files:** `scripts/lib/cross_asset/hooks.py`, `scripts/lib/cio_hermes_research.py`
- **Changes:** `notify_hermes_result_completed` fail-soft after `_persist_stamped_result`
- **Tests:** `tests/test_cadi_spine_hooks_20260929.py`
- **Honesty:** hermetic ≠ OBSERVED until promote + live Hermes complete with flag on

### CADI-012 — DONE (hermetic)
- **Title:** Desk consumers prefer shared spine
- **Purpose:** Options / watch / reentry / holdings see the same CIO thesis.
- **Files:** `hooks.overlay_thesis_fields_from_spine`, `symbol_thesis_attach.thesis_fields_for_symbol`,
  `options_engine._research_universe_rows` / `_reentry_research_rows`
- **Changes:** overlay on thesis attach; spine rows first in options universe merge; reentry overlay
- **Tests:** `tests/test_cadi_spine_hooks_20260929.py` (+ spine unit file)
- **Honesty:** wiring proven hermetically; organic E2E needs Bill C live canary

### CADI-013
- **Title:** Spine coverage metric
- **Purpose:** % of researched symbols with POPULATED spine
- **Status:** open

### CADI-014
- **Title:** CC API spine read
- **Purpose:** `GET /api/v2/research/spine/{symbol}`
- **Status:** open

---

## Order of execution

1. CADI-001 → 002 → 003 → 004 → 005 → 008 (ship Phase 1–3 core)  
2. CADI-006 → 007 → 009  
3. CADI-010 continuous updates  
4. CADI-011 → 012 (producer/consumer hooks) — **landed hermetic 2026-09-29**  
5. CADI-013 → 014; UI deferred until shadow metrics exist  
6. Organic OBSERVED canary after promote + `CROSS_ASSET_SPINE=1`  
