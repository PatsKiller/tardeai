# Overnight F5 — Model-call cost accounting

**Wave:** Overnight F5  
**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY · no deploy · no cron install  
**Branch:** `fix/overnight-f5-model-cost`  
**Rails:** AGENTS.md §9.2 / §12  
**Store set:** none (event log append remains fail-soft FinOps)

## Finding

§9.2 requires every model call to record **measured cost**, the **rate tier**
(`peak` / `off_peak`), and whether input was a **cache hit** — never a hardcoded
literal. Three gaps remained on `origin/main` after Wave E:

1. **`provider_cost.pricing.is_peak` ignored weekdays.** Saturday/Sunday hours
   inside the UTC clock windows were billed as peak, disagreeing with the vendor
   doc, `deepseek_offpeak.is_deepseek_peak_utc`, and the registry peak detector.
2. **`ProviderCostEvent` dropped the band.** `calculate_usd` returned `band`, but
   `emit_cost_event` never persisted `rate_tier` / `cache_hit` on the event.
3. **Budget checks could fail open.** `reserved_usd_open` returned `0.0` on
   ledger errors (understating open holds). Direct `deepseek_client.chat`
   callers had no pre-send budget gate.

Hardcoded USD expectations in `tests/test_deepseek_cost_governance.py`
(`0.0028`, `1.305`) were already stale against the 2026-08-16 schedule — exactly
the class of audit lie §9.2 warns about.

## Change this tranche

| File | Change |
|------|--------|
| `scripts/lib/provider_cost/pricing.py` | Weekday-only peak; expose `band` + `cache_hit` |
| `config/provider_pricing_schedules.json` (+ fixtures) | Explicit `peak_days: Mon-Fri` |
| `scripts/lib/provider_cost/schema.py` | `rate_tier`, `cache_hit` fields on `ProviderCostEvent` |
| `scripts/lib/provider_cost/emit.py` | Persist measured tier + cache hit |
| `scripts/lib/provider_cost/budget.py` | **New** — pre-send budget check; never fail open |
| `scripts/lib/llm_model_registry.py` | `estimate_usd_cost` prefers schedule table |
| `scripts/lib/deepseek_client.py` | Budget before POST; response carries tier/cache/schedule id |
| `scripts/lib/llm_consumption.py` | `check_cost_cap` / `reserved_usd_open` deny on error |
| `tests/test_overnight_f5_model_cost.py` | Wave suite + CI allowlist gate |
| `tests/test_deepseek_cost_governance.py` | Derive expected USD from schedule (no literals) |

## Invariants

- Rates live in `config/provider_pricing_schedules.json`, not accounting Python.
- Peak: `01:00–04:00` and `06:00–10:00` UTC **Monday–Friday only**.
- Budget precheck: reservation held → allow; test context → allow; otherwise
  require persistence + global cap; any check error → **deny** (`fail_open=False`).
- Secrets: never printed (API key redacted / fingerprint only).

## Proof commands

```bash
python3 -m pytest -q tests/test_overnight_f5_model_cost.py
python3 -m pytest -q tests/test_deepseek_cost_governance.py
python3 scripts/run_cio_hardening_ci.py
python3 scripts/check_test_coverage.py --fail-on-new
```

## Deploy

None. Push + merge only.
