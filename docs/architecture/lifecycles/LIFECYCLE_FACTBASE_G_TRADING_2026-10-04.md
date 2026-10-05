# Lifecycle Factbase — Family G: Trading Desks & Active Trader

Status: ACTIVE
as_of: 2026-10-04T21:05:00-04:00
Measured at: 4f932b88a

Live CURRENT = `4f932b88a-main-exact-phase2-20261004-202102` (`readlink -f .../portfolio-server/CURRENT`); dev tree HEAD = 4f932b88a.
Measurement was read-only: SELECT under `SET TRANSACTION READ ONLY`, GET on :7777, file and log reads. No broker, OpenD trade, 2FA or Telegram call was made.

Tags: **[M]** = measured (the command or file:line is given). **[D]** = documented (the doc or memory file is named). **[I]** = inferred from [M]/[D] facts; the reasoning is stated.

Today is Sunday. The last trading session measured is Fri 2026-10-02. Everything shipped 10-03..10-04 (#1416, #1424, #1431, #1432) **has not yet run on a market day**.

---

## G1 — Momentum-scalp discovery → ignition engine

**(a) Purpose, actors and stores**
- Purpose: find low-float momentum names, then score them each minute (IGN score, lanes, trigger state machine).
- Discovery actors:
  - `run_finviz_momentum_scalp_scan.py` (CUR, `*/5 6-11 * * 1-5`, `--apply --sync-signals --generate-proposals`);
  - `momentum_scalp_validation_fast_path.py --dry-run` (`*/2 6-11`).
  - [M] crontab lines 76-77 of the non-comment listing.
- Ignition actor: `run_scalp_shadow_logger.sh`. It is installed with `$PROJ`=CURRENT, but the wrapper `cd`s to the **dev tree** and runs `scalp_shadow_logger.py --live --apply --top 0` [M] `scripts/run_scalp_shadow_logger.sh:9-20`.
- Stores: `scalp_scan_results`, `scalp_ignition_events`, `scalp_t2_shadow`, `scalp_decision_outcomes`.

**(b) State machine**
- Scan decision: GO / WAIT / AVOID.
- Engine lane: BELOW / IGN_45 / IGN_75 / IGN_ACCEL / TRIGGER.
- Setup state: ARMED / FIRED / DATA_UNAVAILABLE.
- Gate: PASS / VETO.

**(c) Flow**
Finviz scan → `scalp_scan_results` → universe → minute scoring (Alpaca IEX, T0 tier) → `scalp_ignition_events` → trigger engine → (since #1431) the alert pass (G2).

**(d) Iterations**
- 09-17: the startup DDL began hitting the lock timeout.
- `af535e130` (#1424, merged 2026-10-04 06:49): the logger skips the DDL when `registry_hash` exists [M] `scalp_shadow_logger.py:284-300`.
- `b11fd0a69`: scalps became advisory, the window became 06:00–12:00 ET, and one 8% spread limit applies.

**(e) Open questions**
- Will the first post-fix run on Mon 10-05 write rows?
- Should T2 be promoted? Still an open operator decision [D] `MOOMOO_T2_SHADOW.md` "P4 NOT done".

**(f) Measurements [M]**
- `scalp_ignition_events`: 30,197 rows, 2026-07-13..**2026-09-17**. The last row is 09-17 11:55 ET. **Nothing has been written for 11 trading days** (09-18..10-02).
- `scalp_shadow_logger.log` (persistent-state/logs, which starts 09-28): 150 runs (30/day × 5 days, 09-28..10-02). There are 150 `psycopg2.errors.LockNotAvailable` tracebacks in `ensure_schema` (`scalp_shadow_logger.py:290`), so **every run crashed**. The last write was 10-02 11:55.
- 09-04..09-17 lanes: BELOW 10,882 · TRIGGER 30 · IGN_45 1. **IGN_75 and IGN_ACCEL: 0.** Gates: VETO 10,746 / PASS 167. Setup state: ARMED 7,198 / DATA_UNAVAILABLE 3,663 / FIRED 52.
- Tier: 14,389 of 14,389 rows since 09-01 are T0 with dcf 0.40. `data_tiers.active_tier: T0` [M] `config/scalp_signal_engine.yaml:143`.
- `scalp_t2_shadow`: last row 09-17. It was available only 09-14..09-17 (263 rows total per the doc).
- `scalp_decision_outcomes`: **0 rows**.
- `scalp_scan_results` 09-23..10-02: 361 rows, WAIT 275 / AVOID 86, **GO 0**, alerted 45.
- `paper_trade_proposals` for momentum_scalp in the last 45 days: 2 (1 REJECTED 09-15, 1 EXPIRED 09-24).

**(g) Failure paths**
- Lock timeout on the DDL. This was a silent 16-day outage, and no health alarm fired [I]: the only evidence is in the log.
- If the IRON RULE check reads holdings total ≤ 0, the wrapper aborts (`run_scalp_shadow_logger.sh:11-14`). The current value is >0 [M].
- The kill file `~/.tradeai/SCALP_ENGINE_DISABLED` is absent [M].

**(h) Maturity by stage**

| Stage | Score |
|---|---|
| Scan | 3 |
| Ignition scoring | 1 (fix shipped, unproven) |
| Outcomes | 0 |
| T2 | 1 (shadow, stale) |

**(i) Target and exit**
- Rows in `scalp_ignition_events` for 10-05 (≥25 passes, 0 tracebacks).
- `scalp_decision_outcomes` populating.
- A stale-writer alarm on `max(created_at)`.

---

## G2 — Active Trader Phase 1 alerts (ARMED / TRIGGERED)

**(a) Purpose, actors and stores**
- Purpose: deterministic, advisory "time to buy?" alerts confirmed by moomoo Level 2 and tape. There is no order path [D] `ACTIVE_TRADER_PHASE1_ALERTS.md`.
- Actor: `scalp_shadow_logger.py:630-636` calls `momentum_alert_pass.run_from_logger` [M].
- Store: persistent-state `data/active_trader/momentum_alerts{,_scored}.jsonl`, `_throttle.json`, `_heartbeat.json`.
- Reader: `momentum_alerts_api.py:306-322` [M].

**(b) State machine**
- Candidate → ARMED (trigger ARMED or IGN_75/ACCEL, plus book bid/ask ≥1.0×, spread ≤80 bps), or
- Candidate → TRIGGERED (fire ≤6 min old, bid/ask ≥1.2×, ≥15 prints, buys ≥55% of the last 50, stop set), or
- Candidate → VETO (any input stale or missing).
- Then a throttle applies: 15 min per symbol and kind, 12 per hour, 8 candidates per pass [M] `momentum_alerts.py:56-62,219-220`.

**(c) Flow**
Logger pass → candidates → moomoo quote-context reads (book / ticker / snapshot) → decide → journal → `telegram_alert.send_telegram(bypass_router=True, message_class=active_trader_scalp_alert)` → comms editor exemption (`scripts/lib/comms_editor.py`), which applies only to the missing-CIO-decision hold.

**(d) Iterations**
- d7521b17d / #1431: Phase 1 in shadow.
- 89a508083 / #1432 (10-04): send mode plus the Alerts tab.

**(e) Open questions**
- The API reports `engine.window_et` as hard-coded `("09:30","11:55")` [M] `momentum_alerts_api.py:28`. The engine config says 06:00 start, no new fire after 12:00 [M] `scalp_signal_engine.yaml:30-33`. The logger runs the `regular` session, so these agree in practice, but the label is a constant.
- Weekend book timestamps fall back to `ts_source: fetch` [D].

**(f) Measurements [M]**
- Mode is **send**: `config/scalp_signal_engine.yaml:211-212`, and `GET /api/v3/active-trader/alerts` returns `"mode":"send","delivery":"telegram"`.
- The persistent-state directory `data/active_trader/` **does not exist** (`ls` → no such file). There is no journal, heartbeat or throttle yet. The API shows `last_pass_at: null`, `decisions: 0`, `scored_total: 0`.
- The upstream logger has written 0 rows since 09-17 (G1). **The alert path has never executed on a live session.**
- OpenD health is 720 of 720 OK over 09-28..10-02 (144/day), and `trade-ai-lab-moomoo-opend.service` is active.
- L2 was proven at 60 levels on 2026-10-04 [D] `MOOMOO_STAGE0_FOUNDATION_v1.md` §"Level 2 entitlement".
- The tests named in the doc exist [M].

**(g) Failure paths**
- If the logger crashes (G1), there are no alerts and no heartbeat. The UI then shows null and no error.
- If OpenD is down, every candidate is a VETO (fail-closed).
- If Telegram fails or the comms editor holds the alert, the operator sees nothing. Delivery confirmation for this class is unmeasured.
- A CIO disagreement still holds the alert [D].

**(h) Maturity by stage**

| Stage | Score |
|---|---|
| Decision logic | 3 (tested, replay of 30 fires) |
| Live data | 3 |
| Journal | 1 (never written) |
| Delivery | 1 (config only) |
| Scoring / precision | 0 |

**(i) Target and exit**
- On Mon 10-05: a heartbeat every pass, ≥1 decision row, and the Telegram send outcome journaled.
- After 2 weeks: precision at 1/5/15 min for alerts vs vetoes.

---

## G3 — Motion runtime, T2 leases and momentum exit policy (shadow)

**(a) Purpose, actors and stores**
- Purpose: a 30-second motion snapshot, JIT leases for T2 (L2) subscriptions, and exit-hysteresis evidence.
- Actor: `tradeai-active-trader-motion.service`. It has been active since 2026-09-18 03:46, with **NRestarts=355**.
- It runs from the pinned deployment `~/trade-ai-deployments/active-trader/306f81799…` (commit 2026-07-29, #252), with the dev-tree venv [M] (`systemctl --user show`, drop-in).
- Stores (dev tree): `data/active_trader/motion_journal.jsonl` (a 5,000-line ring), `motion_runtime_state.json` and `motion_runtime_heartbeat.json`.
- The API reads them through the drop-in `35-active-trader-motion-journal.conf` [M].

**(b) State machines**
- T2 JIT: admitted / continued / denied with `session_not_active`, `motion_not_authorized`, `gate_not_pass`, `t2_capacity_full`, … [M] `t2_jit_policy.py:29-48`.
- Exit policy: HOLD → WATCH → EXIT_ARMED → EXIT_SIGNAL, plus PROTECT_ONLY [M] `momentum_exit_policy.py`.
- Neither has an account, broker or order action (module docstring).

**(c) Flow**
momentum_loader → positions → JIT policy (requires an ACTIVE Active Trader session) → lease → exit policy → journal → `GET /api/v3/active-trader/motion`.

**(d) Iterations**
- 10-04: the journal-path split was fixed (the API had been reading an empty release-local directory).

**(f) Measurements [M]**
- Ring 2026-10-03 03:13 → 10-04 20:53 (5,000 snapshots): **leases 0, T2 decisions 0, exit signals 0, positions 0.**
- Runtime state: `cycle_count 191,882`, `t2.leases []`, `exit_policies {}`. Heartbeat: `restored_t2_lease_count 0`, `status healthy`. API: `data_state LIVE_DATA`, `operating_cap 2`, `provider_hard_cap 8`.

**(g) Failure paths**
- The service code is pinned to a 2-month-old deployment, so dev-tree fixes don't reach it [I].
- 355 restarts are unexplained.
- [I] No lease can ever be admitted: admission requires `session_state=ACTIVE`, and `LIVE_ACTIVATION_ENABLED=False` (`session_control.py:36`) means sessions are simulation-only. `GET .../sessions` → `live_session_enabled:false`.

**(h) Maturity by stage**

| Stage | Score |
|---|---|
| Runtime / snapshot | 3 |
| Leases | 1 (code only) |
| Exit policy | 1 (shadow, never fed a position) |

**(i) Exit criteria**
- Redeploy from the current SHA.
- Explain the restarts.
- One simulated session that admits a lease end-to-end.

---

## G4 — Strategy review gate (momentum_scalp)

**(a) Actors and stores**
- `config/strategies/momentum_scalp.yaml` `validation_gate` / `performance_context`.
- `strategy_registry`, `paper_strategy_scorecards`.
- `active_trader/config_read.py:262-345` (review-gate panel, `_gate_met`).

**(b) State machine**
UNVALIDATED → TESTING → (human promotion review) → LIVE. `strategy_registry.momentum_scalp` = **TESTING, active** [M].

**(f) Measurements [M]**
- Gate: ≥30 closed validation trades, WR ≥0.5, PF ≥1.3, ≥6 months, human promotion review (`momentum_scalp.yaml:286-298`).
- Progress: `performance_context.closed_paper_trades: 3`, WR 0.3333, PF 1.2858, `ready_for_review: false`, **`last_updated: 2026-06-28`** (98 days stale, although the comment says "populated nightly") (`:350-366`).
- The DB agrees: `paper_trades` momentum_scalp has 3 closed (05-12..06-01), 18 cancelled, 1 dedup. The latest scorecard is **2026-05-16** (3 closed, 'insufficient').
- Family scalp, real money: `trade_closed.strategy_id='scalp'` = **83 trades**, 43 W / 40 L, net +$1,677.12, 2025-09-10..2026-09-25. These do not count toward the momentum_scalp gate.
- The review thresholds inside `performance_context` say PF ≥1.25, while `validation_gate` says PF ≥1.3. These are two thresholds for the same gate.

**(g) Failure paths**
- No new momentum_scalp paper trades since 06-01. With 2 proposals in 45 days, the gate cannot progress [I].
- Stale YAML progress feeds LLM prompts (note at `:366`).

**(h) Maturity:** gate definition 3, progress tracking 1, sample accrual 0.

**(i) Target**
- Decide whether the 83 family-scalp real trades count as evidence.
- Restart the nightly `performance_context` writer.
- Make the PF threshold a single value.

---

## G5 — Options desk (fill truth, order authorization)

**(a) Actors**
- Crons: `options_lifecycle_run`, `options_thesis_lifecycle` (:07/:22/:37/:52), `options_monitor`, `options_chain_snapshot`, `options_iv_snapshot`, `options_memory_projector`, `options_runtime_snapshot` [M].
- Order route: `/api/v2/options/{validate,preflight,confirm}` → `options_order_pilot.confirm_authorization` → `schwab_transport.place_order` [D] `reference_options_contract_test_runbook.md`, `OPTIONS_ORDER_GATE_PROOF_2026-09-27.md`.

**(b) State machine**
Proposal → validate → queue approve (pin, TTL 240 min) → preflight (desk gate + buying power) → 2FA confirm → evidence-bound authorization (`order_spec_hash`) → submit → readiness and revalidation → Schwab.

**(d) Iterations**
- #1300–#1316 went live 09-27 (CURRENT 0be1da1c8 / 4aec538e3). They included the order-authorization contract, and contract proofs passed 65/65 [D] memory `project_options_fill_truth_20260927.md`.
- In the commit log since 09-14, 89 non-merge subjects mention options [M].

**(f) Measurements [M]**
- `options_approval_queue`: blocked 2,808 (latest 10-04 05:28), rejected 63, approved 1 (07-20).
- `options_fill_evidence` **0 rows**, `options_journal_events` **0**, `options_lifecycle_tickets` **0**.
- `broker_order_intents` with options in the JSON since 09-14: 2 (both PREFLIGHTED).
- Arming: `system_controls.options_execution_enabled=true` (since 06-22), the note says "INTENTIONALLY ARMED … per-order 2FA"; `options_execution_policy.py:11-12` has `ENABLED=True`, `GATES_REMOVED=False`, allowlist of 3 Schwab accounts, max 5 contracts and $25k.
- **Live options trading is NOT authorized.** The first real submit must be a supervised 1-lot [D] memory runbook and fill-truth line 56.

**(g) Failure paths**
- A weekend or closed-market chain produces `awaiting live quotes` for everything.
- `place_order` reuses the buying-power read from confirm.
- The desk bot is not restarted on promote [D].

**(h) Maturity by stage**

| Stage | Score |
|---|---|
| Proposal / research | 3 |
| Gates and authorization | 3 (tested, never end-to-end) |
| Fill truth | 0 (no fills) |
| Lifecycle tickets | 0 |

**(i) Exit criteria**
- One operator-supervised 1-lot that writes `options_fill_evidence` and journal rows.

---

## G6 — Live execution gates

**(a) Actors**
- `live_trading_gate.py` (paper-only enforcement): `ALPACA_MODE`, `LIVE_TRADING_ENABLED`, the DB policy, and governance.
- `live_trading_interlock.py` (`gate_status`, `assert_writable`). It is called by api_v2 only when enabling `api_write` or AUTO_LIVE (`api_v2.py:52388-52539`).
- `execution_guard` / `execution_readiness` / 2FA on `schwab_transport.place_order` (`:102-129`).
- Alpaca live raises `NotImplementedError` (`brokers/alpaca_factory.py:75-80`).
- moomoo `place_order`/`unlock_trade` raise `MoomooAuthorityError` (`moomoo/client.py:380-466`).
- AT sessions: `LIVE_ACTIVATION_ENABLED=False` (`session_control.py:36`).
- `MBI_BEHAVIOR = 0` is a READ_ONLY_ADVISORY docstring marker on advisory modules (e.g. `maria_outbound_gate.py:18`). It is not a runtime switch [M].

**(f) Measurements [M]**
- `GET /api/v2/live-trading-gate` → `PAPER_ONLY`, `autonomous_live_trading_allowed:false`, `operator_live_via_2fa_allowed:true` ("ENABLED via standing_db_unlock — per-order 2FA required").
- The four gates:

| Gate | Required | Current | Result |
|---|---|---|---|
| Win rate | ≥0.55 | 0.514 | FAIL |
| Profit factor | ≥1.3 | 1.35 | pass |
| Closed trades | ≥30 | 142 | pass |
| Time in paper | ≥6 months | 5.0 | FAIL |

- `paper_validation_policy` id 1: start 2026-05-08, 183 days, **100** trades, WR 0.55, PF 1.30, governance required, `live_trading_allowed=false`. `governance_approvals` has no live row.
- Inconsistency: the API says 30 trades are required, while the policy row says 100.
- `system_controls`:
  - `broker_live_enabled=true` (06-22);
  - **`pilot_armed_until=2099-12-31`**;
  - `schwab_pilot_standing_unlock=true`;
  - `protective_stops_enabled=true`;
  - `halt_live_only=false`.
- CURRENT `.env`: `ALPACA_MODE=paper`, `BROKER_LIVE_ENABLED=true`, `LIVE_TRADING_ENABLED` unset.
- `canary_gate.GATES_REMOVED=True` (`brokers/canary_gate.py:41`) and `protective_stop_policy.GATES_REMOVED=True` (`:30`).
- `broker_accounts`:
  - schwab live: 3, `api_write` on;
  - moomoo live: 2, off;
  - alpaca live: 2, off;
  - alpaca paper: 1, on.
- `broker_order_intents`: SUBMITTED 3 (last 2026-06-15), PREFLIGHTED 141 (last 09-23).
- Schwab token: healthy, live probe OK, **`true_expiry 2026-10-05 12:06 ET`, `due_now: true`**. Manual re-auth is needed before Monday midday.

**(g) Failure paths**
- The only per-order gate on Schwab is 2FA. The pilot is standing-armed to 2099, and canary limits are removed [D] memory `project_live_execution_gates.md`.
- If the token expires, stop and order submits fail with `invalid_grant`.

**(h) Maturity:** refusal gates (Alpaca, moomoo, AT) 4; Schwab operator 2FA path 3; autonomous gate 3 (fail-closed and measured).

**(i) Target**
- Reconcile 30 vs 100.
- Decide whether the standing arm to 2099 remains intended.

---

## G7 — Stops and protection

**(a) Actors**
- `unified_stop_supervisor.py --apply` (`*/3 9-16` 1-5, via `market_day_gate`).
- `broker_stop_reconcile.py --apply` (06:12).
- `fidelity_stop_sync.py --apply` (10:05; the registry note also says 16:05).
- `stop_reconcile`, `stoplights`, `stop_policy_migration_report`.
- Stores: `stops.json`, `manual_broker_stops`, `fidelity_monitored_stops`, `system_controls.fidelity_stops_*`.

**(d) Iterations**
- 2d9253532 / #1416 (10-03): removed 7 closed Fidelity positions (ARKX DXCM SCHG CSCO DIVI QCOM ANET). An empty registry is now authoritative and retires the account's active manual stops, with no baked-in fallback.
- The `market_day_gate.sh` fix: release directories have no `.venv`, so the gate had "failed open" on every run (`market_day_gate.sh:13-20`).

**(f) Measurements [M]**
- `config/fidelity_rollover_stops.json`: `stops: 0`, `_fidelity_as_of 2026-07-13`.
- **`manual_broker_stops` still has 7 active Fidelity rows** (updated 10-02 10:05), because no sync has run since the change. `system_controls.fidelity_stops_last_sync` shows 10-02 with 7 upserted and 0 retired. Retirement is expected Mon 10-05 10:05 [I].
- `fidelity_monitored_stops`: 4 rows, all canceled (07-16).
- Broker reconcile (10-02): 5 live broker stop orders (AXTI, BAH, NFLX, PFLT, V).
- Supervisor log:
  - "Protected: NO" on 397 lines, the last on 10-02 16:30. By day: 09-29 243, 10-01 18, 10-02 136. Latest result: 2/2 "Protected: YES".
  - 799 "failing open" gate lines (about 160/day, 09-28..10-02).
  - The log also shows supervisor runs every ~5 min on Sat/Sun (10-03 00:02 … 10-04 10:40). The crontab (`*/3 9-16 * * 1-5`) does not explain them, and the source was **not identified**.
  - `send_enabled: false` in the defect reports, so defects do not page.

**(g) Failure paths**
- The operator cancels a GTC at Fidelity, but SnapTrade does not sync stops, so the registry is manual [D] registry `_comment`.
- "Protected: NO" episodes produce no Telegram.
- The schedule source is ambiguous.

**(h) Maturity:** Schwab protective stops 3; Fidelity registry 2 (manual, change unapplied); alerting on unprotected 1.

**(i) Target**
- Confirm the 7 rows retire on 10-05.
- Page on "Protected: NO" for more than N minutes.
- Identify the weekend writer.

---

## Family maturity: **1.9 / 5**

Gates and refusals are strong (4). The scoring, alert and motion data plane has never run end-to-end in production since 09-17. There are no outcomes (0 rows), no fills (0 rows), and no leases (0).

## Top 5 risks

1. **The ignition engine has been dark since 09-17**, a 16-day silent outage (G1). The Phase 1 alerts in `send` mode depend on it, and neither has a live run (G2).
2. **Standing live arm:** `pilot_armed_until=2099-12-31`, `BROKER_LIVE_ENABLED=true`, and canary and protective gates removed. Per-order 2FA is the single control on Schwab (G6).
3. **Schwab token true expiry is 2026-10-05 12:06 ET.** If it is not re-authed, protective-stop and order paths fail (G6/G7).
4. **Protection alarms are muted:** "Protected: NO" appeared 397 times with `send_enabled:false`. The weekend supervisor runs have an unknown source (G7).
5. **The motion service runs a pinned July deployment** with 355 restarts. A lease cannot be admitted by design, so the T2 / exit stack is untested on real flow (G3).

## Top 5 recommendations

1. Mon 10-05 09:35 ET: verify `scalp_ignition_events` rows for 10-05, that `persistent-state/data/active_trader/momentum_alerts_heartbeat.json` exists, and that the scalp log has 0 tracebacks. Add a stale-writer alarm on `max(created_at)`.
2. Re-auth Schwab before 12:06 ET on 10-05. Decide whether `pilot_armed_until=2099` stays.
3. Turn on `send_enabled` (or an operator page) for sustained "Protected: NO", and identify the weekend supervisor caller.
4. Redeploy the motion service from CURRENT and explain NRestarts=355. Run one simulated AT session that admits a lease.
5. Restart the momentum_scalp `performance_context` writer (stale since 06-28). Reconcile the review thresholds: PF 1.25 vs 1.3, and live-gate trades 30 (API) vs 100 (DB).

## Phase 2 / 3 gating facts (must be true before automated entry or Schwab)

- **Phase 2 (automated entry/exit) is a proposal, not a build** [D] `ACTIVE_TRADER_PHASE1_ALERTS.md`. These Stage 0 denials remain binding [D] `ACTIVE_TRADER_CURRENT_GUARDRAILS.md`:
  - live place/modify/cancel on any venue;
  - session authorize / 2FA ceremony;
  - `live_canary`;
  - unattended discover-and-fire;
  - the moomoo order path / OpenD unlock.
- Required before Phase 2:
  - a signed session authorization envelope (not built);
  - `LIVE_ACTIVATION_ENABLED` (hard False) [M];
  - all `/status` feature flags false today [M].
- Evidence prerequisites [I] (each currently zero):
  - an ignition engine running daily;
  - a scored alert track record (`momentum_alerts_scored.jsonl`, `scalp_decision_outcomes`);
  - a momentum_scalp validation gate met (30 closed, WR ≥0.5, PF ≥1.3, 6 months, human review). Today: 3 / 30.
- Autonomous live gate: `paper_validation_policy.live_trading_allowed=false`, there is no governance approval, and WR (0.514) and time (5.0 months) are failing [M].
- **Phase 3 (Schwab):**
  - Schwab is documented as primary execution when electronically eligible; moomoo/Alpaca augment it [D] route map.
  - Today, Schwab live writes go only through the operator's per-order 2FA path (`execution_guard` + `execution_readiness` + evidence revalidation).
  - An automated Schwab entry would also need the interlock `assert_writable` on that path, which today applies only to enabling `api_write`/AUTO_LIVE [M] `api_v2.py:52388-52539`.
  - It would also need a durable token, which today has a weekly true expiry [M].
  - Venue eligibility (low-float/call-broker blocks) is documented only [D] `ACTIVE_TRADER_VENUE_ELIGIBILITY_v1.md`.
- Alpaca live: `NotImplementedError`. moomoo orders: `MoomooAuthorityError`. moomoo live accounts have `api_write=false` [M].
