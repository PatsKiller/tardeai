# CENSUS — PART 1: BACKEND

**Authority:** READ_ONLY_ADVISORY. `MBI_BEHAVIOR=0`, `MBI_COGNITION=1`. No writes to any store; no
promote, deploy, merge or Telegram. Broker subsystem explicitly out of scope.

**Scope:** every Python module, script and entrypoint in the repository, plus the schedulers that
invoke them, the versioned schema literals they declare, and the stores they read and write.
The Command Center operator surface (routes, pages, tabs, rendered fields) belongs to PART 2 and is
**not** censused here.

**Status: PASS 1 of N.** Published progressively per the brief. Sections marked `PENDING` are not
yet measured and are named so that no reader mistakes absence for a zero.

---

## 0. Roots, interpreters and as-of

Every count in this document carries the root it was read from. Two measurements of a live-appending
store are not in conflict unless they share an as-of.

| role | path | evidence |
|---|---|---|
| repo worktree read for source | `/home/johnclaw/r20-r24-exact-main-deploy` | `[VERIFIED]` `git rev-parse HEAD` → `79a3f573` |
| census worktree (this document) | `/home/johnclaw/census-part1-backend` | `[VERIFIED]` `git worktree add … -b docs/census-part1-backend 79a3f573` |
| served release | `/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT` | `[VERIFIED]` `readlink -f` — **see §0.1, this moved three times during the census** |
| hub repo | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` | `[VERIFIED]` `git rev-parse --git-common-dir` from the deploy worktree resolves here |
| interpreter | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python` | `[VERIFIED]` used for every measurement below |

`as_of` for all §1–§5 counts: **2026-08-30T23:15Z – 23:30Z**.

### 0.1 Two premises in the brief are refuted by measurement

The brief states main tip `1306132c` and served release `1306132c-main-exact-phase2-20260830-151435`.
Neither holds.

- `[VERIFIED]` `git log --oneline -3` in the deploy worktree → main tip is **`79a3f573`**
  ("docs: CLAUDE.md becomes the standing rules…", PR #711), with `9d92b6e0` (#710) and `4d56b58a`
  (#709) beneath it. `1306132c` is not the tip.
- `[VERIFIED]` `readlink -f CURRENT` returned **three different releases within 15 minutes**:
  `a9389f67-…-191046` at 23:15Z → `865a4a1d-…-191554` at 23:18Z → and a parallel measurement
  observed `a5006df1-…-192221` at ~23:25Z.

**Finding C-01 — the served release rotates faster than a census can be taken.** Any figure in this
document that was read from `CURRENT` names the concrete release hash it was read from, never the
symlink. A reader who re-runs a `CURRENT`-relative command will likely be measuring a different
release. This also means *no* audit of this system may quote `CURRENT` as a stable identifier.

---

## 1. The 563 / 543 scheduler discrepancy — resolved

The brief asks me to establish the real number without adopting either figure as a premise.

### 1.1 The arithmetic

`[VERIFIED]`, `crontab -l` as_of 2026-08-30T23:15Z:

```
total lines                            997
blank lines                             45
comment lines (^\s*#)                  454
env assignments (SHELL=, PROJ=, PY=…)    6
actual job lines                       492
unclassified                             0
```

492 + 6 + 45 = **543**, which is exactly what `crontab -l | grep -vc '^\s*#'` reports `[VERIFIED]`.

**The 543 figure is not a job count.** It is the count of lines that are not comments, and it
silently includes 45 blank lines and 6 environment assignments. The real number of scheduled cron
job lines is **492**.

The 6 env assignments matter to the rest of this census and are recorded here `[VERIFIED]`:
`SHELL=/bin/bash`, `PROJ=…/trade-ai-v12-rebuild/trade-ai-v12-rebuild`, `PY=$PROJ/.venv/bin/python`,
`TRADEAI_ENV=/run/user/1000/tradeai/env`, `BLIND_REVIEW_LANES=deepseek-flash,grok,chatgpt`,
`CIO_DUAL_CHATGPT_CAP=1100`.

### 1.2 The 563 figure has no documentary source

`[VERIFIED]` `grep -rn '563 entr\|563 lane\|563-entry\|563 cron'` across `*.md`, `*.txt`, `*.json`
in the repository returns **no matches**. `[VERIFIED]` `grep -rn '\b563\b' docs/ *.md` returns 7
hits and every one is either a pull-request number (`(#563)` in `docs/CHANGELOG.md` ×2,
`docs/architecture/cio/LOOP_CLOSURE_2026-08-27.md`), a byte size in an archive inventory, an
unrelated decimal (`fused 0.563`), or a different quantity entirely (`deleted 1,563 obsolete files`).

**Finding C-02 — no document in this repository claims a 563-entry lane-registry baseline.** The
figure appears to be PR **#563** read as a count. I could not locate any artifact that would support
it, and I am recording this as a refuted premise rather than reconciling to it.

### 1.3 The lane registry is a third, unrelated quantity — and it is 56

The brief couples "563" to a *lane registry*. A lane registry does exist, but it is not the crontab
and it is not on that order of magnitude.

- `[CODE]` `scripts/api_v2.py:35859` routes `/api/v2/consumption/lane-registry` →
  `_consumption_lane_registry()` (`scripts/api_v2.py:10834`), which calls
  `lib.llm_consumption.registry_lane_map()`.
- `[CODE]` `scripts/lib/llm_consumption.py:1277` builds the map from `_load_registry()`, whose
  source is `REGISTRY_PATH = ROOT/"config"/"llm_process_registry.json"` (line 18).
- `[VERIFIED]` measured against the **live served release** over HTTP at 23:20:19Z
  (release `865a4a1d-…-191554`):

```
processes: 56   policy_labels: 6
lane_policy distribution:
  either 26 · deepseek_only 16 · grok_only 5 · ensemble 5 · both_preferred 4
```

- `[VERIFIED]` the backing file is byte-identical across all three roots —
  `sha256 420ce1f0ed3ecf71c593e8dcbcef620149b66c16718b6634a750cbf95319dccb`, 30,372 bytes, in the
  served release, the deploy worktree and the hub. It is tracked in git and is not gitignored.

So the three numbers in play are **492** (cron job lines), **543** (a non-comment line count that
includes blanks and env vars), and **56** (lane registry entries). None of them is 563, and no two
of them measure the same thing.

### 1.4 A correction I am obliged to record

My first measurement of the lane-registry endpoint reported `ok: True` with **0 processes**, and I
began writing it up as a live defect — a green surface serving an empty set, which is precisely the
governing failure class in `CLAUDE.md`.

That claim was wrong and I withdraw it. `[VERIFIED]` the endpoint wraps its payload in a `data`
envelope (`{"ok": true, "data": {"ok": true, "processes": {…}}}`); my parser read `processes` at the
top level, found nothing, and reported a zero that was an artifact of my own reader. Re-measured at
the correct level the endpoint returns 56/6 and is **correct**.

**Method note M-01 — a zero produced by the measuring instrument is indistinguishable from a zero in
the system.** I nearly filed a false defect against a healthy endpoint. Any "surface returns empty"
finding in this programme must be corroborated by reading the producer directly before it is
reported.

---

## 2. Scheduler inventory

### 2.1 Cron — 492 job lines

`[VERIFIED]`, as_of 2026-08-30T23:15Z. Resolution of each job line to the module it invokes was done
by path-suffix matching against `git ls-files`, not by bare basename matching (see M-02).

| measure | value |
|---|---|
| job lines | 492 |
| distinct tracked `.py` modules referenced | **311** |
| distinct `.sh` basenames referenced | 47 |
| job lines invoking a module by `-m` | 2 |
| job lines with no `.py`/`.sh`/`-m` target (inline `python -c`) | 7 |

**Root the job runs in** `[VERIFIED]`:

| root | job lines |
|---|---|
| hub (`$PROJ` or literal hub path) | 456 |
| served release (`portfolio-server/CURRENT`) | 30 |
| no explicit `cd` | 6 |

**Finding C-03 — 456 of 492 cron job lines execute in the hub, not the served release.** Only 30 run
from `CURRENT`. The deploy protocol's instruction to "prove behaviour from the served release" does
not describe where the great majority of scheduled work actually happens. A change promoted to
`CURRENT` does not reach 93% of the cron tree.

**Interpreter** `[VERIFIED]`:

| interpreter | job lines |
|---|---|
| `$PY` (hub venv) | 291 |
| `.venv/bin/python` (relative to the `cd` target) | 117 |
| no python (shell/curl/other) | 81 |
| **system `python3`** | **3** |

The 3 system-`python3` lines are 928–930, all of the form
`cd …/CURRENT && python3 -c "from scripts.lib.cio_event_detector import run_cio_event_detector_once; …"`.
`[VERIFIED]` I tested the import only (not the call, which writes): from `CURRENT` under
`/usr/bin/python3` (Python 3.14.4) the import succeeds, `rc=0`, `IMPORT OK`. These three lines are
viable despite bypassing the venv. Their cadences are weekday 05:00, Sunday 08:00 and **monthly on
the 1st at 09:00** — the monthly one is indistinguishable from a dead job on any day but the 1st.

**The crontab is not exclusively this project's.** `[VERIFIED]` grouping job lines by the first
absolute path they name: `trade-ai-v12-rebuild` 133, `trade-ai-releases` 29, `nyc-dof-auction` **2**,
`tradeai-wt-watch-review-automation` 2, `.config` 2, `.claude` 1, and 323 lines that name no
absolute path (these use `$PROJ`, i.e. the hub). Any future count of "our" scheduled jobs must
exclude the `nyc-dof-auction` lines (154, 162), which belong to an unrelated project.

### 2.2 systemd — checked, and it changes the answer

`[VERIFIED]` `systemctl --user list-unit-files '*.timer'` → 94 unit files, of which **78** are in the
tradeai/hermes/aegis/recovery family: **65 enabled, 13 disabled**.

The 13 declared-but-disabled user timers `[VERIFIED]`:
`hermes-autonomous-loop`, `tradeai-continuous`, `tradeai-flash-llm-intelligence`,
`tradeai-flash-portfolio-risk-hourly`, `tradeai-flash-portfolio-risk-weekend`,
`tradeai-flash-watchlist-daily`, `tradeai-governance-facts`, `tradeai-governance-status`,
`tradeai-hermes-research-remediation`, `tradeai-intelligence-remediation`,
`tradeai-main-desk-free-llm-weekly`, `tradeai-maturity-board`, `tradeai-operator-readiness`.

`[VERIFIED]` 54 tracked `.py` modules are referenced by a systemd `ExecStart`; 7 of those are also
referenced by cron. Union of cron- and systemd-referenced tracked modules: **358**.

**Finding C-04 — a unit can be disabled at user level and simultaneously enabled and firing at
system level.** `[VERIFIED]`:

```
tradeai-continuous.timer   user-enabled=disabled  user-active=inactive
tradeai-continuous.timer   sys-enabled=enabled    sys-active=active
```

An audit that ran only `systemctl --user` would conclude `tradeai-continuous` is off. It is not; the
system-level unit fires (`[VERIFIED]` last run Fri 2026-08-28 04:00, next Mon 2026-08-31 04:00).
`tradeai-reprice.timer` is likewise system-level, enabled and active. There are exactly three
system-level tradeai units `[VERIFIED]`: `tradeai-continuous`, `tradeai-reprice`,
`tradeai-portfolio-server`.

### 2.3 The live HTTP server is not started by its systemd unit

`[VERIFIED]`:

```
systemctl is-active  tradeai-portfolio-server → inactive
systemctl is-enabled tradeai-portfolio-server → disabled
```

…yet the server is running. `[VERIFIED]` `ss -tlnp` shows `0.0.0.0:7777` held by a python process
whose argv is
`…/trade-ai-v12-rebuild/.venv/bin/python  …/portfolio-server/<release>/scripts/portfolio_server.py`
— i.e. the **hub's interpreter running the served release's code**, exactly the split the brief
warned about. `[VERIFIED]` its `PYTHONPATH` and `cwd` both point at that release, so its root
resolution is self-consistent.

`[VERIFIED]` the actual supervisor is cron line 426:
`*/2 * * * * bash …/portfolio-server/CURRENT/scripts/portfolio_server_watchdog.sh`.

**Finding C-05 — the disabled `tradeai-portfolio-server.service` is a decoy.** Its `ExecStart` names
the **hub** (`WorkingDirectory=…/trade-ai-v12-rebuild`, `ExecStart=… scripts/portfolio_server.py`),
so if anyone ever enabled it, it would serve the hub's code rather than the promoted release. The
unit is stale relative to how the system actually runs, and it disagrees with the live process about
which root serves.

---

## 3. Module inventory — 3,449 tracked Python files

Enumerated by `git ls-files '*.py'` at `79a3f573` in `/home/johnclaw/r20-r24-exact-main-deploy`.
`[VERIFIED]` count: **3,449**. Total tracked files of all types: 7,384.

### 3.1 Every tracked module compiles

`[VERIFIED]` each of the 3,449 files was compiled with the builtin **`compile(source, path, "exec")`
over raw bytes** — not `ast.parse`, which tolerates a BOM and does not enforce `__future__`
placement. Result: **0 files fail to compile.** (One `SyntaxWarning` for an invalid escape in
`scripts/defense_recommendations.py:1031`; a warning, not a failure.)

This is consistent with PR #710 ("the dark-contract gate passed a file that could not compile") and
#709 ("wire the compile guard into CI") having landed immediately before the census.

### 3.2 Kind

`[VERIFIED]`, N=3,449, root `/home/johnclaw/r20-r24-exact-main-deploy` @ `79a3f573`:

| kind | count | share |
|---|---:|---:|
| entrypoint (contains `__main__`) | 1,348 | 39.1% |
| library | 1,070 | 31.0% |
| test | 1,029 | 29.8% |
| config | 2 | 0.1% |
| generated | 0 | 0.0% |

### 3.3 Invocation class

Computed from a repo-wide import graph (3,449 files parsed; imports resolved against the four import
styles this repo actually uses: `from lib.X`, `from scripts.lib.X`, bare `import X` with
`scripts/` or `scripts/lib` on `sys.path`) unioned with the precise scheduler resolution from §2.

| class | count | share |
|---|---:|---:|
| TEST | 1,029 | 29.8% |
| **NO_INBOUND** — nothing imports it, no scheduler names it | **811** | **23.5%** |
| IMPORTED_BY_HTTP — in the transitive closure of the served server | 682 | 19.8% |
| SCHEDULED — named directly by cron or a systemd unit | 358 | 10.4% |
| IMPORTED_BY_SCHEDULED | 210 | 6.1% |
| IMPORTED_NONLIVE_ONLY — imported, but only by non-live code | 184 | 5.3% |
| TEST_ONLY_IMPORT — imported only by tests | 173 | 5.0% |
| HTTP_ENTRY | 2 | 0.1% |

`NO_INBOUND` and `TEST_ONLY_IMPORT` are the **candidate** `DARK` population — 984 files, 28.5% of the
repository. They are deliberately *not* yet given a `DARK` verdict: see §4 for why a single
observation cannot support that, and §6 for what remains to be done before they can be classified.

### 3.4 Method note M-02 — basename matching is not evidence

My first pass resolved scheduler references by matching module **basenames** against a corpus that
included every `.sh` file under `scripts/`, `bin/` and `linux_launchers/`. It reported 525 scheduled
modules.

`[VERIFIED]` spot-checking that set against the actual schedulers refuted it:
`grep -n 'backfill_acct_periods_v3' crontab user_units` → **no match**;
same for `apps/command-center-v2/serve.py` and `linux_port_v2/scripts/portfolio_price_cache.py`.
All three were false positives introduced by basename collisions in shell text.

Re-resolved by **path-suffix matching against `git ls-files`, restricted to cron job lines and
systemd `ExecStart` only**, the count is **358** (311 cron + 54 systemd, 7 in both). The 525 figure
is withdrawn. This is the third time in this programme that a filename grep has produced a wrong
conclusion, and it is the reason §3.3 is stated at the precision it is.

---

## 4. `last_ran` — why log files are not evidence, and what is

The brief requires durable evidence rather than a log file's existence. Measuring the cron tree
established something stronger: **log mtime is systematically misleading in this system, in both
directions.**

`[VERIFIED]` of the 492 cron job lines, 470 redirect to a `.log`; 465 of those logs exist on disk.
Age distribution of last write:

| age of last log write | job lines |
|---|---:|
| < 1 day | 172 |
| 1–7 days | 274 |
| 7–30 days | 9 |
| 30–90 days | 10 |
| > 90 days | 0 |

That reads as 19 stale jobs. **On investigation, not one of the 19 is dead.** Every one resolved
into one of four categories, and the log told the wrong story in three of them.

### 4.1 Correct low-cadence jobs that merely look dead

`[VERIFIED]` lines 133, 137, 167, 172, 536, 614, 862 are all `0 X 1 * *` — **monthly on the 1st**.
Their logs are 29 days old because they last ran on 2026-08-01 and next run 2026-09-01. Lines 404
(`30 9 2 6 *`) and 419 (`0 7 3 6 *`) are **annual**, in June; their logs are 88–89 days old and
correct. This is exactly the case `CLAUDE.md` warns about: a monthly, quarterly or seasonal job is
indistinguishable from a dead one on any given day.

### 4.2 Jobs that are silent on success — a stale log means it worked

`[VERIFIED]`:
- line 640 `curl -s -m 30 -o /dev/null …/finviz-strip-map` → `logs/finviz_strip_prewarm.log` is
  **0 bytes**, mtime Jun 24. Silent curl writes nothing on success; the log only grows on error.
- line 828 `curl -s … /api/v2/trade-ai` → `logs/trade_ai_prewarm.log` **0 bytes**, mtime Jul 17.
- line 794 `volatility_tier_refresh.py --quiet` → `logs/volatility_tier_refresh.log` **0 bytes**,
  mtime Jul 15.

For these, an empty and old log is the signature of an uninterrupted run of successes. Reading it as
failure inverts the truth.

### 4.3 Jobs whose real output goes to a different file than the cron redirect

This is the most dangerous category, because the cron line names a log that the work never writes.

- `[VERIFIED]` line 405/406 redirect to `logs/protection_pipeline_cron.log`, which is **55 bytes**,
  mtime 2026-07-03, containing exactly one line: `[market_day_gate] 2026-07-03 20:30:01 skipped:
  holiday`. Read alone this says the protection pipeline has not run in 57 days.
  `[CODE]` `scripts/run_protection_pipeline.sh` sets `LOG="$PROJ/logs/protection_pipeline.log"` — a
  **different file** — and writes all eight stages there.
  `[VERIFIED]` that file is **19,084,611 bytes**, mtime 2026-08-28 20:30, last line
  `[2026-08-29 00:30:34 UTC] === protection pipeline done ===`. The schedule is `30 20 * * 1-5`
  (weekday after-close); the census ran on a Sunday, so the previous weekday — Friday 2026-08-28 —
  is exactly right. **The pipeline is LIVE.**
- `[VERIFIED]` line 484 redirects to `logs/profit_capture_refresh_cron.log`, **0 bytes**, mtime
  Jun 7. `[CODE]` `run_profit_capture_refresh.sh:14` sets `LOG=…/logs/profit_capture_refresh.log`.
  `[VERIFIED]` that file is 326,285 bytes, mtime **2026-08-30 03:30**, last line
  `[2026-08-30 07:30:22 UTC] === profit-capture refresh done ===`. Schedule `30 3 * * 0` — weekly on
  Sunday. Today is Sunday. **It ran today.**

### 4.4 A genuinely expired pair — the only dead cron lines found so far

`[VERIFIED]` lines 851 and 852 are guarded by a literal past date:

```
20 12 20 7 * [ "$(date +\%F)" = "2026-07-20" ] && … run_paper_canary_chain.py
22 10 20 7 * [ "$(date +\%F)" = "2026-07-20" ] && … run_paper_canary_chain.py
```

The cron field `20 7` fires every 20 July, but the shell guard pins the **year**, so the condition
can never be true again. `[VERIFIED]` `logs/paper_canary_chain.log` mtime is 41 days old, which is
2026-07-20 — corroborating that both fired once, on that date, and never since.

**Verdict for lines 851–852: `ONE_SHOT` (expired).** They occupy two crontab slots and can never
execute again. Reporting only; removal is an operator decision and I have not proposed one.

### 4.5 Method note M-03

**Log mtime measures "the last time this job printed something", not "the last time it ran".** In
this repository the two diverge for at least three distinct structural reasons (silent-on-success,
gate-only logging, cron-redirect vs. internal `LOG=`). Every `last_ran` value in the per-module
tables of §5 is therefore sourced to a **durable artifact whose existence or content would be
impossible had the job not run**, and the artifact is named. Where no such artifact could be
identified, the value is `UNKNOWN` and is recorded as `UNKNOWN`.

---

## 5. Versioned schema literals

Measured independently and then reconciled against the repository's own auditor,
`scripts/check_dark_contracts.py`. Root `/home/johnclaw/r20-r24-exact-main-deploy` @ `79a3f573`,
as_of 2026-08-30T23:25Z.

| measure | value |
|---|---:|
| distinct versioned schema literals | **437** |
| — declared via a named constant (`SCHEMA`, `*_SCHEMA`, `SCHEMA_VERSION`) | 205 |
| — inline literal only | 232 |
| **zero non-test, non-self production consumers** | **376 (86%)** |
| ≥1 production consumer | 61 |
| **ever read back / compared at runtime in production code** | **9 (2%)** |

`[VERIFIED]` the consumer distribution is extreme: 376 literals at 0 consumers, 45 at 1, 11 at 2,
2 at 3, 2 at 4, 1 at 5. **Nothing in the repository has more than five.**

### 5.1 Zero-production-consumer schema literals — 376 of 437

Reported separately and prominently as required. By defining location `[VERIFIED]`:

| location | zero-consumer literals |
|---|---:|
| `scripts/lib/` | 292 |
| `scripts/` | 48 |
| test-only (literal appears nowhere but tests) | 31 |
| `docs/_evidence/transferson_universe/` | 2 |
| `scripts/lib/provider_cost/` | 2 |

Of the 376, **157 are hard contracts declared as a named constant** rather than incidental strings.
The concentrations `[CODE]`:

- `scripts/lib/cio_intelligence_fabric.py:33-40` — **eight schema constants in one module, all
  zero-consumer**: `IntelligenceDeltaReceipt@v1`, `GraphImpactResolution@v1`,
  `IntelligenceLifecycleReceipt@v1`, `FreeFirstPending@v1`, `EnvelopeProviderStatus@v1`,
  `IntelligenceCoverageMatrix@v1`, `IntelligenceProducerInventory@v1`, `WebEvidenceProvenance@v1`.
- `scripts/lib/cio_institutional_learning.py:25-28` — 4 (`LessonCandidate@v2`,
  `HypothesisCandidate@v1`, `ShadowExperiment@v1`, `LearnableDecision@v1`).
- `scripts/lib/security_identity.py:16-19` — 4 (`IssuerIdentity@v1`, `SecurityIdentity@v1`,
  `ListingIdentity@v1`, `TickerAlias@v1`).
- `scripts/lib/cio_model_learning.py:18-20` (3), `scripts/lib/cio_held_thesis_coverage.py:15-16,326`
  (3), `scripts/lib/cio_canon_v1.py:24-26` (3), `scripts/lib/research_contradiction.py:10-11` (2).

The 31 test-only literals are fixture version strings (`symbol_noc@v1/v3/v5/v7/v8`, `desk@v2/v9`,
`capital_plan@v1/v3`, `CompileGateProbe@v1`) and are correctly outside the actionable set.

### 5.2 Literals with production consumers

| literal | defining file:line | prod consumers |
|---|---|---:|
| `TickerKnowledgeProfile@v1` | `scripts/lib/ticker_knowledge_graph.py:20` | 5 |
| `TransfersonUniverseManifest@v1` | `scripts/lib/transferson_universe.py:31` | 4 |
| `PreferenceCandidate@v1` | `scripts/lib/cio_feedback_learning_v1.py:20` | 4 |
| `OutcomeCheckpoint@v1` | `scripts/lib/cio_lineage.py:41` | 3 |
| `InvestmentIntelligenceCard@v1` | `scripts/lib/cio_symbol_intelligence.py:14` | 3 |
| `ControlPlane@v1.0.0` (TS side) | `apps/command-center-v3/src/control-plane/contractV1.ts:3` | 2 |
| `AgentEpisode@v1` | `scripts/lib/agent_episode.py:14` | 2 |
| `CIOInvestmentProduct@v1` | `scripts/lib/cio_investment_product.py:38` | 2 |
| `hermes_request@v1` | `scripts/lib/cio_hermes_research.py:52` | 2 |

### 5.3 Three findings the counts alone do not show

**Finding C-06 — `ControlPlane@v1.0.0` is declared twice, independently, with nothing linking them.**
`[CODE]` `scripts/lib/control_plane_contract_v1.py:14` sets `SCHEMA = "ControlPlane@v1.0.0"`;
`apps/command-center-v3/src/control-plane/contractV1.ts:3` separately exports the same string. The
TypeScript constant has 2 live consumers; the Python constant has **zero** non-test consumers, its
only non-test reference being the dark-contract auditor's own `KNOWN_DARK` table `[VERIFIED]`.
Front end and back end agree on the contract version **by convention only** — nothing enforces the
equality, and either side can be bumped without the other noticing. *(This one straddles the
PART 1 / PART 2 boundary; flagged for PART 2 in §7.)*

**Finding C-07 — the store registry declares schemas it never validates.** `[CODE]`
`scripts/lib/canonical_store_registry.py` is genuinely live (30+ production importers) and its
`STORES` table carries a `"schema"` field for 18 stores. `load_json_store()` (line 553) **never
compares the declared schema to the loaded data**; `"INVALID_SCHEMA"` is returned only when JSON
parsing fails. The declared value is read in exactly two places
(`control_plane_api.py:693`, `data_store_inventory.py:48`) and both merely pass it through into a
report. Roughly ten literals whose only "consumer" is this registry are therefore **declared,
displayed, and never enforced** — a schema field that cannot fail is not a check.

**Finding C-08 — only 9 of 437 literals (2%) are ever read back.** `[VERIFIED]` scanning non-test
production code for a literal in a comparison or dispatch position yields only `AgentEpisode@v1`,
`DecisionPayload@v1`, `PreferenceCandidate@v1`, `ResearchThesisDelta@v1`, `SpecialistArtifact@v1`,
`TickerKnowledgeProfile@v1`, `desk@v5`, `desk@v6`, `symbol_noc@v2`. **Every other literal is stamped
into output and never examined.** This means the consumer counts in §5.2 overstate real coupling:
most "consumers" write the literal rather than branch on it. Versioning that is never read cannot
protect a migration.

### 5.4 Reconciliation with the repository's own auditor

`[VERIFIED]` `scripts/check_dark_contracts.py` exits 0 and reports:

```
versioned-schema definers : 249
zero-consumer             : 37   (29 inherited-seeded + 8 declared NO_CONSUMER_REASON)
NEW (unexplained)         : 0
uncompilable              : 0
resolved since baseline   : 1  ✓ scripts/lib/proactive_cio.py
```

Its scope is `scripts/**` only and it counts *definers*, not literals, which is why 249 ≠ 437.
Reconciling module-level orphans, **17 of 18 agreed**, and every divergence resolved in the
auditor's favour — my independent script had two of the exact bugs this programme keeps hitting:
a regex that truncated `ControlPlane@v1.0.0` to `ControlPlane@v1` and so counted 21 TypeScript hits
against the Python constant, and a substring collision in which `embedding_policy.py` appeared
consumed by five modules that in fact all import `lib.ollama_embedding_policy`, a different module
`[VERIFIED]`. Both of my errors are recorded here rather than quietly fixed, because the pattern —
a name-shaped match standing in for a resolved symbol — is the recurring defect.

---

## 6. What is not yet measured

Named explicitly so that absence is not read as zero.

- `PENDING` — **canonical store registry**: every store, its writer(s), its reader(s), absolute vs.
  root-relative path, and the stores with no non-test reader. Measurement in progress.
- `PENDING` — **`LIVE_UNCONSUMED` determination for the 358 scheduled modules**: which of them
  produce a durable artifact that nothing reads. This is the most expensive class in the system and
  it is deliberately not estimated here.
- `PENDING` — per-module `produces` / `consumed_by` / `last_ran` rows for the 358 scheduled modules.
- `PENDING` — adjudication of the 984 `NO_INBOUND` + `TEST_ONLY_IMPORT` candidates into `DARK`,
  `ONE_SHOT`, `SUPERSEDED` or `UNKNOWN`. No file in this population has been called dead: per
  `CLAUDE.md`, a single observation cannot support that verdict, and §4 has already shown four
  distinct ways a live component can look dead.

**No verdict totals are published in this pass.** Publishing a `LIVE`/`DARK` split before §6 is
complete would produce exactly the artifact this census exists to prevent: a number everyone trusts,
derived from an aggregate that discarded its members.

---

## 7. For PART 2 and later parts

- **§5.3 / C-06 crosses the boundary.** `ControlPlane@v1.0.0` is declared independently in Python
  and in `apps/command-center-v3/src/control-plane/contractV1.ts`. PART 2 owns the TypeScript side;
  it should verify whether any operator surface would detect a version skew between the two, because
  from the backend side nothing would.
- **C-01 affects PART 2's method.** `CURRENT` rotated three times in fifteen minutes. Any PART 2
  measurement taken against `CURRENT` must record the concrete release hash, or it will not be
  reproducible.
- **C-07 is a surface question too.** The store registry's `schema` field is rendered into reports
  via `control_plane_api.py:693` and `data_store_inventory.py:48`. If an operator surface displays
  that field, it is displaying a value that is never validated — PART 2 should establish whether it
  is shown, and whether it is shown as if it were a check.

---

## 8. Method register

Every claim above is tagged. The techniques that changed a conclusion during this census:

- `compile()` over raw bytes, never `ast.parse` — §3.1.
- Path-suffix resolution against `git ls-files`, never basename grep — M-02, §3.4.
- Durable artifacts, never log existence or mtime, for `last_ran` — M-03, §4.
- Reading the producer before believing an empty surface — M-01, §1.4.
- Checking cron **and** both systemd scopes — C-04, §2.2.
- `${PIPESTATUS[0]}` rather than `$?` after a pipe, and testing for the specific expected exit code
  rather than mere success — applied throughout §2.1 and §3.1.
- `atime` was not used as evidence anywhere in this document; the filesystem is `relatime`.
