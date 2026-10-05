# Trade AI — QUESTION & RESEARCH LIFECYCLES (family B), re-measured

Status: ACTIVE
as_of: 2026-10-04T21:21-04:00 (measurements taken 20:41–21:21 ET)
Measured at: 4f932b88a

```
Family:      B — Questions and research (B1 operator question · B2 system-raised questions · B3 Hermes research · B4 topic research)
Baseline:    docs/architecture/lifecycles/LIFECYCLE_FACTBASE_B_QUESTIONS_2026-09-14.md, and family B of TRADE_AI_AS_IS_LIFECYCLES_2026-09-14.md
Served:      CURRENT → 4f932b88a-main-exact-phase2-20261004-202102 (dev tree HEAD 4f932b88a; the API reports pin_match=true)
Running:     tradeai-cio-telegram started 20:22:06 ET and cio-governed-bridge started 20:22:03 ET, both after the 20:21 promote, so the code is current
Stores:      CURRENT/data/cio, dev data/cio and data/runtime all resolve to persistent-state/data/* (MEASURED: readlink -f)
Method:      read-only. SELECT inside SET TRANSACTION READ ONLY; python jsonl readers; crontab -l; systemctl --user show/cat;
             journalctl; GET http://localhost:7777 only. No LLM, broker, Telegram or POST calls.
Labels:      MEASURED (command or file:line) · DOCUMENTED (taken from docs, commit text or code comments, not observed in data)
Maturity:    L0 exists · L1 provenance+liveness · L2 grounded · L3 judgment validated · L4 loop closed · L5 unattended self-repair+self-report
Window:      "7d" = created_at/ts ≥ 2026-09-27 (UTC) unless stated
```

## 0 · Scoreboard: 09-14 breaks against today

| # | 09-14 break | Today | Evidence |
|---|---|---|---|
| B1 | 26 Hermes jobs orphaned outside the projection | **Partly fixed.** New losses are restored, but **20 pre-09-14 orphans (08-31 → 09-12, all `high`) are still `queued` and missing from the projection.** No alarm sees them | MEASURED: ledger replay vs `hermes_research_projection.json` by_research_id. Restore window 48 h (`cio_hermes_research.py:1362`); health window 24 h (`cio_hermes_queue_health.py:142,151`) |
| B2 | Pending reply not joined to research; subject lost (SpaceX→BOOK) | **Fixed.** 9 pendings all-time: 7 fulfilled, 2 expired. Since 09-14: 7/8 fulfilled and 1 honest expiry. S0 operator requests now carry the subject (NFLX, QURE) | MEASURED: `cio_operator_pending_replies.jsonl`; requests ledger S0 rows |
| B3 | 79% of 7d Hermes jobs fail; 0 thesis changes | **Fixed (failure).** 7d: 182/197 completed (92.4%), 14 failed (7.1%). 14 results WEAKENS/CONFLICTED, but `material_changed` is False on 179/180 and `notified` is False on 180/180 | MEASURED: requests/results ledgers |
| B4 | Alphabetical target starvation and non-security subjects | **Half fixed.** ABOVE/AGAIN: 0 in 7d. The cron still runs `sort -u` + `--limit 5`; 24 of 36 subjects in 7d start A–E; NVDA/OXY/SNDK/XLI sit below the cut | MEASURED: crontab line 1022; `research_objects.jsonl`; `research_targets.jsonl` |
| B5 | Research objects never consumed or advanced | **Worse ratio.** 7d: 2,850 produced, **77 consumed (2.7%)**, all `IDENTIFIED` | MEASURED: research_objects vs `state/receipts.jsonl` source_id |
| B6 | Questions never close | **Unchanged.** DDQ 2,341 rows, `answer_ids` 0, `supersedes_guid` 0, statuses only ASKED/ROUTED; 242 ASKED (oldest 6.5 d). `research_gaps.jsonl` OPEN 118, OPEN_NO_ATTEMPT 118 | MEASURED: DB, `gap_resolution_last_run.json` |
| B7 | TOPIC slugs routed to the security worker | **Masked by an upstream outage.** 0 TOPIC events in 7d, because topic ingestion has been skipped since 09-28. The code path is unchanged | MEASURED: `topic_curator.py:502-504`; `agent_event_router.py:102` |
| B8 | Replies not ledgered or persisted | **Partly fixed.** Agent reply turns on 13/21 free-text questions (62%, was 20.5%); 19/19 desk receipts carry `reply_provenance`. `communication_events` OUTBOUND still has **0 desk producers** | MEASURED: DB |
| B9 | Promoted HRI never expires; staged not reviewed | **Unchanged on expiry.** `research_expires_at` is NULL on 2,781/2,781 promoted. Promotion throughput recovered (77–169/day). `trigger_source`/`lane_used` are NULL on 1,053/1,053 7d rows | MEASURED: DB |
| B10 | Topic research subject-less | **Unchanged.** HRI topic_research 7d: 209, symbol NULL 209. Curation feedback newest 2026-09-02 (32 d) | MEASURED: DB |

**New since 09-14:**
- **N1. Topic ingestion silently dead since 2026-09-28.** `non_trading_hours_gate.sh:18` calls `.venv/bin/python` relative to the release dir, and the release dir has no `.venv`. The gate prints "session check FAILED … skipping job" and **exits 0**, 7 times. MEASURED: `persistent-state/logs/topic_ingestion.log`; `ls CURRENT/.venv` → absent. The same gate wraps crontab lines 780–784 (`run_resear…`) — INFERRED same failure, not checked per job.
- **N2. Research Circle phase 1 has never written its ledger.** `data/cio/research_circle_ledger.jsonl` and `…_checkins.jsonl` do not exist (MEASURED; path at `research_circle.py:57-58`). Phase 2 (`quality_escalate`) is live: 88 SearXNG climbs in 7d, **all `partial`, 0 lifted to answered** (MEASURED: receipts).

---

## B1 · OPERATOR QUESTION LIFECYCLE (Telegram desk · Maria · CIO desk)

### (a) Purpose, actors, stores
- **Purpose:** unchanged. Answer from house data first. On a gap, run declared vectors, then answer, defer with a pending row, or say "no coverage". Close every pending row.
- **Actors:**
  - `tradeai-cio-telegram` (`cio_telegram_bot.py --loop`).
  - `cio_converse_core.py` and `cio_operator_desk_loop.py` (5,236 lines; `try_fulfill_pending_replies` `:5095`).
  - **New since 09-14:**
    - `hermes_subject_join.py` + `operator_internal_first.py` (398c3ab64, 09-23: "Shared Hermes join + internal-first reply chokepoint for desk/Maria parity").
    - `maria_parity_hook.py` → `maria_desk_exchanges.jsonl`.
    - lineage ids across turn → gap → research → outbound (4f9c2fa88, 09-23).
  - Unchanged: `gap_resolver.py` (now also driven by cron `data_gap_resolver.py`, wired 5f6568f08, 09-20) and `tradeai-operator-answer-quality` (30 min). DOCUMENTED (git log)
- **Stores:**
  - `operator_conversation_turns` (DB).
  - `cio_events.jsonl` `operator.message`.
  - `cio_operator_pending_replies.jsonl`.
  - `cio_operator_gap_requests.jsonl`.
  - `gap_resolution_receipts.jsonl`: **now exists**, 8,339 rows, 4.6 MB.
  - `maria_desk_exchanges.jsonl` (new).
  - DB `gap_resolution_outcomes`: **0 rows**.
  - `data_gap_registry`: 86 rows (resolved 83, abandoned 3; newest 10-03).
  - MEASURED (ls, SELECT).

### (b) State machines
- **Desk `kind`:** unchanged set. Observed since 09-14 (MEASURED, 19 `operator.message` receipts):
  - answered 15: deepseek_flash 9, freeform_flash 3, deterministic 1, gap_resolver:backup_provider 1, gap_resolver:llm_curation 1.
  - deferred 3.
  - no_coverage 1.
- **Pending:** `open → fulfilled | expired`, append-only. New pending `kind` values: `soft_research_queue`, `buy_perspective_research_first`, `interim_plus_hermes_queue` (MEASURED ledger). Expiry reasons are now specific, e.g. "the Hermes research run failed (execution language not allowed…)" at 0.1 h (MEASURED, opr_40a1c8f0876c).
- **Gap receipt `outcome`** (7d, MEASURED):
  - partial 183, budget_denied 227, no_answer 134.
  - queued 13 (hermes_research 3, operator_ask 10).
  - error 5.

### (c) Flow (today)
```
 OPERATOR / Maria(skill) ══▶ 1 POLL (bot restarted with each promote: 66 starts/7d) ══▶ 2 TAG+PERSIST
   (373 operator "messages" since 09-14, but 349 are `gapprove:` button callbacks, 3 slash, 21 free text)
 ══▶ 4 INTENT+SUBJECT (free text bound to subject_guid 5/21) ══▶ 5 EVIDENCE (internal-first chokepoint)
 ══▶ 6 GAP RESOLVE (receipts 562/7d: requester data_gap_resolver 535 · desk 13 · operator 14) ──┐
 ══▶ 7 HERMES ENQUEUE (S0 now keeps the subject + the operator's words) ══▶ 8 PENDING (gap_requests: research_id 10/30)
 ══▶ 9 CURATE (pills/legend) ══▶ 10 SEND (19/19 receipts with reply_provenance) ✗✗▶ communication_events (0 desk rows)
 ══▶ 11 AGENT TURN (13/21 free-text questions) ══▶ 12 FULFIL from Hermes result (7 fulfilled · 1 honest expiry since 09-14)
 ══▶ 13 TURN → WAKE (219/573 wakes in 7d carry prior_operator_turn_ids) ══▶ 14 AQ AUDIT (0 findings last runs)
```

### (d) Iterations
| loop | closes? | evidence |
|---|---|---|
| poll | yes | bot active; 0 error/traceback lines in 7d journal (MEASURED `journalctl -u tradeai-cio-telegram`) |
| pending re-check → fulfil | **yes** | fulfil latency: SCHG 64 s, S 45 s, NOK 33 s, QURE 6.9 min, HPE 84 min (MEASURED ledger ts) |
| pending expiry | yes, honest | MCD expired 0.1 h with cause (MEASURED) |
| gap → resolver | runs | 562 receipts/7d. But 118 `research_gaps` OPEN with no attempt; `tradeai-gap-resolution` exits 1 every 30 min, alert "suppressed — unchanged" (MEASURED journal) |
| operator turn → wake (M3) | **yes now** | 219/573 7d wakes carry operator turn ids (was 1 turn ever) (MEASURED `state/wakes.jsonl`) |
| AQ audit → repair | report only | findings 1–4 on 236 of 672 runs in 14d; 0 in latest runs (MEASURED journal) |

### (e) Questions
| question | fate today |
|---|---|
| "what does the operator want, about which instrument?" | 21 free-text asks since 09-14; subject_guid bound on 5. Single-letter `S` (SentinelOne, 5 asks 09-22) and misspelt "nexflix" were unbound in turns, but the desk resolved NFLX for Hermes (MEASURED) |
| "fetch the missing fact" | resolver receipts exist; operator-origin receipts 27/7d |
| "outlook for X" (Hermes) | enqueued with the subject and the operator's words, e.g. "NFLX — operator asked: how is nexflix…" (MEASURED requests ledger) |
| "has the research landed?" | joined by pending → gap_request → research_id → result; 7 delivered |
| Maria questions | 84 exchanges (83 in 7d) recorded; `prose_author` = "downstream LLM (Maria) — not recorded here" 84/84; `decision_integrity_state` NULL 84/84 (MEASURED `maria_desk_exchanges.jsonl`) |

### (f) Live measurements (MEASURED unless noted)
| metric | 09-14 | 10-04 |
|---|---|---|
| free-text operator questions | 39 msgs/8 d | 21 since 09-14; **3 in last 7d** (09-29, 09-30, 10-02) |
| replies captured as agent turn | 8/39 (20.5%) | 13/21 (62%); 7d 2/3 |
| question → reply p50 / p90 | 6.2 s / 14.6 s | 16.7 s / 31.5 s (n=13) |
| subject-bound questions | 25% | 24% (5/21) |
| replies with provenance | 1/8 | receipts 19/19 `reply_provenance`; agent turns with legend/pills 16/22 |
| pendings | 1 (expired late) | 9 all-time: fulfilled 7, expired 2; none open; last pending 09-30 |
| resolver receipts | 0 | 8,339 all-time; 562 in 7d; peak 3,470 on 09-24 |
| desk replies in communication_events | 0 | 0 (OUTBOUND 7d producers: send_telegram 9,223, notify_material_change 15, …) |
| AQ findings (latest) | 7 | 0 (24 h window: 0 turns) |

### (g) Failure paths
1. **Callback noise in the turns store.** 349/373 operator rows since 09-14 are `gapprove:<id>` button presses. Turn-based metrics and memory recall must filter them (MEASURED).
2. **Replies are still not OUTBOUND-ledgered** (0 desk producers).
3. **One pending was not opened at ask time.** NFLX (opr_7d1784a8d832) carries a `backfill` note: "2026-09-29 agent: pending was never opened; Hermes rr_4a877da8499b alr…". The row was written by hand after the fact (MEASURED).
4. **Gap requests lack research_id** on 20/30 rows; the join falls back to subject_guid (9329322a0, DOCUMENTED).
5. **Gap monitor stuck firing.** It exits FAILURE (status 1) on 118 OPEN_NO_ATTEMPT gaps and suppresses its alert as "unchanged".
6. **The desk still contains `symbols[:4] or ["BOOK"]`** (`cio_operator_desk_loop.py:3189`). Measured S0 requests in 7d all carried a subject.
7. **Maria answers are unrecorded prose**, so desk/Maria parity cannot be verified from data.

### (h) Maturity per stage
| stage | 09-14 | now | one-line evidence |
|---|---|---|---|
| 1 poll | L1 | **L2** | restarts with each promote; pin_match true; 0 errors 7d |
| 2 tag/persist | L1–L2 | L1–L2 | callbacks pollute operator turns; 24% bound |
| 3 route | L1 | L1 | unchanged |
| 4 intent/subject | L2 | **L3** | S0 Hermes requests carry subject + the operator's words; dictated tickers resolve |
| 5 evidence | L2 | **L3** | internal-first chokepoint; MCD answered from house data on refusal (54677c4fc) |
| 6 gap resolve | L0 runtime | **L2** | 562 receipts/7d; mostly budget_denied/no_answer; 118 gaps never attempted |
| 7 Hermes enqueue | L1 | **L3** | subject kept (MEASURED S0 rows) |
| 8 defer/pending | L1 | **L2** | ledgered and joined; 1 manual backfill |
| 9 curate | L2–L3 | L3 | pills/legend on 16/22 agent turns |
| 10 provenance+send | L1 | **L2** | 19/19 reply_provenance; not OUTBOUND-ledgered |
| 11 agent turn | L1 | **L2** | 62% capture |
| 12 fulfil | L0 | **L4** | joined, delivered, honest expiry, AQ rule `RESEARCH_LANDED_UNSENT` watching |
| 13 turn → wake/memory | L0 | **L2** | 219/573 wakes carry operator turns |
| 14 AQ audit | report L5 / repair L0 | same | no repair consumer |

### (i) Target / exit
| exit condition | 09-14 | now |
|---|---|---|
| every free-text ask has one sourced reply turn | 20.5% / 12.5% | **62% / ~73%** (16/22 turns) — not met |
| research-blocked pendings fulfilled from Hermes result | 0/1 | **7/8 since 09-14** (1 honest failure) — met in practice |
| resolver receipt for every blocking gap | 0 | operator gaps yes; 118 system gaps OPEN_NO_ATTEMPT — not met |
| desk replies ledgered OUTBOUND | 0 | 0 — not met |
| a new turn changes the next wake | not met | wakes ingest turns (219); effect not isolated — partial |

**Delta since 2026-09-14:**
- The question→research→follow-up loop now closes: 7 deliveries, subject preserved, honest expiry.
- Reply capture rose 20%→62%.
- Gap receipts went from absent to 8.3k.
- Operator turns now reach wakes.
- Still open: the OUTBOUND ledger, callback noise, Maria prose capture.
- Traffic is very low: 3 free-text asks in 7d, so these rates rest on small n.

---

## B2 · SYSTEM-RAISED QUESTIONS (2A wake research · 2B DDQ · 2C situations · Research Circle · free-search fallback)

### (a) Purpose, actors, stores
**2A — wake research**
- Cron `:45` builds targets with `jq | sort -u`, then runs `run_governed_research_producer.py --limit 5 --execute` (now with `RESEARCH_FREE_FALLBACK=1`). Hourly `:00` wake (crontab lines 1022, 1020). MEASURED.
- New writer: `wake_critique_question.jsonl` (CritiqueQuestionWriteback@v1) persists `next_research_question`. MEASURED.
- `cio_wake_dispatch_entrypoint.py` `*/5` → `wake_research_persist.json`. MEASURED file header.

**2B — DDQ**
- `due_diligence_questions.py --apply --route`, `*/20`, `LLM_GLOBAL_DAILY_USD_CAP=2.00` (was 7.00). MEASURED: crontab line 1016.

**2C — situations**
- `cio_situation_detector` → `cio_plans.jsonl`.
- `tradeai-cio-defer-revisit.timer` is now **active** (last ran 20:27 ET). MEASURED: list-timers.

**Research Circle**
- Phase 1 is `research_circle.py` + `run_research_circle.py`. It has no cron/timer, and its ledger is absent. MEASURED.
- Phase 2 `research_quality_escalate.py` is armed by the host flag `~/.config/tradeai/research_quality_escalate` (content "1", 09-19) and runs inside `gap_resolver`. MEASURED.

**Free search**
- `free_search.py`; budget in `runtime/search_budget.json`. MEASURED.

### (b) State machines
| machine | states observed | MEASURED counts |
|---|---|---|
| research object `lifecycle_state` | IDENTIFIED only | 7,422/7,422 |
| wake receipt `effect_kind` (7d) | none 1,577 · changed_question 132 · changed_commitment 16 · changed_view 16 | source_kind: comm_event 924, memory_fact 663, research_object 100, operator_turn 27, instrument_record 27 |
| wake `decision_summary.effect_kind` (7d, 573 wakes) | changed_commitment 347 · changed_question 209 · None 17 | lifecycle SETTLED 556, MEMORY_MALFORMED 17 |
| `next_research_question` persistence | CritiqueQuestionWriteback applied/persisted | 31 rows 09-19 → 10-04 (agent_views/views still contain 0) |
| DDQ `status` | ASKED · ROUTED (no other value ever) | ROUTED 2,099 · ASKED 242 · answer_ids 0/2,341 · supersedes 0 |
| plan status transitions (7d) | expired 643 · cancelled 159 · proposed 26 | 325 created, 276 shadow; last status: draft 188, cancelled 111, proposed 26 |
| denial receipt `spilled_to` | searxng / null | 7d: 201/201 → searxng; all-time null 130 (pre-09-16) |

### (c) Flow
```
 material_changes ─▶ selection feed ══ :45 jq|sort -u ══▶ 11 targets (ADBE, AMC, AVAV, J, NOW | NVDA, NWTG, OXY, SMC, SNDK, XLI)
        --limit 5 → ADBE..NOW every hour ⟳ (alphabetical head unchanged)
 2A PRODUCER ─▶ Brave (caller cap 25/day, hit every day) ─✗cap─▶ free_search → SearXNG (201/201 spilled 7d)
        ◀── research_objects 360/day (15/run × 24) — 2,850/7d, consumed 77 (2.7 %)
 2A WAKE ─▶ 573 wakes/7d ─▶ changed_question 209 ─▶ critique writeback next_research_question (31 rows total) ✗✗▶ next target
 2B DDQ curate (~150–190/day 09-28..10-02, 8 on 10-04) ─▶ route ~70/day (1 per run), 126–144 on 10-03/04
        ─▶ hermes_external_research (sent 7d: chatgpt 655, grok 652, deepseek 485) ✗✗▶ answer_ids (0)
 2C situation ─▶ plan (325/7d) ─▶ Hermes (197 requests/7d) ; plan expiry/revisit now fires (643 expired)
 GAP: research_gaps OPEN 118 ─▶ gap-resolution monitor OPEN_NO_ATTEMPT 118 (alert suppressed) ✗✗▶ resolver
 CIRCLE ph.2: gap_resolver partial → quality_escalate → SearXNG +5 hits → still partial (88/88)
```

### (d) Iterations
| loop | closes? | evidence (MEASURED) |
|---|---|---|
| target build → produce | runs, starves | 36 distinct subjects in 7d, 24 start A–E; ABNB 432 objects, AMZN 201 |
| produce → consume | **worse** | 77/2,850 (2.7%) vs 143/675 (21%) |
| consume → question → next target | **partial** | question text persisted (31); no edge into `research_targets.jsonl` (cron rebuilds from material_changes only) |
| DDQ ask → route | drains ~1/run | 242 ASKED from 09-28..09-30 still unrouted |
| DDQ answer → close | **no** | answer_ids 0/2,341 |
| plan → revisit/expire | **yes now** | 643 `expired` transitions in 7d |
| refusal → free search | **yes** | REFUSED_NOWHERE 0 (`gap_resolution_last_run.json`) |
| thin answer → escalate | runs, no lift | quality_escalate 88 × partial |

### (e) Questions and their fate
| question | n (7d) | fate |
|---|---|---|
| "What changed after <headline>?" | 132 receipts / 209 wakes | text now persisted via critique writeback (31 total); not fed to targeting |
| research need on material subject | 5 targets/h | Brave 25/day, then SearXNG; objects IDENTIFIED forever |
| DDQ (why_now / settle) | 879 created 09-28..10-04 | routed, never closed; settle never tested |
| plan S-type questions | 197 Hermes requests | 92% completed (B3) |
| Research Circle question_guid laps | 0 | phase 1 never run live (no ledger) |

### (f) Live measurements (MEASURED)

**Research objects**
- 360/day flat since 09-26 (2,850 in 7d).
- 0 on ABOVE/AGAIN in 7d (396 all-time).
- `identity_status` field absent on 7d rows.

**Producer health 00:45Z**
- `produced=15 failed=0 budget_denied=0 free_answered=0 spills_recorded=0`, source_sha 4f932b88a.
- 7d denial receipts: 201, all spilled to searxng.

**Brave**
- 25/day every day; monthly 2026-09 579/1,500; 2026-10 105.
- denied/day 5–47.

**SearXNG**
- daily 47–243.
- callers 2026-10: hermes_cio_research 290, governed_research_producer 63, gap_resolver 31, research_quality_escalate 31.

**DDQ**
- created/day: 09-28 132 · 09-29 185 · 09-30 187 · 10-01 168 · 10-02 157 · 10-03 29 · 10-04 8.
- routed/day: 70 · 72 · 70 · 72 · 70 · 144 · 126.
- oldest ASKED 2026-09-28 09:00 ET.

**Plans 7d**
- S3 231, S7 49, S5 17, S6 17, S1 8, S0 3.

### (g) Failure paths
1. Alphabetical head still selected by `sort -u | --limit 5` (crontab line 1022). `governed_research_producer.py:213` sorts by symbol.
2. Research objects are produced at 37× the consumption rate (2,850 vs 77). Storage grows (14 MB) with no expiry or advance.
3. DDQ remains open-ended: no terminal state, no answer join, and LIFO routing leaves a 3-day block of ASKED rows.
4. The quality escalator never converts partial to answered, so phase 2 of the Circle adds receipts but no answers.
5. Research Circle phase 1 has no schedule and no ledger, so it does not exist at runtime.
6. 118 `research_gaps` OPEN with no attempt. The monitor re-fires the same finding count and suppresses the alert.

### (h) Maturity per stage
| stage | 09-14 | now | evidence |
|---|---|---|---|
| 2A target build | L1 | **L1–L2** | non-securities gone; alphabetical head remains |
| 2A produce | L1 | **L2** | free fallback answers every refusal |
| 2A consume | L1 | L1 | 2.7% consumed |
| 2A question → next target | L0 | **L1** | question persisted (31), not consumed |
| 2B DDQ curate | L2–L3 | L2–L3 | unchanged |
| 2B route | L1 | L1 | 242 starved |
| 2B answer → close | L0 | L0 | 0/2,341 |
| 2B lane ranking | L4 narrow | L4 narrow | ext lanes active |
| 2C detect / enqueue | L1–L2 / L1 | L2 / L2 | subject_guid on 181/197 requests |
| 2C plan revisit | L0 | **L2** | 643 expiries/7d via defer-revisit timer |
| Research Circle ph.1 | L0 (dry run) | **L0** | no ledger |
| Circle ph.2 quality escalate | — | **L1** | 88 runs, 0 lifts |
| Free-search fallback | L0 | **L4** | 201/201 spilled; REFUSED_NOWHERE monitored = 0 |

### (i) Target / exit
| exit | 09-14 | now |
|---|---|---|
| ≥90% research spend on CONFIRMED securities | ~61% | ~100% of 7d objects on real tickers (ABOVE/AGAIN 0). Identity status not stamped on the object, so this is INFERRED from the symbols |
| no target starved > 24 h | not met | not met (NVDA…XLI below cut) |
| every question terminal within TTL | 0/872 | 0/2,341 |
| next_research_question diff visible between wakes | not observed | 31 persisted writebacks — partially met |

**Delta since 2026-09-14:**
- Free-search fallback was built and works (the 09-16 rescue now spills 100%).
- Non-security subjects were removed from research spend.
- Plan expiry now fires.
- The question text persists.
- Consumption collapsed in ratio, DDQ closure is still 0, and the Circle is not running.

---

## B3 · HERMES RESEARCH (3A CIO queue · 3B HRI fleet · heartbeat · provenance)

### (a) Purpose, actors, stores
**3A — CIO queue**
- `tradeai-hermes-cio-worker` (timer, last 20:30 ET; `--drain --max 2 --backend live`). Off-peak deferral is disabled for this unit by operator instruction 2026-09-26 (drop-in `offpeak-defer.conf`). MEASURED: systemctl cat.
- Stores:
  - request ledger: 37.8 MB, 9,883 lines.
  - results: 8.9 MB.
  - projection: 57 MB, 1,680 ids, guarded by `hermes_research_projection.lock`.
  - MEASURED: ls.
- New requesters: `options_thesis_lifecycle` 31/7d (69d91566a, 10-03: "Hermes research joins the options review"), `cio_plan_enrichment` 36, `cio_stance_review_request` 5. MEASURED.

**3B — HRI fleet**
- HRI totals: archived 32,822 · promoted 2,781 · rejected 2,480 · staged 229. MEASURED.

**Heartbeat**
- `tradeai-research-lane-health.timer` (15 min) → `research_lane_health.json`. 13 lanes, including `cio-hermes-queue`. MEASURED.

**Provenance**
- `GET /api/v3/cio/research-provenance` (producer `scripts.lib.cio_operator_evidence`). MEASURED.

### (b) State machines
- **3A request:** unchanged states. New events since 09-14 (MEASURED event counts):
  - `HERMES_RESEARCH_REPLAYED`: 68 (provider_error 54, timeout 13, truncated 1); 3 in 7d.
  - `HERMES_RESEARCH_RESTORED`: 12, all on 09-14.
  - `HERMES_RESEARCH_CANCELLED`: 1.
- **Latest status all-time:** completed 931 · failed 747 · queued 21 · cancelled 1.
- **Critique verdict (7d):** VALID 165 · PARTIAL 13 · **FAILED 2**. The critique can now reject; memory is refused on `critique_FAILED` (2).
- **Result classification (7d, 182):**
  - INSUFFICIENT_DATA 74 (41%) · CONFIRMS 56 · NO_NEW_INFO 35.
  - WEAKENS 7 · CONFLICTED 7 · STRENGTHENS 1.
  - None 2.
- **Provenance status:** USED_IN_JUDGMENT · RETRIEVED · REJECTED · UNKNOWN (status_rules in the payload).

### (c) Flow
```
 situation / enrichment / options review / desk S0 ══▶ enqueue (fingerprint; subject_guid 181/197)
   ══▶ ledger ══▶ projection (flock) ══▶ claim_next: reap → replay retryable → restore lost <48h
   ══▶ bridge :8766 (deadline, 4 slots, watchdog) → deepseek-flash (180/182); search via SearXNG (Brave hermes_cio_research = 0)
   ══▶ critique (VALID/PARTIAL/FAILED) ══▶ memory CANDIDATE (177) ══▶ plan merge
   ══▶ material_changed False 179/180 ✗✗▶ notify (0/180)          ══▶ operator pending join (B1) █
   ══▶ intelligence_lineages ADVISORY_USED ══▶ /research-provenance USED_IN_JUDGMENT 97/129 (decision_ids 0/129)
 20 orphans (08-31..09-12) in ledger only ✗ restore window 48 h ✗ heartbeat window 24 h → invisible
 HRI fleet ══▶ staged 229 (p50 ~100–108 h) ══ coordinator 77–169/day ══▶ promoted (expires NULL) ══▶ archived (librarian)
```

### (d) Iterations
| loop | closes? | evidence (MEASURED) |
|---|---|---|
| worker drain | yes | 182 completed/7d; request → complete p50 11.2 min, p90 18.0, max 55 |
| replay retryable | yes | 68 replays all-time |
| restore lost | only < 48 h | 12 restored 09-14; 20 older never |
| research → operator pending | yes | B1 |
| research → notify | **no** | 0/180 |
| result → thesis/plan change | **no** | 14 WEAKENS/CONFLICTED vs material_changed True 0. `material_changed` = plan fingerprint diff (`hermes_research_loop.py:677-678`), which a WEAKENS verdict does not move |
| staged → promoted | yes, recovered | audit/day 09-28..10-04: 84 · 107 · 145 · 169 · 158 · 83 · 77 |
| expiry → re-research | **no** | expires NULL 2,781/2,781 |
| heartbeat → alert | yes for 24 h window | `cio-hermes-queue` firing [] (18 attempts/24 h, 17 non-error) |

### (e) Questions
| question | fate |
|---|---|
| S-type plan questions (S3 104, S7 37, S6 24, S1 15, S5 14, S0 3) | 92% answered; 41% INSUFFICIENT_DATA |
| execution-language guard | 13 of 14 failures (`execution_language:do not establish` 11, `do not add` 2). These are hedging phrases in the model's text, so the guard has false positives (INFERRED from the matched text) |
| options review asks | 31 requests; joined to the options review (DOCUMENTED 69d91566a) |
| "was this research used?" | provenance: 97 used, 32 unknown, 0 rejected |

### (f) Live measurements (MEASURED)
| metric | 09-14 | 10-04 |
|---|---|---|
| 7d created / completed / failed / queued | 176 / 27 (15%) / 137 (78%) / 12 | **197 / 182 (92.4%) / 14 (7.1%) / 1** |
| by day completed/failed (ET) | — | 09-28 24/3 · 09-29 31/3 · 09-30 33/0 · 10-01 25/1 · 10-02 31/4 · 10-03 25/0 · 10-04 9/1 |
| bridge latency p50 / p90 | 15.2 s / 34.7 s | 21.0 s / 44.4 s |
| orphans queued, missing from projection | 26 | **20** (all `high`; 08-31 3, 09-01 1, 09-02 2, 09-03 5, 09-05 3, 09-07 1, 09-10 1, 09-11 1, 09-12 3) |
| BOOK-keyed requests | 11/27 results | 14/197, all S5 cash deployment (portfolio-level, legitimate) |
| notified | 0/553 | 0/180 |
| HRI 7d created | 1,166 | 1,053 (promoted 824, staged 229); subject_guid 778 (74%, was 51%); trigger_source/lane_used NULL 1,053/1,053 |
| HRI staged backlog | 359 | 229: stop_curation 127, youtube 40, momentum 38, protection 24 (p50 100–108 h) |
| external lanes 7d sent | chatgpt 960, grok 444 | chatgpt 655, grok 652, deepseek 485; deepseek skipped 410, error 14 |
| research-provenance | — | 129 artifacts: USED 97 (all via `intelligence_lineages:ADVISORY_USED`), UNKNOWN 32 (all security_research_spine), REJECTED 0; `decision_ids` populated 0/129; `web_evidence_provenance.jsonl` UNAVAILABLE (0 rows); sample rr_e9c1340d76e7 shows `source_as_of` 2026-05-11 on a 10-05 result |
| lane health | — | firing: lane-registry ORPHANED 1 / SILENT 21; drive-sync DEGRADED_STALE_SOURCE (105 notifies); cio-hermes-queue OK |

### (g) Failure paths
1. **Old orphans are permanently invisible.** The restore window is 48 h and the health window 24 h, so 20 jobs from 08-31 to 09-12 can never run or alarm.
2. **Thesis-challenging research changes nothing.** 14 WEAKENS/CONFLICTED results produced no material change and no notification, because the materiality test is a plan-fingerprint diff.
3. **Execution-language guard false positives** ("do not establish") are still the main failure class, and they block replay permanently.
4. **Provenance lacks decision ids** (0/129) and the web-evidence source is empty. "USED_IN_JUDGMENT" proves use by a lineage, not by a named decision.
5. **HRI has no per-row provenance and no expiry.**
6. **41% of answers are INSUFFICIENT_DATA**, the cost of SearXNG-only search for CIO research (Brave allocation to hermes_cio_research = 0).

### (h) Maturity per stage
| stage | 09-14 | now | evidence |
|---|---|---|---|
| plan/request | L1 | **L2** | subject_guid 92% of requests |
| enqueue | L1 | L2 | dedup, fail policy, lineage ids |
| claim | L1 (→L3 after fix) | **L3** | lock + replay + restore; old orphans excluded |
| search/synthesis | L2 | **L3** | 92% completion |
| critique | L3 partial | **L3** | FAILED verdict exists and blocks memory |
| memory accept | L1 | L2 | CANDIDATE 177, refused on FAILED |
| notify | L0 | L0 | 0/180 |
| join to operator | L0 | **L4** | B1 |
| provenance to decisions | — | **L2** | used/unknown receipts; no decision ids |
| HRI staged→promoted | L1–L2 | L2 | throughput recovered, audited |
| expiry/re-research | L0 | L0 | NULL everywhere |
| heartbeat | L0 | **L4** | 15-min lanes alert; 24 h blind spot |

### (i) Target / exit
| exit | 09-14 | now |
|---|---|---|
| 0 queued older than 2× cadence | 26 | **20** — not met |
| 7d completion ≥ 70% | 15% | **92.4%** — met |
| operator-forced completion joined in one pass | 0/1 | met (B1) |
| research_expires_at on 100% promoted | 0% | 0% — not met |
| ≥1 completion changes thesis/next question (M1) | 0/27 | 14 challenging verdicts, 0 material changes — not met |

**Delta since 2026-09-14:**
- The queue went from 78% failing to 7% failing.
- The heartbeat lane is live, the operator join works, and critique can say FAILED.
- A provenance endpoint exists.
- Still open: 20 old orphans, zero notification or thesis effect, HRI expiry, decision-level provenance.

---

## B4 · TOPIC / THEMATIC RESEARCH

### (a) Purpose, actors, stores
- **Purpose:** unchanged.
- **Actors and schedules:**
  - `topic_ingestion.py` (crontab lines 786–787, wrapped in `non_trading_hours_gate.sh`).
  - `topic_curator.py` (lines 324, 326; `$PROJ` is now CURRENT, logging to `persistent-state/logs`).
  - `agent_event_router.py` `*/30`.
  - `hermes_topic_monitor_bridge.py` 07:30.
  - `iterate_research_topics.py` 08:00.
  - `research_intelligence_queue.py` 16:45 / 02:40.
  - MEASURED: crontab.
- **Stores:** unchanged.

### (b) State machines (MEASURED)
- `topic_monitor`: enabled 396 / disabled 33. `last_searched` max **2026-09-27**.
- `agent_event_queue` TOPIC_INTELLIGENCE: last event **2026-09-27**; 0 in 7d.
- `watchlist_agent_jobs` `TOPIC:*` 09-16..09-27: failed 26, expired 4. Completed since 06-22: **0**.
- HRI topic_research: 7d 209 promoted, symbol NULL 209.
- `user_research_topics`: active 76, `last_researched_at` max **2026-10-02** (was 08-03, now revived).
- `ri_research_queue`: done 323, failed 95, running 1 (requested 08-01, started 08-10); last request 09-01.

### (c) Flow
```
 topic_monitor ─▶ T1 INGEST ✗ gate: ".venv/bin/python" missing in release dir → "skipping job", exit 0 (since 09-28)
 T2 CURATE (runs, "Rated: 0 | Agent events: 0"; 7 tracebacks SSL in persistent log) ─▶ feedback ✗ (newest 09-02)
 T3 ROUTER ─▶ T4 security worker (TOPIC: rejected; dormant because T1/T2 produce nothing)
 T5 Hermes topic bridge ─▶ HRI topic_research 209/7d, symbol NULL ─▶ RAG only
 user topics iterate ─▶ last_researched 10-02 ; RI queue zombie running since 08-10
```

### (d)–(f) Iterations, questions, measurements
| loop / question | closes? | MEASURED |
|---|---|---|
| ingest → curate | **no since 09-28** | topic_ingestion.log: 7 × "session check FAILED"; curator "Rated: 0" |
| curate → feedback | no | feedback newest 2026-09-02 |
| curate → agents (TOPIC events) | no (dormant) | 0 events 7d; 30 failed/expired jobs 09-16..27 |
| Hermes topic research | partial | 209 rows, 0 with symbol |
| user topics iterate | **yes (revived)** | last_researched_at 10-02 |
| RI queue drain | no | zombie row |
| research_insights | yes | 4,199 in 7d; newest 10-04 18:50 |

### (g)–(i) Failure paths, maturity, target
**Failure paths**
1. **Silent gate failure** has stopped all topic ingestion for 7 days. Exit 0 hides it, and no lane in `research_lane_health` fired for it. MEASURED: 13 lanes, none topic.
2. TOPIC slug → security worker (code unchanged: `topic_curator.py:504`, `agent_event_router.py:102`).
3. Hermes topic rows are subject-less.
4. The curator still hits SSL drops.
5. The RI queue zombie remains.

**Maturity**

| stage | 09-14 | now | evidence |
|---|---|---|---|
| T1 ingest | L1 | **L0** | dead 7 d |
| T2 curate | L2 | **L1** | runs empty |
| T3 route | L1 | L1 | — |
| T4 topic analysis | L0 | L0 | — |
| T5 Hermes topic | L1 | L1 | — |
| feedback | L0 | L0 | — |
| user topics | L0 | **L1** | revived |
| RI queue | L0 | L0 | — |

**Exit conditions**

| exit condition | status |
|---|---|
| 0 TOPIC rows/day | met only because ingestion is dead |
| feedback daily | 32 d stale |
| ≥50% topic HRI with GUIDs | 0% |
| curator without traceback | not met |

**Delta since 2026-09-14:**
- Regressed. Ingestion broke on 09-28, which masks the routing defect.
- The only improvement is that user topics are iterating again.

---

## 5 · Cross-lifecycle join map (now)
```
 OPERATOR Q ── pending_id ══ gap_request(research_id|subject_guid) ══ HERMES result ══ follow-up   █ (was ✗)
 OPERATOR TURN ══ wake.prior_operator_turn_ids (219/573)                                          █ (was ✗)
 HERMES result ══ intelligence_lineages ADVISORY_USED ══ /research-provenance ──✗── decision_id (0/129)
 HERMES WEAKENS/CONFLICTED ──✗── plan material change / notify (0)
 WAKE changed_question ══ critique writeback (31) ──✗── research_targets
 DDQ ── answer (text match) ──✗── answer_ids / close (0/2,341)
 REFUSAL ══ free_search → SearXNG (201/201)                                                        █ (was ✗)
 TOPIC ── ingestion dead ── router → security worker ✗
```

## 6 · Family maturity

The score is the mean of the per-stage levels in the (h) tables, with the four lifecycles weighted equally.

| lifecycle | 09-14 | 10-04 |
|---|---|---|
| B1 operator question | 1.2 | **2.4** |
| B2 system questions | 1.2 | **1.7** |
| B3 Hermes research | 1.0 | **2.3** |
| B4 topic research | 0.6 | **0.5** (gains in user topics offset by ingestion failure) |
| **Family B** | **≈1.0** | **≈1.7 / 5** |

The 09-14 score is reconstructed from the baseline stage tables. Neither baseline document published a numeric family score (DOCUMENTED: scoreboard §1.2 is qualitative).

## 7 · Top 5 risks
1. **Topic ingestion silently dead since 09-28.** `non_trading_hours_gate.sh` exits 0 on its own failure. The same gate wraps other research jobs (crontab lines 780–784, INFERRED affected), and no heartbeat lane covers it.
2. **Research does not change decisions.** 14 thesis-challenging Hermes verdicts in 7d produced 0 material changes and 0 notifications. Provenance shows "used" but with 0 decision ids. Research is consumed as decoration.
3. **Open-ended question stores grow without closure.**
   - DDQ: 2,341 rows, 0 closed, 242 starved.
   - research_gaps: 118 OPEN_NO_ATTEMPT, with the alert suppressed.
   - Research objects: 2.7% consumed.
   - HRI: no expiry.
4. **20 orphaned `high` Hermes jobs are outside every window** (48 h restore, 24 h health), so the heartbeat reports OK while they rot.
5. **Low and noisy operator signal.** Only 3 free-text asks in 7d; 94% of operator turns are button callbacks. Maria's prose is unrecorded (84/84) and desk replies are absent from `communication_events`. Answer quality cannot be audited end to end.

## 8 · Top 5 recommendations
1. Make the gate resolve its interpreter from `$PY`, or absolute to the dev venv, and make a failed session check exit non-zero. Add a `topic-ingestion` lane to `research_lane_health` (freshness of `topic_monitor.last_searched` < 36 h).
2. Feed result classification into materiality. WEAKENS/CONFLICTED/INVALIDATION should mark the plan material and route through `maybe_notify_plan`. Stamp `decision_ids` on provenance artifacts when a decision consumes a lineage.
3. Run a one-time, operator-approved reconcile of the 20 pre-09-14 orphans (supersede or restore). Extend `cio_hermes_queue_health` to scan all in-flight ids against the projection, not only the 24 h window.
4. Give every question store a terminal state and TTL:
   - DDQ: ANSWERED via answer join, plus EXPIRED.
   - research_gaps: attempt or abandon.
   - Research objects: CONSUMED/EXPIRED.
   - HRI promoted: `research_expires_at`.
   - Route oldest-first.
5. Replace `sort -u | --limit 5` with a rotating or priority cursor. Ledger desk replies as OUTBOUND `communication_events`. Filter callback turns out of `operator_conversation_turns` metrics, and record Maria's reply text, or its sha and excerpt, in `maria_desk_exchanges.jsonl`.

## 9 · Measurement commands (representative, read-only)
```
python3 jsonl readers (persistent-state/data/cio): hermes_research_requests (latest status, REQUESTED created_ts, WORKER_JOB ts/latency,
  LOOP_COMPLETED fields, REPLAYED/RESTORED), hermes_research_results (classification/symbol 7d), hermes_research_projection (by_research_id),
  cio_operator_pending_replies, cio_operator_gap_requests, cio_events (operator.message since 09-14), cio_plans (occurred_at, payload),
  gap_resolution_receipts (finished, vector, outcome), research_gaps, maria_desk_exchanges, wake_critique_question, intelligence_lineages,
  free_first_last_run; runtime/search_budget.json, research_lane_health(.json,_conditions), gap_resolution_last_run.json,
  operator_answer_quality_last_run.json; trade-ai-state/persistent_wake/{research_objects,research_targets,research_producer_health,
  state/wakes,state/receipts,state/agent_views}
SELECT (SET TRANSACTION READ ONLY): operator_conversation_turns (role, chat md5, callbacks vs free text, reply_to join latency, subject_guid),
  communication_events OUTBOUND 7d by producer, due_diligence_questions, hermes_research_intelligence, hermes_promotion_audit(promoted_at),
  hermes_external_research 7d, data_gap_registry, gap_resolution_outcomes, agent_event_queue TOPIC_INTELLIGENCE, watchlist_agent_jobs TOPIC:%,
  topic_monitor, topic_curation_feedback, user_research_topics, ri_research_queue, research_insights
crontab -l (lines 3-4, 324-326, 340, 786-787, 1016, 1020, 1022); systemctl --user list-timers / show / cat (hermes-cio-worker,
  research-lane-health, gap-resolution, cio-defer-revisit, operator-answer-quality, free-first-circulation); journalctl --user -u
  tradeai-cio-telegram / tradeai-operator-answer-quality / tradeai-gap-resolution; GET :7777/api/v3/cio/research-provenance
  (other guessed paths hermes/queue, research/queue, pending-replies, research-circle → 404 unknown_cio_path)
code: cio_hermes_research.py:1362-1418 · cio_hermes_queue_health.py:139-175 · hermes_research_loop.py:528-683 ·
  cio_operator_desk_loop.py:3189, 3301-3360, 5095 · research_circle.py:57-58 · governed_research_producer.py:213 ·
  non_trading_hours_gate.sh:15-25 · topic_curator.py:502-504 · agent_event_router.py:102
git log --since=2026-09-14 on family-B files: 55 commits (e.g. 0a4a82413 free search, 85e0758f6 joinable ids, 7f4495b12/aa817b3d7
  quality escalate, 5f6568f08 resolver cron, 398c3ab64 Hermes join + internal-first, 4f9c2fa88 lineage, 4817e984c NFLX follow-up,
  69d91566a options join, 072b4bfb6 persist operator outputs)
```
