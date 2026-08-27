# Newly-Divergent Symbol Alerting (2026-06-08)
pro_analyst_monitor now ALERTS when an internal-vs-Street divergence first appears.
- On `newly_divergent` (diff vs prior snapshot), writes an idempotent SIEM `alert_events` row per symbol
  (alert_type='analyst_alert', alert_uid='pro_analyst_divergence:<symbol>', ON CONFLICT DO UPDATE → no re-spam
  while it stays divergent) + Telegram (with `--send`, now in the 06:10 cron).
- Verified: LHX + RKLB (internal bearish vs Street bullish) → 2 analyst_alert rows written; note surfaced.
- Fires once per symbol when it first diverges; clears from newly_divergent next run (still tracked in
  divergent_symbols). Resolved divergences logged via resolved_divergence. Advisory; no scoring/trade change.
