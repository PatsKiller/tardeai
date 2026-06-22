"""SnapTrade transport — preview→place with audit (future broker-API path)."""
from __future__ import annotations

import json
from pathlib import Path

_CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "snaptrade_accounts.json"


def account_key_to_snaptrade_id(account_key: str) -> str | None:
    try:
        data = json.loads(_CONFIG.read_text())
        for sid, key in (data.get("accounts") or {}).items():
            if key == account_key:
                return sid
    except Exception:
        pass
    return None


def place_order(account_key: str, order_spec: dict, intent) -> dict:
    """Preview then place via SnapTrade SDK. Requires BROKER_API_ENABLED + per-order 2FA already consumed."""
    from brokers.execution_guard import require
    require(intent, "submit")
    from brokers import snaptrade_trade as st
    aid = account_key_to_snaptrade_id(account_key)
    if not aid:
        raise RuntimeError(f"no SnapTrade account_id mapped for {account_key!r}")
    ok, reasons = st.evaluate_envelope(
        account_key=account_key, action=order_spec.get("action", "SELL"),
        order_type=order_spec.get("order_type", "Stop"),
        units=order_spec.get("units"), price=order_spec.get("price"))
    if not ok:
        raise RuntimeError("; ".join(reasons))
    # universal_symbol_id must be resolved by caller in a full implementation
    raise RuntimeError("SnapTrade broker-API protective stops not live — Fidelity is read-only on SnapTrade. "
                       "Use monitored path (fidelity_monitored_stop) after operator approval.")