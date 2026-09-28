---
Status: PROPOSED
as_of: 2026-09-27T23:50:00-04:00
Measured at: wt/cogx-w4-t1-20260927 (Wave 4 item O-W4-1; package pkg-20260928-waves-3-5-cognition-unification-maturity-80f2)
Supersedes: none (the contract text lived in PLATFORM_INTELLIGENCE_DUE_DILIGENCE_2026-09-27.md §5)
---
# Worker contract (WorkerLease@v1)

Every lane that claims work converges on one contract, implemented by `scripts/lib/worker_contract.py`:

| Element | Rule | Where |
|---|---|---|
| Lease | one per lane: owner pid, `boot_id`, TTL (default 900 s), reclaimed only when the TTL expired or the boot id changed; a live lease raises `LeaseHeld` and the second worker exits 0 | `data/runtime/leases/<lane>.json` under flock |
| Heartbeat | one `LaneHeartbeat@v1` per run at exit (success / failure, claimed / done / failed) | `supervisor_heartbeat.beat` → file + `intelligence.heartbeat` |
| Status vocabulary | `QUEUED → LEASED → RUNNING → DONE \| FAILED \| ABANDONED`; `EXPIRED` by the reaper; every legacy word maps through `STATUS_MAP` | `worker_contract.canonical_status` |
| Idempotency | the store's own key (idempotency_key / candidate_id / event_guid) — the contract does not add one | per store |
| Reaper | a lease past its TTL is reclaimable; a lane's own reaper re-queues its store rows (existing behaviour kept) | per lane |
| Registry | a lane row with `output_signal` and an SLA row; the supervisor reads both | `config/lane_registry.json`, `intelligence.sla` |

## Queue styles and their mapping (measured 2026-09-27)

| Queue | Claim today | Contract step |
|---|---|---|
| Hermes research store (`hermes_research_requests.jsonl`) | flock + CAS, `status=running, locked_by, locked_ts`, 15-min reaper | keep the store; wrap `HermesWorker._process_one` in `lease("hermes-cio-worker")`; statuses map (`running→RUNNING`, `completed→DONE`, `superseded→ABANDONED`) |
| `watchlist_agent_jobs` (PG) | `SELECT … LIMIT` then a separate `UPDATE status='processing'` — **not atomic** (no `FOR UPDATE SKIP LOCKED`); 20-min reaper | keep the table; add `FOR UPDATE SKIP LOCKED`; lane lease per agent; `processing→RUNNING`, `deferred→QUEUED` |
| `inference_ensemble_jobs` (PG) | `UPDATE … FOR UPDATE SKIP LOCKED` (already atomic); heartbeat file | lane lease + `supervisor_heartbeat` (replace the private heartbeat file); `done→DONE`, `error→FAILED` |
| Escalation queues (JSON files) | whole-file read-modify-write under flock; ad-hoc `_dispatch_status` | lane lease for the handler; `dispatched/investigating→RUNNING`, `fixed→DONE` |
| CIO wake jobs + `cio_run_worker` | `claim(lease_seconds=300)`, `recover_expired_leases` (dead-letter after 3) | already the closest; vocabulary maps (`CLAIMED→LEASED`, `IN_FLIGHT→RUNNING`) |
| `action_queue` (PG) | no claim — operator approval queue | out of scope (A4/A5 rail) |

Reference implementation: `scripts/edge_fanout_consumer.py` (this PR). Migration order (one lane per PR, each keeping its store): hermes-cio-worker → watchlist-agent-* → inference ensemble → escalation handler → the rest of the 22 `*_queue` tables (12 §IN-5).

Authority: zero. The contract never decides what work means; it only makes claim, progress and completion legible to the supervisor (06 §3).
