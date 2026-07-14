# Redeploy semantic-integrity release — defect-to-code map (Phase 0)

Operator review 2026-07-14 (post-Phase-13). 23 defects → root causes. Advisory-only throughout.

| # | Defect | Root cause (file:symbol) | Fix |
|---|---|---|---|
| 1 | oversight=pending shown OPERATOR-READY | `RedeployDesk.tsx:planReadiness` treats `pending` as ready; `redeploy_plan_engine._plan_shell` never requires pass for majors (UI-side only) | server-side readiness state machine (`redeploy_decision.readiness_state`); majors require `oversight_status=='passed'`; UI shows `ANALYTICS READY — OVERSIGHT PENDING` |
| 2 | plan dollars ≠ $107,023 (up to $1,659 vanishes) | `_equity_leg` keeps whole-share `filled`, drops fractional remainder; no residual leg; Plan F ignores `net − stage − reserve` | financials block on every plan: `strategic_target + reserve + whole_share_residual = deployable` (invariant asserted at generation) |
| 3 | 3 different Plan-F deploy totals | Plan Lab = whole-share filled at gen quotes; Entries = staged limit prices; Pro forma = modeled closes | canonical snapshot exposes all four labeled figures (`strategic_target/executable_at_current_quote/staged_limit_order/modeled_post_fill`); tabs annotate which they show |
| 4 | Plan F export blocked by XLC (Plan B leg) | `entry_planner_adapter.assess_export_readiness(plans)` unions ALL plans' legs | per-plan readiness: gate on the exported plan's legs only |
| 5 | settlement language after verification | `_plan_shell` objectives/risks are static strings ("before settlement", "Time to reconcile settlement") | narratives derived from `recon.reconciliation_status` + regime; regeneration on state change (new version) |
| 6 | Audit tab empty at v22 | audit rows lived only in `redeploy_monitor_audit` (fills/locks; wiped in fixture cleanup); no lineage writer | `redeploy_audit_log` table + writer + backfill for #144 (`INFERRED_FROM_CURRENT_STATE` where unprovable) |
| 7 | plan performance excludes 75% reserve | `redeploy_performance.plan_performance` weights non-reserve legs only | dual blocks: `invested_sleeve` + `whole_plan` (reserve at its vehicle yield) |
| 8 | income differs across tabs | three independent calcs (dividend_calendar.json in engine; facts/trailing in performance; pro forma own) | one `redeploy_income.income_snapshot()` used by engine, performance, pro forma, memo; carries `yield_type/source/as_of` |
| 9 | FCNTX "unknown" + 4.27% simultaneously | memo reads `exposure.income_status`; performance computes trailing yield separately | income model distinguishes `trailing_distribution_yield` (KNOWN) vs recurring-income estimate (ordinary-vs-capgain split UNAVAILABLE — stated) |
| 10 | ±1σ bands labeled bull/base/bear | `plan_scenarios` row labels | relabeled `+1σ/zero-drift/−1σ statistical shock`, kind `STATISTICAL_BAND` |
| 11 | recession renders 0% @76% cov | reserve counts as 0%-covered → 0/reserve = 0% | risky-leg coverage tracked separately; when 0 → `UNAVAILABLE_FOR_RISKY_LEGS`, no number |
| 12 | Plan B claims "all GICS buckets" | objective string; engine restores top-5 sectors + BND | honest label "partial multi-sector restoration + fixed-income ballast"; per-sector restoration shown |
| 13 | Plan E $53k vs $2.7k gap | `_sleeve_gap_etfs` even-splits FULL deployable | sized `min(gap_usd, tactical_sleeve_budget, concentration_cap, deployable)`; surplus → reserve |
| 14 | Plan A mislabeled close replacement | objective string on 45/35/20 QQQ/SCHD/BND | relabeled "strategic redesign"; quantified deltas in compromises |
| 15 | QQQM "rejected" with favorable text | rejected rows reuse v1 `rationale` verbatim | real rejection codes + reason; QQQ-vs-QQQM competition shown on the leg |
| 16 | leg roles blank | legs never had a `role` field | every leg carries `role` |
| 17 | wrappers in issuer table | `redeploy_pro_forma._issuer_overlap` mixes fund tickers with underlying | 3 tables: direct+wrappers / underlying issuers / unresolved coverage |
| 18 | FORUM/WOULD/OWN/TOO as tickers | `hermes_discovery_candidates.extracted_symbols` prose tokens pass `assemble_universe` | security master validation (known-symbol sources + prose blacklist) → `INVALID_SYMBOL` |
| 19 | MSFT/NVDA "insufficient history" | never backfilled (95-symbol set); one bucket for all failures | classified `HISTORY_NOT_LOADED` vs `INSUFFICIENT_TRADING_HISTORY` vs `HISTORY_PROVIDER_FAILED`; auto-backfill attempt for valid candidates |
| 20 | universe doesn't drive plans | `build_institutional_plans` hardcoded weight lists | role-based selection from candidate universe with competition evidence (rank, alternatives, margin) per leg |
| 21 | PM memo = sentence + raw JSON | `memo` f-string; UI dumps narrative | structured memo builder (18 sections) + professional render |
| 22 | comparison opens empty | `compareIds` starts `[]` | preload system-primary + strategic + income + staged |
| 23 | primary/selected/locked conflated | one `SELECTED` chip | distinct chips: SYSTEM PRIMARY / OPERATOR SELECTED / OPERATOR LOCKED / HIGHEST QUANT RANK |

Tests required: reconciliation invariant, cross-tab consistency, readiness gating, narrative regeneration,
whole-plan performance, scenario honesty, candidate integrity, look-through separation, audit non-empty,
UI states — see `tests/test_redeploy_semantic_integrity.py` (Phase 18).
