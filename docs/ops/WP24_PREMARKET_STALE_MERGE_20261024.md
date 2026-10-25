# WP-24: current-main successor of the verified content port

Design-Task: DSN-20261024-wp24-port-P2-T1

This successor refreshes verified backup `93fbbd87c79b7a7f4e3f3f6519d0d51dee7b7529` onto accepted
`origin/main` `23e87f15b1e973f4520cedb28c5998036374c55e`. The original worktree, branch and backup remain
preserved. Neither the stale #1997 head nor archival `f352121a` is merged into this successor.

The source worktree is `/home/johnclaw/wt-codex-wp24-carryforward-20261024`, branch
`work/DSN-20261024-wp24-port-P2-T1`, session `codex-wp24-carryforward-20261024`, claim
`20261025T001504Z-codex-3996d67d`. Its 29-path claim excludes both metadata files held by other owners.
W8 supplies the exact two `pending_change` objects in owner-authored commit `bb1671027`, and W3 supplies
the three additive derived/history copy declarations in owner-authored commit `c8248bca7`. Their isolated
metadata chain was accepted on `d635873e1`. Main then advanced to `23e87f15b` with only a shared INDEX
overlap. The chain rebased without conflicts as `38223d83d` (W8, parent accepted main) and `d4b3832e4`
(W3, parent W8), retaining both authors and byte-identical metadata files. Registry ownership stays with
W8; this worker performs no registry edit or conflict resolution and authors neither metadata delta.
Their provenance and exact integration heads are recorded in the final verification receipt.

The combined change is limited to the original 31 real port paths. Current main's `cio_asks` authority
and dictionary changes are retained, and INDEX is regenerated from the combined tree. Executable source,
configuration and tests retain the verified port behavior: canonical source-proof readiness and vetoes,
observational SHADOW focus, SHADOW premarket sender/cadence/unified modes and the existing RTH SEND block.
The registry's operative schedules, commands, locks, dispatch blocks, all other rows and top-level pending
disk proposal remain as accepted main; the inherited crontab packet stays an unapplied operator proposal.

Final qualification is bound to the successor's exact head in
`/home/johnclaw/.cache/rtc/codex-wp24-carryforward-20261024/verification.json`: the inherited 295-case
fixture profile with psycopg2 hidden (including both strict real-tree completeness cases), nine read-only
checks, affected ratchets, the frontend build and both strict CIO cases. The coordinator stopped a broader
extra selected CIO sweep; its partial results and limitations are retained separately, without a full-CI
green claim. Historical receipts below do not establish qualification of this new head. No provider,
model, broker, order, stop, credential, live
server, scheduler or activation call is part of this refresh. Captured-input reconciliation is CHECK/dry-run
only. Source readiness, publication, hosted exact-head CI and runtime acceptance remain separate claims.

Only after the required local checks pass is one successor `PUSH_NEEDED` logged. The operator/coordinator
publishes the new branch, closes #1997 after its successor merges and then lands #1991 on top. This worker
never pushes, opens a PR, merges or releases.

## Historical verified content port — original worktree preserved

Design-Task: DSN-20261024-wp24-port-P1-T1

This source delivery follows the coordinator's 2026-10-24 ruling: **do not merge or publish the stale #1997
head or local `f352`**. Instead, port only the 31 real changed paths onto a fresh current-main worktree as one
normal commit. This current section supersedes the historical preflight and continuation instructions below.

## Current port provenance and ownership

| Input | Exact identity |
| --- | --- |
| Original content-diff baseline | `e5fa288ecc6971d1a55a79f7e3ba5bbbb46c5dd0` |
| Current accepted-main parent, including batch 20 | `e30b04418f4d2210a0c5e2cae6014717cfe5fdde` |
| Archival content tree, never publication ancestry | `f352121a056aa5933a8479c9c438edb3aed64098` |
| Stale #1997 head, not merged | `d23a2440a2b9eb71bb7b70adeedd78af0e02b09c` |
| New branch | `work/DSN-20261024-wp24-port-P1-T1` |
| New worktree | `/home/johnclaw/wt-codex-wp24-port-20261024` |
| Session / exact 31-path claim | `codex-wp24-port-20261024` / `20261024T191558Z-codex-28ab654f` |

Batch-20 PR #2070 was still OPEN at the first base read and merged during port preparation. The original owner
normally released the source claim and linked this follow-up task before editing. The follow-up then claimed
exactly the 31 paths whose content differs between the original baseline and the archival tree. A binary patch
applied cleanly; initially all 31 files matched that tree byte for byte. The uncommitted branch then fast-forwarded
to accepted main `e30b04418`; the only overlap was INDEX, which is regenerated to preserve both sets of rows.
No `MERGE_HEAD` was created. Only this report, implementation/packet status and promotion wording, and generated
INDEX are refreshed after the transfer; executable source, configuration and tests retain the reviewed content.

The guard correctly considered both sides of the earlier non-main merge: 872 paths, 844 identical to main.
The old shell sequence incorrectly continued after its refusal and created `f352` through the normal hook.
That execution error, exact output and frozen tree remain recorded in the original `BLOCKED_HANDOFF.md` under
`/home/johnclaw/.cache/rtc/codex-stale-premarket-20261024/`. Functional tests do not erase the refusal. The new
coordinator-authorized content port uses a fresh normal commit with accepted main as its only parent.

## Current behavior and verification boundary

The source preserves main's canonical readiness, primary-publication catalyst requirements, same-session evidence
and vetoes alongside the one-minute evidence block. New premarket sender, cadence, focus and unified modes are
**SHADOW**; fresh focus observations record proposed exclusions without filtering research. Existing RTH SEND is
preserved. The registry adds only two `pending_change` operator proposals; operative schedules, commands, locks,
dispatch and rollout stages remain unchanged. There is no new operative allowlist or contract admission.

The inherited crontab packet is an **unapplied historical operator proposal**, not native n8n scheduling. Its
fake-crontab fixture does not read or modify the host. No live provider, LLM, broker, order, stop, credential,
scheduler, workflow-activation or Command Center operation is part of this source port. The historical grant in
the implementation document is not a current grant.

After the normal commit, the required final profile reruns the same 295 fixture cases with psycopg2 hidden,
including both strict real-tree completeness cases, plus nine read-only checks: health contracts, lane registry,
captured-input reconciliation, data-source authority, host paths, coverage, INDEX, whitespace and Ruff.
Command, exit-code, JUnit, configuration-hash and commit/ancestry receipts are recorded in
`/home/johnclaw/.cache/rtc/codex-wp24-port-20261024/verification.json` and linked in the progress log and PR body.
That final exact-head receipt supplies measured results; this document does not invent them before the commit.

Reconciliation is CHECK only, with the explicitly pinned historical snapshot
`docs/implementation/n8n-maturity/data/scheduler_snapshot_20261009.json` and `--dry-run`; no fresh host discovery,
`crontab -l`, n8n connection or `--write`. Configuration hashes must remain unchanged. The original packet's
131/235/57-case receipts and the archival tree's 295-case receipt stay historical and cannot substitute for this
new commit's required rerun. Runtime, natural-schedule, consumer and notification acceptance remain NOT_MEASURED.

Once the new commit's checks pass, log one `PUSH_NEEDED` for this new branch and retain its task/claim. Publication,
exact-head CI, Active Trader merge and release belong to the operator/coordinator. The coordinator closes #1997
as superseded only after the port merges. Neither the old branch nor `f352` is published.

## Historical preflight — not current status or continuation authority

The following original preflight is retained for audit. Its blocked merge route and instructions to resume that
merge are superseded by the content-port ruling above. Original task: `DSN-20261024-stale-premarket-set-P1-T1`.

Status: BLOCKED — unique source preparation tested; exact original-head merge and final verification remain pending
as_of: 2026-10-24T14:41:27.571811+00:00
Design-Task: DSN-20261024-stale-premarket-set-P1-T1

The exact PR #1997 head can be rebuilt only after its full source scope is claimed. The shared `config/lane_registry.json` claim was refused because Worker A holds it. No Git merge, registry edit, host inspection, provider call, alert delivery, push or deployment was attempted. Under the accepted unique-source claim, a 16-path patch excluding the registry and generated INDEX now prepares the source while the common claim remains blocked. The original head is not yet incorporated in ancestry; publication is not ready.

## Pinned inputs and ownership

| Input | Exact identity |
|---|---|
| Main at task start | `ca39056af0b67491310a7267d75e2a0c882bc7d0` |
| Original #1997 head | `d23a2440a2b9eb71bb7b70adeedd78af0e02b09c` |
| Original implementation commit | `81c5a89ff` |
| Merge base | `53aa1b619c9bac6cf8715d3f64b03d1ca0b5ab9a` |
| Worktree | `/home/johnclaw/wt-codex-stale-premarket-set-20261024` |
| Branch | `work/DSN-20261024-stale-premarket-set-P1-T1` |
| Worker B unique-source claim | `20261024T142242Z-codex-039731d5`, session `codex-stale-premarket-20261024` |
| Shared registry holder | Worker A claim `20261024T142155Z-codex-7d52b03c`, session `codex-stale-n8n-set-20261024`, branch `work/DSN-20261024-stale-n8n-set-P1-T1` |

The exact 18-path incoming delta, parent file hashes and read-only merge-tree digest are in [incoming-scope.json](packets/premarket-stale-merge-20261024/incoming-scope.json). The only textual conflict markers are in `scripts/lib/momentum_setup_evidence.py` and `scripts/lib/unified_momentum_alert.py`; automatic unions elsewhere still need semantic verification.

An initial malformed claim-extension command added the claim ID itself as an unused literal path to this worker's own claim. It acquired no registry scope. The corrected request explicitly refused `config/lane_registry.json`; that refusal is honored. The board was not hand-edited to remove history or change ownership.

## Required merge preservation

- Preserve main's `SetupReadiness@v1`, primary-publication catalyst requirements, same-session evidence, vetoes and scanner/Active Trader adapters. Add the incoming `MomentumEvidenceBlock@v1` without replacing those functions or presenting a second contradictory readiness verdict. When both blocks exist, canonical readiness remains authoritative and book/tape facts must be clearly qualified.
- Preserve original one-minute closed-candle timing, six-second settle, overrun/no-overlap guards, lock/kill-file checks, state-change deduplication, correction exceptions, reopen cooldown, bounded messages and single fallback on failed threaded delivery.
- Preserve main's Hermes generic/index-page rejection while adding the focus observation hook. Missing/stale focus must leave research candidates unchanged; fresh SHADOW focus must also leave them unchanged and report only the proposed exclusions.
- Preserve main's operative scheduler/state/command/lock/dispatch blocks. Original #1997 adds only `pending_change` operator-packet proposals to `active-trader-premarket-watch` and `finviz-momentum-scalp-early-lane`. Those proposals must survive the merge without becoming operative commands. Premarket dispatch remains OFF; no new operative allowlist or contract is admitted.
- Keep the original #1997 crontab packet as an unapplied operator proposal. The worker never runs it against a host. Captured-file fixture preview/apply tests do not establish current scheduler state or authority.

## Explicit SHADOW direction

Main currently configures `active_trader_premarket.mode: send`. The user's latest instruction, “Everything stays shadow,” supersedes retaining that sender in the candidate. The requested candidate must contain:

```yaml
active_trader_premarket:
  mode: shadow
  cadence_mode: shadow
scalp_focus:
  mode: shadow
unified_momentum_alert:
  mode: shadow
```

This would change premarket delivery from SEND to journal-only **after operator publication and deployment**. The current runtime is unchanged by this worker. Existing RTH `active_trader_alerts.mode: send` remains intact. Keep explicit future live code paths and their guards; promotion remains a separate operator decision.

The original focus implementation has no mode guard and filters research with `critique_gate: focus`, including when cadence is SHADOW. A proposed scratch candidate adds a SHADOW default and `would_drop` diagnostics. [The pinned fixture](packets/premarket-stale-merge-20261024/premarket-merge-fixture.json) and [provisional result](packets/premarket-stale-merge-20261024/focus-draft-proof.json) distinguish that proposal from the current source. Its exact inert draft is [scalp_focus_candidate.py.txt](packets/premarket-stale-merge-20261024/scalp_focus_candidate.py.txt); it has not been installed or integrated.

## Claimed unique-source preparation

The two conflict modules now retain main's complete readiness/catalyst/veto functions and the incoming evidence
block, optional event fields and message caps. Readiness-only and block-only consumers preserve their formats;
when both exist, source readiness is authoritative and additional observations are labelled Live facts/drivers.
A block alone never verifies a headline. The premarket adapter forwards its source evidence and vetoes.

The candidate premarket sender, cadence, unified mode and new focus mode are SHADOW. Fresh SHADOW focus keeps
all research candidates, reports proposed exclusions separately, and the actual Hermes execution fixture proves
that behavior. The original real-clock focus test is now pinned; the old window/config test expects the explicitly
requested SHADOW sender while preserving all schedule-boundary assertions. RTH SEND is asserted unchanged.

[Unique-source verification](packets/premarket-stale-merge-20261024/unique-source-verification.json) binds the
source hashes, untouched registry digest and separate test receipts. The common registry-dependent test is
explicitly deferred, not weakened or removed. No final Git merge or end-to-end acceptance is claimed.

## Verification actually performed

| Population | Result | Limit |
|---|---|---|
| Pristine-main evidence/readiness/unified-alert/Hermes-filter tests | **131 passed**, psycopg2 hidden | Baseline only; [JUnit receipt](packets/premarket-stale-merge-20261024/baseline.xml) |
| Scratch focus proposal | **4 assertions passed**: fresh shadow unchanged with proposed exclusions; explicit live fixture filters; stale live unchanged; unknown mode defaults SHADOW | Provisional standalone draft, not integrated source acceptance |
| Unique-source preparation | **235 passed, 1 explicitly deferred** with psycopg2 hidden; [receipt](packets/premarket-stale-merge-20261024/unique-source-235.xml) | Includes 18 new merge/SHADOW negative cases, original cadence and retained main/legacy regressions; common registry case still pending |
| CI-gate/authority regressions | **57 passed** with psycopg2 hidden; [receipt](packets/premarket-stale-merge-20261024/unique-source-guards-57.xml) | Static authority zero findings, 27 proposed-domain warnings retained; no baseline changes |
| Local Git integration | **NOT RUN — claim refused** | No merge state or conflict resolution exists yet |
| Final integrated focused/negative tests, lane/contract gates and CHECK-only reconciliation | **NOT RUN** | Must run after legitimate shared claim and exact local merge |
| Unique-source lint/host/coverage ratchets | Passed; zero new host violations or unlisted tests | Must rerun on the final integrated head |
| Final integrated INDEX, exact-head CI | **NOT MEASURED for the final implementation** | No completed implementation or PR is asserted |
| Natural session, n8n, consumer readback and alert delivery | **NOT MEASURED** | No live access or scheduler changes |

The 131-test baseline ran `test_momentum_setup_evidence_20261012.py`, `test_setup_readiness_20261023.py`, `test_unified_momentum_alert_gate4_20261022.py` and `test_hermes_momentum_source_filter_20261023.py` with `PYTHONPATH=/home/johnclaw/.cache/rtc/nopg` and an owned scratch test directory. [Premerge verification](packets/premarket-stale-merge-20261024/premerge-verification.json) binds the receipt to the pinned inputs. These counts are separate populations and must not be added as an integrated acceptance total.

## Exact continuation

1. Wait for Worker A's accepted integration and legitimate shared-claim release. Ownership transfer to another worker is still a held claim. Do not retry or work around the recorded refusal without that state change.
2. Extend the **existing** Worker B claim with `config/lane_registry.json`, and recheck the complete incoming scope. Reuse this branch/worktree and preflight, without rebasing, force-pushing or renaming the branch.
3. Perform the exact original-head local Git merge, preserve both sides and apply the explicit SHADOW direction. Keep operator-packet rows inert. A classifier refusal stops the affected action; Active Trader publication/merge remains operator-owned.
4. Run all incoming and current-main regressions plus meaningful merge tests. Pin every fixture clock, including the original research-focus test's real-clock input. Prove even an injected legacy-send configuration yields zero **new** threaded sends under cadence SHADOW and zero focus filtering under focus SHADOW.
5. Run mandatory nopg, lane/contract checks, data-source checks, host-path/coverage `--fail-on-new`, documentation INDEX and whitespace/secrets/claim checks. Reconciliation is CHECK/dry-run only against a pinned captured input; never `--write`, live discovery or a host census.
6. Commit and log exactly one `PUSH_NEEDED` only when the rebuilt implementation passes its required local checks. The operator publishes it, observes exact-head CI and owns Active Trader merge/release. No publication command is emitted for this incomplete preflight.
