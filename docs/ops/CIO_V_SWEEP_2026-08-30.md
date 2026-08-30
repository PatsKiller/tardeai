# CIO validation sweep V1–V5 — 2026-08-30

Agent A1, Wave A. Authority **READ_ONLY_ADVISORY**, **MBI_BEHAVIOR=0**.
Nothing promoted, merged, deployed. No cron installed. No Telegram, no vendor call.

Tags: `[VERIFIED]` = a command ran to **exit 0** today and its output is quoted ·
`[CODE]` = source read · `[DOC-CLAIM]` = a document asserts it.

Served release under test: `CURRENT -> 66f97259-main-exact-phase2-20260830-112142`.
Branch base: `origin/main` = `6bae6529`.

---

## 0. The finding that reframes the rest

**V0 is merged to `main` but NOT deployed. Both V0 defects are still live in the served release.** `[VERIFIED]`

```
$ python sweep.py /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
ROOT   : /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
SCANNED: 3447 .py files
FAILED : 1
  FAIL  scripts/cio_event_lifecycle_census.py
        from __future__ imports must occur at the beginning of the file (line 26)
BOM    : 1
  BOM   scripts/atm_position_reconciler.py
AST-BLIND (compile fails, ast.parse passes): 1
  BLIND scripts/cio_event_lifecycle_census.py
```

The same sweep over `origin/main` (this worktree): **3448 files, 0 failures, 0 BOMs.**

The prompt states both files were fixed. That is true of `main` and false of the tree
that actually runs. `PROMOTE OK` was not the same event as "the fix is serving".
The census therefore still cannot run *in the served release*; every census number in
this document was produced by running the **fixed** script from `main` against the
**served release's data** (`--root` defaults to `CURRENT`).

---

## 1. V1 — `compile()`, the gates, and the mutation test

### 1.1 The prompt's rule is right, but for one specific reason — and one of its two examples doesn't hold

Measured on this box, Python 3.14.4 `[VERIFIED]`:

| input | `ast.parse` | `compile()` |
|---|---|---|
| misplaced `from __future__` | **OK** | **SyntaxError** |
| UTF-8 BOM, read as **bytes** | OK | OK |
| UTF-8 BOM, read as **str** | SyntaxError | SyntaxError |

Two corrections that matter operationally:

1. **`compile()` beats `ast.parse()` on `__future__` placement only.** That rule is
   enforced in the compile/symbol-table phase, not the parser. This *is* the defect
   that cost 10 hours, so the rule earns its place.
2. **On BOM the two are identical.** The axis there is **bytes vs str**, not
   compile vs parse. And a BOM does not actually break anything: `[VERIFIED]`
   a BOM'd script both **runs** (`exit 0`, prints) and **imports** cleanly via
   `exec_module`. The BOM on `atm_position_reconciler.py` was a defect *for gates
   that read source as `str`* — not a reason the file could not run. The two V0
   defects were not the same severity: one made a file unrunnable, the other did not.

Correct form for a runtime-truth gate: **`compile(path.read_bytes(), ...)`** — bytes,
because the UTF-8 codec strips a BOM exactly as the interpreter does.

### 1.2 Gate inventory — by following symbols, not filenames

Grep false positives explicitly cleared `[CODE]`: `ingest_tos_watchlists.py:29 _parse_file`
(CSV, not Python), `--source-only` (skips deployed-DB posture guards, not a syntax mode),
`check_no_secrets.py` (11 `compile(` hits, all `re.compile`).

**The single repo-wide compile sweep is `tests/test_every_script_compiles.py`.**
`[VERIFIED]` it is referenced by **nothing**:

```
$ grep -rn 'test_every_script_compiles' .github/ scripts/ tests/conftest.py pyproject.toml
$ echo $?
1
```

`pyproject.toml` has no `[tool.pytest.ini_options]`; no `pytest.ini`/`setup.cfg`/`tox.ini`
exists; every workflow names its test files explicitly and none runs `pytest tests/`.
**The one gate that would have caught the outage fires only if a human types its name.**
That is the deeper reason the census stayed broken for 10 hours — not merely that other
gates used `ast.parse`, but that the gate which used `compile()` was never invoked.

Other gates, by ingestion mode `[CODE]`:

| gate | call | input | verdict |
|---|---|---|---|
| `scripts/check_dark_contracts.py:147` | `ast.parse(read_text(errors="ignore"))` | str | **unsound — fixed below** |
| `scripts/broker_write_scanner.py:92` | `ast.parse(src)`, `except SyntaxError: return findings` | str | **failed OPEN — fixed below** |
| `scripts/lib/cio_telegram_canary.py:156` | `ast.parse(read_text())` | str | unguarded; SyntaxError propagates (acceptable) |
| `tests/*` `py_compile.compile(..., doraise=True)` | 165 sites / 57 files | path | sound (full compile path) |
| `tests/*` `spec.loader.exec_module` | 52 sites | bytes | sound |
| 11 × `scripts/session*_validate.py` | `ast.parse` | str | all **orphans** — no caller anywhere |

**CI/shell compile gates.** Sound and gating: `active-trader-policy-ci.yml:47`
(`compileall`), `watch-quality-governance-ci.yml:73`, and four deploy scripts that
`py_compile || die` before deploying. **Not gating:**

- `.github/workflows/defense-sectors-ci.yml:53` — `python -m py_compile \ ... 2>&1 | tee /tmp/defsec_compile.out`
  then `echo "py_compile exit=${PIPESTATUS[0]}"`. No `set -o pipefail`, step is
  `if: always()`. The real status is **printed and discarded**. `[CODE]` This is the
  standing `$?`-after-a-pipe trap, live in CI today. **Outside my declared write scope
  (`.github/`) — reported, not fixed.**
- `.github/workflows/agentic-mvl-ci.yml:58` — `continue-on-error: true`.

### 1.3 Gates that MODIFY source — do they re-verify?

`[CODE]` Only one does.

| writer | re-verifies? | note |
|---|---|---|
| `scripts/coder_dispatch.py:257` | **YES** — `py_compile` subprocess at :272, returns False on failure | and it is **cron-scheduled** (`crontab_backup.txt:600`, `0 9-18/3 * * 1-5 --from-queue --apply`) |
| `scripts/lib/safe_text_edit.py:114` | **NO** — line-ending style only | this is the repo's *sanctioned* editing helper (`check_line_endings.py:108` recommends it); no production caller |
| `phase2_weekly.py:322`, `phase2b_analyst.py:137,449` | partial — `ast.parse` **before** write | a misplaced `__future__` insertion passes and is written |
| `phase1b_fix.py:71,116` | **NO** — writes unconditionally; `ast.parse` after, advisory, never exits non-zero | damage already on disk |
| `tradeai_fix/scripts/continuous_runner_patch.py:116` | **NO** — verification is a substring check | |

### 1.4 Mutation test of the dark-contract / zero-consumer gate — **IT FAILED**

Mutation: reproduce commit `aa21559c` exactly — hoist `NO_CONSUMER_REASON` above
`from __future__ import annotations` in `scripts/cio_event_lifecycle_census.py`.

```
compile()  : SyntaxError -> from __future__ imports must occur at the beginning of the file (line 23)
ast.parse(): OK   <-- ast.parse is BLIND to this
```

**Before the fix** `[VERIFIED]`:

```
$ python scripts/check_dark_contracts.py --fail-on-new
DARK_MUTATED_EXIT=0
zero-consumer             : 37
  declared NO_CONSUMER_REASON: 8
  NEW (unexplained)       : 0
```

**Exit 0, byte-identical to the clean baseline**, on a file that cannot compile, cannot
be imported and cannot be run. The gate read its own required declaration back out of a
dead file and called it green. **The gate was unsound against the exact defect its own
declaration requirement induces.**

**Fix applied** (`scripts/check_dark_contracts.py`): added `module_compiles()` using
`compile(read_bytes())`, run over the whole definer corpus **before** the consumer
verdict; any uncompilable module is reported and forces exit 1.

**After the fix** `[VERIFIED]`:

```
$ python scripts/check_dark_contracts.py --fail-on-new     # clean tree
FIXED_CLEAN_EXIT=0
uncompilable modules      : 0

$ python scripts/check_dark_contracts.py --fail-on-new     # mutated tree
FIXED_MUTATED_EXIT=1
FAIL: a module under scripts/ does not compile. Its declaration, its
consumers and its schemas are all unverifiable until it does.
  scripts/cio_event_lifecycle_census.py: from __future__ imports must occur at the beginning of the file (line 23)
```

Locked in by `tests/test_dark_contract_gate_compiles_first.py` (4 tests, `[VERIFIED]`
exit 0), which plants the shape in a temp probe module and includes a guard-the-guard
test asserting the probe is still `ast.parse`-clean and `compile`-broken, so the test
cannot go vacuous.

### 1.5 Other V1 repairs (in scope)

- `tests/test_every_script_compiles.py` — `_python_files()` used `glob("*.py")` over
  exactly `("scripts", "scripts/lib")`, reaching **2025** files and leaving **384** in
  37 nested subpackages (`scripts/active_trader`, `agent_runtime`, `brokers`, `moomoo`,
  `lib/options_pipeline`, `lib/hermes_*`, …) outside the only repo-wide sweep.
  Changed to `rglob`. `[VERIFIED]` coverage **2025 → 2409 (+384)**, 5 passed.
- `scripts/broker_write_scanner.py:92` — `except SyntaxError: return findings` returned
  an **empty list**, the same value a clean file returns, so an unparseable script was
  issued a clean broker-write bill of health. Now emits an `unscannable` finding
  (fails closed). `[VERIFIED]` still `ok=True`, 0 findings on the clean tree.

---

## 2. V2 — regenerated metrics

All runs today against the served release. `producing script` exit codes are the
literal value; `0` was the expected value for every runnable producer here.

| metric | published value | regenerated today | producing script | exit | verdict |
|---|---|---|---|---|---|
| lineage `complete_to_checkpoint` | **406 / 752 (54.0%)** | **448 / 803 (55.79%)** | `cio_lineage_completion_report.py --path CURRENT/…` | 0 | **STALE** |
| event lifecycle, weighted full | **2.17%** | **2.17%** | `cio_event_lifecycle_census.py` | 0 | **FRESH_SCRIPT_STALE_SOURCE** |
| event lifecycle, unweighted mean | 67.16% | 67.16% | `cio_event_lifecycle_census.py` | 0 | **STRICKEN** — see §2.1 |
| catalyst family full-lifecycle | **1.49%** | **1.49%** | `cio_event_lifecycle_census.py` | 0 | **FRESH_SCRIPT_STALE_SOURCE** |
| identity production resolvable | **98.9%** | **98.9%** (90/91) | `cio_identity_confidence_census.py` | 0 | **VERIFIED_FRESH** (denominator drifted 89→91) |
| identity confidence score | 0.7996 | **0.9666** | `cio_identity_confidence_census.py` | 0 | **STALE** |
| identity `stamped_pct` | 5.6% | **89.0%** | `cio_identity_confidence_census.py` | 0 | **STALE** |
| arc `research_checkpoint` | 436 | **478** | `cio_lineage_completion_report.py` | 0 | **STALE** |
| arc `cio_notification` | 29 | 29 | `cio_lineage_completion_report.py` | 0 | **VERIFIED_FRESH** |
| first open stage · research | 640 | **685** | `cio_lineage_completion_report.py` | 0 | **STALE** |
| first open stage · cio | 112 | **118** | `cio_lineage_completion_report.py` | 0 | **STALE** |
| SCHG Surface A | EXITED | EXITED | `cio_identity_confidence_census.py` | 0 | **VERIFIED_FRESH** |
| P2-WS5 WATCH count | 30 | **34** | `cio_identity_confidence_census.py` | 0 | **STALE** |
| P3 live spine rows | 129 | **131** | `cio_instrument_record_drill.py` | 0 | **STALE** |
| P9 `missing_cross_id_hits` | 144 | 144 | `cio_registry_orphan_census.py` | 0 | **VERIFIED_FRESH** |
| P9 `orphan_hits` | 3 | 3 | `cio_registry_orphan_census.py` | 0 | **VERIFIED_FRESH** |
| P5 orphan_workflow rate | 50% | **44%** | `cio_specialist_sample_audit.py` | 0 | **STALE** (the FAIL still reproduces) |
| P5 orphan_instrument rate | 36% | **37%** | `cio_specialist_sample_audit.py` | 0 | **STALE** (FAIL reproduces) |
| P4 budget live select | 5 (incl. `SLEEVE:CASH`) | **4** (no CASH slot) | `cio_research_budget_report.py` | 0 | **STALE** |
| P4 `live_overlay_root`, `stores_live_overlay`, `live_budget_report` | present in evidence JSON | — | **none — no script emits these keys** | — | **NO_PRODUCER** |
| `/api/v2/health` | 200 | 200 | `curl` | 0 | **VERIFIED_FRESH** |
| `/v3/cio` | 200 | 200 | `curl` | 0 | **VERIFIED_FRESH** |
| `/api/v3/cio/home` | 200 | 200 | `curl` | 0 | **VERIFIED_FRESH** |
| NOW `origin/main` pin | `015a7891` (Merge #702) | `6bae6529` (3 merges later) | — | — | **NO_PRODUCER** (hand-stamped) |
| DRIVE / gog upsert | FAIL | not attempted | — | — | unverified |

### 2.1 The unweighted mean is STRICKEN, not graded

`[VERIFIED]` recomputed from members rather than trusting the aggregate:

```
catalyst_earnings              accepted=39478  full%=1.49
sector_industry                accepted=  154  full%=100.0
security_holdings_exit_reentry accepted=  120  full%=100.0
total 39752   catalyst share % 99.31
unweighted mean floor if catalyst -> 0: 66.67
```

The catalyst family is **99.31%** of the denominator. The other two families are n=154
and n=120, both at 100%. If the catalyst family collapsed to **zero**, the headline
would still read **66.67%**. A metric whose floor is 66.67% cannot report failure, so
it gets no verdict — it gets struck. The weighted figure (2.17%) is the one that moves.

### 2.2 Why the lifecycle percentages are FRESH_SCRIPT_STALE_SOURCE

`[VERIFIED]` the catalyst family's three stores, on a day that is 2026-08-30:

```
2026-08-27 13:57  CURRENT/data/cio/catalyst_graph_latest.json          (3 days stale)
2026-08-24 08:34  CURRENT/data/portfolios/state/earnings_dates.json    (6 days stale)
2026-08-26 10:30  persistent-state/…/momentum_catalysts/2026-08-26_catalysts.jsonl  (newest; 4 days stale)
```

No catalyst file exists for 08-27, 08-28, 08-29 or 08-30. The census is a runnable
script over a source that stopped moving. Worse than the prompt's premise, which named
only 2026-08-27: `earnings_dates.json` is from **08-24**.

### 2.3 A collector that reports an empty book and exits 0

`[VERIFIED]` — run without an explicit `--path`, from a worktree with no `data/`:

```
$ python scripts/cio_lineage_completion_report.py --fail-on-finding
workflows                0
complete_to_checkpoint   0
arcs                     {}
FAIL_ON_FINDING_EXIT=0
```

`[CODE]` `scripts/lib/cio_lineage_health.py:169` — `if total < min_workflows: return []`,
with `min_workflows` defaulting to 10 and documented as *"Deliberately silent below
`min_workflows`: a quiet window legitimately has…"*. The consequence is inverted: **the
emptier the data, the quieter the gate.** A total data outage (0 workflows) produces no
finding and exit 0 even under `--fail-on-finding`. A quiet window and a dead pipe are
the same signal. Reported, not changed — the threshold is a deliberate design choice and
altering it belongs to whoever owns G-LOOP-01.

---

## 3. V3 — the DONE column re-verified

Every proof script and test named in the scoreboard, the `docs/audits/diligence/` docs
and `CIO_DILIGENCE_SCOREBOARD.json` **exists**; nothing MISSING, no runner exited 2.
Aggregate over the 14 named proof files: **213 passed, exit 0**. `[VERIFIED]`

Reproduced cleanly, conclusion still supported: **P1-WS1, P1-WS2, P1-WS3, P2-WS5, P3,
P6, P7, P8.** P1-WS2 reproduced *exactly* (weighted 2.17, catalyst 1.49, accepted 39478,
recoverable 588).

### Status changes — DONE not supported by reproducible evidence today

**P5 — DONE over a self-declared FAIL (confirmed as briefed).** `[DOC-CLAIM]`
`P5_SPECIALIST_SAMPLE_2026-08-30.md:24-26` records verbatim
`| Zero orphans | workflow orphans **50/100 (50%)**; instrument orphans **36/100 (36%)** | **FAIL** — exit gate not met |`,
while the scoreboard reads `P5 | … | DONE`. `[VERIFIED]` I re-ran it myself:
exit 0, `orphan_workflow_count=44 (0.44)`, `orphan_instrument_count=37 (0.37)`. The FAIL
reproduces. The N=100 sample is also **2 live specialist artifacts + 98 fixture
projections**, with accuracy and relevance both `DATA_UNAVAILABLE`.

**P2-WS4 — DONE over a self-declared unmet target. Same shape as P5, not labelled as
such.** `[DOC-CLAIM]` its finding 3 reads *"Production target 100% resolvable: not met —
98.9% (88/89)"*. `[VERIFIED]` reproduces today at 98.9% (90/91), sole miss `HEALTH`.
Unlike P5, the scoreboard's Proof column does **not** carry an "exit gate FAIL honest"
note, and 98.9% is promoted to the NOW table as a headline. **Status change: DONE →
DONE-over-failing-check.**

**P4 — DONE on evidence that cannot be regenerated.** `[VERIFIED]`
`P4_RESEARCH_GOVERNANCE_CENSUS_2026-08-30.json` carries three top-level keys —
`live_overlay_root`, `stores_live_overlay`, `live_budget_report` — that **no script in
the repo emits** (`grep -rn` over `scripts/` returns nothing; the named census emits only
`free_first / invariants / stores / wave3d_ops_notes / cited_modules`). And the block the
script *did* produce was an **empty book**: the archived run used
`"root": "/home/johnclaw/tradeai-wt-cio-diligence-p4-p5"`, a worktree with no `data/`, so
all six store entries read `"exists": false`. The live half of P4's evidence was
hand-assembled around that empty result. The code-level invariants (cap 5 / hops 1 /
budget 3) do still hold today. **Status change: DONE → evidence not reproducible.**

**P0 / P9 — lineage headline stale, and the guarding test structurally cannot notice.**
`[CODE]` `tests/test_cio_diligence_scoreboard.py` asserts
`now["lineage"]["complete_to_checkpoint"] == 406` and `complete_pct == 54.0`, reading
those values **out of `CIO_DILIGENCE_SCOREBOARD.json` — the same file it validates.** It
is a self-consistency check over hardcoded literals, not a re-measurement, so it stays
green while the live number moves. Live today: 448/803 (55.79%), arcs 478. P9's own
census reproduces *exactly* (144 / 3); only its embedded lineage baseline drifted. The
load-bearing claim (`claim_99_99: false`) is unaffected and the drift is favourable.
**Status change: proof figures stale; conclusions intact.**

Per instruction, the gap register's status column was **not** edited.

---

## 4. V4 — preconditions board, by artifact type

`[VERIFIED]` `python scripts/cio_preconditions_board.py` → exit 0,
`TOTAL green=4 red=0 cannot_verify=0`, root probe `ROOT_OK — 40 subject(s)`.
Green/red is the least interesting column; what each check actually inspected:

| # | check | verdict | **artifact type actually verified** |
|---|---|---|---|
| 1 | S0 attach + rehydrate | GREEN | **One operator-turn record.** `plan_id=plan_79fe9e72f2d4` on `HELD:SCHD`, intent `defer`, read back through the gate input. `records_with_operator_turn=1`, `read_back_ok_n=1`. The entire check rests on a single subject. |
| 2 | CC narrative + cash letter, no ping | GREEN | **A rendered CC payload.** 12 held narratives (`desk@v5`), `cash_fingerprint="Cash sleeve 630784.82."`, `delivery="dashboard"`, `telegram_sent=false`, `would_send_any=false`. |
| 3 | Grok critique attach OR reject | GREEN | **A rejection.** `attach_n=0`, `reject_n=1`, artifact `grok_critique_ebb4120ba659`, `last_outcome="rejected"`, `research_blocked=true`. Green rests entirely on a refusal; **no critique has ever successfully attached.** |
| 4 | dust / CASH cannot mint or fire | GREEN | **9 refusal probes + 1 positive control.** `gate_failures=[]`, `control_symbol_mintable=true`, `dust_threshold_usd=50.0`, live dust `JEPI, LDOS, SCHG, SRNE`, `stored_leaks=[]`. The strongest of the four: it has a negative *and* a positive control. |

**Check 3's tightening is real** `[CODE]` — `cio_preconditions_board.py:411-425` names the
false green it closed: artifact `rw_8893dcc5aad5be6c`, lane `residual_web`, zero grok
lessons, which satisfied a bare `last_artifact_id` while the grok lane was
`POLICY_NOT_ALLOWED`. `_is_critique_shaped()` now requires critique-shaped fields. The
comment is worth keeping: *"A green obtained by the wrong artifact type is worse than a
red."*

### 4.1 The board's own anti-false-green safeguard is defeated by its implementation

`[CODE]` `scan_wake_consumers()` at `cio_preconditions_board.py:704`, whose docstring
promises *"An empty list means the record is written but never consulted, which is a fact
the board must print rather than let a GREEN imply otherwise"* — is a **substring grep**:

```python
if "cio_rehydrate" in src or "cio_instrument_record" in src:
    found.append(rel)
```

It matches the *text* anywhere in a file: a comment, a docstring, an unused import. It
never follows a symbol to a call. It reports 12 "spine wake consumers"; §5.2 shows the
actual number of production callers of the spine read is **zero**. The board therefore
can never print the fact it was designed to print, because the list is guaranteed
non-empty by files that merely mention the name.

### 4.2 A live rail contradicts the scoreboard

`[VERIFIED]` the board's own rail read, against `[DOC-CLAIM]` the NOW block's
`rails | … no notify-on · no Telegram producer`:

```
CIO_SITUATION_NOTIFY       : 1
CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY: 1
ENABLE_TELEGRAM            : true
situation_notify_telegram  : True
notify enabled             : True
interdict raised           : False
```

`[CODE]` and two systemd drop-ins authorise it:
`tradeai-cio-delivery.service.d/32-financial-notify-canary.conf` and the matching
material-scan drop-in, both *"Authorized 2026-08-26: READ_ONLY_ADVISORY CIO
material-financial Telegram canary."* The board's `would_send_any=false` is a property of
**this payload**, not of the rail. "No notify-on" is not true of the running system; the
correct statement is "notify is on, and nothing chose to send."

---

## 5. V5 — one page for the operator

### 5.1 Verified working at runtime today

| capability | command proving it | result |
|---|---|---|
| Server serving CIO surfaces | `curl -o /dev/null -w '%{http_code}' localhost:7777/api/v2/health` | **200** |
| CIO SPA + home payload | same against `/v3/cio` and `/api/v3/cio/home` | **200**, 219,777 bytes |
| Event-lifecycle census | `cio_event_lifecycle_census.py --json` (**from `main`**, not the release) | exit 0, 39,752 accepted |
| Lineage measurement | `cio_lineage_completion_report.py --path CURRENT/…` | exit 0, 803 workflows |
| Identity census | `cio_identity_confidence_census.py --json` | exit 0, 91 production records |
| Preconditions board | `cio_preconditions_board.py` | exit 0, 4 green |
| Spine drill / orphan census / specialist audit / governance census | as named in §2 | all exit 0 |
| Reactive + material-scan wake loops | `journalctl --user -u tradeai-cio-reactive.service` | running every ~2 min all day, ~1s CPU each |
| Dust/CASH refusal | board check 4 | 9 probes held, control mints |

**This is a lot of working machinery, and almost all of it measures rather than acts.**

### 5.2 Does any scheduled process read the InstrumentRecord spine before acting? — **No.**

This was the question most at risk of a wrong answer, so the method matters.

- A first attempt used **atime** on the spine store (mtime 10:58:17, atime 10:58:25, while
  the reactive cycle had run ~40 times since). `[VERIFIED]` `findmnt` reports the
  filesystem is **`relatime`**, under which atime does not update when atime > mtime —
  so atime proves **nothing** here. **Conclusion discarded before it was drawn.**
- `[VERIFIED]` transitive import trace from the three scheduled CIO entry points:
  `cio_delivery_worker.py` reaches the spine **not at all** (1 module walked);
  `cio_reactive_cycle.py` and `cio_material_scan.py` reach
  `scripts.lib.cio_instrument_record` only through **8–16 hop** chains that pass through
  `scripts.api_v3_cio` — i.e. they import the *web API module*, which imports the spine.
  An import is not a read.
- `[CODE]` The spine's read-before-acting entry point is
  `load_instrument_record_for_wake()` (`cio_instrument_record.py:442` — the name says
  "for_wake"). Its **only** production call site is `cio_s0_operator_loop.py:352`, inside
  `rehydrate()`.
- `[CODE]` **`rehydrate()` has no production caller.** The only production import of
  `cio_s0_operator_loop` anywhere is `cio_converse_core.py:148`, which imports
  `route_turn` — a different function that does not call `rehydrate`. Every other
  reference to the module is a test.

The spine *is* read in exactly two places, neither scheduled and neither before acting:
`build_office_home()` (`cio_command_center.py:1638`, via `resolve_record_store`) — the
`/api/v3/cio/home` **render**, on operator HTTP request, explicitly commented *"a render
of an INPUT, not a model call"* — and the audit tooling itself (the board, the drill, the
budget report). `resolve_record_store` is additionally `except Exception: return None`,
so a broken spine degrades to a silent None rather than an error.

**Two scheduled units run every 2–5 minutes, all day, and the record spine is not
consulted by either one before they act.**

### 5.3 Agent-originated fields reaching an operator surface: **18**

`[VERIFIED]` over the live `/api/v3/cio/home` payload (5,111 leaf values, 36 top-level keys):

```
narrative_source : {'record': 18, 'deterministic': 32}
commentary_class : {'D': 20}
commentary_reason: 20 x no_earnings_transcript_row
commentary text  : 20 x 'UNAVAILABLE'
```

Of 50 narrative slots the operator can see, **18 carry agent-written prose from an
InstrumentRecord**; 32 fall back to the deterministic line. All 20 earnings-commentary
slots read the literal string `UNAVAILABLE`. 18 fields out of 5,111 leaves is the honest
measure of how much of this surface an agent actually authored.

### 5.4 Built and unwired

- `tests/test_every_script_compiles.py` — the only repo-wide compile sweep; **no runner
  invokes it.**
- `rehydrate()` / `load_instrument_record_for_wake` — the spine wake read; **no
  production caller** (§5.2).
- 11 × `scripts/session*_validate.py` — syntax/behaviour validators; **no caller
  anywhere**.
- `scripts/lib/safe_text_edit.py` — the sanctioned source-editing helper; **no production
  caller**, and it does not verify what it writes.
- Earnings commentary — surfaced, plumbed, and empty in all 20 slots for want of a
  transcript row.
- Grok critique attach — the lane exists and the board is green on it, via **zero
  attaches and one rejection**.

### 5.5 Claimed and unverifiable

- `DRIVE | FAIL until gog upsert` — no producer exercised; unverified.
- `P4`'s `live_overlay_root` / `stores_live_overlay` / `live_budget_report` — **no script
  emits these keys**; the values cannot be regenerated by anything in the repo.
- The NOW block's `origin/main` pin (`015a7891`) is hand-stamped and three merges stale.
- "No notify-on" — contradicted by the live rail (§4.2).

### 5.6 Conclusion

**This is a mature audit apparatus attached to an immature agent.**

The measurement layer is genuinely good: three-verdict boards that distinguish
CANNOT_VERIFY from RED, a census that refuses to claim 99.99%, a `claim_99_99: false`
flag carried in the payload, a check that was tightened the same day a false green was
found in it, and P5 recording an honest FAIL rather than burying it. That is real
engineering discipline and it should be said plainly.

What it is attached to is thinner than the apparatus implies. The InstrumentRecord spine
— the thing all of this is supposedly measuring — is written by scheduled jobs and read
before acting by **none** of them; its designated wake-read function has zero production
callers. 18 of 5,111 payload leaves are agent-authored. The specialist sample that
carries the N=100 label is 2 live artifacts and 98 fixture projections. The critique lane
is green on a rejection. And the gate that enforces the declaration standard passed a
file that could not be compiled, in the same week that exact defect took a script off
the air for 10 hours while its numbers went on being quoted.

The apparatus is also not yet pointed at itself: its single repo-wide compile sweep runs
only when a human types its name, its lineage collector goes quiet precisely when the
data disappears, its scoreboard test asserts literals against the file it is validating,
and — the finding that reframes all the others — **the fix for the 10-hour outage is
merged to `main` and still not deployed to the release that is actually serving.**

---

## Contradictions with the sweep prompt (finding wins)

1. *"Both fixed"* — true of `main`, **false of the served release**, where both defects
   are live today (§0).
2. *"`atm_position_reconciler.py` had a UTF-8 BOM"* framed as an equal defect — a BOM
   does not stop a file running or importing (§1.1); only the `__future__` defect did.
3. *"`compile()`, never `ast.parse`"* is right, but for `__future__` placement only; on
   BOM the two are identical and the real axis is **bytes vs str** (§1.1).
4. *regenerated `complete_to_checkpoint` 447 / 55.87%* — measured **448 / 55.79%** today;
   the store was written at 12:06 today and moved (§2).
5. *catalyst source last written 2026-08-27* — `catalyst_graph_latest.json` yes, but
   `earnings_dates.json` is **2026-08-24** and the hermes catalyst files stop at
   **2026-08-26** (§2.2).
6. *"nine diligence packages are marked DONE"* — the scoreboard table carries **thirteen**
   rows (P0, P1-WS1/2/3, P2-WS4/5, P3, P4, P5, P6, P7, P8, P9), all DONE.
7. The prompt asks whether any package besides P5 is DONE over a failing check. **Three
   are**: P2-WS4, P4, and P0/P9's lineage figures (§3).
