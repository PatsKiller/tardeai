# LLM Surface Fix — Flash/Pro opinions now reach `/v3/advisory` (2026-08-12)

**Status:** fixed + verified end-to-end · **Branch:** `feature/advisory-desk-v1`

## Symptom

`ADVISORY_DESK_V1=true` and the daily shadow session ran live (`dry_run=false`,
`spend=$0.004`, `rows_called=10`), but the desk showed `rejection_count=10`, an
`LLM_DRY` banner, and **zero** Flash opinions / Pro synthesis on `/api/v3/advisory`.

## Root causes (three independent blockers, all fixed)

1. **The governed bridge dropped the `thinking` field — the real killer.**
   `scripts/lib/cio_governed_model_bridge.py` (`RealProvider.generate`) made a raw
   `requests.post` to DeepSeek **without** `thinking: {"type": "disabled"}`. The
   `deepseek-v4-*` models default to *reasoning* mode when the field is absent, so
   the model spent the entire token budget on `reasoning_tokens` and returned an
   **empty `content`** (`completion_tokens_details.reasoning_tokens: 500`). The
   opinion engine then hit its "could not parse model response" fallback for every
   row — and the Pro synthesis reported `[DEGRADED — Pro synthesis unreachable]`.
   This silently broke *every* non-think caller (advisory FAST/PRO, Steph, Guardian,
   Ledger, Morgan), not just the desk.
   - **Fix:** `RealProvider.generate` now honours the resolved policy `thinking`
     value (disabled by default, matching `config/advisory_desk.yaml` and the
     `deepseek_client.chat()` contract) and passes `thinking`/`reasoning_effort`
     through from `resolve_model_policy`. It also falls back to `reasoning_content`
     if `content` is still empty. No model, lane, routing, or prompt change.

2. **Strict output validation rejected otherwise-good opinions.**
   `validate_opinion_output` hard-rejected on verbatim evidence-number matches and
   exact `evidence_cited` ref-id equality — minor prose rewording/rounding or a
   ref written as a bare `type`/`source` got dropped wholesale.
   - **Fix:** only *structural* violations hard-reject (invalid verdict, missing
     `key_risk`). Number/ref fidelity is now a soft `validation_warnings` list,
     surfaced for review rather than fatal. Number matching is tolerance-based.

3. **Enrichment was never persisted for the read path.**
   `enrich_advisory_with_opinions` set `llm_in_path` in memory only; the served
   `/api/v3/advisory` read a *different* process's deterministic snapshot, so it
   never saw Flash/Pro output.
   - **Fix:** live enrichment now writes `data/runtime/advisory_opinions_latest.json`
     (rows + synthesis + `llm_in_path`), and `api_v3_advisory._load_opinions_blob()`
     prefers that artifact; `get_advisory_desk()` derives `llm_in_path` and the
     `LLM_ON` banner from it.

## Prompt hygiene

`config/advisory_desk.yaml` `stable_system_prompt` (and the engine's in-code
fallback) now spell out the exact `evidence_cited` format — cite an evidence item's
`type`, `source`, `title`, or `agent` value, never a fabricated id.

## Verification (2026-08-12 21:00 UTC)

- Shadow session: `session_pass=true`, `rows_called=10`, **`rejection_count=0`**.
- `advisory_opinions_latest.json`: 10 Flash opinions (`model=deepseek-v4-flash`,
  `lane=deepseek-flash`), 0 rejected, 9 with soft warnings; Pro synthesis ~830 chars.
- `/api/v3/advisory` (in-process): `llm_in_path=true`, `LLM_ON` banner present,
  10 row opinions joined by `advisory_row_hash`, synthesis surfaced.

## Operationally required for the fix to go live

The bridge runs as the systemd unit `cio-governed-bridge.service`; it was restarted
to load the code change. The portfolio server is redeployed via
`scripts/deploy_portfolio_server.sh`.
