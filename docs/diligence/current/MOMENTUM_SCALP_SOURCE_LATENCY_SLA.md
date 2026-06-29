# Momentum Scalp Source → Validation Latency SLA

**Status: WARN** (overall WARN) | window: 30d  
_Generated: 2026-06-29T01:43:01.650140+00:00_  
_Source: `python3 scripts/momentum_scalp_source_latency_sla.py --days N --json`_  

| Window | Range | src→proposal | target | proposal→validation | target | overall | bottleneck |
|--------|-------|-------------:|-------:|--------------------:|-------:|:-------:|:----------:|
| premarket | 06:00-09:30 | — | ≤10 | — | ≤2 | WARN | source_to_proposal |
| open | 09:30-10:30 | — | ≤5 | — | ≤1 | WARN | source_to_proposal |
| late_morning | 10:30-12:00 | — | ≤10 | — | ≤2 | WARN | source_to_proposal |

> Quote freshness is NEVER weakened. A stale-quote DEFER is not counted as a met SLA — proposal→validation only PASSes on a proven fresh-quote evaluation.

> Read-only. No live broker writes. Operator confirmation / 2FA untouched.

> WARN: premarket: no source→proposal lineage samples in window; open: no source→proposal lineage samples in window; late_morning: no source→proposal lineage samples in window

