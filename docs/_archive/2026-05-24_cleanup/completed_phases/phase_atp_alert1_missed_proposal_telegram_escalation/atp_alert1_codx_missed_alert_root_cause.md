# ATP-ALERT-1 — CODX Missed Alert Root Cause

## Root Cause: alert_rule_missing

No script checked `current_price >= target` for pending proposals. The system had:
- Q-1C wrote fresh Alpaca price ($2.43) to CODX proposal
- CODX target was $2.36
- Price crossed target while NEEDS_REVIEW
- No alert rule existed to detect this condition
- No Telegram was generated

## Why Each Check Failed

| Check | Result |
|-------|--------|
| Target-cross check on pending proposals | **Does not exist** |
| Q-1C writeback triggers alert | **No** — only writes price, no alert call |
| Proposal revalidation checks target | **No** — only checks quote age/staleness |
| Promoter alert | **Only at promotion time**, not after price movement |
| Alert dispatcher | Only handles aging/stale alerts |

## Fix Applied

1. Created `run_atp_alert_evaluator.py` with target_crossed_before_review, large_move_before_review, blocked_but_moved
2. Wired into Q-1C: after successful quote writeback, evaluator runs and sends URGENT alert via Telegram
3. Dedupe prevents spam (1 alert per proposal per target-cross event)
