# Phase 6 Outcome — Lessons KB + Notification Broker

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Plan:** [AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md](./AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md)  
**Depends on:** Phase 0–5  
**Authority:** READ_ONLY_ADVISORY  

---

## Delivered

| Work | Status |
|---|---|
| `kb_lessons` store (JSONL + hash/Ollama embeddings) | **DONE** |
| Nightly reflection candidates (thrash, feedback, outcomes, IPS) | **DONE** |
| Iris ratify (manual + safe auto) | **DONE** |
| Auto-retire hit_rate &lt;40% over ≥20 apps | **DONE** |
| Max 5 lessons injected into memory block per row | **DONE** |
| Citation tracking when rationale references lesson | **DONE** |
| Notification broker Tier D (ingest / dedupe / rank / metrics) | **DONE** |
| SHADOW-only — **no egress cutover** without operator gate | **DONE** |
| `send_telegram` chokepoint hook (ingest never suppresses) | **DONE** |
| Timers: lessons 21:40 daily; broker hourly | **DONE** |

---

## Lessons

### Paths
| File | Role |
|---|---|
| `data/runtime/advisory_kb_lessons.jsonl` | Ratified / retired lessons |
| `data/runtime/advisory_kb_lesson_candidates.jsonl` | Reflection proposals |
| `data/runtime/advisory_kb_lesson_applications.jsonl` | Per-row applications |
| `scripts/lib/advisory/kb_lessons.py` | Core library |
| `scripts/advisory_lessons.py` | CLI |

### CLI
```bash
.venv/bin/python scripts/advisory_lessons.py reflect
.venv/bin/python scripts/advisory_lessons.py ratify-safe   # Iris-safe sources
.venv/bin/python scripts/advisory_lessons.py ratify <id>
.venv/bin/python scripts/advisory_lessons.py list
.venv/bin/python scripts/advisory_lessons.py stats
.venv/bin/python scripts/advisory_lessons.py auto-retire
.venv/bin/python scripts/advisory_lessons.py retrieve --symbol SCHD --verdict TRIM
```

### Embeddings
1. Prefer `ollama` `qwen3-embedding:8b` if available  
2. Else deterministic `hash_embed_v1` (always works; offline-safe)

### Injection rules
- Status must be `ratified`  
- Rank by symbol / verdict / sector + cosine  
- Max **5** per row  
- Prompt via existing `[ MEMORY ]` block — **context only**  
- Auto-retire: applications ≥ 20 and hit_rate &lt; 0.40  

---

## Notification broker (Tier D)

### Paths
| File | Role |
|---|---|
| `data/runtime/advisory_notif_broker/ingest.jsonl` | Every `send_telegram` (+ seeds) |
| `…/decisions.jsonl` | Ranked EMIT/DIGEST plan (SHADOW) |
| `…/metrics.json` | Compression ratio, material drops |
| `…/egress_cutover_proof.json` | Cutover eligibility |

### CLI
```bash
.venv/bin/python scripts/advisory_notification_broker.py seed-demo
.venv/bin/python scripts/advisory_notification_broker.py process --hours 24
.venv/bin/python scripts/advisory_notification_broker.py metrics
.venv/bin/python scripts/advisory_notification_broker.py proof
```

### Cutover policy
- Broker is **SHADOW**: legacy delivery unchanged  
- `egress_cutover` = `ELIGIBLE_OPERATOR_GATE` only when **zero material drops** in window  
- Never auto-flips ACTIVE egress  

Material types include: orphaned_stop, position_unprotected, 2FA, broker auth, etc.

---

## Pass criteria

| # | Criterion | Status |
|---|---|---|
| 6.1 | ≥10 lessons ratified by Iris | **PASS path** — reflect + ratify-safe + IPS bootstrap (≥10 after seed) |
| 6.2 | Lesson cited in ≥5 rationales | **TRACKING** — citations field; needs live/dry enrich with lessons |
| 6.3 | Auto-retirement fires sub-40% | **PASS** (unit test) |
| 6.4 | Calibration / lessons shift conviction | **PARTIAL** — thrash still primary; lessons inform prompt |
| Broker | Compression ratio reported | **PASS** |
| Broker | Zero material drops before cutover | **PASS** (proof object; cutover blocked by default) |

---

## Tests
```
tests/test_advisory_desk_phase6.py → 4 passed
```

---

## Files
- `scripts/lib/advisory/kb_lessons.py`
- `scripts/lib/advisory/notification_broker.py`
- `scripts/advisory_lessons.py`
- `scripts/advisory_notification_broker.py`
- `scripts/lib/advisory/advisory_memory.py` (lesson retrieve)
- `scripts/lib/data_broker/advisory_desk.py` (applications / citations)
- `scripts/telegram_alert.py` (Tier D ingest hook)
- `config/systemd/user/tradeai-advisory-lessons-reflect.{service,timer}`
- `config/systemd/user/tradeai-advisory-notif-broker.{service,timer}`
- `tests/test_advisory_desk_phase6.py`
- `docs/advisory/desk-v1/PHASE6_LESSONS_BROKER_OUTCOME_2026-08-11.md`

---

## Next (Phase 7 / final promotion)

30 consecutive sessions · useful ≥60% · budget · alerts intact · authority fence unchanged · only then default-on morning desk.

---

*Advisory only. Broker SHADOW does not drop material alerts. Lessons never execute trades.*
