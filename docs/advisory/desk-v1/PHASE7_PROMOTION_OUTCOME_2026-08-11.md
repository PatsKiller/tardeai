# Phase 7 Outcome — Final Promotion Gate

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Plan:** [AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md](./AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md)  
**Depends on:** Phase 0–6  
**Authority:** READ_ONLY_ADVISORY throughout — **no broker credentials, ever**

---

## What Phase 7 is

The **final promotion gate** for the Advisory Desk as the **default morning advisory path**.

It is **not**:
- Agent fleet `production_activation_authorized`
- Notification broker ACTIVE egress cutover
- Live order / rebalance / 2FA authority for any agent

It **is**:
- 30 **consecutive** green shadow sessions
- Useful-rate ≥60% (n≥5), zero `WRONG_FACT` indefensibles
- Spend within budget on the streak
- Invariants + plausibility + validation green on the streak
- Authority fence still DENIED for broker/order/2FA
- Alert integrity structure intact
- ≥10 ratified lessons
- Operator-confirmed `PROMOTE` → morning path default-on

---

## Delivered

| Item | Path |
|---|---|
| Promotion gate | `scripts/lib/advisory/promotion_gate.py` |
| CLI | `scripts/advisory_promotion.py` |
| State file | `data/runtime/advisory_shadow/PROMOTION.json` |
| Log | `data/runtime/advisory_shadow/promotion_log.jsonl` |
| Scoreboard P7 fields | consecutive_passes, promotion_target=30, phase7_streak_met |
| Morning path gate | `morning_command_digest.advisory_morning_enabled()` |
| API | `GET /api/v3/advisory` includes `promotion` · `GET /api/v3/advisory/promotion` |

---

## States

| Status | Meaning |
|---|---|
| `NOT_PROMOTED` | Default; gates incomplete |
| `ELIGIBLE` | All gates green — operator may promote |
| `PROMOTED` | Operator confirmed; morning advisory path default |

```bash
.venv/bin/python scripts/advisory_promotion.py evaluate
.venv/bin/python scripts/advisory_promotion.py status
.venv/bin/python scripts/advisory_promotion.py promote --confirm --operator john
.venv/bin/python scripts/advisory_promotion.py demote --reason "rollback"
```

**Promote never auto-runs.** Even when `ELIGIBLE`, requires `--confirm`.

---

## Gates (all required)

1. **30 consecutive** `session_pass` sessions (trailing streak)  
2. **Useful rate** ≥ 0.60 with n ≥ 5 (`/advisory rate`)  
3. **Zero** `WRONG_FACT` notuseful ratings  
4. **Budget** respected on the streak (≤ $0.05/session default)  
5. **Invariants / plausibility / validation** green on every session in streak  
6. **Authority fence** — catalog global_authority DENIED; no broker on artifacts  
7. **Alert integrity** — telegram_alert, router, morning sections, legacy delivery present; broker not auto-ACTIVE  
8. **Lessons** — ≥10 ratified  

---

## Morning path after PROMOTED

- `fetch_advisory_brief_section()` always returns the ≤5-line desk brief (unless `ADVISORY_MORNING=0`)  
- Does **not** by itself set `ADVISORY_DESK_V1=true` (paid Flash still operator env)  
- Does **not** enable agent_runtime fleet production  

Live Flash morning sessions remain:

```bash
# ~/.config/tradeai/advisory-shadow.env
ADVISORY_DESK_V1=true
LLM_GLOBAL_DAILY_USD_CAP=0.25
```

---

## Current host snapshot (evaluate)

Run `advisory_promotion.py evaluate` — as of implementation day, streak is **1/30** until weekday shadow timer fills the log. Gates that are already green today:

- Authority fence  
- Alert integrity  
- Lessons (≥10)  

Gates waiting on calendar / operator:

- 30 consecutive sessions  
- Useful-rate n≥5 and ≥60%  

---

## Tests

```
tests/test_advisory_desk_phase7.py → 5 passed
```

Includes: streak logic, authority fence, alert integrity, full promote/demote with mocked 30-session + feedback + lessons, morning path env/promotion.

---

## Pass criteria map

| Design final gate | Implementation |
|---|---|
| 30 consecutive sessions | `consecutive_passes` / `phase7_streak_met` |
| Zero indefensible | `indefensible_wrong_fact == 0` |
| ≥60% useful | `meets_60pct` |
| Spend within budget | per-session + streak budget check |
| Invariants + plausibility green | streak session gates |
| Every existing alert intact | `check_alert_integrity` |
| Authority fence unchanged | `check_authority_fence` |
| Desk default morning path | `PROMOTED` → `morning_path_default` |

---

## Explicit forever non-goals

- Agents holding broker credentials  
- Auto order / stop / rebalance  
- Silent notification broker ACTIVE cutover  
- `production_activation_authorized=true` as a side effect of desk promote  

---

## End-to-end journey (Phases 0–7)

| Phase | Result |
|---|---|
| 0 | Governed bridge + cap refuse |
| 1 | Lots, validation, Risk/Tax holdings |
| 2 | Cache, evidence, Pro synthesis |
| 3 | Memory, feedback, outcomes |
| 4 | `/v3/advisory` + Telegram |
| 5 | Shadow sessions + Guardian/Ledger |
| 6 | Lessons KB + notif broker SHADOW |
| 7 | 30-session promotion gate + morning default |

---

*Advisory only. Promotion makes the desk the default morning **message**, not an autonomous trader.*
