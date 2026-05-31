# Hermes Phase 3A — Autonomous Loop Implementation Plan

**Status:** PLAN ONLY — not implemented

---

## Proposed Scripts

| Script | Purpose | Status |
|--------|---------|--------|
| `scripts/hermes_autonomous_loop.py` | Main runner with loop types, caps, lockfile | TO CREATE in Phase 3B |
| `scripts/hermes_research_prompt.py` | Hardened prompt builder | EXISTS |
| `scripts/hermes_staging_ingest.py` | Validated ingestion | EXISTS |
| `scripts/hermes_embedding_worker.py` | Embedding worker | EXISTS (separate gate) |

## Proposed Config

```yaml
# hermes_sidecar/config/autonomous_loop.yaml (DRAFT)
loops:
  ticker_challenger:
    enabled: false  # must be explicitly enabled
    schedule: "17:00 ET daily"
    max_rows: 5
    model: gemma3:12b
    views: [hermes_v_ticker_context, hermes_v_trade_reflection_context, hermes_v_proposal_context]
  portfolio_reflection:
    enabled: false
    schedule: "22:00 ET daily"
    max_rows: 3
    model: gemma3:12b
    views: [hermes_v_trade_reflection_context, hermes_v_portfolio_context]
  pipeline_quality:
    enabled: false
    schedule: "08:00, 16:00 ET daily"
    max_rows: 5
    model: gemma3:4b
    views: [hermes_v_pipeline_health_context]

global:
  daily_row_cap: 10
  daily_model_call_cap: 15
  max_runtime_seconds: 600
  lockfile: /tmp/hermes_autonomous_loop.lock
  kill_file: hermes_sidecar/.hermes/DISABLED
  dry_run_default: true
```

## Proposed run_id Strategy

Format: `auto_{loop_type}_{YYYYMMDD}_{HHmm}`

Example: `auto_ticker_challenger_20260531_1700`

Stored in evidence_json.run_id for traceability.

## Proposed Manual Commands

```bash
# Dry-run (no DB writes)
.venv/bin/python scripts/hermes_autonomous_loop.py --loop ticker_challenger --dry-run

# Apply (writes to staging)
.venv/bin/python scripts/hermes_autonomous_loop.py --loop ticker_challenger --apply --max-rows 3

# Disable all
touch hermes_sidecar/.hermes/DISABLED

# Re-enable
rm hermes_sidecar/.hermes/DISABLED
```

## Test Plan

| Test | Method |
|------|--------|
| Dry-run produces valid payloads | Manual |
| Kill file aborts loop | Manual |
| Lockfile prevents concurrent runs | Manual |
| Row cap enforced | Manual |
| Validator rejects bad output | Existing 9 tests |
| Timeout enforced | Manual |

## Rollback Plan

1. Stop timer: `systemctl --user stop hermes-autonomous-loop.timer`
2. Disable: `systemctl --user disable hermes-autonomous-loop.timer`
3. Kill file: `touch hermes_sidecar/.hermes/DISABLED`
4. Remove rows: `DELETE FROM hermes_research_intelligence WHERE evidence_json->>'run_id' LIKE 'auto_%'`
5. Keep audit logs

## WARNING

**DO NOT ACTIVATE** until Phase 3B-3F gates are passed and operator approves.
