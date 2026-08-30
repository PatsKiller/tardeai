# CIO Diligence P7 — notification matrix (CC-first)

Date: 2026-08-30  
Authority: READ_ONLY_ADVISORY  
MBI_BEHAVIOR: 0  
INTERDICT: left as found  
Gap: G-NOTIFY-01  

## Delivered

| Artifact | Path |
|----------|------|
| Audit note | `docs/audits/diligence/P7_NOTIFICATION_MATRIX_2026-08-30.md` |
| Matrix suite | `tests/test_cio_diligence_p7_notification_matrix.py` |
| Patterns | `cio_notification_signal` · `cio_situation_notify_bridge` · `cio_notification_policy` (Wave 3B/3E) |

## Matrix at a glance

| Input | Route |
|-------|-------|
| Priority up (first material) | IMMEDIATE once |
| Priority up replay / NEAR churn | SUPPRESSED or DIGEST — never a second IMMEDIATE |
| Priority down sticky | SUPPRESSED after transition |
| Duplicates | SUPPRESSED |
| Dust / TEST | SUPPRESSED |
| Cash HOLD | not IMMEDIATE |
| S6 / DISPUTED council | COMMAND_CENTER_ONLY |
| Default material S3 | DIGEST |

All policy rows: `would_send=false`, shadow delivery. **No Telegram send in tests.**

## Rails

No new Telegram producer. Do not flip notify-on. CC-first only.

## Scoreboard

Package **P7** → DONE (this PR). G-NOTIFY-01 remains open for canary policy (not an enablement).
