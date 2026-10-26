```
Status: ACTIVE
as_of: 2026-10-26T19:40:00-04:00
Measured at: AGENTS.md §25.10 Telegram go-signal · .mergify.yml label=operator-merge
Canonical repo path: docs/ops/AGENT_MERGIFY_HANDOFF.md
Authority: AGENTS.md §25.10; docs/ops/MERGIFY_DEPLOY_FOUNDATION.md
Supersedes: GitHub Approve-by-PatsKiller as Mergify gate; merge-ready label
See also: scripts/lib/pr_merge_telegram.py · scripts/request_pr_merge_approve.py · scripts/notify_pr_merge_ready.py
```

# Agent handoff — Telegram Approve, Mergify merges

## One sentence

**Open a ready PR, run `request_pr_merge_approve.py`, stop. The operator taps Approve on Telegram. The host adds `operator-merge`. Mergify merges in an ET window; the host poller promotes. No github.com Approve UI.**

## Agent path

| Step | Who | Done looks like |
|---|---|---|
| 1. Claim | Agent | `scripts/agent_claim.py` claim + worklog |
| 2. Build / test / dry-run | Agent | `TRADE_AI_CI=1` tests; dry-run quoted if writes/sends |
| 3. Open ready PR to `main` | Agent | Not draft. `solo` / `shared-infra` if needed. Last remote act |
| 4. Request Telegram Approve | Agent | `.venv/bin/python scripts/request_pr_merge_approve.py --pr <N>` (also after CI green). Host timer `notify_pr_merge_ready.py` re-sends when checks turn green |
| 5. Approve merge | **Operator (phone)** | Telegram **Approve merge** button. Deny clears the label |
| 6. STOP | Agent | No `gh pr merge`, no promote, no hand-applied `operator-merge` |
| 7. Queue + merge | Mergify | `label=operator-merge` + four checks green + ET window |
| 8. Promote CURRENT | Host poller | `tradeai-deploy-on-main` → `DeployOnMainReceipt@v1` |

## What unblocks Mergify

| Kind | Unblocks Mergify? |
|---|---|
| Telegram **Approve merge** → host adds `operator-merge` | **Yes** |
| GitHub PR Approve UI | No (not required) |
| Chat LGTM / `Adversarial-review: MERGE` | No (other rails) |
| Telegram `/approve` (guard grants) | No |
| Agent adding `operator-merge` by hand | **Forbidden** — only the settle path after a tap |

## Commands

```bash
# After opening a PR (or when CI is green):
.venv/bin/python scripts/request_pr_merge_approve.py --pr <N>

# Dry-run scan of open PRs (what the timer would notify):
.venv/bin/python scripts/notify_pr_merge_ready.py --dry-run --json

# Live notify for green open PRs (host timer / forced run):
.venv/bin/python scripts/notify_pr_merge_ready.py --apply
```

## Mergify ET windows (America/New_York)

| Window | When |
|---|---|
| Evening | Mon–Fri 18:00–19:00 |
| Midnight | Tue–Sat 00:00–01:00 |
| Morning | Mon–Fri 06:00–07:00 |
| Pre-open | Mon–Fri 08:00–08:45 |

No Mergify merge Mon–Fri 09:30–16:15 ET.

## Labels that block forever

`held`, `broker`, `broker_active_trader`, or paths under `scripts/active_trader/`, `scripts/brokers/`, `scripts/moomoo/`, `.env`, `config/secret_registry.yaml`.

## What the agent must never do

| Action | Why |
|---|---|
| `gh pr merge` / push `main` | Mergify is the merge actor |
| Approve on GitHub / invent a second account | Operator Telegram tap only |
| Add `operator-merge` without a Telegram settle | Go-signal must be the operator’s tap |
| Add `merge-ready` | Retired |
| Promote CURRENT | Host poller / emergency only |

## Operator (phone only for routine merges)

1. Telegram shows **PR merge approval** with Approve / Deny.
2. Tap **Approve merge** → label `operator-merge` appears on the PR.
3. At the next ET window with green CI, Mergify squash-merges.
4. Host poller promotes CURRENT. No GitHub expertise required.
