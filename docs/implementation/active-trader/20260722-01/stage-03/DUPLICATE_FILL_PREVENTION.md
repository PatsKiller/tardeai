# Duplicate-Fill Prevention — Stage 3

The core duplicate-exposure guarantee (v3.3 §16F.8, Law 27) as implemented and tested.

## Arithmetic (evaluator step 6)
```text
envelope_room = authorized_aggregate_quantity
              - confirmed_aggregate_filled
              - confirmed_working_quantity        (across ALL accounts)

max_new_quantity = floor( min(
    requested_quantity,
    envelope_room,
    policy.max_fallback_shares,
    policy.max_fallback_notional / price,
    session_gross_notional_remaining / price,
    policy.max_fallback_risk / per_share_risk,
    session_risk_remaining / per_share_risk ))
```
- floor (never round exposure UP); result < 1 share → NO_FALLBACK;
  envelope_room ≤ 0 → NO_FALLBACK (aggregate envelope exhausted).

## Ambiguity protections (all tested)
| Hazard | Protection |
|---|---|
| Late fill after cancel request | PENDING_CANCEL is non-final → WAIT; only CANCELLED_WITH_**CONFIRMED**_FILL_QUANTITY proceeds |
| Ambiguous cancel | same — confirmation of fill quantity is a hard precondition |
| Timeout / broker unreachable | BROKER_UNREACHABLE → BLOCKED (not WAIT — operator visibility) |
| Stale local state | STALE → BLOCKED |
| Delayed stream event | fill quantity None → BLOCKED; quantities must be confirmed values |
| Partial fill w/ unconfirmed remainder | dedicated non-final state → WAIT |
| Replay of the same rejection | evaluator idempotency key + rejection-event occurrence upsert + notification dedupe — one decision, one row, one operator event |
| Double-count across accounts | confirmed_working_quantity spans all accounts in the reconciliation |

## Worked examples (from tests)
- Source cancelled with 40 confirmed filled, authorized 200 → room 160, request 100 → 100.
- Source filled 150 of authorized 200 → room 50 → fallback capped at 50.
- Authorized 100, filled 60, working 40 → room 0 → NO_FALLBACK.
- notional cap 250 @ $10 → 25 shares; risk cap 10 @ $0.50/share → 20 shares.
