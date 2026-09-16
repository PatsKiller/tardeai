# Phase 3 — Telegram Delivery Reliability Assessment

Status: ACTIVE (four channels measured; device inventory still needed)
as_of: 2026-09-16T19:15:00-04:00
Measured at: branch `agent/telegram-channel-diligence-20260916` · transport `[CODE]`; receipts `[VERIFIED]`; corpus `[VERIFIED]`; historical `[DOC-CLAIM]`
See also: `00_EXECUTIVE_SUMMARY.md` · `04_CONTENT_QUALITY_CURATION.md`

## 0. A third explanation the corpus adds: duplication masquerading as desync

The **TradeAI Proposal Decisions** group export shows **131 of 181 messages (72%) are
duplicate copies** of 8 texts — 87× `holdings write BLOCKED`, 43× the same AES stop warning.
The Trade AI DM was 22.7% duplicates pre-fix, dropping to **2.4% post-fix**. On any device, a
wall of near-identical messages is easily read as "some arrived and some didn't" (or "they keep
disappearing"), when in fact the server sent every one. **Duplication is a reliability problem
in its own right**, and it must be separated from genuine cross-device sync.

## 1. The reported symptom

Same Telegram account across multiple devices; some messages visible on some devices but not
others. This must be split into two independent questions:

1. **Did the server actually send it?** — answerable from receipts/ledger.
2. **Did every device receive it?** — Telegram client sync, chat membership, folders, and
   notification settings.

## 2. Server-side evidence (what the box can prove)

- **Comms Editor receipts:** the send chokepoint records a receipt per send.
  `[VERIFIED]` 2026-09-15: `comms_editor_receipts.jsonl` had 253 lines; the last 80 were all
  `mode=shadow`, **0 `held_reason`**, `send: true` — i.e. the editor decided to send and did
  not hold anything.
- **Transport:** `telegram_transport.deliver_text` returns HTTP result per chat_id; a Markdown
  `400` falls back to one plaintext resend (no silent drop) `[CODE]`.
- **Router:** `should_send_telegram()` + `classify_alert()` decide P0..P3 before send; P2/P3 are
  deliberately **not** sent to the phone `[CODE]` `scripts/telegram_alert_router.py:488`.

**Conclusion:** there is no evidence the server drops a send that should have gone out; the
routing layer *intentionally* suppresses P2/P3 — which can look like "missing" to the operator.

## 3. Most likely causes of inconsistent device visibility

| # | Cause | Mechanism | Evidence level |
|---|---|---|---|
| 1 | **Different bots/chats on different devices** | CIO bot ≠ `tradeai_bigjohn718_bot` ≠ `bigjohn_openclaw_bot`. A device only shows chats it is a member of. If "the same account" means different bots/groups per device, messages will not align. | hypothesis, high |
| 2 | **Not joined to the Proposal group on all devices** | group membership is per-account, but a muted/archived/left group on one device hides it. | hypothesis, medium |
| 3 | **P2/P3 suppression misread as lost** | router files to CC/dashboard, not the phone; the operator sees it on CC but not Telegram. | `[CODE]` confirmed |
| 4 | **Digest timing** | a family routed DIGEST arrives hours later on a different schedule than the immediate event. | `[CODE]` confirmed |
| 5 | **Client folders/mute/archive** | Telegram "New chat" vs "Archive" vs "Chats folders" hide messages; notification settings are per-device. | Telegram client, not server |
| 6 | **Cloud sync latency / device offline** | messages sync when the device reconnects; a long-offline device lags. | Telegram client |

## 4. What to check (device inventory — operator action)

For **each device**: list which of the four chats/groups/bots it is a member of, and whether the
chat is muted/archived/foldered. The mismatch almost certainly lives in this table, not in the
server.

| Chat | Bot | Device A | Device B | Device C |
|---|---|---|---|---|
| CIO Desk | CIO bot | ? | ? | ? |
| Trade AI DM | bigjohn718 | ? | ? | ? |
| Proposal Decisions (group) | bigjohn718 | ? | ? | ? |
| John Openclaw | bigjohn_openclaw | ? | ? | ? |

## 5. Recommendations

1. **Confirm one identity per channel.** There are (at least) **three** bot identities. A
   "single account" does not equal "single bot" — every device must be joined to the exact same
   chats for the same bot.
2. **Use the Communications Hub as ground truth.** `/v3/communications` reads the delivery
   ledger (message id + status). If the ledger shows `SENT` but a device lacks it, it is client
   sync/membership, not server.
3. **Do not treat P2/P3 as lost.** Surface the router's `should_send` decision so
   "suppressed to CC" is visibly distinct from "failed to send".
4. **Verify folders/mute/archive per device** for the four chats above.
5. **Confirm no two bots share a chat name** that the operator could confuse across devices.

## 6. Open items

- Device inventory not yet collected → the table in §4 is unfilled by design.
- Post-09-14 re-export of **TradeAI Proposal Decisions** (current export ends 11 Sep, pre-fix).

## 7. Falsifier re-run 13.09–16.09 — final fixes and empty-channel verdicts

Post-fix re-export of the **Trade AI DM** (`ChatExport_2026-09-16 (4)/messages2.html`,
493 msgs, 13.09 → 16.09 18:52 ET) was falsified on one channel. Findings and fixes below.

### 7.1 DM duplicate rate — 2.2% post-fix (was 31.8% pre-fix)

Pre-fix 31.8% → post-fix **2.2%** duplicate copies. The 09-14/15 dedupe + routing +
editor-live work holds on the re-export.

### 7.2 `⚠️ Research lane RAW-store health` — routed to DIGEST (was ~40×/day to the DM)

The remaining DM noise was the research-lane health heartbeat: ~40 messages/day
(80 over 3 days, 39 on 16.09) — non-actionable telemetry (`budget_throttled`,
`chatgpt error_rate_24h`, `lane-registry SILENT`).

- **Cause:** `scripts/research_lane_health.py::_deliver_telegram` called
  `send_telegram(msg, bypass_router=True)`, which skipped `classify_alert()` and sent
  straight to the phone. The header "⚠️ *Research lane RAW-store health*" classifies as
  `job_telemetry`, which `operator_alert_policy_v2.route_event()` already routes
  **DIGEST** — the bypass defeated that policy. `[CODE]`
- **Fix:** `bypass_router=True → False` at `scripts/research_lane_health.py:401`. The
  message now lands in the reports archive (v3 Reports portal / P1 digest), never the
  phone.
- **Test:** three tests added to `tests/test_research_lane_health_alert.py` —
  `test_raw_store_health_classifies_digest_not_interrupt`,
  `test_deliver_telegram_does_not_bypass_router`,
  `test_alert_suppressed_to_digest_not_transported`. Mutation-tested: restoring
  `bypass_router=True` turns both routing tests red. `[VERIFIED]` (22 passed).

### 7.3 Empty-channel verdicts (13.09 → 16.09)

The operator reported **zero new text** on CIO Desk, Proposal Decisions and OpenClaw
since the job started. "Empty" is only a clean pass if no producer should have fired
(AGENTS.md §8: two states cannot express "no input"). Per channel:

| Channel | Verdict | Evidence |
|---|---|---|
| **CIO Desk** | `CLEAN_EMPTY` *(one open item)* | `cio_material_scan_last.json` fresh (19:08 16.09, `published:false` HOLD_CASH candidates) and `cio_desk_note_latest.md` fresh (18:47) — the scan/desk lanes run. "Run Complete" noise suppressed 14 Sep. ⚠️ `cio_delivery_receipts.jsonl` stale since **29 Aug** (last receipt `SUPPRESSED`, `s1_observational_default_suppressed`) — either "no pending CIO cards to deliver" or the delivery worker stopped; not disambiguable from the repo alone. |
| **Proposal Decisions** | `CLEAN_EMPTY` | `logs/proposal_alerts.log` fresh (16:58 16.09). Recent entries are `BLOCKED_EXECUTION_FAILED` / `NEEDS_OPERATOR_DECISION` with `sent:false status:suppressed` — non-actionable alert types, not pending-approval proposals. No pending proposal to send. |
| **OpenClaw** | `CLEAN_EMPTY` | Conversational (Maria), event-driven on operator input; 24 texts total, 0 dup. Empty = the operator did not ask it anything. |

`cio_delivery_receipts.jsonl` (29 Aug) is the one non-clean signal: flag it for the
operator, do not call the CIO Desk "clean" without noting it.
