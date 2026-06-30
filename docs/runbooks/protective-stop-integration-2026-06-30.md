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

## Validation Snapshot

Last local validation on the integration branch:

- `npm run build` in `apps/command-center-v3`: passed with existing Vite bundle-size/script warnings.
- Requested pytest group after the V trailing-stop incident fix: `66 passed`.
- Earlier full integration pytest group: `73 passed`.
- Focused evidence/manual-ticket/activity tests: `37 passed`.
- Built UI bundle includes build marker `cc-v3 stop-evidence PR33 2026-06-30`.
- V trailing-stop dry-run preflight resolves the local holdings snapshot, then fails closed at `missing_field=postgres_connection` while PostgreSQL is unavailable; no Schwab request is sent.
- `python3 scripts/validate_schwab_write_policy.py`: `24/26`, fail-closed because PostgreSQL was unavailable in the session.
- DB role timeout verification could not run because PostgreSQL was unavailable.
- `python3 scripts/execution_state.py --json`: command ran, but reported `operator_live_via_2fa_allowed=false` and `kill_switch_db_unavailable`.
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
