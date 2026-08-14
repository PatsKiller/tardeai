# PHASE 9 CLOSEOUT — Telegram Alex Product Behavior + Dedupe

**UTC:** 2026-08-14  
**Branch:** `wt/cio-phase1-notify`  
**Version:** `alex_telegram_1.0.0`  
**Authority:** `READ_ONLY_ADVISORY` unchanged  

## Goal

Alex pages the operator like a CIO, not a log stream. Material decisions only,
decision-id semantic dedupe, DEFER lineage, and a dual-gated live canary that
**does not send** without explicit operator env approval.

## Product path

```
material InvestmentDecision / CIO NOW card
  → materiality test
  → semantic dedupe (decision_id + material state)
  → CIO-only transport (TELEGRAM_CIO_* only)
  → receipt (if live)

non-material (thesis bump, heartbeat, thin HOLD, fixtures)
  → internal state only — no Telegram
```

## Module

`scripts/lib/cio_alex_telegram.py`

| Capability | Behavior |
| --- | --- |
| Materiality | Requires `decision_id` + real action/signal; rejects heartbeat/thesis-default/thin hold |
| CIO-speak body | Call, dollars, weight, why, counter-thesis, what changes mind, next review, actions |
| Dedupe | `decision_id` + stance + delta + status fingerprint (6h window via existing store) |
| Unchanged cycle ×2 | Second send suppressed |
| State change | New delta/stance → new key → allowed |
| DEFER lineage | Durable `cio_defer_lineage.jsonl`; reopen preserves `decision_id` |
| Canary package | Destination identity (no secrets), body, dedupe key, disable command |
| Canary execute | Requires `AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1` **and** `CIO_TELEGRAM_CANARY_ENABLE=1` **and** `CIO_TELEGRAM_CANARY_APPROVAL=I_APPROVE_CIO_CANARY_SEND`; blocked under pytest; in-process force ignored |

## Wiring

| File | Change |
| --- | --- |
| `cio_telegram_transport.py` | Optional `dedupe_key` / `decision_id` on send |
| `cio_notification_outbox.py` | `build_dedupe_key` prefers `decision_id` + material state |
| Phase 1 transport rules | Unchanged (CIO-only, no general fallback) |

## Canary (not run live in this phase)

`prepare_canary_package()` returns the review packet.  
`execute_canary_send()` is implemented but **blocked** until the operator sets:

```bash
export AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
export CIO_TELEGRAM_CANARY_ENABLE=1
export CIO_TELEGRAM_CANARY_APPROVAL=I_APPROVE_CIO_CANARY_SEND
# then run a dedicated canary script/session — not automatic
```

Rollback / disable:

```bash
unset AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY
unset CIO_TELEGRAM_CANARY_APPROVAL
unset CIO_TELEGRAM_CANARY_ENABLE
# or: export CIO_TELEGRAM_INTERDICT=1
```

## Exit gate (this implementation)

| Gate | Status |
| --- | --- |
| REAL MESSAGES TO LIVE TELEGRAM | **0** |
| THESIS-VERSION PROACTIVE MESSAGES | **0** (default off) |
| SECOND IDENTICAL CYCLE DUPLICATE | **NO** (suppressed) |
| DEFER FOLLOW-UP LINEAGE | **PASS** |
| GENERAL TELEGRAM RECEIVES CIO TRAFFIC | **NO** |
| DEDICATED CIO CANARY | **READY** (awaiting explicit operator approval — not sent) |

## Tests

```
tests/test_cio_phase9_alex_telegram.py           11 passed
tests/test_cio_phase1_notification_containment.py 11 passed
```

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## SECRETS PRINTED: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

## Next phase allowed

Phase 10 — Git / release manifest / CI / Drive truth.
