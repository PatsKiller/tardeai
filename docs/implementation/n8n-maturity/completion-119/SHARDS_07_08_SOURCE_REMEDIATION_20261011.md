# Completion tranche: original shards 07–08

Status: SOURCE_ONLY — local source remediation, admission withheld
Owner: Codex completion agent 07–08; integrator owns final acceptance
Date: 2026-10-11
Base: `65337da5366b469c8478b198187201bd37671bc2`
Authority: READ_ONLY_ADVISORY; no model choice or runtime authority change

The 119-lane completion population includes 33 lanes from original shards 07–08: five existing local proposals and 28 previously blocked lanes. This branch integrates only the five owned active entrypoints from the older `257596a90d1d739402a08583defb196a175645d3` train. Its retired rows, operational configuration, shared libraries and other shard changes are excluded. The exact per-lane before/after packet is [candidates-07-08.json](candidates-07-08.json).

## Source corrections

Explicit `--dry-run` is an offline plan before runtime imports or work. Unknown arguments exit 2 even when `--dry-run` is also present. The affected entrypoints cover 21 lane invocations across 18 scripts. Previously existing implicit previews retain their business behavior where present; explicit preview no longer counts a live database or calls a model. Injected counted-preview helpers retain separate regression coverage.

- Five existing proposals now have their strict CLI and existing `LaneRunReceipt@v1` implementations in source: document mentions, evening packet, scope governor, recommendation normalizer and score event feeder. Their configuration candidates remain DRAFT in the separate packet. Governor soft failures exit 1; feeder retains its historical kill-switch exit 0. Both leave their previous successful `ok_at` unchanged.
- Deferred drain preview now returns before queue imports, reclaim, expiry and claim. A batch containing failed calls emits a failed receipt and exits 1. Queue/claim errors retain exit 2 and preserve the previous successful receipt. Its legacy heartbeat resolves lazily against durable state on actual work; clock deferral retains its existing behavior and does not manufacture successful completion.
- Hermes version check records missing version evidence as `not_measured`, exits 1 and preserves its successful receipt timestamp. A successful pip command with no usable version result cannot produce a healthy result.
- Usefulness backfill no longer copies the whole `.env` into the process at import. Its owner names DB variables explicitly on a real run; partial/provider failures during apply emit a failed receipt and exit 1.
- Symbol enrichment parses CLI before provider and pipeline telemetry imports. Owner env loading moves to real work and names only used variables. Provider failures still need typed results and truthful receipts before admission.
- RAG indexer preview neither imports the retired embedder nor opens a database. This does not replace or restore Ollama: real embedding remains blocked pending the operator's supported-runtime choice.
- Topic curation, top20 external intelligence, due-diligence questions, watch-review roles and shell wrappers get an explicit offline boundary. Their existing model, child or egress prerequisites remain visible.
- Hermes update and SLO timer entrypoints get source CLI features only; supported timer-native admission remains a design owned by the integrator.

## Boundaries and remaining work

Operational lane registry, run allowlist and health-contract files remain unchanged. All five proposed contracts retain DRAFT status and their original review metadata; no owner review is fabricated. Legacy schedulers remain authoritative. The candidate rows are source proposals, not shadow fire, canary, CURRENT or deployment evidence.

The other 12 lanes retain their current implementation: financial/price/journal/scorer closures, sender/monitor paths, agent-runtime backends, the shared Hermes pipeline, family runner and reporting inline entrypoint. No broker, stop, order, position-sizing, risk, session, 2FA, model provider, scheduler or live-send authority is changed.

The root-owned shared correction `910fbe0ab` is integrated locally: `session13_db.py` and `pipeline_registry.py` now defer bounded environment loading, and existing registered model identities receive stricter binding. This does not authorize unregistered child routes. Remaining shared prerequisites include exact server-approved process mapping, opaque child/queue closure and receipt outcomes, and timer-native policy design. The two-way curation financial children are unchanged by explicit root instruction. The offpeak worker's live secret-source/containment path also stays owner-blocked; its new explicit preview reaches none of it.

## Validation and rollback

The new `tests/test_completion_119_shards_07_08_20261011.py` exercises actual subprocess CLI previews from a neutral scratch cwd, unknown-flag refusal, fake failures preserving prior successful receipts, and five frozen legacy entrypoints against the same injected business callbacks. No paid calls or production connections are used. Existing ARN, RAG, topic and top20 coverage distinguishes offline CLI from injected data previews. The obsolete usefulness-loop `.env` skip is removed now that its import is safe.

Targeted tests run only through the integrator-supplied pre-import safety launcher. The corrected head `ae36b8c5ca836bccbac237dd05a3c0d533a66ab6` passed 165 targeted tests plus six affected RAG tests, with no refusals and every child reaped. The earlier production-env refusal remains a nonaccepted attempt. Exact commands, counts and guard outcomes are committed in [validation-07-08.json](validation-07-08.json). Updated LIE expectations await the agent04 source integration; full CI-parity acceptance belongs to the assembled train and is never inferred from a shard run. Successful terminal `Failed to create stream fd: Operation not permitted` warnings have exit 0 and are not permission refusals (§1A).

Rollback before integration: omit this local branch. Source rollback after integration uses a reviewed revert; no host rollback is needed because this branch installs or activates nothing. Runtime acceptance remains NOT_MEASURED until separately authorized exact-CURRENT deployment and the required observation window.
