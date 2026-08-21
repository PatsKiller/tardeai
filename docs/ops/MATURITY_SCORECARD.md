# Maturity scorecard (GET-only)

**Authority:** READ_ONLY_ADVISORY  
**Financial action:** never  
**Mutations:** none  

## Endpoint

`GET /api/v3/maturity/scorecard`

Routed by `scripts/api_v2.py` → `scripts/api_v3_maturity.py` `handle_get("scorecard")`.  
Compute lives in `scripts/lib/maturity_scorecard.py` so tests do not boot the server.

Schema: `MaturityScorecard@v1`.

```json
{
  "ok": true,
  "authority": "READ_ONLY_ADVISORY",
  "financial_action": false,
  "schema": "MaturityScorecard@v1",
  "as_of": "…",
  "dimensions": {
    "<name>": {
      "score": null,
      "status": "MEASURED | UNMEASURED",
      "inputs": {},
      "last_measured_at": null,
      "metric_path": "data/cio/…"
    }
  }
}
```

## Freshness TTL

**7 days.** A dimension whose artifact is missing, empty, or whose `last_measured_at` is older than 7d is `status=UNMEASURED` and `score=null`. Stale numbers are never returned as the score.

## Dimensions

| Name | Artifact | Score when MEASURED |
|------|----------|---------------------|
| `research_skip` | `data/cio/research_skip_ledger.jsonl` (R1) | `SKIP_UNCHANGED` rate |
| `holdings_universe` | `data/cio/holdings_universe_latest.json` | `held_equity_ticker_n` |
| `held_thesis_coverage` | `data/cio/held_thesis_coverage_latest.json` (R3; may be absent → UNMEASURED) | `coverage_pct` / `held_current_pct`; `fresh_pct` null until R3 adds it |
| `decision_payload` | `data/cio/agent_run_traces.jsonl` | count of `DecisionPayload@v1` |
| `memory_influence` | env `MEMORY_BEHAVIOR_INFLUENCE` | reported value (default **0**). This GET **does not set** the env. |

Skip-ledger row shape R1 can append (one JSON object per line):

```json
{"schema":"ResearchSkipLedger@v1","at":"2026-08-21T12:00:00+00:00","code":"SKIP_UNCHANGED","symbol":"SCHD","lane":"deepseek","metered":true,"material":false}
```

Codes: `SKIP_UNCHANGED` · `SKIP_FRESH` · `RESEARCH_EXECUTED` · `RESEARCH_TRIGGERED`.  
Inputs also include `research_executed_rate` and `metered_calls_per_material_change` when computable.

## Local LLM policy (R4)

`scripts/lib/llm_task_policy.py` — local Ollama (gemma/qwen) is **math-only**. Embed is allowed only for already-local `nomic-embed-text`. Judgment/research/prose must not use gemma unless `LLM_ALLOW_LOCAL_JUDGMENT=1` or `RESEARCH_ALLOW_LOCAL_LLM=1`. Live `llm_router` agent tables are already Flash-only; the guard is there so a future `LOCAL_MODEL` change cannot send judgment to gemma.

## Spend snapshot (R4)

`scripts/lib/provider_spend_snapshot.py` writes (opt-in `--write`) `data/cio/provider_spend_latest.json`. Prefers Flash/bridge `data/runtime/provider_cost/events.jsonl`. If the only source is `llm_consumption_log` k-char / stale-Aug-3 estimator (~$12k/14d garbage), `source_quality=UNTRUSTED` and totals are **not** published as truth. No Drive upload.
