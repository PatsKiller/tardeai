# Communications Gateway — Canary Results

**Status:** Canary **PASS** for message class `ops` → **attempted ACTIVE, then reverted to CANARY**  
**Channel focus:** Telegram first  
**Production mode now:** **CANARY** (`COMMS_GATEWAY_MODE=CANARY`, `CANARY_CLASSES=ops`,
`CANARY_CHATS=6993102664,8797974247`) — `[VERIFIED]` at
`curl -s http://127.0.0.1:7777/api/v2/communications/health` → `"mode": "CANARY"`

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

## Wave A/B sample sends (two verified cases) `[VERIFIED]`

The operator canary exercised two sample sends. Each outcome is the correctness pair the
gateway must exhibit:

| Sample | message_class | Outcome | Meaning |
|---|---|---|---|
| `operator_alert` | normalized → `ops` | **SENT** (gateway-owned, `provider_message_id` populated) | Owned class routes through gateway and settles SENT |
| `report` | (non-owned) | **fail-closed → `LEGACY_DELIVERED`** | Non-owned class does not route through gateway; the auto-reserved stub settles `LEGACY_DELIVERED` instead of staying `RESERVED` (F1 fix) |

The `report` case demonstrates the F1 fix end-to-end: a class the gateway does not own
fails closed and records `LEGACY_DELIVERED` rather than leaving a permanently `RESERVED`
stub.

## Mode revert — ACTIVE → CANARY `[VERIFIED]`

After a ~40-minute ACTIVE-for-`ops` soak, the operator **reverted to CANARY** (the ACTIVE
posture was judged premature). The live systemd drop-in now reads:

```
Environment=COMMS_GATEWAY_MODE=CANARY
Environment=COMMS_GATEWAY_CANARY_CLASSES=ops
Environment=COMMS_GATEWAY_CANARY_CHATS=6993102664,8797974247
```

Verified at `curl -s http://127.0.0.1:7777/api/v2/communications/health` →
`"mode": "CANARY"`, `"owned_classes": ["ops"]`, `"delivery_owned": true`.

## Decision

**This run’s decision:** **HOLD at CANARY** for class `ops` only (filtered to the two
operator chats). The earlier "PROMOTE toward ACTIVE" was walked back by the operator.

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
| 2 | 2026-09-05 | ops | f88853e89 | **REVERT to CANARY** | ACTIVE ~40 min soak judged premature; CANARY_CHATS=6993102664,8797974247; sample sends: `operator_alert`→SENT, `report`→LEGACY_DELIVERED (fail-closed) |
