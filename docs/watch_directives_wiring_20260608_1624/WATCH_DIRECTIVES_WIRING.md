# Watch Directives wired into Trade AI + Hermes (2026-06-08)

Operator standing directives (watch_directives, from the 2026-06-08 migration) now drive both engines.

## Service: `scripts/watch_directives_service.py` (cron */30 9-16 mkt hours, --apply)
For each ACTIVE directive:
- **Resolve symbols**: ticker→spec.symbol; sector/trend→spec.universe[] + spec.seed_symbols[].
- **Trade AI side** (if trade_ai_enabled): record watch_directive_hits (surfaced_by='trade_ai') with current
  analyst divergence + GO/WAIT qualification (promotion_status PROMOTED if in today's GO/WAIT else
  MONITORED_NO_QUALIFY); **promote** each symbol into the watched universe (watchlist_items,
  origin_system='operator_directive', directive_id, in_directive_watch) so news/analysis/scans cover it.
- **Hermes side** (if hermes_enabled): DRAIN hermes_directive_hits_staging (Hermes wrote leads there only —
  the FIREWALL) → watch_directive_hits (surfaced_by='hermes') + promote + mark drained.
- Stamp last_serviced_at. 12h per-(directive,symbol,surfaced_by) dedup. Advisory; no GO/WAIT/scoring/trade.

## Verified end-to-end
Test ticker directive (AVAV) → TA hit + promoted; Hermes staging proposal (RTX) → drained → hermes hit +
promoted; staging marked drained; analyst divergence carried onto hits (RTX aligned). Firewall held (Hermes
only wrote staging; service drained). Test artifacts cleaned → directive set empty, ready for real directives.

## Surfaced
- `GET /api/v2/watch-directives` — directives + recent hits + staging counts + promoted count.
- System→Hermes "Operator Watch Directives" card (directives table + recent hits + staging).

## How operator adds a directive (firewall: operator/app role only)
INSERT INTO watch_directives (kind,label,spec) VALUES
  ('ticker','My AAPL watch','{"symbol":"AAPL"}'),
  ('sector','Defense','{"gics_sector":"Industrials","universe":["LMT","RTX","NOC"]}'),
  ('trend','AI infra','{"keywords":["datacenter"],"seed_symbols":["NVDA","VRT"]}');
Then the service honors them next run; Hermes (SELECT-only) proposes leads into hermes_directive_hits_staging.
