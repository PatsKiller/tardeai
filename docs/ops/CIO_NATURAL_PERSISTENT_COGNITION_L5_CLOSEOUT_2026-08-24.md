# CIO natural persistent cognition L5 closeout

**Date:** 2026-08-24  
**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Status:** SOURCE + TESTED. Natural L5 is awarded only after scheduled material_scan on exact-main.

## Root cause

Natural CIO path:

`tradeai-cio-material-scan.timer` → `scripts/cio_material_scan.py --live` → `scan_office` → `_instrument_scan` → `emit_payloads_for_decisions` → `DecisionPayload@v1` on `agent_run_traces.jsonl`.

`cio_run_worker` and Telegram converse already resolved `cio_persistent_cognition`. **material_scan did not.** Wake dict carried `selected_decision_ids` but **no symbols**, so envelope extract missed tickers. `payload_from_material_decision` built DecisionPayload with `symbol` + financial `current_action` only.

That is why live SCHD traces showed `DATA_CONFLICT` with `notification.sent=false` and **zero** TickerResearchState / `security_guid` / curation versions.

## Fix (this PR)

- `enrich_payload_with_cognition` attaches **bounded refs** (`CIOCognitionRefs@v1`), not the brain blob.
- Live-resolves canonical JSONL at emit time (stale serialized packs are not trusted).
- Persists `ContextUseReceipt@v1` to `data/cio/context_use_receipts.jsonl`.
- material_scan wake now includes `symbols` from selected decisions.
- Does **not** overwrite financial-lane `current_action` (TRIM / DATA_CONFLICT). Cognition answer is `portfolio_delta` / `question`.
- No new store. No LLM. No production SQL.

## Tests

`tests/test_r10_8_cio_l5.py`: payload refs, stale re-resolve, NO_PORTFOLIO_CHANGE replay, material delta, NEED_DATA, CONFLICTED, PRSO not fabricated, same-brain, membership skip.

## Not claimed until natural tick

`CIO_PERSISTENT_COGNITION_L5` and `M4_NATURAL_SAME_BRAIN_PROVEN` remain false until a genuine `tradeai-cio-material-scan.timer` fire on the deployed SHA shows refs in the DecisionPayload trace.
