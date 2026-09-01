Status:      ACTIVE
as_of:       2026-08-31T23:20:21-04:00 (America/New_York)
Measured at: served release git pin `d276657b721011ae126d234b6300c9225d651a3e` (`.../portfolio-server/d276657b7-main-exact-phase2-20260831-225546`, BUILD_STAMP stamped_at 2026-09-01T02:56:30Z); audit worktree `overnight/maturity-maceration-2026-09-01` @ `c0ae53cf1`
Canonical repo path: docs/audits/CIO_OUTCOME_EDGE_CENSUS_2026-09-01.md
Authority:   READ_ONLY_ADVISORY — observational census. No writes, no broker, no orders. MBI_BEHAVIOR = 0.
See also:    docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md, AGENTS.md §13.4 §15, docs/ops/CIO_OUTCOME_DRY_2026-09-01.md

# CIO OUTCOME EDGE — census of `OutcomeCheckpoint@v1`

## 0. Headline, and the finding that overturns the brief

The question this census was commissioned to answer was **"is the outcome edge dark?"**
The threshold set in advance: *has any checkpoint ever transitioned out of `SCHEDULED` into a
settled state, and is the writer that did it on a schedule?*

**Measured answer: NO, the edge is not dark. It settles, and it settled 197 rows today.**
[VERIFIED, §5]

| Measurement | Value | as_of | root read from |
|---|---|---|---|
| Checkpoint store lines | 1,527 | 2026-08-31T23:18:32-04:00 | `/home/johnclaw/trade-ai-releases/persistent-state` |
| Distinct `checkpoint_id` | 1,125 | same | same |
| `RESOLVED` (latest-by-id) | **158** | same | same |
| `OUTCOME_PENDING_DATA` (latest-by-id) | **6** | same | same |
| Pending rows whose pending data is a **named field** | **6 of 6** | same | same |
| Pending rows whose pending data is **UNKNOWN** | **0** | same | same |
| `SCHEDULED` with `due_at = null` (structurally never due) | **871** | same | same |
| Checkpoints carrying a real `plan_id` | **0 of 1,125** | same | same |
| Lesson candidates outcome-derived | **1 of 344** | 2026-08-31T12:54:23-04:00 | same |

Three claims in the commissioning brief and in the dated AS-IS reading did not survive
measurement. **When a finding contradicts the brief, the finding wins** (AGENTS.md §0 rule 10);
all three are recorded in §9 Corrections rather than silently corrected.

---

## 1. Where the store is, and the divergent copies

### 1.1 The path the running system actually uses

[CODE] `scripts/lib/cio_institutional_learning.py:551`
```
CHECKPOINT_PATH = "data/cio/outcome_checkpoints.jsonl"
```
[CODE] `scripts/resolve_due_checkpoints.py:74-76` — the resolver does **not** resolve this against
the working directory. It resolves it against a *declared* state root:
```
def _state_root() -> Path:
    from scripts.lib.canonical_store_registry import production_state_root
    return Path(production_state_root())
```
[CODE] `scripts/lib/canonical_store_registry.py:487-502` — `production_state_root()` prefers, in
order: `TRADEAI_STATE_ROOT` / `TRADEAI_ROOT` env, then `TRADEAI_PERSISTENT_STATE_ROOT`, then
`~/trade-ai-releases/persistent-state` **if it contains `PERSISTENT_STATE_ROOT.json`**, then
`~/trade-ai-releases/portfolio-server/CURRENT`, then the repo root.

[VERIFIED] `PERSISTENT_STATE_ROOT.json` exists, so branch 3 wins:
```
$ ls -la /home/johnclaw/trade-ai-releases/persistent-state/PERSISTENT_STATE_ROOT.json
-rw------- 1 johnclaw johnclaw 448 Aug 26 10:31 .../persistent-state/PERSISTENT_STATE_ROOT.json
```
[VERIFIED] and the hourly resolver's own log confirms the root it chose at runtime — the strongest
available evidence (verification ladder tier 2, a durable artifact of a real run):
```
$ tail -40 /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/logs/resolve_due_checkpoints.log
...
root                   /home/johnclaw/trade-ai-releases/persistent-state
```

[VERIFIED] The served release does not hold its own copy — `data/cio` is a symlink:
```
$ ls -ld .../d276657b7-main-exact-phase2-20260831-225546/data/cio
lrwxrwxrwx ... /data/cio -> /home/johnclaw/trade-ai-releases/persistent-state/data/cio
$ ls -ld .../d276657b7-.../data/runtime
lrwxrwxrwx ... /data/runtime -> /home/johnclaw/trade-ai-releases/persistent-state/data/runtime
```
**Correction to the brief (§9.1):** the store-root trap quoted from the crontab is real for
`CIOPlanStore` (verified in the companion ops doc) but **does not apply to
`outcome_checkpoints.jsonl`**, which is root-declared, not cwd-relative. Reading the served
release and reading persistent-state are literally the same inode.

### 1.2 Every copy on the box — reported, not chosen

[VERIFIED]
```
$ find /home/johnclaw -name 'outcome_checkpoints.jsonl' 2>/dev/null | while read p; do
    printf '%s ' "$(stat -c '%s %y' "$p")"; sha256sum "$p"; done
2200922 2026-08-31 23:03:23.819146940 -0400 48f60c88a3eac254b7aff97d18273f1214f0296fbde8f6589ede7d7492d50299  /home/johnclaw/trade-ai-releases/persistent-state/data/cio/outcome_checkpoints.jsonl
10134   2026-08-29 23:03:10.378578211 -0400 0c4183d212bbd14c2cf84e56c19cdaea71727727cf1ca244b504f4259fb4c1bf  /home/johnclaw/trade-ai-releases/portfolio-server/671d760f-main-exact-phase2-20260828-095246/.claude/worktrees/agent-a5706b0638fd53da8/data/cio/outcome_checkpoints.jsonl
10134   2026-08-29 22:59:23.038591487 -0400 3c91725a26ad12b2b2c414bedbde9601316433e451f4f3f7b9aa0027bcd4b62a  /home/johnclaw/trade-ai-releases/portfolio-server/671d760f-main-exact-phase2-20260828-095246/.claude/worktrees/agent-a4c6199b62b15551e/data/cio/outcome_checkpoints.jsonl
10134   2026-08-30 15:57:38.363109458 -0400 4568047e84a41ea936d60861d55a678a142ccde95c7f7cc8ec69567b5a90a720  /home/johnclaw/tradeai-wt-phase56/data/cio/outcome_checkpoints.jsonl
9738    2026-08-29 04:11:33.287543998 -0400 14a2b1aa52be9bd450d5d4764e616c91835be81671485ef9b0181d3d62c70165  /home/johnclaw/r20-r24-exact-main-deploy/data/cio/outcome_checkpoints.jsonl
137948  2026-08-26 10:14:37.596738699 -0400 2253d9afefcdc756aa5ba542ecdd6f4a62be306b9e2b6f09cfcb59f93900d9a6  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio/outcome_checkpoints.jsonl
```

Six copies. **Nothing here picks one and nothing merges them** (AGENTS.md §0 rule 5). What the
census *can* report without choosing is the id-set relationship between the two that matter:

[VERIFIED]
```
persistent-state distinct checkpoint_id: 1125
main-checkout   distinct checkpoint_id:  153
in both:                                 153
ONLY in main checkout:                     0
ONLY in persistent-state:                972
```
The main-checkout copy at `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` is a strict
subset — a stale prefix frozen at 2026-08-26 10:14, holding **no record that persistent-state does
not also hold**, and holding all 153 of them in `SCHEDULED` with no `resolved_at` anywhere. It is
stale, not forked. That is an observation for the operator; **the decision to reconcile or archive
it is operator-only** (AGENTS.md §0 rule 9, §17). The four ~10KB worktree copies are agent-worktree
seeds, not book state.

### 1.3 The store is live and growing — the census is pinned

[VERIFIED] Between two reads twelve minutes apart the store gained three records:

| read at | sha256 | lines |
|---|---|---|
| 2026-08-31T23:12 ET (mtime 23:03:23) | `48f60c88a3eac254b7aff97d18273f1214f0296fbde8f6589ede7d7492d50299` | 1,524 |
| 2026-08-31T23:20 ET (mtime 23:18:32) | `61a5844d9eb5ce1e79a72fd06c1f51d8229b928c6827e4c1c8f94f10ca7ba049` | 1,527 |

**Every count in §2 onward is measured against the pinned second read**, snapshotted byte-for-byte
before counting:
```
$ cp -p .../persistent-state/data/cio/outcome_checkpoints.jsonl $SCRATCH/cp_snapshot.jsonl
snapshot: size=2204594 mtime=2026-08-31 23:18:32.112575580 -0400
          61a5844d9eb5ce1e79a72fd06c1f51d8229b928c6827e4c1c8f94f10ca7ba049
lines=1527
```
This drift is itself the measurement in §9.3: a number quoted from this document will be wrong
within the hour. Regenerate, do not quote.

---

## 2. Status histogram — the full vocabulary actually present

The store is `APPEND_ONLY_EVIDENCE`; a resolution **appends a new version** of the row rather than
editing it ([CODE] `scripts/lib/outcome_resolution.py:200-217`, `resolution_row()` — *"The store is
append-only, so this supersedes rather than edits"*). Two histograms are therefore both true and
mean different things. Reporting only one would be a defect.

### 2.1 Raw lines (what is on disk) — n = 1,527

| status | count |
|---|---|
| `SCHEDULED` | 1,125 |
| `RESOLVED` | 158 |
| `OUTCOME_PENDING_DATA` | 158 |
| `NOT_PRICE_RESOLVABLE` | 86 |
| **TOTAL** | **1,527** |

### 2.2 Latest-by-id (the live state of each checkpoint) — n = 1,125

| status | count |
|---|---|
| `SCHEDULED` | 875 |
| `RESOLVED` | 158 |
| `NOT_PRICE_RESOLVABLE` | 86 |
| `OUTCOME_PENDING_DATA` | 6 |
| **TOTAL** | **1,125** |

[CODE] The fold is the system's own: `scripts/lib/outcome_resolution.py:87-99`,
`latest_checkpoints()` — *"Counting raw rows would re-resolve a checkpoint every run, because the
resolution itself appends a row."*

Every line carries `"schema": "OutcomeCheckpoint@v1"` — 1,527 of 1,527, no other schema value,
0 unparseable lines. [VERIFIED]

### 2.3 Status vocabulary the CODE defines, versus what the data has ever contained

[CODE] `scripts/lib/outcome_resolution.py:38-47`:
```
STATUS_SCHEDULED           = "SCHEDULED"
STATUS_RESOLVED            = "RESOLVED"
STATUS_PENDING_DATA        = "OUTCOME_PENDING_DATA"
STATUS_NOT_PRICE_RESOLVABLE = "NOT_PRICE_RESOLVABLE"
STATUS_EXPIRED             = "OUTCOME_EXPIRED"
```

| status | defined in code | ever present in data (any line, ever) |
|---|---|---|
| `SCHEDULED` | yes | yes |
| `RESOLVED` | yes | yes |
| `OUTCOME_PENDING_DATA` | yes | yes |
| `NOT_PRICE_RESOLVABLE` | yes | yes |
| **`OUTCOME_EXPIRED`** | **yes** (`outcome_resolution.py:47`) | **NO — zero occurrences** |

**FINDING F-1 — a defined terminal state that has never occurred.** `OUTCOME_EXPIRED` is the only
terminal state for a pending row that will never become a price comparison. [CODE]
`outcome_resolution.py:44-47`: *"Terminal for a PENDING_DATA row that will never become a price
comparison… so receipts show the row was pending, triaged, and explicitly expired."* It is written
at exactly one site, [CODE] `scripts/resolve_due_checkpoints.py:275-278`, and that site is behind
`--apply-pending-data` **plus** `TRADEAI_PENDING_DATA_APPLY=1` ([CODE]
`resolve_due_checkpoints.py:120-123`, `pending_apply_armed()`). No cron passes either (§5.3).
The state has never occurred because nothing has ever been permitted to write it — which is a
different and more benign fact than "the expiry logic is broken". It has also had nothing to do:
the never-resolvable count has been 0 every hour (§3.3).

**No status appears in the data that the code does not define.** [VERIFIED]

`r17_checkpoint_binding.py:270-279` additionally maps `{"BLOCKED_DATA", "OUTCOME_PENDING_DATA"}`
onto a derived display label `"BLOCKED_DATA"`. That is a *lifecycle-view* label, not a store status;
`BLOCKED_DATA` is never written to `outcome_checkpoints.jsonl` and never appears there. Recorded so
a later reader does not count it as a missing state.

---

## 3. The central question: PENDING_DATA → a named field, or UNKNOWN

### 3.1 The answer

There are **6** checkpoints in `OUTCOME_PENDING_DATA`. For **6 of 6** the pending datum is a named
field on a named store. **UNKNOWN = 0.**

Stating the question and the threshold before the value, as required: *for each pending checkpoint,
can the census name the field that would have to be populated for it to settle, and the producer
that would populate it — from source, not from inference?* Threshold: a `path:line` for the read, a
`path:line` for the write, and a scheduling fact. All six clear it.

### 3.2 The six rows

[VERIFIED] all six, latest-by-id, from the pinned snapshot:

| checkpoint_id | symbol | recommendation | due_at (UTC) | resolution_reason | plan_id |
|---|---|---|---|---|---|
| `d4500d07c2cdbd0b59a6` | SCHD | TRIM | 2026-08-31T01:53:28 | `no_price_history_for_comparison` | null |
| `83b0ec86a5dd77a8d196` | SCHD | TRIM | 2026-08-31T10:21:00 | `no_price_history_for_comparison` | null |
| `ca5dde3c45c51757ac79` | SCHD | TRIM | 2026-08-31T11:21:59 | `no_price_history_for_comparison` | null |
| `20680b08dfee0f22b450` | SCHD | TRIM | 2026-08-31T12:33:38 | `no_price_history_for_comparison` | null |
| `541554f1271866238b31` | SCHD | TRIM | 2026-08-31T13:44:17 | `no_price_history_for_comparison` | null |
| `9e8aafb0d0ff947550fc` | SCHD | TRIM | 2026-08-31T14:14:37 | `no_price_history_for_comparison` | null |

All six are the same subject: a **TRIM recommendation on SCHD**, four of them carrying
`lineage_id: "position:SCHD:CONCENTRATION"`. This is one unresolved question asked six times, not
six unrelated gaps.

### 3.3 The named-field table

The hourly resolver re-classifies every pending row on every run and prints the classification. Its
own output names the gap more precisely than the stored `resolution_reason` does:

[VERIFIED] `/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/logs/resolve_due_checkpoints.log`,
last two hourly runs:
```
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

| pending reason | named field (path:line) | producer that would fill it | producer exists? | scheduled? |
|---|---|---|---|---|
| `no_price_history_either_end` (6 rows) | `ticker_prices.close_price`, `ticker_prices.price_date` for `symbol='SCHD'` — read at `scripts/resolve_due_checkpoints.py:89-95` (`SELECT close_price, price_date FROM ticker_prices WHERE symbol = %s AND price_date <= %s ORDER BY price_date DESC LIMIT 1`); classified at `scripts/lib/outcome_resolution.py:247-262` (`_pending_data_gap` → returns `no_price_history_either_end` when *neither* end returns a row) | `scripts/price_db_sync.py` — writes `ticker_prices (symbol, price_date, close_price, source)` at `price_db_sync.py:250` and `:273`, UPSERT on conflict | **yes** | **yes** — crontab: `20 7 * * 1-5 cd $PROJ && $PY scripts/price_db_sync.py >> logs/price_db_sync.log 2>&1` (weekdays 07:20 ET) |
| — | **UNKNOWN** | — | — | **count: 0** |

[CODE] The read side, verbatim, `scripts/resolve_due_checkpoints.py:80-95`:
```
def _price_lookup_factory():
    """Close on or before a date, from ticker_prices. None when absent."""
    try:
        from price_db_sync import _get_conn
        conn = _get_conn()
    except Exception:
        return lambda symbol, on_or_before: None
```
[CODE] `scripts/lib/outcome_resolution.py:255-260` — the classification that distinguishes *which*
end is missing:
```
    then = price_lookup(symbol, decided_at.date().isoformat())
    now_px = price_lookup(symbol, at.date().isoformat())
    if not then and not now_px:
        return "no_price_history_either_end"
```

**FINDING F-2 — the named field is named, but one degree of freedom behind it is not.**
`no_price_history_either_end` is produced when the lookup returns `None` for *both* the decision
date and the horizon date. [CODE] `resolve_due_checkpoints.py:84-86` shows that a failed database
connection degrades to `lambda symbol, on_or_before: None` — a lookup that returns `None` for
everything. So `no_price_history_either_end` has two possible causes that the receipt does not
distinguish:

  (a) `ticker_prices` genuinely holds no row for `SCHD`; or
  (b) the connection was unavailable on that run.

Evidence bearing on it, without resolving it: 152 other checkpoints resolved through this same
lookup with `pending_data_triage_prices_obtained` on 2026-08-29 (§5), so the connection is not
permanently down; and SCHD passes `price_resolvable()` (else it would be `NOT_PRICE_RESOLVABLE`,
not pending), so it is a registered security with a real symbol. [VERIFIED] SCHD is **not** in the
13-symbol watchlist under either root — and `price_db_sync`'s `market_quotes → ticker_prices` path
is watchlist-and-proposal scoped ([CODE] `price_db_sync.py:170-196`), which makes (a) plausible via
a coverage gap rather than a fault. **Which of (a) or (b) holds is UNKNOWN to this census**: the
direct `ticker_prices` query that would settle it was **not run** — see §7 PIN. It is stated here as
an open question rather than filled with a guess.

### 3.4 What actually populates a settled checkpoint

For completeness, the full settle path once the price is present. [CODE]
`scripts/lib/outcome_resolution.py:155-197` `realized_state()` builds
`{symbol, price_at_decision, price_at_horizon, change_pct, decision_price_date,
horizon_price_date, recommendation}` with `source_refs = ["ticker_prices:{symbol}:{date}", …]`;
[CODE] `scripts/lib/cio_institutional_learning.py:648-690` `process_due_checkpoint()` turns that
into an `OutcomeObservation@v1`; [CODE] `resolve_due_checkpoints.py:262-264` appends the
`RESOLVED` row carrying `outcome_id`. The guard is explicit and worth quoting because it is why
the pending count exists at all — [CODE] `outcome_resolution.py:14-18`:
> **Never invent a realized state.** If the price history cannot supply both ends of the
> comparison, the checkpoint is recorded as OUTCOME_PENDING_DATA. A fabricated outcome is worse
> than a missing one.

---

## 4. Age distribution

[VERIFIED] latest-by-id, n = 1,125, `now` = 2026-09-01T03:20:21+00:00:

| measurement | value |
|---|---|
| oldest `created_at` | 2026-08-26T01:53:28+00:00 (`dc03421119248250db87`) |
| newest `created_at` | 2026-09-01T03:18:32+00:00 (`39110c1325e5b277bb0b`) |
| older than 7 days | **0** |
| older than 30 days | **0** |
| older than 90 days | **0** |
| rows with **no `created_at` at all — age UNKNOWN** | **18** |

**FINDING F-3 — nothing in this store is older than six days, and 18 rows cannot be dated at all.**
The 18 undated rows are not scattered: they occupy line indexes 0, 2, 3, 4, 7, 10, 11, 13, 14, 15,
184–188 and 985–987, and **all 18 carry the same `runtime_source_sha`,
`55520666b4a742b9ed893c3231b414d089312363`** — an older writer that predates the `created_at`
field. Their statuses are 10 `SCHEDULED` / 8 `NOT_PRICE_RESOLVABLE`.

Their age is **UNKNOWN and is recorded as UNKNOWN.** File position in an append-only store implies
write order, which would place them before 2026-08-26 — but position is not a timestamp, and this
census will not convert an ordering into a date. Do not read "0 older than 7 days" as "the outcome
edge has no backlog": read it as "the store as it exists today begins on 2026-08-26, and 18 rows
predate its dating convention".

---

## 5. Is the outcome edge dark? — the test, and the answer

### 5.1 The claim under test

[DOC-CLAIM] `docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md:141-149`, verbatim:
```
                  ▓ OutcomeCheckpoint@v1
                    ~791 checkpoints exist
                    only a handful RESOLVED
                    a large block sits OUTCOME_PENDING_DATA
                    — nobody has asked what data is pending
                               │
                               ▼
                          ✗ OUTCOME
                            the edge is dark
```
[DOC-CLAIM] `AGENTS.md` §13.4 Dark contracts: *"`OUTCOME` edge — checkpoints exist; settlement is
dark. Lessons on disk today are research-derived. Do not call them scored."*

### 5.2 The measurement — settlement has happened, repeatedly, and today

[VERIFIED] Status *transition sequences* per checkpoint, folded from the append-only store:

| transition sequence | count |
|---|---|
| `SCHEDULED` (never moved) | 872 |
| `SCHEDULED` → `OUTCOME_PENDING_DATA` → **`RESOLVED`** | **152** |
| `SCHEDULED` → `NOT_PRICE_RESOLVABLE` | 86 |
| `SCHEDULED` → **`RESOLVED`** | **6** |
| `SCHEDULED` → `OUTCOME_PENDING_DATA` (still pending) | 6 |

[VERIFIED] `resolved_at` on the 402 lines that carry one:
```
n= 402  min= 2026-08-27T20:14:04+00:00  max= 2026-08-31T14:20:02+00:00
  2026-08-27   50
  2026-08-29  152
  2026-08-30    3
  2026-08-31  197
```
158 of the 158 `RESOLVED` rows carry a non-null `outcome_id` (157 distinct; one id,
`4ada99f5b93fcb1d4428ab42`, is shared by two checkpoints). [VERIFIED]

### 5.3 The writer, and whether it is scheduled

Writer: `scripts/resolve_due_checkpoints.py`. [VERIFIED] it is in the crontab, hourly, with
`--apply`, running from the served release with the main-checkout venv:
```
$ crontab -l | sed -n '964p'
20 * * * * cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/resolve_due_checkpoints.py --apply >> logs/resolve_due_checkpoints.log 2>&1
```
The surrounding crontab comment records why, and is worth preserving:
```
# ── The 2026-08-27 loop-closure work was itself dark: shipped, run once by hand,
# never scheduled. Without these lines everything from PR #560-#563 reverts to
# inert. Documented in docs/audits/LIFECYCLE_CLOSURE_GROUNDTRUTH_2026-08-27.md §1.
```
[CODE] the script declares the same fact in source, `scripts/resolve_due_checkpoints.py:34-36`:
```
SCHEDULED_ENTRYPOINT = (
    'cron: 20 * * * * -- hourly, --apply (wired 2026-08-27, Phase 2)'
)
```
[VERIFIED] and the log proves the run, not merely the schedule — durable artifact, hourly, most
recent entries at 01:20 and 02:20 UTC on 2026-09-01 with `applied  True` on the SCHEDULED pass.

Note what the cron does **and does not** arm: `--apply` covers only the `SCHEDULED`-due pass.
The PENDING_DATA triage runs on every invocation but is dry unless `--apply-pending-data` **and**
`TRADEAI_PENDING_DATA_APPLY=1` are both supplied ([CODE] `resolve_due_checkpoints.py:120-123`,
`:236-247` `APPLY_REFUSED`), and no cron supplies either. That is why every hourly log line reads
`applied False / resolved 0 / expired 0` under the triage heading while the SCHEDULED heading reads
`applied True`.

### 5.4 The verdict, stated loudly

**The AS-IS document's `✗ OUTCOME — the edge is dark` is FALSE as of 2026-08-31, and
`AGENTS.md` §13.4's "settlement is dark" is FALSE as of the same date.** The finding wins
(AGENTS.md §0 rule 10). Settlement is:

* **implemented** — `scripts/lib/outcome_resolution.py`, 398 lines, with an explicit
  never-invent-an-outcome guard;
* **scheduled** — hourly `--apply`, wired 2026-08-27;
* **running** — 402 resolution rows written across four distinct days, the most recent at
  2026-08-31T14:20:02Z;
* **producing linked outcomes** — 157 distinct `outcome_id`s, all resolvable into
  `data/cio/outcome_observations.jsonl`.

An amendment to `AGENTS.md` §13.4 is warranted (AGENTS.md §0 rule 10 / §20). This census does not
make it: proposing is in scope, editing `AGENTS.md` is not.

### 5.5 What the "dark" reading was probably seeing — and the real dark mass

The AS-IS reading was not wrong about there being a hole. It named the wrong hole.

**FINDING F-4 — 871 of 875 `SCHEDULED` checkpoints have `due_at = null` and can never become due.**

[VERIFIED] latest-by-id:
```
with due_at:  254      null due_at:  871
SCHEDULED total: 875
  with due_at:                                4
  due_at null (can never become due):       871
  due_at in past:                             0
```
[CODE] `scripts/lib/cio_institutional_learning.py:585-612` — `schedule_outcome_checkpoint()`, the
factory, sets `"due_at": None` **unconditionally** (line 606). Nothing in that function accepts or
derives a horizon date.
[CODE] `scripts/lib/outcome_resolution.py:101-117` — `due_checkpoints()` is the selector the hourly
resolver runs, and it is explicit:
> *"A checkpoint with no `due_at` is not due — it is unscheduled. Treating a missing deadline as
> 'now' would resolve the entire backlog on first run."*

So 871 checkpoints sit permanently outside the resolver's selection set. They are not pending, not
stuck, not expired, and not counted by any triage — they are invisible to the loop. The only writer
that populates `due_at` is [CODE] `scripts/lib/r17_checkpoint_binding.py:137,165`
(`due_at_for(horizon, now=now)`), and it accounts for the 254 rows that have one.

**This, not `OUTCOME_PENDING_DATA`, is the outcome edge's dark mass: 871 rows, 77% of the store.**
The pending block the AS-IS doc called "large" is now 6.

---

## 6. The lessons cross-check

### 6.1 There are two lesson stores, and the "337" refers to the CIO one

[VERIFIED] `data/cio/lesson_candidates.jsonl` under the served/persistent root:
```
sha256 15f5b6f9fe229baafabda7c5c433544aeff73081914ed067d16b9446cc0b026e
size 317611  mtime 2026-08-31 12:54:23 -0400   lines 345   distinct lesson_id 344
```
This is the store the AS-IS doc counted as 337 ([DOC-CLAIM] line 65: *"lessons[] 337 candidates —
ALL research-fed"*; line 153: *"▓ from research ← 337 lessons"*). Regenerated today it is **344**,
not 337. This is a *single copy* — [VERIFIED] `find /home/johnclaw -name 'lesson_candidates.jsonl'`
returns exactly one path. No divergence.

The second store, `data/runtime/advisory_kb_lessons.jsonl`, is the advisory desk's KB and is a
different lane. It **does** have divergent copies:

| root | size | mtime | sha256 | lines | distinct id |
|---|---|---|---|---|---|
| `…/persistent-state` | 149,885,406 | 2026-08-26 21:40 | `e6b454d58df33b5b1892d3546d6952a9d1b06d526b7ccb05b66c35c4bcc58262` | 1,617 | 12 |
| `…/trade-ai-v12-rebuild/trade-ai-v12-rebuild` | 154,982,062 | 2026-08-27 09:17 | `d057e6df388a922654c2af7001651f921c153113de20fee4aa91ee05222d3f89` | 1,672 | 12 |

Reported, not reconciled (AGENTS.md §0 rule 5). Only **12** distinct KB lessons exist behind 1,617
append rows; all 12 are `status: ratified`, sourced `reflection_ips` (9), `reflection_thrash` (2),
`reflection_feedback` (1) — reflection-derived, zero `outcome_id` or `checkpoint_id` on any of them.

### 6.2 Provenance classification of the 344 CIO lesson candidates

[VERIFIED] latest-by-id, n = 344, all `LessonCandidate@v2`, all `status: PROVISIONAL`:

| classification | basis | count |
|---|---|---|
| **research-derived** | carries `hermes_result_id` + `supporting_case_summary_ids`, `task_class: CASE_SUMMARY_CONTEXT` | **343** |
| **outcome-derived** | carries `correlated_outcome_ids` / `counterexamples` referencing real `outcome_id`s | **1** |
| **UNKNOWN** | — | **0** |

An explicit `lesson_provenance` field exists on only 8 of 344 rows — 7 `RESEARCH_DERIVED`, 1
`OUTCOME_DERIVED`. The classification above therefore does **not** rest on that field; it rests on
which id-bearing arrays are populated, which is checkable on every row. Where the explicit field is
present it agrees with the structural classification in 8 of 8 cases.

### 6.3 The one outcome-derived lesson — and why it matters

[VERIFIED] the full record:
```json
{
  "lesson_id": "e38856b4febcafbf8b25",
  "amends_lesson_id": "e38856b4febcafbf8b25",
  "provenance_amendment": true,
  "lesson_provenance": "OUTCOME_DERIVED",
  "schema": "LessonCandidate@v2",
  "scope": "SCHD",
  "task_class": "TRIM",
  "statement": "TRIM on SCHD did not hold: the subsequent move averaged 0.314% over the observed horizon, across 1 independent observation(s).",
  "correlated_outcome_ids": ["660c641b5305887d161eed82","4ada99f5b93fcb1d4428ab42","21ddc126c54ff18405cb5034","c5a0c6efaccd3ce9565bbc10"],
  "counterexamples": ["cc06af712aff1dc88af18b7e"],
  "counterexample_search": true,
  "independent_samples": 1,
  "total_observations": 5,
  "sample_size": 0,
  "confidence": 0.5,
  "limitations": "one outcome is not methodology",
  "status": "PROVISIONAL",
  "policy_effect": false,
  "methodology_effect": false,
  "memory_behavior_influence": 0,
  "observational_only": true
}
```
[VERIFIED] all 5 referenced `outcome_id`s resolve into
`data/cio/outcome_observations.jsonl` (782 distinct `outcome_id` there); **0 dangling**. Four of the
five appear in the `RESOLVED` checkpoint rows counted in §5.

**FINDING F-5 — the outcome → lesson edge has fired. Once.** The AS-IS doc's *"ALL research-fed"*
and *"✗ from outcome"* are false by exactly one record. That is a small number and this document
will not inflate it: 343 of 344 remain research-derived, the single outcome-derived lesson rests on
**one** independent observation and says so in its own `limitations` field, and it is
`PROVISIONAL` with `policy_effect: false`. But "the edge has never fired" and "the edge has fired
once, correctly, with its own sample-size caveat attached" are different system states, and the
architecture diagram asserts the first.

### 6.4 Does anything call research-derived lessons "scored"?

Question and threshold stated first: *does any code path or operator surface apply the word
"scored", or a score-like assertion of outcome performance, to a lesson whose provenance is
research?*

[VERIFIED, negative] The only hits are not violations:

* `scripts/lib/advisory/kb_lessons.py:305-323` — `scored` is a **local variable** holding
  `(relevance, lesson)` tuples for retrieval ranking, then discarded (`return [l for _, l in
  scored[:limit]]`). A retrieval-relevance sort, not an outcome score. Not surfaced.
* `scripts/report_operator_page_map.py:30` — `"alert_categories": ["outcome_scored",
  "lesson_generated"]` lists these as **two separate categories**, which is the correct distinction,
  not a conflation.

The 343 research-derived candidates carry `promotion_stage: REVIEW_READY` and
`cannot_become_policy: true` (343 of 343) — the store labels them as *not yet load-bearing* rather
than as scored. **No violation of AGENTS.md §13.4's "do not call them scored" was found.** The
guard is holding.

One nuance the operator should see: the single outcome-derived lesson's `statement` — *"TRIM on
SCHD did not hold"* — **is** a performance assertion, and it is legitimate, because that lesson is
outcome-derived and cites its observations. The §13.4 prohibition is about the other 343.

---

## 7. `plan_id` binding

Question and threshold: *how many checkpoints carry a real `plan_id`, how many a `plan_binding`
reason, how many neither?*

[VERIFIED] latest-by-id, n = 1,125:

| binding | count |
|---|---|
| real (non-null) `plan_id` | **0** |
| `plan_binding: "unbound"` with `plan_id: null` (both fields present) | 564 |
| neither field present | 561 |

**FINDING F-6 — not one checkpoint in the store is bound to a plan.** Zero. The 564 that were
written after the Wave 3B change at least *declare* their unboundedness; the 561 older rows do not
carry the field at all.

[CODE] `scripts/lib/cio_institutional_learning.py:585-596` explains the design intent — the field
is mandatory on new writes so the `complete → checkpoint` rate becomes computable, and a null value
is legal when `plan_binding` says why; [CODE] `:615-637` `persist_checkpoint()` rejects a write
missing the *field* (`"rejected": "missing_plan_id_field"`) but accepts a null *value*. So 564
unbound rows are the system working as designed, not a fault.

**Correction to the brief (§9.4):** the brief states *"A checkpoint bound to nothing cannot
settle."* Measured, that is false. All 158 `RESOLVED` checkpoints have `plan_id: null` and no
`plan_binding` field, and they settled anyway — because settlement keys on `decision_id` plus
`original_decision_state.symbol`, never on `plan_id` ([CODE] `outcome_resolution.py:120-129`
`checkpoint_symbol()`, `:155-197` `realized_state()`). `plan_id` is what makes the *lineage
completion rate* computable; it is not an input to settlement. The consequence of 0 bound
checkpoints is that **`complete → checkpoint` remains UNCOMPUTABLE**, which is exactly what the
`checkpoint_lineage_health` docstring at `cio_institutional_learning.py:617-624` predicts — not that
settlement is blocked.

---

## 8. Supporting inventory

[VERIFIED] `data/cio/outcome_observations.jsonl` (persistent-state root):
```
sha256 0bf653c2af20621c47fdf70c27f5a4833d5295c491c640e2be8237cd2ed81ae4
size 854018  mtime 2026-08-31 17:10:02 -0400   lines 782   distinct outcome_id 782
```
Note the asymmetry, stated without explanation because none was measured: 782 observations exist,
but only 157 distinct `outcome_id`s are referenced from `RESOLVED` checkpoints. The remaining ~625
observations were written by other producers — the first record carries
`"source_refs": ["cio_outcomes.jsonl"]` and `decision_id: "act-830c7ee8"`, an action-ledger id, not
a checkpoint decision id. **Whether those constitute a second, parallel outcome lane is outside
this census's scope and is UNKNOWN here.**

[VERIFIED] `horizon` distribution, latest-by-id: `event-relative` 870, `1_session` 202,
`5_sessions` 48, `20_sessions` 2, `quarterly` 2, `thesis-review` 1. The 870 `event-relative` rows
correlate closely with the 871 `due_at: null` rows of §5.5 — an event-relative horizon has no
calendar date to compute, which is the mechanism behind F-4.

[VERIFIED] `entity_type`, latest-by-id: `UNRESOLVED` 984, absent 138, `PORTFOLIO_CASH` 3.
984 checkpoints have an unresolved entity — recorded as an observation, not diagnosed here.

[VERIFIED] `duplicate: false` on 1,125 of 1,125. No self-declared duplicates.

---

## 9. Corrections

Kept in the document as required, not silently applied.

**9.1 — the store-root trap does not apply to this store.** The brief instructed: *"Assume every
CIO store may be checkout-relative."* Assumed, then tested, then falsified for
`outcome_checkpoints.jsonl`: it resolves through `production_state_root()`
(`canonical_store_registry.py:487-502`), not through the cwd, and the served release reaches it by
symlink. It **is** true for `CIOPlanStore` — verified in the companion ops document, where the same
dry run returns 43 from one root and 0 from the other.

**9.2 — an early count in this session was superseded.** A first read at 23:12 ET measured 1,524
lines / 1,122 distinct ids / 872 `SCHEDULED`. A second read at 23:20 measured 1,527 / 1,125 / 875.
The store had grown; the first reading was not wrong, it was stale within eight minutes. All
published figures are from the pinned snapshot `61a5844d…`. The discrepancy is recorded rather than
overwritten, because the drift rate is itself a finding.

**9.3 — do not quote the numbers in this document.** They were regenerated rather than quoted from
the AS-IS doc, per AGENTS.md §16, and they will be stale on the same timescale that made the AS-IS
doc's `~791` stale. The commands are given inline so the next reader regenerates instead of quoting.

**9.4 — "a checkpoint bound to nothing cannot settle" is false.** See §7. 158 settled checkpoints
have no plan binding at all.

**9.5 — the AS-IS doc's `~791` was not reproduced and is not disproved.** Today's distinct-id count
is 1,125 and the store's oldest datable record is 2026-08-26 — four days after the AS-IS doc's
2026-08-30 dateline is *later* than that. This census cannot reconstruct what the store held on
2026-08-30 and does not claim the earlier figure was wrong; it claims only that it is not the
figure today.

---

## 10. What this census cannot see

Per AGENTS.md §7 — the structural blind spots of this instrument, not a list of things not yet done.

1. **The `ticker_prices` table itself.** Every statement about price availability is inferred from
   the resolver's classification receipts, never from the database. A direct read-only query was
   attempted and **denied by the environment's permission layer**; per AGENTS.md §0 rule 3 the
   denial was not routed around. This is why §3.3's cause (a)-versus-(b) is UNKNOWN. A census that
   could query `ticker_prices` would close that gap in one statement.
2. **Anything Postgres-resident.** If a second outcome lane lives in `agent_scores`,
   `trade_lesson_memory`, `kb_lessons` or `paper_trade` tables, this JSONL-only census cannot see
   it, cannot count it, and cannot tell whether it contradicts anything here. §8's 625 unattributed
   observations are the visible edge of that blind spot.
3. **The past.** The store is append-only and the earliest datable row is 2026-08-26. Whatever was
   truncated, rotated, migrated, or archived before that date is invisible. The 18 undated rows are
   the only trace of a prior writer generation, and they cannot be dated (§4).
4. **Which copy is authoritative.** Six copies of the checkpoint store and two of the KB lesson
   store were found. This census reports paths, sizes, hashes and mtimes and stops there
   (AGENTS.md §0 rule 5). It cannot and must not tell you which to keep.
5. **Whether the numbers survive the night.** The store grew by three records in eight minutes
   during this audit and the hourly resolver appends at :20 past every hour. This is a photograph,
   not a state.
6. **Semantic correctness of a settled outcome.** The census verifies that 158 checkpoints carry an
   `outcome_id` that resolves. It does **not** verify that the price comparison behind any of them
   is right — that the decision date was the right anchor, that the horizon was meaningful, or that
   a copy-forward price did not stand in for a real close. The `--as-of` flag's own help text
   (`resolve_due_checkpoints.py:387-392`) exists precisely because copy-forward prices are a known
   hazard, which means the hazard is real and unmeasured here.
7. **Whether anything reads the lessons.** 344 candidates exist and 343 are `REVIEW_READY`. Whether
   any wake, brief, or operator surface actually loads them is outside this census.
8. **Operator intent.** Nothing here decides that 871 unschedulable checkpoints should be given
   `due_at` values, that the stale checkout copy should be archived, or that the pending-data apply
   path should be armed. Those are operator-only (AGENTS.md §0 rule 9, §17). This document proposes
   nothing and stops.
