# Hermes Phase 33A — Current Automation Inventory

**Date:** 2026-06-01
**Status:** COMPLETE — read-only audit

---

## Systemd User Timers (18 total)

| Timer | Schedule | Service | Hermes-Related |
|-------|----------|---------|---------------|
| hermes-autonomous-loop.timer | Daily 01:00 UTC (21:00 ET) | hermes-autonomous-loop.service | YES |
| portfolio-backup.timer | Daily 02:00 ET | portfolio-backup.service | NO |
| tradeai-continuous.timer | Daily 04:00 ET | tradeai-continuous.service | NO |
| portfolio-daily.timer | Daily 07:00 ET | portfolio-daily.service | NO |
| portfolio-monthly.timer | Monthly 07:05 ET | portfolio-monthly.service | NO |
| recovery-watch.timer | Daily 07:30 ET | recovery-watch.service | NO |
| aegis-surveillance.timer | Daily 08:00 ET | aegis-surveillance.service | NO |
| trade-ai-news-monitor.timer | Daily 09:00 ET | trade-ai-news-monitor.service | NO |
| aegis-overnight.timer | Daily 20:00 ET | aegis-overnight.service | NO |
| db-retention.timer | Weekly Sun 03:00 ET | db-retention.service | NO |
| portfolio-lookthrough.timer | Weekly Sun 06:00 ET | portfolio-lookthrough.service | NO |
| portfolio-price-cache.timer | Weekly Sun 19:00 ET | portfolio-price-cache.service | NO |
| portfolio-weekly.timer | Weekly Sun 20:00 ET | portfolio-weekly.service | NO |
| mcporter-token-refresh.timer | ~45 min recurring | mcporter-token-refresh.service | NO |
| + 4 system timers | Various | Ubuntu/snap | NO |

## Systemd User Services (Always-On)

| Service | Status | Port | Hermes-Related |
|---------|--------|------|---------------|
| hermes-gateway.service | active (running) | 18790 | YES |
| openclaw-gateway.service | active (running) | 18789 | NO (but agent platform) |

## Cron Jobs (187 active entries)

| Category | Count | Examples |
|----------|-------|---------|
| Alpaca reconciler | ~4 | Market open/close reconciliation |
| Quote refresh | ~8 | Pre-market, intraday, after-hours |
| News/enrichment | ~6 | Mid-day news, catalyst refresh |
| Intelligence/scoring | ~6 | Intraday intelligence, calibration |
| Digests/alerts | ~6 | Morning 8AM, evening 4PM, overnight 6PM |
| Strategy/config sync | ~4 | YAML sync, performance context |
| Data gap resolver | ~4 | Self-healing hourly during market |
| Governance/maturity | ~4 | GOV-1, Phase 9C, A1A checker |
| Research cadence | ~4 | ATP-2 scheduled research |
| Drive sync | ~2 | Hourly doc sync at :05 |
| Telegram | ~2 | Command handler polling every 2 min |
| Deep LLM window | ~2 | Friday extended, nightly gemma3 |
| Watchpool/incubator | ~4 | WATCH-2 alerts |
| Other | ~130+ | Various pipeline, health, cleanup jobs |

**None of the 187 cron jobs are Hermes research jobs.** Hermes uses systemd timers exclusively.

## Docker Services

| Container | Image | Status | Ports | Hermes-Related |
|-----------|-------|--------|-------|---------------|
| searxng | searxng/searxng:latest | Up | 127.0.0.1:18888→8080 | YES (shared infra) |

## Manual Scripts (Hermes-Specific)

| Script | Purpose | Last Used |
|--------|---------|-----------|
| scripts/searxng_manual_query.py | Manual SearXNG queries | Phase 23 |
| scripts/hermes_librarian_dry_run.py | Librarian analysis over Hermes rows | Phase 21 |
| scripts/hermes_expanded_librarian_dry_run.py | Expanded analysis over 4 safe views | Phase 30 |
| scripts/hermes_staging_ingest.py | Controlled staging ingestion | Phase 1H |
| scripts/hermes_embedding_worker.py | Embedding worker (--dry-run/--apply) | Phase 2A |
| scripts/hermes_autonomous_loop.py | Autonomous ticker challenger | Active via timer |
| scripts/hermes_browse_proxy.py | Two-step browse proxy | Phase 1E+ |

## Risk Ratings

| Service | Risk | Reason |
|---------|------|--------|
| hermes-autonomous-loop | LOW | Capped 2 rows/day, staged only, kill switch |
| hermes-gateway | LOW | API gateway, no DB writes |
| searxng | LOW | Localhost only, no Hermes integration |
| Trade AI cron (187) | MEDIUM | Many jobs, legacy format, no centralized kill switch |
