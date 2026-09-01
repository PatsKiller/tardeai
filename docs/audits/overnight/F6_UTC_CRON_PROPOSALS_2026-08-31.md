# WAVE F6 — UTC scheduling proposals for LLM-heavy jobs · 2026-08-31

**Authority:** `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0` (rail = unconditional raise)  
**Branch:** `docs/overnight-f6-utc-cron-proposals`  
**Deploy:** none · **Cron/systemd install:** none (operator-only)  
**File set:** this audit (+ optional `docs/ops` pointer)

This tranche **proposes and stops**. It does not edit crontab, timers, wrappers, or lane
registry state. Installing any row below is an operator action after review.

---

## Verdict (state at the top)

| claim | status |
|---|---|
| Host crontab is Eastern wall-clock (host TZ `America/New_York`; no `CRON_TZ=`) | **OBSERVED** `[HOST]` 2026-08-31 |
| Official DeepSeek peak is **UTC** Mon–Fri `01:00–04:00` and `06:00–10:00`; half-rate (off-peak) elsewhere | **CODE** — `scripts/lib/deepseek_offpeak.py` `DEEPSEEK_PEAK_UTC` |
| Many overnight LLM jobs still fire on ET hours that land inside UTC peak under EDT (`ET+4`) and only survive via `run_with_deepseek_offpeak.sh --official` PEAK_SKIP | **OBSERVED** `[HOST]` |
| DST flips Eastern→UTC offset (EDT −4 ↔ EST −5); fixed-UTC naive copies of ET times drift relative to market open and relative to peak | **RISK** — see §DST |
| This PR installs nothing | **RAIL** |

**Jobs proposed below:** **32** (primary LLM-heavy). Market-tied / zero-LLM / already-UTC-timer jobs are inventoried but not retargeted.

---

## 1. Why UTC (and not another ET retarget)

Operator policy already has two layers (`docs/ops/DEEPSEEK_BULK_WINDOW_ET_2026-08-19.md`,
`docs/ops/MATURATION_G1_I0_A1_B1_2026-08-21.md`):

| layer | window | purpose |
|---|---|---|
| Operator bulk ET | 10:00–21:00 `America/New_York` | when substantial Flash/Pro bulk is allowed |
| Official DeepSeek peak UTC | Mon–Fri 01:00–04:00 and 06:00–10:00 UTC | hard extra skip for bulk; **half-rate elsewhere** (Sat/Sun always off-peak) |

A.1 already moved Peak-A/B leftovers into 10:00–20:00 ET + PEAK_SKIP wrapper. That keeps
**Eastern semantics**. F6 addresses the remaining class: overnight / premarket LLM work whose
**ET hour field maps into official UTC peak under daylight time**, so the wrapper exits 0
(`PEAK_SKIP`) and the work never runs until the next non-peak tick — or never, for once-daily
jobs.

UTC proposals make the billable window the schedule, instead of relying on skip-and-miss.

---

## 2. Sources read (no install)

| source | role |
|---|---|
| Host `crontab -l` (2026-08-31) | live Eastern wall-clock schedule |
| Repo `crontab_backup.txt` | checked-in snapshot (lags host; still useful for retired annotations) |
| `config/lane_registry.json` | lane state; LLM lanes mostly `RETIRED` / `PAUSED` / `NEVER_SCHEDULED` — active LLM work is mostly raw cron, not registry timers |
| `config/systemd/user/*.timer` | timers with explicit TZ (`America/New_York`, `Asia/Shanghai`) vs host-local calendars |
| `scripts/lib/deepseek_offpeak.py` | peak + bulk gate |
| `~/.config/tradeai/bin/run_with_deepseek_offpeak.sh` | host PEAK_SKIP wrapper (`--gate` / `--official`) |
| Home crontab backups `~/crontab_backup_*.txt` | historical ET inventory |

**Lane registry note.** `deep-overnight-llm` is `RETIRED` (Phase 102). Flash / Hermes
research timers are `PAUSED`. Active LLM spend is dominated by host crontab lines and a few
systemd units — not by ACTIVE registry lanes.

---

## 3. Peak vs half-rate (proposal rules)

1. **Never schedule bulk DeepSeek for Mon–Fri inside** `01:00–04:00` or `06:00–10:00` **UTC**.
2. Prefer **half-rate (off-peak) UTC hours**: `00:00–01:00`, `04:00–06:00`, and `10:00–24:00` UTC
   Mon–Fri; all hours Sat/Sun.
3. Keep `run_with_deepseek_offpeak.sh` as a safety net after retarget (belt + suspenders), but
   the schedule itself must not depend on daily PEAK_SKIP for once-daily jobs.
4. Market-open–tied jobs (09:30 ET open, RTH enrichers) stay on `America/New_York` semantics —
   either leave ET crontab or use systemd `OnCalendar=… America/New_York`. Do **not** freeze
   them to a single UTC hour year-round.
5. Continuous drains that currently use `*/15` / `*/30` in bulk ET may adopt **half-rate cadence
   outside bulk** (e.g. `*/30` instead of `*/15`) if operator later extends UTC coverage; this
   doc proposes bulk-window UTC equivalents first.

**EDT snapshot used for “current → UTC” columns:** 2026-08-31 is EDT (`UTC−4`). EST column
shows the winter offset (`UTC−5`) so DST risk is visible without installing anything.

---

## 4. Proposal table — 32 LLM-heavy jobs

**Legend**

- **Current ET:** live host crontab minute/hour (host TZ Eastern; no `CRON_TZ`).
- **EDT→UTC / EST→UTC:** naive fixed conversion of that wall-clock (shows DST drift).
- **Proposed UTC cron:** recommended `CRON_TZ=UTC` expression (or systemd `OnCalendar=… UTC`).
- **Why:** peak collision, half-rate landing, or explicit UTC ownership.
- **Wrap:** existing wrapper mode on the live line (`gate` = bulk ET+peak, `official` = UTC peak only, `none`).

### 4.1 Overnight / premarket jobs that land in UTC peak under EDT (move out of peak)

| # | Job | Current ET | EDT→UTC (naive) | Peak hit? | Proposed UTC cron | Why |
|---|---|---|---|---|---|---|
| 1 | `run_research_intelligence_overnight.sh --phase full` (02:15) | `15 2 * * *` | `15 6 * * *` | **06–10** | `15 4 * * *` | Half-rate slot `04–06` UTC; keep `--official` wrapper |
| 2 | `topic_ingestion.py --use-llm-queries` | `45 2 * * *` | `45 6 * * *` | **06–10** | `45 4 * * *` | Same half-rate band; after RI full |
| 3 | `research_intelligence_queue.py --drain` (overnight) | `40 2 * * *` | `40 6 * * *` | **06–10** | `40 5 * * *` | Half-rate `04–06`; stagger from #1–2 |
| 4 | `hermes_backlog_drain.py` nightly | `20 2 * * *` | `20 6 * * *` | **06–10** | `20 5 * * *` | Half-rate; keep `--official` |
| 5 | `hermes_source_curation.py` | `30 23 * * *` | `30 3 * * *` | **01–04** | `30 4 * * *` | Exit Peak A into `04–06` half-rate |
| 6 | `commit_hermes_daily.sh` | `13 23 * * *` | `13 3 * * *` | **01–04** | `13 4 * * *` | Same; after curation |
| 7 | `multi_tier_trade_reviewer.py --tier overnight` | `30 22 * * 1-5` | `30 2 * * 1-5` | **01–04** | `30 4 * * 1-5` | Weekday overnight review off-peak |
| 8 | `topic_research_synthesizer.py --reground` | `50 21 * * *` | `50 1 * * *` | **01–04** | `50 0 * * *` | Pre-peak `00–01` half-rate |
| 9 | `opening_intelligence.py --persist` (03:30) | `30 3 * * 1-5` | `30 7 * * 1-5` | **06–10** | `30 4 * * 1-5` | Half-rate; still pre-RTH in EDT winter/summer — **re-check vs 09:30 ET** before install |
| 10 | `opening_intelligence.py --persist` (05:30) | `30 5 * * 1-5` | `30 9 * * 1-5` | **06–10** | `30 10 * * 1-5` | First half-rate hour after morning peak |
| 11 | `hermes_tag_lift_discovery.py` | `50 3 * * *` | `50 7 * * *` | **06–10** | `50 4 * * *` | Half-rate band |
| 12 | `hermes_industry_novelty_discovery.py` | `25 4 * * *` | `25 8 * * *` | **06–10** | `25 5 * * *` | Half-rate band |
| 13 | `hermes_discovery_yield_builder.py` | `45 3 * * *` | `45 7 * * *` | **06–10** | `45 5 * * *` | Half-rate; after outcome bus |
| 14 | `hermes_discovery_scorecard.py` | `30 5 * * *` | `30 9 * * *` | **06–10** | `30 10 * * *` | Post morning-peak |
| 15 | `run_research_intelligence_overnight.sh --phase archive` | `15 5 * * *` | `15 9 * * *` | **06–10** | `15 10 * * *` | Archive after peak; keep `--official` |
| 16 | ATP2 `--cycle overnight` | `30 0 * * 2-6` | `30 4 * * 2-6` | edge `04:30` OK | `30 4 * * 2-6` | Adopt explicit UTC (same EDT landing); document EST drift → `05:30` UTC |
| 17 | ATP2 `--cycle premarket_4am` | `0 4 * * 1-5` + `--official` | `0 8 * * 1-5` | **06–10** | **leave latency-sensitive** *or* `0 10 * * 1-5` | A.1 left this peak-priced on purpose. Proposal A: keep ET+wrapper. Proposal B (UTC): `10:00` UTC half-rate — **operator chooses**; default recommendation = **keep ET** (listed for completeness, counts as proposed decision) |

### 4.2 Bulk / daytime LLM already in operator bulk ET — UTC ownership (avoid DST ambiguity)

These mostly already sit in half-rate UTC under EDT. Proposal is to pin `CRON_TZ=UTC` (or
document `CRON_TZ=America/New_York`) so winter does not silently slide them toward peak.

| # | Job | Current ET | Proposed UTC cron (EDT-equivalent pin) | Winter EST pin (alt) | Notes |
|---|---|---|---|---|---|
| 18 | `run_watchlist_agent_jobs_offpeak.sh` bulk | `*/15 10-20 * * *` | `*/15 14-23,0 * * *` **bad wrap** → prefer `CRON_TZ=America/New_York` **or** split `*/15 14-23 * * *` + `*/15 0 * * *` under UTC only in EDT season | DST-sensitive range | **Recommend keep ET TZ** for hour ranges; if forcing UTC, maintain two seasonal crons |
| 19 | `research_scheduler.py --mode holdings` | `0 8 * * 1-5` | `0 12 * * 1-5` | `0 13 * * 1-5` | Half-rate; after 10:00 UTC peak |
| 20 | `research_scheduler.py --mode priority` | `0 10-16 * * 1-5` | `0 14-20 * * 1-5` | `0 15-21 * * 1-5` | Aligns with bulk; keep `LLM_GLOBAL_DAILY_USD_CAP` |
| 21 | `research_scheduler.py --mode cold-floor` | `0 10 * * *` (A.1) | `0 14 * * *` | `0 15 * * *` | Already off Peak B |
| 22 | `llm_intelligence_enrichment.py` morning synth heavy | `15 8 * * 1-5` | `15 12 * * 1-5` | `15 13 * * 1-5` | Heavy sections |
| 23 | `holdings_llm_refresh.py` | `15 7 * * 1-5` | `15 11 * * 1-5` | `15 12 * * 1-5` | Just after morning peak ends |
| 24 | `incubator_llm_screener.py` | `10 8 * * 1-5` | `10 12 * * 1-5` | `10 13 * * 1-5` | |
| 25 | `shadow_batch_generator.py` daily | `15 9 * * 1-5` | `15 13 * * 1-5` | `15 14 * * 1-5` | Full LLM critique batch |
| 26 | `proposal_llm_review_worker.py` | `*/30 6-19 * * 1-5` | `*/30 10-23 * * 1-5` | `*/30 11-0 * * 1-5` | Range DST-fragile — prefer ET TZ or seasonal pair |
| 27 | `cloud_consensus_verdict.py` | `*/30 9-16 * * 1-5` | `*/30 13-20 * * 1-5` | `*/30 14-21 * * 1-5` | External LLM policy = market hours; **prefer ET TZ** |
| 28 | `hermes_subject_enhance.py` scalp/proposal | `*/30` / `*/20` `9-16 * * 1-5` | map to `13-20` UTC (EDT) | `14-21` UTC (EST) | Grok+ChatGPT; market-hours — **prefer ET TZ** |
| 29 | `auto_research.py` (A.1 → 20:00 ET) | `0 20 * * 1-5` + gate | `0 0 * * 1-5` | `0 1 * * 1-5` | `00:00` UTC is half-rate; EST pin `01:00` **enters Peak A** — seasonal risk |
| 30 | `aegis_synthesis.py` (A.1 → 20:00 ET) | `0 20 * * *` + gate | `0 0 * * *` | `0 1 * * *` | Same DST cliff as #29 |
| 31 | `trade_close_llm_analyzer.py` structured (A.1) | `0 20 * * 1-5` + gate | `0 0 * * 1-5` | `0 1 * * 1-5` | Same DST cliff |
| 32 | `health_agent_llm_review.py` | `30 20 * * 1-5` | `30 0 * * 1-5` | `30 1 * * 1-5` | EST pin enters Peak A — move to `30 0` year-round UTC **or** keep ET |

**Count:** 32 rows proposed (decisions + UTC expressions). Rows 18, 26–28 explicitly recommend
**retaining Eastern TZ** rather than a brittle UTC range; they still count as F6 scheduling
proposals (UTC-vs-ET ownership decision).

---

## 5. DST risk (load-bearing)

| fact | consequence |
|---|---|
| Host TZ is `America/New_York` (EDT −4 / EST −5) | Crontab hour fields are Eastern wall-clock today |
| DeepSeek peak is fixed **UTC** | The same ET hour is peak in summer and off-peak in winter (or the reverse) |
| Example: `0 20 * * 1-5` ET | EDT → `00:00` UTC (half-rate) · EST → `01:00` UTC (**Peak A starts**) |
| Example: `15 2 * * *` ET | EDT → `06:15` UTC (**Peak B**) · EST → `07:15` UTC (**still Peak B**) |
| Example: `0 4 * * 1-5` ET ATP2 | EDT → `08:00` UTC (peak) · EST → `09:00` UTC (peak) — always peak under naive UTC |

**Operator install choices (pick one per job family):**

1. **`CRON_TZ=UTC` + fixed off-peak UTC hours** — best for pure cost control; market-open
   alignment will drift ±1h across DST.
2. **`CRON_TZ=America/New_York` (or systemd `… America/New_York`)** — best for RTH-tied jobs;
   keep PEAK_SKIP wrapper so UTC peak still cannot bill bulk.
3. **Seasonal dual crontab** — two UTC expressions swapped at DST boundaries (highest toil;
   only if UTC-only hosts appear).

F6 default recommendation: **(1) for overnight LLM batch**, **(2) for RTH / market-hours LLM**.

---

## 6. Systemd timers (inventory — propose TZ annotation, do not enable)

Already TZ-explicit (no F6 change required beyond documentation):

| timer | calendar |
|---|---|
| `hermes-autonomous-loop.timer` | `18…08:10 Asia/Shanghai` (official off-peak) — **do not retune into overnight ET** (A.1 rail) |
| `hermes-deep-research-local.timer` | `22…05:35 America/New_York` |
| `tradeai-free-first-circulation.timer` | `:23 America/New_York` (FREE_FIRST_ONLY — not paid DeepSeek) |
| `tradeai-cio-desk-memo-regen.timer` | `17:45 America/New_York` (disabled by default) |

Host-local calendars (inherit machine TZ = Eastern today; **ambiguous if host TZ ever changes**):

| timer | OnCalendar | F6 note |
|---|---|---|
| `tradeai-cio-nightly-reflection.timer` | `21:50:00` | Pin `America/New_York` or move to `01:50 UTC` only if LLM-backed and peak-checked |
| `tradeai-advisory-lessons-reflect.timer` | `21:40:00` | Same |
| `tradeai-advisory-shadow-seed.timer` | `21:45:00` | Same |
| `tradeai-cio-event-brief.timer` | Mon–Fri `07:50:00` | Prefer `America/New_York` (premarket) |
| `tradeai-hermes-cio-worker.timer` | `*:0/15` | Continuous; paid path already cost-capped / often paused — operator only |
| `tradeai-advisory-shadow-session.timer` | Mon–Fri `09:15:00` | Prefer `America/New_York` |

These timer TZ pins are **not** counted in the 32 cron proposals; they are adjacent operator
hygiene.

---

## 7. Explicitly out of scope / do not install from this wave

- Any crontab or systemd edit from an agent session.
- Raising `LLM_GLOBAL_DAILY_USD_CAP`.
- Re-enabling `deep-overnight-llm` / Phase 102 retired Friday extended window.
- Retuning `hermes-autonomous-loop.timer` into overnight ET.
- Scheduling `cio_residual_web` (remains operator-only / NEVER_SCHEDULED under overnight rails).
- Broker, order, stop, 2FA, or MBI surfaces.

---

## 8. Operator-only install sketch (propose and stop)

```bash
# 0) Backup
crontab -l > ~/crontab_backup_pre_f6_utc_$(date +%Y%m%d_%H%M%S).txt

# 1) Prefer a UTC fragment file reviewed offline, e.g.:
#    CRON_TZ=UTC
#    15 4 * * *  … run_research_intelligence_overnight.sh --phase full …
#    …

# 2) Apply only after diffing against the backup (human).
# 3) Leave run_with_deepseek_offpeak.sh wrappers in place.
# 4) Soak one Mon–Fri cycle; confirm zero PEAK_SKIP for once-daily jobs that were moved.
# 5) Do not promote from this docs PR — docs only.
```

Rollback: `crontab < ~/crontab_backup_pre_f6_utc_….txt`.

---

## 9. Related

- `docs/ops/DEEPSEEK_BULK_WINDOW_ET_2026-08-19.md`
- `docs/ops/MATURATION_G1_I0_A1_B1_2026-08-21.md`
- `docs/ops/HERMES_FREE_FIRST_NATURAL_SCHEDULER_2026-08-23.md`
- `scripts/lib/deepseek_offpeak.py`
- `config/lane_registry.json` (LLM lanes mostly non-ACTIVE)
- Pointer: `docs/ops/F6_UTC_CRON_PROPOSALS.md`

---

## 10. File set

| file | change |
|---|---|
| `docs/audits/overnight/F6_UTC_CRON_PROPOSALS_2026-08-31.md` | this audit |
| `docs/ops/F6_UTC_CRON_PROPOSALS.md` | thin pointer to the dated audit |

**Jobs proposed: 32.** Installs performed: **0**.
