Status:      ACTIVE
as_of:       2026-09-01T12:35:43-04:00
Measured at: origin/main 4554958cc · $PROJ dcb7ec42e→4554958cc · CURRENT a5fc7b378 (BUILD_SHA, by file content)
Canonical repo path: docs/ops/CIO_WAKE_LIVE_DECIDE_2026-09-01.md
Authority:   record for PR B of the banner/wake session; not a behaviour spec
See also:    docs/ops/CIO_BANNER_DATA_ASOF_2026-09-01.md
             AGENTS.md §13.4 "Dark contracts — do not report these as LIVE"

# The scheduled wake now calls `decide_after_load` and writes cognition back

## What #823 said, and what was actually true

#823 reported that live callers of the #810 function were **dry-run only**. Measured:

```
crontab:949   */5 * * * *  cd …/CURRENT && …/.venv/bin/python \
                           scripts/cio_wake_dispatch_entrypoint.py
                           ← NO --dry-run flag
```

**The timer already runs live.** The defect is one level in: `decide_after_load` was called
only inside `dry_run_record_consult()`, which `main()` reaches *only* when `--dry-run` is
passed. So the function was unreachable from the scheduled path — the same outcome #823
described, by a different mechanism. Wiring "remove --dry-run from the cron" would have
changed nothing, because there was no flag to remove.

This is the dark contract AGENTS.md §13.4 names: *"`load-by-subject` — built, tested, **no
scheduled wake consumes it**."*

## Why the existing test could not see it

```python
def test_entrypoint_exposes_dry_run_flag():
    assert "decide_after_load" in src        # ← a dry-run-only call satisfies this
```

A substring search over a file cannot tell which **branch** a name sits in. The test passed
for the entire period the live path never called the function. Detector shape, §7.

It is replaced by an AST test that splits `main()` at the `--dry-run` early return and asks
what is *called* in the statements after it.

## The change

| file | change |
|---|---|
| `cio_wake_dispatcher.py` | dispatch records carry `subject_key` (already computed in the same loop; reset per wake so one wake's subject cannot attach to the next) |
| `cio_wake_dispatch_entrypoint.py` | live loop calls `decide_after_load` **before** the run, then `apply_cycle_and_persist` after it; durable `WakeResearchPersist@v1` artifact |

### Which persist, and why not the one the brief named

`persist_instrument_record` (`scripts/lib/instrument_record.py`) has **zero callers** —
confirmed, one definition and no call site anywhere including tests. #823 was right about
that.

**It is not the writer this wires.** It calls `InstrumentRecordStore.upsert` directly,
which means it routes *around* `apply_cognition` — and `apply_cognition` is what raises
`BehaviorWriteRefused`. Wiring it would have created a scheduled write path with no
behaviour rail on it. It also requires a `symbol` key and rebuilds the record through
`new_record`, which is a shape the wake path does not have.

The real writer is the existing pair:

```
cio_rehydrate.apply_after_cycle  →  apply_cognition  →  BehaviorWriteRefused (rail)
InstrumentRecordStore.upsert     →  the append-only store (no second store)
```

**No new store, no new type, no new id.** §13.4 items 1–4 all resolved to "extend what
exists": the record is `InstrumentRecord@v1`, the stage is WRITE BACK, the fields are the
four cognition fields.

`strict=False` is deliberate. A wake that moved nothing is **recorded** as
`cognition_noop` — still a failed persist, counted as one — rather than raised into a cron
loop where it would abort every remaining dispatch.

## Persist caller count

| | before (origin/main 4554958cc) | after |
|---|---|---|
| `apply_after_cycle` production callers | **0** | **1** — `scripts/cio_wake_dispatch_entrypoint.py` |
| `persist_instrument_record` callers | 0 | 0 (unchanged, deliberately — see above) |

`test_no_scheduled_apply_after_cycle_caller_is_honest` asserted `prod == []` and its own
docstring said: *"If a scheduled caller is wired later, this test should be replaced with an
assertion that names that path — not silently deleted."* It fired, naming this file, and was
replaced with exactly that. **The list stays closed at one**: two schedulers writing
cognition for the same subject is how a record ends up with two versions of what the desk
last decided.

## Dry run — the exact cron form

```
cwd  /tmp/wake-dryrun
     <venv>/python /home/johnclaw/wt-pr-b-wake-live/scripts/cio_wake_dispatch_entrypoint.py --dry-run
     P1_DRY no PENDING wakes
     exit=0
```

Run by absolute path from a foreign cwd, because cron invokes the script *by path* and
`sys.path[0]` is then `<root>/scripts` — `python -c` masks that failure entirely (§7).

**That zero is not evidence the loop works**, only that imports and root resolution do: an
empty cwd has no wake store. Positive control, in an isolated root:

```
store path              /tmp/wake-livepath-proof/data/cio/cio_instrument_records.jsonl
next_eligible_at BEFORE None

decide_after_load       decision=flash  reason=free_sources_exhausted_first_pass
                        decide_called=True  record_loaded=True
                        next_eligible_at=2026-09-04T16:32:40+00:00

apply_cycle_and_persist {"persisted": true, "reason": "persisted",
                         "changed": ["next_eligible_at"]}

re-read from disk       next_eligible_at AFTER 2026-09-04T16:32:40+00:00   moved: True
rail                    BehaviorWriteRefused: cognition may not carry ['size_usd']
```

Proven by a durable artifact re-read from disk, not by an exit code (§0.8).

`InstrumentRecordStore.DEFAULT_PATH` is **relative** (`data/cio/…`), so the store follows
the working directory — the same trap the crontab already flags for `CIOPlanStore`. That is
what makes this isolation real. The live store was byte-identical afterwards:

```
sha256 e619a8694715516a  →  e619a8694715516a      131 records  →  131
```

## Mutations

| mutation | result |
|---|---|
| live path stops calling `decide_after_load` (the pre-fix shape) | **red** |
| cognition write-back removed from the live loop | **red** |
| persist routes around `apply_cognition` (rail bypass) | **red ×2** |

Source restored byte-identical after each (`9961feab56f3`).

## M5 status

**M5 stays NOT_OBSERVED.** Everything above is a hand-run in an isolated root. The claim M5
requires is a *natural, unattended* fire of the `*/5` timer writing
`data/cio/wake_research_persist.json` in the served release. That has not happened yet and
is not claimed here. The artifact exists so that proof is available when it does — a lane
whose only evidence is a hand-run has not proven a schedule.

## Not done

No crontab change of any kind. No live Hermes call. No Telegram. No `outcome --apply`.
`BehaviorWriteRefused` untouched. PP3 cash derivation untouched.
