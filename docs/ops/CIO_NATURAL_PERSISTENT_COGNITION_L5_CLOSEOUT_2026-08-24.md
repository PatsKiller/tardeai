# CIO natural persistent cognition L5 closeout

**Date:** 2026-08-24  
**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Status:** SOURCE + TESTED + MERGED (#502 `1afb1479`) + DEPLOYED (`1afb1479-main-exact-phase2-20260824-230917`) + **NATURALLY_PROVEN** (23:17:23–23:17:37 ET material_scan, SCHD).

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

## Natural tick (not `systemctl start`)

`tradeai-cio-material-scan.timer` LastTrigger **2026-08-24 23:17:23 EDT**, finished 23:17:37, WorkingDirectory CURRENT `1afb1479`, authority READ_ONLY_ADVISORY, dry_run/interdicted delivery.

SCHD DecisionPayload@v1:

- `security_guid` `a29dd6b6-9f88-5f8c-a372-f88786851a76`
- TickerResearchState version `2026-08-25T02:26:31+00:00`
- curation `…:v0:BASELINE` version 0
- SymbolThesis `symbol_schd@v9`
- ResearchGap IDs `[]`
- `ContextUseReceipt@v1`
- `portfolio_delta=NO_PORTFOLIO_CHANGE`
- `question=WHAT_MATERIAL_THING_CHANGED_FOR_THE_PORTFOLIO`
- `paid_dispatch=0` · `notification.sent=false` · `financial_action=false`

CASH/REENTRY membership labels correctly skipped (`DATA_UNAVAILABLE` + skipped cognition).

`CIO_PERSISTENT_COGNITION_L5=true`  
`M4_NATURAL_SAME_BRAIN_PROVEN=true` (SCHD refs match Hermes/CIO/Advisory/Telegram diagnostic matrix)
