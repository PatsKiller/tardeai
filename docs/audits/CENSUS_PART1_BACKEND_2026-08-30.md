# CENSUS — PART 1: BACKEND

**Authority:** READ_ONLY_ADVISORY. `MBI_BEHAVIOR=0`, `MBI_COGNITION=1`. No writes to any store; no
promote, deploy, merge or Telegram. Broker subsystem explicitly out of scope.

**Scope:** every Python module, script and entrypoint in the repository, plus the schedulers that
invoke them, the versioned schema literals they declare, and the stores they read and write.
The Command Center operator surface (routes, pages, tabs, rendered fields) belongs to PART 2 and is
**not** censused here.

**Status: complete for the declared scope, with one third of the repository deliberately left
`UNKNOWN`.** Published progressively per the brief (pass 1 = §0–§5, pass 2 = §6–§10). The `UNKNOWN`
population in §8.2 is a measured result, not an omission: see §8.2 for why no `DARK` verdict is
recorded despite 811 modules having no inbound reference at all.

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

## 6. The canonical store registry

Root read: `/home/johnclaw/trade-ai-releases/persistent-state` (`$PS` below; every registry path
resolves under it). `as_of` **2026-08-30T23:25:45Z**. Hub root `$HUB` =
`/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`.

### 6.0 A correction to the brief — and to `CLAUDE.md` itself

Both the brief and `CLAUDE.md`'s standing-traps section state that
`cio_lineage_health.DEFAULT_PATH` points outside every checkout and that `TRADEAI_ROOT` "can neither
fix nor break it". **Both halves of that are wrong**, and I verified it independently after the
store trace reported it, because it contradicts the standing rules.

`[VERIFIED]`, root `/home/johnclaw/r20-r24-exact-main-deploy` @ `79a3f573`:

```
cio_lineage_health.DEFAULT_PATH exists: False
cio_lineage.DEFAULT_PATH        exists: True
no-env                  DEFAULT_PATH = /home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_workflow_lineage.jsonl
TRADEAI_ROOT=/tmp/fakeroot -> DEFAULT_PATH = /tmp/fakeroot/data/cio/cio_workflow_lineage.jsonl
```

`[CODE]` `scripts/lib/cio_lineage.py:73-78` — the attribute does not exist on
`cio_lineage_health` at all; it is served on **`cio_lineage`** by a module `__getattr__` that
returns `production_state_root() / LINEAGE_RELATIVE`, i.e. it is **computed on every access**.

**Finding C-09 — the path is root-sensitive, and it lives on a different module than the rules say.**
It merely *looks* absolute because the marker file `$PS/PERSISTENT_STATE_ROOT.json` exists and wins
the fallback chain; remove the marker or set `TRADEAI_ROOT` and it moves. `CLAUDE.md` cites this
example as the settled resolution of a dispute in which "two agents drew opposite conclusions about
that collector's root sensitivity; both were reasoning about a path the variable never touched."
The measurement says the variable *does* touch it. **This is a factual error in the standing rules
being used to adjudicate future disagreements**, and it should be corrected there — that is an
operator/coordinator decision, not mine to make.

### 6.1 Five competing registries, not one

`[VERIFIED]` the canonical one is
`/home/johnclaw/r20-r24-exact-main-deploy/scripts/lib/canonical_store_registry.py`
(`CanonicalStoreRegistry@v1`, dict `STORES`, **34 entries**). Established by: ~38 importers across
`scripts/`; every other store-list module imports *it*; it compiles clean under builtin `compile()`;
and `docs/audits/diligence/P1_WS1_AS_BUILT_ARCHITECTURE_2026-08-30.md:173` names it with a matching
count of 34 `[DOC-CLAIM, count independently VERIFIED]`. The `.py` is **byte-identical**
(`sha256 283d966e4856cb8c…`) across the deploy worktree, the hub and the served release.

| # | registry | entries | status |
|---|---|---:|---|
| 1 | `scripts/lib/canonical_store_registry.py` | **34** | **CANONICAL** |
| 2 | `$PS/data/runtime/canonical_store_registry.json` | **19** | frozen 2026-08-26 20:56, **no writer anywhere in the repo — yet this is what production serves** |
| 3 | `scripts/lib/persistent_state_root.py:157-175` `inventory()` | 16 | divergent id namespace; `inventory()` has no non-test caller |
| 4 | `scripts/control_plane_api.py:27-90` `CONTROL_PLANE_DOMAINS` | 9 domains | own fallback list **and its own root resolver** |
| 5 | retired release `671d760f-…-20260828-095246` copy | 29 | not live; recorded for completeness |

**Finding C-10 — production serves the stale 19-entry JSON, not the 34-entry code registry.**
`[VERIFIED]` simulating the live server exactly (served release on `sys.path`, all three root env
vars unset — matching the real server process, which sets **none** of them):

```
LIVE-EQUIVALENT _state_root() = /home/johnclaw/trade-ai-releases/portfolio-server/a5006df1-…
served n = 19   quality = AVAILABLE
source has resolved_path key (=> JSON snapshot): True
```

`[CODE]` `control_plane_api._stores()` (`:50-56, 682-700`) puts the JSON **first** in its candidate
list and returns early on `AVAILABLE`; the 34-store code registry is only a fallback. **15
registered stores are therefore invisible on that surface**: `cio.agent_traces`,
`cio.delivery_receipts`, `cio.instrument_records`, `cio.lesson_binds`, `cio.notification_policy`,
`cio.specialist_artifacts`, `cio.workflow_lineage`, `identity.registry`, `learning.weekly`,
`notifications.audit`, `portfolio.watchlist`, `reconciliation.latest`, `research.hermes_requests`,
`runtime.audit_claims`, `runtime.maturity`. Nothing in the JSON is absent from the code registry.

**Finding C-11 — two different root laws are in force simultaneously.** `[CODE]`
`canonical_store_registry.production_state_root()` (`:487-502`) resolves env → `$PS` marker probe →
`CURRENT` probe → `parents[2]`; `control_plane_api._state_root()` (`:157-163`) resolves env →
`PROJECT_ROOT` (the checkout), with **no marker probe and no `CURRENT` probe**. With no env set the
two disagree. `[VERIFIED]` in production the disagreement is *masked* because the release dir
overlays `data/cio`, `data/runtime`, `data/health` and `data/portfolios/state` as symlinks into `$PS`
(same dev:inode) — **except `data/reconciliation/state`, which is a real directory**, and that single
gap produces the live split-brain in §6.4.

### 6.2 The 34 stores

All paths are `$PS/<suffix>`. **`[VERIFIED]` none of the 34 registry entries carries an absolute
path** — all 34 `path` values and all 8 alias values are root-relative. (The real
absolute-path-outside-every-checkout cases are 12 hardcoded literals in `scripts/`, 9 of them into
`$HUB` — see §6.5.) Writers/readers are `[CODE]`, traced to the actual write call; exists/size/mtime
are `[VERIFIED]` `stat` at as_of.

| # | store id | path suffix | exists · bytes · mtime | traced WRITER | non-test READERS |
|---|---|---|---|---|---|
| 1 | `cio.instrument_records` | `data/cio/cio_instrument_records.jsonl` | ✅ 392,062 · 08-30 14:58 | `cio_instrument_record.py:272` | 6 |
| 2 | `portfolio.watchlist` | `data/portfolios/state/watchlist.json` | ✅ 2,645 · **2026-05-09 (113d)** | `portfolio_watchlist.py:38` (init only; `save_watchlist` has **zero callers**) — operator-edited | 8 |
| 3 | `reconciliation.latest` | `data/reconciliation/state/latest.json` | ❌ **MISSING at `$PS`** | `cio_reconciliation.py:162` → **3 destinations, incl. a hardcoded `$HUB` path at `:154`** | `data_broker/cio_portfolio.py:362` |
| 4 | `learning.weekly` | `data/cio/weekly_learning.jsonl` | ❌ MISSING | **NONE** | **NONE** |
| 5 | `cio.workflow_lineage` | `data/cio/cio_workflow_lineage.jsonl` | ✅ 6,883,798 · 08-30 23:21 | `cio_lineage.py:214` | 5 |
| 6 | `portfolio.holdings.current` | `data/portfolios/state/holdings.json` | ✅ 232,477 · 08-30 12:00 | `schwab_position_sync.py:313,371` via `protected_holdings_write` | ~13 |
| 7 | `cio.product.current` | `data/cio/cio_investment_brief.json` | ✅ 767,043 · 08-30 23:21 | `cio_investment_product.py:2160` — **filename never appears at the write line** | 6 |
| 8 | `cio.product.history` | `data/cio/cio_investment_briefs.jsonl` | ✅ 1,180,032 · 08-30 23:26 | `cio_investment_product.py:2161` | **🔴 NONE** |
| 9 | `cio.operator_product.current` | `data/cio/cio_operator_product.json` | ✅ 151,654 · 08-30 23:17 | `cio_operator_product.py:418` | **🔴 NONE** |
| 10 | `cio.operator_product.history` | `data/cio/cio_operator_product.jsonl` | ✅ 51,791 · 08-30 23:17 | `cio_operator_product.py:420` | **🔴 NONE** |
| 11 | `cio.decisions` | `data/cio/cio_decisions.jsonl` | ❌ MISSING | **NONE** — the `cio_decisions` *Postgres table* is written by `cio_decision_engine.py:194`; no bridge to JSONL | `memory_consolidator_shadow.py:85` reads a file nothing produces |
| 12 | `cio.checkpoints` | `data/cio/outcome_checkpoints.jsonl` | ✅ 1,502,130 · 08-30 23:17 | `cio_institutional_learning.py:638` (**not** the declared `r17_checkpoint_binding`) | 4 |
| 13 | `cio.outcomes` | `data/cio/outcome_observations.jsonl` | ✅ 420,238 · 08-30 21:10 | `cio_institutional_learning.py:567` | 2 |
| 14 | `advisory.current` | `data/runtime/advisory_desk_latest.json` | ✅ 4,795,691 · 08-30 14:25 | **two**: `data_broker/advisory_desk.py:3351` (primary), `api_v3_advisory.py:523` | 4 |
| 15 | `research.current` | `data/cio/hermes_research_projection.json` | ✅ 15,918,995 · 08-30 23:21 | `cio_hermes_research.py:155`; `PROJECTION_PATH` is **CWD-relative** | 2 |
| 16 | `research.raw` | `data/cio/cio_research_impacts.jsonl` | ✅ 300,166 · 08-30 14:25 | `cio_product_reassessment.py:874` (declared `cio_research` **does not exist**) | `control_plane_api:46` only |
| 17 | `research.hermes` | *same file as #15* | ✅ | same as #15 | **🔴 NONE — dead duplicate id** |
| 18 | `memory.canonical` | `data/cio/aif_memory.json` | ✅ 1,738,563 · 08-30 14:25 | `agent_durable_memory.py:248` | **🔴 NONE** — every consumer reads `aif_memory.jsonl` instead |
| 19 | `ops.health` | `data/health` (dir) | ✅ 1 file · 08-18 16:57 | `post_deploy_smoke_test.py:220` | `ops_health_routing:105` greps for strings the writer never emits |
| 20 | `sector.momentum.current` | `data/runtime/sector_momentum_latest.json` | ✅ 8,329 · 08-26 02:04 | `sector_momentum_engine.py:424` | 9 |
| 21 | `industry.momentum.current` | `data/runtime/industry_momentum_latest.json` | ✅ 49,279 · 08-25 20:23 | `finviz_industry_groups.py:295` (**not** declared `industry_momentum`) | 8 |
| 22 | `cio.theses` | `data/cio/cio_theses_projection.json` | ✅ 3,556,867 · 08-30 08:23 | `cio_theses.py:177` — ⚠️ constructing `CIOThesisStore()` can trigger a rebuild-**write** from read-only call sites | 7 |
| 23 | `cio.feedback` | `data/cio/decision_dispositions.jsonl` | ✅ 1,159 · 08-15 15:32 | `api_v3_cio.py:1623` | 4 |
| 24 | `notifications.outbox` | `data/cio/cio_notification_outbox.jsonl` | ❌ MISSING | **NONE reaches this path** — `cio_notification_outbox.py:331-337` defaults to `operator_notification_outbox.jsonl` and both prod callers pass no `root=` | `telegram_receipts.py:30` hedges, reads both names |
| 25 | `cio.agent_traces` | `data/cio/agent_run_traces.jsonl` | ✅ 19,620,037 · 08-30 23:15 | `agent_run_trace.py:199`; **undeclared 2nd writer** `agent_trace_retention.py:101` rewrites the file despite `append_only:True` | 7 |
| 26 | `identity.registry` | `data/runtime/identity_registry.json` | ✅ 9,419,731 · 08-28 09:50 | `identity_registry.py:157` | 10 |
| 27 | `runtime.maturity` | `data/runtime/maturity_score_latest.json` | ✅ 5,423 · **2026-06-28 (63d)** | `compute_maturity_score.py:275` | 2 |
| 28 | `runtime.audit_claims` | `data/runtime/cc_v3_cio_office_audit.json` (**alias**) | ✅ 1,828 · 08-23 20:18 | `cc_v3_cio_office_audit.py:429` writes **only the alias**; the declared primary `audit_capability_claims.json` is **never written by anything** | `control_plane_api:84` only |
| 29 | `research.hermes_requests` | `data/cio/hermes_research_requests.jsonl` | ✅ 10,521,734 · 08-30 23:21 | `cio_hermes_research.py:125` **+ 2 undeclared CWD-relative writers** (`hermes_worker.py:60`, `hermes_research_loop.py:773`) | 3 |
| 30 | `notifications.audit` | `data/cio/cio_notification_audit.jsonl` | ✅ 3,920,120 · 08-27 03:10 | `cio_notification_signal.py:405`; ⚠️ `:362-365` **truncates in place** despite `append_only:True` | 4 |
| 31 | `cio.specialist_artifacts` | `data/cio/cio_specialist_artifacts.jsonl` | ✅ 2,350 (2 rows) · 08-29 20:11 | `cio_specialist_artifact.py:149` — **only caller is a test** | 3 |
| 32 | `cio.notification_policy` | `data/cio/cio_notification_policy.jsonl` | ❌ MISSING | `cio_notification_policy.py:144` — **only caller is a test** | **🔴 NONE — not even a test** |
| 33 | `cio.delivery_receipts` | `data/cio/cio_delivery_receipts.jsonl` | ✅ 410 (1 row) · 08-29 18:30 | `cio_delivery_receipt.py:122` — **only caller is a test** | only the generic `cio_registry_orphan_census:59` |
| 34 | `cio.lesson_binds` | `data/cio/cio_lesson_binds.jsonl` | ❌ MISSING | `cio_lesson_bind.py:143` — **only caller is a test** | `cio_s0_operator_loop.py:330` — **local import inside a `try:`; a filename grep finds nothing** |

**Totals `[VERIFIED]`, as_of 2026-08-30T23:25:45Z, root `$PS`: 34 registered · 28 present on disk ·
6 missing** (`reconciliation.latest`, `learning.weekly`, `cio.decisions`, `notifications.outbox`,
`cio.notification_policy`, `cio.lesson_binds`). 33 distinct paths — #15 and #17 share one file.

### 6.3 Registry metadata is wrong often enough that it cannot be trusted — and it is published

`[CODE]` `control_plane_api._stores()` (`:682-700`) echoes each spec's `writer` field **straight to
the GUI**. The following declared writers name modules that do not exist, or that do not write:

`cio.decisions`→`cio_decision_pipeline` (no such module) · `reconciliation.latest`→
`broker_reconciliation` (no such module) · `identity.registry`→`identity` (no such module) ·
`notifications.audit`→`cio_notification` (no such module) · `research.raw`→`cio_research` (no such
module) · `cio.checkpoints`→`r17_checkpoint_binding` (reads only) ·
`industry.momentum.current`→`industry_momentum` (formatters only) ·
`portfolio.holdings.current`→`"holdings reconciliation"` (prose) · `ops.health`→`"health agents"`
(prose) · `research.current`/`research.hermes`→`hermes_research_loop` (the caller, not the writer) ·
`advisory.current`→`api_v3_advisory` (the secondary writer).

Declared `readers` are wrong at least as often: `cio.operator_product` is listed as a reader of
`cio.instrument_records`, `portfolio.watchlist`, `reconciliation.latest`, `sector.momentum.current`
and `industry.momentum.current`, and `[VERIFIED]` reads **none** of them.
`cio.weekly_learning_review` is a fictional module.

**Finding C-12 — the registry is barely used by the code it describes.** `[VERIFIED]`
`resolve_store(` and `load_json_store(` together have only ~20 non-test call sites; most readers
hardcode filenames — precisely the failure the module's own docstring says it exists to prevent.
Combined with C-07 (§5.3), the registry declares schemas it never validates and writers it never
verifies, and publishes both to an operator surface as if they were facts.

### 6.4 Divergent copies — both reported, no winner picked

`$PS` and the served release are the **same inode**, not copies `[VERIFIED]`. The genuine second
live root is the hub, whose `data/` is a real directory.

**`reconciliation.latest` — a three-way split in which today's write was orphaned by a promote**
`[VERIFIED]`:

| path | bytes | mtime | sha256₁₂ |
|---|---:|---|---|
| `$PS/data/reconciliation/state/latest.json` | — | — | **ABSENT (dir does not exist)** |
| `$HUB/data/reconciliation/state/latest.json` | 721 | **2026-08-30 18:41:50** | `c6c01ce9c64b` |
| `…/portfolio-server/a5006df1-…/data/reconciliation/state/latest.json` | 722 | 2026-08-29 18:41 | `cae3760a74d6` |
| `$PS/data/cio/reconciliation_latest.json` | 721 | **2026-08-30 18:41:50** | `c6c01ce9c64b` |

`[CODE]` `cio_reconciliation.persist()` (`:151-155`) writes three destinations, the first being
`Path(__file__).parents[2]/data/reconciliation/state/latest.json` — **release-local, not
`production_state_root()`**. That write landed inside the live release at 18:41; `CURRENT` then
flipped at 19:15 and again at 19:22, and each promote rsynced the **Aug-29** file forward. So the
registry's canonical path serves a day-old payload while the fresh one survives only at two
non-canonical destinations. `resolve_store("reconciliation.latest")` → MISSING;
`control_plane_api` (PROJECT_ROOT) → FOUND-but-stale. **This is the one store the symlink overlay
does not cover.** Per `CLAUDE.md` I am reporting both paths, both hashes, both timestamps and both
verdicts, and picking neither.

Other genuine `$PS` vs `$HUB` divergences, all live today `[VERIFIED]`:

| store | `$PS` | `$HUB` |
|---|---|---|
| `advisory.current` | 4,795,691 · 08-30 10:25 · `b06ff4f398e8` | 3,031,023 · **08-30 17:45** · `0ba216d77d5a` |
| `research.raw` | 300,166 · 08-30 10:25 · `1e5315856982` | 318,542 · **08-30 13:16** · `aa82d2612d5f` |
| `sector.momentum.current` | 8,329 · 08-25 22:04 · `f435fe85a984` | 7,362 · **08-30 01:51** · `6fcc5a74e178` |
| `portfolio.holdings.current` | 232,477 · 08-30 08:00:24.209 · `91517df4f3cc` | 232,477 · 08-30 08:00:24.297 · `7a2a42019acf` |
| `cio.agent_traces` | 19,620,037 · 08-30 19:15 | 12,348,957 · 08-26 10:24 |
| `cio.product.current` | 767,043 · 08-30 19:21 | 602,053 · 08-26 10:31 |
| `cio.theses` | 3,556,867 · 08-30 04:23 | 3,520,352 · 08-28 17:17 |

**Three of these are fresher in the hub than in production.** And `holdings.json` is the sharpest
case: identical size, **88 µs apart, different hashes** — two separate writes, not a copy.

### 6.5 Absolute paths that bypass the registry

`[VERIFIED]` 12 hardcoded absolute literals in `scripts/`, **9 of them into `$HUB`**, touching 4
registered stores: `run_cio_acceptance.py:35`, `reconcile_holdings_canonical_marks.py:25`,
`cio_live_report.py:24,28`, `cio_acceptance_purity.py:18-20`, `research_lane_health.py:296`,
`data_broker/cio_portfolio.py:364`, `cio_reconciliation.py:154`, plus
`claude_escalation_handler.py:312` (into `CURRENT`) and `cio_instrument_record_drill.py:146` (into
`$PS`). For these, `TRADEAI_ROOT` genuinely cannot fix or break the path — unlike C-09.

Separately, the deploy worktree carries **7 git-tracked stale store files** (e.g.
`outcome_checkpoints.jsonl` 9,738 B vs the live 1,502,130 B; `agent_run_traces.jsonl` 2,268 B vs
19,620,037 B). Harmless while the marker probe wins — but they **become the live store the moment
`TRADEAI_ROOT` points at that checkout**, which is exactly what `control_plane_api._state_root()`
does by default (C-11).

---

## 7. `LIVE_UNCONSUMED` — reported prominently and separately

Per the brief: a component that runs, produces, and whose output nobody reads is the most expensive
thing on the list. It costs compute, it produces evidence of health, and it delivers nothing.

### 7.1 Stores with no non-test reader — seven

`[VERIFIED]` as_of 2026-08-30T23:25:45Z, root `$PS`:

| store | size | last write | why it is unconsumed |
|---|---:|---|---|
| `cio.operator_product.current` | 151,654 | **08-30 23:17** | every declared consumer calls `build_operator_product()` and **re-derives**. `aegis_morning_brief_delivery.py:577` merely *labels* its output `"source": "cio.operator_product.current"` without opening the file |
| `cio.operator_product.history` | 51,791 | **08-30 23:17** | only other mention is a string label at `cio_operator_renderers.py:365` |
| `cio.product.history` | 1,180,032 | **08-30 23:26** | only non-test refs are the writer's own path dict, the registry, a lint allow-list and a deploy manifest. Nothing, not even a test, parses it |
| `memory.canonical` | 1,738,563 | 08-30 14:25 | write-only snapshot; the provider's own `_load()` reads the `.jsonl` event log, never the snapshot |
| `research.hermes` | (alias of #15) | — | dead duplicate id; `"research.hermes"` appears in **zero** non-test call sites |
| `cio.notification_policy` | MISSING | — | the filename appears exactly **twice** in the whole repo: the registry declaration and the writer's own constant |
| `learning.weekly` | MISSING | — | **no writer and no reader.** The registry path is drifted: the live file is `data/cio/cio_weekly_learning_reviews.jsonl` (writer `cio_feedback_learning_v1.py:220`, reader `api_v3_cio.py:95`). The declared writer `multi_tier_trade_reviewer` is Postgres-only |

Plus, effectively unconsumed: `cio.delivery_receipts` (sole consumer is the census that iterates
every store id), and `research.raw` / `runtime.audit_claims` (single reader each, and that reader is
only the generic control-plane collection endpoint).

### 7.2 The scheduled producers behind them — verdict `LIVE_UNCONSUMED`

These are the components that hold the verdict. Each is on a schedule, each writes on that schedule,
and nothing reads what it writes.

| module | schedule | evidence it ran | output nobody reads |
|---|---|---|---|
| `scripts/refresh_operator_product.py` | `[VERIFIED]` cron line 986, **`5 */6 * * *`** (every 6 h), cwd `CURRENT`, hub interpreter | artifacts written **08-30 23:17**, ~14 min before as_of | `cio.operator_product.current` **and** `.history` — **both** |
| `scripts/cio_wake_dispatch_entrypoint.py` | `[VERIFIED]` cron line 934, **`*/5 * * * *`** (every 5 min, 24/7), cwd `CURRENT`, hub interpreter | `cio.product.history` written **08-30 23:26**, ~5 min before as_of | `cio.product.history` (its sibling `cio.product.current` **is** read by 6 consumers) |
| `scripts/lib/agent_durable_memory.py` via `advisory_shadow_seed.py`, `build_lesson_candidates.py` | `[VERIFIED]` both are scheduled | `memory.canonical` written 08-30 14:25 | `memory.canonical` snapshot |

**Finding C-13 — `refresh_operator_product.py` is the cleanest `LIVE_UNCONSUMED` component in the
system.** It runs four times a day from the served release, spends a full operator-product build,
writes 203 KB across two stores, and `[VERIFIED]` **nothing outside tests reads either file** —
every consumer re-derives the same data by calling `build_operator_product()` directly. The compute
is spent twice and the artifact is spent zero times.

### 7.3 A caution against acting on this list too quickly

`[VERIFIED]` `git log --reverse` places `cio_specialist_artifact.py`, `cio_notification_policy.py`,
`cio_delivery_receipt.py` and `cio_lesson_bind.py` all at **2026-08-29 — one day before this
census**. Their "only caller is a test" status should be read as **not yet wired**, not as decayed.
They are recorded as `UNKNOWN`, not `DARK`.

Likewise `portfolio.watchlist` (113 days) and `runtime.maturity` (63 days) look stale, but
`[VERIFIED]` I found **no cron or systemd entry for either producer**, so their intended cadence is
`UNKNOWN`. `portfolio.watchlist` is operator-edited (`save_watchlist` has zero callers), which is a
coherent explanation for a 113-day-old file with 8 active readers — but I did not confirm it, so it
stays `UNKNOWN`.

---

## 8. Verdict counts

`as_of` **2026-08-30T23:30Z**, root `/home/johnclaw/r20-r24-exact-main-deploy` @ `79a3f573`,
N = **3,449** tracked `.py` files.

Two tables, deliberately separated. The first is **measured and complete**. The second is
**partial**, and its largest cell is `UNKNOWN`.

### 8.1 Invocation evidence — complete, every file classified

| class | count | share of repo |
|---|---:|---:|
| TEST | 1,029 | 29.8% |
| NO_INBOUND (nothing imports it, no scheduler names it) | 811 | 23.5% |
| IMPORTED_BY_HTTP (in the served server's transitive closure) | 682 | 19.8% |
| SCHEDULED (named by cron or a systemd unit) | 358 | 10.4% |
| IMPORTED_BY_SCHEDULED | 210 | 6.1% |
| IMPORTED_NONLIVE_ONLY | 184 | 5.3% |
| TEST_ONLY_IMPORT | 173 | 5.0% |
| HTTP_ENTRY | 2 | 0.1% |
| **total** | **3,449** | **100%** |

### 8.2 Verdicts — partial, and honest about it

| verdict | count | share of repo | basis |
|---|---:|---:|---|
| `LIVE` | **1,248** | 36.18% | the 1,252-module live-evidence population (358 SCHEDULED + 682 IMPORTED_BY_HTTP + 2 HTTP_ENTRY + 210 IMPORTED_BY_SCHEDULED), **less** the 3 `LIVE_UNCONSUMED` producers and the 1 `ONE_SHOT` module below |
| `LIVE_UNCONSUMED` | **3** | 0.09% | §7.2 — each proven to run *and* proven to have no reader |
| `ONE_SHOT` | **1** | 0.03% | `scripts/run_paper_canary_chain.py`, reached only by cron lines 851–852, both date-guarded to a past date (§4.4). One module, two dead cron lines |
| `UNKNOWN` | **1,168** | 33.86% | 811 NO_INBOUND + 173 TEST_ONLY_IMPORT + 184 IMPORTED_NONLIVE_ONLY — **not adjudicated** |
| `test` (not given a live/dark verdict) | 1,029 | 29.83% | — |
| `DARK` | **0 adjudicated** | — | see below |
| `ORPHANED` | **0 adjudicated** | — | see below |
| `SUPERSEDED` | **0 adjudicated** | — | see below |

**`DARK`, `ORPHANED` and `SUPERSEDED` are reported as zero *adjudicated*, not as zero *existing*.**
This is the census's central honest result and it should not be smoothed over: **1,168 modules (33.86% of the repository) could not be given a verdict from the evidence gathered in this pass.**
Almost certainly a large majority of the 811 `NO_INBOUND` files are genuinely dark. I am not
recording that, because §4 demonstrated four separate mechanisms by which a live component looks
dead in this system — silent-on-success, gate-only logging, cron-redirect versus internal `LOG=`,
and monthly/annual cadence — and because §7.3 found four modules that are one day old and look
identical to abandoned ones. `CLAUDE.md` is explicit: never conclude "dead" on a single observation.

**An honest `UNKNOWN` is a finding, not a failure.** The correct reading of this table is that the
repository is roughly a third demonstrably live, a third tests, and a third unadjudicated — and that
the unadjudicated third is the work item this census exists to scope.

### 8.3 Scheduler totals

| measure | value | as_of |
|---|---:|---|
| cron job lines | **492** | 23:15Z |
| — of which belong to other projects | 2 | 23:15Z |
| — expired (date-guarded to a past date; 1 module) | 2 | 23:15Z |
| distinct tracked modules named by cron | 311 | 23:15Z |
| distinct tracked modules named by systemd | 54 | 23:20Z |
| union of scheduler-named modules | **358** | 23:20Z |
| tradeai-family user timer units | 78 (65 enabled / 13 disabled) | 23:20Z |
| system-level tradeai units | 3 | 23:20Z |
| lane-registry entries (live, over HTTP) | **56** | 23:20:19Z |
| canonical stores registered / present / missing | **34 / 28 / 6** | 23:25:45Z |
| stores with no non-test reader | **7** | 23:25:45Z |
| versioned schema literals / zero-consumer | **437 / 376 (86%)** | 23:25Z |
| schema literals ever read back at runtime | **9 (2%)** | 23:25Z |

---

## 9. For PART 2 and later parts

- **C-06 crosses the boundary.** `ControlPlane@v1.0.0` is declared independently in
  `scripts/lib/control_plane_contract_v1.py:14` and
  `apps/command-center-v3/src/control-plane/contractV1.ts:3`. The TS side has 2 consumers; the
  Python side has zero. **Nothing enforces that the two strings match.** PART 2 should establish
  whether any operator surface would detect a skew — from the backend side, nothing would.
- **C-10 is a surface finding as much as a backend one.** The control-plane store surface serves the
  **stale 19-entry JSON**, so **15 registered stores are invisible on it**. If PART 2 finds a page
  listing stores, it is listing 19 of 34. That page is not wrong about what it shows; it is silent
  about what it omits.
- **C-07 / C-12 — the registry publishes unvalidated metadata to the GUI.**
  `control_plane_api._stores()` echoes `writer` and `schema` fields straight through, and §6.3 shows
  at least 11 declared writers naming modules that do not exist or do not write. PART 2 should
  establish whether these strings are rendered to the operator, and whether they are rendered as
  facts.
- **C-01 constrains PART 2's method.** `CURRENT` rotated **three times in fifteen minutes** during
  this census. Any PART 2 measurement taken against `CURRENT` must record the concrete release hash
  or it will not be reproducible.
- **C-09 should be corrected in `CLAUDE.md`.** The standing rules cite a root-insensitivity that
  measurement refutes. Whoever owns that file should fix the example; I have not edited it.

---

## 10. Method register

Every claim above carries `[VERIFIED]`, `[CODE]` or `[DOC-CLAIM]`. The techniques that **changed a
conclusion** during this census, each of which had already cost this programme time before:

- **`compile()` over raw bytes, never `ast.parse`** — §3.1. All 3,449 files compile.
- **Path-suffix resolution against `git ls-files`, never basename grep** — M-02/§3.4. Basename
  matching claimed 525 scheduled modules; the true figure is 358. Three spot-checked members of the
  525 were false positives.
- **Durable artifacts, never log existence or mtime, for `last_ran`** — M-03/§4. Nineteen jobs
  looked stale; **none** was dead.
- **Reading the producer before believing an empty surface** — M-01/§1.4. I withdrew a false defect
  against a healthy endpoint whose zero was produced by my own parser.
- **Checking cron *and* both systemd scopes** — C-04. `tradeai-continuous.timer` is disabled at user
  level and enabled and firing at system level.
- **Following symbols to the real write call** — §6.2. Two writes in the registry
  (`cio.product.current`, `cio.lesson_binds`) are unreachable by grepping their filename; one reader
  is a local import inside a `try:`.
- **Testing the specific expected exit code**, and `${PIPESTATUS[0]}` rather than `$?` after a pipe.
- **`atime` was not used as evidence anywhere in this document.** The filesystem is `relatime`.

Claims I made during this census and then **withdrew after measurement refuted them**: the
lane-registry "empty endpoint" defect (§1.4), and the 525-module scheduled count (§3.4). Both are
left in the document rather than deleted, per the working-style rule that the failures belong in the
write-up and not just the final state.

---

# ADDENDUM A — the checkout-relative escalation (C-03 follow-up)

Requested by the coordinator on operator escalation. Scope: which scheduled jobs resolve against the
dev tree, what each is failing on from durable evidence, which fail silently, and **where the
resolution actually happens**. READ-ONLY: no cron edited, no scheduler entry installed or removed.

**Pin.** `CURRENT` → `4baf677d-main-exact-phase2-20260830-193256` `[VERIFIED]` `readlink -f` at
2026-08-30T23:43:42Z. It had rotated twice more since §0.1 (`a9389f67` → `865a4a1d` → `a5006df1` →
`4baf677d`), so every claim below names the concrete release dir. Hub = `$HUB` =
`/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`; `$REL` =
`/home/johnclaw/trade-ai-releases/portfolio-server/4baf677d-main-exact-phase2-20260830-193256`.

## A.0 The escalation's central premise is wrong, and the correction changes the fix

The brief states the two morning jobs crash on a bug **"already fixed in the served release"**, and
infers that a promote failing to reach 93% of the cron tree is the cause. **The first half does not
hold, and therefore neither does the inference.**

`[VERIFIED]` the implicated files are **byte-identical** between the hub and the served release:

```
diff $HUB/scripts/lib/cio_operator_renderers.py  $REL/scripts/lib/cio_operator_renderers.py  -> IDENTICAL
diff $HUB/scripts/lib/research_prompt_context.py $REL/scripts/lib/research_prompt_context.py -> IDENTICAL
```

`[VERIFIED]` and the failure reproduces **from the served release**, using the release's own code,
by replicating exactly what `python scripts/X.py` does to `sys.path` (`sys.path[0]` = the *script's*
directory, not the repo root):

```
served release (4baf677d): import scripts.lib.brief_semantic_dedupe -> FAILS: No module named 'scripts'
same release, root inserted:                                        -> OK
```

**Finding C-14 — this is an invocation-style defect, not a tree-version defect. Promoting to the hub
would not fix it.** The failing jobs would fail identically if their cron lines were repointed at
`CURRENT` today. C-03 (456 of 492 cron lines running in the hub) remains true and remains worth
fixing, but **it is not the cause of these crashes**, and a fix aimed at the working directory would
leave every one of them broken. This is why the coordinator's instruction to fix at the resolution
layer rather than at the cron's working directory is the right call — more so than the brief's own
reasoning implies.

## A.1 Where the resolution actually happens — the named line

`[CODE]` `scripts/portfolio_server.py:100-102`, and **nowhere else in any scheduled path**:

```python
import sys as _sys_root  # noqa: E402
if str(PROJECT_ROOT) not in _sys_root.path:
    _sys_root.path.insert(0, str(PROJECT_ROOT))
```

Its own comment states the failure mode verbatim: *"without the root on sys.path the web server
raises 'No module named scripts'."*

Three facts make this the whole story:

1. `[VERIFIED]` **`scripts/__init__.py` does not exist.** `scripts` is an implicit namespace
   package, so `import scripts.lib.X` resolves **only** when the repository root is on `sys.path`.
2. `[VERIFIED]` **there is no global bootstrap.** No `sitecustomize.py` in the repo or the venv; the
   only `.pth` file on the venv is `distutils-precedence.pth`. Nothing injects the root
   process-wide.
3. `[VERIFIED]` **851 tracked modules use absolute `scripts.` imports — 3,244 statements**, of which
   **1,511 are module-level** (fail at import) and **1,733 are indented inside functions** (latent:
   fail only when that code path executes). 260 of the 851 are in `scripts/lib/`, i.e. the shared
   library layer that cron entrypoints load.

So the repo-root resolution lives **inside the web server entrypoint**. Every scheduled job that
reaches a `from scripts.…` import has no equivalent, and crashes. That is the resolution layer, and
that is where a fix belongs.

### A.1.1 The dual-path fallback cannot work — and that is why this went unnoticed

The codebase anticipated this and guards it in five places with a two-arm import. `[CODE]`
`scripts/send_morning_brief.py:145-148` (identical shape in `aegis_morning_brief_delivery.py:614-617`,
`morning_command_digest.py:75-77`, `portfolio_live_monitor.py:323-325`):

```python
try:
    from lib.cio_operator_renderers import deliver_morning
except ImportError:
    from scripts.lib.cio_operator_renderers import deliver_morning  # type: ignore
```

`[VERIFIED]` `issubclass(ModuleNotFoundError, ImportError)` → **True**.

The first arm *locates* `lib.cio_operator_renderers` successfully — `scripts/` is on `sys.path`. It
then fails **inside** that module, at its line 11, on `from scripts.lib.brief_semantic_dedupe`. That
`ModuleNotFoundError` is caught by `except ImportError`, and the fallback arm imports **the same
module by its other name**, which fails at the same line 11 for the same reason — this time
uncaught.

**Finding C-15 — the fallback is structurally defeated: both arms load the same file, and the
failure is inside it, not in locating it.** The guard was written for "this module is not on the
path", but the actual defect is "this module's own import is unsatisfiable". A guard that cannot
distinguish the two converts a clear failure into a confusing chained traceback and buys nothing.

## A.2 Which scheduled jobs are actually failing, and on what — durable evidence

Static reachability gives an **upper bound**, not a verdict. Recomputed over the 358 scheduler-named
entrypoints `[VERIFIED]`:

| exposure class | count |
|---|---:|
| EXPOSED_LATENT (deferred `scripts.` import in reach, no root bootstrap) | 203 |
| NO_SCRIPTS_IMPORT | 88 |
| EXPOSED_HARD (module-level `scripts.` import in reach, no root bootstrap) | 49 |
| BOOTSTRAPPED (entrypoint itself puts the root on `sys.path`) | 18 |

**I do not report 49 + 203 as "failing".** Many demonstrably run — `cio_wake_dispatch_entrypoint.py`
is classed EXPOSED_HARD and `[VERIFIED]` writes its store every 5 minutes. A module-level
`scripts.` import somewhere in the closure only fires if that module is actually loaded on the taken
path. The static figure bounds the risk; the logs establish the fact.

`[VERIFIED]` sweeping **every** `$HUB/logs/*.log` for `No module named 'scripts'` returns exactly
seven files, resolving to **five distinct scheduled jobs**:

| # | job | schedule | last durable evidence | what it fails on | effect |
|---|---|---|---|---|---|
| 1 | `scripts/send_morning_brief.py` | cron 186, `0 8 * * 1-5` | log ends **at the traceback**, mtime 2026-08-28 08:00:01 | `send_morning_brief.py:148` → `cio_operator_renderers.py:11` | **hard crash — no morning brief delivered** |
| 2 | `scripts/aegis_morning_brief_delivery.py` | cron 252, `5 8 * * 1-5` | log ends **at the traceback**, mtime 2026-08-28 08:05 | `aegis_morning_brief_delivery.py:542` → same line 11 | **hard crash — no Aegis brief delivered** |
| 3 | `scripts/auto_research.py` | cron 164, `0 20 * * 1-5` | log ends at traceback, mtime 2026-08-28 20:00 | `research_prompt_context.py:316` (deferred, inside `build_research_prompt_context`) | **crash mid-run**, after "Found 5 research triggers", on the first symbol (AESP) |
| 4 | `scripts/aegis_overnight.py` | cron 326 + `aegis-overnight.timer` | 2026-08-29 20:03 | same renderer chain, inside a phase | **silent — see A.3** |
| 5 | `portfolio_orchestrator` (`run_portfolio`) | daily ~07:30 | 2026-08-28 07:38 | morning-command bundle send | **silent — see A.3** |

**Regression boundary, from durable evidence** `[VERIFIED]` — `$HUB/logs/aegis_brief.log`:

```
[aegis-brief] Morning brief delivery starting — 2026-08-27T08:05:01.828759
  Telegram: sent
  Export: …/aegis_morning_brief_2026-08-27.md
[aegis-brief] Delivery complete
[aegis-brief] Morning brief delivery starting — 2026-08-28T08:05:01.675499
Traceback (most recent call last): … ModuleNotFoundError: No module named 'scripts'
```

Last good run **2026-08-27 08:05**, first bad run **2026-08-28 08:05**. `[VERIFIED]` the import was
introduced by commit **`6b032f1e`** (2026-08-26 09:23:47 -0400, *"feat(r18-data): finish operator
product convergence locally"*), which created `scripts/lib/brief_semantic_dedupe.py` and added the
module-level `from scripts.lib.brief_semantic_dedupe` to `cio_operator_renderers.py`. It is an
ancestor of the hub's HEAD `[VERIFIED]`.

**Both morning briefs have been undelivered on every weekday run since, and will fail again on
Monday 2026-08-31 08:00.** Aug 29–30 were a weekend, so only one weekday has elapsed — which is why
nothing had escalated yet.

### A.2.1 Third-party import errors in the same logs are *not* this bug

Guarding against a false aggregate: `[VERIFIED]` the same log sweep surfaces `psycopg2`, `dotenv`,
`numpy` and `pandas_ta` failures, and **they are unrelated and mostly historical.** Every `psycopg2`
/ `dotenv` / `numpy` traceback dates to **2026-07-01/02** (e.g. `agent_event_router.log`:
`[2026-07-01 23:30:02] FATAL`), and `[VERIFIED]` those packages were installed into
`.venv/lib/python3.14/site-packages` on **2026-07-01 23:41 / 07-02 00:04** — the failures stop where
the install begins. Their logs have fresh mtimes only because successful runs keep appending. This
is M-03 again, in the opposite direction: **a fresh mtime on a log containing an old error is not
evidence of a current failure.**

One real environment defect did surface `[VERIFIED]`: the hub venv is internally inconsistent —
`pyvenv.cfg` declares `version = 3.13.7`, `executable = /usr/bin/python3.13`, while
`.venv/bin/python` resolves to `/usr/bin/python3.14` (Python 3.14.4), and **both** a `python3.13`
(256 entries) and a `python3.14` (276 entries) `site-packages` exist. `pandas_ta` is absent from the
3.14 tree, so `indicator_engine` degraded for a period. It imports cleanly today. Recorded as a
finding; the interpreter/venv reconciliation is an operator decision, not part of this fix.

## A.3 Silent failures — three distinct mechanisms

Asked specifically: succeeding by exit code while producing nothing, or writing to a tree nobody
serves.

**(a) `aegis_overnight` — a failed phase inside a "COMPLETE" job.** `[VERIFIED]`
`$HUB/logs/aegis_overnight.log`:

```
[2026-08-28 20:14:57]   PHASE START: morning_brief_delivery
[aegis-brief] Morning brief delivery starting — 2026-08-28T20:14:57.905591
[2026-08-28 20:14:57]   PHASE FAILED: morning_brief_delivery — 0.0s — No module named 'scripts'
[2026-08-28 20:14:57] AEGIS OVERNIGHT COMPLETE — aegis-overnight-20260828-200001 — 896s total
[telegram] Suppressed (P1_DIGEST): Aegis Overnight Complete (14min)  Briefs: 15 | Stops: 1
```

The job records the phase failure, then declares itself **COMPLETE** and emits an operator digest
headed *"Aegis Overnight Complete"* claiming **"Briefs: 15"**. The brief-delivery phase produced
nothing. This is precisely `CLAUDE.md`'s governing principle: a component reporting success is not
evidence that it did anything.

**(b) `portfolio_orchestrator` — a failed stage inside "all pipeline stages completed".**
`[VERIFIED]`:

```
  [morning-command] Bundle send failed: No module named 'scripts'
  …
  [notifications] ✅ Daily digest sent via Gmail
all pipeline stages completed
```

**(c) `cio_command_center.py:1620-1624` — a bare `except Exception` that degrades the operator
surface with no log line at all.** `[CODE]`:

```python
try:
    from scripts.lib.cio_operator_renderers import command_center_view
    home["operator_product"] = command_center_view(operator_product)
except Exception:
    home["operator_product"] = operator_product
```

When the import fails, the Command Center home silently serves the **raw** operator product instead
of the rendered view. Nothing is logged, nothing is flagged, and the key
`home["canonical_cio_source"] = "cio.operator_product.current"` is still set on the very next line —
so the surface **labels the payload with a provenance it did not actually render through**. This one
lands on PART 2's surface; see A.5.

**(d) Adjacent, same class, found while verifying (b).** `[CODE]`
`scripts/trade_ai_orchestrator.py:783-785`:

```python
else:
    _err("run_health", f"{_health_status} — {len(scored)} symbols (min {min_symbols}) — {_health_reasons}")
    if not allow_underfilled:
        print(f"\n  ⚠️  Run is {_health_status}. Use --allow-underfilled to proceed anyway.\n")
```

There is **no `return`, no `sys.exit`, no `raise`** — the flag suppresses a message and nothing else,
so the pipeline proceeds regardless. `[VERIFIED]` every screener run back to 2026-08-27 has flagged
`run_health` ❌ and every one still reported `✅ v12 complete`, including four `RUN_FAILED — 0 symbols
(min 40) — ['CSV_EMPTY']` runs on 2026-08-30 that nonetheless published a dashboard, PDF, DOCX and
updated `dashboard_live.html` — the file the operator is told to keep open. Weekday 2026-08-27 runs
show `RUN_UNDERFILLED — 15..17 symbols` with `ONLY_ONE_SCREENER_RETURNED`, so this is not a weekend
artifact. **A gate whose failure branch only prints is not a gate.**

## A.4 Proposed fix at the resolution layer

Read-only: proposed, not applied. Precise enough to hand to an implementer, with what it breaks.

**The chokepoint already exists and is empty.** `[VERIFIED]` `scripts/lib/__init__.py` is present
and **0 bytes**. Every failing chain in A.2 passes through it, because each entrypoint's first arm is
`from lib.<module> import …`, which executes `scripts/lib/__init__.py` **before** any `lib.*` module
body runs — therefore before the `from scripts.lib.…` line that fails.

**Proposal P-1 — put the root resolution in `scripts/lib/__init__.py`:**

```python
# scripts/lib/__init__.py — repo root on sys.path so `from scripts.lib.X` resolves
# for every caller, not only the web server (portfolio_server.py:100-102).
# `scripts` is an implicit namespace package (no scripts/__init__.py), so it is
# importable only when the repository root is on sys.path.
import sys as _sys
from pathlib import Path as _Path
_ROOT = str(_Path(__file__).resolve().parents[2])
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
```

`[VERIFIED]` proof of concept, under the exact cron `sys.path` (`sys.path[0]` = `$HUB/scripts`), with
the root inserted before importing `lib.*`:

```
lib.cio_operator_renderers imported OK -> $HUB/scripts/lib/cio_operator_renderers.py
deliver_morning present: True
```

`parents[2]` from `scripts/lib/__init__.py` is the repo root, and it is **derived from `__file__`**,
so it follows whichever checkout is executing — hub or release — and needs no env var. It cannot
re-break C-09-style, because it never consults `TRADEAI_ROOT`.

**What P-1 would break — stated plainly, because this is the real risk.** Putting the root on
`sys.path` makes **both** `lib.X` and `scripts.lib.X` importable in every process. Python treats
those as **two distinct module objects**, with two distinct copies of every class. That is not
hypothetical here: `docs/CHANGELOG.md` records exactly this defect — *"`cio_portfolio` imports
`DomainEvidence` from `lib.*` while the snapshot imports it from `scripts.lib.*` — two distinct
class objects, so `isinstance` was False for **8 of 18 broker collectors**"*. P-1 does not create
that hazard (it exists today wherever the root is already present, including the entire web server),
but it **extends it to every scheduled process**. Any `isinstance`, `except SomeError`, or module-level
singleton that spans the two import spellings can silently change behaviour.

Mitigations, in the order I would sequence them:

1. **Land P-1 with an import-identity assertion**, not bare. Have `scripts/lib/__init__.py`, or a
   startup self-check, verify that `sys.modules.get("lib.cio_lineage") is sys.modules.get("scripts.lib.cio_lineage")`
   wherever both are loaded, and fail loudly rather than diverge silently. A dual-identity that
   announces itself is recoverable; one that does not is the 8-of-18 defect again.
2. **Then normalise the spellings.** `[VERIFIED]` 3,244 `scripts.`-prefixed statements across 851
   modules. Converting them to the `lib.` form (or the reverse) is mechanical but large, and
   collapsing to one spelling is the only change that removes the hazard rather than containing it.
   That is a separate wave, and it should not gate the morning briefs being restored.

**Alternatives considered and rejected:**

- *Add `scripts/__init__.py`.* Makes `scripts` a regular package, but does **not** put the root on
  `sys.path`, so `import scripts.lib.X` still fails from a cron entrypoint. It does not fix the bug.
- *A `sitecustomize.py` or `.pth` in the venv.* Would work process-wide, but it is environment
  configuration outside the repository, invisible to code review, not carried by a promote, and it
  would apply to unrelated projects sharing the interpreter. It moves the resolution further from
  the code, which is the opposite of the ask.
- *Editing the cron lines' working directory or `PYTHONPATH`.* Explicitly ruled out by the
  coordinator, and correctly: `[VERIFIED]` it also would not work — `python scripts/X.py` sets
  `sys.path[0]` to the **script's** directory regardless of `cwd`, so changing the working directory
  alone does not put the root on the path.

**Fixing C-15 as well.** Independently of P-1, the five two-arm fallbacks should not catch
`ImportError` broadly. Catching `ModuleNotFoundError` **and re-raising when `err.name` is not the
module being located** would have surfaced this on day one instead of producing a chained traceback
that reads like a path problem.

**Not proposed, deliberately.** I have not proposed removing the two expired cron lines (§4.4),
repointing any cron line from the hub to `CURRENT`, or reconciling the 3.13/3.14 venv. Each is an
operator decision under `CLAUDE.md`'s operator-only list or adjacent to it.

## A.5 Hand-off to PART 2

- **A.3(c) is a surface defect.** `cio_command_center.py:1620-1624` silently substitutes the raw
  operator product for the rendered `command_center_view` on import failure, then still stamps
  `home["canonical_cio_source"] = "cio.operator_product.current"`. PART 2 should establish what the
  Command Center home renders when that except fires, and whether the provenance label is displayed
  — because it currently asserts a rendering path that did not run.
- **The morning brief is an operator-facing deliverable and it has been silently absent since
  2026-08-28.** If PART 2 finds a surface that reports brief delivery status, it should be checked
  against A.2 — `aegis_overnight` emits *"Aegis Overnight Complete … Briefs: 15"* on a run whose
  brief-delivery phase failed in 0.0s.
- **`dashboard_live.html` is being overwritten from 0-symbol runs** (A.3(d)). PART 2 owns whether
  that file is an operator surface; if it is, it has been showing an empty scan published under a
  `✅ v12 complete` banner.

## A.6 Corrections to my own work in this addendum

Kept per the coordinator's instruction that a census showing its corrections is more trustworthy
than one reading clean.

- **My first exposure computation was unsound.** I classed an entrypoint `BOOTSTRAPPED` if *any*
  module in its transitive closure put the root on `sys.path`. That is wrong: a bootstrap deep in
  the graph cannot help an import that fires before it is reached. `[VERIFIED]` the error was
  detectable — it classed `scripts/auto_research.py` as `BOOTSTRAPPED` while the log shows it
  crashing on exactly this bug. Corrected to require the **entrypoint itself** to bootstrap, which
  moved the counts from 256/3 to 18/49 and produced the table in A.2.
- **My initial regex for self-bootstrapping matched `sys.path.insert(0, str(PROJECT_ROOT / "scripts"))`
  as if it were a root insert.** It is not — it inserts `scripts/`, which is the very condition under
  which `import scripts.*` fails. Tightened to match only the repo root.
- **I began writing up the `psycopg2`/`numpy`/`dotenv` failures as current.** They are from
  2026-07-01/02 and were resolved by a package install hours later; only the fresh log mtime made
  them look live (A.2.1).
