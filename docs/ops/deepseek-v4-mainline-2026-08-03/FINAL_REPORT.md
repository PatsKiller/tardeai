# DeepSeek V4 Mainline Integration Report

**Verdict: CONDITIONAL_PASS_DO_NOT_PUSH**

## SHAs

| Item | Value |
|------|--------|
| Branch | `fix/deepseek-v4-routing-mainline` |
| Worktree | `/home/johnclaw/tradeai-wt-deepseek-v4-mainline` |
| origin/main base | `ddef4613ec362e6c32307160aba8f4a56b835a20` |
| Final code SHA | `6ac955f0911c3af43a67db5d6211afea9414c78e`
| Prior checkpoint | `6e7070cae536988f4157333111b385490a7b395f` (ancestor) |
| Backup pre-cleanup | `11707968e02908980761bd8f5b61855f078f4326` |

## Exact models

- `deepseek-v4-flash`
- `deepseek-v4-pro`

## Policies

| Policy | Model | Thinking | Effort | Confirm |
|--------|-------|----------|--------|---------|
| FAST | deepseek-v4-flash | disabled | — | no |
| FAST_THINK | deepseek-v4-flash | enabled | high | no |
| PRO | deepseek-v4-pro | disabled | — | no |
| PRO_THINK | deepseek-v4-pro | enabled | high | no |
| PRO_MAX | deepseek-v4-pro | enabled | max | **yes** |

Ambiguous `deepseek-v4` / legacy chat/reasoner: **rejected**.

## Test summary (see TEST_RESULTS.json)

| Suite | Result |
|-------|--------|
| Mocked provider matrix + JSON + tool + cost + registry + no-broker | **86 passed** |
| Safety (no-broker, governance, execution readiness, evidence-bound) | **35 passed** |
| Live Flash/Pro interactive smoke (6 cases) | **6/6 pass** (not service runtime) |
| Frontend tsc | **PASS** |
| Frontend build | **PASS** |
| V3 route maturity vs live :7777 | **14/20 pass** — FAIL reasons: deploy API 500s, health React #310; SPA is release tree not this branch |
| Service-runtime DeepSeek env names on portfolio-server | **BLOCKED / ABSENT** |

## Deployed / pushed / restart

**NO / NO / NO**

## Residual blockers for PASS_FOR_DRAFT_PR

1. Operator wire DeepSeek env into portfolio-server + approved restart + service-context probe.
2. V3 route suite against a server serving **this branch** SPA (or fix live API 500s) to reach 20/20 with URL+heading+active-tab.
3. Optional full backend pytest suite beyond targeted sets.
