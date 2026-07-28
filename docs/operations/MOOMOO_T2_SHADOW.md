# Moomoo OpenD / T2 (L2 depth) — operations

**Status 2026-07-28:** OpenD running and authenticated. L2 depth entitled and flowing
into observations. **Scoring is still T0 — depth influences no decision yet.**

---

## What is live

| Piece | State |
|---|---|
| OpenD daemon | `trade-ai-lab-moomoo-opend.service` — active, enabled, linger on (survives reboot) |
| Credentials | Bitwarden SM: `MOOMOO_OPEND_LOGIN_ACCOUNT`, `MOOMOO_OPEND_LOGIN_PWD_MD5` (MD5, never plaintext) |
| Entitlement | `AVAILABLE_REALTIME` — proven by probe, quota `remain 99` |
| Health probe | `scripts/moomoo/opend_health.py`, every 5 min 06–17 M-F, Telegram after 3 failures |
| Depth → observations | `MoomooT2Provider.fetch_book()` → normalized `ORDER_BOOK` Observation, `DataTier.T2` |
| **Scoring** | **T0 / dcf 0.4 / 40 bps assumed slippage — UNCHANGED** |

## Credential handling

Credentials never live in a file on disk and never in `argv`:

1. Bitwarden Secrets Manager is the source of truth.
2. `opend_launch.sh` reads the tmpfs render (`$XDG_RUNTIME_DIR/tradeai/env`) and writes a
   **0600 config on tmpfs**, then starts OpenD with `-cfg_file=<path>`.
3. `ExecStopPost` deletes the rendered config when the unit stops.

`OpenD.xml` on disk has `login_account` / `login_pwd` **blank**. It previously held the
vendor placeholder `123456`, which is why 2026-07-23 logged
`Login failed, Password does not match` and exited (status 14, six times).

> Passing the credential as `-login_pwd_md5=` on the command line leaked it to any
> process via `/proc/<pid>/cmdline`. Do not reintroduce that.

To rotate:
```bash
.venv/bin/python scripts/moomoo/opend_credentials.py --set
systemctl --user restart trade-ai-lab-moomoo-opend.service
.venv/bin/python scripts/moomoo/opend_health.py      # quote round-trip = real proof
```

## Why the quote round-trip is the health gate

OpenD **binds `127.0.0.1:11111` before it authenticates**. On 2026-07-23 it listened and
exited seconds later on a bad password. A reachable port therefore proves nothing; only a
successful query proves login. `opend_health.py` treats the quote as the gate and unit
state as context — it does *not* AND in `systemctl`, because cron cannot reach the user
bus and reported `unknown`, which called a healthy plane DOWN seven times.

## The T2 shadow (P3) — what it collects and why

`scalp_t2_shadow` records, per armed symbol/minute, the real book metrics and the tier
that **would** have applied, beside the T0 values that actually drove scoring.

`scalp_ignition_events` is deliberately untouched: it keeps writing `data_tier='T0'`
and `dcf=0.4`, so gates, sizing and the permission queue behave exactly as before.

Compare a session:
```sql
SELECT symbol, minute_of_session,
       t0_spread_bps, t2_spread_bps,
       t2_book_imbalance, live_dcf, would_be_dcf, would_be_slip_bps
  FROM scalp_t2_shadow
 WHERE session_date = CURRENT_DATE AND t2_available
 ORDER BY minute_of_session;
```

## Promotion to live scoring (P4) — NOT done, needs an explicit decision

Promoting T2 changes two numbers that make signals **more likely to fire and size larger**:

| | T0 (today) | T2 |
|---|---|---|
| data confidence (`dcf`) | 0.40 | 1.00 (**2.5×**) |
| assumed slippage | 40 bps | 8 bps (**5×** tighter) |

Two reasons this is not automatic:

1. **The T2 module argues against it.** `scalp_t2_metrics.py` states depth
   *"may only ever SIZE DOWN, never justify sizing up"* — displayed size understates true
   size (hidden/venue liquidity). Raising `dcf` on T2 is sizing up, which is in tension
   with that caveat.
2. **No evidence yet.** Collect a shadow period first and compare T0-inferred spread
   against real quoted spread on the same minutes.

When promoting, flip **one** of:
- `data_tiers.active_tier: T2` in `config/scalp_signal_engine.yaml`, or
- `t2.feeds_scoring: true`

`read_api._t2_feeds_scoring()` reads exactly these, and the ActiveTrader panel shows
`l2.feeding_scoring` — so "L2 is connected" can never be mistaken for "L2 is moving
decisions".

## Boundaries

- **No order path.** `MoomooClient` hard-refuses `place_order`, `unlock_trade`,
  `cancel_order` et al. `broker_accounts.moomoo_data_plane` has
  `api_write_enabled=false`, `is_enabled=false`, automation `DISABLED`.
- **Conserving.** L2 is subscribed only while a symbol is armed (FSM `ARMED`), capped at
  `t2.max_armed` (8) with a `ttl_seconds` (180) auto-disarm. `disarm()` releases the real
  subscription — not just the budget slot.
- **Fail-closed.** OpenD down or no fetcher ⇒ `SCAFFOLD_ONLY` and `fetch_book()` returns
  `None`. A T2 capability is never manufactured.

## Gotchas

- **futu threads are non-daemon.** An open context keeps the interpreter alive forever;
  a cron scan would never exit. `FutuTransport` sets `SysConfig.set_all_thread_daemon(True)`
  and registers an `atexit` close.
- **futu logging.** The SDK installs `FTConsoleLog` (stdout, INFO) and `FTFileLog` at
  import; the console one corrupts JSON output and `redirect_stdout` alone cannot stop it
  (its handler binds the real stdout at import). Use `quiet_futu_logging()`.
- **Two security firms.** `SecurityFirm.FUTUSECURITIES` shows only the SIMULATE account;
  the REAL US account lives under `SecurityFirm.FUTUINC`. Querying the wrong one looks
  exactly like "no live account exists".
