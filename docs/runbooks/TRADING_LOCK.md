# Trading lock (READ-ONLY toward brokers) — operator runbook

Status:      DRAFT (code on branch fix/trading-read-only-lock-20261014; not deployed)
as_of:       2026-10-14T16:30:00-04:00
Measured at: branch fix/trading-read-only-lock-20261014 (base 125758051) / not measured live

**Why:** incident SPCX 2026-10-14. Operator directive: "lock it, block cancels too". The system is
READ-ONLY toward every broker. Stopping is easy and re-enabling is hard. Fail secure: if the lock state
is missing, unreadable, malformed, expired or ambiguous, trading is LOCKED.

## What the lock does

`scripts/lib/trading_lock.py` · `assert_trading_unlocked(action, broker=…, account=…, caller=…)`
runs before every broker write: place, replace AND cancel. It runs on these paths:

- the Schwab transport and the raw schwab-py client;
- the legacy Schwab adapter;
- every pilot, the intent router, approval confirm and request;
- the execution guard and the kill switches;
- OCO and the batch stop requester;
- the synthetic-stop and broker-trade monitors;
- SnapTrade, tastytrade and moomoo;
- the Alpaca LIVE factory branch;
- the Telegram `bkapprove` button;
- every API order route and pilot arm.

`tests/test_trading_lock_coverage_20261014.py` is the full, enforced list.

When the lock refuses a write:
- nothing is sent to the broker, and no approval is recorded or consumed;
- one JSONL row is appended to `<persistent-state>/data/runtime/trading_lock_audit.jsonl`;
- at most one P0 Telegram alert per caller per hour goes out
  (`send_telegram(priority="P1", dedupe_minutes=0, producer="trading_lock")`, which is never digested).

The lock takes precedence over every arm state. The stored arm stays untouched in Postgres:
- `system_controls` keys `broker_live_enabled`, `schwab_pilot_standing_unlock`, `pilot_armed_until`
  (2099-12-31), `protective_stops_enabled`, `options_execution_enabled`, `fidelity_stops_enabled`;
- the `broker_live_approvals` table;
- `broker_accounts.api_write_enabled`;
- the env var `BROKER_LIVE_ENABLED`.

`schwab_pilot_arm.py --status` shows the stored arm as `arm_state_armed` and the effective state as
`armed` (false while locked). Arming is refused while locked. Disarming is always allowed.

**Alpaca PAPER is allowed while locked** (paper is training), but only for the exact host
`paper-api.alpaca.markets`. Every other Alpaca host is live and locked.

## Lock state

| File | Effect |
|---|---|
| `~/.local/state/tradeai/TRADING_LOCKED` (any content) | **Locked**, whatever the unlock file says. Any process may create it: this is the PANIC switch. |
| `~/.config/tradeai/trading_unlock.json` absent | **Locked** (the default). |
| `~/.config/tradeai/trading_unlock.json` valid (see below) | Unlocked for the listed brokers and actions until `unlocked_until`. |

No code path creates the unlock file. Only the operator does, by hand, until the later step adds an unlock UI
with WebAuthn, TOTP and a cool-down.

## Stop trading (instant, no MFA)

```bash
mkdir -p ~/.local/state/tradeai && date -Is > ~/.local/state/tradeai/TRADING_LOCKED
rm -f ~/.config/tradeai/trading_unlock.json
```

## Unlock (operator only, by hand, at most 24h)

1. Confirm why you are unlocking, and keep the window as short as possible.
2. Write the file. The rules are:
   - the timestamp MUST carry a timezone;
   - it must be no more than 24h ahead, or the file counts as malformed and stays locked;
   - list the brokers explicitly;
   - `actions` is optional (place, replace, cancel); leave it out to mean all three. A Schwab stop
     *replace* is cancel-then-place, so it needs all three.

```bash
mkdir -p ~/.config/tradeai
cat > ~/.config/tradeai/trading_unlock.json <<'JSON'
{
  "unlocked_until": "2026-10-15T16:00:00-04:00",
  "reason": "replace SPCX protective stop after review",
  "operator": "john",
  "brokers": ["schwab"],
  "actions": ["cancel", "place", "replace"]
}
JSON
chmod 600 ~/.config/tradeai/trading_unlock.json
rm -f ~/.local/state/tradeai/TRADING_LOCKED   # the PANIC file wins over any unlock
python3 scripts/lib/trading_lock.py           # prints the effective state; expect "locked": false
```

The file must be a regular file (not a symlink), owned by you, mode `600` (no group or world write), and at
most 4 KiB. Anything else locks.

3. Re-lock as soon as you are done. Delete the file, or create the PANIC file. It also re-locks by itself
   at `unlocked_until`.

## Checks

- Effective state: `python3 scripts/lib/trading_lock.py`.
- Refusals: `tail <persistent-state>/data/runtime/trading_lock_audit.jsonl`.
- Pilot arm vs effective: `python3 scripts/schwab_pilot_arm.py --status` (`trading_locked`,
  `arm_state_armed`, `armed`).

## Limits (honest residuals)

- The lock is code. Only code copies that contain it honour it (SR-6: hundreds of worktree and release
  copies of `schwab_transport.py`). Until every served copy is replaced, credential revocation at Schwab
  stays the authoritative kill.
- Any process running as uid `johnclaw` can write the unlock file. Real separation needs a different uid
  for the unlock service (the later step).
- Resting orders already at the broker (the SPCX case) are not touched. Cancels are locked too.
- Fidelity monitored stops (software alerts) cannot be armed while locked, and a synthetic-stop breach
  only raises a critical alert. Act manually at the broker.
