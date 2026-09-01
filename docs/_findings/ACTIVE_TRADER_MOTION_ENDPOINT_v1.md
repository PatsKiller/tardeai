# Active Trader Live Motion Endpoint — v1

Status:      HISTORICAL
as_of:       2026-07-29T09:06:18-04:00
Measured at: efcc51365 / not measured

**Endpoint:** `GET /api/v3/active-trader/motion`
**Contract emitted:** `active-trader-motion-snapshot-v1`
**Stacked on:** PR #250 (`agent/active-trader-t2-jit-policy-v1`) — merges AFTER #250.
**Lights up:** PR #252 UI (`agent/active-trader-live-motion-ui-v1`).
**Order authority:** none. **Write:** false. **Read-only:** yes.

## 1. What this is

One aggregate, read-only motion snapshot for the Active Trader desk, shaped from the
two deterministic policy modules that land in #250:

* `t2_jit_policy` (`T2LeaseManager`) — scarce T2 motion-resource leasing.
* `momentum_exit_policy` (`MomentumExitPolicy`) — momentum-exit hysteresis
  (HOLD / WATCH / EXIT_ARMED / EXIT_SIGNAL / PROTECT_ONLY).

The UI polls ONE endpoint (not one request per ticker) and updates rows in place.
`EXIT_SIGNAL` in the payload is **evidence only** — the endpoint exposes it and never
acts on it. No broker / session / 2FA / credential / order / LLM is touched on the GET
path.

## 2. Journal-backed architecture (keeps the GET pure)

```
motion_shadow.py  (producer, invoked separately — NO cron wired here)
   gather near-fire candidates (arming ladder) + open-position evidence
   -> T2LeaseManager.reconcile + MomentumExitPolicy.evaluate
   -> assemble_motion_snapshot()  -> active-trader-motion-snapshot-v1 dict
   -> motion_journal.append_snapshot()           [the ONLY writer]

data/active_trader/motion_journal.jsonl   (append-only JSONL, file-based, git-ignored)

motion_api.motion_snapshot()  (PURE READ — the GET handler)
   -> motion_journal.latest_snapshot()  (reads last line only; never writes)
   -> freshness-gate -> contract envelope

read_http.dispatch()  GET /api/v3/active-trader/motion
   -> 200 motion_snapshot()  |  405 on non-GET  |  503 fail-closed on exception
```

The read handler NEVER writes the journal. Proven by
`test_get_path_performs_no_write` (journal bytes unchanged after repeated reads).

### Files
| File | Role |
| --- | --- |
| `scripts/active_trader/motion_journal.py` | append-only persistent shadow journal (JSONL); `append_snapshot` / `latest_snapshot` / `snapshot_age_seconds` / `prune_journal`. No DB. |
| `scripts/active_trader/motion_shadow.py` | shadow producer: gather → policies → `assemble_motion_snapshot` → append. `run_shadow_cycle()` + `__main__`. |
| `scripts/active_trader/motion_api.py` | `motion_snapshot()` — pure read + freshness gate + honest envelope. |
| `scripts/active_trader/read_http.py` | dispatch wiring for `motion` (GET-only, 503 fail-closed). |

## 3. Contract shape

```json
{
  "contract": "active-trader-motion-snapshot-v1",
  "generated_at": 0.0,
  "ui_refresh_after_s": 5,
  "push_primary": true,
  "max_pull_fallbacks_per_minute": 2,
  "t2": { "operating_cap": 2, "provider_hard_cap": 8, "leases": [], "decisions": [] },
  "positions": [],
  "exit_signals": [],
  "read_only": true,
  "write": false,
  "authority": { "mutation": false, "order": false, "session_authorize": false, "canary": false, "financial_action": false }
}
```

`ui_refresh_after_s` logic:
* **5** — any T2 lease OR any open position is active.
* **10** — near-fire T1 candidates exist but no T2/positions.
* **30** — idle (T0) otherwise.

## 4. Field mapping to the UI normalizer

The UI (`normalizeMotion.ts`) is the contract source of truth; it reads snake_case
first. Every emitted item carries exactly those keys.

* **lease** ← `T2Lease.to_dict()`: `lease_id, symbol, admitted_at, renewed_at, expires_at, priority, position_open`.
* **decision** ← `CandidateDecision.to_dict()`: `symbol, tier, admitted, reason_code, refresh_after_s, priority`.
* **position** ← `ExitDecision.to_dict()` merged with position market fields:
  `symbol, state, action, reason_code, score, confirmations, drawdown_from_high_r,
  armed_for_s, fire_for_s, recovery_for_s, refresh_after_s` +
  `price, entry_price, hard_stop_price, high_watermark, evidence_age_s`
  (`evidence_age_s` = max finite of quote/book/tape ages).
* **exit_signal** (positions whose state == `EXIT_SIGNAL`): `symbol, state, reason_code, at`.

Parity is enforced by `test_active_trader_motion_api.py::_assert_ui_normalizer_parity`
(a mirror of the normalizer's required snake_case keys). No `inf`/`nan` is ever
emitted (`json.dumps(..., allow_nan=False)` in the test; the journal writer also
rejects non-finite values).

## 5. Fail-closed / read-only posture

* **journal absent/empty** → honest `active-trader-motion-unavailable-v1` envelope
  (a DISTINCT contract → UI `contractOk` is false → shows MOTION API UNAVAILABLE);
  empty `t2/positions/exit_signals` — nothing fabricated. This is CORRECT until the
  shadow producer has run.
* **journal present but stale** (older than `ACTIVE_TRADER_MOTION_MAX_AGE_S`, default
  60s) → the last-good snapshot returned verbatim with its OLD `generated_at`
  preserved plus `stale: true` / `data_state: DATA_STALE` / `last_update_age_s`.
* **exception on the GET path** → dispatch returns `503` (fail-closed; internals never
  leaked).
* `read_only`/`write:false`/`authority` (all false) are re-asserted on the read path —
  a tampered persisted authority block can never leak through.

## 6. How to run the shadow producer (cron DEFERRED)

No cron / systemd / feature-flag / schedule is wired in this PR. Run one cycle
manually:

```
PYTHONPATH=scripts python3 -m active_trader.motion_shadow
# or
PYTHONPATH=scripts python3 scripts/active_trader/motion_shadow.py
```

Optional inputs (honest, no hardcoded symbols):
* `ACTIVE_TRADER_MOTION_AUTHORIZED_SYMBOLS` (or `..._FILE`) — operator opt-in set of
  symbols with motion authorized in an ACTIVE workflow. Absent → nothing authorized →
  no T2 lease (fail-closed default until the session/capability layer supplies
  `motion_eligible`).
* `ACTIVE_TRADER_MOTION_POSITIONS` — JSON file of open-position momentum evidence.
  Absent → no positions (never fabricated).
* `ACTIVE_TRADER_MOTION_JOURNAL` — journal path override (default
  `data/active_trader/motion_journal.jsonl`, under the git-ignored `data/` tree).
* `ACTIVE_TRADER_MOTION_MAX_AGE_S` — stale threshold (default 60s).

## 7. Remaining gaps

* **No cron wired** — the shadow producer is manual/on-demand only in this PR.
* **L2 book freshness (#247) not integrated** — the T2 tier here derives from the JIT
  lease decision, not a live moomoo L2/book feed. Book-fed T2 promotion is future work.
* **Momentum inputs source** — `gather_momentum_observations` reads an optional
  fixtures/live file; a live paper/shadow position → momentum-evidence feed is not yet
  wired. Absent inputs fail closed to an empty (idle) snapshot.
* **Hysteresis across cycles** — a single `__main__` invocation uses fresh policy
  state. A long-running producer should pass a persistent `lease_manager` /
  `exit_policies` to `run_shadow_cycle` to preserve lease + hysteresis state.

## 8. Rollback

Pure additive + stacked on #250. To roll back: revert this PR's commits (removes
`motion_journal.py`, `motion_shadow.py`, `motion_api.py`, the two test files, this
doc, and the `motion` dispatch branch in `read_http.py`). No schema, service,
schedule, feature-flag, broker, session, deployment, or lockfile change to undo. The
runtime journal file lives under the git-ignored `data/` tree and is never committed.
