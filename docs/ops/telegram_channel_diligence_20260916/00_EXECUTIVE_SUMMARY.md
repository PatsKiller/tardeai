# Telegram Channel Diligence — Executive Summary

Status: ACTIVE
as_of: 2026-09-16T16:15:00-04:00
Measured at: origin/main `940425b73` (docs worktree) · code + runtime evidence; ChatExport pending
See also: `01_CHANNEL_INVENTORY_SOURCE_MAP.md` · `02_ROUTING_GOVERNANCE_PROPOSAL.md` · `03_DELIVERY_RELIABILITY.md` · `04_CONTENT_QUALITY_CURATION.md` · `05_COMMAND_CENTER_COVERAGE_GAPS.md` · `06_IMPLEMENTATION_ROADMAP.md`

## The one-sentence version

There are **four Telegram surfaces** — CIO Desk, Trade AI DM, Proposal Decisions, and John
OpenClaw — but two of them historically acted as a single undifferentiated event stream, and
the routing was only split by operator approval on 2026-09-14. The architecture is now
mostly correct at the code layer; the remaining problems are (1) **empirical content audit is
blocked on the ChatExport**, (2) **device-sync inconsistency has no server-side explanation
yet**, and (3) **there is no written per-channel governance contract** that names audience,
required content, and routing rules.

## The four channels (operator name → code identity)

| Operator name | Code / env identity | Primary stack | Bot |
|---|---|---|---|
| CIO Channel | CIO Desk (dedicated CIO bot) | `tradeai-cio-telegram.service`, `lib/cio_notification_signal.py`, CIO delivery + material-scan timers | dedicated CIO bot |
| Trade AI Channels | Operator DM via `TELEGRAM_CHAT_ID` → `tg_chat_ids.chat_ids()` | `telegram_transport` chokepoint → `telegram_alert_router` → Comms Editor | `tradeai_bigjohn718_bot` |
| (Trade AI) Proposal Decisions | `TRADEAI_PROPOSAL_ALERT_CHAT_ID` → `proposal_chat_ids()` | `send_telegram_proposal_alert` + callback poller | `tradeai_bigjohn718_bot` |
| John Openclaw Channel | OpenClaw Telegram binding (`@bigjohn_openclaw_bot` → Maria) | `openclaw-gateway.service` (:18789), OpenClaw skills | `bigjohn_openclaw_bot` |

Naming note: your "Trade AI Channels" maps to **two** distinct code surfaces — the generic DM
(`chat_ids()`) and the Proposal Decisions group (`proposal_chat_ids()`). They share a bot but
must be governed separately, and this package treats them as separate channels.

## Prioritized recommendations

| # | Priority | Recommendation | Doc |
|---|---|---|---|
| 1 | **High** | Re-export **TradeAI Proposal Decisions** post-09-14 to prove the routing split silenced the 87× holdings-BLOCKED / 43× AES flood (current export ends 11 Sep) | 03, 04 |
| 2 | **High** | Approve a written per-channel governance contract (audience, required/optional, routing) before any producer retarget | 02 |
| 3 | **High** | Reconcile the four-channel names: confirm "Trade AI Channels" = DM + Proposals, and pin the bot-per-channel matrix | 01, 02 |
| 4 | **High** | Resolve device-sync: verify every device is joined to the **same** chats/bots (CIO bot ≠ bigjohn bot ≠ OpenClaw bot is the most likely cause of "visible on some devices") | 03 |
| 5 | **Medium** | Enforce CIO Desk = CIO-origin only; route health/ops away from the CIO channel | 02 |
| 6 | **Medium** | Dedupe the morning-command brief and collapse orphaned STOP HEALTH repeats into one digest | 04 |
| 7 | **Low** | Add coverage for holdings/position/initiative facts that CC shows but Telegram never surfaces | 05 |

## What is already true (verified, not assumed)

- Routing split landed: `chat_ids()` = DM only, `proposal_chat_ids()` = proposals only `[CODE]`
  `scripts/tg_chat_ids.py`; guarded by `tests/test_tg_chat_routing_20260914.py`.
- Four delivery classes exist: `IMMEDIATE · DIGEST · COMMAND_CENTER_ONLY · SUPPRESSED`
  `[CODE]` `scripts/lib/cio_notification_signal.py:56-58`.
- ENTRY ALERT now routes IMMEDIATE (was P2 suppress) `[CODE]`
  `scripts/operator_alert_policy_v2.py` (lean PR #1032).
- GO cards deep-link to Trading Hub `/v3/trading?tab=Scalp` (facts live there) `[CODE]`
  `scripts/lib/telegram_rich.py`.
- Comms Editor is `live` on the host `[VERIFIED]` (`~/.config/tradeai/comms_editor_mode` = `live`).

## What is NOT settled

- **Device-sync has no server-side smoking gun yet.** Server receipts show sends succeeded
  (Comms Editor ledger, 0 holds in the last 80 shadow receipts). Inconsistent device visibility
  is therefore more likely **client/chat-membership** than server failure — with a third
  candidate: duplication (72% on Proposal Decisions pre-fix) reads as missing messages.

## Measured corpus (all four channels, `[VERIFIED]`)

Source `~/Downloads/Telegram Desktop/ChatExport_2026-09-16*`:

| Channel | Texts | Duplicate rate | Verdict |
|---|---|---:|---|
| Trade AI DM | 1456 | 22.7% (2.4% post-fix) | noisy pre-fix, clean after 09-14 |
| CIO Desk | 194 | 0% | clean; 46% "Run Complete" stopped 14 Sep |
| TradeAI Proposal Decisions | 181 | **72%** | the duplication offender (pre-fix) |
| John OpenClaw | 24 | 0% | clean, conversational |
