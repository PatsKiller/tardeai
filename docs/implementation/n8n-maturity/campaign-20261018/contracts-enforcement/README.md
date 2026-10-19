# Gateway admission and output evidence enforcement

Status: CODE-ONLY candidate; deployment and useful-output acceptance pending  
Owner: Codex campaign integrator; independent reviewer recorded in campaign ledger  
as_of: 2026-10-18  
Measured at: baseline `3af0a8bdd659e02bf6f493c071800c6a227ae292`; original candidates below

Gateway run requests now reject unknown fields, duplicate JSON members at any
depth, nonfinite numbers and unsupported claim version discriminators. HMAC
claims require finite issuance and expiry times. Existing relay and host v1
producer shapes remain accepted. A new optional authority field requires a
reviewed supported-version migration; an old closed reader may reject it.

For live lanes already declaring `output_receipt: v2`, unavailable or missing
output rules fail the run. The shared verdict binds the immutable lane receipt
to the lane, run, attempt, effective mode, full code SHA and executor time window.
Fatal `no_runner` and lock skips cannot become useful output through a positive
count or an empty-work exemption. Explicitly contracted empty work remains valid.
No allowlist entry or live mode is enabled by this change.

Original implementation/review identities:

- Output: `3039c56a048fec1cf32087c3500a62c5450b8099`, then
  `2475379fc0b2b7b4f68300cc1ffa42cddd19d612`. The identical focused
  test pair produced 23 baseline assertion failures and 30 candidate passes;
  independent review found and closed three further code-SHA assertions.
  Author regression: 698 passing cases; independent final focused suite: 125.
- Gateway: `3ef2fb5c07ac84c67be88035ebae0f56b0941c20`. Three identical
  baseline audit assertions now pass; 32 new cases and 296 related gateway,
  relay, durable-ledger, concurrency, due/outcome/intent cases passed.
- Comms fixture integration: `15771d61b3bf124268ae971449eac9b92984fe40`:
  the two direct harness callers now provide the real attempt/effective-mode
  context that the canonical writer receives in production.

These counts describe overlapping suites and are not added together. The new
tests are registered in the existing CIO CI route. The campaign ledger records
the final integrated head, required exact-head CI, review and release identity
before any remote or production mutation.

Limits: count assertions still originate with lane writers; independent artifact,
input/config version and downstream-consumption attestation are not provided by
this patch. Per-window output validation remains with monitors. No claim is made
that a previously unenforced lane is now enforced. The current 48 opted-in lanes
all have output rules and none uses executor-inline retries; inline retry receipt
identity remains a separate migration before such lanes can opt in.

Rollback is the previously accepted exact release through the canonical release
tool, under an applicable release grant. There is no data migration, scheduler
change, external notification or financial effect in this tranche. On release,
verify the exact artifact, gateway/relay/executor state and one appropriate
natural useful-output observation; health endpoints alone do not accept it.
