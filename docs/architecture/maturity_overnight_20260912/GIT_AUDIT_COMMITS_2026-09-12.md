# Git audit — every commit this campaign produced

Branch `feat/l3-record-integrity-20260912`, PR #975, based on
`eb648174aebc75d0e34eb105b8ff54925efccc7b`.

No force-push. No history rewrite of any pushed commit. One amend, of an
unpushed local checkpoint, to drop generated timestamp churn
(`CI_EVIDENCE_LATEST.md`, `RELEASE_MANIFEST_LATEST.md`,
`OPTIONS_RISK_BLOCK_MATRIX.md`) that running local acceptance regenerates.

## d40316a2c — fix(board): the three oscillator defects PR #974 reported and PR #973 did not close
```
 apps/command-center-v3/package.json                |   2 +-
 .../defense/redesign/DefenseRedesign.tsx           |   7 +-
 .../src/lib/oscillatorDisplay.test.ts              |  44 +++++++++
 .../command-center-v3/src/lib/oscillatorDisplay.ts |  47 +++++++++
 docs/INDEX.md                                      |   2 +-
 .../CONTROL7_LOCAL_EQUIVALENT.txt                  |   2 +-
 .../sop-1.2.0-20260902/CONTROL7_WORKFLOW_PROOF.txt |   2 +-
 .../sop-1.2.0-20260902/FULL_TEST_MATRIX.txt        |   2 +-
 .../sop-1.2.0-20260902/RUFF_SHELLCHECK.txt         |   2 +-
 scripts/ai_local_acceptance.sh                     |  18 +++-
 scripts/api_v2.py                                  |  18 +++-
 scripts/run_cio_hardening_ci.py                    |  24 +++++
 tests/test_oscillator_board_reads.py               |  24 ++++-
 tests/test_oscillator_board_truth_20260912.py      | 109 +++++++++++++++++++++
 14 files changed, 289 insertions(+), 14 deletions(-)
```

## 81274a714 — chore: drop an unused loop variable left by the deadline change
```
 scripts/lib/free_first_circulation.py | 4 +---
 1 file changed, 1 insertion(+), 3 deletions(-)
```

## 5756d80a6 — feat(l4): revisit commitments after their horizon, and say what could not be scored
```
 scripts/lib/commitment_outcome_sweep.py         | 316 ++++++++++++++++++++++++
 scripts/sweep_commitment_outcomes.py            |  84 +++++++
 tests/test_commitment_outcome_sweep_20260912.py | 252 +++++++++++++++++++
 3 files changed, 652 insertions(+)
```

## 872ac5ed2 — feat(lanes): declare the 14 undeclared schedules, the maturity spine among them
```
 config/lane_registry.json | 222 ++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 222 insertions(+)
```

## 22adecd0f — fix(l2,l5): the circulation lane reports its own failures, and health can go false
```
 scripts/check_state_root_split.py                  | 181 ++++++++++++++++++++
 scripts/free_first_refresh.py                      |  53 +++++-
 scripts/lib/free_first_circulation.py              |  83 ++++++++-
 scripts/lib/free_first_scheduler_health.py         | 147 +++++++++++++++-
 scripts/run_free_first_circulation.sh              |  19 ++-
 tests/test_free_first_deadline_20260912.py         | 145 ++++++++++++++++
 tests/test_free_first_scheduler_health_20260912.py | 185 +++++++++++++++++++++
 tests/test_r93_free_first_scheduler.py             |  35 +++-
 tests/test_state_root_split_20260912.py            | 139 ++++++++++++++++
 9 files changed, 974 insertions(+), 13 deletions(-)
```

## e48ff8aaa — fix(l3): judgment records carry real cost, prompt digest, release and a unique id
```
 config/llm_lane_floors.json                 |   6 +
 scripts/ai_local_acceptance.sh              |  14 +-
 scripts/lib/judgment_schema.py              |   4 +
 scripts/lib/l3_judgment_author.py           |  53 +++++-
 scripts/lib/l3_judgment_cache.py            |  38 +++-
 scripts/lib/llm_consumption.py              | 107 ++++++++++-
 scripts/lib/llm_lane_reservation.py         | 191 +++++++++++++++++++
 scripts/lib/persistent_agent_wake.py        |  26 +++
 tests/test_l3_record_integrity_20260912.py  | 275 ++++++++++++++++++++++++++++
 tests/test_llm_lane_reservation_20260912.py | 268 +++++++++++++++++++++++++++
 10 files changed, 969 insertions(+), 13 deletions(-)
```

