Status:      ACTIVE
as_of:       2026-09-09
Measured at: evidence-dated re-reading (2026-09-01/02 audit + ops corpus, 2026-09-08/09 canary closeouts) — NOT a fresh full live census; re-measure volatile nodes before quoting
Canonical repo path: docs/architecture/CIO_ASIS_VS_SPEC_2026-09-09.md
Authority:   dated reading of LIVE / PARTIAL / UNWIRED / DARK — not a behaviour spec
Supersedes:  docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md (readings of nodes that moved)
Superseded-by: docs/architecture/CIO_ASIS_VS_SPEC_2026-09-09-ceiling.md (live-ceiling re-measure)
See also:    docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY_2026-09-09.md
             docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY.md (target, unchanged)
             docs/architecture/CIO_ASIS_VS_FUTURE_GAP_2026-09-09.md
             AGENTS.md §13.4 §15 §19

# CIO Agent — AS-IS vs SPEC (2026-09-09)

**Snapshot as_of 2026-09-09.** This re-measures the 2026-08-30 reading using the
audit corpus that landed between the two dates. It is **not** a fresh full live
census of every pipeline node; it is a dated refresh of the nodes that have
evidence. Nodes with no post-08-30 evidence are marked `UNKNOWN (not re-measured)`
and must not be quoted as current.

```
LEGEND
  █  LIVE       runs on schedule, produces durable output, verified at runtime
  ▓  PARTIAL    runs, but incomplete, degraded, or its consumer is unproven
  ░  UNWIRED    the code exists and is correct; nothing calls it or consumes it
  ✗  DARK       never executed, or produces nothing, in recorded history
  M5_CANDIDATE  scheduled + unattended proven; durability clause not yet OBSERVED
```

---

## Pin / SHA context (authoritative)

| Field | Value |
|---|---|
| Served CURRENT release | `340aaf831-main-exact-phase2-20260908-185931` |
| Served BUILD_SHA | `340aaf831d0f982afb06e318876b50f05ca069cc` (PR #926 promoted) |
| `origin/main` | `441615a4a9243223a74d671250165bec4f95c01b` (post PR #927 docs merge; **not** promoted — docs-only) |
| Prior Stage-2 pin | `aaa9115cbc…` / `…171709` (historical) |
| Measurement corpus | `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md`, `CIO_OUTCOME_EDGE_CENSUS_2026-09-01.md`, `docs/ops/CIO_WAKE_LIVE_DECIDE_2026-09-01.md`, `CIO_M5_FIRST_FIRE_2026-09-01.md`, `CIO_OVERNIGHT_AUTONOMY_SCOREBOARD_2026-09-02.md`, m2-canary campaign closeouts |

Note: `origin/main` is ahead of the served pin by **docs-only** work (PR #927 operator
review package + an unmerged ops mirror branch). The runtime behaviour described below
is that of the served pin, not of the docs commits on top of it.

---

```
                        REAL TRADE AI EVENT
                                  │
          ┌───────────────────────┼────────────────────────┐
          │                       │                        │
    █ Security/Ticker      █ Sector/Industry        ▓ Catalyst
                                                     family completion ~1.49%
          └───────────────────────┼────────────────────────┘   (fix in code, not
                                  │                            served data)
                                  ▼
                       ✗ OPERATOR  (also an event)
              zero operator_turns on any record —
              the turn store does not exist in any root
                                  │
                                  ▼
                     ✗ S0_OPERATOR_CONVERSE
                       loop with no input
                                  │
                                  ▼
                    █ CANONICAL ENTITY / IDENTITY
                                  │
                                  ▼
                         █ MATERIALITY   S1–S7
                                  │
                                  ▼
                         ▓ GRAPH IMPACT
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│              ▓ INSTRUMENT RECORD @v1   (persistent unit)            │
│   █ subject_key · thesis · cc_narrative                             │
│   █ research[] / artifact_ids                                       │
│   ✗ operator_turns[]          zero on all 40 subjects               │
│   ▓ lessons[]                 344 candidates — 343 research-fed,    │
│                               exactly 1 outcome-derived             │
│   █ next_eligible_at · notify_priority                              │
│   M5_CANDIDATE load-by-subject on scheduled wake                    │
│        pre-claim consult wired; decide_after_load live;             │
│        days-earlier honour NOT yet OBSERVED                          │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                        █ RESEARCH GAP
                    (gap vs record; gap-vs-priors still absent)
                                  │
                                  ▼
                ┌──── FREE-FIRST RESEARCH ─────┐
    █ Persistent cognition          ▓ Hermes / RAG / FRED
      lessons · thesis              ░ librarian: index file STILL ABSENT
      █ CASE_SUMMARY (344)          (law governs nothing)
                └──────────────┬───────────────┘
                               │
                    ▓ residual web research
                      lane live · engine pool DEGRADED (quantified)
                      search_health.json never written
                               │
                               ▼
              ✗ LLM only if still unresolved
                 lane still DARK — no model called;
                 phantom MODEL_CALL_RECORDED fixed 08-28;
                 LLM_GLOBAL_DAILY_USD_CAP=0.50 now set
                               │
                               ▼
                    ▓ SPECIALIST DISPATCHER
                      formal type now exists · N=100 gate STILL FAILS
                               │
                               ▼
                  ▓ SpecialistArtifact@v1 (was -lite)
                    formal schema + validate(); 2 artifacts, both orphaned
                               │
                               ▼
                   ░ CIOCouncilSynthesis@v1
                     deterministic · ONE stale artifact (08-26)
                     caller not in crontab · DISPUTED=0 (unfalsifiable)
                               │
                               ▼
              ▓ WRITE BACK TO INSTRUMENT RECORD
                cc_narrative · next_question · priority
                M5_CANDIDATE: cognition persist fires on scheduled wake
                BehaviorWriteRefused rail intact (never exercised in prod)
                               │
                               ▼
                   █ CIOOperatorProduct@v1
                     DETERMINISTIC_PRODUCT · $0.00
                     ▓ field provenance/as_of gaps remain
                               │
                               ▼
                    ▓ NOTIFICATION POLICY
       ┌───────────────────────┼───────────────────────┐
   ✗ IMMEDIATE            █ DIGEST         ✗ COMMAND_CENTER_ONLY
       │  (0 all-time)   (38 all-time)      (0 all-time)
       └───────────────────────┼───────────────────────┘
                       █ or SUPPRESSED (4,611 all-time)
                               │
                               ▼
               ▓ DELIVERY RECEIPT / DEDUPE
                 DEDUPE lane █ LIVE · DeliveryReceipt@v1 ░ (n=1 suppressed)
                               │
                               ▼
                  ▓ OutcomeCheckpoint@v1
                    1,125 ids · 158 RESOLVED · 6 PENDING_DATA (named)
                    871 SCHEDULED with due_at=null (unschedulable dark mass)
                    plan_id binding: 0 of 1,125
                               │
                               ▼
                          ▓ OUTCOME
                            edge no longer dark — settles hourly
                               │
                               ▼
┌─────────┴──────────┐
│                    │
▓ from outcome  (n=1) ▓ from research  ← 343 lessons
│                    │
└─────────┬──────────┘
          ▼
      ▓ LESSON / HYPOTHESIS
        learns mostly from WHAT IT READ,
        one lesson from WHAT HAPPENED
          ▼
   ░ REVIEW_READY  (next wake loads record — M5_CANDIDATE)
          ▼
  █ MBI_BEHAVIOR  = 0   enforced (code-confirmed, never exercised)
  ▓ MBI_COGNITION = 1   a constant, not a gate; inconsistent 0 in one module

┌─────────────────────────────────────────────────────────────────────┐
│              █ CanonicalStoreRegistry@v1                           │
│                █ GOOD_PERSISTENT_ROOT (PSTATE)                     │
│                ▓ 6 of 34 declared stores missing in every root     │
│                ▓ 315 divergent files (283 data + 32 logs)          │
│                ▓ 779 per-release stranded copies (548 distinct)    │
│                ✗ agent_view/commitment/prior/score ids: 0 produced  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Movers since 2026-08-30 (headline)

**Advanced:**

| node | 08-30 | 09-01/09 | evidence |
|---|---|---|---|
| OUTCOME edge / `OutcomeCheckpoint@v1` | ✗ DARK | **▓ PARTIAL** | 1,125 ids; 158 RESOLVED; hourly settler wired (cron `:20`) |
| Lesson provenance | ▓ all research | **▓ +1 outcome** | `OUTCOME_DERIVED` n=1 of 344 (`lesson_provenance`) |
| `SpecialistArtifact` | ░ no type | **▓ formal type** | `cio_specialist_artifact.py` + `validate()`; gate still FAILS |
| `MODEL_CALL_RECORDED` | ✗ phantom | **✗ but receipt fixed** | last receipt 08-28; cap `=0.50` set |
| load-by-subject | ░ UNWIRED | **M5_CANDIDATE** | scheduled `decide_after_load` + cognition persist (09-01 first fire) |

**Regressed (or 08-30 reading too generous):**

| node | 08-30 | 09-01/09 | evidence |
|---|---|---|---|
| `CIOCouncilSynthesis@v1` | █ LIVE | **░ UNWIRED** | one stale artifact (08-26); caller not in crontab |
| NOTIFICATION — IMMEDIATE / CC_ONLY | █ (all four) | **✗ 0 all-time** | 2,046 scanner wakes, 0 IMMEDIATE / 0 CC_ONLY |
| `DeliveryReceipt@v1` | █ | **░ UNWIRED** | n=1 (SUPPRESSED); writer not in cron |
| OPERATOR turn / `S0` | ▓ | **✗ DARK** | 0 turns on 40 subjects; turn store absent |

---

## Node census table (one row per domain)

| # | node | 08-30 | 09-09 | note |
|---|---|---|---|---|
| 1 | OUTCOME edge | ✗ | **▓** | settles; 871 unschedulable `due_at=null` remains |
| 2 | LESSON / HYPOTHESIS | ▓ | **▓** | 343 research / 1 outcome |
| 3 | `AgentView` / `AGENT_COMMITMENT` | ✗ | **✗** | zero instances; no write site |
| 4 | Librarian index | ░ | **░** | `research_source_index.json` absent all roots |
| 5 | `SpecialistArtifact` | ░ | **▓** | formal type; gate FAILS |
| 6 | LLM lane | ✗ | **✗** | dark; phantom receipt fixed |
| 7 | `CIOCouncilSynthesis` | █ | **░** | 1 stale artifact, unscheduled caller |
| 8 | NOTIFICATION SUPPRESSED / DIGEST | █ | **█** | 4,611 / 38 all-time |
| 8b | NOTIFICATION IMMEDIATE / CC_ONLY | █ | **✗** | 0 / 0 all-time |
| 8d | `NotificationPolicy@v1` module | █ | **░** | not on live delivery path |
| 9 | `DeliveryReceipt@v1` | █ | **░** | n=1 suppressed; DEDUPE half █ |
| 10 | `CognitionNoOp` rail | ▓ | **▓** | code-true, unobserved; `MBI_BEHAVIOR` █ |
| 11 | `CanonicalStoreRegistry` | █ | **█** | 6/34 missing; 315 divergent; 779 stranded |
| 12 | OPERATOR turn / S0 | ▓ | **✗** | turn store absent |
| 13 | Catalyst completion | ▓ | **▓** | 1.49%; fix in code, not served data |
| 14 | Residual web engine pool | ▓ | **▓** | CAPTCHA-degraded, quantified; health file never written |
| 15 | Every wake loads record | ░ | **M5_CANDIDATE** | not OBSERVED (durability clause) |
| 16 | Commitments / priors / scoring | ✗ | **✗** | specified, no producer; priors absent |

---

## Maturity bar (§15) — re-measured (2026-09-02, latest named reading)

| # | proof | verdict |
|---|---|---|
| M1 Research | research changes a named field end-to-end under schedule | **NOT_OBSERVED** |
| M2 Advice | critique → `next_research_question` on scheduled council path | **NOT_OBSERVED** |
| M3 Feedback | `operator_turns` populated | **NOT_OBSERVED** (0 turns) |
| M4 Consistency | one cash number per surface | **NOT_OBSERVED** (failure case: multiple cash totals) |
| M5 Persistence | days-earlier disposition honoured unattended | **M5_CANDIDATE** (not OBSERVED) |

---

## Post-08-30 additions that belong in AS-IS (delivery authority / control plane)

### Comms gateway / m2-canary-20260907 — IN PROGRESS (no M2 PASS)

- Stage-2 (activate): **COMPLETE**. Stage-3 organic soak: **ORGANIC_ONLY, in progress**
  (`consecutive_known_trigger_wakes=1`, organic research/commitment not yet seen).
  Stage-4: scaffold only. **M2 / M3 / M4 PASS not claimed.**
- PR #926 (`delivery_owner` stamp into `provider_coordinates` on settle) **merged + promoted**
  onto the served pin; controlled re-proof **SETTLED** pmid `51022`.
- Campaign root: `/home/johnclaw/trade-ai-campaigns/m2-canary-20260907/`
  (master index `evidence/OPERATOR_REVIEW_PACKAGE_20260908T2307Z.md`).

### Guard scopes / operator control plane — LIVE

- `bin/guard` scopes (git-push, release-write, service, telegram, cron, db-write,
  destructive, secret) gate consequential agent actions; remote Telegram approve/deny via
  `scripts/lib/guard_remote_approval.py` (sudo/destructive/file-delete/guard-config/frozen-v2
  remote-forbidden).
- This is operator control, **not** FUTURE self-repair.

### Drive sync exclusions — LIVE filter + incident (honesty)

- `sync-docs-to-drive.sh` `is_runtime_dump_excluded` drops year-in-path dirs
  (e.g. `docs/campaigns/m2-canary-20260907/**`) — dated campaign trees do not mirror to Drive.
- 2026-09-09: a mistaken minimal-`TRADEAI_DOCS_SRC` sync ran cleanup and trashed ~128 Drive files;
  a full-tree restore re-uploaded 503 (failed=0). Undated ops mirror
  `docs/ops/m2_canary_operator_review/` is the Drive-visible copy (core files; nested year dirs
  still filtered).
- Proposed (not ACTIVE) AGENTS amendment: `AGENTS_MD_AMENDMENT_DRIVE_DRY_RUN_PROPOSED.md`.

### Holdings lock / dual-write — implemented, splits residual

- `scripts/lib/holdings_write_lock.py` (#924) shared across repricer/Alpaca/Schwab writers.
- Systemic dual-write: `legacy_read_only:false` + 266 PROJ-rooted vs 45 CURRENT-rooted cron lines;
  315 divergent files (283 data + 32 logs); 6 registry stores missing; 779 per-release stranded
  copies across 302 release trees. Operator-only decisions (§2.7 dark-contracts) not acted.

### PR #927 docs package — merged, not promoted

- Operator review package under `docs/campaigns/m2-canary-20260907/operator_review_20260908/`
  merged to `origin/main` `441615a4a` (docs-only). Ops mirror branch unpushed at last check.

---

## What the spec says and the system does not do (updated)

| Spec node | Reality (09-09) |
|---|---|
| `LLM only if still unresolved AND materially useful` | No model is called on the CIO path. Phantom receipt fixed; lane dark. |
| `lessons[] cognition only → next question` | 344 lessons; 343 research-derived, 1 outcome-derived. No prior moved. |
| `load-by-subject on every wake` | Now wired + scheduled (`M5_CANDIDATE`); days-earlier honour not OBSERVED. |
| `librarian: grade / stale-out` | Law tested; index file still absent; governs nothing. |
| `commitment with falsifier` | Type specified; zero instances; lesson-bind forbids commitment-as-policy. |
| `Telegram reply is the next S0` | No turn store; zero operator turns. There is nothing to consume. |
| `NotificationPolicy routes IMMEDIATE/DIGEST/CC_ONLY` | Router imported only by unscheduled report scripts; producer never calls it. |
| `OUTCOME` | No longer dark — settles hourly; 871 rows permanently unschedulable (`due_at=null`). |

## The one-sentence version (re-measured)

**The nervous system is built and running; the cortex has fired once and no more.** The outcome
edge settled 158 checkpoints and produced exactly one outcome-derived lesson; the load-by-subject
wake reached `M5_CANDIDATE`. Everything that would constitute a view of its own — a model call, a
staked commitment, a moved prior, an agent-raised question — remains dark, unwired, or barred.

## The count that matters (unchallenged)

**Agent-originated fields reaching any operator surface: zero.** The one genuinely non-deterministic
sentence per day is still produced by an external session reading a packet this system composes —
outside every provenance, gating, and lineage mechanism described here.

## What not to quote without re-measure

- Wake honour (M5 OBSERVED vs CANDIDATE) — post-09-04 deferral window UNKNOWN.
- Hourly outcome settler volume (`resolved N`) — store grows ~3 records/8 min.
- Engine-pool health — CAPTCHA suspensions move hourly.
- `origin/main` vs served pin — docs-only commits sit ahead of the promoted pin.
- M1–M4 — last named reading 2026-09-02; not re-lit after.

---

## SILK

**Not defined anywhere on this host** (code, docs, campaigns, or the Aug-30 pair). No acronym,
module, campaign, or seal named "SILK" was found. If SILK is an operator name for a cluster of the
post-08-30 work above (comms gateway, guard, Drive honesty, holdings lock), that mapping is external
to the machine and is **not invented here**. A dedicated SILK section will be added when the operator
defines it.
