"""Ask the CIO — the shared contract (AskRequest@v1, AskAnswer@v1). READ_ONLY_ADVISORY.

Operator 2026-10-23: build "Ask the CIO" as Phases 8–11 after the release-train phases; "the key is the persistent
memory. Across the CIO system." This module is the one contract between

* Phase 8 / 10 / 11 (``scripts/lib/cio_ask_core.py`` — the ask bar, "My questions", Telegram, memory, auto-track,
  re-answer on material change), and
* Phase 9 (``scripts/lib/cio_ask_research.py`` on ``feat/ask-cio-phase9-research-20261023`` — Brave / SEC / news /
  street targets / LLM panel, the prospectus).

It holds data shapes, validation, the MBI guard and the Phase 9 hand-off protocol. It performs no I/O, calls no model
and writes no store. Everything here is JSON-serialisable through ``to_dict``.

Authority rails (AGENTS.md §0 rule 1, §2, §26.1):

* ``MBI_BEHAVIOR = 0``. The CIO never picks a share quantity, never proposes an order, stop, limit or weight.
  ``sizing_context`` is computed **only for quantities the operator named** ("100 or 1,000 TSLA?"): dollar exposure,
  % of portfolio, concentration against the limit, loss at a reference stop. It carries no recommended quantity.
* Quantities are **optional** in every ask (operator clarification 2026-10-23: "I could just ask the question without
  sizes. It can suggest sizes, or I can say sizes."). Nothing here requires or prompts for a size.
* ``size_suggestion`` (advisory, risk-budget based, reasoning shown, never actionable) is designed but **always
  omitted** unless AGENTS.md is at or above 21.0.0 ACTIVE (``size_suggestion_allowed``). Until then
  ``mbi_guard_text`` / ``mbi_guard_payload`` strip model sizing and the strip is recorded, never silent.
* §2A: position dollars and account detail never go to an external model provider. ``sizing_context`` is computed on
  the host from house facts and is never part of a prompt; ``research_context_for_model`` drops it.

Contract versions are frozen strings; a breaking change mints ``@v2`` beside ``@v1``, never edits ``@v1`` in place.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

ASK_REQUEST_SCHEMA = "AskRequest@v1"
ASK_ANSWER_SCHEMA = "AskAnswer@v1"
PROSPECTUS_SCHEMA = "AskProspectus@v1"
SIZING_CONTEXT_SCHEMA = "AskSizingContext@v1"
SIZE_SUGGESTION_SCHEMA = "AskSizeSuggestion@v1"
RESEARCH_CONTEXT_SCHEMA = "AskResearchContext@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

CHANNELS = ("cc", "telegram", "whatsapp", "event")
DEPTHS = ("quick", "deep")
HORIZONS = ("3m", "6m", "12m")
SCENARIOS = ("bear", "base", "bull")
ENTITY_KINDS = ("security", "private_entity", "unresolved")
RESOLUTIONS = ("CONFIRMED", "AMBIGUOUS", "UNRESOLVED_PRIVATE", "UNRESOLVED")
ANSWER_STATUSES = (
    "quick",  # answered by the desk loop (Phase 8 quick path)
    "deep_pending",  # deep research requested; Phase 9 not landed, capped, or still running
    "deep",  # Phase 9 prospectus answer
    "reanswer",  # Phase 11 updated version after a material change
    "capped",  # refused before spend: per-question or daily cap
    "failed",  # the path could not produce an answer (says why in `summary`)
)
CONFIDENCE_LEVELS = ("low", "medium", "high")
QUANTITY_UNITS = ("shares", "usd")
TRACKING_STATES = ("tracked", "untracked")

# Memory event kinds appended to CIO memory keyed by security_guid (or entity_guid for a private entity).
MEMORY_KINDS = (
    "ask.asked",
    "ask.entity_resolved",
    "ask.answer_version",
    "ask.source",
    "ask.follow_up",
    "ask.tracking_changed",
    "ask.reanswer_triggered",
)

# Where Phase 9 lands its deep-research entry point. Resolved lazily by cio_ask_core; absent → deep_pending stub.
DEEP_RESEARCH_ENTRYPOINT = "scripts.lib.cio_ask_research:run_deep_research"

# AGENTS.md version at which size suggestions could be allowed (operator option, not ratified).
SIZE_SUGGESTION_POLICY_VERSION = "21.0.0"
# Anchor the gate requires in AGENTS.md beside the version row. §0 always exists, so today the version row decides; the
# 21.0.0 amendment should name its own section and this constant moves to it in that PR.
SIZE_SUGGESTION_POLICY_ANCHOR = "# 0 · If you read nothing else"

# The InstrumentRecord rail's keys (scripts/lib/cio_instrument_record.py BEHAVIOR_FIELDS) plus sizing words a model
# might invent. Any of these keys in model output is stripped and recorded.
MODEL_BEHAVIOR_KEYS = frozenset(
    {
        "recommended_delta_usd",
        "size_usd",
        "shares",
        "qty",
        "order",
        "stop",
        "limit",
        "target_weight_pct",
        "trade",
        "execution",
        "quantity",
        "recommended_quantity",
        "position_size",
        "share_count",
        "num_shares",
        "size",
        "size_suggestion",
        "suggested_size",
        "allocation_pct",
        "target_weight",
        "buy_quantity",
        "sell_quantity",
        "stop_loss",
        "stop_price",
        "limit_price",
        "order_type",
        "entry_order",
    }
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _h(*parts: Any, n: int = 16) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:n]


def normalise_question(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def make_ask_id(*, channel: str, source_ref: str, question: str) -> str:
    """Deterministic: the same inbound message (channel + message id / CC request id) is the same ask. Idempotent."""
    return "ask_" + _h(channel, source_ref, normalise_question(question))


def make_thread_id(root_ask_id: str) -> str:
    return "thr_" + root_ask_id.removeprefix("ask_")


def private_entity_guid(name: str) -> str:
    """A stable id for an entity with no listed security (e.g. a pre-IPO company). Never a ticker."""
    norm = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
    return "ent_" + str(uuid.uuid5(uuid.NAMESPACE_URL, "tradeai:private-entity:" + norm))


# ── shapes ─────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class EntityRef:
    """One thing the question is about. A security has a CONFIRMED security_guid; a private entity has an entity_guid
    and **no symbol** (never invent a ticker); an unresolved name stays unresolved and is shown so."""

    name: str
    kind: str = "security"
    symbol: Optional[str] = None
    security_guid: Optional[str] = None
    issuer_guid: Optional[str] = None
    entity_guid: Optional[str] = None
    resolution: str = "CONFIRMED"
    note: Optional[str] = None

    @property
    def memory_key(self) -> Optional[str]:
        return self.security_guid or self.entity_guid

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EntityRef":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})  # type: ignore[arg-type]


@dataclass
class NamedQuantity:
    """A quantity the operator wrote in the question. Optional; never required, never prompted for."""

    symbol: str
    amount: float
    unit: str = "shares"  # shares | usd
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AskRequest:
    question: str
    channel: str
    source_ref: str  # CC request id, Telegram message id, or event id — the idempotency anchor
    depth: str = "quick"
    asked_at: str = field(default_factory=utc_now_iso)
    asked_by: str = "operator"
    thread_id: Optional[str] = None  # set for follow-ups; None → this ask roots a new thread
    parent_ask_id: Optional[str] = None
    entities: list[EntityRef] = field(default_factory=list)
    named_quantities: list[NamedQuantity] = field(default_factory=list)
    trigger: Optional[dict[str, Any]] = None  # Phase 11: {event_id, kind, summary, security_guid}
    chat_id: Optional[str] = None
    schema: str = ASK_REQUEST_SCHEMA
    authority: str = AUTHORITY

    @property
    def ask_id(self) -> str:
        return make_ask_id(channel=self.channel, source_ref=self.source_ref, question=self.question)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ask_id"] = self.ask_id
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AskRequest":
        kw = {k: d[k] for k in cls.__dataclass_fields__ if k in d and k not in ("entities", "named_quantities")}
        kw["entities"] = [EntityRef.from_dict(e) for e in d.get("entities") or []]
        kw["named_quantities"] = [NamedQuantity(**q) for q in d.get("named_quantities") or []]
        return cls(**kw)


@dataclass
class Scenario:
    narrative: str
    price: Optional[float] = None
    return_pct: Optional[float] = None


@dataclass
class Catalyst:
    event: str
    date: Optional[str] = None  # ISO date when known
    window: Optional[str] = None  # e.g. "Q1 2027", "late Nov" — when only a window is known
    date_confidence: str = "estimated"  # confirmed | estimated | rumoured
    impact: Optional[str] = None
    source: Optional[str] = None


@dataclass
class StreetTarget:
    low: Optional[float] = None
    median: Optional[float] = None
    high: Optional[float] = None
    n_analysts: Optional[int] = None
    as_of: Optional[str] = None
    source: Optional[str] = None


@dataclass
class SecurityProspectus:
    """AskProspectus@v1 — the fixed per-security format the operator asked for (3 / 6 / 12 months)."""

    entity: EntityRef
    horizons: dict[str, dict[str, Scenario]] = field(default_factory=dict)  # {"3m": {"bear": Scenario, ...}, ...}
    street_target: Optional[StreetTarget] = None
    catalysts: list[Catalyst] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    what_changes_view: list[str] = field(default_factory=list)
    stance: Optional[str] = None  # constructive | neutral | cautious — a view, never an action
    as_of: str = field(default_factory=utc_now_iso)
    schema: str = PROSPECTUS_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["entity"] = self.entity.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SecurityProspectus":
        hz = {h: {s: Scenario(**v) for s, v in (sc or {}).items()} for h, sc in (d.get("horizons") or {}).items()}
        st = d.get("street_target")
        return cls(
            entity=EntityRef.from_dict(d.get("entity") or {"name": "?"}),
            horizons=hz,
            street_target=StreetTarget(**st) if isinstance(st, dict) else None,
            catalysts=[Catalyst(**c) for c in d.get("catalysts") or []],
            risks=list(d.get("risks") or []),
            what_changes_view=list(d.get("what_changes_view") or []),
            stance=d.get("stance"),
            as_of=d.get("as_of") or utc_now_iso(),
        )


@dataclass
class SizingContextRow:
    """AskSizingContext@v1 — exposure and risk of ONE quantity the operator named. Never a recommendation.

    Key names deliberately avoid the InstrumentRecord BEHAVIOR_FIELDS (``shares``, ``qty``, ``stop`` …): this row is
    context for a choice the operator is making, and it is never written to an InstrumentRecord or a model prompt.
    """

    symbol: str
    security_guid: Optional[str]
    operator_amount: float
    operator_unit: str  # shares | usd
    reference_price: Optional[float]
    price_as_of: Optional[str]
    exposure_usd: Optional[float]
    pct_of_portfolio: Optional[float]
    existing_exposure_usd: Optional[float] = None
    combined_pct_of_portfolio: Optional[float] = None
    concentration_limit_pct: Optional[float] = None
    concentration_limit_source: Optional[str] = None
    over_concentration_limit: Optional[bool] = None
    reference_stop_price: Optional[float] = None
    reference_stop_basis: Optional[str] = None  # e.g. "operator-named", "policy reference 8% below price"
    loss_at_reference_usd: Optional[float] = None
    loss_at_reference_pct_of_portfolio: Optional[float] = None
    portfolio_value_usd: Optional[float] = None
    portfolio_as_of: Optional[str] = None
    gaps: list[str] = field(default_factory=list)
    label: str = "Operator-named quantity — exposure and risk shown, not a recommendation"
    schema: str = SIZING_CONTEXT_SCHEMA


@dataclass
class SizeSuggestion:
    """AskSizeSuggestion@v1 — designed, gated off. Emitted only when ``size_suggestion_allowed()`` is True
    (AGENTS.md >= 21.0.0 ACTIVE). Advisory, risk-budget based, reasoning shown, never actionable."""

    symbol: str
    risk_budget_pct: float
    reference_stop_price: float
    illustrative_range: tuple[float, float]
    reasoning: str
    advisory: bool = True
    actionable: bool = False
    schema: str = SIZE_SUGGESTION_SCHEMA


@dataclass
class Source:
    title: str
    kind: str  # house_store | web | sec | news | street | model
    as_of: Optional[str]
    url: Optional[str] = None
    store: Optional[str] = None
    security_guid: Optional[str] = None


@dataclass
class Confidence:
    level: str = "low"
    score: Optional[float] = None
    rationale: str = ""


@dataclass
class ModelDissent:
    model: str
    view: str
    differs_on: str


@dataclass
class AskAnswer:
    ask_id: str
    thread_id: str
    version: int
    depth: str
    status: str
    summary: str  # the operator-facing text, identical on every channel
    entities: list[EntityRef] = field(default_factory=list)
    prospectus: list[SecurityProspectus] = field(default_factory=list)
    sizing_context: list[SizingContextRow] = field(default_factory=list)
    size_suggestion: list[SizeSuggestion] = field(default_factory=list)  # gated; omitted from to_dict until 21.0.0
    sources: list[Source] = field(default_factory=list)
    confidence: Confidence = field(default_factory=Confidence)
    model_dissent: list[ModelDissent] = field(default_factory=list)
    recall: list[dict[str, Any]] = field(default_factory=list)  # prior asks/answers on the same securities
    what_changed: Optional[str] = None  # Phase 11 re-answers
    trigger: Optional[dict[str, Any]] = None
    mbi_guard: dict[str, Any] = field(default_factory=lambda: {"stripped": 0, "findings": []})
    cost_usd: float = 0.0
    produced_by: str = "cio_ask_core"
    produced_at: str = field(default_factory=utc_now_iso)
    provenance: dict[str, Any] = field(default_factory=dict)
    schema: str = ASK_ANSWER_SCHEMA
    authority: str = AUTHORITY
    recommendation: str = "NONE"

    @property
    def answer_id(self) -> str:
        return f"{self.ask_id}:v{self.version}"

    def to_dict(self, *, allow_size_suggestion: Optional[bool] = None) -> dict[str, Any]:
        allowed = size_suggestion_allowed() if allow_size_suggestion is None else allow_size_suggestion
        d = asdict(self)
        d["answer_id"] = self.answer_id
        d["entities"] = [e.to_dict() for e in self.entities]
        d["prospectus"] = [p.to_dict() for p in self.prospectus]
        if not allowed or not self.size_suggestion:
            d.pop("size_suggestion", None)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AskAnswer":
        conf = d.get("confidence") or {}
        return cls(
            ask_id=d["ask_id"],
            thread_id=d["thread_id"],
            version=int(d.get("version") or 1),
            depth=d.get("depth") or "quick",
            status=d.get("status") or "quick",
            summary=d.get("summary") or "",
            entities=[EntityRef.from_dict(e) for e in d.get("entities") or []],
            prospectus=[SecurityProspectus.from_dict(p) for p in d.get("prospectus") or []],
            sizing_context=[SizingContextRow(**r) for r in d.get("sizing_context") or []],
            sources=[Source(**s) for s in d.get("sources") or []],
            confidence=Confidence(**conf) if isinstance(conf, dict) else Confidence(),
            model_dissent=[ModelDissent(**m) for m in d.get("model_dissent") or []],
            recall=list(d.get("recall") or []),
            what_changed=d.get("what_changed"),
            trigger=d.get("trigger"),
            mbi_guard=d.get("mbi_guard") or {"stripped": 0, "findings": []},
            cost_usd=float(d.get("cost_usd") or 0.0),
            produced_by=d.get("produced_by") or "cio_ask_core",
            produced_at=d.get("produced_at") or utc_now_iso(),
            provenance=d.get("provenance") or {},
        )


# ── validation ─────────────────────────────────────────────────────────────────────────────────────────────────────


def validate_request(req: AskRequest) -> list[str]:
    p: list[str] = []
    if not str(req.question or "").strip():
        p.append("question empty")
    if req.channel not in CHANNELS:
        p.append(f"channel {req.channel!r} not in {CHANNELS}")
    if req.depth not in DEPTHS:
        p.append(f"depth {req.depth!r} not in {DEPTHS}")
    if not str(req.source_ref or "").strip():
        p.append("source_ref empty (idempotency anchor)")
    for e in req.entities:
        p.extend(validate_entity(e))
    for q in req.named_quantities:
        if q.unit not in QUANTITY_UNITS:
            p.append(f"named quantity unit {q.unit!r} not in {QUANTITY_UNITS}")
        if not (isinstance(q.amount, (int, float)) and q.amount > 0):
            p.append(f"named quantity amount {q.amount!r} not positive")
    return p


def validate_entity(e: EntityRef) -> list[str]:
    p: list[str] = []
    if e.kind not in ENTITY_KINDS:
        p.append(f"entity kind {e.kind!r} not in {ENTITY_KINDS}")
    if e.resolution not in RESOLUTIONS:
        p.append(f"entity resolution {e.resolution!r} not in {RESOLUTIONS}")
    if e.kind == "security" and not e.security_guid:
        p.append(f"security entity {e.name!r} has no security_guid (unresolved names are kind='unresolved')")
    if e.kind == "private_entity":
        if e.symbol:
            p.append(f"private entity {e.name!r} carries symbol {e.symbol!r} — never invent a ticker")
        if not e.entity_guid:
            p.append(f"private entity {e.name!r} has no entity_guid")
    return p


def validate_prospectus(pr: SecurityProspectus) -> list[str]:
    p: list[str] = []
    for h in HORIZONS:
        sc = pr.horizons.get(h)
        if not sc:
            p.append(f"{pr.entity.name}: horizon {h} missing")
            continue
        for s in SCENARIOS:
            if s not in sc or not str(sc[s].narrative or "").strip():
                p.append(f"{pr.entity.name}: horizon {h} scenario {s} missing")
    for c in pr.catalysts:
        if not (c.date or c.window):
            p.append(f"{pr.entity.name}: catalyst {c.event!r} undated (needs date or window)")
    if not pr.what_changes_view:
        p.append(f"{pr.entity.name}: what_changes_view empty")
    return p


def validate_answer(ans: AskAnswer, *, allow_size_suggestion: Optional[bool] = None) -> list[str]:
    p: list[str] = []
    if ans.status not in ANSWER_STATUSES:
        p.append(f"status {ans.status!r} not in {ANSWER_STATUSES}")
    if ans.depth not in DEPTHS:
        p.append(f"depth {ans.depth!r} not in {DEPTHS}")
    if ans.version < 1:
        p.append("version < 1")
    if ans.confidence.level not in CONFIDENCE_LEVELS:
        p.append(f"confidence level {ans.confidence.level!r} not in {CONFIDENCE_LEVELS}")
    if ans.authority != AUTHORITY or ans.recommendation != "NONE":
        p.append("authority must be READ_ONLY_ADVISORY with recommendation NONE")
    if ans.status in ("deep", "reanswer") and ans.depth == "deep":
        for pr in ans.prospectus:
            p.extend(validate_prospectus(pr))
    for s in ans.sources:
        if not s.as_of:
            p.append(f"source {s.title!r} has no as_of")
    allowed = size_suggestion_allowed() if allow_size_suggestion is None else allow_size_suggestion
    if ans.size_suggestion and not allowed:
        p.append("size_suggestion present while AGENTS.md < 21.0.0 ACTIVE (MBI_BEHAVIOR=0)")
    for s in ans.size_suggestion:
        if s.actionable or not s.advisory:
            p.append(f"size_suggestion for {s.symbol} must be advisory and never actionable")
    _, findings = mbi_guard_text(ans.summary)
    if findings:
        p.append(f"summary proposes a quantity or order: {findings[0]['match']!r}")
    return p


# ── the size-suggestion gate ───────────────────────────────────────────────────────────────────────────────────────


def _version_tuple(v: str) -> Optional[tuple[int, int, int]]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", str(v or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _policy_state_or_later(agents_path: Optional[Path], required: str, anchor: str) -> dict[str, Any]:
    """Use ops_controls_core.policy_state(or_later=True) when present; otherwise the same semantics, fail closed."""
    try:
        from scripts.lib.ops_controls_core import policy_state  # noqa: PLC0415

        try:
            return policy_state(agents_path, required=required, anchor=anchor, or_later=True)
        except TypeError:
            pass  # policy_state predates or_later (PR #1970) — fall through to the equivalent check
    except Exception:  # noqa: BLE001
        pass
    p = Path(agents_path) if agents_path else Path(__file__).resolve().parents[2] / "AGENTS.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return {"state": "UNREADABLE", "required": required, "detail": f"{p}: {type(exc).__name__}"}
    floor = _version_tuple(required)
    rows = re.findall(r"^\|\s*(\d+\.\d+\.\d+)\s*\|[^|]*\|\s*([^|]*)\|", text, re.M)
    hit = [
        v
        for v, s in rows
        if floor and (_version_tuple(v) or (0, 0, 0)) >= floor and s.strip().upper().startswith("ACTIVE")
    ]
    if not hit or anchor not in text:
        return {"state": "NOT_ACTIVE", "required": required, "detail": f"no ACTIVE row at or above {required}"}
    return {"state": "ACTIVE", "required": required, "detail": f"{max(hit, key=_version_tuple)} ACTIVE"}


def size_suggestion_allowed(agents_path: Optional[Path] = None) -> bool:
    """True only when AGENTS.md has an ACTIVE version-history row >= 21.0.0. Read at call time; no env override."""
    st = _policy_state_or_later(agents_path, SIZE_SUGGESTION_POLICY_VERSION, SIZE_SUGGESTION_POLICY_ANCHOR)
    return str(st.get("state")) == "ACTIVE"


# ── the MBI guard — model output never proposes a quantity or an order ─────────────────────────────────────────────

_NUM = r"\d[\d,]*(?:\.\d+)?k?"
_MBI_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "quantity_advice",
        re.compile(
            r"\b(?:i(?:'d| would)?\s+)?(?:recommend|suggest|advise|propose)\w*\s+(?:that\s+you\s+)?(?:buy|buying|sell|"
            r"selling|purchas\w*|acquir\w*|add\w*|trim\w*|hold\w*)\s+(?:about\s+|around\s+|roughly\s+)?"
            + _NUM
            + r"(?:\s+(?:shares?|units?|contracts?))?",
            re.I,
        ),
    ),
    (
        "imperative_quantity",
        re.compile(
            r"\b(?:you\s+should|go\s+with|stick\s+with|choose|pick|take|start\s+with)\s+(?:the\s+)?"
            r"(?:" + _NUM + r")\s*(?:shares?|units?|contracts?)?\b",
            re.I,
        ),
    ),
    (
        "buy_n_shares",
        re.compile(r"\b(?:buy|sell|purchase|short)\s+" + _NUM + r"\s+(?:shares?|units?|contracts?)\b", re.I),
    ),
    (
        "order_instruction",
        re.compile(
            r"\b(?:place|enter|submit|put\s+in|set)\s+(?:a|an|the)?\s*(?:limit|market|stop(?:-loss)?|bracket|"
            r"trailing(?:\s+stop)?)\s+(?:order|at)\b",
            re.I,
        ),
    ),
    ("stop_instruction", re.compile(r"\bset\s+(?:your|a|the)\s+stop(?:-loss)?\s+(?:at|to|near)\b", re.I)),
    (
        "position_size",
        re.compile(
            r"\b(?:position\s+size|allocate|allocation)\s+(?:of\s+|should\s+be\s+|to\s+)?(?:about\s+)?"
            r"(?:" + _NUM + r"\s*%|\$\s?" + _NUM + r"|" + _NUM + r"\s+shares?)",
            re.I,
        ),
    ),
    ("weight_target", re.compile(r"\b(?:target|raise|cut)\s+(?:the\s+)?weight\s+(?:to|at)\s+" + _NUM + r"\s*%", re.I)),
)

MBI_STRIP_NOTE = (
    "[Removed by the MBI guard: the CIO never picks a share quantity, order, stop or weight "
    "(AGENTS.md §0 rule 1). Exposure and risk of the quantities you named are shown below.]"
)


def mbi_guard_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Strip every sentence of model text that proposes a quantity, order, stop or weight. Returns (clean, findings).

    The strip is recorded, never silent: callers put ``findings`` on ``AskAnswer.mbi_guard`` and a visible note
    replaces the removed text.
    """
    body = str(text or "")
    findings: list[dict[str, Any]] = []
    # split on sentence ends and newlines, keeping separators
    parts = re.split(r"(?<=[.!?])\s+|\n", body)
    kept: list[str] = []
    stripped_any = False
    for part in parts:
        hit = None
        for name, pat in _MBI_PATTERNS:
            m = pat.search(part)
            if m:
                hit = (name, m.group(0))
                break
        if hit:
            findings.append({"rule": hit[0], "match": hit[1][:120], "sentence": part.strip()[:240]})
            stripped_any = True
            continue
        kept.append(part)
    if not stripped_any:
        return body, []
    clean = "\n".join(s for s in (" ".join(k for k in kept if k is not None)).split("\n"))
    clean = re.sub(r"[ \t]{2,}", " ", clean).strip()
    clean = (clean + "\n\n" if clean else "") + MBI_STRIP_NOTE
    return clean, findings


def mbi_guard_payload(obj: Any, *, path: str = "$") -> tuple[Any, list[dict[str, Any]]]:
    """Recursively drop MODEL_BEHAVIOR_KEYS from structured model output and run mbi_guard_text over strings."""
    findings: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in MODEL_BEHAVIOR_KEYS:
                findings.append({"rule": "behavior_key", "match": str(k), "path": f"{path}.{k}"})
                continue
            nv, f = mbi_guard_payload(v, path=f"{path}.{k}")
            findings.extend(f)
            out[k] = nv
        return out, findings
    if isinstance(obj, list):
        res = []
        for i, v in enumerate(obj):
            nv, f = mbi_guard_payload(v, path=f"{path}[{i}]")
            findings.extend(f)
            res.append(nv)
        return res, findings
    if isinstance(obj, str):
        clean, f = mbi_guard_text(obj)
        for x in f:
            x["path"] = path
        return clean, f
    return obj, findings


# ── quantity parsing — optional, never required ────────────────────────────────────────────────────────────────────

_QTY_RE = re.compile(
    r"(?P<usd>\$\s?)?(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<k>k\b)?\s*"
    r"(?:(?P<unit>shares?|sh)\b\s*(?:of\s+)?)?(?P<sym>\$?[A-Z]{1,5})?\b"
)


def parse_named_quantities(question: str, symbols: list[str]) -> list[NamedQuantity]:
    """Quantities the operator wrote, tied to a named symbol. "100 or 1,000 TSLA" → two rows for TSLA.

    Returns [] when no quantity is named — that is the normal case and nothing prompts for one.
    """
    syms = [s.upper() for s in symbols if s]
    if not syms:
        return []
    text = str(question or "")
    found: list[NamedQuantity] = []
    for m in _QTY_RE.finditer(text):
        num_s = m.group("num").replace(",", "")
        try:
            amt = float(num_s)
        except ValueError:
            continue
        if m.group("k"):
            amt *= 1000
        sym = (m.group("sym") or "").lstrip("$").upper()
        unit = "usd" if m.group("usd") else "shares"
        has_unit = bool(m.group("unit")) or bool(m.group("usd"))
        if sym and sym not in syms:
            sym = ""
        if not sym and not has_unit:
            # "100 or 1,000 TSLA": a bare number followed (within a few words) by a named symbol counts
            tail = text[m.end() : m.end() + 24]
            nxt = re.search(r"\b(" + "|".join(map(re.escape, syms)) + r")\b", tail)
            if not nxt or not re.match(
                r"^\s*(?:or|and|to|vs\.?|,)?\s*[\d,$k\s]*(?:shares?\s+(?:of\s+)?)?$", tail[: nxt.start()]
            ):
                continue
            sym = nxt.group(1)
        if not sym:
            sym = syms[0] if len(syms) == 1 else ""
        if not sym or amt <= 0:
            continue
        # skip years and percentages
        if re.match(r"^\s*%", text[m.end() : m.end() + 2]) or (
            unit == "shares" and 1900 <= amt <= 2100 and not m.group("unit")
        ):
            continue
        found.append(NamedQuantity(symbol=sym, amount=amt, unit=unit, raw=m.group(0).strip()))
    # dedupe
    seen: set[tuple[str, float, str]] = set()
    out = []
    for q in found:
        key = (q.symbol, q.amount, q.unit)
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out


# ── Phase 9 hand-off ───────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class ResearchBudget:
    """What the deep path may spend for this one question; reserved by cio_ask_core before the call."""

    max_usd: float
    reservation_id: Optional[str] = None
    process_id: str = "cio_ask_deep_research"


@dataclass
class AskResearchContext:
    """Everything the Phase 9 pipeline receives. ``house_facts`` and ``recall`` are already sanitised for egress:
    no position dollars, no account detail (§2A). ``sizing_context`` is never passed — the core adds it after."""

    request: AskRequest
    thread_id: str
    version: int
    recall: list[dict[str, Any]] = field(default_factory=list)
    house_facts: dict[str, Any] = field(default_factory=dict)
    quick_answer: Optional[str] = None
    budget: ResearchBudget = field(default_factory=lambda: ResearchBudget(max_usd=0.0))
    schema: str = RESEARCH_CONTEXT_SCHEMA


@runtime_checkable
class DeepResearchProvider(Protocol):
    """Phase 9 implements ``run_deep_research(ctx) -> AskAnswer`` at DEEP_RESEARCH_ENTRYPOINT.

    The returned answer must pass ``validate_answer``; the core runs ``mbi_guard_payload`` over it again regardless,
    adds ``sizing_context`` and ``recall``, appends it to memory, and posts it in the thread.
    """

    def __call__(self, ctx: AskResearchContext) -> AskAnswer: ...


_EGRESS_DROP_KEYS = frozenset(
    {
        "sizing_context",
        "exposure_usd",
        "existing_exposure_usd",
        "portfolio_value_usd",
        "market_value",
        "cost_basis",
        "account",
        "account_id",
        "account_number",
        "position_usd",
        "loss_at_reference_usd",
        "named_quantities",
    }
)


def research_context_for_model(obj: Any) -> Any:
    """Drop position dollars / account detail / operator quantities before anything goes to a model (§2A)."""
    if isinstance(obj, dict):
        return {k: research_context_for_model(v) for k, v in obj.items() if str(k).lower() not in _EGRESS_DROP_KEYS}
    if isinstance(obj, list):
        return [research_context_for_model(v) for v in obj]
    return obj


__all__ = [
    "ASK_REQUEST_SCHEMA",
    "ASK_ANSWER_SCHEMA",
    "PROSPECTUS_SCHEMA",
    "SIZING_CONTEXT_SCHEMA",
    "SIZE_SUGGESTION_SCHEMA",
    "RESEARCH_CONTEXT_SCHEMA",
    "AUTHORITY",
    "CHANNELS",
    "DEPTHS",
    "HORIZONS",
    "SCENARIOS",
    "ANSWER_STATUSES",
    "MEMORY_KINDS",
    "DEEP_RESEARCH_ENTRYPOINT",
    "MODEL_BEHAVIOR_KEYS",
    "MBI_STRIP_NOTE",
    "EntityRef",
    "NamedQuantity",
    "AskRequest",
    "Scenario",
    "Catalyst",
    "StreetTarget",
    "SecurityProspectus",
    "SizingContextRow",
    "SizeSuggestion",
    "Source",
    "Confidence",
    "ModelDissent",
    "AskAnswer",
    "ResearchBudget",
    "AskResearchContext",
    "DeepResearchProvider",
    "make_ask_id",
    "make_thread_id",
    "private_entity_guid",
    "normalise_question",
    "utc_now_iso",
    "validate_request",
    "validate_entity",
    "validate_prospectus",
    "validate_answer",
    "size_suggestion_allowed",
    "mbi_guard_text",
    "mbi_guard_payload",
    "parse_named_quantities",
    "research_context_for_model",
]
