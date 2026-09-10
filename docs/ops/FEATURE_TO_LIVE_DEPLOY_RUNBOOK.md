# Feature-to-live deploy runbook (single-approval)

Status:      ACTIVE
as_of:       2026-09-10
Measured at: 9853e6b47f13b744287c588cc0dcb5bd8bfe0bf7 (Fib chart declutter — PR #947 + #949)
Authority:   AGENTS.md §Local gates / docs/GIT_HYGIENE.md / RELEASE_COORDINATOR boundary
See also:    scripts/cio_phase2_exact_main_deploy.sh, scripts/new-worktree.sh, bin/guard

## Purpose

Take a finished feature branch all the way to LIVE with **one operator approval**, instead of
stopping to re-grant `git-push` / `release-write` at each boundary. The operator approves the
whole scope set once; the agent drives push → PR → merge (exact green SHA) → prepare → promote →
identity verification, with automatic rollback on a failed promote.

## The one approval

```bash
GUARD=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard
"$GUARD" plan docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md \
  --scopes "git-push release-write" \
  --for 12h --uses 25
```

or, equivalently, the two explicit grants the plan expands to:

```bash
"$GUARD" grant git-push     --for 12h --uses 25 --reason "feature-to-live: push + merge exact green PR heads"
"$GUARD" grant release-write --for 12h --uses 25 --reason "feature-to-live: prepare + promote exact verified merge SHAs"
```

`git-push` covers push + PR open + merge. `release-write` covers the immutable release write +
systemd promote. `maintree` is **not** required — the primary tree fast-forwards with a plain
`git merge --ff-only origin/main`, which is outside the maintree guard, and `checkout main` is an
allowed protected-branch operation.

## The procedure (what the agent runs after approval)

### 0. Work only in an isolated worktree

The primary tree is the LIVE hot-reload source and is shared with other sessions. All branch work
happens in a linked worktree:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
scripts/new-worktree.sh <name>          # → /home/johnclaw/tradeai-wt-<name> on wt/<name>
cd /home/johnclaw/tradeai-wt-<name>
# edit + commit HERE (explicit paths, never add-all)
```

### 1. Local gates before any push

```bash
cd /home/johnclaw/tradeai-wt-<name>/apps/command-center-v3
npx tsc --noEmit                        # typecheck clean
bash ../../scripts/check_design_tokens.sh   # design guard passes (no raw hex / sub-10px)
```

`tsc`/build need `node_modules`; symlink from the primary tree if absent, then remove it before
committing:

```bash
ln -sfn /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/apps/command-center-v3/node_modules node_modules
# ...typecheck... then:
rm -f node_modules
```

### 2. Push + PR

```bash
cd /home/johnclaw/tradeai-wt-<name>
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/agent-push -u origin wt/<name>
gh pr create --base main --head wt/<name> --title "..." --body "..."
```

### 3. Wait for green, merge exact SHA

The base-branch policy blocks merge until required CI passes. Poll until all green, then merge
and record the exact merge SHA (never trust a merge that returns nothing):

```bash
gh pr view <n> --json state,mergeable,statusCheckRollup   # until MERGEABLE + all SUCCESS
gh pr merge <n> --merge --subject "..." 
gh pr view <n> --json state,mergeCommit                    # confirm MERGED + capture oid
```

If `main` advanced while the branch was open, merge it in first and re-push:

```bash
git fetch origin main --quiet && git merge origin/main --no-edit
bin/agent-push -u origin wt/<name>    # then re-merge the PR
```

### 4. Re-sync primary tree to origin/main

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git fetch origin main --quiet
git merge --ff-only origin/main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && echo MATCH   # else re-run; main advances under concurrent merges
git status --short    # must be clean
```

### 5. prepare then promote (never promote alone)

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
bash scripts/cio_phase2_exact_main_deploy.sh prepare    # must end "npm run build OK" + "PREPARE OK"
bash scripts/cio_phase2_exact_main_deploy.sh promote    # must end "PROMOTE OK"
```

`prepare` is the moment the design-guard / pin-check / integrity-hook gates actually fire. A
`vite build only` fallback (design guard failure) is a **defect to fix before promote**, not a
signal to proceed.

### 6. Verify live identity (do not trust "PROMOTE OK" alone)

```bash
R=~/trade-ai-releases/portfolio-server/CURRENT
readlink -f ~/trade-ai-releases/portfolio-server/CURRENT   # → <sha>-main-exact-phase2-<ts>
cat "$R/SOURCE_COMMIT"; cat "$R/BUILD_SHA"
git -C /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild rev-parse origin/main
systemctl --user show portfolio-server.service -p WorkingDirectory --value
curl -fsS --max-time 5 http://localhost:7777/api/v2/health | python3 -c 'import sys,json; print(json.load(sys.stdin).get("ok"))'
```

All four pins (CURRENT dir, SOURCE_COMMIT, BUILD_SHA, origin/main) must be the **same 40-char
SHA**, `WorkingDirectory` must equal the CURRENT dir, and health must be `True`.

## Failure / rollback

`promote` already auto-rolls back to `PREV_RELEASE` on a failed health check. Manual rollback:

```bash
bash scripts/cio_phase2_exact_main_deploy.sh rollback
```

## Invariants to preserve

- Never `prepare`/`promote` a hybrid SHA (HEAD must equal origin/main; the script refuses).
- Never merge without green CI on the exact PR head.
- Never reintroduce raw hex / sub-10px fonts — `check_design_tokens.sh` is a frozen ratchet.
- `secret` and `gate` are **never** grantable; this runbook touches neither.
