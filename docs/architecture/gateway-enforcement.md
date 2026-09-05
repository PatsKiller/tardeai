# Communications Gateway Enforcement (Phase 2)

**Status:** Static ratchets LIVE; runtime `require_event_id` helper LIVE (not yet wired into every adapter).  
**Goal:** Zero unauthorized provider egress. Ratchets may only shrink.

---

## Static controls (CI)

| Checker | Providers | Baseline |
|---|---|---|
| `scripts/check_telegram_chokepoint.py` | Telegram Bot API | `config/telegram_chokepoint_baseline.json` |
| `scripts/check_provider_chokepoint.py` | Slack, SMTP, Twilio, Meta WhatsApp | `config/provider_chokepoint_baseline.json` |
| `scripts/check_comms_gateway_enforcement.py` | Runs both | — |

Semantics (all ratchets):

- **NEW file** with forbidden behaviour → CI fail.
- **Existing file** may not grow violation count.
- Baseline may shrink; empty baseline = true zero.

### Approved adapters (non-Telegram)

| Channel | Approved path |
|---|---|
| Slack | `scripts/alerting.py` (`send_slack`) |
| SMTP | `scripts/alerting.py` (`send_email`) |
| Twilio WhatsApp | `scripts/alerting.py` (`send_whatsapp`) |
| Meta WhatsApp | `scripts/lib/cio_whatsapp_egress.py` (+ ingress/webhook) |

Producers must not call these providers directly. Long-term they must go through `publish_communication` → gateway transport (Phases 3–10).

### Telegram debt (honest)

Telegram ratchet still carries **~45 files / ~133 violations**. That is tracked release-blocker debt, not a pass claiming zero.

Provider ratchet after tooling allowlist: **near-zero** outside approved adapters (Slack/SMTP/Twilio already centralized in `alerting.py`).

---

## Runtime controls (in-process)

`scripts/lib/comms/enforcement.py`:

- `require_event_id(event_id, adapter=...)` — fail closed before provider I/O once adapters are wired.
- `assert_delivery_not_owned_in_off_or_shadow(...)` — OFF/SHADOW may not claim delivery ownership.

Phase 2 does **not** yet rewrite `telegram_transport.send_message` to require event_id (that would break legacy producers overnight). Wiring happens as producers migrate (Phase 5+) and ACTIVE cutover (Phase 11).

Network egress confinement (container/service account only) remains an ops task outside this PR.

---

## Tests

- `tests/test_telegram_chokepoint_ratchet.py` (existing)
- `tests/test_provider_chokepoint_ratchet.py`
- `tests/test_comms_enforcement_gate.py`

---

## Acceptance for ACTIVE (later)

Not Phase 2 complete criteria — ACTIVE gate still requires:

- Telegram baseline **empty**
- Provider baseline **empty**
- Runtime egress proof
- Zero bypass traffic observed
