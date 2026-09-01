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

## M5 — partially observed, and the distinction matters

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
- **The wake cron overlaps itself.** Line 949 is one of the few crontab lines **without
  `flock`** (322 lines use it; this one does not), and runs take 4–6 minutes against a
  `*/5` schedule — two dispatchers were observed running concurrently at 13:05. The lease
  prevents the same wake being dispatched twice, and `upsert` appends one line per write so
  no line can tear. But this change adds a **cognition write** to that path, and two
  overlapping cycles touching one `subject_key` could lose an update (load → append →
  last-writer-wins projection). **Adding `flock` is a cron change and therefore
  operator-only (§17) — proposed, not done.**
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

## Not done, by instruction

No `outcome --apply` · no AgentView/commitment producer · no Telegram, no notify-on · no
holdings collapse · no `.env` · no deletion of the 200 HTML files · no `$PROJ`
fast-forward · no PR C · no PP3 v4 · `BehaviorWriteRefused` untouched.
