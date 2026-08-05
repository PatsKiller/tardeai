# ROCKVILLE_WATCH_CLOSEOUT

**Branch:** `feat/rockville-watch-cio-v1`  
**Status:** **FOUNDATION only — not product completion**

## Explicit product limitation

PR #294 is a **shadow foundation**. It does **not** deliver the full Watch rebuild:

- concise ~20-item prioritized operator page  
- company narrative, industry/benchmark, full fundamentals desk  
- catalyst timeline, thesis/counter-thesis reflective review  
- scheduled review cadence + material-change paid Pro runs  

Do **not** call the Watch rebuild complete.

## Foundation gates

| Gate | Status |
|------|--------|
| LIVE MULTI-SYMBOL PROJECTION | YES — FTH, NUAI, AXTI, SWBI, CECO, held (PFLT) from `decision_packets` |
| FIXTURE NOT INJECTED IN PROD API | YES — `fixture_injected: false` |
| FTH = Faeth (not Fate/FATE) | YES |
| FAIL-CLOSED projection + legacy desk | YES (tooltips sanitized) |
| CIO NO_CALL truthful | YES |
| DEEP REVIEW GATED | YES |
| DESIGN GUARD | PASS required for ship build |
| PAID FLAGS | all false |
| PROVIDER CALLS | 0 |
| LLM AUTHORITY / ORDERS | NO |

## Verify

```bash
.venv/bin/python tests/test_rockville_live_foundation.py -v
.venv/bin/python tests/test_rockville_watch_decision.py -v
curl -sS http://127.0.0.1:7777/api/v3/watch/priority | python3 -c "import sys,json;d=json.load(sys.stdin);p=d.get('data')or d;print(p.get('count'),p.get('fixture_injected'),[c['symbol'] for c in p.get('cards',[])])"
```
