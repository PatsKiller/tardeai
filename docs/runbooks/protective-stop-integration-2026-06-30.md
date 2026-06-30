# Protective Stop Integration Runbook — 2026-06-30

## Scope

Integration branch: `fix/stop-execution-journal-reentry-integration`.

This branch stacks the DB timeout guard, holding quote timestamp fix, OCO DD hardening, stop-management UI decision layer, and stop lock-in trailing advisory. It does not enable Schwab OCO brackets.

Draft PR: https://github.com/PatsKiller/tardeai/pull/33

## Guardrails

- `OCO_BRACKETS_SCHWAB` remains unset/off.
- No autonomous live submit path is enabled.
- Schwab `STOP`, `STOP_LIMIT`, and `TRAILING_STOP` can submit only after the existing operator approval and per-order 2FA flow.
- Fidelity remains manual-ticket only. Trade AI does not submit Fidelity broker writes.
- Mutual funds, money-market funds, cash, FCNTX, and SPAXX are not live stop-order candidates.

## Schwab Evidence-Bound Approval

Protective-stop confirmation now binds the fully approved intent to the exact Schwab order JSON before the broker POST. The stored evidence includes:

- intent id and correlation id
- account, broker, symbol, quantity, order type, stop/limit/trail fields
- exact order spec hash
- readiness snapshot hash
- confirmed approval channel
- operator identity placeholder
- single-use status and expiry

`schwab_transport.place_order()` revalidates the exact order spec hash and readiness snapshot immediately before `client.place_order()`. If quantity, account, symbol, order type, stop price, limit price, or trailing percent changes after approval, submit blocks with `order_spec_hash_changed` and requires a fresh approval.

If evidence is missing, the API must return an internal pre-broker block:

- `mode=blocked`
- `stage=evidence_revalidation`
- `broker_submitted=false`
- `reason=no_evidence_bound_approval`

The UI must say: `Trade AI blocked submit before Schwab: missing evidence-bound approval. No broker order was sent.`

## Schwab Protective Stop Preflight

Before any live STOP / STOP_LIMIT / TRAILING_STOP canary, run:

```bash
python3 scripts/protective_stop_2fa_preflight.py \
  --symbol V \
  --account schwab_rollover_ira \
  --order-kind TRAILING_STOP \
  --trail-pct 8.7 \
  --dry-run
```

The preflight creates a dry-run intent, simulates typed-ticker approval, creates evidence, revalidates the exact order-spec hash, and stops before any Schwab broker write. If PostgreSQL is unavailable, it must fail closed with `missing_field=postgres_connection`.

## Fidelity Activity And Journal

`scripts/snaptrade_activity_ingest.py --apply` is the required path for Fidelity/SnapTrade activity. Position/balance sync alone does not import activity, dividends, or DRIPs.

The ingest maps:

- buys and sells
- dividends
- reinvested dividends / DRIP rows
- interest
- rollover and transfer cash movements
- raw description, account, broker context, symbol, amount, quantity, price, date, and idempotency key

`scripts/journal_ticker_lifecycle.py` aggregates imported activity by ticker:

- total buys and sells
- weighted average cost
- realized P/L and realized P/L %
- dividends received
- entries and exits
- win/loss count
- average hold time
- best/worst trade
- current open shares
- lifetime ticker P/L

The uploaded Fidelity examples produce:

- HPE: two buys totaling `$47,495.98`, sell proceeds `$42,589.12`, realized P/L `-$4,906.86` (`-10.33%`).
- GCTS: buy `$5,970.00`, sell proceeds `$4,599.90`, realized P/L `-$1,370.10` (`-22.95%`).
- SCHD/SCHG/XAR dividends import as income, not trade wins.
- Rollover cash entries are cash movements, not trading P/L.

## Stop-Out Review And Re-Entry Watch

`scripts/stop_out_reentry_watch.py` creates advisory stop-out reviews and re-entry watch rows from realized-loss exits. It does not submit orders.

HPE-like losses are flagged for initial-risk review when the stop was about 10% or more below weighted average cost. GCTS-like stopped-out losses are added to re-entry watch with `WAIT` status until a fresh setup appears.

## OCO Readiness

`scripts/oco_readiness_report.py` is read-only. It reports blockers until all prerequisites are proven:

- DB available
- Schwab write policy validator clean
- execution state allows operator 2FA live path
- basic protective STOP canary passed
- trailing STOP canary passed
- evidence-bound approval clean
- broker read-back verified
- kill switches clear

OCO is not ready until those are clean. This task does not enable an OCO canary.

## Live Stop Readiness Panel & Disabled-Reason UI

A disabled Schwab live-stop button (`STOP` / `STOP_LIMIT` / `TRAILING_STOP`) is **never silent**. The
frontend decision path:

- `apps/command-center-v3/src/lib/stopManagement.ts` — `buildStopLogic()` exposes `disabledReason` /
  `disabledReasonHuman` (the highest-priority blocker). Blocker priority is
  `instrument_not_applicable → source_mismatch → missing_quote → stale_quote → stop_not_protective →
  trail_start_mismatch → floor_mismatch → fractional_qty` (whole-share confirmation last, so a genuine
  data problem is reported before the operator-confirmable one).
- `apps/command-center-v3/src/components/HoldingProtectionActions.tsx` — every disabled button carries the
  reason in its tooltip (`Disabled — …`) and an inline `⛔ Disabled: …` line beside the buttons. The
  whole-share confirmation checkbox is prominent and **immediately above** the action row, labeled
  `"I confirm this Schwab stop will sell N whole shares of <SYM>; residual … remain monitored."` Checking it
  clears the `fractional_qty` blocker and enables the button when all other gates are clean. Genuine backend
  hard-blocks (execution_state blocked / DB-evidence unavailable / OCO on) also disable the button with a
  clear reason; preflight-not-run and active-approval are surfaced as readiness warnings (the per-order 2FA +
  backend evidence revalidation enforce them at submit).

**Read-only readiness endpoint:** `GET /api/v2/holdings/stop-readiness?symbol=&account=`
(`api_v2._stop_live_readiness`). No broker calls, no evidence writes, no order placement
(`broker_request_sent=false`). Returns the gate snapshot — build marker, execution state, db/evidence
availability, schwab validator (cached 5 min), active approval lock, OCO off, preflight status — plus
`canary_state` (`READY_FOR_OPERATOR` when the **backend** gates pass; the panel flips to ✅ only after the
operator also checks whole-share confirmation and the quote is fresh). The "LIVE STOP READINESS" card renders
these with ✅ ready / ⚠️ needs action / ⛔ blocked icons.

`READY_FOR_OPERATOR` never means "submit": the operator must manually click and complete per-order 2FA, the
backend revalidates evidence, and the UI shows `LIVE BROKER STOP` only after broker read-back confirms.

For the **V** Schwab rollover IRA canary the only blocker was `fractional_qty` (201.4412 sh, residual 0.4412,
whole-share unchecked). With confirmation checked and all gates clean, V is `READY_FOR_OPERATOR`.

## Validation Snapshot

Last validation after deploying PR #33 into the runtime checkout:

- `npm run build` in `apps/command-center-v3`: passed with existing Vite bundle-size/script warnings.
- Requested pytest group after the V trailing-stop incident fix: `66 passed`.
- Earlier full integration pytest group: `73 passed`.
- Focused evidence/manual-ticket/activity tests: `37 passed`.
- Runtime checkout before deployment: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`, branch `fix/db-hang-prevention`, commit `32c58202d6dac5f6047ad7b7fe0bc671ffdd4bdd`, serving stale `/v3/assets/index-DDl-G8gk.js`.
- Runtime checkout after deployment: branch `runtime/pr33-stop-evidence-deploy`, commit `494674104dafbd0ff59f23795944e022270bfcb6`.
- New served UI bundle: `/v3/assets/index-CDfEtgRO.js`.
- Served UI bundle includes build marker `cc-v3 stop-evidence PR33 2026-06-30`.
- Served UI bundle no longer contains `placeholder:"000000"` or `approved, but Schwab rejected`.
- Served UI bundle contains `Trade AI blocked submit before Schwab`, `Request Schwab stop via 2FA`, and `Create Fidelity manual ticket`.
- Runtime server restarted through `bash linux_launchers/restart_server.sh`; backend health returned `{"ok": true, "version": "2.0", "port": 7777, "holdings_exists": true}`.
- PostgreSQL was reachable with the runtime `.env`; DB role timeouts verified as `lock_timeout=3s`, `idle_in_transaction_session_timeout=2min`, and `statement_timeout=3min`.
- `pg_stat_activity` showed no blocked queries; stale idle sessions were not terminated because `pg_blocking_pids` returned no blockers.
- `python3 scripts/validate_schwab_write_policy.py`: `27/27 guards green`.
- `python3 scripts/execution_state.py --json`: `operator_live_via_2fa_allowed=true`, `operator_approved_live_submit_possible=true`, `autonomous_live_submit_allowed=false`, and no current blockers.
- `python3 scripts/validate_release_readiness.py --json --skip-build`: `ok=true`, `status=WARN` only because of pre-existing non-live-adjacent dirty `config/strategies/*.yaml` files in the runtime checkout; `live_adjacent=[]`.
- V trailing-stop dry-run preflight passed with `whole_qty=201`, `residual_qty=0.4412`, matching approved/submit order-spec hashes, evidence revalidation `ok=true`, and `broker_submitted=false`.
- The dry-run preflight now **supersedes its own** simulated `evidence_bound_approvals` row at the end of the run (`evidence_approval.supersede_approval(intent_id)` → `status='superseded'`), so repeated dry-runs never leave a false "active approval lock". The result carries `dry_run_evidence_superseded` + `active_approval_lock=false`. (Previously the cleanup called `approval_service.reject()`, which only resets `trade_approvals` 2FA-channel rows — not the `evidence_bound_approvals` lock — so those locks accumulated and showed as a false active approval in the readiness panel.) Verified: two consecutive V dry-runs leave zero active locks.
- `python3 scripts/oco_readiness_report.py`: `ready_for_oco_one_share_canary=false`.

## Remaining Blockers Before Any OCO Canary

- PostgreSQL available and DB role defaults verified:
  - `lock_timeout=3s`
  - `idle_in_transaction_session_timeout=120s`
  - `statement_timeout=180s`
- `validate_schwab_write_policy.py` passes cleanly with DB available.
- Execution state shows operator-approved 2FA live path clean and kill switches clear.
- A basic Schwab protective STOP canary passes with evidence-bound approval and broker read-back.
- A Schwab trailing STOP canary passes with evidence-bound approval and broker read-back.
- OCO readiness report has no blockers.
