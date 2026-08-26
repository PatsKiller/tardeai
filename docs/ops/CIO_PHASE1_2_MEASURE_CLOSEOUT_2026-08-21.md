# CIO Phase 1–2 Measure Closeout — 2026-08-21

**Authority:** READ_ONLY_ADVISORY  
**CURRENT at closeout write:** promote target includes Phase 1 DecisionPayload + Phase 2 measure harness + daily timer.

## What is live

| Item | Value |
|------|--------|
| DecisionPayload capture | `AGENT_DECISION_PAYLOAD=1` on **portfolio-server** (`29-…`) **and producers** (`30-decision-payload.conf` on material-scan / telegram / reactive / measure / advisory-shadow). Code default still 0. |
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
payload_v1=0 coverage=0.0   # producers did not inherit the flag — HOLD-fallback lie
wakes≈2420 dual_path=True gate=NOT_PROMOTED influence_active=False
```

**Correction (evening):** that 5-day window is a **false start**. Producers now have `AGENT_DECISION_PAYLOAD=1`. Restart the clock the first day `with_decision_payload_v1_non_synth ≥ 1`. Measure honesty (0 v1 ⇒ `decision_payloads_available=false`) is in #435; promote before trusting the JSON.

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
