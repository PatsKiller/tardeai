from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .contracts import canonical_hash


@dataclass(frozen=True)
class SentinelFinding:
    code: str
    severity: str
    message: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class SentinelReport:
    symbol: str
    verdict: str
    release_allowed: bool
    findings: tuple[SentinelFinding, ...]
    ticket_hash: str
    validation_hash: str
    checked_at: str
    kernel_version: str = "sentinel-integrity-v1"

    @property
    def report_hash(self) -> str:
        return canonical_hash(asdict(self))


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _state(value: Any) -> str:
    return _text(value).replace("-", "_").replace(" ", "_").upper()


def _mechanics(ticket: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("mechanics", "current_mechanics", "selected_mechanics"):
        value = ticket.get(key)
        if isinstance(value, Mapping):
            return value
    selected = ticket.get("selected_family")
    if isinstance(selected, Mapping) and isinstance(selected.get("mechanics"), Mapping):
        return selected["mechanics"]
    return {}


def _freshness_hours(value: Any, now: datetime) -> float | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() / 3600)


def inspect_ticket(
    ticket: Mapping[str, Any],
    deterministic_validation: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_hours: float = 24.0,
) -> SentinelReport:
    """Run the synchronous deterministic Sentinel kernel.

    The kernel can block or quarantine a reflective artifact. It cannot repair,
    release, submit, or mutate a ticket. A model is not involved.
    """

    current_time = now or datetime.now(timezone.utc)
    symbol = _text(ticket.get("symbol")).upper() or "UNKNOWN"
    findings: list[SentinelFinding] = []
    mechanics = _mechanics(ticket)
    state = _state(ticket.get("state") or ticket.get("action_state") or ticket.get("decision_state"))
    direction = _state(ticket.get("direction") or mechanics.get("direction") or "LONG")
    validation_state = _state(deterministic_validation.get("state") or deterministic_validation.get("verdict"))
    hard_failures = deterministic_validation.get("hard_failures") or deterministic_validation.get("failures") or []

    def add(code: str, severity: str, message: str, evidence: Mapping[str, Any]) -> None:
        findings.append(SentinelFinding(code=code, severity=severity, message=message, evidence=dict(evidence)))

    if validation_state in {"FAIL", "FAILED", "REJECT", "REJECTED", "BLOCK", "BLOCKED"} or hard_failures:
        add("DETERMINISTIC_FAILURE_SOVEREIGN", "BLOCK", "Deterministic validation failed; no reflective result may release this ticket.", {"validation_state": validation_state, "hard_failures": list(hard_failures)})

    if not _text(ticket.get("symbol")):
        add("MISSING_SYMBOL", "BLOCK", "Ticket identity is missing.", {})

    validation_hash = _text(ticket.get("validation_hash") or deterministic_validation.get("validation_hash") or deterministic_validation.get("hash"))
    if len(validation_hash) != 64 or any(character not in "0123456789abcdef" for character in validation_hash.lower()):
        add("MISSING_VALIDATION_HASH", "BLOCK", "Ticket is not bound to a SHA-256 deterministic-validation artifact.", {"validation_hash": validation_hash or None})

    input_hash = _text(ticket.get("input_hash") or ticket.get("source_hash"))
    if len(input_hash) != 64 or any(character not in "0123456789abcdef" for character in input_hash.lower()):
        add("MISSING_INPUT_HASH", "BLOCK", "Ticket is not bound to a SHA-256 input artifact.", {"input_hash": input_hash or None})

    as_of = ticket.get("as_of") or ticket.get("computed_at") or ticket.get("generated_at")
    age_hours = _freshness_hours(as_of, current_time)
    if age_hours is None:
        add("FRESHNESS_UNPROVEN", "BLOCK", "Ticket freshness cannot be proven.", {"as_of": as_of})
    elif age_hours > max_age_hours:
        add("STALE_TICKET", "BLOCK", "Ticket exceeds the permitted evidence age.", {"age_hours": round(age_hours, 3), "max_age_hours": max_age_hours})

    terminal_states = {"BLOCKED", "REJECTED", "NO_TRADE", "UNAVAILABLE", "STALE", "REFRESH"}
    if state in terminal_states and mechanics:
        add("MECHANICS_EXPOSED_FOR_NONACTIONABLE_STATE", "BLOCK", "A blocked, rejected, no-trade, stale or refresh ticket must not expose current actionable mechanics.", {"state": state, "mechanic_keys": sorted(mechanics)})

    entry_low = _number(mechanics.get("entry_low") or mechanics.get("entry"))
    entry_high = _number(mechanics.get("entry_high") or mechanics.get("entry"))
    stop = _number(mechanics.get("stop") or mechanics.get("stop_price"))
    target = _number(mechanics.get("target") or mechanics.get("target_price"))
    limit = _number(mechanics.get("limit") or mechanics.get("limit_price"))

    if entry_low is not None and entry_high is not None and entry_low > entry_high:
        add("ENTRY_RANGE_REVERSED", "BLOCK", "Entry low exceeds entry high.", {"entry_low": entry_low, "entry_high": entry_high})

    entry_reference = entry_low if entry_low is not None else entry_high
    if direction in {"LONG", "BUY", "BULLISH"} and entry_reference is not None:
        if stop is not None and stop >= entry_reference:
            add("LONG_STOP_DIRECTION_INVALID", "BLOCK", "Long stop must remain below entry.", {"entry": entry_reference, "stop": stop})
        if target is not None and target <= entry_reference:
            add("LONG_TARGET_DIRECTION_INVALID", "BLOCK", "Long target must remain above entry.", {"entry": entry_reference, "target": target})
    if direction in {"SHORT", "SELL", "BEARISH"} and entry_reference is not None:
        if stop is not None and stop <= entry_reference:
            add("SHORT_STOP_DIRECTION_INVALID", "BLOCK", "Short stop must remain above entry.", {"entry": entry_reference, "stop": stop})
        if target is not None and target >= entry_reference:
            add("SHORT_TARGET_DIRECTION_INVALID", "BLOCK", "Short target must remain below entry.", {"entry": entry_reference, "target": target})

    if limit is not None and entry_low is not None and entry_high is not None and not entry_low <= limit <= entry_high:
        add("LIMIT_OUTSIDE_ENTRY_RANGE", "BLOCK", "Limit price falls outside the declared entry range.", {"entry_low": entry_low, "entry_high": entry_high, "limit": limit})

    rr = _number(mechanics.get("rr") or mechanics.get("risk_reward") or mechanics.get("risk_reward_ratio"))
    if rr is not None and rr <= 0:
        add("NONPOSITIVE_RISK_REWARD", "BLOCK", "Risk/reward must be positive.", {"risk_reward": rr})

    proposal_allowed = bool(deterministic_validation.get("proposal_allowed", validation_state == "PASS"))
    if state in terminal_states and proposal_allowed:
        add("PROPOSAL_ALLOWED_STATE_CONTRADICTION", "BLOCK", "Deterministic proposal permission contradicts the ticket state.", {"state": state, "proposal_allowed": proposal_allowed})

    if ticket.get("broker_action") or ticket.get("order_payload") or ticket.get("authorization") or ticket.get("two_factor"):
        add("FINANCIAL_AUTHORITY_IN_REFLECTIVE_TICKET", "QUARANTINE", "Reflective ticket contains broker/order/authorization material and must be quarantined.", {"present": [key for key in ("broker_action", "order_payload", "authorization", "two_factor") if ticket.get(key)]})

    severities = {finding.severity for finding in findings}
    release_allowed = not severities.intersection({"BLOCK", "QUARANTINE"}) and validation_state == "PASS" and proposal_allowed
    verdict = "PASS" if release_allowed else "QUARANTINE" if "QUARANTINE" in severities else "BLOCK"
    return SentinelReport(
        symbol=symbol,
        verdict=verdict,
        release_allowed=release_allowed,
        findings=tuple(findings),
        ticket_hash=canonical_hash(ticket),
        validation_hash=canonical_hash(deterministic_validation),
        checked_at=current_time.astimezone(timezone.utc).isoformat(),
    )


def finding_codes(report: SentinelReport) -> set[str]:
    return {finding.code for finding in report.findings}


def inspect_population(rows: Sequence[Mapping[str, Any]], validations: Mapping[str, Mapping[str, Any]], *, now: datetime | None = None) -> list[SentinelReport]:
    return [inspect_ticket(row, validations.get(_text(row.get("symbol")).upper(), {}), now=now) for row in rows]
