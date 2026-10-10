Status:      ACTIVE
as_of:       2026-10-09T23:00:06-04:00
Measured at: main c4782f219 / live b7dbe6e60-main-exact-phase2-20261009-210323

# Cron / n8n Remediation Plan — from the verified inventory

**Status:** v1, 2026-10-09 ~23:00 ET. Owner: verifier session trade-ai-v12-rebuild-0e. **Operator freeze in force:** no cron job is
migrated, modified, disabled, consolidated or retired without operator approval of its inventory row (2026-10-09 21:50 ET).
Every item below is a **proposal awaiting approval** unless marked APPROVED. Evidence per row:
`cron-inventory/enrich_S*.csv` (`evidence_notes`) and `cron-inventory/analysis/`.

## 1. Classification of every scheduled unit (676 rows; 560 active)

| Classification | All | Active | What it means for the plan |
|---|---|---|---|
| Requires Refactoring Before Migration | 247 | 247 | Mostly **policy-blocked first** (allowlist `never` list: senders, ingest/memory/learning writers, LLM lanes gated to R1/R2), then code: dry-run flag, receipt, honest exit code, lock |
| Candidate for Retirement | 166 | 60 | 106 already inactive (archive record); **60 live lines/timers that do nothing or duplicate others** |
| Retain as Existing Cron Job | 134 | 131 | Stays on cron/systemd; n8n heartbeat-watches it |
| Not Recommended for Migration | 93 | 92 | §23.14 broker/order/stop/secret/daemon lines and n8n's own watchdogs |
| Ready for Migration | 21 | 21 | Allowlist entry + matching lock + dry-run + receipt already exist |
| Requires Custom Development | 15 | 9 | The 6 generic workflows (built, not imported) + bespoke lanes |

Per shard: S1 R53/Ret18/Keep14/NR8/CD1/Ready0 · S2 R55/Keep23/NR7/CD3/Ready3/Ret3 · S3 R39/Keep26/NR13/Ret8/CD5/Ready3 ·
S4 R52/Keep18/NR13/Ready8/Ret3 · S5 R34/NR27/Keep19/Ret10/Ready4 · S6 Ret124/Keep34/NR25/R14/CD6/Ready3.

## 2. Decisions

| # | Item | Decision | Status |
|---|---|---|---|
| D1 | maturity-remeasure double-scheduled (n8n e18d7849b4142927 live + cron L1000 `--write`, collide Mon 10-12 06:40) | **(b) unpublish the n8n live workflow; cron L1000 stays the single scheduler** | **DONE 22:30 ET** under grant 26b8747d6cc949bb: unpublished + n8n restarted; 10 active, e18d not loaded |
| D2 | F2 relay addressing | Keep the IP in workflows; pin the subnet (runbook `packets/n8n-network-pin.md`), Sat window | APPROVED 2026-10-09 ~22:15; grants requested at the window |
| D3 | F3 pre-import guard | PR #1636 | **MERGED** c4782f219 (not promoted) |
| D4 | F1 archive 16 RELAY_HOST workflows | grant ee4dfdf11479cd3c | awaiting operator UI clicks (backups taken) |

## 3. Fix plan — ranked

### P0 — operator-visible breakage, fix first (each needs operator approval of the row + the named grant)
| # | Finding (verified) | Fix | Owner / approval |
|---|---|---|---|
| 1 | **L227 proposal Telegram alerts dead since 10-06 ~14:54 ET**: line calls `.venv/bin/python` relative to CURRENT (no .venv in releases; "No such file" 3,443/6,186 log lines); registry signal is log mtime so it shows green | Replace with `$PY` like L232 (fixed 17:29) | crontab edit — **cron grant** + row approval |
| 2 | **Urgent emails never delivered (L570)**: `gog` not on cron's PATH, 8/8 failures | Absolute path to gog / PATH in crontab | cron grant |
| 3 | **Retiring the P1 digest on 10-08 cut off process_reaper's alerts** | Route reaper alerts to SYSTEM ops family / fan-in | agent PR |
| 4 | **Fidelity stop sync L712 logged "registry empty: retired every active stop for the account"** | Operator checks stop coverage at the broker | **operator only** (broker subsystem, §0 rail 2) |
| 5 | **Fidelity/SnapTrade holdings not synced ≥ 11 days** (L479/480/482): `config/snaptrade_accounts.json` only in the dev tree | Move the config to persistent-state and point the job at it | agent PR + config-write |
| 6 | **DOF auction pipeline (L152) failing every Saturday since ≥ 08-29** (DB auth) while exiting 0; **L156 transcript purge never deletes** (`exec()` in a comprehension can't set `pw`) | Fix credentials path / script; honest exit | agent PR |

### P1 — safety and governance
| # | Finding | Fix | Owner / approval |
|---|---|---|---|
| 7 | **L323 auto-proposal-general is a paper-ORDER lane the registry deems dispatch-eligible** (`MOMENTUM_SCALP_VALIDATION_SUBMIT=1` → `submit_paper`) | Eligibility test reads env/argv flags; mark row stay-behind | agent PR (registry lock) |
| 8 | **commit-hermes-daily (L518) would `git push origin main` from cron**; **L429 profit-capture does git checkout/commit/push from cron** in the dev worktree; L556 coder-dispatch opens PRs from cron | Remove the push paths or retire the jobs | operator decision (rail 4) |
| 9 | **cron_self_heal can re-add crontab lines itself** (conflicts with §9.3: scheduler edits are operator-only) | Make it report-only | agent PR |
| 10 | **tradeai-continuous** (system timer, 7.5 h daemon, dev tree) has **no registry row** | Add the row; run from the release | agent PR + service grant |
| 11 | **~40 lanes must stay outside n8n** that the mechanical pre-check missed (senders, CIO/persona loops, ingest writers on the never-list); the broker-token matcher also has false hits ("deploy" in cash-redeploy, "stop" in stoplights/scripts/topic, "size" in synthesizer) | Correct `must_remain_outside_n8n` in the registry; make the token test word-boundary + env-aware | agent PR |
| 12 | **Dev-tree code run by served schedulers**: L92, L128, L191, L194, L196, L230, agent-router L135/L173/L200 (repricer + stops.json producer with `\|\| true`), L567, L613, L617, L700, L802, L804, 14 timers, health agent | Point at CURRENT via `$PY`/release paths | agent PR + cron/service grants |
| 13 | L1046 comms-lifecycle deletes after archiving; no rail-6 tripwire found | Add/verify tripwire | agent PR |
| 14 | L956 runs a script from ~/trade-ai-campaigns (outside repo and release) | Move into the repo or retire | operator decision |

### P2 — failing or failure-hiding jobs (honest exit codes, then fix)
| # | Finding | Fix |
|---|---|---|
| 15 | portfolio-live-monitor timed out 30/32 tick runs | Profile + raise budget or split |
| 16 | Hermes CIO worker failed 32× this week (first OOM victim) | Memory cap + root cause |
| 17 | provider-cost-reconcile ends every step `\|\| true` (always exit 0) | Honest exit |
| 18 | hermes_config_governor fails 13/13 (writes "a -> b" into a json column, `:58-64`) | Fix serialisation |
| 19 | self-tune (L577) writes weights into the release dir → wiped every promote (served yaml from 08-27) | Write to persistent-state |
| 20 | **VWAP job (L608) `*/20 13-21` is UTC hours** → misses the morning session | `*/20 9-16` ET (cron edit) |
| 21 | Hermes coordinator always exit 0 (curator step FK error on 75/75 ticks); incubator screener PROCESS_NOT_REGISTERED; watch-review workers "legacy DeepSeek model id rejected"; system_rollup_daily insert failing since 10-05 (jsonb size) while green; L746 missing column; L944/L981 exit 0 on abort/cost-cap; L977 password auth; micro-recorders L1007/L1008 ~45–50% InterfaceError | Per-job fixes + honest exits |
| 22 | Orchestrator midday slots L1030 (12/14/16:00) killed at +21 min, reports empty 5/5 days | Timeout/budget fix |
| 23 | Scalp-live L1050 output_signal file and receipts do not exist → cannot be heartbeat-watched; 7 cycles on 10-09 at 133–272 s vs 295 s timeout; possible double GO with L961 | Write the receipt; verify dedupe |
| 24 | Monthly (L138) / weekly (L131) reviewers fail (Anthropic credits / empty LLM); L190 skips (no key); L469 "credit balance too low" | Provider routing per §9.2 |

### P3 — retire / consolidate (60 active retirement candidates; examples, each with proof in the inventory)
| Group | Members | Action |
|---|---|---|
| **Persona timers that do nothing** | maria, vega, risk_agent, tax_agent, sentinel, reflection (0 tasks / 7 d); aegis (DESIGNED), iris (0 jobs), argus & darwin (refuse every job as stale) — ~12,000+ fires/week | Retire (steph, morgan stay) |
| Workers with no work | hermes-advisory-cache-worker (0/388), high-llm-execution-worker (0 jobs, loads gemma3:12b each run), hermes-source-discovery-dryrun (0/8), L998 approval reconcile (NO_ACTION 140/140), advisory-shadow-session (6/6 fail, target exceeded) | Retire |
| Never-run / no-op lines | L157, L789, L822, L748, L633, L687, L609, L588, L279 (ask_alerts empty), L260, L264, L271, L125 | Retire |
| L273 `risk_gate --test` writes synthetic rows into risk_gate_results/audit_log hourly | | Retire (pollutes audit) |
| Duplicates | 4 stale-proposal cleaners (L132, L181, L188, L170); L184/185/186; L199+L205 vs L213; L92/L128 same minute; L479/L480; L759/L765; L760/L766; L821/L822; L844–846; L697/698; L674/676; L1010/L1011; L499 vs positions_sync; L468/L471; L600 vs L184–186; L561 vs L516 | Merge per `analysis/duplicates.csv` |

## 4. Migration roadmap (after approvals)
1. **Ready for Migration (21)** → first dispatcher wave once the six generic workflows are imported and activated (one cron grant, §23.11), shadow → canary → cutover per §23.12.
2. **Requires Refactoring (247)** → the R1/R2 amendment decides which policy-blocked classes may move at all; code work only after that.
3. **Requires Custom Development (15)** → the six generic workflows first (they unlock everything else).
4. **Not Recommended (93) + Retain (134)** → stay; heartbeat watcher covers them.
5. **Retire (60 active)** → after operator approval per row; comment, never delete (rail 6).
