# Cursor rules snippet — agent claim board (operator installs)

Not installed by any agent. To use it, the operator copies the block below into `.cursor/rules/agent-start.mdc`
(or the project rules in Cursor settings).

```
---
description: Trade AI — start every session from the agent claim board
alwaysApply: true
---
Before editing anything in this repository:
1. Read docs/ops/AGENT_START_HERE.md and follow its 5 commands.
2. export AGENT_CLAIM_VENDOR=cursor AGENT_CLAIM_SESSION=<unique id> AGENT_CLAIM_AGENT=<name>
3. Run: python3 scripts/agent_claim.py status
4. Take work with: python3 scripts/agent_claim.py next   (or take <task-id>, or takeover <claim_id> --claim)
5. Keep the worklog current (plan / done / note / blocker / handoff); heartbeat every 2 h.
Cloud/background agents that cannot reach the host's claims dir: open your PR as a draft early (the board sees it).
Never edit the canonical checkout; work in your own worktree.
```
