Status:      ACTIVE
as_of:       2026-09-09
Measured at: evidence-dated (2026-09-01/02 audit + ops corpus; 2026-09-08/09 canary closeouts)
Canonical repo path: docs/architecture/CIO_ASIS_VS_FUTURE_GAP_2026-09-09.md
Authority:   gap analysis — AS-IS (2026-09-09) vs FUTURE (2026-09-09 target); not a behaviour spec
Supersedes:  none
Superseded-by: docs/architecture/CIO_ASIS_VS_FUTURE_GAP_2026-09-09-ceiling.md (live-ceiling delta)
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-09-09.md
             docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY_2026-09-09.md
             AGENTS.md §13.4 §15 §19

# CIO Agent — GAP analysis: AS-IS vs FUTURE (2026-09-09)

The gap is between **what runs today** (AS-IS 2026-09-09) and **full maturity**
(FUTURE 2026-09-09). Grouped by the four maturity additions and the build order, then by
the structural defects that block all of them.

---

## 1. The four additions — gap at a glance

| # | FUTURE capability | AS-IS today | Gap |
|---|---|---|---|
| ① Judgment | `AgentView@v1`, gated/costed, critique-graded | LLM lane DARK; phantom receipt fixed; cap set but lane off | **Full gap** — a cost decision away, but no producer, no view type written |
| ② Commitment | `AGENT_COMMITMENT@v1` + falsifier + horizon + bound checkpoint | Type specified; **zero instances**; `cio_lesson_bind` forbids commitment-as-policy | **Full gap** — no write site exists |
| ③ Scoring | CONFIRMED/REFUTED/EXPIRED → move priors; calibration | Priors absent; `OUTCOME_DERIVED` lesson n=1/344; no prior store | **Full gap** — outcome edge is PARTIAL, but nothing scores into a prior |
| ④ Self-repair | detect → PR → effect-verify → CI fails new dark | Guard scopes (operator control) + audits exist; not a continuous detect-PR-verify loop | **Full gap** — the audits are measurement, not repair |

**Bottom line:** the cortex (①–④) is still effectively **dark or specified-with-no-producer**.
The nervous system advanced — outcome settlement and the scheduled wake load — but the four
things that make it "self-thinking" have not landed.

---

## 2. Build-order gap (the six steps)

| step | target | status today | gap |
|---|---|---|---|
| 1 | every wake loads the record first | **M5_CANDIDATE** | durability proof missing; writer stamp wrong (#836) |
| 2 | outcomes resolve | **PARTIAL** (158 RESOLVED, hourly settler) | 871 rows `due_at=null` unschedulable; 0 plan-bound; PENDING apply unarmed |
| 3 | judgment layer | DARK | lane off; no `AgentView` producer |
| 4 | commitments + falsifiers | specified, no producer | no write site; organic commitment=0 in canary |
| 5 | scoring moves priors | absent | no priors store; n=1 outcome lesson |
| 6 | self-repair | not FUTURE-shaped | no detect-PR-effect loop |

---

## 3. Structural defects blocking the whole target

These are the recurring shapes the audits found. Each one is a gap in its own right, and each
must be closed before the corresponding maturity step can be trusted.

| defect | evidence | blocks |
|---|---|---|
| **Correct module, unscheduled caller** | council synthesis (1 stale artifact), `NotificationPolicy@v1`, `DeliveryReceipt@v1`, `build_catalyst_graph` — all "not in crontab" | judgment (③→surface), notification, outcome graph |
| **Dual-write / split stores** | 315 divergent files (283 data + 32 logs), 6/34 registry stores missing, 779 per-release stranded copies, `legacy_read_only:false` | self-repair (④) — no single authoritative store to trust |
| **Zero operator turns** | 0 `operator_turns` on 40 subjects; turn store absent in every root | ② commitment and the whole two-way loop; M3 |
| **Silent send gate** | `_interdicted()` returns with no log line — never observed firing, unobservable by construction | self-repair verify-by-effect; delivery honesty |
| **Librarian index absent** | `research_source_index.json` missing in all three roots; `STALE_AFTER_DAYS` law governs nothing | persistent cognition / free-first research |
| **Unfalsifiable "DISPUTED stands"** | `CIOCouncilSynthesis` DISPUTED count = 0; one stale artifact | judgment critique pass |
| **Notification classes never fire** | IMMEDIATE 0, CC_ONLY 0 all-time (2,046 scanner wakes) | the "surface" half of maturity |
| **Money split (M4)** | multiple cash totals in one `/api/v3/cio/home` body; fossil prose + evidence_refs stale | consistency (M4) |

---

## 4. What is NOT a gap (state the positives honestly)

- Outcome edge settles on a schedule and produced one correctly-caveated outcome-derived lesson.
- `MBI_BEHAVIOR = 0` is code-confirmed and the cognition write-back now fires on the scheduled wake.
- The `delivery_owner` stamp (PR #926) is promoted and controlled-re-proven (pmid 51022).
- The guard control plane holds the operator boundary (git-push / release-write / destructive / etc.).

These are prerequisites, not the target. They narrow the gap without crossing it.

---

## 5. The gap in one paragraph

The system has become a **better, more honest reporter**: it now loads the record on a schedule,
settles outcomes, and stamps delivery ownership. It still does not **think for itself** in any
falsifiable sense — no gated model view, no staked commitment, no moved prior, no self-repair
loop — and the plumbing that would carry those (operator turns, librarian index, notification
router, one authoritative store) is unwired, split, or absent. The path is known and ordered;
steps 1 and 2 are mid-flight; steps 3–6 are unstarted.
