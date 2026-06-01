# Phase 36 — Scheduled Job Consolidation Audit Closeout

**Date:** 2026-06-01
**Status:** ALL PHASES COMPLETE

---

## Phase Summary

| Phase | Status | Commit | Description |
|-------|--------|--------|-------------|
| 36A | COMPLETE | `a1a0532` | Cron risk and grouping — 187 jobs, 5 groups |
| 36B | COMPLETE | `9ce372b` | Duplicate/overlap — 11+ scripts multi-scheduled |
| 36C | COMPLETE | `9ce372b` | Consolidation design — 5 target categories |
| 36D | COMPLETE | `9ce372b` | Low-latency vs batch classification |
| 36E | COMPLETE | `9ce372b` | Migration plan — Phases 41–46 |
| 36F | COMPLETE | (this commit) | Closeout |

## Key Findings

| Metric | Value |
|--------|-------|
| Cron jobs audited | 187 |
| Duplicate/overlap risks | 11+ scripts scheduled multiple times |
| Peak congestion | 28 jobs at 7–8 AM ET |
| Jobs using flock | 57 (30%) |
| Jobs WITHOUT flock | 130 (70%) |
| Jobs using market_day_gate | 14 (7%) |

## Consolidation Recommendations

| Category | Jobs | Action |
|----------|------|--------|
| Keep as cron | ~140 | No change |
| Migrate to systemd timer | ~15 | Phase 41 |
| Merge into pipeline controller | ~30 → ~3 | Phase 42–43 |
| Event-driven queue | ~5 | Phase 44 |
| Retire | ~5–10 | Phase 45 |
| Needs review | ~5 | Owner audit |

## Safety

| Check | Result |
|-------|--------|
| Runtime changes | ZERO |
| Cron changes | ZERO |
| DB writes | ZERO |
| Broker/proposal/trade/journal mutations | ZERO |

## Recommended Next Gates

| Option | Description |
|--------|-------------|
| A | Phase 37 — Hermes-to-Trade AI research bridge design |
| B | Phase 41 — migrate safest 5 cron jobs to systemd |
| C | Source discovery for highest-priority backlog items |
| D | Observation period (let all timers run 7 days) |

NOT recommended: autonomous research, broad cron changes without per-job approval.
