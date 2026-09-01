Status:      ACTIVE
as_of:       2026-09-01T15:22:56-04:00
Measured at: CURRENT 18a3da0dc (BUILD_SHA, by file content) · origin/main ac4b37cea · $PROJ 0a591048b
Canonical repo path: docs/ops/litmus/LITMUS_LANES_2026-09-01.md
Authority:   discovery only — measurement, no product change, no lane declared
See also:    config/lane_registry.json · scripts/lib/lane_registry.py
             docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md (line 174, "four confirmed
             checkout-relative splits")

# Litmus A — lanes

Slice A of a two-slice litmus. **Discovery only.** No lane was declared, no crontab touched,
no code changed.

## Pre-flight

```
worktree (hub)   0a591048b
origin/main      ac4b37cea
CURRENT BUILD_SHA 18a3da0dc      <- file content, not git log inside CURRENT
CURRENT resolved  /home/johnclaw/trade-ai-releases/portfolio-server/18a3da0dc-…-143119
$PROJ            0a591048b
$PROJ == origin/main : NO — lags by ac4b37cea (#830), 18a3da0dc (#829), 8898c7fbb (#828)
```

Reported and measurement continued against CURRENT, per instruction. **This lag is itself
load-bearing for finding F1** and is not incidental.

Twin search over 34 open PRs: **#777** (`fix/cash-freshness`) is adjacent but is a product
fix for one field's derivation, not a lane census; **#150** contains the word "litmus" but is
Active Trader Stage 0, DRAFT, different domain. Neither is a twin.

## Format note

The prescribed row is `surface | endpoint | field | writer | clock | as_of | verdict`. A lane
has no endpoint, so this slice reads it as
**`lane | scheduler | declared signal | writer | clock | as_of | verdict`** — same seven
columns, one renamed. Said out loud rather than silently substituted.

---

## F1 — The lane monitor's verdict depends on which checkout it is imported from

**21 of 64 lanes (33%) return a different verdict for the same registry at the same instant.**

```
lane_registry.py:42   ROOT = Path(__file__).resolve().parent.parent.parent
lane_registry.py:194  root = Path(root) if root else ROOT
lane_registry.py:200  if not p.is_absolute(): p = root / p
```

Every `output_signal.path` in the registry is **relative**. It is resolved against the repo
root of whichever tree the module was imported from. There are two such trees in production
and they are not the same filesystem:

| dir | CURRENT | $PROJ (hub) |
|---|---|---|
| `data/cio` | SYMLINK → persistent-state | **real dir** |
| `data/runtime` | SYMLINK → persistent-state | **real dir** |
| `data/portfolios/state` | SYMLINK → persistent-state | **real dir** |

Inode proof, four samples, **none shared**:

```
data/portfolios/state/price_cache.json   CURRENT inode 4390820   $PROJ inode 2886605
data/cio/wake_record_consult.json        CURRENT inode 3483747   $PROJ  (absent)
data/runtime/sm_render_state.json        CURRENT inode 9633670   $PROJ inode 3572552
data/runtime/research_lane_health.json   CURRENT inode 9633723   $PROJ inode 3571843
```

The flip is **bidirectional**, which is what makes it a split rather than a lag — 13 lanes are
LIVE only from the served tree, 8 are LIVE only from the hub:

| lane | from CURRENT | from $PROJ | age CURRENT | age $PROJ |
|---|---|---|---|---|
| cio-wake-dispatch | LIVE | SILENT | 0.0h | absent |
| cio-material-scan | LIVE | SILENT | 0.1h | absent |
| research-lane-health | LIVE | SILENT | 0.1h | 244.5h |
| cio-reactive-cycle | LIVE | SILENT | 0.0h | 148.8h |
| due-checkpoints | LIVE | SILENT | 0.0h | 149.1h |
| autonomy-watchdog | LIVE | SILENT | 0.0h | 148.9h |
| free-first-circulation | LIVE | SILENT | 0.8h | 148.9h |
| cio-wake-turn-effects | LIVE | SILENT | 0.7h | absent |
| hermes-momentum-catalyst-morning | LIVE | SILENT | 0.8h | absent |
| cio-nightly-reflection | LIVE | SILENT | 17.5h | 161.5h |
| cio-memory-shadow-measure | LIVE | SILENT | 9.0h | 153.0h |
| provider-cost-reconcile | LIVE | SILENT | 8.7h | 152.7h |
| advisory-shadow-seed | LIVE | SILENT | 17.6h | 161.6h |
| governance-pipeline | **SILENT** | LIVE | 151.7h | 7.7h |
| sm-render | **SILENT** | LIVE | 52.3h | 0.8h |
| tax-lots-rebuild | **SILENT** | LIVE | 152.1h | 8.1h |
| holdings-agent-enqueue | **SILENT** | LIVE | 150.8h | 1.8h |
| hermes-update-check | SLOW | LIVE | 204.3h | 36.2h |
| portfolio-weekly-cadence | SLOW | LIVE | 210.7h | 42.7h |
| portfolio-price-cache | SLOW | LIVE | 210.7h | 42.7h |
| portfolio-live-monitor | **SILENT** | SLOW | 210.7h | 42.7h |

**verdict: SPLIT** — one registry, two data planes, and the monitor reports whichever plane
its own import path lands in.

> This is the mechanism behind the "four confirmed checkout-relative splits" named in
> `CIO_ASIS_VS_SPEC_2026-08-30.md` line 174. The census puts the number at **21 of 64 lanes**,
> measured, not four.

---

## F2 — `portfolio-price-cache`: the timer succeeds and the served artifact does not move

| | |
|---|---|
| lane | `portfolio-price-cache` (ACTIVE) |
| scheduler | **user** timer `portfolio-price-cache.timer`, enabled, `OnCalendar=Sun *-*-* 19:00:00` |
| declared signal | `file_mtime: data/portfolios/state/price_cache.json`, cadence **168h** |
| writer | `linux_launchers/run_price_cache.sh` → `portfolio_price_cache.py --project-root .`, `WorkingDirectory=$PROJ` |
| clock | file mtime |
| as_of (served) | **2026-08-23 20:37** — 210.7h / 8.8 days |
| as_of (hub) | 2026-08-30 20:35 — 42.7h |

```
systemctl --user show portfolio-price-cache.service
  Result=success   ExecMainStatus=0   ExecMainExitTimestamp=Sun 2026-08-30 19:00:24 EDT
```

The run exited **0** ~44h ago. The **served** artifact is 8.8 days old. It writes the hub copy
because its `WorkingDirectory` is `$PROJ`; everything that reads it does so through CURRENT.

**verdict: SPLIT** — AGENTS.md §0.8, *"exit code 0 is not evidence of work."* Here the work
happened; it landed in the tree nobody serves.

*Correction to my own first reading:* I initially reported this timer as unknown to systemd.
That was wrong — I ran `ls` against `/etc/systemd/system` and `~/.config/systemd/user` in one
command and attributed the combined output to the first. These are **user** units and
`systemctl --user` finds them.

---

## F3 — `portfolio-live-monitor`: fires every 20 minutes, produces nothing

| | |
|---|---|
| lane | `portfolio-live-monitor` (ACTIVE) |
| scheduler | cron 440 — `*/20 9-16 * * 1-5 cd $PROJ && flock -n … portfolio_live_monitor.py` |
| declared signal | `file_mtime: data/portfolios/state/price_cache.json`, cadence **24h** |
| writer | `scripts/portfolio_live_monitor.py` |
| clock | file mtime |
| as_of (served) | 210.7h |
| log | `$PROJ/logs/portfolio_live_monitor.log` — **0 bytes**, mtime 2026-09-01 10:00:01 |

Declared expression matches the installed line exactly. It runs; its declared signal has not
moved in 8.8 days; its log is empty. A `*/20` job whose output signal is declared at 24h
cannot fail a cadence check for 72 consecutive missed runs.

**verdict: STALE**

---

## F4 — Two lanes declare the same artifact, with different cadences

`portfolio-live-monitor` (24h) and `portfolio-price-cache` (168h) both declare
`data/portfolios/state/price_cache.json` as their `output_signal`.

One file cannot answer two cadence questions, and neither lane's liveness can be
distinguished from the other's by it: whichever writes last exonerates both. At 210.7h the
served copy is stale against **both** declarations.

**verdict: SPLIT**

---

## F5 — `warm-caches`: the one clean lane of the four

| | |
|---|---|
| scheduler | cron 592 — `*/8 * * * * … warm_caches.py` (matches declared) |
| declared signal | `file_mtime: data/runtime/rotation_summary_cache.json`, cadence **1h** |
| as_of | **0.02h** — fresh from both roots |

**verdict: LIVE.** One caveat, from the registry's own note: *"DECLARED BY THE INTEGRATOR, not
this lane's owner … the cron was added while PRs were in flight and check_lane_registry failed
on clean main, blocking every merge."* Declared cadence 1h against a `*/8` schedule is **7.5×
looser than the actual**, so the lane could miss 7 of 8 runs and still read LIVE. Correct
today by luck of freshness, not by the tightness of its declaration.

---

## F6 — Crontab 949 (`cio-wake-dispatch`): registry expression no longer describes the line

| | |
|---|---|
| declared expression | `*/5 * * * * cio_wake_dispatch_entrypoint.py` |
| installed line 949 | `*/5 * * * * cd …/CURRENT && flock -n -E 99 -o /tmp/cio_wake_dispatch.lock timeout -k 60s 15m … cio_wake_dispatch_entrypoint.py …` |
| declared signal | `json_key: data/cio/wake_record_consult.json`, cadence 0.25h — **0.0h, LIVE** from served |

The `match` token (`cio_wake_dispatch_entrypoint.py`) still resolves, so the gate is satisfied
and nothing is broken. The declared *expression* is now a description of a command that is not
the installed one — a documentation drift the registry has no check for, because
`_scheduler_present` matches on the token, never on the expression.

Also observed: the artifact `data/cio/wake_research_persist.json` is **not any lane's declared
signal**, and it is **overwritten every cycle** — a hit is unrecoverable from it five minutes
later.

**verdict: LIVE** (drift noted, not a finding against liveness)

---

## F7 — The repricer: three schedulers, no lane, permanently exempt

`portfolio_repricer.py` writes `holdings.json`, `data_as_of` (`compute_data_as_of`, line 53,
applied line 780) and reads `price_cache.json` (line 286). It is the writer behind the numbers
Slice B is measuring.

Three installed cron lines:

```
509  10 16 * * 1-5    cd  && safe_flock … portfolio_repricer.py && holdings_reconcile.py --apply && …
642  */15 9-16 * * 1-5 cd  && safe_flock … portfolio_repricer.py
643  5 9 * * 1-5       cd  && safe_flock … portfolio_repricer.py
```

**No lane row exists for it.** It is not reported as undeclared either: 5 matching entries sit
in `undeclared_baseline`, which exempts them permanently.

**verdict: DARK** — the most consequential writer on the box has no declared cadence, no
declared output signal, and no verdict any monitor can produce.

---

## F8 — The liveness verdict reaches no gate and no schedule

- `check_lane_registry.py` — the gate wired into `ai_local_acceptance.sh` (line 108,
  `--fail-on-new`) — evaluates **structure and undeclared-ness only**. It never calls
  `evaluate_lane`. Nothing it reports is a liveness verdict.
- `report_store_cadence.py` **does** produce verdicts and has `--fail-on-finding` (exit 1 on
  SILENT/ORPHANED). Its own docstring says it exists so a SILENT verdict reaches an operator.
- Scheduler references to it: **crontab 0, systemd units 0.**

So every SILENT and SPLIT above is computable today and is computed by nothing on a schedule.

**verdict: DARK** — AGENTS.md §9.1, *"a verdict that reaches only a log file has not reached
the operator"*; here it does not reach even a log file, because nothing runs it.

### Gate coverage, for scale

```
schedulers discovered : 494 cron + 94 systemd = 588
declared lanes        : 64
undeclared_baseline   : 535   (permanently exempt)
undeclared findings   : 0     -> gate reports "clean"
```

The gate is a **change detector on a shrink-only baseline**, not a coverage measure. "Lane
registry: clean" means *no new undeclared scheduler appeared*, and is compatible with 535
exempt schedulers and 21 split verdicts.

---

## Summary

| # | subject | verdict |
|---|---|---|
| F1 | 21/64 lanes, verdict depends on importer's checkout | **SPLIT** |
| F2 | `portfolio-price-cache` timer exits 0, served artifact 8.8d old | **SPLIT** |
| F3 | `portfolio-live-monitor` fires `*/20`, empty log, signal 210.7h | **STALE** |
| F4 | two lanes declare one artifact, cadences 24h vs 168h | **SPLIT** |
| F5 | `warm-caches` fresh; declared cadence 7.5× looser than schedule | **LIVE** |
| F6 | crontab 949 installed command ≠ declared expression | **LIVE** (drift) |
| F7 | repricer: 3 schedulers, no lane, baseline-exempt | **DARK** |
| F8 | liveness verdict has a reporter and no scheduler | **DARK** |

## Not done

No lane declared. No crontab, no `docs/INDEX.md`, no `$PROJ` fast-forward, no promote, no
push, no PR. `BehaviorWriteRefused` untouched. No remediation proposed — this is Slice A
discovery, and every item above is a measurement, not a plan.
