# Live baseline — 2026-08-03 (stop truth restored)

## What is baseline

The portfolio-server release tree that is **running after the stop-truth fix**:

- Path: `trade-ai-releases/portfolio-server/af45096e-platform-audit-20260802`
- Content: commit `974a2bac` (Re-Entry data broker + LLM fleet work) **plus** stop-truth hardening
- Verified: `/api/v2/holdings/live-stops` returns ~16 Schwab+Alpaca protective stops (not MU-only)

## Stop-truth root cause (do not regress)

1. Release trees must ship `config/broker_credentials.env` as a **0600 symlink** to the rebuild secrets file (Fernet key `SCHWAB_TOKEN_ENC_KEY`). Without it, Schwab account hashes cannot decrypt → order reads return `needs_account_hash` → Portfolio shows **NO STOP** while ToS still has working stops.
2. `broker_secrets.load_into_env` must **not** latch `_loaded=True` when the secrets file is missing (fixed in baseline).
3. `/api/v2/holdings/live-stops` exposes `schwab_hash_ok_accounts`, `schwab_hash_missing_accounts`, `broker_stop_read_ok_accounts`, and `warning` so hash failures are not silent.

## Deploy rule for any new release dir

```bash
ln -sfn /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/broker_credentials.env \
  <release>/config/broker_credentials.env
chmod 600 /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/broker_credentials.env
```

Never commit the secrets file. Never rsync a release without re-linking secrets.

## Git

Branch `wt/cursor-guardrails` tip = this baseline. Live `SOURCE_COMMIT` should match that tip after deploy.
