# Command Center v3 Metric Definitions

**Status:** Active  
**Owner:** Command Center v3 / Portfolio Server  
**Created:** 2026-06-16  
**Registry:** `config/metric_registry.yaml`

## Purpose

This document defines the trust contract for top-level KPIs in Command Center v3.
The prior issue was not that the metrics were necessarily wrong; it was that several
surfaces could display similar labels with different scopes, especially win rate and
live-blocked status. A metric can only be trusted when the operator can see its scope,
denominator, source, and freshness.

## Rules

1. Every headline KPI must map to a `metric_id` in `config/metric_registry.yaml`.
2. The UI must not show ambiguous labels such as bare `WIN RATE` without scope.
3. Journal win rate and paper-validation win rate are separate metrics.
4. General live-trading status and protective-stop authorization are separate metrics.
5. Stale metrics must show WARN, not a bare value.
6. Metric consistency is checked by `scripts/validate_metric_consistency.py`.

## Key definitions

| Metric ID | UI Label | Scope | Denominator |
|---|---|---|---|
| `portfolio_value` | Portfolio value | all included accounts in holdings state | dollars |
| `today_pnl` | Today P&L | mark-to-market day change | dollars and percent |
| `journal_pnl` | Journal P&L | realized journal-tracked P&L | dollars |
| `journal_win_rate` | Journal win rate | journal-counted closed trades | journal closed trade count |
| `paper_validation_win_rate` | Paper validation win rate | paper trades eligible for validation gate | closed paper trade count |
| `setup_counts` | Setups | GO / WAIT / NOGO setup counts | count by setup state |
| `market_regime` | Regime | current regime classification | label + confidence |
| `vix` | VIX | latest VIX observation | index level |
| `last_pipeline_run` | Last run | latest relevant pipeline marker | timestamp / run ID |
| `live_blocked_state` | Live trading status | global live trading interlock | enum |
| `broker_protective_stop_state` | Protective stop status | standing protective-stop authorization and stop lifecycle health | count by state |
| `rotation_candidates` | Rotation candidates | advisory trim/add/rotate candidates | count by action class |

## Operator-facing label examples

Correct:

```text
Journal win rate: 55.3% · 121 journal trades
Paper validation: 45.8% · 24 closed paper trades
Protective stops: 8 healthy · 0 alert
Live trading: blocked globally · protective stops authorized
```

Incorrect:

```text
WIN RATE 55.3% · 121
LIVE BLOCKED
```

## Validation

Run:

```bash
python3 scripts/validate_metric_consistency.py --strict
```

A strict failure does not mean a trade is unsafe; it means the UI can mislead the
operator and must be corrected before a trust-hardening release is tagged.

## Safety

This metric registry does not authorize live trading, does not alter broker behavior,
and does not change any protective-stop envelope. It only makes displayed values
traceable and consistent.
