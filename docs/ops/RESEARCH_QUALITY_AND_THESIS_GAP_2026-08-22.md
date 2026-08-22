# Research quality, thesis mint gap, alarms — 2026-08-22

**Authority:** READ_ONLY_ADVISORY  
**Freeze:** **lifted 2026-08-22** (payload window invalid: 89% reentry, 4 surfaces at zero, 0.03% change rate). CURRENT pin `5e91225a` **still not promoted**.  
**Proof artifacts:** `data/cio/research_store_audit_2026-08-22.json`, `data/cio/research_full_dump_2026-08-22.md`, `data/cio/thesis_mint_dryrun_2026-08-22.json`  
**Session index:** `docs/ops/SESSION_CLOSEOUT_2026-08-22.md`

## The number

539 DeepSeek calls. **$0.168934**. Thesis CURRENT **3/22 (13.6%)** — DIV, DIVI, JEPI — **unchanged**. 19 still `RESEARCH_REQUIRED`.

Plumbing is green. The brain did not learn. Research writes `hermes_external_research`. **Nothing mints `symbol_<ticker>` into `cio_theses.jsonl`.**

## Q1 — Are today's rows good?

Deterministic sample n=40 (20 T1, 10 T0-HOLD, 10 reentry). Heuristic, not a human grade. Blind sheet remains sealed.

| Metric | Result |
|---|---|
| Median length | **320 chars** |
| % under 300 chars | **45%** |
| % symbol-specific keyword (earnings/filing/catalyst/…) | **60%** |
| % generic-prose (HOLD/WATCH, insufficient evidence, …) | **15%** (threshold 40% — **not** a clone farm) |
| % numeric restatement suspect | **15%** |
| Cross-symbol near-duplicate (5-gram Jaccard ≥0.45) | **0%** |
| % that would survive as a thesis without human editing | **27.5%** |

Verdict: the lane is **not** repeating the same paragraph across tickers. It is also **not** producing mint-grade theses. Median 320 chars, 45% under 300, 27.5% survivable. Error-prefix health is a crash detector; this is the content half.

## Q2 — Mint path dry-run (no live store)

`scripts/thesis_mint_from_research.py --apply-staging`

Sources: existing `hermes_external_research` + Hermes rank + portfolio role. **No new LLM.** Staging only: `data/cio/staging/symbol_thesis_mint_dryrun.jsonl`.

| Book | Live CURRENT | Would mint from disk |
|---|---|---|
| T0-HOLD 22 | 3 | **22/22** |
| Of the 19 RESEARCH_REQUIRED | 0 | **19/19** |
| Reentry 25 | (not in held SLA) | **25/25** |

**Coverage was never a research problem.** It was a wiring problem. Every T1 dollar bought data the thesis store does not read. Apply mint after 8/27; do not publish to live `cio_theses.jsonl` during the window.

CURRENT bar **was** `summary >= 40` chars on `symbol_<ticker>`. That is the fake-green. M1 splits it.

## M1 — Quality gate (THIN ≠ CURRENT). Three published numbers.

`CURRENT` is now PASS-grade (Q1 survivable): ≥400 chars, ticker, symbol-specific fact, non-generic, numeric fidelity, survive-needle (invalidation / role / why own / catalyst / stop). Grade B/C mint as **`THIN`**. THIN counts toward `coverage_pct` and `fresh_pct`. It does **not** count toward `substantive_pct`. `sla_met` requires coverage 100 **and** fresh ≥90 **and** substantive ≥70.

Live held book after the classifier (no live mint):

| | n | % |
|---|---:|---:|
| coverage (CURRENT\|THIN) | 3/22 | 13.64 |
| fresh | 3/22 | 13.64 |
| **substantive (PASS)** | **0/22** | **0.0** |
| THIN (DIV, DIVI, JEPI re-graded) | 3 | — |
| RESEARCH_REQUIRED | 19 | — |

The three names that were "CURRENT" were paragraphs, not theses. `substantive_pct=0` is the honest number.

**Projected split of the 19 RESEARCH_REQUIRED (today's disk, no new LLM):**

| Input | CURRENT (PASS) | THIN | SKIP |
|---|---:|---:|---:|
| rec-only (`recommendation` column) | **2** | 15 | 2 |
| joined (rec + dissent + evidence) | **12** | 7 | 0 |

**2/19 rec-only, 12/19 joined.** That is the number to remember, not 19/19. 19/19 is coverage after a join. Joined mint would land ~15/22 holdings CURRENT (68%) — shy of the 70% substantive target. Staging only: `data/cio/staging/symbol_thesis_mint_dryrun.jsonl`. Live `cio_theses.jsonl` untouched.

### Q1 — the other 5 of 19 (there is no unlabeled remainder)

The 2 CURRENT / 12 THIN mix came from stacking rec-only CURRENT (2) with joined CURRENT (12). Those are two different grades of the same 19, not CURRENT+THIN. Rec-only (what the mint now uses — stored `recommendation`, not joined evidence):

| Bucket | n | Names |
|---|---:|---|
| CURRENT (A / PASS) | **2** | AMANX, BAH |
| THIN/B | 11 | ARKX, BND, CSWC, DXCM, LDOS, QCOM, SPCX, SRNE, XAR, XLB, XLI |
| THIN/C (sub-300 / missing needles) | 4 | RTX, SCHD, SCHG, V |
| **STUB/F** (ungradeable stored rec) | **2** | NOC 17 chars, PFLT 7 chars |

2+11+4+2 = 19. THIN total = 15. STUB = do not mint; stay `RESEARCH_REQUIRED`.

### Q2 — dashboard after mint is not 19/19 and not 5/22 grandfathered

Mint grade is rec-only. Quality gate still runs on read for **everyone**, including the existing 3 (DIV, DIVI, JEPI fail PASS → THIN). Grandfathering those 3 as CURRENT would hide the thing the gate caught.

After rec-only mint apply (still after 8/27):

| Tile | n | % |
|---|---:|---:|
| CURRENT (PASS) | 2/22 | **9.1** (AMANX, BAH) |
| THIN | 18/22 | 81.8 (15 minted + 3 existing) |
| RESEARCH_REQUIRED / STUB | 2/22 | 9.1 (NOC, PFLT) |
| coverage_pct (CURRENT\|THIN) | 20/22 | 90.9 |
| substantive_pct | 2/22 | 9.1 |

5/22 = 22.7% only if we counted the existing 3 as CURRENT. We will not. `sla_met` stays false. The 19/19 green tile cannot happen.

Coverage-stall now fires on **PASS count < 70% of held**, not row-exists. A 22/22 THIN mint with 5 PASS still fires.

## M2 — 320 chars is the stored field, not Flash.

Config actually sent:

| Knob | Value |
|---|---|
| Process `max_output_tokens` | **1024** (`hermes_external_research`) |
| Caller default | 1500 → gate `min` → **1024** |
| Flash model ceiling | **384000** |
| Parser | `recommendation[:500]` |
| Prompt brevity | none explicit; JSON contract + "Give a clear recommendation…" |

Today's `llm_consumption_log` (n=546, $0.168934):

| | p50 | p90 | notes |
|---|---:|---:|---|
| tokens_in | 576 | 831 | input dominates |
| tokens_out | **824** | 1022 | not 80 tokens |
| response_chars | **3513** | 4316 | model already writes |
| % at 1024 cap | | | **11.4% (62)** |

Stored `recommendation` today (n=545): **p50=230 chars**, 61.7% <300, 16% at/over 500 (parser cluster). Q1's 320 was a 40-row sample of the same truncated column.

You already pay for ~825 output tokens and keep 500 characters. There is no cost argument for thin **stored** recs. Proposed, **not applied**: parser `[:500]→[:4000]`; prompt requires the recommendation string to *be* the thesis; ceiling 1024→4096. Dollar caps unchanged.

Sandbox 20 (`HERMES_SANDBOX_OUTPUT_CEILING=1`, `--no-store`, prompt-file, 4096, trigger `holdings`, 20/20 sent):

| Grade on | PASS |
|---|---:|
| stored rec (still `[:500]`) | **40%** |
| joined rec+dissent+evidence | **90%** |
| raw model text | **100%** |

The ceiling+prompt package makes the **model** thesis-survivable. The parser still throws the thesis away. Production cap stays 1024. Cron does not pass the flags. Highest-leverage unapplied patch is `recommendation[:500]→[:4000]`.

## M3 — Drive 404s

Hourly sweep ≠ targeted gog replace. Failures were `docs/_archive`, dated session-dump dirs, `_findings` / `ui_review` screenshot trees. Sweep now excludes those, purges dead cache lines, and **does not fall back to the Drive root on mkdir fail**.

Proved on the **same sweep path** cron uses (`CURRENT/scripts/sync-docs-to-drive.sh` overlay): **uploaded=26, skipped=2069, failed=0, exit_code=0** at 2026-08-22T21:09:15Z. Alarm can go green on the next lane-health tick.

## M4 — Freeze / payload clock

`git diff` vs #453 on DecisionPayload producers: **empty**. Traces CURRENT `agent_run_traces.jsonl`:

| UTC | v1 | reentry | material_scan | freeform | watch | holdings | advisory | opportunity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8/21 | 268 | 165 | 102 | 1 | 0 | 0 | 0 | 0 |
| 8/22 | 3500 | 3125 | 375 | 0 | 0 | 0 | 0 | 0 |

Reentry and material_scan **accrued**. freeform 1→0 is a one-off Telegram desk reply, not a daily producer — clock does **not** restart. watch/holdings/advisory/opportunity still 0 (pre-existing emit gap). CURRENT pin `5e91225a` lacks #451+ docs. **Noted. Not promoted.**

## Q3 — Alarm holes

- DeepSeek stays in `lanes[]` always. Telegram `--alert` now prints a **Watched: deepseek** line even when ok, so the outage alarm cannot "forget" the lane it was built for.
- **`main()` exits 0** when the check ran. Exit 1 = collect crashed. Exit 2 = Telegram send failed. Alarm state is JSON `ok`/`firing` + Telegram. systemd `failed` no longer means "found problems."
- New lane **`coverage-stall`**: DeepSeek ok_24h ≥ 20 and held **PASS/CURRENT < 70%** while research is not falling. THIN rows do not quiet it. **Today would fire.**

## Q4 — Overnight-deep: fix. Autonomous-loop: disable.

China-night timer (18:00–08:35 Asia/Shanghai) is **US daytime**. That is why the unit dry-runs at hour=9–12 ET with `targets=[]`. Last `deep_overnight_llm_results` row **2026-05-24**. Policy is ChatGPT 22:00–06:00 ET.

- **Fix:** `hermes-deep-research-local.timer` → `America/New_York` 22,23,00,01,02,03,04,05:35. Service `--model chatgpt` (script already remaps on US overnight).
- **Kill:** `hermes-autonomous-loop.timer` disabled. Script **refuses `--apply`** when model is gemma and `RESEARCH_ALLOW_LOCAL_LLM=0` (the 12:10 AJG/AMAT 503 path).

## Q5 — T3 SLA

Published 1×/14d × 2537 names = **181/day**. Production was **20/day → 127-day cycle**. At $0.000313/call the 14-day cycle is **$0.057/day** inside $0.50. Blocker was the **120-call process cap**, not dollars (today 34% of $0.50).

Change: `hermes_external_research` **daily_soft_cap 120 → 600**. Dollar caps stay **process $0.30 / global $0.50**. Cold-floor cron **budget 20 → 180**. 180×14 ≈ 2520. SLA is now physically possible.

## P2 — Mint grades JOINED rec+dissent+evidence

`scripts/thesis_mint_from_research.py` now sets `g_mint = g_joined if summary_joined else g_rec`. `would_mint_state` and staging extra use that joined grade. Report JSON still publishes **both** rec-only and joined splits (`projected_split_of_19.rec_only` / `.joined`).

`--apply-live` is opt-in and writes the **shared CURRENT/rebuild** store (`CURRENT/data/cio/cio_theses.jsonl`, inode 3064869). Default remains staging. Freeze is lifted; live apply uses joined rec+dissent+evidence.

Historical Q2 numbers above (rec-only 2/19 CURRENT) are the pre-P2 dry-run. Joined was already 12/19 CURRENT on the same disk.

## P3 — RESEARCH_SKIP_GATE=1 on live crontab (code default stays 0)

Do **not** change the code default. `skip_gate_enabled()` reads `RESEARCH_SKIP_GATE` with default **`"0"`**.

**Live crontab (applied):** all 6 `research_scheduler.py` jobs now prefix `env RESEARCH_SKIP_GATE=1`. Holdings 08:00/12:30/16:30, priority hourly 10–16, watchlist 20:30, cold-floor 10:00, incubator Sun 19:00.

When the gate is on: execute_set = due ∩ (changed ∪ stale ∪ triggered). Skips land in `data/cio/research_skip_ledger.jsonl`.

Ledger is empty until the next weekday scheduler tick (Sat 8/22 after 16:30 — next holdings **Mon 08:00 ET**). Until then:

```
.venv/bin/python scripts/research_skip_gate_report.py
# → ledger empty / gate off
```

## P4 — Thesis-change CIO Desk card

`--apply-staging` → `notify=False`, no desk card.  
`--apply-live` → `notify=True` (Telegram still gated by `CIO_THESIS_TELEGRAM` default **off**) **and** a `ThesisChangeCard@v1` row on `CURRENT/data/cio/thesis_change_cards.jsonl` plus bus event `thesis.changed` (wakes Alex). Kind = minted / upgraded / downgraded / invalidated / revised. Volume is supposed to be low.

---

## Recovery audit (S1–S7, R1–R2, G1) — numbers not prose

### S1 — What is actually stored

Table `hermes_external_research`. **All model-output columns are `text` / `jsonb`, not VARCHAR(500).** Parser slices are Python, not the schema. `[:500]→[:4000]` does **not** need ALTER.

| Column | DB type | Parser slice (pre-P1 / P1) | Today n=545 p50 / p90 / max |
|---|---|---|---|
| recommendation | text | 500 → **4000** | **230 / 500 / 4000** |
| dissent | text | 500 → **4000** | **443 / 500 / 500** |
| evidence_json | jsonb | 5× text[:300] | **1040 / 1338 / 1594** |
| learning_candidate | text | 300 → 800 | **300 / 300 / 300** |
| operator_action | text | 300 → 800 | **300 / 300 / 300** |
| risk_flags | jsonb | list as-is | 344 / 462 / 671 |
| data_i_doubt | — | parsed, **not inserted** | never lands |
| raw_response | text (migration applied) | always `raw[:16000]` after P1 | **0 nonempty historically** |

`llm_consumption_log` stores `response_chars` only (p50 **3513**). No body. Hash only.

Where the 3,513 chars go: JSON split across rec+dissent+evidence+learning+operator+risk_flags. Bytes that never land: `data_i_doubt` as its own field, and the tail of any field that hit its parser slice (dissent/learning/operator medians **are** the old slice).

### S2 — Raw store

PR #449 fallback: on JSON parse-miss, dump `raw.strip()[:4000]` **into recommendation**. Not a dedicated column.

P1 migration `2026-08-22_hermes_external_research_raw_response.sql`: column **exists, TEXT**. Write path always stores `raw_response[:16000]`. **First date with data: none yet** (0 nonempty). Overlay onto rebuild still required for the next call to write it.

Today 545 nonempty DeepSeek: **50** rows are the #449 fallback (49 fenced ` ```json `, 1 raw JSON). First: AMANX 2026-08-22 11:05 ET.

### S3 — Actual loss. Today n=545 DeepSeek nonempty

| Bucket | n | % |
|---|---:|---:|
| (a) recoverable by joining rec+dissent+evidence | **545** | **100%** |
| (b) recoverable only by re-parsing the raw dump sitting in `recommendation` | **50** | 9.2% (also in a — join already grades them) |
| (c) genuinely gone | **0** | **0%** |

Rec-only grades: CURRENT 111 / THIN 432 / F 2. Joined: CURRENT **474** / THIN 71 / F 0. The 2 rec-only F rows (NEE 36ch, AVGG 6ch) recover via dissent+evidence.

Last 30 days: n=546 (one extra: SCHD 2026-08-21). Same shape. Crash-loop 8/13–21 called almost nothing.

### S4 — Write path (P1) + schema

- Schema is TEXT. No ALTER for length. `raw_response TEXT` **applied**.
- Parser `[:500]→[:4000]`, learning/operator `[:300]→[:800]`.
- Always store raw `[:16000]`.
- Ceiling 1024→**4096**. Dollar caps unchanged $0.30 / $0.50.
- Prompt: recommendation field **IS** the living thesis.
- New p50 after one holdings run: **not yet** — overlay onto rebuild `$PROJ` is what the crontab actually executes; next holdings is **Mon 08:00 ET**.

### S5 — Read path (the bigger win)

Mint now grades **joined**. Dry-run on today's latest rows (no new LLM): rec-only **1/19 CURRENT**, joined **9/19 CURRENT / 10 THIN / 0 SKIP**. Of all 22 holdings, joined would-mint **12 CURRENT / 10 THIN**.

**Live apply 2026-08-22T22:14Z** (CURRENT `cio_theses.jsonl`, 47 publishes then 47 remint after fixing `would_say[:400]` which had chopped PASS bodies to 400 chars):

| Tile | n | % |
|---|---:|---:|
| coverage_pct (CURRENT\|THIN) | 22/22 | **100.0** |
| fresh_pct | 22/22 | **100.0** |
| **substantive_pct (PASS)** | **12/22** | **54.55** |
| THIN | 10 | ARKX BAH BND PFLT SCHD SCHG SPCX V XAR XLB |
| CURRENT | 12 | AMANX CSWC DIV DIVI DXCM JEPI LDOS NOC QCOM RTX SRNE XLI |
| sla_met | false | substantive target 70 |

DIV/DIVI/JEPI are CURRENT because **joined research now PASSES**, not because they were grandfathered. NOC rec-only 17 chars → joined 993 CURRENT. PFLT rec-only 7 chars → joined 620 THIN. `needs_coverage_n=0`.

### S6 — Backfill

Raw column empty for history. Tried to re-parse the 50 #449 dumps in `recommendation`: **0/50 parse**. They are truncated at 4000 chars mid-JSON (`endswith 'han 1 day old, treat'`). Join already grades them; structured split needs a re-call. 50 × $0.000313 ≈ **$0.016** — not spent. Do not re-call the other 495. Full 545 would be ~$0.17.

### S7 — Retention (answered with job, dates, counts)

| Store | Job | Policy | Oldest row | Rows older than 90d | Under 90d expiry? |
|---|---|---|---|---:|---|
| `hermes_external_research` (incl. `raw_response`) | `hermes_autonomous_self_tune.py --apply` **daily 17:00 ET** `DELETE … created_at < NOW() - 180d` | `HERMES_EXTERNAL_RETENTION_DAYS` default **180**, no `.env` override | **2026-06-07** (~76d) | **0** | **no** |
| `raw_response` column | same table / same DELETE | 180d | 6 nonempty rows, all tonight (post-overlay) | 0 | no |
| `llm_consumption_log` | **none** — not in `db_retention.py` POLICIES, not in crontab | unbounded | 2026-07-08 | **0** | **no** |
| `hermes_research_intelligence` | same self-tune, 180d, only `status IN (rejected,superseded,expired)` | 180d | 2026-05-30 | 0 | no |

`db_retention.py` is **not on crontab** (destructive, EXCLUDED). Last self-tune tonight 17:00: `external_purged=0`. Next run **Sun 17:00 ET**. First 180d cutoff for current oldest row ≈ **2026-12-04**.

Nothing expires under 90 days. Snapshot taken anyway because there is no historical raw: `/home/johnclaw/archives/research-corpus-2026-08-22/` (`hermes_external_research.dump` 31MB, `llm_consumption_log.dump`, theses jsonl).

### S7b — 94 `thesis.changed` cards are a mint backfill

`CURRENT/data/cio/thesis_change_cards.jsonl`: **94 cards, 47 symbols, 2 batches** (22:14:06Z v1 400-char stub + 22:14:46–47Z full remint). Telegram off.

| Verdict | n |
|---|---:|
| STRENGTHENS | **0** |
| WEAKENS | **0** |
| INVALIDATES | **0** |
| CONFIRMS | **0** |
| minted / revised / upgraded | 69 / 13 / 12 |

The field does not exist. P4 fires on mint, not a delta contract. **Do not page.** 5 strongest WEAKENS/INVALIDATES: **none**. Most negative mint bodies (LMT, AMANX, SPCX, SCHG, MOGU) are first impressions, not revisions.

### T3 catalyst-only (approved)

Live T3 DeepSeek today: **30 rows**, not 181. T3 SLA lanes were `local-gemma` only — **catalyst could not call DeepSeek**. The 181/day figure was policy math. Cold-floor cron queued local-gemma (`budget=20` in last log).

Shipped: `T3-COLD` lanes include `deepseek`; existing gate `T2/T3 and not catalyst → ext_lanes=[]` is the safety net. **Cold-floor crontab commented out.**

Projected DeepSeek/day (clock, skip-gate off, no confirm-run):

| Tier | Rule | Calls/day |
|---|---|---:|
| T0-HOLD | 22 × 3 | 66 |
| T0-PROP | 30 × 2 | 60 |
| T1-WATCH | 325 × 4/7 | ~186 |
| T2-INCUB | catalyst only (already) | ~0–5 |
| T3-COLD | catalyst only (now) | ~0–5 |
| **Total** | | **~312–322** |

Skip-gate (on, unmeasured until Mon 08:00) cuts the T0 3×/day when hash unchanged. 50–80/day still needs R3 (ATR/catalyst/14d floor on T0+T1), not just T3.

### R1 — Prompt is amnesiac (QCOM dump)

Exact prompt: `data/cio/research_prompt_dump_QCOM.txt`.

| In the prompt? | |
|---|---|
| current `symbol_thesis` | **false** |
| previous research + date (`hermes_intelligence`) | **true** |
| what changed since | **false** |
| deterministic trend | **false** |
| operator feedback | **false** |
| temperature | **0.3** |

Every call is a re-ask. Prior DeepSeek rec can appear inside `hermes_intelligence` as another paragraph, not as a standing thesis to confirm or invalidate. Rewording at temp 0.3 can trip `_research_fingerprint` (hashes recommendation+confidence).

### R2 — What triggers an LLM call

With gate off (code default 0): **SLA timer expired**. `due` = T0 always, or age ≥ window/refreshes. Catalyst is a **+25 score**, not a dispatch (except T2/T3 externals, catalyst-gated). Price move, analyst revision, sector divergence do **not** trigger.

With gate on (live crontab as of tonight): execute_set = due ∩ (changed ∪ stale ∪ triggered). Still not ATR/analyst/sector — those are R3 (proposal, not built).

### R3 — Trigger set (propose, not built)

Deterministic daily is free. Escalate to LLM on ATR move, RVOL spike, catalyst, analyst revision, sector-ETF divergence, desk state change, NEED_DATA/DISAGREE, 14-day floor.

**Honest arithmetic:** today's 545 is mostly T3 1×/14d (181) + T1 4×/7d (189) + T0 126. The 50–80/day number **only works if T3 is catalyst-only** and the 14-day floor applies to T0+T1 (~383 names / 14 ≈ 27), not 2,537 cold names. T3 SLA 1×/14d is the bulk. Operator must approve dropping it.

Spend the freed budget on 4096-token outputs (already shipped), joined evidence (already the mint read), Pro-tier on contested names.

### G1 — Taxonomy that already exists (do not mix with LLM tags)

| Tag | Lives where | Join to `hermes_external_research`? |
|---|---|---|
| sector / industry | `symbol_profiles` (yfinance + Finviz fallback) | **yes**, `symbol` |
| Finviz file cache | `data/state/ticker_enrichment_cache.json` | app-join only |
| S&P 500 | `sp500_constituents_sector` | yes, `symbol` |
| industry momentum | `industry_momentum_state` (Finviz groups) | via `symbol_profiles.industry` |
| sector ETFs | tracked as symbols; not a research join | no |
| `street_mean_target` | schema field; SPCX printed **DATA_UNAVAILABLE** | **unpopulated, not dead** |
| 481 INDUSTRY MOMENTUM Telegram | `finviz_industry_groups.py` / `sector_leaders_service.py` | **not fed to research** |

G2–G6 (controlled-vocab tags, contradiction test, aggregates, thematic fan-out): **not built**. Sequence holds: G4 before G5/G6.

### R4 / R5 / G4 — not this commit

Prior-brief + DELTA contract (R4) is the actual research fix. Thesis STRENGTHENS/WEAKENS/INVALIDATES cards (R5) need R4 first; tonight's path fires on **mint** (P4). Contradiction detection (G4) needs G2/G3 tags.
