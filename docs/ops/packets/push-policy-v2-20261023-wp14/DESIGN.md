# WP-14: rebuilt push-policy-v2 operator package

Status: DRAFT — PROPOSED patch; operator application and ratification required
as_of: 2026-10-24T02:33:00Z
Measured at: base `4acb33ada3eed278c5f7652fcdcd6cbda15e68e5` (main after #2032)

This package replaces the stale 53aa1b619-based delivery. SOURCE_MANIFEST.json preserves
all original file digests and the source path. The original source package remains there.
The protected source files in the worker/canonical worktrees are unchanged: all proposed
edits are carried inside push-policy-v2.patch and tested only in isolated clones.

## Proposed behavior

- `wip`: typed live-claim reason on a proven-draft-PR branch; fast-forward only; one per
  fifteen minutes per branch and 32 per branch per day; excluded from the review budget.
- `review`: typed live-claim reason; 300 estimated runner-minutes per branch and 3000
  per repository over a rolling 24-hour window. The inherited estimate is 75 per full run.
- `operator`: an active scoped guard grant named in the typed reason.
- `train`: exact train ref/reason checks are present. The class **fails closed** with
  `TRAIN_AUTHORITY_UNPROVEN` because this generic hook has no verified host-service
  ReleaseCapability reservation bridge. Environment variables, AUTHORIZED, and a guard
  override do not prove that authority. A separate reviewed service integration is needed
  before the train checkout can use this class. Do not work around this refusal.
- Agents cannot push main, train refs, tags, deletes or rewritten wip history.
- Policy/library loading comes from the hook's own checkout. The append-only local
  ledger records decisions. In enforce, a shared reservation lock serializes the decision,
  preflights and durable append across all worktrees; unreadable state and append failure
  refuse the hook. Refusals consume no ledger budget. A successful pre-push hook reserves
  before upload, so later transport failure remains conservatively charged until operator
  reconciliation. Enforce does not spend the separate v1 counters. No remote publication
  is introduced. Unknown, absent, disabled or failed PR lookup refuses WIP; initial branch
  publication uses review class, then the operator/agent opens a draft.

`Push-Policy-v2: PROPOSED` preserves v1 decisions and logs v2 shadow results. ACTIVE
requires an operator-approved exact-SHA ratification plus AGENTS >=20.0.0 ACTIVE.
WITHDRAWN restores v1 behavior. No source file or policy is activated by this delivery PR.
#2032's draft-CI work is now merged; this packet does not duplicate its workflows.

## Integrity and verification

`BASE_SHA` pins the current main base. apply-push-policy-v2.sh refuses if an operator-owned
file changed relative to that base, or if patch/package digests differ. The package includes
its new test and canonical CI gate. Verification covers no patch, PROPOSED, and a simulated
ratified clone; fixture remotes are local bare repositories, never GitHub. The ratification
script requires the full exact head SHA and a matching approval line by the repository owner.

The operator must have a live claim for protected files if the commit claim gate is active.
A claim refusal remains a refusal; these scripts do not install a claim override.

## Operator steps

From this package directory in its published worker worktree:

```bash
cd /home/johnclaw/wt-codex-wp14-20261023
bash docs/ops/packets/push-policy-v2-20261023-wp14/apply-push-policy-v2.sh
bash docs/ops/packets/push-policy-v2-20261023-wp14/apply-push-policy-v2.sh --apply
```

Default application branch: `ops/push-policy-v2-wp14-20261023`.
Default application worktree: `/home/johnclaw/wt-push-policy-v2-wp14-apply-20261023`.
The script prints the actual next publication commands. It never pushes, opens a PR or merges.
It refuses if those names already exist; any continuation uses the existing work, never a
branch rename to evade a push budget. The protected-file PR is the operator's own act.

After the operator opens the protected-file PR, run `bash
/home/johnclaw/wt-codex-wp14-20261023/docs/ops/packets/push-policy-v2-20261023-wp14/ratify-instructions.sh`.
This read-only helper resolves the actual open PR and exact matching local/remote head, then
prints bound approval and dry-run/apply commands. Those values do not exist before publication,
so no fabricated approval or placeholder ratification command is supplied. Ratification is separate from this package-delivery PR.
The operator merges/releases; the worker never does.

## Train follow-up

The existing release controller and release_capability module already enforce reservation
and revocation at effects. A reviewed bridge must let the hook verify that same bound
reservation/service actor at push time; this packet does not invent a second authority record
or treat a self-asserted environment variable as one. Until that exists, train-class requests
are refused even after policy ratification. The train checkout must keep its current approved
publication path; do not change its hooksPath merely to avoid a refusal.
