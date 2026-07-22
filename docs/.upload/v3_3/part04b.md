
## 16F.2 Account discovery

Each adapter implements:

```yaml
discover_accounts:
read_account:
read_balances:
read_positions:
read_orders:
read_capabilities:
validate_symbol:
validate_order:
place_order:
replace_order:
cancel_order:
cancel_all:
close_position:
close_all_positions:
stream_order_events:
reconcile:
```

Unsupported methods return a typed `CAPABILITY_UNAVAILABLE`, not a fabricated success and not a generic `NotImplementedError` at the operator surface.

## 16F.3 Broker capability registry

Required capability dimensions:

```text
READ_ACCOUNT
READ_POSITION
READ_ORDER
STREAM_ORDER_EVENTS
PLACE_MARKET_RTH
PLACE_LIMIT_RTH
PLACE_LIMIT_EXTENDED
REPLACE_ORDER
CANCEL_ORDER
CANCEL_ALL_ACCOUNT
CANCEL_ALL_SYMBOL
NATIVE_CLOSE_POSITION
NATIVE_CLOSE_ALL
OPPOSITE_ORDER_CLOSE
BRACKET_ORDER
OTO_PROTECTION
TRAILING_STOP
FRACTIONAL_SHARES
SHORT_SELL
MULTI_ACCOUNT
LIVE_SESSION_UNLOCK
PRETRADE_ESTIMATE
SYMBOL_TRADABILITY
ELECTRONIC_ENTRY_ELIGIBILITY
```

Every capability row records:

```yaml
broker:
account_id:
environment:
capability:
state: SUPPORTED|UNSUPPORTED|UNKNOWN|DEGRADED|RESTRICTED
source: DOCUMENTATION|RUNTIME_PROBE|BROKER_RESPONSE|OPERATOR_OVERRIDE
verified_at:
expires_at:
adapter_version:
evidence_ref:
notes:
```

Runtime broker responses override stale documentation for the affected account and symbol.

## 16F.4 Controlling broker semantics

### Alpaca

The adapter may use native API operations where available for:

- cancel a single order;
- cancel all account orders;
- close a symbol position;
- close all positions;
- equity market, limit, stop, stop-limit, and trailing-stop orders;
- bracket/OTO protection where supported by the selected environment and session.

Every multi-status response is reconciled per child operation.

### Moomoo

Moomoo supports modify/cancel operations and a live-account cancel-all operation with documented account-level rate limits. Closing a position is implemented as an opposite-side order for the current position quantity when no dedicated native flatten primitive is available.

US 24-hour trading permits limit orders rather than assuming a market order.

### Schwab

The adapter must capability-probe place, replace, cancel, order-state, and session support against the current Trader API account.

No generic native “flatten” operation is assumed.

Flatten translates to:

```text
cancel relevant non-protective orders
→ refresh the position
→ create an opposite-side close order
→ use RTH market order only when account, symbol, session, and policy permit
→ otherwise use governed marketable-limit logic
→ reconcile to verified zero
```

Schwab may reject electronic opening transactions for some symbols or require broker assistance. Trade AI treats the returned rejection as authoritative for that symbol/account and does not repeatedly submit the same rejected opening order.

## 16F.5 Broker preflight

Before authorization, Active Trader performs non-order preflight where supported:

- account status;
- balances and buying power;
- symbol recognition;
- tradability flags;
- order-type and session capability;
- account restrictions;
- shortability when relevant;
- price increment;
- maximum quantity/notional where exposed.

A preflight pass is not a guarantee that a broker will accept the live order.

## 16F.6 Normalized rejection classifier

Every rejected or failed order receives:

```yaml
rejection_event_id:
broker:
account_id:
symbol:
order_intent_id:
raw_status:
raw_code:
raw_message:
normalized_code:
retryable:
requires_operator:
requires_broker_call:
affected_capability:
first_seen_at:
last_seen_at:
expires_at:
evidence_hash:
```

Normalized codes include:

```text
SECURITY_REQUIRES_BROKER_ASSISTANCE
ELECTRONIC_ENTRY_NOT_ALLOWED
LOW_PRICE_OR_MICROCAP_RESTRICTION
SECURITY_NOT_DAY_TRADE_ELIGIBLE
ACCOUNT_RESTRICTED
ACCOUNT_NOT_AUTHORIZED
INSUFFICIENT_BUYING_POWER
INSUFFICIENT_SHARES
ORDER_TYPE_NOT_SUPPORTED
SESSION_NOT_SUPPORTED
PRICE_INCREMENT_INVALID
PRICE_BAND_REJECTED
QUANTITY_LIMIT_REJECTED
POSITION_OR_ORDER_CONFLICT
RATE_LIMITED
MARKET_CLOSED
HALTED
STALE_ACCOUNT_STATE
AUTHENTICATION_EXPIRED
UNKNOWN_BROKER_REJECTION
```

Unknown rejections never enter an infinite retry loop.

## 16F.7 User notification

A material rejection generates:

- blocking modal in Active Trader;
- audible alert when the operator has enabled sound;
- journal event;
- Command Center notification;
- Telegram/push alert where configured;
- optional email for unresolved or broker-call-required restrictions.

The notification states:

```text
broker
account
symbol
requested quantity
raw broker message
normalized reason
whether any quantity filled
current protection state
authorized alternate accounts
required operator action
```

## 16F.8 Primary and fallback accounts

An account may be authorized as:

```text
PRIMARY
FALLBACK
DISABLED
```

A fallback account has:

- zero or explicit initial allocation;
- maximum fallback shares/notional;
- maximum fallback risk;
- permitted rejection classes;
- priority;
- broker and account identity;
- included session authorization hash.

Automatic fallback is allowed only when:

```text
source order is confirmed rejected or safely cancelled
AND source filled quantity is known
AND alternate account is already authorized
AND symbol is eligible there
AND fresh market and Level 2 conditions still pass
AND session risk remains available
AND aggregate quantity/risk remains inside the envelope
AND auto_failover policy is enabled
```

The engine never duplicates the rejected quantity without first proving the source account did not fill it.

## 16F.9 Alternate broker not already authorized

When no authorized fallback exists:

1. stop automated entry for that symbol;
2. preserve all other session activity;
3. notify the operator;
4. display eligible alternate accounts;
5. allow the operator to amend the session draft;
6. require a new session 2FA because the account set or quantity envelope changed;
7. reactivate only after the new hash is authorized.

The rejection screen may not silently add an account after 2FA.

---

# 16G. COMPLETE TICKET, POSITION, AND PROFIT/LOSS EXPERIENCE

## 16G.1 Pre-trade ticket

Before submission, the ticket displays:

```text
symbol
broker/account child allocations
side
shares and notional
current last/bid/ask
arrival spread
expected entry range
maximum authorized entry
estimated average entry
stop and protection type
targets and runner policy
risk per share
risk by account
aggregate risk
estimated fees
float and source
volume, RVOL, dollar volume and float turnover
catalyst
data-quality state
Level 2/tape state
session authorization ID and short hash
```

## 16G.2 Working-order ticket

While entering:

```text
requested shares
filled shares
remaining shares
average fill
current limit
next allowed limit
maximum cap
modifications used
rate tokens remaining
time in force
TTL remaining
book/tape reason
cancel eligibility
protection state for filled quantity
```

## 16G.3 In-trade ticket

Aggregate and per-account views display:

```text
current last/bid/ask/microprice
shares
average entry
cost basis
market value
unrealized P&L $
unrealized P&L %
unrealized P&L in R
realized P&L
total P&L
MFE
MAE
capture ratio
active stop
stop distance
profit-protection state
RES
RRS
runner state
current management mode
next resistance
next support
current working orders
estimated flatten value
estimated smart-sell value
```

P&L uses broker positions and order events reconciled with current marks. The UI identifies the mark source and timestamp.

## 16G.4 Post-trade ticket

After flat:

- realized P&L by account and aggregate;
- fees;
- slippage;
- execution-quality grade;
- MFE/MAE;
- exit efficiency;
- runner result;
- reason codes;
- replay link;
- journal completeness;
- broker/database reconciliation;
- Darwin score when available.

---

# 16H. QUICK ADD, CANCEL, FLATTEN, AND INTELLIGENT SELL

## 16H.1 Quick-add controls

Default quick-add presets:

```text
100
200
500
1000
```

The unit selector is explicit:

```text
SHARES
DOLLARS
```

Presets are operator-configurable.

A quick-add click opens a confirmation modal showing:

- selected increment;
- account distribution;
- projected total shares;
- projected average entry;
- projected notional;
- current and projected risk;
- current stop;
- projected maximum loss;
- remaining session limits;
- current RES/RRS;
- Level 2 entry mode;
- rejection/fallback policy.

The confirmed add uses the same validated smart-limit entry manager as the original entry.

## 16H.2 Add eligibility

An add is blocked when:

- session not active;
- symbol/account not authorized;
- increment exceeds account or session envelope;
- protection is uncertain;
- current price exceeds authorized add cap;
- RES/RRS policy does not permit adding;
- Level 2/tape state is stale or contradictory;
- broker/account restriction exists;
