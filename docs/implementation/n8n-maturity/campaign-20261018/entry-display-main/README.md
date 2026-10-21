# Entry display compatibility on refreshed main

Status: DRAFT
as_of: 2026-10-20T14:04:04.352972+00:00
Measured at: source baseline `720fce06c09ca7e7c21224364ab789505be40f5a`; reviewed campaign source `221967c5559ff1945861cf4d191d207290d48e12`; candidate source/test SHA256 values in `evidence/final-source-parity.json.gz`.

The current packet producer emits `rr_at_ideal_entry` and `rr_at_current_price`. The runner was reading two obsolete keys, then its card could display a plan ratio as the current ratio. The selective correction reads those existing canonical fields and labels both price bases. Missing, malformed and nonfinite values display `unavailable`; supplied zero stays zero. Existing aliases and explicit-null precedence remain supported. No public packet shape, trading eligibility or authority changes.

Agent A's merged shared `entry_alert_context`, planner sender consolidation, gathered company/catalyst/CIO facts and on-record CIO review fallback are preserved. The runner changes exactly two display projection lines. The renderer reuses the exact reviewed221 blob; every other existing renderer definition has equal AST. Existing main entry tests retain their shared-query ownership checks while the two formatting-dependent wake/digest checks reuse221 actual-handler tests and three contained mutation controls. Six pure projection cases preserve upstream review precedence without invoking a sender or store.

The identical three reviewed display test files failed on720 with **28 expected AssertionErrors and7 passing controls**, then passed **35/35** on the candidate. Existing entry/alarm/card-routing plus new review-precedence cases passed **61/61**. Existing fake-effects sender-consolidation cases passed **5/5**;17 unrelated cases were deselected. These101 distinct focused cases are local source checks, not native or operational proof. The existing card suite's hermetic guard refused six live-DSN connection attempts before libpq; no production SQL or financial records were read. Raw logs and XML preserve that fact.

Pinned Ruff0.16.2 lint passed all seven owned code/test paths; format checks passed the renderer and five test paths. The new-main runner's existing byte format is preserved rather than reformatted. The two formatted test files retain identical complete pre/post AST; proof and original bytes are archived. `git diff --check` passed.

All evidence is source-only. Full native acceptance, shared CI test registration, independent integration review, exact-head hosted checks, merge, release and production output verification remain pending. No source under `active_trader`, strategy/runtime configuration, SQL schema, action registry, route, grant, scheduler, workflow, sender behavior or deployment control was changed. No provider, notification, financial or runtime effect was exercised. This work used only the named local source leases; remote or runtime authority was not requested.

`artifact-manifest.json` records deterministic gzip files and both stored and original byte digests. Baseline failed assertions and successful controls are retained unchanged. The older381/5c native failures and their separately reviewed test-contract corrections remain historical; this focused pair is a fresh reproduction against720 and does not relabel old acceptance.
