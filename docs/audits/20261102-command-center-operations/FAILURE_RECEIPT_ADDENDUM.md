# Receipt remediation addendum — 2026-11-02

**Local source fixes are committed, unpushed and undeployed. Production recovery and lane admission are not established.** The immutable 18:45:27Z failure inventory and original report remain unchanged.

## Prospect shadow attempt binding

Commit: 07376f6557b106af0d937980214a038f9f3b7acb.
Files: scripts/cio_prospect_shadow_build.py; tests/test_cio_prospect_attempt_receipt_20261102.py; config/ci_gates/cio_prospect_attempt_receipt_20261102.json.

[CODE] The existing canary success branch writes the same shadow and comparison artifacts, hashes their actual bytes, and calls the existing shared write_lane_receipt writer at the same registered last-receipt path. The writer produces its normal immutable LaneRunReceipt@v2 attempt under its existing run/attempt/mode/code identity. Four legacy mutable fields are retained additively; the immutable attempt carries them in summary. Its success clock now records receipt completion. No new store, schema, DB connection, financial judgment, reader authority or scheduled invocation was introduced.

[CODE] A pre-existing attempt is refused before replacing its artifacts. A count inconsistent with the actual prospect list, artifact-write failure or shared-receipt failure cannot return exit zero. Empty input preserves the previous good shadow and mutable receipt, as before; it does not create a successful current attempt. The existing dry-run path never reaches the artifact or receipt writer. Optional company-facts behavior is unchanged.

[VERIFIED] New synthetic test runs:
- Initial suite: 12 passed in 1.47s.
- Added writer-failure/count-integrity cases: 2 passed, 12 deselected in 1.28s.
- Mandatory existing broker-free import/capability regression: 7 passed in 1.83s.
- Ruff and git diff whitespace checks passed.

The real output verifier accepts the actual immutable attempt and rejects wrong lane/run/attempt/code/mode/time. Tests compare each receipt hash with the real temporary artifact bytes and show that a duplicate attempt leaves all artifact bytes unchanged. Inputs, company-facts call and DB boundary are stubbed; no production state or paid provider was reached.

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
