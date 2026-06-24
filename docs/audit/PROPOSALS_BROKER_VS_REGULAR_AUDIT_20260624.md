# Proposals Audit — Broker vs Regular (Frontend + Backend)

**Date:** 2026-06-24 · **Scope:** `paper_trade_proposals` lifecycle, broker-promotion layer, and both Command Center v3 UIs · **Type:** read-only audit, gaps + enhancements.

## 0. Central architecture fact

There is **no separate broker-proposal entity**. A "broker proposal" is a `paper_trade_proposals` row whose `intended_broker`/`target_account` resolves to `schwab*`/`fidelity*` with `status IN ('PENDING','APPROVED_FOR_PAPER_TEST')`. The broker queue is a **filtered view over the same table** that backs regular (Alpaca paper) proposals, with a **parallel, heavier gate stack** bolted on via routing fields. Promotion does an **in-place UPDATE** of the row (account/levels/shares) — the paper plan is overwritten; lineage survives only as a `sizing_basis` JSON patch.

Implication: the two systems share one schema and one set of status values but diverge sharply in (a) gate depth, (b) execution path, and (c) UI affordances. Most gaps are **asymmetries** — something one side has that the other lacks.

---

## 1. Backend comparison

| Dimension | Regular (paper) | Broker (promote) |
|---|---|---|
| Generation | `auto_proposal_generator` + 8 generators → `paper_trade_proposals` | Promote an existing paper row (`prepare-promote` → `promote-from-paper`) or `manual-submit` |
| Sizing | `account_policy.compute_sizing` (percent-of-equity) | `broker_promote_sizing` re-sizes on **destination cash** (live) + strategy live caps |
| Gates | risk_gate (~22 codes) + approval-time gates + market revalidation | agent reviews (Maria/Risk/Steph) + local LLM + intel diligence + **trade-plan gate** + cloud consensus + sizing + 3-lock routing arm + per-order 2FA |
| Cloud oversight | optional (`run-ai-review`) | Grok+ChatGPT auto-queued (`BROKER_AUTO_CLOUD_OVERSIGHT=1`), advisory (`REQUIRE_CLOUD=0`) |
| Execution | approve = instant paper submit (Alpaca) | route STEP 1 (build OTOCO + request 2FA) → STEP 2 (confirm 2FA → live submit); Fidelity = record-only |
| Modify | **Telegram-only** (`trade_modify`), no REST | `/route` edit + `/prepare-manual` + `evaluate-promote` previews |
| Audit | `queue_decision_audit` | `queue_decision_audit` + `sizing_basis` patch (no immutable snapshot) |

### Backend gaps (severity-tagged)

**P0 — correctness / safety**
- **No immutable broker-proposal record.** `promote_proposal_to_broker` (`paper_trade_logger.py:1180`) UPDATEs the shared row in place; "paper plan vs promoted plan" history depends entirely on a jsonb patch. → audit/repro risk.
- **Cloud oversight is effectively advisory.** `REQUIRE_CLOUD=0` + disagreement only BLOCKs when `lanes_ok≥1` (`broker_promote_oversight.py:683`). If both lanes error, a real disagree is silently downgraded.
- **Fail-open gates + swallowed exceptions.** `risk_gate` returns APPROVED on exception outside `FAIL_CLOSED_CONTEXTS` (`risk_gate.py:444`); agent-review fetch errors yield "no pending agents" → agent gate can silently PASS (`broker_promote_oversight._q`). Litmus wraps sizing/oversight in bare `except: pass`.
- **Non-atomic stops** for market & extended-hours orders (`alpaca_paper_adapter.py:612`); EH fills via monitor get no stop at submit; bracket child stop id not captured (`PROTECTED_UNRECORDED`).
- **News auto-close absent** from the execution path (only an external monitor) — adverse-news exit not guaranteed for proposal trades.

**P1 — consistency / hygiene**
- **R:R floor divergence:** `check_quality` `rr<1.2` (dead) vs pre-promotion/ATM `≥2.0` vs litmus `1.2` vs curator `2` — 3–4 different floors across one flow. Centralize.
- **Price-freshness has 3 definitions:** band 20m (`BROKER_PRICE_MAX_AGE_MIN`), market validator 15m, and `assess_price_freshness` trusts any `refreshed_at` as age 0 (`broker_thesis_validity.py:35`).
- **Hardcoded values** (violate the no-hardcode rule): `REQUIRED_AGENTS=("maria","risk_agent","steph")`, `BLOCK/WARN_VOTES`, overnight-expiry `strategy_id NOT IN ('momentum_scalp','gap_and_go')`.
- **Status casing drift:** lowercase `expired` rows vs canonical `EXPIRED`; `cleanup_stale_proposals` can flip an already-approved+traded row to REJECTED while its `paper_trades` stays open.
- **Two live-submit paths** (canary `schwab_pilot_orders`+`canary_gate` vs queue-route `broker_order_intents`+`execution_guard`+`approval_service`) — can't tell from data which path an order took.
- **Namespace inconsistency:** diligence under `/paper-proposals/broker-diligence` while the rest is `/broker-proposals/*`.
- **`operator_route` waiver mismatch:** litmus/preview uses `operator_route=True` (caps→warnings) but `/promote-from-paper` never sets it → preview and actual promote disagree.
- **Trade-plan gate kill-switch** (`BROKER_REQUIRE_TRADE_PLAN=0`) disables the entire anti-gambling protection with no audit trail in the row.

**Regular-side specific**
- **No REST modify/requeue** — only Telegram inline buttons can resize a paper proposal; `apply_size` sets absolute shares with **no risk-gate re-check** and `apply_risk` doesn't update target/RR (stale R:R after stop move).
- Reject is terminal; no un-reject/requeue.

---

## 2. Frontend comparison

| Capability | Regular UI (`ProposalsRich`) | Broker UI (`BrokerProposals`) |
|---|---|---|
| Evidence depth | **Rich** — 9 evidence tiles, pipeline chevron, full trust audit, support/reject cases | Moderate — intel panel, thesis band, cloud lanes |
| Edit trade (size/price) | ❌ **dead code** (`isModified=false`, no setters) | ✅ "✎ Edit trade" + route-size/policy-cap controls |
| Live quote / thesis band | partial (drift, current price) | ✅ full drift-gap band + live R:R + room up/down |
| Cloud verdicts | external-intel badges (Grok/ChatGPT tooltip) | ✅ per-lane verdict/assessment/concerns + consensus |
| 2FA / routing | ❌ (auto-paper only) | ✅ dual-channel (web ticker / telegram code) |
| Account selection | ❌ | ✅ Schwab auto/manual vs Fidelity picker + activity |
| Refresh pattern | `window.location.reload()` + `alert()` | React state, polled detail, cloud-running poll |
| Bulk ops | only "Dismiss all Entry-Missed" (bulk reject) | cloud-batch (page/filtered); no bulk route |
| Drill-down | inline expand (not the app `DetailDrawer`) | modal-based |

### Frontend gaps (severity-tagged)

**P0 — operator capability / data integrity**
- **Regular UI has no sizing/price edit** despite the approve endpoint accepting `{shares,entry,stop,target}` — the override is dead code (`ProposalsRich.tsx:195-210`). Biggest regular-vs-broker gap. Operator must approve as-proposed or reject.
- **`window.location.reload()` on every enrichment/diligence/submit action** (`runAction`) — loses scroll/filters/open drawers; inconsistent with approve (which uses `refetch`).
- **Native `alert()` for errors AND success** (incl. the market-revalidation summary) — blocking, crude.

**P1 — UX / surface parity**
- **`EnsembleValidationCard` (the app-standard Grok+ChatGPT+Gemma scored card) is wired everywhere EXCEPT both proposal surfaces** — broker has bespoke lane rendering, regular has badges only. No standardized 0–10 scoring on either.
- **`/broker-proposals/audit`** (pipeline-dysfunction + sweep preview) exists backend, **never called** by any UI.
- **No requeue/un-reject, no multi-select bulk approve** on either surface.
- **`pipeline-run-health` never refetches** after mount (regular) — banner goes stale until full reload.
- **Per-card N×2 fetches** (subject-intel + L2 book) against the single-threaded API on long lists — perf risk (see `reference_dashboard_performance`).
- **Duplicated oversight rendering** broker modal vs card (different poll intervals — modal 12s local-agents, card 15s cloud-only) — two paths to keep in sync.
- **`PositionSizingRiskBar` hidden exactly when operator-route override is active** — loses the risk visual precisely when sizing exceeds policy.

**P2 — polish / a11y**
- **Zero accessibility** across both surfaces — no `aria-*`/`role`, div/span `onClick` without keyboard handlers, unlabeled inputs (2FA, filters, account picker).
- **No responsive/mobile** — fixed grids, dense headers overflow on narrow screens.
- Banner truncates to 3 blockers with no "show more"; proposals not deep-linkable; no last-poll/next-refresh indicator.

---

## 3. Top enhancements (prioritized)

**P0 (correctness + the operator's #1 missing control)**
1. **Regular UI: real edit-trade** — wire shares/entry/stop/target inputs → `isModified`, send overrides to approve; re-run risk-gate server-side on modified sizing (also fixes the `apply_size` no-recheck backend gap). Reuse the broker `onEdit` pattern.
2. **Immutable broker-promotion snapshot** — write a child `broker_proposal_snapshot` (or append-only `proposal_promotions`) row instead of/in addition to the in-place UPDATE, so paper-plan vs promoted-plan is auditable.
3. **Centralize R:R floor + price-freshness** into one config-driven helper; remove the dead 1.2 check; make `assess_price_freshness` honor the actual timestamp.
4. **Tighten cloud-oversight fail-closed**: when 0 lanes return, treat as BLOCK-or-explicit-WARN (not silent pass); surface the lane-failure state in the UI.

**P1 (parity + reliability)**
5. **Replace `window.location.reload()`/`alert()`** in `ProposalsRich` with `refetch()` + inline toasts; refetch `pipeline-run-health` on Refresh.
6. **Standardize on `EnsembleValidationCard`** for both proposal surfaces (one scored Grok+ChatGPT+Gemma card) — removes the bespoke broker lane code and gives regular proposals real scoring.
7. **De-hardcode** required-agents / expiry-strategy / vote sets → config/DB; fix status casing + the cleanup sweep that rejects already-traded rows.
8. **Surface `/broker-proposals/audit`** as a small queue-health panel; add requeue/un-reject.
9. **Unify the two live-submit paths** (or clearly tag which path an order took via `intent_id`/`correlation_id` on the row).

**P2 (polish)**
10. Accessibility pass (aria/labels/keyboard) + responsive grids on both surfaces.
11. Bulk multi-select approve/route; deep-linkable proposals via the app `DetailDrawer`; "show more" on blockers; last-poll indicator.

---

## Appendix — key files
Backend: `auto_proposal_generator.py`, `proposal_lifecycle.py`, `account_policy.py`, `paper_trade_logger.py`, `atm_auto_approver.py`, `proposal_paper_submitter.py`, `alpaca_paper_adapter.py`, `risk_gate.py`, `broker_promote_sizing.py`, `broker_promote_oversight.py`, `broker_thesis_validity.py`, `broker_trade_plan_gate.py`, `queue_router.py`, `trade_modify.py`, `api_v2.py`.
Frontend: `pages/TradingHub.tsx`, `components/ProposalsRich.tsx`, `components/BrokerProposals.tsx`, `BrokerProposalCard.tsx`, `BrokerPromoteModal.tsx`, `BrokerIntelPanel.tsx`, `BrokerRouteConfirmModal.tsx`, `EnsembleValidationCard.tsx`, `lib/proposalRouting.ts`.
