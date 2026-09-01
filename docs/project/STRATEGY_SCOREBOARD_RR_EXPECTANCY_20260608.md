# Strategy Scoreboard — R:R, Expectancy & Self-Healing Freshness (2026-06-08)

Status:      ACTIVE
as_of:       2026-06-08T09:17:48-04:00
Measured at: efcc51365 / not measured

Strategy Hub scoreboard (`/api/v2/paper-trade-readiness`, real paper trades) enhanced:
- **R:R column** — realized payoff ratio = avg win / avg loss; color-coded (≥2 green, ≥1 amber, <1 red).
- **Expectancy column** — per-trade $ expectancy = net P&L / closed trades (green if >0).
- **No-loss strategies** (100% win rate, e.g. fib_retracement_bounce) show R:R/PF as **∞** (not "—"): with zero
  losing trades the ratios are mathematically undefined, not missing data.
- **Expectancy-aware status (display only):** a win-rate<55% strategy with positive expectancy AND
  (R:R≥2 or PF≥1.5 or no losses) now shows "**profitable · low WR**" (teal) instead of red "below gate";
  thin samples (<10 trades) flagged with ⚠. The real `governance_state` / GO-WAIT gate is UNCHANGED — this is
  labeling only. Rationale: win-rate-only gating wrongly condemns high-payoff/low-win-rate strategies
  (e.g. swing_trade: 16.7% WR but R:R 20.83, PF 10.42, +$41/trade expectancy).
- **Self-healing freshness guard:** the readiness endpoint recomputes the stats file if missing or >3h old
  (root-cause fix — no scheduled regen existed; scoreboard had gone ~1 week stale) + exposes `data_age_min`.

Backing: `scripts/paper_trade_statistics.py` adds avg_win/avg_loss/rr/expectancy/no_losses per strategy.
Open governance decision (unchanged): cull/promote by expectancy, not win-rate.
