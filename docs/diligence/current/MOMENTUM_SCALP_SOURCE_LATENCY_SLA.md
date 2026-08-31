# Momentum Scalp Source → Validation Latency SLA

Status:      ACTIVE
as_of:       2026-06-28T22:49:34-04:00
Measured at: efcc51365 / not measured

**Status: WARN_PENDING_OBSERVATION** | readiness score: 4.5/5 | observed score: pending | samples: 0 | window: 30d  
_4.5-ready, pending live in-window observation_  
_Generated: 2026-06-29T02:48:13.568154+00:00_  
_Source: `python3 scripts/momentum_scalp_source_latency_sla.py --days N --json`_  

| Window | Range | samples | src→proposal | target | proposal→validation | target | status | bottleneck |
|--------|-------|--------:|-------------:|-------:|--------------------:|-------:|:------:|:----------:|
| premarket | 06:00-09:30 | 0 | — | ≤10 | — | ≤2 | WARN_PENDING_OBSERVATION | source_to_proposal |
| open | 09:30-10:30 | 0 | — | ≤5 | — | ≤1 | WARN_PENDING_OBSERVATION | source_to_proposal |
| late_morning | 10:30-12:00 | 0 | — | ≤10 | — | ≤2 | WARN_PENDING_OBSERVATION | source_to_proposal |

> No in-window lineage samples → WARN_PENDING_OBSERVATION (NOT a code failure). PASS requires observed samples meeting the SLA; 5.0 observed-score requires live in-window samples passing — not claimed before observation.

> Quote freshness is NEVER weakened. A stale-quote DEFER is not counted as a met SLA — proposal→validation only PASSes on a proven fresh-quote evaluation.

> Read-only. No live broker writes. Operator confirmation / 2FA untouched.

> WARN: premarket: no source→proposal lineage samples in window; open: no source→proposal lineage samples in window; late_morning: no source→proposal lineage samples in window

