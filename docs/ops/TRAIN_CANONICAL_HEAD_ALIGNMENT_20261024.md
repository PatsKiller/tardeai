# WP-08: align the clean canonical verifier before train preparation

Status: DRAFT — local source and fixture verification; operator publication/merge pending
as_of: 2026-10-24T15:16:16.596632+00:00
Base: `e5fa288ecc6971d1a55a79f7e3ba5bbbb46c5dd0`
Design-Task: DSN-20261024-train-canonical-head-P1-T1

The reported train `rt-20261024-1800-4436fd` merged PR #2069 at `e5fa288ec`, but the canonical verifier checkout remained at `ca39056af`. The controller required those identities to match and stopped with `MERGED_NOT_LIVE / CANONICAL_SOURCE_HEAD_MISMATCH`. These incident observations were supplied with the task; this worker did not inspect or repair live train state.

The controller now aligns a **clean** canonical verifier checkout with the exact merged SHA after its existing exact-main CI check passes and before issuing a new prepare capability. An already aligned clean tree is a NO_OP. A dirty tree refuses before any checkout or new prepare capability. The only production source change is `scripts/lib/release_train_controller.py`; the deployment verifier remains unchanged.

## Order and retained boundaries

1. Run the existing promote boundary and exact-SHA main checks. Existing quarantine, rollback-target and release-checkout-clean checks remain in place.
2. Recheck CURRENT, then inspect canonical `git status --porcelain --untracked-files=all`. A failed status read or dirty tree refuses explicitly.
3. Read and validate the canonical commit identity. Missing/unreadable identity refuses. If already at the merge SHA, record NO_OP without checkout.
4. For a clean stale tree, recheck the existing STOP/control/epoch boundary, recheck cleanliness, record CHECKOUT_STARTED and run only `git checkout --detach <exact merge SHA>` in the configured canonical tree.
5. Recheck cleanliness and the existing strict canonical-head requirement, record ALIGNED, then retain the existing prepare capability, reservation, CURRENT recheck, preparation and verification flow.

There is no force, reset, clean, branch update or fetch in the new operation. It does not accept dirty work, change flags, weaken CI, change capability scope or bypass the deployment verifier. The existing final strict head check remains. The train's release-checkout operation still runs under its existing prepare capability.

Alignment uses valid `promoting` events with payload `step: canonical_source_alignment`, action NO_OP/CHECKOUT_STARTED/ALIGNED/REFUSED, the validated old/target/new commit identities and an optional refusal reason. The same payload is retained in train state. Git output and dirty file names are not copied into errors, events or state; raw stderr can contain sensitive text. Status, checkout and Git exceptions produce clear `CANONICAL_SOURCE_*` refusals with `MERGED_NOT_LIVE`, before any new prepare capability.

## Verification

New tests use a fake prepare issuer that raises at the issuance boundary, fake Git, or an owned temporary Git repository. They never invoke a real train, prepare/promote script, service, network provider, live canonical checkout or real capability issuer. Existing native train tests use only temporary fixture authority keys and state.

The [complete native receipt](packets/train-canonical-head-20261024/native-NON_GREEN.xml.gz) is **NON_GREEN: 382 passed / 7 failed of 389**. It is preserved byte-for-byte using deterministic gzip; [verification.json](packets/train-canonical-head-20261024/verification.json) includes its raw and compressed hashes. Inspect with:

```bash
gzip -cd docs/ops/packets/train-canonical-head-20261024/native-NON_GREEN.xml.gz
```

Six complete modules passed all **320 cases**, including all **16 new alignment cases** and all **122 native controller cases**. [The green subset receipt](packets/train-canonical-head-20261024/controller-core-green.xml) is explicitly derived from that same run and contains only these complete modules: canonical-head, controller, injected-failures, forced-canary, authority and phase-7 prerequisites. It is not a second run or a replacement for the full non-green receipt.

The new cases prove CI→alignment→prepare-issuance order; stale-clean alignment; aligned NO_OP; dirty refusal even at the target SHA; status/checkout/read/exception failures with sanitized output; post-checkout head/cleanliness checks; STOP and CURRENT preservation; actual detach checkout and tracked/untracked work preservation in temporary repositories. Native controller coverage retains its capability, rollback, verification and refusal assertions.

The seven initial environment failures and their targeted reruns are recorded separately:

- Two unchanged checkout/arming fixture cases put their sandbox under the explicit RTC pytest directory while TMPDIR defaulted to `/tmp`; the sandbox location guard refused. Both then passed with the runner TMPDIR set to the owned RTC parent containing the test directory. [Two-case receipt](packets/train-canonical-head-20261024/arm-corrected-2.xml). The guard and assertions are unchanged.
- Five unchanged STOP HTTP cases initially could not create an ephemeral socket in the restricted sandbox (`PermissionError`). Source inspection confirmed temporary tokens/state, stubbed environment/database access and only fixture-owned ephemeral loopback listeners. Formal review accepted the exact fixture test command, and all five passed. [Five-case receipt](packets/train-canonical-head-20261024/stop-reviewed-5.xml). No live `:7777` access, real credentials or production STOP operation occurred.

Latest case coverage is **389/389 passed across the original run and these seven targeted reruns**. This is not a single green native run; the original 382/7 receipt remains unchanged. No production source or test assertion changed between those runs. The independent root worker/reviewer reviewed the bounded source diff and new tests; that is technical review, not operator merge/release authority.

Ruff, host-path and test-coverage ratchets pass, with zero new host-path violations or unlisted tests. All changed/new Python tests ran with psycopg2 hidden. Documentation INDEX, source hashes, whitespace, claim and secrets checks are required before the local delivery commit. Exact-head GitHub checks remain pending publication.

## Operator boundary and remaining proof

This is a protected controller source fix. The operator owns GitHub merge and release; the controller must not merge a change to its own verifier. One publication command will be recorded as PUSH_NEEDED after the local package is complete. No push, merge, release, live canonical checkout, train rerun, grant or real capability was performed by this worker.

After an authorized operator merge/deployment, a new train still needs natural evidence of exact-main CI, clean canonical alignment event, strict head match, prepare/promote capability receipts and final served-release verification. The reported old train is not relabelled successful by this source change. Worker B's separate PR #1997 preparation remains intact on its own branch, waiting for the shared registry ownership boundary.
