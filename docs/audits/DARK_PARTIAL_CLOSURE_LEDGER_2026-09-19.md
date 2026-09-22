# DARK / PARTIAL / UNWIRED closure ledger

```
Status: ACTIVE
as_of: 2026-09-22T02:38:00-04:00
Measured at: LIVE-cio-stance-governance UNATTENDED_ORGANIC_OBSERVED (organic=1780; +1776 since Mon 06:00 ET); M1–M5 OBSERVED; soft_share=0.098; §17 DEFERRED parks unchanged
Authority: Tue early observe 2026-09-22 ~06:35 ET slot; AGENTS.md §8 honesty (forced/mechanical ≠ unattended)
Canonical: docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19.md
See also: docs/ops/LIVE_CIO_STANCE_GOVERNANCE_2026-09-21.md
```

**Rule:** this table may only shrink or move rows to CLOSED with proof. Adding a row requires naming the evidence that it is dark/partial.

| id | status | evidence | closure path | proof required |
|---|---|---|---|---|
| DARK-load-by-subject-schedule | CLOSED | [VERIFIED] pin 18a41066d consult instrument_enqueue_skipped_cadence=9; M5 OBSERVED | #1087+#1089 promote | M5 OBSERVED skipped_cadence/instrument_enqueue_skipped>0 |
| DARK-bitemporal-m2-substrate | §17 **DEFERRED** · staging ALIGNED | staging `:55432` audited; packaging auto-heal landed (`init_bitemporal_db.sh` / `bitemporal_schema_heal`); prod `:5432` still blocked | Operator **DEFER**; report + heal docs | later APPROVE_* + prod apply |
| DARK-OUTCOME-settlement | CLOSED | [VERIFIED] AEC 02:00:13 EDT on pin **8c12ea757**: learning `commitment_outcome` outcome=EXPIRED commitment_id=`cmt_fb32f783…` via=`prior_open_settle`; cycle Result=success exit 0; narrator telegram=accepted | — | OBSERVED EXPIRED from schedule |
| DARK-AgentView-producer | CLOSED | [VERIFIED] unattended 20:00:15 EDT AgentView@v1 (PORTFOLIO / day-bucket claim) from tradeai-aec-command-center-cycle.timer | — | OBSERVED AgentView from served schedule |
| DARK-AGENT_COMMITMENT-producer | CLOSED | [VERIFIED] unattended 20:00:15 EDT AGENT_COMMITMENT@v1 cmt_7f86ca… + CommitmentOutcome@v1 | — | OBSERVED commitment+settlement from schedule |
| DARK-librarian-index | CLOSED | [VERIFIED] persistent-state + CURRENT `research_source_index.json` ResearchSourceIndex@v1 n_sources=120 (mtime 2026-09-16) | — | file present on served path |
| DARK-hermes_advisory_event_enqueue | §17 **DEFERRED** · PROPOSED RETIRE available | AGENTS research table; automatic writer is librarian backlog loop; no caller | Operator **DEFER** 2026-09-20 on docs/ops/PROPOSED_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE_2026-09-19.md | later APPROVE_RETIRE_* or WIRE |
| DARK-KNOWN_DARK-cio_identity_resolver | CLOSED | aec_agent_bus.resolve_payload_agent_refs [CODE] 850b9fda9 | — | removed from KNOWN_DARK; wiring tests PASS |
| DARK-KNOWN_DARK-cio_disposition_identity | CLOSED | aec_command_center_cycle decision_key [CODE] 850b9fda9 | — | removed from KNOWN_DARK; wiring tests PASS |
| LIVE-cio-stance-governance (was PARTIAL-telegram-CIO-stance) | **CLOSED · UNATTENDED_ORGANIC_OBSERVED** | Goal stays closed (no reopen). Honesty upgrade: Mon 2026-09-21 market-hours producers wrote **1776 NEW** hold rows after Mon 06:00 ET (`source=check_investment_send`; callers `send_telegram_proposal_alert`=1748 + `screener_go_alerts`=28). `[VERIFIED]` Tue early observe 2026-09-22T06:36:16Z: organic=**1780** non_organic=2 total=1782 exit=0; latest DFAU `as_of=2026-09-21T20:58:08Z` caller=`send_telegram_proposal_alert` held_reason=`cio_stance_conflict`; holds mtime 2026-09-21T16:58:08-04:00. Prior organic=4 (AEMD/LSTA) were FORCE-mechanical / Sun hand-replay — not unattended. Host timers: early LastTrigger=Mon 06:35:11; main LastTrigger=Mon 09:05:43 (both still organic=4); Tue early Next=06:35:10 (this agent slot). Remasure: M1–M5 all OBSERVED exit 0 pin `58dac0884-…000413`; soft_unsupported_share=**0.098** (160/1636) PASS ≤0.15. | docs/ops/LIVE_CIO_STANCE_GOVERNANCE_2026-09-21.md; report_organic_stance_hold.py | keep observing; MBI_BEHAVIOR=0 inviolable |
| PARTIAL-bridge-pin-soak | CLOSED | [VERIFIED] soak_ready=YES streak=5 @ 2026-09-20T04:44:54Z post-#1110 promote; pins_match | — | soak_ready=YES |
| PARTIAL-quality-escalate-organic | **OBSERVED (unattended)** | [VERIFIED] Sun 08:00 ET weekly cron: ARKQ+NEE `requester=data_gap_resolver` `vector=quality_escalate` `provider=searxng` `outcome=partial` started 2026-09-20T12:00:07Z/12:00:11Z; weekly.log Chain resolve 2/2. Hand proof at 10:30Z was precursor. | — | unattended same stamps |
| PARTIAL-soft-share-live-SLO | CLOSED | [VERIFIED] soft_unsupported 3/998≈0.003; #1087 report filter | — | share≤0.15 |
| PARTIAL-M1-M5 | CLOSED | [VERIFIED] post-promote 2026-09-20T04:44:54Z pin 8090bf675: M1–M5 OBSERVED under prior bar (fail=0); operator remasure 2026-09-20 keeps M4 PARTIAL on census WARN — see PARTIAL-M4-census-warn | promote #1110 tip | all five OBSERVED |
| PARTIAL-M4-census-warn | **CLOSED** | [VERIFIED] PROMOTE OK `6a78d41cc-main-exact-phase2-20260920-094308`; census as_of=2026-09-20T13:44:45Z **pass=11 warn=0 fail=0**; M4 OBSERVED (AI Analyst Fresh under 72h) | — | warn=0 → M4 OBSERVED |

| PARTIAL-CIO-Advisor-Narrator-mesh | CLOSED | [VERIFIED] unattended 20:00 EDT: AgentView+commitment+narrator telegram=accepted; spines strategic=2 learning=5; bitemporal dry_run=false | — | unattended cycle from CURRENT |
| PARTIAL-memory-four-spines | CLOSED | [VERIFIED] organic `aec_wake_spine_receipts.jsonl` as_of=2026-09-20T01:04:31Z subject=PORTFOLIO policy_decision=aec_spines_loaded counts strategic=2 learning=5; wake consult 01:05:09Z | #1099 promote | wake receipt aec_spines_loaded |
| PARTIAL-relationship-spine-data | §17 **DEFERRED** · ◆ | no domain data; spine slot exists | Operator **DEFER** 2026-09-20 on docs/ops/PROPOSED_RELATIONSHIP_SPINE_SOURCES_2026-09-19.md (§7A/§17) | later APPROVE_RELATIONSHIP_* + registry rows |
| PARTIAL-narrator-unprompted-telegram | CLOSED | [VERIFIED] unattended 20:00:15 EDT narrator_notify notify_attempted=true telegram=accepted (AEC_NARRATOR_NOTIFY on unit) | — | unprompted brief delivered |
| DARK-cio-runs-truncated-tail | CLOSED | incomplete last line blocked create_run; wake errors=5 | archive + cio_run harden 7ea5835f9 | repair receipt + test |
| FORBIDDEN-broker | FORBIDDEN | §0/§2 | never | N/A |

## Closed this wave

| id | closed_at | proof |
|---|---|---|
| LIVE-cio-stance-governance | 2026-09-22T02:38 ET | **UNATTENDED_ORGANIC_OBSERVED** honesty upgrade (organic=1780; +1776 Mon daytime); goal not reopened |
| DARK-cio-runs-truncated-tail | 2026-09-19 | repair + 7ea5835f9 |
| DARK-librarian-index | 2026-09-19 | research_source_index.json n=120 on CURRENT+persistent-state |
| DARK-KNOWN_DARK-cio_identity_resolver | 2026-09-19 | 850b9fda9 AEC bus consumer |
| DARK-KNOWN_DARK-cio_disposition_identity | 2026-09-19 | 850b9fda9 AEC cycle consumer |
| PARTIAL-M1-M5 | 2026-09-19 | #1097/#1095 promote; census+soak |
| DARK-AgentView-producer | 2026-09-19 | AEC timer 20:00 AgentView@v1 |
| DARK-AGENT_COMMITMENT-producer | 2026-09-19 | AEC timer 20:00 cmt_7f86ca… |
| PARTIAL-CIO-Advisor-Narrator-mesh | 2026-09-19 | AEC timer 20:00 mesh+telegram |
| PARTIAL-narrator-unprompted-telegram | 2026-09-19 | narrator_notify telegram=accepted |
| PARTIAL-memory-four-spines | 2026-09-20 | aec_wake_spine_receipts.jsonl 01:04:31Z aec_spines_loaded |
| DARK-OUTCOME-settlement | 2026-09-20 | AEC 02:00:13 EDT EXPIRED cmt_fb32f783 prior_open_settle on 8c12ea757 |

---

## Wave log

Timestamped wave entries live in **`DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19_LOG.md`**.

**Append new wave sections there, not here.** That file carries `merge=union` in
`.gitattributes`, so concurrent sessions appending at the same time merge cleanly instead
of conflicting. This file stays hand-merged on purpose: its table is shrink-only and a
mechanical merge could silently reopen a row someone closed with proof.
