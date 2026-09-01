Status:      ACTIVE
as_of:       2026-08-31T23:52:00-04:00 (America/New_York)
Measured at: served release `d276657b7`; branch `overnight/maturity-maceration-2026-09-01` @ `c400501c1`;
             `origin/main` @ `2b9dc0de0` (both moved during the wave — Closeout §1.1)
Canonical repo path: docs/briefs/WAVE_OVERNIGHT_2026-09-01.md
Authority:   READ_ONLY_ADVISORY summary. **Subordinate to `docs/ops/CIO_OVERNIGHT_CLOSEOUT_2026-09-01.md`.**
             Where this file compresses, the closeout governs. Nothing here is evidence; every claim
             points at the document that holds it. MBI_BEHAVIOR = 0.
See also:    docs/ops/CIO_OVERNIGHT_CLOSEOUT_2026-09-01.md  ← the full packet

> **A NOTE ON THIS FILE'S LOCATION, recorded rather than silently absorbed (AGENTS.md §0 rule 10).**
> `docs/briefs/README.md` defines a *brief* as **the operator's instruction that starts a wave**,
> held **verbatim or as a stub**, and states one content rule: *"A brief states questions and
> thresholds. It never states current measured values."* **This file is the opposite of all three** —
> it is a readout written after the fact, by an agent, and it is made of measured values. It was
> commissioned at this path, and this worker's declared file set does not permit creating a file
> elsewhere, so it is written here **with the conflict named**. **Morning decision:** either move it
> to `docs/ops/` (where readouts belong per §14's table) or amend the README to admit a second
> document kind. Naming also strains the convention `WAVE_<n>_<slug>.md`, reading `<n>` as
> `OVERNIGHT`. Neither was resolved tonight.

# CIO overnight wave — the five-minute version, 2026-09-01

## Nothing was pushed

**Nothing pushed, nothing merged, nothing deployed. No cron or systemd entry created, edited or
restarted. No code changed. No store written. No process killed. No Telegram sent. No model called.
No broker path touched.** Documents only, as **10 local commits** on
`overnight/maturity-maceration-2026-09-01`.

**The unpublished count is 12, not 138.** Local `main` is a stale ref, **129 commits behind
`origin/main`**; diffing against it counts other people's merged work as this wave's and overstates
it roughly elevenfold. The honest baseline is `origin/main`.

Both numbers moved during the wave (10/136 at 23:41 → 12/138 at 23:57, as the coordinator committed
and `origin/main` advanced a **third** time). **They moved by the same +2** — the stale-`main` error
is a constant 129-commit offset, not a rate, so re-measuring never rescues the wrong baseline.
*(Closeout §1, §1.1.)*

## The night in one sentence

**The CIO's persistent memory has no writer and never had one — a one-off migration filled it on
2026-08-30, nothing in production has written it since, and that single absence is why four of the
five maturity proofs fail, why a 37-hour-stale number is the one six live decisions cite as their
evidence, and why the PR written to close the filing-cabinet defect reproduced it.**

## The maturity bar (AGENTS.md §15) — five proofs, no percentage

| # | proof | verdict | why |
|---|---|---|---|
| M1 | Research | **NOT_OBSERVED** | Research raises and completes (**343 of 344 lessons research-derived**), but no completed request has ever changed a field on a record. Blocked on the writer. |
| M2 | Advice | **NOT_OBSERVED** | Closest of the five. `next_research_question` genuinely **changed** on `HELD:SCHD` and both questions can be shown — but the writer was the migration, nothing schedules the path, and the council store's last write (2026-08-26) is **four days before** the change, so no critique verdict can be attributed. |
| M3 | Feedback | **NOT_OBSERVED** | **Zero `operator_turns` across all 131 records.** Turn store absent in every root. Two workers, two methods, same answer. |
| M4 | Consistency | **NOT_OBSERVED** — a documented **failure** | **14 statements of total cash, 3 distinct values, in ONE response body.** Naming a failure is not proving a proof. |
| M5 | Persistence | **NOT_OBSERVED** at `d276657b7` | Not for want of wiring (the consult runs) nor want of input (wakes arrive) — **for want of a live disposition.** Zero unexpired deferrals exist; criterion (d) is structurally unsatisfiable at any wake volume. |
| — | *separate, never merged* | **`M5_CANDIDATE` @ pin `1d64cb59f`, as_of 2026-08-31T07:12 ET** | A previous release met every clause. **Worker A refused to launder it across a promote boundary** and recorded it as its own stamped claim. **Do not merge it into the M5 verdict** — whether the two pins share the consult path is UNKNOWN. |

**Zero of five.** §15: *a truthful three-of-five is worth more than a claimed five.* Four of the five
fail through **one** cause, not four.

## P0 — restart before anything else

**`tradeai-health-agent.service` has been running frozen five-day-old code.** Its wrapper calls
`.resolve()` on `CURRENT` **once at start**; PID 3637980 started 2026-08-26 20:38:03 and has held
release `40360117` across **166 subsequent builds**, auto-remediating live (`remediated_ok: 1`,
`dry_run=False`) from a stale tree, logging 20 MB into an orphaned path with no counterpart in
`persistent-state`, reporting **16,356 × `rc=127`** and **19 unfixed escalations, zero resolved**,
where nobody reads.

**The inversion:** `Restart=always`, `NRestarts=0`. It would have re-resolved on any crash. **It is
stale precisely because it has been healthy** — correctness decays with uptime, so no liveness check
will ever catch it and every monitor reports green.

```
# MITIGATION (operator-only; this wave did not run it)
systemctl --user restart tradeai-health-agent.service
# VERIFY BY THE THING THAT MATTERS — not by "service is active":
readlink /proc/$(systemctl --user show -p MainPID --value tradeai-health-agent.service)/cwd
#   must print the CURRENT release dir, NOT 40360117-…
```

**A restart only resets the clock** — it rots again from the next promote. Durable fix is two
candidate shapes (per-cycle re-resolve, or a post-promote hook); **do not choose**, and note
`WorkingDirectory=` is frozen too, so the wrapper fix alone may not suffice. *(Closeout §2 · C §2.4d.)*

## The seven findings

**1 · The record store has no writer, and never had one.**
126 of 131 rows written by `cio_migrate_instrument_records.py` in one 12-hour window on 2026-08-30;
`persist_instrument_record` has **zero callers** (its own `def` is the only occurrence in the served
release) and nothing in crontab reaches `upsert()`. **M5 is blocked on the writer, not the wake** —
and so are M1, M2 and M3.
→ `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` §3 · `docs/ops/CIO_M5_TIMER_WATCH_2026-09-01.md` §8

**2 · PR #810's own contract is dark.**
`decide_after_load` — the module whose title is *"load InstrumentRecord before `decide()`"* — has two
non-test callers: one behind `--dry-run`, **which the cron does not pass**, and one unscheduled
report. **The PR written to close the filing-cabinet defect reproduced it**, and the telemetry that
made `load-by-subject` look wired is a different, shallower consult.
→ `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` §3.4

**3 · The stale store leaks into operator prose.**
`cash_letter.what` reads **"Cash sleeve 630784.82."** — sourced from the unwritten `SLEEVE:CASH`
record — and that same figure appears **six times as `evidence_refs[*].total_cash`**, cited by live
decisions and re-entry candidates justifying themselves. **The stalest of the three values is the one
the system points at as evidence.**
→ `docs/audits/CIO_SURFACE_ASOF_2026-09-01.md` §6

**4 · A production daemon has a frozen `CURRENT`.**
Stated above as P0. Five days, 166 builds, one resolution, stale auto-remediation code, failures into
an invisible log.
→ `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` §2.4d · Closeout §2

**5 · Three `AGENTS.md` §13.4 entries are stale.**
`load-by-subject` (**partly** — right about #810, wrong about the consult), the `OUTCOME` edge
(**158 RESOLVED** via an hourly `--apply` resolver — not dark), and the Telegram gate (**one day
stale** as of commit C4; it now gates the CIO family but still misses 46 chokepoint bypasses). **Each
needs an amendment PR — all queued for morning, none opened tonight**, because opening a PR is a
remote action.
→ Closeout §4.5 · §9

**6 · Node movement since 2026-08-30: four advanced, four regressed.**
Advanced: OUTCOME edge, first outcome-derived lesson (**n=1 of 345**), `SpecialistArtifact@v1-lite`,
phantom receipt stopped. Regressed: council synthesis, notification policy (**zero all-time across
2,046 wakes**), `DeliveryReceipt@v1` (**114 real deliveries, zero receipts**), operator turn / S0.
**Three of the four regressions share one shape — a correct, tested module whose only caller is a
report script not in crontab.** That is the same defect as finding 2.
→ `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` §1.1

**7 · 315 store splits measured against 4 claimed.**
Plus a class no document has a category for: **267 per-release copies of one store, 197 distinct**,
inode-verified as genuinely separate files — and **779 copies / 548 distinct** across three stores,
two of which are the durable state of CIO systemd timers that lose their cursor on every promote.
**315 is a lower bound at a moving instant.** Nothing was picked, merged or deleted.
→ `docs/audits/CIO_DARK_CONTRACTS_2026-09-01.md` §2.3–2.4

## The late fact — the instrument misleads everyone who reads it

Five wakes fired between 23:12 and 23:38 (`wake_ev_morgan`, `wake_ev_steph`, `wake_ev_alex`, two
`wake_goal_goal_*`). **Every one had `subject_resolved=0` with `no_subject=N`. The consult runs, on
an empty set, every time.**

**Both Worker A and Worker C independently nearly mis-scored `load-by-subject` because of this
line.** That is not two worker errors — it is **one instrument defect with a perfect hit rate on the
auditors who read it.** The line also omits a `no_record` counter, so a total memory outage and a
quiet queue emit **byte-identical** output. *(Closeout §5.)*

Exactly 24 hours earlier the same three wake ids produced *"The disposition was recorded earlier and
nobody replayed it."* **The system said M5's own sentence a day ago and cannot say it tonight.**

## Operator-only (§17) — propose and stop

**The list grew: 16 added, 0 closed.** §17 says growth is a finding about how the wave was run, so
plainly: **the wave's shape determined the direction before a single measurement was taken.** A
docs-only read-only census with push, promote, cron edits, `--apply` and live sends all pinned is
**structurally incapable of closing a §17 item.**

**All 16 were DISCOVERED, none CREATED** — every one predates 23:12 ET. The wave wrote no code and
created no new decision; it found sixteen already waiting.
**Recommendation: constitute the next wave with authority to close the reversible ones.** §17
explicitly excludes *labeling, error strings, reversible routing defaults, and additive monitoring*
from the escalate-never-resolve rule.

1. **Restart the frozen health-agent daemon** *(P0)* — and its durable fix, two shapes, do not choose.
2. **Stores:** the holdings pair · `"legacy_read_only": false → true` · symlink `data/audit` + `data/state`
   (would silently merge 779 copies) · two `advisory_kb_lessons.jsonl` copies · six
   `outcome_checkpoints.jsonl` copies.
3. **Scheduled:** crontab 928–930 quoting bug (**fires 05:00 ET; loses telemetry only, not wakes**) ·
   arm `OUTCOME_EXPIRED` · give `due_at` to the **871 structurally-invisible** checkpoints.
4. **Surfaces:** disclose the earmark clamp (**$395,338.80 currently invisible**) · choose the
   canonical cash producer · the `as_of` rename · reclassify `case_summaries` `A → T` — **ask first,
   it may be a deliberate reservation.**
5. **Live-exercise pins:** positive-control the Telegram gate (**silent by construction**) · `--apply`
   catalyst rebuild.

*Full table with flags: Closeout §7. Nineteen proposed morning diffs: Closeout §8. Seven queued
amendment PRs: Closeout §9.*

## What corrected itself, and why that is the headline under the headline

**Nine corrections, kept in per §14.** The coordinator's false Labor Day premise (**2026-09-01 is a
Tuesday; Labor Day is Sept 7**) — kept because it would have licensed writing off a quiet night as a
holiday. The coordinator's false `plan_id` premise, refuted by measurement (**0 of 1,125 carry one;
all 158 settled anyway**). Worker D's §13.5 mis-citation and its **withdrawal** — the brief was
right, and D struck the entries through rather than deleting them. The coordinator finding **four of
its own six stitch headers claimed times after their own commits.** Worker C's **detector-artifact
zero**, and a "six stranded writes" finding that **collapsed to one write seen through six aliases**
under an inode check. Worker A's initial misattribution of wake volume to the cron bug.

**Present these as evidence of method.** A wave that corrected itself nine times measured nine things
it would otherwise have published wrong.

## Status

**A, B, C, D, E complete. No worker aborted.** Every hard pin reached was recognised and stopped at;
one permission denial was **absorbed without routing around it**, and the worker substituted stronger
evidence than the run it was denied.

## `DRIVE_SYNC=OK`

**Folder:** `TradeAI / CIO overnight 2026-09-01` — https://drive.google.com/drive/folders/1Ur6VXRgl2HfVwbDTqdGlkPnLS_Q_85nc
(id `1Ur6VXRgl2HfVwbDTqdGlkPnLS_Q_85nc`, via the `gog` CLI, account `john@jwwhiting.com`, as_of
2026-08-31T23:55 ET.)

**uploaded = 11, failed = 0**, verified by reading the folder back: every byte count matches its
local file, and one document was downloaded out of Drive and compared — **sha256 identical**.
Uploaded as raw Markdown, no Google-Docs conversion, so the evidence blocks survive verbatim.

**Two corrections to the sync instruction.** (1) The set is **eleven**, not the nine the brief named:
six + three omits this brief and the closeout, which are the two documents the packet exists to
deliver. (2) *"TradeAI / CIO overnight 2026-09-01"* was ambiguous — **no `TradeAI` folder exists at
the Drive root**, so the name was created **verbatim as quoted**, as a new root folder. **No existing
folder was modified.** Moving it under `TradeAI CIO Ops` is a one-step operator action.

**No `.env`, keys, credentials or `holdings.json`** — all eleven are Markdown under `docs/`, verified
by a filename check and a content scan for private-key headers, API keys, `sk-` tokens, bot tokens
and AWS keys (no matches).

**The hourly `5 * * * *` sync did not carry this wave.** It ran clean at 23:05 with `uploaded: 32`,
but it reads from the **served release** and tonight's docs are on an unpushed branch in a worktree.
**Its success is not this wave's sync.** `scripts/sync-docs-to-drive.sh` was read, not run; no shared
manifest state was touched. `rclone` has no remotes configured and was not the path.

*Full read-back evidence and the eleven local paths: Closeout §11.*
