"""Audit persistence for broker order intents (ADR-B2 §audit). Append-only state events."""
from __future__ import annotations

import json


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def save_intent(intent, validation=None, translation=None, capability_notes=None,
                state=None, blocked_reason=None):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO broker_order_intents
        (intent_id, correlation_id, broker, account_key, symbol, state, intent_json, validation_json,
         translation_json, capability_json, blocked_reason)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (intent_id) DO UPDATE SET
          state=EXCLUDED.state, intent_json=EXCLUDED.intent_json, validation_json=EXCLUDED.validation_json,
          translation_json=EXCLUDED.translation_json, capability_json=EXCLUDED.capability_json,
          blocked_reason=EXCLUDED.blocked_reason, updated_at=NOW()""",
        (intent.intent_id, intent.correlation_id, intent.broker, intent.account_key,
         intent.instrument.symbol, (state or intent.state.value), json.dumps(intent.to_dict()),
         json.dumps(validation or {}), json.dumps(translation or {}),
         json.dumps(capability_notes or []), blocked_reason))
    cur.execute("""INSERT INTO intent_state_events (intent_id, correlation_id, event, detail)
                   VALUES (%s,%s,%s,%s)""",
                (intent.intent_id, intent.correlation_id, f"state:{state or intent.state.value}",
                 blocked_reason or ""))
    conn.commit()


def record_guard_decision(intent, action, decision):
    conn = _conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO intent_state_events (intent_id, correlation_id, event, detail)
                   VALUES (%s,%s,%s,%s)""",
                (intent.intent_id, intent.correlation_id,
                 f"guard:{action}:{'ALLOW' if decision.allowed else 'BLOCK'}:{decision.mode.value}",
                 decision.reason))
    conn.commit()


def load_drafts(broker=None, limit=50):
    conn = _conn(); cur = conn.cursor()
    q = """SELECT intent_id, broker, symbol, state, intent_json, validation_json, translation_json,
                  capability_json, blocked_reason, updated_at
           FROM broker_order_intents"""
    args = []
    if broker:
        q += " WHERE broker=%s"; args.append(broker)
    q += " ORDER BY updated_at DESC LIMIT %s"; args.append(limit)
    cur.execute(q, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
