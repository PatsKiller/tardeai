# CIO Memory Shadow Measure — Phase 2 start (2026-08-21)

**READ_ONLY_ADVISORY.** `MEMORY_BEHAVIOR_INFLUENCE` stays **0**.

## Window

| Field | Value |
|-------|--------|
| Capture start | 2026-08-21 (CURRENT tip with `AGENT_DECISION_PAYLOAD=1`) |
| Decision-level evidence target | **≥ 5 trading days** of DecisionPayload@v1 corpus |
| Earliest promotion reconsideration | after window + measured metrics (not a calendar promise) |

## Runtime posture

| Flag | Value |
|------|--------|
| `MEMORY_PROVIDER` | `durable` |
| `MEMORY_SHADOW` | `1` |
| `MEMORY_BEHAVIOR_INFLUENCE` | **`0`** |
| `GOVERNED_MEMORY_ADVISORY_INFLUENCE` | `SHADOW` (measure posture) |
| `AGENT_DECISION_PAYLOAD` | **`1`** (measuring) |

Drop-in: `~/.config/systemd/user/portfolio-server.service.d/29-decision-payload-measure.conf`

## TTL policy (operator choice 2026-08-21)

**KEEP_CURRENT_TTLS** — do not make OPERATOR_EXPLICIT_PREFERENCE non-expiring yet. Revisit after first weekly report.

## Measure command

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT
export PYTHONPATH=.:scripts
python3 scripts/run_memory_shadow_measure.py
# artifact: data/cio/memory_shadow_measure_latest.json
```

## Metrics

`memory_retrieval_rate` · `memory_changed_decision` · `memory_changed_notification` ·  
`operator_recall_hit` / `memory_false_positive` may stay `UNAVAILABLE` until labeled corpus exists ·  
`truth_override_attempts` must remain 0.

## Promotion gate

Do **not** weaken. With influence OFF, verdict must remain `NOT_PROMOTED`.
