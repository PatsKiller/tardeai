# Research and thesis lifecycle — as of 2026-08-22 night

**Authority:** READ_ONLY_ADVISORY  
**CURRENT pin:** `5e91225a` — **not promoted** (CIO delivery + reactive cycle run from this pin).  
**Live research crontab:** `$PROJ=` `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`.  
**This file is the current-state map.** Older snapshots (`RESEARCH_COVERAGE_SNAPSHOT_2026-08-22.md`, Q1 sample, 10:24 ET counts) are history.

Related: `docs/ops/RESEARCH_LIFECYCLE_STANDARD.md` (intended methodology) · `docs/ops/RESEARCH_TIER_LLM_CADENCE.md` (tiers/cron) · `docs/ops/LLM_ROUTING_AND_DATA_LAYERS.md` (two LLM families) · `docs/ops/RESEARCH_QUALITY_AND_THESIS_GAP_2026-08-22.md` (parser/join diagnosis) · `docs/ops/SESSION_CLOSEOUT_2026-08-22.md` (index).

> **R8 branch addendum (not live):** The stale statement "research has never
> minted live theses" is false; the table below records the operator-driven mint.
> The remaining gap is automatic circulation. The review branch adds a canonical
> stateful prompt, `ResearchThesisDelta@v1`, quality-gated automatic reconciliation,
> provenance on every new write, replay suppression, and deterministic
> `ThesisDecisionGate@v1`. CURRENT does not serve those changes until a separately
> authorized merge and promotion. See the R8 correction section in
> `docs/architecture/TRADEAI_SYSTEM_STATE_AND_AUTONOMY_2026-08-20.md`.
>
> **NOC source acceptance (not live):**
> `scripts/run_noc_autonomous_advisory_golden.py` exercises the existing accepted-
> research bridge twice against an isolated data root. The first pass publishes
> `symbol_noc@v2`, preserves full `/v3/advisory` and CIO thesis lineage, emits one
> decision trace, and links an operator disposition to the decision and thesis.
> The next stateful prompt includes that disposition and the prior delta. The
> second identical pass returns `NO_NEW_INFO` with no thesis, card, decision,
> research-request, notification, or Telegram duplication. Evidence:
> `docs/_evidence/autonomous_advisory_loop/noc_golden_loop_isolated.json`.
> This is explicitly `live_proven=false`; localhost browser acceptance and a
> natural production run require reviewed merge and separately authorized release.

---

## The book, tonight

| Book | Untruncated DeepSeek | Living theses minted | CURRENT (PASS) | THIN | SKIP |
|---|---:|---:|---:|---:|---:|
| T0-HOLD | 22/22 | 22 | **17** | 5 (JEPI QCOM SCHG XAR XLB) | 0 |
| Reentry READY/NEAR | 25/25 | 25 | **24** | 1 (FATN) | 0 |
| T1-WATCH (ex hold/reentry) | **299/299** | 299 | **292** | 7 | 0 |
| Held SLA | — | — | coverage **100** · fresh **100** · **substantive 77.27** | — | **sla_met true** |

This morning the same held book was `substantive_pct = 0/22`. The model was already writing ~3,500-character answers. The parser stored `recommendation[:500]`. We were grading a stub.

PRs: **#457** write-path + joined mint, **#458** T3 catalyst-only + S7 snapshot.

---

## One picture

```
TRIGGER (clock and/or skip-gate)
    │
    ▼
DeepSeek Flash  (Family A — research_scheduler)
    │  max_output_tokens 4096, temperature 0.3
    │  prompt: "what do you think about X" + hermes_intelligence dump
    │  NOT: standing thesis, what-changed, trend, operator feedback
    ▼
parse_external_research_result
    │  recommendation[:4000]  dissent[:4000]  evidence 5×[:300]
    │  always raw_response[:16000]
    ▼
hermes_external_research  (Postgres, TEXT, retain 180d)
    │
    ├── next LLM prompt     hermes_prompt_block()  (last 3 recs, uncut)
    ├── advisory desk       _load_external_research() then [:240]
    └── mint (manual tonight, not cron)
            ▼
        cio_theses.jsonl  symbol_<ticker>@vN
            ├── next Telegram/desk card  (join living thesis — was DATA_UNAVAILABLE)
            ├── thesis_change_cards.jsonl
            └── bus thesis.changed  HIGH
                    └── live CURRENT pin IGNORES it (no type on 5e91225a)
            └── memory bridge may admit CANDIDATE
                    └── MEMORY_BEHAVIOR_INFLUENCE=0  (cannot steer)
```

Family B (ChatGPT/Grok OAuth every 2h, `hermes_top20_external_intel`) still writes the same table with a different `lane`. It is not the sanctioned auto lane.

---

## Stage 1 — Who gets called

Five universe tiers. Highest membership wins. Local gemma is listed on SLAs and **off** (`RESEARCH_ALLOW_LOCAL_LLM=0`).

| Tier | Who | Auto DeepSeek | SLA (policy) | Live cron |
|---|---|---|---|---|
| T0-HOLD | 22 held equities | yes | 3× / day | M–F 08:00 / 12:30 / 16:30 `--mode holdings` budget 70 |
| T0-PROP | ~30 paper proposals | yes | 2× / day | M–F 10–16 `--mode priority` budget 40 |
| T1-WATCH | rank ≤200 **or** ticker directive **or** reentry READY/NEAR | yes, one external/refresh | 4× / 7d | M–F 20:30 `--mode watchlist` budget 50; also priority if due |
| T2-INCUB | incubator | **catalyst only** | 1× / 7d local accounting | Sun 19:00 `--mode incubator` |
| T3-COLD | rest of `symbol_profiles` | **catalyst only** | 14d sweep **dropped** | cold-floor crontab **commented out** 2026-08-22 |

`RESEARCH_SKIP_GATE=1` on all six scheduler crontab lines (code default still `"0"`). When on: `execute_set = due ∩ (changed ∪ stale ∪ triggered)`. Ledger: `data/cio/research_skip_ledger.jsonl`. Empty until the next weekday tick (Saturday run was manual).

Catalyst for T2/T3: `trade_ai_scans` rvol≥5 or \|gap\|≥10, or Hermes `momentum_catalyst` in 36h. **Not** ATR, analyst revision, or sector-ETF divergence (R3, not built).

Prompt is **amnesiac**. Exact dump: `data/cio/research_prompt_dump_QCOM_post457.txt` (and `~/research-recovery-2026-08-22/`). Context keys: `symbol`, `trade_strategy_status_counts`, `recent_research_topics`, `hermes_intelligence`. Standing `symbol_qcom` is **not** in the prompt even after mint.

---

## Stage 2 — Write path (what we pay for vs what we keep)

| Knob | This morning | Tonight |
|---|---|---|
| `max_output_tokens` | 1024 | **4096** |
| Parser `recommendation` / `dissent` | `[:500]` | **`[:4000]`** |
| `learning` / `operator_action` | `[:300]` | `[:800]` |
| `raw_response` | none (except #449 dump-into-rec) | **always `[:16000]`** |
| Schema | TEXT / jsonb — never VARCHAR(500) | same |
| Prompt OUTPUT | one-line recommendation | recommendation **IS** the living thesis |

Holdings proof run (22 names, trigger=`holdings`):

| | before `[:500]` | untruncated run |
|---|---:|---:|
| rec p50 | 230 | **2,228** |
| rec p90 | 500 | **2,550** |
| `tokens_out` p50 | 824 | **1,215** (20/22 would have hit old 1024 cap) |
| raw stored | 0 | **22/22**, p50 5,376 |
| mint CURRENT/THIN/STUB | 2 / 15 / 2 (rec-only of 19) | **17 / 5 / 0** |

Caps standing (restored after tonight’s operator override): process **600 calls / $0.30**, global **$0.50**. Tonight’s ignore-cap finish spent process **$0.340 / 916 calls**, global **$0.407**. DB `llm_process_config` put back to 600 / $0.30.

Request cap counts `llm_cost_reservations` reserved+settled, not just successful log rows. Error `[ERROR] COST_CAP_EXCEEDED` rows still occupy a slot.

---

## Stage 3 — Mint (research → living thesis)

`scripts/thesis_mint_from_research.py`

- Reads **joined** rec + dissent + evidence. Grades PASS → `CURRENT`, B/C → `THIN`, ungradeable → skip.
- `--only holdings|reentry|watchlist|all`. `--apply-live` writes shared CURRENT/rebuild `cio_theses.jsonl` (inode 3064869).
- THIN ≠ CURRENT. `sla_met` needs coverage 100 **and** fresh ≥90 **and** substantive ≥70. THIN counts for coverage/fresh, not substantive.
- DIV/DIVI/JEPI were not grandfathered. They PASS on joined untruncated text.
- No cron mints. Tonight’s apply was operator-driven.

`--apply-live` also writes `ThesisChangeCard@v1` and emits `thesis.changed`. Kinds tonight: minted / upgraded / revised. **STRENGTHENS / WEAKENS / INVALIDATES / CONFIRMS do not exist.** 735 cards = mint batches, not 735 mind-changes.

---

## Stage 4 — Who consumes it (pull, not push)

| Consumer | What it reads | What it does with tonight’s data |
|---|---|---|
| Next DeepSeek / watchlist-agent / holdings_llm_refresh | `hermes_prompt_block` last 3 external recs | Sees the new paragraph as more `hermes_intelligence`. Still no standing-thesis question. |
| Advisory desk | latest DeepSeek / symbol, 14d | Attaches evidence, then **cuts rec to 240 chars**. |
| Telegram / reentry cards | living `symbol_<ticker>` via attach | **Join now has a row** for minted names. Next card render can stop printing `Thesis: DATA_UNAVAILABLE` for those tickers. Not sent tonight. |
| CIO desk memo | `cio_desk_synthesis` | Uses **desk@vN** (platform thesis), not 346 symbol theses. |
| Alex reactive cycle | CIOEventBus, `ALEX_EVENTS` | Runs from **CURRENT pin**. That pin’s bus **does not list `thesis.changed`**. Cycle 23:55Z **enqueued 0**. |
| Telegram “CIO thesis updated” | `notify_thesis_published` | **Off.** `CIO_THESIS_TELEGRAM` unset. |
| Memory | `research_memory_bridge` | Some `RESEARCH_REFERENCE` **CANDIDATE**s admitted (`NON_AUTHORITATIVE_CONTEXT`, 30d). `MEMORY_BEHAVIOR_INFLUENCE=0` — cannot steer. |

Nothing auto-trades, auto-stops, or auto-flips a directive off a thesis.

---

## Stage 5 — Retention

| Store | Job | Policy | Oldest | <90d expiry? |
|---|---|---|---|---|
| `hermes_external_research` + `raw_response` | `hermes_autonomous_self_tune.py --apply` daily 17:00 ET | 180d | 2026-06-07 (~76d) | no |
| `llm_consumption_log` | none | unbounded | 2026-07-08 | no |
| Snapshot | `/home/johnclaw/archives/research-corpus-2026-08-22/` | — | tonight | — |

Pre-#457 rows have **no historical raw**. They exist as stored columns only. First 180d delete of current oldest ≈ 2026-12-04.

---

## Flags and dual-root (do not mix)

| Flag | Live |
|---|---|
| `RESEARCH_SKIP_GATE` | **1** on crontab; code default 0 |
| `MEMORY_BEHAVIOR_INFLUENCE` | **0** |
| `RESEARCH_ALLOW_LOCAL_LLM` | **0** |
| `CIO_THESIS_TELEGRAM` | unset / off |
| `LLM_GLOBAL_DAILY_USD_CAP` | **0.50** (crontab prefix) |
| Process cap | **600 / $0.30** (restored) |

Research jobs: rebuild `$PROJ`. CIO reactive + Telegram delivery: CURRENT pin `5e91225a`. That split is why theses can exist and Alex still sleeps.

---

## What is still not the lifecycle we described

| ID | Status |
|---|---|
| R4 prior-brief + DELTA (`CONFIRMS/STRENGTHENS/WEAKENS/INVALIDATES/NO_NEW_INFO`) | **Not built.** Prompt is still a first impression. |
| R3 event triggers (ATR, RVOL, analyst, sector ETF) | **Not built.** Skip-gate is content-hash + stale + catalyst only. |
| G2–G6 metatags / contradiction | **Not built.** G1 inventory exists. |
| `thesis.changed` → Alex on **live pin** | Type missing on `5e91225a`. Overlay or promote after 8/27 (D4). |
| Telegram T4 thesis/catalyst join | Slot exists; next card should pick up minted names. Token `DATA_UNAVAILABLE` still in templates. |
| Automatic mint on each research row | **No cron.** Tonight was `--apply-live`. |
| 50–80 calls/day | Needs R3, not just T3 off. Clock T0+T1 still ~312/day with skip-gate off. |

---

## Operator commands

```
# living held coverage
PYTHONPATH=scripts .venv/bin/python -c \
  "from pathlib import Path; from scripts.lib.cio_held_thesis_coverage import build_held_coverage_report as b; \
   print(b(root=Path('/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT')))"

# mint dry / live
.venv/bin/python scripts/thesis_mint_from_research.py --only holdings
.venv/bin/python scripts/thesis_mint_from_research.py --only holdings --apply-live

# skip-gate 48h
.venv/bin/python scripts/research_skip_gate_report.py

# QCOM exact prompt reconstruction
# ~/research-recovery-2026-08-22/research_prompt_dump_QCOM_post457.txt
```

Proof artifacts (gitignored): `data/cio/held_thesis_coverage_latest.json`, `~/research-recovery-2026-08-22/`, `/tmp/thesis_mint_*.json`, `/tmp/holdings_parser_proof_2026-08-22.log`.
