# CURRENT cutover — execute after 2026-08-27 close

**Do not run during the DecisionPayload burn-in.** Dual-root: serve CURRENT,
most systemd + crontab still `WorkingDirectory` / `cd $PROJ` =
`~/trade-ai-v12-rebuild/trade-ai-v12-rebuild` (often a dirty feature branch).
That is the same disease as the silent docs overlay. Zero LLM budget.

## Already on CURRENT scripts

| Job | When |
|---|---|
| `tradeai-research-lane-health` timer + crontab `*/15` | 2026-08-21 |
| Drive `sync-docs-to-drive.sh` crontab `:05` | 2026-08-21 |
| `watch_alerts_eval.py` crontab `*/20 9-16` | 2026-08-21 (emit-only) |
| `portfolio-server.service` | exact-main pin |
| CIO material-scan / telegram / reactive drop-ins | PYTHONPATH=CURRENT |

## Gap (inventory, not a switch-flip tonight)

~80 user systemd units + the rest of crontab still execute rebuild tree
scripts. Rebuild `feat/two-way-watchlist-curation` ≠ `origin/main` ≠ CURRENT
`cf5768a6`. Watch emit existed on CURRENT and was invisible because cron
used rebuild. Advisory cache worker has no `AGENT_DECISION_PAYLOAD` and no
`emit_advisory_opinion_payload`. Holdings refresh has no emit at all.

## Plan (after 8/27 close)

1. **Inventory.** `systemctl --user list-units --type=service --all` +
   `crontab -l`: classify each ExecStart / `cd $PROJ` as
   CURRENT-already / rebuild / other-worktree / dead.
2. **Pin check first.** `current_pin_integrity.py` must be green on the
   then-CURRENT SHA. No cutover onto a hybrid.
3. **Batch A — capture producers (no broker).** advisory-cache-worker,
   holdings_llm_refresh, opportunity book emit, remaining CIO timers.
   For each: `WorkingDirectory=CURRENT`, `Environment=AGENT_DECISION_PAYLOAD=1`
   (only if already a decision surface), `MEMORY_BEHAVIOR_INFLUENCE=0`.
   ExecStart venv may stay rebuild `.venv` (shared).
4. **Batch B — research crontab.** `research_scheduler`, hermes workers,
   DeepSeek writer: CURRENT `scripts/` so `llm_lane` import cannot drift.
5. **Batch C — everything else.** Health agents, quotes, journal — still
   READ_ONLY_ADVISORY. One unit per PR, `current-pin` must stay green.
6. **Never** point broker/order/stop/2FA units at a dirty rebuild branch
   “because that’s where they always ran.” Those stay operator-gated and
   out of this cutover unless a later explicit order.
7. **Rollback.** Each batch is a crontab/systemd drop-in diff; restore
   `PROJ=` rebuild if a unit fails health.

## Capture wiring to land with Batch A (not now)

- `holdings_llm_refresh.py`: after a successful parse, `emit_decision_payload`
  surface `situation` or a new `holdings` value in `VALID_SURFACES`. Flag-gated.
- `build_opportunity_book`: one payload per ranked top-N row, surface
  `opportunity`.
- `hermes-advisory-cache-worker`: CURRENT tree + `AGENT_DECISION_PAYLOAD=1`
  so `emit_advisory_opinion_payload` actually runs. **This can change
  advisory text vs the dirty rebuild branch** — not during burn-in.

## Friday weekly oversight (do not auto-pay)

Crontab `15 18 * * 5` `scripts/defense_weekly_paid_review.py` is **ChatGPT OAuth
auto**. Paid Claude is operator-only: `--apply-paid`. **Never** add that flag to
crontab. 2026-08-21 18:16 ET spent $0.396 `claude-opus-4-8` because
`weekly_paid_review=true` auto-called `run_paid_review`.

Retarget this line to CURRENT with Batch C (after 8/27). Until then the rebuild
tree must carry the same script/config or 8/28 will spend Opus again. Do not
promote CURRENT for this during the payload window.

## Success

- `systemctl --user show UNIT -p WorkingDirectory` is CURRENT for Batch A/B.
- `research_lane_health` `current-pin` ok.
- New v1 rows for watch (RTH), holdings, opportunity, advisory.
- Rebuild tree is a git checkout of `origin/main` or is no longer ExecStart.
