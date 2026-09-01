Status:      ACTIVE
as_of:       2026-08-31T23:20:21-04:00 (America/New_York)
Measured at: served release git pin `d276657b721011ae126d234b6300c9225d651a3e` (`.../portfolio-server/d276657b7-main-exact-phase2-20260831-225546`); audit worktree `overnight/maturity-maceration-2026-09-01` @ `c0ae53cf1`
Canonical repo path: docs/ops/CIO_OUTCOME_DRY_2026-09-01.md
Authority:   READ_ONLY_ADVISORY — dry-run receipt. No writes, no broker, no orders, no expiry. MBI_BEHAVIOR = 0.
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md, AGENTS.md §13.4 §15, docs/audits/CIO_OUTCOME_EDGE_CENSUS_2026-09-01.md

# CIO staleness routine — dry-run receipt

> # NO `--apply` WAS RUN. NOTHING WAS EXPIRED.
>
> No `--apply`, `--run`, `--execute`, `--commit`, or any other write flag was passed to any tool
> in this session. Nothing was expired, cancelled, deleted, mass-expired, or archived. The two
> commands executed below are the tools' own default no-flag dry paths. §5 proves by durable
> artifact that the target stores are byte-identical before and after.

---

## 1. The routine, and why this one

The staleness routine that applies to CIO plans and drafts is **`scripts/cio_draft_plan_hygiene.py`**
(library: `scripts/lib/cio_draft_plan_hygiene.py`). It is the tool the brief flagged as running
`--apply` from cron at 06:52.

A second staleness/expiry path exists for **checkpoints** rather than plans —
`scripts/resolve_due_checkpoints.py --apply-pending-data`, which writes `OUTCOME_EXPIRED`. It is
covered in §7 from its own durable log rather than by a run here; see §8 PIN for why.

## 2. The dry-run flag, read from the argument parser

[CODE] `scripts/cio_draft_plan_hygiene.py:20-24` — the parser, verbatim:
```
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write PLAN_UPDATED/STATUS_CHANGED (default dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="Max plans (0 = all eligible)")
    ap.add_argument("--json", action="store_true")
```
There is no `--dry-run` flag. **Dry is the default; `--apply` is the only write switch**, and
`action="store_true"` means it defaults to `False` when absent. `--json` and `--limit` are
read-only shape controls.

[CODE] `scripts/cio_draft_plan_hygiene.py:26-30` — the call, which threads `apply` straight through:
```
    from scripts.lib.cio_plans import CIOPlanStore
    from scripts.lib.cio_draft_plan_hygiene import expire_stale_empty_drafts
    store = CIOPlanStore()
    rec = expire_stale_empty_drafts(store, apply=args.apply, limit=args.limit)
```

## 3. Confirming the dry path is genuinely non-writing — before running it

The brief's condition: *confirm from source that no write occurs without `--apply`; if you cannot,
do not run it.* Three write surfaces were checked, not one.

**3a. The expiry function itself.** [CODE] `scripts/lib/cio_draft_plan_hygiene.py:77-97` —
the *only* mutation in the module is `store.update_plan(...)` at line 91, and it sits inside
`if apply:` at line 86:
```
def expire_stale_empty_drafts(store, *, apply=False, now=None, limit=0):
    candidates = select_stale_empty_drafts(store, now=now, limit=limit)
    expired: list[str] = []
    if apply:                                          # <- line 86
        for plan in candidates:
            ...
            store.update_plan(                         # <- line 91, the ONLY write
                pid, status="cancelled",
                status_reason=HYGIENE_REASON,
                actor_id="cio_draft_plan_hygiene",
            )
```
With `apply=False` the function calls only `select_stale_empty_drafts`, which iterates
`store._plans` **in memory** ([CODE] `:59-74`) and returns dicts. No file handle is opened.

**3b. The selection predicate.** [CODE] `:41-56` `is_stale_empty_draft` — pure, reads plan fields
only, no I/O.

**3c. The store constructor — the non-obvious one.** `CIOPlanStore()` is instantiated before
`apply` is ever consulted, so it must be checked independently. [CODE] `scripts/lib/cio_plans.py:101-122`:
```
    def __init__(self, event_path=DEFAULT_EVENT_PATH, projection_path=DEFAULT_PROJECTION_PATH):
        self.event_path = Path(event_path)
        self.projection_path = Path(projection_path)
        self.event_path.parent.mkdir(parents=True, exist_ok=True)     # line 108
        self._plans = {}
        self._load_or_rebuild()

    def _load_or_rebuild(self) -> None:
        if self.projection_path.exists():
            try:
                data = json.loads(self.projection_path.read_text())
                plans = data.get("plans") or {}
                if isinstance(plans, dict):
                    self._plans = plans
                    return                                            # line 119 — early return, NO write
            except Exception:
                pass
        self.rebuild_projection()                                     # line 122 — this DOES write
```
[CODE] `rebuild_projection()` (`:124-139`) ends in `self._write_projection()` (`:141-149`), which
performs a real `tmp.write_text(...)` + `os.replace(...)`.

**So the constructor has a conditional write.** It writes `cio_plans_projection.json` **only if**
that file is missing or does not parse into a dict under key `plans`. This was verified as
non-triggering under both roots *before* running anything:

[VERIFIED]
```
=== /home/johnclaw/trade-ai-releases/persistent-state
  projection parses: True plan_count 1092 updated_ts 2026-09-01T03:12:02.041131+00:00
=== /home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546
  projection parses: True plan_count 1092 updated_ts 2026-09-01T03:12:02.041131+00:00
=== /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
  projection parses: True plan_count 620 updated_ts 2026-08-30T01:32:18.762218+00:00
```
Both projections exist and parse, so `_load_or_rebuild` takes the line-119 early return and writes
nothing. Line 108's `mkdir(parents=True, exist_ok=True)` is a no-op where `data/cio` already exists,
which it does under both roots.

**Recorded as an ops hazard even though it did not fire here:** running this "dry" tool from a root
whose `cio_plans_projection.json` is absent or corrupt **will write a 14 MB projection file** as a
side effect of a dry run. That is why the run below was not attempted from this audit worktree,
which has a `data/cio` directory but no plan store in it — the dry run there would have *created*
one.

**Conclusion: the dry path is confirmed non-writing under the roots used.** Proceeding.

## 4. The dry runs — full commands, full output

### 4a. From the served release (the root the cron uses)

Root chosen: `/home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546`
— the concrete directory that `CURRENT` resolved to at audit time, pinned rather than the symlink
because the symlink has rotated repeatedly. **Why this root:** `CIOPlanStore` genuinely *is*
cwd-relative — [CODE] `scripts/lib/cio_plans.py:20-21`:
```
DEFAULT_EVENT_PATH      = Path("data/cio/cio_plans.jsonl")
DEFAULT_PROJECTION_PATH = Path("data/cio/cio_plans_projection.json")
```
Bare relative `Path`s, resolved against the process working directory. The crontab's own warning is
correct for this tool:
> `# cwd MUST be the served release: CIOPlanStore uses a RELATIVE path`
> `# (data/cio/cio_plans.jsonl), so it follows the working directory, NOT`
> `# TRADEAI_ROOT. Running it from $PROJ sweeps the dev book and leaves the served`
> `# one untouched -- that mistake was made on 2026-08-30.`

Command, verbatim (the cron line with `--apply` replaced by `--json`):
```
$ cd /home/johnclaw/trade-ai-releases/portfolio-server/d276657b7-main-exact-phase2-20260831-225546 \
  && TRADEAI_ROOT=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT \
     /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python \
     scripts/cio_draft_plan_hygiene.py --json
```
Output (head; the tool caps its own `samples` array at 8 — [CODE]
`cio_draft_plan_hygiene.py:111` `for p in candidates[:8]`):
```
{
  "schema": "DraftPlanHygiene@v1",
  "authority": "READ_ONLY_ADVISORY",
  "apply": false,
  "would_expire": 43,
  "expired": 0,
  "samples": [
    { "plan_id": "plan_8863ceebeb2b", "situation_type": "S3_REENTRY_CANDIDATE", "symbols": ["NEE"],   "revisit_at": "2026-08-31T11:01:29.978515+00:00" },
    { "plan_id": "plan_4c3f9ba3ce00", "situation_type": "S3_REENTRY_CANDIDATE", "symbols": ["IRDM"],  "revisit_at": "2026-08-31T11:20:44.780653+00:00" },
    { "plan_id": "plan_ac308a48f8ee", "situation_type": "S3_REENTRY_CANDIDATE", "symbols": ["FSPTX"], "revisit_at": "2026-08-31T13:44:33.838216+00:00" },
    { "plan_id": "plan_2713d66269e5", "situation_type": "S3_REENTRY_CANDIDATE", "symbols": ["GWH"],   "revisit_at": "2026-08-31T13:44:49.622588+00:00" },
    { "plan_id": "plan_53543f088b67", "situation_type": "S3_REENTRY_CANDIDATE", "symbols": ["DHX"],   "revisit_at": "2026-08-31T13:46:44.655442+00:00" },
    { "plan_id": "plan_fba512cc7f93", "situation_type": "S3_REENTRY_CANDIDATE", "symbols": ["DIVI"],  "revisit_at": "2026-08-31T13:57:30.004514+00:00" },
    { "plan_id": "plan_6bba1c2eea43", "situation_type": "S3_REENTRY_CANDIDATE", "symbols": ["KTOS"],  "revisit_at": "2026-08-31T14:04:07.903744+00:00" },
    ...
  ]
}
EXIT=0
```
`would_expire=43`, `expired=0`, `apply=false`. Per AGENTS.md §0 rule 8, `EXIT=0` is recorded but is
**not** the evidence — §5 is.

### 4b. From the main checkout `$PROJ` — the root trap, demonstrated

Command, verbatim:
```
$ cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild \
  && ./.venv/bin/python scripts/cio_draft_plan_hygiene.py
```
Output, complete:
```
would_expire=0 expired=0 apply=False
```

### 4c. The diff

| root (cwd) | plans in book | `would_expire` |
|---|---|---|
| `.../portfolio-server/d276657b7-…` (served; `data/cio` → persistent-state) | 1,092 | **43** |
| `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` (`$PROJ`) | 620 | **0** |

**The store-root trap is real and is reproduced here.** The same command, same code, same minute,
different working directory: 43 versus 0. Two entirely different books —
`cio_plans.jsonl` is 29,897,167 bytes / sha `829c095d…` under the served root and 16,044,198 bytes
/ sha `f21c5e15…` under `$PROJ`, last written 2026-08-31T23:12 and 2026-08-29T21:32 respectively.
An operator reading `would_expire=0` from `$PROJ` would conclude the served book is clean. It is
not; it has 43 eligible drafts.

**Both copies are reported. Neither is chosen and nothing was merged** (AGENTS.md §0 rule 5).

## 5. Inverse proof: nothing was written

Two independent proofs, because a hash comparison alone is fragile against a live system.

### 5a. sha256 + mtime, before and after (served / persistent-state root)

BEFORE — captured 2026-08-31T23:17:04-04:00:
```
data/cio/cio_plans.jsonl            size=29897167  mtime=2026-08-31 23:12:02.040906715 -0400
  829c095dfb9a151256d1949fc4cfb6d5bdcad817565045849c64bc74a7d9ed5f
data/cio/cio_plans_projection.json  size=14097059  mtime=2026-08-31 23:12:02.087910049 -0400
  a77907a56d47aa7ded56f5f26a71e39e3a72655acb86eb90b1377f21c72e72bf
data/cio/outcome_checkpoints.jsonl  size=2200922   mtime=2026-08-31 23:03:23.819146940 -0400
  48f60c88a3eac254b7aff97d18273f1214f0296fbde8f6589ede7d7492d50299
hygiene_actor_events_before=854
cancelled_status_changed_before=427
```
AFTER — captured 2026-08-31T23:17:18-04:00, after the §4a run:
```
data/cio/cio_plans.jsonl            size=29897167  mtime=2026-08-31 23:12:02.040906715 -0400
  829c095dfb9a151256d1949fc4cfb6d5bdcad817565045849c64bc74a7d9ed5f
data/cio/cio_plans_projection.json  size=14097059  mtime=2026-08-31 23:12:02.087910049 -0400
  a77907a56d47aa7ded56f5f26a71e39e3a72655acb86eb90b1377f21c72e72bf
data/cio/outcome_checkpoints.jsonl  size=2200922   mtime=2026-08-31 23:03:23.819146940 -0400
  48f60c88a3eac254b7aff97d18273f1214f0296fbde8f6589ede7d7492d50299
hygiene_actor_events_after=854
cancelled_status_changed_after=427
```
**Identical: all three sha256s, all three sizes, all three mtimes to the nanosecond.**

### 5b. Semantic proof, robust to concurrent writers

A hash match can be luck on a live box. The stronger proof is that the *specific events this tool
would have written* did not appear. [CODE] `cio_draft_plan_hygiene.py` writes only through
`store.update_plan(..., status="cancelled", status_reason="draft_hygiene_revisit_overdue",
actor_id="cio_draft_plan_hygiene")` — every write it can make is tagged with that actor and reason.

| marker in `cio_plans.jsonl` | before | after |
|---|---|---|
| lines containing `cio_draft_plan_hygiene` | **854** | **854** |
| lines containing `draft_hygiene_revisit_overdue` | **427** | **427** |

Zero new hygiene events. If `--apply` had run, 43 plans × the `update_plan` event pair would have
appeared here.

### 5c. Same proof for `$PROJ` (§4b run)

```
BEFORE  cio_plans.jsonl            16044198  2026-08-29 21:32:18.761843891  f21c5e1575d20c9a0c95b6d6db160ab1a82598954ec65955c5c82c18ffa42524
BEFORE  cio_plans_projection.json   8113375  2026-08-29 21:32:18.790692841  03251cfdadc751abd8eb4ed040feaa33c78ab4898d616b50bfa6110241fd916a
AFTER   cio_plans.jsonl            16044198  2026-08-29 21:32:18.761843891  f21c5e1575d20c9a0c95b6d6db160ab1a82598954ec65955c5c82c18ffa42524
AFTER   cio_plans_projection.json   8113375  2026-08-29 21:32:18.790692841  03251cfdadc751abd8eb4ed040feaa33c78ab4898d616b50bfa6110241fd916a
```
Identical. Notably the projection mtime did **not** advance, which independently confirms the
line-119 early return of §3c: the constructor did not rebuild.

## 6. What it WOULD expire — all 43, itemised, with the criterion each tripped

The tool prints only 8 samples. The full list below was derived **read-only** by applying the
tool's own predicate (`is_stale_empty_draft`, `cio_draft_plan_hygiene.py:41-56`) directly to
`cio_plans_projection.json` — a file read, no store instantiation, no import of the writing module.

Criterion, from source. A plan is eligible when **all** hold ([CODE] `:41-56`):
`status == "draft"` · `hermes_result_id` falsy (no research attached) · `situation_type` not in
`{S5_CASH_DEPLOYMENT, S6_CONCENTRATION_OR_DISPOSITION}` · not (`material is True` and
`situation_type` starts `S5`/`S6`) · `revisit_at` parses · **`revisit_at < now`**.

The single trip-wire that fires for all 43 is the last one: `revisit_at` in the past.

```
as_of 2026-09-01T03:17:30.787238+00:00   projection plan_count 1092   WOULD_EXPIRE 43

plan_id                situation_type            symbols   revisit_at (UTC)                    overdue
plan_8863ceebeb2b      S3_REENTRY_CANDIDATE      NEE       2026-08-31T11:01:29.978515+00:00     16.27h
plan_4c3f9ba3ce00      S3_REENTRY_CANDIDATE      IRDM      2026-08-31T11:20:44.780653+00:00     15.95h
plan_ac308a48f8ee      S3_REENTRY_CANDIDATE      FSPTX     2026-08-31T13:44:33.838216+00:00     13.55h
plan_2713d66269e5      S3_REENTRY_CANDIDATE      GWH       2026-08-31T13:44:49.622588+00:00     13.54h
plan_53543f088b67      S3_REENTRY_CANDIDATE      DHX       2026-08-31T13:46:44.655442+00:00     13.51h
plan_fba512cc7f93      S3_REENTRY_CANDIDATE      DIVI      2026-08-31T13:57:30.004514+00:00     13.33h
plan_6bba1c2eea43      S3_REENTRY_CANDIDATE      KTOS      2026-08-31T14:04:07.903744+00:00     13.22h
plan_f064d70ddc22      S3_REENTRY_CANDIDATE      ARKQ      2026-08-31T14:48:51.480144+00:00     12.48h
plan_d35a8435ff75      S3_REENTRY_CANDIDATE      WLDS      2026-08-31T17:20:20.463381+00:00      9.95h
plan_d1596ed90f2e      S3_REENTRY_CANDIDATE      AMC       2026-08-31T18:50:38.461590+00:00      8.45h
plan_5352dc0a2141      S3_REENTRY_CANDIDATE      AUUD      2026-08-31T20:01:39.826329+00:00      7.26h
plan_7e903b1a04d7      S3_REENTRY_CANDIDATE      PEPG      2026-08-31T20:08:20.459092+00:00      7.15h
plan_edd50fc2eda5      S3_REENTRY_CANDIDATE      BJDX      2026-08-31T20:10:27.082074+00:00      7.12h
plan_c729b3583833      S3_REENTRY_CANDIDATE      SHPH      2026-08-31T20:10:28.406545+00:00      7.12h
plan_e07ee66c90a7      S3_REENTRY_CANDIDATE      ACHV      2026-08-31T20:17:10.753829+00:00      7.01h
plan_9d82dcb65c8b      S3_REENTRY_CANDIDATE      FCNTX     2026-08-31T20:17:16.394363+00:00      7.00h
plan_3bd73ea93974      S3_REENTRY_CANDIDATE      GXAI      2026-08-31T20:17:17.708794+00:00      7.00h
plan_e047e165d514      S3_REENTRY_CANDIDATE      LMT       2026-08-31T20:21:15.577604+00:00      6.94h
plan_784a71c461c1      S3_REENTRY_CANDIDATE      MOGU      2026-08-31T20:23:38.818842+00:00      6.90h
plan_170883e6c7b4      S3_REENTRY_CANDIDATE      RGNT      2026-08-31T20:23:39.973804+00:00      6.90h
plan_41f08abdf312      S3_REENTRY_CANDIDATE      SPRC      2026-08-31T20:23:40.975988+00:00      6.90h
plan_e9df7980affa      S3_REENTRY_CANDIDATE      VIVS      2026-08-31T20:23:42.026203+00:00      6.90h
plan_dcc694263932      S3_REENTRY_CANDIDATE      CACI      2026-08-31T21:41:38.487677+00:00      5.60h
plan_ade1a281c8c2      S3_REENTRY_CANDIDATE      AXTI      2026-08-31T21:56:38.301210+00:00      5.35h
plan_d98c2d9740f3      S3_REENTRY_CANDIDATE      GCTS      2026-08-31T22:09:58.802600+00:00      5.13h
plan_41cb44dffb55      S3_REENTRY_CANDIDATE      AIRE      2026-08-31T22:31:40.716030+00:00      4.76h
plan_115a0f6d0e22      S3_REENTRY_CANDIDATE      IBIO      2026-08-31T22:33:39.532912+00:00      4.73h
plan_4bbfd17a96ff      S3_REENTRY_CANDIDATE      NEE       2026-08-31T23:03:38.226980+00:00      4.23h
plan_05af4e73ba62      S3_REENTRY_CANDIDATE      ADBE      2026-08-31T23:21:10.583857+00:00      3.94h
plan_9ba93bb78f47      S3_REENTRY_CANDIDATE      IRDM      2026-08-31T23:21:16.241132+00:00      3.94h
plan_80ba9d0534cc      S3_REENTRY_CANDIDATE      LASE      2026-09-01T01:38:38.133415+00:00      1.65h
plan_69895b4a18e1      S3_REENTRY_CANDIDATE      FSPTX     2026-09-01T01:45:21.891150+00:00      1.54h
plan_42385e9208ac      S3_REENTRY_CANDIDATE      GWH       2026-09-01T01:45:23.303530+00:00      1.54h
plan_97e7fe7aaf26      S3_REENTRY_CANDIDATE      ALXO      2026-09-01T01:47:33.718330+00:00      1.50h
plan_0fad4a1dbbee      S3_REENTRY_CANDIDATE      DHX       2026-09-01T01:47:34.924329+00:00      1.50h
plan_6f8341038319      S3_REENTRY_CANDIDATE      ELAB      2026-09-01T01:47:35.970351+00:00      1.50h
plan_42706345ed93      S3_REENTRY_CANDIDATE      KBR       2026-09-01T01:47:37.190333+00:00      1.50h
plan_2b435ca426f7      S3_REENTRY_CANDIDATE      CSCO      2026-09-01T01:58:38.869346+00:00      1.31h
plan_555a41c9e2da      S3_REENTRY_CANDIDATE      DIVI      2026-09-01T01:58:39.969808+00:00      1.31h
plan_1b7ed78f35e7      S3_REENTRY_CANDIDATE      SLNH      2026-09-01T02:00:41.826818+00:00      1.28h
plan_99a44288e719      S3_REENTRY_CANDIDATE      KTOS      2026-09-01T02:05:19.048037+00:00      1.20h
plan_22f89165bff8      S3_REENTRY_CANDIDATE      NUAI      2026-09-01T02:22:20.872732+00:00      0.92h
plan_2c1676977c89      S3_REENTRY_CANDIDATE      ARKQ      2026-09-01T02:49:26.245594+00:00      0.47h
```

Observations on the list, offered as observations only:

* **All 43 are `S3_REENTRY_CANDIDATE`.** Not one is S1, S5, S6 or any other situation type. The
  protections in `PROTECTED_SITUATIONS` are not what is doing the filtering — S3 is simply the only
  situation currently generating empty, unresearched, short-horizon drafts at volume.
* **The youngest is 0.47 hours overdue.** The cron comment describes this as *"draft plans whose
  24h revisit horizon lapsed"*, but the code criterion is plain `revisit_at < now`
  (`cio_draft_plan_hygiene.py:52-56`) with no grace window. Any horizon length set at plan creation
  is honoured, and several of these carry roughly one-hour horizons. **Correction: the effective
  criterion is "past its own revisit_at", not "24h old".**
* **Repeats.** NEE, IRDM, FSPTX, GWH, DHX, DIVI, KTOS and ARKQ each appear twice — an earlier
  instance from 2026-08-31 daytime and a fresh one from overnight. The tool would cancel both.

## 7. The checkpoint-side expiry path (`OUTCOME_EXPIRED`)

For completeness, since the brief asked about checkpoints as well as plans.

[CODE] `scripts/resolve_due_checkpoints.py:369-379` — the parser:
```
    ap.add_argument("--apply", action="store_true",
                    help="write SCHEDULED resolutions (default: dry run)")
    ap.add_argument(
        "--apply-pending-data",
        action="store_true",
        help=(f"resolve obtainable / expire never-resolvable PENDING_DATA "
              f"(requires {PENDING_APPLY_ENV}=1; append-only)"),
    )
```
Dry is again the default, and the pending-data expiry is **double-gated**: [CODE] `:120-123`
`pending_apply_armed()` returns true only for `TRADEAI_PENDING_DATA_APPLY == "1"` exactly, and
`:236-247` downgrades `apply` to `False` with an `APPLY_REFUSED` receipt otherwise. Writes appear at
`:151`, `:165`, `:170-172`, `:262-264` and `:275-278` — every one inside `if apply:`.

Rather than run it, this section quotes its **own hourly durable artifact**, which is a stronger
tier of evidence than a fresh dry run (verification ladder tier 2 — a real scheduled execution):

[VERIFIED] `/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/logs/resolve_due_checkpoints.log`
(size 23,465, mtime 2026-08-31 22:20), last complete cycle:
```
── SCHEDULED due ──
due                    0
resolved               0
pending_data           0
not_price_resolvable   0
applied                True
── PENDING_DATA triage ──
as_of                  2026-09-01T02:20:01+00:00
root                   /home/johnclaw/trade-ai-releases/persistent-state
pending_total          6
future_dated           0
obtainable             0
stuck_waiting_data     6
never_resolvable       0
applied                False
resolved               0
expired                0
  pending reason:   6x  no_price_history_either_end
```
**`would_expire` for the checkpoint path is 0** (`never_resolvable 0`). Nothing is currently
eligible for `OUTCOME_EXPIRED`, which is consistent with that status having zero occurrences in the
store's entire history (census §2.3, F-1). The 6 pending rows are classified `stuck_waiting_data`,
not `never_resolvable`, so the expiry gate would decline them even if it were armed.

## 8. PIN encountered

One command was **denied by the environment's permission layer** and was **not retried, restructured,
or routed around** (AGENTS.md §0 rule 3, and the brief's standing pin):

```
$ cd .../d276657b7-... && .../.venv/bin/python scripts/resolve_due_checkpoints.py    # no flags = dry
→ Permission denied by the auto-mode classifier.
```
The command carried no write flag and §7 confirms from source that it would have been non-writing,
but the denial stands unchallenged. Consequence: the checkpoint-side figures in §7 come from the
hourly cron's own log rather than from a run made here. The mandated dry run for this document
(§4, `cio_draft_plan_hygiene.py`) executed successfully, so the deliverable is unaffected.

A second, related gap follows from the same rail: the direct `ticker_prices` query that would
distinguish "SCHD genuinely absent from the price table" from "connection unavailable on that run"
was likewise not run. That is recorded as UNKNOWN in census §3.3 and §10.1, not guessed at.

## 9. Observation for the operator — the 06:52 cron

**Stated as an observation. This document does not interfere with it, and nothing here was done to
alter its behaviour.**

[VERIFIED] crontab line 997, verbatim:
```
52 6 * * * cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && TRADEAI_ROOT=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT flock -n /tmp/cio_draft_hygiene.lock /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/cio_draft_plan_hygiene.py --apply >> /home/johnclaw/logs/cio_draft_hygiene.log 2>&1
```

**Will it fire before 08:00 ET? Yes.** Current time 2026-08-31T23:20 ET; next firing
**2026-09-01T06:52 ET**, about 7h32m away, and 68 minutes before 08:00 ET.

**What it would do.** Exactly the `--apply` branch of §3a: cancel each eligible draft with
`status="cancelled"`, `status_reason="draft_hygiene_revisit_overdue"`,
`actor_id="cio_draft_plan_hygiene"`. It appends events; it does **not** delete JSONL history
([CODE] module docstring, `cio_draft_plan_hygiene.py:1` *"Do not delete JSONL history"*; the module
contains no delete or truncate call). It sends no notification (`"notify": False`, `:114`).
S5/S6 and anything with `hermes_result_id` are protected (`:44-51`).

**How many.** At least the 43 listed in §6, and more — the served book minted 12 new eligible drafts
between 01:38 and 02:49 UTC tonight, so the S3 lane is actively producing. The count at 06:52 will
be higher than 43. Do not read 43 as a prediction.

**Precedent — it has run with `--apply` and it works.** [VERIFIED] the log's own mtime is
2026-08-31 06:52:14, and the served book records the events:
```
hygiene-actor events in cio_plans.jsonl: 854
first: 2026-08-28T15:32:57.605416+00:00
last:  2026-08-31T10:52:14.641991+00:00
by date: 2026-08-28: 534   2026-08-30: 196   2026-08-31: 124
```
The 2026-08-31 run cancelled 124 events' worth of drafts at 06:52:14 ET. This is a functioning,
proven job. Nothing in this audit touched it, and nothing in this audit recommends changing it —
that would be operator-only (AGENTS.md §0 rule 9).

## 10. Summary

| item | value |
|---|---|
| `--apply` / write flag passed | **never, to anything** |
| plans expired by this session | **0** |
| checkpoints expired by this session | **0** |
| `would_expire` (plans, served root, 2026-09-01T03:17:30Z) | **43** |
| `would_expire` (plans, `$PROJ` root, same minute) | **0** |
| `would_expire` (checkpoints → `OUTCOME_EXPIRED`, per hourly log 02:20Z) | **0** |
| target stores byte-identical before/after | **yes — 5 files, 5 sha256 matches, mtimes unchanged** |
| new hygiene-actor events written | **0** (854 before, 854 after) |
| PIN hit | 1 — permission denial on a no-flag dry run (§8); not routed around |
