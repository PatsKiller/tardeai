# PP-UX-1 API Contract

## New Fields Added to GET /api/v2/paper-proposals per proposal

| Field | Type | Source |
|-------|------|--------|
| strategy_description | string | YAML purpose |
| strategy_display_name | string | YAML display_name |
| strategy_timeframe_display | string | YAML timeframe |
| strategy_timeframe_class | string | YAML timeframe_class |
| strategy_status | string | YAML status |
| strategy_entry_criteria | array | YAML entry_criteria [{id, description}] |
| strategy_risk_rules | object | YAML risk {risk_per_trade_pct, max_position_size, max_daily_trades, stop_method, target_method} |
| strategy_disqualifiers | array | YAML auto_disqualifiers [{id, description}] |
| entry_rationale | string | Computed from scan_price + source |
| stop_rationale | string | Computed from entry/stop/ATR + stop_method |
| target_rationale | string | Computed from entry/target/R:R + target_method |
| staleness_policy | object | {max_age_hours, timeframe_class, is_stale, action} |
| approval_blockers | array | Structured [{gate, reason, action}] |

## New Fields in summary.incubator_diagnostics

| Field | Type | Description |
|-------|------|-------------|
| ready_count | int | Incubator candidates ready for promotion |
| pending_proposals | int | Current pending proposal count |
| pending_limit | int | Max pending proposals (20) |
| headroom | int | How many more proposals can be promoted |
| last_promotion_run | datetime | Last promoter run timestamp |
| promotion_blocked_reason | string | Why promotion is blocked, or null |

## Rules

- All new fields are read-only joins from existing data
- No INSERT/UPDATE/DELETE
- No broker calls, no order calls, no trade creation
- Missing values are explicit null, not hidden
- No NaN values
- Strategy YAML loaded once per strategy_id and cached per request
