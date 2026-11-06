# Receipt remediation addendum — 2026-11-02

**Local source fixes are committed, unpushed and undeployed. Production recovery and lane admission are not established.** The immutable 18:45:27Z failure inventory and original report remain unchanged.

## Prospect shadow attempt binding — original claim refuted, repair in review

Original source:07376f6557b106af0d937980214a038f9f3b7acb.
Current local repair:322ae6735fab996ecbfd02defc43fe1092f05228, pending two independent exact-head reviews.
Neither source is deployed.

[DOC-CLAIM — REFUTED] The original author asserted that duplicate/count/writer-failure handling
could never replace good artifacts or return success without immutable proof. Independent review
disproved that universal claim. Invalid count validation happened after replacing shared artifacts.
A real normalized run-ID filename collision introduced after the initial check made the shared
O_EXCL writer refuse its attempt, yet the producer returned0 using its mutable last receipt.

[VERIFIED — REPORTED INDEPENDENT PROBE] The reviewer reproduced the actual shared writer collision
with raw IDs fixture:prospect:attempt and fixture_prospect_attempt. The competing immutable record
remained, the producer exited0, and the real verifier returned receipt_identity_mismatch.
The earlier author tests passed but did not cover this path. Prior passing fixtures are not evidence
that the refuted property held.

[CODE] Repair322ae6735 validates the actual list/count before either shared artifact is replaced.
Complete execution identity is required before a write. After the unchanged shared writer returns,
the producer reads the actual immutable attempt, applies the configured real output verifier and
compares identity/mode/code/time/exit/count/summary/evidence plus both current artifact hashes before
success. Missing or mismatched proof raises failure; competing immutable bytes are not overwritten.

[DOC-CLAIM — AUTHOR VALIDATION]34synthetic cases and7broker-free regressions pass, including the
reviewer's real collision. The two independent reviewers are replaying those proofs. Their final
new-head verdicts, publication, deployment and actual scheduled output remain pending.

No collector/main, broker, shared-writer authority, schedule or financial behavior changed.
The original07376BLOCK remains historical evidence, not silently promoted to MERGE.

## Conflict comparison output proof

Commit: bed851780efb52efb6a7868ae468887923fea9ed.
Files: scripts/conflict_resolver.py; config/n8n_health_contracts.json; tests/test_conflict_output_receipt_20261102.py; config/ci_gates/conflict_output_receipt_20261102.json.

[CODE] Only the non-broker _run receipt/report seam changed. The output contract requires one completed ConflictResolverReceipt@v1 comparison report. Both attempted and produced counters use report units; subjects evaluated are separate. Zero subjects or zero findings can still produce a useful comparison report with an explicit empty-input flag, input-manifest digest, before/after comparison and no notifications. Zero output is not an allowed success.

[CODE] An explicit report run ID that disagrees with the executor's run ID is refused in _run before report/ledger effects. The existing report uses exclusive file creation and a run-ID-derived path; the receipt records its actual file hash, schema, relative reference and input-manifest digest through the existing shared immutable attempt writer. If no report file exists, hashing fails before a successful attempt receipt is written. The early identity refusal applies at _run; the outer wrapper may already have acquired its existing lock.

[VERIFIED] Thirteen new synthetic _run cases passed in 1.48s under the final guard. The guard refuses protected broker, positions, transport and collector modules, including import aliases/from-list targets. Collector and CLI entrypoints are tripwires. Five existing pure runner cases passed in 1.14s under a process-wide protected-import guard. Fake memory writers and disposable roots were used; no live collector, DB, model or broker path ran.

[VERIFIED] The real verifier accepts a fresh identity-bound report attempt, rejects absent output and stale/wrong identity, and rejects produced_count zero even if a no-subject reason is supplied. A deliberately dropped report cannot create a successful attempt. Dry-run cannot reach a file or receipt writer. Existing collector and main source sections are byte-identical to the committed parent.

[VERIFIED] The structural health-contract gate returned errors=[] for 165 contracts / 140 targets. It retained 153 inherited warnings. Ruff and git diff whitespace checks passed; new test files unlisted by CI: 0.

## Governance and limitations

OI-135 remains OPEN: the conflict collector's transitive broker capability is still a separate governance blocker. No collector, main, attachment producer, capability baseline, scheduler, allowlist, registry or admission logic was changed, tested against a broker, waived or declared safe/live. The source change repairs receipt proof; it does not authorize the lane's protected closure.

The generic output verifier validates immutable receipt identity, code, time, mode and counters; it does not independently reopen artifact files. The producer boundary and synthetic failure tests establish that the claimed report/shadow bytes existed before its successful receipt was emitted. These tests establish source behavior, not runtime recovery.

Next: independent exact-commit review; lead-owned draft publication, CI and governed release; observe the served diagnostics and new naturally scheduled attempt receipts. Bind CC-OUTPUT-ATTEMPT-MISSING and CC-OUTPUT-RULE-MISSING to these concrete source fixes and actual PR/ticket receipts. Keep all protected execution/admission investigation blocked until its scoped governance requirement is satisfied.
