# Trade AI — COMMUNICATION LIFECYCLES (family E), re-measured

Status: ACTIVE
as_of: 2026-10-04T21:20-04:00 (ET)
Measured at: 4f932b88a

Supersedes for current-state purposes: `docs/architecture/lifecycles/LIFECYCLE_FACTBASE_E_COMMS_2026-09-14.md` (baseline) and the family-E chapters (E1–E4) of `docs/architecture/TRADE_AI_AS_IS_LIFECYCLES_2026-09-14.md`. Same four lifecycles, same anatomy (a)–(i), same maturity scale (L0 absent/severed · L1 runs, unmeasured or wrong · L2 measured, mostly correct · L3 closed loop · L4 self-correcting · L5 proven ≥3 cycles on one SHA).

**Method (read-only).** Host ms01. Dev tree and CURRENT both at `4f932b88a` (CURRENT → `4f932b88a-main-exact-phase2-20261004-202102`, symlinked 2026-10-04 20:21:55 ET). SQL ran under `SET TRANSACTION READ ONLY`. Also used: JSONL readers over persistent-state, `~/.local/state/tradeai`, `~/.cursor/approvals`, the wake store; `journalctl --user`; crontab; `/proc/<pid>/{cwd,environ}` (flag names only); `git log --since=2026-09-14`. No Telegram API calls, no sends, no LLM calls, no writes. No secrets and no chat ids are printed; chats appear as md5[:8] hashes, the same convention as the baseline.
**Labels.** **MEASURED**: observed now, with the source named. **DOCUMENTED**: from code, commit messages or docs, not exercised. **INFERRED**: reasoned from the two, and said so.
**Window.** "7d" means `created_at > now() − 7 days` at about 21:00 ET on 10-04, so roughly 09-27 21:00 to 10-04 21:00. 10-03 and 10-04 are a Saturday and a Sunday, so volume is lower on those days. The ledger starts on 09-05.

---

## 0. Headline: what changed since 2026-09-14

| # | Finding | Evidence | Label |
|---|---|---|---|
| H1 | **The Communications Editor is LIVE and is the de-facto outbound gate.** The host mode file says `live`; it was promoted 09-15 after a shadow day. 7d: 1,360 decisions, of which 822 sent and 538 not sent. The not-sent rows are **452 duplicate suppressions** (20 h fingerprint window; 0 duplicates were sent) and **102 holds**: 76 `cio_disagreement` and 26 `cio_decision_missing`. One shared receipts file serves the dev tree and CURRENT through a symlink. | `~/.config/tradeai/comms_editor_mode`; `persistent-state/data/runtime/comms_editor_receipts.jsonl` (6,367 rows since 09-14 16:07Z) | MEASURED |
| H2 | **Baseline break B2 is fixed going forward: SUPPRESSED now settles.** Every outbound SUPPRESSED row from 09-26 to 09-29 reads `UNSETTLED`. From 09-30 onward rows read `provider_settlement_state=SUPPRESSED`: 244 on 09-30, then 1,406, 1,556, 749 and 721 on the following days. 3,853 7d-window rows written before the fix are still UNSETTLED and were not backfilled. Owner stamp: `delivery_owner` is set on 9,243 of 9,245 7d outbound rows. | SQL `communication_events` ⨝ `communication_deliveries` by day; commit 8a41f0ac7 (09-30) | MEASURED |
| H3 | **Legacy sends now carry a Telegram message id.** 7d: SENT 504, of which 498 have a `provider_message_id`. LEGACY_DELIVERED is down to 210 rows, all without one. Of the 714 delivered rows, 498 (**69.7%**) carry a provider id; the baseline figure was 27 of 32 SENT, and 0 on the legacy path. | SQL; commits afe311fe3, 6a9c32b11 (09-22) | MEASURED |
| H4 | **Volume exploded, and it is router-suppressed noise.** 7d outbound events: **9,245** (baseline 758), about 1,400–1,670 per weekday. 8,529 (**92.3%**) are SUPPRESSED. Of the suppressed rows, **5,216** are one body: "🏥 Health Inspector [DEGRADED]" (`hermes_health_inspector`, about 745 a day). Next come "SYSTEM HEALTH: Telegram Bot Daemon — MISSING" (460), "ATP REVIEW ALERT" (319 + 78) and "TRADE CANCELLED — <sym> (pullback macd reversal)" (≥433 across six symbols). | SQL `left(short_summary,45)` grouped | MEASURED |
| H5 | **The gateway share fell further, to 0.16%.** 7d: 15 gateway-owned events (`notify_material_change`; 9 SETTLED, **6 SENT but UNSETTLED**) out of 9,245. CANARY is still set only on the portfolio-server drop-in and the two material-change cron lines (`CANARY_CLASSES=ops`). | systemd drop-in `32-comms-gateway-mode.conf`; crontab L996, L1050; SQL | MEASURED |
| H6 | **Subject tagging and chrome leaks.** 39.8% of subject-tagged editor receipts (317 of 796, 7d) carry at least one non-company tag. Tier 1 is the set fixed on 10-04: `ET`, `API`, `MNDY` (120 receipts). Tier 2 is word-tokens still unfiltered: `PRICE`, `ALERT`, `OI`, `NONE`, `OFF`, `LIVE`, `MORE`, `PR` (213 receipts). 235 of the 317 were sent with the wrong tags. The ET/API fix (2bf2d458b) and the Monday→MNDY fix (a1db4a039) reached CURRENT only at 20:21 ET on 10-04. Since then there are 6 receipts and none carry a chrome tag (too few to call it proven). | receipts `subjects[]`; `_AMBIGUOUS_WORDS` in `scripts/lib/comms_editor.py` L389-L397 | MEASURED / INFERRED (tier-2 classification is judgement) |
| H7 | **Active Trader scalp-alert exemption: deployed, not yet exercised.** `is_active_trader_scalp_alert` drops the `cio_decision_missing` hold only for bodies headed `ACTIVE TRADER · SCALP ALERT` that also carry `ADVISORY ONLY — NOT AN ORDER`. A CIO disagreement still rewrites or holds. 7d receipts with `at_scalp_cio_missing_exempt`: **0**. One live AT scalp alert exists: SOUN, 10-04 22:57Z, `message_class=active_trader_scalp_alert`, SETTLED with a provider id. It took the soft-block path (`rewrote:go_to_watch:SOUN`, CIO stance annotation), not the exemption. It also carried the `MNDY` chrome tag four minutes before a1db4a039 was committed. | `comms_editor.py` L408-L421, L797-L818; receipts; SQL | MEASURED |
| H8 | **Guard grant requests run end to end over Telegram: the first closed communication loop in family E.** `~/.cursor/approvals/remote_requests.json` (the baseline found this file absent) holds 200 requests, 171 in 7d: **132 APPROVED via `telegram_button`**, 39 SUPERSEDED. Request→approve latency p50 **8 s**, p90 128 s. Scopes: release-write 88, git-push 46, service 15, maintree 8, cron 6, telegram 4. Each tap is persisted as an operator turn `gapprove:<id>` (159 in 7d). The editor never holds these requests (`is_operator_approval_request`). | file counts (no codes printed); SQL | MEASURED |
| H9 | **Baseline break B10 is fixed: the CIO bot and the poller both run CURRENT.** `cio_telegram_bot.py --loop` (started 20:22:05) and `run_telegram_callback_poller.py --daemon` (20:22:01) both have cwd `4f932b88a`. The 409 Conflicts continue at 2–6 a day in the poller log (09-25 → 10-04: 5, 5, 6, 5, 2, 3, 2, 3, 6, 4). | `/proc/<pid>/cwd`; `CURRENT/logs/telegram_callback_poller.log` | MEASURED |
| H10 | **The CIO outbox recorded 1,694 fake confirmations.** `operator_notification_outbox.jsonl` on 09-26: 2,933 ENQUEUED by `cio_run_worker`; on 09-26/27, 1,731 CLAIMED+CONFIRMED. Of those confirmations, **1,694 carry `external_message_id` = the literal string "None"**; 37 carry real ids. The journal shows 345 runs with `delivered_count=5`. 1,204 ENQUEUED notifications have no CLAIMED event and no EXPIRED/CANCELLED terminal. 7d: 8 real enqueue→confirm cycles. | jsonl; `journalctl -u tradeai-cio-delivery` | MEASURED; "confirmed without a send" INFERRED |

---

## E1 · OUTBOUND MESSAGE

### (a) Purpose, actors, stores
- **Purpose** (unchanged): deliver each producer finding once, on the right chat, with links and subject identity; prove arrival with a provider id; roll held items into a digest.
- **Producers, 7d** (`communication_events.producer`, MEASURED): `telegram_alert.send_telegram` 9,223 · `notify_material_change` 15 · `telegram_alert.send_telegram_document` 5 · `send_watchpool_maturity_alerts` 1 · `crawl_v3_dashboard` 1. Every row has `message_class=ops`, except 1 `active_trader_scalp_alert`.
- **Chokepoints** (DOCUMENTED, in call order):
  1. `telegram_alert.send_telegram` → legacy router (`telegram_alert_router`).
  2. `telegram_transport.deliver_text` → `comms_editor.edit/commit` → Telegram.
  3. The CIO stance gate (`scripts/lib/cio_telegram_stance_gate.py`) runs for investment-shaped sends: `send_telegram_proposal_alert`, `screener_go_alerts`, `maria_outbound_gate`, `publisher_stance_gate`.
- **Stores (MEASURED counts):**
  - `communication_events`: OUTBOUND 69,707 all-time, 9,245 7d, 851 24h.
  - `communication_deliveries`: SUPPRESSED 67,140 · LEGACY_DELIVERED 1,482 · SENT 961 · RESERVED 643 · FAILED 8.
  - `telegram_outbox` 7d: `telegram ok=t` 82, `reports_archive ok=f` 515.
  - `comms_editor_receipts.jsonl` (3.2 MB) and `comms_editor_ledger.json`.
  - `cio_telegram_stance_holds.jsonl`: 4,945 rows, dual-written to `~/.local/state/tradeai/` and `persistent-state/data/cio/`. These are two inodes with identical size; this is by design (`_hold_write_targets`).
  - `operator_notification_outbox.jsonl`: 6,962 events.

### (b) State machines
- **ChannelDelivery** values are unchanged (`delivery.py`). Present in 7d (MEASURED): SUPPRESSED 8,529 · SENT 504 · LEGACY_DELIVERED 210 · RESERVED (outbound) 2. FAILED: 8 all-time, the last on 09-10, never retried.
- **Settlement × status, 7d outbound (MEASURED):**

| delivery status | settlement | owner | n |
|---|---|---|---|
| SUPPRESSED | SUPPRESSED | legacy | 4,676 |
| SUPPRESSED | UNSETTLED | legacy | 3,853 (all before the 09-30 fix) |
| SENT | SETTLED | legacy | 489 |
| LEGACY_DELIVERED | UNKNOWN_LEGACY | legacy | 210 |
| SENT | SETTLED | gateway | 9 |
| SENT | UNSETTLED | gateway | 6 (contradiction) |
| RESERVED | UNSETTLED | null | 2 |

- **Editor decision** (`CommsEditorDecision@v1`, MEASURED 7d): `mode=live` on 1,360 of 1,360. `held_reason` ∈ {null 1,258, `cio_disagreement` 76, `cio_decision_missing` 26}; there were no `operator_product_invalid` holds in 7d. `duplicate_of` was set on 452 rows; `send` was true on 822.
- **Stance gate hold** (`CioTelegramStanceHold@v1`): `held_reason` ∈ {`cio_stance_conflict` 2,623, `cio_decision_missing` 2,322} all-time. Hold rows by `as_of` date: 1,780 / 1,496 / 1,504 on 09-21..09-23, then ≤65 a day after a dedupe landed. **63 hold rows have `as_of` ≥ 09-27.** No hold row has been written since 10-02 17:46 ET (file mtime). `review_status` values: deduped 63, source_not_eligible 56, created 30, skipped_observe_only 5. `cio_stance_review_requests.jsonl` has 31 rows, the last on 09-30.
- **Normalization runtime:** `config/operator_alert_policy.yaml` `runtime_mode: "SHADOW"`; it was `"OFF"` at baseline.

### (c) End-to-end flow (as measured)
```
producers ─▶ send_telegram ─▶ legacy router ── suppress (92.3%) ─▶ ledger SUPPRESSED (settles since 09-30)
                                   │                                └▶ telegram_outbox reports_archive (515/7d) ─▶ p1_digest (0 */4)
                                   ▼ pass
                      deliver_text ─▶ COMMS EDITOR (live)
                         ├ duplicate (20 h) ─▶ not sent (452/7d)
                         ├ CIO disagreement ─▶ soft-block rewrite GO→WATCH, or hold (76/7d)
                         ├ CIO decision missing ─▶ hold (26/7d) ── AT scalp alert exempt (0 uses)
                         ├ guard approval request ─▶ never held
                         └ send: HTML + links + GUID footer + subject tags (39.8% chrome-contaminated)
                                   ▼
                      Telegram ─▶ message_id ─▶ ledger SENT+pmid (498/504)
material change ─▶ gateway CANARY ─▶ SENT (15/7d; 6 left UNSETTLED)
cio_run_worker ─▶ NotificationOutbox ─▶ cio_delivery_worker */5 ─▶ CONFIRMED (1,694 with id "None", 09-26/27)
```

### (d) Iterations and loops
- **Editor duplicate ledger:** a durable per-chat fingerprint with a 20 h window. This replaces the per-process router caches as the effective dedupe. It closes: 452 duplicates blocked, 0 leaked (MEASURED).
- **Stance soft-block rewrite** (09-20 C2): 2 rewrites in 7d (receipts `rewrote:*`).
- **Hold → CIO review request** (09-23 "missing stance forces review"): 30 `created` all-time; the last request was 09-30. The loop exists, but it is quiet (MEASURED).
- **RESERVED expiry:** still absent. 117 outbound RESERVED rows, all older than 1 day, the newest 09-29 (MEASURED).
- **CIO outbox retry/expiry:** 1,204 notifications enqueued and never claimed, with no EXPIRED event (MEASURED).

### (e) Questions a message asks
- Unchanged from baseline for sentinel, material-change and CIO product messages.
- New: **AT scalp alerts** ask "act intraday?"; the body says "advisory only". No reply path is joined.
- New: **guard grant requests** ask "approve?" and get an answer by button (see H8). This is the only message kind whose answer is joined back to its request.

### (f) Live measurements (MEASURED, 7d)
- **Outbound per day (ET):** 09-27 578 · 09-28 1,484 · 09-29 1,554 · 09-30 1,401 · 10-01 1,514 · 10-02 1,667 · 10-03 805 · 10-04 775.
- **Delivered:** 714 ledger rows (SENT 504 + LEGACY_DELIVERED 210); 70% carry a provider id. The editor `send=true` count is 822; its scope also covers CIO bot and desk sends.
- **Editor sends per day:** 16 · 168 · 175 · 139 · 124 · 128 · 35 · 37. **Holds per day:** 0 · 14 · 11 · 17 · 27 · 25 · 2 · 6.
- **Editor `cio_decision_missing` holds** were the word-token `MORE` (24: 12 on 10-01, 12 on 10-02), `NFLX` 2 and `T` 2. All 24 MORE holds are false holds on an English word. The fix shipped in 7ed3d90a4 (10-03), and no MORE hold appears after 10-02.
- **Top `cio_disagreement` holds:** `B` 29, `D` 20, FCNTX 12, ACHV 11, RKLB 10, PFLT 10, DTE 6. The single letters B and D passed the single-letter filter. The receipts do not keep the text, so whether each was a marked `$B` or a leak cannot be verified (UNVERIFIED).
- **Subject GUID** is set on 7,227 of 9,245 outbound events (78%).
- **`causation_id`** is set on 9,245 of 9,245, and equals `event_id` on all 9,245. It is self-referential, so it carries no linkage. `reply_to_event_id` is set on 0.
- **`command_center_url` column:** 0 of 9,245. Links are now added by the editor in the body footer: `links` on 774 of 1,360 receipts.

### (g) Failure paths
1. **Router noise flood.** One health-inspector body accounts for 56% of all outbound ledger rows. The ledger grows about 1,500 rows a weekday for nothing the operator sees.
2. **Chrome tags.** Tier 2 word-tokens are still unfiltered. The `_AMBIGUOUS_WORDS` list is hand-maintained, and each new leak needs a code change.
3. **Pre-fix UNSETTLED backlog.** 3,853 SUPPRESSED rows in the 7d window, plus older ones, were never backfilled.
4. **The gateway carries only material change**, and 6 of its 15 7d sends are left SENT but UNSETTLED.
5. **CIO outbox:** fake "None" confirmations and 1,204 enqueued notifications with no terminal state.
6. **Outbound RESERVED (117)** never expire.

### (h) Maturity per stage

| Stage | 09-14 | 10-04 | Evidence |
|---|---|---|---|
| Producing event | L2 | L2 | volume up 12×, dominated by one noisy producer |
| Classification/policy | L1 | L2 | the router suppresses 92%; the normalization runtime is SHADOW |
| Dedup | L1 | **L3** | durable editor fingerprint: 452 blocked, 0 duplicates sent |
| CIO agreement gate | — | **L2** | live holds and rewrites; false holds on `MORE` fixed 10-03 |
| Reservation | L1 | L1 | inbound stubs and outbound RESERVED rows never expire |
| Send (legacy) | L2 | L2 | 70% of delivered rows carry a provider id |
| Send (gateway) | L1–L2 | L1 | 0.16% share; 6 UNSETTLED SENT |
| Settlement | L1 (regressed) | **L2** | SUPPRESSED settles since 09-30; owner stamped; no backfill |
| Subject identity / links | L1 | L2− | GUID on 78%; 39.8% of tagged receipts carry chrome |
| Digest roll-up | L2 | L2 | p1_digest runs every 4 h ("delivered 4/6 suppressed messages") |
| Lifecycle monitoring | L1 | L1 | CIO outbox confirms without an id; nothing alarms on it |

### (i) Target and exit conditions
- **Target** (unchanged): one path; persisted policy decision; gateway send; SETTLED with a provider id; terminal SUPPRESSED; an expirer.
- **Exits today (MEASURED):**
  - SETTLED (legacy 489, gateway 9)
  - SUPPRESSED (now terminal)
  - UNKNOWN_LEGACY (210)
  - UNSETTLED (pre-fix rows, plus 6 gateway rows)
  - RESERVED (never exits)
  - editor-held and duplicate rows (live in receipts only)

**Delta since 2026-09-14:** the editor is live (dedupe, CIO gate, links, GUIDs); SUPPRESSED settles; the legacy provider id is kept; CIO decision cards (b5c541007) and portfolio-aware held alerts (a7ec067d6) shipped; material-change notice v2 pages only actionable items and adds a daily digest (13f35ffcd); AT scalp alerts are LIVE with the missing-CIO exemption. Regressions: noise volume ×12, and gateway share 2.5% → 0.16%.

---

## E2 · INBOUND OPERATOR REPLY

### (a) Purpose, actors, stores
- **Purpose:** unchanged.
- **Actors (MEASURED):**
  - Main-bot poller `run_telegram_callback_poller.py --daemon`: cwd CURRENT; env `ATOMIC_INBOUND_ENABLED=1`, `CIO_REPLY_ENABLED=1`, `CIO_TELEGRAM_CONVERSE=1`.
  - CIO bot `cio_telegram_bot.py --loop`: cwd CURRENT; `CIO_TELEGRAM_CONVERSE=1`.
- **Stores (MEASURED):**
  - INBOUND `communication_events`: 528 all-time, 146 7d.
  - `communication_inbound_checkpoint`: advanced 10-04 20:19:31.
  - `communication_inbound_quarantine`: 27, unchanged since 09-08, `resolved=false` on all.
  - `communication_agent_consumption_receipts`: 501.
  - `operator_conversation_turns`: 751 rows (676 operator, 75 agent).
  - `cio_operator_pending_replies.jsonl`: 18 rows.
  - Wake store: 1,731 wakes.

### (b) State machines
- **AtomicInbound and checkpoint:** unchanged (DOCUMENTED).
- **Receipts:** `purpose=operator_turn_intake` on 162 of 162 in 7d; `policy_decision` null; **`wake_id` set on 0 of 501**.
- **Pending reply:** open 9 · fulfilled 7 · expired 2. The baseline had 1 open and 1 expired; a `fulfilled` exit is now observed.

### (c) Flow
```
operator tap/msg ─▶ poller (CURRENT) ─▶ claim ─▶ INBOUND event (+ RESERVED stub ✗) ─▶ tag ─▶ turn ─▶ receipt (no wake_id ✗) ─▶ checkpoint
   gapprove:<id> tap ─▶ guard_remote_approval ─▶ remote_requests.json APPROVED (p50 8 s) ✓ closed loop
CIO bot ─▶ converse ─▶ agent turn (event_id NULL ✗, not in ledger ✗)
hourly wake ─▶ prior_operator_turn_ids: newest included turn is from 09-25 ✗ (turns after 09-25 not seen)
```

### (d) Iterations
- **Wake intake has partly improved.** The 504 wakes in 7d carry operator turns in 186 cases, over 30 distinct turn ids. These include turns 214 and 430–478 (09-13 → 09-25), where the baseline carried only turn 115. Turn 115 (09-11) is still replayed in 168 of 504 wakes (MEASURED).
- **No genuine text turn after 09-25 has reached a wake.** The newest genuine operator text turn is id 698, on 10-02 (MEASURED).

### (e) Questions
- **Guard approvals:** answered and closed (H8).
- **Desk questions:** genuine operator text turns since 09-14, excluding fixture chat `9ea9c185` and callbacks, number **23** in total: 09-14 6 · 09-22 8 · 09-23 4 · one each on 09-25, 09-27, 09-29, 09-30 and 10-02. Telegram desk use is low (MEASURED).

### (f) Measurements (7d, MEASURED)
- **INBOUND events:** `callback_query` 143, `telegram_command` 3.
- **Identity on INBOUND:** `bot_id` non-empty 0 of 146 · `provider_message_id` 0 · `reply_to_event_id` 0 · `subject_guid` 1.
- **Inbound delivery stubs** are still auto-created: 526 inbound RESERVED (513 older than 1 day); 146 in 7d.
- **Inbound settlement:** UNSETTLED 407, UNKNOWN_LEGACY 117.
- **Operator turns 7d:** 184 rows over 149 distinct messages; 159 are `gapprove` callbacks (136 distinct).
- **Fixture chat `9ea9c185`** is still being written: 22 rows over 3 message ids in 7d, 79 since 09-14, the last on **10-03 17:47 ET**. Baseline break B6 is open.
- **Agent turns:** 9 in 7d, the last on 10-02; 0 carry `event_id`, so desk replies are still not in the ledger (B4 open).
- **409 Conflicts:** 2–6 a day (H9).

### (g) Failure paths
1. Inbound identity is still missing: bot_id, provider id and reply linkage are 0.
2. Inbound RESERVED stubs keep accumulating.
3. Receipts are never stamped with `wake_id`.
4. Fixture rows still leak into production turns.
5. Desk replies stay outside the communication ledger.
6. The second consumer behind the 409s is still unidentified.
7. The 27 quarantine rows are unresolved after 26 days.

### (h) Maturity per stage

| Stage | 09-14 | 10-04 | Evidence |
|---|---|---|---|
| Receive (main bot) | L2 | L2 | CURRENT, checkpoint advancing; 409s continue |
| Receive (CIO bot) | L1 | **L2** | on CURRENT after promote |
| Atomic intake/checkpoint | L2 | L2 | — |
| Event identity | L1 | L1 | bot_id, provider id and reply_to all 0 |
| Turn persistence | L1 | L1 | fixture chat still writing |
| Consumption receipt | L1 | L1 | wake_id 0 of 501 |
| Reply ledgering | L0 | L0 | agent turns have event_id 0 |
| Pending fulfilment | L1 | L2 | 7 fulfilled |
| Wake intake | L0 | **L1** | 30 turns reached wakes, but none after 09-25 |
| Approvals via Telegram | L1 | **L3** | 132 button approvals, p50 8 s, closed |

### (i) Target and exits
- **Target:** unchanged from the baseline.
- **Exits today:** checkpoint committed · guard request APPROVED or SUPERSEDED · pending fulfilled or expired · agent turn written. Ledger closure of a reply is still absent.

**Delta since 2026-09-14:** the CIO bot is no longer stale; guard approvals are live and closed; pending replies can be fulfilled; some turns reach wakes (lineage, 4f9c2fa88). Unchanged: identity gaps, inbound stubs, no wake_id, fixture leak, unledgered replies.

---

## E3 · PLATFORM-MONITOR ALERT (incl. PLATFORM_AVAILABILITY)

### (a) Purpose, actors, stores
- **Detectors** (systemd timers): `check_data_source_health`, `check_gap_resolution`, `check_operator_answer_quality`, `check_expected_services`, data plausibility, and a new `served_copy_split` detector.
- **State files** under `~/.local/state/tradeai/*_last_alert.json` now hold `fingerprint`, `conditions`, `metrics`, `today_metrics` and `updated_at`.
- **Other stores:** `alert_events` (9,638 rows), `alert_incidents` (108), `alert_occurrences` (19,495, SHADOW).

### (b) State machine (DOCUMENTED from journals and commits 7c4b99f6f, f425e345f)
```
DETECT ─▶ fingerprint == last ? ─▶ suppressed (heartbeat after 360 min if still unhealthy)
          changed               ─▶ send ─▶ "accepted by the platform" ─▶ alert_event with message_id
          worsened/improved     ─▶ "reversed recorded"
          empty                 ─▶ "recovered recorded" ─▶ alert_event resolved
```
- `alert_events.lifecycle_state`: active 9,065 · resolved **531** · acknowledged **42**. The baseline had 0 resolved and 2 acknowledged. `acknowledged_by` is null on all 42.
- `alert_incidents`: open 108, resolved 0, `synthetic=false`. Sums: notified 1,267, suppressed 18,228. 25 incidents first seen in 7d; 0 resolved; 0 acknowledged.
- `alert_occurrences` runtime is SHADOW: 27 escalations and 11 resolutions were flagged, but delivery does not act on them.

### (c)–(d) Flow and iterations (MEASURED 7d)
**`check_data_source_health` journal:** 39 accepted · 128 suppressed-unchanged · 26 reversed · 12 heartbeats · 1 recovered · 1 healthy. Latest run (20:27 ET): checked=18, off=3, idle=5.
- 26 reversals in a week means the source set flaps.
- The heartbeat is a reminder stage, which was L0 at baseline.

**PLATFORM_AVAILABILITY-tagged outbound:** **64 delivered** (47 SENT with a provider id, 17 LEGACY_DELIVERED); the last was 10-04 18:27. The baseline had 4 in 7d.

**Other sentinel tags:** DATA_INTEGRITY 23 delivered · OPERATIONAL 2.

**`alert_events` from `check_data_source_health.py`, 7d:** 36 active and 3 resolved; all 39 carry a `telegram_message_id`.

**Other detectors:**
- answer quality: 15 accepted, 194 healthy, 127 suppressed, 9 heartbeats, 2 recovered, 4 reversed.
- gap resolution: 1 accepted, 335 suppressed. Its state file was last written 09-28.

**`alert_events` sources, 7d:** `research_topics_api` 1,844 and `hermes_score_alerts` 1,173 are still a write-only pile (active, no resolution).

### (e) Questions
- Unchanged: no acknowledge command or button; operator replies are not joined.
- Closure comes from the detector (recovered/resolved), now recorded in `alert_events`.

### (f) Measurements: see (c)–(d).
**Mean time to recovery:** derivable in principle from `alert_events.created_at → resolved_at` for `check_data_source_health.py` (55 resolved all-time). It was not computed here.

### (g) Failure paths
1. Flapping: 26 reversals in 7d produce about 9 PLATFORM_AVAILABILITY messages a day.
2. Incidents never resolve (108 open, 0 resolved); the normalization runtime is SHADOW.
3. Acknowledgement has no actor (`acknowledged_by` null on 42).
4. Research and hermes alert_events (3,000+ in 7d) have no consumer.

### (h) Maturity per stage

| Stage | 09-14 | 10-04 |
|---|---|---|
| Detect | L2 | L2 |
| Fingerprint/dedup | L2 | L2 (flaps) |
| Alert body | L2 | L2 |
| Delivery proof | L1 | **L2** (message_id on alert_events) |
| Re-alert/reminder | L0 | **L2** (360-min heartbeat, 12 + 9 in 7d) |
| Resolution | L2 | **L3** (resolved recorded in alert_events; 531 all-time) |
| Escalation | L0 | L1 (SHADOW flags only) |
| Acknowledgement | L0 | L0–L1 (42 acks, no actor) |
| Incident record | L0 | L1 (108 open, 0 resolved) |

### (i) Target and exits
- **Target:** unchanged (incident with ack and MTTR).
- **Exits today:** accepted (with message_id) · suppressed-unchanged · heartbeat · reversed · recovered (with resolved alert_event).

**Delta since 2026-09-14:** heartbeat reminders, delivery proof, recovery written to `alert_events`, normalization moved OFF → SHADOW, and an incidents table that fills but never closes.

---

## E4 · EMAIL / DRIVE PUBLICATION

| Flow | 10-04 measurement (MEASURED) | 09-14 | Delta | L |
|---|---|---|---|---|
| Gmail daily digest (`notification_log channel=gmail`) | 17 `sent` rows in 21 days. Weekdays about 07:30 ET; missing 09-18 to 09-20 and 10-03; three rows at weekend evening times (09-26 18:59, 09-27 20:38, 10-04 20:40 ET). Still outside `communication_events`: the ledger's non-telegram rows are the 10 smoke rows from 09-05. | 1 a weekday, silent from 09-11 | resumed; not ledgered | L2− |
| Docs → Drive (`~/logs/drive-sync.log`) | Hourly. Latest 01:05Z: 0 uploaded, 2,775 unchanged, 0 failed. Runs with failures since 09-14: 09-23 (4, 2) and 09-25 (1). | L2 | stable | L2 |
| Google token (`mcporter-token-refresh`) | **failed** at the latest run (10-04 20:36 ET: "gcloud auth print-access-token returned empty"). 223 failures in 7d; first failure in the 14-day journal 09-20 22:03. | failed 09-13; re-auth 09-14 | **failed again since ~09-20** | L1 |
| Other `notification_log` telegram types | `alert_fatigue_meta` 25, `stop_confirmation_reminder` 15, `api_credits_depleted` 14 (last 10-02) | — | measured | L2 |

**Delta since 2026-09-14:** the Gmail digest resumed; the Google token refresh has failed again for about 14 days with no re-auth; email is still not in the communication ledger.

---

## 5. Family maturity

| Lifecycle | 09-14 | 10-04 | Weakest stage now |
|---|---|---|---|
| E1 Outbound | L1 | **L2** | gateway L1 · reservation L1 · noise flood |
| E2 Inbound | L1 (intake L2, effect L0) | **L1–L2** | reply ledgering L0 · identity L1 |
| E3 Platform alert | L1–L2 | **L2** | incidents L1 · ack L0–L1 |
| E4 Email/Drive | L1–L2 | L1–L2 | Google token L1 |

**Family E score: 2.0 / 5**, against about 1.3 / 5 on 09-14 (scoreboard "L1"). The step up comes from three things: the live editor (dedupe L3), settlement repair, and guard approvals as the first closed loop (L3). Three things hold it at 2: no stage is L4, gateway ownership is 0.16%, and replies never reach the ledger or a wake.

## 6. Top 5 risks
1. **Noise flood hides real alerts and bloats the ledger.** 9,245 outbound rows a week; 56% are one "Health Inspector [DEGRADED]" body suppressed by the router. A real health page is one row among about 1,300 a day (H4).
2. **The CIO outbox records delivery without a send.** It holds 1,694 CONFIRMED events with `external_message_id="None"` and 1,204 enqueued items with no terminal state. Any metric built on CONFIRMED overstates CIO reach (H10).
3. **Wrong subject tags on 40% of tagged messages.** Footers and links attach ET, API, PRICE, ALERT, OI and similar to unrelated companies. CIO-gate decisions keyed on those tags can hold or rewrite on noise; the 24 `MORE` holds on 10-01/02 are proven cases (H6).
4. **The operator→cognition loop is still open.** `wake_id` is 0 of 501 receipts; no genuine operator text turn after 09-25 has reached a wake; desk replies are unledgered; fixture chat rows are still written to production turns (E2).
5. **The Google credential has been failing about 14 days with no alert in the comms path.** Drive and Calendar tooling depend on it (E4). Second-order: 108 open alert incidents and 27 quarantined inbound updates have no resolver.

## 7. Top 5 recommendations
1. **Throttle at the source.** Make `hermes_health_inspector` / health_agent send on state change only. Do not write a ledger row for router-suppressed repeats of an identical fingerprint; keep a count instead. Target: under 200 outbound rows a weekday.
2. **Make the CIO outbox honest.** Treat a CONFIRMED event without a real `external_message_id` as `RELEASED` or `SUPPRESSED` with a reason. Expire the 1,204 orphans to EXPIRED. Point the `cio-delivery` lane at real provider ids.
3. **Default subject tags to "must be marked".** Accept a tag only when it is the primary symbol, `$SYM`, `ticker: SYM`, or a registry-confirmed company name. Retire the hand-maintained `_AMBIGUOUS_WORDS` list. Measure the chrome rate daily from the receipts (now 39.8%; target under 2%).
4. **Close inbound identity and wake intake.** Stamp `bot_id`, the provider message id and `reply_to_event_id`; stop reserving delivery stubs for INBOUND rows; stamp `wake_id` on receipts; ledger desk replies as OUTBOUND with `causation_id` set to the inbound event, not to itself. Block fixture chat `9ea9c185` from production writes.
5. **Turn on the incident lifecycle and re-auth Google.** Move `alert_runtime_mode` SHADOW → ACTIVE for sentinel classes, so incidents resolve when a detector recovers. Add an acknowledge button joined to `alert_incidents`. Damp data-source flapping with a minimum dwell time before "reversed". The operator re-runs `gcloud auth login` for the mcporter token (operator-only action).

## 8. Reproduction (read-only)
- **SQL:**
  - `communication_events` ⨝ `communication_deliveries`: status × settlement by day; `left(short_summary,45)` for suppressed rows.
  - Also queried: `communication_agent_consumption_receipts`, `communication_inbound_checkpoint`, `communication_inbound_quarantine` (`quarantined_at`), `operator_conversation_turns` (`occurred_at`, `md5(chat_id)`), `alert_events`, `alert_incidents`, `alert_occurrences`, `telegram_outbox`, `notification_log`, `trade_approvals`, `alert_dispatch_log`.
- **Files:**
  - `persistent-state/data/runtime/comms_editor_receipts.jsonl`
  - `~/.config/tradeai/comms_editor_mode`
  - `~/.local/state/tradeai/{cio_telegram_stance_holds,cio_stance_review_requests}.jsonl` and `*_last_alert.json`
  - `persistent-state/data/cio/{operator_notification_outbox,cio_operator_pending_replies}.jsonl`
  - `~/.cursor/approvals/remote_requests.json` (status, timestamps and scope only)
  - `trade-ai-state/persistent_wake/state/wakes.jsonl`
  - `~/logs/drive-sync.log`
  - `CURRENT/logs/{telegram_callback_poller,p1_digest,alert_dispatcher}.log`
- **Journals:** `tradeai-data-source-health`, `tradeai-gap-resolution`, `tradeai-operator-answer-quality`, `tradeai-cio-delivery`, `tradeai-cio-telegram`, `mcporter-token-refresh`.
- **Commits cited:** 008adbe8f, 4a761002d, 7c4b99f6f (09-15/16) · 3ed39e23e, 089e9723a (09-18) · 09a29ce62 (09-20) · f425e345f (09-21) · afe311fe3, 6a9c32b11, 3e647b793, 43f9fc47e (09-22) · 515b025b3, 4f9c2fa88 (09-23) · 13f35ffcd (09-24) · 681ef5a51 (09-29) · 8a41f0ac7, b5c541007 (09-30) · 7ed3d90a4 (10-03) · 89a508083, 2bf2d458b, a1db4a039 (10-04).
