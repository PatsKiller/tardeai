# CIO Phase 1–2 Measure Closeout — 2026-08-21

**Authority:** READ_ONLY_ADVISORY  
**CURRENT at closeout write:** promote target includes Phase 1 DecisionPayload + Phase 2 measure harness + daily timer.

## What is live

| Item | Value |
|------|--------|
| DecisionPayload capture | `AGENT_DECISION_PAYLOAD=1` (drop-in `29-decision-payload-measure.conf`) |
| Memory influence | **`MEMORY_BEHAVIOR_INFLUENCE=0`** |
| Memory provider / shadow | `durable` / `1` |
| Governed memory posture | `SHADOW` |
| TTL policy | **KEEP_CURRENT_TTLS** (operator choice) |
| Daily timer | `tradeai-cio-memory-shadow-measure.timer` @ **06:20** local |
| Measure artifact | `data/cio/memory_shadow_measure_latest.json` |

## Manual test (2026-08-21 ~11:58 EDT)

```text
systemctl --user start tradeai-cio-memory-shadow-measure.service
→ status=0/SUCCESS
payload_v1=0 coverage=0.0   # window just opened; corpus will fill over sessions
wakes≈2420 dual_path=True gate=NOT_PROMOTED influence_active=False
```

Next timer fire: **2026-08-22 06:20 EDT**.

## PRs

| PR | Topic |
|----|--------|
| #430 | DecisionPayload@v1 (flag default OFF in code) |
| #431 | Shadow measure harness |
| #432 | Daily systemd timer |
| (this) | Docs closeout + Drive sync |

## 5-trading-day window

| Start | 2026-08-21 |
|-------|------------|
| Do | Let material_scan / IIC / freeform emit payloads; daily measure refreshes artifact |
| Do not | Flip `MEMORY_BEHAVIOR_INFLUENCE` or weaken promotion_gate |
| After ≥5 trading days | Re-read metrics; only then reconsider influence |

## Operator commands

```bash
systemctl --user start tradeai-cio-memory-shadow-measure.service
systemctl --user list-timers | grep memory-shadow
cd ~/trade-ai-releases/portfolio-server/CURRENT && PYTHONPATH=.:scripts \
  python3 scripts/run_memory_shadow_measure.py
```

## Drive

Synced to Trade_AI_Docs_v2 under `docs/ops/` (targeted upload after merge).
