# Wave C — Communications Gateway, inbound half (implementation)

```
Status: DRAFT
as_of: 2026-09-05T11:45:00-04:00
Measured at: not measured (uncommitted worktree files; no commit SHA exists yet)
```

This documents the inbound half of Wave C. It builds on the Phase 1–11 gateway
(`docs/architecture/communications-workspace.md`) and closes the inbound gap the
live attestation flagged as **PARTIAL**:

> *"Inbound command events — `operator_command` rows present (`inbound_7d`);
> full update_id/checkpoint quarantine not re-attested."*
> — `docs/audit/live-attest-2026-09-05.md`

---

## 1. What this wave built

| artifact | path | purpose |
|---|---|---|
| inbound module | `scripts/lib/comms/inbound.py` | build INBOUND events; durable update_id checkpoint; callback quarantine |
| migration | `migrations/2026_09_05_communication_inbound_checkpoint.sql` (+ `.down.sql`) | checkpoint + quarantine tables, additive only |
| tests | `tests/test_comms_inbound.py` | 13 tests, DB-isolated (file-backed path under `tmp_path`) |
| this doc | `docs/audit/wave-c-inbound-implementation.md` | record + poller-wiring proposal |

**No new `@v1` type was minted.** Inbound events reuse `CommunicationEvent@v2`
(§13.4). The checkpoint and quarantine are new *tables*, not new id types — they
are transport bookkeeping keyed by Telegram `update_id`, which is a provider
coordinate, not a Trade-AI identity.

---

## 2. The defect being fixed

The live poller advances its Telegram offset **before** processing each update
`[CODE]`:

```python
# scripts/run_telegram_callback_poller.py:95
for update in results:
    _save_offset(update["update_id"])   # durable write at the TOP of the loop
    # ... handle callback_query or message ...
```

Telegram never re-delivers an update whose `update_id` is at or below the
supplied `offset`. A crash between the offset write and the persist therefore
**permanently drops** that update, and the poller's own offset file asserts it
was done. This is the "offset advanced before processing" defect. The same shape
appears in the two sibling pollers:

- `scripts/telegram_reply_processor.py:88` — `_save_offset(results[-1]["update_id"] + 1)` after fetch, before processing.
- `scripts/cio_telegram_bot.py:96` — `_save_offset(int(uid))` before processing.

**The fix is a two-phase API** (not a moved line):

- `claim_update(update_id)` — read-only gate. Returns whether the update is
  already processed. **Performs no durable write**, so a crash here loses
  nothing.
- `commit_checkpoint(update_id)` — the *only* durable offset write, called after
  the CommunicationEvent is persisted. Monotonic and idempotent.

Replay-denial is a consequence of the checkpoint, not a separate side effect:
`is_update_already_processed(u)` is `u <= committed_offset`.

---

## 3. Public API (`scripts/lib/comms/inbound.py`)

| symbol | semantics |
|---|---|
| `build_inbound_event(update) -> CommunicationEvent` | INBOUND event; `event_type` `telegram_command` or `callback_query`; `message_class = normalize_message_class(update.get("message_class") or "operator_command")`; `retention_class = "inbound_7d"`; deterministic `subject_key = f"telegram:inbound:{chat_id}:{message_id}"`; `provider_coordinates` = `{chat_id, message_id, reply_to_message_id, callback_query_id, update_id, bot_id}` |
| `claim_update(update_id) -> ClaimResult` | `{update_id, already_processed, checkpoint_offset}` — no durable write |
| `commit_checkpoint(update_id) -> int` | advance committed offset to `max(offset, update_id)`; returns new offset |
| `get_checkpoint_offset() -> int` | highest persisted update_id; poller passes `offset + 1` to `getUpdates` |
| `is_update_already_processed(update_id) -> bool` | replay-denial helper / negative control |
| `quarantine_callback(reason, provider_coordinates, update_id, callback_query_id=None) -> dict` | record unresolved callback; idempotent on `update_id` |
| `list_quarantined(resolved=None) -> list[dict]` | quarantine rows, newest first |
| `reset_inbound_state()` | test helper; clears the file-backed store only |

**Durability layering.** The checkpoint and quarantine are stored in the DB
tables from the migration when reachable, and in a file under
`COMMS_INBOUND_STATE_DIR` (default `data/portfolios/state/`) otherwise. This
mirrors the `_db_conn()` best-effort pattern already used across
`scripts/lib/comms/`. The file-backed path is what the test suite exercises
(via a stubbed `_db_conn`), and it is the guarantee the defect fix depends on:
the committed offset survives process restarts without a database.

---

## 4. Migration

`migrations/2026_09_05_communication_inbound_checkpoint.sql` is **additive only**
— it creates two new tables and touches no broker/order/2FA/guardrail table:

- `communication_inbound_checkpoint` — single-row (`id = 1`), monotonic
  `committed_update_id BIGINT`.
- `communication_inbound_quarantine` — one row per unresolved callback,
  `UNIQUE (update_id)`, plus a partial index on pending rows.

`.down.sql` drops both tables in reverse order. Applying/downing/this migration
against production Postgres is **operator-gated** (deploy boundary).

---

## 5. Verification

### 5.1 Tests `[VERIFIED]`

Command:

```
python3 -m pytest tests/test_comms_inbound.py -q
```

Output:

```
.............                                                            [100%]
13 passed in 0.45s
```

Coverage (per the required pattern): build_inbound_event shape +
`provider_coordinates`; `claim_update` replay denial; `commit_checkpoint`
atomicity (crash-before-commit does not lose the update); quarantine of an
orphan callback; `normalize_message_class` reuse. The autouse fixture stubs
`client` / `delivery` / `subject_memory` / `inbound` `_db_conn` to `None` and
points `COMMS_INBOUND_STATE_DIR` at a fresh `tmp_path`, so the suite never
touches production Postgres.

### 5.2 Dry-run of checkpoint + quarantine `[VERIFIED]`

Command (read-only against Postgres — `_db_conn` forced to the file-backed
path; state written to `/tmp/wave_c_dryrun`):

```
python3 -c '
import sys, os, json
sys.path.insert(0, ".")
os.environ["COMMS_INBOUND_STATE_DIR"] = "/tmp/wave_c_dryrun"
import scripts.lib.comms.inbound as ib
ib._db_conn = lambda: None
ib.reset_inbound_state()
ev = ib.build_inbound_event({"update_id": 9001,
    "message": {"message_id": 42, "chat": {"id": 123456}, "text": "/status"},
    "bot_id": "987654321"})
print("event_id:", ev.event_id)
print("subject_key:", ev.subject_key)
print("provider_coordinates:", json.dumps(ev.provider_coordinates, sort_keys=True))
claim = ib.claim_update(9001)
print("claim.already_processed(before commit):", claim.already_processed)
ib.commit_checkpoint(9001)
print("claim.already_processed(after commit):", ib.claim_update(9001).already_processed)
row = ib.quarantine_callback("unresolved_callback:no_matching_proposal",
    {"chat_id": "123456", "message_id": 43, "callback_query_id": "cb-9", "update_id": 9002}, 9002)
print("quarantine_row:", json.dumps(row, sort_keys=True, default=str))
print("quarantined_count:", len(ib.list_quarantined()))
'
```

Output:

```
event_id: 01a0723f-5504-7407-a3d9-f8e348b64962
subject_key: telegram:inbound:123456:42
provider_coordinates: {"bot_id": "987654321", "callback_query_id": null, "chat_id": "123456", "message_id": 42, "reply_to_message_id": null, "update_id": 9001}
claim.already_processed(before commit): False
claim.already_processed(after commit): True
quarantine_row: {"callback_query_id": "cb-9", "provider_coordinates": {"callback_query_id": "cb-9", "chat_id": "123456", "message_id": 43, "update_id": 9002}, "quarantine_id": null, "quarantined_at": "2026-09-05T15:45:48.292883+00:00", "reason": "unresolved_callback:no_matching_proposal", "resolution_note": null, "resolved": false, "resolved_at": null, "update_id": 9002}
quarantined_count: 1
```

The `already_processed` flips only at `commit_checkpoint` — the point of the
fix — and the quarantine row is durable and observable.

---

## 6. Poller-wiring proposal

### Single inbound consumer

**`scripts/run_telegram_callback_poller.py`** is the single inbound consumer.

Rationale:

- It is the only poller that already requests **both** `callback_query` and
  `message` in one `getUpdates` call
  (`allowed_updates=["callback_query","message"]`,
  `scripts/run_telegram_callback_poller.py:72`), so it sees the full inbound
  surface in one place.
- It already dispatches inline button callbacks (`handle_callback_query`) and
  text commands (`/pt*`, `/stop*`, `/atm`, Schwab OAuth paste).
- It carries the clearest instance of the offset-before-processing defect
  (`:95`).
- The siblings have narrower, disjoint scopes and separate bot tokens:
  `telegram_reply_processor.py` (stop-confirmation replies),
  `cio_telegram_bot.py` (CIO converse, `TELEGRAM_CIO_BOT_TOKEN`).

### Wiring steps (NOT performed this wave — operator-gated, §8)

1. In `poll_once`, import from `scripts.lib.comms.inbound`:
   `claim_update`, `commit_checkpoint`, `build_inbound_event`,
   `quarantine_callback`, `get_checkpoint_offset`.
2. Replace the `.telegram_callback_offset` file read/write (`_get_offset` /
   `_save_offset`) with `get_checkpoint_offset()`; the `getUpdates` call passes
   `offset = get_checkpoint_offset() + 1`.
3. Replace the top-of-loop `_save_offset(update["update_id"])` (`:95`) with:
   ```python
   claim = claim_update(update["update_id"])
   if claim.already_processed:
       continue
   ```
4. Build the event once per update:
   ```python
   event = build_inbound_event(update)
   ```
5. Persist the ledger row:
   ```python
   result = publish_communication(event)
   ```
6. Advance the offset **only after** persist:
   ```python
   if result.ok:
       commit_checkpoint(update["update_id"])
   ```
7. On build/handler failure (malformed update, callback with no matching
   proposal, unauthorized chat), quarantine and **do not** commit so the update
   is re-delivered next poll:
   ```python
   quarantine_callback(reason, event.provider_coordinates, update["update_id"])
   ```
8. Keep the business handlers (`handle_callback_query`, `_handle_proposal_command`,
   `_handle_stop_command`, `_handle_atm_command`, `_handle_schwab_callback`) as
   they are; the gateway ledger write and the legacy business action run
   sequentially, with the offset committed only when the event is persisted.

### Migration of sibling pollers (follow-up, same pattern)

`telegram_reply_processor.py` and `cio_telegram_bot.py` keep their existing
offset handling until rewired. Each should adopt the same `claim → build →
publish → commit` sequence when their scope is folded in. Until then their
offset-before-processing behaviour is unchanged and **honestly documented as a
remaining gap**, not silently fixed.

---

## 7. Operator-gated items

1. **Poller rewiring requires operator sign-off** (§17, §8 — a live process /
   scheduler path and the operator-facing command surface). This wave writes
   the module + migration + tests only; it does not edit `run_telegram_callback_poller.py`.
2. **Applying the migration to production Postgres** is a deploy-boundary action
   (`AI_WORK_POLICY.md`); `.down.sql` provided for rollback.
3. **`COMMS_GATEWAY_MODE` / allowlists untouched.** No mode change and no
   ownership widening in this wave.
4. The sibling pollers (`telegram_reply_processor.py`, `cio_telegram_bot.py`,
   `telegram_command_handler.py`) are **not** rewired here; their offset
   handling is a named, deferred gap.

---

## 8. What remains unpublished

Stated at the top, per the closeout format: this entire wave is uncommitted and
unpushed — four new files exist on disk only. The poller wiring (§6) and the
migration apply (§7) are proposed, not performed.
