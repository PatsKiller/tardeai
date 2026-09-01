# Parallel worktree and merge strategy

Status:      ACTIVE
as_of:       2026-08-16T22:32:42-04:00
Measured at: efcc51365 / not measured

## Isolation

This branch was created in a physically separate worktree and never entered the
other agent's checkout.

| Item | Value |
|---|---|
| Base SHA | `968dafb6beda21aa11aa4cedeb7c9c3920c3fec4` |
| Base source | fresh `origin/main` (PR #339 already merged) |
| Branch | `feature/financial-senses-parallel-v1` |
| Worktree | `/home/johnclaw/tardeai-financial-senses-parallel-v1` |
| Main worktree | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` |
| Other active branch | `feature/agent-intelligence-foundation` |
| Other active worktree | `/home/johnclaw/tradeai-wt-cio-decision-truth` |

## Path-isolation policy

- All new code: `scripts/lib/financial_senses/`
- All new tests: `tests/financial_senses/`
- All docs: `docs/financial-senses/`
- All config: `config/financial_senses/`

Forbidden / avoided (owned by the other agent):
`docs/agent-intelligence/**`, central MCP gateway, ContextEnvelope,
AgentRunTrace, memory, global orchestration/notification, production
deployment/systemd/cron, broker surfaces.

## Collision audit

`git diff --name-only origin/main...feature/agent-intelligence-foundation`
shows only `docs/agent-intelligence/**`, `scripts/lib/agent_*.py`,
`tests/test_agent_*.py`. No overlap with this branch's filesystem namespace.

## Merge strategy

1. Do not merge automatically.
2. Rebase onto fresh `origin/main` only if it moves.
3. Resolve only legitimate independent changes.
4. Defer central MCP gateway wiring to a post-merge integration PR (see
   `INTEGRATION_WITH_AGENT_INTELLIGENCE_FOUNDATION.md`).

## Dependencies

No root dependency files were edited. Providers use the standard library plus
lazy imports of the existing `db_adapter` / `sec_data_ingest` modules. OpenBB is
not installed (`OPENBB_DECISION = DEFER`). FRED/OpenFIGI are config-only
(credentials optional; `NOT_CONFIGURED` without them).
