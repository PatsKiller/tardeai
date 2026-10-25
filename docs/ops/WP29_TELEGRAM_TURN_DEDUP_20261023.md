# WP-29 item e: idempotent Telegram conversation capture

Status: DRAFT source candidate; production duplicate frequency NOT_MEASURED
as_of: 2026-10-24T03:00:00Z
Measured at: main fe826d2ecdb59a19bd7c510c8923c7b743f06eee; task DSN-20261023-handoff-v3-P6-T295

The conversation writer accepted an identical provider page repeatedly. A private PostgreSQL regression reproduced this directly: a second call with the same role, channel, chat, message, text and subject inserted another row. This confirms a source-level replay defect; it does not establish the count or cause of every production duplicate.

## Source paths

- `atomic_inbound._persist_turn_for_update` writes the canonical operator turn during callback-poller intake.
- `cio_telegram_converse.process_telegram_message` also captures the operator turn before the shared core's message deduplication. A replay arriving here can write again even when later processing is refused as duplicate.
- `cio_poller_reply.make_send_fn` and the conversation entrypoint capture agent replies through `_best_effort_capture_turn`.
- `notify_material_change.capture_agent_turns` persists each delivered message/subject pair.
- All these paths use `inbound_identity_tagger.persist_turn`, which previously inserted unconditionally. Its SQL table has no provider-page uniqueness constraint.

The table's intended grain is one row per turn and resolved entity. Multiple different subjects in a page are legitimate; two raw rows alone do not prove duplication. The historical TypeError send retry is already corrected in the core and is not reintroduced by this change.

## Change and limits

For a turn with both chat and message coordinates, the existing writer takes a transaction-scoped advisory lock derived from role/channel/chat/message, then performs its insert only if no exact subject/issuer/symbol/text row exists. The query after lock acquisition uses a fresh READ COMMITTED snapshot, so concurrent entrypoints serialize and observe the first commit. Autocommit and stronger snapshot modes explicitly refuse rather than falsely claiming this concurrency guarantee. Current source callers use normal transactional connections. The method still owns its existing commit.

Exact replays return zero newly inserted rows. Roles, chats, distinct subjects, edited text and missing-coordinate turns remain distinct. Existing identical history is neither updated nor deleted. The first persisted row and its lineage remain intact. No new store, writer, schema migration, message send or broker behavior is introduced.

The existing tests' fake cursors now model row counts and isolation metadata; lineage assertions still inspect the actual inserted lineage positions. The new concurrency test uses a real, newly initialized private PostgreSQL fixture with a Unix socket, trust-auth fixture role, pinned timestamp default and no TCP listener, password, host env or production DSN.

## Evidence and remaining measurement

`/home/johnclaw/.cache/rtc/codex-wp29e-20261023/` contains `before.log` (duplicate regression fails before the fix), `after.log` (121 passed), `final-regression.log` (130 passed), `packet-registry.log` (33 passed, including all eight private-Postgres cases and the aggregate-only operator SQL), and retained owned fixture logs. Five concurrent captures insert one row; the other four return zero. Negative cases cover identity/role/chat separation, corrections, unresolved subjects, missing coordinates, unsupported transaction modes and preservation of prior duplicates.

Existing compatibility tests attempt live-DSN connections; the hermetic guard refused them before libpq. These are not live acceptance evidence. The new PostgreSQL fixture never loads host credentials.

Automatic approval review rejected the requested live aggregate census before execution because it would load database password credentials. No query ran and no workaround was attempted. Production duplicates and post-release acceptance remain NOT_MEASURED. The operator can run the aggregate-only SQL through an existing authorized PostgreSQL session:

```bash
psql --no-psqlrc --host=127.0.0.1 --dbname=trade_ai --username=trade_ai --set=ON_ERROR_STOP=1 --file=/home/johnclaw/wt-codex-wp29e-20261023/docs/ops/packets/telegram-turn-dedupe-20261023/read-only-census.sql
```

It prompts for authentication through psql if required and prints only grouped counts. Release and observation belong to the coordinator/operator. This worker does not alter existing rows or scheduler authority.
