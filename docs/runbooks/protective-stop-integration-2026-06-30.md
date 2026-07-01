# Protective Stop Integration Runbook — 2026-06-30

## Scope

**Deployed branch:** `main` (merged 2026-07-01). Historical integration source: `fix/stop-execution-journal-reentry-integration` (behind `main` — do not merge as-is).

Stacks: DB timeout guard, quote timestamps, session-aware freshness, click-time preflight UX (1A–5A), Stop Management tab, duplicate-stop guard (P1–P3), evidence-hash 2FA fix, family-floor reconciliation, OCO DD hardening, lock-in trailing advisory. Does not enable Schwab OCO brackets.

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

## Live Broker Stops & Last-Reviewed Tooltips

Portfolio and Open Trades must show **current** broker protective-stop state, not a stale advisory overlay.

- **`GET /api/v2/holdings/live-stops`** — read-only Schwab/Alpaca SELL stops (60s cache), keyed
  `SYMBOL:account` (holdings account labels, e.g. `schwab_roth` not `schwab_roth_ira`). Returns `by_key`,
  `fetched_at`, `cache_ttl_sec`. No broker writes.
- **Portfolio** (`PortfolioHub.tsx`): polls `/api/v2/holdings/live-stops` every **60s** and merges into
  `confirmedStop` via `mergeLiveStop()` before `HoldingProtectionActions` renders.
- **Open Trades** (`open_trades_intelligence.py`): each `broker_stop` on a position carries `fetched_at`; summary
  includes `broker_stops_fetched_at`.
- **Trailing live stops**: Schwab trailing orders often have `stop_price=null`. UI treats `trail_offset` +
  `order_type=TRAILING_STOP` as `LIVE BROKER STOP`; estimated floor = `price × (1 − trail%)`.
- **Last-reviewed tooltips** (`stopReviewTooltip.ts`): hover STOP STATUS, 🛡 badge, broker/advisor fields, and
  Open Trades “PROTECTED” banner for:
  - Broker stop last read (Schwab API `fetched_at`)
  - Protection advisory last reviewed (`protection.at` + model)
  - Quote as-of
  - Operator confirmed stop (`confirmed_at`, Fidelity manual)
- Inline label on Portfolio stop panel: `last reviewed {timestamp}` beside STOP STATUS.
- Build marker after live-stops wiring: `cc-v3 live-stops-review-ts 2026-06-30`.

## Click-Time Preflight (Portfolio UX — 1A–5A)

Operator UX choices locked **2026-06-30** on `runtime/pr33-stop-evidence-deploy`:

| Choice | Behavior |
|--------|----------|
| **1A** | Unchanged logic after validation → auto-proceed to 2FA / Fidelity manual ticket |
| **2A** | Changed logic → structured amber diff + **Proceed anyway** / **Cancel** |
| **3A** | Preflight re-fetches `/api/v2/portfolio/llm-coverage` (fresh protection advisory) |
| **4A** | Always full preflight on every click (~1–3s) |
| **5A** | Holding card updates price / market value / timestamps from preflight |

**Trigger:** Schwab `Request … via 2FA` buttons, Fidelity `Create … manual ticket`, and Schwab 2FA `approve` buttons.

**Read-only API chain (no broker writes until 2FA completes):**

1. `POST /api/v2/holdings/protective-stop/refresh-quote`
2. `GET /api/v2/portfolio/llm-coverage` → merge `protection[SYMBOL]`
3. `GET /api/v2/holdings/live-stops`
4. `GET /api/v2/holdings/stop-readiness` (Schwab only)
5. Recalc `buildStopLogic` in `stopManagement.ts`

**2A structured diff** (`data-testid="preflight-diff"`): price, decision, status, advisor stop, broker stop (fixed or trailing), recommendation text, blockers added (+) / removed (−).

**5A holding patch:** `PortfolioHub` `onPreflightUpdate` merges into local state — `current_price`, `source_timestamp`, `price_as_of`, `market_value`, protection chip — so the card above the stop panel reflects the validated quote.

**Build marker:** `cc-v3 stop-audit-sync 2026-07-01` (footer of Command Center v3).

## Quote Timestamp Normalization & After-Hours Policy

The quote feeds emit several timestamp shapes (`...T...-04:00`, `...Z`, `YYYY-MM-DD HH:MM:SS`, and
`YYYY-MM-DD HH:MM:SS ET`). `datetime.fromisoformat()` raised on the ` ET` / space-separated shapes, which
previously surfaced `Quote validation failed: Invalid isoformat string` to the operator.

- **Shared normalizer** `scripts/brokers/quote_time.py`: `parse_quote_ts` returns one tz-aware datetime (or
  `None`), `classify_session` → `regular | pre_market | after_hours | closed | unknown` (America/New_York via
  `zoneinfo`; EDT/EST resolved by date). ` ET`/space-separated → Eastern, never silent UTC. Unparseable →
  `None`, so callers block with a human message — never a raw isoformat error.
- Used by the `api_v2` protective-stop quote gate, the `/api/v2/holdings/stop-readiness` panel, and
  `protective_stop_2fa_preflight` (which now reports `quote_session`, `quote_freshness_class`, and
  `operator_readiness`, and FAILS on an unparseable quote).
- **After-hours policy (24/7 GTC):** a protective stop is submitted **GTC** (`GOOD_TILL_CANCEL`) and rests
  until triggered, so it is valid to place **24/7**. An after-hours / pre-market quote does **not** block the
  canary — it requires the operator **after-hours acknowledgement** (`after_hours_ack`): *"I understand this
  is after-hours; Schwab may accept the GTC order but trigger behavior depends on regular-market conditions."*
  Readiness reports `READY_FOR_OPERATOR_AFTER_HOURS_GTC` + `requires_after_hours_ack` for a fresh after-hours
  quote. An optional kill-switch `SCHWAB_AFTER_HOURS_STOPS_DISABLED=1` forbids after-hours submission entirely
  (default: allowed with ack). The ack relaxes **only** the session gate — fresh+parseable quote,
  evidence-bound approval, whole-share qty, per-order 2FA, and read-back still apply, and broad stops are
  never enabled from an after-hours canary. (Regular session needs no ack.)
- **UI:** the readiness panel shows Quote (parsed/fresh), Session, raw→normalized timestamp, a three-state
  canary badge (`READY_FOR_OPERATOR` / `READY — AFTER-HOURS GTC` / `BLOCKED`), and a human readiness message.
  An after-hours acknowledgement checkbox appears when the quote is after-hours; checking it (plus whole-share
  confirmation) enables the trailing-stop button. The raw `Invalid isoformat string` is never shown.

**Operator instruction:** the V trailing-stop canary can be placed **any time a fresh quote is available
(24/7)**. When the readiness panel shows `Quote: fresh` and the badge is green: (1) check whole-share
confirmation; (2) if `Session` is after-hours/pre-market, also check the after-hours acknowledgement; (3)
click *Request Schwab trailing stop via 2FA* **once** and complete per-order 2FA. The GTC order rests until
triggered. (During the dead overnight window the quote will be stale → `BLOCKED`; wait for a fresh tick.)

## Validation Snapshot

Last validation on `main` (2026-07-01 hygiene pass):

- `tests/test_stop_fixed_trailing_validation.py` + `tests/test_stop_management_decision_logic.py` +
  `tests/test_stop_management_ui_hardening.py` (incl. test_16–18): **40 passed**.
- `npm run build` in `apps/command-center-v3`: passed (tsc + vite).
- Build marker: `cc-v3 stop-audit-sync 2026-07-01` (unified across App, api_v2, tests, docs).
- UI assertions: preflight chain (`refresh-quote` → `llm-coverage` → `live-stops` → `stop-readiness`);
  `preflight-diff` + `onPreflightUpdate`; session-aware quote freshness (15m regular / 60m extended).
- **Not wired (pending approval):** Open Trades preflight; `stop_out_reentry_watch` API/UI.

Prior validation on integration branch `fix/stop-execution-journal-reentry-integration`:

- `tests/test_stop_fixed_trailing_validation.py`: fixed vs trailing math/UI/backend parity (distance %, trail
  alignment 0.35%, floor mismatch, live trailing `stop_price=null`, Schwab order-spec shape).
- `python3 scripts/verify_protective_stop_submit_flow.py --json`: PASS (`no_submit_performed=true`).
- Build marker (live-stops wiring): `cc-v3 live-stops-review-ts 2026-06-30`.

Prior validation after deploying PR #33 into the runtime checkout:

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
