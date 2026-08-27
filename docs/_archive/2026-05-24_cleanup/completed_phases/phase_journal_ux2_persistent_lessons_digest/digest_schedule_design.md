# JOURNAL-UX-2 — Digest Schedule Design

**Status:** Design only (cron not installed)

## Recommended Schedule
- 16:15 or 16:30 ET M-F: end-of-day closed-trade digest
- Route as P1_DIGEST through OPS-HYGIENE router
- Suppress if no closed trades and no lessons
- Log-only on success (P3)
- P0 only if sending fails repeatedly

## Cron Entry (when approved)
```
15 16 * * 1-5 cd $PROJ && .venv/bin/python scripts/send_closed_trade_digest.py --date today --send >> logs/closed_trade_digest.log 2>&1
```

## Not installed until operator approves after test digest review.
