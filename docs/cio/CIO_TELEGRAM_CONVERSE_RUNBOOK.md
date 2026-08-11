# CIO Telegram converse — operator runbook

**Authority:** READ_ONLY_ADVISORY forever  
**Branch:** `feature/advisory-desk-v1`  
**Code:** `scripts/lib/cio_telegram_converse.py`, `scripts/cio_telegram_bot.py`  
**Unit:** `config/systemd/user/tradeai-cio-telegram.service`

This is **not** autonomous trading. Path: **chat → event bus → wake → structured reply**.

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
| `/cio ack\|rate\|defer\|done\|reject` | Same ledger dispositions as before |
| Free-text | `operator.message` on bus → wake (Alex) → structured reply + draft/proposed plan |
| Reply-to bot plan message | Continues **same `plan_id`** |
| `ack` reply | Ack linked plan if reply-to present |

Footer on every converse reply includes `plan_id` and how to ack.

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
- Situation bulk notify (`situation.raised` → Telegram) remains **off** unless separately enabled
- LLM path: Phase P1 uses **template reply** (`LLM deferred`) under budget; still useful

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
```
