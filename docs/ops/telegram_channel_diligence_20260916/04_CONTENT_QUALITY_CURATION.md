# Phase 4 — Content Quality, Relevance & Curation Audit

Status: ACTIVE (four channels measured)
as_of: 2026-09-16T17:00:00-04:00
Measured at: origin/main `940425b73` · router/policy `[CODE]` · **live corpus `[VERIFIED]`** (4 chats)
See also: `02_ROUTING_GOVERNANCE_PROPOSAL.md` · `05_COMMAND_CENTER_COVERAGE_GAPS.md`

> **Correction.** An earlier draft attributed the "66% duplicates" figure to the Trade AI DM.
> Re-parsing the folder titles showed that corpus is actually the **TradeAI Proposal Decisions**
> group. This version corrects that and covers all four channels.

## 0. Measured corpus — all four channels (`[VERIFIED]`)

Source: `~/Downloads/Telegram Desktop/ChatExport_2026-09-16*` → `messages*.html`.

| Channel | Folder | Window | Texts | Distinct | Duplicate copies | Rate |
|---|---|---|---|---|---|---:|
| Trade AI DM (`tradeai_bigjohn718_bot`) | `…2026-09-16` | 25 Aug → 16 Sep | 1456 | 1125 | 331 | **22.7%** |
| CIO Desk | `…2026-09-16 (1)` | 27 Aug → 16 Sep | 194 | 194 | 0 | 0% |
| TradeAI Proposal Decisions | `…2026-09-16 (3)` | 25 Aug → 11 Sep | 181 | 50 | **131** | **72%** |
| John OpenClaw | `…2026-09-16 (2)` | 25 Aug → 15 Sep | 24 | 24 | 0 | 0% |

### The DM improves 31.8% → 2.4% after the 09-14 fix (`[VERIFIED]`)

| DM window | Texts | Duplicate copies | Rate |
|---|---:|---:|---:|
| Pre-fix (25 Aug – 13 Sep) | 1000 | 318 | **31.8%** |
| Post-fix (13 – 16 Sep) | 456 | **11** | **2.4%** |

The 09-14/15 dedupe + routing + editor-live work is empirically effective on this channel.

### TradeAI Proposal Decisions — the real duplication offender (`[VERIFIED]`)

72% duplicate copies of 8 texts (pre-fix window, export ends 11 Sep):

| Family | Copies | Detail |
|---|---:|---|
| `🛑 holdings write BLOCKED (holdings_reconcile)` | **87** | `total_value 594,765 below sanity floor 1,000,000` — 19–23×/day 01–04 Sep |
| `⚠️ STOP WARNING *AES*` | **43** | same `$14.77→$14.72→$14.68`, 13× on 27 Aug |
| pipeline alerts, basis audit, tech gaps, protective stops | rest | only ~17 actual proposals |

This is the exact "health/stop noise in the Proposal group" defect the 09-14 routing split
fixed (`tg_chat_ids`). The export predates that fix, so a **post-09-14 re-export** of this
group is still required to prove it is now proposals-only.

### CIO Desk — clean, but 46% "Run Complete" (now fixed) (`[VERIFIED]`)

0 duplicates. But **89 of 194 (46%)** were `CIO Run Complete — <uuid> … Nothing requires
action today` (57 said "nothing requires action"). Last one: **14 Sep** — the run-complete
suppression (`lib/cio_run_worker.py`, tested 09-14) landed and the noise stops. CIO Desk is
otherwise CIO-origin only, no health/holdings bleed.

### John OpenClaw — clean and light (`[VERIFIED]`)

24 texts, 0 duplicates, conversational assistant traffic only.

## 1. Mechanism-level (what the code enforces now)

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

## 3. Classification rubric

| Tier | Definition | Examples |
|---|---|---|
| **Critical / Immediate Action** | capital at risk, operator must act now | orphaned stop, protection failure, broker auth block, GO with actionable criteria |
| **High Priority** | material move / entry / decision worth acting on today | material change, ENTRY READY, CIO ADD/TRIM/EXIT |
| **Informational** | useful context, no immediate action | confluence flip, regime note, research digest |
| **Background Context** | reference material | scanner WAIT/AVOID universe, analyst notes |
| **Unnecessary / Low Value** | noise | reaper notices, "Run Complete", revalidation churn |

## 4. Signal-to-noise assessment (measured `[VERIFIED]` + mechanism `[CODE]`)

| Channel | Measured S/N | Note |
|---|---|---|
| CIO Desk | **High** — 0 dup, CIO-origin only; 46% "Run Complete" noise stopped 14 Sep | product standard holds |
| Trade AI DM | **Medium→High** — 22.7% dup overall but **2.4% post-fix** | noise = orphaned-stop health + watch alerts + duplicated morning briefs |
| TradeAI Proposal Decisions | **Low pre-fix** (72% dup, 87× holdings-BLOCKED) — needs post-fix re-export to confirm | the channel the 09-14 split targeted |
| John OpenClaw | **High** — 0 dup, 24 texts, conversational | per-query, not per-alert |

## 5. Actionability

- **Actionable:** GO (criteria list), ENTRY (zone/stop/R:R/invalidation), CIO act-now
  (disposition buttons), paper proposals (approve/reject).
- **Not actionable but sent:** orphaned-stop health (repeats per symbol), watch-alert price
  crosses, duplicated morning-command briefs — digest or dedupe, not immediate.
- **Actionable but suppressed (historical bug, fixed):** ENTRY was P2 before 09-15; now
  `cio_entry_state` → IMMEDIATE `[CODE]`.

## 6. Recommendations

1. **Re-export TradeAI Proposal Decisions post-09-14** to prove the routing split silenced the
   87× holdings-BLOCKED / 43× AES flood (the current export ends 11 Sep, before the fix).
2. **Dedupe the morning-command brief** — it appears duplicated in the DM "OTHER" bucket.
3. **Collapse orphaned STOP HEALTH** per-symbol repeats into one daily digest.
4. **Cap immediate sends** with a volume budget (T7: 30/day, Ops exempt).
5. **Keep the CIO product standard** and the Run-Complete suppression as the template.
