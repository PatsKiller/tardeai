# Breach@v1 — an SLA breach on a lane, with its evidence and ladder level

```
Status:      ACTIVE (Wave 1 tranche 2 — SHADOW; emitted by scripts/supervisor_breach_detector.py)
as_of:       2026-09-27T20:10:00-04:00
Measured at: cbf603526 (origin/main) / not measured at runtime yet
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No ladder level is executed in Wave 1.
Package:     docs/architecture/cognitive_transformation_20260927/ (PR #1304); approval pkg-20260927-cogx-w1-d9e1
```

Emitted by `supervisor_breach_detector.detect()` and appended to `data/runtime/supervisor_breaches.jsonl` (one row per NEW breach id; the id is
stable per lane × kind × UTC day, so a repeat observation is not a new row). Projected to `intelligence.breach` when the schema exists.

| Field | Meaning |
|---|---|
| breach_id ("br_" + 16 hex) | sha256(lane_id, kind, day) |
| lane_id, silo_id | lane from `config/lane_registry.json`; silo from `config/platform_silos.json` |
| kind | SILENT · HUNG · BACKLOG · FAILING · NO_OUTPUT · MEMORY_UNREACHABLE · SLO_MISS · UNGOVERNED (06 §5) |
| detected_at, evidence{} | the heartbeat/SLA/output-signal facts that raised it, with the command to reproduce where one exists |
| level 1..5, state OPEN · RECOVERING · RECOVERED · ESCALATED · CLOSED, recovery[] | Wave 1 writes level 1 (2 for MEMORY_UNREACHABLE) and state OPEN only; L1–L5 actions and RecoveryReceipt@v1 arrive in Wave 2 |

Rules: UNGOVERNED = an ACTIVE lane with no SLA row (seed with `scripts/seed_supervisor_sla.py`). SILENT needs a prior beat (a lane that never beat is
UNMEASURED, not SILENT). NO_OUTPUT = the registered output signal is unreadable or older than 3 × cadence (min 15 min). RECOVERED (Wave 2) requires the
output signal, never exit 0.
