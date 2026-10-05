# Lifecycle Fact Base D — Cognition (CIO, agents, memory) — re-measurement

Status: ACTIVE
as_of: 2026-10-04T21:20-04:00 (measurement window 20:41–21:20 ET; UTC 2026-10-05 00:41–01:20Z)
Measured at: 4f932b88a

```
Baseline:   docs/architecture/lifecycles/LIFECYCLE_FACTBASE_D_COGNITION_2026-09-14.md (+ As-Is §D1–D5, heat map X5)
Served:     CURRENT -> 4f932b88a-main-exact-phase2-20261004-202102; API :7777 _serving.pin_match=True, loaded_pin=4f932b88a
Method:     read-only. GET on :7777; psql SELECT inside SET TRANSACTION READ ONLY; jsonl readers; crontab -l;
            systemctl --user list-timers/cat; journalctl --user; git log --since=2026-09-14 (1,683 commits).
            No writes to repo/config/cron/services, no POST, no LLM/broker calls.
Stores:     wake state   ~/trade-ai-state/persistent_wake/state/
            CIO stores   ~/trade-ai-releases/persistent-state/data/cio/
            governance   ~/trade-ai-releases/persistent-state/data/{governance,runtime}/
Labels:     MEASURED (read in this window) · DOCUMENTED (commit/doc/config text, not re-observed) · DERIVED (arithmetic or
            reasoning over MEASURED rows)
```

## Headline — what changed since 2026-09-14 (evidence-ranked)

1. **The commitment → outcome edge now runs, and it settles nothing.** The sweep cron is installed: `20 18 * * *`, `sweep_commitment_outcomes.py --apply` (MEASURED crontab:1054). It writes `commitment_outcomes.jsonl`, which holds 883 rows.
   - All 883 are `INSUFFICIENT_EVIDENCE / claim_not_falsifiable`. The last sweep reported `due 883, scored 0, unfalsifiable 883, lessons_proposed 0` (MEASURED).
   - Since 09-25, the vacuous-falsifier rule (`refuse_vacuous_falsifier`, cortex_shadow_pipeline.py:119) stops boilerplate GovernedCommitments from being minted. That stopped GC minting almost entirely: 0 between 09-26 and 10-02, and 1 on 10-03, which carries a real price falsifier (MEASURED).
2. **The 09-14 #1 defect is still live: the ADBE operator turn 115 is still replayed every hour.**
   - In the last 24h, 25 of 75 wakes were ADBE and all 25 carry `prior_operator_turn_ids=['115']`. All-time, ADBE has 563 wakes and 532 of them carry turn 115 (MEASURED).
   - The branch label moved from `organic_from_operator_turn` to `organic_from_memory` (173/173 ADBE wakes in 7d), but the turn is the same one, asked on 09-11.
3. **L3 judgment is now diverse, and the critic disagrees.**
   - Over 7d: 113 views, with 95 distinct judgment_ids, 94 distinct summaries and 92 distinct falsifiers.
   - Critic verdicts were accept 93, abstain 11, **revise 9**. On 09-14 it was 11/11 accept.
   - 31 critique→question writebacks are recorded in `wake_critique_question.jsonl` (`applied: True`). The M2 counter (a critic `revise`) is met (MEASURED).
   - Stances remain INSUFFICIENT 93 / ABSTAIN 15 / NEUTRAL 4 / DISPUTE 1.
4. **Checkpoints now terminate.**
   - New checkpoints get `due_at` from `fallback_30d`; 201/201 of those created on 10-04 have one.
   - RESOLVED grew from 163 (09-14) to 477. Resolutions run 6–99 per day over 09-25→10-04 (MEASURED).
   - A legacy debt remains: 10,217 SCHEDULED checkpoints still have a null `due_at`.
5. **Agent runtimes dispatch work now (SHADOW).** In the last 24h: alex COMPLETED 399 / REFUSED_STALE 1,905; steph 762 / 176; morgan 45 / 239 (MEASURED journalctl). On 09-14, every sampled run showed `total 0`.
   - sentinel, iris: total 0. darwin, argus: REFUSED_STALE only.
   - maria, aegis, risk_agent: `state=DESIGNED enabled=False`.
6. **The CIO event bus chain is valid.** `CIOEventBus.verify_integrity()` returned `(True, 'event bus chain valid (13394 events)')` on a byte copy taken at 00:46Z (MEASURED).
   - 8,310 rows carry `rechain` metadata.
   - 30 events appended after the 00:22Z re-chain (13,364 → 13,394) also link correctly.
   - The pre-rechain archive and its sha256 exist at `trade-ai-releases/archive/cio_event_bus_fork_20261004/` (MEASURED).
7. **Decision lineage is mostly UNKNOWN.** Three decisions were probed against the 21-stage `CIODecisionLineage@v1`. The best-case one had 3 LIVE stages. **No probe exceeded 4 LIVE of 21**, and 12–16 stages were UNKNOWN in each (MEASURED).
8. **The ratified policy drives capital-plan sizing.** `max_single_name_pct=12.0`, with `policy_source.max_single_name_pct = "ratified"`.
   - The source event is `concentration_hierarchy {"max_single_position_pct": 12.0}`, OPERATOR_CONFIRMED, at 2026-10-04T11:35:28Z in `operator_profile.jsonl`. That file is 10 events and its hash chain links (MEASURED).
   - One field is still not ratified: `concentration_fire_pct=16.5` is sourced from `desk_thesis_fallback`.
9. **The memory influence stays at zero.**
   - All ring2 and influence surfaces are `SHADOW`. The 09-27 ENFORCED flip of `context:persistent-wake` was rolled back the same day (config/memory_influence_policy.json, DOCUMENTED).
   - The memory shadow promotion gate reads `NOT_PROMOTED`, and `memory_changed_decision 0.0` (MEASURED).
   - Retrieval attribution (PR #1412) is stamped on only **49 of 32,071 retrievals (0.15%)** since it shipped (MEASURED).

---

## D1 — Hourly persistent wake (WakeRecord@v2)

**(a) Purpose / actors / stores.** The purpose is unchanged: an advisory hourly wake over ≤3 subjects.
- Cron, MEASURED:
  - `:45` runs the research producer and target export (crontab:1022).
  - `:55` runs `wake_selection_feed.py`, still from the campaign tree `trade-ai-campaigns/m2-canary-20260907/ops/` (crontab:1019).
  - `:00` runs `run_persistent_wake.py`. Its environment includes `WAKE_L3_JUDGMENT=1` and `WAKE_L3_ALLOW_LIVE_PROVIDER=1` (crontab:1020).
- New inputs since 09-14 (DOCUMENTED commits; MEASURED provenance):
  - AEC four-spine memory: `aec_spines_loaded` on 503 of 519 7d wakes.
  - Selection source `instrument_record_due`.
  - Belief grounding: `organic_from_belief` 7.
- Stores (MEASURED): wakes.jsonl 1,728 · commitments.jsonl 2,591 · views.jsonl 242 · agent_views.jsonl 1,603 · l3_judgment_cache · receipts · commitment_outcomes.jsonl 883 · research_objects.jsonl 7,422.

**(b) State machine.** The baseline machine is unchanged; no new states were observed.
- Last 7d (n=573): SETTLED 556 · MEMORY_MALFORMED 17.
- Decision reasons: organic_from_memory 347 · organic_from_selection 197 · organic_from_belief 7 · organic_from_operator_turn 5 · null 17.
- Policy tokens:

| token | count (7d) |
|---|---|
| l3_judged | 140 |
| l3_view_persisted | 140 |
| l3_refused:offpeak_deferred | 175 |
| l3_skipped_ungrounded | 174 |
| l3_critique_question_writeback | 18 |
| l3_refused:schema_invalid | 7 |
| l3_refused:budget_cap | 4 |
| l3_refused:provider_outage | 2 |

**(c) Flow.** RO/instrument record → select → load (memory + AEC spines + belief) → decide → `_maybe_judge` → critic → view → cortex shadow (AgentView 72/day) → GC mint, gated by `refuse_vacuous_falsifier` → 18:20 sweep.
- New edge: critic `revise` writes `next_research_question` (wake_critique_question.jsonl, 31 rows; the latest, 10-04 23:01Z, is a Fonon question, `applied: True`).
- `parent_kind` is still null on 573/573 7d wakes. The next wake still does not read prior commitments.

**(d) Iterations.**
- Slot coverage: 499 slots from 09-14 05Z→10-05 00Z. Only 2 are missing (09-27 15Z, 16Z). The 09-14 baseline had 17 missing.
- 52 distinct subjects in 7d, but concentration is high: ADBE 173, 1a04783c 89, 063d8ce4 60.
- The ADBE wake is still built on turn 115 every slot.
- L3 judgments now differ between slots: 94 distinct summaries out of 113 views.

**(e) Questions.**
- Operator turns reaching wakes: turn 115 (ADBE) on 191 wakes in 7d. One wake set carries turns 132/127/125/116/12/5/4 (25 wakes), and 2 wakes carry turns 430–478.
- Critic-revised questions now persist (31).

**(f) Measurements.**

| measure | 09-14 | 10-04 | label |
|---|---|---|---|
| wakes/day | 24–72 | 72 (66 on 09-27) | MEASURED |
| missing slots | 17 | 2 since 09-14 | MEASURED |
| L3 judged / views 7d | 19 / 11 (3 distinct) | 140 / 113 (95 distinct) | MEASURED |
| critic revise | 0 | 9 (7d) | MEASURED |
| L3 cost 7d (views.cost_usd) | — | $0.168 | MEASURED |
| turn-115 replays | 40 | 532 all-time; 25/24h | MEASURED |
| retrieval filtered_wrong_subject per load | 892 | 1,666 (latest wake) | MEASURED |

**(g) Failure paths.**
1. The operator-turn replay (turn 115) is unresolved. The branch moved to the memory label; the turn id is unchanged.
2. Offpeak deferral still refuses L3 on 175 wakes in 7d.
3. `l3_skipped_ungrounded` 174: subjects without memory are still not judged.
4. The selection feed is still produced from a campaign directory outside the repo.
5. The next wake does not read prior commitments or views (`parent_kind` null).

**(h) Maturity per stage.**

| stage | 09-14 | 10-04 | evidence |
|---|---|---|---|
| selection | L1 | L1 | 52 subjects, but turn-115 replay |
| wake open/close | L1 | L2 | 499/501 slots, 556/573 SETTLED |
| memory load | L2 (1 subject) | L2 | 356/573 with memory; AEC spines 503 |
| L3 judgment | L3 partial | L3 | 95 distinct judgments in 7d |
| critique | L3 partial | L3 | revise 9, abstain 11 |
| synthesis (views) | L1/L3p | L3 | 92 distinct falsifiers |
| commitment | L1 | L1 | GC falsifiable 1/884 |
| next-slot carry | L1 | L2 | critique question writeback; commitments still not read |

**(i) Target / exit.**
- M2 is met (revise + writeback).
- Still open:
  - M3: a turn ≠115 that changes a decision.
  - M5: a commitment settled CONFIRMED/REFUTED.
  - Receipting the selecting research object (RO) on the memory/turn branch, to end the ADBE replay.

**Delta since 2026-09-14:**
- L3 diversity and the critic revise edge are now live.
- The sweep is scheduled.
- The vacuous falsifier is refused at mint.
- Slot loss collapsed (17 → 2).
- The turn-115 replay persists, and has grown 13×.

---

## D2 — Commitment → checkpoint → outcome → lesson

**(a) Actors (MEASURED crontab/timers):**
- `sweep_commitment_outcomes.py --apply` at 18:20 daily.
- `write_instrument_beliefs.py --apply` at 18:50.
- `resolve_due_checkpoints.py --apply --apply-pending-data` hourly at :20, with `TRADEAI_PENDING_DATA_APPLY=1`. The env gate from 09-14 is now set.
- `build_lesson_candidates.py --apply` at 06:40.
- `tradeai-advisory-outcome-scorer` at 18:30.
- `lesson_promotions.jsonl` (LessonPromotion@v1, `policy:lesson_queue_p2`).
- Lane `due-checkpoints` is RETIRED; `commitment-outcome-sweep` and `instrument-belief-writer` are ACTIVE (config/lane_registry.json).

**(b) State machines.**
- Checkpoints, latest per id over 18,254 ids: SCHEDULED 15,902 · NOT_PRICE_RESOLVABLE 1,867 · RESOLVED 477 · OUTCOME_PENDING_DATA 8.
  - SCHEDULED with null due_at: 10,217.
  - plan_binding: bound 201 (was 0) · unbound 17,492.
  - entity_type: UNRESOLVED 16,068 · SECURITY 1,751 · GOAL 413.
  - SCHEDULED overdue: 0.
- New on checkpoints: an `expectation` field (DecisionExpectation@v1, `ExpectationPolicy@v1`) on 183/201 of 10-04's checkpoints. All 183 are `POLICY_DEFAULT`, not author-specified (MEASURED).
- GovernedCommitmentOutcome@v1: 883 rows, all INSUFFICIENT_EVIDENCE. 0 CONFIRMED/REFUTED.
- Lessons: 781 ids, all PROVISIONAL. Provenance: RESEARCH_DERIVED 438 · null 336 · OUTCOME_DERIVED 7.
  - All 7 OUTCOME_DERIVED lessons are SCHD TRIM, with samples 1→7 and moves −22% to −37%. These are consistent with the suspect SCHD price series flagged on 09-14 (DERIVED).
- Lesson promotion queue: 633 QUEUED → 633 ARCHIVED ("case_summary_context: no outcome attached"). **0 PROMOTED** (MEASURED).

**(c) Flow.** cio_run_worker / material_scan → checkpoint (+30d) → hourly resolver → observations → 06:40 lesson candidates → promotion queue (archive) → instrument beliefs (18:50).
- `write_instrument_beliefs` latest: `settled={advisory 134, checkpoint 20, governed_commitment 0}`, `written=8`, subjects HELD:SCHD / HELD:V / HELD:XLI (MEASURED log).

**(d) Iterations.** Resolutions per day, 09-25→10-04: 6, 37, 31, 46, 21, 18, 10, 8, 27, 99. The 09-14 baseline was 5 in 7d.
- In the last two hourly runs, the resolver found due 5 and due 10. All were `not_price_resolvable: no_security_subject`. PENDING 8 are `no_price_history_either_end` (MEASURED).

**(e) Questions.** Lessons are statements, not questions.
- Operator-evidence learning block (MEASURED):

| field | value |
|---|---|
| settled_count | 427 |
| settled_without_verdict_count | 407 |
| directional sample | 20, successful 15 (0.75) |
| maturity_state | `OBSERVATION_ONLY` |
| review_ready | 0 |
| producer_review_ready_unproven | 99 |

**(f) Measurements.**

| measure | 09-14 | 10-04 |
|---|---|---|
| RESOLVED checkpoints | 163 | 477 |
| resolve rate | 5/886 per 7d | 214 in 7d (09-28→10-04) |
| wake-commitment settlement | absent | 883 swept, 0 scored |
| lessons ratified/promoted | 0/414 | 0/781 |
| calibration groups | none | 1_session 2/7 · 5_sessions 7/7 · event-relative 6/6 |

**(g) Failure paths.**
1. 883 historical GCs are permanently unfalsifiable. Under the new rule, almost nothing new is minted.
2. 10,217 legacy null-due checkpoints remain.
3. Most new checkpoints are GOAL or UNRESOLVED entities. They resolve NOT_PRICE_RESOLVABLE (`no_security_subject`).
4. The promotion queue archives everything, so there is no promotion path in use.
5. The only OUTCOME_DERIVED lessons rest on a suspect price series.

**(h) Maturity:**

| stage | level | 09-14 |
|---|---|---|
| checkpoint register | L2 | L1 |
| resolve | L2 | L1 |
| observation | L1 | L1 |
| lesson generation | L1 | L1 |
| lesson promotion | L0 | L0 |
| GC settlement | L1 | L0; runs, scores 0 |
| calibration | L1 | none; n=20, observation-only |

**(i) Target / exit.**
- First CONFIRMED/REFUTED GovernedCommitmentOutcome on a judged-wake falsifier.
- An OUTCOME_DERIVED lesson on clean prices reaching SUPPORTED (≥5 samples).
- First PROMOTED LessonPromotion.

**Delta since 2026-09-14:**
- The sweep is scheduled.
- The pending-data gate is open.
- Checkpoints get a due date and an expectation.
- bound checkpoints 0 → 201.
- The resolve rate is up about 40×.
- Settlement verdicts and promotions are both still 0.

---

## D3 — Reflection and agent runtimes (Sentinel, Darwin, Iris, alex/steph/morgan…)

**(a) Actors (MEASURED timers):**
- `tradeai-agent-runtime@{alex,steph,morgan,iris,sentinel,maria,aegis,vega}` every ~5 min.
- `@darwin`, `@argus`, `@risk_agent`: hourly or half-hourly.
- `@reflection`: daily. `@tax_agent`: weekdays.
- `tradeai-agent-runtime-producer` (~2 min), `tradeai-cio-nightly-reflection` (21:50), `tradeai-advisory-shadow-session` (Mon–Fri 09:15), `tradeai-advisory-lessons-reflect` (19:40).
- Unit: `AGENT_RUNTIME_OPERATOR_AUTH=1`, `LLM_GLOBAL_DAILY_USD_CAP` loaded from the drop-in (=2.00), "PREPARE-ONLY".

**(b) State machines.** Dispatch outcomes, last 24h (MEASURED journalctl):

| agent | runs | total | COMPLETED | REFUSED_STALE | state |
|---|---|---|---|---|---|
| alex | 288 | 2,304 | 399 | 1,905 | SHADOW enabled |
| steph | 288 | 938 | 762 | 176 | SHADOW |
| morgan | 288 | 284 | 45 | 239 | SHADOW |
| darwin | 24 | 192 | 0 | 192 | SHADOW |
| argus | 48 | 384 | 0 | 384 | SHADOW |
| sentinel, iris | 288 each | 0 | 0 | 0 | SHADOW, idle |
| maria, aegis, risk_agent | — | — | — | — | DESIGNED, enabled=False |

- config/agent_registry.json lists maria/aegis/risk_agent as `ACTIVE` while their runtime reports `DESIGNED`. This is a registry/runtime disagreement (MEASURED).

**(c) Flow.** The producer leases the trigger queue → runner → AgentRunTrace.
- `/api/v3/agents/runtime-proof`: alex `decisions_contributed 1053`, last natural wake material_scan at 01:10Z. cio `last_memory_retrieval RECORDED 42`.
- `/api/v3/agents/calibration`: only alex is MEASURED (20 scored, hit 0.75, brier None).

**(d) Iterations.** Nightly reflection (the last 8 nights ending 10-03):
- cases_seen 3,035 → 3,338; scored 2,701 → 3,032.
- `proposals` = 1 every night (the same `unresolved_contradiction`); `auto_promotions 0`.
- 3,032/3,338 joined cases are EXPIRED, and darwin scores 60 on 3,030. PR #1423 ("Darwin scores only market outcomes", 10-03) is not yet reflected in the 10-03 21:50 row (MEASURED; the next run is 21:50 tonight).
- Sentinel: 191 rows, last 30 all PASS. They review the same three agents, guardian/ledger/steph. The store was last written 10-02 09:22 (weekday-only timer).
- Darwin scorecards: 274 rows, the same three agents, overall 0.81–1.0.

**(e) Questions.** Reflection still raises one standing question. Sentinel and Darwin raise none.

**(f) Measurements.** Runtime COMPLETED/24h = 1,206 (was 0). The REFUSED_STALE share is 2,896 of 4,102 (71%) (DERIVED).

**(g) Failure paths.**
1. The staleness refusal dominates alex, darwin and argus.
2. Reflection still scores horizon expiries.
3. No ratifier exists; promotions stay at 0.
4. The registry state (ACTIVE) disagrees with the runtime state (DESIGNED) for 3 agents.
5. Sentinel's coverage is still 3 fixed agents.

**(h) Maturity:**

| stage | level | 09-14 |
|---|---|---|
| runtime dispatch | L2 | L0 |
| reflection run | L1 | L1 |
| reflection effect | L0 | L0 |
| Sentinel | L1 | L1 |
| Darwin | L1 | L1 |
| agent calibration | L1 | none |
| ratify | L0, by design | L0 |

**(i) Exit.**
- REFUSED_STALE below 20% for alex.
- Sentinel covering more than 3 agents.
- A reflection proposal with an operator receipt.
- Darwin scoring market outcomes only, visible in the nightly row.

**Delta since 2026-09-14:**
- The runtime moved from 0 to 1,206 COMPLETED per day, for 3 agents.
- An agent calibration surface exists.
- Reflection is unchanged.

---

## D4 — CIO run lifecycle (reactive cycle · wake jobs · situations · defer · event bus)

**(a) Actors (MEASURED):**
- `tradeai-cio-reactive.timer` (~2 min).
- `cio_wake_dispatch_entrypoint.py` `*/5`, with WAKE_L3 env (crontab:907).
- `tradeai-cio-material-scan`, `tradeai-cio-defer-revisit` (hourly :27).
- The cio_event_detector crons.
- Stores: cio_runs.jsonl (51.6 MB), cio_wake_jobs.jsonl (30.9 MB), cio_events.jsonl (13,394 events).
- DB `cio_decisions`: 90,367 rows. The writer is still not identified: the cron at crontab:170 has been disabled since 08-08, yet a ~3,710-row batch lands on alternating days (09-25 3,711 · 09-26 72 · 09-27 3,713 · 09-28 21 · … · 10-04 3,717). All 18,684 rows in the last 7d have status `proposed`. RESEARCH_MORE 14,071 · ADD_ON_PULLBACK 3,000 · HUMAN_REVIEW 1,309 (MEASURED).

**(b) State machines.**
- CIO runs by UTC day:

| day (UTC) | created | completed |
|---|---|---|
| 09-28 | 1,001 | 1,001 |
| 09-29 | 598 | 597 |
| 09-30 | 48 | 48 |
| 10-01 | 20 | 20 |
| 10-02 | 41 | 41 |
| 10-03 | 47 | 46 (1 FAILED) |
| 10-04 | 121 | 121 |

- BLOCKED: 0 in 7d (09-14 baseline: 579 all-time).
- Non-terminal runs: 143 all-time, the oldest from 09-06. 53 of them were created since 09-27 (MEASURED).
- Wake-job streams first seen in 7d (8,019): CANCELLED 5,414 (all `BACKLOG_SUPERSEDED:trigger=SCHEDULE_DUE`) · COMPLETED 2,059 · EXPIRED 338 (`EVENT_BUS` 331) · ENQUEUED 204 · DISPATCHED 3 · IN_FLIGHT 1.
  - EXPIRED is 4.2% of the 8,019 streams, against 1,446 EXPIRED vs 396 COMPLETED on 09-14 (DERIVED).
  - 193 ENQUEUED streams are older than 4h, the oldest from 09-30T01:01Z. Four 09-30 streams were being dispatched at 01:00Z on 10-05, about 4.5 days after enqueue (MEASURED).
- Situations: 241 `situation.raised` in 7d (S3_REENTRY 201) over 40 distinct (type, symbol) pairs. `semantic_event_key` is empty on 241/241 and `acknowledged` on 0/241, both unchanged since 09-14 (MEASURED).
- Defer lineage: newest write is still 2026-08-18 (MEASURED mtime).

**(c) Flow.** The bus carries memory.delta 4,528 · thesis.changed 334 · situation.raised 241 · plan.enriched 241 · watch.new_signal 49 · operator.message 3 (7d). Flow: reactive → wake jobs → record consult → run → checkpoint (D2) → notification (digest-only when nothing is new: "no advisory action; check-in not sent", dispatcher log 21:00 ET).
- The latest record consult shows `decisions_changed_by_record 8/8`, all `skipped_cadence_not_due`.
- The latest research persist shows `dispatched 5, research_called 2, persisted 0`. Over the last 20 hits, `persisted` was 1–2 (10-04/10-05).

**(d) Iterations.**
- `wake_turn_effects` `turn_changed_decision=true` on 3 rows on 10-03. All 3 replay the 08-30 SCHD defer turn (`plan_schd_s6`). No new operator turn has changed a decision (MEASURED).

**(e) Event-bus integrity.** Verified above (Headline 6): the chain is valid, and post-rechain appends link. The archive is retained (MEASURED).

**(f) Measurements.**

| measure | 09-14 | 10-04 |
|---|---|---|
| run completion 7d | 474 of ≥592 | ≈99.9% (1 FAILED) |
| run BLOCKED 7d | 525+ | 0 |
| wake-job EXPIRED share | 80% | 4.2% (CANCELLED-as-superseded 67.5%) |
| oldest stuck DISPATCHED/IN_FLIGHT | 8 days | 0 stuck >2× cadence; ENQUEUED backlog to 09-30 |
| situations ack/semantic key | 0 / 0 | 0 / 0 |
| bus chain | (fork undetected) | valid, 13,394 |

**(g) Failure paths.**
1. The 5,414 superseded cancellations hide schedule-due over-enqueue.
2. An ENQUEUED backlog is up to 5 days old.
3. Situations are still un-acked and un-keyed.
4. The `cio_decisions` writer is unknown, all rows are `proposed`, and none is ever terminal.
5. Defer is dormant.
6. 143 non-terminal runs are never reaped.

**(h) Maturity:**

| stage | level | 09-14 |
|---|---|---|
| reactive intake | L2 | L1 |
| wake-job dispatch | L2 | L1 |
| synthesis | L2 | L1 |
| event bus integrity | L2 | — |
| decisions | L1 | L1 |
| situation detector | L1 | L1 |
| defer | L1 | L1 |
| record consult | L2 | L2 |

**(i) Exit.**
- ENQUEUED >24h = 0.
- `semantic_event_key` populated.
- A `cio_decisions` writer identified, with a terminal status.
- The non-terminal run reaper.

**Delta since 2026-09-14:**
- Expiry fell from 80% to 4%.
- BLOCKED runs fell to 0.
- The bus fork was repaired and verifies.
- The dispatcher hang was fixed (bc277b695, DOCUMENTED).
- Situations and decisions are unchanged.

---

## D5 — Epoch lifecycle (promote → wakes → acceptance)

**(a)–(c).** The rail is unchanged. Wakes stamp `source_sha` and `provenance.epoch_id`. The maturity-remeasure lane exists (cron Mon 06:40, MEASURED crontab). The M2 campaign collector is still not scheduled (no cron line found).

**(d) Iterations, 09-14 05Z → 10-05 00Z (MEASURED wake stamps).**
- 155 epochs over 499 slots; mean 3.22 slots per epoch (09-14: 2.4).
- 50 epochs reached ≥3 contiguous slots, 21 reached ≥8, and the longest ran 20 slots.
- The last 7d still show 1–2-slot epochs, around merge trains (e.g. a9e8d0be8 1, c0f764f99 1, 956cb4e5f 1). Long runs did occur: a2e49ad55 18, e0507a147 15, f73d8c6bb 13.

**(e) Questions.** None. Acceptance is still not computed by a scheduled job.

**(f) Measurements.**
- 2 missed slots in 21 days.
- Release directories retained: 8 dated after 09-14 (10-02 1, 10-03 2, 10-04 5). Retention prunes older ones, so this is not a count of promotes (MEASURED).

**(g) Failure paths.**
1. Promote bursts on merge days still reset contiguity.
2. There is no scheduled acceptance receipt.

**(h) Maturity:**

| stage | level | 09-14 |
|---|---|---|
| promote/stamp | L2 | L1 |
| contiguity | L2 | L1 |
| acceptance | L0 | L0 |
| freeze discipline | L0 | L0 |

**(i) Exit.** A scheduled collector that writes a clause receipt per SHA.

**Delta since 2026-09-14:** Power-cut slot loss is gone. Longer epochs are now common. Acceptance is still unbuilt.

---

## D6 (new) — Decision lineage and operator evidence

**(a) Purpose.**
- `GET /api/v3/cio/decision/<id>/lineage` (CIODecisionLineage@v1, api_v3_cio.py:1753) joins one decision across cio_decisions, the capital-plan decision store, workflow lineage, intelligence lineages, checkpoints, dispositions and production cases.
- `GET /api/v3/cio/operator-evidence` (CIOOperatorEvidence@v1) has four blocks: research, institutional_cognition, learning and capability_coverage.
- Built by PRs #1387–#1402 and #1419 (DOCUMENTED git log).

**(b) Stage states, 21 stages (MEASURED, 3 probes).**

| decision | source | LIVE | PARTIAL | UNKNOWN | UNWIRED | other |
|---|---|---|---|---|---|---|
| dec_a8a706d112e9b468 (SCHD, capital plan) | CIOCapitalPlanDecision | 4 (identity, office_truth, canon_frameworks, judgment) | 0 | 16 | 1 | — |
| cio-aeo-20261004123627 (cio_decisions) | DB | 3 (identity, judgment, confidence) | 0 | 16 | 2 | — |
| 434cfc7b-… (GOAL checkpoint, 00:42Z) | workflow 6 + checkpoint 1 | 3 (wake_event, notification, checkpoint) | 1 (judgment) | 12 | 2 | NOT_RUN 2, PENDING 1 (outcome) |

- Internal inconsistency: on the capital-plan decision, `canon_frameworks` is LIVE, yet `unwired_stages` still says no producer writes framework_refs. That text is stale relative to PR #1402 (MEASURED).
- `specialist_disagreement` is UNWIRED on every probe.
- `/lineage` latency: 0.6–1.3 s.

**(c) Operator evidence (MEASURED, composition 00:41Z, cache 6 s):**
- research: used_in_judgment 96, unknown 32, retrieved 0, rejected 0.
- institutional cognition: available 401, retrieved 178, used 50, changed **0**, contradictory 2. memory_behavior_influence 0.
- capability coverage, 23 rows: LIVE 6 · PARTIAL 13 · DARK 2 (specialist disagreement, hypothesis) · UNKNOWN 2 (canon retrieval, historical analogue). Freshness: FRESH 15 · STALE 3 · UNKNOWN 5.
- lineage completion log (`cio_lineage_completion_report.py`, every 4h): complete_to_checkpoint 17,799 (87.0%). First open stage: research 18,991 · cio 1,462.

**(d)–(e).** No iteration. The projection is read-time only.

**(f)–(g) Failure paths.**
1. 12–16 of 21 stages are UNKNOWN on every probe, so "why" cannot be answered for a typical decision.
2. The capital-plan and DB decision families do not join to workflow/checkpoint rows (`matched_sources` all 0).
3. Stale unwired text.

**(h) Maturity:**

| stage | level |
|---|---|
| projection/API | L2 |
| per-decision completeness | L1 (≤4/21 LIVE) |
| operator evidence | L2 |

**(i) Exit.** ≥12/21 LIVE on a natural decision, and the capital-plan decisions joined to checkpoints.

**Delta since 2026-09-14:** Entirely new: the endpoint, the 21-stage contract and the operator-evidence surface.

---

## D7 (new) — Capital-plan policy (ratification → sizing → served decision)

**(a) Actors.**
- `operator_profile.jsonl`: an event-sourced, hash-chained profile (10 events, chain linked, MEASURED).
- `GET /api/v2/cio/capital-plan` (`capital_plan_1.3.0`).
- `cio_capital_plan_decisions.jsonl` (CIOCapitalPlanDecision@v1, 21 rows).
- Built by PRs #1403 and #1415/#1418 (9a1981849 "ratified investment policy drives capital-plan sizing; 12% cap", DOCUMENTED).

**(b) Ratification events (MEASURED).**

| when (UTC) | field | value |
|---|---|---|
| 10-01 | time_horizon | "less than 3 years" |
| 10-01 | cash_target_range_pct | 2–15 |
| 10-01 | minimum_liquidity_reserve_usd | 75,000 |
| 10-01 | equity_range_pct | 40–70 |
| 10-04 11:35 | concentration_hierarchy | max_single_position_pct 12.0 |
| 10-04 11:35 | fixed_income_range_pct | 0–20 |
| 10-04 11:35 | alternatives_range_pct | 0–15 |
| 10-04 11:35 | investable_cash_definition | v2 |

All events are OPERATOR_CONFIRMED.

**(c) Served plan (MEASURED 00:41Z):**
- sizing_policy: `max_single_name_pct 12.0 (ratified)`, `cash_band 2–15 (ratified)`, `reserve_floor_usd 75,000 (ratified)`, `concentration_fire_pct 16.5 (desk_thesis_fallback)`.
- A thesis-proposed `cash_band_min_pct 20` is `PROPOSED_NOT_APPLIED`.
- Plan figures: portfolio $1,264,247 · cash $877,376 (ABOVE_BAND) · net_recommended_deploy $524,228 · post-plan cash 27.93%.
- 21 position decisions. `decision_field_parity ok`.
- `financial_truth_gate ok=false` (CONFLICTED): 13 symbols are act-now suppressed, 31 exceptions.

**(d) Iterations.** The decision store was last written 2026-10-03 14:54Z. The 21 served ids match the stored 21, so ids are stable across today's ratification. The store did not re-record after the 10-04 policy change (MEASURED mtime).

**(g) Failure paths.**
1. The financial-truth gate is CONFLICTED on 13 symbols, which suppresses act-now.
2. The concentration fire threshold is still unratified.
3. Capital-plan decisions have no checkpoint or outcome join (D6).

**(h) Maturity:**

| stage | level |
|---|---|
| ratification store | L3 (chained, operator-confirmed) |
| policy → sizing | L2 |
| decision persistence | L2 |
| outcome feedback | L0 |

**Delta since 2026-09-14:** Entirely new.

---

## Cross-cutting

**Cognition transformation waves (COGX W1–W5).**
- Merged 09-27→09-28: #1305–#1328 (DOCUMENTED).
- Lane registry (MEASURED) lists as ACTIVE: gir-projector, edge-fanout-consumer, sec-filings-feed, supervisor-breach-detector, platform-conformance-audit, alert-quality, options-memory-projector.
- Registry drift, `NEVER_SCHEDULED` while actually installed:
  - contradiction-adjudicator: its timer is installed and last ran at 19:30 ET today, `mode apply, selected 20, NOT_A_CONTRADICTION 15, UNRESOLVED 5`.
  - maturity-remeasure: its cron line `40 6 * * 1` exists.
- Lane registry lists counterfactual-ledger as `NEVER_SCHEDULED`.
- Flips, all SHADOW or not flipped (MEASURED config/memory_influence_policy.json and unit/env grep):
  - ring2 surfaces 5/5 SHADOW; influence surfaces SHADOW.
  - `TRADEAI_AGENT_REGISTRY_ROUTING`, `TRADEAI_MODEL_CHOOSER` (receipts file last 10-03), `TRADEAI_CONFORMANCE_GATE=block`, `--ladder`, `--heal`, `TRADEAI_EMBEDDINGS`: none set in any user unit or env file.
- Independent maturity re-measurement: one row, 2026-09-28 12:18Z, overall **2.89/5**. Domains: memory 3, cross_silo 3, knowledge_graph 4, agents 2, workers 3. The next scheduled run is Mon 10-05 06:40 (MEASURED governance/maturity_scores.jsonl).

**Memory.**
- aif_memory_retrievals: 218,401 rows. Since PR #1412 (10-03 21:30Z), attribution is stamped on 49/32,071 (cio 39, hermes-cio-worker-1 10). `runtime-proof` reports alex `last_memory_retrieval NOT_RECORDED (unattributed_in_window 1125)` (MEASURED).
- Memory shadow measure (10-04 10:23Z): retrieval_rate 1.0 · memory_changed_decision 0.0 · contexts opened 4,421 · promotion gate `NOT_PROMOTED` (operator_rejection_recall not measured; behavior_influence not enabled).

**LLM routing and cost (MEASURED DB llm_consumption_log, ET days).**
- Spend per day 09-27→10-04: $0.46, 0.91, 1.28, 0.88, 0.76, 0.73, 0.53, 0.41. Every day is under `LLM_GLOBAL_DAILY_USD_CAP=2.00` (drop-in env, operator 09-14).
- 7d by lane: fast $3.10 (3,921 calls) · deepseek-flash $2.50 (1,832) · grok and chatgpt $0 (2,476 / 763 OAuth).
- CIO-attributed top spends: Hermes research job $0.99 · plan enrichment $0.64 · watchlist synth $0.43+$0.35 · contradiction adjudicator $0.025 (140 calls) · L3 critic $0 (122).
- `TRADEAI_TIER2_DAILY_USD_CAP` is now read by `tiered_validation.py:91–148`, which closes the 09-17 "read by no code" finding at code level (DOCUMENTED).
- The model chooser and registry routing are not enforced.

---

## Feedback-edge ledger (vs 09-14)

| edge | 09-14 | 10-04 | evidence |
|---|---|---|---|
| receipt → selection | yes (RO) / no (turn) | same | turn 115 on 25/25 ADBE wakes in 24h |
| critic → question | no | **yes** | 9 revise; 31 writebacks |
| wake/view → memory | no | partial | views cite 17 mem ids; influence 0 |
| commitment → outcome | unscheduled | **runs, 0 scored** | 883 INSUFFICIENT |
| checkpoint → outcome | 5/7d | **214/7d** | resolved/day |
| outcome → lesson | marginal | marginal | 7 OUTCOME_DERIVED, all SCHD |
| lesson → promotion | none | queue, 0 promoted | 633 archived |
| reflection → promotion | no | no | 1 proposal nightly |
| runtime dispatch | 0 | **1,206 COMPLETED/24h** | journalctl |
| record → wake skip | yes | yes | 8/8 |
| research persist → record | no | trickle | 1–2 per hit |
| memory → decision | 0 | 0 | changed_decision 0.0 |

---

## Family maturity score

Scale 0–5, DERIVED as the mean of the generic-stage levels per lifecycle (As-Is X5 method).

| lifecycle | 09-14 | 10-04 |
|---|---|---|
| D1 | ~1.3 | ~1.9 |
| D2 | ~0.6 | ~1.1 |
| D3 | ~0.7 | ~1.1 |
| D4 | ~1.2 | ~1.7 |
| D5 | ~0.5 | ~1.0 |
| D6 (new) | — | ~1.7 |
| D7 (new) | — | ~1.8 |

**Family D: about 0.9/5 on 09-14 → about 1.5/5 on 10-04 (DERIVED).**
- The independent lane score (different rubric) is 2.89 on 09-28 (MEASURED). No lifecycle in this family has a closed outcome→behaviour loop.
- Memory influence = 0, promotions = 0, and settled CONFIRMED/REFUTED = 0, so no lifecycle reaches L4.

## Top 5 risks

1. **The learning loop closes on nothing.** 883 swept commitments: 0 scored, 0 promoted lessons, and 7 outcome lessons all built on a suspect SCHD price series. The dashboards' "settled 427 / success 0.75 on n=20" figure can be mistaken for proven skill.
2. **The operator-turn replay has run unchecked for 23 days.** One 09-11 ADBE turn drives about a third of all wakes (25/75 in 24h), consuming slots and L3 budget on one subject.
3. **Lineage is mostly unknowable.** ≤4/21 stages are LIVE per decision, and the capital-plan and DB decision families have no checkpoint join. The operator cannot audit "why" for a typical decision.
4. **Control-plane drift.**
   - Registry says ACTIVE vs runtime DESIGNED for 3 agents.
   - The lane registry says NEVER_SCHEDULED for 2 installed lanes.
   - The `cio_decisions` writer is unidentified (90k rows, all `proposed`).
   - The stale `unwired_stages` text.
5. **Wake-job over-enqueue and backlog.** 5,414 superseded cancellations plus 193 ENQUEUED streams older than 4h (since 09-30). Situations are still un-keyed and un-acked, so the bus amplifies re-raises.

## Top 5 recommendations

1. Receipt the selecting research object (RO) on the memory and turn branches of `default_decide`, and age out operator turns after they are answered or N days old. Exit counter: ADBE ≤1 wake per 24h unless a new turn or RO exists.
2. Mint GovernedCommitments only from judged views whose author falsifier passes `refuse_vacuous_falsifier`, and route them to the 18:20 sweep. Exit counter: the first CONFIRMED or REFUTED GovernedCommitmentOutcome. Quarantine the SCHD-derived lessons until prices are verified.
3. Join capital-plan and `cio_decisions` ids to checkpoints at mint time, and wire the `research_*` and `falsifier` lineage stages. Exit: ≥12/21 LIVE on a natural decision. Fix the stale `unwired_stages` text.
4. Reconcile the registries: agent_registry vs runtime state, and lane_registry for contradiction-adjudicator and maturity-remeasure. Identify the `cio_decisions` batch writer and give its rows a terminal status.
5. Populate `semantic_event_key` and ack on situations, and dedupe SCHEDULE_DUE enqueue at the source. Exit: ENQUEUED >24h = 0, and re-raises ≤1/day per key.

## Commands (representative)

```
curl -s :7777/api/v3/cio/decision/{dec_a8a706d112e9b468,cio-aeo-20261004123627,434cfc7b-075e-46ee-9080-7d813bc129c9}/lineage
curl -s :7777/api/v3/cio/operator-evidence · /api/v2/cio/capital-plan · /api/v3/agents/{runtime-proof,calibration}
python3 readers over wake state {wakes,views,commitments,commitment_outcomes,agent_views}.jsonl and data/cio
  {operator_profile,cio_capital_plan_decisions,outcome_checkpoints,lesson_candidates,lesson_promotions,cio_reflection_candidates,
   sentinel_reviews,darwin_scorecards,cio_runs,cio_wake_jobs,wake_turn_effects,wake_research_persist,wake_critique_question,
   aif_memory_retrievals,retrieval_receipts,memory_shadow_measure_latest}
CIOEventBus(bus_path=<byte copy of cio_events.jsonl>).verify_integrity(); repair_cio_event_bus_fork.first_break()
psql READ ONLY: cio_decisions by day/status/action; llm_consumption_log by day/lane/process
journalctl --user -u tradeai-agent-runtime@<agent> --since -24h | grep "dispatch summary"
crontab -l; systemctl --user list-timers --all; config/{lane_registry,agent_registry,memory_influence_policy}.json
```
