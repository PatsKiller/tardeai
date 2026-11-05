```
Status: ACTIVE
as_of: 2026-10-26T10:25:00-04:00
Measured at: cutover branch feat/mergify-replace-train-20261026 (24.0.0 ACTIVE)
Canonical repo path: docs/ops/MERGIFY_CUTOVER_CHECKLIST.md
Authority: plan mergify_replace_train; docs/ops/MERGIFY_DEPLOY_FOUNDATION.md; AGENTS.md §25.10 ACTIVE
Supersedes: soft-add DRAFT checklist on same path
See also: docs/ops/EMERGENCY_MANUAL_PROMOTE.md, AGENTS.md §25.10
```

# Mergify cutover checklist (operator)

24.0.0 is ACTIVE. Soft-add code is on the cutover branch. Complete remote/host steps below.

## 0 — Preconditions (in the PR)

- [x] `docs/ops/MERGIFY_DEPLOY_FOUNDATION.md` + `EMERGENCY_MANUAL_PROMOTE.md`
- [x] AGENTS.md **24.0.0 ACTIVE** + AI_WORK_POLICY §28 + pin tests
- [x] `.mergify.yml` (queues, ET schedule, required checks, broker/held exclusions)
- [x] `scripts/lib/deploy_on_main.py` + `scripts/deploy_on_main_poll.py`
- [x] `scripts/emergency_manual_promote.sh` (receipt path=`manual_emergency`)
- [x] `scripts/post_release_tester.py` + `scripts/delivery_failure_alerts.py`
- [x] `config/systemd/user/tradeai-deploy-on-main.{timer,service}` (`--apply`)
- [x] Train UI surfaces removed / replaced with deploy strip (`DeployHoldStrip`; `ReleaseTrainCard` re-exports)
- [x] `RELEASE_TRAIN_*` docs copied to `archive/release_train_20261026/` + `TRIPWIRE.md`; live docs carry SUPERSEDED banners; `TRAIN_CONTROLLER_STATUS=BUILD_ONLY`
- [x] CI gates: `agents_policy_24_0_0_mergify_deploy`, `deploy_on_main_20261026`

## 1 — Ratify policy

1. [x] Operator approved 24.0.0 PROPOSED in session 2026-10-26, then directed full cutover.
2. [ ] Bind on PR open: comment `APPROVE_AGENTS_POLICY_24_0_0 <pr> <head_sha>` (§20).
3. [x] Header **24.0.0 ACTIVE** on the cutover branch.
4. [ ] Standing **deploy** delegation on the host (`~/.config/tradeai/deploy_on_main/delegation.json`, status ACTIVE).

## 2 — Install Mergify

1. [ ] Install Mergify on `PatsKiller/tardeai`.
2. [ ] Confirm `.mergify.yml` is on `main` (after merge) or the branch Mergify reads.
3. [ ] Open a non-broker test PR with label `merge-ready`; confirm it queues and does **not**
   merge outside an ET window.
4. [ ] Confirm a `broker` / `held` labeled PR never auto-queues.

## 3 — Arm host poller

1. [ ] Dry-run from CURRENT / worktree.
2. [ ] Quote the receipt under `persistent-state/data/runtime/deploy_on_main/`.
3. [ ] Install units; `daemon-reload`; `enable --now tradeai-deploy-on-main.timer`.
4. [ ] Confirm timer fires: `systemctl --user status tradeai-deploy-on-main.timer`.

## 4 — Disable the custom train

1. [x] `TRAIN_CONTROLLER_STATUS` is `BUILD_ONLY` on the cutover tree.
2. [ ] Disable claimer: `systemctl --user disable --now tradeai-release-train-claim.timer` (+ `.path`).
3. [ ] Pause or revoke the release-train GitHub App installation (D2 custody — §17).
4. [ ] Leave STOP latch semantics in place for **deploy** hold.

## 5 — Prove one cycle

1. Land one eligible PR via Mergify in a window.
2. Wait for poller (or run once with `--apply`).
3. Prove: CURRENT pin == that SHA; `DeployOnMainReceipt@v1` `path=poller` `outcome=verified`.

## 6 — Rollback if needed

- Engage deploy STOP — Mergify may still queue; promote stops.
- Disable `tradeai-deploy-on-main.timer`.
- Emergency path: `docs/ops/EMERGENCY_MANUAL_PROMOTE.md`.
