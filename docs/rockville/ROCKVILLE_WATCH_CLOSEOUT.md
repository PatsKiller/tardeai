# ROCKVILLE_WATCH_CLOSEOUT

**Branch:** `feat/rockville-watch-cio-v1`  
**Date:** 2026-08-04  

## Closeout checklist

| Gate | Status |
|------|--------|
| EXACT FLASH MODEL VERIFIED | YES — `deepseek-v4-flash` via `resolve_policy(WATCH_FAST)` tests |
| EXACT PRO MODEL VERIFIED | YES — `deepseek-v4-pro` via `resolve_policy(CIO_DAILY_PRO)` tests |
| SILENT FALLBACKS | NONE — forbidden providers/models raise; no Gemma/Grok/ChatGPT path in Rockville |
| DAILY CALL LIMIT VERIFIED | YES — scheduler `SKIP_ALREADY_COMPLETE` / lock tests |
| NO-CHANGE PROVIDER CALLS | YES — `SKIP_NO_MATERIAL_CHANGE` + `NO_MATERIAL_CHANGE` artifact cost 0 |
| DETERMINISTIC FAIL WITH MECHANICS | FAIL FIXED — projection + FTH fixture assert zero mechanics |
| BLOCKED WITH MECHANICS | PASS — tests assert zero |
| STALE WITH MECHANICS | PASS — tests assert zero |
| FTH FIXTURE PASS | YES — see unit tests |
| CIO DIGEST VISIBLE | SHADOW — panel mounted when shadow/visible flag |
| PER-CARD LLM SYNTHESIS VISIBLE | SHADOW — panel on card; paid Flash gated off |
| LLM FINANCIAL AUTHORITY ADDED | NO |
| REAL ORDER QUEUED OR SUBMITTED | NO |
| PRODUCTION SECRET EXPOSED | NO |
| ROLLBACK TESTED | DOCUMENTED — flag + path retain prior projection |

## Not yet production-enabled

- Live DeepSeek Flash per-symbol generation  
- Live CIO_DAILY_PRO provider runner at 16:20 ET  
- Screenshot CI pack (placeholder dir created)  
- Full evidence module drill-downs on every live packet  

## How to verify

```bash
cd $PROJ
.venv/bin/python -m unittest tests.test_rockville_watch_decision -v
curl -sS http://127.0.0.1:7777/api/v3/watch/priority | python3 -m json.tool | head
curl -sS http://127.0.0.1:7777/api/v3/watch/symbols/FTH | python3 -m json.tool | head
```

Open `/v3/watch` → Rockville shadow band shows FTH DETERMINISTIC FAIL card without current mechanics.
