# Maturation slices G.1 + I.0 + A.1 + B.1 — 2026-08-21

**Authority:** READ_ONLY_ADVISORY  
**Influence:** `MEMORY_BEHAVIOR_INFLUENCE=0` (unchanged)  
**Cap:** `LLM_GLOBAL_DAILY_USD_CAP=0.50` (unchanged)  
**PRs:** [#434](https://github.com/PatsKiller/tardeai/pull/434) G.1 · [#435](https://github.com/PatsKiller/tardeai/pull/435) I.0/A.1/B.1

Successor to Phase 0 `docs/_findings/ALEX_AUTONOMY_GROUND_TRUTH_2026-08-21.md` (closed snapshot). This file is the live ops record for the first four approved slices.

---

## What is live on the host (before/after promote)

| Item | Host now | After promote of these PRs |
|------|----------|----------------------------|
| TSLA injection canary `mem_5989433c2194182282b6e49bedb19cde` | **RETRACTED** `p0_adversarial_quarantine_2026-08-21` | same (shared JSONL) |
| `MEMORY_ADVERSARIAL_SCAN` | **0** (parity) until #434 is promoted + drop-in `31-memory-adversarial-scan.conf` | code present; enable drop-in after promote |
| Producer `AGENT_DECISION_PAYLOAD` | **1** on material-scan, telegram, reactive, measure, advisory-shadow | same drop-ins in repo |
| DecisionPayload@v1 corpus | still **0** rows (clock starts on next producer fire) | honesty fix: 0 v1 ⇒ `decision_payloads_available=false` |
| 5-trading-day window | **false start 2026-08-21 11:58 EDT** (0 v1, HOLD-fallback lie) | **restart** the first day `payload_v1_count ≥ 1` non-synth |
| Crontab Peak A/B bulk | **10 lines retargeted** to 10:00–20:00 ET + PEAK_SKIP wrapper | helper in repo |
| `hermes-autonomous-loop.timer` | **unchanged** 18:00–08:10 Asia/Shanghai (official off-peak) | same |
| ATP2 `premarket_4am` | **unchanged** (peak-priced, latency-sensitive) | same |
| Drive sync SRC | still rebuild cron until this script is what cron runs | **CURRENT** default (`TRADEAI_DOCS_SRC` override) |
| Tree-pin | **215 TradeAI drift** (185 rebuild / 30 hybrid / 15 current) | audit only; no unit massacre |

Backup: `crontab_backup_pre_offpeak_retarget_20260821_180645.txt`.

---

## G.1 — why the existing scans missed the canary

- `is_forbidden_authoritative` matches **canonical-truth field tokens** (`order state`, `price`, `cash`). `"place an order"` is not `"order state"`.
- Secret scan is token-shaped (`sk-`, `ghp_`, …).
- `research_memory_bridge._forbidden` includes `"place an order"` — this record did **not** go through the bridge.
- Program 3 cert admitted it as `OPERATOR_EXPLICIT_PREFERENCE` / `operator_feedback` → AUTO ACTIVE.
- `test_prompt_injection_stays_data` still admits CASE_SUMMARY when the scan flag is **off** (parity). Flag **on** rejects all types.

---

## A.1 retarget table (ET)

| Job | Was | Now |
|-----|-----|-----|
| `research_scheduler --mode cold-floor` | 02:00 Peak B | 10:00 |
| `hermes_outcome_grader` | 02:50 | 10:50 |
| `hermes_tag_engine` | 03:05 | 11:05 |
| `hermes_outcome_feedback_agent` | 03:25 | 11:25 |
| `hermes_outcome_learning` | 03:35 | 11:35 |
| `hermes_score_history_retention` | 03:35 | 11:40 |
| `hermes_config_governor` | 03:40 | 11:45 |
| `auto_research` / `aegis_synthesis` / structured eval | 21:00 Peak A | 20:00 |

Wrapper: `~/.config/tradeai/bin/run_with_deepseek_offpeak.sh` (PEAK_SKIP → exit 0).

---

## B.1 producer units

Drop-in `30-decision-payload.conf` on:

- `tradeai-cio-material-scan.service`
- `tradeai-cio-telegram.service` (restarted)
- `tradeai-cio-reactive.service`
- `tradeai-cio-memory-shadow-measure.service` (also `MEMORY_PROVIDER=durable`, `MEMORY_SHADOW=1`)
- `tradeai-advisory-shadow-session.service` (flag on; emit still unwired — B.2)

Code default remains `AGENT_DECISION_PAYLOAD=0`.

---

## Do not

- Flip `MEMORY_BEHAVIOR_INFLUENCE`
- Count today’s 5-day window as started
- Raise `LLM_GLOBAL_DAILY_USD_CAP`
- Retune `hermes-autonomous-loop.timer` into overnight ET
- Merge `feat/two-way-watchlist-curation` as a side effect of tree-pin
