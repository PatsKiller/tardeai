# Phase 4 — Content Quality, Relevance & Curation Audit

Status: ACTIVE (partial — corpus classification pending ChatExport)
as_of: 2026-09-16T16:30:00-04:00
Measured at: origin/main `940425b73` · router/policy `[CODE]`; historical corpus `[DOC-CLAIM]`
See also: `02_ROUTING_GOVERNANCE_PROPOSAL.md` · `05_COMMAND_CENTER_COVERAGE_GAPS.md`

## 1. What we know without the export (mechanism-level)

The routing policy already encodes a quality bar; the audit is whether producers *comply*.

| Delivery class | Meaning | Should reach phone? |
|---|---|---|
| `IMMEDIATE` | capital at risk / operator-requested action | yes |
| `DIGEST` | batched, non-urgent | one per window |
| `COMMAND_CENTER_ONLY` | surfaced to CC, not phone | no |
| `SUPPRESSED` | deduped / held | no |

`[CODE]` `scripts/lib/cio_notification_signal.py:56-58` and
`scripts/telegram_alert_router.py:164`.

## 2. Historical corpus signals (pre-routing-map, `[DOC-CLAIM]`)

- **2026-07-28** (13,004 msgs): 21.9% exact within-chat duplicates; projected **99.7%**
  reduction to ~9 phone notifications + 1–2 digests/day was achievable.
  `docs/ops/alerts/telegram_notification_normalization_2026_07_28/...`
- **2026-08-22** (18,130 msgs, 4 feeds): bot feed "not a trading feed" (115/day, 13%
  actionable, 5.8% last-14d); STOP_TRIGGERED buried in health noise; Proposal Decisions 77%
  actionable; CIO Desk best-designed.
  `docs/ops/TELEGRAM_FEED_REMEDIATION_2026-08-22.md`
- **CIO Desk noise (fixed):** 86 of 95 messages were "CIO Run Complete — <uuid>";
  removed by `lib/cio_run_worker.py` `[CODE]`.

## 3. Classification rubric (apply against export)

| Tier | Definition | Examples (expected) |
|---|---|---|
| **Critical / Immediate Action** | capital at risk, operator must act now | orphaned stop, protection failure, broker auth block, GO with actionable criteria |
| **High Priority** | material move / entry / decision worth acting on today | material change, ENTRY READY, CIO ADD/TRIM/EXIT |
| **Informational** | useful context, no immediate action | confluence flip, regime note, research digest |
| **Background Context** | reference material | scanner WAIT/AVOID universe, analyst notes |
| **Unnecessary / Low Value** | noise | reaper notices, "Run Complete", revalidation churn |

## 4. Signal-to-noise assessment (current, by mechanism)

| Channel | S/N (mechanism-based) | Note |
|---|---|---|
| CIO Desk | **High** (after Run-Complete removal) | strong product standard; still verify no health bleed |
| Trade AI DM | **Medium** | IMMEDIATE now scarce + digests batched, but ops families still land here |
| Proposal Decisions | **High** (77% actionable historical) | narrowest, best-scoped |
| John Openclaw | **N/A** (conversational) | S/N is per-query, not per-alert |

## 5. Actionability

- **Actionable:** GO (criteria list), ENTRY (zone/stop/R:R/invalidation), CIO act-now
  (disposition buttons), paper proposals (approve/reject).
- **Not actionable but sent:** routine health/SIEM/reaper — should be digest or Ops.
- **Actionable but suppressed (historical bug, fixed):** ENTRY was P2 before 09-15; now
  `cio_entry_state` → IMMEDIATE `[CODE]`.

## 6. Recommendations

1. **Apply the 5-tier rubric to the ChatExport** and produce per-channel counts — this is the
   empirical core of the audit and is blocked only on the export.
2. **Cap immediate sends** with a volume budget (T7: 30/day, Ops exempt) once the export
   confirms volume.
3. **Summarize, don't stream:** digests already exist; extend to health/SIEM so the DM is not a
   raw log.
4. **Keep the CIO product standard** as the template for every actionable card.
5. **Mark provenance** on every card (already in Comms Editor live) so "noise vs signal" is
   auditable, not impressionistic.
