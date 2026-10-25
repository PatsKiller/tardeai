# Premarket 1-minute cadence — operator crontab packet (2026-10-23)

**Retained historical proposal, 2026-10-24:** the [WP-24 content-only port](../../WP24_PREMARKET_STALE_MERGE_20261024.md)
does not install this packet or authorize host scheduling. Its fake-crontab tests use private fixtures only.
The captured lines and commands below preserve the original proposal; they are not current host evidence,
native n8n scheduling or a newly accepted change packet. Sender, cadence, unified and focus remain SHADOW.

```
Status:      PROPOSED — operator-run; the agent never ran it against the live crontab
as_of:       2026-10-23T09:30:00-04:00
Measured at: crontab -l captured read-only 2026-10-23 (both old lines present exactly once)
```

Operator decision 2026-10-23 (verbatim): "I agree for every minute, because on manually, I do a 1 minute candle
check." Design and the live switch: `docs/implementation/PREMARKET_1MIN_THREADED.md`.

## What it changes

Two crontab lines change, each matched by its **exact text**, never by line number.

### 1. `active-trader-premarket-watch`

Before:

```
*/5 6-9 * * 1-5 cd $PROJ && flock -n /tmp/at_premarket.lock timeout 240 $PY scripts/active_trader/premarket_watch.py --apply >> logs/at_premarket_watch.log 2>&1
```

After:

```
*/5 6-9 * * 1-5 cd $PROJ && flock -n /tmp/at_premarket.lock timeout 13200 $PY scripts/active_trader/premarket_watch.py --apply --loop >> logs/at_premarket_watch.log 2>&1
```

- The cron-launched loop ticks on every closed 1-minute candle and exits at window end.
- While it runs, each `*/5` relaunch finds the flock held and exits at once. A dead loop restarts within 5 minutes.

### 2. `finviz-momentum-scalp-early-lane`

The single `*/5 6-11 … --refresh-if-older-min 15 …` line becomes two:

- `*/5 6-9 … --refresh-if-older-min 5 …`
- `*/5 10-11 … --refresh-if-older-min 15 …`

Everything else on the line is unchanged: lock, deadline and stages.

**Finding.** The `scalp-hot-list` line (`*/2 6-9`) shares the refresh receipt and already keeps it ≤ 2 minutes old
from 06:00 to 09:58. The 5-minute threshold is a safety net for when the hot line fails or is killed.

The 2026-10-24 rebuild is journal-only: premarket sender, cadence and focus mode are SHADOW. Publishing and
deploying that candidate would change main's old premarket SEND behavior even before this packet is applied.
RTH `active_trader_alerts.mode: send` is unchanged. New threaded delivery and focus filtering require separate
operator promotion; changing cadence alone does not enable either.

The measurement above is historical input from the original proposal. This rebuild did not collect a fresh
host census or approve these lines. A current approved capture and replacement review remain operator work.

## Run

Run this after 09:35 ET or before 05:55 ET. The script refuses inside the premarket window.

```
bash docs/ops/packets/premarket-1min-20261023/install.sh --preview   # backup + exact diff, changes nothing
bash docs/ops/packets/premarket-1min-20261023/install.sh             # same, then type APPLY
```

## Safety checks

- **Host and user.** Refuses unless running as `ms01-openclaw` / `johnclaw`.
- **Served release.** Refuses unless the served release (crontab `PROJ`) already has `--loop` and `cadence_mode`.
  Serve the PR first.
- **Backup.** `~/.cache/crontab.bak-<UTC>`, taken before anything else. Never deleted.
- **Exact-text match.** Each old line must be present exactly once. If the new lines are already there, the step
  reports `already applied`. Any drift → `REFUSED`, nothing changed.
- **Drift since preview.** Before installing, the crontab is re-read into a file and compared byte for byte with
  the preview.
- **Verify.** After installing, `crontab -l` is captured to a file, compared byte for byte with the candidate, and
  each new line is checked to be present exactly once. It never pipes `crontab -l | grep -q` under pipefail (the
  SIGPIPE false-FAILED fixed in PR #1965).
- **Rollback.** `crontab ~/.cache/crontab.bak-<UTC>`. The script prints the exact command.

## Historical post-install expectations — no installation in this port

- On the next qualifying market session after a separately approved installation, from 06:00,
  `logs/at_premarket_watch.log` is expected to show `[1m]` (state changes) and `[focus]` (in/out) lines every minute.
- The heartbeat `data/active_trader/momentum_alerts_premarket_heartbeat.json` advances each minute.
- Compare the session with `python3 scripts/premarket_cadence_compare.py --day <date>`. Future promotion needs a
  separate operator decision for the independent sender, cadence, unified and focus modes; this port keeps them SHADOW.
- The registry rows `active-trader-premarket-watch` and `finviz-momentum-scalp-early-lane` carry `pending_change`
  with these lines. Fold it into `scheduler` once installed (registry-truth PR).
