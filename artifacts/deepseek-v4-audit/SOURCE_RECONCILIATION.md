# Stage 0 — Source Reconciliation

**Task:** DeepSeek V4 routing and site maturity  
**Captured:** 2026-08-03T13:31:44Z–local (commands in `STAGE0_COMMANDS.txt`)  
**Mode:** read-only discovery; no production restart; no deploy; `tradeai-wt-cursor-guardrails` not modified

## Checksums

```
cd /home/johnclaw/implementation-inputs/deepseek-v4-2026-08-03
sha256sum -c SHA256SUMS.txt
```

**Result:** ALL OK (exit 0).  
Files verified: EXECUTE prompt, README_FIRST, audit MD, model registry proposed, process policy proposed, UPLOAD_FROM_POWERSHELL.ps1.

`PACKAGE_AUDIT.json` is not listed in `SHA256SUMS.txt` (informational only).

## Package inputs read

| File | Role | Treatment |
|------|------|-----------|
| EXECUTE_…_PROMPT.md | Execution contract | Binding |
| README_FIRST.md | Package index | Binding |
| PACKAGE_AUDIT.json | Inventory | Review input |
| TRADE_AI_DEEPSEEK_V4_ROUTING…AUDIT…md | Audit | Review input, not unquestionable fact |
| TRADE_AI_LLM_MODEL_REGISTRY_PROPOSED.json | Proposed registry | Review input |
| TRADE_AI_LLM_PROCESS_POLICY_PROPOSED.json | Proposed process policy | Review input |

## Applicable repository instructions (canonical checkout)

| Path | Present |
|------|---------|
| `AGENTS.md` | YES (dirty in main worktree vs HEAD) |
| `OPERATIONS.md` | YES |
| `ARCHITECTURE.md` | YES |
| `README.txt` | YES |
| `CLAUDE.md` / `.cursorrules` | MISSING in canonical checkout |
| `docs/ops/LIVE_BASELINE_2026-08-03_STOP_TRUTH.md` | MISSING on this main tree; present on `tradeai-wt-cursor-guardrails` @ 31cd8398 (do not edit that worktree for this task) |

## Canonical repository

| Field | Value |
|-------|--------|
| **Canonical path** | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` |
| **Remote** | `https://github.com/PatsKiller/tardeai` (origin fetch+push) |
| **Branch (main worktree)** | `main` |
| **Local HEAD** | `72b6ddd201e541357cb52f30c3fdeb073adef02d` |
| **Subject** | `DeepSeek: fix silent local-gemma fallback, wire frontend, dry-test, screenshots` |

### Other PatsKiller/tardeai checkouts (not used as base)

- `/home/johnclaw/tradeai-wt-cursor-guardrails` @ `31cd8398` branch `wt/cursor-guardrails` — **FORBIDDEN to edit for this task**
- Many other worktrees under `/home/johnclaw/tradeai-wt-*`, `/home/johnclaw/wt-*`, rebuild worktrees — see `STAGE0_COMMANDS.txt`

## GitHub / origin/main

| Field | Value | Evidence |
|-------|--------|----------|
| `origin/main` after `git fetch --all --prune` | `ddef4613ec362e6c32307160aba8f4a56b835a20` | local + `gh api repos/PatsKiller/tardeai/commits/main` |
| GitHub API | `ddef4613…` | matches origin/main |
| Local main vs origin/main | **DIVERGED** | merge-base `f31eb179…`; neither is ancestor of the other |

### Commits on local main not on origin/main

```
72b6ddd2 DeepSeek: fix silent local-gemma fallback, wire frontend, dry-test, screenshots
3c632d20 feat(overview): weekend-aware pipeline status + off-market refresh
98c1eba5 fix(cron): correct script paths and lane args in cron_freshness_watcher
14cb1b9c fix(server): remove SO_LINGER=0 that truncated large HTTP responses
```

### Commits on origin/main not on local main

Includes PR merges #272–#277 (stop truth, portfolio maturity, reentry, trading desk maturity) starting from `ddef4613` back through the diverged history. Full list in `STAGE0_COMMANDS.txt` / `STAGE0_GIT_STATUS.txt`.

## Commit 72b6ddd2 recovery

| Check | Result |
|-------|--------|
| Local object | **YES** — `git cat-file -t 72b6ddd2` → `commit` |
| On local branch | **YES** — only `main` (`git branch -a --contains 72b6ddd2`) |
| On any `origin/*` remote branch | **NO** — empty `git branch -r --contains 72b6ddd2` |
| On GitHub | **NO** — API 422 “No commit found for SHA: 72b6ddd2…” |
| Content | 11 files; maps lanes `deepseek-flash`→`deepseek-chat`, `deepseek-v4`→`deepseek-reasoner` (legacy aliases — aligns with audit claim; exact V4 IDs **not** verified live yet) |

**Recoverable: YES.** Safe base for implementation worktree: **`72b6ddd2`** (contains DeepSeek work; clean tree when checked out as worktree tip).

## Dirty files (main worktree only)

| Metric | Value |
|--------|--------|
| Dirty count at Stage 0 | **184** (`103` modified, `81` untracked) |
| Drive / STATE_OF_REPO_LATEST | reported **173** dirty @ `main @ 72b6ddd2` (stale count vs current 184 — **conflict preserved**) |
| Top dirty roots | scripts (107), apps (39), config (18), docs (14), … |
| LLM/DeepSeek-related dirty | `llm_lane.py`, `llm_router.py`, `llm_consumption.py`, `ConsumptionHub.tsx`, `useOAuthLanes.ts`, `cloudLlmRun.ts`, `llm_process_registry.json`, `llm_route_policy.py` (untracked), etc. |

**Ownership:** Treat all 184 as **unowned by this task**. They remain on the main worktree. Implementation proceeds in a **dedicated clean worktree** at `72b6ddd2` so dirty files are **not** overwritten.

## Deployed / runtime SHA

| Field | Value |
|-------|--------|
| Live process cwd | `/home/johnclaw/trade-ai-releases/portfolio-server/af45096e-platform-audit-20260802` |
| `SOURCE_COMMIT` | `31cd83989a3e65ed84cde92aacabaac04c4ade10` |
| `RELEASE_NOTE` | baseline 31cd8398 agents-md stop-truth policy |
| Relation to 72b6ddd2 | **DIFFERENT lineage** (cursor-guardrails stop-truth baseline, not local main DeepSeek commit) |
| Relation to origin/main | Different branch tip (`wt/cursor-guardrails`); not equal to `ddef4613` |

## Drive / auto-generated reports

| Source | Claim | Verification |
|--------|--------|--------------|
| `docs/project/STATE_OF_REPO_LATEST.md` | main, dirty 173, tip 72b6ddd2 | Tip matches; dirty count now 184 |
| `docs/project/SYSTEM_FACTS_LATEST.md` | Git: main @ 72b6ddd2 | Matches local HEAD |
| Audit package Drive narrative | local DeepSeek not on GitHub | **CONFIRMED** |

## SHA agreement matrix

| Source | SHA | Agrees with local HEAD 72b6ddd2? |
|--------|-----|----------------------------------|
| Local main HEAD | 72b6ddd2 | — |
| origin/main / GitHub main | ddef4613 | **NO** (diverged) |
| Deployed portfolio-server | 31cd8398 | **NO** |
| Drive/STATE_OF_REPO tip | 72b6ddd2 | **YES** (tip only) |
| Drive dirty count 173 | — | **NO** vs 184 current |

**GitHub, server (deployed), local main, and Drive tip do not all agree.** Divergence is explained: local main holds unpushed DeepSeek + 3 commits; GitHub main advanced via other PRs; live HTTP serves a separate release tree pinned to `wt/cursor-guardrails` stop-truth baseline.

## Safe base commit (implementation branch)

```
72b6ddd201e541357cb52f30c3fdeb073adef02d
```

**Rationale:**

1. Recoverable DeepSeek work lives only here (not on origin/main).
2. Checkout as a new worktree yields a **clean** tree (0 dirty), satisfying “do not overwrite unrelated dirty files.”
3. Audit Phase 0 and execution contract both prefer the recoverable DeepSeek commit over bare origin/main for this task.
4. Residual risk: branch is **behind/diverged** from origin/main; PR later may need rebase onto origin/main — record as residual risk, not Stage 0 blocker.

## Stage 0 gate checklist

| Gate | Status |
|------|--------|
| Input checksums pass | **PASS** |
| Remote is PatsKiller/tardeai | **PASS** |
| Safe base commit identified | **PASS** (`72b6ddd2`) |
| Local DeepSeek commit recoverable | **PASS** |
| Unrelated dirty files would be overwritten | **PASS** (worktree isolates; main dirty left alone) |
| Dedicated worktree can be created | **PASS** (path free; branch name free) |
| tradeai-wt-cursor-guardrails not edited | **PASS** |

## Stage 0 stop conditions

None triggered. Proceed to create worktree:

```bash
REPO=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
BASE=72b6ddd201e541357cb52f30c3fdeb073adef02d
WT=/home/johnclaw/tradeai-wt-deepseek-v4-routing
BRANCH=fix/deepseek-v4-routing
git -C "$REPO" worktree add -b "$BRANCH" "$WT" "$BASE"
```

## Residual risks (preserved)

1. origin/main and 72b6ddd2 have **diverged**; integration with latest main is out of Stage 0 scope.
2. Deployed live (`31cd8398`) already has different DeepSeek/LLM surface than 72b6ddd2 — do not assume live behavior equals this branch.
3. At 72b6ddd2, provider IDs are still **legacy** `deepseek-chat` / `deepseek-reasoner` — Stage 2 must re-verify official API.
4. Dirty main tree continues to evolve; do not sync dirty files into the implementation worktree without ownership analysis.
