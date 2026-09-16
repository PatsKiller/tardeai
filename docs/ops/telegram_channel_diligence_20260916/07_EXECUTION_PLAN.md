# Phase 7 — Execution Plan & Maturity Scorecard

Status: ACTIVE (proposed; `02` still requires approval before routing code changes)
as_of: 2026-09-16T17:05:00-04:00
Measured at: origin/main `940425b73` · corpus `[VERIFIED]` · code `[CODE]`
See also: `00_EXECUTIVE_SUMMARY.md` · `02_ROUTING_GOVERNANCE_PROPOSAL.md` · `04_CONTENT_QUALITY_CURATION.md` · `05_COMMAND_CENTER_COVERAGE_GAPS.md`

> This is the plan. It answers the five questions the earlier package left open and gives an
> ordered, acceptance-gated execution sequence.

## 1. Maturity scorecard — current → 10, and exactly what "10" requires

The goal is **perfection: every dimension at 10.** "10" is not a feeling — each row names its
measurable acceptance test.

| # | Dimension | Now | 10 = (measurable) | To get from now → 10 |
|---|---:|---|---|---|
| D1 | Right channel, right message | 4 | A periodic 4-channel re-export shows **zero** misroutes: Proposal Decisions = proposals only; CIO Desk = CIO-origin only; DM = approved categories only | Re-export Proposal Decisions post-09-14; code-gate CIO-origin-only + proposals-only; periodic 4-channel audit job |
| D2 | Dedupe / no-repeat | 7 | **0 duplicate copies** in any window; every send idempotent by `(producer, type, subject, observation_version)` | Re-export Proposal Decisions (confirm 72%→~0); dedupe morning brief; idempotency-key audit |
| D3 | Signal-to-noise | 6 | Every Immediate message is actionable; **all** non-actionable → digest/CC, none on the phone | Collapse orphaned STOP HEALTH to one digest; route watch-alert crosses + reaper to digest; volume budget |
| D4 | Actionability | 5 | Every phone message carries an action + falsifier + evidence; no "run complete"/telemetry on phone | Held/not-held labels; action language on every card; telemetry → CC only |
| D5 | Content completeness (have→present) | 3 | The standing book is on the phone daily and matches CC: holdings, exposures, cash, initiatives, earnings, dividends | Daily portfolio brief; earnings/dividend "this week" line; entry plans IMMEDIATE; cash-posture line |
| D6 | Governance (written contract) | 1 | Contract approved **and** mechanically enforced by a test that fails on a non-conforming producer | Approve `02`; code-gate CIO-origin + proposals-only; pin by test |
| D7 | Delivery observability | 6 | Per-device sync state + per-send receipt visible; a monitor fires the moment a send isn't delivered | Device membership inventory; per-device state in `/v3/communications`; delivery monitor |

**Overall now: ~4–5 / 10. Target: 10 / 10.** D1 and D5 are the two lowest and carry the most
weight; both have a concrete, orderable fix. Nothing here is a research problem — every gap is
a known producer, a missing surface, or a missing test.

## 2. Single accountable owner — a goal task, not a deterministic rule

**There is no single agent that owns message curation today.** It is split across the
deterministic router (`telegram_alert_router`), the deterministic editor (`comms_editor`), the
CIO notification signal, and ~182 `send_telegram` call sites. That diffusion *is* why the
system scored 4/10 on routing and 1/10 on governance: nobody is measured on the whole.

**Fix: one named owner holds one persistent goal, tracked in the goal loop** (the same store as
`scripts/lib/cio_goals.py`, which already carries owner, thesis, status, and falsifier):

- **Owner:** `cio` — the single accountable agent for "every outbound Telegram message is
  curated correctly".
- **Goal (thesis):** *every message reaches the right channel, deduped, actionable, and
  complete against the standing book — measured 10/10 by the four-channel re-export audit.*
- **Falsifier (what would disprove the goal):** a periodic 4-channel export showing any
  misroute, duplicate, non-actionable Immediate, or missing standing-book content.
- **Acceptance (done =):** all seven dimensions at 10, re-measured, with the audit receipt
  committed.

The deterministic router and editor **stay** — they are the mechanical floor. The goal task is
what holds one agent responsible for *continuously curating to perfection*, closing the gap
between "the rules exist" and "the channels are actually right." A deterministic rule cannot
notice that Proposal Decisions was 72% noise for weeks; an owner with a falsifier and a
periodic re-measure can.

The goal is registered in two places so it survives both the session and the machine:

1. **Cursor long-running goal** (session-level) — created via the native goal tool.
2. **`data/cio/cio_goals.jsonl`** (machine-level) — a `GOAL_CREATED` event owned by `cio`,
   so the goal loop and its `GOAL_STATUS_CHANGED` counter (currently **0** over 37 days /
   34,718 wakes — `report_goal_loop_baseline.py`) start measuring actual progress against it.

## 3. Are messages going to the right channels? — the measured verdict

| Channel | Verdict | Evidence |
|---|---|---|
| **TradeAI Proposal Decisions** | **NO (pre-fix)** — 72% of it was holdings/stop/pipeline noise, not proposals | 87× `holdings write BLOCKED`, 43× AES stop warning, ~17 real proposals `[VERIFIED]` |
| **Trade AI DM** | **Partial** — right bot, but catch-all mix (health + watch + brief + GO/entry) | 439 health-ish + 244 watch/brief/other of 1456 `[VERIFIED]` |
| **CIO Desk** | **Yes** — CIO-origin only, 0 dup | 194 texts, 0% dup, 46% "Run Complete" (now suppressed) `[VERIFIED]` |
| **John OpenClaw** | **Yes** — assistant only, 0 dup | 24 texts `[VERIFIED]` |

**Answer: the routing split exists in code but was only partially verified. Proposal Decisions
is the channel that was demonstrably wrong, and it is the one not yet re-exported post-fix.**

## 4. Missing content — what we already have but do not surface

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

## 5. Why you don't see every channel on every device — the answer

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

## 6. Execution plan (ordered, with acceptance)

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

## 7. What I will do next (on your word)

1. **Register the single owner as a goal task** (now, on approval) — create the goal owned by
   `cio` in `data/cio/cio_goals.jsonl` + the Cursor long-running goal, so the goal-loop's
   `GOAL_STATUS_CHANGED` counter starts measuring progress from its current **0**.
2. **A3** — you approve `02`; I wire the governance contract into `tg_chat_ids` docs/tests.
3. **B1–B3** — implement with dry-runs, tests, PR, exact-main promote (same flow as the lean CC work).
4. **C1–C3** — build the daily portfolio brief, earnings/dividend line, and entry-plans IMMEDIATE.
5. **D1–D3** — code-gate the contract, volume budget, per-device delivery visibility.

Say "approve the plan" and I start by registering the goal task + B1–B3, or tell me which
phase to open first. The goal of **10/10** is now the stated success criterion, not the
deterministic rules alone.
