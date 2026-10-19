# Active Trader motion runtime back up, supervised by n8n (2026-10-19)

```
Status:      PACKET (unit fix + watchdog code/config + tests in the PR; marker, unit install, start, live list and
             relay restarts are NOT done: operator)
as_of:       2026-10-19
Authority:   operator decision 2026-10-19 (keep the loop on systemd; n8n owns its supervision); AGENTS.md §0 rules 2/7,
             §23.3, §23.23, §24.1, §24.10
Targets:     ~/.config/systemd/user/tradeai-active-trader-motion.service (gate line fix), /etc/tradeai marker (operator),
             lane active-trader-motion-watchdog -> TRADEAI_N8N_RELAY_LIVE_LANES
Live apply:  cutover.sh install|start|relay --apply under a verified guard grant id; rollback --apply reverses the relay
```

## Why the runtime is down

`tradeai-active-trader-motion.service` runs `python -m active_trader.motion_runtime`. It is the long-running producer
of the Active Trader motion journal, with a 5, 10 or 30 second cadence. It holds no broker or order authority: every
heartbeat `authority` field is false. It ran healthy for 209,263 cycles until a clean stop on 2026-10-10 at 21:43 ET.
It has not restarted since, for this reason:

| | installed copy (2026-10-10) | served repo before this PR | this PR |
|---|---|---|---|
| `ConditionPathExists=` | `/etc/` + misspelt `tardeai` dir (never existed) | `%h/.config/tradeai/enable-active-trader-motion` | **`/etc/tradeai/enable-active-trader-motion`** |
| `EnvironmentFile=` | `-/etc/` + misspelt dir `/active-trader-motion.env` (silently skipped) | `-%h/.config/tradeai/active-trader-motion.env` | unchanged: `-%h/.config/tradeai/active-trader-motion.env` |

`systemctl --user show` (2026-10-19, read-only) reports `ConditionResult=no` with `ConditionTimestamp=Sat 2026-10-10
21:49:03 EDT`, the operator's restart attempt. `/etc/tradeai` exists, is root-owned and holds `agent_runtime_enabled`.

**Deviation from the brief, on purpose: `EnvironmentFile` is not moved to `/etc/tradeai`.** The env file that exists on
the host is the user-owned `~/.config/tradeai/active-trader-motion.env` (`-rw-------`, 2026-07-29). According to the
registry row evidence, that file points `ACTIVE_TRADER_MOTION_HEARTBEAT` (and the journal and state paths) at the dev
tree. The file's values were not read (§24.7). `/etc/tradeai/active-trader-motion.env` does not exist. Because the
`-` prefix makes systemd skip a missing file silently, moving the line there would start the runtime on its
release-relative defaults. The heartbeat would then land where neither the watchdog nor the API looks, which is the
K-04 silent-default failure (`scripts/check_unit_env_files.py`). The repo unit has named the user-owned file since
2026-10-04. Only the marker moves to the root-owned `/etc/tradeai`, per the operator's gate decision. To move the env
file as well, the operator must first copy it into `/etc/tradeai` (root) and then change this line in a follow-up PR.

## What n8n supervises, and how (it never restarts)

The operator decided to keep the loop on systemd: n8n's minimum schedule is 1 minute and its runs are stateless
processes. Lane `active-trader-motion-watchdog` runs `scripts/check_active_trader_motion_heartbeat.py --apply`. It is
fired by the already-active `tradeai-dispatcher` every 5 minutes.

```
motion runtime (systemd user unit) --heartbeat each cycle--> data/active_trader/motion_runtime_heartbeat.json (dev tree)
  n8n tradeai-dispatcher */5 -> relay -> gateway -> executor -> check_active_trader_motion_heartbeat.py --apply
     reads heartbeat + /proc/<pid>/cmdline + marker existence (read-only)  -> band
     band change inside the window -> ONE comms intent host/active_trader_motion_watchdog (DIGEST)
  -> n8n_comms_intent_consumer.py -> P2 incident -> n8n_incident_fanin.py -> incident_notifier.py (the only sender)
```

| band | when | alert (inside the window only) |
|---|---|---|
| HEALTHY | heartbeat age <= 120 s, status `healthy`, the pid is alive and its cmdline is the motion module | a recovery line, once, after STALE/DOWN/DEGRADED |
| STALE | the process is alive but the heartbeat is older than 120 s | once on entry |
| DEGRADED | the heartbeat is fresh but its status is not `healthy`, or `consecutive_failures` >= 3 | once on entry |
| DOWN | no heartbeat, an unreadable or wrong-contract heartbeat, or the pid is dead or reused | once on entry |
| DISABLED | the marker is absent and the runtime is not running: an operator-gated state | never; it resets the dedupe |

- **Window.** Trading days only, from 07:00 ET to the official close (13:00 on early-close days), from
  `scripts/lib/cio_market_session.py`. The runtime itself runs around the clock, so a verdict is computed and printed
  at every hour, but nothing alerts outside the window. A fault that starts overnight alerts at 07:00 ET. A calendar
  error counts as inside the window.
- **Dedupe.** The dedupe key is `last_alerted_band` in `data/runtime/active_trader_motion_watchdog_state.json`. The
  comms store adds a second layer: an identical subject within 1 h folds into the same intent. If the intent cannot be
  queued (no ledger, rate limit), the run exits 1 with `dependency_unavailable` and the band stays un-alerted, so the
  next run retries.
- **Receipt.** The run writes a LaneRunReceipt@v2 with `output=` fields. A verdict inside the window gives
  produced_count 1 and an empty one gives `market_closed` or `window_not_reached` (`empty_allowed`). The fatal reason
  is `dependency_unavailable`.
- **Thresholds and paths.** These are in `config/active_trader_motion_watchdog.json`. The 120 s threshold is four idle
  cycles (30 s idle cadence, 30 s maximum backoff).
- **Lane shape.** This mirrors `n8n-comms-intent-consumer`:

| item | value |
|---|---|
| registry `scheduler` | `{kind n8n, expression dispatcher, match scripts/check_active_trader_motion_heartbeat.py, cadence */5, stage canary, wave W1}` |
| registry `dispatch` | `{mode live, cron [*/5 * * * *], class monitor, priority 1, retry_policy transient-2}` |
| allowlist | `live_arg ["--apply"]`, `dry_run_arg ["--dry-run"]`, own flock `/tmp/tradeai_active_trader_motion_watchdog.lock`, 60 s, `output_receipt v2`, env **enforce** (closure reviewed in `tests/test_n8n_executor_env_allowlist_20261009.py`) |
| health contract | REVIEWED, canary, `expected_output` `empty_allowed` (`market_closed`, `window_not_reached`), fatal `dependency_unavailable` |
| host route | `config/host_comms_intent_routes.json` `host / active_trader_motion_watchdog`, DIGEST, producer `active_trader_motion_watchdog` |
| effect key | none. There is no cron side to fence, and effects are idempotent per band |
| workflow | **none new**. The lane is fired by the already-active `tradeai-dispatcher` |
| motion row | `tradeai-active-trader-motion-service.note` records that it is supervised by this lane (no `supervised_by` field exists in the schema) |

## First run (read-only, 2026-10-19 11:10 ET)

The result, recorded in `01_first_run.txt`, is **DISABLED**. The marker is absent, the heartbeat pid 484546 is dead,
and the last heartbeat (cycle 209263) is about 8.6 days old (2026-10-10 21:43 ET). No page fires.

## Operator sequence

```bash
P=docs/ops/packets/active-trader-motion-n8n-20261019/cutover.sh   # run from the served CURRENT or the dev tree
# 0. merge + promote this PR so CURRENT serves it
bash $P pre                                         # read-only
bash $P marker                                      # prints the next line; never runs sudo
sudo touch /etc/tradeai/enable-active-trader-motion # OPERATOR ONLY (root; AGENTS.md §24.10 item 4)
export TRADEAI_FABRIC_GRANT=$(bin/guard id config-write)   # or an execution-ops grant id for install/start
bash $P install            # dry: shows the diff
bash $P install --apply    # archives the old unit copy, installs the fixed unit, daemon-reload (no start)
bash $P start              # dry: refuses unless the session is CLOSED (20:00-04:00 ET trading days, weekends, holidays)
bash $P start --apply      # systemctl --user restart; outside CLOSED only with --force-open-hours (operator only)
bash $P proof              # heartbeat <= 60 s, cycle_count up, journal growing, pid alive, healthy, authority false
export TRADEAI_FABRIC_GRANT=$(bin/guard id config-write)
bash $P relay              # dry
bash $P relay --apply      # live list += active-trader-motion-watchdog; restart relay + gateway; read-back
# wait one */5 slot, then:
bash $P pre                # the watchdog --dry-run shows band HEALTHY
```

**Start window.** The brief asked to refuse 09:30-16:00 ET. AGENTS.md §24.10 is stricter and binds any agent acting
under `execution-ops`: a broker-execution unit is restarted only while `market_session()["state"]` is `CLOSED`, and
pre-market and post-market count as open. The safer rule wins, so `start` refuses unless the state is `CLOSED`.
`--force-open-hours` is the operator's own override and is never used under an agent grant. *Example:* on a trading
day such as Mon 2026-10-19, the earliest allowed start is 20:00 ET.

**Grants.** Every `--apply` verifies `TRADEAI_FABRIC_GRANT` against the guard ledger with `scripts/lib/fabric_grant.py`.
This is a byte-identical copy of the file in open PR #1851, which introduced the mechanism. Git merges an identical
add cleanly. `install` and `start` accept a `config-write` or `execution-ops` grant, while `relay` and `rollback`
accept `config-write` or `cron`. A free-text label is refused.

## Rollback

- `bash $P rollback --apply` removes the watchdog from the live list (with backup and read-back) and restarts relay
  and gateway. The gateway then demotes every fire to `dry_run`, which only prints.
- The motion unit is never stopped by this script. The operator-only commands are printed:
  - `systemctl --user stop tradeai-active-trader-motion.service`
  - `sudo mv /etc/tradeai/enable-active-trader-motion /etc/tradeai/enable-active-trader-motion.archived-<date>`
- To return to the previous unit file, copy back
  `~/.config/systemd/user/tradeai-active-trader-motion.service.archived-<UTC>` and run `daemon-reload`. Nothing is
  deleted (§0 rule 6).

## AGENTS.md

AGENTS.md §24.10 still records the misspelt marker path twice:

- the *Cause* note, as history of 2026-10-10;
- item 4, as a measurement of 2026-10-10. `tests/test_agents_policy_5_0_0_execution_ops.py` pins that text.

Changing either one is a PATCH, and it is **not applied here**. A PATCH needs a Policy-Version bump, a changelog row
and the operator's per-PR word to merge AGENTS.md (§23.13). It also stays true until the operator installs the fixed
unit. The draft is `AGENTS_PATCH_DRAFT.md`.

## Files

- `config/systemd/tradeai-active-trader-motion.service`: the gate line fix.
- `config/systemd/active-trader-motion.env.example`: the misspelt dir in two commented examples.
- `scripts/check_active_trader_motion_heartbeat.py` and `config/active_trader_motion_watchdog.json`.
- Wiring: `config/host_comms_intent_routes.json`, `config/lane_registry.json` (new row and motion-row note),
  `config/n8n_run_allowlist.json` and `config/n8n_health_contracts.json`.
- `scripts/lib/fabric_grant.py`: a copy of #1851.
- `tests/test_active_trader_motion_watchdog_20261019.py`, `tests/support/active_trader_motion_watchdog.py` and the
  inventory pins.
- `docs/_findings/ACTIVE_TRADER_MOTION_RUNTIME_v1.md` and `scripts/check_unit_env_files.py`: corrections.
