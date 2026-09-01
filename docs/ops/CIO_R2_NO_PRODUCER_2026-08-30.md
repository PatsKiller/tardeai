# The two NO_PRODUCER rows — P4's evidence and the scoreboard pin

Status:      HISTORICAL
as_of:       2026-08-30T19:40:14-04:00
Measured at: efcc51365 / not measured

Agent **R2**, Wave A-RECONCILE, 2026-08-30. Authority **READ_ONLY_ADVISORY**,
`MBI_BEHAVIOR=0`, `MBI_COGNITION=1`. Nothing promoted, merged, deployed or
notified. No cron or systemd unit installed. No vendor call.

Tags: `[VERIFIED]` = a command ran and its output is quoted · `[CODE]` = source
read · `[DOC-CLAIM]` = a document asserts it, unconfirmed.

Base: `origin/main` = `9d92b6e0`. Live release under measurement:
`CURRENT -> 9d92b6e0-main-exact-phase2-20260830-125544`.

---

## 0. The headline, and where it corrects the brief

`docs/ops/CIO_V_SWEEP_2026-08-30.md` recorded `NO_PRODUCER` for **three** keys in
P4's evidence JSON. Two corrections, both of which make the finding sharper
rather than softer.

**There are four keys, not three.** The fourth is nested and the sweep's
top-level scan missed it: `free_first.note_live`. `[VERIFIED]`

```
$ diff <(census keys) <(published keys)
PUBLISHED-ONLY KEYS : ['live_overlay_root', 'stores_live_overlay', 'live_budget_report']
free_first PUB-only  : ['note_live']
```

**"Never measured" is wrong, and the truth is a different defect.** Three of the
four keys hold values a real producer can still emit — under different names, at
a different root, from a different run. What has no producer is **the document**.
One `CIOResearchGovernanceCensus@v1` object, carrying a single `as_of` and a
single `root`, was assembled by hand out of *three runs against two roots plus
one written sentence*. Nothing in the repository could regenerate it as
published. That is worse than a stale number, because the schema tag asserts it
is a census the script emits.

---

## 1. Producer search — the negative, and why it is credible

The brief warns that grepping a key name has produced three wrong conclusions
here. So the search was run five ways, and the structural argument is the one
that actually settles it.

**`[CODE]` The module cannot emit these keys.** `census()`
(`scripts/cio_research_governance_census.py:127`) `return`s a **dict literal**.
`main()` does `json.dumps(doc)` and writes it. Between them there is no
`.update()`, no `**` splat, no `setdefault`, no dynamic key construction, and no
locally-imported helper of any kind. There is no code path that could add a key.

**`[VERIFIED]` Nothing wraps it.** The only importer of the module anywhere in
the repository is `tests/test_cio_diligence_p4_p5_research_specialists.py:19`,
which calls `census.census(root)` and asserts on the returned object. No script,
shell wrapper or workflow invokes it at all.

**`[VERIFIED]` Tracked tree at the main tip** — the four strings live in exactly
two files, both documents:

```
$ git grep -n -e live_overlay_root -e stores_live_overlay -e live_budget_report -e note_live 9d92b6e0
9d92b6e0:docs/audits/diligence/P4_RESEARCH_GOVERNANCE_CENSUS_2026-08-30.json:32,135,136,171
9d92b6e0:docs/ops/CIO_V_SWEEP_2026-08-30.md:211,300,468
```

**`[VERIFIED]` A producer was never deleted either.** Across every ref in the
repository's full history, no Python file has ever contained any of them:

```
$ for k in live_overlay_root stores_live_overlay live_budget_report note_live selected_subjects; do
    git log --all --oneline -S"$k" -- '*.py' | wc -l; done
0
0
0
0
0
```

`git log --all -S` over *all* paths returns exactly two commits per key:
`dee83bf6` (which introduced the JSON **and the script in the same commit** —
and `git show dee83bf6:scripts/cio_research_governance_census.py` contains none
of them) and the sweep commit that named them.

**`[VERIFIED]` Nothing was left outside git.** The originating worktree named in
the old evidence, `/home/johnclaw/tradeai-wt-cio-diligence-p4-p5`, is **clean**
(`git status --short` empty at `d959111c`): no untracked scratch producer. The
served release tree contains the strings only in the same two documents.

### Verdict per key

| key | producer | evidence |
|---|---|---|
| `live_overlay_root` | **none** | Never emitted by any `.py` at any commit on any ref. Its *value* is the `root` field of a second census run — see §2. |
| `stores_live_overlay` | **none** | As above. Its *value* is that run's `stores` block, renamed. |
| `live_budget_report` | **none** | As above. Its *value* is a hand-reduced subset of `cio_research_budget_report.py --json`; its `selected_subjects` key exists **nowhere** in the codebase (`select()` emits `selected`, a list of row dicts — `cio_research_budget.py:477`). |
| `free_first.note_live` | **none** | Not a measurement at all — one hand-written sentence. Missed by the sweep. |

---

## 2. Where the numbers actually came from

Not fabricated. Reconstructed by running the existing producer at the root the
old document names. `[VERIFIED]`

```
$ python scripts/cio_research_governance_census.py \
    --root /home/johnclaw/trade-ai-releases/persistent-state --json
census --root persistent-state  'root' = /home/johnclaw/trade-ai-releases/persistent-state
published live_overlay_root      = /home/johnclaw/trade-ai-releases/persistent-state
root string match: True

  instrument_records       path_match=True  pub=True,382039,129   now=True,392062,131
  specialist_artifacts     path_match=True  pub=True,2350,2       now=True,2350,2
  hermes_research_results  path_match=True  pub=True,2287866,471  now=True,2330515,477
  workflow_lineage         path_match=True  pub=True,5820557,8562 now=True,6190302,9099
  research_budget_ledger   path_match=True  pub=False             now=False
  plans_projection         path_match=True  pub=True,12384347     now=True,12831817
```

Every path matches; the counts moved because four of these are live-appending
stores read at a later as-of, which is not a conflict. So `live_overlay_root`
and `stores_live_overlay` are the `root` and `stores` blocks of a **second
census run**, renamed by hand and pasted under the first run's `as_of`.

`live_budget_report` is the third run. `[VERIFIED]`

```
$ python scripts/cio_research_budget_report.py --root CURRENT --json
BUDGET_EXIT=0
day 2026-08-30 cap 5 selected_count 4 slots {'held': 3, 'cash': 1, 'reentry_or_watch': 1}
selected: ['HELD:PFLT', 'HELD:NOC', 'HELD:RTX', 'EXIT:CAST']
records_loaded 40   applied False   ledger_rows_appended 0
```

Four, not the published five: the CASH slot goes unfilled today. Confirms the
sweep's `STALE`.

**No producer was reconstructed, and none should be.** The published value would
be trivial to reproduce with a fifteen-line script, and that script would be
manufacturing evidence for an already-published conclusion — the last row of
CLAUDE.md's *not accepted as completion* list.

---

## 3. The empty book — and how much of P4 it actually invalidates

The brief asked whether P4's *surviving* numbers are invalid too, because the
archived run used `"root": "/home/johnclaw/tradeai-wt-cio-diligence-p4-p5"`, a
worktree with no `data/`, so all six `stores` entries read `exists: false`.

**Answer: only the `stores` block. The rest regenerates exactly.** `[VERIFIED]`,
regenerating against the live release and diffing block by block:

| block | verdict |
|---|---|
| `invariants` (cap 5 · hop 1 · budget 3 · C/D∉`corpus_hit` · ladder) | **VERIFIED_FRESH** — `live == published` compares **True**, whole block, byte for byte |
| `free_first` (7 FRED series, 3 FF factor files, provider/ingest/refresh flags) | **VERIFIED_FRESH** — identical once `note_live` is set aside |
| `stores` | **INVALID** — measured at a root with no data; six false negatives |
| `wave3d_ops_notes`, `cited_modules` | static path lists, unchanged |

So the finding is **not** "the whole package's evidence is invalid". It is: P4's
*code-level* evidence is sound and reproducible; its *store* evidence was a
measurement of the wrong directory; and its *live* evidence was pasted in under
key names nothing emits.

**The root cause of all three defects is one thing.** The census was run from a
checkout instead of the live release. `[CODE]` `_exists()` joins `root` with
`data/cio/...` and reports `exists: false` with exit 0 — the collector cannot
tell an empty book from a wrong root. The hand-added overlay keys existed
*only* to paper over that. `[VERIFIED]` `CURRENT/data/cio` is a symlink into
`persistent-state`, so a single run at the live release root resolves the code
facts **and** the store facts at one `as_of`:

```
$ ls -ld CURRENT/data/cio
... CURRENT/data/cio -> /home/johnclaw/trade-ai-releases/persistent-state/data/cio
```

---

## 4. What was changed

**Evidence JSON** — `docs/audits/diligence/P4_RESEARCH_GOVERNANCE_CENSUS_2026-08-30.json`
is now the **verbatim output of its own producer**, written by the producer:

```
$ python scripts/cio_research_governance_census.py \
    --root /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT \
    --write-evidence docs/audits/diligence/P4_RESEARCH_GOVERNANCE_CENSUS_2026-08-30.json
wrote docs/audits/diligence/P4_RESEARCH_GOVERNANCE_CENSUS_2026-08-30.json
WRITE_EVIDENCE_EXIT=0
```

Four keys struck; the empty book replaced by a real one (131 / 2 / 477 / 9099
rows, `research_budget_ledger` genuinely absent); one `as_of`, one `root`.
Nothing hand-added — deliberately, since a hand-added "what we struck" block
would repeat the defect being fixed. The strike record lives in prose instead,
in the review doc and here.

**Docs that published the struck numbers.** The five-subject budget select is
removed from `P4_RESEARCH_ENGINE_REVIEW_2026-08-30.md` and
`CIO_DILIGENCE_P4_P5_2026-08-30.md` and replaced with the regeneration command
plus today's measured value and its as-of — a daily-varying quantity should not
be frozen in a document at all. The hermes row count now carries its as-of and
root. Both docs' command blocks now pass the live release root; `--root .` is
what produced the empty book.

**P4 status.** `DONE` → `NEEDS_REVERIFICATION` in scoreboard `.md` and `.json`,
with `status_note`, `evidence_regenerated_at` and `evidence_producer`. The
evidence is regenerable again, but this agent does not re-award the DONE it
downgraded: that is the coordinator's, against the proof.

---

## 5. The second NO_PRODUCER row — the `origin/main` pin: **labelled, not automated**

`[VERIFIED]` Nothing reads or writes the scoreboard at all:

```
$ grep -rn "DILIGENCE_SCOREBOARD" scripts/ .github/
GREP_EXIT=1
```

Every value in the NOW block is hand-typed, the pin included.

`[CODE]` A real producer for that exact quantity does exist —
`scripts/cio_release_manifest.py:124 git_origin_main()`, i.e.
`git rev-parse origin/main` — and it is already wired, to the **release
manifest**.

**It should not be wired here, and that is the finding rather than a
limitation.** The pin's job is to record *which tip these numbers were measured
at*. A producer would write today's tip. Since the numbers beneath it are
hand-stamped and several are already `STALE`, auto-refreshing the pin would hand
stale figures a current pin — a green obtained by the wrong artifact, which
CLAUDE.md rates worse than a red. Correctness here requires the pin and the
numbers to move together, and only the numbers have producers.

So the pin is **labelled where it is displayed**: `hand_stamped_no_producer` in
the JSON with a note naming the real producer and why it is deliberately not
used, and a *NOW provenance* section in the `.md`. The scoreboard already had
the right precedent — `now.event_lifecycle.instrument` names its producer; this
extends that convention to the fields that have none.

---

## 6. One thing this could not fix, and it is the more interesting defect

`[VERIFIED]` The status downgrade turns three tests red. Both before and after,
run with the same command; before the edit these four files were **19 passed,
exit 0**.

```
$ python -m pytest -q tests/test_cio_diligence_scoreboard.py \
    tests/test_cio_diligence_p1_ws1.py \
    tests/test_cio_diligence_p4_p5_research_specialists.py \
    tests/test_cio_diligence_p1_ws2_lifecycle.py
TESTS_AFTER_EXIT=1

>       assert now["phase_cursor"] in {"COMPLETE", "DONE"}
E       AssertionError: assert 'P4_PENDING_REVERIFICATION' in {'COMPLETE', 'DONE'}

>       assert "COMPLETE" in md or "all packages P0-P9 DONE" in md
E       AssertionError

FAILED tests/test_cio_diligence_scoreboard.py::test_diligence_json_contract
FAILED tests/test_cio_diligence_scoreboard.py::test_all_packages_p0_p9_done_with_pr_and_proof
FAILED tests/test_cio_diligence_p1_ws1.py::test_scoreboard_p1_ws1_done
3 failed, 19 passed in 0.71s
```

`tests/**` is agent R1's declared file set this wave, so it was not touched.

**Correcting myself:** I first wrote this section predicting the failure would
land on the P4 status assertion at `test_cio_diligence_scoreboard.py:96`. It
does not — the run above shows the file fails earlier, at the `phase_cursor` and
markdown checks, and **line 96 is never reached**. It will fail once those are
fixed. The prediction was a `[DOC-CLAIM]` wearing a `[VERIFIED]` tag until the
command was actually run, which is the precise error this vocabulary exists to
catch.

The point survives the scheduling detail. `test_cio_diligence_scoreboard.py`
reads `CIO_DILIGENCE_SCOREBOARD.json` and asserts the statuses **out of the file
it is validating** — the same shape CLAUDE.md names ("a test asserting literals
from the file it validates"), and the same one the sweep found in this test's
lineage assertions. Because the literal it pins is `"DONE"`, the test cannot
detect a wrong status; it can only **prevent a correct one from being
recorded**. A self-consistency check over a status column is a ratchet that only
turns one way.

Four assertions must move with the downgrade, and all four belong to R1:

| file:line | assertion | reached? |
|---|---|---|
| `tests/test_cio_diligence_scoreboard.py:39` | `now["phase_cursor"] in {"COMPLETE","DONE"}` | **fails now** |
| `tests/test_cio_diligence_scoreboard.py:93` | `"COMPLETE" in md or "all packages P0–P9 DONE" in md` | **fails now** |
| `tests/test_cio_diligence_scoreboard.py:96` | `pkgs[pid]["status"] == "DONE"` for every P0–P9 | not reached; fails once :93 is fixed |
| `tests/test_cio_diligence_p1_ws1.py:95` | `now["phase_cursor"] in {"COMPLETE","DONE"}` | **fails now** |

A note on the second: `"COMPLETE"` is a substring of `"INCOMPLETE"`, so a
phase-cursor token spelled that way would have kept the test green by accident.
The token chosen is `P4_PENDING_REVERIFICATION` specifically so the test fails
honestly instead.

### 6.1 Those three reds do not fail CI — nothing runs them

`[VERIFIED]` The entire P0–P9 diligence suite is invoked by nothing:

```
$ grep -rn "test_cio_diligence" --exclude-dir=.git --exclude-dir=node_modules .
  (every hit outside tests/ is a DOCUMENT: scoreboard proof lists, package
   write-ups, this note. Zero hits in .github/, scripts/, or any runner.)

$ grep -rn "diligence\|scoreboard" scripts/run_release_ci_equivalent.py   -> exit 1
$ grep -rn "diligence" scripts/run_cio_hardening_ci.py                     -> exit 1
$ grep -rln "test_cio_diligence" .github/workflows/                        -> exit 1
```

Every workflow names its test files explicitly; none names these. So the
documented local acceptance went **green on this very commit** —
`ACCEPT_FINAL_EXIT=0`, 17/17 release-proof checks — while three of its own
diligence tests were red, because a docs-only diff routes past the CIO lane and
no lane covers them anyway.

That is the governing principle in miniature: **a component reporting success is
not evidence that it did anything.** The scoreboard's guard tests belong on the
"built and unwired" list beside `test_every_script_compiles.py` before #709 —
except these are worse, because they assert literals out of the file they
validate, so wiring them without first fixing that would gate the repository on
a self-consistency check.

The red is therefore reported, not hidden, and it is a human-typed red rather
than a CI one. Its value is entirely in what R1 does with it.

---

## 7. Also observed, outside this brief

`[VERIFIED]` `CURRENT -> 9d92b6e0-main-exact-phase2-20260830-125544`. The sweep's
§0 headline — that the V0 compile fix was merged to `main` but not deployed, and
both defects were live in the served release — **no longer holds**: the release
serving now is the main tip carrying the fix. Reported for the coordinator; the
sweep's §0 is not edited here.

---

## Rails

No order, no size, no broker write. `MBI_BEHAVIOR=0` throughout. The budget
report was run **dry** (`applied False`, `ledger_rows_appended 0`); no
append-only store was written. No producer was created. No file under
`scripts/`, `tests/` or `.github/` was modified. No cron or systemd entry
proposed or installed. Nothing promoted or deployed.
