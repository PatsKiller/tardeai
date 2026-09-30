"""Cross-asset decision intelligence primitives.

This module is deliberately pure and broker-free.  It creates a canonical,
versioned comparison envelope for an equity signal and the option structures
that are appropriate to compare against it.  It does not price contracts,
size positions, approve proposals, or submit orders.

Contract: SymbolDecisionObject@v1
Authority: READ_ONLY_ADVISORY
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "SymbolDecisionObject@v1"
EVENT_SCHEMA = "CrossAssetDecisionEvent@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

SIGNALS = (
    "BUY", "STRONG_BUY", "ADD", "ADD_ON_PULLBACK", "REENTRY", "ENTRY_NEAR",
    "UPGRADE", "CONVICTION", "HOLD", "MONITOR", "HEDGE", "SELL", "TRIM",
    "REDUCE", "EXIT",
)

# Candidate names are policy vocabulary, not executable order instructions.
EXPRESSION_MATRIX: dict[str, tuple[str, ...]] = {
    "BUY": ("shares", "cash_secured_put", "long_call", "bull_call_spread"),
    "STRONG_BUY": ("shares", "cash_secured_put", "long_call", "bull_call_spread"),
    "ADD": ("shares", "covered_call", "bull_call_spread"),
    "ADD_ON_PULLBACK": ("shares", "cash_secured_put", "bull_call_spread"),
    "REENTRY": ("shares", "cash_secured_put", "bull_call_spread"),
    "ENTRY_NEAR": ("shares", "long_call", "bull_call_spread"),
    "UPGRADE": ("shares", "cash_secured_put", "long_call", "bull_call_spread"),
    "CONVICTION": ("shares", "cash_secured_put", "long_call", "credit_spread"),
    "HOLD": ("shares", "covered_call", "protective_put", "collar"),
    "MONITOR": ("no_action", "put_spread", "defined_risk_entry"),
    "HEDGE": ("protective_put", "put_spread", "collar"),
    "SELL": ("sell_shares", "collar", "protective_put"),
    "TRIM": ("trim_shares", "covered_call", "collar"),
    "REDUCE": ("reduce_shares", "collar", "protective_put"),
    "EXIT": ("sell_shares", "no_action", "protective_put"),
}

HARD_BLOCKS = frozenset({
    "LIQUIDITY", "OPEN_INTEREST", "SPREAD", "EARNINGS", "QUOTE_STALE",
    "CONTRACT_UNAVAILABLE", "POSITION_SIZE",
})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    """Return a stable SHA-256 digest for an event or projection payload."""
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def normalize_signal(signal: str) -> str:
    normalized = str(signal or "").strip().upper().replace(" ", "_")
    if normalized not in SIGNALS:
        raise ValueError(f"unsupported_signal:{normalized or 'EMPTY'}")
    return normalized


def normalize_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    symbol = str(identity.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("identity_missing_symbol")
    security_guid = identity.get("security_guid")
    status = str(identity.get("identity_status") or ("CONFIRMED" if security_guid else "UNRESOLVED"))
    if status not in {"CONFIRMED", "UNRESOLVED", "CONFLICTED"}:
        raise ValueError(f"identity_invalid_status:{status}")
    return {
        "symbol": symbol,
        "security_guid": str(security_guid) if security_guid else None,
        "share_class": identity.get("share_class") or "common",
        "issuer_guid": identity.get("issuer_guid"),
        "identity_status": status,
        "source_refs": list(identity.get("source_refs") or []),
        "as_of": identity.get("as_of") or _now(),
    }


def candidate_expressions(signal: str, *, held: bool = False, shares: float = 0) -> list[str]:
    """Return comparison candidates; never returns an executable instruction."""
    normalized = normalize_signal(signal)
    candidates = list(EXPRESSION_MATRIX[normalized])
    if not held and "covered_call" in candidates:
        candidates.remove("covered_call")
    if shares < 100 and "covered_call" in candidates:
        candidates.remove("covered_call")
    return candidates


def build_event(
    *, symbol: str, signal: str, source: str, payload: Mapping[str, Any] | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic, immutable input event."""
    normalized_signal = normalize_signal(signal)
    body = {
        "schema": EVENT_SCHEMA,
        "symbol": str(symbol or "").strip().upper(),
        "signal": normalized_signal,
        "source": str(source or "unknown"),
        "payload": dict(payload or {}),
        "observed_at": observed_at or _now(),
    }
    if not body["symbol"]:
        raise ValueError("event_missing_symbol")
    body["event_id"] = "evt_" + digest(body)[:24]
    return body


def build_decision_object(
    *, event: Mapping[str, Any], identity: Mapping[str, Any], thesis: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None, position: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None, cio: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a canonical comparison envelope from source facts."""
    if event.get("schema") != EVENT_SCHEMA:
        raise ValueError("event_schema_required")
    normalized_identity = normalize_identity(identity)
    if normalized_identity["symbol"] != str(event.get("symbol") or "").upper():
        raise ValueError("identity_symbol_mismatch")
    position = dict(position or {})
    signal = normalize_signal(str(event["signal"]))
    candidates = candidate_expressions(
        signal,
        held=bool(position.get("held")),
        shares=float(position.get("shares") or 0),
    )
    obj = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "evaluation_id": "eval_" + digest({"event_id": event["event_id"], "identity": normalized_identity})[:24],
        "as_of": event.get("observed_at") or _now(),
        "identity": normalized_identity,
        "equity_thesis": dict(thesis or {}),
        "research_state": dict(research or {}),
        "event_state": {"trigger": event.get("source"), "payload": dict(event.get("payload") or {})},
        "signal_state": {"action": signal, "source": event.get("source"), "event_id": event["event_id"]},
        "position_state": position,
        "options_state": dict(options or {}),
        "cio_state": dict(cio or {}),
        "historical_state": {"source_refs": []},
        "expression_comparison": {
            "candidates": [{"structure": name, "state": "UNSCORED"} for name in candidates],
            "winner": None,
            "decision": "SHADOW_ONLY",
            "why": "Candidates require current market facts and policy evaluation.",
        },
        "audit_history": [{"event_id": event["event_id"], "event_digest": digest(event)}],
    }
    obj["object_digest"] = digest(obj)
    return obj


def validate_decision_object(obj: Mapping[str, Any]) -> list[str]:
    required = {
        "schema", "authority", "financial_action", "evaluation_id", "as_of", "identity",
        "equity_thesis", "research_state", "event_state", "signal_state", "position_state",
        "options_state", "cio_state", "historical_state", "expression_comparison", "audit_history",
    }
    errors = [f"missing:{key}" for key in sorted(required) if key not in obj]
    if obj.get("schema") != SCHEMA:
        errors.append("schema_mismatch")
    if obj.get("authority") != AUTHORITY:
        errors.append("authority_mismatch")
    if obj.get("financial_action") is not False:
        errors.append("financial_action_must_be_false")
    try:
        normalize_identity(obj.get("identity") or {})
    except ValueError as exc:
        errors.append(str(exc))
    try:
        normalize_signal((obj.get("signal_state") or {}).get("action"))
    except ValueError as exc:
        errors.append(str(exc))
    if not (obj.get("audit_history") or []):
        errors.append("audit_history_empty")
    return errors


class AppendOnlyDecisionStore:
    """Small JSONL shadow store for local tests and shadow mode.

    This class never resolves a production path and never overwrites a row.
    Callers must pass an explicit path; production integration is a later phase.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, obj: Mapping[str, Any]) -> str:
        errors = validate_decision_object(obj)
        if errors:
            raise ValueError("invalid_decision_object:" + ",".join(errors))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing_ids: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    existing_ids.add(str(json.loads(line).get("evaluation_id") or ""))
        evaluation_id = str(obj["evaluation_id"])
        if evaluation_id in existing_ids:
            return "DUPLICATE_IGNORED"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(dict(obj)) + "\n")
        return "APPENDED"

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


def coverage_row(obj: Mapping[str, Any]) -> dict[str, Any]:
    """Produce a reconciliation row for the missed-opportunity ledger."""
    comparison = obj.get("expression_comparison") or {}
    candidates = comparison.get("candidates") or []
    return {
        "evaluation_id": obj.get("evaluation_id"),
        "symbol": (obj.get("identity") or {}).get("symbol"),
        "signal": (obj.get("signal_state") or {}).get("action"),
        "expected_count": len(candidates),
        "generated_count": len(candidates),
        "missing": [],
        "state": "COVERED" if candidates else "MISSING_COMPARISON",
        "as_of": obj.get("as_of"),
    }


def link_symbol_sources(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Join source records by symbol without silently resolving conflicts."""
    joined: dict[str, dict[str, Any]] = {}
    for record in records:
        symbol = str(record.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        row = joined.setdefault(symbol, {"symbol": symbol, "sources": [], "conflicts": []})
        row["sources"].append({
            "source": record.get("source") or "unknown",
            "source_id": record.get("source_id"),
            "as_of": record.get("as_of"),
        })
        for field in ("security_guid", "signal", "stance", "thesis_version"):
            value = record.get(field)
            if value in (None, ""):
                continue
            prior = row.get(field)
            if prior not in (None, "", value):
                row["conflicts"].append({"field": field, "prior": prior, "new": value})
                row["identity_status"] = "CONFLICTED"
            elif prior in (None, ""):
                row[field] = value
    for row in joined.values():
        row.setdefault("identity_status", "CONFIRMED" if row.get("security_guid") else "UNRESOLVED")
    return joined


def _fact_blockers(facts: Mapping[str, Any]) -> list[str]:
    blocks: list[str] = []
    if facts.get("contract_available") is False:
        blocks.append("CONTRACT_UNAVAILABLE")
    if facts.get("quote_age_minutes") is not None and float(facts["quote_age_minutes"]) > 30:
        blocks.append("QUOTE_STALE")
    if facts.get("liquid") is False:
        blocks.append("LIQUIDITY")
    if facts.get("open_interest") is not None and float(facts["open_interest"]) < 50:
        blocks.append("OPEN_INTEREST")
    if facts.get("spread_pct") is not None and float(facts["spread_pct"]) > 12:
        blocks.append("SPREAD")
    if facts.get("earnings_before_expiry") is True:
        blocks.append("EARNINGS")
    if facts.get("position_size_ok") is False:
        blocks.append("POSITION_SIZE")
    return blocks


def evaluate_expressions(
    obj: Mapping[str, Any], facts_by_structure: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply hard facts to candidates; no pricing or order side effects occur."""
    rows: list[dict[str, Any]] = []
    for candidate in (obj.get("expression_comparison") or {}).get("candidates") or []:
        structure = str(candidate.get("structure") or "")
        facts = dict(facts_by_structure.get(structure) or {})
        blockers = _fact_blockers(facts) if structure not in {
            "shares", "sell_shares", "trim_shares", "reduce_shares", "no_action"
        } else []
        if facts.get("thesis_complete") is False:
            blockers.append("THESIS_INCOMPLETE")
        if facts.get("cio_approved") is False and facts.get("cio_required") is True:
            blockers.append("CIO_REVIEW")
        expected_return = facts.get("expected_return")
        capital = facts.get("capital_required")
        risk = facts.get("maximum_risk")
        score = facts.get("score")
        if score is None and expected_return is not None and capital not in (None, 0):
            score = round(float(expected_return) / abs(float(capital)) * 100, 6)
        rows.append({
            "structure": structure,
            "state": "BLOCKED" if blockers else ("SCORED" if score is not None else "UNSCORED"),
            "blockers": list(dict.fromkeys(blockers)),
            "score": score,
            "expected_return": expected_return,
            "capital_required": capital,
            "maximum_risk": risk,
            "facts_as_of": facts.get("as_of"),
        })
    ranked = sorted(
        (row for row in rows if row["state"] == "SCORED"),
        key=lambda row: float(row["score"]), reverse=True,
    )
    winner = ranked[0]["structure"] if ranked else None
    return {
        "candidates": rows,
        "winner": winner,
        "decision": "SHADOW_RECOMMENDATION" if winner else "NO_WINNER",
        "why": "Highest supplied score among unblocked candidates." if winner else "No unblocked scored candidate.",
    }


def apply_expression_evaluation(
    obj: Mapping[str, Any], facts_by_structure: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a copied object with a computed comparison and refreshed digest."""
    updated = json.loads(json.dumps(obj))
    updated["expression_comparison"] = evaluate_expressions(updated, facts_by_structure)
    updated["object_digest"] = digest(updated)
    return updated


def replay_events(
    events: Iterable[Mapping[str, Any]], *, identity_by_symbol: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Replay frozen events in timestamp order without looking ahead."""
    ordered = sorted(events, key=lambda row: (str(row.get("observed_at") or ""), str(row.get("event_id") or "")))
    output: list[dict[str, Any]] = []
    for event in ordered:
        symbol = str(event.get("symbol") or "").upper()
        identity = identity_by_symbol.get(symbol)
        if identity is None:
            raise ValueError(f"replay_identity_missing:{symbol}")
        output.append(build_decision_object(event=event, identity=identity))
    return output


def run_shadow(
    events: Iterable[Mapping[str, Any]], *, identity_by_symbol: Mapping[str, Mapping[str, Any]],
    store: AppendOnlyDecisionStore,
) -> dict[str, Any]:
    """Run a frozen event batch in shadow mode and persist only advisory rows."""
    decisions = replay_events(events, identity_by_symbol=identity_by_symbol)
    appended = 0
    duplicates = 0
    coverage: list[dict[str, Any]] = []
    for decision in decisions:
        result = store.append(decision)
        appended += result == "APPENDED"
        duplicates += result == "DUPLICATE_IGNORED"
        coverage.append(coverage_row(decision))
    return {
        "schema": "CrossAssetShadowReceipt@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "events": len(decisions),
        "appended": appended,
        "duplicates": duplicates,
        "coverage": coverage,
        "state": "SHADOW_ONLY",
    }


__all__ = [
    "AppendOnlyDecisionStore", "AUTHORITY", "EXPRESSION_MATRIX", "SCHEMA", "SIGNALS",
    "apply_expression_evaluation", "build_decision_object", "build_event",
    "candidate_expressions", "coverage_row", "digest", "evaluate_expressions",
    "link_symbol_sources", "normalize_identity", "normalize_signal", "replay_events", "run_shadow",
    "validate_decision_object",
]
