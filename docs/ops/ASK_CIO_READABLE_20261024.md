# Ask CIO: readable canonical answers and live completion

Design-Task: DSN-20261024-ask-cio-readable-P1-T1

Worker `codex-ask-cio-readable-20261024`; claim `20261024T221725Z-codex-d3b1b351`.
Accepted base `9228634873392073f5849aaa77ec9b9121eb6094`.

## Contract and source boundary

This frontend package implements quality-request items 4 and 6. Root's backend package owns prose normalization, identity-correct quotes, cents rounding, actual settled spend and bounded CIO-memory contributions. Newly written `AnswerVersion.summary` and POST `answer_text` are canonical plain text, identical to the Telegram mirror. The UI renders the selected string verbatim: it does not strip diagnostics, rewrite Markdown, round embedded numbers or infer merger probabilities/actions.

Both the header and My Questions use one readable body component. Structured `sources` appear in a collapsed **How I know this** disclosure, with source titles/links and observation times. A date-only source keeps date-only precision. Source kinds, internal thread identifiers and a separate provenance dump do not become answer prose. Original reasoning and earlier answer versions remain available.

## Refresh and identity

The header's open answer reads its recorded thread, polling every 5 seconds while that ask is pending and every 30 seconds otherwise. It only replaces the initial canonical POST text with a strictly newer version belonging to the same thread and ask. A different turn's pending state does not relabel the displayed question. Closing/replacing the answer unmounts its request hook.

My Questions retains 30-second list and 15-second thread fallback refresh, accelerating to 5 seconds when their source status is pending. A local completion event refreshes the list and matching open views when the actual fetched version changes. Events are emitted only after successful mutations or observed version changes; they do not invoke research, spend or sends. Source identity and monotonic version tests prevent cross-question cache promotion. A selected thread remounts on navigation, so the previous thread's retained body cannot appear while a new request loads. Failed or unmatched updates remain visible as a gap and never promote another question's text.

## Field lineage

| UI element | Existing API | Canonical field / owner |
|---|---|---|
| Header initial answer | `POST /api/v2/cio/ask` | `answer_text`, backend canonical answer also mirrored to Telegram |
| Header completed answer | `GET /api/v2/cio/asks/{thread_id}` | Matching `turns[].ask_id`, newest `answers[].version` and its `summary` |
| My Questions body / earlier versions | Same thread GET | Actual saved `answers[].summary` |
| Collapsed evidence | POST thread / thread GET | Same answer version's `sources[].title`, `url`, `as_of` |
| List status / updated time | `GET /api/v2/cio/asks` | Source `threads[].status`, `updated_at` |
| Pending / completion labels | POST thread / thread GET | Source status and version, not inferred answer quality |

No new store, provider fetch, business-data writer or backend judgment is introduced here. Historical ledger entries remain immutable; any legacy read-only normalization belongs to the backend package.

## Checkpoint and remaining evidence

Existing Ask model tests and new verbatim-text, identity, monotonic-version, source-clock and event tests pass. TypeScript caught an unsupported newer array method during the first checkpoint; it was replaced with indexing compatible with the repository target. The corrected native checkpoint passes. Hidden-driver source/workflow/registry tests pass (187), both strict real-tree CIO checks pass (2), and all four no-new ratchets pass. These are source-checkpoint results; final validation remains required after fixture-driven integration and source freeze.

The browser harness requires the actual root-generated copied-ledger fixture and fails without it. It will exercise the header and My Questions together, delayed completion without reload, byte-for-byte Telegram equality, source disclosures, closing/unmounting and wrong-thread responses at 1440/412. No sample prose or financial numbers substitute for that final evidence. Final native/hidden-driver/ratchet/CIO/index checks, screenshots and the single publication command are still pending. This package is not ready for `PUSH_NEEDED` at this checkpoint.
