# Phase 3 — Telegram Delivery Reliability Assessment

Status: ACTIVE (partial — one channel measured; device inventory + 3 exports still needed)
as_of: 2026-09-16T16:45:00-04:00
Measured at: origin/main `940425b73` · transport `[CODE]`; receipts `[VERIFIED]`; corpus `[VERIFIED]`; historical `[DOC-CLAIM]`
See also: `00_EXECUTIVE_SUMMARY.md` · `04_CONTENT_QUALITY_CURATION.md`

## 0. A third explanation the corpus adds: duplication masquerading as desync

The `tradeai_bigjohn718_bot` export shows **131 of 198 messages (66%) are duplicate copies**
of 8 texts — e.g. 85× the same `holdings write BLOCKED` and 43× the same AES stop warning.
On any device, a wall of near-identical messages is easily read as "some arrived and some
didn't" (or "they keep disappearing"), when in fact the server sent every one. **Duplication
is a reliability problem in its own right**, and it must be separated from genuine
cross-device sync.

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

- ChatExport pending → will confirm per-chat send/duplicate behavior empirically.
- Device inventory not yet collected → the table in §4 is unfilled by design.
