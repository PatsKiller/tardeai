# Risk & Session Limit Matrix — Stage 7
Caps: gross_notional_cap, per_symbol_caps, per_account_caps, risk_cap, trade_count_cap,
daily_loss_cap (all non-negative, validated). Sizing validates against caps and stale
buying-power snapshots (caller supplies the snapshot; sizing is pure). Rounding floors shares;
remainder explicit. Feature controls cannot enlarge any cap or authority.
