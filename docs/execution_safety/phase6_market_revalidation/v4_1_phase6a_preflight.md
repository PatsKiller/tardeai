# Phase 6A Preflight — Paper Approval Market Revalidation Hardening

**Date:** 2026-05-15
**Phase:** 6A
**Operator:** John / Claude Code

## Git State

```
65ba0cf phase 8: strategy analytics dashboard — 7 panels
3758b0b Add real-time market revalidation gate to proposal approval flow
4dca0e0 docs: system maturity audit — answer operator's five concerns
3eb351b phase 7: trade intelligence expansion panel in journal UI
a540c9d phase 6: strategy best-fit ranking engine
5b20f97 Enable hourly auto-proposals and incubator promoter during trading hours
252dd49 docs: proposal pipeline cleanup cron and dashboard BLOCKED fix
```

Dirty files (not staged, not Phase 6A related):
- `apps/command-center-v2/src/pages/Overview.tsx` (prior session)
- `apps/command-center-v2/src/pages/PaperJournal.tsx` (prior session)
- `apps/command-center-v2/src/pages/PaperOutcomes.tsx` (prior session)
- `apps/command-center-v2/tsconfig.app.tsbuildinfo` (build artifact)
- `config/youtube_cookies.txt` (unrelated)

## Safety Checks

| Check | Result |
|-------|--------|
| ALPACA_MODE | **paper** |
| LLM_DISABLE_LIVE_EXECUTION | **true** |
| Holdings guard ($1M+) | **OK: $1,189,358** |
| scripts/api_v2.py exists | **YES** (835,062 bytes) |
| Endpoint found | **YES** — line 12556 |
| market_revalidation in response | **YES** — line 12647 |

## Relevant Cron Jobs

| Schedule | Job | Purpose |
|----------|-----|---------|
| */5 9-16 M-F | paper_execution_sweep.py | Safety net for approved proposals |
| */5 9-16 M-F | paper_trade_monitor.py | Monitor open paper trades |
| 0 10-16 M-F | alpaca_paper_adapter.py --sync-only | Hourly position reconciliation |
| 0 7-17 M-F | incubator_proposal_promoter.py --run | Hourly auto-promotions |
| 0 10,15 M-F | cleanup_stale_proposals.py --apply | Reject stale proposals |
| 35 9 / 5 16 M-F | alpaca_paper_reconciler.py | Broker reconciliation |

## Preflight Verdict

**PASS** — All safety gates confirmed. Proceeding with Phase 6A.
