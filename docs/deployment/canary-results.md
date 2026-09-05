# Communications Gateway — Canary Results Template

**Status:** Awaiting canary — **no canary run recorded yet**  
**Channel focus:** Telegram first  
**Mode during canary:** `COMMS_GATEWAY_MODE=CANARY` on designated host only  
**Production today:** **OFF**

---

## Run header (fill per canary)

| Field | Value |
|---|---|
| Date (UTC) | _awaiting_ |
| Operator | _awaiting_ |
| Deploy SHA | _awaiting_ |
| Host / environment | _awaiting_ |
| Message class allowlist | _e.g. operator_alert_ |
| Recipient / chat allowlist | _awaiting_ |
| Soak window | _awaiting_ |
| Shadow report attached? | _yes/no + path_ |

---

## Metrics (paste after run)

| Metric | Value |
|---|---|
| Events published (canary classes) | _awaiting_ |
| Deliveries SENT / FAILED | _awaiting_ |
| Legacy vs gateway match rate | _from shadow_report prior or parallel_ |
| subject_key mismatches | _awaiting_ |
| severity mismatches | _awaiting_ |
| route_intent mismatches | _awaiting_ |
| Duplicate / idempotent collisions | _awaiting_ |
| Operator-visible incidents | _awaiting_ |

---

## Decision

| Outcome | Criteria |
|---|---|
| HOLD | Insufficient soak or open mismatches |
| EXPAND class | Green soak; next class per `rollout-plan.md` |
| ROLLBACK to OFF | Any dual-send or safety concern — see `rollback-plan.md` |
| PROMOTE toward ACTIVE | Only after `production-activation.md` gates |

**This run’s decision:** _awaiting canary_

---

## Evidence paste

```
# Paste shadow_report() JSON summary and canary logs here
```

---

## History

| # | Date | Class | SHA | Decision | Notes |
|---|---|---|---|---|---|
| — | — | — | — | — | No canary yet |
