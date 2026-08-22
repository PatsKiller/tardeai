# Telegram feed audit — P0 gates (freeze window) + P1 queue

**Date:** 2026-08-22  
**Authority:** READ_ONLY_ADVISORY  
**Freeze:** 8/21–8/27 close. **P0 only in this PR** (suppression / no second send). T3–T7 after the window.  
**CURRENT:** do not promote.  
**Corpus:** 18,130 messages · 4 feeds · 2026-05-19 → 2026-08-22 (operator audit).

## What shipped (T1 + T2)

Code: `scripts/lib/telegram_card_gate.py`, `scripts/lib/telegram_send_idempotency.py`, `scripts/telegram_transport.py` (`deliver_text`).

| Rule | Behavior | Metric |
|---|---|---|
| **R:R** | Recompute from entry/stop/target. Never emit `0.0:1`. Missing/non-positive → `R:R UNAVAILABLE` and **not** `ACTIONABLE_READY`. ASPN $5.42 / $5.15 / $5.96 → **2.0:1**. | suppress JSONL `rr_unavailable` is not a withhold; quote fail is |
| **Quote fail** | `quote_execution_eligible=false` (the `Quote: alpaca ❌` card) → **withhold** the proposal. | `telegram_p0_suppress.jsonl` rule `quote_fail` |
| **Invalidation** | Long: invalidation must be **&lt; price**. Else suppress IIC (JTAI $1.59 / inv $1.60). Short inverted. | rule `invalidation_contradicts_price` |
| **Double-post** | Markdown 400 → one plaintext send (first never posted). Known `(surface, symbol, decision_id)` → **editMessageText**. `send_telegram_proposal_alert` no longer posts a second copy. | idempotency map `data/runtime/telegram_send_idempotency.json` |

3-day suppress report: count lines in `data/cio/telegram_p0_suppress.jsonl` grouped by `rule`.

## Not in this PR (after 8/27)

| ID | Work |
|---|---|
| **T3** | One resolver per field. `Zone ?–?` vs Levels zone. Placeholder `?` never renders. |
| **T4** | Thesis/catalyst join: bind slots to desk / Hermes / `hermes_external_research`. Operator copy not `DATA_UNAVAILABLE`. Dollar-sized call requires capital context. |
| **T5** | Strip `dec_`/`prod_`/`plan_` from CIO Desk operator copy; round floats. |
| **T6** | Four feeds: CIO Desk / **TradeAI Alerts** (NEW) / Proposal Decisions / **TradeAI Ops** (NEW, muted). Move health+STOP_TRIGGERED. Kill 1,330 ChatGPT research-update pushes. Dedupe Hermes watchlist. **New producers — freeze forbids now.** |
| **T7** | Volume budget 30/day (Ops exempt, muted). Over → digest. |

`tradeai_bigjohn718_bot` remains the ops+market mix until T6. CIO Desk stays the template.

## Structural verdict (audit, unchanged)

Bot feed is not a trading feed (115/day, 13% actionable, 5.8% last-14d). STOP_TRIGGERED (374) is buried in UNHEALTHY/DEGRADED. Proposal Decisions 77% actionable — keep. CIO Desk best-designed.

## Flags / pin

`RESEARCH_SKIP_GATE` 0 · `MEMORY_BEHAVIOR_INFLUENCE` 0 · `RESEARCH_ALLOW_LOCAL_LLM` 0. CURRENT pin `5e91225a` not advanced.
