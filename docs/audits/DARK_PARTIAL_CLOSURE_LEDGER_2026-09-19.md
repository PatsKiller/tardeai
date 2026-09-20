# DARK / PARTIAL / UNWIRED closure ledger

```
Status: ACTIVE
as_of: 2026-09-19T20:05:00-04:00
Measured at: served pin 0ed980353-main-exact-phase2-20260919-200406 (#1097 PROMOTE OK); M1–M5 all OBSERVED; soft≈0.003 (3/998); #1095 OPEN
Authority: operator /plan rail-to-full; shrink-only
Canonical: docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19.md
```

**Rule:** this table may only shrink or move rows to CLOSED with proof. Adding a row requires naming the evidence that it is dark/partial.

| id | status | evidence | closure path | proof required |
|---|---|---|---|---|
| DARK-load-by-subject-schedule | CLOSED | [VERIFIED] pin 18a41066d consult instrument_enqueue_skipped_cadence=9; M5 OBSERVED | #1087+#1089 promote | M5 OBSERVED skipped_cadence/instrument_enqueue_skipped>0 |
| DARK-bitemporal-m2-substrate | PARTIAL | schema v2 + CIOEnvelopeIntegrator on :55432; 211 correctness tests; EXPLAIN Index Scan fact_valid_spgist; production :5432 NOT applied | Organic wake schedule + operator shadow cutover grant | OBSERVED unattended write from served |
| DARK-OUTCOME-settlement | PARTIAL→CLOSING | [VERIFIED] hand `--apply` emitted INSUFFICIENT_EVIDENCE; hermetic CONFIRMED via observe; **defect**: static claim_fp froze OUTCOME after first apply (18:00/19:00 timer → null outcome). Fix on #1094: day-bucket claim + suppressed-repeat re-eval | Promote #1094 + unattended timer with observe/expiry | OBSERVED CONFIRMED/REFUTED/EXPIRED from schedule |
| DARK-AgentView-producer | PARTIAL→CLOSING | [VERIFIED] AgentView@v1 @ 21:27:45Z then timer SUPPRESSED_REPEAT. Fix: day-bucketed advisor claim so schedule mints once/UTC-day | Promote #1094 + next day/new-day timer fire | OBSERVED AgentView from served schedule |
| DARK-AGENT_COMMITMENT-producer | PARTIAL→CLOSING | [VERIFIED] cmt_df57fd… then frozen by anti-repeat. Same day-bucket + re-eval fix on #1094 | Promote #1094 + schedule | OBSERVED commitment+settlement from schedule |
| DARK-librarian-index | CLOSED | [VERIFIED] persistent-state + CURRENT `research_source_index.json` ResearchSourceIndex@v1 n_sources=120 (mtime 2026-09-16) | — | file present on served path |
| DARK-hermes_advisory_event_enqueue | KNOWN DARK · PROPOSED RETIRE | AGENTS research table; automatic writer is librarian backlog loop | Operator grant on docs/ops/PROPOSED_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE_2026-09-19.md | RETIRED lane row or wired consumer |
| DARK-KNOWN_DARK-cio_identity_resolver | CLOSED | aec_agent_bus.resolve_payload_agent_refs [CODE] 850b9fda9 | — | removed from KNOWN_DARK; wiring tests PASS |
| DARK-KNOWN_DARK-cio_disposition_identity | CLOSED | aec_command_center_cycle decision_key [CODE] 850b9fda9 | — | removed from KNOWN_DARK; wiring tests PASS |
| PARTIAL-telegram-CIO-stance | PARTIAL | **#1082 MERGED**; served pin 4bafd6f83 includes tip lineage | Observe live hold receipt from CURRENT | live hold receipt from CURRENT |
| PARTIAL-bridge-pin-soak | CLOSED | [VERIFIED] soak_ready=YES streak=4 on tip 4bafd6f83 @ 2026-09-19T20:02:08Z | — | soak_ready=YES |
| PARTIAL-quality-escalate-organic | PARTIAL | code on #1081; flag off | Flag on served + organic thin answer | receipt spilled_to/free climb |
| PARTIAL-soft-share-live-SLO | CLOSED | [VERIFIED] soft_unsupported 3/998 ≈0.003 on pin 0ed980353 @ 2026-09-20T00:05Z; ≤0.15 | — | share≤0.15 |
| PARTIAL-M1-M5 | CLOSED | [VERIFIED] 2026-09-20T00:05:17Z pin 0ed980353: M1–M5 OBSERVED (M2 HELD:NOC; M4 soak+census pass=9 fail=0); soft 3/998≈0.003 | #1094+#1097 promote | all five OBSERVED from served |
| PARTIAL-CIO-Advisor-Narrator-mesh | PARTIAL→CLOSING | [VERIFIED] unattended timer fire LastTrigger=18:00:13 EDT (bitemporal dry_run=false; narrator telegram dry_run); next 19:00 | Live narrator --notify + organic AgentView when not SUPPRESSED_REPEAT | unattended cycle from CURRENT |
| PARTIAL-memory-four-spines | PARTIAL→CLOSING | [VERIFIED] #1090 promoted (pin a628ed0b3); spines load on wake path; organic cycle 18:00 wrote bitemporal + bus | Organic wake provenance aec_spines_loaded on served | wake reads spines from CURRENT |
| PARTIAL-relationship-spine-data | ◆ | no domain data yet | Operator-approved sources only | registry approval rows |
| PARTIAL-narrator-unprompted-telegram | PARTIAL | aec_narrator renders brief; cycle dry-runs; live notify is explicit-flag only | Schedule + --notify under telegram grant + COVERS | unprompted brief delivered |
| DARK-cio-runs-truncated-tail | CLOSED | incomplete last line blocked create_run; wake errors=5 | archive + cio_run harden 7ea5835f9 | repair receipt + test |
| FORBIDDEN-broker | FORBIDDEN | §0/§2 | never | N/A |

## Closed this wave

| id | closed_at | proof |
|---|---|---|
| DARK-cio-runs-truncated-tail | 2026-09-19 | repair + 7ea5835f9 |
| DARK-librarian-index | 2026-09-19 | research_source_index.json n=120 on CURRENT+persistent-state |
| DARK-KNOWN_DARK-cio_identity_resolver | 2026-09-19 | 850b9fda9 AEC bus consumer |
| DARK-KNOWN_DARK-cio_disposition_identity | 2026-09-19 | 850b9fda9 AEC cycle consumer |
| PARTIAL-M1-M5 | 2026-09-19 | #1097 promote 0ed980353; census+soak; soft≈0.003 |


## 2026-09-19T14:01 ET — KNOWN_DARK emptied

- `cio_identity_resolver` → `scripts/lib/aec_agent_bus.resolve_payload_agent_refs`
- `cio_disposition_identity` → `scripts/aec_command_center_cycle` commitment `decision_key`
- `tests/test_identity_memory_module_wiring.py` KNOWN_DARK = set()
- Proof: `pytest tests/test_aec_agent_bus_memory_20260919.py tests/test_identity_memory_module_wiring.py` → 9 passed


## 2026-09-19T18:12 ET — #1081 merged

- Merge commit `93c1f5ea66151b5cde41de72b75cc6e3081a110e`
- Required check cio-hardening PASS 12m34s on head `c8031a7a1`
- release-write remote approval requested `request_id=23da0962fe3d3f7f` (Telegram interrupt)
- #1082/#1083 awaiting cio-hardening on post-merge-main heads

## 2026-09-19T15:15 ET — merges landed; promote blocked

- #1081/`93c1f5ea6`, #1082/`db114592b`, #1083/`7bdbcc760`, #1084 docs/`d33f28ee8` on `origin/main`
- Served CURRENT still `99c79ec17…` — promote blocked on release-write request `a981abde177d13da` PENDING
- Soft-share FAIL 0.22 (stored risk_agent confidence rows); M1/M2/M5 NOT_OBSERVED
- No production bitemporal apply

## 2026-09-19T16:13 ET — post-promote soak + #1087 M2

- Served pin `4bafd6f83-main-exact-phase2-20260919-153247`
- soak_ready=YES streak=4; soft_unsupported_share=0.002
- M1 OBSERVED (field_changes next_eligible_at, cc_narrative via wake_dispatcher_log)
- #1087 OPEN `19d8264e4` — critique→InstrumentRecord writeback + instrument_record_due selection + consult instrument_enqueue stamp
- release-write remote request `fadb526f2ce47469` PENDING (promote after #1087 merge)
- No production bitemporal apply on :5432

## 2026-09-19T17:01 ET — M3 bar + #1087 merge

- #1087 MERGED `6d577026f`; tip not yet promoted (release-write pending)
- M3 reporter now requires `turn_changed_decision` + differing with/without `next_research_question` → OBSERVED on HELD:SCHD @ 2026-09-08
- M5 was OBSERVED @ 20:55Z consult then CANDIDATE @ 21:00Z (cycle variance) — still PARTIAL until stable

## 2026-09-19T17:35 ET — promote 18a41066d + L3 author registry

- PROMOTE OK tip `18a41066d` (merge #1089) → `18a41066d-main-exact-phase2-20260919-171754`; telegram cwd matches
- M1/M3/M5 OBSERVED; soft_unsupported_share=0.002 SLO PASS; soak streak=4
- M2 still NOT_OBSERVED: `data/cio/wake_critique_question.jsonl` absent; persistent_wake log shows `llm_lane_unregistered process_id=l3_judgment_author` and DeepSeek `HTTP_402` on curation/author path
- Fix landed on branch: register `l3_judgment_author` in `config/llm_process_registry.json` + `sync_cio_process_caps.py`; DB sync applied (cost=0.25 soft=48). Does not invent WAKE_L3 grant; does not clear provider 402

## 2026-09-19T17:40 ET — AEC apply + bitemporal apply flag

- Dry-run then `--apply` AEC cycle (advisory): bus events cio/advisor/narrator; spines strategic+learning written; AgentView + AGENT_COMMITMENT + CommitmentOutcome emitted
- Found defect: `integrate_wake_envelope(..., apply=False)` hardcoded in cycle even when `--apply` — fixed to `apply=apply` (still isolated :55432; prod :5432 refused)
- Narrator Telegram remains explicit-flag only (`notify_executive_brief(apply=False)` from cycle) — PARTIAL-narrator-unprompted-telegram unchanged

## 2026-09-19T17:45 ET — wake loads AEC spines

- `persistent_agent_wake.load_aec_spines_for_wake` + context/provenance stamp (fail-soft)
- Hermetic tests in `test_aec_agent_bus_memory_20260919.py`

## 2026-09-19T17:34 ET — AEC cycle scheduled

- Installed `tradeai-aec-command-center-cycle.{service,timer}` (hourly) under cron grant; lane_registry row ACTIVE; output_signal `data/cio/aec_agent_bus.jsonl`
- Dry-run quoted then `systemctl --user enable --now`; oneshot `start` exit 0 (advisory apply; narrator telegram still dry_run)
- Next natural fire ~18:00 ET

## 2026-09-19T18:10 ET — post-#1090 organic AEC + M1 hit-retention

- [VERIFIED] `tradeai-aec-command-center-cycle.timer` LastTrigger=18:00:13 EDT; unattended cycle finished with bitemporal `dry_run=false`, narrator `telegram: dry_run`; next 19:00 EDT.
- [VERIFIED] M1 NOT_OBSERVED root cause: hit FIFO dropped `persisted=True` rows (HELD:BAH 15:46 ET `next_eligible_at,cc_narrative`) under research-only flood; dispatcher log still held proof.
- Fix in flight: `trim_hits` prefers persist evidence; reporter recovers M1 from wake_dispatcher_log when hits lost the row.
- M2 still blocked: cron lacks `WAKE_L3_*` (see `docs/ops/PROPOSED_WAKE_L3_CRON_FLAGS_2026-09-19.md`); DeepSeek 402 remains provider/operator.
- PARTIAL-CIO-Advisor-Narrator-mesh / PARTIAL-memory-four-spines: unattended schedule OBSERVED at 18:00; narrator live telegram and relationship sources still operator.

## 2026-09-19T18:15 ET — narrator notify env + WAKE_L3 cron

- Cron: WAKE_L3_* on wake `*/5` (after `cd &&`).
- Code: `AEC_NARRATOR_NOTIFY` gates cycle telegram; unit sets `=1` (needs #1094 promote for served code).
- release-write requested (Telegram) for post-#1094 promote.

## 2026-09-19T18:20 ET — post-1090 remeasure + AEC anti-repeat fix

- [VERIFIED] pin a628ed0b3… server/telegram/health cwd match; no release-write → no re-promote.
- [VERIFIED] AEC timer 18:00:13 EDT; bus last 22:00:13Z; advisor SUPPRESSED_REPEAT (null view/commitment/outcome).
- [VERIFIED] M1 NOT_OBSERVED: post-pin wakes `daily_cap_reached` (DAILY_CAP=5) / cognition_noop; historical persist hits=0 in artifact; hub lacks #1094 log-alone recover.
- [VERIFIED] soft_unsupported_share=0.002; M3/M5 OBSERVED; M4 PARTIAL soak=4; M2 NOT_OBSERVED.
- Code: day-bucket advisor claim + suppressed-repeat commitment re-eval (`aec_command_center_cycle.py`); hermetic 12 passed.

## 2026-09-19T19:26 ET — #1094 promoted; M1+M2 OBSERVED

- [VERIFIED] #1094 MERGED `2258b16c6`; PROMOTE OK pin `2258b16c6-main-exact-phase2-20260919-192238`; server+telegram cwd match; health ok.
- [VERIFIED] M1 OBSERVED via wake_dispatcher_log recover (HELD:BAH 15:46Z field_changes next_eligible_at,cc_narrative).
- [VERIFIED] M2 OBSERVED writeback HELD:NOC critique accept crt_926c90933bff… (`l3_judged` + `l3_critique_question_writeback`); wake_critique_question.jsonl present on hub.
- M3/M5 OBSERVED; M4 PARTIAL (soak=4; full operator-number census not run); soft_unsupported 2/995 (~0.002).
- #1095 quality-escalate host-file arm OPEN tip e52fd4018 (cio-hardening pending after main sync).
- Remaining PARTIAL: M4 census, narrator live telegram, quality-escalate organic receipt, relationship sources, bitemporal :5432, hermes RETIRE, organic AEC CONFIRMED/REFUTED on day-bucket schedule.

## 2026-09-19T20:05 ET — M1–M5 OBSERVED on served

- #1097 MERGED `0ed980353` → PREPARE+PROMOTE OK pin `0ed980353-main-exact-phase2-20260919-200406`
- [VERIFIED] `report_maturity_bar_m1_m5.py` from served: M1–M5 OBSERVED; census pass=9 warn=2 fail=0
- [VERIFIED] soft_unsupported 3/998 ≈ 0.003 (≤0.15)
- #1096 ledger MERGED earlier; #1095 quality-escalate still OPEN (CI after sync)
- Goal remains open: remaining PARTIAL/DARK (quality-escalate host arm, narrator organic, relationship, bitemporal :5432, hermes RETIRE, AEC CONFIRMED/REFUTED)
