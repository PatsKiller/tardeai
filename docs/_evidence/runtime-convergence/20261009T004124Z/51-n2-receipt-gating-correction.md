# N2 predecessor proof and bounded polling correction

Status: FIX_NOW_SOURCE; runtime activation and cutover NOT ACCEPTED.
Owner: platform.
as_of: 2026-10-09T12:36:00Z.
Evidence classes: SOURCE_ONLY implementation; TEST_ONLY fixtures. Actual N2 workflow activation and natural dependency proof are NOT_MEASURED.

The current main introduced receipt gating that checked only RUN_DONE and a completion calendar day. It accepted shadow, nonzero-exit, future-dated and mismatched-lane evidence. Its retry counter counted the latest Wait node's output items, so a one-item loop could remain at attempt two indefinitely. The relay omitted exit_code, making the necessary completion proof unavailable to the workflow.

The additive relay projection now retains lane, mode, requested_at, finished_at, state and exit_code; only the display run_id may be removed to fit the bounded body. Oversized proof refuses rather than dropping required fields. The endpoint remains authenticated and read-only: no gateway request or spawn, credential copy, ledger write, or authority change.

Generated gates require matching projection and lane identities, live mode, RUN_DONE, numeric exit 0, timezone-aware request/completion instants, and request <= completion <= now. The request anchors the business-day dependency. An overnight predecessor belongs to the previous America/New_York day and may finish after midnight on the current day. No fixed lane/date exception was added. Missing, stale, shadow, failed, skipped-lock, reversed, naive or future evidence fails closed. The node run index bounds polling to five total checks and four waits; the fifth unsatisfied check throws. Both shadow and live child templates require actual live predecessor proof.

The eight existing pending N2 workflow files and generated INDEX were regenerated through the existing generator. They remain inactive and were not imported into n8n. The allowlist, process/model/provider policies, secrets, host senders, broker/order/stop/risk/2FA authority and policy ratification were unchanged. Source deployment of this endpoint is separate from N2 activation, which remains blocked by N1 acceptance and the documented readiness gaps.

[Prior negatives](51-n2-negative-prior.log): 19 failures, six passing cases. [Focused final](51-n2-focused-final.log): 25 passing cases. The [first broader attempt](51-n2-pre-regeneration-attempt.log) failed only because generated files were stale; it is preserved as failed. After regeneration, the [complete template/relay suite](51-n2-regression-final.log) passed 70 tests. An independent Node harness passed [48 contracts](51-n2-independent-js.json), including DST transitions, overnight completion, live/shadow, missing proof, state/exit contradictions, realistic one-item retries, fifth-check success, and missing/invalid counters. These are fixture checks, not natural n8n acceptance.

The retry correction follows the distinction between the latest node output items and the current node run index documented by [n8n's built-in node access](https://docs.n8n.io/code/builtin/output-other-nodes/) and [workflow metadata](https://docs.n8n.io/code/builtin/n8n-metadata/). Live loop behavior still requires natural inactive-to-shadow acceptance before any eventual cutover.

The [fresh morning observation](57-current-after-approval-wait.json) measured main/CURRENT and all four core process roots at ea90bd8807f6e258a013e9f5fd7e6d989e090e89, with 437 cron jobs and 1,047 raw lines. The overnight approval wait did not grant runtime authority. A [fresh exclusive coordination lease](57-fresh-coordination-lease.json) replaced expired coordination ownership through the native coordinator; it likewise grants no runtime authority. The [isolated four-lane N1 rollback rehearsal](56-n1-independent-rollback-rehearsal.json) passed without host mutations or grant consumption.
