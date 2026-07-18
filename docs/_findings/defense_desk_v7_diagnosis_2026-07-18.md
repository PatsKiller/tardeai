# Defense Desk v7 — Phase 0 Diagnosis + EXEC Branch Decision (2026-07-18)

## Findings
| Question | Verdict | Evidence |
|---|---|---|
| Live equity submit beyond stops? | **EXISTS but pilot-fenced** | `schwab_transport.place_order` is REAL (Stage 2b SB-1, operator-approved 2026-06-12) — but its stack is `_pilot_preconditions` (TAXABLE-ONLY assert) → execution_guard (canary OR protective gate → standing locks → pilot caps ~5 orders → 2FA) → readiness → evidence revalidation → idempotency. `kind ∈ {canary, protective_stop, options}` families. **Defense intents mostly target the Rollover IRA — outside the fence.** |
| 2FA machinery reuse points | **brokers/approval_service + the stop-path pill** (`2fa_stop_request` kind, schwab_2fa vs fidelity_manual routing, `broker_submit: disabled_until_2fa_approval`) — api_v2 ~880–1271 |
| Equity approvals analog | **`action_queue`** — `approvals_pending()` aggregates it into the “9 APPROVALS” chip; `/api/v2/approvals/decision` decides. Defense intents get ONE new table (`defense_order_intents`, full detail) + a mirror row in action_queue → SAME approvals UI, SAME decision endpoint, no parallel system. |
| Paper executors | `alpaca_paper_options_executor.py` (options, reads options_approval_queue); equity paper legs ride the established paper_trade_proposals → ATM pipeline |
| Fill polling today | journal/transactions ingest ~12h lag (14:18 cron); `schwab_transport.get_transactions(account_key)` is a live read — intent-scoped 10-min polling is feasible inside the fence |
| Chain re-pull cost | `get_option_chain(symbol, strike_count)` — one throttled read; single-contract validation ≈ 1 call, fine at button cadence |

## THE EXEC BRANCH DECISION
**Live legs → ARMED ORDER TICKET (post-approval, post-2FA), NOT place_order.**
Rationale: place_order's fence is taxable-only + canary/protective kinds with hard caps —
widening it to IRA accounts and new order kinds IS the "final live-transmission wiring"
that the standing project boundary reserves as an operator-owned step (precedent: the
Redeploy Desk runs the same pattern — "broker execution NOT granted; fresh export at
ticket time, limits only"). So:
- **Paper legs**: full auto post-2FA via the existing Alpaca lanes (proposals pipeline /
  options executor). The loop closes itself.
- **Live legs**: intent → approvals UI → 2FA pill → **ARMED ORDER TICKET** (exact
  instrument/side/qty/limit-band/account, ToS-ready) → operator places → the 10-min
  fill poller reconciles automatically and advances ladder/pair/RT state.
- `autonomous_live_submit_allowed` remains **False**; nothing in v7 widens the pilot
  fence. When the operator later grants defense-kind live submits, the intents already
  carry everything place_order needs — the wiring is a config/fence decision, not a build.

## Execution topology (one line)
Card → **stage** (whitelist+caps+kill, refusals rendered) → `defense_order_intents`
(+ action_queue mirror) → operator **approve** (existing UI) → **2FA pill** (Telegram,
code consume) → paper: Alpaca auto / live: ARMED TICKET → **fill poller** (10-min RTH)
→ ladder/pair/RT advance + audit chain complete (`defense_execution_audit`, never deleted).
