# Agent start here — any vendor (Claude, Codex, Cursor)

```
Status:  ACTIVE (code); claim-before-edit is mandatory from AGENTS.md 20.0.0 ACTIVE (§28.3, §28.3a)
as_of:   2026-10-23
Design:  docs/ops/AGENT_CLAIM_BOARD.md
```

Operator 2026-10-23: tell any agent "read AGENTS.md, pick up open work", and it registers a task, does it and
finishes without further instruction. Work must carry over without loss between Claude sessions, Codex and Cursor.

Every session sets its identity once. Give every worker its own session id:

```bash
export AGENT_CLAIM_VENDOR=codex            # claude | codex | cursor
export AGENT_CLAIM_SESSION=<unique id>     # one per session/worker, never shared
export AGENT_CLAIM_AGENT=<short name>
```

Work only in your own git worktree under `$HOME`, never in the canonical checkout.

## The 5 commands

```bash
python3 scripts/agent_claim.py status                 # 1. what is in flight, what can be taken over, local work at risk
python3 scripts/agent_claim.py next [--kind fix]      # 2. take the highest-priority free task (or: take <task-id>)
python3 scripts/agent_claim.py plan "<step>"          # 3. keep the worklog: plan / done "<step>" / note "<why>" / blocker "<what, from whom>"
python3 scripts/agent_claim.py stage <claim_id> pr_open --pr <N>    # 4. after you open the PR (building before that)
python3 scripts/agent_claim.py task done <task-id>    # 5. finish; then release --summary "<one line>" when the claim is done
```

Steps:

1. **`status`** prints:
   - every in-flight claim: stage, age, vendor, branch, worktree, live head SHA and the Handoff line;
   - stale claims and claims that can be taken over;
   - **local-only work at risk**: branches with commits on no remote and no open PR.

   To continue someone's work, run `takeover <claim_id>`. It prints the Handoff section first. Add `--claim` to take
   the work over; the worklog is carried forward.
2. **`next`** picks a free task:
   - its dependencies are done;
   - its areas overlap no live claim;
   - highest priority (1 is highest) first.

   It claims the task's areas and opens your worklog (`<claims_dir>/<claim_id>.worklog.md`) with the task's
   acceptance criteria as the Plan. `take <task-id>` picks one specific task. Need more files? Run
   `claim --add <paths>`; it is refused on overlap.
3. **Keep the worklog current.** Use `plan`, `done`, `note` (`--change` for a change made), `blocker` and
   `handoff --next "<exact next step>" --verify "<how>"`. Run `heartbeat <claim_id>` at least every 2 h: it records
   your head SHA and appends new commits to the worklog. From AGENTS.md 20.0.0 the pre-commit gate refuses a
   commit from a session in three cases:
   - its claim has no plan;
   - its worklog has no entry in the last 2 h;
   - the staged files are not covered by its claim.
4. **Stages.** Run `stage <id> building` when you start and `stage <id> pr_open --pr N` when the PR is open. The
   board observes `ci_green`, `merged` (your files are freed) and `released` by itself.
5. **Finish.** `task done <task-id>` checks the acceptance boxes. Then run
   `release <claim_id> --summary "<one line>"`. If you cannot finish, run
   `task release <task-id> --handoff "<exact next step>"`. The task goes back on the board with its history, and
   the next picker's worklog continues yours.

Bypass a blocked commit only with `TRADEAI_CLAIM_OVERRIDE=<reason>`. Every use is logged.

Adapters (files only; the operator installs them):
- Cursor: `docs/ops/agent_start/cursor-rule.md`
- Codex: `docs/ops/agent_start/codex-note.md`
- Claude Code SessionStart hook: `scripts/agent_session_start.sh`
