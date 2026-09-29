# Cross-Asset Decision Intelligence — Readiness Report

Status: ACTIVE  
as_of: 2026-09-29T17:55:00-04:00  
Measured at: worktree `wt/cross-asset-decision-intel` after Phase 1–3 scaffold + hermetic green  
Authority: Operator program 2026-09-29  
See also: Implementation Plan, Test Plan, Backlog

---

## Architecture Complete

**NO** (scaffold only through Phase 3 expression router; Phases 4–10 incomplete)

Completed:
- SymbolDecisionObject@v1 schema + validator + JSONL persistence
- Assemble from Hermes/provenance/holdings/signal/CIO/options packet snapshots
- Shadow expression router for Buy/Hold/Reentry/Sell with honest `collar` unavailable
- Flag-gated research-complete hook (`CROSS_ASSET_SHADOW`)
- Missed-opportunity expression ledger
- Historical replay CLI that refuses invented counterfactuals (`INSUFFICIENT_DATA`)
- Shadow cycle CLI (dry-run / apply-ledger)

Not complete:
- Live event wiring into Hermes/watch/reentry producers (stub only)
- Chain-priced EV / comparable ranking engine
- UI
- Continuous shadow systemd
- 30/60/90d archive-backed replay with metrics that answer “would options have been superior?”

---

## Tests Passed

**8 / 8** hermetic (`tests/test_cross_asset_symbol_decision_object_20260929.py`)

Evidence: `/tmp/cadi_pytest.txt` — `8 passed in 0.27s`  
Gate registered: `cross_asset_decision_intel_20260929` in `run_cio_hardening_ci.py`

## Failed Tests

**0** (current suite)

---

## Historical Validation Results

| Window | data_quality | signals_evaluated | options_superior_rate |
|---|---|---|---|
| 30d | INSUFFICIENT_DATA | 0 | null |
| 60d | INSUFFICIENT_DATA | 0 | null |
| 90d | INSUFFICIENT_DATA | 0 | null |

Artifact: `/tmp/cadi_hist_metrics.json` (regenerate via `scripts/ops/run_cross_asset_historical_replay.py`)

**Honesty:** Without signal/price/chain archives, the harness correctly refuses to invent superiority metrics.

---

## Known Risks

1. Expression `expected_value` is null — ranking is structural order, not EV.  
2. Collar remains unavailable (matrix ABSENT).  
3. Shadow flag default OFF — no continuous reevaluation in production yet.  
4. Assembled objects from live stores not yet wired; fixtures prove shape only.  
5. Promoting this module without EV model would create false confidence in “top_family”.

---

## Technical Debt

- Duplicate decision payload families still coexist (DecisionPayload@v1, OptionsDecisionPacket@v2, SymbolDecisionObject@v1) — intentional adapter stage.  
- No Postgres projection for SymbolDecisionObject.  
- No CC UI.  
- Historical archives not defined/contracted.

---

## Go-Live Recommendation

### **NOT READY**

**Reasoning:** The program asked whether the system can answer “highest expected-value expression of that thesis, and can we prove it?” Today we can:
- enumerate candidate expressions honestly,
- persist a canonical object,
- run shadow dry-runs,
- refuse fake historical superiority claims.

We **cannot** yet prove EV superiority across shares vs options with chain economics, continuous shadow evidence, or 30/60/90d counterfactuals. Production routing on this scaffold would over-claim.

### Conditional path to READY
1. Wire Phase 4 events + run shadow ≥14 days with ledger growth metrics.  
2. Implement Phase 6 EV using real chains; keep advisory.  
3. Land archives + Phase 9 metrics with non-null superiority rates on a defined universe.  
4. Operator review of Readiness READY + feature flag grant.

---

## Auditable trail (this cut)

| Artifact | Path |
|---|---|
| Plan | `docs/CROSS_ASSET_DECISION_INTELLIGENCE_IMPLEMENTATION_PLAN.md` |
| Backlog | `docs/CROSS_ASSET_DECISION_INTELLIGENCE_BACKLOG.md` |
| Test plan | `docs/CROSS_ASSET_DECISION_INTELLIGENCE_TEST_PLAN.md` |
| Code | `scripts/lib/cross_asset/*`, `scripts/ops/run_cross_asset_*.py` |
| Tests | `tests/test_cross_asset_symbol_decision_object_20260929.py` |
| Commits | `bc9b38c1d` + `1a406daa5` on `wt/cross-asset-decision-intel` |
