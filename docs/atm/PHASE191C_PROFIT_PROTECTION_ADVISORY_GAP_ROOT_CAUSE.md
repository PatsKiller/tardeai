# PHASE 191C — Root Cause: Why the Profit-Protection Advisory Did Not Show

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only · evidence-based**

---

## Answer
The data was **present but not surfaced**, and the only protection logic that existed was
**binary (stop exists / missing)** — there was no concept of stop *quality*, profit-lock, giveback,
or take-profit, and no inline advisory surface.

## Findings by surface
| Surface | Why it didn't show the advisory |
|---|---|
| `strategy_trailing_policy` v2.3 | Computes a trailing recommendation **only at ≥ 1.0R tiers**, and returns `hold` / `invalid entry/stop data` when `planned_stop` is NULL (ANY/SNOW). So for the two positions that most needed advice, it produced **nothing**. It is also a *trailing* engine — it has no "lock profit now / take-profit / giveback" advisory below its tiers. |
| `unified_stop_supervisor` | Pre-Phase-190 only checked stop **existence**, not stop **quality**; Phase 190 added defect detection (naked/untracked) but still not "stop too loose vs unrealized gain." |
| `protection_alerts` (190D) | Detects missing/untracked/large-gain-no-TP, but had no "loose stop / giveback / lock-profit" advisory and no inline surface. |
| Hermes | 189E/190E gave Hermes a protection **view**, but its rules covered missing/untracked stops — **not** profit-protection quality (loose stop on a winner). Its autonomous loop also only reads **closed** trades. |
| ATM dashboard / AutomatedTradeJournal / AI Advisory | No component rendered a per-trade stop-quality / profit-protection advisory; the protection-coverage panel (190F) shows counts, not per-trade *action* advice. |
| TradeAI open-position intelligence | Looked at **stop existence**, not **stop quality** (is it protecting the gain?). No take-profit / profit-lock concept existed. |
| Trailing policy output | Blocked because no `planned_stop`/R was computable for `unknown_sync` positions (see row 1). |

## Root-cause classification
- **Was data missing?** No — entry, price, stop, P&L all available (Phase 190 made stops tracked).
- **Was it present but not surfaced?** **Yes** — no inline advisory component, no per-trade action.
- **Was there no rule?** **Yes** — no stop-quality / profit-lock / giveback / take-profit rule.
- **Rule only for missing stops, not loose stops?** **Yes** — exactly the gap.
- **Blocked because no planned_stop/R computable?** **Yes** for ANY/SNOW — trailing engine no-op'd.
- **Hermes only closed trades?** Its autonomous loop, yes; its protection view is open trades but
  had no profit-protection rule until 191E.
- **TradeAI only stop existence, not quality?** **Yes.**
- **No take-profit / profit-lock concept?** **Correct — none existed before Phase 191.**

## Fix (Phase 191)
A dedicated advisory layer that evaluates **stop quality vs unrealized gain** independently of the
trailing-tier algorithm, computes profit-lock/giveback, and surfaces a per-trade action with a
Hermes second opinion — using the broker stop as a risk basis when `planned_stop` is absent.
