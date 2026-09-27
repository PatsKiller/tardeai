# Options order gate proof — broker layer (2026-09-27)

**Served release tested:** `8f2a178d59a0b300f4b946a79c8c7c75b95601a1` (CURRENT `8f2a178d5-main-exact-phase2-20260927-171004`).
`scripts/brokers/**` in this branch is byte-identical to the served release; the proofs import those modules.
Built under a per-task `execution-engineering` grant (AGENTS 1.3.0 rule 2): tests only, no broker source changed,
no order, no 2FA request, no arm/disarm.

**Reviewer requirement (item 5):** prove that stale quotes, missing thesis or CIO approval, failed liquidity,
insufficient buying power, archived proposals and changed legs prevent order creation even when the broker route
is open and the user has 2FA.

## Where each gate lives

| Layer | Runs at | Code |
|---|---|---|
| Desk | proposal generation → approval queue → `/api/v2/options/preflight` (desk gate) | `options_desk_enterprise.evaluate_hard_risk_blocks`, `check_preflight_approval`, `preflight_desk_gate` (PR: options order gates) |
| Broker | `/api/v2/options/preflight` → `execution_guard.authorize`; `/api/v2/options/confirm` → `approval_service.confirm`; `schwab_transport.place_order` → `execution_readiness` → `evidence_approval.revalidate_before_submit` → `execution_guard.require` | `scripts/brokers/**`, `scripts/schwab_transport.py:101` |

## Results (`tests/test_options_broker_gates_20260927.py`, 16 passed, 2 strict xfail)

| # | Condition | Gate (file:function) | Proof | Result |
|---|---|---|---|---|
| a | confirm without verified 2FA never reaches submit | `approval_service.confirm` (wrong code / web click without typed ticker refused); api_v2 confirm handler submits only after `fully_approved`; `execution_guard.authorize` DENIED without `is_fully_approved`; `execution_readiness` submit mode hard-blocks `operator_2fa_confirmed` | `test_a_*` (4) | **PASS** |
| b | kill switch blocks | `execution_readiness._kill_switches_clear` → hard block; `revalidate_before_submit` → `kill_switch_after_approval`; no connection → synthetic global switch; raising connection → `kill_switch_inspect_failed` / `kill_switch_check_failed` | `test_b_*` (3) | **PASS** — note: `authorize()` alone does not consult kill switches; they are enforced by `place_order`'s readiness + revalidation steps, which run before `require()` (AST-verified order) |
| c | state change between preflight and confirm blocks | `place_order` re-runs readiness, evidence revalidation and `require` at submit; `revalidate_before_submit` → `readiness_changed_to_block`, `readiness_hash_changed`, `readiness_bundle_unavailable_fail_closed`, single-use, expiry | `test_c_*` (2) | **PASS** |
| d | changed legs rejected | the mechanism exists (`order_spec_hash` pin → `order_spec_hash_changed`) **but the options preflight never creates an evidence-bound approval** (`create_order_evidence_approval` is called only by the protective-stop and router paths), so `place_order` fails closed with `no_evidence_bound_approval` for every options order; and `options_order_pilot.spec_from_intent` rebuilds the order from the **proposals cache**, not the 2FA'd intent | `test_d_*` (4; one strict xfail) | **FAIL-CLOSED today, GAP in design**: the options route cannot submit at all, and if an evidence approval were added without fixing `spec_from_intent`, a leg or premium changed in the cache after preflight would be the one hashed at submit |
| e | stale / unknown quote fails closed | `execution_readiness` `fresh_market_data`: unknown (no age, no source) → blocked; age > 120 s → blocked; `bs_estimate` source → blocked; chain > 300 s → `option_chain_fresh` blocked. `options_order_pilot.build_intent` carries **no** `quote_age_seconds`/`data_source`, so every options submit is blocked as "quote freshness unknown" | `test_e_*` (4; one strict xfail) | **PASS (fail-closed) with GAP**: a missing quote age passes as fresh whenever a `data_source` is named |
| f | LLM cannot unlock | `execution_readiness._llm_cannot_unlock` | `test_f_*` | **PASS** |

Existing broker suites on the served release (`tests/test_execution_readiness.py`, `test_kill_switches.py`,
`test_schwab_protective_stop_2fa.py`, `test_execution_state.py`): **30 passed** at `8f2a178d5`.

## Gaps and the fix for each (not implemented here — outside "tests only")

1. **`spec_from_intent` must build from the approved intent.** Drop the proposals-cache overlay (or use it only
   for display) so the order legs, contracts and limit price are exactly those the operator 2FA'd. Then have the
   options preflight call `evidence_approval.create_order_evidence_approval(intent, order_spec, readiness_snapshot)`
   so `place_order`'s `order_spec_hash` pin applies to options too. Until then the route is fail-closed and unusable.
2. **`fresh_market_data`:** treat `quote_age_seconds is None` as unknown regardless of `data_source`.
3. **`build_intent`:** carry `quote_age_seconds`, `chain_age_seconds`, `data_source` (from the proposal's
   `quotes_as_of` / chain `fetched_at`, PR options fill truth) so readiness can judge freshness instead of failing
   on "unknown".
4. **Buying power** is not evaluated anywhere on the broker path for options; the desk gate fails closed on its
   absence (PR options order gates). A broker balance read at preflight is the fix.
5. **Share count / cost basis reconciliation** (reviewer item 3 tail) is not performed at approval; `held_qty`
   reaches the intent from `_protective_holding_truth` at preflight only.

## What this does not prove
- Live behaviour of the Schwab client, Telegram delivery, or the DB write fence: all faked.
- Anything on the `active_trader` path (out of the grant's scope).
