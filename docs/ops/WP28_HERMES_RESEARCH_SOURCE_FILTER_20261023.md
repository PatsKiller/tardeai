# WP-28 item 2: Hermes research article selection

Status: DRAFT — implemented and verified locally; PR CI and release pending
as_of: 2026-10-24T03:12:50Z
Measured at: base `325ff34f2b3b272090b78d5210a2847c8c30bd2a`; session `codex-wp28-research-20261023`; task `DSN-20261023-handoff-v3-P6-T282`

Hermes previously counted section/index pages among its first three search results and selected the first result's title as its catalyst summary. The existing downstream identity validator rejected such a record later, even when an actual article appeared behind those pages in the search response.

The researcher now uses the existing pure `generic_index_page` validator before the per-path source cap and again before accumulating sources for first-headline selection. The hot-tier routed path, standard search-router path and direct SearXNG response processing share this filter. An article behind rejected listings can fill an existing source slot; provider/source-policy order among retained results stays intact.

## Contract preserved

- Source-policy filtering still runs before final article selection.
- Route choice, caller/intent/priority, request class, provider query, request limits, cache TTL, timeouts and the existing three-query ceiling are unchanged.
- Source dictionaries keep their provenance fields; hot-route metadata remains attached. Duplicate URLs and error rows keep their existing treatment.
- Classification and confidence formulas remain the same. Source count/confidence now count retained sources; these values are heuristic source-count scores, not calibrated factual probabilities.
- Company/ticker identity and approval are still enforced by the downstream validator. An article about another company remains UNVERIFIED_IDENTITY; this change does not declare every retained article verified or tradeable.
- Advisory/no-execution output fields, store/merge behavior, contracts and rollout state are unchanged.

This implements only WP-28 item 2. Prior-close reference, float authority, universe date scope and duplicate-run policy remain separate operator decisions. No source-of-truth ruling or trading permission was made here.

## Verification

The new test file `tests/test_hermes_momentum_source_filter_20261023.py` has a canonical CI gate. Its **18 synthetic tests** cover generic titles, homepage/section/tag/series URLs, retained order and fields, error rows, all three result paths, article-after-cap regression, route arguments, source policy, duplicate URLs, no-clear-catalyst output, pinned clocks and the unchanged downstream company-identity refusal. Search/model/secret/DB work is stubbed or blocked; no real provider request was made.

A broader existing regression bundle passed **99 tests**, but its hermetic guard reported **four attempted live-DSN connections via `scripts/db_adapter.py:194`, refused before libpq**. No database connection occurred. The affected broad bundle was not repeated or weakened. That existing isolation finding remains a follow-up; the new synthetic module passes independently without those attempts. The clean final scope, the new module plus CI-registry checks, passed **43 tests** with no live-DSN diagnostic.

The source change is 24 lines: an import, a shared selection helper and filtering before existing caps/selection. The existing validator/matcher is reused unchanged. No live lane was run, no `.env` loaded, no alert sent, and no workflow/contract review or activation status changed.

## Coordinator follow-up

Publish the local branch through its PUSH_NEEDED command, watch exact-head required checks, then let the coordinator merge/release. After an authorized release, compare a natural research record's source list, headline and downstream identity verdict. Local fixture success does not prove live publication or business-output freshness.

Investigate the broad-suite DSN attempts with isolated imports/fake adapters before running that bundle again; retain its production-access guard.
