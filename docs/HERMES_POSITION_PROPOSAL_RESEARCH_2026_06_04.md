# Hermes auto-research of held positions + open proposals — 2026-06-04

Status:      HISTORICAL
as_of:       2026-06-04T20:44:22-04:00
Measured at: efcc51365 / not measured

Closes the gap found this session: Hermes's 24/7 loop only researched **closed trades** (retrospective
reflection). It did **not** research currently-held positions or open proposals — those were covered
only by TradeAI's daily/intraday enrichment crons, not by the always-on engine.

## What changed
`scripts/hermes_autonomous_loop.py` → `get_ticker_targets()` now selects, prioritized:
| pri | Source | Tables | Dedup |
|-----|--------|--------|-------|
| 0 | **HELD positions, all accounts** | `trades` + `paper_trades` where `status=open` | re-research if not done in **last 24h** (around-the-clock cycling) |
| 1 | **OPEN proposals** | `paper_trade_proposals` status ∈ (PENDING, APPROVED, APPROVED_FOR_PAPER_TEST, MODIFIED) | last 24h window |
| 2 | CLOSED trades (reflection) | `hermes_v_trade_reflection_context` | lifetime dedup (one-time, unchanged) |

- **All 6 accounts covered:** schwab_rollover_ira, schwab_taxable, schwab_roth_ira, alpaca_paper,
  ALPACA_PAPER, TOS_PAPER (56 distinct held tickers at build time).
- **CUSIP filter:** `symbol ~ '^[A-Z]{1,5}$'` — excludes Schwab bond/security CUSIPs (e.g.
  `731094207`) that are useless as LLM research targets; keeps real equity/fund tickers.
- **Dedup is per-symbol** (DISTINCT ON, min priority) so a symbol that is both held and a closed
  trade is researched once, at its highest priority.
- **Throughput:** coordinator runs `ticker_challenger --apply --max-rows 3` every `*/15` (≈288
  research slots/day) — ample to cycle 56 held + proposals daily and still leave room for closed-trade
  reflection. Held/proposals are prioritized so live portfolio relevance comes first.

No new table, no new cron, no change to the coordinator — the expansion rides the **existing**
autonomous-loop → validate → `--apply` insert → coordinator promote/embed pipeline.

## Verification (end-to-end)
- Target selection: held positions returned first (ADBE, AGNC, AMANX, AMC, APAM, ARKQ…); **0 CUSIPs**
  after the filter.
- Dry-run cycle: ADBE (held_position) → gemma3:4b → VALIDATED.
- **`--apply` cycle: ADBE (held_position) → VALIDATED confidence 0.85 → COMMITTED id=788** →
  `hermes_research_intelligence` 782→783, newest row `ADBE / ticker_thesis_challenge / staged / 0.85`.
- Coordinator confirmed to invoke the loop with `--apply` (`hermes_coordinator.py:112`), so this runs
  in production every `*/15`.

## Dynamic all-account detection — verified
The held-position query is **account-agnostic**: it has **no hardcoded account list**, only
`status=open` across `trades` + `paper_trades`. Consequences (verified 2026-06-04):
- **Add:** a new open position in ANY account — including a brand-new account that starts appearing
  in `trades`/`paper_trades` — is auto-included on the next `*/15` tick. Nothing to update.
- **Delete:** when a position is sold, its row flips to `closed`/`cancelled`, so it auto-drops from
  the held set (confirmed: `trades` 152 open / 200 closed; `paper_trades` open/closed/cancelled).
- **Coverage at build time:** all 6 accounts detected — schwab_rollover_ira (53), schwab_taxable
  (30), schwab_roth_ira (5), alpaca_paper (3), ALPACA_PAPER (2), TOS_PAPER (1).
- **Completeness:** no other current-holdings table holds uncovered accounts (`holdings` stale/1-row,
  `portfolio_snapshots` has no account dimension, no `schwab_positions`/`account_positions` tables) —
  so `trades`+`paper_trades` is the authoritative, complete source.
- **Standing assumption:** held detection is complete *as long as every account's open positions flow
  into `trades` or `paper_trades`*. If a future broker writes positions to a new table, add it to the
  `held` CTE — it is the single point to extend.

## Scope note (honest)
- This makes **Hermes** (the always-on engine) research what we *hold* and what's *proposed* — a new
  capability. TradeAI's enrichment crons (holdings_llm_refresh, asset_intelligence, proposal_enrichment)
  still run; this adds Hermes's thesis-challenge lens on top, around the clock.
- `open_trade_intelligence_snapshots` is still empty (a separate dormant table) — not used here; held
  positions are sourced from `trades`/`paper_trades`, which are live.

---
*Built 2026-06-04. Additive change to `get_ticker_targets`; verified by one real `--apply` cycle
committing a held-position research row. Runs via the existing coordinator `*/15`.*
