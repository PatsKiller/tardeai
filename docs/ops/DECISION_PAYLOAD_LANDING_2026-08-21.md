# DecisionPayload landing check — 2026-08-21 19:31 ET

**Authority:** READ_ONLY_ADVISORY. Capture only. No flag flips.

**CURRENT pin:** `cf5768a6` at `2026-08-21T19:20:47-04:00` (`…192047`).
**Store:** `data/cio/agent_run_traces.jsonl` (CURRENT and rebuild share the inode).

## Counts

| | |
|---|---|
| DecisionPayload@v1 rows **all-time** | **213** |
| **First row** | **2026-08-21T18:15:38Z** (14:15 ET **today**) |
| Last row at check | 2026-08-21T23:30:42Z (19:30 ET) |
| Rows **since pin 19:20:47 ET** | **27** |

Phase 0’s 2,414 wakes with **zero** payloads and “flag already on” are both true:
the flag **is** the gate (`emit_decision_payload` returns immediately when
`AGENT_DECISION_PAYLOAD=0`). First v1 row is **today 14:15 ET**, not an older
corpus. Before that, producers never called emit (or called it with the flag off).
The B.1 drop-ins turned the gate on; emit started landing this afternoon.

Post-pin proof that the window is **not** empty: 19:30 ET material-scan on
CURRENT wrote **3 material_scan + 24 reentry** payloads (`since_pin=27`).

## Per-surface (today)

| Surface (operator name) | v1 rows today | Since pin | Live path | Verdict |
|---|---:|---:|---|---|
| material_scan | 96 | 3 | `tradeai-cio-material-scan` → CURRENT, `AGENT_DECISION_PAYLOAD=1` | **emitting** |
| reentry | 116 | 24 | `reentry_decision_desk` via CURRENT (portfolio-server / scan) | **emitting** |
| telegram / freeform | 1 | 0 | `tradeai-cio-telegram` + desk loop; needs an operator message | **wired**, operator-gated |
| watch alerts | 0 | 0 | Cron was **rebuild** (`watch_alerts_eval.py` **has no emit**). RTH today: 11 armed, **0 fired**. | **wiring** (rebuild vs CURRENT) **and** zero fires this session |
| advisory shadow | 0 | 0 | `hermes-advisory-cache-worker` ExecStart = **rebuild**, **no** `AGENT_DECISION_PAYLOAD`, rebuild engine has `emit_watchlist_feedback` not `emit_advisory_opinion_payload` | **wiring** — do **not** retarget during freeze (rebuild branch ≠ main; opinions could change) |
| holdings refresh | 0 | 0 | `holdings_llm_refresh.py` **no emit in CURRENT or rebuild**. Job **did run** 07:15 ET (HOLD/STRONG HOLD rows). | **wiring** — producer writes, capture does not |
| opportunity ranking | 0 | 0 | `build_opportunity_book` in `cio_investment_product.py` (CURRENT) never calls emit. Surface `opportunity` exists in the schema. | **wiring** |

### What was fixed tonight (capture only)

Watch cron now `cd CURRENT` (diff vs rebuild is **emit-only**). Next RTH fire
(Mon 09:00–16:00 ET) can write `surface=watch`. No ranking/alert logic change.

### What was **not** fixed tonight (freeze)

Holdings emit, opportunity emit, and advisory-worker retarget to CURRENT would
either add capture on a new path or move a producer off the dirty rebuild
branch. That is D4 / post-window, **or** a clock restart if done now.

`cio-reactive` ran four times after the pin with **zero** payloads. It is not
in the six-surface list; it does not call emit. Leave it.

## Tomorrow (2026-08-22) re-count

Re-run against the same jsonl:

```
ended_at >= 2026-08-21T23:20:47Z
group by decision.surface
```

Expect: material_scan and reentry **non-zero**. Watch still 0 until Monday RTH
unless an alert fires. Holdings/advisory/opportunity stay 0 until wiring.

## Freeze (D3)

`RESEARCH_SKIP_GATE` unset/0. `MEMORY_BEHAVIOR_INFLUENCE=0`.
`AGENT_DECISION_PAYLOAD=1` unchanged. No routing. No new producers.
Payload window for **material_scan + reentry** is live and writing. Do not
restart the clock for those two. Do not pretend the other four surfaces are
in the window.
