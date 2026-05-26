# Designer Replacement: alert_routing_migration_patch

**Status:** DESIGN ONLY — requires phased migration  
**Git Baseline:** `c1286d314deb377df49713e1646f139db7f43643`  
**Created:** 2026-05-26  

## Problem

64 files call `send_telegram()` directly. 40 files reference `api.telegram.org` directly.
3 files use `bypass_router=True`. This creates:

1. **No central control** — any script can send unlimited Telegram messages
2. **No suppression** — duplicate/noisy alerts reach the operator
3. **No audit trail** — no record of what was sent, suppressed, or failed
4. **No rate limiting** — burst of alerts during incidents

The routing architecture has three layers:
- `telegram_alert.py:send_telegram()` — primary send function with optional router bypass
- `telegram_alert_router.py:should_send_telegram()` — rate limiting/dedup layer
- `telegram_alert_routing_policy.py` — policy rules (severity, cooldowns)

But most files import `send_telegram` from `telegram_alert.py` and some bypass even that
by calling `requests.post(f"https://api.telegram.org/bot{token}/sendMessage")` directly.

## Design Principle

This is a **phased migration**, not a single patch. P0.5 adds observability only.
Actual migration of direct senders happens in a future P1 package.

## P0.5 Changes (This Patch)

### 1. Add send audit log to `telegram_alert.py`

After every send attempt (success or suppressed), append to `logs/telegram_send_audit.jsonl`:

```python
import json
from datetime import datetime, timezone

def _audit_send(message: str, result: str, bypass: bool, caller: str = ""):
    """Append send audit event to JSONL log."""
    try:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "result": result,  # "sent", "suppressed", "failed", "bypass_sent"
            "bypass_router": bypass,
            "message_preview": message[:120],
            "caller": caller,
        }
        log_path = Path(__file__).resolve().parent.parent / "logs" / "telegram_send_audit.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass  # Audit must never break sending
```

Call `_audit_send()` in these locations within `send_telegram()`:
- After `_raw_send_telegram()` returns True: `_audit_send(message, "sent", bypass_router)`
- After `_raw_send_telegram()` returns False: `_audit_send(message, "failed", bypass_router)`
- After router suppresses: `_audit_send(message, "suppressed", bypass_router)`
- When bypass_router=True and send succeeds: `_audit_send(message, "bypass_sent", True)`

### 2. Add bypass_router inventory to `/api/v2/system-health`

Add a static inventory to the system health response:

```python
response["alert_routing"] = {
    "bypass_router_files": [
        "scripts/send_closed_trade_digest.py",
        "scripts/system_health_agent.py",
        "scripts/telegram_alert.py",
    ],
    "direct_telegram_sender_count": 64,
    "direct_api_telegram_count": 40,
    "audit_log": "logs/telegram_send_audit.jsonl",
    "migration_status": "P0.5_AUDIT_ONLY",
}
```

### 3. Add alert audit summary to SystemHealth.tsx

Show a small card in System Health dashboard:

```
Alert Routing Status: AUDIT ONLY
- 64 direct Telegram senders
- 3 bypass_router files
- Audit log: active
- Migration: P1 pending
```

## Future P1 Migration (NOT in this patch)

- Refactor all 40 direct `api.telegram.org` callers to use `send_telegram()`
- Add mandatory `caller=` parameter to `send_telegram()` for attribution
- Add per-caller rate limits to `telegram_alert_routing_policy.py`
- Migrate `bypass_router` callers to explicit P0 severity enum

## Testing

1. Trigger a known Telegram send (e.g., run alert_dispatcher_unified)
2. Check `logs/telegram_send_audit.jsonl` has the event
3. Verify `result` field shows "sent" or "suppressed"
4. Check `/api/v2/system-health` shows `alert_routing` block
5. Verify no change to actual message delivery behavior
