# FREE_FIRST_ONLY natural scheduler

**Date:** 2026-08-23  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  
**Paid provider dispatch:** forbidden  

This is the source-controlled production timer that #489 lacked.

## Why

`scripts/free_first_refresh.py --circulate` was merged and proven on CURRENT by a **manual** operator pass. No cron or systemd unit invoked it. The existing timers are not substitutes:

| Unit | Why not the proof vehicle |
|---|---|
| `tradeai-hermes-cio-worker` | old paid `--backend live` drain; already 429 `COST_CAP_EXCEEDED` |
| `hermes-librarian-backlog-loop` | rebuild WorkingDirectory, not CURRENT `#489` lineage |
| rebuild crontab Hermes fleet | dual-root `$PROJ` |

## Units

| | |
|---|---|
| service | `config/systemd/user/tradeai-free-first-circulation.service` |
| timer | `config/systemd/user/tradeai-free-first-circulation.timer` |
| wrapper | `scripts/run_free_first_circulation.sh` |
| installer | `scripts/install_free_first_circulation_timer.sh` |
| lock | `/tmp/tradeai_free_first_circulation.lock` (`flock -n -E 75` + python fcntl) |
| log | `CURRENT/logs/free_first_circulation.log` |
| receipt | `CURRENT/data/cio/free_first_last_run.json` |

## ExecStart contract

WorkingDirectory = `~/trade-ai-releases/portfolio-server/CURRENT`

```
flock -n -E 75 /tmp/tradeai_free_first_circulation.lock
bash CURRENT/scripts/run_free_first_circulation.sh
  → python scripts/free_first_refresh.py --root CURRENT --circulate --json --max-searx 1
```

`--max-searx 1` **enables residual SearXNG only**. `circulate_symbol` still skips names already resolved by Hermes/RAG/structured. It is not a 120-symbol search.

`HERMES_BACKEND=live` is **not** set. `dispatch_paid_provider` remains unreachable. A name may finish `NO_NEW_INFO` / `FRESH_NO_CHANGE` / `LLM_ELIGIBLE_NOT_AUTHORIZED`. It may not result in a paid call.

## Cadence

**Hourly at :23 America/New_York**, `Persistent=true`, `RandomizedDelaySec=90`.

Why not every 15 minutes: a 120-symbol circulate is delta-driven persistent intelligence (~2.5–5 min measured), not a quote loop. :23 sits between `hermes-cio-worker` :00/:15/:30/:45.

## Install

```
# from exact-main / CURRENT after merge
bash scripts/install_free_first_circulation_timer.sh --now
```

`--now` enables the **timer**, not the oneshot service. Do not `systemctl start tradeai-free-first-circulation.service` for proof.

Overlap: second invocation exits 75 / `FreeFirstOverlap@v1` without killing the first worker.

## Health

`NO_NEW_INFO` is a healthy last run. Timer freshness does **not** mean “must call an LLM.” See `scripts/lib/free_first_scheduler_health.py`.

Host `ExecStart` is the bash wrapper **without** systemd `flock` (python `fcntl` only). Do not re-run the installer from CURRENT after promote — the repo unit file still mentions flock.

## Observed natural fires

| tick | LastTrigger ET | finished | run_id | source | exit | shape |
|---|---|---|---|---|---|---|
| 1 | 2026-08-23 22:24:15 | 22:27:05 | `433f8a56-…` | `3dd6f8d5` | 0 | 117/2/1/0/120/0 |
| 2 | 2026-08-23 23:23:11 | 23:25:57 | `6458ea63-…` | `3dd6f8d5` | 0 | 117/2/1/0/120/0 |
| post-#492 | 2026-08-24 00:23:52 | 00:26:51 | `62652d0c-…` | `bc6ff5c6` | 0 | 117/2/1/0/120/0 |

NextElapse after post-C: **2026-08-24 01:24:27 EDT**. Do not `systemctl start` the service for proof.
