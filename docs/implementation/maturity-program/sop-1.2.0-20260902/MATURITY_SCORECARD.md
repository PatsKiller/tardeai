Status:      ACTIVE
as_of:       2026-09-02T10:30:00-04:00
run_id:      sop-1.2.0-20260902
worktree:    /home/johnclaw/trade-ai-worktrees/agent-sop-1.2.0
base_sha:    4bcba2cf7168f1cc9b1b7ffd18ab749b2eed44a9
Authority:   local evidence. INDEPENDENT_VERIFICATION_PENDING. No remote.

# Maturity scorecard — Multi-Agent SOP 1.2.0 (completion pass)

| dimension | verdict | evidence |
|---|---|---|
| Policy 1.2.0 PROPOSED / PENDING | PASS | AGENTS.md header |
| Control 6 docs index + changed-file gates | PASS | CONTROL6_* + FULL_TEST_MATRIX / quality cmd |
| Control 7 agent-governance workflow | PASS | CONTROL7_WORKFLOW_PROOF + LOCAL_EQUIVALENT |
| Client registry | PASS | tests/test_agent_clients_registry.py |
| Session receipts | PASS | tests/test_agent_session_and_lease.py |
| Atomic leases TTL/heartbeat/abandon | PASS | extended lease tests |
| Safe worktree | PASS | new-worktree.sh + tests |
| Drive mirror fixtures | PASS | tests/test_agents_drive_mirror_policy.py (no Drive write) |
| eac13cfd0 disposition | RETAIN historical | EAC13CFD0_DRIVE_MANIFEST_DISPOSITION.md |
| Independent verification | INDEPENDENT_VERIFICATION_PENDING | |
| Autonomous financial readiness | NOT_APPLICABLE | |

## Seven-control table

| # | control | verdict | evidence path |
|---|---|---|---|
| 1 | PR collision | PASS | STAGE_01_PR_COLLISION.md |
| 2 | Client registry | PASS | config/agent_clients.yaml |
| 3 | Session receipt | PASS | scripts/agent_session_start.py |
| 4 | File/store leases | PASS | scripts/lib/agent_file_lease.py |
| 5 | Safe worktree | PASS | scripts/new-worktree.sh |
| 6 | Doc index + quality | PASS | CONTROL6_INDEX_RECHECK.txt fingerprint e804b46ad29e |
| 7 | agent-governance CI | PASS | CONTROL7_WORKFLOW_PROOF.txt (required-context enablement still operator) |
