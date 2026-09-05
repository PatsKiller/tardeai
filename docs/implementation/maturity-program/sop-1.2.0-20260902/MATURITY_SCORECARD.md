Status:      ACTIVE
as_of:       2026-09-02T18:00:00Z
run_id:      sop-1.2.0-20260902
worktree:    /home/johnclaw/trade-ai-worktrees/agent-sop-1.2.0
base_sha:    4bcba2cf7168f1cc9b1b7ffd18ab749b2eed44a9
control_surface_digest=13fbf92261f5e7b77ec4d213133cae5ec296051b2ed34c6163d95aca7b35ae96
Authority:   local Layer-1 evidence + runtime attestation. INDEPENDENT_VERIFICATION_PENDING. No remote.

# Maturity scorecard — Multi-Agent SOP 1.2.0

| dimension | verdict | evidence |
|---|---|---|
| Policy 1.2.0 PROPOSED / PENDING | PASS | AGENTS.md header |
| Control 6 docs index + quality | PASS | CONTROL6_INDEX_FINGERPRINT.txt + FULL_TEST_MATRIX.txt + RUFF_SHELLCHECK.txt |
| Control 7 agent-governance | PASS | CONTROL7_WORKFLOW_PROOF.txt + CONTROL7_LOCAL_EQUIVALENT.txt (EXIT_*=0) |
| Client registry | PASS | tests/test_agent_clients_registry.py |
| Session receipts | PASS | tests/test_agent_session_and_lease.py |
| Atomic leases + durable TTL | PASS | tests/test_agent_file_lease_canonical.py |
| Safe worktree / identity | PASS | tests/test_agent_worktree_identity.py + VERIFIER_RUNBOOK.md |
| Drive mirror fixtures | PASS | tests/test_agents_drive_mirror_policy.py |
| Evidence integrity | PASS | tests/test_sop_evidence_integrity.py + validate_sop_evidence_integrity.py |
| Toolchain version capture | PASS | tests/test_sop_toolchain.py (Ruff pinned + ShellCheck exact version) |
| eac13cfd0 disposition | RETAIN historical | EAC13CFD0_DRIVE_MANIFEST_DISPOSITION.md |
| Independent verification | INDEPENDENT_VERIFICATION_PENDING | must use governed launcher + runtime attestation |
| Autonomous financial readiness | NOT_APPLICABLE | |

## Seven-control table

| # | control | verdict | evidence path |
|---|---|---|---|
| 1 | PR collision | PASS | STAGE_01_PR_COLLISION.md |
| 2 | Client registry | PASS | config/agent_clients.yaml |
| 3 | Session receipt | PASS | agent_session_start + worktree identity |
| 4 | File/store leases | PASS | agent_file_lease canonical + UTC/boot TTL |
| 5 | Safe worktree | PASS | new-worktree.sh + identity adversarial |
| 6 | Doc index + quality | PASS | check-index command + fail-closed Ruff |
| 7 | agent-governance CI | PASS | CONTROL7_WORKFLOW_PROOF.txt (blob c03a4ef8c6f7…) |

Historical CONTROL6_* / FINAL_EXACT_STATE.txt are SUPERSEDED_NON_AUTHORITATIVE.
