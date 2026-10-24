# WP-23: reconcile Ask-CIO implementation and preserve source provenance

Status: DRAFT source candidate; publication and exact-head CI pending
as_of: 2026-10-24T02:46:00Z
Measured at: main fe826d2ecdb59a19bd7c510c8923c7b743f06eee; task DSN-20261023-handoff-v3-P5-T23

The existing #2011 implementation is preserved through local commit `8b09a5b99`, which already corrected the direct CIO sender, direct memory-silo import and missing route-ledger/classification failures reported by its older published head `c825b8e9e`. This candidate merges current main and unions the build checks, both CSRF routes, schema declarations and documentation entries. It does not reset a push budget or retry a refused push; the operator publishes the requested work branch.

## Contract corrections

- `StreetTarget.mean` carries the actual published analyst mean. The historical `median` field stays readable and is not filled from a mean. Mean-only observations are retained.
- `Scenario.citation` preserves the original anchor with its fact identity, source reference, citation and observation time. Missing anchors remain null. Round trips preserve older payloads with neither new field.
- The default host ask ledger refuses writes until `cio_asks` exists in the granted domains with actual approval evidence. A proposed-domain row is insufficient. Default dependencies disable Ask-CIO before tracking/memory effects while the store awaits approval; isolated tests inject scratch stores.
- Deep spend remains PROPOSED, re-answer mode remains shadow, and the live memory flag is not enabled. No model call, message send, live store write or production API mutation was performed by this worker.

## Verification

The source, fixture API, CC/Telegram correlation, GUID memory, tracking/untrack, cap, re-answer, contract and source-flow suite passed **105 tests**. The hermetic runtime/fixture-immutability harness passed **15 tests** after permitting its isolated local fixture socket. The initial sandbox socket denial is retained. Authority validation reports no blocking findings. The full Command Center build (model checks, TypeScript and Vite) passed using a copied dependency tree whose lockfile exactly matches this worktree. Browser evidence is recorded in the durable scratch directory.

Durable evidence: `/home/johnclaw/.cache/rtc/codex-wp23-20261023/` (`regression.log`, `fixture-harness.log`, `frontend-build.log`, `browser.log`, `api-census.json`, `authority.json`). All HTTP browser testing uses an isolated static fixture server without a production proxy, and every API request is mocked.

## Remaining owner/coordinator actions

- Publish this work branch using its one `PUSH_NEEDED` command, obtain all four required checks on its exact head, and review it as the successor to #2011. Leave #2011 open until the successor is merged. This worker never merges or releases.
- Grant the proposed `cio_asks` store, positions-reader and memory permissions; choose actual Ask/global spend caps and register the LLM process. No relayed or historical general approval is substituted for those decisions.
- #2006's operative research-lane contract still needs its actual owner review; the worker cannot mark it REVIEWED. Its existing CI is not green. No n8n research or re-answer lane was activated here.
- The current census still does not trace the module-level `api_v2.handle -> cio_ask_api.handle` dispatch: `api-census.json` contains no `/api/v2/cio/ask(s)` endpoint. The schema declaration records this analysis gap. Do not label `AskAnswer@v1` independently surface-proven until that dispatch and record edge are traced; browser fixtures prove presentation behavior, not source-census completeness or runtime acceptance.

Production readiness and live acceptance remain **NOT_MEASURED** for this candidate.
