# CIO Operator Product (proactive Alex)

Authority: `READ_ONLY_ADVISORY`. No broker/order/stop/2FA.

## What this pass adds

- Decision-first Telegram card (`Alex · CIO NOW`) with **inline URL buttons**
- Signed Tailscale action links (`/v3/go/cio/decision/{id}/action/{action}?t=`)
- GET confirms only; POST applies `post_decision_disposition`
- Material publisher + holdings delta (transfer ≠ purchase)
- Symbol research packet (honest NAV UNAVAILABLE; R8 is not OOS)
- Production case JSONL + nightly reflection (propose only)
- Delivery worker no longer treats a batch summary as one notification
- `scripts/cio_telegram_mode.sh {status|live|interdict}` rollback

## What is still not claimed

- `CIO_ONLY_LIVE` on portfolio-server until `cio_telegram_mode.sh live` after COP
- Learning runtime remains `OPERATIONAL_BUT_EVIDENCE_ACCUMULATING`
- STOCK_ALMANAC_INTEGRATION stays FAIL in CIO v4 honesty gates
