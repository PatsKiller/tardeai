# Hermes Bounded Summary Recovery (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T12:15:48-04:00
Measured at: efcc51365 / not measured

## Root cause
After fixing the deterministic-field rejects (hermes_agent_name/research_type @6304065, topic @3707347),
the residual drain rejects were all `MISSING required column: summary` — gemma3 sometimes returns useful
text but not under the exact `summary` key (or as raw text when JSON shape drifts). `summary` is the only
remaining strict-required field that is genuine LLM CONTENT, so it must never be fabricated.

## Implementation (scripts/hermes_output_recovery.py)
`recover_summary_from_output(raw_output, symbol, min_chars=80)` — invoked ONLY when strict validation
fails with exactly `['MISSING required column: summary']`:
- alt keys (priority): summary, trade_summary, reflection_summary, analysis_summary, executive_summary,
  rationale, analysis; then first specific text block in the JSON; then first coherent paragraph from raw
  text (only if JSON parse failed).
- Quality gates (all must hold): >= 80 chars; NOT evasive ("I cannot"/"not enough information"/etc.);
  trade-SPECIFIC = symbol present OR an outcome figure (n%/nR/gain/loss) OR >= 2 distinct trade-context
  terms; not bullets-without-substance. Otherwise stays REJECTED.
- Confidence: high (summary/trade/reflection key) · medium (other alt key) · low (first-block/raw-para).
- Recovered rows record evidence_json.summary_recovery {summary_recovered, recovery_method, source_key,
  recovery_confidence, validator_version, raw_validation_error}. trade_instance_id STILL required.

## Strictness preserved
- Strict path runs first and is unchanged. Recovery triggers ONLY for the missing-summary case.
- All OTHER validation failures remain failures. Empty/generic/evasive/too-short summaries remain rejected
  (no fabrication, no quality-bar lowering). Canonical trade_instance_id linkage is never bypassed.

## Validation — 10/10 PASS (scripts/validate_hermes_summary_recovery.py)
strict recovers high · executive_summary/analysis recover · raw paragraph recovers when specific · generic
rejected · evasive rejected · too-short rejected · generic-no-context rejected · no-text rejected ·
context-only (trade terms) recovers.

## Running driver
The full-drain driver (brpwf0zys) was RUNNING during this change. NOT interrupted; no second driver started.
Each driver iteration is a fresh subprocess, so recovery applies from the NEXT iteration onward. Impact is
measured in the ongoing 10-min drain reports (look for "SUMMARY RECOVERED" lines + reject-rate drop).

## Safety
ALPACA_MODE=paper, live disabled. Research-only (writes hermes_research_intelligence via validated path).
No broker/order/proposal/GO-WAIT/strategy/live/Phase-205 changes; no production learning graft.
