# Cost model and caps

## Pricing snapshot (official docs 2026-08-03)

| Model | Cache-hit in | Cache-miss in | Output | / 1M tokens USD |
|-------|-------------:|--------------:|-------:|-----------------|
| deepseek-v4-flash | 0.0028 | 0.14 | 0.28 | |
| deepseek-v4-pro | 0.003625 | 0.435 | 0.87 | |

Source: https://api-docs.deepseek.com/quick_start/pricing

## Accounting

`lib.llm_model_registry.estimate_usd_cost` multiplies provider token usage by registry snapshot.
`cost_basis=provider_usage_x_registry_snapshot` — **not** billed actual unless finance-reconciled.

Character-based relative units are **not** used for DeepSeek estimates in the new client.

## Caps (process registry v3)

| Process | daily_cost_cap_usd |
|---------|-------------------:|
| watchlist_maria_priority | 5.0 |

Global daily USD hard cap + service enforcement: **PARTIAL** (fields present for selected processes; gate wiring residual).

PRO_MAX requires operator cost confirmation at policy resolve time.
