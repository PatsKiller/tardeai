# Active Trader — Stage 1b: Near-Ready Candidate Read Model (v1)

**Status:** read-only. NO orders, NO session LIVE, NO canary, NO auto-fire.
**Contract id:** `active-trader-near-ready-v1`
**Endpoint:** `GET /api/v3/active-trader/near-ready` (served by `portfolio_server.py` →
`active_trader_read_boot` → `read_http.dispatch`; NOT api_v2).
**Feature flag:** `near_ready_desk` — **default OFF**.

---

## 1. Intent

The near-ready desk lists candidates that are **below** the classic Trade AI scanner GO bar
(roughly ≥5× RVOL / an actionable GO verdict) but show *building* characteristics — elevated-
but-sub-GO relative volume, constructive momentum, a pullback-break setup, a constructive RSI.

These are **watch-quality reads**. The operator opts in later; this stage only defines and
serves the read contract. Nothing here routes, fires, sizes, or authorizes anything.

> **This is NOT a Trade AI scanner GO.** Near-ready is a *weaker*, earlier, building-
> characteristics read. A symbol that already clears the GO bar is **excluded** from this desk
> (tier `excluded_already_go`) — it belongs to the main scanner. Do not treat a near-ready row
> as a GO, a signal to fire, or an approval of any kind.

---

## 2. Eligibility signals (deterministic)

Scoring is pure and deterministic given the same input + config (`scripts/active_trader/near_ready.py`).
Each candidate is evaluated against four **building signals**. Fields are read from either the
Stage 1b fixture or an existing scanner/watch payload (same field names).

| Signal | Rule (default config) | Sourced from |
|---|---|---|
| `building_volume` | `near_rvol_min (1.5) ≤ rvol < go_rvol (5.0)` | `rvol` / `relative_volume` |
| `momentum` | `momentum_min_pct (1.0) ≤ change_pct ≤ momentum_max_pct (60.0)` | `change_pct` / `change_percent` |
| `pullback_break` | `entry_setup` matches one of `{pullback, pullback_break, breakout, flag, bull_flag, base, vwap_reclaim}` | `entry_setup` / `setup` / `setup_type` |
| `constructive_rsi` | `rsi_min (45) ≤ rsi ≤ rsi_max (68)` | `rsi` / `rsi_14` |

All thresholds live in `DEFAULT_CONFIG` and are config-overridable (no magic numbers buried in
logic). Missing fields simply **fail** their signal — a partial record never raises.

### Tiers

Let `n` = number of building signals satisfied, and `is_trade_ai_go` = `rvol ≥ go_rvol` **or**
(`decision_actionable is True` and verdict/decision/operator_pill ∈ `{GO, STRONG_GO}`).

| Tier | Condition |
|---|---|
| `excluded_already_go` | `is_trade_ai_go` (checked first — a GO is never near-ready) |
| `near_ready` | `n ≥ min_signals (2)` |
| `watch` | `n == 1` |
| `excluded` | `n == 0` |

`select_near_ready()` returns `near_ready` rows by default (highest score first, RVOL tiebreak);
`include_watch=True` also returns `watch` rows. `excluded*` rows are never returned.

**Design note — red-day pullbacks qualify.** A candidate down on the day (negative `change_pct`)
with a pullback setup + constructive RSI + building volume still reaches `near_ready`. The
`momentum` signal is only one of four; the setup is the point, not today's sign.

---

## 3. Read contract

`GET /api/v3/active-trader/near-ready` returns:

```jsonc
{
  "contract": "active-trader-stage0-read-api-v1",
  "stage": 1, "sub_stage": "1b",
  "write": false, "canary": false, "read_only": true, "auto_route": false,
  "desk_enabled": false,                 // reflects near_ready_desk flag (default OFF)
  "near_ready_contract": "active-trader-near-ready-v1",
  "capability_source": "fixtures",       // or "empty"
  "count": 3,
  "candidates": [
    {
      "symbol": "CRNT", "tier": "near_ready", "score": 4, "max_score": 4,
      "signals": {"building_volume": true, "momentum": true, "pullback_break": true, "constructive_rsi": true},
      "reasons": ["building volume rvol=2.8 (below 5x GO)", "constructive momentum +3.5%", "..."],
      "is_trade_ai_go": false,
      "rvol": 2.8, "change_pct": 3.5, "rsi": 58.0, "setup": "pullback",
      "venue_status": "eligible",        // Stage 1a join (see §4)
      "venue_prompt_required": false,    // prompt-only flag; never routes
      "venue_auto_route": false
    }
  ],
  "authority": { "mutation": false, "order": false, "session_authorize": false, "canary": false, "financial_action": false }
}
```

- **GET-only.** Any other method → `405`, `write:false`.
- **Empty is OK.** No fixture / no qualifying candidate → `count:0`, `candidates:[]`.
- **Optional query:** `?include_watch=true` also lists single-signal `watch` rows.

### `desk_enabled` and the feature flag

`near_ready_desk` **defaults OFF** and gates **operational promotion** (UI surfacing / later
stages), NOT read visibility — the endpoint always serves the read model (reading is safe), and
reports the flag as `desk_enabled` so consumers know not to promote/act on it. The flag is a
read-desk gate; it is deliberately **not** in `HARD_OFF` (it grants no write/canary/order
authority). `assert_stage0_safe()` continues to pass with it on or off.

---

## 4. Venue-eligibility join (prompt_required only)

When `join_venue` is set (default for the endpoint), each returned row is annotated using the
Stage 1a evaluator (`venue_eligibility.evaluate_eligibility`) against the Schwab-primary default:

- `venue_status` — `eligible | blocked_schwab_compliance | unknown | restricted`
- `venue_prompt_required` — **boolean only**; whether an operator prompt would be required
- `venue_auto_route` — hard `false`

This is advisory context for the eventual operator UX. It carries **no** routing, no venue
switch, no order path. A blocked symbol simply surfaces `venue_prompt_required: true`.

---

## 5. Safety posture (what this stage does NOT do)

- No order, no session authorize, no canary, no auto-fire, no runner, no multi-account live.
- No broker writes; the module is pure scoring over fixture/payload dicts.
- `auto_route`/`venue_auto_route` hard `false`; `authority.*` all `false`.
- Hard-off flags (`live_canary`, `order_routes`, `session_authorize`, `moomoo_order_path`,
  `multi_account_live`, `runner`) untouched and still enforced by `assert_stage0_safe()`.
- No packet enables write or canary.

---

## 6. Files

| File | Role |
|---|---|
| `scripts/active_trader/near_ready.py` | Pure scoring/filter (`score_candidate`, `select_near_ready`) |
| `scripts/active_trader/read_api.py` | `_load_near_ready_fixtures`, `near_ready_candidates`, `ReadOnlyActiveTraderAPI.near_ready` |
| `scripts/active_trader/read_http.py` | `near-ready` GET route |
| `config/active_trader_near_ready_fixtures.example.json` | Deterministic fixture inputs |
| `tests/test_active_trader_near_ready.py` | 20 tests (scoring, tiers, endpoint, flag-OFF) |

**Live override:** drop a `config/active_trader_near_ready_fixtures.json` (or set
`ACTIVE_TRADER_NEAR_READY_FIXTURES=/path`) to feed real scanner/watch-derived candidates; the
committed `.example.json` is the fallback. A later stage adapts the live scanner/watch pull
directly (same field names) — no contract change required here.
