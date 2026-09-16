# Phase 7 — Execution Plan & Maturity Scorecard

Status: ACTIVE (proposed; `02` still requires approval before routing code changes)
as_of: 2026-09-16T17:05:00-04:00
Measured at: origin/main `940425b73` · corpus `[VERIFIED]` · code `[CODE]`
See also: `00_EXECUTIVE_SUMMARY.md` · `02_ROUTING_GOVERNANCE_PROPOSAL.md` · `04_CONTENT_QUALITY_CURATION.md` · `05_COMMAND_CENTER_COVERAGE_GAPS.md`

> This is the plan. It answers the five questions the earlier package left open and gives an
> ordered, acceptance-gated execution sequence.

## 1. Maturity scorecard (1–10, current state — measured, not assumed)

| # | Dimension | Score | Evidence | What would raise it |
|---|---|---:|---|---|
| D1 | **Right channel, right message** | **4 / 10** | Proposal Decisions was 72% non-proposal noise (87× holdings-BLOCKED, 43× AES stop) pre-fix `[VERIFIED]`; DM carried health/watch/brief mix. The 09-14 `tg_chat_ids` split is in code but **unproven post-fix** (no re-export). | Re-export Proposal Decisions post-09-14; confirm proposals-only |
| D2 | **Dedupe / no-repeat** | **7 / 10** | DM 31.8%→**2.4%** duplicate copies after 09-14 `[VERIFIED]`; CIO Desk 0%; OpenClaw 0% | Re-export Proposal Decisions to confirm its 72% fell too |
| D3 | **Signal-to-noise / noise control** | **6 / 10** | Orphaned STOP HEALTH repeats per symbol; duplicated morning-command brief; watch-alert price crosses still flood DM `[VERIFIED]` | Collapse repeats to one daily digest; dedupe morning brief |
| D4 | **Actionability of what is sent** | **5 / 10** | GO/ENTRY/CIO/proposal cards are actionable; health/watch alerts are not; no portfolio-level actionable brief | Held/not-held labels; portfolio digest |
| D5 | **Content completeness (have → present)** | **3 / 10** | CC holds full portfolio, watch dossiers, rotation plans, earnings/dividend dates, cash posture; Telegram surfaces only event cards `[CODE]` + `05` | Surface the standing book (§3 below) |
| D6 | **Governance (written routing contract)** | **1 / 10** | No per-channel contract existed before this package; `02` is now proposed, unapproved | Approve `02`; then code-gate CIO-origin-only |
| D7 | **Delivery observability** | **6 / 10** | Comms Editor receipts + `/v3/communications` ledger exist; no per-device sync state | Device membership inventory + a sync check |

**Overall: ~4–5 / 10.** Not "everything is 1/10" — dedupe and CIO/OpenClaw are genuinely
clean — but **routing correctness (D1) and content completeness (D5) are the two weak links**,
and both are fixable.

## 2. Are messages going to the right channels? — the measured verdict

| Channel | Verdict | Evidence |
|---|---|---|
| **TradeAI Proposal Decisions** | **NO (pre-fix)** — 72% of it was holdings/stop/pipeline noise, not proposals | 87× `holdings write BLOCKED`, 43× AES stop warning, ~17 real proposals `[VERIFIED]` |
| **Trade AI DM** | **Partial** — right bot, but catch-all mix (health + watch + brief + GO/entry) | 439 health-ish + 244 watch/brief/other of 1456 `[VERIFIED]` |
| **CIO Desk** | **Yes** — CIO-origin only, 0 dup | 194 texts, 0% dup, 46% "Run Complete" (now suppressed) `[VERIFIED]` |
| **John OpenClaw** | **Yes** — assistant only, 0 dup | 24 texts `[VERIFIED]` |

**Answer: the routing split exists in code but was only partially verified. Proposal Decisions
is the channel that was demonstrably wrong, and it is the one not yet re-exported post-fix.**

## 3. Missing content — what we already have but do not surface

This is the actionable gap (D5). Every item below **already exists in Command Center** and is
simply not pushed to Telegram in an actionable form.

| Already in CC | Telegram today | Fix |
|---|---|---|
| Full portfolio / holdings / exposures / lookthrough | never surfaced | daily **portfolio brief** to DM |
| Watch Intelligence dossier (thesis, catalysts, S/R, freshness) | only event cards (GO/entry) | "watch card" for names that move |
| Rotation entry plans (zone/stop/R:R) | suppressed as P2 (now partially IMMEDIATE) | route entry plans to DM, actionable |
| CIO capital plan / cash posture | only gated IMMEDIATE cards | scheduled posture line in the brief |
| Earnings dates (held names) | absent | "this week: earnings" line |
| Dividend dates | absent | "this week: dividends" line |
| Data-source health / research queue | only on alarm | weekly health line in digest |

## 4. Why you don't see every channel on every device — the answer

**They are not one channel.** They are **three separate bots + one group**:

| Surface | Identity | Kind |
|---|---|---|
| CIO Desk | dedicated CIO bot | 1:1 DM |
| Trade AI DM | `tradeai_bigjohn718_bot` | 1:1 DM |
| Proposal Decisions | `tradeai_bigjohn718_bot` | **group** |
| John OpenClaw | `bigjohn_openclaw_bot` | 1:1 DM |

Telegram syncs **your account's** chats across your own devices automatically. So the reason a
"channel" is missing on a device is **not** the server (server sends to fixed `chat_id`s and
receipts show success). It is one of:

1. **The device is not a member of the Proposal Decisions *group*** — group membership is what
   hides a group from a device. (Most likely.)
2. **The chat is archived or in a folder** on that device.
3. **You are conflating the three bots** — "the CIO channel" and "the Trade AI channel" and
   "OpenClaw" are three different DMs; a device shows each only if that DM exists on your account.

**Fix (5 minutes, per device):** on each device, confirm you are (a) logged into the same
account, (b) a member of "TradeAI Proposal Decisions", (c) the three bot DMs are not archived.
Fill this table and send it back:

| Device | CIO Desk DM? | Trade AI DM? | Proposal group member? | OpenClaw DM? |
|---|---|---|---|---|
| phone | | | | |
| desktop 1 | | | | |
| desktop 2 | | | | |

## 5. Execution plan (ordered, with acceptance)

### Phase A — verify (no code)
| # | Step | Acceptance |
|---|---|---|
| A1 | Re-export **TradeAI Proposal Decisions** post-09-14 | 0 holdings/stop messages; proposals-only |
| A2 | Fill the device-membership table (§4) | every device shows all 4 surfaces |
| A3 | Approve `02_ROUTING_GOVERNANCE_PROPOSAL.md` | governance contract is authoritative |

### Phase B — quick fixes (code, dry-run first)
| # | Step | Acceptance |
|---|---|---|
| B1 | Dedupe morning-command brief (one per day) | brief count = 1/day |
| B2 | Collapse orphaned STOP HEALTH per-symbol repeats → one daily digest | no per-symbol spam |
| B3 | Held/not-held label on GO/entry/material alerts | triage at a glance |

### Phase C — content surface (medium)
| # | Step | Acceptance |
|---|---|---|
| C1 | Daily **portfolio brief** (holdings, top movers, cash, initiatives) to DM | book visible on phone |
| C2 | Earnings + dividend "this week" line for held names | calendar on phone |
| C3 | Entry plans route IMMEDIATE (not P2) | confirmed from the planner path |

### Phase D — governance hardening (long)
| # | Step | Acceptance |
|---|---|---|
| D1 | Code-gate CIO Desk = CIO-origin only | test fails on non-CIO producer to CIO chat |
| D2 | Volume budget (30/day, ops exempt) | over → digest |
| D3 | Cross-device delivery check surfaced in `/v3/communications` | per-device state visible |

## 6. What I will do next (on your word)

1. **A3** — you approve `02`; I wire the governance contract into `tg_chat_ids` docs/tests.
2. **B1–B3** — I implement with dry-runs, tests, PR, and exact-main promote (same flow as the lean CC work).
3. **C1** — I build the daily portfolio brief (the single biggest actionable-content win).

Say "approve the plan" and I start B1–B3 now, or tell me which phase to open first.
