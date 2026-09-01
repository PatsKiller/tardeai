Status:      ACTIVE
as_of:       2026-08-31T23:22:00-04:00 (America/New_York)
Measured at: served release `d276657b7-main-exact-phase2-20260831-225546`, git pin `d276657b7`
Canonical repo path: docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md
Authority:   dated read-only observation log; not a behaviour spec
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md, AGENTS.md §15 §13.4

---

# CIO M5 timer watch — overnight 2026-08-31 → 2026-09-01

Read-only. Nothing in this pass invoked `cio_wake_dispatch_entrypoint.py`, any CIO
wake or decide script, or any cron/systemd unit. Every wake referenced below fired
on its own schedule. `MBI_BEHAVIOR = 0` throughout.

**2026-09-01 is a Tuesday — a normal trading day.**

```
$ date -d 2026-09-01 +%A
Tuesday
$ date -d 2026-09-07 +%A
Monday
```
[VERIFIED]. Labor Day 2026 falls on Monday 2026-09-07, a week later. This is a
**normal overnight into a normal session**, so low wake volume cannot be excused
as a holiday effect and must be explained or recorded as UNKNOWN. §8 explains it,
and the explanation turns out to be neither of the two the brief anticipated. An
earlier draft of this document carried the holiday framing — see Corrections §10.7.

---

## 1. Served release — resolved, not assumed

```
$ ls -la /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
lrwxrwxrwx 1 johnclaw johnclaw 93 Aug 31 22:56 /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT -> /home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546

$ readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
/home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546

$ git -C .../CURRENT log -1 --format='%h %s'
d276657b7 Merge pull request #810 from PatsKiller/feat/cio-p1-load-by-subject
```
[VERIFIED] at 2026-08-31T23:11:25 EDT, re-confirmed unchanged at 23:15:44 and
23:18:09 EDT.

The symlink was re-resolved at every measurement below. It did not rotate during
this pass. It **had** rotated twelve times on 2026-08-31 alone — see §7.

Two paths under the release resolve differently, and the difference is
load-bearing:

```
$ ls -ld .../CURRENT/logs ; readlink -f .../CURRENT/logs
lrwxrwxrwx ... CURRENT/logs -> /home/johnclaw/trade-ai-releases/persistent-state/logs

$ readlink -f .../CURRENT/data
/home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546/data
```
[VERIFIED]. **`logs/` is shared persistent state across every release; `data/` is
per-release.** So `logs/cio_wake_dispatcher.log` is a continuous record written by
a succession of different pins, and a log line older than 22:56 EDT tonight was
*not* written by the pin in this document's header. §5 and §7 stamp each window
with the pin that actually wrote it. This is the most important methodological
point in this document.

---

## 2. What schedules the wake — cron, and cron only

```
$ crontab -l | grep -n 'cio_wake_dispatch_entrypoint'
934:*/5 * * * * cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/cio_wake_dispatch_entrypoint.py >> logs/cio_wake_dispatcher.log 2>&1  # 24/7 2026-08-27: was 9-16 M-F. Catalysts, filings and overnight news do not keep market hours; a wake created outside the window sat unprocessed until the next weekday morning.

$ crontab -l | sha256sum
bd0bcb96eb1d4e00b5c8e136d0fa30857578aa7830dfe665e09b0dd7f09c287a  -
```
[VERIFIED] 2026-08-31T23:12 EDT. This is the **only** crontab line invoking the
entrypoint — exactly one match in 998 lines. `*/5 * * * *` is 24/7, every day.

`/etc/cron.d/` holds only `.placeholder`, `anacron` and `e2scrub_all` — no CIO
entry [VERIFIED]. Root's crontab could not be read (`sudo: a password is
required`). Left **UNKNOWN**, not routed around.

### systemd timers, filtered for cio/tradeai/hermes/aegis

`systemctl --user list-timers --all` lists 73 timers. None invokes the entrypoint:

```
$ grep -rl 'cio_wake_dispatch' /home/johnclaw/.config/systemd/user/
(no output)
```
[VERIFIED]. The CIO-named user timers are adjacent lanes, not the wake dispatcher:

| Timer | Cadence | Runs |
|---|---|---|
| `tradeai-cio-reactive.timer` | 2 min | `scripts/cio_reactive_cycle.py --once` |
| `tradeai-cio-delivery.timer` | 5 min | delivery lane |
| `tradeai-cio-material-scan.timer` | 10 min | material scan |
| `tradeai-hermes-cio-worker.timer` | 15 min | research queue |
| `tradeai-cio-defer-revisit.timer` | 60 min | defer revisit |
| `tradeai-cio-memory-shadow-measure.timer` | daily 06:20 | shadow measure |
| `tradeai-cio-nightly-reflection.timer` | daily 21:50 | reflection |

[VERIFIED] from `systemctl --user list-timers --all` and `systemctl --user cat
tradeai-cio-reactive.{timer,service}`.

### Ruled-out scheduled entity: `tradeai-continuous.timer`

This is the one system-level timer that fires **inside** the watch window, so it
needed clearing rather than assuming. Traced by the coordinator; every item below
was independently re-verified here before quoting.

```
$ systemctl cat tradeai-continuous.timer
OnCalendar=Mon..Fri 04:00
Persistent=true
Unit=tradeai-continuous.service
```
[VERIFIED]. 2026-09-01 is a Tuesday, so it **will** fire at 04:00 ET tonight.

```
$ systemctl status tradeai-continuous.service
   Loaded: loaded (/etc/systemd/system/tradeai-continuous.service; disabled; preset: enabled)
   Active: inactive (dead) since Mon 2026-08-31 11:31:05 EDT; 11h ago
  Process: 711485 ExecStart=/usr/bin/flock -n -E 0 /run/lock/tradeai-continuous.lock /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/linux_launchers/run_continuous.sh (code=exited, status=0/SUCCESS)
```
[VERIFIED]. Last natural unattended run 04:00 → 11:31 on 2026-08-31, exit 0.

It runs from `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` — **the
main checkout, not the served release.** A different root, which matters given
that every store path in this system is root-relative.

```
$ cat linux_launchers/run_continuous.sh          # 20 lines
  … python scripts/system_preflight_check.py …
  … python scripts/continuous_runner.py --project-root .
```
[CODE].

```
$ grep -ciE 'cio|wake|instrument.?record|subject_key' scripts/continuous_runner.py
0                                                        (966 lines)
```
[CODE]. The coordinator reports the same zero across the fan-out —
`trade_ai_orchestrator.py` (1254 lines), `morning_digest.py` (303),
`system_preflight_check.py` (214), `strategy_signal_sync.py` — which I did not
re-run; that part is [DOC-CLAIM] from the coordinator.

Strongest evidence, from the lane's own last natural run:
```
$ grep -ciE "cio|wake_dispatch|instrument_record" logs/run_continuous-20260831-040000.log
0                                        (149725 bytes, 04:00 → 11:31)
```
[VERIFIED]. Its tagged output is the finviz/scalp scanner lane.

**Structural blind spot, recorded rather than glossed:** the drop-in
`/etc/systemd/system/tradeai-continuous.service.d/singleton.conf` is **not
readable** by this account (`Failed to chase … Permission denied`). Its effect —
the `flock -n -E 0` singleton wrapper — is inferred from the *resolved* ExecStart
above, not read from the file. If that drop-in also injected environment or a
second `ExecStart`, this analysis would miss it. **UNKNOWN**, and not routed
around.

> **Affirmative statement, so no reader has to assume it:** the CIO wake path has
> exactly **one** scheduled driver — crontab line 934, `*/5`, running
> `cio_wake_dispatch_entrypoint.py` from the served release. systemd runs
> neighbouring CIO lanes but not the dispatcher, and `tradeai-continuous.timer` is
> a different lane on a different root, ruled out by source and by its own
> natural-run log. **The wake is cron-driven only.**

### Proof the `*/5` fire is genuinely unattended

Process ancestry captured passively at the moment of a natural fire. The capture
loop polled `/proc` and started nothing:

```
captured_at=2026-08-31T23:15:01 EDT
leaf_pid=2103058 (comm=python)
2103058 2103041 johnclaw Mon Aug 31 23:15:00 2026 python
2103041 2103013 johnclaw Mon Aug 31 23:15:00 2026 bash
2103013    6472 root     Mon Aug 31 23:15:00 2026 cron
   6472       1 root     Fri Aug 21 12:51:33 2026 cron
      1       0 root     systemd
```
[VERIFIED]. `python ← bash ← cron ← cron(pid 6472, up since Aug 21) ← systemd`.
No terminal, no session, no agent in the chain. **This is verification-ladder
rung 1 for the *mechanism*: the entrypoint is executed unattended by cron on its
own schedule.** It is not rung 1 for the M5 *claim* — that additionally needs the
right counters, which is §4's job.

---

## 3. Where the record load happens relative to `decide()` — [CODE]

Source read at pin `d276657b7`, re-read before citing. This describes what the
code *says*; it is not evidence that it ran.

`scripts/cio_wake_dispatch_entrypoint.py:132-133` — dispatch is the only step that
touches wakes:
```
132:        dispatcher = CIOWakeDispatcher(wake_store=wake_store, run_store=run_store)
133:        result = dispatcher.poll_and_dispatch(max_dispatches=5)
```

The consult lives inside `poll_and_dispatch`. In
`scripts/lib/cio_wake_dispatcher.py`:

- `:158-168` — the record store is opened and all known subject keys read **once
  per cycle**, before the per-wake loop:
  ```
  159:        # M5: the record is consulted BEFORE anything is claimed or run. Loaded
  160:        # once per cycle so the per-wake consult is a dict lookup, not I/O.
  164:            from scripts.lib.cio_wake_subject import decide as _subject_decide
  166:            from scripts.lib.cio_instrument_record import InstrumentRecordStore
  167:            _rec_store = InstrumentRecordStore()
  ```
- `:169-173` — if the store is unavailable the cycle still runs and says so
  (`log.warning("record consult unavailable, wakes proceed unfiltered: %s", exc)`)
  rather than silently dropping the check. This branch is **fail-open**: a
  `record_found=0` line can also mean "memory was unreachable". §4 covers what the
  log line can and cannot distinguish.
- `:192-202` — the consult, and the skip, both happen **before** the claim:
  ```
  192:            # M5: load the record before acting. A disposition the operator
  193:            # recorded days ago must change what happens next. This runs before
  194:            # the claim, so a deferred subject costs no lease and creates no run.
  195:            if _subject_decide is not None:
  197:                    _d = _subject_decide(wake, store=_rec_store, known_keys=_known_keys)
  199:                    if _d["verdict"] == _SKIP_CADENCE:
  200:                        log.info("wake %s skipped by record: %s", wake_job_id, _d["reason"])
  202:                        continue
  ```
- `:240-246` — the claim, reached only by wakes that survived line 202.
- `:369` — the per-cycle summary the log line is built from:
  `"record_consult": _summarise_subject(subject_decisions),`

The load itself is `scripts/lib/cio_wake_subject.py:168`:
```
168:        rec = store.load(key)                      # <-- load-by-subject
```
reached only after `:157` resolves a subject key, returning `SKIP_CADENCE` at
`:184-190` when `next_eligible_at` is still in the future.

**Plainly: yes, the load precedes the decision, and precedes the claim and the
run.** Ordering is unambiguous — consult at `dispatcher.py:195-202`, claim at
`:240`, `CIORunWorker.execute` at `entrypoint.py:222`. A wake deferred by its
record never gets a lease and never mints a run. [CODE] — this proves the
ordering, not that any of it executed.

One caveat on the module's own framing.
`scripts/lib/cio_wake_subject.py:12-13` carries a measurement in its docstring:

> ```
>       wakes in the store                          1,513
>       wakes carrying a subject_key                    0
> ```

A [DOC-CLAIM] dated 2026-08-30, embedded in source. §5 shows it is no longer the
operative situation: 524 subject resolutions have since been counted. **The
finding wins over the docstring.**

---

## 4. Acceptance criterion — fixed before the verdict

Stated as a question with thresholds, not as an expected value.

> **Q(M5).** Does `logs/cio_wake_dispatcher.log` contain at least one
> `record_consult:` line for which **all** of the following hold?
>
> **(a) Unattended.** The emitting process was parented by `cron`, on the `*/5`
> schedule, with no session, terminal or agent in its ancestry. Threshold: the
> line's timestamp falls in the regular `*/5`-derived series with no off-cadence
> outlier, **and** ancestry was captured for at least one fire in that series.
>
> **(b) A real wake existed.** `wakes ≥ 1`. A `wakes=0` line makes every other
> counter trivially zero and is evidence of nothing.
>
> **(c) The record was actually loaded.** `record_found ≥ 1` — the counter that
> separates "called `store.load(subject_key)` and got a record back" from every
> other outcome. Nothing weaker substitutes: `subject_resolved ≥ 1` proves only
> that a key was derived; `wakes ≥ 1` proves only that the queue was non-empty.
>
> **(d) The record changed what happened.** `skipped_cadence_not_due ≥ 1` **or**
> `changed_by_record ≥ 1`, corroborated by a matching `wake … skipped by record:`
> or `record_changed_decision:` line naming the `subject_key` and the
> `next_eligible_at` honoured. (c) proves a read; (d) proves the read had
> consequences. M5 requires consequences.
>
> **(e) Nobody replayed it.** The honoured `next_eligible_at` was written to the
> record store at least **12 hours** before the fire that honoured it, and the
> store file was **not modified** between the write and the fire.
>
> If (a)–(e) hold for a natural fire, the answer is yes.

**On the 12-hour threshold in (e).** AGENTS.md §15 words M5 as "a disposition made
*days* earlier". 12h is weaker than a literal reading. I chose it and am flagging
the choice rather than burying it: the observed deferral horizon in this store is
24h, so a strict 24h threshold would be unsatisfiable by construction for the most
common deferral and would end up testing the *store's cadence policy* rather than
the *wake path's memory*. The coordinator may reasonably insist on 24h. Under a
strict 24h reading the best evidence in §5 misses by ~11 hours at the first
honouring fire (though it clears at the last). Both readings are carried into §8.

### Finding: what the telemetry can and cannot distinguish

The log line emits six counters
(`cio_wake_dispatch_entrypoint.py:148-154`):
```
record_consult: wakes=%s subject_resolved=%s record_found=%s
                changed_by_record=%s skipped_cadence_not_due=%s no_subject=%s
```

**It cannot distinguish "loaded the record" from "found no wakes to load a record
for" in the all-zeros case.** `wakes=0 subject_resolved=0 record_found=0 …` is
emitted identically whether:

1. the wake queue was empty; or
2. the queue held only already-dispatched/active wakes, filtered at
   `cio_wake_dispatcher.py:176-188` **before** the consult — those are `continue`d
   past it and never enter `subject_decisions`; or
3. the record store was unavailable and the cycle went fail-open
   (`:169-173`), leaving `subject_decisions` empty.

Case 3 is the dangerous one: **a total memory outage and a quiet queue produce
byte-identical log lines.** The durable artifact carries a seventh counter,
`no_record`, that the log line omits, but the artifact is overwritten every 5
minutes and lives in per-release `data/`, so it survives neither time nor a
promote.

**Partially mitigated by measurement, not by design.** Across all 335 lines the
totals are `subject_resolved=524` and `record_found=524` — *exactly equal* (§5).
So in 335 observed cycles, every resolved subject found a record: the `NO_RECORD`
branch (`cio_wake_subject.py:174-176`) has never fired, and the load-exception
branch (`:169-171`) has never fired. That materially narrows the ambiguity — but
it is an empirical accident of this dataset, not a property the telemetry
guarantees.

Recommended (proposed, not applied — no code edits in this lane): add `no_record`
and a `store_available=true|false` field to the log line. Until then
`record_found ≥ 1` is trustworthy as a **positive** signal and `record_found = 0`
is **not** trustworthy as a negative one.

### Second finding: the durable artifact hard-codes its own unattendedness

`cio_wake_dispatch_entrypoint.py:168-171`:
```
168:            "unattended": True,
170:            "entrypoint": "cron: */5 * * * * cio_wake_dispatch_entrypoint.py",
```
Both are literals, written unconditionally. A hand-run
`python scripts/cio_wake_dispatch_entrypoint.py` writes `"unattended": true` and
the cron string into `data/cio/wake_record_consult.json` exactly as a cron fire
does. **The artifact's claim to be unattended is worth nothing as evidence** — it
is a comment, not a measurement. Anyone citing that file as M5 proof is citing a
literal. The ancestry capture in §2 is the real evidence, and it is external to
the program. Flagged because this is precisely the shape of the trap this lane was
warned about.

---

## 5. Full historical scan of `record_consult`

Root: `/home/johnclaw/trade-ai-releases/persistent-state/logs/cio_wake_dispatcher.log`
(via `CURRENT/logs`), read 2026-08-31T23:13 EDT.

```
$ stat -c '%s' cio_wake_dispatcher.log     → 1442365 bytes
$ head -1 | cut -c1-19                     → 2026-08-27 18:56:06
$ tail -1 | cut -c1-19                     → 2026-08-31 23:13:05
$ grep -c 'record_consult:'                → 335
```
[VERIFIED]. The log opens 2026-08-27 18:56, but the **first `record_consult:` line
is 2026-08-30 19:21:42** — the telemetry has existed for 3 days 4 hours, not for
the log's full span.

### Distribution of the 335 lines

```
$ grep -o 'record_consult: wakes=.*' log | sort | uniq -c | sort -rn
    123 wakes=0 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=0
     56 wakes=3 subject_resolved=3 record_found=3 changed_by_record=3 skipped_cadence_not_due=3 no_subject=0
     26 wakes=5 subject_resolved=5 record_found=5 changed_by_record=5 skipped_cadence_not_due=5 no_subject=0
     16 wakes=1 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=1
     13 wakes=5 subject_resolved=1 record_found=1 changed_by_record=0 skipped_cadence_not_due=0 no_subject=4
     11 wakes=2 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=2
     … (remaining shapes each <11)
```
[VERIFIED]. Aggregates, all `as_of` 2026-08-31 23:13 EDT, root as above:

| Measurement | Value |
|---|---|
| `record_consult:` lines total | 335 |
| lines with `record_found ≥ 1` | **165** (49.3%) |
| lines with `skipped_cadence_not_due ≥ 1` | **117** (34.9%) |
| lines with `wakes = 0` (no evidence either way) | 123 (36.7%) |
| earliest `record_consult:` line | 2026-08-30 19:21:42 |
| latest `record_consult:` line | 2026-08-31 23:13:05 |
| earliest with `record_found ≥ 1` | 2026-08-30 19:36:49 |
| latest with `record_found ≥ 1` | 2026-08-31 22:28:08 |
| latest with `skipped_cadence_not_due ≥ 1` | **2026-08-31 10:57:32** |
| `P1_DRY` (dry-run marker) lines in log | **0** |

Counter totals summed across all 335 lines:
```
wakes=795  subject_resolved=524  record_found=524
changed_by_record=389  skipped_cadence_not_due=389  no_subject=271
```
[VERIFIED]. Two exact equalities are worth naming: `subject_resolved == record_found`
(524 = 524) and `changed_by_record == skipped_cadence_not_due` (389 = 389). The
first is discussed in §4. The second says every decision the record changed was a
cadence skip — the record has never changed an outcome in any other direction.

**Has any `record_consult` line ever shown `record_found > 0`? Yes — 165 of them,
totalling 524 record loads.** This directly contradicts the brief's premise and
AGENTS.md §13.4. See §8.

Zero `P1_DRY` lines means no `--dry-run` invocation has ever written to this log,
so the series is not contaminated by dry-run output.

### Representative lines, quoted verbatim

The strongest M5-shaped fire in the log — every clause visible at once:
```
2026-08-31 07:12:05,623 [tradeai.cio_wake_dispatch_entrypoint] record_consult: wakes=5 subject_resolved=5 record_found=5 changed_by_record=5 skipped_cadence_not_due=5 no_subject=0
```

The corroborating per-wake line, naming subject and honoured deferral:
```
2026-08-30 23:57:04,487 [tradeai.cio_wake_dispatcher] wake wake_ev_morgan_3cdd2e5a4562d094_2026083103 skipped by record: HELD:SCHD: the record defers research until 2026-08-31T14:58:17.884559+00:00 (11.0h away). The disposition was recorded earlier and nobody replayed it.
```

The decision-delta line, showing the record *changed* the outcome:
```
2026-08-31 10:52:37,115 [tradeai.cio_wake_dispatch_entrypoint] record_changed_decision: subject=HELD:SCHD without_record=proceed with_record=skip/cadence_not_due reason=HELD:SCHD: the record defers research until 2026-08-31T14:58:17.884559+00:00 (0.1h away). The disposition was recorded earlier and nobody replayed it.
```
`without_record=proceed with_record=skip/cadence_not_due` is the counterfactual
stated by the code itself: absent the record this wake would have been claimed and
run.

Tonight's contrasting shape — a fire with real wakes that produced no consult:
```
2026-08-31 23:18:09,250 [tradeai.cio_wake_dispatch_entrypoint] record_consult: wakes=3 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=3
```

### The deferral, traced to its origin — criterion (e)

`data/cio/cio_instrument_records.jsonl` at pin `d276657b7`: 131 physical lines,
**40 distinct `subject_key`s** under append-only last-wins semantics [VERIFIED].
The last `HELD:SCHD` record:
```
{"subject_key": "HELD:SCHD",
 "next_eligible_at": "2026-08-31T14:58:17.884559+00:00",
 "created_ts":      "2026-08-30T02:34:32.326336+00:00",
 "updated_ts":      "2026-08-30T14:58:17.884753+00:00",
 "next_research_question": "Prior research was refused (rejected). What INDEPENDENT evidence would settle this without restating it?"}
```
```
$ ls -la data/cio/cio_instrument_records.jsonl
-rw------- 1 johnclaw johnclaw 392062 Aug 30 10:58 cio_instrument_records.jsonl
```
[VERIFIED]. The timeline:

| Event | UTC | ET |
|---|---|---|
| Disposition written; store last modified | 2026-08-30T14:58:17Z | 2026-08-30 10:58 |
| First fire that honoured it | 2026-08-31T03:57:04Z | 2026-08-30 23:57 |
| Last fire that honoured it | 2026-08-31T14:57:32Z | 2026-08-31 10:57 |
| Deferral expires | 2026-08-31T14:58:17Z | 2026-08-31 10:58 |

**The record store was not written to once in the 24 hours between the disposition
and its expiry** — the file mtime and the record's `updated_ts` are the same
instant to the second. Across that window 117 unattended `*/5` fires honoured the
deferral; the honouring stopped 45 seconds before expiry and never resumed.
Elapsed from write to first honouring fire: **13.0 hours** — clears (e)'s 12h
threshold, misses a strict 24h reading (the last honouring fire clears 24h).

This is a closed causal loop a hand-run cannot fake: a disposition recorded once,
honoured 117 times by cron over 24 hours with nobody touching the store, ceasing
precisely when it expired.

---

## 6. Cross-check — other CIO logs under the served release

```
$ ls -la --time-style=long-iso CURRENT/logs/ | grep -iE 'cio|wake|instrument|record'
-rw-rw-r-- ...     834 2026-08-31 05:00 cio_detector.log
-rw-rw-r-- ...     417 2026-08-30 08:00 cio_detector_weekly.log
-rw-rw-r-- ...  402783 2026-08-31 23:14 cio_reactive_cycle.log
-rw-rw-r-- ... 1442365 2026-08-31 23:13 cio_wake_dispatcher.log
-rw-rw-r-- ...  105768 2026-08-31 23:00 hermes_cio_worker.log
-rw-rw-r-- ...     234 2026-08-29 03:29 sweep_schwab_instruments.log
```
[VERIFIED] 2026-08-31T23:15 EDT.

| Log | Last write | Status |
|---|---|---|
| `cio_wake_dispatcher.log` | 23:13 | **live** — the M5 log |
| `cio_reactive_cycle.log` | 23:14 | **live** — 2-min systemd lane, separate path |
| `hermes_cio_worker.log` | 23:00 | live |
| `cio_detector.log` | 05:00, 834 bytes | **stale — writes only tracebacks**, below |
| `cio_detector_weekly.log` | 2026-08-30 08:00 | stale (weekly cadence, plausible) |
| `sweep_schwab_instruments.log` | 2026-08-29 03:29 | stale |

There is **no** `logs/cio_decisions.log` in the served release; the crontab line
that would write it is commented out:
```
175:#0 7 * * 1-5 cd $PROJ && $PY scripts/cio_decision_engine.py --run >> logs/cio_decisions.log 2>&1  # DISABLED 2026-08-08
```
[VERIFIED].

### Incidental finding: a shell-quoting bug in the detector cron lines

`cio_detector.log` contains nothing but two identical tracebacks [VERIFIED]:
```
NameError: name 'wakes_created' is not defined
```
Root cause, from crontab lines 928–930 [VERIFIED]:
```
928:0 5 * * 1-5 cd .../CURRENT && python3 -c "from scripts.lib.cio_event_detector import run_cio_event_detector_once; r=run_cio_event_detector_once(); print(f'Wakes: {r.get("wakes_created",0)}')" >> logs/cio_detector.log 2>&1
```
The inner `"wakes_created"` sits inside the outer double-quoted `-c "…"`, so the
shell strips it and Python sees a bare identifier. Affects the daily (line 928,
05:00 M-F), weekly (929) and monthly (930) detector lines.

**Important scoping of this finding, corrected mid-investigation.** The traceback
is raised while evaluating the f-string, which happens **after**
`r = run_cio_event_detector_once()` has already returned. **The detector itself
runs and creates its wakes; only the count printout dies.** So this bug loses
telemetry, not wakes, and it is **not** a cause of tonight's wake volume. Line 928
will fire at 05:00 ET inside this watch window and will crash again in the same
harmless way. Not in this lane's declared file set and not fixed here; routed to
the coordinator.

Two further recurring non-fatal errors in `cio_wake_dispatcher.log`, unrelated to
the record consult but named for completeness [VERIFIED]:
`Health boundary check failed: 'CIOHealthBoundary' object has no attribute
'current_advisory_state'`, and `Action write failed for rec N: 'stream_id'`
(25 consecutive at 23:03:23).

---

## 7. Watch table

Sampler root: `…/scratchpad/watch/samples.txt` (detached, read-only, 30-min
cadence to 08:00 ET). Rows marked † are this pass's own direct log reads, finer
than the sampler's ticks. Crontab sha256 is `bd0bcb9…` on every row; unchanged
throughout.

| Tick (ET) | CURRENT pin | crontab sha | wakes / subj / rec_found / changed / skip_cad | Note |
|---|---|---|---|---|
| 23:03:06 † | d276657b7 | bd0bcb9 | 1 / 0 / 0 / 0 / 0 | `no_subject=1`; dispatched=1, run COMPLETED |
| 23:07:50 † | d276657b7 | bd0bcb9 | 0 / 0 / 0 / 0 / 0 | empty queue; no evidence either way |
| 23:09:58 | d276657b7 | bd0bcb9 | (no new bytes) | sampler tick 1; log unchanged since 23:07:59 |
| 23:12:58 † | d276657b7 | bd0bcb9 | 0 / 0 / 0 / 0 / 0 | empty queue |
| 23:15:00 † | d276657b7 | bd0bcb9 | (fire observed) | **ancestry captured: python ← bash ← cron ← systemd** |
| 23:18:09 † | d276657b7 | bd0bcb9 | **3** / 0 / 0 / 0 / 0 | three real wakes, all `no_subject`; consult ran |

Fires are regular. `entrypoint complete` timestamps, last twelve cycles:
```
22:18:32 22:23:09 22:28:31 22:33:33 22:38:09 22:43:12
22:48:21 22:53:02 22:58:20 23:03:24 23:07:59 23:13:05
```
[VERIFIED] — a clean 5-minute series with 2–3 minutes of in-cycle work (the
backlog policy walks ~1,500 wakes), no gaps, no off-cadence outlier. Nothing in
this series looks hand-started.

### Tonight in aggregate, 20:00 → 23:18 ET (40 fires)

[VERIFIED] from the same log. Of 40 fires: 5 produced `record_found ≥ 1`
(20:08, 20:13, 21:52, 22:02, 22:28); **0 produced `skipped_cadence_not_due ≥ 1`**;
the remainder split between `wakes=0` and `no_subject`-only. So subject resolution
*is* working tonight — it worked as recently as 22:28 — and wakes *are* arriving.
The missing ingredient is elsewhere; §8 names it.

### Which pin wrote the historical evidence

Release directory mtimes give the promote timeline [VERIFIED]:
```
2026-08-31 02:21  1d64cb59f-main-exact-phase2-20260831-022046
2026-08-31 09:09  77433ef54-…-090841
2026-08-31 09:34  d81ee8ae5-…-093342
2026-08-31 10:14  373a82078-…-101330
2026-08-31 11:50  efcc51365-…-114929
2026-08-31 14:29  4530f0123-…-142845
2026-08-31 20:27  9929a208e-…-202653
2026-08-31 21:25  edc0b6556-…-211353
2026-08-31 22:56  d276657b7-…-225546   ← current
```
Twelve promotes on 2026-08-31. Therefore:

- the `07:12:05` line (`5/5/5/5/5`) was written by pin **`1d64cb59f`**;
- the `2026-08-30 23:57:04` `HELD:SCHD` skip was written by a still-earlier pin,
  which I did not identify — **UNKNOWN**;
- **no** line with `record_found ≥ 1` has yet been written by pin `d276657b7`.

---

## 8. Verdict

> ### `NOT_OBSERVED`
> — at pin `d276657b7`, as of 2026-08-31T23:22 EDT, first pass.

Criterion (a) is met: fires are unattended and cron-parented, proven by ancestry
capture. (b) is met: real wakes arrived (23:03, 23:18). (c), (d) and (e) are not
met at this pin.

### Neither "want of input" nor "want of wiring" — a third thing

The brief offered two categories. Tonight's data fits neither, and the real reason
is sharper than both.

- **Not want of wiring.** The consult runs on every fire. §3 shows the call site;
  the 23:18:09 line reporting `no_subject=3` can only be emitted by the consult
  having executed and classified three wakes. AGENTS.md §13.4's "no scheduled wake
  consumes it… persistence is unwired" is **false as of tonight**.
- **Not want of input.** Wakes are arriving — 3 at 23:18, 3 at 22:58, 3 at 22:47.
  And subjects *are* resolving: five fires between 20:08 and 22:28 recorded
  `record_found ≥ 1`. The queue is not empty and the join is not broken. It is also
  not a holiday (§0) and not the detector bug (§6, which loses a printout, not
  wakes).
- **The actual reason: there is no live disposition left to honour.**

Computed from `data/cio/cio_instrument_records.jsonl` at pin `d276657b7`,
append-only last-wins, `as_of` 2026-09-01T03:20:26Z [VERIFIED]:

```
distinct subject_keys (last-wins):                                40
  with no next_eligible_at:                                       38
  with next_eligible_at IN THE FUTURE (would cause a skip):        0
  with next_eligible_at EXPIRED:                                   2
     HELD:SCHD    next_eligible_at=2026-08-31T14:58:17Z  updated=2026-08-30T14:58:17Z
     SLEEVE:CASH  next_eligible_at=2026-08-31T14:53:41Z  updated=2026-08-30T14:53:41Z
```

**Zero unexpired deferrals exist.** Both expired within five minutes of each other
this morning at 10:53 and 10:58 ET. Criterion (d) — `skipped_cadence_not_due ≥ 1`
or `changed_by_record ≥ 1` — is therefore **structurally unsatisfiable tonight,
at any wake volume**, because no record in the store defers anything. This
predicts, and exactly matches, the observation that the last
`skipped_cadence_not_due ≥ 1` line in the entire log is `2026-08-31 10:57:32` —
45 seconds before the last deferral expired.

Call it **`NOT_OBSERVED` for want of a live disposition.** It is a distinct
diagnosis with a distinct remedy: nothing about the timer, the wake queue or the
record loader needs fixing. What is absent is a *writer* — no process has written
to `cio_instrument_records.jsonl` since 2026-08-30 10:58 ET, over 36 hours ago,
so the deferral inventory can only decay. Identifying what is supposed to mint
deferrals, and why it stopped, is the follow-on question this watch surfaces. It
is outside this lane's declared file set and is not investigated here.

A consequence worth stating: **unless a deferral is written before 08:00 ET, no
remaining fire in this watch window can satisfy the criterion**, however many
wakes arrive. Later ticks can still satisfy (c) — a plain record load — and that
is what §9 tells the next pass to look for.

### The evidence that came close, and why it is not a candidate

A previous served release met **every clause**, repeatedly:
```
2026-08-31 07:12:05,623 [tradeai.cio_wake_dispatch_entrypoint] record_consult: wakes=5 subject_resolved=5 record_found=5 changed_by_record=5 skipped_cadence_not_due=5 no_subject=0
```
(a) in the regular `*/5` series ✔ · (b) `wakes=5` ✔ · (c) `record_found=5` ✔ ·
(d) `skipped_cadence_not_due=5`, corroborated by named `HELD:SCHD` skip lines ✔ ·
(e) disposition written 2026-08-30T14:58:17Z, store untouched for 24h ✔.

I am **not** returning `M5_CANDIDATE` on it, for one reason: that line was written
by pin `1d64cb59f`, not by the served release this document is stamped to. Rung 1
says *"observed from the served release"*. `1d64cb59f` was the served release at
07:12 this morning and the observation is honest **for that pin** — but promoting
it to a candidacy for `d276657b7` would be an unstamped measurement, in a
repository where CURRENT rotated twelve times in one day. I will not launder an
observation across a promote boundary.

If the coordinator wants that evidence to stand, it should be recorded as
**`M5_CANDIDATE @ pin 1d64cb59f, as_of 2026-08-31T07:12 ET`** — a separate,
correctly-stamped claim, which I would support.

### What would remain to be shown even for that candidate

1. A fire at pin `d276657b7` meeting (b)–(e). None yet, and per the analysis above
   none is possible tonight without a new deferral being written.
2. That `1d64cb59f` and `d276657b7` share the consult code path unchanged across
   the intervening eleven promotes. Not checked — **UNKNOWN**.
3. That `record_found ≥ 1` reflects a real read rather than the fail-open branch
   at `cio_wake_dispatcher.py:169-173` being skipped for an unrelated reason. The
   `subject_resolved == record_found` equality in §5 is strong circumstantial
   support; the telemetry cannot settle it (§4).
4. A mutation test: with `HELD:SCHD`'s `next_eligible_at` removed, does the same
   wake proceed? Absent that counterfactual the skip is correlational. The
   `record_changed_decision` line asserts `without_record=proceed`, but that is the
   program's own claim about a branch it did not take — rung 5, not rung 1.

---

## 9. What would falsify this verdict

- **Falsifies `NOT_OBSERVED`:** any fire before 08:00 ET at pin `d276657b7` (or its
  successor, correctly re-stamped) emitting `record_found ≥ 1` **together with**
  `skipped_cadence_not_due ≥ 1` or `changed_by_record ≥ 1`, in the regular `*/5`
  series. One such line flips this to `M5_CANDIDATE`.
- **Falsifies "want of a live disposition":** a write to
  `data/cio/cio_instrument_records.jsonl` during the window (watch its mtime — it
  has been frozen at 2026-08-30 10:58 for 36 hours), or a record source other than
  that file. **I did not read `InstrumentRecordStore`'s implementation**, so the
  assumption that this file is the store's only backing is [CODE]-untested — the
  single largest hole in §8's reasoning.
- **Falsifies "not want of wiring":** finding that the 23:18:09 `no_subject=3` line
  is emitted by a path that never calls `store.load()`. §3 says otherwise, but §3
  is [CODE].
- **Falsifies the historical evidence:** any sign that one of the 117
  `skipped_cadence_not_due` fires was hand-started — an off-cadence timestamp, a
  shell-history entry, a session transcript. I checked timestamp regularity and
  found none, and found zero `P1_DRY` lines; **I did not read shell history.**
- **Falsifies criterion (e):** evidence the store was written between
  2026-08-30T14:58:17Z and 2026-08-31T14:58:17Z by a process that preserved mtime.
- **Falsifies the pin attributions in §7:** directory mtime is a proxy for promote
  time, not a promote log. If promotes are recorded somewhere I did not find, that
  record supersedes the table. I looked in `persistent-state/` and found none.
- **Would strengthen, not falsify:** reading root's crontab (§2, UNKNOWN) and the
  unreadable `singleton.conf` drop-in (§2, UNKNOWN). A second `*/5` invocation in
  either would change the fire accounting.

---

## 10. Corrections

Things I got wrong during this investigation, kept rather than tidied away.

1. **I reported the crontab had no CIO wake line. It does — line 934.** My first
   dump was `crontab -l | tee file | head -60`; `head` exited at line 60 and the
   SIGPIPE truncated `tee` at 801 of 998 lines. The `sha256sum` I quoted alongside
   came from a *separate* `crontab -l`, so it matched the real crontab and gave the
   truncated file a false stamp of completeness. I caught it only because `ps`
   showed a running process whose command line was a cron entry I had just claimed
   did not exist. **A checksum taken from a different invocation than the artifact
   it labels is not a checksum of that artifact.** Every later measurement
   re-dumped without `head`.
2. **I initially concluded the wake was systemd-driven**, on the strength of
   `tradeai-cio-reactive.timer` (2-min, CIO-named, CIO-shaped). It runs
   `cio_reactive_cycle.py`, a different script on a different path. Correcting (1)
   corrected this. The lane is cron-only.
3. **My first ancestry capture matched its own shell.** `pgrep -f
   cio_wake_dispatch_entrypoint.py` matched the bash process running the pgrep,
   because the pattern appeared in my own command line, and I nearly recorded a
   `claude ← -bash ← tmux` ancestry as the fire's. Re-run filtering on
   `/proc/PID/comm == python*`, producing the clean cron chain in §2. **A process
   search that can match the searcher is not a process search.**
4. **I began the historical scan before writing down the acceptance criterion.**
   The criterion in §4 was written after I had seen the `5/5/5/5/5` shape. I did
   not weaken it — it is strictly stronger than the brief required, adding clauses
   (a) and (e) — but the reader should discount it accordingly, and clause (e)'s
   12h threshold in particular is a number I chose knowing the data would clear it.
   That is exactly the post-hoc fit the clause exists to prevent, so it is flagged
   in §4 and both readings are carried into §8.
5. **The brief stated the mechanism was dark** (AGENTS.md §13.4: "no scheduled wake
   consumes it… persistence is unwired"). 165 log lines and 524 record loads say
   otherwise. I spent the first part of this pass assuming the brief and looking
   for an absence. The finding wins; §13.4 is stale and should be amended per
   AGENTS.md §20.
6. **I assumed `CURRENT/data` and `CURRENT/logs` behaved alike.** They do not —
   `logs` is a symlink to shared `persistent-state`, `data` is per-release. Had I
   not checked, I would have attributed four days of log history to a pin nineteen
   minutes old. §1 and §7 exist because of this correction.
7. **The brief asserted 2026-09-01 was Labor Day; it is a Tuesday.** Corrected by
   the coordinator mid-pass and re-verified here (`date -d 2026-09-01 +%A` →
   `Tuesday`; Labor Day 2026 is Monday 2026-09-07). **What it would have caused me
   to conclude:** my draft opened by pre-declaring that holiday-suppressed
   instrument events were the expected cause of low wake volume, and §8 would have
   closed the loop by attributing `NOT_OBSERVED` to "want of input, holiday eve".
   That would have been a fully self-consistent, confidently-tagged, **wrong**
   answer — and, worse, an *exculpatory* one that would have closed the
   investigation exactly where the real finding was. Forced to keep looking, I
   found instead that wakes are arriving normally, subjects resolve, records load,
   and the actual blocker is that **zero unexpired deferrals remain in the store**
   (§8). A pre-registered excuse is more dangerous than no hypothesis at all,
   because it survives contact with the data by explaining it away. I had also
   marked the holiday claim `[VERIFIED]`-adjacent by placing it in the header
   without ever running `date` — a brief's factual assertion is a [DOC-CLAIM] and
   must be checked like any other.
8. **I first blamed the detector `NameError` for low wake volume.** Wrong, and it
   was in a draft of §6. The traceback is raised evaluating the f-string, *after*
   `run_cio_event_detector_once()` has returned — the detector runs and creates its
   wakes; only the count printout dies. The bug loses telemetry, not wakes.
   Corrected in §6. This was the second exculpatory story I had to discard before
   reaching §8's answer.
9. **I nearly reported "no wakes are arriving".** At 23:12 the last three fires
   read `wakes=1, 0, 0` and I was drafting "the queue is empty". The 23:18 fire
   read `wakes=3`, and the 20:00–23:18 aggregate shows wakes throughout. Three
   consecutive quiet cycles on a 5-minute timer is not a trend. **Measurements from
   a 15-minute window should not be stated as a state of the system.**

---

*Next pass appends later sampler ticks to §7 and re-runs §8 against them. Per §8,
no remaining fire in this window can satisfy criterion (d) unless a deferral is
written to `cio_instrument_records.jsonl` first — so the next pass should watch
that file's mtime as closely as it watches the log. The sampler continues to
08:00 ET; nothing in this lane restarts or modifies it.*

---

# 11. COORDINATOR WATCH CONTINUATION — 23:23 → 08:09 ET

**Author: coordinator, not Worker A.** A's analysis above ends at 23:23 ET. This section curates the
detached read-only sampler's remaining ticks and closes the watch its brief specified. A's verdict
is re-tested against the full window, not restated.

**Watch complete: 18 ticks, 2026-08-31T23:09:58 → 2026-09-01T07:39 ET, every 30 minutes.** The
sampler invoked no job; it read `systemctl list-timers`, the crontab, and only the dispatcher log
bytes new since the previous tick.

## 11.1 Constants across all 18 ticks `[VERIFIED]`

| quantity | value | moved? |
|---|---|---|
| `CURRENT` pin | `d276657b7-main-exact-phase2-20260831-225546` | **no** |
| crontab sha256 | `bd0bcb96eb1d4e00b5c8e136d0fa30857578aa7830dfe665e09b0dd7f09c287a` | **no** |
| CIO wake driver | crontab line 934, `*/5 * * * *` | **no** |
| matching systemd timers | `tradeai-continuous.timer` only | **no** |

The pin held for the entire window. Every measurement in this document is attributable to one
release — worth stating, because twelve promotes landed on 2026-08-31 and A had to discard its
strongest evidence for belonging to a different pin.

## 11.2 The full-window measurement `[VERIFIED]`, as_of 2026-09-01T08:09 ET

Read from `persistent-state/logs/cio_wake_dispatcher.log`, restricted to fires at or after the
22:55 promote:

```
$ awk '$0 >= "2026-08-31 22:55"' … | grep -c "record_consult:"                    → 111
$ … | grep "record_consult:" | grep -vc "record_found=0"                          →  11
$ … | grep "record_consult:" | grep -v "skipped_cadence_not_due=0" | wc -l        →   0
```

**111 natural unattended fires. 11 loaded at least one record. Zero honoured a disposition.**

The eleven, in full:

```
23:58:06  wakes=3 subject_resolved=3 record_found=3 changed_by_record=0 skipped=0 no_subject=0
01:28:07  wakes=5 subject_resolved=3 record_found=3 changed_by_record=0 skipped=0 no_subject=2
04:33:29  wakes=5 subject_resolved=1 record_found=1 changed_by_record=0 skipped=0 no_subject=4
04:38:11  wakes=5 subject_resolved=1 record_found=1 changed_by_record=0 skipped=0 no_subject=4
04:43:12  wakes=5 subject_resolved=1 record_found=1 changed_by_record=0 skipped=0 no_subject=4
04:48:19  wakes=3 subject_resolved=3 record_found=3 changed_by_record=0 skipped=0 no_subject=0
06:03:21  wakes=3 subject_resolved=3 record_found=3 changed_by_record=0 skipped=0 no_subject=0
06:18:11  wakes=4 subject_resolved=3 record_found=3 changed_by_record=0 skipped=0 no_subject=1
07:28:37  wakes=5 subject_resolved=2 record_found=2 changed_by_record=0 skipped=0 no_subject=3
07:33:38  wakes=1 subject_resolved=1 record_found=1 changed_by_record=0 skipped=0 no_subject=0
08:08:27  wakes=3 subject_resolved=3 record_found=3 changed_by_record=0 skipped=0 no_subject=0
```

`subject_resolved == record_found` on every line — 24 = 24 across the window. Consistent with A's
finding that `NO_RECORD` has never fired.

## 11.3 CORRECTION — a coordinator claim the full window refutes

At 23:39 the coordinator wrote, in the stitch log and to the operator, that *"the consult runs, on
an empty set, every time."* **The full window shows that is false.** It was true of the sample then
in hand — five consecutive fires with `no_subject=N` — and it was generalised from five fires to a
property of the mechanism.

**Across 111 fires the consult resolved subjects and loaded records on 11 of them.** The record
load is not hypothetical at this pin: it is observed, unattended, on schedule, eleven times, with
the command and output quoted. That is rung 1 evidence for the *load*.

This is the same error the wave documented in others — generalising from a sample taken at one
moment — and it is recorded here rather than quietly dropped, because the corrected reading
strengthens the system's position and the original weakened it unfairly.

## 11.4 M5 verdict: `NOT_OBSERVED` — CONFIRMED, and the reason is now proven rather than predicted

The verdict stands at pin `d276657b7`. Criterion (d) was never met: **zero fires in 111 recorded
`skipped_cadence_not_due ≥ 1` or `changed_by_record ≥ 1`.**

Stitch 3 predicted precisely this, structurally: the record store has no production writer, so no
new disposition could be created overnight for a later wake to honour, making (d) unsatisfiable at
any wake volume. **The night ran the experiment and the prediction held.**

`[VERIFIED]` the store did not move:

```
$ ls -l …/persistent-state/data/cio/cio_instrument_records.jsonl
Aug 30 10:58        # unchanged across the entire window; ~45.2h silent as of 08:09
```

The distinction that matters for the morning: **the loader works and is proven; the writer does not
exist.** M5 is not blocked on the wake, the timer, the queue, or the consult. Every one of those
was observed working. It is blocked on the absence of anything that writes a disposition.

## 11.5 The three scheduled events, all as predicted `[VERIFIED]`

| event | prediction | outcome |
|---|---|---|
| 04:00 `tradeai-continuous.timer` | fires; does not touch the CIO record store | **Fired** — `Active: active (running) since Tue 2026-09-01 04:00:00 EDT`. Record store mtime still `Aug 30 10:58`. **The stitch-1 ruling holds.** |
| 05:00 crontab 928 detector | `NameError` again; wakes created, telemetry lost | **Confirmed** — `NameError: name 'wakes_created' is not defined`; count **2 → 3** |
| 06:52 crontab 997 `--apply` | acts on the plans B itemised | **Ran** — `plan_… S3_REENTRY_CANDIDATE ['DIVI'] / ['KTOS'] / ['ARKQ']`, matching B's census |

None was interfered with. All three were observed, not caused.

## 11.6 What this continuation could not see

The sampler captured only log bytes matching its filter, so a wake failing before it reached the
`record_consult` line would be invisible here. The `no_record` counter A identified as missing is
still missing, so a memory outage and a quiet queue remain indistinguishable in the line format —
mitigated only empirically by `subject_resolved == record_found`. And per Worker C, this
continuation read `persistent-state/logs` only; the `logs/` directories of the other 301 release
trees were not swept, and a lane writing into one of those would not appear.

**Watch closed 08:09 ET.** The sampler completed its 18th and final tick at 07:39 and exited on its
own stop condition.
