# Task 7 — P3-1 Clarification: .env Fallback Block (RESOLVED)

**Date:** 2026-04-20
**Resolution:** Fallback removed. Task 7 verified working without it.

---

## Summary

A manual .env fallback parser was added to `portfolio_orchestrator.py` during Task 7 implementation because testing was done with system `python3` (which lacks `python-dotenv`). This was a testing artifact — production always runs via `.venv/bin/python3` where `python-dotenv` is available.

## Resolution

The fallback block has been **removed**. The original `.env` loading code is restored:

```python
    # Load .env so API key is available throughout the pipeline
    import os
    if not os.getenv("ANTHROPIC_API_KEY",""):
        try:
            from dotenv import load_dotenv
            load_dotenv(root/".env")
            if os.getenv("ANTHROPIC_API_KEY",""):
                print("  [env] Loaded API key from .env")
        except Exception:
            pass
```

## Why It Works Without the Fallback

1. Production launcher (`linux_launchers/run_portfolio.sh`) runs `source .venv/bin/activate`
2. `.venv` has `python-dotenv` installed → `load_dotenv('.env')` succeeds
3. `DB_PASSWORD` is set before db_adapter is imported
4. Step 7 imports `portfolio_performance.py` which has its own .env loader (P2-1 fix)
5. By the time `save_performance_daily` is called, `db_adapter.USE_DB` is True

## Verification

Task 7's `performance_daily` insert works correctly with `.venv` and without the fallback:
- Row inserted: `2026-04-20 | $1,209,315.86 | YTD +3.77%`
- Idempotent: `COUNT(*) = 1` after two runs
- JSON unchanged: 7.7KB, all periods, all accounts
