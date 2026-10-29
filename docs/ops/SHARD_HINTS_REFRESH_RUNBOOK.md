Status: ACTIVE
as_of: 2026-10-29T14:41:00Z
Canonical repo path: docs/ops/SHARD_HINTS_REFRESH_RUNBOOK.md
Authority: coordinator/operator housekeeping — the hints are a CI-generated artifact (§0 rule 8: never hand-author a measured value)

# Shard duration hints — refresh runbook (unblocks every PR)

## Why every PR is red

`config/ci_shard_duration_hints.json` was last refreshed from `ci-gate` run `39661659376` (2026-10-10).
Since then 151 more test files were registered, so the coverage gate
`tests/test_ci_duration_hints_20261021.py::test_at_most_ten_percent_of_registered_files_lack_a_shard_hint`
fails: "151 of 1518 registered test files (10.0%) have no hint (limit 10%)." This is a shared gate, so
it blocks every PR, not just the one that added the files.

## Why this cannot be done by hand

The hints are measured per-file wall seconds **on the GitHub Actions runner**. Values measured locally on
the operator's box would produce wrong shard balancing (the 2026-10-21 fix sourced from CI for exactly this
reason). Fabricating 151 values, or attributing local measurements to CI run `39661659376`, would recreate
the "fiction" the gate exists to prevent (AGENTS.md §5, §8A).

## The procedure (chicken-and-egg break)

The refresh must come from a **green full-suite run**; the full suite cannot go green because of the drift.
Break it once, mechanically:

1. **Temporarily raise the threshold** so one run can go green:
   - Edit `scripts/run_cio_hardening_ci.py` `HINT_MISSING_MAX_FRACTION` from `0.10` to e.g. `0.12`.
   - (Or add a one-run `TRADEAI_CI_HINTS_RELAXED=1` env exemption — the minimal-touch option.)
2. **Run the full sharded suite to green** (the normal `ci-gate` workflow on `main`).
3. **Take its `cio-shard-timings` artifact** (the `--verify-shards --timings-out` output) and commit it as
   `config/ci_shard_duration_hints.json`, with the new `source_run` and `source_sha` from that run.
4. **Update the test pin** in `tests/test_ci_duration_hints_20261021.py`:
   - `source_run` → the new run id; `source_sha` → the new 40-char HEAD.
5. **Revert** the step-1 threshold relaxation (`0.12` → `0.10`).

## Verify

```
.venv/bin/python -m pytest tests/test_ci_duration_hints_20261021.py -q
# expect: all pass, and hint_coverage reports 0 missing
```

## What this unblocks

Every open PR that is red solely on `ci_duration_hints_20261021` — including #2266, #2268, #2177, #2118,
#2175, #2281, #2282 — goes green and (for the armed ones) auto-merges via the `--auto` queue.
