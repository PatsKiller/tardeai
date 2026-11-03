# Approved Home v007 additive data contract

`GET /api/v2/market-risk/latest` gains optional `home_v007: HomeMarketRiskContext@v1`. Existing fields keep their contracts.

- `symbols[SYMBOL]`: quote/session, day_change, since_exit, analysis_references, guarded headlines, next_event, CIO stance/conviction/reason, volume_vs_20d, since_exit_history. Each measured field has value/state/as_of/source/age_seconds; missing inputs carry null and remediation.
- `risk`: existing score history, latest score delta, all nine canonical category chips and next_evaluation. No tier/conviction/trigger is synthesized.
- `hedge`: existing trigger progress and observed inverse-fund moves, never a suggested position/order.
- `budgets`: existing measurement plus plain breach/clear condition. Intentional-decision writing stays unavailable until the existing operator-only route's exact subtype is proved; no fake decision receipt is created.

Analysis references use only levels already present in stored re-entry stages. They are distances from an observed price, never a new stop or order level. Data adapter and synthetic tests are being wired independently of the STOPPED-OUT NOW reader hotfix, which ships first. No real portfolio values or private mockup are committed.
