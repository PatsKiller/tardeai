# FRED / ALFRED provider

Status:      ACTIVE
as_of:       2026-08-17T11:10:54-04:00
Measured at: efcc51365 / not measured

Read-only macro provider over the official FRED/ALFRED JSON API.

## Capabilities

`macro.get_series`, `macro.get_series_snapshot`, `macro.get_latest_observation`,
`macro.get_vintage_dates`, `macro.get_vintage`, `macro.compare_vintages`,
`macro.get_decision_time_snapshot`, `macro.regime_inputs`.

## Configuration

`FRED_API_KEY` environment/parameter. Without a key the provider is
`NOT_CONFIGURED` and every query returns `NOT_CONFIGURED` honestly. The governed
series catalog is in `config/financial_senses/macro_series_catalog.json`
(and mirrored in `macro_catalog.py`).

## Governance

No series carries directional trade authority. `decision_use` is descriptive
only. See `MACRO_VINTAGE_POLICY.md`.
