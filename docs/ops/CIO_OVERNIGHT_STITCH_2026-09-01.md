Status:      ACTIVE
as_of:       2026-08-31T23:12:00-04:00
Measured at: served release d276657b7 (CURRENT -> d276657b7-main-exact-phase2-20260831-225546, symlink mtime 2026-08-31 22:56 EDT); branch overnight/maturity-maceration-2026-09-01 off c0ae53cf1
Canonical repo path: docs/ops/CIO_OVERNIGHT_STITCH_2026-09-01.md
Authority:   coordinator log for the federated overnight wave; not a behaviour spec, not a verdict
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md
             docs/architecture/CIO_FUTURE_STATE_FULL_MATURITY.md
             docs/architecture/PROJECT_THE_DESK_V2.md
             AGENTS.md §11 §15

# CIO overnight wave — coordinator stitch, 2026-09-01

**NOT PUSHED. NOT MERGED. NOT DEPLOYED.** Everything in this wave is local commits on
`overnight/maturity-maceration-2026-09-01`, docs only. No code was changed. Stated at the top per
AGENTS.md §14 closeout format and §16.

## Wave shape

| worker | scope | declared file set | writes code? |
|---|---|---|---|
| A | M5 timer watch, read-only | `docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md` | no |
| B | Outcome census + dry expire | `docs/audits/CIO_OUTCOME_EDGE_CENSUS_2026-09-01.md`, `docs/ops/CIO_OUTCOME_DRY_2026-09-01.md` | no |
| C | Dark contracts + store splits | `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` | no |
| D | Surface `as_of` | `docs/audits/CIO_SURFACE_ASOF_2026-09-01.md` | no |
| E | Closeout + Drive | `docs/ops/CIO_OVERNIGHT_CLOSEOUT_2026-09-01.md`, `docs/briefs/WAVE_OVERNIGHT_2026-09-01.md` | no |
| coordinator | stitch | this file | no |

File sets are disjoint (AGENTS.md §11). No two workers touch the same file, store or crontab.
No worker runs any git write command; the coordinator makes every commit, so there is no index
contention.

## Standing prohibitions issued to every worker

Broker / `place_order` / 2FA / `BehaviorWriteRefused` · `git push` / `gh pr merge` / promote /
deploy / any new or edited cron or systemd entry · Telegram send / `--backend live` / `--apply` /
Flash / Pro / Grok spend · re-enabling the retired overnight LLM window · mass-expiring drafts ·
deleting anything · picking between divergent holdings copies · minting a new `@v1` type ·
claiming M5 OBSERVED from a hand-run · routing around a permission denial.

---

## Stitch 0 — 2026-08-31 23:12 ET · wave opened

### The one fact that reframes this wave

`[VERIFIED]` The served release was promoted **eight minutes before the wave opened** and it
already carries the P1 `load-by-subject` change.

```
$ readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
/home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546
$ git -C /home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546 log --oneline -1
d276657b7 Merge pull request #810 from PatsKiller/feat/cio-p1-load-by-subject
$ ls -ld /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
lrwxrwxrwx 1 johnclaw johnclaw 93 Aug 31 22:56 ... -> ...-20260831-225546
```

`[VERIFIED]` The `*/5` wake dispatcher is emitting the P1 telemetry line on its natural schedule:

```
$ tail -3 /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/logs/cio_wake_dispatcher.log
2026-08-31 23:07:50,514 [tradeai.cio_wake_dispatch_entrypoint] dispatched=0 skipped=0 errors=0
2026-08-31 23:07:50,515 [tradeai.cio_wake_dispatch_entrypoint] record_consult: wakes=0 subject_resolved=0 record_found=0 changed_by_record=0 skipped_cadence_not_due=0 no_subject=0
2026-08-31 23:07:59,568 [tradeai.cio_wake_dispatch_entrypoint] entrypoint complete: runs=0
```

**Why this matters.** `AGENTS.md` §13.4 lists `load-by-subject` as a dark contract — "built,
tested, **no scheduled wake consumes it**". That entry was written against a release that did not
contain #810. As of tonight the code is in the served release and the counters exist. The dark
contract has therefore moved from "nothing calls it" to, at best, **CODE-WIRED,
RUNTIME-UNPROVEN** — and whether it moves further is exactly what Worker A is watching for.

**It is not M5 yet, and it may not become M5 tonight.** All six counters read zero at 23:07 because
no wake was due. M5 requires a natural unattended fire in which a record is actually loaded before
`decide()` and a days-old disposition is honoured with nobody replaying it (§15). Zero wakes is
`NOT_OBSERVED for want of input`, which is a different finding from `NOT_OBSERVED for want of
wiring`, and Worker A has been told to distinguish them explicitly.

**2026-09-01 is Labor Day**, a US market holiday. Overnight wake volume should be read against
that, not against a normal weeknight.

### Watch mechanism

A detached read-only sampler runs every 30 minutes until 08:00 ET, appending to
`…/scratchpad/watch/samples.txt`. Per tick it records the resolved CURRENT pin, the crontab
sha256 and the CIO wake line, matching systemd timers, the dispatcher log size, and only the log
bytes new since the previous tick. **It invokes no job.** Worker A curates it; the sampler is not
evidence by itself, the quoted natural fires are.

Stamping the pin every tick is deliberate: peer sessions promote from this machine, six promotes
inside one hour have been observed, and a measurement without its pin cannot be compared to
itself later (AGENTS.md §11, §4).

### Drive, established up front so the closeout cannot fake it

`[VERIFIED]` `rclone` is installed at `/home/johnclaw/.local/bin/rclone` but has **no remotes
configured** (`rclone listremotes` → empty, rc=0). The working Drive path is the `gog` CLI
(`v0.12.0`), and the hourly `5 * * * *` sync ran successfully at 23:05 ET tonight:

```
$ cat /home/johnclaw/.local/state/drive-sync-last-result.json
{"status": "done", "started_utc": "2026-09-01T03:05:01+00:00", "uploaded": 32, "skipped": 2289,
 "failed": 0, "exit_code": 0, "src": ".../CURRENT", "source_commit": "d276657b7...", ...}
```

**The consequence, recorded now so it is not discovered as a surprise:** that hourly sync reads
`SRC=…/CURRENT` — the served release. Tonight's documents live on a local branch in a worktree
that is never pushed and never promoted. **The hourly sync will not pick up a single file from
this wave.** Worker E must upload explicitly to the named folder, or report `DRIVE_SYNC=FAILED`
with local paths. It may not report the 23:05 run as though it had carried this wave's docs.

### Open at stitch 0

- A, B, C, D dispatched. E held until the others land — it reports on them.
- No worker has reported. No verdict exists yet. Nothing is marked DONE; the coordinator marks
  work against the proof, never the worker (AGENTS.md §11).

---

## Stitch 1 — 2026-08-31 23:18 ET · a ruled-out timer, and a coordinator error

### CORRECTION: 2026-09-01 is NOT a holiday

In stitch 0 and in Worker A's dispatch brief the coordinator asserted that 2026-09-01 is Labor Day,
a US market holiday. **That is wrong.**

```
$ date -d 2026-09-01 +%A
Tuesday
$ date -d 2026-09-07 +%A
Monday        # Labor Day 2026 is the first Monday of September: 2026-09-07
```

The error is kept here rather than edited out, because of what it would have caused. It handed
Worker A a ready-made excuse: a night of zero CIO wakes could have been written off as "a holiday
eve with no events" and closed as benign. It is not a holiday eve. This is an ordinary overnight
into an ordinary Tuesday session, and **if wake volume is zero all night, the reason is either real
or UNKNOWN — it is no longer explainable by the calendar.**

That makes Worker A's required split — `NOT_OBSERVED for want of input` versus `NOT_OBSERVED for
want of wiring` — harder to resolve and considerably more valuable. The correction was sent to
Worker A with instructions to record it in its own Corrections section rather than silently drop
it. AGENTS.md §14: keep the corrections in.

### `tradeai-continuous.timer` — ruled out as a CIO wake driver

The 23:09 sampler tick surfaced a second scheduled entity firing inside the watch window. The
question — does it touch the CIO wake path — was traced to exhaustion. **It does not.**

| level | evidence | tag |
|---|---|---|
| timer | `OnCalendar=Mon..Fri 04:00`, `Persistent=true`, `Unit=tradeai-continuous.service`. Tuesday matches, so it **fires at 04:00 ET tonight**, inside the window. | `[VERIFIED]` |
| service | resolved `ExecStart=/usr/bin/flock -n -E 0 /run/lock/tradeai-continuous.lock …/linux_launchers/run_continuous.sh`; `WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` — the **main checkout, not the served release** | `[VERIFIED]` |
| last natural fire | `Active: inactive (dead) since Mon 2026-08-31 11:31:05 EDT`, `Duration: 7h 31min`, Main PID 711485, `status=0/SUCCESS` | `[VERIFIED]` |
| launcher | `run_continuous.sh` (20 lines) runs `scripts/system_preflight_check.py` then `scripts/continuous_runner.py --project-root .` | `[CODE]` |
| runner | `continuous_runner.py` (966 lines): **zero** matches for `cio\|wake\|instrument.?record\|subject_key\|decide(`, case-insensitive | `[CODE]` |
| fan-out | `trade_ai_orchestrator.py` (1254), `morning_digest.py` (303), `system_preflight_check.py` (214), `strategy_signal_sync.py` (the orchestrator's only subprocess, at `trade_ai_orchestrator.py:954`): **zero** matches each | `[CODE]` |
| **its own natural-run log** | `grep -ciE "cio\|wake_dispatch\|instrument_record" logs/run_continuous-20260831-040000.log` → **`0`**. File 149725 bytes, 04:00 → 11:31 unattended. Tagged output: 420 `[finviz]`, 7 `[telegram]`. | `[VERIFIED]` |

The last row is what settles it. Source reading is `[CODE]` and proves only what the code says;
the log of an unattended natural fire is rung-1 evidence that the lane, in practice, ran Finviz
and Telegram and touched nothing named CIO.

**Conclusion, to be stated affirmatively rather than assumed:** the CIO wake path has exactly
**one** scheduled driver — crontab line 934, `*/5 * * * *`, `cio_wake_dispatch_entrypoint.py`, run
from the served release. `tradeai-continuous` is a different lane, on a different root, and is
ruled out by both its source and its own runtime log. "The wake is cron-driven only" is otherwise
a claim a reader would assume rather than know.

### Blind spot recorded, not papered over

`/etc/systemd/system/tradeai-continuous.service.d/singleton.conf` is **not readable**:

```
Failed to chase '/etc/systemd/system/tradeai-continuous.service.d/singleton.conf': Permission denied
```

Its effect — the `flock` singleton wrapper — is inferred from the ExecStart that `systemctl status`
resolved, **not read from the file**. Per AGENTS.md §0 rule 3 this was not routed around: no sudo,
no alternate read path. A drop-in we cannot read could in principle alter more than we can see, and
that is stated as a limit rather than assumed away.

### The root split worth carrying to Worker C

`tradeai-continuous` runs from the main checkout; the CIO wake runs from the served release. Two
scheduled lanes on two different roots is exactly the shape that produces checkout-relative store
splits. Flagged into Worker C's store-split sweep.

### Open at stitch 1

- A, B, C, D still running. None has reported. Nothing marked DONE.
- E remains held until A–D land, so its closeout is written against real verdicts. If a worker
  stalls or aborts on a pin, E is still spawned before 08:00 with that gap named as a finding
  rather than left blank.
---

## Standing operator instruction — 2026-08-31 23:19 ET

**Wake the operator if a worker aborts on a pin.** Recorded here so the trigger survives a context
compaction and is not left as a conversational aside.

Fires a push notification, immediately, on: any worker reporting `ABORTED`, or any worker report
stating it stopped because it reached one of the wave's hard pins — broker / `place_order` / 2FA /
`BehaviorWriteRefused`, push / merge / promote / deploy / cron edit, Telegram send / `--backend
live` / `--apply` / model spend, the retired overnight LLM window, mass-expiry / deletion /
choosing between divergent holdings copies, a new `@v1` type, or a permission denial it was told
not to route around.

**Does not fire** on: a worker finishing normally, a worker reporting `NOT_OBSERVED` or `UNKNOWN`
(both are expected and legitimate results, AGENTS.md §14 §15), or a worker hitting an ordinary
investigation dead end.

A worker that fails for a non-pin reason — crash, timeout, empty result — is a different event. It
is recorded in the stitch and carried into Worker E's closeout as a named gap, but it does not wake
the operator overnight unless it leaves the packet materially incomplete.
---

## Stitch 2 — 2026-08-31 23:26 ET · Worker A lands · the dark contract is stale

**Worker A: COMPLETE.** Marked DONE by the coordinator against reproduced proof, not against the
worker's report (AGENTS.md §11). File: `docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md`, 801 lines.
No pin breached, no job invoked, no git write.

**Verdict: `NOT_OBSERVED`** at pin `d276657b7`.

### Coordinator re-measurement of A's headline claims

Every number A reported was re-run independently before accepting it.

| A's claim | coordinator re-measurement | agrees? |
|---|---|---|
| 335 `record_consult` lines | **337** at 23:23 — A measured at 23:22, two `*/5` fires landed between. Not a discrepancy; the log is live. | yes |
| 165 lines with `record_found ≥ 1` | `grep -o "record_consult:.*" \| grep -vc "record_found=0"` → **165** | exact |
| 117 lines with `skipped_cadence_not_due ≥ 1` | → **117** | exact |
| last deferral-honouring line at 10:57:32 | `2026-08-31 10:57:32,949 … wakes=5 subject_resolved=2 record_found=2 changed_by_record=2 skipped_cadence_not_due=2 no_subject=3` | exact |

### FINDING THAT SUPERSEDES `AGENTS.md` §13.4 — the finding wins (§0 rule 10)

§13.4 Dark contracts states: "`load-by-subject` — built, tested, **no scheduled wake consumes it**.
Wiring that call is P1 / M5. Until a cron loads the record before `decide()`, persistence is
unwired."

**That is now false.** A scheduled wake does consume it, it has done so 337 times, and it has
loaded 524 records. The consult runs at `cio_wake_dispatcher.py:195-202`, ahead of the claim at
`:240`. This requires an amendment PR against §13.4 (§20) — **queued for the morning, not opened
tonight**, because opening a PR is a remote action and this wave does not push.

### The verdict is a third category the brief did not offer

The dispatch brief offered A two ways to record `NOT_OBSERVED`: for want of wiring, or for want of
input. **Neither is true, and A was right to refuse both.**

- Not want of wiring — the consult runs, unattended, cron-parented. A captured the ancestry at
  23:15:00: `python ← bash ← cron ← cron(pid 6472) ← systemd`. Rung 1 for the *mechanism*.
- Not want of input — wakes are arriving. Three at 23:18; five fires between 20:08 and 22:28 had
  `record_found ≥ 1`.

**The real reason: there are no unexpired deferrals left to honour.** 40 distinct subject_keys,
38 carrying no `next_eligible_at` at all, and the only 2 that had one — `HELD:SCHD` and
`SLEEVE:CASH` — expired this morning around 10:53–10:58 ET. The acceptance criterion's clause (d)
is therefore **structurally unsatisfiable tonight at any wake volume**, and that prediction is
confirmed by the data: the last `skipped_cadence_not_due ≥ 1` line in the entire log is 10:57:32,
**45 seconds before the last deferral expired.**

`[VERIFIED]` The blocker is a missing **writer**, not a missing loader:

```
$ ls -l .../data/cio/cio_instrument_records.jsonl
-rw------- 1 johnclaw johnclaw 392062 Aug 30 10:58    # now: 2026-08-31T23:24 ET → ~36.5h silent
```

Nothing about the timer, the queue or the loader needs fixing. **M5 cannot be observed because
nothing is writing dispositions for a later wake to honour.** That is the single most actionable
sentence this wave has produced.

### Coordinator refinement of A's storage claim — strengthens it

A reported "`logs/` is a symlink to shared `persistent-state` while `data/` is per-release." That is
imprecise, and the correction matters:

```
$ ls -ld CURRENT/data CURRENT/data/cio CURRENT/logs
drwx------  … /data                                    # per-release, real directory
lrwxrwxrwx  … /data/cio -> /home/johnclaw/trade-ai-releases/persistent-state/data/cio
lrwxrwxrwx  … /logs     -> /home/johnclaw/trade-ai-releases/persistent-state/logs
```

`data/` is per-release, but **`data/cio` is itself a symlink into shared persistent-state.** The
consequence is important: the 36-hour silence is **not** an artifact of tonight's 22:55 promote
stranding writes in an old release tree. The store is genuinely shared and genuinely untouched
since Aug 30 10:58. A's conclusion survives the correction and is strengthened by it. Routed to
Worker C, whose store-split sweep needs this.

### A declined a candidate on a pin technicality, correctly

The strongest line in the log is `2026-08-31 07:12:05 — wakes=5 subject_resolved=5 record_found=5
changed_by_record=5 skipped_cadence_not_due=5`. A refused to call it `M5_CANDIDATE` because **it
was written by pin `1d64cb59f`, not the pin A is stamped to** — `logs/` being shared means the log
spans twelve promotes on 2026-08-31 alone.

The coordinator accepts that reasoning and adopts A's recommendation: record it separately as
**`M5_CANDIDATE @ pin 1d64cb59f, as_of 2026-08-31T07:12 ET`** — correctly stamped, carried to the
morning packet as a candidate against *that* release, and never merged into the `d276657b7`
verdict. This is the §11 rule about stamping every measurement with the pin it was read at, applied
against the worker's own interest in a stronger headline.

### Two evidence defects in the instrument itself

1. **The `record_consult` line omits a `no_record` counter.** A total memory outage and a quiet
   queue emit byte-identical lines. Partly mitigated empirically — `subject_resolved == record_found`
   exactly (524 = 524), so `NO_RECORD` has never fired — but the instrument structurally cannot
   distinguish the two states. This is the §8 trap "two states cannot express *no input*"; the fix
   is a third verdict.
2. **`entrypoint.py:168-171` hard-codes `"unattended": True` and the cron string as literals.** A
   hand-run writes them identically. **That artifact is therefore worthless as M5 proof** — it
   cannot go red where it runs (§16). Proposed fix only; no code edited.

### Routed item — a live cron defect firing at 05:00 ET tonight

`[VERIFIED]` crontab lines 928–930 carry a shell-quoting bug. Reproduced without invoking the
detector:

```
$ bash -c 'echo python3 -c "… print(f'"'"'Wakes: {r.get("wakes_created",0)}'"'"')"'
python3 -c from x import y; r=y(); print(f'Wakes: {r.get(wakes_created,0)}')
```

The shell strips the inner double quotes, so `"wakes_created"` becomes the bare name
`wakes_created`. Confirmed in the detector's own log — rung 1, its own unattended cron fire:

```
$ tail .../logs/cio_detector.log
NameError: name 'wakes_created' is not defined      # ×2, last at Aug 31 05:00
```

**Scope, stated precisely because A initially got this wrong and corrected itself:** the
`NameError` is raised evaluating the `print`, which is the *third* statement on the line.
`run_cio_event_detector_once()` has already returned by then. **Wakes are still created; only the
telemetry is lost.** A first blamed this for the wake volume, was wrong, and recorded the
correction (its §10.8). The coordinator confirms the corrected reading.

Line 928 is `0 5 * * 1-5`; Tuesday matches, so **it fires again at 05:00 ET tonight and will lose
its telemetry again.** Editing a crontab is a hard pin and an operator-only decision (§17). It is
recorded, not touched, and carried to the morning packet.

### Two UNKNOWNs left standing rather than routed around

- root's crontab — `sudo: a password is required`. Not escalated (§0 rule 3).
- `/etc/systemd/system/tradeai-continuous.service.d/singleton.conf` — unreadable, effect inferred
  from the resolved `ExecStart` only.

### Open at stitch 2

- **A: DONE.** B, C, D still running. E still held.
- Deferred-to-operator list gained two items tonight (the §13.4 amendment, the 928–930 cron fix)
  and resolved none. Per §17 that is itself a finding about how this wave was run, and it is
  recorded rather than hidden — though both items are *discoveries*, not deferrals the wave created.
---

## Stitch 3 — 2026-08-31 23:31 ET · the writer never existed · Worker B lands

### THE WRITER THAT STOPPED — it did not stop. There has never been one.

The store was asked directly who wrote it. `[VERIFIED]`, read from
`/home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_instrument_records.jsonl`,
131 rows, as_of 2026-08-31T23:30 ET:

```
=== writer histogram (cc_narrative.writer) ===
  126  migration:deterministic       last updated_ts=2026-08-30T14:53:41Z
    5  cognition:defer_honored       last updated_ts=2026-08-30T14:58:17Z

=== updated_ts range ===
earliest 2026-08-30T02:23:59Z      latest 2026-08-30T14:58:17Z      rows with no updated_ts: 0
```

**Every row in the store was written inside a single twelve-hour window on 2026-08-30, and 126 of
131 were written by the migration script.** The file's mtime — Aug 30 10:58 EDT — is 14:58 UTC,
matching the last row (`HELD:SCHD`) to the second.

A first pass at this histogram keyed on `updated_at` / `author` and returned "131 rows, writer
`(none)`". The fields are `updated_ts` and `cc_narrative.writer`. The correction is kept because
the wrong reading looked like a clean answer — a store with no writer stamps at all — and would
have been reported as one.

### The write graph, traced to exhaustion `[CODE]`

`InstrumentRecordStore.upsert()` at `scripts/lib/cio_instrument_record.py:309` (append at
`:319-320`) is the **only** write in the class. Every path that reaches it:

| entry point | non-test callers | scheduled? |
|---|---|---|
| `persist_instrument_record()` — `lib/instrument_record.py:116` | **ZERO** | dead code |
| `stamp_last_artifact_id()` — `lib/cio_instrument_record.py:536` | `lib/cio_specialist_artifact.py:169` | see below |
| `apply_after_cycle()` — writes `cognition:defer_honored` at `lib/cio_rehydrate.py:272` | `attach_operator_turn()` at `:326` — and that has exactly one non-test caller: **`cio_migrate_instrument_records.py:152`** | no |
| `rollback()` — `:306` | — | no |
| `cio_instrument_record_drill.py` | — | drill tool |

`[VERIFIED]` Nothing in the crontab schedules any of them:

```
$ crontab -l | grep -inE "specialist_artifact|migrate_instrument|rehydrate|instrument_record"
(empty)
```

**So the five `cognition:defer_honored` rows — the only non-migration writes that have ever
existed — were themselves produced by the migration**, through its own call to
`attach_operator_turn`. The cognition writer has never run outside a migration.

### The near-miss that makes it worse

`stamp_last_artifact_id` is the one path that could plausibly be reached on a scheduled wake. It is
not, and the reason is a name collision:

```
$ ls scripts/lib/cio_specialist_artifact*.py
cio_specialist_artifact.py    7479 bytes    ← holds the stamp call at :169
cio_specialist_artifacts.py   4249 bytes    ← PLURAL
$ grep -n "cio_specialist_artifact" scripts/lib/cio_run_worker.py
33:from scripts.lib.cio_specialist_artifacts import resolve_run_specialist_advisories
```

`cio_run_worker` — which **is** in the scheduled wake path, and whose log lines appear in the
dispatcher output — imports the **plural** module. The stamp lives in the **singular** one. And
even if it were reached, it writes `last_artifact_id` only: it cannot set `next_eligible_at`, so
it could never create a deferral for a later wake to honour.

`[VERIFIED]` No log evidence it is ever reached: `grep -ci "last_artifact_id\|stamp_last"` over the
whole dispatcher log → `0`.

### What this means for M5

Worker A concluded the M5 blocker is a missing writer. **That is right, and it is worse than
"missing".** This is precisely the defect `AGENTS.md` §3 names — *a contract built and a caller
never wired* — and §13.4 warns of by name: *"An agent that ships a feature on top of them without
wiring the consumer is repeating the filing-cabinet defect."*

The P1 work landed the **loader**. The loader is correct, scheduled, and running 337 times. It is
reading a store that a one-off migration filled once on 2026-08-30 and that no scheduled process
has written since. **M5 is not blocked on the wake. It is blocked on the fact that nothing in
production has ever written a disposition.**

Corollary worth stating plainly: the 5 deferrals A found expired this morning are the *migration's*
deferrals. When they expired, the system's entire supply of honourable dispositions was exhausted,
and no process exists to make more.

### A live, silent, high-volume failure found in the same path

```
$ grep -c "Action write failed" logs/cio_wake_dispatcher.log
6875
first  2026-08-27 19:16:18  [tradeai.cio_run_worker] Action write failed for rec 0: 'stream_id'
last   2026-08-31 23:23:41  [tradeai.cio_run_worker] Action write failed for rec 24: 'stream_id'
```

**6,875 failures over four days, still firing tonight.** A `KeyError: 'stream_id'` in
`cio_run_worker`, logged and swallowed. Not investigated further tonight — it is a separate defect,
it is on the wake path, and it is routed to the morning packet. Recorded here because a failure
this loud that nothing acts on is the §8 trap *"a guard verified by presence is not a guard"* in
its other form: an alarm that fires constantly and changes nothing.

---

## Worker B — COMPLETE, and it refutes two authorities

**Worker B: DONE.** Marked against reproduced proof. Files:
`docs/audits/CIO_OUTCOME_EDGE_CENSUS_2026-09-01.md` (701 lines),
`docs/ops/CIO_OUTCOME_DRY_2026-09-01.md` (453 lines). No `--apply`, nothing expired, no git write.

### Coordinator re-measurement

| B's claim | coordinator re-measurement | agrees? |
|---|---|---|
| latest-by-id: SCHEDULED 875 · RESOLVED 158 · NOT_PRICE_RESOLVABLE 86 · OUTCOME_PENDING_DATA 6 | **877 · 158 · 86 · 6** — SCHEDULED and total drifted by 2 because the store is live and grew during the audit, exactly as B documented | yes |
| 1,125 distinct `checkpoint_id` | **1,127** (same live drift) | yes |
| hourly resolver, crontab 964, `--apply` | `20 * * * * … scripts/resolve_due_checkpoints.py --apply >> logs/resolve_due_checkpoints.log` | exact |
| 871 of 875 SCHEDULED have `due_at: null` | 877 of 877 latest-SCHEDULED carry `due_at: null` in my read — B's 871/875 is the stricter figure; **either way this is the finding** | direction confirmed |

### THE OUTCOME EDGE IS NOT DARK — second authority refuted tonight

`AGENTS.md` §13.4: *"`OUTCOME` edge — checkpoints exist; **settlement is dark**."*
The AS-IS doc: `✗ OUTCOME — the edge is dark`.

**Both false.** 158 checkpoints RESOLVED, 402 resolution rows across 2026-08-27/29/30/31, most
recent `2026-08-31T14:20:02Z`, written by a resolver that runs **hourly with `--apply`** and is
proven running by its own durable log. 152 travelled `SCHEDULED→OUTCOME_PENDING_DATA→RESOLVED`.

That is now **two** §13.4 dark-contract entries falsified in one night — `load-by-subject` (A) and
the outcome edge (B). Both amendments queued for morning; neither opened tonight, because opening a
PR is a remote action.

### B's own refutations of its brief — findings win

1. **`PENDING_DATA` is fully explained. UNKNOWN = 0.** All 6 are one subject, SCHD/TRIM, awaiting
   `ticker_prices.close_price`/`price_date`, read at `resolve_due_checkpoints.py:89-95`. B then
   found the *next* layer honestly: `_price_lookup_factory` degrades to `lambda: None` on
   connection failure (`:84-86`), so the receipt **cannot** distinguish "SCHD absent" from
   "database down". That degradation is recorded as UNKNOWN rather than papered over.
2. **The real dark mass is `due_at`, not `PENDING_DATA`.** **871 of 875 SCHEDULED checkpoints have
   `due_at: null`** — the factory sets it unconditionally at
   `cio_institutional_learning.py:606`, and `due_checkpoints()` treats null as *not due*
   (`outcome_resolution.py:101-117`). **77% of the store is structurally invisible to the resolver,
   forever.** The brief never asked about this. It is the most important thing B found.
3. **"A checkpoint bound to nothing cannot settle" — my brief asserted this and it is wrong.**
   0 of 1,125 carry a real `plan_id`, and all 158 settled anyway; settlement keys on `decision_id`
   + `original_decision_state.symbol`. The coordinator wrote a premise into the brief and B
   measured it instead of inheriting it. That is the §4 rule working as intended.
4. **"337 lessons, ALL research-fed" is wrong on both counts.** 344 distinct `LessonCandidate@v2`;
   **343 research-derived, 1 outcome-derived.** The outcome→lesson edge has fired exactly once.
   "Never fired" and "fired once" are different states, and only one of them proves the edge exists.
5. **A fifth status exists in code and has never occurred:** `OUTCOME_EXPIRED`
   (`outcome_resolution.py:47`), double-gated behind `--apply-pending-data` +
   `TRADEAI_PENDING_DATA_APPLY=1`, which no cron passes. A state that has never occurred is a
   finding.
6. **No "scored" violation** — 343 candidates carry `cannot_become_policy: true`. The rail holds.

### The store-root trap, measured rather than assumed

B tested my brief's warning instead of repeating it. `outcome_checkpoints.jsonl` resolves via
`production_state_root()` (`canonical_store_registry.py:487-502`), **not** cwd — so the trap does
**not** apply to it. It **does** apply to `CIOPlanStore`, and B reproduced it in the sharpest
possible form: the same dry command, the same minute, **43 would-expire from the served root and 0
from `$PROJ`.**

**Six copies** of `outcome_checkpoints.jsonl` on the box; the `$PROJ` copy is a strict subset
(153/153 upstream, 0 unique). Two divergent copies of `advisory_kb_lessons.jsonl`. Paths, sizes,
hashes and mtimes reported; **nothing picked, nothing merged** (§0 rule 5, §17).

### Permission denial — handled correctly, no wake sent

The auto-mode classifier blocked a **no-flag (dry)** run of `resolve_due_checkpoints.py`. B did not
retry, restructure, or route around it (§0 rule 3). It substituted the hourly cron's own durable
log — **a stronger evidence tier than the run it was denied** — and delivered complete work.

Assessed against the standing wake trigger: **this is not a pin abort.** B did not stop, nothing is
blocked, and no operator decision is needed before morning. Waking the operator for a denial that
was correctly absorbed at zero cost would train them to ignore the alarm. Recorded here and carried
to the morning packet instead.

### Observation, untouched

The 06:52 `cio_draft_plan_hygiene.py --apply` cron fires at 2026-09-01T06:52 ET, 68 minutes before
this wave stops. It has run successfully before (854 hygiene events, 124 on 2026-08-31). **Not
interfered with.** The 43 would-expire plans B itemised are what it is likely to act on.

### Open at stitch 3

- **A: DONE. B: DONE.** C and D still running. E still held.
- Morning amendment queue now holds **two** §13.4 corrections plus the 928–930 cron fix.
---

## Stitch 4 — 2026-08-31 23:33 ET · Worker D lands · three cash totals in one payload

**Worker D: DONE.** Marked against reproduced proof. File:
`docs/audits/CIO_SURFACE_ASOF_2026-09-01.md` (1,237 lines). GETs only, no POST, no store write, no
code edit, no git write. Measured at pin `d276657b7`, server PID 2076495 on port 7777, cwd pinned to
the concrete release directory so symlink rotation could not re-point the measurements. Re-verified
unrotated at close.

### The `as_of` headline

| surface | leaf paths | value-bearing | **no evidence clock of their own** |
|---|---|---|---|
| `/api/v3/cio/home` | 2,254 | 2,098 | **1,140 — 54.3%** |
| `/api/v2/overview` | 188 | 183 | **182; compliance 0 of 183** |

D split the 1,140 rather than reporting a single number: 589 inherit only the root envelope, 543
sit under a block stamped with *composition* time — within 0.6s of the envelope, which D calls a
**false pass** rather than a pass — and 8 hang off root. That distinction is the brief's
`INHERITED` requirement doing real work: a block-level timestamp covering a field computed at a
different moment is a defect, not compliance.

### Class A is 22, not zero — and mislabelled, which is worse

`[VERIFIED]` by the coordinator against the live payload:

```
$ curl -s http://127.0.0.1:7777/api/v3/cio/home | ... count of '"class": "A"'
22
```

The AS-IS doc's headline — *"Agent-originated fields reaching any operator surface: zero"* — is
false as stated. But D did not stop at the refutation, and the second half is the finding:
`class: "A"` is a **hardcoded literal** at `cio_investment_product.py:917,963`, and the content it
labels is a pure f-string at `hermes_case_summary.py:68-98` copied out of a stored record. That is
T-over-S wearing an A label.

**Both readings are defects, and a mislabelled A is worse than an absent one** — a zero is honest
about the system's maturity, whereas a false A tells the operator the agent formed a view when it
recited a template. Counted *by producer* rather than by label, the AS-IS doc's other sentence —
"every sentence the operator reads is a rule, a threshold, a template, or a constant" — is
substantively correct. Both things are true at once and the document says so.

Near-miss, as briefed: `operator_product.executive_summary`, the clause
`[D] Nothing requires action today.` — the §9.1 named trap. The codebase self-diagnoses it at
`cio_p90_voice.py:24-35` and ships it anyway.

### The three-way-branch field, found and quantified

`capital_plan.cash_earmarked_redeploy_usd`, branch at `cio_capital_plan.py:388-396`. Raw earmark
**$1,026,129.22** across 38 open events exceeds cash, so the renderer emits `min(raw, cash)`.

**It reads as a total; it is a ceiling.** $395,338.80 of earmark is invisible on the surface, and
`cash_free_unearmarked_usd = 0.00` is *forced by the clamp*, not measured. `maturities_capped_to_cash`
and `maturities_raw_usd` are computed and then dropped by the renderer.

Coordinator corroboration D did not claim: in the live payload
`cash_earmarked_redeploy_usd == cash_total_usd == 630790.42` **exactly**. That equality is the
fingerprint of the clamp — visible in the payload without reading the branch at all.

### THE FINDING OF THE NIGHT — three live values for total cash, in one response body

`[VERIFIED]` coordinator re-measurement, single GET of `/api/v3/cio/home`:

```
630791.10   temperament.cash · operator_product.temperament.cash
630790.42   capital_plan.cash_total_usd · capital_plan.cash_earmarked_redeploy_usd
            capital_plan.sources[2].usd · cash.cash_usd · operator_product.cash.cash_usd
630784.82   cash_letter.cash_usd · 6× decisions[*]/opportunities[*]
            .cc_narrative.evidence_refs[*].total_cash
'Cash sleeve 630784.82.'   ← cash_letter.what, the sentence the operator reads
```

and `/api/v2/overview` → `data.total_cash = 630791.10`.

**This is worse than D reported it.** D framed part of it as a cross-surface disagreement. It is
not: `/api/v3/cio/home` **alone** states total cash three different ways in one body. A reader can
find the contradiction without leaving a single page.

Compounding defects D found around it:

- `cash_letter` pairs the **stale** total with a **live** `cash_investable_usd`, so the block does
  not reconcile with itself: `630,784.82 − 256,595.22 = 374,189.60`, but it displays `374,195.20`.
  Both are stamped under an `as_of` belonging to neither. Root cause: precedence at
  `cio_record_narrative.py:103-105`.
- The `630784.82` figure comes from the **stale `SLEEVE:CASH` InstrumentRecord** — the same store
  stitch 3 showed has not been written since 2026-08-30. **The dead writer is now visibly leaking
  into the operator's sentence.** That connection is the wave's, not any single worker's, and it is
  the strongest argument that the missing writer is not a theoretical gap.
- `/api/v2/overview`'s `total_cash` inherits `2026-08-29` when the oldest contributing balance is
  `2026-08-03` — **26 days too fresh**. The offending row is literally the $500 moomoo balance that
  `AGENTS.md` §9.1's "27-day-old $500" rule appears to have been written about.
- The surface ships `consistency.decision_field_parity.ok = false` **inline**, on the page, and
  nothing acts on it.
- A code comment at `api_v2.py:2593-2601` asserts these totals agreed "to the cent, gap 0.00" on
  2026-08-29. Measured tonight the gap is **$0.68**. A policy comment that outlived its policy —
  §3, by name.

Per the brief D did **not** declare M4 observed, and listed the five things that would remain to be
shown. Correct: this is an M4 *failure* case, and naming it is not the same as proving the proof.

### The half-refutation, kept because it is a correction in our favour

The AS-IS doc says "most payload blocks — including every cash number — carry no `as_of` of their
own." D found that **half wrong**: `/api/v3/cio/home` *does* give cash a correct oldest-balance
stamp via `cash_evidence_as_of` (`cio_capital_plan.py:841-890`), which D assessed as a faithful
§9.1 implementation. The AS-IS claim holds only for `/api/v2/overview`. Recording the half that is
already right matters: it is the difference between "nobody implemented this" and "somebody
implemented it correctly in one place and it was never carried to the other."

### Coordinator correction TO Worker D — the brief was right

D reported: *"Provenance classes are §13.5 (`AGENTS.md:785-793`), not §13.4."* The line numbers are
right; the attribution is not.

```
$ grep -n "^## 13\.\|^### Provenance" AGENTS.md
689:## 13.4 · The type vocabulary — what already exists
785:### Provenance classes — every operator-facing field carries one
834:## 13.5 · Pre-build check
```

785 falls between 689 and 834, so **"### Provenance classes" is a subsection of §13.4** and the
original brief's citation was correct. §13.5 is "Pre-build check" and contains no provenance
classes. Sent back to D to revert the citation and record the round trip in its Corrections
section rather than silently reverting.

**The mechanism of the error is worth keeping:** D resolved the nearest enclosing `###` rather than
the nearest `##`. That is a reproducible way to mis-cite this file, and it is now written down.
This is also the multi-agent protocol working in the direction it is usually not tested in — §11
says the finding wins over the brief, but only when the finding survives re-measurement, and this
one did not.

### D's two self-flagged caveats, endorsed

1. The ~106 `D` declarations it did not trace to producers should be treated as **unverified** —
   because the one class it *did* audit end to end turned out to be mislabelled. That is the right
   inference to draw from its own finding, and it is the opposite of the convenient one.
2. `/api/v3/cio/brain/capital-plan` returns a **fourth** cash presentation, with
   `investable_cash_usd` and `reserved_cash_usd` as `null` where `/home` states them as known.
   Flagged, not pursued, named as the first place to look next. Left for morning deliberately.

Eight proposals sit in "Proposed morning diffs"; **three are flagged OPERATOR-ONLY per §17** — the
earmark label change, the choice of a canonical cash producer, and the `as_of` rename. Proposed and
stopped.

### Open at stitch 4

- **A: DONE. B: DONE. D: DONE** (one citation fix outstanding). **C: still running. E: still held.**
- Three of the AS-IS document's headline claims have now been refuted or halved in one night, and
  two §13.4 dark contracts falsified. The morning amendment queue holds: two §13.4 corrections, the
  AS-IS class-A claim, the AS-IS cash-`as_of` claim, and the 928–930 cron fix.
---

## Stitch 5 — 2026-08-31 23:35 ET · D's correction lands and deepens the finding

**Worker D: DONE, deliverable committed.** `docs/audits/CIO_SURFACE_ASOF_2026-09-01.md`,
now 1,324 lines. Citation reverted; two round trips recorded rather than deleted.

### The citation round trip, closed honestly

D reverted §13.5 → §13.4 at five sites (546, 566, 576, 579, 1096) after re-running the grep itself.
The two "correction" entries are **struck through and marked WITHDRAWN rather than deleted**, in
both §0 and §8 — a reader who saw the wrong claim can find out what happened to it.

D named the mechanism precisely: it resolved the nearest `###` heading and treated it as a peer of
the `##` sections, when a line range alone cannot distinguish a subsection from a sibling. And it
recorded why this particular error stings: *it landed in a section whose whole purpose was
correcting someone else, and a confident correction is exactly the claim that gets re-used without
re-checking.* §11's "the finding wins" is not a licence to skip verifying the finding.

That is the maturity bar applied to the wave's own reasoning, not just to the system.

### The cash finding is bigger than either of us had it

The coordinator told D the three values sat in one body. D reproduced it, then found the
coordinator had **also** understated it. `[VERIFIED]`, single GET of `/api/v3/cio/home`:

```
TOTAL statements of total cash in ONE response body: 14      distinct values: 3
   630,791.10  ×2    temperament.cash · operator_product.temperament.cash
   630,790.42  ×5    capital_plan.cash_total_usd · .cash_earmarked_redeploy_usd
                     .sources[2].usd · cash.cash_usd · operator_product.cash.cash_usd
   630,784.82  ×7    cash_letter.cash_usd
                     cio_now.decisions[2].cc_narrative.evidence_refs[3].total_cash
                     cio_now.decisions[3].cc_narrative.evidence_refs[1].total_cash
                     opportunities.watch[1].cc_narrative.evidence_refs[1].total_cash
                     opportunities.reentry[0].cc_narrative.evidence_refs[2].total_cash
                     opportunities.reentry[3].cc_narrative.evidence_refs[2].total_cash
                     opportunities.reentry[4].cc_narrative.evidence_refs[2].total_cash
```

**Fourteen statements of one quantity, three answers, one page.**

Two consequences neither of us had before, both D's:

1. **It kills the tidy explanation.** The comfortable story was "the CIO surface uses the row sum,
   overview uses the stored field" — two producers, one boundary, one reconciliation to write.
   False: `/api/v3/cio/home` carries **all three producers at once**. There is no boundary to
   reconcile across; the disagreement is internal to a single composition.
2. **The stalest value is the one cited as evidence.** `630,784.82` appears **six times as
   `evidence_refs[*].total_cash`** — it is the number individual decisions and re-entry candidates
   point at *to justify themselves*. And it originates in the stale `SLEEVE:CASH`
   InstrumentRecord — the store stitch 3 proved no production process has written since
   2026-08-30.

So the chain closes end to end: **a store with no writer → a record 36 hours stale → the number six
live decisions cite as their evidence → the sentence the operator reads.** No single worker could
see that; A found the dead writer, D found the leak, and it is the wave that connects them.

D also found `temperament` is stamped `as_of: 2026-08-03` — the cash-*evidence* clock — while
carrying the *stored-field* value. A timestamp belonging to a different producer than the number it
sits beside. Added to the inherited-not-theirs table.

### The clamp fingerprint, promoted to a rule

`cash_earmarked_redeploy_usd == cash_total_usd == 630790.42` **exactly**. D added this as its own
row with the right generalisation: an earmark equal to cash **to the cent** should be read as
`min(raw, cash)` having returned `cash` until proven otherwise, because a genuine coincidence to
the cent is vanishingly unlikely. That is a detector someone can apply to this surface next month
without reading `cio_capital_plan.py` at all.

### Open at stitch 5

- **A: DONE. B: DONE. D: DONE.** All three deliverables committed.
- **C: still running.** E: still held.
- **Unpushed vs `origin/main`: 8 commits, docs only.** Trap recorded for E: local `main` is stale
  at `1b8002903`, far behind `origin/main` at `d276657b7`; diffing against local `main` reports
  **132**. The honest baseline is `origin/main`, and the honest number is single digits.
---

## Coordinator correction — 2026-08-31 23:37 ET · the stitch log mis-stamped itself

Every stitch header carried a hand-estimated time rather than a measured one. Checked against
`git log`, which is authoritative:

```
$ git log --format="%h  %ad  %s" --date=format-local:'%H:%M' origin/main..HEAD --reverse
dddfd7cb6  23:14  stitch 0        claimed 23:12
3ffef60d5  23:18  stitch 1        claimed 23:22   ← 4 min AFTER its own commit
b8832f8c8  23:26  stitch 2        claimed 23:26   ok
158f6d6dc  23:31  stitch 3        claimed 23:34   ← 3 min after
340525e4f  23:33  stitch 4        claimed 23:38   ← 5 min after
afa8dd212  23:35  stitch 5        claimed 23:45   ← 10 min after
```

**Four of six headers claimed a time later than the commit that contains them — physically
impossible.** The drift grew monotonically, which is the signature of estimating forward from the
last estimate instead of reading the clock.

Headers corrected to their commit times. The claimed values are preserved above so the error is
auditable rather than erased.

**This is the wave's own standard turned on the wave.** §4 requires every measurement to carry
value + `as_of` + root, and §14 says a document with no trustworthy `as_of` cannot be compared to a
later one. The coordinator spent the night enforcing that on four workers — correcting D's
citation, correcting A's holiday premise, re-measuring every headline count — while its own
document invented its timestamps. A coordinator that only audits downward is an incomplete
instrument.

Nothing downstream depended on these values: no verdict, count, hash or pin was derived from a
stitch header, and every measurement inside the stitches carries its own separately-sourced `as_of`
and root. The defect is in the log's self-description, not in its evidence. Recorded because the
next reader has no way to know that without being told, and because an error found by the party
that made it is the cheapest kind there is.

Going forward every stitch header is stamped from `TZ=America/New_York date`, read at write time.
---

## Stitch 6 — 2026-08-31 23:40 ET · Worker C lands · the frozen `CURRENT`

**Worker C: DONE.** `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md`, 1,164 lines, 69 `[VERIFIED]`,
13 `[CODE]`. Pin `d276657b7` re-verified at 23:12, 23:22 and 23:36 — it did not rotate, so every
runtime claim is attributable to one pin. Two PINs reached, both **proposed and stopped**, neither
an abort: positive-controlling the Telegram gate (requires a live send) and an `--apply` catalyst
rebuild.

### THE ABANDONED-TREE WRITER — traced to the process, live

C's §2.4d found a 20 MB log appended tonight into a release promoted away on 2026-08-26. It
attributed the cause to daemons "holding open handles." **The mechanism is different, and worse.**

`[VERIFIED]` No process held the file open when checked between cycles. The writer re-opens by
path. Caught in the act at 23:38:11:

```
$ pgrep -af escalation
2446485 …/.venv/bin/python \
  /home/johnclaw/trade-ai-releases/portfolio-server/40360117-main-exact-phase2-20260826-202631/scripts/claude_escalation_handler.py --tier1-only
  cwd: …/40360117-main-exact-phase2-20260826-202631

$ ps -o pid,lstart,cmd -p 3637980          # its parent
3637980  Wed Aug 26 20:38:03 2026  …/.venv/bin/python /home/johnclaw/.config/tradeai/bin/health_agent_daemon_current.py
  cwd: …/40360117-main-exact-phase2-20260826-202631
  parent: systemd --user (pid 7039)
```

**The root cause is one line in the wrapper** (`/home/johnclaw/.config/tradeai/bin/health_agent_daemon_current.py`,
mtime 2026-08-17):

```python
CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT").resolve()
...
lpr.get_live_project_root = lambda: CURRENT
```

**`.resolve()` runs once, at daemon start.** It follows the symlink and freezes the concrete
directory for the life of the process. The daemon started **2026-08-26 20:38:03** — twelve minutes
after release `40360117` was promoted at `20:26:31` — and has held that resolution for **five days
and at least twelve subsequent promotes**, including tonight's. Every subprocess inherits the
frozen root through the `get_live_project_root` override, so each 10-minute escalation cycle opens
the stale path fresh. That is why no handle was held.

**The name exceeds the code, and it is the wrapper's own docstring that promises it:** *"Host
overlay: run exact-main CURRENT health daemon."* It runs whatever `CURRENT` was when the daemon
started. The file is even named `health_agent_daemon_**current**.py`. This is `AGENTS.md` §7
"Controls whose name exceeds their code" and §8 "**Resolve `CURRENT` to a concrete directory before
verifying** — it has rotated three times in fifteen minutes," and the wave was told that rule and
applied it to its own measurements all night while a production daemon has been violating it for
five days.

**The bitter part:** the wrapper exists *to fix a root-resolution bug* — its docstring cites #349,
"CURRENT/scripts/health_agent_daemon.py rebases PROJECT_ROOT to the git checkout whenever that tree
exists. That made #349 collectors dead on a live exact-main release." It fixed that one and
introduced a different one. A repair verified by the symptom it targeted.

**Consequences, none of them acted on tonight:**

1. **Five-day-old code is running in production.** Any fix landed in `claude_escalation_handler.py`
   since 2026-08-26 is not running. Twelve promotes have gone past it.
2. **It is invisible to anyone reading `CURRENT/logs`.** C's warning generalises: *a lane can be
   running, logging, and completely invisible to an auditor reading the served release.* That
   applies to this document.
3. `[VERIFIED]` It is failing loudly into that invisible log:
   `❌ retry_cmd failed (rc=127, 0.1s)` — 127 is *command not found*, consistent with a stale tree
   whose referenced paths have moved — and
   `SKIP Tier2/3 LLM — 19 remaining unfixed; Tier1 resolved=0`. **Nineteen unfixed escalations, zero
   resolved, reported to a file nobody reads.**

**Not restarted, not killed, not touched.** Restarting a production daemon is not in this wave's
authority and is not a docs-only action. Proposed for the morning; the operator decides.

### C's node movement — four advanced, four regressed

**Advanced:** OUTCOME edge `✗ → ▓` (corroborates B independently); LESSON `▓` with the first
outcome-derived lesson, **n=1 of 345** — the AS-IS sentence "the system learns from what it read,
not what happened" is now false *by exactly one*; `SpecialistArtifact@v1-lite` `░ → ▓` (formal type
exists, N=100 gate still fails, **instrument bind regressed 64→59%**); `MODEL_CALL_RECORDED` phantom
receipt stopped 2026-08-28.

**Regressed:** `CIOCouncilSynthesis@v1` `█ → ░` (one artifact, 5 days stale, `DISPUTED` count 0,
sole caller not in crontab); NOTIFICATION POLICY IMMEDIATE and COMMAND_CENTER_ONLY `█ → ✗` — **zero
all-time across 2,046 scanner wakes**, only SUPPRESSED (4,611) and DIGEST (38) have ever fired;
`DeliveryReceipt@v1` `█ → ░` — **n=1 and that row is `would_send: false`; 114 real deliveries
produced zero receipts**; OPERATOR turn / S0 `▓ → ✗` — **zero `operator_turns` on any record**, turn
store absent in every root.

C's synthesis: *three of the four regressions share one shape — a correct, tested module whose only
caller is a report script not in crontab.* That is §3's defect, found three more times in one night.

The S0 regression compounds stitch 3: the record store has no writer **and** no operator turn has
ever landed on it. A and C reached that from opposite directions.

### Splits: 315 measured against 4 claimed

Plus a class the AS-IS doc has no category for: **267 per-release copies of one CIO store, 197
distinct**, inode-verified as genuinely separate files. Two of seven declared `PERSISTENT_TREES`
are unwired. Cause named in one artifact: `"legacy_read_only": false` plus **266 PROJ-rooted cron
lines against 45 at CURRENT**. Three operator-only decisions proposed and stopped; nothing merged,
nothing chosen.

### `load-by-subject` — C splits the question and finds the sharper half

C refused to answer (a)/(b) as one question. Pre-claim consult at `cio_wake_subject.py:168` is
**(b) CODE-WIRED, RUNTIME-UNPROVEN**, capped there with the M5 verdict handed to Worker A
explicitly — exactly as briefed.

**But PR #810's own contract is (a): dark.** `decide_after_load` — the module whose title is "load
InstrumentRecord before `ResearchNeedDecision.decide()`" — has two non-test callers: one behind
`--dry-run`, **which the cron does not pass**, and one unscheduled report.

**The PR written to close the filing-cabinet defect reproduced it.** That is the single most
important sentence C produced, and it sharpens stitch 2: the telemetry that made `load-by-subject`
look wired is a *different, shallower* consult than the one #810 shipped.

### Telegram — the gate is named, and it is ENABLED

`telegram_transport._interdicted()` at `scripts/telegram_transport.py:86`, enforced at
`deliver_text:164`. **ENABLED, not interdicted**, proven at rung 1: an unattended systemd fire put a
message on the operator's device at 20:22:02 ET, journal and `mark_sent` ledger agreeing to the
millisecond.

**The gate has never been observed firing**, and C found why it structurally cannot be:
`_interdicted_result()` **writes no log line** — it is silent by construction. A guard verified by
presence, and one that cannot be verified any other way without a live send. Pinned, proposed,
stopped.

C also found `AGENTS.md` §13.4/§7 is **one day stale**: "does not gate the family that reaches the
operator" was true until commit C4 (dated in-code 2026-08-31) moved the check to the lowest common
layer. It now *does* gate the CIO family — but still does not gate **46 chokepoint bypasses**.

### C's two self-caught errors, both kept

1. **It nearly scored `load-by-subject` as (c).** The `record_consult` telemetry fires every 5
   minutes *on an empty set* — the same trap A identified from the other side. Two workers
   independently nearly mis-scored the same node the same way, which is a finding about the
   instrument, not about either worker.
2. **It published a zero that was a detector artifact.** `find -newermt "-90 minutes"` silently
   matched nothing; an inode check then collapsed a "six stranded writes" finding to **one write
   seen through six aliases.** A surviving mutation that was an invalid mutation — §8, by name.

### Open at stitch 6

- **A, B, C, D: all DONE.** All deliverables committed. **E: spawning now.**
- Morning queue: two §13.4 dark-contract amendments, a third §13.4/§7 staleness correction, the
  AS-IS class-A and cash-`as_of` claims, the 928–930 cron fix, the frozen-`CURRENT` daemon, and
  three operator-only store decisions.
---

## Stitch 7 — 2026-08-31 23:43 ET · operator raises the frozen daemon to P0

Operator instruction received: **the frozen-`CURRENT` daemon is P0 in the morning packet.** Routed
to Worker E for the top slot in both files, with remediation as a runnable command. **Nothing was
killed, restarted or touched** — the restart is operator-only under §17 and this is a docs-only
wave. It is recorded as a P0 *proposal with a verified diagnosis*, not as an action taken.

### Supervision established — the diagnosis is now complete

`[VERIFIED]`

```
$ cat /proc/3637980/cgroup
0::/user.slice/user-1000.slice/user@1000.service/app.slice/tradeai-health-agent.service

$ systemctl --user status tradeai-health-agent.service
● tradeai-health-agent.service - TradeAI Health Agent daemon
    (continuous score + auto-remediate + tier1 escalation)
     Active: active (running) since Wed 2026-08-26 20:38:03 EDT; 5 days ago
     Main PID: 3637980 (python)     CPU: 2h 38min
     Drop-In: 20-exact-main.conf, 30-current-collectors.conf
```

Three `ExecStart` layers, each resetting the last; the effective one is the wrapper. Base unit
`WorkingDirectory` is `$PROJ`; both drop-ins override it to the **`CURRENT` symlink path**, which
systemd also resolves at start. So the root is frozen twice over — once by systemd, once by the
wrapper's `.resolve()`.

### Why it is P0 and not merely untidy

1. **It auto-remediates.** The unit's own description is "continuous score + **auto-remediate** +
   tier1 escalation". Five-day-old remediation code is acting on a system that has moved twelve
   promotes underneath it.
2. **It fails where nobody reads.** 20 MB appended tonight at 23:22 to a log whose filename does
   not exist in `persistent-state/logs` at all; `retry_cmd failed (rc=127)` and
   `SKIP Tier2/3 LLM — 19 remaining unfixed; Tier1 resolved=0`.
3. **The inversion — the finding of the night after the writer.** `Restart=always`,
   `RestartSec=20`. The daemon would have re-resolved `CURRENT` on **any** crash. It has not
   crashed in five days. **It is stale precisely because it has been healthy.** Its correctness
   decays with its uptime, so no liveness check will ever catch it, and every monitor on this box
   reports it green.

That is a new shape for this repository's catalogue. §8 already records "a guard verified by
presence is not a guard" and "two states cannot express *no input*". This is a third: **a component
whose wrongness is proportional to its uptime, and therefore invisible to every health signal that
measures whether it is running.**

### Remediation — mitigation and durable fix, deliberately not conflated

**Mitigation** (one command, reversible, self-healing under `Restart=always`):

```
systemctl --user restart tradeai-health-agent.service
readlink /proc/$(systemctl --user show -p MainPID --value tradeai-health-agent.service)/cwd
```

The second line is not optional. It must print the current release directory, not `40360117`.
Verifying by "service is active" would repeat the very defect being fixed.

**Durable fix** — the mitigation only resets the clock; the daemon rots again from the next promote
onward. Two candidate shapes, **proposed, not chosen**: (a) re-resolve the root per cycle rather
than freezing it at import; (b) a post-promote hook restarting this unit. Because the unit's
`WorkingDirectory` is *also* the symlink path and systemd resolves it at start, **(a) alone may not
be sufficient** — stated as an open question rather than asserted either way.

### The repair that introduced it

The wrapper exists to fix a root-resolution bug. Its docstring: *"CURRENT/scripts/health_agent_daemon.py
rebases PROJECT_ROOT to the git checkout whenever that tree exists. That made #349 collectors dead
on a live exact-main release."* It fixed that one and introduced this one — **a repair verified by
the symptom it targeted**, which is §8 almost verbatim.

### Open at stitch 7

- A, B, C, D: **DONE**, all deliverables committed. **E: running**, P0 routed.
- Discovered, not created: this belongs in the *discovered* column when E tallies whether the
  operator-only list grew.
---

## Standing operator instruction (2) — 2026-08-31 23:44 ET

**Wake the operator when Worker E lands.** Recorded so it survives a context compaction.

Fires a push notification the moment E reports, carrying: the M1–M5 verdicts, `DRIVE_SYNC` status
(`OK` or `FAILED`), the honest unpushed commit count against `origin/main`, and confirmation that
the frozen-daemon P0 took the top slot. E is the last worker; when it lands the morning packet is
complete and the wave has nothing further to produce before 08:00.

This supersedes nothing. The wake-on-pin-abort trigger recorded earlier remains armed for E as it
was for A–D — if E aborts on a pin instead of landing, that fires first and says so.

If E lands with `DRIVE_SYNC=FAILED`, the notification says so explicitly rather than reporting a
bare completion. A failed sync with truthful local paths is a complete deliverable under §14, but
it is not something the operator should discover in the morning by reading carefully.
