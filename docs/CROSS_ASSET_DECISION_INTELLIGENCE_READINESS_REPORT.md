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

---

## 2026-10-09 supplement — offline replay repaired; production NOT_READY

Status: SOURCE_ONLY implementation / TEST_ONLY validation; production **NOT_READY**

Source checkpoint: `e9c0b5d5c6fc0ecbdd8e27b5bf66eed1ce948817`, branch
`wt/cadi-archive-replay-20261009`, based on main
`bbff99766cd80ea630543abfaa639eb41eae5eb9`. The September 29 measurements above
are preserved as historical evidence. Their zero/null 30/60/90 results are
**STALE_HISTORICAL**, not a fresh October 9 production replay.

The offline CLI now reads timestamped archived events, confirmed identities,
actual spot-price snapshots and optional per-structure evaluator facts. It
uses the existing pure advisory evaluator, reports price coverage and skipped
inputs, excludes facts known after the signal, and refuses malformed or
conflicting input. The adapter and its limits are defined in the
[offline archive contract](implementation/CADI_OFFLINE_HISTORICAL_REPLAY_ARCHIVE_CONTRACT.md).
Supplied scores support `SCORING_COMPARISON_ONLY`; they do not establish
realized options superiority, actual fills or a new analytical model.
`options_would_be_superior` and `options_superior_rate` remain null.

Validation: **46 TEST_ONLY tests passed** across replay/core,
SymbolDecisionObject and shared-spine hook families. The prior-defect test
proved that a valid archive formerly produced `signals_evaluated=0`; 17 new
cases failed on the original stub. A separate negative proved equal-time
conflicting facts must be compared as instants across UTC offsets. Evidence:
`/tmp/tradeai-cadi-replay-negative-prior-20261009.log`,
`/tmp/tradeai-cadi-replay-offset-negative-20261009.log`,
`/tmp/tradeai-cadi-replay-regression-final-20261009.log`, and the source/log hash
manifest `/tmp/tradeai-cadi-replay-source-handoff-20261009.json`.

The independent live audit, measured October 9 at 13:45:32 UTC against CURRENT
`a9fa8b89b616f685145d27d6d2d62da3a1fab970`, found:

| Evidence class | Observation | Readiness implication |
|---|---|---|
| OBSERVED_HOST | Canonical `symbol_decisions` and `expression_missed_opportunities` ledgers absent at their declared paths; no dedicated current decision RunReceipt found | Continuous expression decisions and their durable proof remain unproven |
| OBSERVED_HOST | Shared research spine has 775 rows, latest 13:31:17 UTC | Fresh research memory is not an expression-decision ledger or counterfactual proof |
| OBSERVED_DB | 48,419 option-chain snapshots are summary-only; zero full contract/expiration arrays or embedded quote timestamps | These records cannot establish historical per-contract option economics |
| OBSERVED_DB / SOURCE_ONLY producer semantics | Historical action signals use `UPSERT(signal_date,symbol)`; bars can arrive later and be updated for the same market time | Mutable latest rows and late ingestion do not prove what was available at a historical signal instant |
| NOT_MEASURED | No fresh actual-archive 30/60/90 replay result | Fixture success cannot close the production historical-validation requirement |

Audit artifacts: `/tmp/crossasset-live-gap-assessment-20261009T134300Z.json`,
`/tmp/crossasset-live-gap-audit-20261009T133138Z.json`, and
`/tmp/crossasset-archive-asof-audit-20261009T134145Z.json`. The latter cites the
summary writer (`scripts/options_desk_enterprise.py:1851`), signal upsert
(`scripts/db_adapter.py:587`) and bar upsert
(`scripts/market_data_snapshot_loader.py:100`). These are dated read-only
observations; this supplement does not claim a later deployment or live replay.

Remaining prerequisites are immutable canonical event/decision lineage,
market-time **and availability-time** proof, full historical option economics,
actual 30/60/90 archive coverage, and the production producer → receipt → output
→ consumer chain. No model/provider was selected or called, no production
archive exporter was added, and no scheduler or financial authority changed.
The end-to-end program and expression-EV recommendation remain **NOT_READY**.


### October 9 independent-review correction checkpoint

At source checkpoint `1d92fd2c01b00cbc943d52cda904473e605fe288`, the final
three-family CADI regression is **53 TEST_ONLY tests passed** (2.29 seconds).
This adds archive-alias preservation and derived-nonfinite-score refusal to the
`e9c0b5d5c` / 46-test checkpoint above; that earlier receipt is preserved.
The new negative first proved seven failures, including actual input-byte
corruption through hardlink/symlink output aliases and a finite-input calculation
that produced Infinity. The fix refuses aliased outputs before writing and
returns typed `INVALID_DATA` rather than an unbounded score or uncaught dump
error. It changes no evaluator thresholds or model selection.

Evidence: `/tmp/tradeai-cadi-replay-alias-overflow-prior-20261009.log` and
`/tmp/tradeai-cadi-replay-alias-overflow-final-20261009.log`. The independent
prior reproduction is
`/tmp/cadi-replay-independent-prior-probes-20261009.json`. These are source and
fixture checks; actual-archive 30/60/90 validation and production readiness
remain **NOT_READY / NOT_MEASURED**.
