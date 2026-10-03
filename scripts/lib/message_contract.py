"""Canonical operator-message contract, registry, renderer, and safe adapter.

This module is deliberately independent of Telegram transport.  Producers may still
hand the system text while they migrate, but text is classified here before routing or
rendering.  A model can be attached to :func:`record_shadow_proposal`; that function
only records advice and never participates in classification, routing, or delivery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

CONTRACT_VERSION = "MessageEnvelope@v1"
REGISTRY_VERSION = "telegram-formatting-registry@v1"
RENDERER_VERSION = "telegram-card-renderer@v1"
MAX_TELEGRAM_UTF16 = 4096
SEVERITIES = frozenset({"info", "notice", "warning", "urgent", "critical"})
ROUTES = frozenset({"IMMEDIATE", "DIGEST", "COMMAND_CENTER", "LOG"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _clean_symbols(values: Any) -> tuple[str, ...]:
    if isinstance(values, str):
        values = [values]
    result: list[str] = []
    for value in values or []:
        symbol = str(value or "").strip().lstrip("$").upper()
        if symbol and symbol.isalpha() and 1 <= len(symbol) <= 6 and symbol not in result:
            result.append(symbol)
    return tuple(result)


@dataclass(frozen=True)
class MessageEnvelope:
    message_type: str
    schema_version: str = CONTRACT_VERSION
    producer: str = "unknown"
    source_event_id: str | None = None
    primary_symbols: tuple[str, ...] = ()
    severity: str = "info"
    route_intent: str | None = None
    operator_action: str | None = None
    headline: str | None = None
    facts: Mapping[str, Any] = field(default_factory=dict)
    sections: tuple[tuple[str, tuple[str, ...]], ...] = ()
    evidence: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    sources: tuple[tuple[str, str], ...] = ()
    timestamps: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    data_completeness: str = "unknown"
    authority: str = "READ_ONLY_ADVISORY"
    dedupe_key: str | None = None
    raw_text: str | None = None
    classification_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "primary_symbols", _clean_symbols(self.primary_symbols))
        if self.severity not in SEVERITIES:
            raise ValueError(f"unsupported severity: {self.severity}")
        if self.route_intent is not None and self.route_intent not in ROUTES:
            raise ValueError(f"unsupported route: {self.route_intent}")
        if not self.dedupe_key:
            raw = "|".join((self.message_type, self.producer, *self.primary_symbols, self.raw_text or ""))
            object.__setattr__(self, "dedupe_key", hashlib.sha256(raw.encode()).hexdigest())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MessageEnvelope":
        sections: list[tuple[str, tuple[str, ...]]] = []
        for item in value.get("sections", ()) or ():
            if isinstance(item, Mapping):
                sections.append((str(item.get("title", "")), tuple(str(x) for x in item.get("lines", ()) or ())))
            else:
                title, lines = item
                sections.append((str(title), tuple(str(x) for x in lines or ())))
        sources = tuple((str(x[0]), str(x[1])) for x in value.get("sources", ()) or ())
        return cls(
            message_type=str(value.get("message_type") or "unknown"),
            schema_version=str(value.get("schema_version") or CONTRACT_VERSION),
            producer=str(value.get("producer") or "unknown"),
            source_event_id=value.get("source_event_id"),
            primary_symbols=_clean_symbols(value.get("primary_symbols", ())),
            severity=str(value.get("severity") or "info").lower(),
            route_intent=value.get("route_intent"),
            operator_action=value.get("operator_action"),
            headline=value.get("headline"),
            facts=dict(value.get("facts") or {}),
            sections=tuple(sections),
            evidence=tuple(str(x) for x in value.get("evidence", ()) or ()),
            diagnostics=tuple(str(x) for x in value.get("diagnostics", ()) or ()),
            sources=sources,
            timestamps=dict(value.get("timestamps") or {}),
            provenance=dict(value.get("provenance") or {}),
            data_completeness=str(value.get("data_completeness") or "unknown"),
            authority=str(value.get("authority") or "READ_ONLY_ADVISORY"),
            dedupe_key=value.get("dedupe_key"),
            raw_text=value.get("raw_text"),
            classification_reason=value.get("classification_reason"),
        )


@dataclass(frozen=True)
class RegistryEntry:
    message_type: str
    owner: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    headline_template: str
    section_order: tuple[str, ...]
    marker: str
    default_route: str
    action_button_policy: str = "none"
    maximum_density: str = "standard"
    aliases: tuple[str, ...] = ()


def _entry(name: str, owner: str, required: Sequence[str], headline: str, route: str,
           marker: str, aliases: Sequence[str] = (), buttons: str = "none") -> RegistryEntry:
    return RegistryEntry(name, owner, tuple(required), (), headline,
                         ("Decision", "Key facts", "Action", "Evidence"), marker, route, buttons,
                         "standard", tuple(aliases))


MESSAGE_REGISTRY: dict[str, RegistryEntry] = {
    "cio_decision": _entry("cio_decision", "cio", ("decision", "why", "next_action"),
                           "{decision} · {symbol}", "IMMEDIATE", "🧭", ("buy", "sell", "add", "trim", "hold"), "command_center"),
    "entry_watch": _entry("entry_watch", "entry-desk", ("price", "entry_zone", "action"),
                           "{status} · {symbol}", "DIGEST", "🎯", ("buy ready", "near entry", "watch"), "command_center"),
    "scalp_setup": _entry("scalp_setup", "scalp-desk", ("price", "setup", "action"),
                           "{signal} · {symbol}", "COMMAND_CENTER", "⚡", ("new go", "scalp", "social scalp"), "command_center"),
    "reentry": _entry("reentry", "reentry-desk", ("thesis_state", "action"),
                       "Re-entry · {symbol}", "DIGEST", "🔁", ("re-enter", "re_entry"), "command_center"),
    "options": _entry("options", "options-desk", ("structure", "verdict", "max_risk"),
                       "{strategy} · {symbol}", "DIGEST", "🧩", ("options",), "command_center"),
    "protection_risk": _entry("protection_risk", "risk", ("risk_state", "action"),
                               "{risk_state} · {symbol}", "IMMEDIATE", "🛡️", ("stop health", "orphaned", "unprotected"), "command_center"),
    "approval": _entry("approval", "operator-authorization", ("scope", "action", "expiry"),
                        "Approval requested", "IMMEDIATE", "🔐", ("2fa", "approval"), "approval"),
    "platform_availability": _entry("platform_availability", "platform-operations", ("state", "impact", "next_check"),
                                     "Platform · {state}", "IMMEDIATE", "📡", ("platform_availability", "recovered", "service")),
    "data_integrity": _entry("data_integrity", "data-quality", ("dataset", "impact", "action"),
                              "Data integrity · {dataset}", "IMMEDIATE", "🧪", ("data_integrity", "scale violation")),
    "research": _entry("research", "research", ("state", "what_is_known", "next_step"),
                        "Research · {state}", "DIGEST", "🔎", ("research update", "research complete", "catalyst research")),
    "digest": _entry("digest", "operator-comms", ("period", "counts", "top_action"),
                      "{period} digest", "DIGEST", "🗂️", ("digest", "suppressed-message")),
    "health_operations": _entry("health_operations", "platform-operations", ("state", "severity", "next_check"),
                                 "Operations · {state}", "DIGEST", "⚙️", ("health agent", "system health", "job telemetry")),
    "market_context": _entry("market_context", "market-context", ("regime", "key_measures", "implication"),
                              "Market · {regime}", "DIGEST", "🌐", ("pre-open", "regime", "vix", "breadth")),
    "progress_status": _entry("progress_status", "operator-comms", ("result", "next_step"),
                               "{operation} · {result}", "DIGEST", "📍", ("progress", "sync", "deployment")),
    "operator_answer": _entry("operator_answer", "cio", ("answer", "evidence_status", "next_action"),
                               "Answer · {symbol}", "IMMEDIATE", "💬", ("operator answer", "research answer")),
    "unknown": _entry("unknown", "communications", (), "Unclassified platform message", "COMMAND_CENTER", "⚠️"),
}


def lint_registry(registry: Mapping[str, RegistryEntry] = MESSAGE_REGISTRY) -> list[str]:
    errors: list[str] = []
    for name, entry in registry.items():
        if name != entry.message_type:
            errors.append(f"{name}: message_type mismatch")
        if not entry.owner:
            errors.append(f"{name}: missing owner")
        if entry.default_route not in ROUTES:
            errors.append(f"{name}: unsupported route")
        if entry.action_button_policy == "approval" and name != "approval":
            errors.append(f"{name}: unsafe approval buttons")
        if not entry.headline_template:
            errors.append(f"{name}: missing headline template")
        if not entry.section_order:
            errors.append(f"{name}: empty section order")
    aliases: dict[str, str] = {}
    for name, entry in registry.items():
        for alias in entry.aliases:
            if alias in aliases:
                errors.append(f"alias collision: {alias}")
            aliases[alias] = name
    return errors


def _legacy_type(text: str) -> tuple[str, str]:
    """Use the established deterministic classifier only as a compatibility input."""
    try:
        from operator_alert_policy_v2 import classify_legacy_message
        kind = classify_legacy_message(text).alert_type
    except Exception:
        kind = ""
    mapping = {
        "cio_entry_state": "entry_watch", "scanner_candidate": "scalp_setup",
        "orphaned_stop": "protection_risk", "position_unprotected": "protection_risk",
        "protection_failure": "protection_risk", "stop_warning": "protection_risk",
        "platform_availability": "platform_availability", "data_integrity": "data_integrity",
        "research_update": "research",
        "system_health": "health_operations", "debug_or_success": "progress_status",
        "paper_proposal": "options", "paper_approval": "approval",
        "live_order_2fa_required": "approval", "live_session_2fa_required": "approval",
        "material_change": "market_context", "thesis_update": "cio_decision",
    }
    if kind in mapping:
        return mapping[kind], f"legacy classifier: {kind}"
    # The compatibility classifier has a conservative catch-all telemetry type.
    # It is not evidence that an arbitrary string is an operations message.
    if kind == "job_telemetry" and re.search(r"health|pipeline|reaper|job|output_invalid|retry_exhausted|locktimeout", text, re.I):
        return "health_operations", "legacy classifier: explicit operations vocabulary"
    return "", "no deterministic registry match"


def classify_message(value: MessageEnvelope | Mapping[str, Any] | str, *, producer: str = "legacy") -> MessageEnvelope:
    """Classify typed or legacy input before any route/send decision."""
    if isinstance(value, MessageEnvelope):
        if value.message_type in MESSAGE_REGISTRY:
            return value
        return MessageEnvelope.from_mapping({**value.__dict__, "message_type": "unknown", "headline": "Unclassified platform message"})
    if isinstance(value, Mapping):
        candidate = MessageEnvelope.from_mapping(value)
        if candidate.message_type in MESSAGE_REGISTRY:
            return candidate
        raw = candidate.raw_text or ""
    else:
        raw = str(value or "")
    message_type, reason = _legacy_type(raw)
    # Registry aliases are compatibility vocabulary, not authority.  They are
    # checked after the established classifier so sentinel-based safety rules
    # (platform/data integrity and protection) retain precedence.
    if not message_type:
        for candidate in sorted(MESSAGE_REGISTRY.values(), key=lambda x: max(map(len, x.aliases), default=0), reverse=True):
            aliases = [a for a in candidate.aliases if len(a) > 3 and a.lower() not in {"service", "watch", "options", "scalp", "regime", "digest", "sync"}]
            if any(re.search(r"(?<![a-z])" + re.escape(alias.lower()) + r"(?![a-z])", raw.lower()) for alias in aliases):
                message_type = candidate.message_type
                reason = f"registry alias: {candidate.message_type}"
                break
    symbol_match = re.search(
        r"\b(?:symbol[:\s]+|new go\s*[—-]\s*|entry alert\s*[—-]*|buy ready\s*|near entry\s*|re[ _-]?enter\s*)"
        r"([A-Z]{1,6})\b", raw, re.I,
    )
    symbols = _clean_symbols([symbol_match.group(1)] if symbol_match else ())
    return MessageEnvelope(
        message_type=message_type or "unknown", producer=producer, primary_symbols=symbols,
        severity="warning" if not message_type else "info", route_intent=None,
        headline=None if message_type else "Unclassified platform message", facts={"summary": raw[:1200]},
        evidence=(raw,) if message_type else (), raw_text=raw,
        classification_reason=reason,
    )


@dataclass(frozen=True)
class RenderedMessage:
    parts: tuple[str, ...]
    parse_mode: str = "HTML"
    buttons: tuple[tuple[str, str], ...] = ()
    preview: Mapping[str, Any] = field(default_factory=lambda: {"is_disabled": True})
    route_metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    renderer_version: str = RENDERER_VERSION

    @property
    def text(self) -> str:
        return self.parts[0] if self.parts else ""


def _value(envelope: MessageEnvelope, key: str) -> str:
    value = envelope.facts.get(key)
    if value is None or value == "":
        return "not available"
    return str(value)


def _split_utf16(text: str, limit: int = MAX_TELEGRAM_UTF16) -> list[str]:
    if _utf16_len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while _utf16_len(remaining) > limit:
        cut = min(len(remaining), limit)
        while cut > 0 and _utf16_len(remaining[:cut]) > limit:
            cut -= 1
        boundary = max(remaining.rfind("\n\n", 0, cut), remaining.rfind("\n", 0, cut))
        if boundary < 1:
            boundary = cut
        chunks.append(remaining[:boundary].rstrip())
        remaining = remaining[boundary:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def route_envelope(envelope: MessageEnvelope) -> dict[str, Any]:
    entry = MESSAGE_REGISTRY.get(envelope.message_type, MESSAGE_REGISTRY["unknown"])
    route = envelope.route_intent or entry.default_route
    # Unknown, incomplete, and model-advised values never gain an interruptive route.
    if envelope.message_type == "unknown":
        route = "COMMAND_CENTER"
    if envelope.message_type == "approval" and (
        not envelope.operator_action or not envelope.facts.get("authorization_ref")
    ):
        route = "COMMAND_CENTER"
    return {"route_mode": route, "message_type": envelope.message_type,
            "registry_version": REGISTRY_VERSION, "dedupe_key": envelope.dedupe_key,
            "policy_decision": "deterministic_registry",
            "action_button_policy": entry.action_button_policy}


def render_message(envelope: MessageEnvelope | Mapping[str, Any] | str) -> RenderedMessage:
    """Render every envelope through one safe HTML card entry point."""
    env = classify_message(envelope)
    entry = MESSAGE_REGISTRY.get(env.message_type, MESSAGE_REGISTRY["unknown"])
    warnings: list[str] = []
    visible = [f"<b>{html.escape(entry.marker + ' ' + (env.headline or entry.headline_template.format_map(_SafeFacts(env))))}</b>"]
    if env.primary_symbols:
        visible.append("Symbols: " + ", ".join(html.escape(x) for x in env.primary_symbols))
    if env.message_type == "unknown":
        visible.append("<i>Summary:</i> " + html.escape(_value(env, "summary")))
        visible.append("<i>Action:</i> not available")
    else:
        for key in entry.required_fields:
            visible.append(f"<b>{html.escape(key.replace('_', ' ').title())}:</b> {html.escape(_value(env, key))}")
        for title, lines in env.sections:
            if lines:
                visible.append("<b>" + html.escape(title) + "</b>\n" + "\n".join(html.escape(line) for line in lines))
        if env.operator_action:
            visible.append(f"<b>Action:</b> {html.escape(env.operator_action)}")
    if env.sources:
        safe_sources = [(label, url) for label, url in env.sources if str(url).startswith("https://")]
        if len(safe_sources) != len(env.sources):
            warnings.append("unsafe source URL omitted")
        if safe_sources:
            visible.append("Source: " + " · ".join(f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>' for label, url in safe_sources[:6]))
    diagnostics = env.diagnostics or env.evidence
    if diagnostics:
        visible.append("<blockquote expandable>" + html.escape("\n".join(diagnostics)) + "</blockquote>")
    body = "\n".join(visible)
    parts = tuple(_split_utf16(body))
    if len(parts) > 1:
        warnings.append("split at paragraph boundary")
    if any(_utf16_len(p) > MAX_TELEGRAM_UTF16 for p in parts):
        warnings.append("message exceeds Telegram UTF-16 limit")
    route_metadata = route_envelope(env)
    buttons: tuple[tuple[str, str], ...] = ()
    action_url = str(env.facts.get("action_url") or "")
    action_label = str(env.facts.get("action_label") or "Review")
    if (entry.action_button_policy != "none" and env.operator_action and
            (entry.action_button_policy != "approval" or env.facts.get("authorization_ref")) and
            action_url.startswith("https://")):
        buttons = ((action_label, action_url),)
    return RenderedMessage(parts=parts, buttons=buttons, route_metadata=route_metadata, warnings=tuple(warnings))


class _SafeFacts(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "not available"

    def __init__(self, envelope: MessageEnvelope):
        super().__init__(envelope.facts)
        self["symbol"] = envelope.primary_symbols[0] if envelope.primary_symbols else "not available"
        self["decision"] = self.get("decision", "Decision")
        self["status"] = self.get("status", "Status")
        self["signal"] = self.get("signal", "Signal")
        self["strategy"] = self.get("strategy", "Strategy")
        self["risk_state"] = self.get("risk_state", "Risk state")
        self["state"] = self.get("state", "State")
        self["dataset"] = self.get("dataset", "dataset")
        self["period"] = self.get("period", "Period")
        self["operation"] = self.get("operation", "Operation")
        self["result"] = self.get("result", "Result")


def record_shadow_proposal(envelope: MessageEnvelope, proposal: Mapping[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """Persist redacted advisory output; it cannot mutate the envelope or policy."""
    safe = {"candidate_type": proposal.get("candidate_type"), "field_mapping": proposal.get("field_mapping"),
            "gaps": proposal.get("gaps"), "recorded_at": _now(), "source_event_id": envelope.source_event_id,
            "advisory_only": True, "registry_version": REGISTRY_VERSION}
    target = path or Path(os.getenv("TRADEAI_MESSAGE_SHADOW_PATH", "data/runtime/telegram_message_shadow.jsonl"))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(safe, sort_keys=True, default=str) + "\n")
    except OSError:
        pass
    return safe


def audit_unknown(envelope: MessageEnvelope, *, path: Path | None = None) -> None:
    if envelope.message_type != "unknown":
        return
    target = path or Path(os.getenv("TRADEAI_MESSAGE_AUDIT_PATH", "data/runtime/telegram_message_classification_audit.jsonl"))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "unknown_message", "recorded_at": _now(), "producer": envelope.producer,
                                 "summary": (envelope.raw_text or "")[:1200], "dedupe_key": envelope.dedupe_key}, sort_keys=True) + "\n")
    except OSError:
        pass


if lint_registry():  # pragma: no cover - protects accidental source edits at import time
    raise RuntimeError("invalid message registry: " + "; ".join(lint_registry()))
