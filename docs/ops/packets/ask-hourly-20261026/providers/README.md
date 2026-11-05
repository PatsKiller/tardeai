# Ask hourly provider slice — source handoff

Task: `DSN-20261026-ask-hourly-P1-T2`. Base: `ddc4c1a44`.

This source adds an Opus primary and independent DeepSeek, Grok and ChatGPT critique roles. Each role uses a named server route and records the actual served provider, model, native reservation, request identity, and known cost. A missing or misconfigured role refuses before dispatch; another provider cannot count as that reviewer. An unavailable critic remains visible in partial-answer provenance.

The primary uses `cio_ask_deep_research` with explicit operator intent or the separate automated `cio_ask_reanswer` process with `manual_trigger=False`. The root caller must supply the intent; channel names do not manufacture it. Every paid role forwards a narrowing-only call ceiling to the native bridge. The local question governor admits the sum of role ceilings. The root Ask ledger owns the durable cumulative question/day reservation and the aggregate 30 native request slots/day (four conservatively reserved per panel). No monetary cap is raised.

`registration-proposal.json` is **not applied**. The active registry owner must accept the normal handoff for process, routing, source-authority and n8n process-set changes. Named server task maps are source-wired here; no live process-cap sync, lane activation, scheduler edit or release is performed. Do not declare the complete hourly task finished from this slice alone.

## Core interfaces

- `run_deep_research(ctx, *, manual_trigger=False, process_id=None, memory_apply=False, **test_seams) -> AskAnswer`. The core passes `True` only for genuine operator entry; scheduled work passes `False` and `cio_ask_reanswer`. Legacy injected `deep_provider(ctx)` remains the core owner's compatibility seam.
- `collect_current_evidence(request, *, sources=None, db_query=None, now=None, state_root=None, thread_id=None, ...)` returns `request`, `binding`, resolved `entities` (`Entity` objects), `facts` (`Fact` objects), `gaps`, `source_runs`, and `fingerprint`. It invokes neither panel nor memory. Governed sources may perform their normal reads/searches; this is not a zero-side-effect promise for a paid search adapter.
- Pass the complete in-memory collector result as `prepared_evidence=` to research. Its binding checks normalized question, thread, and resolved entity identities; a parent's old ask ID may become a generated `auto:<childid>` ask ID without repeating search.
- Every answer carries `provenance.evidence_fingerprint`, `cost_usage_known`, `cost_receipt`, `native_request_count`, and `native_request_count_known`. `AskAnswer.cost_usd` is the sum of observed known actuals, including known zero. Unknown billable outcomes retain their hold in the root ledger; the partial known sum must not release that hold. Missing native evidence similarly retains four request slots.
- `retry_research_memory(answer_or_payload, *, apply=False)` replays facts only through the same `MemoryAppender` and dedup ledger, without source/model calls. Missing or invalid replay data returns `pending/not_measured`. Approved apply returns affirmative `ok` only when every fact was acknowledged or already recorded. The root separately owns the Spine summary write and delivery/retry state.

`provenance.memory_retry_payload` contains all entity/fact dictionaries, including local-only facts, and the request ID. It is canonical local replay data. `research_context_for_model` removes this entire key recursively, and model prompts still filter out local-only facts. No retry payload belongs in external model context.

Memory receipts distinguish `planned_count` and `applied_count`; compatibility `appended` means applied. Dry runs never increment applied counts or dedup ledgers. Apply requires an affirmative `ok`/`accepted` acknowledgement, or the canonical integrator's committed memory-version receipt. A bare dictionary or a `None` return is not an acknowledgement.

## Search evidence

The web adapter remains list-compatible while preserving router `ok`, `reason`, `provider`, `cache_hit`, reservation and receipt. Successful empty runs are `no_data`; disabled/refused runs keep their explicit reason. Fingerprints ignore cache receipts, successful routing-decision changes and retrieval-only clock changes, while retaining sourced content/time and failure transitions.

## Verification and limits

Tests use the canonical venv, `TMPDIR=~/.cache/agent-tmp/ask-hourly`, the no-Postgres shim, `TRADE_AI_CI=1`, and the repository's hermetic guards. The fixed-loopback bridge client is injected in tests; no live provider, DB, credential, broker, sender or host API is used. The research lane's transitive capability test must remain green. The bridge source retains CRLF; local whitespace checks use `core.whitespace=cr-at-eol`.

Formatting the changed bridge/shared-map files follows the required pinned Ruff gate; resulting reflow preserves behavior. Native integration still requires the held configuration handoff, reviewed release/cap-sync, and separately authorized runtime verification. The existing memory dedup ledger is the retry checkpoint; this slice does not claim a distributed transaction between the memory database and that file.
