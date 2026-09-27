# LaneHeartbeat@v1 — every lane beats; a beat is not success

```
Status:      ACTIVE (Wave 1 tranche 1 — SHADOW; emitted by scripts/lib/intelligence_client.py)
as_of:       2026-09-27T19:30:00-04:00
Measured at: cbf603526 (origin/main) / not measured at runtime yet
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
Package:     docs/architecture/cognitive_transformation_20260927/ (PR #1304); approval pkg-20260927-cogx-w1-d9e1
```

Written by `supervisor_heartbeat.beat(lane_id, ...)`: always to `data/runtime/heartbeats/<lane_id>.json` (atomic), and to `intelligence.heartbeat` when a connection is
passed and the table exists (`pg` ∈ written · absent · error · skipped). Fields: lane_id, boot_id (host boot id + pid), pid, host, release_sha, cwd, last_beat,
last_success (moves only with `success=True`), last_output_signal (moves only with `output_signal=True`), work_claimed/done/failed, queue_depth, oldest_queued,
memory_context_ok, degraded_reasons[]. Postgres failures never raise out of `beat`. The SLA row per lane is seeded by `scripts/seed_supervisor_sla.py` (06 §4).
