# Ask CIO: readable canonical answers and live completion

Design-Task: DSN-20261024-ask-cio-readable-P1-T1

Worker `codex-ask-cio-readable-20261024`; claim `20261024T221725Z-codex-d3b1b351`.
Accepted base `9228634873392073f5849aaa77ec9b9121eb6094`; local merge of accepted `d635873e1063efb8a9ff8e8ce542654ed2ef7654` retained both native build test entries. Source snapshot before final fixture/doc packaging: `8c3f714432d43f2fa270dff8386bc8258ddfed0b`.

## Contract and source boundary

This frontend package implements quality-request items 4 and 6. Root's backend package owns prose normalization, identity-correct quotes, cents rounding, actual settled spend and bounded CIO-memory contributions. Newly written `AnswerVersion.summary` and POST `answer_text` are canonical plain text, identical to the Telegram mirror. The UI renders the selected string verbatim: it does not strip diagnostics, rewrite Markdown, round embedded numbers or infer merger probabilities/actions.

Both the header and My Questions use one readable body component. Structured `sources` appear in a collapsed **How I know this** disclosure, with source titles/links and observation times. A date-only source keeps date-only precision. Source kinds, internal thread identifiers and a separate provenance dump do not become answer prose. Original reasoning and earlier answer versions remain available.

## Refresh and identity

The header's open answer reads its recorded thread, polling every 5 seconds while that ask is pending and every 30 seconds otherwise. It only replaces the initial canonical POST text with a strictly newer version belonging to the same thread and ask. A different turn's pending state does not relabel the displayed question. Closing/replacing the answer unmounts its request hook.

My Questions retains 30-second list and 15-second thread fallback refresh, accelerating to 5 seconds when their source status is pending. A local completion event refreshes the list and matching open views when the actual fetched version changes. Events are emitted only after successful mutations or observed version changes; they do not invoke research, spend or sends. Source identity and monotonic version tests prevent cross-question cache promotion. A selected thread remounts on navigation, so the previous thread's retained body cannot appear while a new request loads. Failed, unmatched or regressing updates retain the known newer snapshot with an explicit gap.

The actual copied ledger contains quick answer v1, a status-only pending v2 and the completed partial deep answer v3. A pending status record does not replace the substantive quick reasoning; its exact saved progress sentence appears separately once. The answer advances to the actual deep body when v3 arrives. Earlier substantive versions remain available. Transport retention is component-local memory of the actual backend snapshot, with no new store or business-data writer.

## Field lineage

| UI element | Existing API | Canonical field / owner |
|---|---|---|
| Header initial answer | `POST /api/v2/cio/ask` | `answer_text`, backend canonical answer also mirrored to Telegram |
| Header completed answer | `GET /api/v2/cio/asks/{thread_id}` | Matching `turns[].ask_id`, newest `answers[].version` and its `summary` |
| My Questions body / earlier versions | Same thread GET | Actual saved `answers[].summary` |
| Collapsed evidence | POST thread / thread GET | Same answer version's `sources[].title`, `url`, `as_of` |
| List status / updated time | `GET /api/v2/cio/asks` | Source `threads[].status`, `updated_at` |
| Pending / completion labels | POST thread / thread GET | Source status and version, not inferred answer quality |
| Question / follow-ups | Same thread GET | `title`, `turns[].question`, `turn_kind`, `channel` |
| Confidence / change / original clocks | Same thread GET | Saved `confidence.level`, `what_changed`, `produced_at`, thread creation/update times |
| Named-quantity context | Same answer version | Structured `sizing_context` exposure/reference fields; existing formatting only, no new sizing calculation |
| Tracking chips | Thread GET / tracked GET | Actual entity tracking state; the renderer does not infer a successful canonical Watch write |

No new store, provider fetch, business-data writer or backend judgment is introduced here. Historical ledger entries remain immutable; any legacy read-only normalization belongs to the backend package.

## Verification and deployment boundary

The [copied-ledger rendered question and answers](packets/ask-cio-readable-20261024/rendered-answer.txt) are backend-generated. The committed fixture SHA-256 is `79ded987953caf0dfed186c858c81e3a157cb41e654bd95b51ba28bf06edf29a`. No sampled mockup prose or invented financial figures substitute for it. The captured sources have no current recorded CIO stance, so that gap stays explicit; populated-view/conflict behavior belongs to the backend's separate source tests. Unknown cost is not rendered as zero.

All nine final actual-component browser cases pass at 1440×1100, 412×915 and 390×844. They prove byte-for-byte equality with captured canonical Telegram text, quick reasoning while pending, delayed deep completion and list refresh without reload, collapsed sources, wrong-thread rejection, retention after an older response, and stopped polling after closing/unmounting. Each case makes exactly one explicitly driven synthetic ask POST; there are no provider calls, production sends or additional research submissions. Fourteen healthy screenshots and source/input hashes are recorded in the [browser receipt](packets/ask-cio-readable-20261024/browser-proof.json); the 390 deep header and 412 deep thread were inspected.

On phones, answers and selected threads open as full-screen sheets with focused entry, Back navigation, contained scrolling and restored focus. The primary Ask and Open thread actions are full-width. The list's filter is URL-backed and retained across thread Back/Forward. Each phone's combined case actually taps Ask, the source disclosure, Open thread, Back, filter and a filtered question, then exercises browser Back/Forward. Assertions verify the resulting focused sheet fills its viewport, visible controls have at least 44×44 hit areas, and the page has no horizontal overflow. Loading and wrong-identity failures use the same sheet immediately, without showing another thread's retained body. No shared request hook or backend semantics changed. The all-controls assertion caught and corrected the microphone's previous 34×30 inline minimum.

The native frontend build passes, including house guards, existing/new model checks, TypeScript and Vite. The final hidden-driver source/governance/registry profile passes 195 tests. Both strict source-tree CIO checks and all four no-new ratchets pass; a final completeness run after staging the copied fixture is recorded in the [validation receipt](packets/ask-cio-readable-20261024/validation.json). Workflow artifacts include run attempts and use no job-level runner context. The only native advisory is the existing Vite bundle-size notice.

This frontend depends on the separate backend quality package for new canonical prose, quote identity, actual cost, source-memory behavior and confirmed tracking. It does not normalize historical ledger prose or prove live model execution. The frozen partial answer retains the actual source/refusal boundaries. This is source/fixture acceptance; the coordinator/operator owns merge, joint deployment and the production re-ask.
