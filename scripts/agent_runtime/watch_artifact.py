from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .contracts import assert_no_secret_material, canonical_hash

WATCH_ARTIFACT_VERSION = "watch-artifact-v1"


class WatchArtifactError(ValueError):
    pass


_FORBIDDEN_AUTHORITY_KEYS = {
    "broker_action",
    "broker_request",
    "order_payload",
    "order_intent",
    "submit_order",
    "authorization",
    "authorization_token",
    "two_factor",
    "2fa",
    "totp",
    "credential",
    "credentials",
    "password",
    "private_key",
    "api_key",
    "secret",
    "secrets",
}


@dataclass(frozen=True)
class WatchProvenance:
    source_type: str
    source_ref: str
    source_hash: str
    observed_at: str
    adapter_version: str = WATCH_ARTIFACT_VERSION


@dataclass(frozen=True)
class WatchArtifact:
    artifact_key: str
    symbol: str
    state: str
    direction: str
    as_of: str
    input_hash: str
    validation_hash: str
    input_hash_origin: str
    validation_hash_origin: str
    mechanics: Mapping[str, Any]
    deterministic_validation: Mapping[str, Any]
    market_context: Mapping[str, Any]
    strategy_context: Mapping[str, Any]
    source_refs: tuple[str, ...]
    data_gaps: tuple[str, ...]
    provenance: WatchProvenance
    advisory_only: bool = True
    financial_authority: str = "DENIED"
    artifact_version: str = WATCH_ARTIFACT_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def artifact_hash(self) -> str:
        return canonical_hash(asdict(self))

    def validate(self) -> None:
        if not self.symbol or self.symbol == "UNKNOWN":
            raise WatchArtifactError("Watch artifact requires a symbol")
        if self.financial_authority != "DENIED" or not self.advisory_only:
            raise WatchArtifactError("Watch artifact must remain advisory with financial authority denied")
        for value, label in ((self.input_hash, "input_hash"), (self.validation_hash, "validation_hash"), (self.provenance.source_hash, "source_hash")):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value.lower()):
                raise WatchArtifactError(f"{label} must be sha256")
        if not self.source_refs:
            raise WatchArtifactError("at least one source reference is required")
        assert_no_secret_material(asdict(self))

    def sentinel_ticket(self) -> dict[str, Any]:
        """Return the exact deterministic surface consumed by Sentinel."""
        self.validate()
        return {
            "symbol": self.symbol,
            "state": self.state,
            "direction": self.direction,
            "as_of": self.as_of,
            "input_hash": self.input_hash,
            "validation_hash": self.validation_hash,
            "mechanics": dict(self.mechanics),
            "artifact_hash": self.artifact_hash,
            "source_refs": list(self.source_refs),
            "advisory_only": True,
            "financial_authority": "DENIED",
        }


@dataclass(frozen=True)
class WatchAdapterResult:
    artifact: WatchArtifact
    source_validation: Mapping[str, Any]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _state(value: Any, default: str = "UNKNOWN") -> str:
    normalized = _text(value).replace("-", "_").replace(" ", "_").upper()
    return normalized or default


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _path(value: Any, dotted: str) -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _first(value: Mapping[str, Any], paths: Sequence[str]) -> Any:
    for candidate in paths:
        resolved = _path(value, candidate)
        if resolved is not None and resolved != "":
            return resolved
    return None


def _first_mapping(value: Mapping[str, Any], paths: Sequence[str]) -> Mapping[str, Any]:
    resolved = _first(value, paths)
    return dict(resolved) if isinstance(resolved, Mapping) else {}


def _first_text(value: Mapping[str, Any], paths: Sequence[str], default: str = "") -> str:
    return _text(_first(value, paths)) or default


def _first_number(value: Mapping[str, Any], paths: Sequence[str]) -> float | None:
    return _number(_first(value, paths))


def _iso(value: Any, *, now: datetime) -> str:
    raw = _text(value)
    if not raw:
        return now.astimezone(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WatchArtifactError(f"invalid Watch as-of timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _valid_sha(value: Any) -> str | None:
    raw = _text(value).lower()
    if len(raw) == 64 and all(character in "0123456789abcdef" for character in raw):
        return raw
    return None


def _scan_authority(value: Any, path: str = "root") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _text(key).lower()
            if normalized in _FORBIDDEN_AUTHORITY_KEYS:
                findings.append(f"{path}.{key}")
            findings.extend(_scan_authority(child, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            findings.extend(_scan_authority(child, f"{path}[{index}]"))
    return findings


def _mechanics(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    packet = _first_mapping(raw, ["decision_packet"])
    mechanics = _first_mapping(
        raw,
        [
            "decision_packet.current_actionable_plan.mechanics",
            "decision_packet.current_mechanics",
            "decision_packet.selected_family.mechanics",
            "decision_packet.mechanics",
            "current_actionable_plan.mechanics",
            "selected_family.mechanics",
            "reentry_plan",
            "mechanics",
        ],
    )
    if not mechanics and packet:
        selected = packet.get("selected_family")
        if isinstance(selected, Mapping) and isinstance(selected.get("mechanics"), Mapping):
            mechanics = dict(selected["mechanics"])
    allowed: dict[str, Any] = {}
    aliases = {
        "entry": ("entry", "entry_price", "entry_limit"),
        "entry_low": ("entry_low", "entry_zone_low", "reentry_zone_low"),
        "entry_high": ("entry_high", "entry_zone_high", "reentry_zone_high"),
        "limit": ("limit", "limit_price", "entry_limit"),
        "stop": ("stop", "stop_price", "entry_stop", "reentry_stop"),
        "target": ("target", "target_price", "entry_target", "reentry_target"),
        "rr": ("rr", "risk_reward", "risk_reward_ratio"),
        "trigger": ("trigger",),
        "time_horizon": ("time_horizon", "horizon"),
        "direction": ("direction", "side"),
    }
    for target, candidates in aliases.items():
        for candidate in candidates:
            if candidate not in mechanics:
                continue
            value = mechanics[candidate]
            if target in {"entry", "entry_low", "entry_high", "limit", "stop", "target", "rr"}:
                numeric = _number(value)
                if numeric is not None:
                    allowed[target] = numeric
            elif _text(value):
                allowed[target] = _text(value)
            break
    return allowed


def _validation(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    validation = _first_mapping(
        raw,
        [
            "decision_packet.current_actionable_plan.ticket_validation",
            "decision_packet.ticket_validation",
            "current_actionable_plan.ticket_validation",
            "ticket_validation",
            "validation",
        ],
    )
    review = _first_mapping(raw, ["decision_packet.ticket_review", "ticket_review"])
    tickets = review.get("tickets_validated") if isinstance(review, Mapping) else None
    if not validation and isinstance(tickets, list) and tickets and isinstance(tickets[0], Mapping):
        validation = dict(tickets[0])
    state = _state(validation.get("state") or validation.get("verdict") or review.get("reconciled", {}).get("state") if isinstance(review.get("reconciled"), Mapping) else None, "NOT_RUN")
    failures = validation.get("hard_failures") or validation.get("failures") or []
    if not isinstance(failures, list):
        failures = [failures]
    proposal_allowed = validation.get("proposal_allowed")
    if proposal_allowed is None:
        proposal_allowed = state == "PASS"
    return {
        "state": state,
        "proposal_allowed": bool(proposal_allowed),
        "hard_failures": [str(item) for item in failures if _text(item)],
        "source": _first_text(raw, ["decision_packet.current_actionable_plan.ticket_validation.source", "ticket_validation.source"], "watch-source"),
    }


def _market_context(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    price = _first_number(raw, ["price", "last_price", "price_live", "current_price", "quote.last", "decision_packet.current_input_snapshot.price"])
    rsi = _first_number(raw, ["rsi", "rsi_14", "technical.rsi", "technicals.rsi", "decision_packet.current_input_snapshot.rsi"])
    resistance = _first_number(raw, ["resistance", "resistance_level", "decision_packet.selected_family.mechanics.resistance"])
    support = _first_number(raw, ["support", "support_level", "decision_packet.selected_family.mechanics.support"])
    return {
        "price": price,
        "rsi": rsi,
        "trend": _state(_first(raw, ["trend_state", "trend_direction", "technical_state.overall_direction", "decision_packet.technical_state.overall_direction"]), "UNAVAILABLE"),
        "resistance": resistance,
        "support": support,
        "regime": _state(_first(raw, ["regime", "regime_label", "decision_packet.regime"]), "UNAVAILABLE"),
    }


def _strategy_context(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    flags = _first(raw, ["flags", "strategy_flags", "portfolio_flags"])
    if isinstance(flags, Mapping):
        normalized_flags = sorted(_text(key).upper() for key, enabled in flags.items() if enabled)
    elif isinstance(flags, list):
        normalized_flags = sorted(_text(item).upper() for item in flags if _text(item))
    else:
        normalized_flags = []
    return {
        "recommendation": _state(_first(raw, ["synthesis_recommendation", "latest_recommendation", "recommendation"]), "UNAVAILABLE"),
        "sector": _first_text(raw, ["profile_sector", "sector"], ""),
        "catalyst": _first_text(raw, ["catalyst_headline", "catalyst"], ""),
        "earnings_date": _first_text(raw, ["earnings_date", "next_earnings_date"], ""),
        "flags": normalized_flags,
        "starred": bool(raw.get("starred")),
        "origin": _first_text(raw, ["origin_system", "source"], "watch"),
    }


def _source_refs(raw: Mapping[str, Any], symbol: str) -> tuple[str, ...]:
    refs = [
        _first_text(raw, ["watch_id", "id", "item_id", "directive_id"], ""),
        _first_text(raw, ["decision_packet.packet_id", "decision_packet.id"], ""),
        _first_text(raw, ["source_ref", "source_record_id"], ""),
    ]
    normalized = [f"watch:{symbol}"]
    normalized.extend(f"source:{value}" for value in refs if value)
    return tuple(dict.fromkeys(normalized))


def adapt_watch_item(raw: Mapping[str, Any], *, now: datetime | None = None) -> WatchAdapterResult:
    """Normalize one Watch row into a non-financial, hash-bound artifact."""
    if not isinstance(raw, Mapping):
        raise WatchArtifactError("Watch source must be a mapping")
    authority_paths = _scan_authority(raw)
    if authority_paths:
        raise WatchArtifactError(f"financial/secret authority material present: {', '.join(authority_paths)}")
    assert_no_secret_material(raw)

    current_time = now or datetime.now(timezone.utc)
    symbol = _first_text(raw, ["symbol", "ticker"], "UNKNOWN").upper()
    packet = _first_mapping(raw, ["decision_packet"])
    state = _state(
        _first(
            raw,
            [
                "decision_packet.current_actionable_plan.state",
                "decision_packet.state",
                "action_state",
                "decision_state",
                "state",
                "status",
            ],
        ),
        "UNKNOWN",
    )
    mechanics = _mechanics(raw)
    direction = _state(_first(raw, ["direction", "side", "decision_packet.direction", "decision_packet.selected_family.mechanics.direction"]), _state(mechanics.get("direction"), "LONG"))
    observed = _iso(_first(raw, ["decision_packet_at", "last_enriched_at", "computed_at", "as_of", "updated_at", "created_at"]), now=current_time)
    validation = _validation(raw)
    market = _market_context(raw)
    strategy = _strategy_context(raw)

    input_snapshot = _first_mapping(raw, ["decision_packet.current_input_snapshot", "current_input_snapshot", "input_snapshot"])
    if not input_snapshot:
        input_snapshot = {
            "symbol": symbol,
            "state": state,
            "direction": direction,
            "as_of": observed,
            "market_context": market,
            "strategy_context": strategy,
            "mechanics": mechanics,
        }
    existing_input_hash = _valid_sha(_first(raw, ["input_hash", "source_hash", "decision_packet.input_hash", "decision_packet.current_input_snapshot_hash"]))
    input_hash = existing_input_hash or canonical_hash(input_snapshot)
    input_hash_origin = "source" if existing_input_hash else "adapter-canonical-input-snapshot"

    existing_validation_hash = _valid_sha(_first(raw, ["validation_hash", "decision_packet.validation_hash", "decision_packet.current_actionable_plan.ticket_validation.hash", "ticket_validation.hash"]))
    validation_hash = existing_validation_hash or canonical_hash(validation)
    validation_hash_origin = "source" if existing_validation_hash else "adapter-canonical-validation"

    source_hash = canonical_hash(raw)
    refs = _source_refs(raw, symbol)
    gaps: list[str] = []
    if market.get("price") is None:
        gaps.append("price unavailable")
    if market.get("rsi") is None:
        gaps.append("rsi unavailable")
    if not strategy.get("sector"):
        gaps.append("sector unavailable")
    if not strategy.get("catalyst"):
        gaps.append("catalyst unavailable")
    if validation.get("state") in {"NOT_RUN", "UNAVAILABLE", "UNKNOWN"}:
        gaps.append("deterministic validation unavailable")
    if not mechanics:
        gaps.append("mechanics unavailable")

    source_ref = refs[1] if len(refs) > 1 else refs[0]
    artifact = WatchArtifact(
        artifact_key=f"watch:{symbol}:{source_hash[:16]}",
        symbol=symbol,
        state=state,
        direction=direction,
        as_of=observed,
        input_hash=input_hash,
        validation_hash=validation_hash,
        input_hash_origin=input_hash_origin,
        validation_hash_origin=validation_hash_origin,
        mechanics=mechanics,
        deterministic_validation=validation,
        market_context=market,
        strategy_context=strategy,
        source_refs=refs,
        data_gaps=tuple(gaps),
        provenance=WatchProvenance(
            source_type="watchlist-item",
            source_ref=source_ref,
            source_hash=source_hash,
            observed_at=observed,
        ),
    )
    artifact.validate()
    return WatchAdapterResult(artifact=artifact, source_validation=validation)
