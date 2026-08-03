# DeepSeek V4 Mainline Integration Report

**Verdict: CONDITIONAL_PASS**

## SHAs (exact)

| Item | Value |
|------|--------|
| Branch | `fix/deepseek-v4-routing-mainline` |
| Worktree | `/home/johnclaw/tradeai-wt-deepseek-v4-mainline` |
| origin/main base | `ddef4613ec362e6c32307160aba8f4a56b835a20` |
| Final code SHA | `a6868431fba802a201f67b8e519e10fcbfa76974` |
| Backup pre-cleanup | `11707968e02908980761bd8f5b61855f078f4326` (`backup/deepseek-v4-mainline-before-cleanup`) |

## Exact models

- Flash: `deepseek-v4-flash`
- Pro: `deepseek-v4-pro`

## Policies

| Policy | Model | Thinking | Effort | Confirm |
|--------|-------|----------|--------|---------|
| FAST | deepseek-v4-flash | disabled | — | no |
| FAST_THINK | deepseek-v4-flash | enabled | high | no |
| PRO | deepseek-v4-pro | disabled | — | no |
| PRO_THINK | deepseek-v4-pro | enabled | high | no |
| PRO_MAX | deepseek-v4-pro | enabled | max | **yes** |

- Ambiguous `deepseek-v4` → **AMBIGUOUS_LEGACY_LANE** (rejected, never available)
- Legacy `deepseek-chat` / `deepseek-reasoner` → rejected as model IDs

## Tests executed

| Command | Result |
|---------|--------|
| `pytest tests/test_llm_model_registry.py tests/test_llm_governance_no_override.py tests/test_no_broker_write_bypass.py` | **31 passed** |
| `npx tsc -p tsconfig.json --noEmit` | **PASS** (0 errors after deepseek_pro fix) |
| `npm run build` (design guard + chip scope + tsc + vite) | **PASS** |
| Live provider smoke (this worktree run) | **NOT RUN** |
| portfolio-server DeepSeek env names | **FAIL historically** (process lacks deepseek_* keys; see SERVICE_RUNTIME_OPERATOR_STEPS.md) |
| Full Playwright V3 route/subtab suite | **NOT RUN** (static inventory only: 71 route hits in /tmp) |

## Deployed / pushed

**DEPLOYED: NO** · **PUSHED: NO** (await operator approval)

## Residual risks

1. Service runtime must receive `DEEPSEEK_API_KEY` / legacy `deepseek_tradeai` via systemd EnvironmentFile before production DeepSeek works.
2. Full process-schema suite coverage beyond four named schemas is partial.
3. Full V3 URL+heading+active-tab screenshot maturity suite not executed.
4. Rebase/merge to main still requires PR review; origin/main diverged history was rebuilt cleanly from ddef4613.
