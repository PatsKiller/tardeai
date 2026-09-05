# Gateway Channel Adapters — Phase 10

**Status:** Phase 10 implemented (typed client). **Default does not send.**  
**Code:** `scripts/lib/comms/channel_adapters.py`  
**Public API:** `send_via_gateway` (exported from `scripts.lib.comms`)  
**Gateway mode env:** `COMMS_GATEWAY_MODE` = `OFF` (default) \| `SHADOW` \| `CANARY` \| `ACTIVE`

---

## Purpose

Producers call a single typed gateway client for non-Telegram channels so that:

1. A `CommunicationEvent@v2` is minted via `publish_communication`
2. A `ChannelDelivery@v1` stub is reserved
3. Provider send happens **only** when `deliver=True` **and** mode is `CANARY` or `ACTIVE`
4. Delivery is settled `SENT` / `FAILED` when a send is attempted
5. `require_event_id` runs before any real provider call

Default `deliver=False` is SHADOW/record-only: ledger + reservation, **no network**.

---

## Supported channels

| Channel key | Underlying approved adapter |
|---|---|
| `email` | `scripts.alerting.send_email` |
| `slack` | `scripts.alerting.send_slack` |
| `whatsapp_twilio` | `scripts.alerting.send_whatsapp` |
| `whatsapp_meta` | `scripts.lib.cio_whatsapp_egress.send_whatsapp_text` (optional) |

Lazy imports keep the gateway package free of Twilio/SMTP/requests load until a real send path runs.

Telegram remains on its own transport / Phase 9 chokepoint track. This module does **not** touch the Telegram baseline.

---

## API

```python
from scripts.lib.comms import send_via_gateway

result = send_via_gateway(
    "email",
    body="…",
    subject="…",          # email
    producer="ops.watchdog",
    subject_key="system:watchdog",
    event_type="operator_message",
    message_class="operator_alert",
    retention_class="operational_30d",
    deliver=False,        # default — record only
)
```

Extra kwargs (forwarded on deliver):

- email: `html`, `attachments`
- whatsapp_meta: `to_wa_id` / `to`, `reply_to`, `dry_run`, `http_post`, …

### Return shape (dict)

| Field | Meaning |
|---|---|
| `ok` | Publish succeeded (and send succeeded when deliver attempted) |
| `event_id` | Ledger identity |
| `delivery_id` / `delivery_ids` | Reserved attempt id(s) |
| `delivery_owned` | `True` only when deliver was allowed and gateway attempted send |
| `delivered` | `True` only after a successful provider send |
| `gateway_mode` | Mode observed at call time |
| `error` | e.g. `delivery_blocked_mode`, `unsupported_channel`, `publish_failed` |

---

## Mode semantics

| Mode | `deliver=False` | `deliver=True` |
|---|---|---|
| OFF / SHADOW | Publish + reserve | **Refused** — `error=delivery_blocked_mode`; no provider I/O |
| CANARY / ACTIVE | Publish + reserve | `require_event_id` → approved adapter → `settle_delivery` SENT/FAILED |

`COMMS_GATEWAY_MODE` stays **OFF by default**. Phase 10 does not flip ACTIVE.

---

## Non-goals

- Enabling ACTIVE by default
- Migrating all legacy `alerting.send_*` callers (adoption is gradual)
- Telegram chokepoint baseline edits (Phase 9)
- CommunicationsHub UI changes
- Network calls from unit tests (adapters are monkeypatched)

---

## Tests

`tests/test_comms_channel_adapters.py` — default record-only, OFF deliver blocked, ACTIVE settles SENT, `require_event_id` gate, meta optional path, unsupported channel.
