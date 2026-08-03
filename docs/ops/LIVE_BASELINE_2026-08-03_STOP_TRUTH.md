# Live baseline — 2026-08-03 (stop truth restored)

> **Agents:** this is the long form. The short **must-follow** policy is in
> [`AGENTS.md`](../../AGENTS.md) → *MANDATORY — Live baseline, git, and portfolio-server releases*.
> Operator index: [`OPERATIONS.md`](../../OPERATIONS.md) §0.

## What is baseline

The portfolio-server release tree that is **running after the stop-truth fix**:

| Item | Value |
|------|--------|
| Path | `~/trade-ai-releases/portfolio-server/af45096e-platform-audit-20260802` |
| Branch | `wt/cursor-guardrails` |
| How to read tip | `git rev-parse origin/wt/cursor-guardrails` |
| Stamp | `$LIVE/SOURCE_COMMIT` + `$LIVE/RELEASE_NOTE` must match git tip after deploy |
| Smoke | `/api/v2/holdings/live-stops` → ~16 Schwab+Alpaca protective stops (**not** MU-only) |

**Live-after-fix is the baseline.** Do not force-push git in a way that drops live code unless the operator approved a deliberate live rollback.

## Stop-truth root cause (do not regress)

1. Release trees must ship `config/broker_credentials.env` as a **0600 symlink** to the rebuild secrets file (Fernet key `SCHWAB_TOKEN_ENC_KEY`). Without it, Schwab account hashes cannot decrypt → order reads return `needs_account_hash` → Portfolio shows **NO STOP** while ToS still has working stops.
2. `broker_secrets.load_into_env` must **not** latch `_loaded=True` when the secrets file is missing (fixed on baseline).
3. `/api/v2/holdings/live-stops` exposes `schwab_hash_ok_accounts`, `schwab_hash_missing_accounts`, `broker_stop_read_ok_accounts`, and `warning` so hash failures are not silent.

## Deploy rule for any new release dir

```bash
ln -sfn /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/broker_credentials.env \
  <release>/config/broker_credentials.env
chmod 600 /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/broker_credentials.env
```

### After create / rsync / copy

1. Confirm secrets link: `test -L <release>/config/broker_credentials.env`
2. Stamp: `git rev-parse HEAD > <release>/SOURCE_COMMIT` (and a short `RELEASE_NOTE`)
3. Restart if needed: `systemctl --user restart portfolio-server.service`
4. Smoke:
   ```bash
   curl -s localhost:7777/api/v2/holdings/live-stops | python3 -c \
     "import sys,json;d=json.load(sys.stdin);x=d.get('data')or d;print(len(x.get('by_key')or{}),x.get('warning'),x.get('schwab_hash_ok_accounts'))"
   ```
   Expect: count ≥ ~10, `warning` None, Schwab accounts in `hash_ok`.

Never commit the secrets file. Never rsync a release without re-linking secrets.
No mid-stack “push every commit then half-deploy” — land a coherent tip, then deploy once.

## Git pairing

| Action | Required pair |
|--------|----------------|
| Hotfix on live | Same diff committed to `wt/cursor-guardrails`; update `$LIVE/SOURCE_COMMIT` |
| Reset / rewrite git | Update live the same way **or** operator-approved live rollback |
| New release dir | Secrets symlink + SOURCE_COMMIT + smoke above |

## Code touchpoints

| Concern | File / API |
|---------|------------|
| Secrets load (no false latch) | `scripts/broker_secrets.py` |
| Live stops + hash diagnostics | `scripts/api_v2.py` → `_holdings_live_stops` |
| Account hash decrypt | `scripts/schwab_transport.py` → `_get_hash` |
| Broker stop map | `scripts/open_trades_intelligence.py` → `_broker_protective_stops` |
| API smoke | `GET /api/v2/holdings/live-stops` |
