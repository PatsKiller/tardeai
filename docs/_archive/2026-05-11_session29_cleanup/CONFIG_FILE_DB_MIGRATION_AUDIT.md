# Config File DB Migration Audit

Generated: 2026-05-09T12:10:51.274095
Total files scanned: 976

## Summary by Category

| Category | Count | Recommendation |
|----------|-------|----------------|
| agent_config | 5 | migrate_to_generic_config_documents |
| authoritative_state | 4 | keep_as_file |
| cache | 391 | keep_as_file, keep_as_file_and_cache |
| frontend_package_config | 5 | keep_as_file |
| pipeline_config | 1 | migrate_to_domain_table |
| portfolio_config | 3 | migrate_to_generic_config_documents |
| report_output | 21 | keep_as_file |
| runtime_config | 6 | migrate_to_generic_config_documents |
| runtime_state | 168 | keep_as_file_and_cache |
| screener_config | 1 | migrate_to_domain_table |
| strategy_config | 23 | migrate_to_domain_table |
| unknown | 348 | keep_as_file |

## Summary by Recommendation

| Recommendation | Count |
|----------------|-------|
| keep_as_file | 766 |
| keep_as_file_and_cache | 171 |
| migrate_to_domain_table | 25 |
| migrate_to_generic_config_documents | 14 |

## Files Recommended for DB Migration

| Path | Category | Size | Shape |
|------|----------|------|-------|
| `./agents/openai.yaml` | agent_config | 220 | object |
| `./config/agents.json` | agent_config | 13694 | invalid_or_binary |
| `./config/agents.yaml` | agent_config | 6033 | object |
| `./config/agents_data_sources.yaml` | agent_config | 4274 | object |
| `./config/agents_sec_interaction.yaml` | agent_config | 2909 | object |
| `./config/pipeline_controller.bootstrap.yaml` | pipeline_config | 7421 | object |
| `./assets/portfolio_accounts.yaml` | portfolio_config | 25508 | object |
| `./assets/portfolio_intent.yaml` | portfolio_config | 3958 | object |
| `./assets/weights.yaml` | portfolio_config | 3180 | object |
| `./config/agent_discovery_config.json` | runtime_config | 1715 | object |
| `./config/agent_runtime.json` | runtime_config | 3848 | object |
| `./config/asset_classification_rules.json` | runtime_config | 2954 | object |
| `./config/indicator_strategies.yaml` | runtime_config | 5889 | object |
| `./config/manual_beta_overrides.json` | runtime_config | 7704 | object |
| `./config/thesis.json` | runtime_config | 792 | object |
| `./assets/screeners.yaml` | screener_config | 1893 | object |
| `./config/strategies/bond_income.yaml` | strategy_config | 3028 | object |
| `./config/strategies/cash_or_stable.yaml` | strategy_config | 2824 | object |
| `./config/strategies/core_growth_compounder.yaml` | strategy_config | 2990 | object |
| `./config/strategies/core_index.yaml` | strategy_config | 2630 | object |
| `./config/strategies/covered_call_income.yaml` | strategy_config | 3155 | object |
| `./config/strategies/defense_thesis.yaml` | strategy_config | 3433 | object |
| `./config/strategies/dividend_growth_compounder.yaml` | strategy_config | 3051 | object |
| `./config/strategies/earnings_catalyst.yaml` | strategy_config | 2149 | object |
| `./config/strategies/gap_and_go.yaml` | strategy_config | 1967 | object |
| `./config/strategies/high_yield_income_bdc.yaml` | strategy_config | 3104 | object |
| `./config/strategies/income_add.yaml` | strategy_config | 2355 | object |
| `./config/strategies/international_dividend.yaml` | strategy_config | 3191 | object |
| `./config/strategies/momentum_scalp.yaml` | strategy_config | 3502 | object |
| `./config/strategies/recommendation_schema.yaml` | strategy_config | 2082 | object |
| `./config/strategies/recovery_watch.yaml` | strategy_config | 3002 | object |
| `./config/strategies/reit_income.yaml` | strategy_config | 3137 | object |
| `./config/strategies/sector_rotation.yaml` | strategy_config | 1869 | object |
| `./config/strategies/shared_risk_rules.yaml` | strategy_config | 3049 | object |
| `./config/strategies/speculative_growth.yaml` | strategy_config | 2910 | object |
| `./config/strategies/strategy_schema.yaml` | strategy_config | 727 | object |
| `./config/strategies/swing_breakout.yaml` | strategy_config | 2148 | object |
| `./config/strategies/swing_trade.yaml` | strategy_config | 2809 | object |
| `./config/strategies/tax_loss_harvest.yaml` | strategy_config | 3216 | object |

## Authoritative State Files (DO NOT migrate blindly)

| Path | Size | Recommendation | Reason |
|------|------|----------------|--------|
| `./data/portfolios/state/ai_deep_holdings.json` | 3654 | keep_as_file | CRITICAL: portfolio authority file. DB mirror only. |
| `./data/portfolios/state/data/portfolios/state/holdings.json` | 202627 | keep_as_file | CRITICAL: portfolio authority file. DB mirror only. |
| `./data/portfolios/state/holdings.json` | 188936 | keep_as_file | CRITICAL: portfolio authority file. DB mirror only. |
| `./data/portfolios/state/personal_situation.json` | 10473 | keep_as_file | Personal data — DB table already exists, audit/compare only |

## Files Kept as File (766 files)

Disposable caches, generated artifacts, frontend config. No action needed.