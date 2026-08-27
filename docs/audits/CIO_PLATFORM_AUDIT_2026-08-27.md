# CIO Platform Comprehensive Audit — Phase 1: Findings

**Date:** 2026-08-27
**Scope:** Validate whether the CIO Agent/Desk functions as the authoritative data/decision source of truth for the Trade AI platform, and whether Command Center, Portfolio Management, Balances/Positions, Trade Execution, Data Pipelines, Reporting, and Agent Orchestration are actually wired to it and to real, non-mocked data — as documented.
**Method:** 11 independent evidence-gathering investigations (state reconciliation + 9 domain briefs + a repo/docs consistency sweep), each required to cite doc claim vs. code vs. live evidence (cron/systemd state, log output, grep results for binary-checkable claims). No finding rests on a doc claim or file's existence alone. Full companion remediation plan: [`CIO_PLATFORM_REMEDIATION_2026-08-27.md`](CIO_PLATFORM_REMEDIATION_2026-08-27.md).

**Framing, per operator direction:** "CIO Desk as authoritative source of truth" is scoped to **data/decision authority** — the canonical context, definitions, and decisions other systems should read from. Execution posture (`READ_ONLY_ADVISORY`, no broker order/stop/risk-limit authority — [`docs/cio/AUTHORITY.md`](../cio/AUTHORITY.md)) is explicitly out of scope and unchanged by this audit.

**Correction (2026-08-27, same day, before merge):** Finding C4 as originally investigated was accurate for the codebase it examined (the live hub checkout) but has since been corrected below — `scripts/lib/canonical_store_registry.py` (literal `SCHEMA = "CanonicalStoreRegistry@v1"`) already exists on `origin/main`, wired into 11 real consumers. See the corrected C4 entry for the full explanation; this is a state-reconciliation finding (M1), not a missing-feature finding.

---

## Headline Answer

**The CIO Desk is not, in practice, the authoritative decision source for this platform.** Its committee/`InvestmentDecision@v1` architecture is real, tested, well-designed code — but nothing outside the CIO Desk's own lane (situations, plans, Telegram, `/v3/cio`) is gated on consulting it. The platform's actual daily rebalance-recommendation generator, `portfolio_rebalancer.py`, runs on an independent cron with zero CIO involvement (Finding 1). This is the single most important finding in this audit and the starting point for Phase 2.

Separately, this audit surfaced **data-integrity gaps that are independent of the CIO-authority question and more urgent** — a live, unguarded corrupt-price-bar problem (Finding 3) and a hallucination-prevention gate that exists in code but was never wired into a live decision path (Finding 2) are Critical severity regardless of how CIO authority gets resolved.

---

## Severity Rubric

| Severity | Criteria |
|---|---|
| **Critical** | Data-integrity risk that could drive a real financial decision on wrong/stale/hallucinated data; a claimed safety guard that doesn't actually hold in code; two systems silently disagreeing on ground truth. |
| **High** | A component believed authoritative/live is actually stale, superseded, or bypassable with real operational consequence; state candidates materially disagree; numbers diverge from source data. |
| **Medium** | Functional but mis-documented behavior; dead-but-harmless code; scheduling gaps with no confirmed incident; tests that exist but aren't wired into CI. |
| **Low** | Pure documentation drift, naming inconsistency, cosmetic staleness. |

Severity is assigned by **worst plausible consequence if unaddressed**, not likelihood.

---

## Critical Findings

### C1 — CIO Desk is bypassed by the platform's actual daily rebalance path
`portfolio_rebalancer.py` (the real daily rebalance-recommendation generator, cron `15 7 * * 1-5` via `portfolio_orchestrator.py`) has **zero CIO references** anywhere in it. It emits advisory Telegram alerts directly (`portfolio_alerts.py`) when drift exceeds $200k, entirely independent of `cio_decision_engine.py` / `cio_committee_synthesis.py`. The weaker fallback chain (`cio_decision_engine.py → cio_decisions table → autonomous_rebalance_planner.py`) has been **disabled since 2026-08-08** (`# DISABLED 2026-08-08` in crontab), and `autonomous_rebalance_planner.py` itself has no cron/systemd entry at all — never scheduled in production. `InvestmentDecision@v1` (the CIO Desk's core output contract) is defined and tested but consumed nowhere outside its own module.
**Evidence:** `scripts/portfolio_rebalancer.py` (no `cio_*` imports), crontab `# DISABLED 2026-08-08` on the `cio_decision_engine.py` entry, `grep` of `InvestmentDecision` usage limited to `cio_committee_synthesis.py`/`cio_decision_pipeline.py`/tests.
**Consequence if unaddressed:** the platform's real recommendation surface (the one an operator sees in Telegram) never reflects CIO Desk analysis — the "authoritative source of truth" goal is architecturally false today, not just under-documented.

### C2 — Position-hallucination enforcement gate exists but is never called
`scripts/position_truth.py` was built (and passes a regression test, `tests/test_stage_a_shadow_service.py::test_beta_false_position_is_caught`) specifically to prevent the 2026-07-20 incident where an agent recommended trimming a position that didn't exist ([`docs/_findings/BETA_WATCHLIST_TRUST_INCIDENT_2026-07-20.md`](../_findings/BETA_WATCHLIST_TRUST_INCIDENT_2026-07-20.md)). The actual enforcement function, `is_recommendation_admissible()` / `to_block()`, is called **only from within `position_truth.py` itself and its own tests.** Live callers (`shadow_decision_service.py:765`, `packet_invalidation.py:236`) invoke only the passive `ownership_from_holdings()` and pass a bare JSON dict into `blind_review.build_facts_packet()` — the emphatic block text and the hard admissibility gate never execute in the live decision path.
**Evidence:** repo-wide grep confirms zero production callers of `is_recommendation_admissible`/`to_block` outside `position_truth.py` and tests.
**Consequence if unaddressed:** the exact incident this module was built to prevent can recur today — the fix looks shipped (file exists, is well-tested, is imported for other purposes) but the enforcement it exists for is dead code. This matches this codebase's known failure pattern (cf. the stash-conflict-marker incident that silently killed ATR/support calculations for weeks).

### C3 — Corrupt/outlier price bars are live and unguarded
The 07-24-era corrupt-bar class of incident (e.g. NVDA showing $0.05) is **not fixed** — it is ongoing. The original corrupt NVDA rows (`0.0500` on 2026-05-06, `0.1800` on 2026-05-05, `source=finviz`) are still present in `ticker_prices`, never scrubbed. A direct query found **59 additional 10x+ single-day jump/drop outliers in the last 30 days** (e.g. BYND 0.42→13.45 in a day; SRNE oscillating 0.0007↔0.29 repeatedly; RCON 0.04→6.00). `backfill_ticker_prices.py` and `price_db_sync.py` have no outlier/bounds-checking logic — only a bare `price > 0` guard.
**Evidence:** `price_db_sync.py:147,162,243,261` (only `>0` check); direct `ticker_prices` query surfaced the unscrubbed original rows plus 59 fresh outliers.
**Consequence if unaddressed:** implausible prices reach Watch, Hermes research, and rebalance/proposal calculations with no guard — a single bad tick can distort position sizing, drift %, or a trim/entry recommendation.

### C4 — CORRECTED: the canonical registry exists on `origin/main`; the gap is hub deployment lag, not a missing feature
**Original finding (as investigated against the live hub checkout, `feat/two-way-watchlist-curation`):** no unified `CanonicalStoreRegistry@v1` existed; `scripts/lib/cio_lineage.py` (added 2026-08-26) implemented a genuine but narrow analog scoped to the Hermes research sub-flow only.

**Correction:** that finding was accurate *for the hub*, but incomplete — `scripts/lib/canonical_store_registry.py` already exists on `origin/main` (last touched by commit `fd61ac46`, 2026-08-26 21:51, the same evening as `cio_lineage.py`) and is **missing from the hub's live checkout entirely** (confirmed: `test -f` on the hub path fails). It is not a stub:

- Literal `SCHEMA = "CanonicalStoreRegistry@v1"`, an explicit `OWNERSHIP_CLASSES` taxonomy (`AUTHORITATIVE` / `APPEND_ONLY_EVIDENCE` / `CANONICAL_PERSISTENT_STATE` / `DERIVED_CURRENT_PROJECTION` / `CACHE` / `OPS_LOG` / `RETIRED`), and 24 registered logical stores (positions, decisions, quotes, notifications, lineage, checkpoints, learning, research, identity, maturity, etc.), each declaring its writer, readers, and whether it's rebuildable.
- `resolve_store()`/`load_json_store()` give consumers a store-ID lookup with alias fallback for stale filenames — exactly the "one contract for persisted intelligence stores" the diagram's `CanonicalStoreRegistry@v1` implies.
- **Genuinely wired**, not aspirational: 11 real consumer files import it, including `scripts/api_v3_cio.py` (the main CIO API), `scripts/control_plane_api.py`, `scripts/aegis_evening_packet.py`, plus dedicated integrity tooling (`filename_drift_audit.py`, `data_integrity_audit.py`, `production_root_map.py`) that specifically checks for the kind of store-fragmentation this registry exists to prevent.
- It also **contains a literal, wired `CIOOperatorProduct@v1`** (`scripts/lib/cio_operator_product.py`, `SCHEMA = "CIOOperatorProduct@v1"`, imports `canonical_store_registry` directly) — correcting L7 below, which classified that diagram type as "renamed-equivalent, diffuse." It is not diffuse; it is a real, registry-backed module with that exact name, present on `origin/main`, absent from the hub.

**Evidence:** `scripts/lib/canonical_store_registry.py` (full file read); `git log -1 -- scripts/lib/canonical_store_registry.py` → `fd61ac46530e93fde5740a98482e1ae3209adec5 2026-08-26 21:51:03`; `test -f <hub>/scripts/lib/canonical_store_registry.py` → missing; `grep -rl "canonical_store_registry\|resolve_store(" scripts/ apps/` → 11 files.
**Revised consequence:** this is not a "never built" gap — it is an **M1 state-reconciliation consequence**. The registry that would resolve the 92-file "source of truth" fragmentation (see M9) already exists and is merged to `origin/main`, but the live hub (what cron/systemd actually run) doesn't have it yet because the hub's checkout has diverged onto an unmerged feature branch. Fixing M1 (getting the hub current with `origin/main`) is very likely the actual fix for the operator-facing part of this finding, not new registry-building work. Severity revised from Critical to **Medium** — the code risk is closed; what remains is a deployment-currency risk already covered by M1.

### C5 — A confirmed hard-cap portfolio breach went unalerted for multiple days
`scripts/portfolio_level_qa.py` runs daily (07:40) and internally tags violations by severity, including `critical` for hard-cap breaches. A live breach — `core_compounders: 86.1–86.2%` against a `40–60%` target, explicitly tagged `[OVER_HARD_CAP]` at `critical` severity in code — was logged to `logs/portfolio_qa.log` and a DB event row across **multiple consecutive daily runs** with **no Telegram/alert call anywhere in the script** (`grep` confirms zero). A separate hard crash (`FileNotFoundError: .../.env`) also killed a run entirely with no alert.
**Evidence:** `logs/portfolio_qa.log:570-584` (crash); `portfolio_level_qa.py:80-81` (severity tagging logic present, no dispatch to any notifier).
**Consequence if unaddressed:** the one script explicitly designed to catch allocation-limit breaches has no path to a human — a `critical`-tagged violation is operationally identical to a routine one until someone happens to read the log file.

---

## High Findings

### H1 — Daily rebalance suggestions are never verified; only an unrelated monthly tier is
`rebalance_verifier.py` (cron: Sundays 10:30) verifies **only** rows tagged `analysis_tier='gemma3_monthly'` in `rebalance_analysis_results` — a separate system fed monthly by `rebalance_deep_analyzer.py`. It has no connection to `portfolio_rebalancer.py`'s daily drift-based suggestions, which reach the operator via Telegram (>$200k drift) and the dashboard Rebalancing tab. These daily suggestions are **never checked for SSDI/IRMAA/tax compliance by anything** — not delayed-but-eventually-verified, structurally excluded.
**Evidence:** `rebalance_verifier.py` SQL filter on `analysis_tier='gemma3_monthly'`; zero references to `portfolio_rebalancer` output in the verifier.

### H2 — Command Center v2 is not fully retired
The deployed `portfolio_server.py` (the actual running release) still contains live `/v2/` route-serving code and lists `/v2/` in `AUTH_EXEMPT_PREFIXES` — it 404s today only because `apps/command-center-v2/dist/index.html` happens to be missing in this checkout, not because the route was removed. `docs/CHEAT_SHEET.md:214` gives the literal operator command `cd apps/command-center-v2 && npm run build` with no v3 equivalent documented anywhere in that file. `docs/MASTER_SYSTEM_DOCUMENTATION.md` §14 (dated 2026-06-22) describes v2 as "the" frontend in present tense and has **zero** mentions of v3 anywhere in the document. `scripts/run_tradeai_regression.sh` still builds v2, not v3, under its `--frontend` flag (opt-in, default off).
**Evidence:** `portfolio_server.py` route table; `docs/CHEAT_SHEET.md:214`; `docs/MASTER_SYSTEM_DOCUMENTATION.md` §14.

### H3 — The "truth gate" test doesn't test truth, and doesn't run
`apps/command-center-v3/e2e/cio-truth-gates.spec.ts` mocks its own API responses via `page.route()` and asserts UI rendering logic for a `DATA_CONFLICT` state — it does not verify the UI refuses stale/mocked data or requires live responses, despite its name. It is gated `test.skip(!enabled)` where `enabled` requires an env var never set anywhere, and none of the repo's 14 CI workflow files reference it. It has never executed automatically.
**Evidence:** `apps/command-center-v3/e2e/cio-truth-gates.spec.ts` (61 lines); grep of `.github/workflows/*.yml` — zero references.

### H4 — The "canonical quote" layer doesn't cover the trading/proposal path
The only canonical-quote module found, `scripts/lib/watch_canonical_quote.py`, resolves a data-source boundary for the Watch list display only — it does not touch `market_quote_provider.py`, `multi_source_quote_refresh.py` (itself orphaned, imported nowhere), or `alpaca_read_client.py`. 34+ files (`options_engine.py`, `paper_trade_logger.py`, `broker_proposal_autocal.py`, `api_v2.py`, `schwab_broker_trade_monitor.py`, etc.) import `market_quote_provider` or `alpaca_read_client` directly, bypassing any canonicalization.
**Evidence:** grep of 34+ direct-import sites; `watch_canonical_quote.py` scope confirmed limited to Watch-list DB tables.
**Consequence:** the Watch UI and the trading/proposal engines can legitimately see different prices for the same symbol at the same instant.

### H5 — Trade journal is stale, CSV-fed, and contradicts the documented "no CSV, API-fed only" standard
`portfolio_trade_journal.build_trade_journal()` reads from manually-dropped Schwab/Fidelity CSVs in `data/portfolios/input/` (newest CSV dated 2026-06-05). Its output, regenerated daily, shows a most-recent `closed_trades` close date of **2026-04-30** — roughly four months stale versus today. By contrast, the live `schwab_pilot_orders` DB table (populated automatically by every real order submission) has entries through 2026-07-31. The journal does not reconcile with real order flow.
**Evidence:** `data/portfolios/input/` newest CSV mtime 2026-06-05; `trade_journal.json` closed_trades max date 2026-04-30 vs. `schwab_pilot_orders` max date 2026-07-31.
**Consequence:** contradicts the standing architecture principle that all pipelines are API-fed with no CSV dependency; any report or reconciliation drawing on the trade journal is working from stale data.

---

## Medium Findings

### M1 — State reconciliation: hub is on a feature branch, ~250K lines diverged from origin/main
The canonical hub (`trade-ai-v12-rebuild/trade-ai-v12-rebuild`, shared object store for ~223 worktrees, what cron/systemd actually execute) is checked out on `feat/two-way-watchlist-curation` (`d0cbb842`), not `main`, diverging from `origin/main` (`2ccee09a`) by **1,648 files / 245,729 insertions / 5,193 deletions**. `/home/johnclaw/tradeai-main-deploy` is a separate stale pinned checkout, `f7de6472`, older still. The `ACTIVE_RELEASE` marker inside the portfolio-server release directory names `890e3aef feature/advisory-desk-v1 20260811-094957` — 15 days and a full branch-generation behind what `CURRENT` actually points to (`2ccee09a-main-exact-phase2-20260826-230915`, which does match `origin/main` exactly).
**Evidence:** `git diff --stat` output; `ACTIVE_RELEASE` file content vs. `CURRENT` symlink target.
**Consequence:** any future audit or debugging session that trusts the hub's own checkout, the stale pinned deploy dir, or the `ACTIVE_RELEASE` marker as "current" will be working from the wrong code.

### M2 — `tradeai-continuous.service`/`.timer` disabled and inactive at the systemd level
Both are `disabled`/`inactive` — the continuous runner is not currently systemd-managed. Whether it is covered by cron or another external invocation was not confirmed in this pass.
**Evidence:** `systemctl is-enabled`/`is-active` output.

### M3 — `autonomous_rebalance_planner.py` is "autonomous" in name only
No cron or systemd entry exists for it anywhere; its only caller besides itself is a validation test script. It writes human-review-gated DRAFT plans when manually invoked, but is never scheduled in production.

### M4 — Two scheduled Finviz "enrichment" cron slots are no-ops
`finviz_enrichment.py`'s `__main__` has no real CLI wiring — invoked bare by its two cron entries (07:00, 13:00 weekdays), it silently falls back to a hardcoded 4-symbol demo list and prints `Price: $?` (None) every run, every day, for months. Real enrichment does flow correctly via a separate job (`watchlist_enrichment_sweep.py`, `*/30 9-15` + 16:15), so this is not a full pipeline outage — but two explicitly-scheduled cron slots are dead weight that could be mistaken for coverage.

### M5 — CIO Desk's snapshot read can silently serve stale cached data
`cio_desk_synthesis.py::_get_snapshot()` has a fast path that returns a cached `cio_snapshot.json` file directly if shape-populated, bypassing the `max_age_s=60` freshness check enforced by the live-collect fallback. No staleness marker propagates downstream when this path is taken.

### M6 — `portfolio_server.py` version/content drift between canonical repo and deployed release
The canonical hub's copy declares `v2.0 (April 10, 2026)` and differs in actual content (missing provenance/SHA-pin code present in the deployed copy) from the release snapshot actually running (`2ccee09a-main-exact-phase2-20260826-230915`). The `tradeai-portfolio-server.service` systemd unit that's supposed to manage this is `disabled`/`inactive`; the real process is a bare orphan kept alive by `portfolio_server_watchdog.sh`, outside systemd's management.

### M7 — "Alex is the CHAIR" claim is overstated relative to the code
`cio_committee_synthesis.py::reconcile_committee()` forcibly downgrades the chair's execution intent to HOLD on `BLOCKED_DEFENSE` or committee opposition — the committee (specifically `guardian`/`risk_agent` veto offices) can override the chair; the reverse is not true. The docstring's "sole producer... chair gates it" framing overstates actual chair authority. Not a safety problem (the override direction is conservative), but a documentation-accuracy issue.

### M8 — Internal ground-truth inconsistency inside `holdings.json` itself
At least one position (CSWC) carries two disagreeing P&L fields in the same file: `gain_loss` ($4.27) vs. `unrealized_pl` ($3.14). The audited report used the former consistently, but the underlying source file is not internally self-consistent.

### M9 — Master docs lag ~2 weeks of shipped CIO/research work
`docs/MASTER_SYSTEM_DOCUMENTATION.md` (doc-version stamp 2026-06-22, last git-modified 2026-08-13) and `docs/cio/ARCHITECTURE.md` (last modified 2026-08-12) contain zero mentions of concrete "what shipped" claims from closeout docs dated 2026-08-20 through 2026-08-22 (DecisionPayload capture, Symbol Intelligence dossier, five research tiers, Telegram P0 fixes). `docs/DOCUMENTATION_INDEX.md` (last modified 2026-08-16) is missing entries for the two most recent closeout docs.

---

## Low Findings (confirmed, no action urgency)

- **L1** — Seven `.bak`/`.backup` files sitting live in `scripts/` (`finviz_validator.py.backup-*` ×2, `llm_router.py.bak_v36`, `intel_query.py.bak_v36`, `agent_event_router.py.bak_v36`, `agent_watchlist_engine.py.bak_v36`, `api_v2.py.bak_journal_maturity`, `overnight_batch.py.bak_journal_maturity`) — confirmed dead, no Python import, no shell/crontab reference. Safe to delete.
- **L2** — No hard contradictions found across 75 live docs using the phrase "source of truth" — claims are correctly domain-scoped (paper-book vs. real-book positions, stops, decisions, config) though scoping is rarely stated inline, which invites misreading.
- **L3** — `snaptrade_*.py` never writes to any broker API (confirmed no outbound mutation calls), but does write to local DB tables (`trade_transactions`, `system_controls`) — the blanket "read-only" label is accurate re: broker risk but imprecise as stated.
- **L4** — `"Zero vendor string literals"` claim on `broker_adapter.py` is technically false by grep (one docstring mention of "Schwab/IBKR") but true in functional/dispatch logic.
- **L5** — `scripts/brokers/schwab_order_adapter.py` is a dormant stub (every mutating method unconditionally raises) — not the live order path; its name is misleading relative to `schwab_transport.py`, which is the real one.
- **L6** — `aegis_morning_brief_2026-08-27.json` shows a small ($2,087 / 0.16%) rounding gap vs. ground-truth total portfolio value — non-material, likely LLM-summary rounding, different codepath than the audited `reporting_engine.py` output (which reconciled exactly).
- **L7** — Diagram type reconciliation, corrected: `CIOCouncilSynthesis@v1`→`InvestmentDecision@v1` (naming-drift-only) and `SpecialistArtifact@v2`→informal dict convention (naming-drift-only) stand as originally found. `OutcomeCheckpoint@v1` is a literal, freshly-built match (`cio_lineage.py`). `CIOOperatorProduct@v1` was originally classified "renamed-equivalent, diffuse" against `cio_full_cycle.py`'s pipeline output — **corrected**: `scripts/lib/cio_operator_product.py` on `origin/main` has that exact literal schema name, registry-backed, not diffuse (see corrected C4/M10). `CanonicalStoreRegistry@v1` was originally classified "never implemented" — **corrected**: exists on `origin/main` as `scripts/lib/canonical_store_registry.py`, wired into 11 consumers (see M10). Net: 2 of 5 diagram types are exact literal matches on `origin/main` today (`OutcomeCheckpoint@v1`, `CIOOperatorProduct@v1`), one more (`CanonicalStoreRegistry@v1`) matches by concept and near-exact by name; only `CIOCouncilSynthesis@v1` and `SpecialistArtifact@v2` remain genuine naming drift. No file in the repo formally scoped this diagram end-to-end — but its vocabulary converges with real, merged, wired implementation work far more than the original investigation (run against the lagging hub checkout) found.

---

## Verified Clean (no finding — stated explicitly so these don't get "fixed" into a regression)

- **GATE B** (`schwab_position_sync.py`) genuinely fail-closes: `sane_payload()` and the catastrophic-drop guard both `return` before any write on violation, not log-and-proceed.
- **The real Schwab order-placement path is properly gated end-to-end**: `intent_submit_router.submit_fully_approved()` (2FA/`approval_service` gate) → pilot → `schwab_transport.place_order()`, which itself runs `execution_readiness` (including kill switches), `evidence_approval.revalidate_before_submit`, and `execution_guard.require()` before any POST. No bypass path found across all mutating callers.
- **`HERMES_DISABLED` kill switch** is checked as the unconditional first statement of `hermes_coordinator.py::main()` — cannot be skipped by an error path.
- **`report_maturity_control_board.py`**'s "Read-only. No mutations. No trading." claim holds — zero write/mutate operations found.
- **`agent_runtime`'s "shadow/lab only, no authority" self-declaration holds** at every confirmed live import site (`portfolio_server.py`, `cio_wake_dispatcher.py` touch only the read/definitions side; the write/dispatch machinery is isolated behind separate boot modules, a distinct DB role, and an operator-file kill switch).
- **`hermes_coordinator.py` and `scripts/agent_runtime/` are genuinely unrelated parallel systems** — zero cross-references found either direction; no accidental authority leakage between them.
- **`reporting_engine.py`'s prospectus output reconciles exactly** against `holdings.json` ground truth (price, entry price, unrealized P&L, portfolio weight all matched to the cent/bp for the sampled position).
- **No live code references `docs/_archive/`** as a config/prompt source path.
- **No superseded/duplicate reporting scripts found** — `reports_portal.py`, `generate_reports_hub.py`, `generate_weekly_docx.py` serve distinct, non-overlapping roles.

---

## Findings Index (severity-sorted)

| ID | Finding | Severity |
|---|---|---|
| C1 | CIO Desk bypassed by real daily rebalance path | Critical |
| C2 | Position-hallucination enforcement gate never called | Critical |
| C3 | Corrupt/outlier price bars live, unguarded | Critical |
| C5 | Hard-cap breach unalerted for multiple days | Critical |
| H1 | Daily rebalance suggestions never verified | High |
| H2 | Command Center v2 not fully retired | High |
| H3 | "Truth gate" test doesn't test truth, doesn't run | High |
| H4 | Canonical quote layer doesn't cover trading path | High |
| H5 | Trade journal stale, CSV-fed, contradicts standard | High |
| M1 | State reconciliation: hub off-main, stale release marker | Medium |
| M2 | tradeai-continuous service/timer disabled+inactive | Medium |
| M3 | autonomous_rebalance_planner never scheduled | Medium |
| M4 | Two Finviz enrichment cron slots are no-ops | Medium |
| M5 | CIO snapshot read bypasses freshness check | Medium |
| M6 | portfolio_server.py version/content drift | Medium |
| M7 | "Alex is CHAIR" overstated vs. code | Medium |
| M8 | holdings.json internal P&L field inconsistency | Medium |
| M9 | Master docs lag ~2 weeks of shipped work | Medium |
| M10 | (was C4) Canonical registry exists on origin/main, missing from hub — an M1 consequence, not a missing feature | Medium |
| L1–L7 | Dead code, doc precision, minor drift | Low |
