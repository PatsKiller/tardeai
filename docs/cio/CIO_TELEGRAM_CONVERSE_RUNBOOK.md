# CIO Telegram converse — operator runbook

**Authority:** READ_ONLY_ADVISORY forever  
**Branch:** `feature/advisory-desk-v1`  
**Code:** `scripts/lib/cio_telegram_converse.py`, `scripts/cio_telegram_bot.py`  
**Unit:** `config/systemd/user/tradeai-cio-telegram.service`

This is **not** autonomous trading. Path: **chat → event bus → wake → structured reply**.

WhatsApp mirror (same core, transport only): [CIO_WHATSAPP_CONVERSE_RUNBOOK.md](CIO_WHATSAPP_CONVERSE_RUNBOOK.md).

---

## Setup (once)

1. Create a **dedicated** Telegram bot with @BotFather (not Maria’s token).
2. Set env (prefer SM / `~/.config/tradeai` or `/run/user/$UID/tradeai/env`):

```bash
TELEGRAM_CIO_BOT_TOKEN=...          # dedicated bot
TELEGRAM_CIO_CHAT_IDS=123456789     # operator chat id(s), comma-separated
CIO_TELEGRAM_CONVERSE=1             # 0 to disable free-text wakes
CIO_TELEGRAM_WAKES_PER_HOUR=20      # rate limit
# optional:
COMMAND_CENTER_BASE_URL=https://your-host
```

3. Message the new bot once from the allowlisted account.
4. Install unit (optional loop):

```bash
cp config/systemd/user/tradeai-cio-telegram.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-cio-telegram.service
```

Or one-shot poll:

```bash
.venv/bin/python scripts/cio_telegram_bot.py --once --json
```

---

## How to talk

| Mode | What happens |
|---|---|
| `/cio`, `/cio portfolio`, `/cio actions`, `/cio risk`, `/cio hermes` | Deterministic status — **no LLM** |
| `/cio plans` / `/cio plan <id>` | List/show advisory plans |
| `/cio thesis` / `/cio thesis history` | Versioned desk thesis (P3; see [THESIS_STORE_P3.md](THESIS_STORE_P3.md)) |
| `/cio traces [n]` | Wake traces — why wake / llm path (zero LLM; see [WAKE_TRACES_P5.md](WAKE_TRACES_P5.md)) |
| `/cio ack\|rate\|defer\|done\|reject` | Same ledger dispositions as before |
| Free-text | `operator.message` on bus → wake (Alex) → structured reply + draft/proposed plan |
| Reply-to bot plan message | Continues **same `plan_id`** |
| `ack` reply | Ack linked plan if reply-to present |

Footer on every converse reply includes `plan_id` and how to ack.

**Every free-text reply says where it came from (2026-09-13).** Before the authority tail each reply
carries `Sources:` — the Command Center stores it read, with their computed / as-of time, and the
model plus its role when a model wrote prose — and, only when the answer needed anything outside the
Command Center (gap-resolver vector, Hermes queue, a model call), `Went outside: <what> — <why>`.
Enforced at one chokepoint, `scripts/lib/reply_provenance.py::finalize_operator_reply`; the receipt is
`reply_provenance` on the `operator.message` payload. Slash commands are out of scope. Full path map:
[`docs/OPERATOR_REPLY_ROUTING.md`](../OPERATOR_REPLY_ROUTING.md). Tests:
`tests/test_operator_reply_routing_sources_20260913.py`.

**Named stocks, memory and pending questions (2026-09-13, PRs #998–#1001).** A question that names a
company resolves to its instrument first (`scripts/lib/operator_subject_resolver.py`; "Visa" and "V" are one
subject GUID). The reply is that subject's brief, never the whole re-entry book: last close and 30-day change,
re-entry desk levels, analyst view with its as-of date and age, the newest research of each type, and "What
this means". Below it, "Earlier on V" recalls up to three earlier questions about the same subject in this
chat and what was answered. When facts are missing the reply names the data gap rows it queued and when the
gap resolver next runs (read from the crontab), or promises nothing. A pending question closes with a
message saying what was asked, how long it was open, why it closed and what was missing.

| Switch | Default | Effect |
|---|---|---|
| `CIO_SUBJECT_FLASH` | `1` | DeepSeek Flash may reword a subject brief; its text is used only when every number is in the brief. `0` sends the deterministic brief |
| `CIO_SUBJECT_MEMORY` | `1` | per-subject recall from `operator_conversation_turns`; `0` disables |
| `CIO_SUBJECT_MEMORY_DAYS` | `30` | recall window |
| `CIO_OPERATOR_PENDING_ETA_GRACE_HOURS` | `1` | a pending with an ETA stays open until ETA + grace; without an ETA it closes at 2 h |
| `CIO_GAP_RESOLVER` | `1` | run the declared gap vectors for a blocking gap; `0` restores the pre-2026-09-13 pending path |
| `GAP_RESOLVER_LIVE` | unset | unset = side-effecting vectors record what they would do (dry run) |

Full map: [`docs/OPERATOR_REPLY_ROUTING.md`](../OPERATOR_REPLY_ROUTING.md); gap queue:
[`docs/GAP_RESOLUTION.md`](../GAP_RESOLUTION.md).

---

## After a deploy

`promote` does not restart this bot. After any deploy that changes desk or converse code
(`scripts/lib/cio_operator_desk_loop.py`, `cio_converse_core.py`, `reply_provenance.py`,
`operator_subject_resolver.py`, `cio_telegram_converse.py`):

```bash
systemctl --user restart tradeai-cio-telegram.service
readlink /proc/$(systemctl --user show -p MainPID --value tradeai-cio-telegram.service)/cwd   # the new release
```

The half-hourly `tradeai-operator-answer-quality.timer` (`scripts/check_operator_answer_quality.py`) audits the
replies actually sent — missing Sources line, false "empty" claims, book dumps for a named symbol, pendings
never closed. Known limit: it flags a pending open past a flat 2 h even when the desk is honouring a longer ETA.

---

## Disable

```bash
CIO_TELEGRAM_CONVERSE=0
# or stop unit
systemctl --user stop tradeai-cio-telegram.service
```

Slash `/cio` status still works if you re-enable only allowlisted polls; with converse=0 free-text wakes are skipped.

---

## Safety

- Non-allowlisted chats: **ignored**
- Rate limit: default 20 converse wakes/hour/chat
- No broker credentials, orders, or stop placement from chat
- Situation bulk notify (`situation.raised` → Telegram) remains **off** unless separately enabled (`CIO_SITUATION_NOTIFY=1`)
- LLM path (P2b): material converse enriches linked plan via governed bridge under cap;  
  if blocked → **template + “LLM deferred”**. Disable with `CIO_LLM_ENRICH=0`.  
  See `docs/cio/P2B_PLAN_ENRICHMENT.md`.

---

## Continuity files

| Path | Role |
|---|---|
| `data/cio/cio_telegram_msg_dedup.jsonl` | message_id once |
| `data/cio/cio_telegram_plan_messages.jsonl` | telegram_message_id ↔ plan_id |
| `data/cio/cio_telegram_rate.jsonl` | wake rate limit |
| `data/cio/.cio_telegram_offset` | getUpdates offset |
| `data/cio/cio_plans.jsonl` | plans |

---

## Tests

```bash
.venv/bin/python -m pytest tests/test_cio_telegram_converse.py -q
.venv/bin/python -m pytest -q tests/test_operator_reply_routing_sources_20260913.py \
  tests/test_subject_answer_completeness_20260913.py tests/test_subject_memory_recall_20260913.py \
  tests/test_pending_close_wording_20260913.py tests/test_pending_expiry_unanswerable_20260913.py \
  tests/test_desk_gap_queue_reconnect_20260913.py
```
