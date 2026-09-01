# Stage 2b — Schwab Write Pilot Spec (operator-approved parameters, 2026-06-12)

Status:      ACTIVE
as_of:       2026-06-12T18:49:26-04:00
Measured at: efcc51365 / not measured

**Status: SPEC — no write code authorized until each gate below is checked off in order.**
**Supersedes nothing; builds on `stage2a-canary-protocol.md` and the committed `brokers/canary_gate.py`.**

## Operator decisions on record (2026-06-12)

| Question | Operator answer |
|---|---|
| Environment | Schwab support told operator the new app/account is a **sandbox** |
| First account | **schwab_taxable** only (IRAs excluded from the entire pilot) |
| Caps | **qty ≤ 10 shares · price < $10 · max 5 trades total** for testing |
| Confirmation | **Per-order operator confirm** before every POST |
| Architecture | All writes via `schwab_transport` only; validator guards **rewritten, not removed** |

## SB-0 — Environment identity proof (BLOCKING; do this before anything else)

Schwab's retail Trader API has no documented paper-trading environment; "Sandbox" is normally an
*app approval status*, not an isolated money-less environment. Before any order POST, prove what
the sandbox credentials actually touch — read-only:

1. With the sandbox app's token: `GET /trader/v1/accounts/accountNumbers` and `GET /accounts`
   (balances). **Read-only.**
2. Compare returned account numbers/hashes + balances against the three known real accounts
   (read via the existing production read-only transport).
3. Verdict, recorded in `docs/brokers/stage2a-reconciliation-log.md`:
   - Returns DIFFERENT account(s) with fake balances → genuine sandbox; pilot may relax to the
     operator caps (qty ≤ 10, price < $10) since fills are fake.
   - Returns the REAL taxable account → **it is not a sandbox**; every POST is a real order. The
     pilot then runs under the FULL canary protocol: committed allowlist symbols, committed
     session date, $4/$40 envelope first, operator caps only as the outer bound.
4. Either way: orders only ever target the taxable hash; IRA hashes are never passed to any write
   call (assert in code, not convention).

## Envelope reconciliation (committed gate vs operator caps)

`brokers/canary_gate.py` is hardcoded-by-commit (price ≤ $4, qty ≤ 10, notional ≤ $40, allowlist
GRAB/XRX, single committed session date, auto-expire). Operator caps (price < $10, 5 trades) are
WIDER. Rule: **the canary gate stays the inner gate; operator caps become a new outer committed
envelope.** Widening the inner gate (e.g. to $10) happens only by commit, only after SB-0 says
genuine-sandbox, and reverts by commit after the test window. Add to the committed envelope:
`MAX_PILOT_ORDERS_TOTAL = 5` — a cumulative counter persisted in the audit log; order #6 is
blocked regardless of anything else.

## SB-1 — Write surface (transport only)

- Implement `schwab_transport.place_order(account_key, payload)` and `cancel_order` ONLY. No
  replace in the pilot (cancel + new order instead — simpler recon).
- Guarded by, in order: `execution_guard.require()` → `canary_gate` envelope → pilot caps →
  `broker_accounts.api_write_enabled` (flipped true for schwab_taxable only, by migration) →
  per-order operator confirmation token.
- Idempotency: every order carries a locally-generated client correlation id persisted BEFORE the
  POST; on timeout, reconcile via `GET /orders` before any retry (Schwab does not dedupe).
- Raw `requests.post` outside the transport stays a validator failure.

## SB-2 — Per-order confirmation flow

1. Preflight (`schwab_stage2b_canary_preflight.py`, already read-only) renders the exact payload
   + quote check + envelope verdict.
2. Operator confirms via typed phrase (existing preflight convention) — the confirm token is
   single-use, order-hash-bound, expires in 10 minutes.
3. Transport POSTs; 201 Location order-id captured; immediate `GET /orders/{id}` read-back.
4. Shadow recon (`schwab_shadow_recon`) verifies Schwab's representation vs the predicted payload
   — mismatch = protocol ABORT (existing rule).
5. Telegram + audit row per order (submitted/filled/canceled), counting toward the 5-order cap.

## SB-3 — Pilot script (the 5 trades)

With ladder tickets now generated (`lib/schwabTickets.ts` / Manual ToS desk), the pilot exercises
the exact shapes the ladder needs, smallest first:

| # | Ticket | Proves |
|---|---|---|
| 1 | BUY LIMIT (marketable, tiny) DAY | entry path, 201 + Location, read-back |
| 2 | SELL LIMIT GTC (T1-style, above market) | GTC accept + resting order recon |
| 3 | CANCEL of #2 | cancel path + status read-back |
| 4 | SELL STOP GTC (protective-stop shape) | stop trigger accept |
| 5 | SELL TRAILING_STOP GTC (runner shape, VALUE offset) | trailing accept + field echo |

(#4/#5 require holding the shares from #1; if #1 doesn't fill, substitute repeat LIMIT+cancel
pairs — shape coverage over fill coverage.)

## Validator rewrite (SB-1 prerequisite, same commit as the write code)

`validate_schwab_no_writes.py` becomes `validate_schwab_write_policy.py`: instead of proving "no
write path exists," it proves "writes exist ONLY behind the stack" — transport-only write surface,
guard ordering, canary gate in front, api_write_enabled flags match policy (taxable true, IRAs
false), pilot counter enforced, confirm-token required, raw-write grep still clean elsewhere.
Target stays 18/18-style all-green, with the new assertions documented in
`execution-safety-guards.md`.

## Exit criteria

Pilot closes (success or abort) → `api_write_enabled` reverts to false by migration, inner gate
date expires (automatic), results logged in the reconciliation log + CHANGELOG, and a Stage 2c
decision (ladder automation on Schwab) is a NEW spec gated on SB-0's environment verdict.

## Open items — RESOLVED (operator, 2026-06-12 evening)

1. Keyset: **same app / same credentials** as the existing read-only integration (operator: "same
   API account was selected in API"). There is no separate sandbox keyset — the write tokens ARE
   the production tokens. Consequence: per-order confirm is non-negotiable, and the no-IRA-hash
   assert moves into the transport write path itself.
2. OAuth callback: **same redirect URI.**
3. **SB-0 EXECUTED 2026-06-12 (read-only): NOT A SANDBOX.** The app's credentials returned all
   three REAL accounts with REAL balances (taxable equity $76,105 / cash $7,901; rollover
   $572,672; roth $43,463). Operator decision on record: **continue live-tiny under the committed
   $4/$40 inner canary envelope** (price ≤ $4 · qty ≤ 10 · notional ≤ $40 · committed allowlist ·
   committed session date · long-only · LIMIT only). The operator's wider caps (price < $10) are
   VOID for live orders; the 5-trade total cap stands.

## SB-1 BUILT 2026-06-12 (session day: 2026-06-13)

- [x] `schwab_transport.place_order/cancel_order` real impl behind the full stack
      (`_pilot_preconditions` taxable-only assert + api_write_enabled → `execution_guard.require`:
      canary gate → standing locks → pilot caps → per-trade 2FA); `replace_order` stays fenced
- [x] `brokers/pilot_caps.py` — commit-only literals: taxable-only allowlist + 5-order lifetime cap
- [x] Correlation row persisted in `schwab_pilot_orders` BEFORE any POST; timeout note forbids
      blind retry (reconcile via GET first); 2FA set consumed single-use at submit
- [x] `brokers/capabilities.py` schwab mode → LIVE_ENABLED_FUTURE (reachable, fail-closed);
      `execution_guard` LIVE branch can now GRANT (submit: caps+2FA; cancel: safe direction)
- [x] Arm/disarm: `scripts/schwab_pilot_arm.py` (typed-phrase confirmed; sets db control row +
      standing approval + api_write_enabled; env flag + restart stay manual on purpose)
- [x] API: GET broker-orders/pilot/status · POST pilot/preflight (full Stage 2b preflight, saves
      draft for the existing 2FA routes) · POST pilot/execute (sole transport caller) · POST
      pilot/cancel — UI: Stage 2b Pilot Console at the top of v3 Trading → Broker Orders
- [x] `validate_schwab_write_policy.py` (25 guards incl. tamper-evidence: gate modules must match
      git HEAD) + `validate_schwab_no_writes.py` kept as passthrough shim
- [ ] MORNING-OF (2026-06-13, in order): re-screen GRAB/XRX (≤$4 + sane spread at open) → commit
      new `CANARY_SESSION_DATE = "2026-06-13"` (+ rotated allowlist if re-screen changes it) →
      `schwab_pilot_arm.py --arm --confirm "ARM SCHWAB PILOT 2026-06-13"` → add
      `BROKER_LIVE_ENABLED=true` to .env → restart server → validator 25/25 → run the 5-ticket
      pilot from the console (per-order 2FA each time) → after session: `--disarm`, remove env
      flag, validator green again

### Confirmation factors per order (operator question 2026-06-12: "robust 2-3 factor")
① Web: type the TICKER exactly in the confirm popup (anti-fat-finger, single-use, 10-min TTL)
② Telegram: one-tap Approve on the proposals chat (or type the 6-digit code back) — second device
③ Structural: committed canary envelope + committed session date + 5-order cap + typed arm phrase
   — plus one-order-at-a-time (a second intent can't even request approval while one is active)
