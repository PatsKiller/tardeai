
Architect feedback integrated:

1. explicit Minimum Viable Loop;
2. Sentinel SLA and fail-open/fail-closed semantics;
3. wrap-don't-rewrite data ruling;
4. unified roadmap and baseline reports;
5. side-by-side product-upgrade lab;
6. Moomoo data, microstructure, scalp, broker and safety integration;
7. SnapTrade exclusion pending evidence;
8. current credentials and 2FA constitution.

---

# APPENDIX B — VERSION DISCOVERY SNAPSHOT

As of 2026-07-22 public discovery:

```text
OpenAI Python SDK latest observed: 2.46.0
OpenAI Agents SDK latest observed: 0.18.3
Hermes Agent latest observed: 0.19.0
OpenClaw stable observed: 2026.7.1-2
OpenClaw beta observed: 2026.7.2-beta.3
Moomoo OpenD documentation observed: 10.9.6908
```

These values are discovery inputs. The live host inventory and compatibility artifacts control promotion.

---

# APPENDIX C — FIRST IMPLEMENTATION CLOSEOUT TEMPLATE

```text
BASELINE SHA:
DEPLOYED SHA:
PRODUCTION SERVICES CHANGED: NO|YES
PRODUCTION PACKAGES UPGRADED IN PLACE: NO

P0 REPORTS COMPLETE:
UPGRADE LAB CREATED:
PROD SECRETS PRESENT IN LAB: NO
ROLLBACK TESTED:

MVL
  Sentinel kernel:
  KB:
  Darwin:
  nightly reflection:
  end-to-end case:
  retrieval rate:
  scored artifact rate:

MOOMOO
  OpenD state:
  entitlement state:
  quota:
  replay:
  sequence gaps:
  decision use enabled: NO

SCALP
  mode: DESIGN|SHADOW|SIMULATION|LIVE_CANARY
  live adapter:
  live account:
  session authorization id:
  session authorization hash:
  session start:
  session entry cutoff:
  session expiry:
  max trades:
  max concurrent positions:
  max gross notional:
  max risk per trade:
  max daily loss:
  live orders submitted:
  positions reconciled:
  session closeout:

SAFETY
  orders outside authorization: 0
  session-limit breaches reaching adapter: 0
  unprotected live scalp positions: 0
  reflective-agent broker writes: 0
  emergency revocation tested:
```

# APPENDIX D — ACTIVE TRADER DUE-DILIGENCE NOTES

## Repository observations

- Command Center v3 currently uses React 18, React Router 6, Vite 5, TypeScript, Playwright, lightweight-charts and Recharts.
- The current router is served under `/v3`.
- The current Trading hub already includes a `Scalp` tab, broker orders, execution quality, and scanner-selection behavior.
- The current terminal chrome is always on; it is not an existing classic/new feature toggle.
- Therefore the least disruptive delivery is a separate `/v3-next` bundle rather than an in-place TradingHub rewrite.

## Moomoo API observations

- Real-time order book and tick-by-tick require subscription.
- US Level 2 does not provide the same detailed order-book identity as certain Hong Kong entitlements.
- Market snapshot provides volume, turnover, issued shares, outstanding shares and market value fields.
- Moomoo screening can provide float-share data.
- Live place, modify and cancel calls require OpenD trading unlock.
- OpenD unlock is shared across connections, making single-gateway isolation mandatory.
- `place_order` is documented at 15 requests per 30 seconds per account.
- `modify_order` is documented at 20 requests per 30 seconds per account.
- The legacy 750 ms chase loop is therefore rejected.

## Market-microstructure research observations

- Order-flow imbalance has a stronger short-horizon relationship with price changes than raw trade volume in the cited research.
- Queue imbalance has statistically significant one-tick predictive content, stronger for large-tick than small-tick stocks.
- Multi-level integrated OFI can explain more than top-level OFI alone.
- These findings justify feature inclusion, not a claim of deployable edge. Trade AI must validate them on its own Moomoo replay.

## Intraday-margin transition

The SEC approved FINRA's replacement of pattern-day-trader provisions with intraday-margin standards in April 2026, with a FINRA-announced effective date and an 18-month broker phase-in.

Trade AI must therefore avoid hard-coding one universal PDT interpretation. It reads and journals the actual broker/account rule state and capability effective at order time.

## Codex delivery observations

Codex performs best on large changes when it receives:

- repository instructions;
- a configured test environment;
- a scoped implementation plan;
- bounded permissions;
- explicit acceptance checks;
- iterative review.

The staged implementation prompt delivered with v3.2 follows that pattern.

## Primary references

1. Moomoo API v10.9 — Subscribe and Unsubscribe.
2. Moomoo API v10.9 — Get Real-time Order Book.
3. Moomoo API v10.9 — Get Real-time Tick-by-Tick.
4. Moomoo API v10.9 — Get Market Snapshot.
5. Moomoo API v10.9 — Place Orders.
6. Moomoo API v10.9 — Modify or Cancel Orders.
7. Moomoo API v10.9 — Unlock Trade.
8. Cont, Kukanov and Stoikov — The Price Impact of Order Book Events.
9. Gould and Bonart — Queue Imbalance as a One-Tick-Ahead Price Predictor.
10. Cont, Cucuringu and Zhang — Cross-Impact of Order Flow Imbalance in Equity Markets.
11. SEC Release 34-105226 — FINRA Rule 4210 intraday-margin approval and transition.
12. OpenAI — Introducing Codex; Running Codex Safely; How OpenAI Uses Codex.

# APPENDIX E — MULTI-BROKER, DOCUMENTATION, AND NOTIFICATION DUE DILIGENCE

## Broker action evidence

### Alpaca

Official Alpaca API documentation provides:

- cancel-all-open-orders endpoints;
- close-position by symbol;
- close-all-positions;
- market, limit, stop, stop-limit, and trailing-stop equity order types;
- bracket and OTO order structures.

The adapter should use native operations only after environment/account capability verification and must reconcile HTTP multi-status results.

### Moomoo

Official Moomoo documentation provides:

- modify/cancel;
- live cancel-all for supported account/market combinations;
- documented request limits;
- opposite-order close semantics for shortable securities;
- limit-only US 24-hour trading.

Therefore Moomoo flatten is a translated close workflow, not an assumed universal native endpoint.

### Schwab

Public Schwab materials state that electronic or broker-assisted eligibility can vary for securities, including micro-cap/restricted acceptance review, and that market orders are not available for extended-hours trading.

The current Trader API capability and rejection behavior must be learned from the live account/API response. The architecture does not hard-code a promise that every low-float symbol is electronically eligible.

## Google Drive

The Drive API supports create/update and resumable uploads. Stage sync uses idempotent file IDs and hashes rather than creating duplicate copies after retries.

## Gmail

The Gmail API supports sending MIME messages through `users.messages.send`. The implementation uses a dedicated notification credential with minimum send scope.

## Bitwarden

Bitwarden Secrets Manager supports secrets grouped into projects and machine accounts with read or read/write permissions. The unattended implementation uses a lab-scoped write identity for placeholders and never grants agents raw production-secret access.

## Review principle

The external architecture litmus review is challenge-only. It produces evidence and a verdict; it does not “helpfully” change code or architecture.
