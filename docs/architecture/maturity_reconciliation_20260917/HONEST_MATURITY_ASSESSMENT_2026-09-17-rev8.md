Status: ACTIVE
as_of: 2026-09-17 (gate board recomputed hourly; the `2026-09-17T08:35:01Z` run is quoted)
Measured at: served pin `ede0698a5` — equal to `origin/main` `ede0698a5` `[VERIFIED]`
Canonical repo path: docs/architecture/maturity_reconciliation_20260917/HONEST_MATURITY_ASSESSMENT_2026-09-17-rev8.md
Authority: dated reading — READ_ONLY_ADVISORY, `MBI_BEHAVIOR=0`. A gate with no store can never pass.
Revision: 8
Supersedes: Revision 7 (`HONEST_MATURITY_ASSESSMENT_2026-09-16-1759`), Revision 6, Revisions 4–5
See also: docs/architecture/maturity_reconciliation_20260917/CIO_AS_IS_2026-09-17-rev8.md
 docs/architecture/maturity_reconciliation_20260917/REVISION_LEDGER_2026-09-17-rev8.md

# Honest maturity assessment — Revision 8 (2026-09-17)

**The headline number got worse on purpose.** The board went from 8/12 passing
to **0/12 passing** on 2026-09-16, and that is the most honest thing that has
happened to it. Nothing regressed. Eight gates stopped lying.

---

## 1 · The board as it stands

`scripts/cio_gate_measurement_bridge.py`, run `2026-09-17T08:35:01Z`
(agent `alex`, root = the dev tree):

```
  Passing:       0/12
  Not measured:  8
  Failing:       4
  Promotable:    False (authority: HUMAN_ONLY, automatic: False)
```

### Evidence the board is computed from

| Item | Count |
|---|---|
| Real actions | 82 (target ≥ 100) |
| Dedup merges | 25 |
| Snapshots | 65 |
| Darwin scorecards | 232 (78 name an Alex action) |
| Sentinel reviews | 149 (**0** name an Alex action; 144 name another population) |
| Run traces | 22,408 |

### The four that are measured and failing

| Gate | Value | Threshold | Why |
|---|---|---|---|
| `min_artifact_population` | 82 | 100 | 82 advisory actions in `cio_action_ledger.jsonl` (SUPERSEDED dedup merges and GENESIS excluded) |
| `retrieval_provenance_completeness` | 0.9512 | 1.0000 | 78/82 actions carry domain provenance |
| `independent_review_coverage` | **0.0000** | 1.0000 | **0/82** actions have an independent review. 149 review rows exist, but 144 name artifacts outside Alex's action population and 5 carry no artifact id at all |
| `independent_score_coverage` | 0.9512 | 1.0000 | 78/82 independently scored (scorer ≠ producer `alex`, scorer ≠ reviewer); 0 self-scored, 0 scorer == reviewer |

### The eight that are NOT MEASURED — and why that is the honest value

A gate with no store reads `NOT_YET_MEASURED` and **can never pass**. Quoted
from the bridge's own output:

| Gate | Why unmeasured |
|---|---|
| `unsupported_claim_rate` | was hardcoded `0.0` on the argument that a deterministic producer cannot hallucinate. That argues about the producer, not about claim support. Needs a per-claim retrieval-support store |
| `stale_input_refusal_accuracy` | was hardcoded `1.0` on the argument that inputs are collected fresh. Freshness of inputs is not accuracy of refusals |
| `deadline_budget_adherence` | was hardcoded `1.0` from one log line. The per-run store records no elapsed, cost, model-call or deadline value |
| `duplicate_run_rate` | was hardcoded `0.0` because *caught* duplicates were counted. The rate of **uncaught** non-idempotent duplicates is what the gate asks |
| `rollback_test_passed` | was hardcoded `True` by citing a test file. AGENTS.md §0 rule 8 — exit 0 is not evidence; needs a recorded rollback + replay receipt |
| `authority_violations` | was hardcoded `0` from the existence of a deny-list. An enforced control is not an observation |
| `operator_usefulness` | the gate is an **operator rating**; the available number is an automated Darwin grade proxy (0.5432 over 88 grades), which is not the operator's judgement |
| `contradiction_rate` | zero Alex actions have an independent review, so the denominator is empty — a contradiction rate is not computable |

---

## 2 · What the old 8/12 was actually made of

Recorded in commit `9dcba7beb` ("P9/P10: gate honesty"), merged in PR #1048:

> The board read 8/12 passing with `gates_not_measured: 0` for an agent that had
> measured almost nothing.

**Eight dishonest gates, not six.** The distinction matters because the count
has itself been misquoted:

- **Six hardcoded literals** with no evidence read at all — `unsupported_claim_rate=0.0`,
  `stale_input_refusal_accuracy=1.0`, `deadline_budget_adherence=1.0`,
  `duplicate_run_rate=0.0`, `rollback_test_passed=True`, `authority_violations=0`.
- **A seventh**, `operator_usefulness`, reported an automated **Darwin grade
  average under a gate defined as an operator rating** — a proxy standing in for
  a judgement only a human can give.
- **An eighth**, `independent_review_coverage`, **reused the SCORE count**, so it
  inherited the scorer's coverage and reported **0.9512 for a population with
  0/82 independent reviews**.

`gates_passing 8 → 0`, `gates_not_measured 0 → 8`, `gates_failing 4`.
**Every gate that previously passed was one of the dishonest ones; no honestly
measured gate regressed** — `retrieval_provenance_completeness` was already
failing at 0.9512.

`PROMOTION_AUTHORITY=HUMAN_ONLY` and `AUTOMATIC_PROMOTION_PERMITTED=False`
are unchanged.

---

## 3 · ⚠ The catalog still publishes the old lie

`config/agent_maturity_catalog.json` (schema `trade-ai-agent-maturity-catalog-v1`,
`environment: SHADOW`, `production_activation_authorized: false`, 17 agents) still
carries, under agent `alex`:

```json
"acceptance_evidence": [ … "11/12 gates passing (0 not yet measured)" ],
"current_limitations": [ … "Gate measurement: 11/12 passing, 0 not measured, 1 failing" ]
```

Both are contradicted by the live board (**0 passing, 8 not measured, 4
failing**), and neither matches even the superseded 8/12 — they are an older
claim again, from commit `255469380` ("fix 5 failing CIO maturity gates — 11/12
PASS", 2026-08-09).

Worse, the catalog **contains no gate ids at all**:

```
$ grep -c '"gates"'  config/agent_maturity_catalog.json   → 0
$ grep -c 'gate_id'  config/agent_maturity_catalog.json   → 0
```

The bridge gained `--update-catalog`, which writes every gate id into the
catalog. **The `:35` cron line omits the flag**, so the catalog has never been
updated by it. The fix is a one-flag change to a crontab line, which is
operator-only (AGENTS.md §17) — see the ledger's operator-action list.

So the reader-facing artifact claims 11/12 passing, the live measurement says
0/12, and the machine-readable gate list is empty. **A reader consulting the
catalog today is misinformed in three different ways at once.**

---

## 4 · The control number that outranks the gate board

| Counter | Value | Meaning |
|---|---|---|
| `GOAL_WAKE_RECORDED` | **34,912** | the loop wakes, constantly |
| `GOAL_STATUS_CHANGED` | **0** | no goal has ever changed state |
| `GOAL_PREDICATE_SET` | **0** | no goal has a definition of "done" |

Measured `2026-09-17T09:20:01Z` from the baseline receipt, and confirmed
directly against the store (`grep -c` on `data/cio/cio_goals.jsonl` → `0` for
both event types). `GOAL_PREDICATE_SET` is defined at
`scripts/lib/cio_goals.py:59` and emitted only by `set_predicate` (line 555),
which nothing calls.

**This is the number to read first.** A maturity board measures how well the
agent does its work; this measures whether the goal loop has ever done any. It
has not. 34,912 wakes, 29,862 thesis updates (**100 % provider-blocked**), and
not one goal that could ever be closed, because none has a predicate whose
satisfaction would close it.

PR #1059 (OPEN) adds `set_goal_predicate.py` — dry-run by default, `--apply`
operator-gated. Until a predicate exists, `GOAL_STATUS_CHANGED` cannot become
anything but 0, **and a future 0 would prove nothing new**.

---

## 5 · Honesty ledger

- **Fewer passing gates is the correct direction.** 0/12 with 8 unmeasured is a
  truer statement than 8/12 with 0 unmeasured. Do not "restore" the old number.
- **`ok: true` is not a verdict.** The `:40` pilot has written 15 consecutive
  `ok: true` receipts containing **zero** verdicts; every one records
  `status: library_loaded` — the wrapper ran, the pilot evaluated nothing.
- **Exit 0 is not evidence** (§0 rule 8). `check_lane_registry.py` exits 0 and
  prints "lane registry: clean" while two ACTIVE lanes are SILENT;
  `run_cio_hardening_ci.py` is documented to print `CIO HARDENING CI FAILED`
  while exiting 0. Both were read as text, not as status codes.
- **An absent store is `unavailable` with a reason, never `0`.** Where a zero
  appears here it was confirmed against the underlying store.
- **Merged ≠ served, and published ≠ merged.** Revision 7 was emailed as
  canonical while PR #1055 was — and remains — OPEN and CONFLICTING.
- **A hermetic PASS is not an observation.** Test suites passing in CI say
  nothing about what the served release does.

## 6 · The one-sentence version

**The gate board honestly reports that almost nothing about this agent has been
measured (0 passing, 8 unmeasured, 4 failing, not promotable), the catalog a
reader would consult still advertises "11/12 gates passing" with zero gate ids
in it, and the goal loop underneath has woken 34,912 times without ever setting
a predicate or changing a single goal's status.**
