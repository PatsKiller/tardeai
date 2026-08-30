# P7 — Notification routing matrix (CC-first)

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0  
**INTERDICT:** left as found (CC-first / `would_send=false`)  
**Gap:** G-NOTIFY-01  
**Package:** Diligence Phase 7 (master plan § PHASE 7)

## Claim

Routing for `IMMEDIATE` / `DIGEST` / `COMMAND_CENTER_ONLY` / `SUPPRESSED` is
proven for the diligence matrix **without sending Telegram** and without
flipping `CIO_SITUATION_NOTIFY` or clearing INTERDICT. No new Telegram producer.

## Code under audit

| Layer | Path | Role |
|-------|------|------|
| Signal gate | `scripts/lib/cio_notification_signal.py` | production `decide_notification` |
| Situation bridge | `scripts/lib/cio_situation_notify_bridge.py` | situation → decision shape |
| Policy (Wave 3B) | `scripts/lib/cio_notification_policy.py` | plan-book shadow router |
| CC render (Wave 3E) | `scripts/lib/cio_command_center.py` `build_notification_block` | display only |
| P7 suite | `tests/test_cio_diligence_p7_notification_matrix.py` | matrix + pins |

## Matrix (summary)

| Scenario | Expected class | Mechanism |
|----------|----------------|-----------|
| Priority up (WAIT→TRIM act_now) | `IMMEDIATE` once | signal material generation change |
| Priority up replay | `SUPPRESSED` / sticky `DIGEST` | unchanged generation |
| Priority down / block sticky | `SUPPRESSED` after transition | replay suppression |
| Reentry NEAR churn under WAIT | not `IMMEDIATE` | same reentry generation |
| Duplicate subject | `SUPPRESSED` | policy `duplicate_subject` |
| Dust / TEST / FIXTURE | `SUPPRESSED` | `is_forbidden_from_production` |
| Cash HOLD | not `IMMEDIATE` | non-action / cash lineage |
| S5 cash plan | `SUPPRESSED` | policy default |
| S6 fire | `COMMAND_CENTER_ONLY` | policy + Wave 3E CC block |
| Council DISPUTED | `COMMAND_CENTER_ONLY` | policy |
| Material S3 (default) | `DIGEST` | policy |
| Operator-directed | `IMMEDIATE` schema path | still `would_send=false` / shadow |

Every policy decision under test records `would_send: false`, `delivery: shadow`.

## G-NOTIFY-01

Alert fatigue vs miss under INTERDICT remains open as an **ops canary policy**
question. P7 **proves the matrix and the CC-first rail**; it does **not** enable
notify-on or recommend lifting INTERDICT.

Evidence retained from Wave 3E live book: 462/466 suppressed CC-only, 0 Telegram.

## Rails

- No new Telegram producer (grep pin on signal / bridge / policy).
- Policy never assigns env (`os.environ[...] =` / `putenv` absent).
- Bridge stamps `memory_behavior_influence=0`, `executable_order=None`.

## Exit gate

**PASS** when P7 suite is green and producer/env pins hold. Notify-on remains off.
