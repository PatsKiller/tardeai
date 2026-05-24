# Phase 4 — LLM Fleet Observability

**Status:** COMPLETE
**Fleet status:** OK (0 alerts)

## Purpose

Operational visibility for the completed 5-model LLM fleet.

## Commands

```bash
# Fleet status
.venv/bin/python scripts/report_llm_fleet_status.py --verbose

# Alert check
.venv/bin/python scripts/check_llm_fleet_alerts.py --verbose

# Daily summary
.venv/bin/python scripts/write_daily_llm_fleet_summary.py --verbose

# Rollback observability
./scripts/rollback_phase4_observability.sh --status
```

## Model Fleet

| Role | Model | Size | Residency |
|------|-------|------|-----------|
| STANDARD/REALTIME | qwen3:14b | 10 GB | Always resident |
| MEDIA/PROSE | gemma3:4b | 3.3 GB | Always resident |
| EMBEDDING | nomic-embed-text | 274 MB | Always resident |
| HYBRID OFFLINE | qwen3-embedding:8b | 4.7 GB | Transient (prefetch) |
| DEEP REASONING | gemma3-overnight | 17 GB | Transient (deep window) |

## Alert Rules

Config: `config/llm_fleet_alert_rules.yaml`

Monitors: missing models, unexpected residency, VRAM pressure, latency, fallbacks, failures.

## API/Dashboard

Deferred — CLI reports are sufficient for current operational needs.
