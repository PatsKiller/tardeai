Status:      ACTIVE
as_of:       2026-09-01T13:08:48-04:00
Measured at: origin/main 0a591048b · $PROJ dcb7ec42e · CURRENT 0a591048b (BUILD_SHA, by file content)
Canonical repo path: docs/ops/CIO_BANNER_WAKE_CLOSEOUT_2026-09-01.md
Authority:   closeout for the banner/wake session; not a behaviour spec
See also:    docs/ops/CIO_BANNER_DATA_ASOF_2026-09-01.md (#825, by a peer)
             docs/ops/CIO_WAKE_LIVE_DECIDE_2026-09-01.md (#826)

# Banner + wake — closeout

**UNPUBLISHED.** This document is committed locally and **not pushed**. The session's push
budget was spent on #826 and the operator approved exactly one override for the corrective
push; this closeout does not consume another.

## Pre-flight

```
deploy worktree  a5fc7b378
origin/main      dcb7ec42e
$PROJ            dcb7ec42e   ==  origin/main  → PROCEED
CURRENT          a5fc7b378   by BUILD_SHA file content, PP3 markers present
```

`$PROJ` showed no lag, so no fast-forward was performed.

## Step 0 — the twins

```
#818  commented "Superseded by #822. Do not merge."  → CLOSED   mergeCommit null
#821  same                                          → CLOSED   mergeCommit null
```

Neither was rebased or merged. GitHub accepted both closes.

## PR A — **already landed by a peer as #825**

While PR A was being built, a peer merged the identical work as **#825** (`4554958cc`,
16:20:18Z) and promoted it at 12:51. **This session duplicated it.** The brief said "Do not
open #825"; the correct reading was to check what #825 *was* before starting, and that was
not done. No divergent copy was landed — the duplicate branch is committed locally and
unpushed.

Its acceptance was verified anyway, live, rather than assumed:

```
as_of              '2026-08-29'          the loader ran
data_as_of         '2026-08-03'          the money
data_as_of_account 'moomoo_taxable_live'

chip age = now - data_as_of = 29.5d (709h)   → STALE · data 29.5d · moomoo_taxable_live
bundle   index-Cxzecs0t.js → index-B2UNPQZo.js   (hash-named; stale bundle uncacheable)
dollars  portfolio_value 1278305.39 · total_cash 631013.62   unchanged
```

### Report-only: what #825 does not cover

Verified against `origin/main`, not asserted:

1. **The API emission is unpinned.** No test references `api_v2`/`overview` alongside
   `data_as_of`. Deleting `"data_as_of": h.get("data_as_of")` from `overview()` turns
   nothing red — and the field's absence is exactly the condition that made this a
   two-sided defect.
2. **The tile labels the wrong field.** `MetricStrip.tsx:185` renders the literal string
   `as_of` while `asOf` now holds `dataAsOf` (`surfaceFreshness.ts:238,247`). Value right,
   label wrong.
3. **The UNDATED branch renders the loader's date.** `asOf: overview.as_of` when the data
   clock is missing, so a block labelled `STALE · data UNDATED` still displays a date in a
   field a reader now believes is the money's clock.

None is a live-behaviour bug. Left as report-only per the "No PR C" instruction.

## PR B — #826, merged `0a591048b`, promoted

### #823 was right in effect and wrong in mechanism

The installed timer never passed `--dry-run`. There was no flag to remove.
`decide_after_load` sat inside `dry_run_record_consult()`, which `main()` reaches **only
when the flag is passed**. Same outcome, different cause — and a "remove the flag" fix
would have changed nothing.

`test_entrypoint_exposes_dry_run_flag` asserted `"decide_after_load" in src`, which a
dry-run-only call satisfies. **A substring search cannot tell which branch a name is in**,
so it passed for the entire period the live path never called the function.

### The persist deliberately is not the one the brief named

`persist_instrument_record` has zero callers, as #823 said. It calls
`InstrumentRecordStore.upsert` **directly**, routing around `apply_cognition` — the
function that raises `BehaviorWriteRefused`. Wiring it would have created a scheduled
write path with no behaviour rail on it. The existing pair was used instead:

```
apply_after_cycle → apply_cognition → BehaviorWriteRefused (rail)
                  → InstrumentRecordStore.upsert (no second store)
```

`apply_after_cycle` production callers: **0 → 1**. `persist_instrument_record`: 0 → 0.

## Deploy

```
prepare  diff_count 0 · extra_count 0 · firing []   source_commit 0a591048b
promote  PASS  health ok + /v3/cio=200
CURRENT  0a591048b-main-exact-phase2-20260901-130000   (BUILD_SHA file)
serving  pid 3226725 cwd → the new release
```

Verified by file content: `apply_cycle_and_persist` 2 · `decide_after_load` 5 ·
`WakeResearchPersist@v1` 1 · `subject_key` on dispatch 1 · PP3 `_cash_ts_from_rows` 2
(unregressed).

## M5 — OBSERVED at 13:35 (the three-stage account below)

A natural, unattended `*/5` fire at **13:08:56** ran the new code and wrote its artifact.
Proven by a signal only the new code can emit (the old build has no such line):

```
entrypoint complete: runs=0 research=0 persisted=0
WakeResearchPersist@v1  dispatched 0 · research_called 0 · persisted 0 · cognition_noop 0
```

The in-flight process was confirmed to be executing the promoted file before it finished:
`cwd → 0a591048b-…`, script sha `6de5f9c2e849413f`, identical to the served copy.

**OBSERVED:** the wired entrypoint runs under the real timer, unattended, and leaves a
durable artifact.

**NOT OBSERVED:** the research gate and the cognition persist. **Zero wakes were dispatched
in that cycle, so `persisted: 0` is the no-input case, not evidence the write works.** A
counter of completed work cannot distinguish work never started from work that failed on its
first instruction — the `attempts_24h` trap in AGENTS.md §7, and it applies to this change's
own evidence. Wakes do occur on this box (5 dispatched at 12:38, 4 at 12:44), so the path
is expected to exercise naturally; until a cycle with `dispatched > 0` writes
`research_called > 0`, **M5 remains NOT_OBSERVED** and the hand-run positive control in
`CIO_WAKE_LIVE_DECIDE_2026-09-01.md` is the only proof the write path works.

### Second observation — a dispatching cycle, 13:19

```
dispatched 2 · research_called 0 · persisted 0
cognition_persist subject=None persisted=False reason=no_subject   (x2)
wake_goal_goal_f2664540d8c1_2026090117 / wake_goal_goal_695a5dbe2401_2026090117
```

The plumbing is now proven end-to-end under the real timer: the dispatcher carried
`subject_key` through to the entrypoint, `apply_cycle_and_persist` was invoked per wake, and
the outcome was recorded honestly rather than silently skipped.

`subject_key: null` is **correct here, and cross-checked from an independent code path**:
the pre-existing consult reports `subject_resolved: 0, no_subject: 2` for those same two
wakes. They are `wake_goal_goal_*` — goal wakes that resolve no subject — and the new code
declined to invent one, as its comment requires.

**Still not exercised: `decide_after_load` and the persist with a real subject.** Event
wakes do resolve subjects on this box (`subject_resolved: 3` at both 12:38 and 12:44), so
the path is expected to run naturally when an event wake next dispatches. Until a cycle
records `research_called > 0`, **M5 remains NOT_OBSERVED** and the hand-run positive control
is still the only proof the write path works.

### Third observation — M5 CLOSED, 13:35

A natural, unattended cycle dispatched four wakes, three of which resolved a real subject:

```
research_gate     EXIT:WLDS  flash / free_sources_exhausted_first_pass
                  decide_called=True  record_loaded=True
cognition_persist EXIT:WLDS  persisted=True  changed=["next_eligible_at"]
research_gate     EXIT:WLDS  skip / cadence_not_due     <- reads back what was just written

WakeResearchPersist@v1: dispatched 4 · research_called 3 · persisted 1 · cognition_noop 2
```

Verified in the durable store, re-read from disk rather than inferred from the log:

```
cio_instrument_records.jsonl   131 -> 132 rows (append-only)
EXIT:WLDS   next_eligible_at   None -> 2026-09-04T17:35:11
behaviour fields on the record  NONE  -- the rail held
```

**The loop closed.** Wake 1 ran the gate and wrote `next_eligible_at`; wakes 2 and 3 for the
same subject then read that value back and were cadence-skipped **because of it**. A record
that changes the next decision is the whole point of M5 — `cio_rehydrate`'s own docstring:
*"a record nothing reads is just a slower log."* This is that, unattended, in production.

**On the two `cognition_noop`s:** both followed a `cadence_not_due` skip, so nothing *should*
have moved and the noop is the correct outcome, not a defect. §13.4 calls a noop a failed
persist, and that framing is aimed at a wake which actually researched and still moved
nothing. **A refinement worth having: the artifact does not yet distinguish "noop after a
cadence skip" from "noop after real research".** Only the second is a finding. Named, not
built.

**Concurrency, concretely.** Three wakes for one `subject_key` landed in a single cycle and
were handled sequentially, which is safe. Across two *overlapping* cycles the same three
would interleave against a last-writer-wins projection — the exact loss this session's
`flock` now prevents. The risk was not hypothetical.

## Mistakes made in this session

1. **Duplicated PR A** rather than checking what #825 was.
2. **CRLF churn.** Line endings were verified on PR A's files and the check was not repeated
   on PR B's; `write_text()` converted two fully-CRLF files to LF. Cost the CI cycle that
   exhausted the push budget.
3. **An invalid mutation scored as SURVIVED.** An 8-space anchor is a substring of the
   12-space `pricing` line, so `replace(…, 1)` hit the wrong site. Re-anchored it goes red.
   The misfire did expose a real gap (a presence-only assertion), which was then fixed.
4. **A watcher keyed on the wrong signal.** "The consult artifact's mtime advanced" cannot
   distinguish old code from new. It fired on the 13:00 run — which started **before** the
   13:01:55 promote and therefore ran the old code. Re-armed on signals only the new code
   can emit. Detector shape, again, in the act of proving detector shape.

## Report only — not fixed

- **`portfolio_live_monitor`**: log 0 bytes, mtime 2026-09-01 10:00:01. Its own declared
  `output_signal`, `price_cache.json`, is **40.3h** old against a declared
  `expected_cadence_hours: 24` — so this lane should already evaluate stale, and that
  verdict still reaches no operator surface. Lane row declares 24h against a `*/20 9-16`
  cron. Left alone, by instruction.
- **The wake cron overlapped itself — FIXED, operator-authorized.** See the section below.
- **`ai_local_acceptance.sh` does not run `run_cio_hardening_ci.py`.** A PR that adds a
  document passes every local gate and fails CI on `docs_index_drift`. That is what
  happened here.
- **The evidence generators strip §14 headers.** Running local acceptance rewrote
  `CI_EVIDENCE_LATEST.md`, `RELEASE_MANIFEST_LATEST.md` and `OPTIONS_RISK_BLOCK_MATRIX.md`
  **removing** their `Status:/as_of:/Measured at:` headers. Those rewrites were discarded
  rather than committed, twice.
- **`$PROJ` now lags `origin/main` by two commits** (#825, #826). Not fast-forwarded, per
  the pin. Harmless for these two changes specifically: the wake cron runs `cd CURRENT`, and
  `api_v2`/the SPA are served from `CURRENT`. Nothing in either PR is executed from `$PROJ`.

## Crontab line 949 — `flock` added (operator-authorized)

Proposed as operator-only under §17; the operator then instructed "add flock to line 949",
which is the authorization §17 requires. Applied.

**Why it mattered now.** Runs take 4–6 minutes against a `*/5` schedule and two dispatchers
were observed running concurrently at 13:05. The lease prevents the same wake dispatching
twice, and `upsert` writes one whole line per append so nothing can tear. But #826 puts a
**cognition write** on that path, and two overlapping cycles touching one `subject_key`
could lose an update through load → append → last-writer-wins projection.

```
- */5 … && PY scripts/cio_wake_dispatch_entrypoint.py >> logs/… 2>&1  # …
+ */5 … && flock -n -E 99 /tmp/cio_wake_dispatch.lock PY scripts/… >> logs/… 2>&1; rc=$?; \
+   [ $rc -eq 99 ] && echo "$(date …) [flock] wake dispatch skipped - previous cycle still running" >> …
```

**`-E 99` and the skip line are deliberate, not scope creep.** A bare `flock -n` exits 1 and
writes nothing, so a skipped cycle would be indistinguishable from a cycle that never fired —
a new blind spot on the very lane that just gained a write. AGENTS.md §9.1: silence must
never be indistinguishable from a dead system. This is the pattern crontab line 928 already
uses, reused rather than reinvented.

**`timeout` added in a second pass**, on operator instruction. See the section below.

### Proof the control engages

Mechanism, three states, before touching the crontab:

```
lock free    → rc=0   command ran
lock held    → rc=99  command did NOT run
lock freed   → rc=0   command ran again
```

Then the exact installed command form (with cron's `\%` un-escaped as cron does), scratch
lock and log:

```
overlap → inner rc=99
log     → 2026-09-01 13:32:58 [flock] wake dispatch skipped - previous cycle still running
```

### Change safety

```
backup    /home/johnclaw/backups-crontab/crontab.20260901-133122.bak   sha a3071398ae744cbd
diff      exactly 1 line removed, 1 added; 1013 lines before and after
readback  byte-identical to the candidate (sha 9e0525727567cbe3)
```

Anchored on unique line CONTENT and then asserted to be at line 949, rather than trusting a
line number. `~/backups` was not touched; the backup went to a new sibling directory.
`MAILTO` is unset and nothing parses this log for exit status, so the trailing test's
non-zero exit on a healthy run is inert — and matches line 928.

## Crontab line 949 — `timeout` added (operator-authorized, second pass)

Final installed form:

```
*/5 * * * * cd …/CURRENT && flock -n -E 99 -o /tmp/cio_wake_dispatch.lock \
  timeout -k 60s 15m PY scripts/cio_wake_dispatch_entrypoint.py >> logs/… 2>&1; rc=$?; \
  [ $rc -eq 99 ] && echo "… [flock] skipped …" >> logs/…; \
  { [ $rc -eq 124 ] || [ $rc -eq 137 ]; } && echo "… [timeout] KILLED after 15m (rc=$rc) …" >> logs/…
```

### Why 15 minutes

Measured, not guessed, over 1377 logged completions:

```
median 107s · p90 204s · p99 262s · longest directly observed 5m28s
```

**The historical metric is right-censored at 300s** — it measures completion-since-the-nearest
`*/5` boundary, so any run over 5 minutes wraps and is under-reported. 299s is therefore not
the max, and 42 of 1377 runs completed >4min after a boundary. 15m is ~3.4x p99 and ~2.7x the
longest run actually seen, and still releases a hung lock within three cycles. Line 928 uses
45m for a much heavier job.

### Two defects the positive control caught before install

Both would have shipped as controls whose name exceeds their code.

**1 · `-k` escalation exits 137, not 124.** The first draft logged only `rc -eq 124`, so the
*worst* case — a process ignoring SIGTERM and needing SIGKILL — would have been **silent**,
which is precisely what the log line exists to prevent. Both codes are now logged, and `rc` is
printed so the two are distinguishable.

**2 · `timeout` alone does NOT release the lock.** `timeout` kills only its direct child. A
surviving grandchild inherits the flock file descriptor and keeps the lock held:

```
without -o   hard hang killed → rc 137 → lock STILL HELD    (timeout defeated)
with    -o   hard hang killed → rc 137 → lock FREE          (orphan still alive)
```

This matters concretely: the entrypoint spawns subprocesses, so without `-o` a hung cycle
would have left the lock held forever — reintroducing the exact failure the timeout was added
to fix, while appearing to fix it. `flock -o` (`--close`) closes the descriptor before exec so
the command's children cannot hold it. Verified `-o` still excludes concurrent runs (rc 99,
command did not run) and still frees on normal exit.

Final dry run of the exact form, four states, scratch lock and log:

```
1 normal        rc 0    no incident line
2 overtime      rc 124  logged
3 hard hang     rc 137  logged
4 lock after 3  FREE, despite two surviving orphans
```

### Kill safety

`timeout` sends SIGTERM first, and `InstrumentRecordStore._load()` wraps `json.loads` in
`try/except: continue`, so a torn line would be **skipped rather than fatal**. The residual
cost of a kill is losing one appended record version, not a corrupt store. Named because it is
a real if bounded cost, not because it was observed.

### The install was rejected once, correctly

The first attempt carried the full rationale as a crontab comment and cron refused it:

```
"crontab.candidate2":949: command too long   (1706 chars; limit 1000, longest existing line 925)
errors in crontab file, can't install.
```

**The live crontab was unchanged — 0 lines differing — so the failure was fail-closed, not
partial.** Putting 1700 characters of reasoning in a crontab comment was the wrong call; the
reasoning belongs here. The comment now preserves the original 24/7 note verbatim and points
at this document. Space was reclaimed by using the relative `logs/cio_wake_dispatcher.log` in
the echo branches — verified to be the **same inode** as the absolute path (4131997), and
unreachable if `cd` fails since `rc` would then be 1 and no branch fires. Final line: 884
chars.

### Confirmed in production

Verified with a detector keyed on `comm=flock`, which structurally cannot match this
session's own shell — a text `ps | grep` had already produced one false positive by matching
its own command line.

```
13:50:05  in flight: flock -n -E 99 -o /tmp/cio_wake_dispatch.lock timeout -k 60s 15m
                     PY scripts/cio_wake_dispatch_entrypoint.py
          flock -o PRESENT · timeout PRESENT
13:53:58  entrypoint complete: runs=0 research=0 persisted=0
          incident lines: 0   (no overlap, no hang)
```

The lane runs and completes normally under both controls. No `[flock]` skip has fired yet
because no overlap has occurred since install — **absence of a skip is not evidence the lock
is dead**; the mechanism was positive-controlled directly, in all four states, before install.

### Change safety

```
backup    crontab.20260901-134051.pre-timeout.bak   sha 9e0525727567cbe3
diff      exactly 1 line removed, 1 added; 1013 lines before and after
bash -n   syntax OK on the command portion before install
readback  byte-identical to the candidate (ec50dc2ab3949e82)
```

Both backups retained: `crontab.20260901-133122.bak` is the original pre-flock state.

## Not done, by instruction

No `outcome --apply` · no AgentView/commitment producer · no Telegram, no notify-on · no
holdings collapse · no `.env` · no deletion of the 200 HTML files · no `$PROJ`
fast-forward · no PR C · no PP3 v4 · `BehaviorWriteRefused` untouched.
