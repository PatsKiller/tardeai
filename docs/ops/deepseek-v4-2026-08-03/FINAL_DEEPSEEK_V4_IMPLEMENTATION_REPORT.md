# FINAL — DeepSeek V4 routing and site maturity

## Verdict

**CONDITIONAL_FAIL** — core provider/registry/fail-closed routing implemented and unit-tested; service-runtime key wiring, full JSON process schemas, cost gate enforcement, frontend policy de-duplication, and full `/v3` route/tab screenshot proof remain open.

## SHAs

| Item | Value |
|------|--------|
| Worktree | `/home/johnclaw/tradeai-wt-deepseek-v4-routing` |
| Branch | `fix/deepseek-v4-routing` |
| Start (safe base) | `72b6ddd201e541357cb52f30c3fdeb073adef02d` |
| End | see `git rev-parse HEAD` |
| origin/main | `ddef4613ec362e6c32307160aba8f4a56b835a20` |
| Deployed live | `31cd8398` (unrelated stop-truth baseline) |
| Local DeepSeek commit recovered | YES (`72b6ddd2`, not on GitHub) |

## Exact models

- `deepseek-v4-flash`
- `deepseek-v4-pro`

## What passed

- Package checksums
- Source reconciliation + dirty isolation via dedicated worktree
- Live `/v1/models` both V4 IDs
- Chat smoke exact Flash/Pro return themselves
- Legacy reasoner/chat return Flash (provider) — client now rejects legacy IDs
- Registry + logical policies
- No silent Gemma for DeepSeek/unknown lanes
- 25 unit/safety tests PASS
- No deploy / no service restart / no broker authority change

## What failed / incomplete

- **Service-runtime key**: portfolio-server process lacks DeepSeek env names (interactive rendered env has `deepseek_tradeai`)
- Full process JSON schema modules + repair loops
- Tool-call reasoning_content replay suite
- Global cost hard-cap enforcement path
- Frontend server-authoritative policy (TS duplication residual)
- Full `/v3` route/subtab URL+heading+active-tab screenshot suite
- Frontend build/typecheck not run in this session
- Branch not merged; origin/main still diverged from 72b6ddd2 lineage

## Operator actions still required

1. Wire `DEEPSEEK_API_KEY` or `deepseek_tradeai` into `portfolio-server` EnvironmentFile (rendered Bitwarden env). **No restart in this task.**
2. Review/PR `fix/deepseek-v4-routing` (rebase onto origin/main carefully — histories diverged).
3. Approve bounded Pro Max / live canary later.
4. Complete V3 route maturity suite before claiming site maturity PASS.

## Deployed

**NO**

## Rollback

See `ROLLBACK.md`
