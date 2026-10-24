# WP-23: governed Ask-CIO process registration

Design-Task: `DSN-20261024-cio-ask-process-P1-T1`

Source work on accepted main `9228634873392073f5849aaa77ec9b9121eb6094`.
This package fixes the missing `cio_ask_deep_research` registration. It does not
run a model, synchronize the live database, restart a bridge, enable a lane,
change the global budget, or establish live answer quality.

The existing APPROVED cost section of `config/cio_ask.json` records the
operator's October 24 authority: $0.50 per question and $5 per day, inside
`LLM_GLOBAL_DAILY_USD_CAP`. This package uses those values without changing
that configuration or inventing a new approval. A stricter global limit can
still refuse Ask-CIO before its process allowance is exhausted.

| Boundary | Source behavior |
| --- | --- |
| Process | One new `cio_ask_deep_research` row, manual default, advisory only, no tools. All existing rows are preserved. |
| Standard task | `advisory_desk` / `cio_ask_deep_research`: existing `n8n_oauth_first` route, Grok OAuth → ChatGPT OAuth → DeepSeek FAST. |
| Depth task | `advisory_desk` / `cio_ask_deep_research_depth`: same process and budget bucket; server mapping selects the existing reasoning lane, DeepSeek PRO_THINK, with declared OAuth fallback. |
| Client overrides | Arbitrary body model/provider/policy/tier cannot select the execution policy. The existing handler ignores them; arbitrary process injection remains refused. Only the declared server task selects depth. |
| Per-call ceiling | Routing policy refuses projected cost above $0.50 before reservation. This is not an answer-wide cap. |
| Per-question cap | The Ask caller must enforce the existing cumulative $0.50 budget across actual panel/retry/depth work. Actual settled-cost booking is a separate quality-fix package. |
| Process/day and global | Existing real cap checker, reservation and settlement paths remain unchanged. Process cap $5/day; actual global cap remains independent and unchanged. |
| Count | Thirty requests per day: a restrictive engineering bound from three existing panel members × ten full $0.50 budget slots. This is not measured demand or a promise of ten answers. Free OAuth calls still use count slots. |
| Sync | Optional `--process-id` narrows the existing script to one declared process. No-argument behavior remains a full sync. Unknown IDs refuse before database import. New Ask rows start manual; conflict updates preserve existing modes. |

The fixed route can serve the same provider on multiple calls. A result must
name its actual provider; repeated Grok answers are not three independent
model voices. The root quality-fix worker owns caller intent, cumulative
question budget, actual settled spend, factual identity, answer rendering and
spine contribution changes. Event re-answer remains shadow in the unchanged
Ask configuration.

Validation is source/fixture only. New tests exercise the actual bridge route
and actual process/global cap checker with injected transports, pricing and
ledger persistence. They also drive the real HTTP handler using in-memory
streams, proving that body overrides cannot select depth. The exact client
helper is verified with a fake `urlopen`, never a live bridge call. Optional
`context_id` forwards a real retrieved context header, or inherits the existing
current context; it never manufactures an ID. The async caller must open/inherit
a genuine context, preferably passing its ID explicitly across that boundary.
Missing context remains subject to Ring2, and unsafe/unavailable context fails
before transport. Monotonic
route clocks are pinned by the existing hermetic fixture; cap totals and
request counts are explicit fixture inputs.

Current receipts, the initial mock-socket sandbox failure, its separately
reviewed fixture proof, and any unrelated baseline failures are retained in
[the source packet](packets/cio-ask-process-20261024/README.md). No scoped pass
is called whole-project CI. Merge, source cap synchronization, bridge restart,
deployment and operator re-ask belong to the coordinator/operator.

Initial source-checkpoint validation: **21 new source tests pass**, including selected sync,
server depth and real process/global cap refusals. Ten source guards pass;
configuration hashes are unchanged during CHECK. Supplemental receipts retain
the older bridge fixture's initial socket failure and separately reviewed pass,
and the unrelated unchanged registry-mode assertion failure (4 passes/1 failure
in its whole file). No assertion or unrelated process was altered. This is
source readiness with an explicit baseline finding, not whole-project or live
acceptance.

The context follow-up passes **72 tests**, containing all **28 new registration/
context cases** plus the complete existing model-job/model-job-operation/label
files. The two complete environment/executor files pass **214 tests** after the
new context-reader import. These runs overlap earlier receipts and are not
added into a misleading total. All ten source guards pass again, compilation
passes, and CHECK changes no configuration bytes. No live admission is claimed.
