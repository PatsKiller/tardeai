# Autonomy & scheduling truth — Advisory Desk + agent fleet

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Authority:** READ_ONLY_ADVISORY — no broker / order / 2FA  
**Question answered:** *Are these agents 100% autonomous with brains, not relying on crons?*

---

## Short answer

| Claim | Truth |
|---|---|
| 100% autonomous **traders** | **No.** Forbidden by design. Human owns every order. |
| 100% autonomous **advisory factory** (unattended observe → reason → surface) | **Target yes; runtime partial.** Code path Phases 0–7 is built. Promotion still `NOT_PROMOTED` (1/30 sessions). |
| Free-running “always-on brains” that wake themselves | **No.** Invocation is **deterministic schedule** (user systemd timers / oneshot services). Agents do **not** self-reschedule. |
| LLM brains in the loop when a job runs | **Yes, when flags + bridge + cap allow.** Flash (opinions) + Pro (synthesis) via governed bridge `:8766`. |
| Wealth / CIO fleet (Steph, Morgan, Guardian, …) fully autonomous | **No.** `agent_runtime@*` is **SHADOW / prepare-only**, currently **failing** (queue module misconfigured). |

**Honest product line:** *scheduled advisory factory with LLM brains* — not continuous autonomous agents, not autonomous traders.

**2026-08-11 update (goal/thesis gap):** Durable `CIOGoalStore` + `CIOWakeDispatcher.enqueue_goal_wakes` add **goal-due / idle** wakes beside the existing event claim path. Still timer-driven oneshots; still no self-scheduling agents. See [AUTONOMY_GOAL_THESIS_COMPLETE.md](./AUTONOMY_GOAL_THESIS_COMPLETE.md) and [RUNTIME_TRUTH_2026-08-11.md](./RUNTIME_TRUTH_2026-08-11.md).

---

## How work actually runs (scheduling model)

```
systemd timer (cron-like)  →  oneshot service  →  Python job
        │                           │
        │                           ├─ optional Flash / Pro via bridge
        │                           └─ write runtime JSON / Telegram / scoreboard
        │
        └── agents cannot start themselves; only the timer may start them
```

Timers are the **heartbeat**. LLM is the **brain on demand**, not a resident daemon of “thinking agents.”

| Job | Timer / unit | Cadence (installed) | Needs LLM? |
|---|---|---|---|
| Bitwarden SM env | `tradeai-sm-render.timer` | periodic | No |
| Governed bridge | `cio-governed-bridge.service` | **always-on** daemon | N/A (egress) |
| Tax lots rebuild | `tradeai-tax-lots-rebuild.timer` | Mon–Fri ~07:15 + 16:45 | No |
| Risk/Tax holdings enqueue | `tradeai-holdings-agent-enqueue.timer` | Mon–Fri 08:30 + 13:30 | Indirect (queue later) |
| Shadow desk session | `tradeai-advisory-shadow-session.timer` | Mon–Fri **09:15** | Yes if `ADVISORY_DESK_V1` + live env |
| Notif broker (SHADOW) | `tradeai-advisory-notif-broker.timer` | hourly | No (routing only) |
| Outcome scorer | `tradeai-advisory-outcome-scorer.timer` | daily 18:30 | No (deterministic) |
| Lessons reflect | `tradeai-advisory-lessons-reflect.timer` | daily 21:40 | Optional / rule-based |
| Morning digest | existing morning path | morning | Desk section after `PROMOTED` or env |
| `agent_runtime@*` (Alex/Morgan/Steph, …) | templated timers | ~every few min | SHADOW oneshot — **fixed** provider env (2026-08-11); goal jobs when open goals exist |
| Goal/thesis wakes | via `CIOWakeDispatcher.poll_and_dispatch` | on dispatcher cycle | No extra cron; enqueues GOAL_DUE wakes |

There is also host **cron** for unrelated ops (e.g. Drive docs sync hourly `:05`). Advisory desk units are **user systemd**, not classic crontab, but the **scheduling dependency is the same idea**.

---

## “Brains” vs schedule

| Layer | What it is | Autonomous? |
|---|---|---|
| L0–L2 data + deterministic rows | Pure code on each build | Unattended when scheduled |
| L5 Flash opinions | LLM per material/changed row | Only when job runs + flag + cap |
| L6 Pro synthesis | One LLM “three things today” | Same |
| L4 memory / feedback / outcomes | Storage + scorer | Scorer is scheduled; feedback is human (`/advisory rate`) |
| L7 delivery | Telegram / API / CC | Push when job or morning path runs |
| Promotion gate | 30 green sessions + operator `promote --confirm` | **Never auto-promotes** |

So: **brains exist**, but they **turn on when a timer fires a job**. No free-form continuous agent loop owns the desk today.

---

## Fleet agents (Steph / Morgan / Guardian / …) — 2026-08-11 host truth

```
AGENT RUNTIME BOUNDED RUNNER — PREPARE-ONLY / DEFAULT-DISABLED
agent=steph state=SHADOW enabled=True
dispatch refused: ModuleNotFoundError: No module named
  'agent_runtime_live_providers  # real DeepSeek/Ollama + Data Broker + event bus'
```

Implications:

1. Units are labeled **SHADOW, prepare-only** — not production traders.  
2. They are **timer-driven oneshots** (`--once`), not long-lived autonomous processes.  
3. On this host they are currently **failing** (status 78 / CONFIG) — no live “brain loop.”  
4. Desk does **not** wait on fleet production activation; desk promotion never sets `production_activation_authorized`.

---

## What *is* live for the desk today

| Component | State |
|---|---|
| Bridge `cio-governed-bridge` | **running** (canary, caps) |
| Shadow timer | **armed** (next Mon–Fri 09:15); default dry until `~/.config/tradeai/advisory-shadow.env` |
| Promotion status | **`NOT_PROMOTED`** — consecutive **1/30**; useful-rate needs n≥5 |
| Morning desk default | Off until operator `promote --confirm` after gates |
| Broker credentials on agents | **Never** (fence green) |

---

## What “done” would look like for unattended advisory (not trading)

1. Weekday shadow timer runs live Flash under cap for **30 consecutive** green sessions.  
2. Operator rates useful ≥60% (n≥5); zero `WRONG_FACT`.  
3. `advisory_promotion.py evaluate` → `ELIGIBLE` → operator `promote --confirm`.  
4. Morning digest includes desk brief without manual flag.  
5. Fleet agents (optional later): fixed queue module, SHADOW proven, **separate** production gate — still no broker.

That is **scheduled autonomy with brains**, still human-in-the-loop for money.

---

## Explicit forever non-goals (unchanged)

- Agents placing/modifying orders or stops  
- Agents holding broker credentials or 2FA  
- Silent budget override / cap bypass  
- Auto-promote morning path without operator confirm  
- Agents that schedule themselves without a deterministic timer  

---

## Operator one-liners

```bash
# Desk promotion truth
.venv/bin/python scripts/advisory_promotion.py evaluate

# Timers that own the desk cadence
systemctl --user list-timers 'tradeai-advisory-*' 'tradeai-tax-lots-*' 'tradeai-holdings-*' 'cio-governed-bridge*'

# Fleet is NOT the desk
systemctl --user --failed 'tradeai-agent-runtime@*'
```

---

*Docs under `docs/advisory/desk-v1/` are canonical. Drive mirror: `scripts/sync-docs-to-drive.sh`.*
