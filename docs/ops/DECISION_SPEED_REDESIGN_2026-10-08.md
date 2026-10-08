# Decision-speed redesign — Telegram cards, Home, Communications, Watch (2026-10-08)

Your review (2026-10-08): "Right now the system is optimized for completeness. It needs to be optimized for
decision-making speed." 80% of the screen should answer three questions: what needs action right now, what is my
highest risk, and what is my highest opportunity. Everything else goes behind an expander. Numbers come first:
huge number, small label, colour card. Opportunity and risk never share one visual area.

## Telegram — decision cards (`scripts/lib/telegram_cards.py`)

| Family | Before | After |
|---|---|---|
| CIO entry alert (`telegram_rich.cio_entry_alert`, both producers) | `🟡 CIO ENTRY ALERT — SWMR · New position` with eight text sections | `🟡 HIGH CONVICTION ENTRY` / `$SWMR` / STATUS / ACTION REQUIRED / 💰 ENTRY · 🛑 STOP · 🎯 TARGET · R:R / 🏢 COMPANY (with industry) / ⚡ CIO VERDICT + reasons / TTL. Buttons: Open Research · Open TradingView · Review Position. Deep context stays collapsed. |
| Stop health (`stop_health_check.py`) | `🚨 STOP HEALTH — 3 alert(s) (1 urgent)` as Markdown text | `🚨 CRITICAL STOP ALERT` / `$DT` / 🛑 STOP HEALTH ISSUE (`STOP HEALTH — ORPHANED · account`) / urgent and total counts / 👉 ACTION / TTL. Buttons: Open Position · Check Stops. |

- **Headers:**
  - `HIGH CONVICTION ENTRY` — READY;
  - `ENTRY APPROACHING` — near;
  - `ADD-ON ENTRY` — held;
  - `ENTRY BLOCKED` — hard block;
  - `ENTRY ALERT` — anything else.
- **Marker colours:** green only when the CIO reviewed the name; blocked is red; everything else amber.
- **Routing is unchanged, and proven.** These read the text, and all were updated together:
  - `operator_alert_policy_v2` (entry headers route as `cio_entry_state`);
  - the daily-budget exemption in `telegram_alert_router`;
  - `config/comms_categories.yaml`;
  - Communications symbol extraction (the `$TICKER` line);
  - per-symbol topic keys, so one name's card never supersedes another's;
  - subject-resolver stopwords.

  `tests/test_decision_cards_20261008.py` renders every entry and stop shape both ways and requires the same
  alert type, severity, budget exemption and category.
- **One deliberate correction.** A warning-only stop batch used to route as `job_telemetry` (OPS digest), because
  STOP and NEAR were never on the same line. It now routes as `stop_warning` (RISK digest). It still goes to a digest,
  but now in the right bucket.
- **Rollback:** `config/telegram_cards.yaml` → `enabled: false` per family. It is read on every send, so no deploy is
  needed. If building a card fails, the alert falls back to the previous layout and is never lost.

## Command Center

- **Colour families** (`components/decision/DecisionParts.tsx`). Theme tokens only:

  | Family | Token |
  |---|---|
  | Critical | danger, with a stronger fill |
  | High | warning |
  | Medium | info |
  | Opportunity | success |
  | Security | ai |

  `familyFor(priority, category)` maps every item to its family.
- **Home**, from the top:
  1. Executive strip: Portfolio (largest), Today with %, Realized, Win rate.
  2. 🚨 REQUIRES ATTENTION: a red, full-width card with active issues (large), critical threats, expiring soon,
     approvals pending, and Review now (opens Communications on the attention view).
  3. 🟢 BEST OPPORTUNITIES (green), from the CIO opportunity ranking.
  4. 🔴 TOP RISKS (red): threats grouped by symbol, with Review stops.

  The old metric grid is now a collapsed **More metrics** section, and the duplicate Top-opportunities widget
  lower down was removed.
- **Communications:**
  - The board is big-number cards: Live, Actionable and Informational, then one card per question. Clicking a
    card filters the feed.
  - Feed rows are colour-bordered cards showing the icon, ticker, alert type, ▶ action, the priority score (large)
    and time remaining.
  - Score bars, status, source and timestamps are in the detail drawer.
  - `?preset=attention|…` opens a view directly.
- **Watch:** the decision board is the same big-number cards.

## Verify

- `tests/test_decision_cards_20261008.py` (gate `decision_cards_20261008`), the UI-standards guard, tsc and the vite
  build.
- After deploy, the next entry and stop alerts arrive as cards. Their Communications rows keep the same category,
  and their `symbols` include the ticker.
