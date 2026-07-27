"""Active Trader Stage 0 read API — health/status/sessions + Stage 1a venue eligibility."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .flags import Stage0Flags, load_flags

READ_API_CONTRACT = "active-trader-stage0-read-api-v1"
STAGE = 0

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Product intent venues (2026-07-27). Stage 0: inventory only — all live flags false.
VENUE_IDS = ("schwab", "moomoo", "alpaca")


def _load_compliance_fixtures() -> dict[str, Any]:
    """Read-only compliance/tradeability snapshot (fixture at Stage 1a). Prefers a live
    config file, falls back to the committed example, then to a minimal safe default.
    Never raises — returns {} at worst so eligibility fails closed to 'unknown'."""
    candidates = []
    env = os.environ.get("ACTIVE_TRADER_COMPLIANCE_FIXTURES", "").strip()
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(_REPO_ROOT / "config" / "active_trader_compliance_fixtures.json")
    candidates.append(_REPO_ROOT / "config" / "active_trader_compliance_fixtures.example.json")
    for p in candidates:
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def capability_snapshot(flags: Stage0Flags | None = None) -> dict[str, Any]:
    """Build the read-only capability snapshot the venue-eligibility evaluator consumes.

    Combines the venue inventory (roles) with the compliance fixtures (per-symbol Schwab
    blocks + venue availability / operator opt-in). All order/execution authority stays
    false — this only informs eligibility + the operator-prompt UX contract."""
    inv = venue_inventory(flags)
    fx = _load_compliance_fixtures()
    fx_venues = fx.get("venues") if isinstance(fx.get("venues"), Mapping) else {}
    venues: dict[str, Any] = {}
    for vid in VENUE_IDS:
        base = dict(inv.get(vid) or {})
        extra = fx_venues.get(vid) if isinstance(fx_venues.get(vid), Mapping) else {}
        # merge fixture availability/opt-in/coverage over the inventory role (no order auth)
        merged = {**base, **{k: v for k, v in extra.items() if k != "order_path"}}
        merged["order_path"] = False
        venues[vid] = merged
    compliance = fx.get("symbol_compliance") if isinstance(fx.get("symbol_compliance"), Mapping) else {}
    return {
        "venues": venues,
        "symbol_compliance": dict(compliance),
        "source": "fixtures" if fx else "empty",
        "read_only": True,
    }


def venue_inventory(flags: Stage0Flags | None = None) -> dict[str, dict[str, Any]]:
    """Read-only venue matrix. data/execution always false at Stage 0."""
    _ = flags
    out: dict[str, dict[str, Any]] = {}
    roles = {
        "schwab": "primary_execution_when_eligible",
        "moomoo": "augment_on_schwab_block_plus_l2_tape",
        "alpaca": "augment_execution_alternate",
    }
    for vid in VENUE_IDS:
        out[vid] = {
            "data": False,
            "execution": False,
            "read_only_inventory": True,
            "order_path": False,
            "role_intent": roles[vid],
        }
    return out


class ReadOnlyActiveTraderAPI:
    """Framework-neutral Stage 0 read surface. No create/update/delete/order methods."""

    def __init__(self, flags: Stage0Flags | None = None) -> None:
        self._flags = flags or load_flags()

    def health(self) -> dict[str, Any]:
        return {
            "contract": READ_API_CONTRACT,
            "stage": STAGE,
            "write": False,
            "canary": False,
            "read_only": True,
            "live_orders": False,
            "session_authorize": False,
            "venues": venue_inventory(self._flags),
            "ok": True,
            "product_intent": {
                "multi_broker": True,
                "schwab_primary": True,
                "operator_opt_in_required": True,
                "unattended_discover_and_fire": False,
            },
        }

    def status(self) -> dict[str, Any]:
        body = self.health()
        body["feature_flags"] = {
            k: bool(v) for k, v in self._flags.flags.items()
        }
        # Force hard offs even if misconfigured file somehow loaded (assert already ran)
        body["feature_flags"]["live_canary"] = False
        body["feature_flags"]["order_routes"] = False
        body["mode"] = "read_only_baseline"
        body["authority"] = {
            "mutation": False,
            "order": False,
            "session_authorize": False,
            "canary": False,
            "financial_action": False,
        }
        return body

    def list_sessions(self) -> dict[str, Any]:
        return {
            "contract": READ_API_CONTRACT,
            "stage": STAGE,
            "write": False,
            "canary": False,
            "sessions": [],
            "venues": venue_inventory(self._flags),
            "note": "Stage 0: no session schema yet; empty list is honest",
        }

    def venue_eligibility(self, symbol: str, proposed_venue: str | None = None) -> dict[str, Any]:
        """Stage 1a capability read: is `symbol` executable on `proposed_venue` (Schwab by
        default)? Read-only; on a Schwab compliance block it returns the block reason + an
        operator-prompt TEMPLATE and never auto-routes. Fail-closed to 'unknown'."""
        from .venue_eligibility import evaluate_eligibility, operator_prompt_required
        snap = capability_snapshot(self._flags)
        # proposed_venue None/"" -> evaluate_eligibility defaults to its SCHWAB product
        # constant (Schwab-primary contract); no venue string is hardcoded here.
        result = evaluate_eligibility(symbol, proposed_venue or "", snap)
        return {
            "contract": READ_API_CONTRACT,
            "stage": 1,
            "sub_stage": "1a",
            "write": False,
            "canary": False,
            "read_only": True,
            "auto_route": False,
            "capability_source": snap.get("source"),
            "eligibility": result.to_dict(),
            "operator_prompt": operator_prompt_required(result),
            "authority": {
                "mutation": False, "order": False, "session_authorize": False,
                "canary": False, "financial_action": False,
            },
        }
