# Session Draft Schema — Stage 7
Fields: draft_id(UUID) · draft_version · environment(SHADOW/SIMULATION/LIVE; LIVE gated) ·
session_name · start/end · entry_cutoff · symbol_policy(list|universe rule) ·
account_roles[AccountSelection] · quantity_policy · gross_notional_cap · per_symbol_caps ·
per_account_caps · risk_cap · trade_count_cap · daily_loss_cap · fallback_policy ·
quick_add_config{unit,presets} · runner_policy · feature_policy_versions · notes · created_by.
Persistence maps into Stage 1 `active_trader_session_drafts` (append-only). Non-authority fields
(session_name, notes, created_by, version) are excluded from the authority hash.
