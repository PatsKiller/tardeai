Status:      ACTIVE
as_of:       2026-09-01T13:05:00-04:00
Measured at: CURRENT 4554958cc (BUILD_SHA) · origin/main 4554958cc · $PROJ dcb7ec42e
Canonical repo path: docs/ops/CIO_WAKE_LIVE_DECIDE_2026-09-01.md
Authority:   dated record of wiring #810's contract onto the live wake path
See also:    docs/ops/CIO_OVERNIGHT_CLOSEOUT_2026-09-01.md · AGENTS.md §13.4 §15

# The scheduled wake now calls `decide_after_load`

## The defect, measured on CURRENT before the edit

```
scripts/cio_wake_dispatch_entrypoint.py:45  from …cio_research_preflight import decide_after_load
scripts/cio_wake_dispatch_entrypoint.py:62      research = decide_after_load(   ← inside
scripts/cio_wake_dispatch_entrypoint.py:36  def dry_run_record_consult(...)     ← this
scripts/cio_wake_dispatch_entrypoint.py:97      if args.dry_run:                ← reached only here
                                                    dry_run_record_consult()
                                                    return
```

The installed cron, quoted verbatim:

```
*/5 * * * * cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && \
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python \
  scripts/cio_wake_dispatch_entrypoint.py >> logs/cio_wake_dispatcher.log 2>&1
```

**No flag.** `args.dry_run` is False, the dry-run branch is skipped, and the live path below it
never calls `decide_after_load`. The only other reference is `cio_research_gate_report.py`, an
unscheduled report.

**Why the node looked wired.** A `record_consult:` line has fired every five minutes since
2026-08-30 — 337 of them, 524 record loads. That telemetry comes from
`cio_wake_subject.decide`, a *shallower* subject consult inside `poll_and_dispatch`. The deeper
load-then-decide that #810 shipped and tested was never reached. **The PR written to close the
filing-cabinet defect reproduced it**, and the evidence line was strong enough to hide that.

## The change

Wired into `CIOWakeDispatcher.poll_and_dispatch`, not bolted onto the entrypoint — §13.4 says
extend the stage that owns the behaviour, and that loop is where the subject is already resolved
and the record already loaded.

**Placed AFTER the cadence gate.** A record that says "not due" still costs nothing: the wake is
skipped before the preflight runs. A test asserts that ordering, because reversing it would make
every deferred subject pay for a research decision each cycle.

**`decide_after_load` is read-only** — a test asserts its source contains no `upsert(`,
`persist_instrument_record`, `write_text(` or `json.dump(`. Wiring it into the claim path
therefore adds **no store write**.

Failure is caught, named and logged (`research preflight failed for %s`), never bare — §7.

## Telemetry

The evidence line now shows whether the deeper call ran, instead of leaving the shallower consult
to imply it:

```
record_consult: wakes=… subject_resolved=… record_found=… changed_by_record=…
                skipped_cadence_not_due=… no_subject=…
                research_preflight=… research_decide=… research_loaded=… research_err=…
```

`research_errors` is counted separately so a failure can never read as a successful preflight.

## The persist requirement — NOT met, and why

The brief required that after cognition apply, `persist_instrument_record` be called.

**No cognition apply happens at this site.** `decide_after_load` loads a record and returns a
decision; it moves no cognition field. There is therefore no delta to persist, and calling a
writer here would persist nothing.

`[VERIFIED]` on CURRENT, `persist_instrument_record` still has **0 callers** — only its definition
at `scripts/lib/instrument_record.py:116`. Its body ends:

```python
    except Exception:
        return False
```

**Wiring that as-is would install a writer that fails silently** — the same fail-open shape removed
from the analyst cache earlier today (#814/#815). Naming it rather than calling it is the honest
outcome: the real writer for a cognition delta does not yet exist on this path, and inventing a
call site would produce a green line and no data.

**This is the remaining half of M5.** The loader is now genuinely wired end to end; the writer is
still absent.

## Validation

```
tests/test_cio_p1_load_by_subject.py                    7 passed   (#810 A/B still green)
wake_subject / wake_dispatch / research_preflight       20 passed
tests/test_live_wake_calls_decide_after_load.py         8 passed
coverage gate                                           5 passed
```

**Mutation-verified.** Deleting the live preflight block (lines 214–243, the exact pre-fix shape)
turns 3 of 8 red:

```
[FAIL] test_the_live_dispatch_path_calls_decide_after_load
[FAIL] test_preflight_runs_after_the_cadence_gate_not_before
[FAIL] test_preflight_failure_is_named_never_bare
3 failed, 5 passed        → restored: 8 passed
```

**The mutation also caught a weak test of mine.** The first version asserted `"_decide_after_load"
in src`, which the *import line* alone satisfies — it passed against the mutated, pre-fix shape.
It now requires an actual invocation (`_decide_after_load\s*\(`). A guard that reads correctly and
cannot fail is not a guard.

Cron form dry-run, from `/tmp`, absolute paths:

```
$ cd <worktree> && <venv>/python scripts/cio_wake_dispatch_entrypoint.py --dry-run
P1_DRY no PENDING wakes
exit=0
```

An honest empty: no wakes were queued at that moment.

## M5 status

**Still `NOT_OBSERVED`, and it must stay that way until a natural fire proves it.** This wiring is
`[CODE]` plus unit evidence. Rung 1 requires the `*/5` cron to run unattended, resolve a subject,
and show `research_preflight ≥ 1` in a log line nobody staged.

**Do not hand-run the entrypoint to produce that line.** §8: a proof staged by hand does not
satisfy a claim that something happens on schedule. The next natural timer is the candidate.
