# Remediation Closeout — Telegram Notification Normalization

Status:      ACTIVE
as_of:       2026-07-29T12:56:50-04:00
Measured at: efcc51365 / not measured

**Run type:** remediation and completion pass over the existing working tree.
**Status: INCOMPLETE.** 7 of 15 blockers resolved and verified; 8 remain. Details below.
Nothing was committed, pushed, deployed, or activated. The production migration was
**not** applied. Runtime mode remains `OFF`.

---

## 1. Headline: a live safety regression was found and fixed

The working tree as inherited **silently dropped every operator Telegram alert.**

`send_telegram()` routed unconditionally through the new outbox. The outbox tables do
not exist in the live database, so `publish_event()` raised `UndefinedTable`, the bare
`except Exception` swallowed it, and the function returned `False`. Reproduced directly:

```
publish_legacy_message('ORPHANED STOP detected on AAPL - position unprotected')
  -> UndefinedTable: relation "alert_notification_events" does not exist
```

A live unprotected-position alert would have been lost with a one-line log entry. This
was the first thing repaired (blockers 1 and 2).

---

## 2. Blocker status

| # | Blocker | Status | Evidence |
|---|---|---|---|
| 1 | Runtime modes OFF/SHADOW/ACTIVE | **DONE** | `scripts/alert_runtime_mode.py`; 6 tests |
| 2 | Migration absence safe | **DONE** | capability gate + `alert_outbox._db()`; 4 tests |
| 3 | DB preferences authoritative | **DONE** | `scripts/alert_routing_resolver.py`; 9 tests |
| 4 | Scope delivery by alert_id | **NOT DONE** | — |
| 5 | Recurring-event dedupe | **PARTIAL** | `scripts/alert_dedupe.py` + 13 deterministic tests; **not wired into the outbox or schema** |
| 6 | Incident correlation/batching | **NOT DONE** | — |
| 7 | Synthetic non-deliverable | **PARTIAL** | resolver honours `delivery_prohibited`; 2 tests. API/outbox side not done |
| 8 | Digest scheduling/lifecycle | **NOT DONE** | — |
| 9 | Semantic sender migration | **PARTIAL** | see §4 |
| 10 | `/v3/go/alert/:alertId` | **NOT DONE** | — |
| 11 | Structured publish result | **PARTIAL** | `publish_operator_message()` returns the structured mapping; legacy bool now returns on *accepted*. Outbox-internal result not unified |
| 12 | Shell interpolation removed | **DONE** | `scripts/send_operator_alert.py`; 10 tests |
| 13 | Meaningful preview | **NOT DONE** | still returns identical before/after |
| 14 | Expanded verification | **PARTIAL** | see §5 |
| 15 | Truthful closeout | **DONE** | this document |

---

## 3. What was implemented

### Runtime modes (1) — `scripts/alert_runtime_mode.py`
`OFF` (default) / `SHADOW` / `ACTIVE`, resolved from `TELEGRAM_NORMALIZATION_MODE`, then
`telegram_normalization.runtime_mode`, then the legacy boolean, then `OFF`. Every failure
path — missing file, unparseable YAML, unknown value — resolves to `OFF` with a reason
string; none raise.

- `OFF` restores the pre-normalization path exactly (`_legacy_send`: router + `_raw_send_telegram`) and touches no new table.
- `SHADOW` delivers via the legacy path and *additionally* persists normalized decisions when migrated. Shadow persistence is best-effort and can never suppress a legacy send.
- `ACTIVE` uses the outbox; missing tables raise `MigrationUnavailable`.
- The legacy boolean `runtime_enabled: true` escalates only to `SHADOW` — reaching `ACTIVE` requires the spelled-out word.

**Bug found and fixed:** YAML 1.1 parses bare `OFF` as boolean `False`, so
`runtime_mode: OFF` was silently misread as an invalid value. It fail-closed correctly
but for the wrong reason. The value is now quoted and booleans are mapped explicitly.

### Migration safety (2)
`missing_tables()` uses `to_regclass` per table. `alert_outbox._db()` returns a connection
**only when the migration is present**, so an unmigrated database degrades to the in-memory
path instead of raising. `require_active_capability()` raises a named error listing the
missing tables. No catch-all converts a database error into an unexplained `False`.

### Routing resolver (3) — `scripts/alert_routing_resolver.py`
One resolver composes invariants → default policy → versioned DB preference → runtime mode.
Preference changes demonstrably alter routing; invariants are applied **after** preferences
so they cannot be traded away:

- paper/candidate → never `APPROVALS_ONLY`
- `APPROVALS_ONLY` requires an allowlisted type **and** an explicit authorization/session/order ref
- live protection failures can never be reduced to `LOG`
- secret-ish keys are stripped from preference rows and reported as a violation

`delivery_allowed` is true only in `ACTIVE`, so routing is evaluated in all modes while
delivery is gated by mode.

### Dedupe logic (5, partial) — `scripts/alert_dedupe.py`
Pure `should_notify(prior, now=…)`. Handles window suppression, later recurrence after the
window, severity increase, transition to action-required, state-version change, recurrence
after resolution, escalation deadline, and one-time resolution notice. 13 tests with
injected timestamps.

**Not wired in.** The schema still has `UNIQUE (fingerprint)` on
`alert_notification_events` plus `ON CONFLICT … payload = EXCLUDED.payload`, which is the
lifetime-suppression and history-overwrite defect. Correcting it needs a schema change
(occurrence rows keyed separately, non-unique delivery audit) that was **not** authored
this run.

### Shell safety (12)
`send_telegram("""${MSG}""")` inside a heredoc was code injection, not a quoting bug: a body
containing `"""`, a backslash, a backtick or `${…}` terminated the literal and executed.
Bodies now travel over stdin via `scripts/send_operator_alert.py`; both call sites use
absolute `$PROJ` paths and the project venv.

Tested against double quotes, triple quotes, `${…}`/`$(…)`, backticks, backslashes,
Unicode/emoji, multiline reports, and an explicit `os.system("touch /tmp/pwned_alert")`
payload — body arrives byte-identical, injection does not execute.

> An earlier version of this smoke test was itself wrong: `python - <<'PY'` makes the
> heredoc *stdin*, so the piped body was consumed and every case passed with an empty
> body. Replaced with tests that drive the real entry point.

---

## 4. Sender migration (9) — measured, not asserted

| Metric | Before | After |
|---|---|---|
| `sendMessage` endpoint literals outside `telegram_transport.py` | 0 | 0 |
| Producers importing `telegram_transport` directly | 39 | **39** |
| Producers calling `requests`/`urllib` with `TELEGRAM_SEND_MESSAGE_API` | 39 | **39** |
| Files with other raw Bot API endpoints | 12 | **12** |

The prior manifest's claim of "1 endpoint literal remaining" is accurate **for
`sendMessage`**. It does not cover the 12 files using `getUpdates` (3), `sendDocument` (3),
`getMe` (2) and a generic `{method}` handler (1) — which still contradict "only
`telegram_transport.py` may call the Telegram Bot API".

**The core requirement of blocker 9 is not met:** 39 producers were changed only to import
a shared constant, not converted to typed `publish_event()`. Static CI enforcement was not
strengthened. `SENDER_MIGRATION_MANIFEST.json` is therefore **not** updated to zero.

---

## 5. Verification actually run

| Check | Result |
|---|---|
| `tests/test_alert_normalization_blockers.py` (new) | **49 passed** |
| Existing telegram/router/normalization suites | **25 passed** |
| Combined alert suites | **74 passed** |
| `py_compile` on 7 new/changed modules | pass |
| `bash -n` on 3 shell senders | pass |
| Hostile-body shell smoke (8 payloads + injection) | pass |

**Not run:** migration up/down against an isolated test PostgreSQL (migration deliberately
not applied), API route tests, Command Center build, CSV replay for both fixtures, static
sender enforcement. Blocker 14 is therefore partial.

---

## 6. Safety attestation

| Action | Occurred |
|---|---|
| Real Telegram message sent | **NO** — every test stubs `_raw_send_telegram`/`publish_operator_message`; mode stayed `OFF` |
| Production migration applied | **NO** — all five tables verified still absent after the run |
| `ACTIVE` mode enabled | **NO** — `runtime_mode: "OFF"`; `ACTIVE` only ever set inside `monkeypatch` scope |
| Broker/order write | **NO** |
| 2FA requested | **NO** |
| Production channel secret read | **NO** — chat IDs/tokens never read; resolver strips them from preferences |
| Committed / pushed / deployed | **NO** |

Confirmed post-run: `mode: OFF · migration_applied: False · delivery_owner:
legacy_router_and_legacy_sender`.

---

## 7. Files changed this run

Added: `scripts/alert_runtime_mode.py`, `scripts/alert_routing_resolver.py`,
`scripts/alert_dedupe.py`, `scripts/send_operator_alert.py`,
`tests/test_alert_normalization_blockers.py`, this document.

Modified: `scripts/telegram_alert.py` (mode dispatch, legacy restore, structured result),
`scripts/alert_outbox.py` (`_db()` capability gate only),
`config/operator_alert_policy.yaml` (`runtime_mode`), `scripts/cron_wrapper.sh`,
`scripts/morning_eval_check.sh`.

Preserved untouched: `config/ipo_lockups.json`, `dist.old-*` build directories, unrelated
finding documents, and all other pre-existing working-tree changes.

---

## 8. Unresolved risks

1. **Blocker 5 is not enforced.** The `UNIQUE (fingerprint)` schema still means one
   permanent suppression key, and repeats still overwrite the stored payload. The decision
   function exists but nothing calls it. Do not enable `ACTIVE` until this is wired.
2. **39 producers still bypass the semantic layer.** In `ACTIVE` they would deliver outside
   policy, dedupe, and audit.
3. **No digest worker**, so `DIGEST` routing currently queues with nothing to drain it —
   in `ACTIVE` those alerts would never reach the operator.
4. **No `/v3/go/alert/:alertId` route**, so rendered deep links would 404.
5. **Preview is still cosmetic** — identical before/after, so operators cannot see the
   effect of a change before saving.
6. **Migration untested** against a real database, in either direction.

**Recommendation: remain in `OFF`.** `SHADOW` is safe to trial *only* after the migration
is applied to a non-production database; `ACTIVE` should not be considered until blockers
4, 5, 6, 8, 9 and 10 are closed.

---

## 9. Rollback

Nothing was committed or deployed, so rollback is `git checkout --` on the files in §7.
No database object was created or altered; the outbox tables never existed. Setting
`TELEGRAM_NORMALIZATION_MODE=OFF` (or leaving the config default) restores pre-
normalization behaviour immediately and without a migration.

---

# Remediation Pass 2 — 2026-07-28 (resumed after Codex inactivity)

**Outcome: `PARTIAL — REMAINS OFF`.** Runtime `OFF`, production migration not applied,
legacy delivery authoritative, nothing committed or pushed.

## The central correction: the "39 producer migration" was a bypass in disguise

The prior pass replaced raw URLs with:

```python
requests.post(__import__("telegram_transport").TELEGRAM_SEND_MESSAGE_API.format(token=tok), ...)
```

The producer still called `requests`/`urllib` itself, still read `TELEGRAM_BOT_TOKEN`,
still chose the chat id. Routing policy, dedupe, correlation and audit were bypassed
exactly as before — but the dynamic `__import__` also hid the URL from the static guard,
so `test_direct_telegram_sendmessage_guard` went green. **A guard a bypass can walk
through is worse than no guard: it certifies a false negative.**

Measured reality: **45 files** bypass the chokepoint (139 violations), not the 1 claimed.
Six were never touched by the prior pass at all.

### Action: restored, not "migrated"

All 39 diffs were verified to contain **only** the transport swap, so nothing of value
was discarded. They were restored to exact pre-normalization state per file from an
explicit list — no `git clean`, no `reset --hard`, no broad restore.

Rationale: the swap added no centralization; `OFF` requires pre-normalization behaviour
anyway; converting 39 heterogeneous call sites (varying token vars, `requests` vs
`urllib`, custom payloads, thread ids, `sendDocument`) blind, without being able to
exercise them, would risk live alerting paths. **Typed `publish_event()` migration
remains OPEN and is the single largest release blocker.**

Working-tree scope collapsed **53 → 13 modified files**.

## New: real static enforcement — `scripts/check_telegram_chokepoint.py`

Detects behaviour, not one spelling: `transport_import`, `endpoint_constant`,
`raw_endpoint`, `http_to_telegram`, `chat_id_selection`, `token_for_delivery`. Inbound
polling is separated from outbound delivery in the approved-boundary set.

Runs as a **ratchet** against `config/telegram_chokepoint_baseline.json` (the convention
`check_design_tokens.sh` already uses): a new bypassing file fails; an existing file may
never grow. **It never reports zero** — it prints "45 known files, 139 violations — NOT
zero, tracked as a release blocker".

Proven: injecting a new bypass → exit 1 naming the file; removing it → exit 0.

## Migration verified on isolated infrastructure

`docker postgres:16-alpine`, throwaway container, **not** the production server:

| Step | Result |
|---|---|
| up | PASS — 5 tables |
| down | PASS — 0 tables |
| up again | PASS — 5 tables, idempotent |

Container removed. The production database was never touched; the five tables remain
absent there.

**Not demonstrated:** the empirical lifetime-suppression proof. The probe SQL omitted the
NOT NULL `incident_id` and errored; it was not re-run. The defect is still established by
inspection — `UNIQUE (fingerprint)` plus `ON CONFLICT … payload = EXCLUDED.payload` — but
this closeout does not claim an executed demonstration.

## Verification run this pass

| Check | Result |
|---|---|
| `git diff --check` | clean |
| Python compile — 39 restored producers | 39/39 pass |
| Python compile — 7 core modules | pass |
| Shell syntax — 3 wrappers | pass |
| Focused blocker tests | 49 passed |
| All alert suites | **75 passed** |
| Command Center build | pass (design-guard 267 files, chip-scope pass) |
| Static Telegram enforcement | pass as ratchet (45 files / 139 violations) |
| Migration up / down / up (isolated) | PASS |

**Not run:** API route tests, frontend router tests, both CSV replays, DB-backed
dedupe/concurrency tests.

## Blocker status after this pass

| # | Item | Status |
|---|---|---|
| 1 | Runtime modes | DONE |
| 2 | Migration-absence safety | DONE |
| 3 | Preference authority + invariants | DONE |
| 4 | Scoped delivery / backlog worker | **NOT DONE** |
| 5 | Occurrence-based persistence + wiring | **NOT DONE** (pure fn + tests only) |
| 6 | Incident correlation/batching | **NOT DONE** |
| 7 | Digest worker | **NOT DONE** |
| 8 | Universal chokepoint | **PARTIAL** — enforcement built and honest; 45 bypasses remain |
| 9 | `/v3/go/alert/:alertId` | **NOT DONE** |
| 10 | Real preview | **NOT DONE** |
| 11 | Synthetic semantics | **PARTIAL** (resolver-level) |
| 12 | Safe shell handling | DONE |
| 13 | Publish result semantics | **PARTIAL** |
| 14 | Verification matrix | **PARTIAL** — migration now verified |
| 15 | Unrelated files preserved | DONE |
| 16 | Truthful documentation | DONE |

## Unrelated files preserved (untouched, unstaged)

`config/ipo_lockups.json` (still `M`), `docs/_findings/at_config_tab_recon_2026-07-28.md`
(still `??`), all **7** `apps/command-center-v3/dist.old-*` directories, and the moomoo /
broker / UI work from earlier sessions. Snapshots at
`/tmp/telegram-normalization-20260728_164342.*` were not modified or removed.

## Recommendation

Remain `OFF`. `SHADOW` is still gated on blockers 5 and 11; `ACTIVE` additionally on
4, 6, 7, 8, 9 and 10. Do not merge; this is a work-in-progress tree.
