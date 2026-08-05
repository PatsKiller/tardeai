# ROCKVILLE_WATCH_BASELINE

**Date:** 2026-08-04  
**Target:** Command Center v3 `/v3/watch`  
**Architecture:** `docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md`  
**Implementation agent:** Rockville  

## Problem

The Watch card mixed:

1. Header state **WAIT** with ticket verification **DETERMINISTIC FAIL** (FTH)
2. Live trigger / invalidation while quality admission failed (float floor, ATR cap)
3. Fragmented packet dump instead of one operator decision
4. No governed once-per-day CIO synthesis with exact DeepSeek V4 Pro policy

## Operator decisions (locked)

| Decision | Implementation |
|----------|----------------|
| DeepSeek only paid LLM for Watch/CIO | `config/rockville/ROCKVILLE_WATCH_CIO_MODEL_POLICY.json` |
| Exact models only | `deepseek-v4-flash`, `deepseek-v4-pro` — aliases rejected |
| Flash for per-symbol narrative | Policy `WATCH_FAST` |
| Pro+thinking high for daily CIO | Policy `CIO_DAILY_PRO` |
| ≤1 CIO auto call per market day | `scripts/lib/rockville/cio_scheduler.py` |
| Material fingerprint (not quote ticks) | `watch_material_fingerprint.v1` |
| LLM advisory only | Projection ignores `llm_override_state` |
| Deterministic fail ≠ READY/WAIT | `project_watch_decision` + operator_presentation fix |
| Additive APIs / flags | `/api/v3/watch/*` + feature flags default off/shadow |

## Observed FTH contradiction (pre-fix)

- Header: WAIT / Waiting for confirmation  
- Mechanics: trigger 37.9, invalidation 23.12  
- Ticket: DETERMINISTIC FAIL  
- Quality: float 18.6M < 20M; ATR 12.1% > cap  

Root cause in legacy path: `scripts/operator_presentation.py` mapped `DETERMINISTIC_FAIL` → header `WAIT`.

## Corrected contract

- `primary_state`: **DETERMINISTIC_FAIL**
- `allowed_action_now`: **NO TRADE ACTION**
- `proposal_allowed`: false  
- Zero current mechanics (trigger/entry/stop/targets/R:R hidden)  
- History only under **NOT CURRENT**  
- DeepSeek may explain thesis conflict; must not invent ticket  

## Rollout posture (current)

| Flag | Default |
|------|---------|
| `watch_card_v2_shadow` | true |
| `watch_card_v2_visible` | false |
| `watch_deepseek_flash_enabled` | false |
| `watch_cio_daily_enabled` | false |
| `watch_cio_deep_review_enabled` | false |

Paid provider calls remain blocked until exact-model, JSON, cost, and idempotency tests pass (rollout step 5+).
