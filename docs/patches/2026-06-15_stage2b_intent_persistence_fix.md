# Stage 2b Schwab Pilot Hotfix — Intent Persistence Before Approval

Status: proposed hotfix. This document does not execute trades and does not widen the canary.

## Root cause

The database showed confirmed approvals for Stage 2b intent IDs, but `broker_order_intents` did not contain matching current intent rows and `schwab_pilot_orders` did not exist. Since `schwab_transport.place_order()` creates `schwab_pilot_orders` before contacting Schwab, the absence of that table means the flow stopped before the transport boundary.

The likely failure is: approval rows are created for an intent that the execute route later cannot reconstruct from `broker_order_intents`, or the approval expires before execute. This patch fixes the first issue by persisting the exact intent before approval rows are created.

## Safety posture

This does **not**:

- Change `CANARY_SYMBOL_ALLOWLIST`
- Change `CANARY_SESSION_DATE`
- Change max price / max qty / max notional
- Enable IRAs
- Bypass `execution_guard.require()`
- Bypass approval TTL
- Bypass pilot caps
- Call Schwab

It only makes the approval handoff durable so execute can reload the exact current preflight intent.

## Patch target

File:

```text
scripts/brokers/approval_service.py
```

## Patch

Add these imports near the top:

```python
import json
from dataclasses import asdict, is_dataclass
```

Add these helper functions after `_conn()`:

```python
def _json_safe(value):
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _intent_payload(intent) -> dict:
    try:
        payload = asdict(intent) if is_dataclass(intent) else dict(getattr(intent, "__dict__", {}))
    except Exception:
        payload = {}
    payload.setdefault("intent_id", str(getattr(intent, "intent_id", "")))
    payload.setdefault("correlation_id", str(getattr(intent, "correlation_id", "")))
    payload.setdefault("broker", getattr(intent, "broker", None))
    payload.setdefault("account_key", getattr(intent, "account_key", None))
    inst = getattr(intent, "instrument", None)
    payload.setdefault("instrument", {"symbol": getattr(inst, "symbol", None)})
    return json.loads(json.dumps(payload, default=_json_safe))


def _ensure_intent_persisted(cur, intent) -> None:
    iid = str(getattr(intent, "intent_id", "") or "").strip()
    if not iid:
        return
    corr = str(getattr(intent, "correlation_id", "") or "").strip() or None
    broker = getattr(intent, "broker", None) or "schwab"
    account_key = getattr(intent, "account_key", None)
    inst = getattr(intent, "instrument", None)
    symbol = (getattr(inst, "symbol", None) or "").strip().upper() or None
    payload = _intent_payload(intent)
    cur.execute("""
        INSERT INTO broker_order_intents
          (intent_id, correlation_id, broker, account_key, symbol, state, intent_json, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'PREFLIGHTED', %s::jsonb, NOW())
        ON CONFLICT (intent_id) DO UPDATE SET
          correlation_id = EXCLUDED.correlation_id,
          broker = EXCLUDED.broker,
          account_key = EXCLUDED.account_key,
          symbol = EXCLUDED.symbol,
          intent_json = EXCLUDED.intent_json,
          updated_at = NOW()
    """, (iid, corr, broker, account_key, symbol, json.dumps(payload, default=_json_safe)))
```

Then, inside `request_approval(intent)`, immediately after:

```python
conn = _conn(); cur = conn.cursor()
```

add:

```python
    _ensure_intent_persisted(cur, intent)
```

In the holder-refusal block, before returning, add rollback so the partial intent upsert does not commit when a different active approval is occupying the slot:

```python
        conn.rollback()
```

Finally, in the successful return object, add:

```python
"intent_persisted": True
```

## Validation

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate

python scripts/validate_schwab_write_policy.py

python -m py_compile scripts/brokers/approval_service.py
```

## Read-only post-patch check

Run a fresh Pilot Console preflight and request approval. Do not execute yet. Then run:

```bash
psql "$DATABASE_URL" -X -c "
select intent_id, state, broker, account_key, symbol, created_at, updated_at
from broker_order_intents
order by updated_at desc
limit 10;
"

psql "$DATABASE_URL" -X -c "
select intent_id, channel, status, confirmed_at, expires_at, expires_at > now() as still_valid
from trade_approvals
order by id desc
limit 12;
"
```

Pass condition: the newest `trade_approvals.intent_id` must exist in `broker_order_intents` with the same ID and `still_valid=true` before tapping execute.

## Operator sequence after patch

1. Arm pilot.
2. Run fresh preflight.
3. Request approval for that exact current preflight.
4. Confirm web or Telegram.
5. Verify the same intent ID exists in both `trade_approvals` and `broker_order_intents` and `still_valid=true`.
6. Only then tap execute.
