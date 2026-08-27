> **UPDATE / SUPERSEDED STATUS — 2026-05-20**
> This diagnostic report reflects the pre-fix state. It has been superseded by AGENT-WORKER-1 (commit 00a6967).
> Current status: **FIXED**.
> Current result: worker not running was misdiagnosis; cron-triggered batch; schema mismatch fixed; 125 stuck jobs recovered.
> Safety: no trades, no orders, no live trading.

# Agent Queue Health Report
Generated: 2026-05-20T15:21:57.927381+00:00

## Status Counts (7 days)
| Status | Count |
|--------|-------|
| completed | 1763 |
| failed | 307 |
| processing | 95 |
| queued | 1121 |

## Queue State
- **Oldest queued:** 2026-05-19T10:23:13.281633-04:00
- **Worker running:** False

## Root Cause
- worker process not running; queue backlog: 1121 queued jobs; oldest queued job is 25.0h old

## Recommended Fix
- start the agent job worker process