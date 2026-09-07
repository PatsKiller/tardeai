# Phase 2 — Delivery reconciliation: the 26 RESERVED rows, the settle path, and the dark inbound plane

```
Date:                 2026-09-05
Campaign:             pre-persistent-agent-truth-closeout-20260905
Posture:              READ_ONLY_ADVISORY — investigation only, no comms code touched
Investigating branch: wt/cc-header-final @ 0553ee6e0a2915e42254dc0bfd5251f91aecafcf
Serving release:      f88853e89-main-exact-phase2-20260905-135414 (CURRENT symlink)
Owning lane:          wt/comms-gateway-phase0 — every fix below belongs to that session
DB observed:          trade_ai @ localhost, SELECT-only, default_transaction_read_only=on
Measurement wall:     2026-09-05T15:54:18-04:00
```

**No file outside this one was modified. No test was executed. No row was written.**

---

## 0 · CORRECTION TO THE BRIEF, FIRST

The task brief's ground truth was **8 SENT / 44 RESERVED / 5 LEGACY_DELIVERED**. That is
no longer the state and I am not going to write a report against numbers I did not
measure.

| bucket | brief (earlier today) | measured 15:54 | delta |
|---|---:|---:|---:|
| SENT | 8 | **8** | 0 |
| RESERVED | 44 | **26** | **−18** |
| LEGACY_DELIVERED | 5 | **23** | **+18** |
| FAILED | 0 | **0** | 0 |
| **total** | **57** | **57** | **0** |

Total is unchanged, so nothing was inserted or deleted: **18 pre-existing RESERVED rows
were transitioned to LEGACY_DELIVERED between the brief's snapshot and mine.** The
mechanism is identified in §1.4 and it is not a backfill — it is an accident of
idempotency, and it is the single most important thing in this document, because
**the ledger now asserts a delivery disposition for 18 rows on the strength of a
different send, hours later, that nobody checked the result of.**

Everything below is measured at 15:54 unless stated.

---

## 1 · THE 26 RESERVED ROWS

### 1.1 Where they come from — the reservation is unconditional

`scripts/lib/comms/client.py:289` — the last statement of `publish_communication`:

```python
return _reserve_deliveries(result, channels)
```

`scripts/lib/comms/client.py:98-121` — `_reserve_deliveries` loops the resolved
channels and calls `attach_delivery_reservation`, which is
`scripts/lib/comms/delivery.py:347-349` → `reserve_delivery(...)` →
`scripts/lib/comms/delivery.py:303-344`, which mints `status="RESERVED"`
(`delivery.py:330`) and persists it.

There is no flag, no mode gate, no opt-out. **Any successful `publish_communication`
of an OUTBOUND event creates a RESERVED row.** Channel resolution defaults to
`["telegram"]` for OUTBOUND (`client.py:239-245`), so a producer that names no channel
still gets a Telegram reservation.

### 1.2 Where settlement is supposed to happen — two call sites, total

`grep -rn "settle_delivery" --include=*.py` over non-test code returns exactly **two**
call sites:

1. `scripts/lib/comms/channel_adapters.py:423` (`status="FAILED"`) and `:430`
   (`status="SENT"`) — inside `send_via_gateway`, reached only when `deliver=True`
   **and** the mode gate and the Telegram class allowlist both pass.
2. `scripts/telegram_alert.py:265` (`status="LEGACY_DELIVERED"`) — inside
   `_best_effort_comms_publish`.

That is the whole settlement surface. There is **no reaper, no sweeper, no refund path,
no TTL, no expiry job**. `EXPIRED` and `CANCELLED` are legal transitions out of
RESERVED (`delivery.py:57-59`) and **nothing in the repository ever writes them** —
confirmed by grep: zero non-test occurrences of `status="EXPIRED"` or
`status="CANCELLED"`.

### 1.3 Why settlement never runs — three named mechanisms

The brief asks whether the settle call is *missing*, *unreachable*, or *failing
silently*. Measured answer: **all three, in different rows.** They do not collapse into
one bucket.

**(a) UNREACHABLE — `send_via_gateway` abandons its own reservation on every early
return.** `send_via_gateway` reserves at `channel_adapters.py:326-333` (or reuses the
caller's id at `:317-321`) and then has four exits that return **before** the settle
block at `:421-437`:

| line | condition | `base["error"]` | reservation left |
|---|---|---|---|
| `channel_adapters.py:367-371` | `if not deliver:` | *(none — `ok=True`)* | **RESERVED forever** |
| `channel_adapters.py:376-382` | mode not in `_DELIVERABLE_MODES` | `delivery_blocked_mode` | **RESERVED forever** |
| `channel_adapters.py:385-393` | telegram class not allowlisted | `delivery_blocked_allowlist` | **RESERVED forever** |
| `channel_adapters.py:308-310` | channel unsupported | `unsupported_channel` | *(reserve not yet reached)* |

The first row is the worst, because it is the **default**: `deliver: bool = False` at
`channel_adapters.py:274`. The documented, intended, everyday call leaves a permanent
in-flight row. The second and third are the fail-closed gates working correctly and
then leaking a phantom — a *deliberate non-delivery* recorded as *in flight*. The
honest terminal for a blocked send is `SUPPRESSED` or `CANCELLED`; neither is written.

This is not theory. Six RESERVED rows carry `subject_key` values minted by the
channel-adapter suite and name the exact gates:
`test:channel_adapters:blocked`, `:tg_canary_empty`, `:tg_active_empty`,
`:require_id`, `:email`, `:tg_record`.

**(b) MISSING — 42 producer scripts publish and never settle, on top of a send that
already happened.** `publish_communication(CommunicationEvent(...))` appears at
**44 call sites across 42 files** under `scripts/` (measured). The shape is identical
in every one I sampled, and it is a *second* publish stacked on a send that already
went out:

`scripts/pipeline_watchdog.py:39-57`
```python
        from telegram_alert import send_telegram as _tg
        prefix = '🚨' if urgent else '⚠️'
        text = f"{prefix} WATCHDOG: {message}"
        _tg(text)                                   # ← alert already sent (and, since
                                                    #   today, already settled LEGACY)
        try:
            ...
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(   # ← second event, auto-reserved
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="pipeline_watchdog", subject_key="ops:pipeline_watchdog",
                ...
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
```

Same shape verbatim at `scripts/protection_alerts.py:99-114`,
`scripts/system_health_alerts.py:155-170`, `scripts/portfolio_alerts.py:499-516`,
`scripts/proposal_alerter.py:36-47`, `scripts/open_trade_monitor.py:289-297` and
`:326-336`. Note `protection_alerts.py:100` and `system_health_alerts.py:156` both
capture `ok = send_telegram(...)` and then **discard it** — the outcome the ledger most
needs is measured and thrown away one line before the publish that would have carried it.

Consequence, and it is visible in the data: one operator alert produces **two ledger
events with no link between them** — one settled `LEGACY_DELIVERED` by
`telegram_alert`, one stranded `RESERVED` by the producer. The AAPL stop alert is the
worked example:

| delivery_id | producer | status | reserved_at |
|---|---|---|---|
| `dlv_01a06fde-4a45-77b9-b764-5e1278ea7346` | `telegram_alert.send_telegram` | LEGACY_DELIVERED | 00:40:34.107 |
| `dlv_01a06fde-4a51-728a-bca7-533bd3c5ced2` | `open_trade_monitor` | **RESERVED** | 00:40:34.129 |

Both carry `🛑 STOP_HIT_CLOSE AAPL — stop hit at 182.40`. 22 milliseconds apart. One
message, two ledger rows, two different dispositions, no correlation id joining them.
`correlation_id`, `causation_id` and `parent_event_id` all exist on
`communication_events` and are unused by this pattern.

**RESERVED will therefore grow without bound**, one row per producer alert, for as long
as those 44 call sites fire. The count is only 26 today because the tables were created
today and most of the 42 producers have not run yet. This is the load-bearing forecast
in this document.

**(c) FAILING SILENTLY — three swallow points.**

- `channel_adapters.py:436-437`: a settle exception is appended to `base["errors"]` and
  the call returns `ok=True` anyway if the provider succeeded. No caller in the repo
  inspects `errors` on success.
- `telegram_alert.py:279-280`: the entire `_best_effort_comms_publish` body is wrapped
  in `except Exception: return`. A settle failure *inside* the inner loop is now
  printed (`telegram_alert.py:274-277`, landed 12:47:39 today in `b236b7fef`) but a
  failure of the publish itself is still silent.
- `delivery.py:336-343`: `reserve_delivery` catches **any** DB exception and falls back
  to `_persist_memory`. The reservation then exists only in that process's `_MEM` dict.
  A settle from any other process raises `delivery_not_found` (`delivery.py:421-433`);
  a settle from the same process takes the memory branch (`delivery.py:397-418`) and
  **returns success having written nothing durable**. Exit code 0, no row.

### 1.4 The 18 rows that moved — settlement by idempotency collision

The 18 RESERVED→LEGACY_DELIVERED transitions in §0 were **not** a reconciliation run.
Measured:

```
   updated_at        | n  |   reserved_at range
 2026-09-05 15:37    |  1 | 2026-09-05 00:42:43
 2026-09-05 15:39    |  2 | 2026-09-05 00:16:18
 2026-09-05 15:48    |  3 | 2026-09-05 00:31:38
 2026-09-05 15:49    | 15 | 2026-09-05 00:40:32 … 00:40:34
```

Every one of them is a **15-hour gap between reservation and settlement**, and the
bodies are the same probe corpus (`📋 P1 digest — probe`, `probe: harness self-test`,
`C1 probe: transport chain`, `⚠️ AUTO-RETRY PAUSED …`). What happened:

1. A probe suite re-sent the same message bodies at 15:37–15:49.
2. `publish_communication` deduped on the content-derived idempotency key
   (`client.py` `_persist_db` → `ON CONFLICT (idempotency_key) DO NOTHING`) and
   returned the **00:40 event_id**.
3. `_reserve_deliveries` → `reserve_delivery` → `_persist_db`
   (`delivery.py:236-299`) hit `ON CONFLICT (idempotency_key) DO NOTHING` at `:260` and
   returned the **00:40 delivery row**.
4. `telegram_alert.py:265` settled *that fifteen-hour-old row* to `LEGACY_DELIVERED`.

So `reserved_at = 00:40:34`, `completed_at = 15:49:17`, and the row now asserts that
the 00:40 attempt was delivered. **It asserts nothing of the kind.** It records that a
*different* send of the same text, at 15:49, reached the legacy path.

And the legacy path's own outcome was never checked. `telegram_alert.py:413-432`:

```python
        ok = _legacy_send(message, bypass_router, ...)
        _best_effort_comms_publish(message, message_class=mc)   # :420 — ok ignored
        return ok
...
        ok = _legacy_send(message, bypass_router)
        _best_effort_comms_publish(message, message_class=mc)   # :430 — ok ignored
        return ok
    _best_effort_comms_publish(message, message_class=mc)       # :432 — result ignored
```

`_best_effort_comms_publish` is called **unconditionally** on all three branches. It
never receives `ok`, never receives `result["delivered"]`. `publish_operator_message`
returns `delivered: False, suppressed: True, reason: "legacy_router_suppressed_or_unconfigured"`
when the router digests or drops the message (`telegram_alert.py:176-181`) — and the
ledger writes `LEGACY_DELIVERED` regardless.

> **`LEGACY_DELIVERED` is currently an unverified assertion.** It means "the legacy
> code path was entered", not "the operator received this". 23 of 57 rows carry it,
> 0 of 23 carry a `provider_message_id`, and all 23 carry
> `provider_coordinates = {"delivery_owner": "legacy"}` and nothing else.

This is the same defect class as the `delivery_owned = False` constant in
`docs/_findings/comms_delivery_owned_contradiction_2026-09-05.md`: a value that was
true under a premise, rendered as a live fact after the premise expired. Here the
premise is "the legacy path delivers", which the legacy path itself contradicts on
every suppressed alert.

### 1.5 The 26, grouped, with age and evidence

Measured 15:54. `age_h` from `reserved_at`. **`provider_message_id` is NULL on all 26;
`sent_at` is NULL on all 26; `completed_at` is NULL on all 26; `error_taxonomy` is NULL
on all 26.** There is no provider evidence of any kind attached to any RESERVED row.

**Group A — test-suite residue written into production (16 rows, 15.5–15.6 h)**

| producer | channels | n | subject_key shape |
|---|---|---:|---|
| `ops.test` | telegram 3, slack 2, email 1 | 6 | `test:channel_adapters:*` |
| `ops.watchdog` | telegram 2, slack 2, email 1 | 5 | `system:watchdog` |
| `ops.health` | telegram 4 | 4 | `system:pipeline`, `symbol:RKLB` |
| `p` | email 1 | 1 | `k` / summary `s` |

All 16 reserved within a 101-second window, 00:16:18–00:17:59. The producer strings,
subject keys and event types (`pipeline_stale`, `symbol_alert`, `health_digest`,
`health_debug`) appear **only in `tests/`** — `tests/test_communications_portal.py:64,66,144`,
`tests/test_comms_subject_memory.py:110,119,121,131,133`,
`tests/test_comms_delivery_ledger.py:59,214,239`,
`tests/test_comms_channel_adapters.py`. This is the exact pollution class the campaign
brief warns about, already realised.

*Mitigation already landed, and it is worth stating because it changes the residual
risk:* every comms test file that calls `publish_communication` now stubs `_db_conn`.
Measured `grep -c '_db_conn", lambda: None'` per file — `test_communications_portal.py`
8, `test_comms_delivery_ledger.py` 3, `test_comms_channel_adapters.py` 3,
`test_comms_subject_memory.py` 3, `test_comms_inbound.py` 4. The four files showing 0
(`test_comms_curation.py`, `test_comms_enforcement_gate.py`, `test_comms_shadow_compare.py`,
`test_comms_vocabulary.py`) were checked individually and **none calls
`publish_communication`**. So the 16 rows are historical residue from before the stubs,
not an ongoing leak. **The campaign's do-not-run-tests constraint remains correct** —
I did not run them — but the mechanism that produced these rows is closed.

**Group B — gateway smoke/soak probes (4 rows, 15.66–15.68 h)**

| delivery_id | producer | mode at write |
|---|---|---|
| `dlv_01a06fc0-6b49-74f0-b464-56cbb0a21393` | `comms_live_cutover_smoke` | OFF |
| `dlv_01a06fc0-6b5a-764d-9a68-16e2d446349f` | `comms_live_cutover_smoke` | OFF |
| `dlv_01a06fc1-465b-74b8-be25-d5423d06b1a0` | `comms_shadow_soak` | OFF |
| `dlv_01a06fc1-dadb-760a-adb2-5db596c71d22` | `comms_shadow_soak` | SHADOW |

`grep -rn` for both producer strings across the entire repository returns **zero hits**.
These were minted by an uncommitted scratch probe. Under OFF and SHADOW the gateway
never performs provider I/O by construction (`channel_adapters.py:41`,
`:376-382`), so these are provably non-deliveries.

**Group C — real production alerts, gateway-unowned, pre-F1 (4 rows, 3.2–15.1 h)**

| delivery_id | reserved_at | class | body head |
|---|---|---|---|
| `dlv_01a06fdf-dfc7-733c-ad1b-df3682c78f66` | 00:42:17 | operator_alert | `⚠️ AUTO-RETRY PAUSED … health:execution_health` |
| `dlv_01a06fdf-e01b-74f3-b4f4-32143ad88e2b` | 00:42:18 | operator_alert | `⚠️ AUTO-RETRY PAUSED … health:data_quality:schw` |
| `dlv_01a0704b-a501-76da-b162-64c872f3dd64` | 02:40:00 | operator_alert | `🚨 Health Agent: UNHEALTHY — 64/100` |
| `dlv_01a070dd-4f42-73e2-855f-60213b85fdfb` | 05:19:07 | operator_alert | `⚠️ Health Agent: DEGRADED — 68/100` |

All four predate `614744cc6` *"fix(comms): settle legacy stubs (F1)"* (committed
2026-09-05 10:59:55 −0400). At the time these were written the settle call at
`telegram_alert.py:265` **did not exist**. Cause: *missing*, since remedied for new
rows. These four are the only genuinely-operator-facing RESERVED rows in Group C.

**Group D — deliberate negative control, post-F1 (1 row, 3.2 h)**

`dlv_01a07270-0c85-72f9-a0c1-82f26019df6f`, 12:39:00, `message_class=report`,
`gateway_mode_at_write=CANARY`, body `🧪 GATEWAY CANARY NEGATIVE CONTROL — report class
should NOT …`. The allowlist correctly refused it: owned classes are `["ops"]`, so
`telegram_class_allowed("CANARY", "report")` is False and `send_via_gateway` returned at
`channel_adapters.py:385-393` **without settling**. This is mechanism (a) caught in the
act on live data, 100 minutes after F1 landed. Six minutes later, at 12:45:54, a
*report*-class row **did** settle to LEGACY_DELIVERED — so the difference is which entry
point was used, not whether F1 was deployed.

**Group E — production stop-path alert (1 row, 15.14 h)**

`dlv_01a06fde-4a51-728a-bca7-533bd3c5ced2`, `open_trade_monitor`, `ops:open_trade`,
`🛑 STOP_HIT_CLOSE AAPL`. Mechanism (b), worked through in §1.3.

**Structural anomaly (1 row).** `dlv_01a06fc9-9e54-73a9-90ff-a6b953feb236` (slack,
`ops.watchdog`) is the only delivery in the table with **no matching
`communication_outbox` row**. 56 of 57 deliveries join; this one does not. Cause
**unmeasured** — a partial write, or a path that reserves without the outbox insert.
Flagged, not diagnosed.

---

## 2 · REAL TERMINAL DISPOSITION OF EACH RESERVED ROW

The standing instruction is: classify with provider evidence, or leave
LEGACY_DELIVERED/UNKNOWN, never fabricate. **There is no provider evidence attached to
any of the 26.** So the classification below rests entirely on *code-path proof of
non-delivery*, which is a weaker and different warrant, and I mark it as such. They do
not collapse to one bucket.

| group | n | real disposition | warrant | evidence class |
|---|---:|---|---|---|
| A — test residue | 16 | **NEVER ATTEMPTED** | test fixtures with `_db_conn` stubs absent at the time; no provider call is reachable from the paths that minted them | code-path proof |
| B — smoke/soak | 4 | **NEVER ATTEMPTED** | OFF/SHADOW cannot reach `_provider_send` (`channel_adapters.py:376-382`) | code-path proof |
| D — negative control | 1 | **SUPPRESSED BY POLICY** | allowlist refusal at `channel_adapters.py:385-393`; the refusal is the intended outcome | code-path proof |
| C — pre-F1 operator alerts | 4 | **UNKNOWN — probably delivered by legacy** | `send_telegram` was entered, so `_legacy_send` ran; but its return value was discarded (`telegram_alert.py:420,430,432`) and no provider id was captured | **no evidence — do not upgrade** |
| E — `open_trade_monitor` | 1 | **UNKNOWN — probably delivered by legacy** | `open_trade_monitor.py:289` gates on `if not _send(...): return`, so the publish at `:293` only runs when `_send` returned truthy — but `_send` is `send_telegram`, whose contract is *accepted*, not *delivered* (`telegram_alert.py:358-366`) | **weak evidence — do not upgrade** |

**On Group C and E specifically.** The tempting move is to mass-settle these five to
`LEGACY_DELIVERED` on the argument that "the legacy path ran". That argument is exactly
the one §1.4 shows to be unsound, and `send_telegram`'s own docstring
(`telegram_alert.py:358-366`) says so in terms: *"It deliberately does NOT mean 'a
Telegram message was sent'"*. Five rows have no honest terminal available from inside
the database.

Two external sources could settle them and neither was consulted here (both are
**unmeasured**, and reading either is arguably outside a READ_ONLY_ADVISORY brief):

- **Telegram Bot API `getUpdates`/history** — cannot retrieve the bot's own outbound
  message history; no read path exists. Rules this out as a reconciliation source
  in principle, not merely in practice.
- **The alert router's own store** (`alert_outbox` / `notifications.outbox`) — reachable
  and would say whether the router suppressed or emitted each of those five bodies at
  those timestamps. **This is the one lead worth pulling** and I did not pull it, because
  correlating it requires a join key the comms ledger does not currently write
  (§5, R-4).

Recommended: leave all five `UNKNOWN`. `UNKNOWN` is a legal terminal
(`delivery.py:57-58`) and its transition table `{"UNKNOWN": frozenset()}`
(`delivery.py:65`) makes it a permanent sink — which is the correct semantics for
"we will never know". **Writing it is still an operator decision** (§5).

### 2.1 The SENT rows are not exempt

The brief did not ask, but the same evidence question applies and the answer changes
what "8 SENT" means.

| delivery_id | channel | provider_message_id | producer |
|---|---|---|---|
| `dlv_01a0705c-8979-72bd-87d4-9423ca85fd0f` | telegram | `50581,50582` | `telegram_alert.send_telegram` |
| `dlv_01a0726c-cba0-77b9-8a25-14246ac45d85` | telegram | `50613,50614` | `telegram_alert.send_telegram` |
| `dlv_01a06fc8-1567-7034-bdfc-ba46bf3dea8b` | whatsapp_meta | `wamid.test_1` | **`ops.test`** |
| `dlv_01a06fc8-15b4-76c7-a2f5-4c5591391eed` | telegram | *(null)* | `ops.test` |
| `dlv_01a06fc8-1525-76af-8793-5edcc3996bcb` | email | *(null)* | `ops.test` |
| `dlv_01a06fc8-1552-72f4-9093-df6cc993ed3d` | whatsapp_twilio | *(null)* | `ops.test` |
| `dlv_01a06fd5-1472-756f-8ba7-89945f1b4a27` | telegram | *(null)* | `telegram_alert.send_telegram` |
| `dlv_01a06fd5-9800-7554-b090-5cafe1cce255` | telegram | *(null)* | `telegram_alert.send_telegram` |

Read carefully:

- The brief's *"provider_message_id present on only 3 rows"* is right, but **one of the
  three is `wamid.test_1`** — a test stub, not a provider id. **Genuinely
  provider-evidenced sends: 2**, both Telegram, both at 02:58 and 12:35 today, both
  carrying real `message_ids` and `chat_ids` in `provider_coordinates`.
- **4 of 8 SENT rows have producer `ops.test`** — test residue, same 00:16:18 window as
  Group A.
- The two `telegram_alert` SENT rows at 00:30:30 and 00:31:04 are the CANARY and ACTIVE
  cutover proofs. They have no `provider_message_id` because the capture wiring landed
  at 02:52:28 in `92b0b9d00`. Their delivery is attested elsewhere (the operator's
  Telegram, per the `delivery_owned` finding); the *ledger* does not attest it.

**Net: zero organic production traffic has been gateway-delivered with provider
evidence.** All four evidenced or near-evidenced sends are the comms session's own
smoke messages. That is the honest state of the CANARY.

---

## 3 · THE INBOUND PLANE

### 3.1 The code exists and is correctly shaped

`scripts/lib/comms/inbound.py` (498 lines) implements persist-before-process properly:

- `build_inbound_event(update)` — `inbound.py:78`
- `claim_update(update_id)` — `inbound.py:271-281`; `already_processed = uid <= offset`
- `commit_checkpoint(update_id)` — `inbound.py:284-323`; the module docstring at
  `inbound.py:23-26` calls it *"the **only** durable offset write"* and that is true
- `quarantine_callback(...)` — `inbound.py:372-422`
- Tables: `_CHECKPOINT_TABLE` / `_QUARANTINE_TABLE` at `inbound.py:49-50`

The poller consumes it correctly. `scripts/run_telegram_callback_poller.py`:

- `:99` — `offset = inbound["get_checkpoint_offset"]()` when the gateway half imports
- `:133-136` — claim, `continue` on replay
- `:138-139` — **publish before any handler runs**
- `:141-158` — on publish failure: quarantine and `continue` **without** advancing the
  checkpoint, so Telegram re-delivers
- `:171`, `:178`, `:184`, `:231` — `commit_checkpoint(uid)` only after processing

The ordering contract is right. This is good code.

### 3.2 It has never executed against real traffic — measured

```
communication_inbound_checkpoint  : 0 rows
communication_inbound_quarantine  : 0 rows
communication_events, INBOUND     : 2 rows
```

Both INBOUND events are test residue — `producer=telegram_command_handler`,
`subject_key=chat:123:cmd:status` and `chat:1:cmd:status`, created 00:17:59, same
window as Group A. Neither came from the poller.

The poller **is** live: PID 2163523, started 13:56, running
`.../f88853e89-main-exact-phase2-20260905-135414/scripts/run_telegram_callback_poller.py --daemon`
— i.e. the release that contains Wave C (`0bff6e51b`, merged in `f88853e89`). Scheduled
`*/2 * * * *` via `/home/johnclaw/.config/tradeai/bin/run_telegram_callback_poller_current.sh`,
flock-guarded, plus a `*/5` watchdog. `PYTHONPATH` is set to `CURRENT:CURRENT/scripts`
by the launcher, so `from scripts.lib.comms.inbound import ...` at
`run_telegram_callback_poller.py:39-45` resolves — **the silent
`except Exception: return None` degradation at `:55-56` is not being taken.**

So: the code is deployed, the process is up, and the path has produced zero rows.

### 3.3 What is missing for persist-before-process to be *provable*

**M-1 — no evidence has ever been generated.** Zero checkpoint rows, zero quarantine
rows, zero poller-authored INBOUND events. The claim is unfalsifiable from durable
state. Nothing is broken; nothing is proven. Until the operator presses one inline
button, the plane is asserted, not observed.

**M-2 — the checkpoint was never seeded from the legacy offset. This is the live
hazard.** The legacy file still holds the real position:

```
CURRENT/data/portfolios/state/.telegram_callback_offset  = 113864091   (mtime Aug 28 13:48)
CURRENT/data/portfolios/state/communication_inbound_checkpoint.json    = does not exist
communication_inbound_checkpoint (DB)                    = 0 rows
```

`get_checkpoint_offset()` (`inbound.py:248-268`) reads the DB, finds no row, returns
`0`. The poller then requests `offset = 0 + 1 = 1`
(`run_telegram_callback_poller.py:101-105`). `claim_update` compares against 0, so
`already_processed` is False for **every** update Telegram returns, and
`handle_callback_query` re-executes it — including `/ptapprove` and the inline
approve/reject buttons.

Two nuances that bound this, stated so the fix is not over-scoped: Telegram drops
updates already confirmed by a prior `getUpdates` offset ack, and the old poller
confirmed through 113864091, so the server-side queue should be empty for those. The
exposure is therefore limited to updates that arrived while no poller was confirming.
`OFFSET_FILE` (`run_telegram_callback_poller.py:28`) is still written at `:154` on the
legacy branch, so the two mechanisms have silently diverged since the cutover. **The
seed is a one-line insert and it requires operator authority** (§5, R-6).

**M-3 — both checkpoint functions degrade silently to a file that does not exist.**
`get_checkpoint_offset` `inbound.py:262-268` and `commit_checkpoint`
`inbound.py:311-323` each swallow every DB exception and fall through to
`_read_checkpoint_file()` / `_write_json_atomic`. A transient DB blip silently
**resets the offset to 0** and re-arms M-2, with no log line and no alert. This is the
same shape as `delivery.py:336-343`.

**M-4 — mode divergence between two live processes.** Measured from `/proc/*/environ`:

```
pid 2162719 (portfolio-server): COMMS_GATEWAY_MODE=CANARY
                                COMMS_GATEWAY_CANARY_CLASSES=ops
                                COMMS_GATEWAY_CANARY_CHATS=6993102664,8797974247
pid 2163523 (callback poller):  (no COMMS_* variables at all)  → resolves OFF
```

The launcher sources `~/.config/tradeai/cio-telegram.env` and the rebuild `.env`
(`run_telegram_callback_poller_current.sh:17-19`) and neither carries `COMMS_*`. Inbound
publish still works in OFF, so nothing is currently broken — but the two halves of the
gateway disagree about what mode the gateway is in, and that will matter the moment any
inbound path becomes mode-sensitive.

**M-5 — `getUpdates` HTTP 409 storm, 13:16–13:18.** The release log shows ~30 consecutive
`getUpdates failed: HTTP Error 409: Conflict` before the 13:55/13:56 restarts. Two
consumers were competing for one bot token. Quiet since 13:56 with a single flock holder.
Root cause **unmeasured**; the crontab carries a comment recording the same class of
incident on 2026-08-26.

### 3.4 Live health endpoint

`GET localhost:7777/api/v2/communications/health` (measured 15:54) now reports
`delivery_owned: true`, `owned_classes: ["ops"]`, `banner: "Ledger-backed · gateway owns
Telegram classes: ops"`. **The `delivery_owned` constant defect from
`comms_delivery_owned_contradiction_2026-09-05.md` is fixed and serving.** Confirmed
independently here.

One caveat for anyone tempted to use it for reconciliation: the same payload carries
`"deliveries_total_sample": 1`. It samples a single row. **It cannot see the 26 RESERVED
and must not be used as the reconciliation surface** (§5, R-5).

---

## 4 · NON-TELEGRAM CHANNELS

**Confirmed as asked: `scripts/lib/comms/channel_adapters.py:274` reads
`deliver: bool = False`.** The module docstring at `:1-4` states the same contract:
*"Default is SHADOW record-only (`deliver=False`)."*

Which channels are truthfully dark, and in what sense — three different senses, and
conflating them would misstate the risk:

| channel | reachable? | provider evidence? | truthful status |
|---|---|---|---|
| `telegram` | **yes** | **yes** — `channel_adapters.py:213-215` returns real `message_ids` + `chat_ids` | **LIVE, evidenced.** Sole gateway-owned channel; class-gated to `ops` under CANARY |
| `email` | code path exists | **no** | **DARK by absence of a caller** |
| `slack` | code path exists | **no** | **DARK by absence of a caller** |
| `whatsapp_twilio` | code path exists | **no** | **DARK by absence of a caller** |
| `whatsapp_meta` | code path exists | yes — returns `message_id` (`:250-254`) | **DARK by absence of a caller** |

**Dark by absence of a caller.** `grep -rn "send_via_gateway"` over non-test code returns
call sites in exactly one file: `scripts/telegram_alert.py:299,303,326`. **No production
code ever calls `send_via_gateway` for email, slack, whatsapp_twilio or whatsapp_meta.**
The four non-Telegram adapters are unreachable from production regardless of the
`deliver` default. Their only exercise is `tests/test_comms_channel_adapters.py`
(12 call sites) — which is precisely where the four `ops.test` SENT rows and six
`ops.test` RESERVED rows in the production table came from.

**And a second defect, which is why "dark" is the merciful reading.** Three of the four
adapters fabricate success (`channel_adapters.py:216-242`):

```python
    if channel == "email":
        from scripts.alerting import send_email
        send_email(subject or ..., body, html=..., attachments=...)
        return {"ok": True, "provider_message_id": None}      # :223 — return value discarded

    if channel == "slack":
        from scripts.alerting import send_slack
        send_slack(body)
        return {"ok": True, "provider_message_id": None}      # :229 — same

    if channel == "whatsapp_twilio":
        from scripts.alerting import send_whatsapp
        send_whatsapp(body)
        return {"ok": True, "provider_message_id": None}      # :235 — same
```

`ok: True` is a **literal**. The underlying adapter's return value is never inspected.
Any failure short of a raised exception settles the row `SENT`
(`channel_adapters.py:429-435`) with a NULL `provider_message_id`. Only `whatsapp_meta`
(`:236-260`) checks `result.get("ok")` and propagates a real id.

That is the same constant-presented-as-a-live-fact shape as `delivery_owned = False`
and as `LEGACY_DELIVERED`-without-a-check. **Three instances of one defect class in one
subsystem.** If these channels are ever wired to a caller, `SENT` on email, slack and
whatsapp_twilio will be unfalsifiable from the first message onward. Fixing it *before*
the first caller is far cheaper than reconciling afterwards — which is the whole lesson
of §1.

---

## 5 · PROPOSALS — NOT IMPLEMENTED

Nothing in this section was built. All of it belongs to `wt/comms-gateway-phase0`.

### 5.1 The three channel contract tests

Named to the defect each one would have caught, not to the function they cover. All
three run with `_db_conn` stubbed to `None` — the harness at
`tests/test_comms_telegram_canary_active.py:20-35` already provides it, so **no new
scaffolding and no database**.

**CT-1 — `test_every_reservation_reaches_a_terminal_or_is_refunded`.**
For each of the four `send_via_gateway` early-return paths — `deliver=False`
(`channel_adapters.py:367`), `delivery_blocked_mode` (`:376`),
`delivery_blocked_allowlist` (`:385`), and the success path — assert that the delivery
named by `result["delivery_id"]` is **not** left `RESERVED` in
`memory_delivery_snapshot()`. Blocked sends must land `SUPPRESSED`; `deliver=False` must
land whatever terminal the owning session decides record-only deserves.
*Fails today on three of four paths.* This is the test whose absence produced 21 of
the 26 rows.

**CT-2 — `test_no_channel_adapter_reports_ok_without_provider_evidence`.**
Parametrise over `SUPPORTED_CHANNELS` (`channel_adapters.py:29-32`). Monkeypatch each
underlying sender (`scripts.alerting.send_email`, `send_slack`, `send_whatsapp`,
`cio_whatsapp_egress.send_whatsapp_text`, `telegram_alert._raw_send_telegram_result`) to
report failure, then assert `_provider_send` returns `ok=False` and the row settles
`FAILED`, not `SENT`. *Fails today for email, slack, whatsapp_twilio* — the literal
`return {"ok": True, ...}` at `:223`, `:229`, `:235`. Second half: with the sender
succeeding, assert `SENT` implies a non-null `provider_message_id` **or** an explicit
`provider_evidence: "none"` marker, so an unevidenced SENT is never silently
indistinguishable from an evidenced one.

**CT-3 — `test_legacy_delivered_requires_a_legacy_delivery_result`.**
Monkeypatch `telegram_alert._legacy_send` to return `False`, call `send_telegram`, and
assert the resulting delivery is **not** `LEGACY_DELIVERED`. Then monkeypatch
`publish_operator_message` to return `{"delivered": False, "suppressed": True,
"reason": "legacy_router_suppressed_or_unconfigured"}` and assert the same.
*Fails today on both* — `telegram_alert.py:420,430,432` call
`_best_effort_comms_publish` unconditionally. Requires threading the send outcome into
`_best_effort_comms_publish`, which is the minimal honest fix for §1.4.

A fourth is worth considering but is a lint, not a unit test:
**CT-4** — assert that no file under `scripts/` both calls `send_telegram` (or
`send_telegram_document`) **and** calls `publish_communication` in the same function.
That is the 42-file double-publish pattern; it is greppable, and a lint would stop it
spreading to producer 43.

### 5.2 Reconciliation procedure

Read-only through step 4. **Steps 5 and 6 write and are operator-gated.**

1. **Freeze the denominator.** `SELECT status, count(*) FROM communication_deliveries
   GROUP BY 1` with a wall-clock stamp, into a dated artifact. §0 exists because this
   was not done before.
2. **Partition by cause, not by status.** For every RESERVED row, join
   `communication_events` and bucket by `(producer, gateway_mode_at_write, channel)`
   into: test residue · uncommitted-probe residue · policy-suppressed · pre-fix
   orphan · double-publish orphan. The five buckets have five different correct
   terminals. §1.5 is a worked instance.
3. **Attach provider evidence where it exists.** For Telegram, `provider_coordinates`
   already carries `message_ids` and `chat_ids` on evidenced rows
   (`channel_adapters.py:206-219`). **A row with no provider evidence is never upgraded
   past UNKNOWN.**
4. **Attempt the one external correlation available.** Join Group C/E bodies and
   timestamps against the alert router's own store (`alert_outbox` /
   `notifications.outbox`) to see whether the router emitted or suppressed each. This is
   **unmeasured here** and is the only lead that could move those five rows off UNKNOWN.
   Read-only.
5. **Settle, per bucket, with the warrant recorded in the row.** `SUPPRESSED` for
   policy-blocked; `CANCELLED` for test and probe residue; `UNKNOWN` for the five with
   no evidence. Write the warrant into `provider_coordinates`
   (e.g. `{"reconciled_by": "...", "warrant": "code_path_proof|provider_evidence|none",
   "run_id": "..."}`) so the next reader can tell a reasoned settlement from a fabricated
   one. All legal transitions out of RESERVED (`delivery.py:57-59`). **OPERATOR
   AUTHORITY.**
6. **Seed the inbound checkpoint** from `.telegram_callback_offset` (113864091) before
   the next real callback arrives. One row, `id=1`. **OPERATOR AUTHORITY** — see R-6.
7. **Re-measure and publish the delta**, including rows that moved *for reasons other
   than the reconciliation* (§0 is why this step is not optional).

### 5.3 Requires operator authority

| id | action | why it is operator-only |
|---|---|---|
| **R-1** | Any UPDATE to `communication_deliveries.status` | Writes a delivery disposition into the financial-advisory notification ledger. A wrong settlement is a fabricated delivery record — AGENTS.md §0.7, §0.9 |
| **R-2** | Deleting or archiving the 20 test/probe residue rows | AGENTS.md §0.6 — never delete. Settling them terminal is reversible-in-spirit; removing them is not |
| **R-3** | Changing `deliver` defaults, allowlists, or `COMMS_GATEWAY_MODE` | Widens live egress; belongs to the cutover runbook, not to reconciliation |
| **R-4** | Adding `correlation_id` linkage between producer shadow-publishes and `telegram_alert` publishes | Schema/semantics change to the ledger; also the prerequisite for step 4 |
| **R-5** | Raising `deliveries_total_sample` or adding a RESERVED-age gauge to `/health` | Changes an operator surface; and a new gauge must not repeat the `delivery_owned` mistake of publishing a constant |
| **R-6** | Seeding `communication_inbound_checkpoint` from the legacy offset | Directly governs whether operator button-presses can be re-executed. Highest-consequence single row in this document |
| **R-7** | Exporting `COMMS_*` into the poller's environment (M-4) | Changes the runtime mode of a live process |

---

## 6 · WHAT THIS DOCUMENT DOES NOT KNOW

Marked explicitly, per AGENTS.md §1 responsibility 1.

- **Whether any of the five Group C/E alerts reached the operator.** Not determinable
  from the comms ledger. The router store (§5.2 step 4) is **unmeasured**.
- **Why `dlv_01a06fc9-9e54-…` has no `communication_outbox` row** while 56 of 57 do.
  **Unmeasured.**
- **Why the 12:39 negative control did not settle while the 12:45 report-class row did.**
  §1.5 Group D gives the mechanism (`channel_adapters.py:385-393` vs the
  `telegram_alert` path) but I did not reproduce it. **The specific entry point used at
  12:39 is unmeasured.**
- **What minted the `comms_live_cutover_smoke` and `comms_shadow_soak` rows.** Zero
  repository hits; an uncommitted scratch probe. **Unmeasured.**
- **Root cause of the 13:16–13:18 HTTP 409 storm.** **Unmeasured.**
- **Whether CI covers any of this.** I did not run or read the CI configuration.
  **Unmeasured.**
- **Nothing here was reproduced by executing a comms test.** Per the campaign
  constraint, `tests/test_communications_portal.py` and
  `tests/test_comms_subject_memory.py` were **read, never run**. Every claim above rests
  on SELECT-only SQL, source reading, `/proc` inspection, and one unauthenticated GET to
  a local health endpoint.

---

## 7 · THE ONE-PARAGRAPH VERSION

The delivery ledger reserves unconditionally and settles almost never. Reservation is
wired into `publish_communication` itself (`client.py:289`); settlement exists at two
call sites, and each of the four early returns in `send_via_gateway` — including the
`deliver=False` default at `channel_adapters.py:274` — abandons the row it just created.
On top of that, 42 producer scripts publish a *second* event after an alert has already
been sent and never settle it, so RESERVED grows one row per production alert forever.
The 18 rows that did settle since this morning settled by accident: a repeat probe hit
the idempotency key, resolved to a fifteen-hour-old row, and stamped it
`LEGACY_DELIVERED` — a status the code writes without ever checking whether the legacy
path delivered anything (`telegram_alert.py:420,430,432`). Five of the 26 remaining rows
are genuine operator alerts with no honest terminal available; they should stay UNKNOWN
until the router store is correlated. Telegram is the only live, evidenced channel, and
only 2 rows in the whole table carry real provider evidence — the other four adapters are
unreachable from production and three of them return a hardcoded `ok: True`. The inbound
plane is deployed, running, correctly ordered, and has produced zero rows; its checkpoint
sits at 0 while the legacy offset file holds 113864091, and closing that gap is one
operator-authorised insert.
