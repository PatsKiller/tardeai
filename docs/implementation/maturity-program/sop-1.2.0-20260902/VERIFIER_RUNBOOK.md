# SOP 1.2.0 · Independent verifier runbook

**Status:** binding for any independent verification of this tranche
**Authority:** local evidence only until remote sync is explicitly authorized
**Does not authorize:** push, PR, merge, Drive write, branch protection, deploy, production, or trading

## Why this runbook exists

A verifier was once launched from a **release directory** whose `.git` file borrowed
another registered worktree's Git metadata. Git reported that release path as
`--show-toplevel`, HEAD resolved to the **wrong** commit (e.g. `origin/main` instead
of the SOP tip), and `git status` showed ~1,760 phantom modifications. The verifier
never entered the intended worktree.

That bypass is now a named adversarial case. The governed session launcher fails
closed **before any write** (no leases, no receipt files, no generated artifacts).

## Mandatory launcher

Independent verification **must** start through:

```bash
cd /ABSOLUTE/PATH/TO/REGISTERED/SOP/WORKTREE
python3 scripts/agent_session_start.py \
  --agent <registered_or_advisory_id> \
  --verifier \
  --expected-worktree /ABSOLUTE/PATH/TO/REGISTERED/SOP/WORKTREE \
  --expected-head <full-40-char-sop-tip-sha> \
  --json
```

Requirements:

1. **cwd** is the registered SOP worktree (not a release dir, not the hub, not another WT).
2. **`--expected-worktree`** equals that same canonical path.
3. **`--expected-head`** equals the exact SOP tip being verified.
4. **`--verifier`** forces read-only mode and requires the two expected-* flags.
5. Do **not** run verification from `/home/johnclaw/trade-ai-releases/**` or any path
   whose `.git` is a `gitdir:` pointer at another checkout.
6. Do **not** touch release `build-meta.json`, other worktrees, or production trees.

If the launcher prints `ok=False`, **stop**. Do not proceed to tests, builds, or edits.

## Exact identity assertions (fail closed)

Implemented in `scripts/lib/agent_worktree_identity.py` and invoked from
`scripts/lib/agent_session_receipt.py` **before** lease acquisition or receipt
persistence:

| # | Condition | Error code |
|---|---|---|
| 1 | Canonicalized cwd ≠ expected worktree | `CWD_NE_EXPECTED_WORKTREE` |
| 2 | `git rev-parse --show-toplevel` ≠ expected | `TOPLEVEL_NE_EXPECTED_WORKTREE` |
| 3 | Expected path absent from `git worktree list --porcelain` | `EXPECTED_NOT_IN_WORKTREE_LIST` |
| 4 | Git directory / identity belongs to another registered worktree | `GITDIR_BELONGS_TO_OTHER_WORKTREE` |
| 5 | Release/deployment dir borrows another worktree's gitdir | `BORROWED_GITDIR_OR_RELEASE_DIR` |
| 6 | Actual HEAD ≠ expected HEAD | `HEAD_NE_EXPECTED` |
| 7 | Tracked/untracked dirty without `--acknowledge-dirty` | `DIRTY_UNACKNOWLEDGED` |

Deterministic tests: `tests/test_agent_worktree_identity.py`
(positive: clean registered detached worktree accepted in verifier mode;
negatives: each adversarial borrow / mismatch above).

## Why a raw shell verifier bypasses this

Any process that:

- `cd`s into a release dir and runs `git` / pytest / make directly, or
- assumes `git rev-parse HEAD` in cwd is the SOP tip without the launcher,

**skips** `agent_session_start.py` and therefore skips identity assertion. That is
operator/process error, not a green signal. The runbook rule is: **no verification
without a successful governed launcher receipt** showing matching
`expected_worktree`, `expected_head`, and `identity.ok=true`.

## After a successful launcher receipt

Only then run the seven-control matrix inside the **same** worktree. Still no push,
PR, Drive write, branch-protection change, or deploy unless a later operator phrase
explicitly authorizes remote sync.
