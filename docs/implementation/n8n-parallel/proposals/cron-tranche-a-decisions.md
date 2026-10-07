# Cron tranche A — operator decisions (2026-10-07)

Rank 1 applied only the unambiguous edits (see `crontab_after_tranche_a_rank1.txt`): the annual one-off
`morning_eval_check.sh` (L400), the exact cron twin of `tradeai-maturity-feeds.timer` (L725, same minute
and args), two cadence merges (`watchlist_enrichment_sweep` → `*/30 9-16`; `plan_drift_revalidator` →
`0 10,13`), a missing lock on the 30-minute `auto_proposal_generator` line, and 16 commented-out job
lines. Two study findings were **corrected on verification**: the two auto-proposal lines are
complementary (momentum-scalp only vs. everything else), and the 16:10 repricer line is the only place
`holdings_reconcile.py --apply` and the look-through resolver run. Both stay.

Decisions that change cadence, tree or ownership and are therefore yours:

| # | Lines | Today | Options | Recommendation |
|---|---|---|---|---|
| D1 | L855 `watch_decision_scheduler.py --run */15 7-16` vs `tradeai-watch-decision-scheduler.timer` (09:35, 11:00, 13:30, 15:45 + weekend 09:00/14:00) | 40 cron runs/day + 4 timer runs; the timer is the declared lane | (a) keep both (status quo); (b) delete the cron line → 4 runs/day; (c) delete the timer, declare the cron line | (b) if the 4-slot design from the watch desk is still intended; otherwise (c) |
| D2 | L763 `hermes_momentum_catalyst_researcher.py --source scalp 25 6-15` (CURRENT, 10/day) vs `hermes-momentum-catalyst-morning.timer` (every 15 min 08:00–15:45, **dev tree**, 32/day) | 42 runs/day from two trees | (a) repoint the timer to CURRENT and delete the cron line (32/day); (b) disable the timer and keep the cron line (10/day) | (b): fewer paid research calls and CURRENT code; revisit cadence with the Hermes owner |
| D3 | L1006 `hermes_external_feedback_loop.py 15 * * * *` (off-peak wrapper, cap $2.00) vs `hermes-external-feedback.timer` 04:00 (`--model deepseek-v4-flash`) | hourly + nightly, different model and cap | (a) keep both; (b) keep hourly only; (c) keep nightly only | (b): the hourly line carries the explicit cap |
| D4 | L132 `paper_trade_monitor.py */2 9-16` | documented as replaced by `unified_stop_supervisor`, but the supervisor header says it does not move stops in this phase | (a) keep; (b) verify the supervisor owns R-multiple stop moves, then delete | (b), with the stop owner's sign-off; paper lane only |
| D5 | L360/L361 `atm_position_reconciler.py */15 9-16` and `45 16` | never execute (log directory missing), 165 wasted firings/week | (a) create `logs/atm_position_reconciliation/` and keep one line (activates a reconciler that has not run for weeks); (b) retire both and declare RETIRED | (b) unless the ATM owner wants it back; it is broker-adjacent |

Rank 2 (poller service) is installed under the config-write grant once approved; rank 3 (health tick) and
rank 4 (maintenance pipeline) follow as code PRs with their own registry rows.
