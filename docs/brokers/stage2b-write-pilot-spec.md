# Stage 2b — Schwab Write Pilot Spec (operator-approved parameters, 2026-06-12)

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

## Next: SB-1 build checklist (write surface + validator rewrite, one commit)

- [ ] `schwab_transport.place_order/cancel_order` (real impl) behind: execution_guard →
      canary_gate → 5-order cumulative cap → `api_write_enabled` → single-use confirm token
- [ ] Hard assert in the write path: account_key == 'schwab_taxable' (IRA keys raise, always)
- [ ] Correlation id persisted before POST; timeout ⇒ reconcile via GET before any retry
- [ ] Migration: `api_write_enabled=true` for schwab_taxable ONLY (reversible, operator-approved)
- [ ] `validate_schwab_no_writes.py` → `validate_schwab_write_policy.py` (all-green redefinition
      per this spec; same runner wiring so Stage 2a battery + cron keep working)
- [ ] Pilot session scheduling: commit a NEW `CANARY_SESSION_DATE` + re-screened allowlist the
      morning of the session (GRAB $3.37 / XRX $3.45 quotes are from 2026-06-12 AH — re-verify
      price ≤ $4 and spread at the open; rotate back after)
