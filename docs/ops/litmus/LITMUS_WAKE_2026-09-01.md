Status:      ACTIVE
as_of:       2026-09-01T15:24:00-04:00
Measured at: CURRENT BUILD_SHA 18a3da0dc1598700d5005eda0cb80bccd4bc98c5 (file content)
             dir 18a3da0dc-main-exact-phase2-20260901-143119
             origin/main ac4b37cea · $PROJ 0a591048b (3 behind — reported, CURRENT measured)
Canonical repo path: docs/ops/litmus/LITMUS_WAKE_2026-09-01.md
Authority:   discovery only. M5_CANDIDATE only — not OBSERVED. Entrypoint was not run.
See also:    docs/ops/CIO_WAKE_LIVE_DECIDE_2026-09-01.md
             docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md
             docs/ops/CIO_M5_FIRST_FIRE_2026-09-01.md (absent on CURRENT; present in worktree —
             live log re-verified against it)

# Litmus · E wake

Wake path on the served release: scheduled driver, `decide_after_load`, cognition persist,
and the durable artifact. **M5 stays `M5_CANDIDATE`.** The entrypoint was not invoked.

## Pre-flight

```
CURRENT      18a3da0dc1598700d5005eda0cb80bccd4bc98c5  [BUILD_SHA file content]
CURRENT_dir  18a3da0dc-main-exact-phase2-20260901-143119
origin/main  ac4b37cea
$PROJ        0a591048b   ≠ origin/main (behind 3) — measured CURRENT anyway
twin PR      none for LITMUS_WAKE
twin file    none at write time
```

`CIO_M5_FIRST_FIRE_2026-09-01.md` is **ABSENT** under CURRENT `docs/ops/`; it exists in
`tradeai-wt-final-operator-convergence`. Live log and store were re-measured; where they
agree with that doc, both are quoted.

## Findings

| surface | endpoint / path | field | writer | clock | as_of | verdict | one sentence |
|---|---|---|---|---|---|---|---|
| cron | crontab:949 | `cio_wake_dispatch_entrypoint.py` | cron `*/5` + flock/timeout | schedule | live line present | **LIVE** | Sole scheduled driver; no `--dry-run`; cwd is `CURRENT`. |
| code | `scripts/cio_wake_dispatch_entrypoint.py` | `decide_after_load` | live loop before `worker.execute` | n/a | pin `18a3da0dc` | **LIVE** | #810 gate sits on the scheduled path, not only behind `--dry-run`. |
| code | same | `apply_cycle_and_persist` | live loop after run | n/a | pin `18a3da0dc` | **LIVE** | Cognition write-back is wired; `BehaviorWriteRefused` path untouched. |
| artifact | `data/cio/wake_research_persist.json` | whole document | `_p.write_text(...)` each cycle | file `as_of` | **2026-09-01T19:19:57Z** | **SPLIT** | Schema claims durable proof; writer **overwrites** every fire, so the cycle that mattered is gone. |
| artifact | same | `research_called` / `persisted` | last cycle only | last write | 0 / 0 | **EMPTY** | Latest body is two `no_subject` goal wakes — not the 13:35 persist. |
| artifact | `data/cio/wake_record_consult.json` | consult counters | same overwrite shape | `as_of` | **2026-09-01T19:19:24Z** | **EMPTY** | `subject_resolved=0` `no_subject=2` — consult runs on an empty set this cycle. |
| log | `logs/cio_wake_dispatcher.log` | `research_gate` / `cognition_persist` | entrypoint logger | line ts | **2026-09-01 13:35 ET** | **LIVE** | Only surviving evidence of the first persist fire (log is shared via `CURRENT/logs` symlink). |
| store | `cio_instrument_records.jsonl` | `EXIT:WLDS.next_eligible_at` | `apply_after_cycle` → upsert | `updated_ts` | **2026-09-01T17:35:17Z** | **LIVE** | Disposition still on disk: defer until **2026-09-04T17:35:11Z**. |
| store | same row | `cc_narrative.writer` | inherited stamp | n/a | `migration:deterministic` | **STALE** | Production wake wrote the row; stamp still names the migration. |
| maturity | AGENTS.md §15 M5 | proof | n/a | n/a | this pin | **M5_CANDIDATE** | Same-cycle honor observed; days-earlier honor not yet in the log. |

## Overwrite of `wake_research_persist.json`?

**Yes. By design in the served code, every successful entrypoint completion replaces the file.**

```python
# scripts/cio_wake_dispatch_entrypoint.py:351-368  [CODE, CURRENT]
_p = _PROJECT / "data" / "cio" / "wake_research_persist.json"
_p.write_text(_json.dumps({
    "schema": "WakeResearchPersist@v1",
    ...
    "as_of": _dt.now(_tz.utc).replace(microsecond=0).isoformat(),
    "research_called": len(research_rows),
    "persisted": sum(1 for r in persist_rows if r.get("persisted")),
    "research": research_rows,
    "persist": persist_rows,
}, indent=2, default=str) + "\n", encoding="utf-8")
```

`write_text` is a full replace, not append. There is one inode:

```
CURRENT/data/cio -> persistent-state/data/cio   (symlink)
inode 3491901  wake_research_persist.json
birth  2026-09-01 13:08:56 ET   (first cycle that emitted the new complete line shape)
mtime  2026-09-01 15:19:57 ET   (latest */5 fire)
```

**Live body now** (quotes the losing cycle, not the one that persisted):

```
schema           WakeResearchPersist@v1
as_of            2026-09-01T19:19:57+00:00
unattended       true
entrypoint       cron: */5 * * * * cio_wake_dispatch_entrypoint.py
dispatched       2
research_called  0
persisted        0
persist[]        two rows, subject_key=null, reason=no_subject
                 wake_goal_goal_f2664540d8c1_2026090119
                 wake_goal_goal_695a5dbe2401_2026090119
```

`CIO_M5_FIRST_FIRE_2026-09-01.md` already named this: the 13:35 artifact was overwritten by a
later empty cycle; **only the log still holds the fire.** Re-verified: still true at 15:19.

The comment above the write says a scheduled run "must leave proof… not only a log line that
rotates." The implementation leaves **last-cycle-only** proof. A surface that overwrites the
cycle that closed the loop cannot be the sole carrier of M5 evidence.

## The 13:35 fire — still `M5_CANDIDATE`

Log, shared `persistent-state/logs/cio_wake_dispatcher.log`, pin ancestry: `0a591048b` is an
ancestor of CURRENT `18a3da0dc` (docs/promote commits only after the fire). Quoted verbatim:

```
13:35:11,547  research_gate      subject=EXIT:WLDS decision=flash
                                 reason=free_sources_exhausted_first_pass
                                 decide_called=True record_loaded=True
13:35:17,610  cognition_persist  subject=EXIT:WLDS persisted=True reason=persisted
                                 changed=next_eligible_at
13:35:17,613  research_gate      subject=EXIT:WLDS decision=skip reason=cadence_not_due
                                 decide_called=True record_loaded=True
13:35:23,326  cognition_persist  subject=EXIT:WLDS persisted=False reason=cognition_noop
13:35:23,328  research_gate      subject=EXIT:WLDS decision=skip reason=cadence_not_due
13:35:28,902  cognition_persist  subject=EXIT:WLDS persisted=False reason=cognition_noop
13:35:28,902  entrypoint complete: runs=4 research=3 persisted=1
```

Store re-read now:

```
rows                 132
EXIT:WLDS.updated_ts 2026-09-01T17:35:17.610434+00:00
EXIT:WLDS.next_eligible_at 2026-09-04T17:35:11.542672+00:00
cc_narrative.writer  migration:deterministic     ← wrong author stamp (FIRST_FIRE defect 2)
```

**Since 13:35:** exactly **one** `persisted=True` line in the whole log window (that fire).
**Zero** later `research_gate subject=EXIT:WLDS` lines — subsequent cycles are mostly
`no_subject` goal wakes, so they never load this record and cannot demonstrate
`cadence_not_due` days later.

### Why still CANDIDATE, not OBSERVED

AGENTS.md §15 M5 requires a disposition **made days earlier** still honoured with nobody
replaying it. Same-cycle honor (wakes 2–3 at 13:35, six seconds after the write) is real and
logged; it does **not** satisfy the durability clause. The staged clock is
`next_eligible_at=2026-09-04T17:35:11Z`. Conversion to OBSERVED needs unattended log lines
after that write, on this or a later served pin, showing `EXIT:WLDS` → `cadence_not_due`
without a hand run. **That has not happened yet. Not claimed.**

## Doc vs live

| claim | doc | live on CURRENT `18a3da0dc` |
|---|---|---|
| `decide_after_load` on scheduled path | WAKE_LIVE_DECIDE: wired | **LIVE** in source; cron has no `--dry-run` |
| M5 | FIRST_FIRE: `M5_CANDIDATE` | **still CANDIDATE** — disposition intact, no multi-day honor line yet |
| persist artifact | FIRST_FIRE: 13:35 overwritten | **confirmed** — body is 15:19 empty cycle |
| writer stamp | FIRST_FIRE: migration label on live write | **unchanged** — still `migration:deterministic` |
| FIRST_FIRE file on CURRENT | — | **ABSENT** under `CURRENT/docs/ops/` (worktree-only) |

## Pins

Entrypoint **not** run. No Telegram, no `outcome --apply`, no holdings write, no `.env`,
no `$PROJ` fast-forward, no promote, no crontab edit, no `AGENTS.md` edit, no `docs/INDEX.md`.
`BehaviorWriteRefused` untouched.
