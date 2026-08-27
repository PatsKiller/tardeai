# Watch Directives wiring (2026-06-08) — SUPERSEDED

> **This early wiring note is superseded by the canonical doc: [`docs/WATCH_DIRECTIVES.md`](../WATCH_DIRECTIVES.md).**
> It described the initial *flat watchlist-add* promotion, which was **replaced** by the real evaluation
> engine. Kept only as a historical record. The corrected behavior is below.

## What changed since this note
- **Promotion no longer flat-adds to `watchlist_items` with "PROMOTED if in today's GO/WAIT".** The service
  (`watch_directives_service.py`) now routes every promotion through
  `directive_promotion.promote_directive_lead` — a **real evaluation**: governor (source tier + Street
  divergence) → register provenance → enrich-on-demand → classify (**Bucket 2/3 only**; momentum_scalp /
  gap_and_go / SAME_DAY hard-excluded) → `strategy_watchpool`. Statuses are PROMOTED /
  MONITORED_NO_QUALIFY / REGISTERED_NO_TECH / STAGED_FOR_REVIEW.
- **Sector resolution** added: ETF + DISTINCT Finviz-sector constituents from `incubator_universe`
  (capped 25, logged) — not just operator `spec.universe`.
- **Auto-pause-on-cold** added for trend directives (7d reconfirm / 14d cold → paused, advisory).
- **UI** (`/v3/watchpool`), **provenance/create/promote endpoints**, **Telegram intents** (`watch`/`promote`),
  and the **morning-brief section** were added (D-3/D-4).

## Unchanged (still accurate)
- The Hermes **firewall**: Hermes SELECTs directives + writes proposed leads to
  `hermes_directive_hits_staging` only; the app role drains it. Hermes never writes operator/production tables.
- `GET /api/v2/watch-directives` + the System→Hermes "Operator Watch Directives" card.

See **[`docs/WATCH_DIRECTIVES.md`](../WATCH_DIRECTIVES.md)** for the full, current design (D-0 → D-4).
