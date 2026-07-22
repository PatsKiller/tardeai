#!/usr/bin/env python3
"""premium_ticket_review.py — operator-triggered paid expert critique (§6).

Fail-closed: nothing runs unless a registry provider is enabled=true AND its
credentials env var is present AND the operator supplies the exact typed
confirmation from the estimate. Never scheduled; one ticket at a time; actual
cost recorded. A premium PASS cannot override a deterministic failure.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

_CFG = PROJECT_ROOT / "config" / "premium_review_providers.yaml"


def _registry() -> list[dict]:
    try:
        import yaml
        return (yaml.safe_load(_CFG.read_text()) or {}).get("providers") or []
    except Exception:
        return []


def estimate(symbol: str, ticket_hash: str) -> dict:
    enabled = [p for p in _registry()
               if p.get("enabled") and os.getenv(p.get("credentials_env", ""), "")]
    if not enabled:
        cfg_only = [p for p in _registry() if p.get("enabled")]
        reason = ("provider enabled but credentials absent"
                  if cfg_only else "no provider enabled in premium_review_providers.yaml")
        return {"available": False, "reason": f"PREMIUM_NOT_CONFIGURED — {reason}",
                "providers_listed": [f"{p['provider']}/{p['model']}" for p in _registry()]}
    p = enabled[0]
    return {"available": True, "provider": p["provider"], "model": p["model"],
            "symbol": symbol, "ticket_hash": ticket_hash,
            "est_input_tokens": p["est_input_tokens"],
            "est_output_tokens": p["est_output_tokens"],
            "est_cost_usd": p["est_cost_usd"],
            "daily_budget_usd": p["daily_budget_usd"],
            "monthly_budget_usd": p["monthly_budget_usd"],
            "expected_latency_s": p["timeout_s"],
            "scope": "expert critique of the exact immutable ticket — no mechanics authority",
            "confirm_with": f"RUN PREMIUM REVIEW {symbol} {ticket_hash}"}


def run(symbol: str, ticket_hash: str, confirmation: str) -> dict:
    est = estimate(symbol, ticket_hash)
    if not est.get("available"):
        return {"ok": False, "error": est.get("reason")}
    want = est["confirm_with"]
    if confirmation != want:
        return {"ok": False, "error": f"explicit confirmation required — type exactly: {want!r}"}
    # Dispatch stub intentionally ends here until an operator enables a provider:
    # the registry ships disabled and this line is unreachable in that state.
    return {"ok": False, "error": "premium dispatch not yet implemented for the "
            "enabled provider — contact engineering before enabling"}
