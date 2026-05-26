# Source Export: config/strategies/shared_risk_rules.yaml

| Field | Value |
|-------|-------|
| **Original Path** | `config/strategies/shared_risk_rules.yaml` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:49:17Z` |
| **SHA256** | `66b5e326610f4a77e4da3d81cc95f41ee68f6cf01e879d1e3a6c52a7bb115416` |
| **File Size** | 3049 bytes |

## Full Source

```yaml
version: "1.1"

global_disqualifiers:
  - id: REVERSE_SPLIT
    action: BLOCK
  - id: TRADING_HALT
    action: BLOCK
  - id: NO_STOP_DEFINED
    action: BLOCK
  - id: DATA_STALE
    action: BLOCK
  - id: DAILY_LOSS_LIMIT
    action: BLOCK_ALL
  - id: WEEKLY_LOSS_LIMIT
    action: BLOCK_ALL
  - id: STRATEGY_NOT_VALIDATED
    action: PAPER_ONLY
  - id: STRATEGY_KILLED
    action: BLOCK
  - id: STRATEGY_QUARANTINED
    action: PAPER_ONLY
  - id: GLOBAL_HALT
    action: BLOCK_ALL
  - id: LIVE_HALT
    action: BLOCK_LIVE
  - id: ACCOUNT_INELIGIBLE
    action: BLOCK
  - id: DATA_QUALITY_LOW
    action: BLOCK_OR_DOWNGRADE

risk_limits:
  daily_loss_limit_multiplier_testing: 4
  daily_loss_limit_multiplier_live: 3
  weekly_loss_limit_multiplier_testing: 8
  weekly_loss_limit_multiplier_live: 6
  max_simultaneous_positions_taxable: 3
  max_simultaneous_positions_ira: 5
  max_simultaneous_total: 8
  max_same_sector_positions: 1
  default_risk_per_trade: 150

market_regime_rules:
  vix_below_25:
    all_strategies: active
  vix_25_to_35:
    momentum_scalp:
      require_catalyst_verified: true
      min_rvol: 7.0
    gap_and_go:
      min_gap_pct: 10.0
    swing_breakout: paused
    sector_rotation:
      size_multiplier: 0.5
  vix_above_35:
    momentum_scalp: paused
    gap_and_go: paused
    swing_breakout: paused
    earnings_catalyst: paused
    sector_rotation:
      inverse_etfs_only: true
    income_add: active

source_quality_scores:
  sec_8k: 1.00
  company_press_release: 0.90
  analyst_upgrade: 0.85
  finnhub_verified: 0.80
  yahoo_news_verified: 0.75
  finviz_headline: 0.70
  stocktwits_high_volume: 0.55
  reddit_mention: 0.40
  stocktwits_low_volume: 0.35
  unknown_social: 0.20

catalyst_rules:
  social_only_max_grade: WATCH
  min_source_quality_for_go: 0.70
  min_source_quality_for_aplus: 0.85

llm_rules:
  llm_cannot_fabricate_data: true
  if_required_field_missing: DATA_INCOMPLETE
  forbidden_llm_actions:
    - fabricate_price
    - fabricate_volume
    - fabricate_catalyst
    - fabricate_financial_data
    - fabricate_tax_impact

recommendation_hierarchy:
  - DISCOVERED
  - QUALIFIED
  - CANDIDATE
  - WATCH
  - WAIT
  - PAPER_TRADE
  - LIVE_ELIGIBLE
  - RECOMMEND
  - APPROVAL_REQUIRED
  - EXECUTION_READY

lifecycle_stages:
  UNVALIDATED:
    min_duration_weeks: 2
    min_signals_for_advancement: 15
    min_avg_grade: B
    allowed_actions: [DISCOVERED, QUALIFIED, CANDIDATE, WATCH]
  TESTING:
    min_paper_trades: 30
    allowed_actions: [DISCOVERED, QUALIFIED, CANDIDATE, WATCH, WAIT, PAPER_TRADE]
  VALIDATED:
    initial_sizing_multiplier: 0.25
    step_up_after_trades: 30
    sizing_steps: [0.25, 0.5, 1.0]
    allowed_actions: [DISCOVERED, QUALIFIED, CANDIDATE, WATCH, WAIT, PAPER_TRADE, LIVE_ELIGIBLE, RECOMMEND, APPROVAL_REQUIRED, EXECUTION_READY]
  SCALING:
    max_weekly_gross: 5000
    watchlist_trigger_win_rate_drop_pct: 10
    killing_trigger_win_rate_drop_pct: 15
  KILLED:
    allowed_actions: [DISCOVERED]
    signals_suppressed: true
    revival_requires: full_unvalidated_cycle
```
