# WP-15: AGENTS 20.2.0 operator package

Status: DRAFT — proposed operator package; no policy or runtime flag is activated
as_of: 2026-10-24T02:20:00Z
Measured at: base `4acb33ada3eed278c5f7652fcdcd6cbda15e68e5` / AGENTS 20.1.0 ACTIVE

This package is an operator-applied proposal. The worker builds patches and verifies isolated copies; the operator applies and ratifies them. Current repository policy, adapters and runtime flags are unchanged by delivery of this directory.

The exact package manifest is `SHA256SUMS`. Compare its own SHA-256 with the delivery report, then run `sha256sum -c SHA256SUMS`. `BASE_SHA`, `base-digests.json` and `package.json` bind every patched file and the unchanged Ops Controls configuration. A changed digest refuses application. Unrelated main commits are allowed only when all bound file bytes are identical.

## Scope

- §27.2: named Work pipeline Tier 2 acts are the operator's own acts, with a fresh passkey assertion and typed phrase through the existing host applier. Required checks must be exactly success on the shown PR head; releases keep exact-main checks and an active bound release-write grant.
- Grant-binding package approval is excluded; `approve_item_enabled` stays false. The older proposal's Telegram wording was not copied because current §27.3 says Telegram is notification only.
- §28.3: declared shared-additive paths never conflict; missing/invalid configuration restores exclusive paths.
- §28.3a: evidence-only closure is for already-shipped free tasks, never taken tasks.
- §28.3b: every task carries problem, definition of done, agent prompt, operator commands and proof; done requires evidence (WP-41).
- Four adapters and their parity test say **eleven**. Their §0 bodies remain byte-identical.
- §28.8 already uses `TRADEAI_LIVE_SMOKE_AFTER_CLOSE=1` on this base, so no redundant change is made.
- Historical 20.0.0/20.1.0 pinning tests undo only the exact new additions before retaining their original hashes. New whole-document pins blank the renderer-owned §7A table. The WP-19 note's fix is already in the base and is preserved.

## Operator commands

The package is installed at the durable server path below. Run from the operator's terminal. Default invocations are previews; `--apply` requires a TTY and the exact displayed phrase. Nothing merges automatically.

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git fetch -q origin
wp15_package=/home/johnclaw/trade-ai-releases/persistent-state/data/coordination/handoffs/agents-20-2
cd "$wp15_package"
sha256sum SHA256SUMS
sha256sum -c SHA256SUMS
bash apply202-operator.sh
bash apply202-operator.sh --apply
```

The apply step creates `/home/johnclaw/wt-agents-20-2-operator-20261023`, branch `ops/agents-20-2-20261023`, runs the governance checks, commits and publishes the PROPOSED PR. It prints the actual PR number and SHA. It refuses if that branch or worktree already exists; inspect rather than replace it.

After reviewing that actual proposed PR, these commands derive its real values and record the operator's own token; no placeholder or fabricated PR number is used:

```bash
cd /home/johnclaw/wt-agents-20-2-operator-20261023
wp15_policy_pr=$(gh pr view ops/agents-20-2-20261023 --repo PatsKiller/tardeai --json number -q .number)
wp15_policy_sha=$(gh pr view "$wp15_policy_pr" --repo PatsKiller/tardeai --json headRefOid -q .headRefOid)
gh pr comment "$wp15_policy_pr" --repo PatsKiller/tardeai --body "APPROVE_AGENTS_POLICY_20_2_0 $wp15_policy_pr $wp15_policy_sha"
bash /home/johnclaw/trade-ai-releases/persistent-state/data/coordination/handoffs/agents-20-2/ratify202-operator.sh --pr "$wp15_policy_pr" --sha "$wp15_policy_sha"
bash /home/johnclaw/trade-ai-releases/persistent-state/data/coordination/handoffs/agents-20-2/ratify202-operator.sh --pr "$wp15_policy_pr" --sha "$wp15_policy_sha" --apply
gh pr checks "$wp15_policy_pr" --required
```

Ratification accepts only an exact token comment authored by `PatsKiller`, the exact open PR head/branch, a clean worktree and a fresh TTY confirmation. It changes only the header/banner/history activation text and performs the second ordinary branch push. The operator/coordinator merges after exact-head checks pass; agents never merge or release.

Paste back the proposed PR URL/head, the ratification preview's comment ID/time and the required-check results. Never paste keys or tokens other than the nonsecret policy approval phrase.

## Three-stage verification

```bash
PY=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python bash /home/johnclaw/trade-ai-releases/persistent-state/data/coordination/handoffs/agents-20-2/verify202.sh --stage all
```

Each invocation creates unique `none`, `proposed` and `ratified` exports under `/home/johnclaw/.cache/rtc/codex-wp15-20261023/`. Nothing is deleted or overwritten there. The ratified fixture uses a clearly synthetic approval; it is not a production ratification. All policy suites, adapter parity, CI gate registry, state checker, docs index and whitespace checks run against the exports. The verifier performs no remote write, credential read, live endpoint, broker call or service operation.

## Follow-up feature flags

`tier2-flags-after-ratification.patch` is an inert review aid only. Neither application nor ratification scripts apply it. A separate reviewed task/PR must first verify 20.2.0 is actually ACTIVE and merged, then set only `merge_pr_enabled` and `release_now_enabled` true. `approve_item_enabled` remains false. This worker does not open or apply that enabling PR before ratification.

## Recovery

Before the proposal is merged, close its PR and archive its worktree with the original branch and contents retained; do not delete. No runtime flag or service was changed by the package. After a policy merge, withdrawal/reversal is a new operator-reviewed policy change. A failed later feature-flag release uses the existing release rollback procedure; this package never invokes it.
