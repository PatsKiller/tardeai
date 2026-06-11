# Broker Orders — UI Card Contracts (Phase 5)

**Status:** IMPLEMENTED (endpoints live, dormant execution) · Surface: new "Broker Orders" area (operator
decision 2026-06-11) — separate from paper-proposal cards.

## Endpoints (all read/validate/translate/audit; NO execution endpoint exists)
| Endpoint | Purpose |
|---|---|
| `GET /api/v2/broker-orders/capabilities?broker=` | what the UI may show/edit per broker (native/composed/degraded/blocked + confidence + execution_disabled_notice) |
| `POST /api/v2/broker-orders/preview` | canonical intent in → validation + capability annotations + EXACT would-be broker payload + blocked-execution status; persists as draft |
| `GET /api/v2/broker-orders/drafts?broker=` | saved intents with state/translation/blocked_reason |

## Card payload shape (the editable state model = canonical OrderIntent)
```jsonc
{
  "instrument": {"symbol": "NVDA", "asset_type": "EQUITY"},
  "direction": "LONG",                    // LONG | SHORT
  "broker": "schwab", "account_key": null,
  "entry": {"method": "LIMIT",            // MARKET|LIMIT|STOP|STOP_LIMIT|MARKET_ON_CLOSE|LIMIT_ON_CLOSE
            "limit_price": 180.0, "stop_price": null,
            "entry_range": {"low": 178.0, "high": 181.0},      // optional product concept
            "price_link": {"basis": "BID", "type": "VALUE", "offset": 0.02}},  // bid-style entry (Schwab)
  "quantity": {"qty": 10},                // exactly one of qty | notional | contracts
  "tif": "DAY", "session": "NORMAL",      // sessions AM|PM|SEAMLESS = Schwab extended hours
  "exit_policy": {
    "stop": {"price": 172.0, "trail": {"basis": "LAST", "type": "PERCENT", "offset": 3.0}},
    "targets": [{"price": 195.0, "qty_pct": 50}, {"price": 205.0, "qty_pct": 50}],
    "oco": true, "on_stop_place_failure": "CLOSE_POSITION"},
  "ladder": {"legs": [{"entry_price": 179.0, "qty_pct": 50}, {"entry_price": 176.5, "qty_pct": 50}],
             "cancel_policy": "ALL_ON_STOP"},
  "risk": {"risk_reward": 2.0, "max_dollar_risk": 150, "position_size_usd": 1800, "sizing_basis": "shares"},
  "meta": {"strategy_id": "swing_breakout", "proposal_id": 203,
           "thesis": "trade thesis / proposal context", "signal_evidence": {"...": "..."}}
}
```

## Preview response (validation messages, capability hints, translation preview, execution-disabled notice)
```jsonc
{
  "ok": true, "intent_id": "uuid", "correlation_id": "uuid", "state": "TRANSLATED",  // or BLOCKED
  "validation": {"errors": [], "warnings": ["oco=true but exits incomplete ..."]},
  "capabilities": [          // unsupported-field indicators come straight from here
    {"capability": "exit.trailing", "level": "native", "confidence": "VERIFIED-SDK", "note": "..."},
    {"capability": "exit.multi_target", "level": "composed", "confidence": "UNVERIFIED", "note": "..."}],
  "translation_preview": {"orders": [/* exact Schwab payload: TRIGGER -> OCO[...] */],
                          "notes": ["ladder expanded ..."], "unverified": ["multi-target ..."]},
  "execution": {"allowed": false, "mode": "BROKER_DISABLED",
                "reason": "broker 'schwab' execution disabled (fail-closed default)"}
}
```

## Card UX rules
- Controls render only for capabilities ≠ blocked; `degraded` shows an amber hint (e.g., Alpaca trailing =
  "synthetic via monitor"); `blocked` renders a disabled control + the registry `msg`.
- The translation preview panel shows the EXACT broker JSON — the reviewable artifact for the future
  enablement checklist.
- Every card footer carries the execution-disabled notice verbatim from the capabilities endpoint.
- Draft save = POST preview (idempotent on intent_id); load = GET drafts.
