# Phase 5 Outcome — Shadow Autonomy + Guardian / Ledger

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Plan:** [AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md](./AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md)  
**Depends on:** Phase 0–4  
**Authority:** READ_ONLY_ADVISORY · mode **SHADOW**  

---

## What Phase 5 is

Not “turn on production trading.” It is the **20-session operator shadow track** plus the first **Guardian / Ledger / Steph** specialist mandates — all fenced.

| Goal | Mechanism |
|---|---|
| 20 sessions, flag ON for operator only | `advisory_shadow_session.py` + weekday timer |
| Gates every session | validation · plausibility · invariants · spend ≤ budget |
| Useful-rate ≥60% | From `advisory_feedback.jsonl` |
| Median changed-rows/day | Scoreboard from session hash diffs |
| Guardian cash / IPS | Deterministic artifact + Sentinel + Darwin |
| Ledger Roth / Golden Window | `portfolio_retirement` only — **no DeepSeek tax** |
| Steph idle cash | Narrative only — **no rebalance.execute** |

---

## Delivered

| Item | Path / unit |
|---|---|
| Shadow session runner | `scripts/lib/advisory/shadow_session.py` |
| CLI | `scripts/advisory_shadow_session.py` |
| Specialists | `scripts/lib/advisory/specialist_shadow.py` |
| Session log | `data/runtime/advisory_shadow/sessions.jsonl` |
| Scoreboard | `data/runtime/advisory_shadow/scoreboard.json` |
| Artifacts | `data/runtime/advisory_shadow/artifacts/` |
| Sentinel / Darwin (local) | `…/sentinel_reviews.jsonl`, `…/darwin_scorecards.jsonl` |
| Timer | `tradeai-advisory-shadow-session.timer` Mon–Fri 09:15 |

---

## Commands

```bash
# One dry shadow session (deterministic enrich + specialists; $0 LLM)
.venv/bin/python scripts/advisory_shadow_session.py --once

# Operator live Flash/Pro session (requires bridge + ADVISORY_DESK_V1)
.venv/bin/python scripts/advisory_shadow_session.py --once --live

# Scoreboard toward 20
.venv/bin/python scripts/advisory_shadow_session.py --status

# Specialists only
.venv/bin/python scripts/advisory_shadow_session.py --specialists-only
```

### Enable live on the timer (operator)

```bash
mkdir -p ~/.config/tradeai
cat > ~/.config/tradeai/advisory-shadow.env <<'EOF'
ADVISORY_DESK_V1=true
LLM_GLOBAL_DAILY_USD_CAP=0.25
EOF
systemctl --user restart tradeai-advisory-shadow-session.timer
```

Default timer is **dry** (safe) until that env file exists.

---

## Session gates (`session_pass`)

All must hold:

1. `validation_ok`  
2. `plausibility_gate == PASS`  
3. `invariant_violation_count == 0`  
4. `spend_usd ≤ budget` (default $0.05)  

---

## Specialists

| Agent | Mandate | Tax / exec fence |
|---|---|---|
| **Guardian** | Cash concentration + IPS max position | No broker / order |
| **Ledger** | Roth ladder → Golden Window | Numbers from `portfolio_retirement` only; `deepseek_used=false` |
| **Steph** | Idle cash deployment narrative | `rebalance.execute` denied |

Each artifact: Sentinel PASS required; Darwin scorecard appended (0 model $).

---

## Pass criteria (design Phase 5 / 6 shadow)

| # | Criterion | Status |
|---|---|---|
| 5.1 | 20 sessions, no invariant violations | **TRACKING** — runner enforces per session; count builds daily |
| 5.2 | No plausibility failures to operator | **Enforced** in `session_pass` |
| 5.3 | Spend within budget every session | **Enforced** |
| 5.4 | Useful rate ≥60% on actionable | **Tracked** from feedback (needs operator ratings) |
| 5.5 | Zero indefensible (WRONG_FACT) | **Tracked** |
| 5.6 | Median changed-rows/day documented | **Scoreboard field** |
| Guardian/Ledger | 20 artifacts, 0 contradictions | **Path live** — 3 artifacts/session × days |

`phase5_ready` flips true only when: ≥20 passed sessions · useful≥60% (n≥5) · 0 WRONG_FACT · ≥20 specialist artifacts.

### First session (2026-08-11, dry)

```
session pass=True live=False spend=$0.0 changed=52 progress=1/20 specialists_ok=True
artifacts: guardian_*, ledger_*, steph_*
timer: tradeai-advisory-shadow-session.timer Mon–Fri 09:15
```

---

## Tests

```
tests/test_advisory_desk_phase5.py → 4 passed
```

---

## Explicit non-goals (still)

- Enabling full agent_runtime fleet without opt-in  
- Un-containing CIO heartbeat without separate gate  
- `production_activation_authorized`  
- DeepSeek on Roth/IRMAA/SSDI tax lane  
- Any order / rebalance execution  

---

## Next (Phase 6)

`kb_lessons` + Iris · notification broker compression · 30-session promotion gate.

---

*Advisory only. Shadow does not grant broker credentials or order endpoints.*
