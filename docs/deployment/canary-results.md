# Communications Gateway — Canary Results

**Status:** Canary **PASS** for message class `ops` → promoted to **ACTIVE** (`COMMS_GATEWAY_ACTIVE_CLASSES=ops`)  
**Channel focus:** Telegram first  
**Production mode now:** **ACTIVE** (allowlisted classes only)

### Telegram canary / ACTIVE env (fail-closed; never repo defaults)

| Env | Purpose |
|---|---|
| `COMMS_GATEWAY_MODE=CANARY` / `ACTIVE` | Ownership mode (host-local systemd) |
| `COMMS_GATEWAY_CANARY_CLASSES` | Comma-separated classes for CANARY deliver |
| `COMMS_GATEWAY_CANARY_CHATS` | Optional chat id filter for CANARY |
| `COMMS_GATEWAY_ACTIVE_CLASSES` | Comma-separated classes for ACTIVE deliver |

Empty class allowlist → Telegram deliver **blocked**. Repo default remains **OFF**.

---

## Run header

| Field | Value |
|---|---|
| Date (UTC) | 2026-09-05T04:30:30Z (canary) → 2026-09-05T04:31:04Z (ACTIVE) |
| Operator | johnclaw (agent-assisted cutover) |
| Deploy SHA | `f579053b8accb775c12b7d5e4e35f5533b179fbe` (PR #864) |
| Host / environment | portfolio-server CURRENT exact-main |
| Message class allowlist | CANARY: `ops` → ACTIVE: `ops` |
| Recipient / chat allowlist | existing Telegram operator chats (from rendered env) |
| Soak window | short operator soak; canary SENT then ACTIVE for same class |
| Shadow report attached? | yes — `~/.local/state/cio-phase2-exact-main/comms-shadow-evidence/shadow_report.json` (match rate 1.0) |

---

## Metrics

| Metric | Value |
|---|---|
| Events published (canary/active ops) | ≥2 gateway-owned (`telegram_alert.send_telegram`) |
| Deliveries SENT / FAILED | Telegram **SENT** ≥2 (`adapter_version=telegram@v1`) |
| Legacy vs gateway match rate | **1.0** on production shadow compares |
| subject_key / severity / route_intent mismatches | 0 (prod); 1 intentional probe |
| Operator-visible incidents | Markdown parse_mode 400 then plain-text resend (known); delivery ok |

---

## Decision

**This run’s decision:** **PROMOTE toward ACTIVE** for class `ops` only.

Non-`ops` classes remain legacy-send + best-effort ledger until a new canary row lands.

---

## Evidence paste

```
Shadow: production_match_rate=1.0 (2/2 live events)
Canary: gateway_mode_at_write=CANARY message_class=ops SENT telegram@v1
ACTIVE: gateway_mode_at_write=ACTIVE message_class=ops SENT telegram@v1
Systemd: 32-comms-gateway-mode.conf MODE=ACTIVE ACTIVE_CLASSES=ops
```

---

## History

| # | Date | Class | SHA | Decision | Notes |
|---|---|---|---|---|---|
| 1 | 2026-09-05 | ops | f579053b8 | PROMOTE ACTIVE | PR #864 Telegram ownership + allowlists |
