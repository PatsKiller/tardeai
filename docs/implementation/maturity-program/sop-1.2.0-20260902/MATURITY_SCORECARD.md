Status:      ACTIVE
as_of:       2026-09-02T09:45:00-04:00
run_id:      sop-1.2.0-20260902
base_sha:    4bcba2cf7168f1cc9b1b7ffd18ab749b2eed44a9
Authority:   local evidence. INDEPENDENT_VERIFICATION_PENDING. No remote.

# Maturity scorecard — Multi-Agent SOP 1.2.0

| dimension | verdict | evidence |
|---|---|---|
| Policy versioning | PASS (PROPOSED 1.2.0 drafted; 1.1.0 still governs until approve+merge) | AGENTS.md header + version history |
| Client registry | PASS (local) | config/agent_clients.yaml + tests |
| Session receipts | PASS (local) | scripts/agent_session_start.py + tests |
| Atomic leases | PASS (local) | scripts/lib/agent_file_lease.py + overlap tests |
| Safe worktree | PASS (local harden) | scripts/new-worktree.sh |
| Changed-file quality | PASS (local cmd) | scripts/agent_changed_file_quality.py |
| agent-governance CI | PASS (workflow added; **required-context enablement NOT_VERIFIED** — operator) | .github/workflows/agent-governance.yml |
| Parallel safety | PASS (local lease tests) | test_agent_session_and_lease.py |
| Release integrity / promote | NOT_APPLICABLE this tranche | promote denied by prompt |
| Autonomous financial readiness | NOT_APPLICABLE | SOP ≠ trading auth |
| Independent verification | INDEPENDENT_VERIFICATION_PENDING | single-agent implementer |

## Seven-control table

| # | control | verdict | path |
|---|---|---|---|
| 1 | PR collision inventory | PASS | STAGE_01_PR_COLLISION.md + JSON |
| 2 | Agent client registry | PASS | config/agent_clients.yaml |
| 3 | Session receipt | PASS | scripts/lib/agent_session_receipt.py |
| 4 | File/store leases | PASS | scripts/lib/agent_file_lease.py |
| 5 | Safe worktree | PASS | scripts/new-worktree.sh |
| 6 | Doc attestation + quality | PARTIAL | quality cmd present; attestation fields on receipt; full INDEX regen NOT run this checkpoint |
| 7 | agent-governance CI | PASS (added) | workflow; branch-protection recommendation pending operator |
