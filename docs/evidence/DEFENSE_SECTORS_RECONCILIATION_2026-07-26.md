# Defense/Sectors Production Reconciliation (Lane C)

Status:      HISTORICAL
as_of:       2026-07-26T11:30:00-04:00
Measured at: efcc51365 / not measured

Branch `codex/defense-sectors-production-reconciliation-v1`, based exactly on
`origin/main` (20a24027017a5ecb0a207ac8960ed7e2f995e54d). Draft PR only — nothing
merged, deployed, scheduled, or promoted.

## What was ported (deliberately, not by merging stale history)

### Institutional decision board (UI) — from `feat/holdings-levels-fundamentals` @ f8381023
- `components/rotation/ActionableSectorDecisionBoard.tsx` (the live board) +
  `InstitutionalRotationBrief.tsx` (thin re-export).
- Wired on `DefenseHub.tsx` and `SectorsHub.tsx`; `FinvizSectorPanel.tsx` re-tokenized
  (raw hex removed → design-token compliant).
- Sector→industry→ETF→stock workflow with ELIGIBLE NOW / RESEARCH WATCH / AVOID-REDUCE /
  NO DECISION exposure; visible coverage counts + timestamps; critique-only model wording.
- Consumes only endpoints already live on main (`sectors/monitor`, `defense/posture`,
  `defense/industries`, `defense/recommendations`, `watch/provenance`, `watch/directives`).
- The global `defenseSectorsResponsive.css` from the source branch was intentionally NOT
  ported: it restyles app-wide layout classes (nav-rail, app-body) outside Lane C scope.
  The board is fully functional on inline styles.

### Corrected data-quality producers — from `agent/defense-data-quality-v1` (PR #168)
- `scripts/defense_data_quality.py` — the corrected contract:
  `exact_session_breadth(sessions=20, min_members=8)` (breadth from N *distinct dates* per
  symbol, last-write-wins dedup), `stock_quality_gate` (roic/fcf/net_debt-ebitda/
  interest_coverage/crowding/book_overlap, fail-closed, advisory-only), `quarantine_stale_rows`,
  `field_ledger` (evidence/provider/as-of), `fund_lookthrough_quality` (unmapped weight),
  `label_market_internals` (covered-sample ≠ exchange-wide breadth), `target_gap`
  (active-tilt cap), `directive_review`.
- `scripts/defense_shadow_replay.py` — historical legacy-vs-exact20 replay (read-only).
- Additively appended the four holdings-lane helpers
  (`realized_vol_corr`, `allocation_decision`, `peer_medians`, `stock_quality_assessment`)
  so the v10 launcher imports coherently against this single reconciled module.

### Additive + DISABLED producers — from `feat/holdings-levels-fundamentals`
- `scripts/sector_momentum_engine_v4.py` — exact-20-session, uncapped deterministic covered
  membership (`base._breadth = breadth_v4`). NOT scheduled.
- `scripts/defense_recommendations_v10.py` — account-specific rotate-in launcher
  (`base.rotate_in = rotate_in_v10`). NOT scheduled.
- `scripts/defense_account_exposure.py` — pure account effective exposure + per-account
  sizing/dollar bands + explicit unmapped weight (never redistributed).
- `config/defense_account_exposure.json`, `config/defense_breadth_policy.json`,
  `config/industry_sector_map.json` — new configs (no live producer reads them until switch).
- The live default `sector_momentum_engine.py` and the already-live per-account
  `defense_recommendations.py` are UNCHANGED (no regression).

### api_v2 (additive, fail-open) — from `agent/defense-data-quality-v1`
Applied by hand (main is 94 commits ahead of that branch's base — a whole-file checkout
would have regressed api_v2). Two additive blocks:
- `_market_movers`: scope-truth labels + `internals_scope` (top-movers sample, not
  exchange-wide breadth).
- `_sectors_monitor`: `data_quality` ledger + per-row `stale`/`source_age_days`/
  `stale_sla_days`/`quarantine_reason`/`recommendation_eligible`.
Both wrapped in try/except; every pre-existing key untouched.

### Board fixtures — from `agent/defense-sectors-institutional-polish` (PR #166)
`e2e/fixtures/{defense_posture,defense_industries,defense_recommendations,sectors_monitor}.json`
+ `sanitize_fixtures.py`. The PR #166 render-gate SPEC was NOT ported: its assertions target
that PR's self-contained brief wording, not the live ActionableSectorDecisionBoard, and it
requires a dev server + Playwright to run. It needs re-authoring against the live board.

## Live-payload vs new-producer field comparison (loopback 127.0.0.1:7777)

| Endpoint | Live today | New producers WOULD add |
|---|---|---|
| `/api/v2/sectors/monitor` | payload keys `legend, sectors, spy_change_pct`; row has `rs_n, constituent_count, momentum, rs_20d_pct`… **no** `data_quality`/`stale` | top-level `data_quality` ledger; per-row `stale`, `source_age_days`, `stale_sla_days`, `quarantine_reason`, `recommendation_eligible` |
| `/api/v2/defense/posture` | momentum row has `breadth_pct, breadth_n, book_pct, state, as_of` (% above 20-day MA) | exact-20-distinct-session `breadth_pct`/`coverage_n`/`membership_n`/`duplicate_dates_removed` + quality state (via v4) |
| `/api/v2/defense/recommendations` | already has `account_equities, accounts`; SHADOW; `get_into` empty | per-card `account_sizing`, `dollars_by_account`, `allocation_policy`, `account_exposure`, `risk_context`, `quality_gate` (via v10) |
| `/api/v2/market movers` | `new_high`/`new_low` unlabeled | scope-labeled sample + `internals_scope` |

## Validation
- Backend: 54 ported tests pass (`test_defense_data_quality`, `test_defense_quality_integration`,
  `test_defense_account_exposure`, `test_defense_recommendations_v10`, `test_sector_momentum_engine_v4`).
- All ported scripts `py_compile` clean; `defense_data_quality` + `defense_recommendations_v10`
  import cleanly.
- Frontend: `npm run build` → design-guard PASS (256 files), chip-scope PASS, `tsc` clean,
  `vite build` succeeded.

## Deferred / operator-authorization required
- Repointing the host scheduled job from `sector_momentum_engine.py` to
  `sector_momentum_engine_v4.py` (external cron/timer — packet does not touch it).
- Applying `scripts/defense_breadth_switch_packet.sh --apply` (regen + smoke).
- Enabling `defense_recommendations_v10.py` in the live recs job.
- Deploying the api_v2 additive annotations (changes live payload shape once served).
- Merging / marking the PR ready.
