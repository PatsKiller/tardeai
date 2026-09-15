# Trade-AI work log — 2026-09-15

```
Date:          2026-09-15 (Tuesday)
Operator ask:  "Fix everything, even what's not yours. You're the chief architect." (independent architect
               review R-01..R-10 / E-01..E-10, cutoff 15:20:37Z), plus the watchlist lifecycle decisions of the
               morning (CIO owns entry state and BUY; operator and CIO alerted; small caps in scope, labeled).
Live at end:   see "Identity" at the bottom (filled in after the last deploy of the day).
Rails:         MBI_BEHAVIOR=0. No broker writes, no orders, no stops, no 2FA/AT Stage 14/BF-1 changes.
```

This log supersedes the identity statements in the 2026-09-14 set (`TRADE_AI_WORKLOG_2026-09-14.md`, the As-Is /
Future-State documents and fact bases A–F). Those documents remain the measured record of 2026-09-14; where they say
"live at 341bce2c1", read this log for what changed after.

## 1. What shipped (merged, deployed, verified)

| PR | Merged (ET) | Merge | What it fixed | How it was verified |
|---|---|---|---|---|
| #1026 | 01:23 | `89fe742fa` | Word/PDF docs rev 2 (fact-base headers, INDEX regen) | CI green; Drive + email |
| #1027 | 10:42 | `a53b3d32f` | Pullback + watchlist proposals expiring on arrival | 10 tests; E-05 monitor later |
| #1029 | 11:31 | `46f7c0904` | Watch-decision refresh queue deadlock; NaN in decision packets | queue drained |
| #1031 | 12:21 | `7d5a22ce3` | Watchlist lifecycle: lock holders, card catalysts, small-cap labels, agent retries, goods check, incubator plan levels, **CIO entry state (BUY_READY / ENTRY_NEAR) with operator + CIO alerts**, HTML alert polish, material-change notice with direction / catalyst / provenance / strategy / CIO view | first live run 12:30: 8 BUY_READY alerts + 28-name digest sent |
| #1033 | 15:25 | `f5fc9e334` | Architect remediation R-01..R-09, E-03..E-07 (table below) | health 64/100 (15 critical) → 70/100 (7 critical) |
| #1034 | 16:40 | `7be78a58c` | ENABLE_TELEGRAM=1 no longer disables operator alerts; entry-state pages only on moves toward a buy; CIO desk delivery receipt; E-10 daily spend-cap proof; archive-tripwire false trip | served-copy split=0 |
| #1035 | 16:40 | `d6bdce31f` | Cron dead-script check resolves like cron; indicator lane names the script that exists | live crontab: 0 findings |
| #1036 | 18:03 | `b9276acb8` | Hotfix: bare `%` in a SQL comment crashed the material-change detector | read-only run on live code: 31 changes, 0 errors |

## 2. Architect findings — measured cause and fix

| ID | Finding | Measured root cause | Fix |
|---|---|---|---|
| R-01 | audit ledger chain break; `submit_requested` missing | One break (line 1558) = the 2026-08-26..09-13 served-copy split fork. Tests mirrored every event into the production `audit_ledger_events` table (14,291 junk rows, incl. every `submit_requested`). | Fork pinned by event_id + both hashes (`config/audit_ledger_acknowledged_forks.json`); no row rewritten. conftest disables the DB mirror in tests. Coverage is WARN, not FAIL: `submit_requested` has no writer outside `scripts/brokers/` (out of scope). |
| R-02 | finnhub 401; research_discovery stale 161h | finnhub retired 2026-09-13 (row kept its last 401). Discovery surfaced 60 names/day, all already listed; `ON CONFLICT DO NOTHING` wrote 0 → "error". | Retired providers skipped (warns only if called after retirement). Discovery refreshes listed ideas; healthy since 18:07. Schwab: operator re-authorized 17:45 (token valid to 09-22). |
| R-03 | 96–186 agent jobs stuck | Market canary and off-peak drain took the same flock at the same second; `flock -n` lost every daytime tick. | Drain waits up to 240 s. Auto-queue only validated securities. |
| R-04 | research lanes firing | `research_lane_health.json` only ever wrote firing lanes; recovered lanes fired for weeks. Two "orphaned" lanes were registry name mismatches; catalyst graph had no schedule. | Recovered lanes recorded ok (12 → 2 firing). Catalyst graph scheduled 06:10. |
| R-05 | unprotected position | Alpaca **paper** option RTX260918C00160000. | Operator: ignore. |
| R-06 | docs identity lag | Rev-2 package described `341bce2c1`. | This log + identity notes + Word/PDF rev 3. |
| R-07 | 8,028/8,029 empty governed verdicts | Desk suggestions drained into `watch_directive_hits` (no verdict/state columns) within the minute they were staged. | Staging state carried while the hit is under review; verdict snapshots non-empty after deploy. |
| R-08 | host resilience | fancontrol failed 09-12: hwmon renumbered (hwmon4 is now the Wi-Fi chip). Disk 86%. No UPS. | fancontrol watched by health agent. Repair (sudo), UPS: operator. |
| R-09 | hygiene | RAG left borrowed connections idle in transaction; `system_health_agent` re-ran the disabled `cio_decision_engine` daily (≈340 HUMAN_REVIEW rows per run). | Borrowed connections returned idle; engine retired from self-heal. |
| R-10 | MVL SHADOW | Agent runtime has no LIVE environment; `OPERATIONAL` fails closed until every maturity gate is measured PASS. | See §5. |
| E-03 | "health 200" masks unhealthy | Transport `ok` vs verdict. | `/api/v2/health` adds `healthy` + `headline`. |
| E-04 | verdict-store monitor | — | `governed_verdicts_empty_while_desk_in_zone` |
| E-05 | expire-on-arrival metric | 136/215 proposals expired within 1 h. | `proposals_expire_on_arrival`; bridge 6 h same-plan cooldown. |
| E-07 | host telemetry | — | fancontrol in watched units; disk check already present. |
| E-10 | spend proof | — | `llm_spend_policy_unproven` reads the host cap file. |

## 3. Regressions introduced today and fixed the same day

| Introduced | Symptom | Cause | Fixed by |
|---|---|---|---|
| #1031 | material-change detector crashed every run 12:30–18:04 (no notices) | SQL comment "moved 21%" inside a parameterized query | #1036 + a guard test that formats every `execute()` string |
| #1031 | agent-job drain crashed every run after 12:23; 186 jobs queued | deferral wrote maturity status `pending`, which the table constraint forbids | maturity-status hotfix (this evening) |
| #1033 | ARCHIVE TRIPWIRE page | fork acknowledgement quoted the reconcile archive path | #1034 |
| #1033 | indicator lane pointed at a never-merged script | registry match guessed from a dead cron line | #1035 |
| cron edit 12:36 | operator alerts silent at 12:40 | cron line loaded `cio-operator-live.env` (`ENABLE_TELEGRAM=1`) | cron line corrected; #1034 accepts 1/yes/on |

Lessons: tests that mock the cursor never format the SQL; a check that flags `%` must accept `%%`; editing a CRLF file with
`write_text` trips the line-ending guard; the health daemon can start seconds before the dev-tree fast-forward — restart it.

## 4. Host changes (not in git; crontab backups kept)

- Watchlist lanes: `catalyst_symbol_impact_writer` 07/12/17:20, `cio_entry_state_runner` every 10 min 09–16 (loads the
  runtime env + `cio-telegram.env`), `watch_goods_consistency_check` 08/12/16:40, `build_catalyst_graph` 06:10.
- `DEAD_SCRIPT_20260915` comments (never merged to main): `cron_freshness_watcher.py` (12,066 failures),
  `refresh_reentry_resistance.py`, `run_governed_cio_tis_digest.sh`, two `data_broker_indicator_refresh.py` desk lines;
  05:45 indicator refresh now runs `scripts/indicator_cache_refresh.py`.
- `deepseek_balance_snapshot` loads the runtime env (was `no_api_key` every hour).
- Operator "agents clear": the 5 retired agent-job cron comments were masked so the containment auto-restore cannot
  revive them, then `AGENT_JOBS_P0_CONTAINED` was archived with a tripwire note.
- Operator "remove the stale caps": `LLM_GLOBAL_DAILY_USD_CAP` removed from `.env` (0.50) and `agent-operator.env`
  (0.25); the ruling cap is `~/.config/tradeai/llm_global_daily_usd_cap.env` ($2.00). The Bitwarden-rendered runtime
  env still carries 0.50 until the secret is removed in Bitwarden (operator).

## 5. MVL (R-10) — operator said "promote"

The runtime contract (`scripts/agent_runtime/contracts.py`) has environments `LAB` and `SHADOW` only; promotion means an
agent's `deployment_state` becomes `OPERATIONAL`, and `maturity_gates.assert_not_operational` raises unless every gate is
measured and PASS. Promotion therefore waits on measured gates, not a config flip; the per-agent gate report is in the
session record and the next step is the acceptance run that measures them. Broker, order, approval, 2FA and secret
authority stay DENIED in every state.

## 6. Operator decisions recorded today

- CIO owns entry state and BUY; operator and CIO alerted; small caps admitted and labeled.
- Active Trader is a notifier, not an executor.
- One combined watchlist PR.
- R-05 paper call: ignore.
- Schwab re-authorized by the operator.
- Agents: clear containment.
- Supersede 3,257 HUMAN_REVIEW decisions (pending: the bulk update was held by the session permission guard).
- Word re-render and Markdown both.
- MVL: promote (gated, §5).
- Remove stale 0.50 / 0.25 LLM caps.

## Identity

```
(filled after the final deploy of 2026-09-15)
```
