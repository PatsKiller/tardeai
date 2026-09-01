Status:      ACTIVE
as_of:       2026-09-01T14:15:00-04:00
Measured at: CURRENT BUILD_SHA 0a591048b827d57cebd5e61f39af77bde8c58274
             dir 0a591048b-main-exact-phase2-20260901-130000, promoted 13:01:33 ET
Canonical repo path: docs/ops/CIO_M5_FIRST_FIRE_2026-09-01.md
Authority:   dated observation of one unattended wake cycle; NOT an M5 OBSERVED claim
See also:    docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md · AGENTS.md §8 §15

# M5 — first fire

## VERDICT: `M5_CANDIDATE`

**Not `OBSERVED`.** One clause of §15 is unmet and is stated below. Nothing in this document
came from a command that invoked the wake path — the entrypoint was not run by hand.

## The fire

`[VERIFIED]` unattended `*/5` cron, 34 minutes after the #826 promote. Quoted verbatim from
`persistent-state/logs/cio_wake_dispatcher.log`:

```
13:35:11,547  research_gate      subject=EXIT:WLDS decision=flash
                                 reason=free_sources_exhausted_first_pass
                                 decide_called=True record_loaded=True
13:35:17,610  cognition_persist  subject=EXIT:WLDS persisted=True reason=persisted
                                 changed=next_eligible_at
13:35:17,613  research_gate      subject=EXIT:WLDS decision=skip reason=cadence_not_due
                                 decide_called=True record_loaded=True
13:35:23,326  cognition_persist  subject=EXIT:WLDS persisted=False reason=cognition_noop changed=
13:35:23,328  research_gate      subject=EXIT:WLDS decision=skip reason=cadence_not_due
                                 decide_called=True record_loaded=True
13:35:28,902  cognition_persist  subject=EXIT:WLDS persisted=False reason=cognition_noop changed=
13:35:28,902  entrypoint complete: runs=4 research=3 persisted=1
```

**The loop closes inside one cycle.** Wake 1 loaded the record, the gate decided `flash`, and the
write-back moved `next_eligible_at`. Wakes 2 and 3 loaded the same record, saw that disposition,
and **skipped on `cadence_not_due`** — behaviour changed by a write nobody replayed.

`cognition_noop` fired correctly on wakes 2 and 3: a write moving nothing is a failed persist, not
a silent success. The rail behaved as §13.4 specifies.

## The store was written — for the first time since the migration

```
$ wc -l persistent-state/data/cio/cio_instrument_records.jsonl
132        (was 131; mtime Sep 1 13:35)

writer histogram
   127  migration:deterministic
     5  cognition:defer_honored

rows written today: 1
   EXIT:WLDS  updated_ts=2026-09-01T17:35:17.610434+00:00
              next_eligible_at=2026-09-04T17:35:11.542672+00:00
```

**This is the finding that matters beyond M5.** The overnight wave established that the
InstrumentRecord store had no production writer: 126 of 131 rows written by
`cio_migrate_instrument_records.py` inside one twelve-hour window on 2026-08-30, and nothing
scheduled reaching `upsert()`. That is no longer true. A scheduled wake wrote a durable
disposition, and the store grew for the first time in 46 hours.

## Why this is a CANDIDATE and not OBSERVED

§15 M5: *"A scheduled wake loads the record before acting, and **a disposition made days earlier**
is still honoured with nobody replaying it."*

**The honoured disposition was six seconds old**, written by wake 1 of the same cycle and honoured
by wakes 2 and 3. Every mechanical clause is satisfied — scheduled, unattended, record loaded
before acting, disposition honoured, nobody replaying it — **except the durability one.**

The durable test is already staged and needs no intervention: `next_eligible_at` is
**2026-09-04T17:35:11Z**, a three-day deferral. If wakes between now and then keep returning
`cadence_not_due` for `EXIT:WLDS`, that is a disposition made days earlier being honoured, and it
converts this candidate into an observation. **That evidence must come from the log, unattended.**

## Two defects in the evidence itself

1. **The durable artifact is last-cycle-only.** `data/cio/wake_research_persist.json` reads
   `as_of 2026-09-01T18:05:09+00:00` with `research_called: 0, persisted: 0` — the 14:05 cycle,
   which found no subject. **The 13:35 artifact was overwritten.** The only surviving record of the
   fire is the log. An artifact that keeps just the most recent cycle cannot hold the cycle that
   mattered; the proof survived by luck.
2. **The writer stamp is wrong.** The row written at 13:35 carries
   `cc_narrative.writer = migration:deterministic`, but no migration wrote it — the live wake path
   did. The stamp is inherited from the prior version rather than set by the actual writer, so the
   store now attributes a production write to a migration. §9.2 requires `writer` to name the
   author. Reported, not fixed.

## Scope

Read-only. The wake entrypoint was **not** invoked. No `.env`, holdings, Moomoo, Telegram, or
`outcome --apply` was touched. No PR opened.
