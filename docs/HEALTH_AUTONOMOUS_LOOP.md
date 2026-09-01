# Health autonomous fix loop (no manual operator / no one-off agent fixes)

Status:      ACTIVE
as_of:       2026-08-08T18:02:23-04:00
Measured at: efcc51365 / not measured

## Who fixes what

| Layer | Schedule | Role |
|-------|----------|------|
| `health_agent.py` | cron `*/15` | Detect findings → **auto_remediate** producers immediately → enqueue rest |
| `claude_escalation_handler.py --tier1-only` | cron `*/10` | Drain queue → allowlisted retry → **verify** → fixed or re-arm |
| `process_watchlist_agent_jobs.py` | cron (weekend/night/market) | Drain decision-feeding backlog (`AGENT_JOBS_LOCK_HELD_EXTERNALLY=1`) |
| `ops_agent_daemon.py --apply` | always-on | Layer-1 ops ladder (eligible producers) |
| `heal_trade_ai_session_cache.py` | via health/escalation | SETUPS `run_date` session heal |

## Rules

1. **Do not hand-run remediations** for production — fix the map/allowlist/cron instead.
2. **Success = verify**, not exit 0 (paper stuck, jobs, backup, SETUPS, scalp GO).
3. **never_auto_remediate**: stops, SIEM, tokens, audit ledger (operator CTA only).
4. Exhausted retries **re-arm in 30m** with escalated job limit — no human requeue.
5. Double-flock is forbidden: outer flock must set `AGENT_JOBS_LOCK_HELD_EXTERNALLY=1`.

## Root-cause memory (iterative autonomous fixes)

Durable store: `data/runtime/health_root_cause_memory.json`
Audit trail: `logs/health_root_cause_memory.jsonl`
Module: `scripts/lib/health_root_cause_memory.py`

For hard residuals the agent **records** error → root_cause → how_to_fix, then walks a **strategy ladder** so the same thrashing command is not re-run forever:

| Finding | Iterative remediator | Ladder (high level) |
|---------|----------------------|---------------------|
| `scalp_catalyst_verification_dead` | `remediate_scalp_go_dark.py` | diagnose → rescan → social+rescan → news+rescan → finviz lane → hold (low_max_score_regime) |
| `pipeline_failures` | `remediate_pipeline_failures.py` | diagnose → clear zombie pipeline_runs → reset stuck jobs → re-run orchestrator → small/medium job drain |

Root-cause codes (examples):

- **scalp**: `catalyst_cap_bug`, `low_max_score_regime`, `news_or_social_feed_dead`, `finviz_metrics_missing`, `scanner_not_running`
- **pipeline**: `orchestrator_stage_fail`, `agent_flash_circuit_open`, `db_connection_blip`, `zombie_running_rows`, `jobs_sla_backlog`

On verify-fail, escalation also upgrades bare map cmds to these iterative remediator scripts.

## Policy

- `config/health_agent_policy.json` → `auto_remediate.finding_types` + `remediation_map` + `never_auto_remediate`
- `config/claude_escalation_allowlist.yaml` → safe scripts only

## Continuous daemon (no cron required for score)

| Unit | Role |
|------|------|
| `tradeai-health-agent.service` | `health_agent_daemon.py` loop — score + auto-remediate; when unhealthy/degraded also runs escalation `--tier1-only` |
| `tradeai-ops-agent.service` | Layer-1 ops inspect loop |

Adaptive cadence (`config/health_agent_policy.json` → `daemon.cadence_seconds`):

| status | default sleep |
|--------|----------------|
| healthy | 1800s (30m) |
| degraded | 300s (5m) |
| unhealthy | 90s |

Shared flock `/tmp/health_agent.lock` with cron `*/15` — safe to keep both.

```bash
systemctl --user status tradeai-health-agent.service
journalctl --user -u tradeai-health-agent.service -f
```
