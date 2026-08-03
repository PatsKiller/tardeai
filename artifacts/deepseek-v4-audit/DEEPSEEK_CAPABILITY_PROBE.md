# DeepSeek capability probe

## Models list (`GET /v1/models`)

| Field | Value |
|-------|--------|
| HTTP | 200 |
| Duration ms | 1445 |
| Key env name | `deepseek_tradeai` (value never logged) |
| Key present (interactive probe) | True |
| Model IDs | `['deepseek-v4-flash', 'deepseek-v4-pro']` |
| has deepseek-v4-flash | True |
| has deepseek-v4-pro | True |
| has deepseek-chat | False |
| has deepseek-reasoner | False |

## Service-runtime key (portfolio-server process)

**FAIL / operator remediation required:** `portfolio_server` process environ has **no** DeepSeek-related env key names.
Rendered Bitwarden tmpfs **does** contain `deepseek_tradeai` for interactive user context.

Remediation (do not perform in this task — no service mutate): ensure portfolio-server.service loads the same env file that provides `DEEPSEEK_API_KEY` or `deepseek_tradeai` (e.g. EnvironmentFile= for rendered tradeai env), then restart is **operator-approved** only (this prompt forbids restart).

## Chat smoke (exact IDs)

- **flash_plain**: ok=True http=200 returned_model=`deepseek-v4-flash` finish=stop err=None ms=2205
- **pro_plain**: ok=True http=200 returned_model=`deepseek-v4-pro` finish=stop err=None ms=1200
- **flash_json**: ok=True http=200 returned_model=`deepseek-v4-flash` finish=stop err=None ms=1192
- **pro_json**: ok=True http=200 returned_model=`deepseek-v4-pro` finish=stop err=None ms=1367
- **legacy_chat**: ok=True http=200 returned_model=`deepseek-v4-flash` finish=stop err=None ms=1061
- **legacy_reasoner**: ok=True http=200 returned_model=`deepseek-v4-flash` finish=stop err=None ms=1507
- **flash_think_high**: ok=True http=200 returned_model=`deepseek-v4-flash` finish=stop err=None ms=1278
- **pro_think_high**: ok=True http=200 returned_model=`deepseek-v4-pro` finish=stop err=None ms=1435

### Critical finding

Legacy IDs `deepseek-chat` and `deepseek-reasoner` still HTTP 200 but return **`deepseek-v4-flash`**, not Pro.
Therefore `llm_lane.py` mapping `deepseek-v4` → `deepseek-reasoner` never invokes V4 Pro.

Exact IDs `deepseek-v4-flash` and `deepseek-v4-pro` return themselves correctly.

## Official docs

See `DEEPSEEK_OFFICIAL_DOC_FACTS.json` (pricing page 2026-08-03).
