# Test Evidence

Run: `python -m pytest tests/test_execution_state.py tests/test_execution_readiness.py ...`

Minimum scenarios: live globally prohibited, policy on DB arm off, desk approval missing,
quote stale after approval, kill switch after approval, LLM cannot override hard block,
no broker write bypass, release blocked by dirty live-adjacent file.
