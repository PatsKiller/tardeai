# Session closeout — 2026-08-22

**Authority:** READ_ONLY_ADVISORY  
**CURRENT pin:** `5e91225a` — **not promoted** (freeze 8/21–8/27 close).  
**Live research crontab:** `$PROJ=` rebuild. CIO delivery: CURRENT.  
**Flags:** `RESEARCH_SKIP_GATE` 0 · `MEMORY_BEHAVIOR_INFLUENCE` 0 · `RESEARCH_ALLOW_LOCAL_LLM` 0.  
**Dollar cap:** `LLM_GLOBAL_DAILY_USD_CAP=0.50` (not raised). Process `hermes_external_research` **600 calls / $0.30**.

This is the **index of findings and fixes** from 2026-08-22. Detail lives in the linked docs. Do not treat the 10:24 coverage snapshot as current DeepSeek counts.

---

## The one number that matters

| What ran | What the brain stored |
|---|---|
| DeepSeek **545 nonempty** / **$0.168934** (confirm-run) | Living thesis CURRENT **3/22 (13.6%)** — DIV, DIVI, JEPI — **unchanged** |
| T0-HOLD 22/22 · T0-PROP 30/30 · T1 331/331 · reentry 25/25 · T2 141/141 forced · T3 20/20 slice | 19 holdings still `RESEARCH_REQUIRED` |

Research writes `hermes_external_research`. **Nothing mints `symbol_<ticker>` into `cio_theses.jsonl`.** Dry-run: **19/19** of those names would mint **a row** from data already on disk. Coverage was a **join gap**, not a research gap. Quality gate (M1): rec-only **2/19 CURRENT**, joined **12/19 CURRENT**, rest THIN. Live `substantive_pct=0.0` (DIV/DIVI/JEPI re-grade THIN). Mint apply **after 8/27**, and only as CURRENT vs THIN — never a fake-green 19/19.

Canonical: `docs/ops/RESEARCH_QUALITY_AND_THESIS_GAP_2026-08-22.md`

---

## Findings

### Research / LLM
1. **Two LLM families.** Scheduler auto = DeepSeek only (Family A). ChatGPT/Grok every 2h is Family B (`hermes_top20_external_intel`, trigger labeled `holdings` if in the book). That is why holdings looked OAuth-first. `docs/ops/LLM_ROUTING_AND_DATA_LAYERS.md`
2. **One watchlist research tier: T1-WATCH.** Five universe tiers total. Reentry READY/NEAR **joins T1**. Hermes S0–S3 and directive hygiene 1–3 are **not** LLM queues. `docs/ops/RESEARCH_TIER_LLM_CADENCE.md`
3. **T3 SLA was fiction.** Published 1×/14d needed ~181/day. Production was 20/day = **127-day** cycle. Blocker was the **120-call process cap**, not the $0.50 dollar cap (~$0.000313/call).
4. **DeepSeek content is thin, not cloned.** Sample n=40: median 320 chars, 45% <300, 15% generic, 0% cross-ticker dupes, **27.5% thesis-survivable**. Error-prefix health detects crashes, not filler. Blind sheet still sealed.
5. **Overnight-deep was a zombie.** Last `deep_overnight_llm_results` **2026-05-24**. Timer was China-night = **US daytime** dry-run, `targets=[]`, gemma3:27b vs ChatGPT policy.
6. **Third local-LLM path:** `hermes-autonomous-loop` `--apply` gemma3:12b (AJG/AMAT 503 at 12:10) while `RESEARCH_ALLOW_LOCAL_LLM=0`.

### Telegram (18,130 msgs, 4 feeds)
7. Bot feed is an **ops console**, not a trading feed (115/day, 5.8% actionable last-14d). STOP_TRIGGERED (374) buried in UNHEALTHY/DEGRADED.
8. **`R:R 0.0:1`** on live proposals (ASPN true 2.0:1). **Invalidation above price** on longs (JTAI $1.59 / inv $1.60). **951** sized proposals with `Quote: alpaca ❌`. Markdown parse failure → **plaintext second send**.
9. **`DATA_UNAVAILABLE`** on Thesis/Catalyst with full technicals is a **slot join** to living thesis, not missing quotes. 52 cards. SCHD TRIM $-44,000 with capital DATA_UNAVAILABLE.

### Alarms / Drive
10. Lane-health Telegram every 15 min: nested `lanes` JSON, `last_alert` never found. DeepSeek dropped off `firing` when healthy — looked like the outage alarm stopped watching DeepSeek.
11. systemd **exit 1 when alarms found** = unit `failed` whether the check worked or crashed (same shape as `last_real`).
12. Hourly Drive sweep: **0 uploaded, 1230 FAILED 404s** (dead parent IDs). Targeted gog replace of canonical docs **does** work. Sweep ≠ healed.

---

## Fixes shipped (PRs)

| PR | What | Live? |
|---|---|---|
| **#449** | Cron loads `LLM_GLOBAL_DAILY_USD_CAP`; store raw when JSON truncates | rebuild overlay |
| **#448** | Lane-health unwrap + 6h Telegram dedup | systemd drop-in → worktree / overlay |
| **#451** | Five tiers, T1-WATCH only, cadence + confirm-run table | docs on main; CURRENT pin lacks them |
| **#452** | Telegram P0: R:R compute, quote withhold, inverted invalidation suppress, edit-on-retry | overlay rebuild + CURRENT scripts |
| **#453** | Q1 sample, Q2 staging mint, coverage-stall, exit 0 on alarm, overnight ChatGPT timer, loop refuse gemma, call cap 600, cold-floor 180 | overlay + live timers/crontab |

### Caps / cron (live)
- Global **$0.50** unchanged. Process **600 / $0.30**.
- Cold-floor `--budget 180` daily 10:00 (was 20).
- Scheduler jobs prefix `env LLM_GLOBAL_DAILY_USD_CAP=0.50`.
- Overnight timer: **22:00–06:00 America/New_York**, `--model chatgpt`. Next: **22:35 ET**.
- `hermes-autonomous-loop.timer` **disabled**.

### Telegram P0 (live overlay, freeze-safe)
Never print `0.0:1`. Quote-ineligible → withhold. Long invalidation ≥ price → no IIC. Markdown retry **edits**. Metric: `data/cio/telegram_p0_suppress.jsonl`.

---

## After 8/27 (do not do during freeze)

| ID | Work |
|---|---|
| Thesis mint | Apply `thesis_mint_from_research.py` to **live** `cio_theses.jsonl` as CURRENT vs THIN (staging: rec-only 2/19 PASS, joined 12/19 PASS). Do not mint THIN as CURRENT. |
| Telegram T3 | One resolver per field; `?` never renders |
| Telegram T4 | Bind Thesis/Catalyst to desk + Hermes + `hermes_external_research`; no machine token; sized TRIM needs capital |
| Telegram T5 | Strip `dec_`/`prod_`/`plan_` from CIO Desk |
| Telegram T6 | Four feeds (CIO Desk / Alerts / Proposals / Ops muted). Kill 1,330 ChatGPT research-update pushes. Move STOP_TRIGGERED |
| Telegram T7 | 30/day cap (Ops exempt, muted) |
| D4 | CURRENT cutover after window; `docs/ops/CURRENT_CUTOVER_AFTER_2026-08-27.md` |
| Drive 404s | Heal dead parent IDs (`docs/_archive` mostly) |
| Blind sheet | Operator scores `DO_NOT_OPEN_UNTIL_SCORED` |

---

## Where to read

| Topic | Doc |
|---|---|
| This index | **this file** |
| Tiers / cron / confirm-run | `docs/ops/RESEARCH_TIER_LLM_CADENCE.md` |
| Two LLM families + DATA_UNAVAILABLE | `docs/ops/LLM_ROUTING_AND_DATA_LAYERS.md` |
| 10:24 ET snapshot (pre-confirm-run) | `docs/ops/RESEARCH_COVERAGE_SNAPSHOT_2026-08-22.md` |
| Quality + mint + Q3–Q5 | `docs/ops/RESEARCH_QUALITY_AND_THESIS_GAP_2026-08-22.md` |
| Telegram audit P0/P1 | `docs/ops/TELEGRAM_FEED_REMEDIATION_2026-08-22.md` |
| RAW-store alarm | `docs/ops/RESEARCH_LANE_HEALTH.md` |
| Policy SLA | `docs/RESEARCH_PRIORITIZATION.md` |
