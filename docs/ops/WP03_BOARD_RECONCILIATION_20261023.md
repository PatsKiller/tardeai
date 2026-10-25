# WP-03: board, PR and worktree reconciliation

Status: DRAFT — worker evidence; coordinator acceptance pending
as_of: 2026-10-24T01:44:42Z
Measured at: served `d0c8b70d8d915098094aa7180f25d6b0b0e0cffe`; main `3ca91af49`; session `codex-handoff-worker-20261023`

**Unpublished:** this report is a local worker deliverable. No merge, release, timer installation, contract review, live-list change, broker change or worktree removal was performed. The coordinator owns merges and releases under task `DSN-20261023-coordinator-P1-T1`.

The first branch push was rejected before execution by automatic approval review: remote Git pushes are reserved for the user/operator, and narrow scope plus existing authorization does not override that deny. No push occurred and no PR was opened. Publication must be performed by the operator; the worker did not attempt an alternate API, remote or branch.

Inspect the completed local change, then publish it:

```bash
cd /home/johnclaw/wt-codex-wp03-20261023
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push -u origin work/DSN-20261023-handoff-v3-P1-T03
gh pr create --base main --head work/DSN-20261023-handoff-v3-P1-T03 --title "WP-03 reconcile shipped tasks and stale PRs against the served release" --body-file /home/johnclaw/.cache/rtc/codex-wp03-20261023/pr-body.md
```

Paste back the push result and PR URL. The coordinator then verifies the four required checks and owns the merge/release.

## Completed cleanup

`agent_claim.py sync --dry-run --json` with GitHub access reported 40 observed claims and 35 lifecycle changes, including 15 released file claims. The subsequent `sync --apply --json` wrote 40 observations, applied the 35 transitions and reported no GitHub warning. The initial sandboxed preview could not reach GitHub; it was not used to authorize the connected apply.

The worker then closed 12 **free**, historical source-delivery tasks using `task done --evidence-only`, with PR URLs and the served SHA. Taken tasks owned by peer sessions were left to their owners; no `--force`, ownership override or coordinator takeover was used.

| Previously open PR | Integration evidence | Disposition |
|---|---|---|
| #1976 | `a9164e0183fa324a1350a2802d93fc940ce35fc9`, batch 7 #1982 | Closed with shipping comment; data-approval readiness is already served |
| #1879 | `a4b8e49ef4cc62e9a9dd3238c5d4f70cc6e08328` | Closed with shipping comment; exact head and integration are served |
| #1880 | `6a48c9e16ef461457f140c63d7ec1010cb080e4f` | Closed with shipping comment; exact head and integration are served |
| #1881 | `e0d02c488e229e214d269075db598ccd67ec639f` | Closed with shipping comment; exact head and integration are served |

Every closure preview checked the current remote state/head and proved both the exact PR head and integration commit were ancestors of the observed served SHA. Apply rechecked those facts, then confirmed the remote PR was CLOSED. No additional PR merge was needed. The open PR count fell from 38 to 34.

| Closed free task | Evidence |
|---|---|
| `DSN-20261023-account-labels-P1-T1` | #2020; served account-display library |
| `DSN-20261023-nvda-false-alert-P2-T1` | #2027; already merged and served |
| `T-20261023-c72f3b` | #1996, #2000, #2001; closes input-wiring delivery only |
| `DSN-20261022-momentum-alerts-P4-T3` | #1957; served `calibration-shadow-harness` remains shadow |
| `DSN-20261022-cio-prospect-store-P7-T1` | #1958, #1960 |
| `DSN-20261022-data-domains-P6-T1` | #1976, batch 7 #1982; domain approvals remain separate |
| `DSN-20261022-ops-controls-P4-T1` | #1972; promotion letters A–F remain separate |
| `DSN-20261022-ops-controls-P5-T1` | #1970; enabling the sudo window remains separate |
| `DSN-20261023-open-pr-triage-P2-T1` | #1879–#1881; closes source-delivery/PR cleanup only |
| `T-20261023-0ab508` | #1996, #2028; builder prerequisites already delivered |
| `DSN-20261022-cio-prospect-store-P6-T1` | #1955; served TradeInView journey |
| `DSN-20261023-work-pipeline-P2-T1` | #2024 via batch 10 #2023; protected Tier 2 flags remain disabled |

## Plan versus observed reality

The handoff plan was not edited. Ancestry establishes source inclusion, not runtime output or approval. In particular, a reverted change can remain an ancestor.

| WP | Plan says | Observed reality |
|---|---|---|
| WP-01 | Batch 11 done | Served SHA matches batch 11. Main additionally contains #2048 and #2030; those are not served. Coordinator release remains necessary. |
| WP-02 | #2031 in progress | OPEN at `27f696bee313ab50438c34c2f2be9ba7deb8f46d`; four required checks PASS. Operator/coordinator merge pending. |
| WP-06 | Four test jobs done | T1 #2043, T2 #2044, T3 #2035, T4 #2045 exist. Their eventual train merge/ejection outcomes remain separate work. |
| WP-07 | All four shadow windows COMPLETED | Receipt state is COMPLETED for the four cited reports. 00:00, 06:00 and 08:00 have `outcome=NO_OP`, `reason=NOTHING_ELIGIBLE`, no integration. The cited 18:00 report built `eb9d405d2ee334fa7b8bdbcf8b446974a305b88f`, kept #2043/#2044, and ejected #2045 for merge conflict. Distinguish receipt completion from integration coverage. The requested proof document is absent from served source. |
| WP-08 | Wiring PRs in progress | #1935/#1936 are OPEN and green; #1937/#1939/#1942 remain draft, green. D2 config is absent; train timers are not installed. |
| WP-12 | #2032 in progress | OPEN at `3540b757fd32dec09a263af1d123a8d5769e6c08`; all four required checks PASS. Worker cannot merge; draft-behavior proof follows its merge. |
| WP-13 | Local shard work in progress | #1943 still OPEN; planned successor remains local and depends on WP-12's workflow ownership/merge. |
| WP-18 | Rotation PR needs contract review | #2016 still OPEN; this worker did not review its contract or run rotation. |
| WP-19 | #2030 red/in progress | #2030 is MERGED at `3ca91af49` and its four checks passed; not in CURRENT. The coordinator worklog records the migration applied; this worker did not query production DB or independently attest that migration. |
| WP-20 | Writer in progress | #2034 remains OPEN with failing ci-gate. No dual-write flag was changed. |
| WP-23 | Research live, asks/lane in progress | #2005 is served; #2011/#2006 remain OPEN. No model, spend, memory or credential flag was changed. |
| WP-24 / WP-25 | AT PRs waiting | #1997 and #1991 remain OPEN. No AT code, host schedule or live mode was touched. |
| WP-26 | Gate 4/calibration/consolidation source live | #1971, #1957 and #1978 are ancestors of served source. That does not approve the live replacement or execute the operator packet. |
| WP-29 | Library/UI/NVDA fix live | #2020/#2026/#2027 are served; account confirmation and listed follow-ups remain open. |
| WP-31 | Watch baseline live; polish pending | #2008 is served. Responsive polish remains a separate AGENT package. |
| WP-32 | Memory fix live; verification pending | #2012 is served; this cleanup does not attest a full market session or remaining heavy routes. |
| WP-33 | Dashboard and parser live; remaining items open | #1972/#2022 are served. #1879–#1881 were already served and their stale PRs are now closed. No promotion letter was approved or applied. |
| WP-34 | #1976 needs rebase | Contradicted by exact-head ancestry: #1976 shipped in batch 7. Its stale PR is now closed. Remaining operator settings and config-modal work stay open. |
| WP-36 | P3 #2017 live | Source is served, but the requested `p3-cosmetics.spec.ts` registration is absent from the served `cc-surface-agreement-ci.yml`. The task remains open. |
| WP-41 | Work-board structure in progress | #2047 is OPEN at `8b6f0079a92b29fcb0e3dca15f5dd427cdb158fa`; all four required checks PASS. Not merged or served. |

Do **not** close #1953's tasks from ancestry: batch 10 reverted its lane registration. Likewise, the code prerequisite being served does not complete an operator action (arming, sudo-window enablement, migration, contract review, kill-switch act or scheduler change).

## Worktrees and remaining board ownership

`git worktree list --porcelain` enumerated **567 worktrees**: 274 HEADs are ancestors of main, 271 are ancestors of the observed served SHA. The complete path/branch/HEAD/ancestry inventory is `/home/johnclaw/.cache/rtc/codex-wp03-20261023/worktree_inventory.md`, with machine-readable `worktree-inventory.json` beside it. Worktree dirtiness was not measured; merged ancestry is not permission to remove a worktree. None was removed or archived.

Several completed source-delivery tasks are still taken by previous sessions, including batch 10 integration, shared-additive claims, the timer-packet implementation and D2 helper implementation. Their claims advanced from GitHub/release evidence, but `task done --evidence-only` intentionally closes free tasks only. Owners/coordinator should reconcile the task records; this worker did not bypass that ownership boundary. Tasks whose acceptance includes the later operator installation remain open.

## Commands for the operator/coordinator

The worker does not execute these. Run the checks before any merge and respect the coordinator's release freeze.

```bash
gh pr checks 2031 --required
gh pr checks 2032 --required
gh pr checks 2047 --required

# Operator: protected claim-hook change; coordinator: draft-CI and work-board deliveries.
gh pr merge 2031 --merge --match-head-commit 27f696bee313ab50438c34c2f2be9ba7deb8f46d
gh pr merge 2032 --merge --match-head-commit 3540b757fd32dec09a263af1d123a8d5769e6c08
gh pr merge 2047 --merge --match-head-commit 8b6f0079a92b29fcb0e3dca15f5dd427cdb158fa
```

WP-04 remains operator-only. Preview before installation:

```bash
cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
.venv/bin/python scripts/release_train_window_request.py --window 1800 --dry-run --shadow-only
bash docs/ops/packets/release-train-host-trigger-20261023/install.sh --preview
bash docs/ops/packets/release-train-host-trigger-20261023/install.sh --apply
systemctl --user list-timers --all 'tradeai-release-train-request@*.timer' 'tradeai-pr-census@*.timer'
```

WP-05 remains operator-only. Preview before creating/verifying the App configuration:

```bash
cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
.venv/bin/python scripts/ops/release_train_github_app_config.py --app-id 5419776 --repository PatsKiller/tardeai --dry-run
.venv/bin/python scripts/ops/release_train_github_app_config.py --app-id 5419776 --repository PatsKiller/tardeai
stat -c '%a %U' /home/johnclaw/.config/tradeai/release_train/github-app.json
```

Paste back the installer preview/apply result and timer list, and the App helper's success/failure plus mode/owner only; never paste keys or tokens.

## Evidence and validation

Local evidence root: `/home/johnclaw/.cache/rtc/codex-wp03-20261023/`.

- `sync-dry-run-connected.json`, `sync-applied.json`: preview and applied lifecycle transitions.
- `tasks-before.json`, `claims-before.json`, `task-audit.json`: original board snapshot and per-task PR/ancestry audit.
- `prs.json`, `open-prs.json`, `open-pr-ancestry.json`, `closed-prs.json`: PR states, heads and verified closures.
- `closed-tasks.json`: task IDs, closure summaries and evidence links.
- `worktree_inventory.md`, `worktree-inventory.json`: full non-destructive inventory.
- Four shadow receipts: `persistent-state/data/runtime/release_window/train_requests/reports/rtw-20261024-{0000-f734f52,0600-f980157,0800-f8a4a44,1800-fdb4df6}.json`.

Checks are read-only metadata and source-ancestry checks, plus the documentation index and whitespace checks. Native `fast_check.sh` selected 55 test files in 20 gates; its sole failure was three `ci_fixture_immutability` tests denied permission to create their fixture sockets. Re-running that hermetic gate with local sockets allowed passed all seven tests in 2.55 seconds. Secrets scanning, test coverage registration, host-path checks, documentation-index checks and whitespace checks passed. The initial sandbox failure is preserved in `fast-check.log`; the successful isolated rerun is in `fixture-gate-rerun.log`. No new production code or test file was introduced.
