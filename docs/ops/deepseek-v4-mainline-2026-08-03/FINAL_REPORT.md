# DeepSeek V4 Mainline Integration Report

**Verdict: CONDITIONAL_PASS** (core integration complete; live provider smoke in service runtime and full Playwright route suite not executed here)

## SHAs

| Item | SHA |
|------|-----|
| origin/main base | `ddef4613ec362e6c32307160aba8f4a56b835a20` |
| Branch tip (pre-this-report commits may follow) | see git after final commit |
| Backup before cleanup | `11707968e02908980761bd8f5b61855f078f4326` (`backup/deepseek-v4-mainline-before-cleanup`) |

## Exact models

- `deepseek-v4-flash`
- `deepseek-v4-pro`

## Policies

| Policy | Model | Thinking | Effort |
|--------|-------|----------|--------|
| FAST | deepseek-v4-flash | off | — |
| FAST_THINK | deepseek-v4-flash | on | high |
| PRO | deepseek-v4-pro | off | — |
| PRO_THINK | deepseek-v4-pro | on | high |
| PRO_MAX | deepseek-v4-pro | on | max (operator confirm) |

Ambiguous `deepseek-v4` → **AMBIGUOUS_LEGACY_LANE** (rejected).
Legacy `deepseek-chat` / `deepseek-reasoner` → rejected.

## Key fixes

1. Clean history: no raw audit commits (a167b8b3 / 11707968 removed).
2. Process gate preserves operator_confirmed, response_json, provenance, cost fields.
3. relative_units separated from estimated_cost_usd.
4. Process DB sync + cost caps (process + optional global env).
5. Strict JSON schemas + one repair for named process schemas.
6. Tool-loop helper preserves reasoning_content.
7. Frontend uses deepseek-v4-pro / Flash labels (not V4 R1).

## Tests run

- `pytest tests/test_llm_model_registry.py tests/test_llm_governance_no_override.py tests/test_no_broker_write_bypass.py` → **31 passed**
- `npx tsc --noEmit` → **PASS** (after deepseek_pro fix)
- `npm run build` → **PASS**
- Live service-runtime key on portfolio-server → **not re-probed this run** (prior: FAIL — no DeepSeek env on process)
- Full Playwright V3 subtab suite → **NOT RUN**

## Deployed

**NO** · **Pushed: NO** (awaiting operator approval)
