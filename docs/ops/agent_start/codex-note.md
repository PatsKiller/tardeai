# Codex note — agent claim board (operator installs)

Not installed by any agent. To use it, the operator adds the paragraph below to the Codex instructions
(`AGENTS.md` is read by Codex already; this is the short pointer for the Codex task prompt or `~/.codex/instructions.md`).

```
Trade AI: start every task from the agent claim board. Read docs/ops/AGENT_START_HERE.md and run its 5 commands:
export AGENT_CLAIM_VENDOR=codex AGENT_CLAIM_SESSION=<unique id> AGENT_CLAIM_AGENT=<name>; then
python3 scripts/agent_claim.py status; python3 scripts/agent_claim.py next (or take <task-id> / takeover <claim_id> --claim);
keep the worklog (plan/done/note/blocker/handoff), stage building / pr_open --pr N, task done, release --summary.
Codex cloud cannot reach the host claims dir: open the PR as a draft first thing so the board and other agents see it.
```
