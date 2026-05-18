# PAR-1 Source Registry Design

## Allowed Internal Sources
- auto_proposal_generator
- incubator_promoter
- system
- telegram_manual
- operator_manual
- strategy_watchpool
- paper_trade_logger
- manual

## Blocked Out-of-Scope Sources
- daily_momentum_scalp
- tradeai_daily_scalp
- external_scalp
- unknown_external

## Current Finding
All 83 proposals come from allowed internal sources. No leakage detected.

## Daily Momentum Scalp Boundary
Trade AI `momentum_scalp` YAML strategy is a valid internal strategy.
External "daily momentum scalp" workflows must use distinct source identifiers.
If external records enter the system, they must be tagged and filtered.

## Future Enforcement
- Add `source_system` column if needed for finer classification
- API filters should exclude blocked sources from paper-proposals response
- A-5/SP reports should exclude blocked sources
- Route audit should mark blocked sources as out_of_scope
