# Profit-Capture — Intrabar Path Ingestion + Path-Measured Premature-Exit (Phase 206c, 2026-06-06)

**Status:** Complete. Evidence-only analytics. No trading behavior changed. Validation **PASS 14/14**.

Closes the last honesty gap in the rule backtest: premature-exit cost can now be **measured** from the
actual intrabar price path instead of approximated. The single-peak MFE summary could not order a
stop trigger against later profit; replaying candidate rules against real bars can.

## What was missing

The MFE analyzer fetched intraday bars per trade but persisted only the summary (mfe/mae); the path
was discarded. `market_ohlcv_bars` covered only 9 symbols through 2026-05-07 — none of the measurable
trades' windows (2026-05-11 → 2026-06-05). So premature-exit cost was flagged `unknown` and recovery
was an upper bound.

## What was built

### Ingestion — `trade_intrabar_bars` + `trade_intrabar_ingest_log` (migration 206c)
`scripts/ingest_trade_intrabar_bars.py` fetches the ordered 5m OHLC path (yfinance, read-only) over
each closed measurable trade's [entry, exit] window and persists it. Honest gating: empty/out-of-range
fetches are recorded (`status=no_bars`), never fabricated. Dry-run default; `--apply` to write.

- Coverage: **29 of 34 measurable trades** got real paths (**3,043 bars**); 5 `no_bars`.
- **All 13 measurable winners have a path** (100% of the give-back population).

### Pricer — `scripts/profit_protection_path_pricer.py` (long-only)
Replays a candidate rule against the real bars: activates at the trigger R, ratchets the stop
(breakeven / lock-fraction / trailing-%), and exits when a bar's low breaches the stop (gap-down fills
at the open). Partial-TP sells half at the trigger if the path actually reaches it. Returns
path-measured captured profit + a `premature` flag (rule exited for less than the realized result).

### Backtest wiring — `scripts/backtest_profit_protection_rules.py`
- Per trade with a path → **path-measured** simulated capture + premature flag; otherwise single-peak
  fallback.
- `premature_exit_cost_known = (every evaluated trade was path-priced)`;
  `estimate_quality ∈ {path_measured, partial_path, upper_bound_single_peak}`.
- The data-quality gate's bar-detail requirement now uses the **real path bar count** (not the stale
  MFE summary count), and `reliable` requires a real intrabar path.

## Before / after (the decisive result)

The path reverses the single-peak optimism — measured premature-exit cost dominates avoided give-back:

| rule | single-peak (prior) | path-measured (now) |
|------|---------------------|---------------------|
| `trail5_after_2R` | avoided $447, premature **$0**, net **+$447**, n=2 | avoided $56.67, premature **$322.61**, **net −$265.94**, reliable n=8 |
| `lock50_after_2R` | net +$1,502 (raw) / +$118 (gated) | avoided $7.02, premature $347.97, **net −$340.95** |
| `breakeven_after_1R` | net ~$0 | premature $159.98, **net −$159.98** |
| best rule with evidence | trail5 (+, "high") | `swing_lock50_after_2R` **net −$49.96**, `path_measured`, reliable n=6 |

**Every protection rule is net-negative once premature-exit cost is path-measured.** On this sample the
trailing/lock stops fire on noisy intrabar pullbacks and cut winners short far more than they save
give-back. `premature_exit_cost_known=true`, `estimate_quality=path_measured`.

Concrete example — **ANY** (realized $310, single-peak claimed $532 "money left"): a 5% trail after 2R
would have stopped out intrabar at $3.26 for **$18.51** — a ~$291 premature-exit cost the single-peak
model scored as avoided give-back.

## Verdicts (unchanged posture, stronger basis)

Max reliable n = 8 (< 20 floor) → every rule and family **DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE**. Now the
block rests on path-measured evidence showing negative net, not just an upper-bound caveat. Nothing
grafted; no thresholds/strategy/GO-WAIT/orders changed.

## Endpoint / UI

`/api/v2/atm/profit-capture` surfaces `rule_backtest_net_usd`, `rule_backtest_premature_cost_usd`,
`estimate_quality`, `premature_exit_cost_known`, and selects the best rule **with evidence**. The v3
panel shows a "Best rule net" card (red when negative) and a qualifier: `avoided − premature = net`,
reliable n vs raw n, estimate quality (`path measured`), and `DO_NOT_GRAFT`.

## 1-minute tightening (addendum)

`ingest_trade_intrabar_bars.py --fine` upgrades trades to **1m** bars when the window ended within
`--fine-days` (default 30, yfinance's 1m lookback) **and** the 1m data reaches back to the entry
(coverage check), so we never trade a full 5m path for a partial 1m one. Fallback to 5m otherwise.

- Persisted: **30 trades on 1m (10,836 bars) + 1 on 5m**; coverage 91.2% (31/34).
- Finer granularity **reduced measured premature cost** (5m bars' wider high–low ranges over-trigger
  stops): `trail5_after_2R` premature $322.61→**$263.74** (net −$265.94→**−$207.07**),
  `lock50_after_2R` premature $347.97→**$289.10**. reliable n 8→**9**.
- Conclusion unchanged: still net-negative for the core rules, every rule and family
  **DO_NOT_GRAFT** (reliable n 9 < 20). 1m makes the premature-exit price more accurate, not the
  verdict different.

## Limitations (honest)

- 1m/5m granularity (not tick): intrabar fill order within a bar is unknown, so the pricer uses a
  conservative gap-down fill. 1m is used where it fully covers the window; older windows use 5m.
- 3 trades (no path) remain single-peak; their rule rows are labelled `partial_path` /
  `upper_bound_single_peak`, not `path_measured`.
- Long-only; the 34 measurable trades are all long.

## Safety proof

`ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, no `LIVE_TRADING`. yfinance is read-only market
data. No broker/order/stop/proposal/GO-WAIT/strategy/YAML mutation; no live enablement; no Phase 205
work; Hermes drain untouched. `validate_profit_capture_rule_quality.py` → **PASS 14/14**.
