# CIO Platform Comprehensive Audit — Phase 2: Remediation Plan

**Date:** 2026-08-27
**Companion findings doc:** [`CIO_PLATFORM_AUDIT_2026-08-27.md`](CIO_PLATFORM_AUDIT_2026-08-27.md)
**Scope note:** Execution posture (CIO Desk `READ_ONLY_ADVISORY`) is unchanged by this plan. Every remediation below closes a *data/decision-authority* or *data-integrity* gap, not an execution-authority change.

**Correction (2026-08-27, same day):** C4 was originally scoped as "extend `cio_lineage.py`" — corrected below. `scripts/lib/canonical_store_registry.py` (the real `CanonicalStoreRegistry@v1`) already exists on `origin/main`, wired into 11 consumers; it's simply missing from the live hub checkout. The fix is now folded into M1 (state reconciliation), not separate registry-building work. C4 moves from P1 to P2 accordingly.

---

## Priority Order

**P0 (data-integrity, fix independent of everything else, no dependencies):** C2, C3, C5
**P1 (CIO-authority wiring, the core ask of this audit):** C1, H1, H4
**P2 (retirement/consistency, lower urgency, real but not financial-risk):** H2, H3, H5, M1–M9, M10 (was C4)
**P3 (cleanup, do opportunistically):** L1–L7

---

## P0 — Data Integrity (fix first, independent of CIO-authority work)

### Fix C2 — Wire `position_truth.py`'s enforcement gate into the live decision path
**Problem:** `is_recommendation_admissible()`/`to_block()` exist and are tested but are never called from `shadow_decision_service.py` or `packet_invalidation.py` — only the passive `ownership_from_holdings()` is used.
**Fix:** In `shadow_decision_service.py:765` and `packet_invalidation.py:236`, replace the passive `ownership_from_holdings().to_dict()` call with a call through `is_recommendation_admissible()` before any recommendation is finalized; on a contradiction, surface `to_block()`'s directive text into the packet instead of silently proceeding.
**Validation:** re-run `tests/test_stage_a_shadow_service.py::test_beta_false_position_is_caught` and confirm it now fails if the wiring is reverted (i.e., add an integration-level test that exercises the real caller path, not just the module in isolation) — the current test only proves the module works standalone, not that production calls it.
**Risk:** low — this is closing a gap, not changing existing behavior for the (presumably common) case where positions are correctly held.

### Fix C3 — Add outlier/bounds guards to price ingestion, scrub known-bad rows
**Problem:** `price_db_sync.py`/`backfill_ticker_prices.py` only check `price > 0`; 59 fresh 10x+ single-day outliers found in the last 30 days plus the original unscrubbed NVDA corrupt rows.
**Fix:**
1. Add a bounds/outlier check at ingestion (e.g. reject or flag a single-day move beyond a configurable multiple of recent ATR/volatility, per the existing `Dynamic Stop Policy` vol-tier pattern already used elsewhere in this codebase — reuse, don't reinvent).
2. Backfill-scrub the known-corrupt rows (NVDA 2026-05-05/06 and the 59 identified outliers) — mark them invalid rather than silently deleting, so downstream consumers can distinguish "no data" from "bad data."
3. Any consumer reading `ticker_prices` (Watch, Hermes, proposal/rebalance calcs) should skip flagged rows by default.
**Validation:** re-run the direct outlier query from Brief 7 post-fix and confirm zero new unflagged 10x+ moves accumulate over a subsequent 2-week observation window.
**Risk:** medium — a bounds check can have false positives on legitimate large moves (earnings gaps, splits); tune thresholds conservatively and log-not-drop initially before hardening to reject.

### Fix C5 — Wire `portfolio_level_qa.py` critical violations to an actual alert
**Problem:** severity is tagged in code but nothing dispatches a notification; a confirmed `[OVER_HARD_CAP]` critical breach went unalerted for multiple days, and a hard crash (`FileNotFoundError`) killed a run silently.
**Fix:** reuse the existing `portfolio_alerts.py` Telegram-dispatch pattern (already used by `portfolio_rebalancer.py` for the $200k-drift alert) — call it from `portfolio_level_qa.py` whenever a violation is tagged `critical`, and wrap the script's entry point so an unhandled exception also triggers an alert rather than a silent log entry.
**Validation:** intentionally trigger a synthetic hard-cap breach in a test/staging run and confirm a Telegram message is received; confirm a forced exception also alerts.
**Risk:** low.

---

## P1 — CIO Authority Wiring (the core ask)

### Fix C1 — Route the real rebalance path through a CIO decision, or explicitly document that it doesn't (operator decision required)
**Problem:** `portfolio_rebalancer.py` runs independently of CIO Desk; the intended chain (`cio_decision_engine.py`) has been disabled since 2026-08-08.
**This needs an operator decision, not just a code fix** — two legitimate paths:
- **(a) Wire it:** `portfolio_orchestrator.py`'s 7:15 cron step calls `cio_committee_synthesis.py` (or a lighter CIO check) before `portfolio_alerts.py` fires, so the daily drift alert carries CIO Desk context/veto rather than being purely mechanical. Re-enable the `cio_decision_engine.py` cron entry only after confirming why it was disabled 2026-08-08 (check the commit/PR that disabled it before re-enabling — it may have been disabled for a reason that still applies).
- **(b) Document the boundary:** if daily mechanical drift-alerting is intentionally kept separate from CIO Desk (e.g., to avoid LLM latency/cost on a time-sensitive alert), update `docs/cio/AUTHORITY.md` and `docs/cio/ARCHITECTURE.md` to say so explicitly, so "CIO Desk is the source of truth" is scoped honestly (e.g. "CIO Desk is authoritative for situations/plans/thesis; daily mechanical rebalance-drift alerting is a separate, intentionally CIO-independent safety mechanism").
**Recommendation:** (b) as an immediate documentation fix, with (a) as a scoped follow-up only if the operator actually wants daily rebalance alerts CIO-gated — don't silently re-enable a disabled cron entry without understanding why it was disabled.
**Validation:** whichever path is chosen, `InvestmentDecision@v1` consumption should show up in a repo-wide grep beyond its own module — that's the checkable signal this gap is closed.

### Fix H1 — Extend rebalance verification to cover the daily drift path
**Problem:** `rebalance_verifier.py` only checks the unrelated monthly `gemma3_monthly` tier; daily drift-based suggestions that actually reach the operator are never verified.
**Fix:** either (a) add a lightweight daily verification pass for `portfolio_rebalancer.py` output (reuse the SSDI/IRMAA/tax-compliance checks `rebalance_verifier.py` already has, applied to the daily suggestions before the Telegram alert fires — verify-before-notify, not verify-after), or (b) if Sunday-only verification is intentional for cost/complexity reasons, make that limitation visible to the operator in the Telegram alert itself ("unverified drift suggestion — full compliance check runs Sunday").
**Recommendation:** (a) — verify-before-notify is a small change (call the existing verifier logic inline before `portfolio_alerts.py` fires) and closes a real compliance blind spot on the path an operator is most likely to act on.
**Validation:** confirm a synthetic SSDI/IRMAA-violating rebalance suggestion gets flagged before reaching Telegram, not after.

### Fix H4 — Route all price-consuming code through one canonical quote layer
**Problem:** `watch_canonical_quote.py` only resolves Watch-list display quotes; 34+ files bypass it and query `market_quote_provider`/`alpaca_read_client` directly.
**Fix:** this is a larger refactor — don't attempt it as one PR. Phase it: (1) extend the canonical layer's scope/name to make clear it's Watch-only today (rename or docstring), (2) pick the highest-risk direct-import sites first (anything touching order sizing or proposal generation — `broker_proposal_autocal.py`, `schwab_broker_trade_monitor.py`) and route those through a canonical resolver, (3) leave lower-risk display-only consumers (dashboards) for a later pass. Remove or archive `multi_source_quote_refresh.py` if confirmed genuinely orphaned (re-check before deleting — an earlier finding already confirmed zero production imports).
**Validation:** for each migrated call site, confirm quote values match pre-migration behavior in a side-by-side comparison before cutover.
**Risk:** medium — quote-source behavior changes are exactly the kind of thing that can silently shift position sizing; migrate incrementally with comparison logging.

---

## P2 — Retirement & Consistency

| Fix | Action | Validation |
|---|---|---|
| **H2** — Retire Command Center v2 | Remove `/v2/` route-serving code from `portfolio_server.py` (or gate it behind an explicit, off-by-default flag if a rollback path is still wanted); update `docs/CHEAT_SHEET.md` and `docs/MASTER_SYSTEM_DOCUMENTATION.md` §14 to describe v3 as current; remove the `--frontend` v2 build path from `run_tradeai_regression.sh` or repoint it to v3. | `curl` the `/v2/` route post-fix and confirm a deliberate 404/410, not an accidental one; grep docs for remaining present-tense v2 references. |
| **H3** — Fix or rename the truth-gate test | Either rewrite `cio-truth-gates.spec.ts` to actually assert live-vs-mock data behavior (per its name), or rename it to reflect what it actually tests (DATA_CONFLICT UI rendering) and write the real truth-gate test separately. Wire whichever exists into a CI workflow — remove the `test.skip(!enabled)` default-off gate once it's confirmed safe to run in CI. | Confirm the spec (or its replacement) runs and fails on a deliberately-introduced live-vs-mock regression in a test branch. |
| **H5** — Migrate trade journal off manual CSV | Replace the CSV-drop input path in `portfolio_trade_journal.py` with a direct read from `schwab_pilot_orders` (already populated automatically on every real order) — this both fixes staleness and brings the journal in line with the "no CSV, API-fed" standard. | Confirm `trade_journal.json`'s most recent entry date tracks within a day of the latest real order, going forward. |
| **M1** — Resolve state divergence | Decide and document a deliberate policy: either merge the hub's `feat/two-way-watchlist-curation` work to `main` and re-check out `main` on the hub, or explicitly document why the hub intentionally lags (canary practice) with a monitored max-lag threshold. Fix `ACTIVE_RELEASE` to actually reflect what `CURRENT` points to — this should be written by whatever script updates `CURRENT`, not left to drift. | `git diff --stat HEAD origin/main` shows near-zero drift, or a documented policy explains an intentional gap; `ACTIVE_RELEASE` content matches `CURRENT`'s target on every deploy. |
| **M2 (corrected)** — Clean up the vestigial user-level `tradeai-continuous` unit | No real gap: a system-level unit (`/etc/systemd/system/tradeai-continuous.service`) is confirmed live, running `continuous_runner.py` since 04:00 ET today. The user-level unit (`~/.config/systemd/user/tradeai-continuous.service`) is a dormant duplicate, harmless (shared singleton lock) but a trap for future investigators who check `systemctl --user` alone, as the original audit pass did. Add a one-line comment to the user-level unit file pointing at the system-level one, or remove it. | `systemctl --user status tradeai-continuous.service` output (or its absence) no longer reads as "the continuous runner might not be running." |
| **M3** — Schedule or retire `autonomous_rebalance_planner.py` | If still wanted, add a cron entry with the same human-review gate already built in; if superseded by the daily rebalancer, mark it explicitly deprecated in its docstring. | — |
| **M4** — Fix or remove the dead Finviz enrichment cron slots | Either wire `finviz_enrichment.py`'s `__main__` to accept real symbol input (matching what `watchlist_enrichment_sweep.py` already does correctly), or remove the two no-op cron entries to stop the misleading `Price: $?` log noise. | Confirm the cron slots either produce real prices or are removed. |
| **M5** — Add a staleness marker to CIO snapshot's cache-first read | Propagate a `stale: true` / age field when `_get_snapshot()` takes the cached-file fast path, so downstream renderers can flag it. | Force a stale-cache scenario and confirm the marker appears in the synthesis output. |
| **M6** — Reconcile canonical-repo vs. deployed-release content drift | Ensure the release-build pipeline always builds from a clean `origin/main` checkout (not the hub's working tree) so canonical repo and deployed release never diverge in content; fix `tradeai-portfolio-server.service` to actually manage the live process instead of leaving it to a bare watchdog script outside systemd, or document why that's intentional. | `diff` canonical repo copy vs. deployed release copy shows zero unexpected divergence after a fresh deploy. |
| **M7** — Correct "Alex is the CHAIR" documentation | Update `cio_committee_synthesis.py`'s docstring and `docs/cio/ARCHITECTURE.md` to accurately describe the override direction (committee veto offices can override chair, not vice versa). | Docs match code on re-read. |
| **M8** — Reconcile `holdings.json`'s duplicate P&L fields | Determine which of `gain_loss`/`unrealized_pl` is canonical, deprecate the other or document the difference (e.g. pre-fee vs. post-fee) if both are intentionally different metrics. | All consumers reference the same field consistently, or the difference is documented. |
| **M9** — Refresh master docs | Fold the 08-20 through 08-22 closeout docs' "what shipped" claims into `docs/MASTER_SYSTEM_DOCUMENTATION.md` and `docs/cio/ARCHITECTURE.md`; add the missing entries to `docs/DOCUMENTATION_INDEX.md`. Given this pattern (closeout docs not folding back into master docs) is recurring, consider adding it as a checklist item to whatever process produces closeout docs. | Master docs mention the shipped features found in this audit's Brief 10. |
| **M10** (was C4) — Get the hub current with `origin/main` so `canonical_store_registry.py` actually runs | This is the same action as fixing M1: `scripts/lib/canonical_store_registry.py` (the real `CanonicalStoreRegistry@v1`, wired into 11 consumers including `api_v3_cio.py`) exists on `origin/main` but is missing from the hub's live checkout. No new registry-building work is needed — bringing the hub current closes this. Once current, document `cio_lineage.py`'s narrower Hermes-only scope relative to the broader registry in its own docstring, so the two aren't confused. | `test -f <hub>/scripts/lib/canonical_store_registry.py` succeeds; the 92-file "source of truth" grep sweep (M9) shows a declining count as more domains resolve through the registry over time. |

---

## P3 — Cleanup (opportunistic)

- **L1** — Delete the 7 confirmed-dead `.bak`/`.backup` files in `scripts/`.
- **L3** — Rewrite the `snaptrade_*.py` "read-only" claim to specify "read-only w.r.t. broker APIs; writes local ingestion tables" for precision.
- **L4** — Remove the one "Schwab/IBKR" docstring mention in `broker_adapter.py` if the zero-vendor-literal claim needs to be literally true, or amend the claim's wording to "zero vendor literals in dispatch logic."
- **L5** — Rename or docstring-flag `schwab_order_adapter.py` as a dormant stub to avoid future confusion with the real live path (`schwab_transport.py`).
- **L6** — No action required (non-material rounding, different codepath, already reconciles within noise).
- **L7** — Add a short note to `docs/architecture/cio/` mapping the audited diagram's 5 type names to their actual code equivalents, so a future reader doesn't repeat this reconciliation from scratch.

---

## Definition of Done

1. **C1 resolved (done)** — the CIO/rebalance boundary is explicitly and honestly documented. **M10 (was C4) resolved** when the hub is current with `origin/main` and `canonical_store_registry.py` is actually running in production, not just merged.
2. **All P0 items (C2, C3, C5) closed** — position-truth gate live-wired, price outlier guard in place with known-bad rows scrubbed, critical QA violations alert a human.
3. **All Critical/High findings from Phase 1 have a closed remediation item** — fixed, or explicitly accepted-risk with operator sign-off (appropriate for a solo operator, not a team consensus process).
4. **Safety guards remain independently testable** — every guard this audit verified as working (GATE B, kill switches, approval_service chain, HERMES_DISABLED, agent_runtime boundary, report_maturity_control_board read-only) should gain or keep a regression test that would catch a future silent regression of the kind this audit specifically looked for (cf. the stash-conflict-marker incident precedent).
5. **Documentation hierarchy clarified** — master docs reflect shipped work; the CIO-authority boundary (what CIO Desk is and isn't authoritative for) is stated in one place operators and future audits can trust without re-deriving it.
6. **No regressions from this remediation itself** — every fix above should be validated per its own validation step before being considered closed; this plan intentionally sequences P0 (safe, additive data-integrity fixes) before P1 (architectural wiring decisions that need operator judgment) before P2/P3 (lower-urgency cleanup) so the highest-consequence gaps close first without waiting on the harder architectural questions.

---

## Open Items Requiring Operator Decision (not just engineering)

- **C1 — RESOLVED (2026-08-27):** operator decision was to document the mechanical-independence honestly rather than wire it. Shipped: `docs/cio/AUTHORITY.md` + `ARCHITECTURE.md` updated (PR #526).
- **C4 — SUPERSEDED (2026-08-27):** the original question ("how far should `cio_lineage.py` be extended") no longer applies — the real registry already exists on `origin/main`. The remaining open item folds into M1 below.
- **M1**: is the hub intentionally lagging `origin/main` for canary purposes, or should it be kept in sync going forward? This is now higher-stakes than originally scoped — the hub is not just stale, it's missing a wired, actively-consumed module (`canonical_store_registry.py`) that 11 other files depend on. Merging/rebasing the live hub branch affects the actively-running production system and should not happen without explicit operator sign-off on timing and rollback plan.

These are flagged separately because they're judgment calls about intended system design, not bugs with a single correct fix — surfaced here so they don't get silently resolved one way by whoever picks up the remediation work.
