# CIO WhatsApp converse — operator runbook (P4)

**Authority:** READ_ONLY_ADVISORY forever  
**Branch:** `feature/advisory-desk-v1`  
**Role:** **Mirror channel** for the same Telegram CIO advisory loop — not a second brain, not an autonomous trader.

| Layer | Module |
|---|---|
| Ingress | `scripts/lib/cio_whatsapp_ingress.py` |
| Egress | `scripts/lib/cio_whatsapp_egress.py` (sole Cloud API sender) |
| Shared core | `scripts/lib/cio_converse_core.py` (same path as Telegram) |
| Webhook | `scripts/cio_whatsapp_webhook.py` |
| Unit | `config/systemd/user/tradeai-cio-whatsapp.service` (default **off**) |

Telegram remains the primary slash-rich channel. WhatsApp reuses:

- `operator.message` event shape (`channel=whatsapp`)
- `OPERATOR_MESSAGE` wakes → plan store → P2b enrichment
- Structured reply formatter (plain-text friendly on WA)
- plan_id continuity via outbound message map

---

## Meta setup (Cloud API)

1. Meta Developer App → **WhatsApp** product → Business Cloud API.
2. Create / attach a **WhatsApp Business** phone number → note **Phone number ID**.
3. Generate a permanent **System User** access token (or long-lived) with `whatsapp_business_messaging`.
4. Configure webhook:
   - Callback URL: `https://<your-host>/cio/whatsapp/webhook`  
     (local: reverse-proxy to `127.0.0.1:8787`)
   - Verify token: choose a random string → `WHATSAPP_VERIFY_TOKEN`
   - Subscribe to **messages**
5. App secret → `WHATSAPP_APP_SECRET` (required for `X-Hub-Signature-256`; fail-closed if unset unless `WHATSAPP_SKIP_SIGNATURE=1` for local dev only).

### Session vs template (honest limits)

| Window | What works |
|---|---|
| **User-initiated 24h session** | Free-form **text** replies to the operator (this implementation) |
| **Outside 24h / business-initiated** | Meta **template** messages required — **not** implemented here (no marketing spam) |
| Groups / multi-operator | **Out of scope** — single allowlisted `wa_id` first |

If the operator has not messaged the business number recently, Cloud API may reject free-text sends. Start a session by messaging the business number first.

---

## Environment

Prefer `~/.config/tradeai/cio-whatsapp.env` (mode 600) or SM `/run/user/$UID/tradeai/env`:

```bash
# Master flag — default OFF until ready
CIO_WHATSAPP_CONVERSE=0

# Meta Cloud API
WHATSAPP_TOKEN=...                    # or WHATSAPP_ACCESS_TOKEN
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_VERIFY_TOKEN=...             # webhook challenge
WHATSAPP_APP_SECRET=...               # HMAC signature

# Allowlist (digits, comma-separated; no + required)
WHATSAPP_WA_IDS=15551234567

# Optional
CIO_WHATSAPP_WAKES_PER_HOUR=20
WHATSAPP_GRAPH_VERSION=v19.0
# WHATSAPP_SKIP_SIGNATURE=1           # DEV ONLY
```

**Never** commit tokens. Do not reuse Telegram bot tokens.

---

## Enable

```bash
# 1) Write env (flag still 0)
install -m 600 /dev/null ~/.config/tradeai/cio-whatsapp.env
# edit file with token, phone id, allowlist, verify token, app secret

# 2) Install unit (still flag 0 in unit file)
cp config/systemd/user/tradeai-cio-whatsapp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tradeai-cio-whatsapp.service

# 3) Point Meta webhook at host; complete GET verify challenge

# 4) Flip flag when ready
# In cio-whatsapp.env:
#   CIO_WHATSAPP_CONVERSE=1
systemctl --user restart tradeai-cio-whatsapp.service
```

Local dry-run webhook (no Meta):

```bash
CIO_WHATSAPP_CONVERSE=0 .venv/bin/python scripts/cio_whatsapp_webhook.py --port 8787 --dry-run
```

---

## How to talk (WhatsApp vs Telegram)

| Action | WhatsApp | Telegram |
|---|---|---|
| Free-text advisory | Yes → same wake/enrich/plan path | Yes |
| Reply to bot msg | Continues `plan_id` if map hit | Same |
| List plans | Text `plans` or `cio plans` | `/cio plans` |
| Desk thesis (P3) | Text `thesis` / `thesis history` | `/cio thesis` |
| Ack plan | `ack` (reply-to) or `ack plan_xxx` | `/cio ack` / reply `ack` |
| Full slash set | Partial plain-text parity | Full `/cio …` |
| Traces / rate / defer | Prefer Telegram `/cio` | Full |

Footer on WA replies is plain text (no Markdown). Reminds operator that full slash lives on Telegram.

---

## Security

- Allowlist only — non-listed `wa_id` ignored  
- Signature check when `WHATSAPP_APP_SECRET` set  
- Flag 0 → **no egress** (even for command handlers)  
- No broker / order / stop / 2FA language executed  
- Single egress: `send_whatsapp_text` in `cio_whatsapp_egress.py`

---

## Data files

| Path | Role |
|---|---|
| `data/cio/cio_whatsapp_msg_dedup.jsonl` | Inbound message_id dedup |
| `data/cio/cio_whatsapp_plan_messages.jsonl` | Outbound mid → plan_id |
| `data/cio/cio_whatsapp_rate.jsonl` | Per-wa_id wake rate |

Shares plan/goal stores and enrichment with Telegram (`data/cio/cio_plans.jsonl`, etc.).

---

## Tests

```bash
.venv/bin/python -m pytest tests/test_cio_whatsapp_p4.py tests/test_cio_telegram_converse.py -q
```

No live Meta calls in CI (HTTP mocked / dry_run).

---

## Autonomy truth

WhatsApp is a **mirror transport** for the existing advisory colleague loop.  
It does **not** add free-running agents, mass situation notify, or trading authority.
