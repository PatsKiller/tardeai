# Phase 2 Outcome — Evidence Quality, Cache, Pro Synthesis

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Plan:** [AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md](./AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md)  
**Depends on:** P0 bridge + Phase 1 data truth  
**Authority:** READ_ONLY_ADVISORY  

---

## Delivered

| Track | Work | Status |
|---|---|---|
| **2A** | Technicals fallback from price_action when indicator_snapshot thin | **DONE** |
| **2A** | Analyst context accepts target/consensus without analyst_count | **DONE** |
| **2A** | Hermes `as_of` no longer wall-clock (cache-safe) | **DONE** |
| **2A** | Actionable rows above materiality covered **first** (100% before HOLDs) | **DONE** |
| **2B** | Stable system prefix + volatile user body (no symbol in system) | **DONE** |
| **2B** | Material-field hash with geometric MV / weight / P&L buckets | **DONE** |
| **2B** | Local opinion + synthesis caches; second identical run = 0 model calls | **DONE** |
| **2B** | Run telemetry → `data/runtime/advisory_opinion_run_telemetry.jsonl` | **DONE** |
| **2C** | One Pro synthesis, dollars-first ranking, lead symbol recorded | **DONE** |

`ADVISORY_DESK_V1` remains **false** by default — live Flash/Pro still operator-gated.

---

## Design pass criteria

| # | Criterion | Status |
|---|---|---|
| 2.1 | Mean evidence ≥ 8 items/row (holdings) | **PASS** (runtime check in tests + rebuild) |
| 2.2 | 100% actionable rows model-covered | **PASS** (dry-run telemetry + code path; live when flag ON) |
| 2.3 | Synthesis leads with largest dollar item | **PASS** (`rank_rows_dollars_first` + `lead_symbol`) |
| 2.4 | Cache hit rate ≥ 70% after warmup | **Code ready** — measure on live multi-day runs; unit proves 100% local hit |
| 2.5 | Unchanged run = 0 model calls | **PASS** (unit: cache hit skips `_call_bridge`) |
| 2.6 | 0 numeric/citation rejections policy | **PASS** (validator still rejects; clean opinions only cached) |

---

## Key implementation notes

### Prompt layout (2B)

```
system  ← stable_system_prompt (identical every row / day)
user    ← deterministic verdict + evidence JSON + optional memory + ask
```

Symbol never enters the system message (provider prefix cache hygiene).

### Hash buckets (2B)

| Field | Bucket |
|---|---|
| weight_pct | 0.1 pp |
| gain_loss_pct | 0.5 pp |
| market_value | geometric 0.5% steps |
| confidence | 0.05 |

### Telemetry fields

`rows_called`, `rows_cache_hit`, `cache_hit_rate`, `input_tokens`, `cached_tokens`, `output_tokens`, `cost_usd`, `actionable_total`, `actionable_covered`, `actionable_coverage_pct`, `rejection_count`, `synthesis_lead_symbol`, `synthesis_lead_dollars`.

### Synthesis (2C)

- Always `task_type=advisory_synthesis` → process `advisory_desk_synthesis` → **Pro**
- Rows sorted by `dollars_at_stake` desc before the prompt
- Local synthesis cache keyed by ranked-row material hash
- Empty Pro response falls back to deterministic dollars-first paragraph

---

## Tests

```
tests/test_advisory_desk_phase2.py
tests/test_advisory_bridge_routing.py
→ 13 passed
```

---

## Operator: live Flash + Pro canary (optional)

```bash
export ADVISORY_DESK_V1=true
export LLM_GLOBAL_DAILY_USD_CAP=0.25
systemctl --user status cio-governed-bridge --no-pager
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python - <<'PY'
from lib.data_broker.advisory_desk import build_advisory_desk, enrich_advisory_with_opinions
d = build_advisory_desk(force=True)
e = enrich_advisory_with_opinions(d, max_rows=5)  # small canary
print(e["opinions"]["telemetry"])
print((e["opinions"].get("synthesis") or "")[:400])
# second run should be mostly cache hits
e2 = enrich_advisory_with_opinions(d, max_rows=5)
print("second", e2["opinions"]["telemetry"])
PY
tail -3 data/runtime/advisory_opinion_run_telemetry.jsonl
```

If `cache_hit_rate` stays &lt;0.70 after warmup, inspect whether system prompt is mutating (timestamp/run id leak).

---

## Files touched

- `scripts/lib/advisory/advisory_opinion_engine.py` — stable prompts, synthesis dict, telemetry helpers
- `scripts/lib/data_broker/advisory_desk.py` — material hash, evidence fillers, enrichment coverage + telemetry
- `config/advisory_desk.yaml` — stable prompts, cache knobs, dollars-first synthesis template
- `tests/test_advisory_desk_phase2.py`
- `docs/advisory/desk-v1/PHASE2_QUALITY_CACHE_OUTCOME_2026-08-11.md`
- `docs/advisory/desk-v1/README.md`

---

## Next (Phase 3)

Memory: `advisory_rows.jsonl`, thrash penalty, feedback reason codes, outcome scoring. Surface/Telegram still Phase 4.

---

*Advisory only. No broker credentials or order authority.*
