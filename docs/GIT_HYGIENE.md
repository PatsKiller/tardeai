# Git Hygiene — protect the live primary tree (2026-07-01)

Status:      ACTIVE
as_of:       2026-07-01T18:02:15-04:00
Measured at: efcc51365 / not measured

## Problem
`portfolio_server.py` **hot-reloads code from the primary working tree** (`PROJECT_ROOT =
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`). Multiple long-running interactive coding
sessions (claude, codex) share that one checkout. A single working tree has **one shared HEAD/index**, so:

- a `git checkout <branch>` / `git reset` in the primary tree swaps files **under the live dashboard**
  (it starts serving whatever is on disk — possibly a half-applied feature branch), and
- a `git commit` while another session has a feature branch checked out lands **on that branch**, and
- `reset`/`cherry-pick` rewrite state under everyone.

On 2026-07-01 this discarded uncommitted work and contaminated a pushed branch. Root cause was NOT the
`coder_dispatch` auto-fix agent (it is correctly worktree-isolated + advisory) — it was interactive
sessions doing branch work in the shared tree.

## The rule
**The primary tree is for the running server. Do all branch work in an isolated worktree.**

```
scripts/new-worktree.sh <name>     # → /home/johnclaw/tradeai-wt-<name> on branch wt/<name>
cd /home/johnclaw/tradeai-wt-<name>
# edit, commit, push HERE; gh pr create --base main
git -C <PROJECT_ROOT> worktree remove /home/johnclaw/tradeai-wt-<name> --force   # when done
```
`gh pr merge/create` are remote operations — safe from any directory.

## The guard (enforcement)
`scripts/install-git-hygiene.sh` installs two layers. Both fire **only** in the primary tree while the
server is live, and **only** there — linked worktrees and a stopped server pass through. Bypass a single
legit server-tree op (deploy pull) with `ALLOW_MAINTREE_GIT=1`.

| Layer | Blocks | Mechanism |
|-------|--------|-----------|
| `git` shell wrapper (`git-hygiene.sh`, sourced in `~/.bashrc`) | `switch`/`checkout` to a non-`main` branch, `checkout -b`, `reset --hard/--merge`, `rebase`, `cherry-pick` | git has **no pre-checkout hook** — a wrapper is the only way to block branch switches |
| git hooks (`scripts/githooks/`) | `pre-commit` on a non-`main` branch; `pre-rebase`; `post-checkout` warns+logs | apply to **all** git invocations, incl. sessions that never sourced the wrapper |

`git commit` **on `main`** in the primary tree is still allowed (the hermes-daily / CHANGELOG automations
rely on it); only commits on a **feature** branch there are blocked.

## Stale sessions
Old abandoned agent shells hold the tree for days. List / reap them:
```
scripts/reap-stale-coding-sessions.sh                 # dry-run, flags >2d
scripts/reap-stale-coding-sessions.sh --kill --older-than 5
```
It never kills the current session's own ancestry, and only targets `claude`/`codex` processes (SIGTERM).

## Files
- `scripts/git_hygiene_guard.sh` — shared checks (primary-tree? server-live? override?)
- `scripts/git-hygiene.sh` — the `git` wrapper (source in interactive shells)
- `scripts/githooks/{pre-commit,pre-rebase,post-checkout}` — hook backstops
- `scripts/new-worktree.sh` — worktree helper
- `scripts/reap-stale-coding-sessions.sh` — stale-session reaper
- `scripts/install-git-hygiene.sh` — installer (hooks + ~/.bashrc)
