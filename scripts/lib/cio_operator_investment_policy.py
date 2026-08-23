"""OperatorInvestmentPolicy@v1 projection and explicit ratification.

The projection reuses the hash-chained OperatorProfile store. Legacy configuration
is evidence of conflicting historical claims, not permission to select a mandate.
Only operator-confirmed fields can make the policy complete.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_operator_profile import OperatorProfile


AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "OperatorInvestmentPolicy@v1"
DEFAULT_STORE = "data/cio/operator_profile.jsonl"

FIELD_SPECS: dict[str, dict[str, Any]] = {
    "cash_target_range_pct": {"domain": "investment_policy_statement", "kind": "range_pct", "required": True},
    "minimum_liquidity_reserve_usd": {"domain": "cash_liquidity_needs", "kind": "money", "required": True},
    "investable_cash_definition": {"domain": "cash_liquidity_needs", "kind": "text", "required": True},
    "equity_range_pct": {"domain": "investment_policy_statement", "kind": "range_pct", "required": True},
    "fixed_income_range_pct": {"domain": "investment_policy_statement", "kind": "range_pct", "required": True},
    "alternatives_range_pct": {"domain": "investment_policy_statement", "kind": "range_pct", "required": True},
    "growth_objective": {"domain": "goals", "kind": "text", "required": True},
    "income_objective": {"domain": "income_needs", "kind": "text", "required": True},
    "capital_preservation_objective": {"domain": "goals", "kind": "text", "required": True},
    "time_horizon": {"domain": "time_horizon", "kind": "text", "required": True},
    "withdrawal_needs": {"domain": "cash_liquidity_needs", "kind": "text", "required": True},
    "future_known_cash_requirements": {"domain": "cash_liquidity_needs", "kind": "list", "required": True},
    "tax_constraints": {"domain": "tax_constraints", "kind": "list", "required": True},
    "account_location_constraints": {"domain": "account_constraints", "kind": "list", "required": True},
    "concentration_hierarchy": {"domain": "risk_constraints", "kind": "object", "required": True},
    "preferred_instruments": {"domain": "investment_policy_statement", "kind": "list", "required": True},
    "excluded_instruments": {"domain": "investment_policy_statement", "kind": "list", "required": True},
    "benchmark": {"domain": "investment_policy_statement", "kind": "text", "required": True},
    "sleeve_ranges_pct": {"domain": "investment_policy_statement", "kind": "object", "required": True},
    "risk_tolerance": {"domain": "risk_constraints", "kind": "text", "required": True},
}

CONFLICT_RESOLUTION_FIELD = {
    "cash_target_range_pct": "cash_target_range_pct",
    "max_single_position_pct": "concentration_hierarchy",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _nested(doc: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        value: Any = doc
        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if value is not None:
            return value
    return None


def _source_label(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return path.name


def discover_legacy_policy_claims(repo_root: Path) -> list[dict[str, Any]]:
    """Inventory material legacy claims without treating them as current policy."""
    claims: list[dict[str, Any]] = []
    ips_path = repo_root / "config" / "investment_policy_statement.json"
    ips = _read_json(ips_path)
    ips_max = _nested(ips, ("risk", "max_single_position_pct"), ("constraints", "max_single_position_pct"), ("max_single_position_pct",))
    if ips_max is not None:
        claims.append({"field": "max_single_position_pct", "value": ips_max, "source": _source_label(ips_path, repo_root), "status": "LEGACY_UNCONFIRMED"})

    model_path = repo_root / "config" / "model_portfolio.json"
    model = _read_json(model_path)
    model_max = _nested(model, ("risk_overlay", "max_single_position_var_pct"), ("max_single_position_var_pct",))
    if model_max is not None:
        claims.append({
            "field": "max_single_position_var_pct",
            "value": model_max,
            "source": _source_label(model_path, repo_root),
            "status": "LEGACY_UNCONFIRMED",
        })
    cash_allocation = _nested(model, ("strategic_allocation", "cash_and_equivalents"))
    if isinstance(cash_allocation, dict):
        claims.append({
            "field": "cash_target_range_pct",
            "value": {
                "min": cash_allocation.get("min_pct"),
                "target": cash_allocation.get("target_pct"),
                "max": cash_allocation.get("max_pct"),
            },
            "source": _source_label(model_path, repo_root),
            "status": "LEGACY_UNCONFIRMED",
        })

    situations_path = repo_root / "config" / "cio_situations.yaml"
    try:
        situations_text = situations_path.read_text(encoding="utf-8")
    except OSError:
        situations_text = ""
    match = re.search(r"^\s*cash_pct_band_min:\s*([0-9.]+)", situations_text, re.MULTILINE)
    if match:
        claims.append({
            "field": "cash_target_range_pct",
            "value": {"min": float(match.group(1)), "target": None, "max": None},
            "source": _source_label(situations_path, repo_root),
            "status": "LEGACY_UNCONFIRMED",
        })

    desk_path = repo_root / "config" / "advisory_desk.yaml"
    try:
        desk_text = desk_path.read_text(encoding="utf-8")
    except OSError:
        desk_text = ""
    match = re.search(r"max single position\s+([0-9.]+)%", desk_text, re.IGNORECASE)
    if match:
        claims.append({"field": "max_single_position_pct", "value": float(match.group(1)), "source": _source_label(desk_path, repo_root), "status": "LEGACY_UNCONFIRMED"})

    decision_path = repo_root / "scripts" / "lib" / "cio_decision_quality.py"
    try:
        decision_text = decision_path.read_text(encoding="utf-8")
    except OSError:
        decision_text = ""
    match = re.search(r"max_single_name_pct\s*=\s*([0-9.]+)", decision_text)
    if match:
        claims.append({
            "field": "max_single_position_pct",
            "value": float(match.group(1)),
            "source": _source_label(decision_path, repo_root),
            "status": "LEGACY_UNCONFIRMED",
        })
    return claims


def _validate_value(kind: str, value: Any) -> Any:
    if kind == "range_pct":
        if not isinstance(value, dict) or set(value) < {"min", "max"}:
            raise ValueError("range fields require {min, max}")
        low, high = float(value["min"]), float(value["max"])
        if not 0 <= low <= high <= 100:
            raise ValueError("percentage range must satisfy 0 <= min <= max <= 100")
        return {"min": low, "max": high}
    if kind == "money":
        amount = float(value)
        if amount < 0:
            raise ValueError("money value must be non-negative")
        return amount
    if kind == "text":
        text = str(value or "").strip()
        if not text:
            raise ValueError("text value must not be empty")
        return text
    if kind == "list":
        if not isinstance(value, list):
            raise ValueError("list value required")
        return value
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError("object value required")
        return value
    raise ValueError(f"unsupported policy value kind: {kind}")


def build_operator_investment_policy(
    *, store_path: str = DEFAULT_STORE, repo_root: Path | None = None
) -> dict[str, Any]:
    root = repo_root or Path(__file__).resolve().parents[2]
    store = OperatorProfile(store_path)
    fields: dict[str, Any] = {}
    missing: list[str] = []
    for name, spec in FIELD_SPECS.items():
        current = store.get_field(spec["domain"], name)
        if current and current.get("status") == "OPERATOR_CONFIRMED":
            fields[name] = {
                "value": current.get("value"),
                "source": current.get("source"),
                "confirmed_at": current.get("confirmed_at"),
                "operator_confirmed": True,
                "version": current.get("version", 1),
                "status": "OPERATOR_CONFIRMED",
                "kind": spec["kind"],
            }
        else:
            fields[name] = {
                "value": None,
                "source": current.get("source") if current else None,
                "confirmed_at": None,
                "operator_confirmed": False,
                "version": current.get("version", 0) if current else 0,
                "status": current.get("status", "POLICY_REQUIRED") if current else "POLICY_REQUIRED",
                "kind": spec["kind"],
            }
            if spec["required"]:
                missing.append(name)

    legacy_claims = discover_legacy_policy_claims(root)
    by_field: dict[str, set[str]] = {}
    for claim in legacy_claims:
        by_field.setdefault(claim["field"], set()).add(json.dumps(claim["value"], sort_keys=True))
    conflicts = []
    for field, values in sorted(by_field.items()):
        resolution_field = CONFLICT_RESOLUTION_FIELD.get(field, field)
        resolved = bool(fields.get(resolution_field, {}).get("operator_confirmed"))
        if len(values) > 1 and not resolved:
            conflicts.append({
                "field": field,
                "resolved_by": resolution_field,
                "status": "POLICY_REQUIRED",
                "claims": [c for c in legacy_claims if c["field"] == field],
            })
    confirmed = len(fields) - len(missing)
    payload = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "version": max((int(f.get("version") or 0) for f in fields.values()), default=0),
        "status": "CONFIRMED" if not missing and not conflicts else "POLICY_REQUIRED",
        "fields": fields,
        "confirmed_field_count": confirmed,
        "required_field_count": len(FIELD_SPECS),
        "missing_fields": missing,
        "legacy_conflicts": conflicts,
        "legacy_claims": legacy_claims,
        "generated_at": _now(),
    }
    payload["content_hash"] = hashlib.sha256(
        json.dumps({k: payload[k] for k in ("fields", "missing_fields", "legacy_conflicts")}, sort_keys=True).encode()
    ).hexdigest()
    return payload


def ratify_policy_field(
    field_name: str,
    value: Any,
    *,
    store_path: str = DEFAULT_STORE,
    actor: str = "operator",
    source: str = "command_center_policy_ratification",
) -> dict[str, Any]:
    spec = FIELD_SPECS.get(field_name)
    if not spec:
        raise ValueError(f"unknown policy field: {field_name}")
    normalized = _validate_value(spec["kind"], value)
    store = OperatorProfile(store_path)
    store.initialize()
    event = store.update_field(
        spec["domain"],
        field_name,
        normalized,
        source,
        actor=actor,
        actor_type="operator",
        confirmed_by_operator=True,
    )
    return {
        "ok": True,
        "schema": "OperatorPolicyRatificationReceipt@v1",
        "authority": AUTHORITY,
        "field_name": field_name,
        "value": normalized,
        "event_id": event["event_id"],
        "event_hash": event["event_hash"],
        "confirmed_at": event["occurred_at"],
        "financial_authority_changed": False,
    }
