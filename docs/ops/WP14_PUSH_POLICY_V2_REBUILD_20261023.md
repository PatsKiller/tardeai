# WP-14 push-policy-v2 operator package rebuild

Status: DRAFT — local package delivery; operator publication, application and ratification pending
as_of: 2026-10-24T02:36:54Z
Measured at: `origin/main` base `4acb33ada3eed278c5f7652fcdcd6cbda15e68e5` after #2032
Owner: codex-wp14-20261023; board DSN-20261023-handoff-v3-P3-T14

The rebuilt package carries the proposed protected-file changes as reviewable artifacts.
The canonical checkout and worker checkout keep their original policies, hooks and budget
library. No real push, merge, release, ratification, live-server request or credential access
was performed. The delivery branch is `work/DSN-20261023-handoff-v3-P3-T14`.

## Delivered behavior and held authority

The package is `docs/ops/packets/push-policy-v2-20261023-wp14/`. It pins the base and every
artifact digest, preserves the original package digests in SOURCE_MANIFEST.json, and includes
the new regression test with its canonical `config/ci_gates` record inside the patch.
`PROPOSED` keeps the current v1 decision authoritative and records v2 shadow decisions.
Enforcement requires separate exact-head operator ratification and ACTIVE AGENTS >=20.0.0.

WIP requires a live branch claim, proven fast-forward, and a proven draft PR. Unknown,
missing, disabled, malformed or failed PR lookup refuses WIP. Initial branch publication
uses the budgeted review class before opening a draft. Review pushes retain the proposed
300 estimated runner-minute branch and 3000 repository rolling-day caps. A shared lock
covers the enforcing decision, local preflights and durable ledger append across worktrees.
Unreadable state and append failure refuse the hook; rejected requests spend no ledger
budget. Enforce uses the ledger exclusively, without spending a separate v1 counter.

A successful pre-push hook reserves budget before Git's upload. It does not prove the
remote accepted the push; a subsequent transport failure remains conservatively charged
until operator reconciliation. Local refusal is distinct from that later transport outcome.

Train environment values identify only the requested train ref. The existing controller's
ReleaseCapability reservation is not exposed through a verified generic-hook bridge.
The proposed train class therefore refuses with `TRAIN_AUTHORITY_UNPROVEN` even with
AUTHORIZED and a guard override. This package does **not** enable train publication.
The coordinator/operator must separately review that service-reservation bridge before
activating train semantics or changing the train checkout's hook configuration. This is an
explicit authority boundary, rather than an environment-only authorization shortcut.

## Verification evidence

The package's VERIFICATION.json records exact input/output source hashes, proof-stage
results and hashed local evidence paths. Raw logs remain under
`/home/johnclaw/.cache/rtc/codex-wp14-20261023/`; they are not production acceptance receipts.

The baseline passes **255 tests** before the patch. The final PROPOSED and simulated
ratified stages each pass **323 tests**; the focused policy suite passes **68 tests**. The full application and simulated ratified
stages cover the new policy suite plus existing policy, hook, common-directory budget,
guard authorization/scope, CI isolation, claim lifecycle and canonical-gate suites. Negative
wrapper proofs reject short SHA, wrong owner, approval substring and replay of an older
head. Tampered package digests refuse application. Unauthorized hook invocation refuses
at every stage. Ratification testing uses a fake local `gh` executable and local bare
fixture repositories; no real approval was supplied or consumed.

Five simultaneous enforcing review hooks competing for one remaining repository budget
slot yield one durable reservation and four budget refusals. Additional fixtures verify
unknown/API-failed PR refusal, unreadable ledgers, failed durable writes, retained v1/shadow
behavior and spoofed train environment refusal. Initial fixture failures were corrected by
including the claim lifecycle imports in the miniature fixture and invoking that fixture's
legacy hook rather than an unrelated ACTIVE proposal checkout. Assertions remain intact.

Blank unified-patch context lines have their single prefix space removed so the artifact
passes the repository whitespace check. Git accepts that encoding; applied source digests
are checked byte-for-byte against the original candidate source. No whitespace guard or
repository attribute was weakened.

Package patch SHA-256: `cc56c0389c3e1b6e03da80a32cb70dbbf2242fecc3f72552919fc8593d5aa2c2`.
SHA256SUMS SHA-256: `a0829b2567d31b479241380d247bab1e382c74db55516a1530bf748c60638e31`.

## Operator commands

Publish this delivery branch using the one PUSH_NEEDED command in PROGRESS_LOG.md. The
coordinator merges only after required exact-head checks are green. This delivery PR does
not activate the protected policy proposal. After the delivery is available locally, preview:

```bash
cd /home/johnclaw/wt-codex-wp14-20261023
bash docs/ops/packets/push-policy-v2-20261023-wp14/apply-push-policy-v2.sh
```

Then the operator applies into the separate proposal worktree:

```bash
cd /home/johnclaw/wt-codex-wp14-20261023
bash docs/ops/packets/push-policy-v2-20261023-wp14/apply-push-policy-v2.sh --apply
```

Paste the base/main identities, digest verification, stage verification and resulting local
proposal commit. Defaults are branch `ops/push-policy-v2-wp14-20261023` and worktree
`/home/johnclaw/wt-push-policy-v2-wp14-apply-20261023`; existing names cause refusal rather
than overwrite. The script prints publication commands but never executes them.

After the separate protected-file proposal PR exists, resolve its actual identity:

```bash
bash /home/johnclaw/wt-codex-wp14-20261023/docs/ops/packets/push-policy-v2-20261023-wp14/ratify-instructions.sh
```

That read-only helper requires exact local/remote head agreement and prints the real
owner approval phrase plus dry-run/apply commands. Paste its PR number/full SHA and
verification result. No placeholder PR is presented as an approval. Publication, protected
policy approval, merge and rollout remain coordinator/operator actions.
