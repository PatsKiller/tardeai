---
title: Phase 4 — Verification matrix with negative controls
date: 2026-09-05
status: findings
scope: read-only advisory
worktree: /home/johnclaw/tradeai-wt-cc-header-final (branch wt/cc-header-final)
interpreter: /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
---

# Phase 4 — Verification matrix with negative controls

A rail that has never been observed to fail proves nothing. This phase ran every
gate in the Phase-4 list, then deliberately reintroduced the defect each guard
exists to catch and recorded whether the guard actually noticed.

**Seven negative controls were run. Five caught their defect. Two did not, and
both non-catches are real gaps, not test-authoring noise.**

Everything below is quoted from actual output. Where a gate did not run, it says
so rather than reporting a count.

---

## 0 · Provenance and tree hygiene

**Baseline at start of session** (`git status --porcelain`):

```
 M scripts/lib/research_provider_truth.py
 M tests/test_research_provider_truth.py
```

The tree was **not** clean when Phase 4 began. Those two files were committed by a
concurrent agent mid-session as `af3349528 research(budget): the two ceilings were
the same constraint twice` (authored 2026-09-05 15:56:49, i.e. after this phase's
first gate run started). All measurements below that touch those two files were
taken *after* that commit landed, against the committed content.

**Final `git status --porcelain`:**

```
 M docs/INDEX.md
 M scripts/brave_search.py
 M tests/test_overnight_f3_search_budget.py
?? docs/_findings/phase1_research_router_inventory_2026-09-05.md
?? docs/_findings/phase2_delivery_reconciliation_2026-09-05.md
?? docs/_findings/phase4_verification_matrix_2026-09-05.md
```

**Only `docs/_findings/phase4_verification_matrix_2026-09-05.md` is mine.** Every
other entry is a concurrent agent's work landing in this shared tree while Phase 4
ran, and each is timestamped after my last verified-clean checkpoint:

| Path | mtime | Whose |
|---|---|---|
| `docs/INDEX.md` | 16:08:16 | another agent — the F4 regeneration (2395 → 2397) |
| `scripts/brave_search.py` | 16:09:44 | another agent — `_budget_file()` canonical-state-root refactor |
| `tests/test_overnight_f3_search_budget.py` | 16:10:04 | another agent, same change |
| `docs/_findings/phase1_…`, `phase2_…` | — | Phase 1 / Phase 2 deliverables |
| `docs/_findings/phase4_…` | 16:09:36 | **mine** |

`scripts/brave_search.py` deserves an explicit clearance because NC3 patched it. It
was byte-verified back to baseline (`af8a8d2ec3f97613e3b35eaf07a7c7d9`) after NC3 and
again after NC3b. The current diff is an unrelated refactor moving the L2 budget
ledger to one canonical state root, and none of my negative-control strings survive:

```
$ grep -nE "out of 1000|1,000/month free tier|1000/month free|free plan allows|NEGATIVE CONTROL" scripts/brave_search.py
NONE — my defect is not present
```

Nothing was committed, pushed, merged, deployed or migrated.

Every file touched by a negative control was byte-compared against a pre-edit
backup after revert:

```
MATCH  scripts/portfolio_server.py
MATCH  scripts/brave_search.py
MATCH  config/design_features.yaml
MATCH  scripts/lib/research_provider_truth.py
MATCH  scripts/lib/portfolio_aggregate_contract.py
MATCH  apps/command-center-v3/src/components/MetricStrip.tsx
```

One transient process was started and stopped: `vite preview --port 4191`, to serve
the freshly built bundle to the design-flags probe. It is gone (`4191=000`). Two
other vite previews (`:4173`, `:4193`) belong to other worktrees/agents and were
left untouched.

### A hazard I hit before I could avoid it

The task brief forbids running `tests/test_communications_portal.py` and
`tests/test_comms_subject_memory.py` because a live Postgres (`dbname=trade_ai`) is
reachable. **`scripts/run_cio_hardening_ci.py` runs both of them itself**, inside
its `comms_gateway_phase0` gate:

```
[RUN]  comms_gateway_phase0: ... tests/test_comms_subject_memory.py ... tests/test_communications_portal.py ...
[PASS] comms_gateway_phase0
```

So the mandated Gate 1 and the DB prohibition are in direct conflict. I ran Gate 1
twice before noticing.

**Assessed impact: no production write occurred**, and the gate passing is itself
the evidence. Both files carry an `autouse` fixture that forces the in-memory
ledger:

```python
monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)
```

with the comment naming exactly this hazard:

> every call site is `conn = _db_conn(); if conn is not None: <db> else: <memory>`
> — so on a box where localhost Postgres answers, the DB branch wins, the
> assertions fail, AND the test run WRITES INTO THE PRODUCTION trade_ai database.

The suites assert `source == "memory"`. Had the stub failed, those assertions would
have failed *and* the gate would have gone red. It went green, so the memory branch
was taken. **The guard is self-evidencing: a pass proves the DB was not reached.**

*Recommendation:* the DB prohibition should name the transitive path too, or the CI
harness should be given an offline mode, because "don't run these two files" is not
actionable while the one mandatory gate runs them.

---

## 1 · Gate results

### Gate 1 — `python scripts/run_cio_hardening_ci.py`

**110 gates ran. 108 `[PASS]`, 2 `[FAIL]`. Exit code 1.**

```
CIO HARDENING CI FAILED: ['overnight_g3_docs_index', 'docs_index_drift']
```

Both failures are **one root cause**, and it is a genuine defect the gate caught
correctly — not flake, and not caused by me.

```
[FAIL] overnight_g3_docs_index
[FAIL] docs_index_drift — docs/INDEX.md does not match regenerate
```

with the nested detail:

```
[FAIL] docs/INDEX.md drift — regenerate with --write-index
-**Tree fingerprint:** `8e19db7ce69d554bf87e2cccf6e987761f6ac3259366787a54260b7718ffcfc9`
+**Tree fingerprint:** `c8ac1d675eed9da02285fd7527a7911c38bd7bd7b0e31a133bb129c63980d10e`
-| Files under `docs/` (excl. this INDEX) | 2395 |
+| Files under `docs/` (excl. this INDEX) | 2397 |
+| `docs/RESEARCH_PROVIDER_ROUTING.md` | Research provider routing — when Brave should be used | ...
+| `docs/_findings/phase3_documentation_truth_audit_2026-09-05.md` | Phase 3 — Documentation truth audit ...
```

**Root cause, measured.** Commit `af3349528` regenerated `docs/INDEX.md` at a count
of 2395 and, *in the same commit*, added two more docs:

```
$ git show af3349528 -- docs/INDEX.md
-| Files under `docs/` (excl. this INDEX) | 2394 |
+| Files under `docs/` (excl. this INDEX) | 2395 |
```

Both new docs are tracked (`git ls-files --error-unmatch` confirms). The author ran
`--write-index` before creating the two files, then committed all three together.
Ordering bug, correctly caught.

**A caveat I checked and then had to withdraw.** My first reading was that this gate
fingerprints a filesystem walk of `docs/` and would therefore be permanently unstable
in a shared worktree where several agents write `docs/_findings/*` concurrently —
including this file. **That is wrong, and the generator says so explicitly.**
`scripts/report_docs_inventory.py:160-190` is git-aware:

```python
"""Files under `root` that git tracks, falling back to a filesystem walk.

WHY THIS IS GIT-AWARE. This previously used `root.rglob("*")`, a plain
filesystem walk with no knowledge of git. The index it generates is checked by
...
    ["git", "-C", str(PROJ), "ls-files", "-z", "--", str(root)],
```

Measured confirmation: none of the three untracked findings docs present in this
tree (`phase1_…`, `phase2_…`, and this file) appear in the regenerated index —
`grep -c` returns `0` for each. **Untracked work in progress does not move the
fingerprint.** The gate is stable under concurrent agents and its failure was purely
the `af3349528` ordering bug.

**Resolved during this session.** Another agent regenerated `docs/INDEX.md` at
16:08:16 (2395 → 2397, adding the two missing rows), which is exactly the F4 fix. It
shows in my final `git status` as ` M docs/INDEX.md` and is **not my edit** — my only
write is this file, created at 16:09:36.

The remaining 108 gates passed. Full ordered list of gate names is in the run log;
notable ones relevant to this branch: `cc_header_truth_v2`, `research_provider_truth`,
`research_observation_contract`, `cc_runtime_harness`, `holdings_data_clock`,
`canonical_observation_contract`, `comms_gateway_phase0`, `financial_truth_gate`.

One informational, non-failing line:

```
[PASS] generate_candidate_manifest → .../data/audit/manifest_candidate
[info] candidate DIFFERS from committed pin (informational; not a substitute for check-committed)
```

The committed pin is `chore/cio-pin-aa037b73` / `aa037b73…`; the candidate is this
branch. Expected on a feature branch.

### Gate 2 — targeted pytest

```
$ python -m pytest tests/test_header_truth_regression.py tests/test_design_features.py \
    tests/test_research_provider_truth.py tests/test_cc_v3_boot_no_reload_loop.py -q
....................................................................     [100%]
68 passed in 3.03s
```

**This count is misleading and I am flagging it rather than reporting it as four
files' worth of coverage.** See NC5 — the fourth file contributes **zero** tests.

```
$ python -m pytest tests/test_cc_v3_boot_no_reload_loop.py --collect-only -q
no tests collected in 0.21s
```

The three files that *do* collect account for all 68:

```
$ python -m pytest tests/test_header_truth_regression.py tests/test_design_features.py \
    tests/test_research_provider_truth.py -q
68 passed in 3.83s
```

### Gate 3 — `node scripts/test_metric_strip_labels.mjs`

```
metric_strip_labels: 40 passed, 0 failed
metric_strip_header_truth: 47 passed, 0 failed
```

**87 source rails, exactly as expected.** Exit 0.

### Gate 4 — `npm run build`

Succeeded, exit 0.

```
[design-guard] pass (341 files checked against baseline)
...
metric_strip_labels: 40 passed, 0 failed
metric_strip_header_truth: 47 passed, 0 failed
BookTreemap squarify: 12 passed, 0 failed
vite v5.4.21 building for production...
✓ 1380 modules transformed.
dist/assets/index-C724GvTg.js   4,411.16 kB │ gzip: 1,187.61 kB
✓ built in 8.44s
```

**Raw hexes in MetricStrip: 0**, verified directly —
`grep -oE '#[0-9a-fA-F]{3,8}\b' apps/command-center-v3/src/components/MetricStrip.tsx | wc -l` → `0`.

### Gate 5 — e2e

Backend on `:7777` was **up** (`curl` → `302`), so both probes ran for real.

`e2e/header_geometry.mjs http://127.0.0.1:7777`:

```
header_geometry: 49 passed, 0 failed
[PASS] strip height is identical at every width (75, 75, 75, 75)
```

Measured at 1280 / 1440 / 1700 / 2000 px. Strip height 75px against a
`MAX_STRIP_HEIGHT` of 88.

`e2e/design_flags_probe.mjs http://127.0.0.1:4191/v3/ http://127.0.0.1:7777`:

```
design_flags_probe: 24 passed, 0 failed
faults visible under defaults: clock_divergence, quote_coverage, stale_surface
```

`:4191` was not up; I served the *freshly built* `dist/` there with
`vite preview --port 4191 --strictPort` so the probe tested my build rather than
the deployed one, then stopped it. This is the more hermetic of the two options —
pointing at `:7777/v3` would have tested whatever is currently deployed.

---

## 2 · Negative controls

Method: patch → run guard → revert (trap-based, so revert fires even on failure) →
byte-compare against backup → re-run guard to confirm green. Each defect lived in
the shared tree for one command's duration.

| # | Defect introduced | Guard | Caught? |
|---|---|---|---|
| NC1 | `clock_divergence: false` added to `config/design_features.yaml` | `tests/test_design_features.py` | **YES** |
| NC2 | `PortfolioAggregate` derives `valuation_time` from the position clock | `tests/test_header_truth_regression.py` | **NO** |
| NC3 | "1,000/month free tier" restored to `scripts/brave_search.py` | `tests/test_research_provider_truth.py` | **YES** (literal only) |
| NC3b | Same claim, paraphrased | same | **NO** |
| NC4 | Zero-guard removed; `0` read as a real monthly ceiling | `tests/test_research_provider_truth.py` | **YES** (3 tests) |
| NC5 | Version check injected at `</head>`, after the module script | `tests/test_cc_v3_boot_no_reload_loop.py` | **YES as a script / NO in any gate** |
| NC6 | `% win` label stripped from the TRADING tile | `scripts/test_metric_strip_labels.mjs` | **YES** |
| NC7 | Raw hex `#ff0066` added to `MetricStrip.tsx` | `scripts/check_design_tokens.sh` (build) | **YES** |

---

### NC1 — PROTECTED_SIGNAL named in config → CAUGHT

Injected into `config/design_features.yaml`:

```yaml
  state_dots: true

  # NEGATIVE CONTROL (temporary)
  clock_divergence: false
```

`tests/test_design_features.py` went **1 failed, 25 passed**:

```
>       assert out["errors"] == [], out["errors"]
E       AssertionError: ["'clock_divergence' is not a feature flag and cannot be configured
E       — it reports two copies of the position clock disa... said 2026-07-17 and the position
E       rows said 2026-09-04, and the header showed one of them. Remove it from the config."]
```

**Nuance on the brief's wording ("loader must error").** The loader does **not**
raise. It returns `loaded: True` with the error in an `errors` list, and — importantly
— does *not* apply the flag:

```
LOADER RETURNED (no raise): {'loaded': True,
 'errors': ["'clock_divergence' is not a feature flag and cannot be configured …"],
 'protected_signals': ['clock_divergence', 'missing_accounts', 'quote_coverage',
                       'run_health', 'stale_surface', 'unaccounted_rows', 'undated_surface'],
 'header': {'state_dots': True, 'tile_rails': True, 'quiet_provenance': True,
            'coverage_pct_on_face': False, 'run_clocks_on_face': True, 'density': 'normal'}}
```

`clock_divergence` is absent from `header`. This is **fail-soft by design**, and the
config file documents the intent: *"Unknown keys are ignored and reported. A
malformed value falls back to the shipped default rather than taking the surface
down."* The rejection is real; the enforcement lives in the test, not in a raise.
That is a defensible split — a bad config file must not take the header down — but
it means **the protection is CI-time, not runtime**. The runtime protection is the
separate one NC-adjacent to this: the `design_flags_probe` e2e, which drives hostile
payloads at a real browser and confirms faults stay on screen (24 passed, above).
Both layers exist. Good.

Reverted: md5 `4c39e7cd7bcc2ae2c19cfa39685f65c9` matched; re-run **26 passed**.

---

### NC2 — one clock for three sources → **NOT CAUGHT** (finding)

`scripts/lib/portfolio_aggregate_contract.py` exists to publish each clock under its
own name and *never derive one from another*. Its module docstring:

> Three clocks, one name. … v2 publishes each clock under its own name and never
> derives one from another … never borrow the valuation clock to date a position.

I introduced exactly that defect:

```python
-  "valuation_time": str(row.get("last_repriced") or "").strip(),
+  "valuation_time": obs or "",  # NEGATIVE CONTROL: one clock for three sources
```

Result:

```
....................                                                     [100%]
20 passed in 2.20s
```

**The guard did not notice.** The header-truth regression suite passed with the
valuation clock derived from the position clock — the precise defect it was written
to prevent.

**Why.** I ran a second control (NC2b) with a sentinel to prove the field is read at
all:

```python
+  "valuation_time": "1999-01-01",  # NC2b sentinel
```

```
>       assert row["valuation_time"] == "2026-09-04"
E       AssertionError: assert '1999-01-01' == '2026-09-04'
tests/test_header_truth_regression.py:176
```

So the assertion **is** live — it simply cannot distinguish the two clocks, because
in the fixture they hold the same value. From
`tests/test_header_truth_regression.py:173-176`:

```python
def test_the_dominant_account_reports_every_clock_separately(clock_aggregate):
    """schwab_rollover_ira is 90% of the book and every clock on it differs."""
    assert row["position_observation_time"] == "2026-09-04"  # from the live rows
    assert row["summary_as_of"] == "2026-07-17"
    assert row["valuation_time"] == "2026-09-04"
    assert row["reported_total_as_of"] == "2026-04-30"
```

**The docstring says "every clock on it differs". Two of them do not.**
`position_observation_time` and `valuation_time` are both `2026-09-04`, because
`tests/fixtures/header_truth/clock_contradiction_20260903_20260904.json` sets
`"last_repriced": "2026-09-04"` for that account alongside position rows observed
the same day.

**Verdict: partially vacuous.** The test proves the four clocks are *published under
four names*; it does **not** prove they are *independently sourced*. A regression
that collapses the valuation clock into the position clock ships green.

**Proposed fix (not applied — read-only phase):** change `last_repriced` for
`schwab_rollover_ira` in that fixture to a date distinct from the position
observation (the real value is `"2026-09-04 13:45:01 ET"` at the top level of the
same fixture, so a distinct per-account date is realistic), and update the
assertion. One-line fixture change; makes the existing assertion load-bearing.

---

### NC3 — "1,000/month free tier" → CAUGHT literally, **evaded by paraphrase**

Restored the retired claim to `scripts/brave_search.py`:

```
Daily budget cap: 120/day, 1500/month. Brave gives 1,000/month free tier, so we
reserve 150 for P0/manual searches out of 1000.
```

A guard **does** exist and fired:

```
_______ test_brave_search_states_no_provider_plan_it_has_not_observed _______
        for claim in ("out of 1000", "1,000/month free tier", "1000/month free"):
>           assert claim not in src, f"provider-plan claim reintroduced: {claim!r}"
E           AssertionError: provider-plan claim reintroduced: 'out of 1000'
tests/test_research_provider_truth.py:157
1 failed, 21 passed
```

I also swept the neighbouring budget suites; **none** of them caught it:

```
tests/test_search_budget_and_health.py             20 passed
tests/test_overnight_f3_search_budget.py           15 passed
tests/test_overnight_f4_search_health.py           17 passed
```

**NC3b — the paraphrase.** The guard is a three-phrase literal blocklist over one
file. I re-injected the same false assumption in different words:

```
Daily budget cap: 120/day, 1500/month. Brave's free plan allows 1000 searches
per month, and we hold back 150 of those for P0/manual work.
```

```
......................                                                   [100%]
22 passed in 0.50s
```

**Not caught.** The semantically identical claim ships green.

**Verdict:** the guard is real but narrow on two axes —
1. **Phrasing:** it matches three exact strings, so any rewording restores the false
   provider fact silently.
2. **Scope:** it reads only `scripts/brave_search.py`
   (`(ROOT / "scripts" / "brave_search.py").read_text(...)`). The same claim
   reintroduced in `scripts/lib/search_budget.py`, in `docs/`, or in any other
   caller is unguarded.

This directly answers the brief's question: **yes, a guard catches the literal
string; no, it does not protect the assumption.** The assumption *can* return
unnoticed. Suggested hardening: match on the number-plus-concept (`/1[,.]?000[^\n]{0,40}(free|plan|tier|quota)/i`)
across the whole `scripts/` + `docs/` tree rather than three literals in one file.

---

### NC4 — `0` as a real monthly ceiling → CAUGHT (3 tests)

Removed the zero-guard in `ProviderCapacity.monthly_limit()`:

```python
-  if lim is not None and lim <= 0:
-      return None
-  return lim
+  # NEGATIVE CONTROL: zero-guard removed; 0 read as a real ceiling
+  return lim
```

**3 failed, 19 passed:**

```
test_zero_monthly_window_is_not_a_ceiling_of_zero
>       assert cap.monthly_limit() is None
E       AssertionError: assert 0 is None

test_unmetered_month_does_not_fabricate_a_conflict
>       assert rec["conflict"] is None, "a working key must not be reported as over its limit"
E       AssertionError: a working key must not be reported as over its limit
E       assert 'LOCAL_MONTHLY_COST_POLICY allows 1500/month but the provider reports 0/month
E       — the local ceiling cannot be honoured' is None

test_unmetered_is_distinguishable_from_never_observed
>       assert observed["binding_ceiling"] == never["binding_ceiling"] == "local_policy"
E       AssertionError: assert 'provider' == 'local_policy'
```

Note `test_a_real_positive_monthly_limit_still_binds_and_still_conflicts` stayed
green — it is the counter-guard ensuring the zero-guard does not swallow a genuine
provider ceiling. **This is the best-constructed rail in the set:** three tests pin
the defect from three angles and a fourth pins the over-correction. Non-vacuous.

Reverted: md5 `21035e76aa10dd4db16c9daf9e1c8b23` matched.

---

### NC5 — version check after the module script → **guard works, but runs in no gate** (finding)

The defect, in `scripts/portfolio_server.py`:

```python
-  _mod = _body.find(b'<script type="module"')
-  if _mod != -1:
-      _body = _body[:_mod] + _inject + _body[_mod:]
-  elif b"</head>" in _body:
-      _body = _body.replace(b"</head>", _inject + b"</head>", 1)
+  # NEGATIVE CONTROL: appended at </head>, i.e. AFTER the module script
+  if b"</head>" in _body:
+      _body = _body.replace(b"</head>", _inject + b"</head>", 1)
```

Under pytest — the invocation the Phase-4 brief specifies:

```
$ python -m pytest tests/test_cc_v3_boot_no_reload_loop.py -q
no tests ran in 0.30s
```

Exit code **5** (no tests collected). Run as a script, it catches the defect
cleanly:

```
$ python tests/test_cc_v3_boot_no_reload_loop.py
PASS: no hardcoded per-path version literals remain
PASS: single shared fallback constant exists
PASS: both boot paths resolve via the shared helper
PASS: version resolves identically with NO ui_version in build-meta
PASS: fallback is the shared constant
PASS: ui_version from build-meta is honoured
PASS: both scripts use one sessionStorage key
FAIL: the reload check is injected before the module script, not at </head>
      — appending at </head> puts it after the bundle tag and aborts the in-flight fetch
EXIT=1
```

Clean, as a script: `All 11 cc-v3 boot-loop guards passed.`

**The gap.** This file has **zero `def test_` functions** (`grep -c` → `0`); it is a
`main()` + `raise SystemExit` script. Consequently:

- `pytest tests/test_cc_v3_boot_no_reload_loop.py --collect-only -q` → `no tests collected`
- it contributes **0 of the 68** in Gate 2, so Gate 2's headline number silently
  covers three files, not four
- `grep -n 'cc_v3_boot' scripts/run_cio_hardening_ci.py` → **no match**. It is not in
  the CIO hardening harness either.

**So the 2026-07-28 reload-loop outage is protected by 11 good assertions that no
automated gate executes.** They run only if a human types the path. A `pytest`-shaped
filename in `tests/` that collects nothing is worse than no file, because it reads as
covered.

*Proposed fix (not applied):* wrap the checks in a single `def test_cc_v3_boot_guards(): assert main() == 0`,
or add the file to `run_cio_hardening_ci.py` as a script-invoked gate. Either makes
the 11 assertions real.

Side note: this test temporarily rewrites `apps/command-center-v3/dist/build-meta.json`
and restores it in a `finally`. Verified restored, `ui_version` intact.

---

### NC6 — label stripped from the TRADING tile → CAUGHT

```
-  `${winRate}% win${winTrades ? ...}`
+  `${winRate}%${winTrades ? ...}`
```

```
  [FAIL] the TRADING tile labels its win rate
  [PASS] the TRADING tile labels its trade count
  [PASS] the TRADING tile labels its P&L

metric_strip_header_truth: 46 passed, 1 failed
```

Exit 1. Precisely one rail moved — no collateral. Reverted, back to 47/47.

---

### NC7 — raw hex reintroduced → CAUGHT (blocks the build)

Added `color: '#ff0066'` to the TRADING tile in `MetricStrip.tsx`:

```
[design-guard] FAIL components/MetricStrip.tsx: 1 raw-hex/sub-10px violations
               (baseline 0) — use watchTokens (BB/T/DASH), no fonts below 10
[design-guard] blocked. Fix the file or (only for deliberate legacy freezes) --update-baseline.
```

Exit 1. This runs **first** in `npm run build`, so the defect cannot reach `dist/`.
Reverted; `[design-guard] pass (341 files checked against baseline)`.

---

## 3 · Vacuity check — did each guard measure anything real?

| Guard | Measured something real? | Evidence |
|---|---|---|
| `run_cio_hardening_ci.py` (110 gates) | **YES** | Went red on a real ordering defect in `af3349528`; 2 gates failed, 108 passed. Not a trivial pass. |
| `test_design_features.py` | **YES** | NC1 flipped it to 1 failed / 25 passed with the exact protected-signal message. |
| `test_header_truth_regression.py` | **PARTLY — see NC2** | Field is read (NC2b sentinel fails), but the fixture gives two clocks the same value, so the derivation defect is invisible. **Reported as a failure of the rail.** |
| `test_research_provider_truth.py` — zero-guard | **YES, strongly** | NC4 tripped 3 tests, with a 4th counter-guard pinning the over-correction. |
| `test_research_provider_truth.py` — free-tier claim | **PARTLY** | Catches 3 literal strings in 1 file (NC3 red). A paraphrase passes (NC3b green). Assumption is not protected. |
| `test_cc_v3_boot_no_reload_loop.py` | **NO, as invoked** | Collects 0 tests under pytest; absent from the CI harness. The assertions are good and do catch NC5 — but **nothing runs them**. Reported as a failure. |
| `test_metric_strip_labels.mjs` (87 rails) | **YES** | NC6 moved exactly one rail to FAIL. |
| `check_design_tokens.sh` | **YES** | NC7 blocked the build with a specific violation count. |
| `e2e/header_geometry.mjs` (49) | **YES — self-guarding** | Carries its own anti-vacuity rail: `[PASS] every tile exposes its named parts (else the size checks are vacuous)`, at all four widths. |
| `e2e/design_flags_probe.mjs` (24) | **YES — self-guarding** | `[PASS] at least one fault is on screen, so the survival checks mean something`, naming `clock_divergence, quote_coverage, stale_surface`. |
| `comms_gateway_phase0` | **YES — self-evidencing** | Asserts `source == "memory"`; a pass proves the production DB branch was not taken. |

**Two rails failed the vacuity check and are reported as failures:**

1. **`test_cc_v3_boot_no_reload_loop.py` runs in no gate.** Highest-severity finding
   here: 11 assertions guarding a real outage, executed by nothing. The Gate 2
   command in the Phase-4 brief itself silently discards this file.
2. **The header-truth clock-independence assertion is blind to its own defect
   class**, because the fixture makes two of the four clocks identical. The
   docstring's claim that "every clock on it differs" is not true of the fixture.

Two more are **narrow rather than vacuous** and worth widening: the free-tier
blocklist (literal-and-single-file), and the design-features rejection (CI-time
only — though the e2e probe covers the runtime side independently).

---

## 4 · Summary of findings

| # | Finding | Severity |
|---|---|---|
| F1 | `tests/test_cc_v3_boot_no_reload_loop.py` collects 0 tests under pytest and is not in `run_cio_hardening_ci.py`. 11 outage guards run in no gate. | **High** |
| F2 | Header-truth fixture gives `position_observation_time` and `valuation_time` the same value; collapsing the two clocks passes 20/20. | **High** |
| F3 | The free-tier-claim guard is 3 literal strings over 1 file; a paraphrase, or the same claim in another file, is unguarded. | **Medium** |
| F4 | `docs_index_drift` / `overnight_g3_docs_index` red on main-line branch: `af3349528` regenerated `docs/INDEX.md` before adding two docs in the same commit. **Fixed by another agent at 16:08 during this session.** | **Medium** (real, correctly caught, now resolved) |
| F5 | The mandatory Gate 1 transitively runs both files the DB-hazard rule forbids. No write occurred (stubs held, gate green), but the prohibition is not actionable as written. | **Medium** (process) |
| ~~F6~~ | **Withdrawn.** I initially recorded that `docs/INDEX.md` fingerprinting counts untracked files and so cannot be green under concurrent agents. Checked against `scripts/report_docs_inventory.py:160-190`: it uses `git ls-files`, untracked files are excluded, and none of the three untracked findings docs appear in the regenerated index. The claim was false and is retracted rather than shipped. | n/a |

Nothing in F1–F6 was fixed. This phase is read-only advisory; all edits were
negative controls, reverted and byte-verified.
