# Editable ATM + Proposal Controls — PAPER-ONLY, GATE-INTERLOCKED (2026-06-04)

Status:      HISTORICAL
as_of:       2026-06-04T21:38:20-04:00
Measured at: efcc51365 / not measured

The #2 "arm-execution" work, scoped safely. Every control operates on paper and is **physically
blocked from arming any LIVE account until the live-trading gate passes**. No live-money switch was
built; the live Schwab arm stays a deliberate, out-of-band, later step (after gate + Schwab adapter +
broker-confirmation). All writes route through the proven `admin_write` guard (access → two-step
confirm → append-only `admin_audit_log`).

## The hard interlock (built + proven FIRST)
`scripts/live_trading_interlock.py` — fail-closed:
- `assert_writable(conn, account, action)` — raises `InterlockRefused` if the account's
  `accounts.mode = 'live'` AND `paper_validation_policy.live_trading_allowed` is not TRUE. Paper
  accounts always pass; **unknown accounts are refused (fail-closed)**.
- `gate_status(conn)` — `passed` (governed by the master flag) + progress (days / closed_trades /
  win_rate / profit_factor vs minimums).

**Proof (module + API):**
- Module: schwab_taxable / schwab_roth_ira / schwab_rollover_ira / fidelity_401k → REFUSE;
  alpaca_paper → ALLOW; bogus → REFUSE (fail-closed).
- API (`POST /api/v2/admin/atm/set-state`): arm schwab live + valid token → **403**; arm live with
  no token → **403** (interlock fires before the token check); unknown account → **403**; paper +
  token → passes interlock → guard asks two-step confirm (no apply); paper + no token → 403 (token
  still required). All verified; no state changed.

## Endpoints (all guarded; live targets 403 via interlock)
| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/atm/gate-status` | gate state + progress + per-account interlock status + current ATM mode + risk config |
| `GET /api/v2/atm/schwab-readiness` | unchecked prerequisites before Schwab live could arm (visibility only) |
| `GET /api/v2/atm/actionable-proposals` | proposals the operator can act on |
| `POST /api/v2/admin/atm/set-state` | set ATM DISABLED/DRY_RUN/ACTIVE/PAUSED (paper) — interlock + guard |
| `POST /api/v2/admin/risk-config` | edit the 6 risk limits in atm_config.yaml — guard + **IRON-RULE backup before write** |
| `POST /api/v2/admin/proposal/approve` | approve (paper) — interlock on proposal account + guard |
| `POST /api/v2/admin/proposal/adjust-approve` | edit entry/stop/target/shares THEN approve — guard, old→new diff |
| `POST /api/v2/admin/proposal/edit-criteria` | edit params, no approve — guard |

## Frontend — TradingHub → "ATM Controls" tab (`ATMControlPanel.tsx`)
Gate banner (BLOCKED + real progress) · ATM state buttons (paper, current shown) · risk-limit editor
(current values + per-field Set) · account cards (4 live accounts render **🔒 requires live-trading
gate pass**, alpaca_paper **writable**) · proposal Approve / Adjust-&-Approve / Edit-Criteria ·
Schwab readiness checklist. All writes go through `AdminConfirmModal` (preview old→new → confirm).
Verified by screenshot + API.

## Schwab readiness (design/stub — wires NOTHING live)
Checklist, all unchecked except adapter-code-present: **gate not passed**, `broker_confirm_schwab.py`
**missing** (Schwab fills cannot be confirmed), broker-confirmation **not proven on Schwab**, operator
out-of-band confirmation pending. So "what's left before Schwab live" is visible; nothing live exists
(even Alpaca `submit_order` is `NotImplementedError`/test-and-design).

## Safety posture (unchanged stance)
- Live arming is **not** a web toggle. It is gated server-side (interlock) AND will be a deliberate,
  out-of-band step taken only after: gate passes, Schwab adapter + broker-confirmation work and are
  proven on Schwab. The controls being ready-and-tested ≠ the live path being open.
- No mutations were made building/verifying this (preview / no-token / interlock-refused only); ATM
  state remains `active` (paper) as before.

## Operational note
The API server hot-reload stalled once during rapid successive edits (single-threaded server) and was
restarted (kill → systemd `Restart=always` respawn, MainPID 2045519); all endpoints then verified
<100 ms. If editing api_v2 heavily, expect a possible reload stall — a restart clears it.

---
*Built 2026-06-04. Interlock proven before controls; controls paper-only + live-disabled in UI and
server-side; no live-money path wired.*
