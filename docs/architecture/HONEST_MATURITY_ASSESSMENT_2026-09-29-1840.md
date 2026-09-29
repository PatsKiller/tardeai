Status: ACTIVE
as_of: 2026-09-29 18:40 America/New_York
Measured at: live data census + PR #1361 + CURRENT e2ff33b24
Canonical repo path: docs/architecture/HONEST_MATURITY_ASSESSMENT_2026-09-29-1840.md
Authority: honest rating — hermetic ≠ OBSERVED
Supersedes: none
See also: docs/architecture/CIO_AS_IS_2026-09-29-1840.md
           docs/architecture/CIO_FUTURE_2026-09-29-1840.md
           docs/architecture/CIO_GAP_2026-09-29-1840.md

# Honest maturity assessment — persistent agent across silos

## Overall rating: **38 / 100 — D+**

Rails and several AEC loops are real. OBSERVED end-to-end “research once / one GUID / every desk sees it” is **not**. Shared spine = library LIVE + hermetic hooks on PR; identity registry = PASS; judgment-store GUID carriage = FAIL/PARTIAL.

---

## Sub-scores

| Dimension | Score | Note |
|---|---:|---|
| Identity registry authority | 85 | 10,887 GUIDs; issuer ~49% |
| GUID carriage into stores | 18 | Hermes 5–13%; theses/IR/watch 0% |
| Shared SecurityResearchSpine | 30 | Library+flag; organic E2E not OBSERVED |
| Hermes research lane | 55 | Proven; stamp decay |
| Desk consumers (opt/watch/reentry/hold) | 25 | Code on #1361; not promoted/OBSERVED |
| Commitments / wakes | 70 | ★ proven-unattended |
| Judgment / independent scoring | 15 | Empty / dark |
| Council synthesis | 10 | UNWIRED |
| Notification / receipt | 45 | DIGEST★; receipt partial |
| Outcome loop | 55 | ★ partial |
| **Weighted lifecycle** | **38** | D+ |

---

## Identity due diligence verdict: **PARTIAL (2/5)**

- **PASS:** one registry; mint/supersession rules; agents are *supposed* to join on subject_guid/issuer_guid.
- **FAIL carriage:** most research topics and ticker-keyed desks do **not** persistently carry those GUIDs today.
- **Separate silo IDs exist:** subject_key, ticker dict keys, smoke-guid, narrative `tradeai:entity:*` — aliases that become forks when used alone.

---

## What would move the grade

| To | Requires |
|---|---|
| C (55+) | #1361 promoted + organic spine canary OBSERVED + Hermes new-write GUID ≥90% |
| B (70+) | theses + InstrumentRecord + watch stamp GUIDs; spine refuses non-registry; coverage metric |
| A (85+) | Council + scoring live; weekly multi-desk canary; issuer_guid on traded universe |

---

## Bottom line for the operator

You asked whether everything has unique GUIDs carried in memory and agents with no silo-local IDs. **Not yet.** The registry is the single source of truth; the silos largely do not persist it. CADI-011/012 closes the *research* silo fork in code; promoting #1361 is necessary but not sufficient for the identity carriage gap.
