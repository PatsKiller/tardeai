# Trade AI memory and whole-system live audit

Status: ACTIVE
as_of: 2026-09-28
Authority: READ_ONLY_ADVISORY
Auditor: Brock Build
Evidence class: read-only production observation plus static traces. No fix, deploy, flag change, schema change, job fire, Telegram send, broker order, or 2FA ceremony was performed.

```
report_id: TRADEAI-MEM-SYS-AUDIT-20260928
served_sha: 25afedb355108e11aa664c495081939aaaeb33b4
served_ui: 3.14+mulrnppm
built_at: 2026-09-28T21:35:33.090Z
promote_at: 2026-09-28T21:35:55.392100+00:00
observation_window_utc: 2026-09-28T21:35:55Z .. 2026-09-29T01:41:00Z
observation_window_et: 2026-09-28 17:35:55 .. 21:41:00 EDT
last_successful_build_meta: 2026-09-29T01:34:09Z
origin_main_at_report: f306b5e6dadce417ba68ae33eba009982ecab23c
release_git_head_at_report: f306b5e6dadce417ba68ae33eba009982ecab23c
process_pin: 25afedb355108e11aa664c495081939aaaeb33b4
clock: America/New_York EDT (UTC-4), NTP synchronized
```

This document is a measurement of the served pin. It is not a maturity certificate and it does not authorize a release.

---

## 1. Executive verdict

Nothing in the observed window is an autonomous trader. The system wakes on clocks and on an internal event bus. Those wakes read memory with behavior influence forced off. They do not place orders, and on this pin they did not write a new CIO decision.

At the close of the window the HTTP server stopped answering. `GET /v3/build-meta.json` timed out at 8s (01:38Z) and at 25s (about 01:40Z) with 0 bytes. The unit stayed `active` on PID 435701 (started 20:18:58 ET, `NRestarts` still 3). The process was in `futex_do_wait` with about 66 `CLOSE-WAIT` and 26 `ESTAB` sockets on port 7777 and about 51 KB sitting unread. The last successful build-meta read in this audit is 2026-09-29T01:34:09Z and was still `25afedb35`. This audit did not restart the service. See F-27.

What wakes by itself, on this pin, after 17:35 ET:

- The CIO wake dispatcher, every 5 minutes. 39 completes in the window, 0 error lines found. Each of the last five dispatched 5 runs and persisted 0.
- The persistent wake, on the hour. Four hourly slots, each `outcome=ok`.
- The reactive cycle timer, about every 2 minutes. 111 cycles. It enqueued wakes (peak 6). It did not claim them (`dispatched=0` on the sampled cycles). The earlier description of this unit as inactive described the oneshot between fires, not a disabled timer.
- Sentinel, Iris, and Darwin bounded runners, in SHADOW / prepare-only. Sentinel and Iris leased 0 items on every fire sampled after 21:00 ET. Darwin at 21:01 ET leased 8 and refused all 8 as stale. Completed work was 0.
- The commitment-outcome sweep at 18:20 ET and the instrument-belief writer at 18:50 ET. Both applied. The sweep scored 0 of 692 due rows. The belief writer wrote 1 belief and set `memory_behavior_influence` to 0.
- The gate-measurement bridge at :35. Three writes landed in the `25afedb35` tree.

What is scheduled and did not produce new useful work on this pin:

- Nightly reflection. Last natural fire was 2026-09-27 21:50 ET (3,038 cases seen, 2,701 scored, 1 proposal, 0 auto-promotions, `mutates_production` false). Next timer: 2026-09-28 21:50 ET, after this window.
- Options monitor. Last log line 2026-09-28 16:06 ET, before this promote, and the script changes directory into the dev tree. Next weekday slot: 2026-09-29 12:00 ET.
- Trade AI orchestrator. No run after this promote. The 17:30 ET label started on an older release and was still writing after the symlink moved. Next: 2026-09-29 09:00 ET.
- `portfolio.material_change` on the event bus. Last event 2026-08-09. Natural proof of material-change-to-wake is pending.

What is dark or split:

- Production database `trade_ai` has no `agentic_runtime` schema. The migration SQL is in the release and was not applied there. That production absence is design, not a failed job.
- The same tables do exist on database `trade_ai_agentic_lab` (role `agentic_runtime_reader`): `kb_lessons` 487, `kb_cases` 20, `kb_chunks` 487, `agent_runs` 3789, `agent_artifacts` 10919, `agent_tool_calls` 0, `agent_reviews` 167, `agent_scores` 267. Last writes are 2026-07-27 through 2026-08-03. Every `agent_runs` row is environment `SHADOW`. There are 0 LIVE rows and 0 updates after this promote. That store is OBSERVED_HISTORICAL.
- `memory_r10_m2` has 6 tables and 0 rows. `intelligence.retrieval_receipt` has 0 rows. `intelligence.heartbeat` has about 992 rows and an empty `release_sha`. The newest beat is 2026-09-28 21:20 ET, inside this window, and still cannot be pinned to a SHA.
- Agent views and wake receipts in Postgres `trade_ai` last moved on 2026-09-07.
- The operator notification outbox has had no append since 2026-09-28 14:28 UTC, while wakes continued.
- Two proposal-list GETs in the first pass returned 0 bytes at 40s and at 90s. A later GET in the same window returned HTTP 200, about 264 KB, 7 cards, `live_eligible` 0, every card BLOCKED. The handler can answer, and it can also sit silent long enough that a client shows nothing.
- Buy-ready packets for AXTI, DXCM, NYT, PEW, SWK, TDG, and TSLA are `PACKET_UNVERIFIED` because `packet_view` is not defined on this pin (`ImportError`). Stored `OPTIONS_ALT_OK` claims are withheld. That is containment.
- PR #1339 is the tip of `origin/main`. It is also the git HEAD of the release directory, which was fast-forwarded at 20:26 ET while portfolio-server PID 435701 (started 20:18:58 ET) kept running. Hash-object of the memory and agent-runtime files, and of the earnings-gate modules, still matches `25afedb35`. The process is the older pin. `git rev-parse` in that directory is not.

Options, stated separately:

- Research: the holdings funnel is readable. It is a holdings backfill. The proposal list, when it returns, shows 7 blocked cards and 0 qualified. Buy-ready alternatives are withheld. Usable as a blocked-research view. Not a qualified-idea view.
- Operator decision: every returned card has `approvable` false, `cio_approved` false, and `readiness.live_submit` false. The funnel summary says `cc_eligible` 3 while `cc_by_status.CC_ELIGIBLE` is 1. Header TODAY is −2412.59 and the securities book is −2380.91 on the same date. Decision surfaces disagree with each other.
- Execution: not proven, and not attempted. Status reads report `armed_for_execution: true` because a database flag set on 2026-06-22 is still true and the served policy file has `ENABLED = True`. The module docstring still says the default is off. The live-trading gate is `PAPER_ONLY` with `all_gates_passed` false, `autonomous_live_submit_allowed` false, and `per_order_2fa_required` true. Per-order 2FA was not invoked. A supervised live one-lot is NOT_MEASURED.

The canonical 12-gate board, recomputed read-only at 2026-09-29T01:19:08Z by the served script against the live ledger, is 1 PASS / 3 FAIL / 8 NOT_YET_MEASURED. That reconfirms the later claim. It does not reconfirm an older 0/12 or an older hardcoded 8/12. The denominator is the whole ledger, not actions born on this pin.

Memory did not change an action. `MEMORY_BEHAVIOR_INFLUENCE=0` is set on the portfolio server. The belief writer, the retrieval log, and the lesson candidates all record 0. A retrieval with `behavior_mode=OFF` is a receipt, not influence.

---

## 2. Scope, access, pin timeline, method

### 2.1 What was read first

- `AGENTS.md` Policy-Version 1.3.0, Status ACTIVE, Effective-Date 2026-09-27. Section 15 is the maturity bar. Section 0 keeps `MBI_BEHAVIOR = 0`.
- `docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md` is the controlling architecture and is a target, not a deployment receipt. v2.0, v3.0, v3.1, and v3.2 each carry `Status: SUPERSEDED BY` v3.3.
- `docs/architecture/V3_3_IMPLEMENTATION_STATUS_2026-09-27.md` (as_of 2026-09-27) is an annex. Several of its sentences are now stale and are marked as conflicts below.
- Active Trader / Moomoo: `docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_2.md` is an implementation prompt. The litmus review it describes is a read-only second architect. This audit did not find a served Moomoo order path and did not exercise one. `trade-ai-lab-moomoo-opend.service` is running a local OpenD build started 2026-09-13. That process is not evidence of live Moomoo orders.
- The Trade AI skill file on disk still says the project root is `/home/john/` and `psql -U john`. Both are false on this host. It was not used as evidence.

### 2.2 Access

| Surface | Result |
|---|---|
| HTTP `127.0.0.1:7777` GET | Used. MagicDNS was not required. |
| Postgres `trade_ai` as the application user | Read-only session. Role `johnclaw` has no login; the application user does. |
| Postgres `trade_ai_agentic_lab` as `agentic_runtime_reader` | Read-only. Exact counts. This is a second database. |
| User crontab, user systemd, journals | Read. |
| Broker order endpoints, 2FA initiate, Telegram send, option-chain and preflight | Not called. |
| Production runners | Not invoked. A manual run is not a natural fire, and none was authorized. |
| Browser viewport | NOT_MEASURED. No browser was driven. API census is section 6. Layout claims are absent on purpose. |

The options execution-status GET calls `options_pilot_arm.status()`, and that function issues `CREATE TABLE IF NOT EXISTS system_controls` before the read. The existing row's `updated_at` is 2026-06-22 16:25 ET, so this audit did not change the flag. The side effect is disclosed because the handler is not a pure read.

### 2.3 Pin timeline

Do not blend these. The observation window is only the last row.

| ET 2026-09-28 | UTC | SHA | What it is |
|---|---|---|---|
| 10:55 | 14:55 | `e2dcfce1a` | PR #1337. The UI the operator pasted earlier in the day. |
| 12:03 | 16:03 | `914dcb5ab` | PR #1342. |
| 12:34 | 16:34 | `8d5edc621` | PR #1345 book-map day P&L. Ancestor of the served pin. Not the served pin. |
| 12:52 | 16:52 | `d3bfc9ca0` | PR #1347. Previous release recorded on the promote receipt. |
| 13:49 | 17:49 | `490735fba` | PR #1348 re-entry entry alerts. |
| 17:07 commit, 17:34 promote | 21:07 / 21:35 | `25afedb355108e11aa664c495081939aaaeb33b4` | PR #1349. **Served.** Release dir `25afedb35-main-exact-phase2-20260928-173440`. UI `3.14+mulrnppm`. |
| 20:26 commit, not promoted | 00:26Z Sep 29 | `f306b5e6d` | PR #1339 merge. `origin/main`. **Not the process.** |

`8d5edc621` is an ancestor of the served SHA. `f306b5e6d` is not an ancestor of the served SHA. The packet fail-closed commit `f7be59c72` (stored verdicts are not trusted; `PACKET_UNVERIFIED` / `STALE_PRE_FIX`) is an ancestor of the served SHA. The rest of the #1339 earnings-gate package is only on `origin/main` and in the release directory's git HEAD.

Pin integrity, re-read at 2026-09-29T01:34:09Z:

- `GET /v3/build-meta.json` `git_sha` is still `25afedb355108e11aa664c495081939aaaeb33b4`. UI `3.14+mulrnppm`. `built_at` `2026-09-28T21:35:33.090Z`.
- `CURRENT` still points at `25afedb35-main-exact-phase2-20260928-173440`.
- `portfolio-server` MainPID 435701, `ActiveEnterTimestamp` Mon 2026-09-28 20:18:58 EDT, cwd that release. The process started after the 17:34 ET promote and was not restarted when git moved.
- The release worktree's git HEAD is detached `f306b5e6d`, and `git status` is dirty against that HEAD (deleted and modified paths that belong to the older checkout). The fast-forward was 2026-09-28 20:26:24 EDT, after the process start and after the 18:20 and 18:50 ET crons. At 18:20 and 18:50 the worktree HEAD was still `25afedb35`.
- Hash-object of 58 memory and agent-runtime files on disk matches blob `25afedb35` (0 mismatches). On-disk `scripts/lib/buy_ready_options_alternatives.py` and `scripts/options_desk_enterprise.py` match the pin blobs, not the #1339 blobs. `packet_view` is not defined in the served alternatives module. mtimes of those files are before the process start.
- Do not call this release directory a clean detached checkout of `25afedb35`. Do not treat `f306b5e6d` behavior as served behavior. Evidence in this report is split by what the process and the on-disk blobs are, which is `25afedb35`.

Bound units at the start of the window, from `check_worker_pins.py` against this CURRENT: `portfolio-server`, `tradeai-cio-telegram`, `tradeai-health-agent`, and `cio-governed-bridge` are SERVED on `25afedb35`. `tradeai-aec-command-center-cycle` and the reactive **service** were inactive at that instant. The reactive **timer** is enabled. See section 5.

`MEMORY_BEHAVIOR_INFLUENCE=0` and `GOVERNED_MEMORY_ADVISORY_INFLUENCE=SHADOW` are in the portfolio-server environment.

### 2.4 Method

Verdicts mean what the work order says. A unit in `active` or an HTTP 200 is not a later stage. `written_beliefs >= 0`, a cron installation, and a dashboard constant are not passes.

Proof labels used: STATIC (code or schema text), HERMETIC (not run fresh in this audit except where an existing test name is cited as code), NATURAL_PRODUCTION (a log or row whose timestamp is inside the window and whose producer is a schedule, not this auditor), OBSERVED_HISTORICAL (a real row on an earlier pin or before 21:35:55Z).

The 12-gate script was run as `cio_gate_measurement_bridge.py --json --root CURRENT`. The write flags were not passed. Output: `/tmp/audit-gates-25afedb35.json` on the host, not in git.

### 2.5 Conflicts between documents and the served system

| Document claim | Served observation |
|---|---|
| v3.3 maturity table, about 4.3/10, dated 2026-07-22 | A target narrative. Not recomputed as a decimal. Section 3 uses categories. |
| v3.3 MVL schema is required | SQL file is in the release. Schema `agentic_runtime` is absent from production `trade_ai`. The same tables exist on `trade_ai_agentic_lab`, last written July–August 2026, all runs `SHADOW`, 0 LIVE rows. |
| v3.3 `/v3/scalp` | Annex says the built route is `/v3/active-trader`. Not re-browsed. |
| Annex: most crons still start in the dev tree | 441/469 active jobs `cd` to CURRENT. 0 crontab lines `cd` to the rebuild tree. 48 user timers still have WorkingDirectory on the rebuild tree. Both are true and the annex sentence is too broad. |
| Annex: beliefs are written; outcome validation is not closed | Belief writer did apply at 18:50 ET. Sweep scored 0. Consistent. |
| Skill file: 63 crons, Windows paths, `psql -U john` | False. 469 active jobs. Linux. Application DB role is not `john`. |
| `options_execution_policy.py` docstring: default OFF | Served source line is `ENABLED = True`. |
| Health critical "release manifest FAIL" | The markdown it reads was generated 2026-09-27T00:09:17Z. Its dirty-file section says live-adjacent dirty: none. The critical is a stale document still being displayed. |
| Earlier boards: 0/12, then 8/12, then 1 PASS / 3 FAIL / 8 NOT_MEASURED | The script's own header says 8/12 was hardcoded literals. This run is 1/3/8. See section 3. |
| #1339 "live proof" merged | Merged to `origin/main` at 20:26 ET. The release directory's git HEAD was moved to that commit under a still-running process whose blobs remain `25afedb35`. |

---

## 3. Maturity boards

### 3.1 Rubric

A dimension is not a percentage.

| Category | Meaning |
|---|---|
| OBSERVED_SERVED | Both ends and a natural handoff on `25afedb35`, with a trace and times. |
| OBSERVED_HISTORICAL | Valid on an earlier pin or before 21:35:55Z. Not promoted. |
| WIRED_UNPROVEN | Code, timer, or schema exists. No relevant natural consumption in the window. |
| PARTIAL | At least one step observed. The missing edge is named. |
| DESIGN_ONLY | Documented. Not deployed. |
| FAIL | Contradictory, unsafe, dead, or broken on a measured sample. |
| NOT_MEASURED | No sample, no access, or no natural opportunity. Not a pass. |

Confidence is high when this audit ran the query or read the journal, medium when a log lacks a SHA, low when the only support is an older document.

### 3.2 M1–M5 (AGENTS.md §15, the canonical definitions)

§15 says maturity is not a percentage. A package is complete only when the proof is observed at runtime from the served release.

| Proof | Definition (canonical) | This pin | Historical | Verdict |
|---|---|---|---|---|
| M1 Research | The system raised a research request itself, it completed, and it changed a named field on a named record. Show the diff. | `cio_decisions` created after 21:35:55Z: **0**. `wake_research_persist.json` after promote: 12 hits. Latest 2026-09-29T01:24:48Z, entrypoint `cron: */5 cio_wake_dispatch_entrypoint.py`, `research_called` 5, `persisted` 0, `field_changes` length 0, `cognition_noop` 5. | `WakeResearchPersist@v1` hit at 2026-09-25T00:03:26Z: unattended, `research_called` 5, `persisted` 5, `field_changes` exactly `next_eligible_at` and `cc_narrative`, 5 subjects. No `source_sha` on the hit. Same shape on the 09-20 through 09-24 00:02Z hits. | OBSERVED_HISTORICAL for 2026-09-25. On this pin research ran and changed 0 fields. |
| M2 Advice | A critique verdict changed `next_research_question` rather than being logged beside it. | Sentinel leased 0. `cio_instrument_records.jsonl` has 0 copies of critique id `crt_4107cafde6cfaf0e567b8c7b` and 0 `next_research_question` changes after promote. | `wake_critique_question.jsonl` one row, `CritiqueQuestionWriteback@v1`, `as_of` 2026-09-25T14:01:24Z, subject `HELD:NOC`, `critique_verdict` `accept`, `applied` true. `before` hash `9f4fe1d5f4c7` (len 257) differs from `after` hash `f7aba6fa63bb` (len 259). | OBSERVED_HISTORICAL. Not on this pin. |
| M3 Feedback | An operator reply landed on a record and changed the next wake. Show the decision with and without the turn. | No production chat was seeded. `agent_wake_receipts` max `created_at` is 2026-09-07. No `turn_changed_decision` true row after promote. Latest SCHD turn row 2026-09-28T16:41:51Z has `turn_changed_decision` false. | `wake_turn_effects.jsonl`: 1,052 rows with `turn_changed_decision` true, all `HELD:SCHD`, last true row 2026-09-24T22:10:24.685893Z, influence 0. With the turn, `note_source` `operator_turn` and the next-question hash differs from the without-turn question (`note_source` `none`). Both sides share `next_eligible_at` 2026-10-01T22:10:24Z. Question texts are system questions, not the operator message. | OBSERVED_HISTORICAL. The SCHD incident correction is not in a store the wake loads (section 4.6). |
| M4 Consistency | Every operator-facing number traces to one regenerable producer, and two surfaces do not state the same quantity differently without a labeled scope. | Book-map `total_day_change` **−2380.91** equals performance `1D.change` **−2380.91** (`source=market_day`, quality `reliable`, label `Σ accounts`). `GET /api/v2/overview` `today_change` **−2412.59** (`today_pct` −0.19). Header minus book = **−31.68**. `today_by_account` sums to the header. Funnel `cc_eligible` 3 versus `cc_by_status.CC_ELIGIBLE` 1. Position counts: overview 10, holdings rows 20, book rows 25. | On `e2dcfce1a` the same day, book and header disagreed by a similar cash-versus-mark gap. That pin is not this pin. The gap remeasured here is $31.68. | PARTIAL. Book and 1D match. Header and book do not. The header scope is all accounts; the book is securities-only. The $31.68 was not isolated to a named cash day-change line. |
| M5 Persistence | A scheduled wake loads the record before acting, and a disposition made days earlier is still honoured with nobody replaying it. | `wake_record_consult.jsonl`: about 39 rows after promote. Latest `as_of` 2026-09-29T01:25:07Z, unattended, `*/5` dispatcher, `record_found` 13, `decisions_changed_by_record` 8, `skipped_cadence_not_due` 8. The code defines `decisions_changed_by_record` as the count of `skip/cadence_not_due`, so those two numbers are one fact. Diff: `without_record=proceed`, `with_record=skip/cadence_not_due`. None of the eight subjects is SCHD. The age of the write that set `next_eligible_at` was not measured. Tonight's belief writer produced 0 `organic_from_belief` lines at or after 2026-09-28T22:50:00Z. | One `BELIEF_REVIEW` in `wakes.jsonl` / `commitments.jsonl`: `produced_at` 2026-09-27T17:00:02.108033Z, `source_sha` `33342ceaeda5b74b9e2d429dde236b3f79365c94`, `authority` `READ_ONLY_ADVISORY`, `effect_kind` `changed_question`, claim hash `f6bee1152d44` (length 83). No size, order, stop, or weight. Ledger token counts: `counterfactual` 0, `decision_diff` 0, `BELIEF_REVIEW` 0, `organic_from_belief` 0. | PARTIAL on this pin (cadence deferral). OBSERVED_HISTORICAL for a question change on an earlier SHA. Influence stays 0. A same-action shadow is not influence. |

### 3.3 Canonical 12-gate board

Source of the definitions: `scripts/cio_gate_measurement_bridge.py` on the served tree (P9 gate honesty, 2026-09-16). The agent id the script measures is `alex`. Thresholds are in the script, not in a second board. `passing` is false when the value is null. Status string for null is `NOT_YET_MEASURED`.

Computed 2026-09-29T01:19:08Z. Root: CURRENT. Ledger is the live overlay, all pins mixed inside the file. That is a property of the script. This audit did not filter it, because filtering would be a different board.

| Gate | Threshold | Value | Status | Evidence |
|---|---|---|---|---|
| min_artifact_population | ≥ 100 | 40022 | PASS | Advisory actions the gate script counted at 01:19:08Z. That run saw 40048 lines including 25 SUPERSEDED and genesis. A later `wc -l` at 01:27:54Z was 40222. Keep the board on 40022. Do not blend the later line count into this denominator. |
| retrieval_provenance_completeness | 100% | 0.0 | FAIL | 0/40022 have non-empty `evidence_refs` and a `source_snapshot_id`. 39666 have refs without a snapshot. 40018 have a domain label, which the script treats as routing, not provenance. |
| independent_review_coverage | 100% | 0.0 | FAIL | 0/40022. 179 review rows: 174 name other artifacts, 5 have no artifact id. |
| independent_score_coverage | 100% | 0.0019 | FAIL | 78/40022. Refused self-score 0. Refused scorer==reviewer 0. |
| contradiction_rate | ≤ 2% | null | NOT_YET_MEASURED | Review denominator is empty. |
| unsupported_claim_rate | 0 | null | NOT_YET_MEASURED | No claim-to-support ledger. Previously hardcoded 0. |
| stale_input_refusal_accuracy | 100% | null | NOT_YET_MEASURED | No refusal receipts. Previously hardcoded 1. |
| deadline_budget_adherence | 100% | null | NOT_YET_MEASURED | 27353 run-trace rows, 19994 carry the literal `UNMEASURED`. |
| duplicate_run_rate | 0 | null | NOT_YET_MEASURED | 25 caught SUPERSEDED merges. Uncaught duplicates are not stored. |
| operator_usefulness | ≥ 0.7 | null | NOT_YET_MEASURED | No operator-rating store. Darwin grade proxy is not the gate. |
| rollback_test_passed | true | null | NOT_YET_MEASURED | No rollback-and-replay receipt. Exit 0 is not evidence. |
| authority_violations | 0 | null | NOT_YET_MEASURED | No violations ledger. A deny-list existing is not an observation. |

Summary: **1 PASS, 3 FAIL, 8 NOT_YET_MEASURED. Not promotable.** Promotion authority in the script is `HUMAN_ONLY`. Automatic promotion is false.

How this sits against earlier claims:

- The script header says a previous board showed 8/12 with `gates_not_measured: 0` because seven gates were literals. That 8/12 is a known false green. It is not the current function.
- A 0/12 figure appears in older package notes from before the population gate had 100 real actions, and in catalog prose the script now refuses to store. It is not what this function returns today.
- The 1 / 3 / 8 split is what this function returns on the live ledger. Reconfirmed. The pass is population only.

Store sizes behind the board (same run): snapshots 65, Darwin scorecards 262, sentinel reviews 179, handoffs 3, Hermes challenges 939, notifications 6941.

### 3.4 v3.3 Minimum Viable Loop acceptance

Canonical text: architecture v3.3 §4.3. Absent tables are DESIGN_ONLY, not failed jobs.

| Criterion | Numerator / denominator | Verdict |
|---|---|---|
| 100 reviewed Watch artifacts | Independent reviews of Alex actions: 0/40022. Sentinel file last row 2026-09-28T13:21:33Z, before this pin. | FAIL against the bridge denominator. If "Watch artifacts" means a different population, that population was not defined in §4.3 and was not measured separately. |
| ≥ 20 known-bad regression fixtures | Tests in the tree mention a ≥20 lesson shadow. This audit did not re-run them. | NOT_MEASURED as a fresh hermetic run. STATIC: the tests exist. Not a production pass. |
| Retrieval on ≥ 95% of eligible Sentinel reviews | Provenance gate 0/40022. Retrieval log is a different store and does not join those reviews. | FAIL on the gate that exists. The 95% figure was not computed on a joined sample because the join is empty. |
| 0 deterministic failures released | No release-failure ledger for this criterion. The health critical is a stale manifest document (finding F-04). | NOT_MEASURED. |
| Sentinel false-positive rate measured | Contradiction gate is null because the review denominator is 0. | NOT_MEASURED. |
| Darwin scoring ≥ 95% of artifacts | 78/40022 = 0.19%. On this pin Darwin completed 0 and refused 8 stale at 21:01 ET. | FAIL. |
| Nightly reflection creates candidate lessons | 2026-09-27 21:50:13 ET: `cases_seen` 3038, `scored` 2701, `proposal_count` 1, `auto_promotions` 0, `mutates_production` false, stamp 2026-09-28T01:50:14Z. | OBSERVED_HISTORICAL. At 2026-09-29T01:34:09Z the timer's next fire was still 2026-09-28 21:50:00 EDT (15 min left). Journal since 21:00 ET: no entries. |
| Iris or operator can ratify or reject | Iris runtime leased 0 at 21:15–21:26 ET. `tradeai-advisory-lessons-reflect` ran 19:40:13–19:41:04 ET, exit 0, while HEAD was still `25afedb35`, and `advisory_kb_lessons.jsonl` did not append (mtime stayed 12:17:04 ET). `lesson_candidates.jsonl` 616 rows, schema `LessonCandidate@v2`. `lesson_promotions.jsonl` 633 rows, last 2026-09-28T12:18:50Z, schema `Procedure@v1`. `iris_auto_ratify_safe` promotes only sources `reflection_ips` / `reflection_thrash` / `reflection_feedback`. | Run OBSERVED_SERVED with zero new rows. A ratification that changes a later retrieval was not observed. |
| No production config mutation by the reflection | Last reflection JSON: `mutates_production` false, `auto_promotions` 0. | OBSERVED_HISTORICAL for that run. |
| No broker call by the reflection | Same JSON, and this audit made none. | OBSERVED_HISTORICAL for that run. Not a general proof. |

Schema deployment:

| Object | Where specified | What was measured |
|---|---|---|
| `agentic_runtime.kb_*` and `agent_*` on production `trade_ai` | `migrations/agentic_runtime/0001_mvl.up.sql` and `0002_roles.up.sql` are in the release. They were not applied to `trade_ai`. | Schema absent. DESIGN_ONLY on the production database. |
| Same tables on `trade_ai_agentic_lab` | Read DSN `AGENT_RUNTIME_READ_DSN`, role `agentic_runtime_reader`. | Exact: `kb_lessons` 487 (max `created_at` 2026-07-27 11:30:20-04, newest id prefix `a0e8bb9f7951`, lifecycle `CANDIDATE`); `kb_cases` 20 (max 2026-07-27 11:29:55-04); `kb_chunks` 487; `agent_runs` 3789 (max `updated_at` 2026-08-03 15:05:24-04, 0 updated after promote; SHADOW/`REVIEW_REQUIRED` 2841, SHADOW/`CREATED` 918, SHADOW/`COMPLETED` 28, SHADOW/`READY_TO_REASON` 2; **0 LIVE**); `agent_artifacts` 10919; `agent_tool_calls` 0; `agent_reviews` 167 (max 2026-07-31); `agent_scores` 267 (max 2026-07-31; self-score join 0). OBSERVED_HISTORICAL. |
| `memory_r10_m2` (6 tables) | Present on `trade_ai` | All counts 0. WIRED_UNPROVEN. |
| `intelligence.retrieval_receipt`, `memory_context`, `embedding`, `gir_*` | Present on `trade_ai` | 0 rows. File `retrieval_receipts.jsonl` is a different store (685 rows, all `mode=SHADOW`, step 7 `not_installed` on 685/685). |
| `intelligence.heartbeat` | Present on `trade_ai` | About 992 rows. `release_sha` empty on the grouped read. `memory_context_ok` null. Last beat 2026-09-28 21:20:19-04, which is inside this window. Pin attribution NOT_MEASURED because the SHA column is empty. |
| `intelligence.sla` | Present | 157 rows. Max `updated_at` 2026-09-28 08:18 ET, before this pin. |
| `content_embeddings` | Present | 1,283,885 rows. Model `nomic-embed-text`. Dimension 768. Column type jsonb, not a vector type. |
| `cio_decisions` | Present | 71,821 rows. Min 2026-07-01. Max 2026-09-28 16:52:08 ET, before this pin. |
| `agent_event_queue` | Present | 417 rows. 416 `done`, 1 `processing`. Max `created_at` 2026-09-27 13:33 ET. |
| `trade_lesson_memory` | Present | 254 rows. 244 inserted in the minute of 18:30 ET, which is inside the window. `close_date` from 2026-05-12 through 2026-09-23. **0 closed on 2026-09-28.** Exit reasons in that batch: stop_hit 122, broker_stop_hit_reconciled 94, target_hit 12, position_closed_in_alpaca 8, and smaller phantom/manual/instant buckets. This is a batch write of older closes, not 244 new outcomes. |
| `agent_commitments` | Present | 2,013. Max `created_at` 2026-09-07. |
| `agent_views` | Present | 25. Max 2026-09-07. |
| `agent_wake_receipts` | Present | 125. Max 2026-09-07. |
| `agent_learning_scores` | Present | 0. |

Public base tables: 690. No alembic or flyway version table was found.

Models and the deterministic core, on the served blobs: `inspect_ticket` states a model is not involved and the kernel cannot repair, release, submit, or mutate a ticket (`kernel_version` `sentinel-integrity-v1`). `sentinel_pipeline.py` passes `may_change_ticket: false`, `may_override_deterministic_failure: false`, `may_submit_or_authorize: false`. `reconcile_critics` keeps `deterministic_verdict` and does not flip `release_allowed` when a critic says `REJECT`. `persistence.record_score` raises if `producer_agent_id == scorer_agent_id`. The lab `agent_scores` self-score join is 0. The gate function's refused-self-score count on the file ledger is 0, which means no self-score was present to drop. Reflection `auto_promotions` is 0 and `mutates_production` is false on the 2026-09-27 run. `iris_auto_ratify_safe` does not edit the sentinel kernel. `ENABLED` and the pilot flag are operator/commit state. A complete bypass audit of every model tool is NOT_MEASURED. Verdict: the rails that were read are in the served code, and no self-score or auto-promotion was observed on this pin.

### 3.5 Dimension categories

These replace the v3.3 decimal table for this pin. Confidence is in the last column.

| Dimension | Category | Why | Confidence |
|---|---|---|---|
| Deterministic safety rails (MBI, no order from this audit) | PARTIAL | Influence is 0 and no order was sent. Execution policy is armed (F-01). | high |
| Scheduled wakes | OBSERVED_SERVED | Dispatcher, persistent wake, reactive enqueue, gate bridge. | high on logs; medium where the log has no SHA |
| Durable agent runtime (Sentinel, Darwin, Iris as processes that finish work) | FAIL | Timers fire. Leased work is 0 or refused-stale. Completed 0. | high |
| Institutional memory stores | PARTIAL | File stores and `content_embeddings` are live. Production `trade_ai` has no MVL schema. The lab KB is two months stale and has no LIVE runs. Influence stays 0. | high |
| Outcome to belief to next decision | PARTIAL | Sweep and belief writer fired on this pin. Scored outcomes 0. Next CIO decision 0. One historical `BELIEF_REVIEW` changed a question on SHA `33342cea…`. | high |
| Retrieval before reasoning | PARTIAL | Retrieval rows with status OK and behavior OFF. Step 7 `not_installed` on 685/685 receipts. Not joined to a new decision. | high |
| Corrective memory / ratification | WIRED_UNPROVEN | Candidates exist. Promotions queued. Iris reflect ran and appended 0 lessons. SCHD case row was not written. | high |
| Operator-surface honesty | PARTIAL | Book and 1D match. Header differs by $31.68. Health criticals include a stale manifest. Proposal list both hung and later returned 7 blocked cards. | high on the calls that returned |
| Options research | PARTIAL | Funnel returned. Proposal list returned 7 blocked cards on the later GET. Buy-ready alternatives withheld as `PACKET_UNVERIFIED`. | high |
| Options execution | NOT_MEASURED | Armed flags are true. No authorized order. 2FA not started. | high that it was not measured |

---

## 4. Memory map and lifecycle

### 4.1 Stores that exist

Owner is the producer named in code or the cron. Readers are what this audit could see consuming them. Encryption at rest was not inspected (disk is local; no envelope was proven). Retention is whatever the file rotation already did; this audit did not rotate anything.

| Store | Kind | Last movement | Reader evidence | Influence |
|---|---|---|---|---|
| `data/cio/` on CURRENT | Same inode as `persistent-state/data/cio` | Writing during the window | Dispatcher, gate bridge, belief writer | Files say 0 |
| `cio_action_ledger.jsonl` | File. Gate script 40048 lines / 40022 real at 01:19:08Z. `wc -l` 40222 at 01:27:54Z. Last `occurred_at` 2026-09-29T01:26:17Z, event `1457e34b0d75`, type `CIO_ACTION_CREATED`, authority `shadow_advisory_only` | Gate board | n/a |
| `aif_memory_retrievals.jsonl` | 42637 lines. Last 2026-09-29T01:02:20Z. Influence `"0"` on all 42637 | The row itself is the receipt | `behavior_mode=OFF` |
| `cio_wake_jobs.jsonl` | 14.9 MB | Completed 01:24:48Z | Dispatcher log | persist 0 |
| `sentinel_reviews.jsonl` | 39 KB, 179 rows | Last 13:21:33Z | Gate script: 0 join Alex actions | historical |
| `darwin_scorecards.jsonl` | 117 KB, 262 rows | Last 13:21:33Z | 78 join Alex actions | historical relative to this pin |
| `cio_plans.jsonl` | 63 MB | mtime during the window | Not joined to a new decision | advisory |
| `instrument_belief_latest.json` | `InstrumentBeliefWriter@v1` | 2026-09-28T22:50:01Z | Writer's own summary | 0, `financial_action` false |
| `cio_instrument_records.jsonl` | Belief store path named by the writer | Named, not dumped | Writer | 0 |
| `lesson_candidates.jsonl` | `LessonCandidate@v2` | Tail all PROVISIONAL | No Iris accept | 0 |
| `lesson_promotions.jsonl` | `Procedure@v1` | Tail all QUEUED, last ts 12:18Z | No accept | advisory |
| `cio_reflection_candidates.json` | Nightly summary | 2026-09-28T01:50:14Z | The service log | mutates false |
| `advisory_kb_lessons.jsonl` | 253 MB file | mtime 12:17 ET | Not the Postgres KB | not the MVL table |
| `content_embeddings` | Postgres jsonb | 1,283,885 × nomic-embed-text / 768 | No retrieval-receipt row in `intelligence.retrieval_receipt` | not joined |
| OpenClaw gateway | Process, started 2026-09-23 | Running | Session files were not copied into CIO memory | NOT_MEASURED as a cross-agent store |
| `agent_wake_receipts`, `agent_views` | Postgres | Frozen 2026-09-07 | No reader in the window | dark |

`advisory_kb_lessons.jsonl` is a file. It is not `agentic_runtime.kb_lessons`. The lab table of that name is a third store, last written 2026-07-27, lifecycle `CANDIDATE`. Treating any of the three as the others would be a false pass.

File census at 2026-09-29T01:27:54Z (`wc -l` and last record). Identifiers are prefixes.

| Store | Lines | Last record | Id |
|---|---:|---|---|
| `sentinel_reviews.jsonl` | 179 | 2026-09-28T13:21:33Z | artifact `b626e5ee081b`, reviewer `sentinel`, agent `steph`, status `PASS` |
| shadow sentinel | 132 | same stamp | same artifact prefix |
| `darwin_scorecards.jsonl` | 262 | 2026-09-28T13:21:33Z | scorer `darwin`; payload agent key present; not a self-score of `darwin` |
| shadow darwin | 132 | same stamp | — |
| `agent_run_traces.jsonl` | 27353 | ended_at 2026-09-29T01:25:25Z | trace `2d1481c704bc`, agent `alex`, status `completed` |
| `cio_wake_jobs.jsonl` | 16847 | 2026-09-29T01:25:31Z | event `00d76d583b68`, type `CIO_WAKE_IN_FLIGHT` |
| `aif_memory.jsonl` | 1405 | created_at 2026-09-29T01:01:34Z | memory `110f22bf478b` |
| `aif_memory_admissions.jsonl` | 1371 | admitted_at 2026-09-29T01:01:34Z | same memory prefix, type `CASE_SUMMARY`, accepted |
| `memory_contexts.jsonl` | 28436 | file mtime 2026-09-29T01:22Z | 4658 lines after promote; beliefs present on 34 lines total |
| `retrieval_receipts.jsonl` | 685 | — | all `mode=SHADOW`; step 7 `not_installed` on 685/685 |
| `memory_consumption_receipts.jsonl` | 1900 | consumed_at 2026-09-29T01:02:20Z | receipt `f5239cd142fc`, consumer `advisory_desk_operator`, purpose `operator_truth_join`, influence 0 |
| `instrument_belief_latest.json` | object | as_of 2026-09-28T22:50:01Z | `written_beliefs` 1, `noop` 9, influence 0. SCHD is not in the blob |
| `cio_instrument_records.jsonl` | 342 | SCHD beliefs as_of 2026-09-27T22:50:01Z | `HELD:SCHD`, 4 beliefs, max revision 3, proposal hash `41e64ff4c9cb`. No behavior-size keys |
| `lesson_promotions.jsonl` | 633 | 2026-09-28T12:18:50Z | 0 lines contain `decision_integrity`. 58 contain `SCHD` |
| `lesson_candidates.jsonl` | 616 | mtime 2026-09-28T10:40:01Z | lesson `e79c02de6470` |
| `cio_production_cases.jsonl` | 42333 | — | 0 lines `DecisionIntegrityCase`, `watch_contradiction`, `decision_integrity:`, or `HOUSE_WASH_HOLD` |
| `cio_reflection_candidates.jsonl` | 47 | 2026-09-28T01:50:14Z | `mutates_production` false, `auto_promotions` 0 |
| `advisory_kb_lessons.jsonl` | 3154 | 2026-09-28T16:17:04Z | id `2085bbb94f5c`. Embedding model `qwen3-embedding:8b`, length 4096. 0 lines `decision_integrity` or `HOUSE_WASH` |
| `advisory_kb_lesson_candidates.jsonl` | 17 | 2026-09-14T01:40:15Z | id `cd3a21ceda9e` |
| `advisory_kb_lesson_applications.jsonl` | 2890 | 2026-09-28T16:17:04Z | lesson `2085bbb94f5c` |

Wake state under `/home/johnclaw/trade-ai-state/persistent_wake/state`: `wakes.jsonl` 1299, `commitments.jsonl` 2175, `receipts.jsonl` 1770, `commitment_outcomes.jsonl` mtime 2026-09-28 18:20 EDT.

Embeddings are two populations. `public.content_embeddings` is `nomic-embed-text` / 768 / jsonb, 1283885 rows, max `created_at` 2026-09-28 20:47:29-04, 2621 of those after promote. Writer SHA for those 2621 is NOT_MEASURED: the release git HEAD had already moved at 20:26 ET, and `content_scoring.py` was outside the 58-file hash. Served policy `scripts/lib/ollama_embedding_policy.py` allows only `nomic-embed-text` digest prefix `0a109f422b47e3a3`, dimension 768. `TRADEAI_EMBEDDINGS` is unset on PID 435701, so the CIO ladder's `enabled()` is false. All 685 retrieval receipts record step 7 `not_installed`. `intelligence.embedding` has 0 rows. Hybrid merge exists in an offline comparison script (`compare_phase2f_global_shadow_retrieval.py --hybrid`), not in the wake ladder. CIO semantic retrieval: WIRED_UNPROVEN. Hybrid: DESIGN_ONLY. The advisory KB's newest row is still labelled `qwen3-embedding:8b` length 4096, written 2026-09-28T16:17:04Z while the worktree reflog names pin `914dcb5ab`. That vector is OBSERVED_HISTORICAL and is not what step 7 reads. Ollama also has `qwen3-embedding:8b` installed; the served policy rejects it.

### 4.2 Chain 1 — source to cited decision

Wanted: source observation, normalized fact, research packet, durable memory, indexed retrieval, agent context, cited decision, operator view.

What was actually in the window:

1. `memory.delta` events continued on `cio_events.jsonl` after the promote (the lane census counted 112). Last bus event in that census: `memory.delta` at 2026-09-29T01:01:21Z from `hermes-cio-worker`.
2. Durable memory `110f22bf478b` created 2026-09-29T01:01:34Z, admitted the same second as `CASE_SUMMARY` (accepted) in `aif_memory_admissions.jsonl`.
3. Consumption receipt `f5239cd142fc` at 2026-09-29T01:02:20Z. Consumer `advisory_desk_operator`. Purpose `operator_truth_join`. Influence 0. The paired retrieval row is status `OK`, query `advisory desk operator truth`, `memory_ids` length 4, `behavior_mode=OFF`. Symbol list length 119. Symbols not listed here.
4. Sink missing: `cio_decisions` after the promote is 0. Dispatcher `persisted=0`. The outbox has no append after 14:28Z.

Verdict: **PARTIAL**. Source, admission, and a consumption receipt exist. The cited-decision edge does not.

Two further traces:

- Trace B, a research packet that becomes a case and is quoted by a decision on this pin: **NOT_MEASURED**. No new CIO decision. `cio_production_cases.jsonl` has 42333 lines and 0 `DecisionIntegrityCase` rows.
- Trace C, an indexed embedding hit consumed by a named agent: **NOT_MEASURED**. `intelligence.embedding` and `intelligence.retrieval_receipt` are 0. Step 7 on every file receipt is `not_installed`. The jsonl retrieval names memory ids, not an embedding id.

### 4.3 Chain 2 — outcome to belief to later influence

| Step | Evidence | Verdict |
|---|---|---|
| Frozen advice | Ledger has 40,022 real actions accumulated across pins. Not filtered to this pin. | OBSERVED_HISTORICAL as a store. Not a this-pin sample. |
| Operator disposition | Not newly recorded in `agent_wake_receipts`. | NOT_MEASURED this window. |
| Real outcome | Sweep at 18:20 ET: `CommitmentOutcomeSweep@v1`, `applied=true`, `scanned=2166`, `due=692`, `scored=0`, `unfalsifiable=692`, `outcomes_appended=56`, `financial_action=false`. `trade_lesson_memory` inserted 244 rows of **older** closes (through 2026-09-23), including broker-reconciled stops and a small phantom bucket. Those are not 244 fills from tonight. | PARTIAL. A writer ran. Nothing due was scored. Closes are historical. |
| Attribution | `scored=0`. | FAIL for "scored the due set". The due set was labeled unfalsifiable, which is a recorded outcome of the sweep, not a silent skip. |
| Belief | 18:50 ET. `written_beliefs=1`, `would_write_beliefs=1`, `applied=true`, `refused=0`, `noop=9`. Settled rows: advisory 108, checkpoint 15, governed commitment 0, options paper 1. Skipped: checkpoint_no_direction 6922, commitment_not_settled 692, advisory_no_record 18, advisory_no_settled_bit 19. Subjects with records 53. Subjects written: 1, sha256 prefix `bf61a4cbb262` (symbol withheld). | OBSERVED_SERVED as a writer. `written_beliefs >= 0` is not a pass. The informative facts are 1 write, 6922 checkpoints with no direction, and influence 0. |
| Ratification | No new accepted lesson. | WIRED_UNPROVEN. |
| Later decision changed | CIO decisions after promote: 0. Retrieval behavior OFF. | NOT influence. A shadow with the same action in both modes would not count either. None was needed: the flag is 0. |

### 4.4 Chain 3 — agent run

Sentinel unit text: WorkingDirectory is CURRENT. A later `Environment=PYTHONPATH` points at `trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts`. Systemd applies the later assignment. The runner can import the dev tree while its working directory is the release. That split is STATIC from `systemctl cat` and was not confirmed by printing `sys.path` from the process. Verdict on "served code": **PARTIAL**.

Natural fires after 21:00 ET, all `Result=success`, all prepare-only SHADOW:

| Agent | Sample | Intake | Completed |
|---|---|---|---|
| sentinel | 21:05, 21:10, 21:16, 21:20, 21:26 ET | leased 0, acked 0 | 0 |
| iris | 21:15, 21:20, 21:26 ET | leased 0 | 0 |
| darwin | 21:01 ET | leased 8, acked 8, all `REFUSED_STALE` | 0 |

Checkpoint resume after a crash: **NOT_MEASURED**. No crash of these units in the sample. `resolve_due_checkpoints` did run (section 5) and resolved 12 of 15 due at 23:20Z; later hours resolved 0.

These are not "an agent" in the §15 sense when the dispatch total is 0. They are a timer and a prepare-only process. The persona names (Maria, Alex, and the rest) have matching `tradeai-agent-runtime@` units. The ones inspected between fires are inactive because they are oneshots. Inactive-between-fires is not a disabled timer.

### 4.5 Chain 4 — corrective memory

Contradictory or stale handling that is real:

- Darwin's 8 leased items were refused stale. That is a refusal, not a lesson.
- Lesson candidates in the file tail are PROVISIONAL and carry `cannot_become_policy` in the key set. Promotions are QUEUED.
- Embeddings are not one model. `content_embeddings` is nomic / 768. The newest advisory lesson vector is qwen3 / 4096, written on an earlier pin. CIO step 7 is off. Hybrid retrieval is an offline script. Counterevidence search is a field name on lesson candidates (`counterexample_search`); values were not dumped. Scope and time filters were not executed as a retrieval.
- Quarantine of a poisoned or secret-bearing source: **NOT_MEASURED**. No such injection was performed, and no natural quarantine row was selected.
- Rollback of an embedding migration: v3.3 §10.6 is listed in the annex as not built. DESIGN_ONLY.

### 4.6 Chain 5 — SCHD re-entry follow-through

The incident write-up is `docs/_findings/SCHD_DECISION_INTEGRITY_INCIDENT_2026-09-25.md`. This audit did not seed a chat and did not quote the operator's message. The recorder the document names (`scripts/record_decision_integrity_case.py --apply`) was not run.

`scripts/lib/intelligence_client.py` `default_loaders` reads facts, the instrument record and beliefs, thesis, contradictions, research objects, Hermes, and promoted lessons. It does not read the findings markdown or `cio_production_cases.jsonl`.

| Question | Result |
|---|---|
| Is the message itself in a durable store the next wake loads? | Not found. The markdown is not a wake input. `aif_memory.jsonl` has 0 lines with `HOUSE_WASH_HOLD`, `decision_integrity:`, `house 30-day`, or `HOUSE_RULE`. Thirty SCHD lines are August 2026 `RESEARCH_REFERENCE` plus one `OPERATOR_EXPLICIT_PREFERENCE` (`2d26758e9dc6`, created 2026-08-18, content length 99, no wash/house/30-day/integrity token, `case_ids` empty). |
| Is the corrected conclusion durable? | PARTIAL. The classifier is served code (`scripts/lib/decision_integrity.py`, including `HOUSE_WASH_HOLD`). The case row was not written (0 matching lines in `cio_production_cases.jsonl`). Promoted lessons and advisory KB lessons: 0 `decision_integrity` / `HOUSE_WASH` lines. |
| Does the CIO agent retrieve the house rule next time? | Not observed. Last SCHD `MemoryContext` is 2026-09-28T17:30:40Z, before promote: purpose `RESEARCH`, mode `SHADOW`, context `77d8275a5b80`, 4 beliefs, revision 3, `lessons_state` `NONE_PROMOTED`, `n_lessons` 0. SCHD contexts after promote: 0. SCHD `RetrievalReceipt` after promote: 0. Last SCHD receipt is the same 17:30:40Z stamp, `HIT_FRESH`, `SHADOW`, step 7 `not_installed`. `reused_decision_integrity` is 0 across all receipts. SCHD rows in `aif_memory_retrievals.jsonl` after promote: 4. Last 2026-09-29T01:02:20Z, status `OK`, influence `"0"`, memory ids starting `2d26758e9dc6` (the August preference). |
| Is a later answer better for a recorded reason? | Not observed. No post-promote SCHD retrieval receipt and no case id. |

The reentry desk can apply `decision_integrity` when a card is built. That is code on the request path. It is not a retrieval of a stored correction. No post-promote card receipt of that application was measured here. `HELD:SCHD` beliefs remain revision 3 as of 2026-09-27T22:50:01Z. Tonight's writer did not refresh SCHD.

### 4.7 Freshness

Decision freshness is not retention. The served policy module `evidence_freshness_policy.py` is the code authority for quote TTL. This audit did not re-measure every quote gate. The health agent reports `alpha_vantage` last success 181.3 hours ago (warning, window 192 hours). That is a stale source on the board, not a memory TTL.

---

## 5. Wakes, schedules, lanes

Census clock 2026-09-29T01:26Z. Full recount: host file `/tmp/audit-lanes-20260928.md` (not in git). This section keeps the denominators and the edges. Jobs were not fired.

### 5.1 Recount against the historical lead

| Lead | Recount | Difference |
|---|---:|---|
| 469 cron jobs | 469 active jobs | 0. The crontab file is 1065 lines: 536 comments, 53 blank, 7 environment assignments, 469 jobs. |
| 117 timers | 117 user timer unit files | 0 files. 93 enabled (what `list-timers` shows) and 24 disabled. System timer files are a separate 25. |
| 27 running services | 24 user services running | −3. Which three stopped was not reconstructed. System running services: 41, not part of the 27. |
| 50 dev-tree timers | 48 user timers whose effective WorkingDirectory is the rebuild tree (38 enabled, 10 disabled), plus system `tradeai-continuous.timer` | The old 50 counted a slightly different set. 44 other enabled user timers mention the rebuild tree only as the `.venv` interpreter while WorkingDirectory is CURRENT. Those are not dev-tree jobs. |
| 3 stale daemons | `chatgpt-oauth-proxy`, `grok-oauth-proxy`, `heartbeat-receiver`, all started 2026-09-12 on the rebuild tree | The three match. A fourth stale root is `tradeai-active-trader-motion` on deploy SHA `306f81799` since 2026-09-18. No running unit is pinned to an older portfolio-server release. |
| 6 masked cron lines | 5 comments whose script token is `process_watchlist_agent_jobs[.]py`, tag `RETIRED_NO_AUTORESTORE_20260915` | −1. |
| 225 dead baseline entries | 224 of 515 baseline lines are not an exact live job | −1. A separate 107-line tranche dated 2026-09-28 is 107/107 live and is not inside the 515. |

441/469 jobs `cd` to CURRENT. 0 jobs `cd` to the rebuild tree. 399/469 use `$PY`, which is the dev-tree virtualenv and not the code tree. Exceptions that do not execute CURRENT code: `nyc-dof-auction` (2 jobs, leave them), a Claude sync script, two OpenClaw health-inspect scripts, a campaign wake-selection feed, and two poller wrappers that themselves resolve CURRENT.

`linux_launchers/run_options_monitor.sh` is started from CURRENT and then `cd`s to the rebuild tree. The only `options_monitor.log` found is on the dev tree. Last completion 2026-09-28 16:06 ET, `ok=true`, `proposals=7`, before this pin.

Failed user units: `mcporter-token-refresh.service` (exit 1), `ubuntu-report.path` (resources), `snap.firmware-updater.firmware-notifier.service`. Failed system unit: `fancontrol.service`. None were reset.

### 5.2 Lane registry

`CURRENT/config/lane_registry.json`, 158 lanes.

| State | n | Notes |
|---|---:|---|
| ACTIVE | 121 | 69 cron, 51 systemd, 1 event |
| PAUSED | 13 | |
| NEVER_SCHEDULED | 14 | |
| RETIRED | 10 | |

Host check: 69/69 ACTIVE cron tokens are on an active crontab line. 51/51 ACTIVE systemd timers are enabled.

Dark under the census age rule (missing file, or older than the greater of 36 hours and twice the cadence):

| Lane | Evidence |
|---|---|
| `cio-stance-classification-drain` | file age 74.1 h, cadence 24 h, cron present |
| `source-litmus-vs-yahoo` | file age 61.7 h, cadence 24 h, timer enabled |
| `llm-spend-report-monthly` | output file missing, cron present |
| `approval-package-reminder` | output file missing, cadence 1 h, cron present |

Registry versus host:

- `at-observation-01` and its closeout are RETIRED in the registry and **enabled** as user timers.
- `tradeai-continuous` is PAUSED in the registry and the user timer is disabled. The **system** timer of the same name is enabled. Last trigger 2026-09-28 04:00 ET. WorkingDirectory is the rebuild tree.

10 ACTIVE lanes whose signal is `none` or `db_max` were not freshness-checked. No database query was used for those signals.

### 5.3 Schedule, output, consumption

| Job | Schedule | After promote | Output | Consumer | Edge |
|---|---|---|---|---|---|
| Wake dispatcher | `*/5` | 39 completes, 0 error lines, about 46 slots so 7 gaps unclassified | `runs=5 persisted=0` on the last five | Wake-job file is written | PARTIAL. Dispatch observed. Cognition persist is a no-op. Log has no SHA. |
| Persistent wake | hourly :00 | 4/4 `outcome=ok` | research and due-record rows | Retrieval log moves at 01:00Z | PARTIAL. Wake and retrieval observed. No decision. |
| Reactive timer | ~2 min | 111 cycles, `event_enqueued` peak 6, `dispatched=0` | Enqueue | Dispatcher is a different process | PARTIAL. Not inactive. Claim of the specific ids was not line-joined. |
| Gate bridge | hourly :35 | 3/3 writes into the `25afedb35` tree | `agent_gate_measurements.json` | The file. Catalog was not updated by this audit. | OBSERVED_SERVED for the write. The board is section 3.3. |
| Commitment sweep | 18:20 ET | 1 fire | scored 0, appended 56, unfalsifiable 692 | Belief writer ran 30 min later | PARTIAL. |
| Belief writer | 18:50 ET | 1 fire | 1 belief, influence 0 | No later decision | PARTIAL. Producer only. |
| Due checkpoints | hourly :20 | 22:20Z due 3 resolved 0; 23:20Z due 15 resolved 12; 00:20Z due 68 resolved 0; 01:20Z due 19 resolved 0 | Log | Not a new decision | PARTIAL. |
| Nightly reflection | 21:50 ET | none as of 21:34 ET | Yesterday's JSON: cases 3038, scored 2701, proposals 1, auto_promotions 0 | None new | OBSERVED_HISTORICAL. Next fire 21:50 ET was still future at the close of this window. |
| Advisory lesson reflect | 19:40 ET on this pin | exit 0, 19:40:13–19:41:04 ET, HEAD still `25afedb35` | `advisory_kb_lessons.jsonl` did not append | No new lesson id | OBSERVED_SERVED run, zero rows. |
| Options monitor | weekdays 12:00–15:50 and 16:05 ET | none (window is after the session) | Last log 16:06 ET on the dev tree, `proposals=7` | A later proposal GET returned 7 blocked cards. That GET is not a consumer receipt of the 16:06 run. | WIRED. Next 2026-09-29 12:00 ET. |
| Orchestrator | 09, 10, 12, 14, 16, 17:30 ET | 0 | 09:00 was `c1c531500`. 17:30 was `d3bfc9ca0` and still writing at 21:41Z into the old release path. Labels 10:00, 12:00, 14:00, 16:00 absent from that log. | NOT_MEASURED | OBSERVED_HISTORICAL for 09:00 and 17:30. |

Event to wake: `portfolio.material_change` last at 2026-08-09T14:14:38Z (`evt-bbdfb7a13cc1`). **NOT_MEASURED** on this pin. Next detector slot after the census was 21:30 ET.

What did happen: first `situation.raised` (`S3_REENTRY_CANDIDATE`) at 2026-09-28T23:50:47Z, then a reactive cycle with `event_enqueued=6` at 23:52:53Z. Delta 2 minutes 6 seconds. The dispatcher was completing about every 5 minutes with `runs=5` in that hour. Joining those 6 ids to a specific complete line was not done. Verdict: **PARTIAL**, not a measured latency distribution.

Operator outbox: last `DELIVERY_CONFIRMED` 2026-09-28T14:28:37Z. No append after the promote. Dark consumer relative to the bus, which did move. `agent_handoff_queue.jsonl` idle since 2026-08-09.

Webhook: no crontab line and no user unit matched `webhook` or `whatsapp`. DESIGN_ONLY as a scheduled listener.

Lock parity and duplicate manual runs: not invoked. The health agent reports `schwab_transaction_ingest.py` and `schwab_journal_builder.py` on crontab lines 499 and 500 with two different lock paths. That is a STATIC conflict report from health, not a race this audit started.

---

## 6. Website, API, and options

No browser. Viewport, chain click, payoff chart, and badge color are NOT_MEASURED as user interaction. Endpoint results are the evidence.

### 6.1 Calls on this pin

Two passes. The first (about 01:15–01:23Z) is the parent read. The second (about 01:18–01:29Z) is a read-only GET census of the backing APIs. No browser. Narrow viewport is NOT_MEASURED. Chain click, payoff chart, and badge color were not rendered.

| Endpoint | HTTP | State | Trace |
|---|---:|---|---|
| `GET /v3/build-meta.json` | 200 | WORKING as an identity stamp | SHA, UI, built_at match section 2.3. Re-read at 01:34:09Z. |
| `GET /api/v2/health` | 200 | DEGRADED | `status=degraded`, `mode=advisory`, `healthy` false, score 66. 45 findings: 8 critical, 17 warning, 20 info. Captured 2026-09-29T01:18:22Z on the second pass. A 200 is not health. |
| `GET /api/v2/portfolio/book-map` | 200 | DEGRADED beside the header | `securities_only=true`, `as_of=2026-09-28`, rows 25, unpriced 0, `total_day_change=-2380.91`, `total_value=260179.0`, `cash_total=999690.77`. Cash is a balance beside the book. |
| `GET /api/v2/portfolio/performance` | 200 | WORKING for 1D against the book | `1D.change=-2380.91`. Matches the book. Longer periods were not scored as market returns. The second pass also saw 43 snapshot outliers and a YTD pin note. |
| `GET /api/v2/overview` | 200 | DEGRADED | `today_change=-2412.59`, `today_pct=-0.19`, `as_of=2026-09-28`, `position_count=10`, `pipeline_status=fresh`. `today_pnl.mark_source=finviz_afterhours`, `calculated_at=2026-09-28 16:45:01 ET`. Sum of `today_by_account.change` equals the header. Header minus book = −31.68. |
| `GET /api/v2/portfolio/overview`, `/api/v2/command-center/home`, `/api/v2/dashboard/summary` | 404 | DARK as those paths | The header is `/api/v2/overview`, which returned 200. |
| `GET /api/v2/portfolio/holdings` | 200 | DEGRADED | Count 20. `today_change=-2412.45` (within $0.14 of the header). `last_repriced` 2026-09-28 16:45:01 ET. Symbols not listed. |
| `GET /api/v2/options/holdings-funnel` | 200 | DEGRADED | Readable, and internally inconsistent. See below. |
| `GET /api/v2/options/execution/status` | 200 | DEGRADED as a safety label | `armed_for_execution` true. See F-01. This is a status read, not a fill. The handler's `CREATE TABLE IF NOT EXISTS` did not change `updated_at`. |
| `GET /api/v2/options/proposals` | 000, then 200 | DEGRADED | First pass: 40s and 90s, 0 bytes, HTTP 000. Second pass: 200, ~264 KB, `generated_at` 2026-09-29T01:23:55.955475Z, `market_session` CLOSED, count 7, `live_eligible` 0. |

Router source (`NavRail.tsx`, `App.tsx`, `tradingDeepLink.ts`) names the rail: Home `/`, Portfolio, Trading, Watch, Risk, Active Trader, Journal; CIO Desk, Communications, Research Intel; Health, LLM Spend `/consumption`, System. Trading tabs: Trade AI, Options, Open Trades, Proposals, Entry Desk, Execution, Broker Recon, Scalp, ATM Controls, Broker Orders, Schwab Accounts. Off-rail routes exist (`/portfolio/re-entry`, `/strategy`, `/agents`, `/intelligence`, `/hermes`, `/retirement`, control-plane children). They were classified from the backing GET where one was safe, and left NOT_MEASURED where the only routes are order or 2FA paths.

### 6.1a Surface classes (API, not a clicked screen)

WORKING means the primary payload is populated and does not describe itself as stale or empty. DEGRADED means HTTP 200 with stale, partial, blocked, or inconsistent data. A rendered tab was not observed.

| Surface | Class | Why |
|---|---|---|
| Home | DEGRADED | Header populated. Embedded health 66. Setup strip `RUN_UNDERFILLED`. Book day-change differs by $31.68. |
| Portfolio | DEGRADED | Unpriced 0. Position counts 10 / 20 / 25. Book day-change ≠ header. |
| Trading / Trade AI | DEGRADED | Run `2026-09-28::1730`, `go` 0, `wait` 0, `nogo` 3, review 21, scanned 24, quality `DEGRADED`, freshness `RUN_UNDERFILLED`, reason `PREOPEN_WINDOW_BY_DESIGN`. Cache `stale` false. Do not blend with `universe_nogo` 86. |
| Trading / Options | DEGRADED | 7 cards, `live_eligible` 0, every packet BLOCKED. Quotes ~19:59–20:00Z on 2026-09-28. |
| Trading / Open Trades | DEGRADED | `/api/v2/open-trades` count 1, `last_updated_at` 2026-09-28T16:58:01-04. A separate intelligence list is 23 positions and 63 excluded. |
| Trading / Proposals | DEGRADED | Link rate 2.9% vs target 15%. Broker queue 17/17 blocked, `route_ready` 0. Pending now 129 on the 7-day readiness read. Paper list 15 PENDING of count 50. |
| Trading / Entry Desk | DEGRADED | Automation GET 200 at 01:27:02Z. Drafts and activity are order routes and were not called. |
| Trading / Execution | DEGRADED | Autonomous submit blocked. Operator 2FA path on. See F-24. |
| Trading / Broker Recon | DEGRADED | Latest run started 2026-09-28T09:35:01-04, `finished_at` null, `run_status` completed. 50 items: `CLOSED_BUT_HELD` 31, `ORPHAN_BROKER` 19. |
| Trading / Scalp | DEGRADED | 19 signals: AVOID 18, WAIT 1, GO 0. `ws_available` false. Signal time 2026-09-28T13:30:11Z. |
| Trading / ATM Controls | DEGRADED | `live_trading_allowed` false, `criteria_met` false. State last change 2026-05-22. |
| Trading / Broker Orders | INTENTIONALLY_BLOCKED | Order routes. Not called. |
| Trading / Schwab Accounts | DEGRADED | `accounts-live` 200, `read_only` true, 3 accounts, orders empty. System broker-connectors still say 3 rows `ready_awaiting_creds`, wired false. Position row counts exist and are not printed. |
| Watch / Intelligence | DEGRADED | `data_quality_status` PARTIAL. matched 21, held 22, screener 89, `proposal_eligible` 0, `near_trigger` 0. |
| Watch / Watchpool | DEGRADED | 200 rows. No `as_of`. |
| Watch / Sectors | WORKING | 11 sectors, `as_of` 2026-09-28T20:30:03Z, `stale` false (`stale_after` 72h). |
| Watch / Pullback | DEGRADED | 31 candidates, trigger 4 of which 1 stale, generated 16:40 ET. |
| Risk | DEGRADED | 10 positions, correlation stamp 07:39 ET. Regime latest not stale. |
| Active Trader | DEGRADED | Permission queue `LIVE_DATA`, `read_only` true, mode `MANUAL_PAPER_TEST_ONLY`, actionable 39, `scanner_go_count` 0. |
| Journal | WORKING | `trade_count` 174, lessons 133, integrity warnings 0. Paper readiness `P1_EARLY_SIGNAL`, `live_trading_prohibited` true. Not a live quote. |
| CIO Desk | WORKING | `/api/v3/cio/home` 200, `as_of` 2026-09-29T01:27:00Z, authority `READ_ONLY_ADVISORY`. |
| Communications | DEGRADED | Mode CANARY. Events page returned 5 rows and total 5. Bodies not read. No Telegram send. |
| Research Intel | DEGRADED | `stale_topic_count` 5, coverage gaps 9, queued 51. |
| Health | DEGRADED | Score 66. |
| LLM Spend | DEGRADED | Overview 200. `local-llm-status` model `nomic-embed-text` available, `last_run` 2026-05-12, trades awaiting analysis 127, proposals awaiting 113. |
| System | DEGRADED | Jobs `failed_today` 10. Queue tower `cron_count` 469. Scheduled-jobs health reports cron active 473 (a different counter). Live gate `PAPER_ONLY`. |
| Hermes | DEGRADED | `gateway_status` offline. `coordinator_active` true. `kill_switch_active` false. |
| Deploy events | WORKING | Count 3, `advisory_only` true. |

Unknown-route probes returned 404 HTML whose message names the path (`Not found: /api/v2/does-not-exist-audit-surfaces`). That is a named error for a missing route. It was not exercised from a card click.

### 6.2 Health criticals (the red counters)

Captured 2026-09-29T01:15:26Z inside the health payload, re-read during the window.

| Severity | Type | Message (short) |
|---|---|---|
| critical | `release_manifest_fail` | Manifest status FAIL. The file is `docs/project/RELEASE_MANIFEST_LATEST.md`, generated 2026-09-27T00:09:17Z. Live-adjacent dirty: none. Two FAIL lines are source-only sandbox notes. The dashboard is showing a stale FAIL. |
| critical | `approved_paper_test_stuck` | 6 proposals stuck in `APPROVED_FOR_PAPER_TEST`. |
| critical | `research_lane_firing:cio-hermes-queue` | `unclassified_24h:5`. |
| critical | `research_lane_firing:deepseek` | `budget_throttled:55/126`. |
| critical | `siem_p0p1` | 8 distinct P0/P1 SIEM issues in 24h. |
| critical | `momentum_scalp_go_not_converting` | 6 GO rows in 5 days, 0 momentum-scalp proposals. Skip counts in the message: LOW_SCORE 80, NO_ANALYST 64, STRATEGY_CRITERIA 34, plus a truncated LIQUID bucket. |
| critical | `backup_step_failed` | 1 backup step failed in the last cadence. |
| critical | `db_dump_stale` | Newest full dump 223h old. Threshold cited: 26h. |

Warnings that matter beside memory: `alpha_vantage` 181.3h, 7 orphaned stops, 7 stops in alert with no synthetic coverage, proposal execution link rate 2.9% against a 15% target, 0% of 10 pending broker proposals logged as executed, audit ledger missing `risk_block_emitted`, `evidence_revalidation`, `submit_requested`, `broker_ack_received`, `broker_reject`, cron lines 247 and 253 using a relative `.venv` that does not exist under CURRENT, and the Schwab ingest lock split on lines 499 and 500. Scalp catalyst verification: 42 setups in 3 days, 21 WAIT, 0 catalyst-verified, 0 GO.

These remain findings whether or not memory tests pass.

### 6.3 Options stage chain

| Stage | Served state | Verdict |
|---|---|---|
| Candidate generation | Monitor cron exists. Last natural log 16:06 ET on the dev tree, before this pin, `proposals=7`. The later list also has 7 cards. Those two 7s were not joined. | OBSERVED_HISTORICAL for the monitor log. The list is a later read. |
| Quote / chain | Funnel `resolve_chain=true`, `cc_no_chain=0`. Card quote times are 2026-09-28 ~19:59–20:00Z. Session on the list is CLOSED. Live chain endpoint was not called. | PARTIAL. |
| Leg liquidity, 12% spread, 0.25 credit floor | Cards are blocked. Block codes seen include closed-market quote/liquidity waits, `thesis_required`, and `awaiting_cio_decision`. The 12% and 0.25 floors were not re-measured as numbers on a card. They were not changed. | PARTIAL. A per-card spread percent was not extracted. |
| Strategy id / packet fail-closed | Served read path: if `packet_view` cannot be imported, status is `PACKET_UNVERIFIED`, `qualified_count` 0, alternatives withheld. Live: every current buy-ready packet is that status. `gate_version` null. | OBSERVED_SERVED as containment. |
| #1339 earnings gate | Blobs on disk match `25afedb35`, not `f306b5e6d`. Served `earnings_blackout_check` blocks unknown timestamps only for strategies in `BLOCKING_STRATEGIES`. An empty calendar returns `in_blackout: false`. A strategy outside that set returns `in_blackout: false` with no `gate_version`. | #1339 fail-closed is not what the process loaded. |
| Event / earnings / wash | Card earnings objects have no `gate_version`. Where present, `in_blackout` is false. At least one card has `next_earnings` null and `in_blackout` false. Wash-sale by account was not read. | PARTIAL. Empty-calendar behavior is the served code. |
| CIO review | Every proposal card: `cio_approved` false, cio status unreviewed, decision packet `BLOCKED`. Buy-ready index rows for AXTI and TSLA: `DRY_RUN`. | OBSERVED_SERVED for those cards. |
| Visible card | 7 cards: `cash_secured_put` 3, `protective_put` 2, `covered_call` 2. Tier A 3, B 4. `quality_pass` true is not qualification. `severity` blocked, `enterprise_blocked` true, `approvable` false, `readiness.cta` none. Symbols on the cards: ACET, AAOX, ACHR, SPCX, XAR. Strikes omitted. None of AXTI, TSLA, DELL, SCHD is in this list. | DEGRADED. Blocked cards are visible to a client that waits long enough. |
| Chain swap / view, payoff chart, beginner copy | Not clicked. | NOT_MEASURED. |
| Server preflight | Not called. | NOT_MEASURED. |
| Operator 2FA | Not initiated. `GET /api/v2/live-trading-gate` status `PAPER_ONLY`. `operator_live_via_2fa_allowed` true (standing DB unlock). `per_order_2fa_required` true. `autonomous_live_submit_allowed` false. `all_gates_passed` false (`win_rate` and `time_in_paper` not passed). | WIRED. The standing unlock is real. A fresh ceremony was not started. |
| Broker adapter | `submit()` calls `schwab_transport.place_order`. Not called. | NOT_MEASURED. |
| Position monitor / exit / case | `GET /api/v2/options/open-positions` position_count 0, `paper_lab_retired` true, monitored_at 2026-09-29T01:23:51Z. Overview `needs_action` 0. Monitor log 16:06 ET is historical. | OBSERVED_SERVED for an empty open book. The monitor's own log is historical. |
| Supervised live one-lot | No broker receipt. | NOT_MEASURED. This audit will not perform it. |

Execution status payload, scalars only: `options_execution_enabled` true, `policy_ENABLED_commit` true, `armed_for_execution` true. The database value has been true since 2026-06-22 16:25:33 ET. The served file `scripts/brokers/options_execution_policy.py` sets `ENABLED = True` while the docstring says default OFF. `evaluate()` checks account allowlist, strategy, order type, contracts (max 5), notional (max 25,000), and credit-spread width (max 15%). It does not check the desk's 12% spread cap or the 0.25 credit floor. Those desk gates live elsewhere. A 15% execution width and a 12% desk cap are a conflict (F-02). `GATES_REMOVED` is false. The approve and revoke phrases are generated from today's date in the status function; they are not repeated in this report.

Holdings funnel at 2026-09-29T01:23:22Z, counts only:

| Field | Value |
|---|---|
| holdings_scanned | 13 |
| fractional residue count | 12 |
| cc_by_status | CC_ELIGIBLE 1, EDGE_BELOW 3, INTENT_BYPASS 2, MV_BELOW 1, NEED_100_SHARES 3, NOT_OPTIONABLE 3 |
| summary `cc_eligible` | 3 |
| cc_need_100_shares | 3 |
| cc_edge_below | 3 |
| cc_no_chain | 0 |
| put_eligible | 0 |
| intent_cc | 3 |
| min_shares_cc / min_iv_rank / min_edge | 100 / 20 / 62 |

`cc_eligible` 3 and `CC_ELIGIBLE` 1 are both in the same payload. That is an unlabeled split. Share quantities and account lots are not copied here. The note on the payload says this is a backfill from holdings of record, not every name, and not a silent omit. It is not a market-wide search.

Buy-ready packets, `GET /api/v2/buy-ready/packets`, `data.as_of` 2026-09-29T01:23:44Z: 7 current packets, all `options_alt.status = PACKET_UNVERIFIED`, reason "this build cannot verify stored verdicts (packet_view absent) — alternatives withheld", `qualified_count` 0, `gate_version` null. Symbols withheld: AXTI, DXCM, NYT, PEW, SWK, TDG, TSLA.

| Symbol | Equity state | saved_at | packet_age_h | evaluated_at | considered | Stored claim (withheld) | Desk |
|---|---|---|---:|---|---:|---|---|
| AXTI | ENTRY_NEAR | 2026-09-28T14:20:23Z | 11.06 | 2026-09-28T14:20:04Z | 4 | OPTIONS_ALT_OK | not_built / EDGE_BELOW |
| TSLA | BUY_READY | 2026-09-28T14:50:12Z | 10.56 | 2026-09-28T14:50:03Z | 4 | OPTIONS_ALT_OK | not_in_desk_universe |

Single-symbol GETs for AXTI and TSLA return `status: PACKET_UNVERIFIED`, `stale.code: PACKET_UNVERIFIED`, `stale.reason: staleness check unavailable (ImportError)`, and no `options_alternatives`. Displayed qualification is `PACKET_UNVERIFIED`. CIO review on both index rows is `DRY_RUN`. AXTI is also in `entry_directional_dropped` with reason `EDGE_BELOW`. DELL and SCHD: `GET /api/v2/symbol/{DELL,SCHD}/buy-ready-packet` returns `NO_PACKET`. Neither is in the proposals list. No stored 520/500 packet was present to age. An old `OPTIONS_ALT_OK` did not become a green card.

`PACKET_UNVERIFIED` withholding is containment. It is not proof that a newly stamped qualified packet would render, and it is not the #1339 earnings-gate stamp. That package is on git HEAD in the directory and not in the blobs the process loaded.

Telegram versus Command Center: the outbox did not append after 14:28Z. No alert was sent. A same-timestamp delivered-idea-versus-queue comparison for this pin is NOT_MEASURED. The proposal list, when it returned, did not contain AXTI.

2FA, from the status reads and not from a ceremony: per-intent approval is a separate function (`approval_service.request_approval` before `submit()`). This audit did not observe a live intent hash or a broker acknowledgement. `GET /api/v2/execution/current-state` at 2026-09-29T01:26:29Z has `live_paths.options.armed_for_execution` true and `live_paths.options.live_eligible` true, with `current_blockers` length 0, while every proposal card has `live_eligible` false and autonomous submit is false. Those two uses of "live eligible" are not the same fact (F-24). `paper_mode` on current-state is false and `live_trading_global_allowed` is true. The paper-validation gate is still `PAPER_ONLY`.

---

## 7. Findings register

Severity words: safety, dark lane, correctness, observability, usability.

| ID | Sev | Symptom | Evidence | Cause | User effect | Containment | Close when |
|---|---|---|---|---|---|---|---|
| F-01 | safety | Options execution status reports armed, and the served policy constant is true, while the docstring says default off. | Status GET; `system_controls` updated_at 2026-06-22; `ENABLED = True` at `options_execution_policy.py`. | Standing DB flag plus a commit gate that is on. | An operator can read "armed" and believe a new ceremony happened today. Submit still has a separate 2FA function. Whether every submit path calls it was not exhaustively proven. | Operator confirms the June 22 arm is still wanted. If it is not, revoke through the existing phrase. This audit did not revoke. | A read of the flag after the operator's action, plus a test that a submit without a fresh 2FA receipt is refused. |
| F-02 | correctness | Execution width cap is 15%. Desk spread cap is 12%. | `MAX_SPREAD_WIDTH_PCT = 15.0` versus the desk rule. | Two policies. | A structure the desk blocks could pass `evaluate()` if it were submitted. Not observed as a submit. | Do not loosen 12%. Do not raise or lower 15% in this audit. | One hermetic case: 13% width fails the desk and fails closed at submit. |
| F-03 | usability | Options proposal list can sit silent for 90s and can also return. | First pass: 40s and 90s, 0 bytes. Second pass: 200, ~264 KB, 7 blocked cards, `generated_at` 2026-09-29T01:23:55Z. | Hypothesis: the handler sometimes blocks on a chain or a cache rebuild. The cause was not traced into the process. | A client that gives up at 30s shows an empty desk. A client that waits sees 7 blocked cards and 0 qualified. | Do not restart the server as part of this audit. | A GET under 5s that returns the count, `generated_at`, and per-card state, including the buy-ready withhold list. |
| F-04 | observability | Red critical `release_manifest_fail`. | Manifest markdown generated 2026-09-27T00:09Z, Status FAIL, live-adjacent dirty none. | Health reads a stale Status line. | A red counter that is not a fresh validator failure. | Regenerate the manifest under a change window, or stop treating a day-old sandbox FAIL as critical. Not done here. | Health no longer emits this type from a file older than the release, or the file is PASS and the critical is gone. |
| F-05 | safety | Full database dump is 223h old. Backup step failed. | Health criticals `db_dump_stale`, `backup_step_failed`. | Cadence failure. Cause of the step failure not opened. | Recovery point is older than the stated 26h bar. | Operator backup run. Not started here. | A dump newer than 26h and a cadence log with the failed step green. |
| F-06 | observability | 8 P0/P1 SIEM issues, 6 stuck paper-test proposals, Hermes queue unclassified, DeepSeek throttled 55/126. | Health payload. | Separate lanes. Not root-caused one by one. | The board is loud. Some of it may be real and some stale, as F-04 shows. | Triage the SIEM ids in a follow-up. Do not clear them from this audit. | Each id has an owner and a current/not-current mark. |
| F-07 | dark lane | Sentinel and Iris wake and lease nothing. Darwin refuses stale work. | Journals 21:01–21:26 ET. | SHADOW prepare-only dispatcher, empty or stale intake. | The names exist. They do not review or score. | Do not enable operator auth or a queue just to score the board. | A natural fire with `COMPLETED >= 1` and a new review row whose artifact id joins an action, on one pin. |
| F-08 | correctness | Agent-runtime unit sets PYTHONPATH to the dev tree after setting WorkingDirectory to CURRENT. | `systemctl cat tradeai-agent-runtime@sentinel.service`. | Later Environment= wins. | A "served" agent can import unreleased modules. | Confirm `sys.path` on the next natural fire. Do not edit the unit in this audit. | One log line with the imported file's real path equal to the release, or an explicit decision that the dev tree is the runner. |
| F-09 | dark lane | Three stores share the lesson name and none is the served loop. | Production `trade_ai`: schema `agentic_runtime` absent. Lab DB: tables present, last write 2026-07-27 to 2026-08-03, 0 LIVE `agent_runs`, 0 writes after promote. File `advisory_kb_lessons.jsonl`: 3154 lines, qwen3 4096, last 2026-09-28T16:17:04Z. | Migration not applied to production. Lab writer stopped in August. File writer is a different contract. | Architecture language says `kb_lessons` as if one queryable table were live. | Do not apply the migration in this audit. Do not point the wake at the stale lab DB to make a count. | One named reader, one named store, and a row written on the served pin, or the architecture marked historical. |
| F-10 | correctness | Outcome sweep scored 0 of 692 due. Belief writer skipped 6,922 checkpoints for no direction. | Sweep JSON 18:20 ET. Belief JSON 18:50 ET. | Due rows unfalsifiable; checkpoints lack direction. | Learning looks busy and does not score. | Leave the writers on their schedule. | A later natural sweep with `scored` greater than 0 on rows that have a price and a commitment, and a decision that does not change while influence is 0. |
| F-11 | dark lane | Lesson ratification does not happen. | Candidates PROVISIONAL, promotions QUEUED, Iris leased 0. | No consumer with authority. | Lessons never become retrievable policy, which is the safe failure, and also means the loop is not closed. | Do not auto-promote. | One operator or Iris ratification row, and a later retrieval that cites it, still with influence 0 until a separate grant. |
| F-12 | observability | Heartbeats have no release SHA. | 992 rows, grouped SHA empty. | Writer omits the pin. | A beat cannot be blamed on a release. | Add the SHA in a later change. | New rows carry `25afedb35` or its successor. |
| F-13 | dark lane | Notification outbox idle since 14:28Z while wakes continue. Handoff queue idle since August 9. | File mtimes. | Consumer or producer stopped. Not restarted here. | Operator surface can miss what the bus saw. | Trace the outbox writer. Do not send a test Telegram. | One natural append and one confirmed read, or a documented decision that the outbox is retired. |
| F-14 | correctness | #1339 is merged, is the release directory's git HEAD, and is not what the process loaded. | Build-meta and PID 435701 cwd are `25afedb35`. `git rev-parse` in the release dir is `f306b5e6d` since 20:26:24 EDT. Earnings-gate and memory blobs on disk match `25afedb35`. `f306b5e6d` is not an ancestor of the served commit. | The worktree was fast-forwarded under a live process. | Anyone who trusts `git HEAD` in the release directory will test the wrong code. `packet_view` is absent, so every buy-ready alternative is withheld. | Do not promote from this audit. Do not reset the worktree under the live process. | A promote receipt whose deployed SHA is the intended commit, a process restart onto that tree, and a blob check that matches HEAD. |
| F-15 | dark lane | Options monitor executes the dev tree. | Script `cd`. Log only on the dev tree. Last line before this pin. | Launcher sets PROJECT_ROOT to the rebuild tree. | A promote does not change the monitor's code. | Point the launcher at CURRENT under a change window. Not done here. | A log line after the next 12:00 ET run whose path is the release directory. |
| F-16 | dark lane | Active Trader motion is a 2026-09-18 deploy SHA. Three proxies have been on the dev tree since 2026-09-12. | systemd show. | Not in the CURRENT-bound restart set. | Those processes do not follow promote. | Operator decides whether they should. | Restart onto the intended root, or a written exception. |
| F-17 | correctness | Registry says two Active Trader observation lanes are retired. The timers are enabled. System `tradeai-continuous` runs while the registry says paused. | lane_registry.json versus systemctl. | Registry not updated when the system unit stayed enabled. | The registry lies. | Do not disable timers in this audit. | Registry state matches `UnitFileState` for those three. |
| F-18 | usability | Funnel says 3 covered-call eligible and also 1 `CC_ELIGIBLE`. | Same JSON. | Two counters, unlabeled. | The desk can show two different eligible counts. | Label both or delete one. Not done here. | One number, one definition, a test that locks it. |
| F-19 | observability | Gate board pass is "at least 100 actions," measured on a multi-pin ledger. | Script has no SHA filter. | Cumulative file. | A population pass survives forever once the file is large. | Keep it, and add a this-pin or this-week denominator beside it. | The report shows both denominators. |
| F-20 | dark lane | Four registry lanes are dark by the age rule, including a 1-hour reminder with no file. | Section 5.2. | Producer missing or stalled. | A promised reminder does not exist. | Restore the producer or retire the lane. | File mtime inside cadence, or lane RETIRED and timer absent. |
| F-21 | safety | Every current buy-ready options alternative is withheld. | `GET /api/v2/buy-ready/packets` as_of 2026-09-29T01:23:44Z. 7/7 `PACKET_UNVERIFIED`, `qualified_count` 0, `gate_version` null, reason `packet_view` absent. AXTI and TSLA single-symbol GETs match, stored claim `OPTIONS_ALT_OK` withheld. DELL and SCHD are `NO_PACKET`. | Served alternatives module has no `packet_view`. The #1339 blobs that define it are not the files on disk. | The operator cannot see a verified options alternative on a buy-ready name. The withhold is the safe behavior. A stored `OPTIONS_ALT_OK` must not be read as qualified. | Leave the withhold in place. Do not hot-edit the release tree to import #1339. | After a real promote of the intended SHA, one natural packet with `gate_version` set, or an explicit `PACKET_UNVERIFIED` that names the new reason. |
| F-22 | correctness | Header TODAY and the securities book disagree by $31.68 on this pin. | Overview `today_change` −2412.59. Book `total_day_change` −2380.91. Performance 1D equals the book. Header equals the sum of account day changes. Unpriced 0. Mark source `finviz_afterhours`, calculated 16:45:01 ET. | Header scope is all accounts and uses the Finviz reprice. Book is securities-only. The $31.68 line was not isolated. | Two day-P/L numbers on one date. | Label the scope on both, or show the residual. Not done here. | One labeled residual that sums header to book, with a test. |
| F-23 | correctness | Three position counts: overview 10, holdings 20, book 25. | Same GETs as F-22. | Different filters (cash, duplicates, unpriced handling). Not root-caused row by row. | "How many positions" depends on the page. | Publish the filter beside each count. | One fixture where the three counts are explained by named exclusions. |
| F-24 | safety | Execution state says options `live_eligible` true and `current_blockers` length 0, while every card is `live_eligible` false and autonomous submit is false. | `GET /api/v2/execution/current-state` 2026-09-29T01:26:29Z. Live gate `PAPER_ONLY`, `all_gates_passed` false, `per_order_2fa_required` true, `autonomous_live_submit_allowed` false, `operator_live_via_2fa_allowed` true. Proposals `live_eligible` 0. | Two fields share a name. The standing June 22 arm feeds the execution path. | An operator can read the execution page as ready while the desk has nothing eligible and the paper gate has not passed. | Confirm the arm (F-01). Do not start 2FA from this audit. | The execution label says standing-unlock-plus-per-order-2FA, and it does not say live-eligible while card `live_eligible` is 0. |
| F-25 | correctness | Broker recon has 31 `CLOSED_BUT_HELD` and 19 `ORPHAN_BROKER` in the latest 50 items. | `GET /api/v2/broker-reconciliation` 200. Run started 2026-09-28T09:35:01-04, `finished_at` null, `run_status` completed. | Not root-caused. | The recon tab is a break list, not a clean bill. | Read-only review by the operator. No order repair from this audit. | Each item class has an owner and a current/historical mark. |
| F-26 | dark lane | SCHD house-rule correction is code plus a markdown note. The wake does not load it. | Section 4.6. Case row absent. Post-promote SCHD retrievals cite memory `2d26758e9dc6` (August preference), influence 0. | `default_loaders` does not read the findings file or `cio_production_cases.jsonl`. The `--apply` recorder was not run. | The next SCHD answer can repeat the old path. The classifier exists for a card that is actually built. | Do not seed a production chat. An operator may record the case under the existing tool when they choose. | A case id in `cio_production_cases.jsonl`, a later retrieval that cites it, influence still 0, and no order. |
| F-27 | safety | Command Center HTTP stopped answering at the end of this window. | `GET /v3/build-meta.json` 0 bytes at 8s (2026-09-29T01:38:52Z) and at 25s (about 01:40Z). Unit `active`, PID 435701, start 20:18:58 ET, `NRestarts` 3. `wchan` `futex_do_wait`. Port 7777: 66 `CLOSE-WAIT`, 26 `ESTAB`, recv-queue sum about 51 KB across 90 sockets. Last good build-meta 01:34:09Z, SHA unchanged. | Hypothesis: the single server stopped reading sockets. A proposals handler that can sit for 90s (F-03) is a candidate. Not proven as the cause. The surfaces census issued many GETs in the same hour. | The operator site can look down while the process is still "active." | Restart only through the operator's usual service path. This audit did not restart it, and did not kill sockets. | A build-meta 200 whose SHA is recorded, and a socket count that drains. If the SHA changed, start a new observation window. |

Top risks, in order: F-27 (HTTP not answering while the unit looks active), F-01 and F-24 (armed options path and a live-eligible label while cards and autonomous submit are blocked), F-05 (backup age), F-14 (release git HEAD is not the process), F-21 (buy-ready alternatives withheld), F-03 (proposal list can hang), F-07 and F-09 (agents finish no reviews; the lab knowledge base is stale), F-04 (stale red critical), F-22 (header versus book).

---

## 8. Proposed remediation

This audit does not execute this program. Each item needs its own authorization. Rollback is "do not promote" unless the item says otherwise. Influence stays 0. The 12% spread cap and the 0.25 credit floor stay where they are.

### R1. Contain unsafe presentation

- F-27 first, because the site is the operator's window onto everything else. Acceptance: `GET /v3/build-meta.json` returns 200 and the SHA is written down. If that SHA is not `25afedb35`, this report's served claims stop at 01:34:09Z. Negative control: do not call the restart a proof that the handler is fixed. Authorization: the operator's existing service restart. Rollback: the previous release, only if the restart itself fails health. This audit does not restart.
- F-01: operator decides keep or revoke the June 22 arm. Acceptance: status GET matches the decision. Negative control: a submit fixture with no 2FA receipt is refused. Natural opportunity: the next status read, after F-27. Authorization: operator phrase if revoking. Rollback: the same arm path. Evidence: status JSON and `updated_at`, no order id.
- F-04: regenerate or relabel the release manifest. Acceptance: health either drops `release_manifest_fail` or the manifest `Generated` time is after the release and the FAIL is reproduced by a fresh command. Negative control: a manifest with Status FAIL and a fresh timestamp still shows the critical. Authorization: a docs or ops change, not a promote by itself. Rollback: restore the previous markdown.
- F-02: add a hermetic test only. Do not change the numbers. Acceptance: width 13 fails closed at the submit boundary. Negative control: width 10 still reaches the 2FA mock and stops there.

### R2. Restore producer and consumer edges

- F-03: find why the proposal handler sometimes returns 0 bytes for 90s. Acceptance: GET under 5 seconds with count 7 or an honest empty, and `generated_at`. Negative control: a stale chain fixture returns a named error, not a hang. Natural opportunity: the next market-hours monitor at 12:00 ET, after F-15. Authorization: a code change and, later, a release grant. Rollback: the previous release.
- F-15: make the options launcher stay on CURRENT. Acceptance: the next 12:00 ET log path contains the release directory. Negative control: a dry run prints the directory and does not scan. Authorization: cron or script change, operator-only if it is a new crontab line. The existing line can be edited only with a cron grant. Rollback: the previous launcher.
- F-13: one natural outbox append, or retire the lane. Do not send Telegram to test it.
- F-16 and F-17: decide the four stale processes and the three lying lanes. Authorization: operator, because it is a restart or a disable.

### R3. Prove the memory loop without turning influence on

- F-09: name the store. Production `trade_ai` does not have the schema. The lab database has a stale SHADOW copy. The file store is a third contract with a different embedding model. Acceptance: one reader names one store, and a new row on the served pin is either present or explicitly not expected. Negative control: a reader pointed at the missing production schema fails closed and does not fall through to the August lab rows. Authorization: operator for any schema change. Rollback: the migration's down file, if it has one. This audit did not check the down file for destructiveness. Do not drop tables. Do not apply the migration to make the board green.
- F-07: leave the runners in SHADOW until intake is real. Acceptance: one natural `COMPLETED` and one review row that joins an action id, on one SHA. Negative control: a stale item still returns `REFUSED_STALE` (Darwin already did this). Next opportunities: Sentinel about every few minutes; Darwin about hourly at :01; nightly reflection 21:50 ET.
- F-10: keep the 18:20 and 18:50 ET jobs. Acceptance on a later day: `scored` greater than 0 only when a commitment has a direction and a price, and the next advisory is byte-identical with influence 0. Negative control: a checkpoint with no direction stays in `checkpoint_no_direction`. Next: 2026-09-29 18:20 ET and 18:50 ET.
- F-11: an operator ratification tool that writes one row. Acceptance: a retrieval cites that id and `memory_behavior_influence` is still 0. Negative control: the model cannot set the row to accepted. Authorization: operator. No auto-promote.
- F-08: log the imported path. Acceptance: the path is the release, or the unit is documented as dev-tree-on-purpose. Rollback: drop the log line.

### R4. Dark website and options

- F-21 is already measured on this pin: AXTI and TSLA display `PACKET_UNVERIFIED`, stored claim `OPTIONS_ALT_OK` withheld, `gate_version` null, DELL `NO_PACKET`. The next proof is after a real promote, not another read of this pin. An `OPTIONS_ALT_OK` on an old packet must not render as qualified.
- F-22 and F-23: label header versus book and the three position counts.
- F-24: the execution page's `live_eligible` must not read as "a card is eligible."
- Reconcile funnel counters (F-18) before showing a new eligible number.
- Browser pass, desktop and a narrow viewport, on Home, Trading options, and one refused card. Acceptance: the refusal is visually distinct, the chain control names the endpoint on error, and no control says the order is approvable when the quote or the account is unverified. This audit did not do that pass.

### R5. Monitors

- Heartbeat `release_sha` (F-12).
- Outbox age and proposal-list latency as SLOs.
- Gate board published with two denominators: lifetime ledger, and rows whose time is inside the release (F-19).
- Dump age already alerts. It needs an owner, not another counter (F-05).

### R6. Forward observation

Do not advance a capability to a forward score from this document. The next natural times, ET:

| When | What would count |
|---|---|
| 2026-09-28 21:50 | Nightly reflection on this pin: cases, proposals, auto_promotions 0. |
| 2026-09-28 22:00 | Persistent wake `outcome=ok` and a retrieval with influence 0. |
| 2026-09-29 09:00 | Orchestrator label on the release path, or a recorded miss. |
| 2026-09-29 12:00 | Options monitor log on CURRENT, then a proposal GET. |
| 2026-09-29 18:20 and 18:50 | Sweep `scored` and belief writer, influence still 0. |
| Any time a `portfolio.material_change` is appended | Event time, wake id, advice time. Until then, NOT_MEASURED. |

---

## 9. Appendix

### 9.1 Commands (secrets removed)

- `curl -fsS http://127.0.0.1:7777/v3/build-meta.json`
- `curl -fsS http://127.0.0.1:7777/api/v2/health`
- `readlink -f .../portfolio-server/CURRENT`
- `cio_gate_measurement_bridge.py --json --root CURRENT` (no `--write-measurements`, no `--update-catalog`)
- Postgres: read-only session, `SELECT count(*)`, `information_schema`, max timestamps. No row bodies.
- `crontab -l` classified in process. `systemctl --user` and `journalctl --user` for the named units.
- `GET /api/v2/options/proposals` (first pass timeout; second pass 200), `.../execution/status`, `.../holdings-funnel`, `.../buy-ready/packets`, `.../symbol/AXTI/buy-ready-packet`, `.../symbol/TSLA/buy-ready-packet`, `.../portfolio/book-map`, `.../portfolio/performance`, `.../overview`.
- Host notes, not in git: `/tmp/audit-memory-20260928.md` (measured 2026-09-29T01:27:54Z), `/tmp/audit-lanes-20260928.md`, `/tmp/audit-surfaces-20260928.md` (GETs about 01:18–01:29Z), `/tmp/audit-gates-25afedb35.json`.

### 9.2 Gate verdicts (machine-readable)

```json
{
  "kind": "audit_gate_board",
  "measured_at": "2026-09-29T01:19:08.561685+00:00",
  "served_sha": "25afedb355108e11aa664c495081939aaaeb33b4",
  "denominator": "full cio_action_ledger advisory actions, all pins",
  "actions_real": 40022,
  "pass": ["min_artifact_population"],
  "fail": ["retrieval_provenance_completeness", "independent_review_coverage", "independent_score_coverage"],
  "not_yet_measured": ["contradiction_rate", "unsupported_claim_rate", "stale_input_refusal_accuracy", "deadline_budget_adherence", "duplicate_run_rate", "operator_usefulness", "rollback_test_passed", "authority_violations"],
  "gates_passing": 1,
  "gates_failing": 3,
  "gates_not_measured": 8,
  "promotable": false
}
```

### 9.3 Edge index

| ID | Edge | Verdict |
|---|---|---|
| E-01 | Dispatcher to wake file | PARTIAL |
| E-02 | Persistent wake to retrieval | PARTIAL |
| E-03 | Retrieval to CIO decision | NOT_MEASURED (0 decisions) |
| E-04 | Sweep to scored outcome | FAIL (0/692 scored) |
| E-05 | Belief writer to next action | NOT influence (flag 0, 0 decisions) |
| E-06 | Sentinel timer to review row | FAIL (leased 0, file frozen at 13:21Z) |
| E-07 | Darwin timer to scorecard | FAIL (8 refused stale, 0 completed) |
| E-08 | Iris timer to ratification | WIRED_UNPROVEN |
| E-09 | Nightly reflection to candidate | OBSERVED_HISTORICAL |
| E-10 | MVL SQL to production `trade_ai` | DESIGN_ONLY |
| E-10b | Lab `agentic_runtime` tables to a served writer | OBSERVED_HISTORICAL (last write August 2026, 0 LIVE rows) |
| E-11 | Book day P/L to performance 1D | OBSERVED_SERVED for that pair |
| E-11b | Header TODAY to the securities book | FAIL as an unlabeled match (−2412.59 vs −2380.91) |
| E-12 | Proposal API to cards | DEGRADED (90s silence, then 7 blocked cards) |
| E-13 | Funnel to a single eligible count | FAIL (3 versus 1) |
| E-14 | Execution flags to a fill | NOT_MEASURED |
| E-15 | #1339 main to the running server | NOT served. Git HEAD in the release dir is #1339. Blobs and the process are `25afedb35`. |
| E-16 | Material-change event to wake | NOT_MEASURED since 2026-08-09 |
| E-17 | Situation raised to reactive enqueue | PARTIAL (2m6s, ids not joined) |
| E-18 | Outbox producer to operator | Dark since 14:28Z |
| E-19 | Options monitor cron to CURRENT code | FAIL (script leaves CURRENT) |
| E-20 | SCHD correction file to next CIO retrieval | FAIL as a handoff. The file is not a loader input. Post-promote retrievals cite `2d26758e9dc6`, influence 0. |
| E-21 | `packet_view` import to displayed alternatives | OBSERVED_SERVED withhold (`PACKET_UNVERIFIED`, qualified 0) |
| E-22 | Execution `live_eligible` to card `live_eligible` | FAIL as the same word (true on the path, 0 on the cards) |
| E-23 | Step 7 embedding ladder to a retrieval | WIRED_UNPROVEN (`not_installed` 685/685) |
| E-24 | Belief writer 18:50 ET to `organic_from_belief` | NOT observed after 22:50Z. Historical `BELIEF_REVIEW` is E-25. |
| E-25 | `BELIEF_REVIEW` to a later question | OBSERVED_HISTORICAL (`33342cea…`, 2026-09-27T17:00:02Z, `changed_question`) |

### 9.4 Tests

Hermetic fixtures named in the work order (stale options verdict, unknown strategy, dead consumer, duplicate wake, expired memory, secret-bearing source, provider timeout, checkpoint resume, outcome with no commitment, same-action shadow, cross-account covered call, late fill, stale chain) were **not re-run** in this audit. Existing tests are supporting STATIC evidence only. A same-action shadow must not be scored as influence. No percentage in this report was invented from a zero sample.

### 9.5 Open questions

1. Is the June 22 options arm still intended? Owner: operator. F-01.
2. Should agent-runtime PYTHONPATH be the release? Owner: whoever owns the unit. F-08.
3. Which store is `kb_lessons` for the architecture: the absent production schema, the August lab tables, or `advisory_kb_lessons.jsonl` (qwen3 / 4096)? Owner: architecture. This audit treats them as three stores.
4. The 17:30 orchestrator kept writing into `d3bfc9ca0` after CURRENT moved. Did that process finish cleanly, and which report directory should the operator open? NOT fully measured.
5. Seven dispatcher slots in a ~46-slot window had no complete line. Failures or quiet gaps? The census found 0 Traceback lines and did not classify the 7.
6. Header TODAY versus book is measured (F-22). What the $31.68 residual is, line by line, is still open. Owner: the book-map producer.
7. AXTI and TSLA on this pin are `PACKET_UNVERIFIED` (F-21). DELL is `NO_PACKET`. Whether a future promote of #1339 should be the next release is an operator decision. This audit does not promote.
8. Is the release-directory fast-forward to `f306b5e6d` under PID 435701 an accident of a later prepare, and should that worktree be left dirty until the next promote? Owner: release operator. Do not reset it from this audit.

### 9.6 Follow-up calendar (ET)

| Date | Time | Watch |
|---|---|---|
| 2026-09-28 | 21:50 | Nightly reflection. Expect auto_promotions 0. |
| 2026-09-29 | 09:00 | Orchestrator on the served path. |
| 2026-09-29 | 12:00 | Options monitor. Then proposal GET. |
| 2026-09-29 | 18:20 | Commitment sweep. |
| 2026-09-29 | 18:50 | Belief writer. Influence must still be 0. |
| Next dump | | F-05. Do not wait a week. |

### 9.7 Email

The operator recipient in `scripts/email_notifier.py` is the configured address, and the mechanism is `gog gmail send` on that account. Delivery evidence is appended after send. If send fails, this section stays `EMAIL_PENDING` and the reason is the tool error, not a guessed address.

---

## 10. What this audit refused to do

No deploy, no merge of product code, no promote, no flag edit, no schema apply, no crontab edit, no systemctl restart, no Telegram, no order, no 2FA, no loosening of the 12% spread cap or the 0.25 credit floor, no change to `MEMORY_BEHAVIOR_INFLUENCE`. Findings are not fixes.
