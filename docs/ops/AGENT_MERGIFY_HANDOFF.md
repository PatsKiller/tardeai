```
Status: ACTIVE
as_of: 2026-10-27T10:30:00-04:00
Measured at: AGENTS.md §25.10 Telegram digest go-signal · .mergify.yml label=operator-merge
Canonical repo path: docs/ops/AGENT_MERGIFY_HANDOFF.md
Authority: AGENTS.md §25.10; docs/ops/MERGIFY_DEPLOY_FOUNDATION.md
Supersedes: GitHub Approve-by-PatsKiller as Mergify gate; merge-ready label; per-PR Telegram prompts
See also: scripts/pr_merge_digest.py · scripts/lib/pr_merge_digest.py · config/merge_hold_paths.json · scripts/request_pr_merge_approve.py
```

# Agent handoff — open PR, stop; the digest handles approval

## One sentence

**Agents: open PR, stop; the digest handles approval.** The host digest lists every ready PR in one Telegram message; the operator taps **Approve all** once; the host adds `operator-merge` to each PR (bound to its head SHA); Mergify merges in an ET window; the host poller promotes. No github.com Approve UI, no per-PR request.

## Agent path

| Step | Who | Done looks like |
|---|---|---|
| 1. Claim | Agent | `scripts/agent_claim.py` claim + worklog |
| 2. Build / test / dry-run | Agent | `TRADE_AI_CI=1` tests; dry-run quoted if writes/sends |
| 3. Open ready PR to `main` | Agent | Not draft. `shared-infra` when it applies (never `solo`: retired with the release train, AGENTS.md §28.15 item 7). Last remote act |
| 4. Nothing to request | — | The digest timer finds the PR once it is ready (not draft, four checks green on the head, no held path). `request_pr_merge_approve.py --pr <N>` is optional and only records a nomination + prints the next digest time |
| 5. Approve all | **Operator (phone)** | One tap on the digest. Per-item Hold button or reply `hold #N` excludes one. Held-path PRs are listed as "needs operator merge" with no Approve |
| 6. STOP | Agent | No `gh pr merge`, no promote, no hand-applied `operator-merge`. Pushing a new head after approval drops the label; the PR returns to the next digest |
| 7. Queue + merge | Mergify | `label=operator-merge` + four checks green + ET window |
| 8. Promote CURRENT | Host poller | `tradeai-deploy-on-main` → `DeployOnMainReceipt@v1` |

## What unblocks Mergify

| Kind | Unblocks Mergify? |
|---|---|
| Telegram digest **Approve all** (or coordinator ad-hoc `--single` tap) → host adds `operator-merge` | **Yes** |
| GitHub PR Approve UI | No (not required) |
| Chat LGTM / `Adversarial-review: MERGE` | No (other rails) |
| Telegram `/approve` (guard grants) | No |
| Agent adding `operator-merge` by hand | **Forbidden** — only the settle path after a tap |

## Commands

```bash
# Agents: nothing. Optional — record a nomination and print when the next digest goes:
.venv/bin/python scripts/request_pr_merge_approve.py --pr <N>

# Preview the next digest (no send, no writes):
.venv/bin/python scripts/pr_merge_digest.py --dry-run

# Coordinator only — send the digest now / ad-hoc single-PR prompt:
.venv/bin/python scripts/pr_merge_digest.py --apply --now
.venv/bin/python scripts/request_pr_merge_approve.py --pr <N> --single
```

## Mergify ET windows (America/New_York)

| Window | When |
|---|---|
| Evening | Mon–Fri 18:00–19:00 |
| Midnight | Tue–Sat 00:00–01:00 |
| Morning | Mon–Fri 06:00–07:00 |
| Pre-open | Mon–Fri 08:00–08:45 |

No Mergify merge Mon–Fri 09:30–16:15 ET.

## Labels and paths that block forever

`held`, `broker`, `broker_active_trader`, or any path in `config/merge_hold_paths.json`: broker / Active Trader / order code, secrets, `AGENTS.md` / `AI_WORK_POLICY.md` / adapters, hooks and guard, and the merge + deploy control plane (`.mergify.yml`, the digest, `deploy_on_main`, emergency promote, release grant binding). The digest lists these as "needs operator merge".

## What the agent must never do

| Action | Why |
|---|---|
| `gh pr merge` / push `main` | Mergify is the merge actor |
| Approve on GitHub / invent a second account | Operator Telegram tap only |
| Add `operator-merge` without a Telegram settle | Go-signal must be the operator’s tap |
| Add `merge-ready` | Retired |
| Promote CURRENT | Host poller / emergency only |

## Operator (phone only for routine merges)

1. Telegram shows **PR merge digest** (weekdays 08:00 / 12:00 / 16:30 ET, weekends every 3h) — only when something is ready.
2. Tap **Approve all (N)** once (or Hold one first). Label `operator-merge` appears on each PR.
3. At the next ET window with green CI, Mergify squash-merges. Telegram: "Merged N, deploying".
4. Host poller promotes CURRENT. Telegram: "Live: <sha> — PRs …, post-release tester ok" (a failure is P1).
