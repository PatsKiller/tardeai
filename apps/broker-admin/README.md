# Broker Admin (Tier-2 credential console)

The **secure** place to configure broker API credentials — deliberately separate from the
read-only v3 dashboard, which only *displays* connection status.

## Why a separate app
The v3 Command Center is read-only and unauthenticated (anyone on the LAN can open it).
Broker secrets (Schwab OAuth keys, Alpaca keys) must never live there. This app is the
guarded surface: localhost-only, password-gated, CSRF-protected, secrets at chmod 600.

## Run
```bash
.venv/bin/python apps/broker-admin/broker_admin.py        # http://127.0.0.1:8788
BROKER_ADMIN_PORT=8790 .venv/bin/python apps/broker-admin/broker_admin.py
```
On first run a password is generated and written to `apps/broker-admin/.admin_password`
(chmod 600) and printed once. Override with `BROKER_ADMIN_PASSWORD=...`.

It is **on-demand** — not a systemd service. Start it when you need to set credentials,
stop it (Ctrl-C) when done.

## What it does
- Lists the API-capable brokers (Alpaca live; Schwab/Tastytrade scaffolding) and their
  required fields, showing whether each is set (masked to last 4 — never the full value).
- **Save** writes to `config/broker_credentials.env` (chmod 600, gitignored).
- **Test connection** instantiates the adapter with the saved creds and calls
  `get_account()`/`get_status()`.

## How saved creds take effect
The adapters call `broker_secrets.load_into_env()` on construction, which loads any keys
from `config/broker_credentials.env` that aren't already in the environment — so the main
`.env` still wins for already-live brokers (Alpaca), and newly-configured brokers
(Schwab/Tastytrade) pick up their credentials.

## Security properties
- Binds `127.0.0.1` only (never `0.0.0.0`).
- HMAC-signed httponly session cookie; per-process signing secret (restart = re-login).
- CSRF token required on every write.
- Secrets never logged, never echoed back in full, file is chmod 600 and gitignored.
