# TradingView Lanes (Alpaca multi-account era)

**Status:** Lane 1 documented · Lane 2 **dormant stub only** (feature-flagged OFF)  
**Date:** 2026-07-21 · **Build:** R5 taxonomy

## Lane 1 — Manual (TV → Alpaca native)

| Item | Detail |
|------|--------|
| Front-end | TradingView chart trading panel |
| Broker connection | **Native Alpaca broker connect** inside TradingView (operator-configured) |
| Trade AI role | **Read-only** after the fact: position/order sync when `api_read_enabled`, fill attribution tag `tv_manual`, reconciliation |
| Limits | TV options often single-leg only; typically **one** broker connection at a time in TV |
| Orders | Placed by TV/Alpaca — **not** by Trade AI `approve_proposal` / ATM |

No public webhook required for Lane 1.

## Lane 2 — Automation (webhook → proposal only)

**NOT ENABLED.** Design only + dormant API stub.

### Intended flow (future)

```
TV alert → HTTPS webhook → POST /api/v2/ingress/tradingview
  → create paper_trade_proposals row (origin=tv_webhook)
  → never place orders
  → human / ATM Path A review
```

### Auth design (OPERATOR DECISION PENDING)

1. URL path token (rotateable)  
2. Payload HMAC (shared secret in secrets modal)  
3. Optional TV / CDN IP allowlist  

### Public exposure options (OPERATOR DECISION PENDING)

| Option | Notes |
|--------|--------|
| Tailscale Funnel | Zero public VPS; still exposes a Funnel URL |
| Cloudflare Tunnel | Managed TLS + WAF |
| Relay VPS | Separate attack surface |

**Server today:** Tailscale + localhost gateway — **no public webhook endpoint is opened in this build.**

### Stub behavior

`POST /api/v2/ingress/tradingview` returns **503** when `TRADINGVIEW_INGRESS_ENABLED` is not `true` (default off). Tests prove 503. Enabling requires explicit env + auth implementation in a future session.

## Related

- Account keys: `tradeai_automated`, `alpaca_taxable_live`, `alpaca_ira_live` — `docs/brokers/trading-environments.md`
- Live roadmap: `docs/brokers/alpaca-live-accounts.md`
