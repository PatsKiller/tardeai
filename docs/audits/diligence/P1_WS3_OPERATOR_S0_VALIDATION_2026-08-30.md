# P1-WS3 — Operator S0 workflow validation + failure battery

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0  
**INTERDICT:** left as found — validate **would_send / CC-only / mapping** only; **no notify-on**, **no Telegram send**, **no new producer**  
**Branch:** `feat/cio-diligence-p1-ws3-operator-s0`  
**origin/main at branch cut:** `80f55f6f` (post-#684 P9; past `852ecd47`)  
**Live CURRENT pin (read-only ref):** `852ecd47` (`…/portfolio-server/CURRENT`)  
**Do not promote** from this package.

---

## 1. Code map

### 1.1 Surfaces

| Layer | Path | Role |
|-------|------|------|
| Telegram adapter | `scripts/lib/cio_telegram_converse.py` | Allowlist, dedup JSONL, plan↔message map, rate limit, `ensure_converse_plan` (`S0_OPERATOR_CONVERSE`), slash/free-text → core |
| Channel-agnostic core | `scripts/lib/cio_converse_core.py` | `process_operator_message` — channel-prefixed dedup key, wake enqueue, S0 route hook |
| S0 operator loop | `scripts/lib/cio_s0_operator_loop.py` | `route_turn` / `persist_turn` / `rehydrate` / intents · turn store `data/cio/cio_operator_turns.jsonl` |
| InstrumentRecord tip | `scripts/lib/cio_rehydrate.py` → `attach_operator_turn` | Lands question/ack/defer on cognition record (`last_operator_turn`) so disposition survives plan close |
| InstrumentRecord@v1 adapter | `scripts/lib/instrument_record.py` | `operator_turns[]` / `operator_turn_ids[]` on CC-facing projection |
| Plans enum | `scripts/lib/cio_plans.py` | `S0_OPERATOR_CONVERSE` allowed situation type |
| CC / API label | `scripts/api_v3_cio.py` | `"S0_OPERATOR_CONVERSE": "Operator conversation"` |
| Notification policy | `scripts/lib/cio_notification_policy.py` | S0 → `SUPPRESSED` / `would_send=False`; reads `CIO_TELEGRAM_INTERDICT` (default on) |
| Command Center block | `scripts/lib/cio_command_center.py` | S0 rows visible (`s0_operator_turns`); `would_send_any=False` |

### 1.2 Flow → code

| Operator flow | Intent / action | Primary code |
|---------------|-----------------|--------------|
| **question** ("what about RTX") | `intent=question` · `action=mint` → one S0 draft | `classify_intent` · `route_turn` · `ensure_converse_plan` |
| **ack** | `intent=ack` · `action=attach` (open plan or explicit `plan_id`) | `route_turn` · slash `/cio ack` in converse core |
| **defer** | `intent=defer` · attach; may stamp defer lesson on record | `route_turn` · `attach_operator_turn` (defer branch) |
| **reject** | `intent=reject` (outranks defer/ack) · attach | `classify_intent` order · `route_turn` |
| **CIO escalation** | Mint/attach `S0_OPERATOR_CONVERSE` plan; wake `OPERATOR_MESSAGE` | `ensure_converse_plan` · `enqueue_operator_wake*` |

Attach **beats** refuse: an ack/defer on an already-open plan is kept even for dust/test symbols that would not mint a fresh S0.

### 1.3 Persistence / replay

| Store | Contents | Restart property |
|-------|----------|------------------|
| `cio_telegram_msg_dedup.jsonl` | `{message_id, chat_id, ts}` — keys are `channel:message_id` from core | Append-only; `message_seen` rescans last 5k lines |
| `cio_operator_turns.jsonl` | `S0OperatorTurn@v1` rows: `turn_id`, `text_hash` (**not** raw text), `intent`, `plan_id`, `symbol`, `created_at` | `last_turn_for` sorts by `created_at` (not file order) |
| InstrumentRecord JSONL | `last_operator_turn` tip via `attach_operator_turn` | Cognition store tip reload (P3) |
| Plan projection | Open `S0_OPERATOR_CONVERSE` / other situations for attach resolution | Read via `_open_plans_snapshot` / test fixtures |

Audit trail for turns is hash + intent + ids — product surfaces cannot leak operator free text from the turn store (covered by existing S0 tests + this battery).

---

## 2. INTERDICT-aware matrix

Env readers (`notify_env_state`): `CIO_SITUATION_NOTIFY` (default off) · `CIO_TELEGRAM_INTERDICT` (default **on**). Policy **never** flips these pins.

| Scenario | Policy decision | `would_send` | Delivery | Validated without notify-on? |
|----------|-----------------|--------------|----------|------------------------------|
| S0 operator turn (material) | `SUPPRESSED` (`s0_operator_turn_default_suppressed`) | **False** | shadow | **Yes** — unit |
| S0 rows on CC notification block | visible `s0_operator_turns` / `s0_open_n` | `would_send_any=False` | CC render only | **Yes** — unit |
| INTERDICT default (`CIO_TELEGRAM_INTERDICT` unset/`1`) | `interdicted=True` in `env` | False on all policy outs | no producer | **Yes** — unit |
| Telegram mapping (allowlist / reply→plan_id / footer parse) | n/a (ingress) | n/a | dry_run / mock `send_fn` only | **Yes** — existing + WS3 tests |
| Live Telegram Bot API | **Not exercised** | — | — | Rails: left as found |

**Constraint honored:** INTERDICT-on validates would_send / CC-only paths; this PR does not set notify-on, does not clear INTERDICT, and adds no Telegram producer.

---

## 3. Failure battery (tmp_path · no network)

Executed by `tests/test_cio_diligence_p1_ws3_operator_s0.py`.

| Case | Expected | Result |
|------|----------|--------|
| **Duplicate** message_id (`channel:mid`) | Second process → `duplicate_message_id`; first mark persists across reload | **PASS** |
| **Out-of-order** message ids (101 → 103 → 102) | Each unique id handled once; no sequence gate reject | **PASS** |
| **Missing** mid id (process 1, skip 2, process 3) | 1 and 3 accepted; gap does not corrupt dedup | **PASS** |
| **Late** lower id after higher | Still accepted if unseen | **PASS** |
| **Restart mid-conversation** (turn store) | New reader: `last_turn_for` recovers latest intent by `created_at` | **PASS** |
| **Out-of-order turn append** (older `created_at` written after newer) | Tip intent remains the newer turn | **PASS** |
| **Flow matrix** question / ack / defer / reject / S0 mint | Intents + mint/attach actions match table §1.2 | **PASS** |
| **InstrumentRecord operator turn** | `attach_operator_turn` + `build_instrument_record(operator_turns=…)` | **PASS** |
| **INTERDICT / would_send** | S0 suppressed; CC `would_send_any=False`; default interdicted | **PASS** |
| **No network Telegram** | Empty bot token env; mock/`dry_run` only; no `api.telegram.org` in battery module | **PASS** |

### Known limitations (documented, not fixed here)

- Dedup mark is skipped under `dry_run=True` — callers must mark or use non-dry with a mock `send_fn`.
- `persist_turn` is append-only and **not** idempotent on `turn_id`; duplicate wake retries can append duplicate hash rows. Tip selection remains `created_at`-ordered.
- Free-text `process_operator_message` beyond early exits may touch live plan/wake stores — battery stays on tmp_path helpers + dry early-exit paths to keep READ_ONLY rails.

---

## 4. Gap register touch

| ID | Update |
|----|--------|
| **G-NOTIFY-01** | Remains **OPEN** (P7). WS3 evidence: S0 always `SUPPRESSED`/`would_send=False`; CC surfaces S0 without producer; INTERDICT default left as found. Does not close fatigue/miss policy. |

---

## 5. Proof artifacts

| Artifact | Path |
|----------|------|
| This validation | `docs/audits/diligence/P1_WS3_OPERATOR_S0_VALIDATION_2026-08-30.md` |
| Failure battery tests | `tests/test_cio_diligence_p1_ws3_operator_s0.py` |
| Ops note | `docs/ops/CIO_DILIGENCE_P1_WS3_2026-08-30.md` |
| Scoreboard | `docs/ops/CIO_DILIGENCE_SCOREBOARD.md` + `.json` → **P1-WS3 = DONE** |

No new versioned CLI / SCHEMA module in this package → dark-contract `NO_CONSUMER_REASON` N/A.
