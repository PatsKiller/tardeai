"""Ask the CIO — Phase 9 research pipeline (READ_ONLY_ADVISORY).

Turns one ``AskRequest@v1`` into one ``AskAnswer@v1`` prospectus. Operator approval 2026-10-23
(docs/ops/ASK_THE_CIO_RESEARCH.md).

    request ─► resolve entities (listed: security_guid; private: tracked issuer, never a ticker)
            ─► gather facts in parallel, one timeout per source (internal, web, SEC, news, street)
            ─► LLM panel: every member sees the SAME fact table; disagreement is kept
            ─► synthesis: numbers only from sourced facts, gaps named, MBI guard on all model text
            ─► CIO memory append keyed by security_guid (idempotent), through the integrator

Rails
-----
* ``MBI_BEHAVIOR = 0`` (AGENTS.md §0 rule 1). This module never sizes, orders, stops or weights.
  ``sizing_context`` is arithmetic on quantities the OPERATOR named (exposure and scenario P/L per
  option). Any model text that recommends a quantity, an order, a stop or a weight is stripped and logged
  (``mbi_strip_log``). ``size_suggestion`` is never emitted. It stays withheld until AGENTS >= 21.0.0 is
  ACTIVE (operator decision pending). ``risk_budget_inputs`` only collects the sourced inputs a later
  risk-budget calculation would need.
* Numbers come only from facts. Every fact carries ``as_of`` and a ``citation``. A model-proposed number
  that matches no fact is dropped (``ungrounded_log``). A horizon with no sourced anchor says so; it is
  never filled in.
* Egress (§2A). Holdings, trades and sizing never reach a model provider. They are ``egress: local_only``
  facts, and the panel prompt also passes ``sanitise_for_external``.
* Spend. Every panel call is admitted by a per-question cap, and then by the existing reservation ledger
  (``llm_consumption.check_cost_cap``: the process daily cap plus the global cap). A process with no
  registered cap is refused (fail closed). A refused member does not fail the answer. The answer comes
  back ``partial`` and says why.
* §23.4. On the n8n path (``origin="n8n"``) model-derived text is not written to CIO memory. Only sourced
  facts and the answer's sourced skeleton are written.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import math
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

AUTHORITY = "READ_ONLY_ADVISORY"
LANE_ID = "cio-ask-research"
#: Proposed governed process id for the panel. It is NOT registered in config/llm_process_registry.json until
#: the operator approves its spend cap. Until then the governor refuses every panel call (PROCESS_NOT_REGISTERED).
PROCESS_ID = "cio_ask_research_panel"
FACT_SCHEMA = "AskResearchFact@v1"
RUN_SCHEMA = "AskResearchRun@v1"
MEMORY_SCHEMA = "AskResearchMemoryEvent@v1"
HORIZONS = ("3m", "6m", "12m")
CASES = ("bear", "base", "bull")
STANCES = ("bullish", "neutral", "bearish")
DEFAULT_PER_QUESTION_USD = 0.30
SIZE_SUGGESTION_POLICY = (
    "WITHHELD: MBI_BEHAVIOR=0; size_suggestion needs AGENTS >= 21.0.0 ACTIVE (operator decision pending)"
)

# --------------------------------------------------------------------------------------------------- contract
# The shared contract (AskRequest@v1 / AskAnswer@v1) is owned by the Phase 8/10/11 agent in
# scripts/lib/cio_ask_contract.py. Until it lands this module drafts against the described shape and
# reconciles through these three hooks only.
try:  # pragma: no cover - exercised once the contract module lands
    from scripts.lib import cio_ask_contract as _contract  # type: ignore
except Exception:  # noqa: BLE001
    try:
        import lib.cio_ask_contract as _contract  # type: ignore
    except Exception:  # noqa: BLE001
        _contract = None

ASK_REQUEST_SCHEMA = getattr(_contract, "ASK_REQUEST_SCHEMA", "AskRequest@v1")
ASK_ANSWER_SCHEMA = getattr(_contract, "ASK_ANSWER_SCHEMA", "AskAnswer@v1")


def contract_source() -> str:
    return "scripts.lib.cio_ask_contract" if _contract is not None else "DRAFT_LOCAL (contract module not landed)"


# --------------------------------------------------------------------------------------------------- helpers
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):  # date
        return value.isoformat()
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return _iso(dt)
    except ValueError:
        return None


def _sha(*parts: Any, n: int = 16) -> str:
    h = hashlib.sha256("\x1f".join("" if p is None else str(p) for p in parts).encode("utf-8"))
    return h.hexdigest()[:n]


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _imp(*names: str):
    """Import the first module that resolves among ``names`` (repo uses both ``lib.x`` and ``scripts.lib.x``)."""
    import importlib

    last: Exception | None = None
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise ImportError(f"none of {names} importable: {last}")


# --------------------------------------------------------------------------------------------------- facts
class FactRejected(ValueError):
    """A fact without ``as_of`` or ``citation`` never enters the answer."""


@dataclass(frozen=True)
class Fact:
    source: str  # e.g. "internal.catalysts", "web.brave", "sec.filings", "street.targets"
    family: str  # internal | web | sec | news | street | market
    kind: str  # catalyst | news | filing | fundamental | target | price | thesis | prospect | ...
    subject_key: str  # security_guid (listed) or issuer_guid (private tracked entity)
    claim: str
    as_of: str
    citation: dict[str, Any]
    value: Optional[float] = None
    unit: Optional[str] = None
    field: Optional[str] = None
    symbol: Optional[str] = None
    egress: str = "model_ok"  # model_ok | local_only (§2A: holdings/trades/sizing never leave the box)

    @property
    def fact_id(self) -> str:
        return "f_" + _sha(
            self.source, self.kind, self.subject_key, self.field, self.claim, self.value, self.as_of, n=12
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fact_id"] = self.fact_id
        d["schema"] = FACT_SCHEMA
        return d


def make_fact(
    *,
    source: str,
    family: str,
    kind: str,
    subject_key: str,
    claim: str,
    as_of: Any,
    citation: Mapping[str, Any] | str,
    value: Any = None,
    unit: str | None = None,
    field: str | None = None,
    symbol: str | None = None,
    egress: str = "model_ok",
) -> Fact:
    as_of_iso = _iso(as_of)
    if not as_of_iso:
        raise FactRejected(f"{source}: fact without as_of ({claim[:60]!r})")
    cit = {"ref": citation} if isinstance(citation, str) else dict(citation or {})
    if not any(str(v or "").strip() for v in cit.values()):
        raise FactRejected(f"{source}: fact without citation ({claim[:60]!r})")
    cit.setdefault("source", source)
    if not subject_key:
        raise FactRejected(f"{source}: fact without subject_key")
    return Fact(
        source=source,
        family=family,
        kind=kind,
        subject_key=subject_key,
        claim=str(claim)[:600],
        as_of=as_of_iso,
        citation=cit,
        value=_num(value),
        unit=unit,
        field=field,
        symbol=(symbol or None),
        egress=egress,
    )


# --------------------------------------------------------------------------------------------------- entities
@dataclass
class Entity:
    label: str
    kind: str  # listed | private | unresolved
    symbol: Optional[str] = None
    security_guid: Optional[str] = None
    issuer_guid: Optional[str] = None
    identity_status: str = "UNRESOLVED"
    identity_source: str = ""

    @property
    def subject_key(self) -> Optional[str]:
        """Memory key. A listed security is keyed by security_guid (§26.1). A private company has no security,
        so its tracked key is the deterministic issuer_guid (no ticker is invented). Unresolved: None."""
        if self.kind == "listed":
            return self.security_guid
        if self.kind == "private":
            return self.issuer_guid
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["subject_key"] = self.subject_key
        return d


_TICKER_RE = re.compile(r"(?:\$([A-Za-z]{1,5}(?:\.[A-Za-z])?)\b|\b([A-Z]{1,5}(?:\.[A-Z])?)\b)")
_STOP_TOKENS = frozenset(
    {
        "I",
        "A",
        "AN",
        "OR",
        "AND",
        "THE",
        "CIO",
        "AI",
        "IPO",
        "USA",
        "US",
        "CEO",
        "CFO",
        "SEC",
        "ETF",
        "EPS",
        "GDP",
        "FED",
        "TO",
        "IN",
        "ON",
        "OF",
        "IF",
        "IS",
        "IT",
        "AT",
        "BY",
        "MY",
        "ME",
        "DO",
        "SO",
        "NO",
        "BE",
        "VS",
        "OK",
        "Q",
        "M",
        "B",
        "K",
        "YOY",
        "QOQ",
        "ATH",
    }
)


def default_identity_fn(symbol: str) -> dict[str, Any]:
    mod = _imp("scripts.lib.cio_subject_guid", "lib.cio_subject_guid")
    return mod.lookup_identity_envelope(symbol)


def default_name_fn(name: str) -> Optional[dict[str, Any]]:
    mod = _imp("scripts.lib.company_name_index", "lib.company_name_index")
    return mod.resolve_name(name)


def default_issuer_guid_fn(name: str) -> Optional[str]:
    mod = _imp("scripts.lib.security_identity", "lib.security_identity")
    return mod.issuer_guid(company=name)


def _resolve_symbol(symbol: str, label: str, identity_fn: Callable[[str], Mapping[str, Any]]) -> Entity:
    sym = symbol.strip().upper().lstrip("$")
    try:
        env = dict(identity_fn(sym) or {})
    except Exception as exc:  # noqa: BLE001 - an unreadable registry is not an unknown symbol; say which
        return Entity(label=label, kind="unresolved", symbol=sym, identity_status=f"LOOKUP_FAILED:{type(exc).__name__}")
    sec = env.get("security_guid") or (
        env.get("subject_guid") if env.get("entity_type") in (None, "security") else None
    )
    if sec:
        return Entity(
            label=label,
            kind="listed",
            symbol=sym,
            security_guid=str(sec),
            issuer_guid=env.get("issuer_guid"),
            identity_status="RESOLVED",
            identity_source="identity_registry",
        )
    return Entity(
        label=label, kind="unresolved", symbol=sym, identity_status=str(env.get("identity_lookup") or "UNRESOLVED")
    )


def resolve_entity(
    subject: Mapping[str, Any] | str,
    *,
    identity_fn: Callable[[str], Mapping[str, Any]] = default_identity_fn,
    name_fn: Callable[[str], Optional[Mapping[str, Any]]] = default_name_fn,
    issuer_guid_fn: Callable[[str], Optional[str]] = default_issuer_guid_fn,
) -> Entity:
    """One subject → one Entity. Never mints a ticker.

    * ``{"symbol": "TSLA"}`` → the identity registry's security_guid, or ``unresolved`` (identity unresolved: no
      memory record, §26.1).
    * ``{"name": "Skydance"}`` → the broker instrument name index. If it resolves, it is resolved as a symbol.
      Otherwise the company is a **private / unlisted tracked entity**: deterministic ``issuer_guid`` from the
      name, ``symbol=None``, status ``TRACKED_PRIVATE_UNREGISTERED`` (registering it in the identity table is a
      store write the operator grants, §26.6).
    """
    if isinstance(subject, str):
        subject = (
            {"symbol": subject}
            if re.fullmatch(r"\$?[A-Za-z]{1,5}(\.[A-Za-z])?", subject.strip())
            else {"name": subject}
        )
    sym = str(subject.get("symbol") or "").strip()
    name = str(subject.get("name") or "").strip()
    if sym:
        return _resolve_symbol(sym, name or sym.upper(), identity_fn)
    if not name:
        return Entity(label="", kind="unresolved", identity_status="EMPTY_SUBJECT")
    hit = None
    try:
        hit = name_fn(name)
    except Exception:  # noqa: BLE001 - name index unreadable: fall through to private tracking, flagged
        hit = None
    if hit and hit.get("symbol"):
        ent = _resolve_symbol(str(hit["symbol"]), name, identity_fn)
        ent.identity_source = "company_name_index"
        return ent
    try:
        issuer = issuer_guid_fn(name)
    except Exception:  # noqa: BLE001
        issuer = None
    if not issuer:
        return Entity(label=name, kind="unresolved", identity_status="NAME_UNRESOLVED")
    return Entity(
        label=name,
        kind="private",
        symbol=None,
        security_guid=None,
        issuer_guid=str(issuer),
        identity_status="TRACKED_PRIVATE_UNREGISTERED",
        identity_source="security_identity.issuer_guid(company)",
    )


def extract_subjects(question: str, *, known_symbol: Callable[[str], bool] | None = None) -> list[dict[str, Any]]:
    """Cashtags always count. Bare upper-case tokens count only when ``known_symbol`` confirms them (no guessing)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _TICKER_RE.finditer(question or ""):
        cash, bare = m.group(1), m.group(2)
        tok = (cash or bare or "").upper()
        if not tok or tok in seen:
            continue
        if bare and (tok in _STOP_TOKENS or known_symbol is None or not known_symbol(tok)):
            continue
        seen.add(tok)
        out.append({"symbol": tok})
    return out


_QTY_LIST_RE = re.compile(
    r"(?P<nums>\d[\d,]*(?:\.\d+)?\s*[kK]?(?:\s*(?:,|or|and|vs\.?|versus)\s*\d[\d,]*(?:\.\d+)?\s*[kK]?)*)"
    r"\s+(?:shares?\s+(?:of\s+)?)?\$?(?P<sym>[A-Z]{1,5})\b"
)


def parse_named_quantities(question: str) -> list[dict[str, Any]]:
    """Quantities the operator NAMED ("100 or 1,000 TSLA"). Only these get sizing arithmetic. Nothing is proposed."""
    out: list[dict[str, Any]] = []
    for m in _QTY_LIST_RE.finditer(question or ""):
        sym = m.group("sym").upper()
        if sym in _STOP_TOKENS:
            continue
        for raw in re.findall(r"\d[\d,]*(?:\.\d+)?\s*[kK]?", m.group("nums")):
            r = raw.replace(",", "").strip()
            mult = 1000 if r[-1:] in ("k", "K") else 1
            q = _num(r.rstrip("kK"))
            if q and q > 0:
                out.append({"symbol": sym, "quantity": q * mult, "source": "operator_question"})
    return out


# --------------------------------------------------------------------------------------------------- request
def normalize_request(
    request: Mapping[str, Any], *, known_symbol: Callable[[str], bool] | None = None
) -> dict[str, Any]:
    if _contract is not None and hasattr(_contract, "parse_ask_request"):  # pragma: no cover - reconcile hook
        request = _contract.parse_ask_request(request)  # type: ignore[attr-defined]
        if not isinstance(request, Mapping):
            request = asdict(request) if hasattr(request, "__dataclass_fields__") else dict(request)
    q = str(request.get("question") or "").strip()
    if not q:
        raise ValueError("AskRequest without question")
    subjects = list(request.get("subjects") or []) or extract_subjects(q, known_symbol=known_symbol)
    named = list(request.get("named_quantities") or []) or parse_named_quantities(q)
    return {
        "schema": ASK_REQUEST_SCHEMA,
        "request_id": str(request.get("request_id") or "ask_" + _sha(q, request.get("asked_at"), n=12)),
        "question": q,
        "asked_at": _iso(request.get("asked_at")) or _iso(_now()),
        "channel": str(request.get("channel") or "unknown"),
        "mode": str(request.get("mode") or "deep"),
        "subjects": subjects,
        "named_quantities": named,
    }


# --------------------------------------------------------------------------------------------------- context
@dataclass
class ResearchContext:
    question: str
    db_query: Optional[Callable[..., Any]] = None
    dry_run: bool = False
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    now: datetime = field(default_factory=_now)


SourceFn = Callable[[Entity, ResearchContext], list[Fact]]


@dataclass(frozen=True)
class SourceSpec:
    name: str
    family: str
    fn: SourceFn
    timeout_s: float = 8.0
    needs_symbol: bool = True  # private entities only get sources that work on a name


# --------------------------------------------------------------------------------------------------- gather
def gather_facts(
    entities: Sequence[Entity], sources: Sequence[SourceSpec], ctx: ResearchContext, *, max_workers: int = 8
) -> dict[str, Any]:
    """Run every (entity × source) in parallel, each under its own timeout.

    A timeout, an exception or a fact without as_of/citation becomes a named gap, never a silent drop. The pool
    is abandoned on return (no join on a hung source), so one slow source cannot hold the answer.
    """
    jobs: list[tuple[Entity, SourceSpec]] = []
    gaps: list[dict[str, Any]] = []
    for ent in entities:
        if not ent.subject_key:
            gaps.append({"subject": ent.label, "source": "*", "reason": f"IDENTITY_{ent.identity_status}"})
            continue
        for spec in sources:
            if spec.needs_symbol and not ent.symbol:
                gaps.append({"subject": ent.label, "source": spec.name, "reason": "NOT_APPLICABLE_PRIVATE_ENTITY"})
                continue
            jobs.append((ent, spec))
    facts: list[Fact] = []
    runs: list[dict[str, Any]] = []
    if not jobs:
        return {"facts": facts, "gaps": gaps, "runs": runs}
    pool = cf.ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(jobs))), thread_name_prefix="ask-gather")
    started = time.monotonic()
    pending: dict[cf.Future, tuple[Entity, SourceSpec, float]] = {}
    for ent, spec in jobs:
        pending[pool.submit(spec.fn, ent, ctx)] = (ent, spec, started + float(spec.timeout_s))
    try:
        while pending:
            next_deadline = min(d for _, _, d in pending.values())
            done, _ = cf.wait(
                list(pending), timeout=max(0.0, next_deadline - time.monotonic()), return_when=cf.FIRST_COMPLETED
            )
            for fut in done:
                ent, spec, _ = pending.pop(fut)
                elapsed = round(time.monotonic() - started, 3)
                try:
                    produced = list(fut.result() or [])
                except FactRejected as exc:
                    gaps.append(
                        {"subject": ent.label, "source": spec.name, "reason": "FACT_REJECTED", "detail": str(exc)[:200]}
                    )
                    runs.append({"source": spec.name, "subject": ent.label, "status": "rejected", "elapsed_s": elapsed})
                    continue
                except Exception as exc:  # noqa: BLE001
                    gaps.append(
                        {
                            "subject": ent.label,
                            "source": spec.name,
                            "reason": "SOURCE_ERROR",
                            "detail": f"{type(exc).__name__}: {str(exc)[:160]}",
                        }
                    )
                    runs.append({"source": spec.name, "subject": ent.label, "status": "error", "elapsed_s": elapsed})
                    continue
                kept = 0
                for f in produced:
                    if not isinstance(f, Fact) or not f.as_of or not f.citation:
                        gaps.append(
                            {
                                "subject": ent.label,
                                "source": spec.name,
                                "reason": "FACT_REJECTED",
                                "detail": "missing as_of or citation",
                            }
                        )
                        continue
                    facts.append(f)
                    kept += 1
                if not kept:
                    gaps.append({"subject": ent.label, "source": spec.name, "reason": "NO_DATA"})
                runs.append(
                    {"source": spec.name, "subject": ent.label, "status": "ok", "facts": kept, "elapsed_s": elapsed}
                )
            now_m = time.monotonic()
            for fut in [f for f, (_, _, d) in pending.items() if d <= now_m]:
                ent, spec, _ = pending.pop(fut)
                fut.cancel()
                gaps.append(
                    {"subject": ent.label, "source": spec.name, "reason": "TIMEOUT", "timeout_s": spec.timeout_s}
                )
                runs.append(
                    {
                        "source": spec.name,
                        "subject": ent.label,
                        "status": "timeout",
                        "elapsed_s": round(now_m - started, 3),
                    }
                )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    # de-duplicate identical facts from overlapping sources
    uniq: dict[str, Fact] = {}
    for f in facts:
        uniq.setdefault(f.fact_id, f)
    return {"facts": list(uniq.values()), "gaps": gaps, "runs": runs}


# --------------------------------------------------------------------------------------------------- default sources
def _db(ctx: ResearchContext) -> Callable[..., Any]:
    if ctx.db_query is not None:
        return ctx.db_query
    mod = _imp("db_adapter", "scripts.db_adapter")

    def query(sql: str, params: Any = None, fetch: str = "all") -> Any:
        # data-broker readers call db_query(sql, params) and expect rows; _execute defaults to fetch=None (a bool)
        return mod._execute(sql, params, fetch=fetch)

    return query


def _src_prospect(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    mod = _imp("lib.data_broker.cio_prospect", "scripts.lib.data_broker.cio_prospect")
    res = mod.get_prospect(ent.security_guid or ent.symbol, db_query=_db(ctx))
    p = res.get("prospect") or {}
    if not p:
        return []
    as_of = p.get("evidence_at") or p.get("updated_at") or res.get("as_of")
    cit = {"store": "cio_prospect", "projection": "data_broker.cio_prospect", "security_guid": ent.security_guid}
    out = [
        make_fact(
            source="internal.cio_prospect",
            family="internal",
            kind="prospect",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=f"CIO prospect: stage {p.get('stage')}, stance {p.get('stance')}, "
            f"conviction {p.get('conviction')}; next trigger {p.get('next_trigger')}; missing {p.get('what_is_missing')}",
            as_of=as_of,
            citation=cit,
            field="conviction",
            value=p.get("conviction"),
            unit="score_0_100",
        )
    ]
    for c in p.get("conflicts") or []:
        out.append(
            make_fact(
                source="internal.cio_prospect",
                family="internal",
                kind="conflict",
                subject_key=ent.subject_key,
                symbol=ent.symbol,
                claim=f"Recorded conflict: {json.dumps(c, default=str)[:300]}",
                as_of=as_of,
                citation=cit,
            )
        )
    return out


def _src_holdings(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    """Held flag only, through the data-broker held reader (no qty, no dollars). local_only (§2A)."""
    mod = _imp("lib.data_broker.watch_domains", "scripts.lib.data_broker.watch_domains")
    h = mod.held_positions(db_query=_db(ctx), surface="cio_ask")
    held = ent.symbol in set(h.get("symbols") or set())
    return [
        make_fact(
            source="internal.holdings",
            family="internal",
            kind="held",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=f"{ent.symbol} is {'held' if held else 'not held'} (held flag)",
            as_of=h.get("as_of"),
            citation={"reader": "data_broker.watch_domains.held_positions", "source": h.get("source")},
            field="held",
            value=1 if held else 0,
            egress="local_only",
        )
    ]


def _src_thesis(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    mod = _imp("lib.symbol_thesis_attach", "scripts.lib.symbol_thesis_attach")
    t = mod.thesis_fields_for_symbol(ent.symbol) or {}
    if not t or t.get("thesis_state") in (None, "INSUFFICIENT_DATA"):
        return []
    as_of = t.get("updated_at") or t.get("thesis_updated_at") or t.get("as_of") or t.get("evidence_at")
    cit = {"store": "symbol_thesis", "thesis_id": t.get("symbol_thesis_id"), "version": t.get("symbol_thesis_version")}
    out = [
        make_fact(
            source="internal.thesis",
            family="internal",
            kind="thesis",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=f"Thesis ({t.get('thesis_state')}): {t.get('why_owned_or_watched') or ''}",
            as_of=as_of,
            citation=cit,
        )
    ]
    for inv in (t.get("invalidation_conditions") or [])[:4]:
        out.append(
            make_fact(
                source="internal.thesis",
                family="internal",
                kind="risk",
                subject_key=ent.subject_key,
                symbol=ent.symbol,
                claim=f"Thesis invalidation condition: {inv}",
                as_of=as_of,
                citation=cit,
            )
        )
    return out


def _src_catalysts(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    mod = _imp("lib.data_broker.catalyst_record", "scripts.lib.data_broker.catalyst_record")
    rows = mod.get_symbol_catalysts(_db(ctx), ent.symbol, days=120, limit=8)
    return [
        make_fact(
            source="internal.catalysts",
            family="internal",
            kind="catalyst",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=f"[{r.get('catalyst_type')}] {r.get('headline')}"
            f"{' (verified)' if r.get('verified') else ' (unverified)'}",
            as_of=r.get("at"),
            citation={"store": "catalyst_events", "url": r.get("source_url")},
        )
        for r in rows
        if r.get("at")
    ]


def _src_research(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    mod = _imp("lib.data_broker.subject_research", "scripts.lib.data_broker.subject_research")
    res = mod.get_subject_research(_db(ctx), symbol=ent.symbol, limit=5)
    out = []
    for it in res.get("items") or []:
        out.append(
            make_fact(
                source="internal.hermes_research",
                family="internal",
                kind="research",
                subject_key=ent.subject_key,
                symbol=ent.symbol,
                claim=f"{it.get('research_type') or 'research'}: {(it.get('summary') or it.get('thesis') or '')[:400]}",
                as_of=it.get("created_at"),
                citation={
                    "store": "hermes_research_intelligence",
                    "id": it.get("id"),
                    "agent": it.get("hermes_agent_name"),
                },
            )
        )
    return out


def _src_alerts(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    rows = (
        _db(ctx)(
            "SELECT id, alert_type, severity, created_at FROM alert_events WHERE upper(symbol)=%s "
            "ORDER BY created_at DESC LIMIT 8",
            (ent.symbol,),
            fetch="all",
        )
        or []
    )
    return [
        make_fact(
            source="internal.alerts",
            family="internal",
            kind="alert",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=f"Alert {r.get('alert_type')} ({r.get('severity')})",
            as_of=r.get("created_at"),
            citation={"store": "alert_events", "id": r.get("id")},
        )
        for r in rows
        if r.get("created_at")
    ]


def _src_trades(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    """Past fills: action and date only (no account, no quantity, no price). local_only (§2A)."""
    rows = (
        _db(ctx)(
            "SELECT id, action, trade_date FROM trade_transactions WHERE upper(symbol)=%s "
            "ORDER BY trade_date DESC LIMIT 8",
            (ent.symbol,),
            fetch="all",
        )
        or []
    )
    return [
        make_fact(
            source="internal.trades",
            family="internal",
            kind="trade",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=f"Past fill: {r.get('action')}",
            as_of=r.get("trade_date"),
            citation={"store": "trade_transactions", "id": r.get("id")},
            egress="local_only",
        )
        for r in rows
        if r.get("trade_date")
    ]


def _src_price(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    mod = _imp("lib.data_broker.market_quote", "scripts.lib.data_broker.market_quote")
    q = (mod.get_price_batch(_db(ctx), [ent.symbol], max_age_hours=96, skip_live=True) or {}).get(ent.symbol)
    if not q or _num(q.get("price")) is None:
        return []
    return [
        make_fact(
            source="market.quote",
            family="market",
            kind="price",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=f"{ent.symbol} last price {q['price']}",
            as_of=q.get("as_of"),
            citation={"projection": "data_broker.latest_quote", "source": q.get("source")},
            field="last_price",
            value=q["price"],
            unit="usd",
        )
    ]


def _src_street(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    """Street consensus: yahoo_analyst_targets_history (DB) and the pro_analyst read model. Both are kept: a
    disagreement is shown, never resolved silently (§26.5)."""
    out: list[Fact] = []
    det = _imp("lib.data_broker.analyst_detail", "scripts.lib.data_broker.analyst_detail")
    t = (det.get_analyst_targets(_db(ctx), [ent.symbol]) or {}).get(ent.symbol) or {}
    cit = {"store": "yahoo_analyst_targets_history", "reader": "data_broker.analyst_detail"}
    for fld, key in (
        ("target_low", "target_low"),
        ("target_mean", "target_mean"),
        ("target_high", "target_high"),
        ("analyst_count", "analyst_count"),
    ):
        if _num(t.get(key)) is not None and t.get("created_at"):
            out.append(
                make_fact(
                    source="street.yahoo_targets",
                    family="street",
                    kind="target",
                    subject_key=ent.subject_key,
                    symbol=ent.symbol,
                    claim=f"Street {fld.replace('_', ' ')}: {t.get(key)}",
                    as_of=t["created_at"],
                    citation=cit,
                    field=fld,
                    value=t.get(key),
                    unit="count" if fld == "analyst_count" else "usd",
                )
            )
    try:
        roll = _imp("lib.data_broker.analyst_rollup", "scripts.lib.data_broker.analyst_rollup")
        r = (roll.get_analyst_rollup([ent.symbol]) or {}).get(ent.symbol) or {}
    except Exception:  # noqa: BLE001
        r = {}
    rcit = {"store": "pro_analyst_pills_latest.json", "reader": "data_broker.analyst_rollup"}
    for fld, key in (("target_low", "target_low"), ("target_mean", "mean_target"), ("target_high", "target_high")):
        if _num(r.get(key)) is not None and r.get("as_of"):
            out.append(
                make_fact(
                    source="street.pro_analyst",
                    family="street",
                    kind="target",
                    subject_key=ent.subject_key,
                    symbol=ent.symbol,
                    claim=f"Pro-analyst {fld.replace('_', ' ')}: {r.get(key)}",
                    as_of=r["as_of"],
                    citation=rcit,
                    field=fld,
                    value=r.get(key),
                    unit="usd",
                )
            )
    return out


def _src_sec_filings(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    mod = _imp("lib.sec_filing_documents", "scripts.lib.sec_filing_documents")
    rows = mod.load_primary_disclosures(ent.symbol, execute=_db(ctx), limit=3, max_facts=10)
    out = []
    for d in rows:
        out.append(
            make_fact(
                source="sec.filings",
                family="sec",
                kind="filing",
                subject_key=ent.subject_key,
                symbol=ent.symbol,
                claim=f"{d.get('form')} {d.get('category')}: {d.get('fact')}",
                as_of=d.get("date"),
                citation={"url": d.get("url"), "accession": d.get("accession")},
                field=f"disclosure_{d.get('category')}" if _num(d.get("amount")) is not None else None,
                value=d.get("amount"),
                unit="usd" if _num(d.get("amount")) is not None else None,
            )
        )
    return out


def _src_sec_fundamentals(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    mod = _imp("lib.fundamentals_feed", "scripts.lib.fundamentals_feed")
    card = mod.card_block(ent.symbol, _db(ctx)) or {}
    if card.get("state") not in ("FRESH", "STALE"):
        return []
    as_of = card.get("latest_quarter_end")
    cit = {"store": "sec_xbrl", "url": card.get("filing_url"), "freshness": card.get("state")}
    out = [
        make_fact(
            source="sec.fundamentals",
            family="sec",
            kind="fundamental",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=str(line),
            as_of=as_of,
            citation=cit,
        )
        for line in card.get("lines") or []
    ]
    for fld in ("gross_margin_pct", "operating_margin_pct"):
        if _num(card.get(fld)) is not None:
            out.append(
                make_fact(
                    source="sec.fundamentals",
                    family="sec",
                    kind="fundamental",
                    subject_key=ent.subject_key,
                    symbol=ent.symbol,
                    claim=f"{fld.replace('_', ' ')}: {card[fld]}",
                    as_of=as_of,
                    citation=cit,
                    field=fld,
                    value=card[fld],
                    unit="pct",
                )
            )
    return out


def _src_news(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    mod = _imp("lib.data_broker.catalyst_record", "scripts.lib.data_broker.catalyst_record")
    rows = mod.get_symbol_news(_db(ctx), ent.symbol, days=30, limit=6)
    return [
        make_fact(
            source="news.articles",
            family="news",
            kind="news",
            subject_key=ent.subject_key,
            symbol=ent.symbol,
            claim=f"{r.get('source')}: {r.get('title')}",
            as_of=r.get("published_at"),
            citation={"store": "news_articles", "url": r.get("url")},
        )
        for r in rows
        if r.get("published_at")
    ]


def _src_web(ent: Entity, ctx: ResearchContext) -> list[Fact]:
    """Governed web search: the search routing engine as caller ``web_research`` (class ``operator``: a question
    the operator asked). Its cache, free tiers, Brave budget reservation and receipts apply unchanged. A dry run
    plans without touching a provider."""
    mod = _imp("lib.search_router", "scripts.lib.search_router")
    q = f"{ent.symbol or ent.label} {ctx.question}"[:240]
    resp = mod.route_query(q, caller="web_research", symbol=ent.symbol, kind="web", count=5, dry_run=ctx.dry_run)
    out = []
    for r in getattr(resp, "results", None) or []:
        url = r.get("url")
        published = _iso(r.get("published_at"))
        out.append(
            make_fact(
                source=f"web.{getattr(resp, 'provider', '') or 'search'}",
                family="web",
                kind="web",
                subject_key=ent.subject_key,
                symbol=ent.symbol,
                claim=f"{r.get('title')}: {(r.get('description') or r.get('snippet') or '')[:300]}",
                as_of=published or _iso(ctx.now),
                citation={
                    "url": url,
                    "as_of_basis": "published_at" if published else "retrieved_at",
                    "receipt": (getattr(resp, "receipt", None) or {}).get("receipt_id")
                    if isinstance(getattr(resp, "receipt", None), dict)
                    else None,
                },
            )
        )
    return out


def default_sources() -> list[SourceSpec]:
    return [
        SourceSpec("internal.cio_prospect", "internal", _src_prospect, 6.0),
        SourceSpec("internal.holdings", "internal", _src_holdings, 6.0),
        SourceSpec("internal.thesis", "internal", _src_thesis, 6.0),
        SourceSpec("internal.catalysts", "internal", _src_catalysts, 6.0),
        SourceSpec("internal.hermes_research", "internal", _src_research, 6.0),
        SourceSpec("internal.alerts", "internal", _src_alerts, 6.0),
        SourceSpec("internal.trades", "internal", _src_trades, 6.0),
        SourceSpec("market.quote", "market", _src_price, 6.0),
        SourceSpec("street.targets", "street", _src_street, 6.0),
        SourceSpec("sec.filings", "sec", _src_sec_filings, 8.0),
        SourceSpec("sec.fundamentals", "sec", _src_sec_fundamentals, 8.0),
        SourceSpec("news.articles", "news", _src_news, 6.0),
        SourceSpec("web.search", "web", _src_web, 20.0, needs_symbol=False),
    ]


# --------------------------------------------------------------------------------------------------- MBI guard
#: Keys a model may never return (BEHAVIOR_FIELDS in cio_instrument_record plus sizing synonyms).
BEHAVIOR_KEYS = frozenset(
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
        "size",
        "position_size",
        "weight",
        "allocation",
        "stop_price",
        "stop_loss",
        "limit_price",
        "size_suggestion",
        "recommended_quantity",
        "share_count",
    }
)
_SIZING_RE = re.compile(
    r"(\b\d[\d,]*(?:\.\d+)?\s*[kK]?\s*(?:shares?|contracts?|lots?|units)\b"
    r"|\bposition[- ]siz\w*|\bsize\s+(?:it|this|the|your|up|down)\b|\ballocat\w*\s+(?:\$|\d)"
    r"|\b(?:buy|sell|short|add|trim|purchase|acquire|accumulate)\s+(?:\$?\d|some|half|a\s+(?:small|full|starter))"
    r"|\bstop[- ]loss\b|\bstop\s+(?:at|of|below|above)\b|\b(?:limit|market)\s+order\b|\btarget\s+weight\b"
    r"|\b\d+(?:\.\d+)?\s*%\s+of\s+(?:the\s+|your\s+)?(?:portfolio|account|book|capital|nav)\b"
    r"|\b(?:i|we)\s+(?:would|recommend|suggest)\s+(?:buy|sell|go\s+with|choose|pick)\b"
    r"|\b(?:go|stick)\s+with\s+(?:the\s+)?\d)",
    re.I,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


def _imperative(text: str) -> Optional[str]:
    try:
        mod = _imp("scripts.lib.execution_language", "lib.execution_language")
        return mod.find_imperative(text)
    except ImportError:
        return None


def strip_behavior_text(text: str, *, where: str, log: list[dict[str, Any]]) -> str:
    """Drop every sentence that sizes, orders, stops or weights. Log what was dropped (never silently)."""
    if not text:
        return text
    kept = []
    for sent in _SENTENCE_RE.split(str(text)):
        if not sent.strip():
            continue
        m = _SIZING_RE.search(sent)
        reason = f"sizing_pattern:{m.group(0)[:40]}" if m else None
        if reason is None:
            imp = _imperative(sent)
            reason = f"execution_imperative:{imp[:40]}" if imp else None
        if reason:
            log.append({"where": where, "reason": reason, "excerpt": sent.strip()[:160], "excerpt_sha": _sha(sent)})
            continue
        kept.append(sent.strip())
    return " ".join(kept)


def strip_behavior(obj: Any, *, where: str, log: list[dict[str, Any]]) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in BEHAVIOR_KEYS:
                log.append(
                    {
                        "where": f"{where}.{k}",
                        "reason": "behavior_key",
                        "excerpt": json.dumps(v, default=str)[:160],
                        "excerpt_sha": _sha(k, v),
                    }
                )
                continue
            out[k] = strip_behavior(v, where=f"{where}.{k}", log=log)
        return out
    if isinstance(obj, list):
        return [strip_behavior(v, where=f"{where}[{i}]", log=log) for i, v in enumerate(obj)]
    if isinstance(obj, str):
        return strip_behavior_text(obj, where=where, log=log)
    return obj


# --------------------------------------------------------------------------------------------------- grounding
_NUM_TOKEN_RE = re.compile(r"(?<![\w.])\$?(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB](?![a-z]))?")


def ungrounded_numbers(text: str, values: Iterable[float], *, rel_tol: float = 0.005) -> list[str]:
    """Numeric tokens in ``text`` that match no fact value. Horizon months (≤ 24) and years are not claims."""
    vals = [v for v in values if v is not None]
    bad = []
    for m in _NUM_TOKEN_RE.finditer(text or ""):
        raw = m.group(1).replace(",", "")
        x = _num(raw)
        if x is None:
            continue
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
        x *= mult
        if x <= 24 and float(x).is_integer():
            continue
        if 1900 <= x <= 2100 and float(x).is_integer() and mult == 1:
            continue
        if any(math.isclose(x, v, rel_tol=rel_tol) or math.isclose(x / mult, v, rel_tol=rel_tol) for v in vals):
            continue
        bad.append(m.group(0).strip())
    return bad


def sourced_values(facts: Iterable[Fact]) -> list[float]:
    """Numbers a model may quote: fact values plus numbers printed in a sourced claim (model_ok facts only)."""
    out: list[float] = []
    for f in facts:
        if f.egress != "model_ok":
            continue
        if f.value is not None:
            out.append(f.value)
        for m in _NUM_TOKEN_RE.finditer(f.claim or ""):
            x = _num(m.group(1).replace(",", ""))
            if x is not None:
                out.append(x * {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1))
    return out


def ground_text(text: str, values: Sequence[float], *, where: str, log: list[dict[str, Any]]) -> str:
    """Drop sentences that carry a number no fact supports (no invented targets)."""
    kept = []
    for sent in _SENTENCE_RE.split(str(text or "")):
        if not sent.strip():
            continue
        bad = ungrounded_numbers(sent, values)
        if bad:
            log.append(
                {"where": where, "reason": "ungrounded_number", "numbers": bad[:5], "excerpt": sent.strip()[:160]}
            )
            continue
        kept.append(sent.strip())
    return " ".join(kept)


# --------------------------------------------------------------------------------------------------- cost
class CostGovernor:
    """Per-question cap here, then the existing reservation ledger (process daily cap + global cap).

    ``check_fn`` defaults to ``llm_consumption.check_cost_cap``. Any error refuses (fail closed). The in-process
    model call (``llm_lane.generate`` → ``gate_and_generate``) reserves and settles the real spend. This governor
    only decides admission before a call is made.
    """

    def __init__(
        self,
        *,
        per_question_usd: float | None = None,
        process_id: str = PROCESS_ID,
        check_fn: Callable[..., Mapping[str, Any]] | None = None,
        registered_fn: Callable[[str], bool] | None = None,
        global_cap: float | None = None,
    ):
        env_cap = _num(os.environ.get("CIO_ASK_RESEARCH_PER_QUESTION_USD"))
        self.per_question_usd = float(
            per_question_usd
            if per_question_usd is not None
            else (env_cap if env_cap is not None else DEFAULT_PER_QUESTION_USD)
        )
        self.process_id = process_id
        self._check_fn = check_fn
        self._registered_fn = registered_fn
        self.global_cap = global_cap
        self.admitted_usd = 0.0
        self.decisions: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def _registered(self) -> bool:
        if self._registered_fn is not None:
            return bool(self._registered_fn(self.process_id))
        try:
            reg = json.loads((Path(__file__).resolve().parents[2] / "config" / "llm_process_registry.json").read_text())
            return any(
                p.get("id") == self.process_id and p.get("daily_cost_cap_usd") is not None
                for p in reg.get("processes") or []
            )
        except Exception:  # noqa: BLE001
            return False

    def _check(self, projected: float) -> Mapping[str, Any]:
        if self._check_fn is not None:
            return self._check_fn(self.process_id, projected_usd=projected, global_cap=self.global_cap)
        mod = _imp("scripts.lib.llm_consumption", "lib.llm_consumption")
        gcap = self.global_cap
        if gcap is None:
            try:
                gcap = _imp("scripts.lib.llm_spend", "lib.llm_spend").configured_global_cap()
            except Exception:  # noqa: BLE001
                gcap = None
        return mod.check_cost_cap(self.process_id, projected_usd=projected, global_cap=gcap)

    def admit(self, member: str, est_usd: float) -> tuple[bool, str]:
        with self._lock:
            reason = "ADMITTED"
            ok = True
            if not self._registered():
                ok, reason = False, "PROCESS_NOT_REGISTERED"
            elif self.admitted_usd + est_usd > self.per_question_usd + 1e-9:
                ok, reason = False, "PER_QUESTION_CAP_EXCEEDED"
            else:
                try:
                    d = dict(self._check(est_usd) or {})
                except Exception as exc:  # noqa: BLE001 - never fail open
                    d = {"allow": False, "reason": f"BUDGET_UNAVAILABLE:{type(exc).__name__}"}
                if not d.get("allow"):
                    ok, reason = False, str(d.get("reason") or "COST_CAP_EXCEEDED")
            if ok:
                self.admitted_usd += est_usd
            self.decisions.append({"member": member, "est_usd": est_usd, "admitted": ok, "reason": reason})
            return ok, reason

    def summary(self) -> dict[str, Any]:
        return {
            "process_id": self.process_id,
            "per_question_cap_usd": self.per_question_usd,
            "admitted_projected_usd": round(self.admitted_usd, 6),
            "decisions": list(self.decisions),
        }


# --------------------------------------------------------------------------------------------------- panel
@dataclass
class PanelMember:
    name: str  # deepseek | grok | chatgpt | claude_oversight
    call: Callable[[str], str]
    est_usd: float = 0.02
    timeout_s: float = 90.0


def default_panel() -> list[PanelMember]:
    """DeepSeek (metered), Grok and ChatGPT (OAuth) through the existing governed generation helper, as the one
    process ``PROCESS_ID``. With TRADEAI_LLM_VIA_BRIDGE on, the bridge walks the registry route instead. There is
    no governed Claude process for this path, so Claude oversight is recorded as unavailable, not improvised."""

    def _lane(lane: str) -> Callable[[str], str]:
        def call(prompt: str) -> str:
            mod = _imp("lib.governed_cloud_generation", "scripts.lib.governed_cloud_generation")
            text, _ = mod.generate_cloud(
                prompt,
                process_id=PROCESS_ID,
                task_summary="ask_the_cio_research_panel",
                lanes=(lane,),
                max_tokens=1500,
                response_json=True,
                timeout=90,
            )
            return text

        return call

    return [
        PanelMember("deepseek", _lane("deepseek-flash"), est_usd=0.01),
        PanelMember("grok", _lane("grok"), est_usd=0.0),
        PanelMember("chatgpt", _lane("chatgpt"), est_usd=0.0),
    ]


PANEL_INSTRUCTIONS = (
    "You are one member of a research panel for an investment committee. Use ONLY the facts below; cite fact_ids. "
    "Do not invent prices, targets or dates. For each subject and each horizon (3m, 6m, 12m) give bear/base/bull "
    "cases: name the fact_id whose value anchors the case (or null when no fact anchors it) and state the "
    "assumption. Never recommend a quantity, an order, a stop, a weight or a position size. Reply with JSON only: "
    '{"subjects":[{"subject_key":"...","stance":"bullish|neutral|bearish","summary":"...",'
    '"horizons":{"3m":{"bear":{"anchor_fact_id":null,"assumption":"..."},"base":{...},"bull":{...}},"6m":{...},"12m":{...}},'
    '"risks":[{"text":"...","fact_ids":["..."]}],"what_changes_view":["..."]}]}'
)


def build_panel_prompt(question: str, entities: Sequence[Entity], facts: Sequence[Fact]) -> str:
    """One prompt, identical for every member. local_only facts (holdings, trades) are excluded (§2A)."""
    table = [
        {
            "fact_id": f.fact_id,
            "subject_key": f.subject_key,
            "symbol": f.symbol,
            "kind": f.kind,
            "claim": f.claim,
            "value": f.value,
            "unit": f.unit,
            "as_of": f.as_of,
        }
        for f in sorted(facts, key=lambda x: (x.subject_key, x.kind, x.fact_id))
        if f.egress == "model_ok"
    ]
    subjects = [
        {"subject_key": e.subject_key, "label": e.label, "symbol": e.symbol, "kind": e.kind}
        for e in entities
        if e.subject_key
    ]
    body = json.dumps({"question": question, "subjects": subjects, "facts": table}, sort_keys=True, default=str)
    prompt = PANEL_INSTRUCTIONS + "\n\nINPUT:\n" + body
    try:
        san = _imp("scripts.lib.cio_egress_sanitiser", "lib.cio_egress_sanitiser")
        # A new caller always takes the redacted copy, whatever TRADEAI_EGRESS_SANITISER's mode (more restrictive).
        res = san.sanitise_for_external([{"role": "user", "content": prompt}], PROCESS_ID) or {}
        msgs = res.get("messages")
        if msgs:
            prompt = str(msgs[0].get("content") or prompt)
    except Exception:  # noqa: BLE001 - sanitiser absent: local_only facts are already excluded above
        pass
    return prompt


def _parse_json(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            v = json.loads(m.group(0))
            return v if isinstance(v, dict) else None
        except ValueError:
            return None
    return None


def run_panel(
    prompt: str, members: Sequence[PanelMember], governor: CostGovernor, *, mbi_log: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every member sees the same prompt (``prompt_sha`` proves it). Admission first, then parallel calls."""
    prompt_sha = _sha(prompt, n=32)
    opinions: list[dict[str, Any]] = []
    admitted: list[PanelMember] = []
    for m in members:
        ok, reason = governor.admit(m.name, m.est_usd)
        if ok:
            admitted.append(m)
        else:
            opinions.append({"member": m.name, "ok": False, "refusal": reason, "prompt_sha": prompt_sha})
    if not admitted:
        return opinions
    pool = cf.ThreadPoolExecutor(max_workers=len(admitted), thread_name_prefix="ask-panel")
    futs = {pool.submit(m.call, prompt): m for m in admitted}
    try:
        deadline = time.monotonic() + max(m.timeout_s for m in admitted)
        done, not_done = cf.wait(list(futs), timeout=max(0.0, deadline - time.monotonic()))
        for fut in not_done:
            fut.cancel()
            opinions.append({"member": futs[fut].name, "ok": False, "refusal": "TIMEOUT", "prompt_sha": prompt_sha})
        for fut in done:
            m = futs[fut]
            try:
                raw = fut.result()
            except Exception as exc:  # noqa: BLE001
                opinions.append(
                    {
                        "member": m.name,
                        "ok": False,
                        "refusal": f"MODEL_ERROR:{type(exc).__name__}:{str(exc)[:120]}",
                        "prompt_sha": prompt_sha,
                    }
                )
                continue
            parsed = _parse_json(raw)
            if parsed is None:
                # unparseable prose is still scanned so a sizing sentence is logged, never shown
                strip_behavior_text(str(raw or ""), where=f"panel.{m.name}.raw", log=mbi_log)
                opinions.append({"member": m.name, "ok": False, "refusal": "SCHEMA_INVALID", "prompt_sha": prompt_sha})
                continue
            clean = strip_behavior(parsed, where=f"panel.{m.name}", log=mbi_log)
            opinions.append({"member": m.name, "ok": True, "prompt_sha": prompt_sha, "output": clean})
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    opinions.sort(key=lambda o: o["member"])
    return opinions


# --------------------------------------------------------------------------------------------------- synthesis
def _latest(facts: Iterable[Fact], *, kind: str, field_name: str) -> list[Fact]:
    rows = [f for f in facts if f.kind == kind and f.field == field_name and f.value is not None]
    return sorted(rows, key=lambda f: f.as_of, reverse=True)


def _fact_ref(f: Optional[Fact]) -> Optional[dict[str, Any]]:
    if f is None:
        return None
    return {
        "value": f.value,
        "unit": f.unit,
        "as_of": f.as_of,
        "fact_id": f.fact_id,
        "source": f.source,
        "citation": f.citation,
    }


def _street_block(sf: Sequence[Fact], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for fld in ("target_low", "target_mean", "target_high", "analyst_count"):
        rows = _latest(sf, kind="target", field_name=fld)
        out[fld] = _fact_ref(rows[0]) if rows else None
        by_src: dict[str, Fact] = {}
        for r in rows:
            by_src.setdefault(r.source, r)
        vals = list(by_src.values())
        if len(vals) > 1 and any(not math.isclose(v.value, vals[0].value, rel_tol=0.01) for v in vals[1:]):
            conflicts.append(
                {
                    "field": f"street.{fld}",
                    "values": [_fact_ref(v) for v in vals],
                    "resolution": "SHOWN_NOT_RESOLVED (§26.5)",
                }
            )
    lo, hi = out.get("target_low"), out.get("target_high")
    out["range"] = [lo["value"], hi["value"]] if lo and hi else None
    if out["range"] is None:
        out["gap"] = "NO_SOURCED_STREET_RANGE"
    return out


_DEFAULT_12M_ANCHOR = {"bear": "target_low", "base": "target_mean", "bull": "target_high"}


def _scenarios(
    subject_key: str,
    sf: Sequence[Fact],
    opinions: Sequence[dict[str, Any]],
    *,
    values: Sequence[float],
    ground_log: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_id = {f.fact_id: f for f in sf}
    dissent: list[dict[str, Any]] = []
    out: dict[str, Any] = {}
    for h in HORIZONS:
        out[h] = {}
        for case in CASES:
            picks: dict[str, Optional[str]] = {}
            assumptions: list[dict[str, Any]] = []
            for op in opinions:
                subj = _subject_out(op, subject_key)
                cell = (((subj or {}).get("horizons") or {}).get(h) or {}).get(case) or {}
                if not isinstance(cell, dict):
                    continue
                fid = cell.get("anchor_fact_id")
                if fid and (fid not in by_id or by_id[fid].value is None):
                    ground_log.append(
                        {
                            "where": f"panel.{op['member']}.{subject_key}.{h}.{case}",
                            "reason": "anchor_not_a_sourced_number",
                            "anchor_fact_id": fid,
                        }
                    )
                    fid = None
                picks[op["member"]] = fid
                txt = ground_text(
                    str(cell.get("assumption") or ""),
                    values,
                    where=f"panel.{op['member']}.{subject_key}.{h}.{case}",
                    log=ground_log,
                )
                if txt:
                    assumptions.append({"member": op["member"], "text": txt})
            chosen = [p for p in picks.values() if p]
            anchor_id = max(set(chosen), key=chosen.count) if chosen else None
            basis = "panel_majority" if anchor_id else None
            if anchor_id is None and h == "12m":
                rows = _latest(sf, kind="target", field_name=_DEFAULT_12M_ANCHOR[case])
                if rows:
                    anchor_id, basis = rows[0].fact_id, f"street {_DEFAULT_12M_ANCHOR[case]} (12-month street target)"
            if len(set(picks.values())) > 1:
                dissent.append(
                    {
                        "kind": "scenario_anchor",
                        "subject_key": subject_key,
                        "horizon": h,
                        "case": case,
                        "positions": {
                            m: (_fact_ref(by_id.get(p)) or {}).get("value") if p else None for m, p in picks.items()
                        },
                    }
                )
            anchor = by_id.get(anchor_id) if anchor_id else None
            out[h][case] = {
                "price": anchor.value if anchor else None,
                "anchor": _fact_ref(anchor),
                "anchor_basis": basis,
                "assumptions": assumptions,
                "gap": None if anchor else "NO_SOURCED_ANCHOR (no number invented)",
            }
    return out, dissent


def _subject_out(op: Mapping[str, Any], subject_key: str) -> Optional[dict[str, Any]]:
    if not op.get("ok"):
        return None
    for s in (op.get("output") or {}).get("subjects") or []:
        if isinstance(s, dict) and s.get("subject_key") == subject_key:
            return s
    subs = (op.get("output") or {}).get("subjects") or []
    return subs[0] if len(subs) == 1 and isinstance(subs[0], dict) else None


def _confidence(
    sf: Sequence[Fact], opinions: Sequence[dict[str, Any]], stances: Mapping[str, str], street: Mapping[str, Any]
) -> dict[str, Any]:
    families = {f.family for f in sf}
    coverage = len(families & {"internal", "street", "sec", "news", "web", "market"}) / 6.0
    ok_members = [o for o in opinions if o.get("ok")]
    agree = (max(list(stances.values()).count(s) for s in set(stances.values())) / len(stances)) if stances else 0.0
    score = round(0.5 * coverage + 0.3 * agree + (0.2 if street.get("range") else 0.0), 3)
    label = "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"
    return {
        "score": score,
        "label": label,
        "basis": {
            "source_family_coverage": round(coverage, 3),
            "families": sorted(families),
            "panel_members_answered": len(ok_members),
            "panel_stance_agreement": round(agree, 3),
            "street_range_sourced": bool(street.get("range")),
        },
    }


def _sizing_context(
    named: Sequence[Mapping[str, Any]], ent: Entity, price: Optional[Fact], scenarios: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Arithmetic only, only for quantities the operator named. Nothing chosen, nothing recommended."""
    out = []
    for n in named:
        if not ent.symbol or str(n.get("symbol") or "").upper() != ent.symbol:
            continue
        q = _num(n.get("quantity"))
        if not q:
            continue
        row: dict[str, Any] = {
            "symbol": ent.symbol,
            "quantity": q,
            "named_by": "operator",
            "reference_price": _fact_ref(price),
            "egress": "local_only",
        }
        if price is None:
            row["gap"] = "NO_SOURCED_REFERENCE_PRICE"
            out.append(row)
            continue
        row["notional_usd"] = round(q * price.value, 2)
        row["scenario_pnl_usd"] = {
            h: {
                c: (
                    round(q * (scenarios[h][c]["price"] - price.value), 2)
                    if scenarios[h][c]["price"] is not None
                    else None
                )
                for c in CASES
            }
            for h in HORIZONS
        }
        out.append(row)
    return out


def _risk_budget_inputs(sf: Sequence[Fact], ent: Entity) -> dict[str, Any]:
    """The sourced inputs a later risk-budget suggestion would need. No suggestion is computed (MBI_BEHAVIOR=0)."""

    def pick(kind: str, fld: str) -> Optional[dict[str, Any]]:
        rows = _latest(sf, kind=kind, field_name=fld)
        return _fact_ref(rows[0]) if rows else None

    inputs = {
        "portfolio_value": pick("portfolio", "portfolio_value"),
        "stop_reference": pick("stop", "stop_reference"),
        "concentration_limit": pick("policy", "concentration_limit_pct"),
        "held_flag": pick("held", "held"),
    }
    return {
        "inputs": inputs,
        "missing": sorted(k for k, v in inputs.items() if v is None),
        "size_suggestion": None,
        "size_suggestion_policy": SIZE_SUGGESTION_POLICY,
        "egress": "local_only",
    }


def synthesize(
    request: Mapping[str, Any],
    entities: Sequence[Entity],
    facts: Sequence[Fact],
    gaps: Sequence[Mapping[str, Any]],
    opinions: Sequence[dict[str, Any]],
    *,
    mbi_log: list[dict[str, Any]],
    governor: Optional[CostGovernor] = None,
    refusals: Sequence[Mapping[str, Any]] = (),
    runs: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    ground_log: list[dict[str, Any]] = []
    prospectus = []
    all_dissent: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for ent in entities:
        if not ent.subject_key:
            prospectus.append({"entity": ent.to_dict(), "status": "identity unresolved", "horizons": None})
            continue
        sf = [f for f in facts if f.subject_key == ent.subject_key]
        values = sourced_values(sf)
        street = _street_block(sf, conflicts)
        scen, dissent = _scenarios(ent.subject_key, sf, opinions, values=values, ground_log=ground_log)
        stances: dict[str, str] = {}
        views = []
        risks: list[dict[str, Any]] = []
        changes: list[dict[str, Any]] = []
        for op in opinions:
            subj = _subject_out(op, ent.subject_key)
            if not subj:
                continue
            st = str(subj.get("stance") or "").lower()
            if st in STANCES:
                stances[op["member"]] = st
            summ = ground_text(
                str(subj.get("summary") or ""), values, where=f"panel.{op['member']}.summary", log=ground_log
            )
            views.append({"member": op["member"], "stance": st or None, "summary": summ})
            for r in subj.get("risks") or []:
                if isinstance(r, dict):
                    txt = ground_text(
                        str(r.get("text") or ""), values, where=f"panel.{op['member']}.risk", log=ground_log
                    )
                    cited = [fid for fid in (r.get("fact_ids") or []) if any(f.fact_id == fid for f in sf)]
                    if txt:
                        risks.append({"member": op["member"], "text": txt, "fact_ids": cited})
            for c in subj.get("what_changes_view") or []:
                txt = ground_text(str(c or ""), values, where=f"panel.{op['member']}.what_changes", log=ground_log)
                if txt:
                    changes.append({"member": op["member"], "text": txt})
        for f in sf:
            if f.kind in ("risk", "conflict"):
                risks.append({"member": "sourced", "text": f.claim, "fact_ids": [f.fact_id]})
        if len(set(stances.values())) > 1:
            dissent.insert(0, {"kind": "stance", "subject_key": ent.subject_key, "positions": dict(stances)})
        all_dissent.extend(dissent)
        price_rows = _latest(sf, kind="price", field_name="last_price")
        price = price_rows[0] if price_rows else None
        catalysts = sorted(
            (
                {"date": f.as_of, "event": f.claim, "fact_id": f.fact_id, "citation": f.citation}
                for f in sf
                if f.kind in ("catalyst", "filing")
            ),
            key=lambda c: c["date"],
            reverse=True,
        )
        prospectus.append(
            {
                "entity": ent.to_dict(),
                "status": "researched",
                "reference_price": _fact_ref(price),
                "street": street,
                "horizons": scen,
                "catalysts": catalysts[:10],
                "risks": risks,
                "what_changes_view": changes,
                "panel_views": views,
                "dissent": dissent,
                "confidence": _confidence(sf, opinions, stances, street),
                "sizing_context": _sizing_context(request.get("named_quantities") or [], ent, price, scen),
                "risk_budget_inputs": _risk_budget_inputs(sf, ent),
            }
        )
    model_refusals = [{"member": o["member"], "reason": o.get("refusal")} for o in opinions if not o.get("ok")]
    partial = bool(model_refusals or refusals or any(g.get("reason") == "TIMEOUT" for g in gaps))
    sources = {}
    for f in facts:
        key = json.dumps(f.citation, sort_keys=True, default=str)
        s = sources.setdefault(key, {"citation": f.citation, "source": f.source, "as_of": f.as_of, "fact_ids": []})
        s["fact_ids"].append(f.fact_id)
        s["as_of"] = max(s["as_of"], f.as_of)
    answer = {
        "schema": ASK_ANSWER_SCHEMA,
        "contract_source": contract_source(),
        "authority": AUTHORITY,
        "mbi_behavior": 0,
        "request_id": request.get("request_id"),
        "question": request.get("question"),
        "answered_at": _iso(_now()),
        "mode": request.get("mode", "deep"),
        "partial": partial,
        "refusals": list(refusals) + model_refusals,
        "prospectus": prospectus,
        "dissent": all_dissent,
        "conflicts": conflicts,
        "sources": sorted(sources.values(), key=lambda s: (s["source"], s["as_of"])),
        "facts": [f.to_dict() for f in facts],
        "gaps": list(gaps),
        "panel": [
            {"member": o["member"], "ok": o.get("ok"), "refusal": o.get("refusal"), "prompt_sha": o.get("prompt_sha")}
            for o in opinions
        ],
        "mbi_strip_log": list(mbi_log),
        "ungrounded_log": ground_log,
        "cost": governor.summary() if governor else None,
        "source_runs": list(runs),
    }
    if _contract is not None and hasattr(_contract, "validate_ask_answer"):  # pragma: no cover - reconcile hook
        _contract.validate_ask_answer(answer)  # type: ignore[attr-defined]
    return answer


def assert_numbers_cited(answer: Mapping[str, Any]) -> list[str]:
    """Every number in the prospectus carries ``as_of`` and a citation (or is operator-named arithmetic)."""
    problems = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "value" in node and node.get("value") is not None and "fact_id" in node:
                if not node.get("as_of") or not node.get("citation"):
                    problems.append(path)
            if "price" in node and node.get("price") is not None and not (node.get("anchor") or {}).get("as_of"):
                problems.append(path + ".price")
            for k, v in node.items():
                if k in ("sizing_context",):
                    continue
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(answer.get("prospectus") or [], "prospectus")
    return problems


# --------------------------------------------------------------------------------------------------- memory
class MemoryAppender:
    """Append every gathered fact and the final answer to CIO memory, keyed by subject (security_guid; issuer_guid
    for a private tracked entity), through the existing integrator (``CIOEnvelopeIntegrator``).

    Idempotent: each event has a deterministic ``event_key``. Keys already appended (the local ledger) are skipped,
    so a retried lane run does not duplicate memory. ``sink`` is injectable for tests. The default sink calls
    ``integrate_envelope(envelope, apply=self.apply)``, so with ``apply=False`` it is a dry run.
    """

    def __init__(
        self,
        *,
        ledger_path: Path | str | None = None,
        sink: Callable[[dict[str, Any]], Any] | None = None,
        apply: bool = False,
    ):
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self.apply = apply
        self._sink = sink
        self._seen: set[str] = set()
        if self.ledger_path and self.ledger_path.exists():
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                try:
                    self._seen.add(json.loads(line)["event_key"])
                except (ValueError, KeyError, TypeError):
                    continue

    def _default_sink(self, envelope: dict[str, Any]) -> Any:
        mod = _imp("scripts.lib.cio_memory_integration", "lib.cio_memory_integration")
        return mod.CIOEnvelopeIntegrator().integrate_envelope(envelope, apply=self.apply, dry_run=not self.apply)

    def _emit(self, key: str, envelope: dict[str, Any], receipt: dict[str, Any]) -> None:
        if key in self._seen:
            receipt["skipped_duplicate"] += 1
            return
        try:
            (self._sink or self._default_sink)(envelope)
        except Exception as exc:  # noqa: BLE001 - a refused envelope is reported, never retried blindly
            receipt["refused"].append({"event_key": key, "reason": f"{type(exc).__name__}: {str(exc)[:160]}"})
            return
        self._seen.add(key)
        receipt["appended"] += 1
        if self.ledger_path:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "event_key": key,
                            "subject_key": envelope.get("subject_guid"),
                            "predicate": envelope.get("predicate"),
                            "at": _iso(_now()),
                        }
                    )
                    + "\n"
                )

    def append(
        self,
        entities: Sequence[Entity],
        facts: Sequence[Fact],
        answer: Mapping[str, Any],
        *,
        origin: str = "in_process",
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "schema": MEMORY_SCHEMA,
            "appended": 0,
            "skipped_duplicate": 0,
            "refused": [],
            "apply": self.apply,
            "origin": origin,
        }
        ent_by_key = {e.subject_key: e for e in entities if e.subject_key}
        for f in facts:
            ent = ent_by_key.get(f.subject_key)
            if ent is None:
                continue
            key = "askfact:" + _sha(f.subject_key, f.fact_id, n=24)
            obj = {
                "fact_id": f.fact_id,
                "kind": f.kind,
                "source": f.source,
                "claim": f.claim,
                "as_of": f.as_of,
                "citation": f.citation,
                "request_id": answer.get("request_id"),
            }
            if f.value is not None and f.egress == "model_ok":
                obj["value"], obj["unit"], obj["field"] = f.value, f.unit, f.field
            self._emit(key, self._envelope(ent, "ask_research_fact", obj, f.claim, f.as_of, key), receipt)
        for p in answer.get("prospectus") or []:
            ent = ent_by_key.get((p.get("entity") or {}).get("subject_key"))
            if ent is None:
                continue
            key = "askanswer:" + _sha(ent.subject_key, answer.get("request_id"), n=24)
            obj = self._answer_object(answer, p, origin=origin)
            claim = f"Ask the CIO: {answer.get('question')}"[:300]
            self._emit(key, self._envelope(ent, "ask_answer", obj, claim, answer.get("answered_at"), key), receipt)
        return receipt

    @staticmethod
    def _envelope(
        ent: Entity, predicate: str, obj: dict[str, Any], claim: str, valid_from: Any, key: str
    ) -> dict[str, Any]:
        return {
            "predicate": predicate,
            "object": obj,
            "claim": claim,
            "source_type": "cio_ask_research",
            "valid_from": _iso(valid_from),
            "source_id": key,
            "event_key": key,
            "subject_guid": ent.subject_key,
            "security_guid": ent.security_guid,
            "issuer_guid": ent.issuer_guid,
            "symbol": ent.symbol,
            "entity_kind": ent.kind,
            "identity_status": ent.identity_status,
        }

    @staticmethod
    def _answer_object(answer: Mapping[str, Any], p: Mapping[str, Any], *, origin: str) -> dict[str, Any]:
        """Sourced skeleton always. Model-derived text only off the n8n path (§23.4). Never sizing (§2A and
        FORBIDDEN_OBJECT_KEYS)."""
        horizons = {
            h: {
                c: {
                    "price": (cell or {}).get("price"),
                    "anchor_fact_id": ((cell or {}).get("anchor") or {}).get("fact_id"),
                    "gap": (cell or {}).get("gap"),
                }
                for c, cell in (row or {}).items()
            }
            for h, row in (p.get("horizons") or {}).items()
        }
        obj: dict[str, Any] = {
            "request_id": answer.get("request_id"),
            "question": answer.get("question"),
            "answered_at": answer.get("answered_at"),
            "partial": answer.get("partial"),
            "street_range": (p.get("street") or {}).get("range"),
            "horizons": horizons,
            "catalyst_fact_ids": [c.get("fact_id") for c in p.get("catalysts") or []],
            "confidence": p.get("confidence"),
            "gap_count": len(answer.get("gaps") or []),
            "origin": origin,
        }
        if origin != "n8n":
            obj["panel_views"] = p.get("panel_views")
            obj["dissent"] = p.get("dissent")
            obj["risks"] = p.get("risks")
            obj["what_changes_view"] = p.get("what_changes_view")
        else:
            obj["model_text"] = "OMITTED_ON_N8N_PATH (AGENTS.md §23.4)"
        return obj


# --------------------------------------------------------------------------------------------------- orchestrator
def run_research(
    request: Mapping[str, Any],
    *,
    db_query: Optional[Callable[..., Any]] = None,
    sources: Optional[Sequence[SourceSpec]] = None,
    panel: Optional[Sequence[PanelMember]] = None,
    governor: Optional[CostGovernor] = None,
    memory: Optional[MemoryAppender] = None,
    origin: str = "in_process",
    dry_run: bool = False,
    identity_fn: Callable[[str], Mapping[str, Any]] = default_identity_fn,
    name_fn: Callable[[str], Optional[Mapping[str, Any]]] = default_name_fn,
    issuer_guid_fn: Callable[[str], Optional[str]] = default_issuer_guid_fn,
    known_symbol: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """One AskRequest → one AskAnswer. Callable in-process (the deep path) and from the lane executor.

    ``mode="fast"`` gathers internal and market facts only and skips the panel. ``dry_run`` gathers nothing:
    it resolves entities and reports the plan (sources, panel admission), spending nothing and writing nothing.
    """
    if known_symbol is None:

        def known_symbol(tok: str) -> bool:  # noqa: E306
            try:
                return bool(
                    (identity_fn(tok) or {}).get("security_guid") or (identity_fn(tok) or {}).get("subject_guid")
                )
            except Exception:  # noqa: BLE001
                return False

    req = normalize_request(request, known_symbol=known_symbol)
    entities = [
        resolve_entity(s, identity_fn=identity_fn, name_fn=name_fn, issuer_guid_fn=issuer_guid_fn)
        for s in req["subjects"]
    ]
    srcs = list(sources if sources is not None else default_sources())
    if req["mode"] == "fast":
        srcs = [s for s in srcs if s.family in ("internal", "market", "street")]
    members = list(panel if panel is not None else ([] if req["mode"] == "fast" else default_panel()))
    governor = governor or CostGovernor()
    if dry_run:
        return {
            "schema": RUN_SCHEMA,
            "dry_run": True,
            "request": req,
            "entities": [e.to_dict() for e in entities],
            "sources": [s.name for s in srcs],
            "panel": [m.name for m in members],
            "governor": {
                "process_id": governor.process_id,
                "registered": governor._registered(),
                "per_question_cap_usd": governor.per_question_usd,
            },
            "would_write": ["AskAnswer (caller-owned output)", "CIO memory events (integrator)"],
        }
    ctx = ResearchContext(question=req["question"], db_query=db_query, dry_run=False)
    g = gather_facts(entities, srcs, ctx)
    mbi_log: list[dict[str, Any]] = []
    opinions: list[dict[str, Any]] = []
    if members and any(e.subject_key for e in entities):
        prompt = build_panel_prompt(req["question"], entities, g["facts"])
        opinions = run_panel(prompt, members, governor, mbi_log=mbi_log)
    answer = synthesize(
        req, entities, g["facts"], g["gaps"], opinions, mbi_log=mbi_log, governor=governor, runs=g["runs"]
    )
    answer["entities"] = [e.to_dict() for e in entities]
    answer["origin"] = origin
    answer["claude_oversight"] = "NOT_AVAILABLE: no governed Claude process for this path (not improvised)"
    if memory is not None:
        answer["memory_receipt"] = memory.append(entities, g["facts"], answer, origin=origin)
    return answer


__all__ = [
    "AUTHORITY",
    "LANE_ID",
    "PROCESS_ID",
    "Fact",
    "FactRejected",
    "make_fact",
    "Entity",
    "resolve_entity",
    "extract_subjects",
    "parse_named_quantities",
    "normalize_request",
    "ResearchContext",
    "SourceSpec",
    "gather_facts",
    "default_sources",
    "strip_behavior",
    "strip_behavior_text",
    "ungrounded_numbers",
    "ground_text",
    "CostGovernor",
    "PanelMember",
    "default_panel",
    "build_panel_prompt",
    "run_panel",
    "synthesize",
    "assert_numbers_cited",
    "MemoryAppender",
    "run_research",
    "contract_source",
]
