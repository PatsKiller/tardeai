# Policy enforcement audit — source proposal, 2026-10-24

No lane, source, model process or live flag was activated. No model was called.
`policy-enforcement-audit` is held pending dedicated process registration, the
operator_decisions source sign-off, measured full-run timing and W8 admission.

## Contract

- Runner: `scripts/policy_enforcement_audit.py`. Default and `--dry-run` return
  before any lock, state creation, model, ledger or receipt write. `--apply` files
  proposals through the single DecisionLedger writer; it cannot record decisions.
- Weekly: Sunday 20:00 America/New_York, `0 20 * * 0`, including non-market days.
  Dedupe identity is the local Sunday-based week AND exact policy document hash.
- Amendment: a distinct completion event names the exact committed policy SHA
  and version. Runner refuses any mismatch. The event emitter belongs to the
  existing governed amendment completion path and is still an integration gap.
  Polling and a weekly execution are not proof that amendment events work.
- Every apply needs executor `TRADEAI_RUN_ID`, `TRADEAI_CODE_SHA` and the usual
  attempt/mode identity. Standard last receipt is
  `data/runtime/policy-enforcement-audit_last.json`; each attempt has its own
  immutable `data/runtime/lane_attempts/policy-enforcement-audit/<run_id>.json`.
- Inner business lock:
  `<persistent-state>/data/runtime/policy_enforcement_audit.lock`. It covers
  weekly, amendment and manual invocations. A busy lock returns 75 with no
  output or ok_at change. W8's outer dispatcher flock uses the distinct
  `policy_enforcement_audit.dispatch.lock`; never reacquire the executor's lock.
  No new lock or temporary data is placed in /tmp.
- Exact argv/env/process/output proposals are in
  `config/proposals/operator_approvals/audit_lane.json` and `audit_process.json`.
  `timeout_s` is deliberately null: no full governed reviewer runtime has been
  measured, so runnable admission remains held instead of inventing a cap.

## What the audit proves

Step 1 reads every document block, maps the reviewed anchors to tests, CI gates
and runtime source files, and reports missing files and unmapped blocks. File
existence proves only existence. Passing tests/runtime checks require an exact
policy source SHA, implementation commit AND document hash receipt at
`data/runtime/policy_enforcement_tests_last.json`; an absent/stale receipt never
earns TESTED or ENFORCED. This runner does not execute arbitrary test commands or
runtime gates from a map. The initial map is partial and reports that gap.

Step 2 is optional `--llm-review`. It requires dedicated registered process
`policy_enforcement_audit`, DeepSeek only, no tools/fallback, ≤6,000 input tokens,
≤1,024 output tokens and ≤$0.05 per day. Each bridge call additionally narrows to
$0.02. Transport timeouts remain the existing governed bridge’s; no unmeasured timeout is introduced. The global cap stays unchanged. Model
registration, cap refusal, mock output or missing governance provenance refuses
the review. The runner never borrows another process or directly calls a model.

Input is a bounded sample of at most eight mapped/sensitive rule blocks and
twelve evidence records. It uses merged local commit metadata and bounded
standard execution-receipt metadata. Raw logs, account IDs, portfolio objects,
credential files and prompts from arbitrary bodies are not loaded. The pure
central egress sanitizer redacts inputs unconditionally before the governed
bridge, including when that bridge's own sanitizer is report-only. Output must
cite actual sampled rule IDs and exact supplied evidence refs; invented refs
are refused. The audit reports sample scope and evidence gaps, never claims a
capped reviewer read every rule or every incident.

Supported findings are AUDIT_FINDINGS proposal events in the canonical decision
ledger, normalized to `status=PROPOSED`, `auto_apply=false`; model-supplied action
fields are discarded. The derived `policy_enforcement_audit_last_report.json`
contains the mechanical map and evidence; the receipt names its actual SHA256.
Retries do not append another event or spend again, and still produce their own
attempt receipt with an honest duplicate/zero-output reason.

## Validation

Pinned-clock isolated tests cover write-free dry-run, unapproved source and
unknown process refusal, exact event identity, stale test evidence, contention,
receipt/attempt output, retry dedupe, redaction/cap routing, mock refusal and
fabricated model citations. All model calls in tests are injected fakes. No test
or agent run spends money, changes a live queue or applies a finding.

The runner also supports packed release trees without `.git`: source identity
is bound to the artifact’s own stamps, policy history to that exact commit, and
blob reads to the explicitly selected canonical repository. Artifact text must
match the committed policy; a checkout moving ahead or an environment override
cannot change the policy being audited.
