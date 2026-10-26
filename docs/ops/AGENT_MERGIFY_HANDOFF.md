```
Status: ACTIVE
as_of: 2026-10-26T17:58:00-04:00
Measured at: AGENTS.md 24.0.0 ACTIVE · §25.10 Approve-only · .mergify.yml on feat/approve-only-mergify-20261026
Canonical repo path: docs/ops/AGENT_MERGIFY_HANDOFF.md
Authority: AGENTS.md §25.10; docs/ops/MERGIFY_DEPLOY_FOUNDATION.md
Supersedes: merge-ready label as Mergify gate; agent handoff via custom release-train queue / Run now
See also: docs/ops/EMERGENCY_MANUAL_PROMOTE.md · docs/ops/MERGIFY_CUTOVER_CHECKLIST.md
```

# Agent handoff — leave everything to Mergify

## One sentence

**Open a green ready (not draft) PR, get one GitHub Approve from PatsKiller, and stop. Mergify merges in an ET window; the host `deploy_on_main` poller promotes. No `merge-ready` label.**

## Agent path (thorough) — who does what

| Step | Who | What “done” looks like |
|---|---|---|
| 1. Claim | **Agent** | `scripts/agent_claim.py` claim + worklog (§0 rule 11) |
| 2. Build / test / dry-run | **Agent** | Tests under `TRADE_AI_CI=1`; dry-run quoted if it writes/sends/schedules |
| 3. Open ready PR to `main` | **Agent** | Not draft. Apply `solo` or `shared-infra` at open if needed. Never `held`/`broker` unless true. PR is the **last remote act** |
| 4. CI green | **GitHub Actions** | All four required checks `success` on the **exact head SHA**: `cio-hardening`, `agent-governance`, `release-readiness`, `ci-gate` |
| 5. Approve | **Operator** (`PatsKiller`) | GitHub PR review = **Approve**. Not a comment, not Telegram, not a policy token |
| 6. STOP (agent) | **Agent** | Worklog: “monitor Mergify / poller”. No `gh pr merge`, no promote, **no `merge-ready` label** |
| 7. Queue + merge | **Mergify** | Only inside ET windows; needs PatsKiller Approve + green + not draft |
| 8. Promote CURRENT | **Host poller** | `tradeai-deploy-on-main` → `DeployOnMainReceipt@v1` (`path=poller`) |

## Who approves? (the race-y part)

Three different “approvals” exist. Only one unblocks Mergify.

| Kind | What it is | Who | Unblocks Mergify? |
|---|---|---|---|
| **A. GitHub PR Approve by PatsKiller** | Review → **Approve** on the PR | **Operator** (`@PatsKiller`). GitHub forbids the PR author from counting as their own approve. | **Yes** — `.mergify.yml` requires `approved-reviews-by=PatsKiller` |
| **B. Branch-protection “required reviews”** | Repo setting `required_approving_review_count` | Measured **2026-10-26: still `0`**; CODEOWNERS is **advisory** | No — protection does not require a review to merge by hand; **Mergify still does** |
| **C. Policy / §17 / design / AGENTS ratification** | Passkey, `APPROVE_AGENTS_POLICY_…`, Ops → Controls, design ledger | Operator only | No — separate from the merge queue |

**Practical rule for agents**

1. Ask the **operator** to open the PR on GitHub and click **Approve** (or Approve from the GitHub mobile/app review UI).
2. Do **not** treat a chat “looks good”, a Telegram `/approve` (that is **guard grants** only), or an `Adversarial-review: MERGE` PR comment as the Mergify gate — those are other rails.
3. Do **not** Approve your own PR. Do **not** invent a second GitHub account to self-approve (§0 rule 3 / §28.4).
4. After a new push to the PR, stale Approves may be dismissed (`dismiss_stale_reviews: true` on main). Re-check: still green + still Approved by PatsKiller on the **new** head before relying on the queue.
5. Measured collaborators with write access on `PatsKiller/tardeai`: **`PatsKiller`** — so the human operator is the intended Approver for Mergify.

**Solo / shared-infra (extra policy, still needs A)**

- Label `solo` or `shared-infra` at PR open (batch size 1). Agent owns these classification labels.
- AGENTS §28.15 also wants an `Adversarial-review: MERGE` receipt from a **non-author** agent for solo eligibility. That is **policy evidence in the PR body/comments**; it does **not** replace step A. Mergify still needs the PatsKiller Approve + green checks + not draft.

## What the agent must do (checklist)

1. **Claim** — `scripts/agent_claim.py status` then claim paths / task id (§0 rule 11, §28.3a).
2. **Build in a worktree** off fresh `origin/main`; never edit broker authority (§0 rules 1–2).
3. **Test + dry-run** for anything that writes, sends, or schedules (§0 rules 7–8, §8.1).
4. **Open a ready (not draft) PR** to `main` (push only with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` inside the push budget). Apply `solo` / `shared-infra` when that class applies. The PR is the agent’s last remote act (§25.1, §25.10).
5. **Wait for required checks** on the exact head SHA — all must be `success`:
   - `cio-hardening`
   - `agent-governance`
   - `release-readiness`
   - `ci-gate`
6. **Get PatsKiller’s GitHub Approve.** Hand the operator the PR URL; do not merge yourself.
7. **Do not add `merge-ready`.** That label is retired as a Mergify gate. Do **not** add `held`, `broker`, or `broker_active_trader` unless the change is truly that class (those never auto-merge).
8. **Stop.** Do not merge, do not push `main`, do not promote, do not run `cio_phase2_exact_main_deploy.sh`, do not set `TRADEAI_EMERGENCY_RELEASE_SHA`.

## What happens next (no agent)

```
Ready PR + green + PatsKiller Approve (not draft)
  → Mergify queue (ET windows only — see below)
  → squash-merge to main
  → tradeai-deploy-on-main.timer → deploy_on_main_poll.py
  → STOP clear + GlobalReleaseLock + standing deploy delegation armed
  → prepare + promote CURRENT to that exact SHA
  → post_release_tester → DeployOnMainReceipt@v1 (path=poller)
```

## Mergify ET windows (America/New_York)

| Window | When |
|---|---|
| Evening | Mon–Fri 18:00–19:00 |
| Midnight | Tue–Sat 00:00–01:00 |
| Morning | Mon–Fri 06:00–07:00 |
| Pre-open | Mon–Fri 08:00–08:45 |

No Mergify merge during market hours Mon–Fri 09:30–16:15 ET (schedule simply does not include that range).

## Labels that block Mergify forever

- `held`
- `broker`
- `broker_active_trader`
- Or paths under `scripts/active_trader/`, `scripts/brokers/`, `scripts/moomoo/`, `.env`, `config/secret_registry.yaml`

Those stay **operator merge only**.

## What the agent must never do

| Action | Why |
|---|---|
| `gh pr merge` / push `main` / `train/*` | §25.10 — Mergify is the merge actor |
| Add `merge-ready` as a gate | Retired; Approve by PatsKiller is the go signal |
| Promote / prepare CURRENT | Host poller only (or operator emergency) |
| Request `release-write` for a routine land | Emergency path is operator-only |
| Clear STOP / arm deploy delegation | §17 |
| Wait for natural schedule as “proof the PR works” | CI + Mergify window are the path; monitor after |

## Operator-only (not agent)

- Install / re-permission Mergify App
- Arm / pause standing **deploy** delegation
- STOP / clear deploy hold (Ops → Controls or host CLI)
- Emergency: `scripts/emergency_manual_promote.sh` + `release-write` naming SHA + `TRADEAI_EMERGENCY_RELEASE_SHA`
- Merge held / broker PRs by hand
- Bootstrap: the first Approve-only config PR on main may still need a one-time manual or temporary `merge-ready` under the **old** rules until this config is served

## Proof the handoff worked

- PR shows Mergify queued or merged in a window after PatsKiller Approve (no `merge-ready`)
- CURRENT pin equals the merged SHA (or poller receipt `already_served` / promote receipt under `persistent-state/data/runtime/deploy_on_main/`)
- Agent worklog marks PR opened + next step = “operator Approve → monitor Mergify / poller”

## References

- `docs/ops/MERGIFY_DEPLOY_FOUNDATION.md` — authority split and normal path
- `docs/ops/EMERGENCY_MANUAL_PROMOTE.md` — operator emergency only
- `docs/ops/MERGIFY_CUTOVER_CHECKLIST.md` — cutover status
- `AGENTS.md` §25.10 (24.0.0 ACTIVE) · §28.12 steps 7–8
- `.mergify.yml` — queues, schedules, PatsKiller Approve, `draft=false`
