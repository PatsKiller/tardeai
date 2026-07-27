# Active Trader — Venue Eligibility & Schwab Compliance-Block Prompt (Stage 1a)

**Status:** Active · **Stage:** 1a (capability + compliance-block UX contract) · **Created:** 2026-07-27
**Scope:** READ-ONLY capability. **NO** place-order, **NO** session LIVE authorize, **NO** canary, **NO**
agent OPERATIONAL. `packet_g` remains Stage 0; no write flags are enabled by this work.

> Advisory/capability only. Nothing here places, routes, modifies, or sends anything. A Schwab
> compliance block **never** auto-routes — the operator must explicitly confirm any venue switch.

---

## 1. Product contract

1. **Schwab is the primary venue** when the symbol/account is eligible.
2. When a symbol/account is **Schwab compliance-blocked** (call-broker / low-float restriction):
   - the explicit **block reason is surfaced** to the operator,
   - the system **NEVER silently auto-routes** to Moomoo/Alpaca,
   - the operator is **prompted to switch** to an alternate venue/account and **must confirm**.
3. **Moomoo** — L2 + tape data role, and an execution alternate **when the operator opts in**.
4. **Alpaca** — an execution alternate **when the operator opts in**.

## 2. Eligibility statuses

| status | meaning |
|---|---|
| `eligible` | The proposed venue can execute this symbol (Schwab, not blocked; or an alternate the operator opted into). |
| `blocked_schwab_compliance` | Schwab is compliance-blocked for this symbol/account. Surfaces `block_code` + reason, sets `prompt_required=true`, suggests `alternate_venues`, and `auto_route=false`. |
| `restricted` | Not usable as-is — e.g. an alternate venue the operator has **not** opted into (needs opt-in), or an unknown venue id. |
| `unknown` | **Fail-closed.** Eligibility cannot be determined (no snapshot, venue capability absent, or non-blocklist coverage for an uncovered symbol). |

**Block codes:** `call_broker`, `low_float_restriction` (extensible).

## 3. Pure module — `scripts/active_trader/venue_eligibility.py`

Pure (no I/O / network / order / send). Fail-closed.

```python
evaluate_eligibility(symbol: str, proposed_venue: str,
                     capability_snapshot: Mapping | None) -> EligibilityResult
operator_prompt_required(block: EligibilityResult) -> dict   # message TEMPLATE, no send
```

`EligibilityResult` fields: `symbol, proposed_venue, status, reason, block_code, prompt_required,
alternate_venues, auto_route (hard-false), detail, contract`.

`operator_prompt_required(...)` returns a template with `prompt_required`,
`requires_operator_confirmation`, `auto_route=false` (hard), `send=false` (hard), `channel`,
`alternate_venues`, and a human `message`. It **raises TypeError** on a non-`EligibilityResult`.

### Capability snapshot shape (may be a fixture)

```json
{
  "venues": {
    "schwab": { "available": true, "compliance_coverage": "blocklist" },
    "moomoo": { "available": true, "operator_opt_in": false },
    "alpaca": { "available": true, "operator_opt_in": false }
  },
  "symbol_compliance": {
    "GNS":  { "schwab_blocked": true,  "block_code": "low_float_restriction", "detail": "…" },
    "AMTD": { "schwab_blocked": true,  "block_code": "call_broker" },
    "AAPL": { "schwab_blocked": false }
  }
}
```

- `compliance_coverage: "blocklist"` (default) → a symbol **not** in `symbol_compliance` is `eligible`
  (Schwab trades it normally; the blocklist is authoritative).
- `compliance_coverage: "allowlist"` / `"unknown"` → an uncovered symbol is `unknown` (fail-closed).
- Schwab venue absent/`available:false` → `unknown`.
- Alternate venue: `available` + `operator_opt_in:true` → `eligible`; `available` without opt-in →
  `restricted` (`prompt_required=true`); absent → `unknown`.

## 4. HTTP endpoint (read-only)

```
GET /api/v3/active-trader/venue-eligibility?symbol=SYM[&venue=schwab|moomoo|alpaca]
```

- Served by `portfolio_server` → `active_trader_read_boot` → `active_trader/read_http.dispatch`.
- **GET-only** (POST/PUT/… → `405`). Missing `symbol` → `400`.
- Uses the capability snapshot from `active_trader/read_api.capability_snapshot()`
  (venue inventory + compliance **fixtures**: `config/active_trader_compliance_fixtures.json`,
  falling back to the committed `…example.json`; env override
  `ACTIVE_TRADER_COMPLIANCE_FIXTURES`). Missing fixtures → snapshot `source:"empty"` → fail-closed `unknown`.
- Response envelope: `stage:1, sub_stage:"1a", write:false, canary:false, read_only:true,
  auto_route:false, eligibility:{…}, operator_prompt:{…}, authority:{order:false, financial_action:false, …}`.

**Example — Schwab block:**
```json
{ "write": false, "canary": false, "auto_route": false,
  "eligibility": { "symbol": "GNS", "proposed_venue": "schwab",
    "status": "blocked_schwab_compliance", "block_code": "low_float_restriction",
    "prompt_required": true, "alternate_venues": ["moomoo","alpaca"], "auto_route": false },
  "operator_prompt": { "prompt_required": true, "requires_operator_confirmation": true,
    "auto_route": false, "send": false, "channel": "operator_confirm",
    "message": "GNS: Schwab is compliance-blocked — … Switch to Moomoo or Alpaca? This will not happen automatically; confirm to proceed." } }
```

## 5. Operator banner copy (UI contract — copy only)

When `eligibility.status == "blocked_schwab_compliance"`, a banner surfaces the block and the
explicit switch prompt (rendered from `operator_prompt.message`). It offers the operator an explicit
choice among `alternate_venues`; **no venue is preselected and nothing routes until the operator
confirms.** When `status == "eligible"`, no banner/prompt is shown. (A live banner component is
deferred — the API + this copy are the Stage 1a contract.)

## 6. Guardrails / non-goals

- No `place_order`, no session LIVE authorize, no canary, no agent OPERATIONAL, no auto-route.
- `packet_g` stays Stage 0; `HARD_OFF` write flags remain false (`assert_stage0_safe()`).
- Real per-symbol Schwab compliance/tradeability data is a later stage; Stage 1a uses fixtures so the
  UX contract is deterministic and testable.

## 7. Source & tests

- Module: `scripts/active_trader/venue_eligibility.py`
- Snapshot/endpoint: `scripts/active_trader/read_api.py`, `scripts/active_trader/read_http.py`
- Fixtures: `config/active_trader_compliance_fixtures.example.json`
- Tests: `tests/test_active_trader_venue_eligibility.py` (17): Schwab block → prompt + no auto-switch;
  eligible Schwab → no prompt; fail-closed unknown; alternate opt-in; GET-only + zero write authority;
  Stage 0 write flags remain off.
