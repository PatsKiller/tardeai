# Source Export: config/llm_fleet_alert_rules.yaml

| Field | Value |
|-------|-------|
| **Original Path** | `config/llm_fleet_alert_rules.yaml` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:50:11Z` |
| **SHA256** | `610cac2a24fcea00f945d917f5ab4d96704993871f178c5b81ae78b044db233b` |
| **File Size** | 552 bytes |

## Full Source

```yaml
# LLM Fleet Alert Rules — Phase 4 Observability
# Read-only monitoring. Does NOT change routing or behavior.

phase: phase4_observability
enabled: true

expected_resident_models:
  outside_deep_window:
    - qwen3:14b
    - gemma3:4b
    - nomic-embed-text
  transient_allowed:
    - qwen3-embedding:8b
    - gemma3-overnight

thresholds:
  min_free_vram_gb_warn: 1.0
  qwen3_latency_ms_warn: 30000
  gemma3_4b_latency_ms_warn: 10000
  nomic_latency_ms_warn: 1000
  fallback_rate_warn_pct: 10
  failure_rate_warn_pct: 5
  deep_restore_required: true
```
