# Social Route Policy Replay

Status:      ACTIVE
as_of:       2026-06-28T13:03:00-04:00
Measured at: efcc51365 / not measured

**Status: PASS** | window: 30d
_Generated: 2026-06-28T17:01:13.356160+00:00_
_Source: `python3 scripts/replay_social_route_policy.py --days N --json`_

Replayed **1457** social scan rows.

## Route distribution

| Route | Count |
|-------|-------|
| watch_only | 1457 |

## OLD score-only vs NEW route-aware injection

- OLD (score ≥ 25) injected: **13**
- NEW tradeable micro-cap momentum_scalp: **0**
- NEW large-float scout (retained, manual review): **0**
- NEW watch-only (not injected): **1457**

- **Social-only GO leaks: 0** (must be 0)
- **Large-float scouts retained for operator: 0**

> Read-only replay. No broker writes. Large-float scouts are retained for operator review (not discarded); social-only candidates can never be GO/actionable.

