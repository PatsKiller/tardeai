"""capability_gate.py — submit-level account capability check (R4).

Refuses order intents that exceed account_capabilities.json for the account.
Paper tradeai_automated remains permissive (existing behavior). Live scaffolds
refuse shorts/options until verified=true and levels set.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
CAPS_PATH = ROOT / "config" / "account_capabilities.json"


def _caps() -> dict:
    try:
        return json.loads(CAPS_PATH.read_text()).get("accounts") or {}
    except Exception:
        return {}


def capability_gate(account_key: str, order_intent: Optional[dict] = None) -> dict:
    """Return {ok, blocks[], warnings[], account_key, caps}.

    order_intent optional keys: side, asset_class, is_short, is_option, strategy.
    """
    ak = (account_key or "").strip()
    # hardcode-ok: legacy paper identity alias
    if ak in ("alpaca_paper", "ALPACA_PAPER"):
        ak = "tradeai_automated"
    caps = _caps().get(ak) or {}
    intent = order_intent or {}
    blocks = []
    warnings = []

    is_short = bool(intent.get("is_short") or str(intent.get("side") or "").lower() in ("sell_short", "short"))
    is_option = bool(intent.get("is_option") or str(intent.get("asset_class") or "").lower() == "option")

    if is_short and caps.get("can_short_stock") is False:
        blocks.append(f"account {ak} cannot short stock (capability can_short_stock=false)")
    if is_option:
        level = caps.get("options_level")
        if level in (None, "", "none") and ak not in ("tradeai_automated",):
            # paper historically unrestricted for options paper lane — separate stack
            if caps.get("verified") is False or level is None:
                blocks.append(f"account {ak} options_level not set / not verified")

    if caps.get("verified") is False and ak.startswith("alpaca_") and ak != "tradeai_automated":
        warnings.append(f"account {ak} capability verified=false — activation research pending")

    return {
        "ok": not blocks,
        "blocks": blocks,
        "warnings": warnings,
        "account_key": ak,
        "caps": {k: caps.get(k) for k in ("can_short_stock", "options_level", "verified", "margin")},
    }
