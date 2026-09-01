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

