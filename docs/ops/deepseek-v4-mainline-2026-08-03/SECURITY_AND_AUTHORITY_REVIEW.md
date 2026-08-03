# Security and authority review — DeepSeek V4 mainline

**Base:** `origin/main` = `ddef4613ec362e6c32307160aba8f4a56b835a20`
**Tip:** see FINAL_REPORT final SHA
**Method:** `git diff --name-only origin/main...HEAD` + targeted safety pytest

## Changed files inventory

All files in `origin/main...HEAD` (25 paths) are LLM/UI/docs/tests except design-token baseline:

| Path | Why | Financial authority | Broker write | Orders | 2FA | Risk/stops | Deploy |
|------|-----|---------------------|--------------|--------|-----|------------|--------|
| `config/llm_model_registry.json` | Exact Flash/Pro registry | No | No | No | No | No | No |
| `config/schemas/llm_model_registry.schema.json` | Schema for registry | No | No | No | No | No | No |
| `config/llm_process_registry.json` | Process DeepSeek policies | No | No | No | No | No | No |
| `config/design_token_baseline.json` | UI design-guard freeze for DeepSeek colors | No | No | No | No | No | No |
| `scripts/lib/deepseek_client.py` | Provider client | No | No | No | No | No | No |
| `scripts/lib/llm_model_registry.py` | Policy resolution | No | No | No | No | No | No |
| `scripts/lib/llm_consumption.py` | Cost/gating for LLM calls only | No | No | No | No | No | No |
| `scripts/lib/llm_json_contract.py` | Structured LLM output | No | No | No | No | No | No |
| `scripts/lib/llm_output_schemas.py` | Pydantic schemas | No | No | No | No | No | No |
| `scripts/llm_lane.py` | Lane dispatch (advisory LLM) | No | No | No | No | No | No |
| `scripts/llm_health_check.py` | Health probe labels | No | No | No | No | No | No |
| `scripts/v3_route_maturity_probe.py` | Read-only UI probe | No | No | No | No | No | No |
| `apps/command-center-v3/src/**` (5 files) | Labels/lanes for DeepSeek UI | No | No | No | No | No | No |
| `tests/**` | Unit tests | No | No | No | No | No | No |
| `docs/**` | Reports | No | No | No | No | No | No |

**No files matching broker / order / 2FA / schwab write / kill-switch / deploy / systemd** appear in the branch diff.

## Safety tests run

```text
pytest tests/test_no_broker_write_bypass.py \
       tests/test_llm_governance_no_override.py \
       tests/test_execution_readiness.py \
       tests/test_evidence_bound_approval.py
→ 35 passed  (exit 0)
```

Also DeepSeek suite (provider/json/tool/cost/registry): **86 passed**.

## Verdict

- Broker write ability: **unchanged**
- Order queue/submit/modify/cancel: **unchanged**
- 2FA: **unchanged**
- Risk/stop enforcement: **unchanged**
- Deployment authority: **unchanged**
- LLM remains **advisory only**


## Credential naming (corrected)

- Canonical env / Bitwarden-rendered name: **`deepseek_tradeai`**
- `DEEPSEEK_API_KEY` is optional compatibility only; not required for production wiring.
- No secret values in git, logs, API browser payloads, or systemd Environment= text.
- Service fix: load existing `/run/user/1000/tradeai/env` EnvironmentFile so the process inherits the **name** `deepseek_tradeai`.
