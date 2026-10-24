# WP-13: isolate canonical Watch quote tests

Status: Implemented and tested locally; publication pending
as_of: 2026-10-24
Design-Task: DSN-20261024-watch-quote-test-isolation-P1-T1
Source base: 9a5027eb0716b70624d0fc11abc9f3103c3676e4

Two inherited tests blocked supplementary Watch verification: the quote-coherence case called the real database adapter, and the provenance case searched the old WatchHub prop-wiring location. This change corrects those two tests only, plus their CI registration and documentation. It changes no production module, renderer, price selection, broker/order/stop behavior, provider call, guard or runtime state.

## Fixture database boundary

`TestLiveCoherenceIdentity.test_live_symbols_have_coherent_identity` retains its historical node name. It now installs an entire fixture `db_adapter` module in `sys.modules` **before** calling the actual `batch_canonical_quotes` reader. Its fixture connection/cursor has no database implementation. The cursor allows exactly two SELECT calls, verifies the expected source tables and exact requested/fallback symbol parameters, and supplies only synthetic rows. No driver, credential, environment file or production state is read.

A fixed `2026-08-04T17:00:00-04:00` observation clock and six symbols exercise dictionary/tuple result adaptation, a market-quote winner, an enrichment winner, equal-time enrichment precedence, a stored-quote fallback, missing winning identity and missing observation time. Four available outputs have explicit expected price, change, source, quote/record ID, observation time, session and freshness; unavailable outputs must retain their typed missing reasons. This prevents an empty/missing result from satisfying the old loop vacuously.

Every original identity/coherence assertion remains: timestamps/IDs/session/freshness, market-quote integer identity, enrichment string identity and absence of losing market-quote identity. The original live test was not rerun before correction. Installing the stub is the boundary; there is no hidden-driver exception or live-read fallback.

## Actual renderer reachability

The current WatchHub renders `WatchIntelligenceUnified`, so its old direct WatchCard prop assertions were stale. `WatchCardV2` is rendered by `WatchLegacy`, reachable through `App.tsx`'s `/watch-legacy` route and `WatchLegacyGate`. The gate still requires the existing legacy query/local-storage opt-in and redirects otherwise.

The test retains all ten component provenance attribute/prop assertions and moves the three old wiring assertions to the actual `<WatchCardV2 ... />` block in WatchLegacy. It also checks session/state/source props and the actual App import, route and gate render/redirect/opt-in path. This verifies a reachable production renderer rather than treating an unused file as proof. It does not claim that the gated legacy view is the primary Watch page or that a live browser was exercised.

## Verification

**67 focused tests pass with psycopg2 hidden**: the revised canonical Watch quote file, related pure quote-selection contracts and CI-gate registry checks. The new gate registers the existing test file through canonical `ci_gates.make_record`/`render`; no test is removed, skipped or denied. Exact observation, source/ID and fail-closed checks are preserved and strengthened.

```bash
PYTHONPATH=/home/johnclaw/.cache/rtc/nopg \
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python -m pytest -q \
  tests/test_watch_canonical_quote.py tests/test_quote_selection_contract.py \
  tests/test_ci_gates_registry_20261021.py
```

The exact supplementary regression profile requested after the two failures also passes: **146 tests in86.42seconds**, with psycopg2 hidden, across `test_watch_canonical_quote.py`, `test_data_source_authority_20260913.py` and `test_ci_draft_pr_skip_20261023.py`. This is a result on the corrected test branch, not Watch integration or production acceptance.

Host-path and test-coverage `--fail-on-new` ratchets both pass with zero new violations. Generated docs index and whitespace checks pass. Effective hidden-driver refusal was separately verified as `ModuleNotFoundError.name == "psycopg2"`. Local receipts are retained under `/home/johnclaw/.cache/rtc/codex-watch-quote-isolation-20261024/`. The coordinator/operator owns publication and subsequent exact-head checks, merge and release. Source-test success does not establish a new production quote observation or deployment.
