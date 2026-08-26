# R5 — CPCV Path Construction

AFML Ch. 12 step 2: chain purged splits into full backtest **paths**.

R1 already generates `combinatorial_purged_splits`. R5 does not replace that.
A path is a sequence of those splits whose test-group sets **partition** the
group axis. Every sample is tested exactly once on a path. P&L is the
chronological concatenation of test-period returns. The family of paths is
reported whole — never a winner-only path.

Fail-closed when `n_groups % n_test_groups != 0` (cannot form covering paths).

Authority: `READ_ONLY_ADVISORY`. Module: `scripts/lib/research_governance/cpcv_paths.py`
