# OCO Brackets + ATM ↔ Proposals Unification — Design

**Status:** Design (approved scope, not yet implemented)
**Date:** 2026-06-29
**Author:** Claude (with John Whiting)
**Related:** `ATM_PROPOSAL_CONTROLS_2026_06_04.md`, `BROKER_PROPOSALS_UI.md`, `CURRENT_EXECUTION_STATE.md`, `ENGINEERING_HARD_RULES.md`, `project_schwab_token_race_recurrence` (memory), `project_stage2c_protective_stops` (memory)

---

## 1. Motivation

The AGNC take-profit incident (2026-06-29) exposed a structural gap:

- Protection take-profit proposals (`ADD_FIXED_TAKE_PROFIT`) are only generated for **already-stopped** positions, whose shares are fully `held_for_orders`. A standalone Alpaca sell-limit for those shares 403s (`insufficient qty available`), and because the failure left the proposal `status='PROPOSED'`, the ATM pass re-submitted it every run.
- The code only ever did a **standalone** `POST /v2/orders` sell-limit. **OCO was anticipated but never built** — the proposal's own `expected_api` field literally reads `"POST /v2/orders (sell limit, paper) — OCO if supported"`.
- A stop and a take-profit on the same shares can only coexist as a **One-Cancels-Other (OCO)** order. Without OCO, "protect the downside AND cap the upside" is structurally impossible.

The interim fix (PR #27) made the take-profit **advisory** so it stops looping. This design replaces "advisory" with **real OCO execution**, and unifies the entry-proposal and ATM-management lifecycles around it.

---

## 2. Approved scope (decisions 2026-06-29)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Paper/Alpaca ATM + 2FA | **Real accounts only need 2FA.** Paper keeps auto-applying (fast test account) — but now via native Alpaca OCO brackets. |
| 2 | ATM execution mechanism (real) | A **ticket that executes the same ATM trade via the Schwab API as a 2FA-gated OCO**. |
| 3 | OCO targets per broker | **Alpaca native OCO** + **Schwab API OCO (2FA)** + **Fidelity manual OCO ticket** (no trading API). |
| 4 | Entries ↔ ATM | **Auto-attach an OCO bracket (stop + take-profit) at fill**, ATM-governed. Entry and exit become one managed unit. |

**Non-negotiable invariants (unchanged):**
- The protective **stop is never absent** — every transition keeps a live stop; risk can only decrease.
- **2FA is untouched** as the live-execution gate for real accounts (`brokers/execution_guard.require(intent, "submit")`).
- Paper auto-apply stays paper-only (`PROTECTION_ATM_AUTO_APPLY_PAPER`); no live order ever bypasses the proposal record.

---

## 3. Target lifecycle (unified)

```
ENTRY PROPOSAL ──(approve/route)──► FILL ──► AUTO-ATTACH OCO BRACKET (stop + take-profit)
      │                                              │
      │ paper: auto-route                            │ paper:  Alpaca order_class=oco/bracket (auto)
      │ real:  2FA ticket (Schwab API)               │ real:   Schwab API OCO ticket → 2FA
      ▼                                              ▼
                       ┌──────────── ATM MANAGEMENT (same OCO group) ───────────┐
                       │ stop-up (breakeven / profit-lock / trailing)           │
                       │ take-profit add/raise                                  │
                       │ exit                                                   │
                       │   paper: REPLACE the OCO legs (auto-apply)             │
                       │   real:  2FA ticket re-issues/replaces the OCO (API)   │
                       └────────────────────────────────────────────────────────┘
```

The OCO **group** is the unit of management. Every ATM adjustment mutates the group's legs (REPLACE), never orphaning the stop.

---

## 4. OCO execution per broker

### 4.1 Alpaca (paper) — native OCO, auto
- **Entry bracket:** extend `alpaca_paper_adapter.submit_entry(...)` (already takes `stop_price` **and** `target_price`) to submit `order_class="bracket"` (entry + take-profit leg + stop-loss leg) instead of entry-then-standalone-stop.
- **Post-fill / retrofit:** for positions already holding a bare stop, submit `order_class="oco"` (take-profit + stop) — which requires **replacing** the standalone stop in the same call so shares are never double-committed (the exact `held_for_orders` 403 we hit). Implement in `alpaca_stop_manager.py` as `convert_to_oco(symbol, stop_price, take_profit_price)`.
- **ATM adjustments:** stop-up / trailing become a **PATCH/replace of the OCO stop leg**; take-profit raise = replace the limit leg. No leg is ever cancelled without its replacement in the same atomic step.
- **Auto-apply:** unchanged policy — paper applies directly (no 2FA), gated by `PROTECTION_ATM_AUTO_APPLY_PAPER`.

### 4.2 Schwab (real) — API OCO, 2FA-gated ticket
- Schwab Trader API supports complex orders: `orderStrategyType: "OCO"` with two `childOrderStrategies` (a SELL LIMIT take-profit + a SELL STOP). This is a **new `order_spec` shape** for the existing `schwab_transport.place_order(account_key, order_spec, intent, kind)` — no new transport, it reuses the full guard stack (readiness → evidence revalidation → **2FA `require(intent,"submit")`** → idempotency fence → POST → read-back).
- Add `kind="oco_bracket"` to tag the pilot family (distinct from `canary` / `protective_stop` caps).
- **The "ticket setup" (decision 2):** an ATM action on a Schwab position builds the **same ATM trade** as an OCO `order_spec`, surfaces it in the unified queue as a **2FA proposal**, and on approval places it via the Schwab API. Replacing an existing OCO uses Schwab `REPLACE` semantics so the stop is never absent across the swap.
- **Fractional-share guard:** Schwab rejects fractional STOP legs (see `project_fee_and_fractional_stops`). The OCO builder must whole-share the legs or fall back to the synthetic-stop monitor path; never emit a fractional OCO leg.

### 4.3 Fidelity (real, no API) — manual OCO ticket
- No trading API. Generate a **manual OCO ticket draft** (symbol, qty, stop, limit, TIF) for the operator to place, mirroring the existing manual-ticket pattern. Tracked as `MANUAL_PENDING` in the proposal record; operator marks "Executed manually" (no auto-submit).

---

## 5. Entry auto-bracket at fill (decision 4)

- **Paper:** preferred path is the native bracket at submit (§4.1). For entries that filled without a bracket, the fill reconciler (`alpaca_paper_reconciler.py`, where `broker_status='filled'` is set) triggers `convert_to_oco(...)` using the entry proposal's `stop_price` / `target_price`.
- **Real (Schwab):** the entry execution path, on confirmed fill (read-back), enqueues an **OCO bracket ticket** (§4.2) — 2FA-gated. Until the operator approves it, the position is protected by the **standalone protective stop** that Stage 2c already places (stop never absent); the OCO ticket only *adds* the take-profit leg and consolidates them.
- **Source of stop/target:** the resolved YAML strategy exit policy (already the system of record for exits), not generic R:R geometry — consistent with current `generate_paper_protection_adjustment_proposals` inputs.

---

## 6. Data model

`paper_trades` (existing): `stop_order_id`, `take_profit_order_id`, `protection_status` — reused. Add:
- `oco_group_id text` — broker OCO/strategy id linking the stop + take-profit legs.
- `bracket_state text` — `NONE | BRACKET_PENDING | OCO_ACTIVE | OCO_REPLACING | MANUAL_PENDING`.

`paper_protection_adjustment_proposals` (existing): add
- `order_class text default 'simple'` — `simple | bracket | oco`.
- `oco_take_profit numeric`, `oco_stop numeric` — the two legs of the proposed group.
- reuse `status`: `PROPOSED → APPLIED | NOT_APPLICABLE | MANUAL_PENDING`.

No DB rename of existing `paper_*` tables (operator-facing taxonomy already calls this the **VALIDATION** lane; keep legacy aliases — see `project_scalp_lifecycle_hardening`).

---

## 7. Unifying ATM ↔ proposals (governance)

- **Proposals → ATM:** entry proposals already carry account routing + policy caps. At fill they emit an ATM bracket record (§5), so every position enters ATM management automatically. One control plane (`broker_accounts` / `broker_policies` / `automation_mode`) governs entry routing *and* the bracket/management actions.
- **ATM → proposals:** every real-account ATM action is **rendered as a proposal row** in the unified queue with its OCO order_class and 2FA requirement — i.e. ATM management is *visible and gated the same way entries are*. Paper ATM actions still auto-apply but (recommended) write a **shadow proposal row** so the queue shows what auto-applied (audit parity).

---

## 8. Phasing

| Phase | Deliverable | Risk |
|-------|-------------|------|
| **P1** | Alpaca native OCO: `convert_to_oco` + bracket `submit_entry`; retrofit AGNC + the stopped paper positions; ATM stop-up replaces OCO stop leg. | Low (paper only) |
| **P2** | Entry auto-bracket at fill (paper), incl. reconciler retrofit hook. | Low |
| **P3** | Schwab API OCO `order_spec` builder + `kind="oco_bracket"` + 2FA ticket in the unified queue; fractional-share guard. | **Med-High** (new live Schwab order surface — harden behind Stage-2 caps + canary before lifting) |
| **P4** | Fidelity manual OCO ticket draft. | Low |
| **P5** | Governance unification + shadow proposal rows for paper auto-apply (audit parity). | Low |

P1–P2 deliver the real take-profit on paper. P3 is the only phase that opens a new **live** broker order type — it must go through the same canary/proof discipline as Stage 2b/2c (small qty, caps, read-back, ARM-to-fire) before broad use.

---

## 9. Safety & edge cases

- **Stop never absent:** every OCO transition is a REPLACE (or add-leg), never cancel-then-place. If an OCO replace fails, the prior protective order remains; alert, do not leave naked.
- **Partial fills:** size the OCO to filled qty only; never reserve more than `qty_available`.
- **Idempotency:** reuse `brokers/order_lifecycle.idempotency_key` so a retried bracket never doubles the order (Schwab does not dedupe).
- **2FA latency on stop-ups (open recommendation):** decision 2 routes real-account ATM actions through 2FA. Risk-*reducing* stop-ups (breakeven/profit-lock — strictly risk-down) are time-sensitive; consider a fast-lane that still records a proposal but does not block the protective move. **Flagged for confirmation before P3.**
- **Schwab OCO API verification:** confirm `orderStrategyType:"OCO"` round-trips through `schwab-py` `place_order` against a sandbox/canary before P3 lift.

---

## 10. Testing

- Unit: OCO `order_spec` builder (Alpaca + Schwab shapes); fractional guard; size-to-available.
- Integration (paper): bracket entry fills → both legs live; take-profit hit cancels stop and vice-versa; stop-up replaces only the stop leg.
- Canary (Schwab): one whole-share OCO via the 2FA ticket, read-back verified, before any cap lift.
- Backout: feature-flag each phase (`OCO_BRACKETS_PAPER`, `OCO_BRACKETS_SCHWAB`); flipping off reverts to the current standalone-stop + advisory-take-profit behavior (PR #27).
