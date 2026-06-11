# Canonical Order-Intent Model (ADR-B2)

**Status:** ACCEPTED · Implemented in `scripts/brokers/order_intent.py`. The model is written to the RICHEST
verified broker surface (Schwab SDK schema) so no future schema migration is needed; brokers that can't
express a field DEGRADE or BLOCK via the capability registry — the model never shrinks to a broker.

## Shape (summary — code is authoritative)
```
OrderIntent
  intent_id (uuid)  correlation_id  created_by  broker  account_key
  instrument: {symbol, asset_type: EQUITY|OPTION, option_legs?: [...model-only this phase]}
  direction: LONG|SHORT
  entry: {method: MARKET|LIMIT|STOP|STOP_LIMIT, limit_price?, stop_price?,
          entry_range?: {low, high},                  # product concept; translators pick representable form
          price_link?: {basis: LAST|BID|ASK|MARK, type: VALUE|PERCENT|TICK, offset}}  # bid-style entries
  quantity: {qty?: Decimal, notional?: Decimal, contracts?: int}    # exactly one set
  tif: DAY|GTC|FOK|IOC|EOW|EOM      session: NORMAL|AM|PM|SEAMLESS
  exit_policy:
    stop?: {price? | trail?: {basis, type, offset}}    # native trailing config (Schwab 1:1)
    targets: [{price, qty_pct}]                        # multi-target exits
    oco: bool                                          # exits linked as OCO
    on_stop_place_failure: CLOSE_POSITION|ALERT_ONLY   # preserves Alpaca behavior contract
  ladder?: {legs: [{entry_price, qty_pct}], cancel_policy: ALL_ON_STOP|INDEPENDENT}
  linked_graph (derived): TRIGGER/OCO node tree built from entry+exit_policy+ladder
  risk: {risk_reward?, max_dollar_risk?, position_size_usd?, sizing_basis}
  meta: {strategy_id, proposal_id?, thesis?, signal_evidence?}      # audit lineage
  state: DRAFT|VALIDATED|TRANSLATED|BLOCKED|SUBMITTED_PENDING|ACKNOWLEDGED|FILLED|CANCELLED
```
States `SUBMITTED_PENDING`→`FILLED` are defined now but unreachable for Schwab this phase (guard blocks at
TRANSLATED). DRAFT/VALIDATED/TRANSLATED/BLOCKED are the live states.

## Validation rules (implemented + tested)
ordering (stop<entry<target for longs, inverted for shorts), exactly-one quantity basis, ladder pct sums to
100±0.01, trailing requires basis+type+offset>0, OCO requires ≥2 exit legs, options intents always validate
to `BLOCKED_CAPABILITY` this phase, entry_range requires low<high and method LIMIT.

## Mappings
- **Alpaca:** entry LIMIT + stop + 1 target + oco=true → `order_class=bracket`. Trailing → capability
  `degraded: monitor_synthetic`. Ladder → N independent intents (cancel coordination ours). SHORT → side
  sell (paper only).
- **Schwab:** entry → SINGLE or TRIGGER root; exits → child OCO {LIMIT target(s), STOP/TRAILING_STOP};
  trailing 1:1 to link basis/type/offset; session enum direct; bid-style entry via price_link.
  Multi-target: N targets → OCO of N limits with qty splits (UNVERIFIED runtime acceptance; translator
  emits, guard blocks).

## Audit metadata
Every intent persists: original product payload, normalized model, per-broker translation, validation
warnings, blocked status + reason, correlation_id — table `broker_order_intents` (append-only states via
`intent_state_events`).
