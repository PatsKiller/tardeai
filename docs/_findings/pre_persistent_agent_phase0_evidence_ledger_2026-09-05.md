# Phase 0 evidence ledger — pre-persistent-agent truth closeout

**Campaign:** `pre-persistent-agent-truth-closeout-20260905`
**Date:** 2026-09-05
**origin/main:** `f88853e89e53fdd63725acccb064ca1395e0bf34` — identical to the campaign's `EXPECTED_MAIN`
**Serving:** `f88853e89-main-exact-phase2-20260905-135414`, `SOURCE_COMMIT f88853e89`
**Method:** every row below was measured against the running system, not read from a document.

---

## Why this ledger changes the certification

The As-Built Certification returns **CONTROLLED NO-GO**, and states its own binding limitation:

> *No accessible artifact tied the currently serving build identity to GitHub main f88853e89.
> The screenshot establishes a live Communications surface, but not the exact source commit.
> This prevents a full green release certification.*

That limitation is an artefact of **access, not of the system**. The auditor ran in a cloud
context and said so — *"Private runtime independently unreachable"*. This ledger is written
from the box itself, so several findings classified `UNPROVEN` / `BUILT DARK` are measurable,
and some are already true.

Nothing below relaxes a verdict on the strength of a document. Where a claim is confirmed it
is confirmed by a number.

## Classification

`SERVING` observed running · `EXERCISED` has produced durable rows · `CONFIGURED` wired, no
traffic · `CODE_PRESENT` merged, not wired · `DOCUMENTATION_ONLY` claimed, unmeasurable here.

---

## 1. Exact serving-SHA attestation — **REFUTED, now SERVING**

Certification: *"No exact serving-SHA attestation — screenshot truth cannot be tied to current
source."* Priority P0.

Five independent sources, one value:

| source | value |
|---|---|
| release `SOURCE_COMMIT` | `f88853e89e53` |
| release `BUILD_SHA` | `f88853e89e53` |
| serving process cwd | `f88853e89-main-exact-phase2-20260905-135414` |
| release `dist/build-meta.json.git_sha` | `f88853e89e53` |
| served `GET /v3/build-meta.json` | `f88853e89e53` |
| `origin/main` | `f88853e89e53` |

**The exit condition in the priority backlog — "Build meta, API, service cwd, origin/main, and
release ID all agree" — is already met.** This P0 is closed by measurement.

## 2. CANARY vs ACTIVE — **not a contradiction**

Certification lists this as a truth conflict: screenshot says CANARY, Drive live-attest at
`faf8c05` says ACTIVE.

Both were true at their own times. The mode is environment-driven and it changed:

```
mode            CANARY        reason: env:COMMS_GATEWAY_MODE
delivery_owned  True
owned_classes   ['ops']
env             COMMS_GATEWAY_MODE=CANARY
                COMMS_GATEWAY_CANARY_CLASSES=ops
                COMMS_GATEWAY_CANARY_CHATS=6993102664,8797974247
```

Earlier in the same day this box served `mode=ACTIVE, reason=env:COMMS_GATEWAY_MODE,
ACTIVE_CLASSES=ops`, and the operator's own Telegram carried
`[COMMS ACTIVE] gateway-owned ops notify 20260905T043104Z`. The certification's first
hypothesis — *"Runtime mode changed"* — is the correct one. No history needs rewriting and
nothing is stale.

## 3. Unsettled Telegram deliveries — **CONFIRMED, and sharper**

Certification: 45 unsettled of 57. Measured:

| status | rows |
|---|---|
| `SENT` | 8 |
| `RESERVED` | **44** |
| `LEGACY_DELIVERED` | 5 |
| `FAILED` | 0 |
| **total** | **57** |

`provider_message_id` present on **3** rows; absent on **54**.

So the 45 is really **44 rows stuck in `RESERVED`** — reserved and never settled or refunded.
That is a real P1 and the exit condition stands: classify each with provider evidence or leave
it `LEGACY_DELIVERED` / `UNKNOWN`. Never fabricate a settlement.

## 4. Inbound checkpoint — **migration APPLIED, path NOT EXERCISED**

Certification: *"CODE MERGED; production migration/restart not proven."* Half right, and the
halves matter separately.

**Applied.** 13 `communication_*` tables exist in production, including
`communication_inbound_checkpoint` and `communication_inbound_quarantine`. The migration the
document calls unproven is in place.

**Not exercised.** `communication_inbound_checkpoint` holds **0 rows**, as does
`communication_inbound_quarantine`. Persist-before-process has never run. The P0 exit
condition — *"persist-before-process/replay proven"* — is genuinely open, but the blocking work
is the poller and its proof, not the migration.

## 5. Control planes called "BUILT DARK" — **several are EXERCISED**

Certification: retention *"production scheduler/enforcement not proven"*; agent consumption
*"BUILT DARK / SHADOW ONLY"*.

| plane | rows | classification |
|---|---|---|
| `retention_decisions` | 24 | **EXERCISED** |
| `tombstones` (purge receipts) | **6** | **EXERCISED — purges have executed** |
| `knowledge_candidates` | 12 | EXERCISED |
| `agent_subscriptions` | 30 | CONFIGURED |
| `agent_consumption_receipts` | 4 | **EXERCISED** |
| `subjects` | 56 | EXERCISED |
| `events` / `deliveries` | 58 / 57 | SERVING |

Retention is not decorative here: **6 tombstones mean purge has run and left immutable
receipts.** Agent consumption has produced durable receipts. Both were unmeasurable from the
cloud, so the document could only classify them as dark.

This does **not** license influence. `MEMORY_BEHAVIOR_INFLUENCE=0` and shadow-only remain
correct; what changes is that the loop is observable rather than theoretical.

## 6. Non-Telegram channels — **CONFIRMED dark**

`channel_adapters.py:274` `deliver: bool = False` by default, documented at `:4` as
record-only. Email/Slack/WhatsApp are truthfully dark. No change needed; contract tests only.

## 7. Brave / Research — **CONFIRMED, the P0 RED is real**

Certification: current main retains legacy static assumptions; no canonical router.

Both confirmed by inspection of `f88853e89`:

```
scripts/brave_search.py:4   "Daily budget cap: 30 requests/day (900/month with buffer for
                             1,000/month free tier)."
scripts/brave_search.py:21  MONTHLY_BUDGET = 850  # Reserve 150 for P0/manual searches out of 1000
```

and no `research_router` / `brave_router` module exists anywhere in `scripts/`.

**This is the same defect class the header campaign spent the week removing: a local policy
stated as a provider fact.** `850 … out of 1000` asserts a plan Brave never published in this
codebase's own evidence; the repaired candidate measured a *rate* limit (50 req/s) and no
metered monthly window. A number we chose is being rendered as a number they impose.

The fix is the one the design truth section already prescribes: parse and report provider
capacity from provider headers, and keep the ceiling only under an explicitly local name with
an owner.

---

## Summary against the priority backlog

| # | backlog item | ledger verdict |
|---|---|---|
| P0 | exact serving-SHA attestation | **CLOSED by measurement** |
| P0 | Brave/Research repair absent | **CONFIRMED OPEN** — real, and the highest-value fix |
| P0 | inbound activation unproven | **PARTIALLY CLOSED** — migration applied; path unexercised |
| P0 | persistent-agent consumption not closed | receipts exist (4); eligibility/ratification proof still open |
| P1 | 45 unsettled deliveries | **CONFIRMED** — 44 `RESERVED`, 3 with provider ids |
| P1 | retention enforcement unproven | **PARTIALLY REFUTED** — 24 decisions, 6 purge tombstones |
| P1 | LLM curation built dark | module present; no measured model invocation — open |
| P1 | Drive truth index stale | not assessed here; requires Drive access |
| P1 | external-link policy narrow | not assessed here |
| P2 | channels dark | **CONFIRMED dark, correctly** |
| P2 | FCNTX/SCHD exceptions | unchanged; still needs statement adjudication |

## What this ledger does not do

It does not re-verdict the campaign. Access was the auditor's stated limitation and this
removes it for the runtime rows only — the Drive corpus, the provider's real rate limits, and
the end-to-end research traces are all still unmeasured. `CONTROLLED NO-GO` on
persistent-agent *influence* is untouched and remains correct.
