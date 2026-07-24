from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .contracts import assert_no_secret_material, canonical_hash
from .sentinel import SentinelReport
from .watch_artifact import WatchArtifact

KB_RETRIEVAL_VERSION = "kb-retrieval-v1"
_ALLOWED_KINDS = {"LESSON", "CASE", "SOURCE_NOTICE", "INCIDENT", "HANDOFF", "OUTCOME"}
_ALLOWED_LIFECYCLES = {"CANDIDATE", "RATIFIED", "DISPUTED", "RETIRED", "OBSERVED"}
_DEFAULT_LIFECYCLES = {"RATIFIED", "DISPUTED", "OBSERVED"}
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,63}")


class KnowledgeError(ValueError):
    pass


@dataclass(frozen=True)
class EmbeddingProvenance:
    provider: str
    model: str
    version: str
    vector_ref: str

    def validate(self) -> None:
        if not all(value.strip() for value in (self.provider, self.model, self.version, self.vector_ref)):
            raise KnowledgeError("embedding provenance requires provider, model, version and vector_ref")


@dataclass(frozen=True)
class KnowledgeRecord:
    record_id: str
    version: int
    kind: str
    lifecycle: str
    title: str
    content: str
    source_refs: tuple[str, ...]
    source_hash: str
    valid_from: str
    valid_to: str | None = None
    tags: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    counterevidence_refs: tuple[str, ...] = ()
    contradicts_refs: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    embedding: EmbeddingProvenance | None = None

    @property
    def retrieval_ref(self) -> str:
        return f"{self.kind.lower()}:{self.record_id}:v{self.version}"

    @property
    def content_hash(self) -> str:
        return canonical_hash({"title": self.title, "content": self.content, "metadata": self.metadata})

    def validate(self) -> None:
        if not self.record_id.strip() or self.version < 1:
            raise KnowledgeError("record_id and positive version are required")
        if self.kind.upper() not in _ALLOWED_KINDS:
            raise KnowledgeError(f"unsupported knowledge kind: {self.kind}")
        if self.lifecycle.upper() not in _ALLOWED_LIFECYCLES:
            raise KnowledgeError(f"unsupported lifecycle: {self.lifecycle}")
        if not self.title.strip() or not self.content.strip():
            raise KnowledgeError("title and content are required")
        if not self.source_refs:
            raise KnowledgeError("source provenance is required")
        if len(self.source_hash) != 64 or any(character not in "0123456789abcdef" for character in self.source_hash.lower()):
            raise KnowledgeError("source_hash must be sha256")
        start = _parse_time(self.valid_from, "valid_from")
        end = _parse_time(self.valid_to, "valid_to") if self.valid_to else None
        if end is not None and end <= start:
            raise KnowledgeError("valid_to must be later than valid_from")
        if self.embedding is not None:
            self.embedding.validate()
        assert_no_secret_material(asdict(self))

    def active_at(self, when: datetime) -> bool:
        self.validate()
        instant = _ensure_utc(when)
        start = _parse_time(self.valid_from, "valid_from")
        end = _parse_time(self.valid_to, "valid_to") if self.valid_to else None
        return start <= instant and (end is None or instant < end)


@dataclass(frozen=True)
class RetrievalHit:
    retrieval_ref: str
    record_id: str
    version: int
    kind: str
    lifecycle: str
    title: str
    content: str
    score: float
    reasons: tuple[str, ...]
    source_refs: tuple[str, ...]
    source_hash: str
    valid_from: str
    valid_to: str | None
    counterevidence_refs: tuple[str, ...]
    contradicts_refs: tuple[str, ...]
    embedding: EmbeddingProvenance | None


@dataclass(frozen=True)
class RetrievalBundle:
    query: str
    query_hash: str
    as_of: str
    hits: tuple[RetrievalHit, ...]
    excluded_counts: Mapping[str, int]
    retrieval_version: str = KB_RETRIEVAL_VERSION

    @property
    def retrieval_refs(self) -> tuple[str, ...]:
        return tuple(hit.retrieval_ref for hit in self.hits)

    @property
    def bundle_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class WatchRetrievalContext:
    query: str
    bundle: RetrievalBundle
    sentinel_findings: tuple[str, ...]
    artifact_hash: str


class KnowledgeIndex:
    """Deterministic temporal retrieval before a vector backend is activated.

    This in-memory facade enforces the same lifecycle, provenance and temporal
    rules required of a later pgvector implementation. It never ratifies,
    retires or mutates a knowledge record.
    """

    def __init__(self, records: Iterable[KnowledgeRecord]) -> None:
        validated: list[KnowledgeRecord] = []
        seen: set[tuple[str, int]] = set()
        for record in records:
            record.validate()
            key = (record.record_id, record.version)
            if key in seen:
                raise KnowledgeError(f"duplicate knowledge version: {key}")
            seen.add(key)
            validated.append(record)
        self._records = tuple(validated)

    @property
    def records(self) -> tuple[KnowledgeRecord, ...]:
        return self._records

    def search(
        self,
        query: str,
        *,
        as_of: datetime | None = None,
        kinds: Sequence[str] | None = None,
        lifecycles: Sequence[str] | None = None,
        symbols: Sequence[str] | None = None,
        limit: int = 12,
    ) -> RetrievalBundle:
        if not query.strip():
            raise KnowledgeError("retrieval query is required")
        if not 1 <= limit <= 100:
            raise KnowledgeError("limit must be between 1 and 100")
        instant = _ensure_utc(as_of or datetime.now(timezone.utc))
        kind_filter = {item.upper() for item in kinds} if kinds else set(_ALLOWED_KINDS)
        lifecycle_filter = {item.upper() for item in lifecycles} if lifecycles else set(_DEFAULT_LIFECYCLES)
        if not kind_filter <= _ALLOWED_KINDS:
            raise KnowledgeError("unsupported kind filter")
        if not lifecycle_filter <= _ALLOWED_LIFECYCLES:
            raise KnowledgeError("unsupported lifecycle filter")
        symbol_filter = {_normalize_symbol(item) for item in symbols or () if _normalize_symbol(item)}
        query_tokens = _tokens(query)
        if not query_tokens:
            raise KnowledgeError("retrieval query has no searchable tokens")

        excluded = {"future": 0, "expired": 0, "lifecycle": 0, "kind": 0, "symbol": 0, "no_match": 0}
        ranked: list[tuple[float, KnowledgeRecord, tuple[str, ...]]] = []
        for record in self._records:
            start = _parse_time(record.valid_from, "valid_from")
            end = _parse_time(record.valid_to, "valid_to") if record.valid_to else None
            if start > instant:
                excluded["future"] += 1
                continue
            if end is not None and instant >= end:
                excluded["expired"] += 1
                continue
            if record.lifecycle.upper() not in lifecycle_filter:
                excluded["lifecycle"] += 1
                continue
            if record.kind.upper() not in kind_filter:
                excluded["kind"] += 1
                continue
            record_symbols = {_normalize_symbol(item) for item in record.symbols if _normalize_symbol(item)}
            if symbol_filter and record_symbols and not symbol_filter.intersection(record_symbols):
                excluded["symbol"] += 1
                continue
            score, reasons = _score(record, query_tokens, symbol_filter)
            if score <= 0:
                excluded["no_match"] += 1
                continue
            ranked.append((score, record, reasons))

        ranked.sort(key=lambda item: (-item[0], _lifecycle_rank(item[1].lifecycle), -item[1].version, item[1].retrieval_ref))
        hits = tuple(_hit(record, score, reasons) for score, record, reasons in ranked[:limit])
        return RetrievalBundle(
            query=query,
            query_hash=canonical_hash({"query": query, "kinds": sorted(kind_filter), "lifecycles": sorted(lifecycle_filter), "symbols": sorted(symbol_filter)}),
            as_of=instant.isoformat(),
            hits=hits,
            excluded_counts=excluded,
        )

    def find_contradictions(self, retrieval_refs: Sequence[str], *, as_of: datetime | None = None) -> tuple[KnowledgeRecord, ...]:
        instant = _ensure_utc(as_of or datetime.now(timezone.utc))
        targets = set(retrieval_refs)
        output = [
            record
            for record in self._records
            if record.active_at(instant)
            and record.lifecycle.upper() in {"RATIFIED", "DISPUTED", "OBSERVED"}
            and (targets.intersection(record.contradicts_refs) or targets.intersection(record.counterevidence_refs))
        ]
        return tuple(sorted(output, key=lambda record: (_lifecycle_rank(record.lifecycle), -record.version, record.retrieval_ref)))

    def retrieve_for_watch(
        self,
        artifact: WatchArtifact,
        report: SentinelReport,
        *,
        as_of: datetime | None = None,
        limit: int = 12,
    ) -> WatchRetrievalContext:
        artifact.validate()
        finding_codes = tuple(sorted(finding.code for finding in report.findings))
        flags = artifact.strategy_context.get("flags") or []
        if not isinstance(flags, (list, tuple)):
            flags = []
        terms = [
            artifact.symbol,
            artifact.state,
            artifact.direction,
            str(artifact.market_context.get("trend") or ""),
            str(artifact.market_context.get("regime") or ""),
            str(artifact.strategy_context.get("sector") or ""),
            *[str(item) for item in flags],
            *finding_codes,
            "ticket integrity historical outcome contradiction",
        ]
        query = " ".join(term for term in terms if term.strip())
        bundle = self.search(
            query,
            as_of=as_of or _parse_time(artifact.as_of, "artifact.as_of"),
            kinds=("LESSON", "CASE", "SOURCE_NOTICE", "INCIDENT", "OUTCOME"),
            symbols=(artifact.symbol,),
            limit=limit,
        )
        return WatchRetrievalContext(
            query=query,
            bundle=bundle,
            sentinel_findings=finding_codes,
            artifact_hash=artifact.artifact_hash,
        )


def record_from_mapping(raw: Mapping[str, Any]) -> KnowledgeRecord:
    embedding_raw = raw.get("embedding")
    embedding = None
    if isinstance(embedding_raw, Mapping):
        embedding = EmbeddingProvenance(
            provider=str(embedding_raw.get("provider") or ""),
            model=str(embedding_raw.get("model") or ""),
            version=str(embedding_raw.get("version") or ""),
            vector_ref=str(embedding_raw.get("vector_ref") or ""),
        )
    source_refs = raw.get("source_refs") or []
    tags = raw.get("tags") or []
    symbols = raw.get("symbols") or []
    counterevidence = raw.get("counterevidence_refs") or []
    contradicts = raw.get("contradicts_refs") or []
    record = KnowledgeRecord(
        record_id=str(raw.get("record_id") or ""),
        version=int(raw.get("version") or 0),
        kind=str(raw.get("kind") or "").upper(),
        lifecycle=str(raw.get("lifecycle") or "").upper(),
        title=str(raw.get("title") or ""),
        content=str(raw.get("content") or ""),
        source_refs=tuple(str(item) for item in source_refs),
        source_hash=str(raw.get("source_hash") or ""),
        valid_from=str(raw.get("valid_from") or ""),
        valid_to=str(raw.get("valid_to")) if raw.get("valid_to") else None,
        tags=tuple(str(item) for item in tags),
        symbols=tuple(_normalize_symbol(item) for item in symbols if _normalize_symbol(item)),
        counterevidence_refs=tuple(str(item) for item in counterevidence),
        contradicts_refs=tuple(str(item) for item in contradicts),
        metadata=dict(raw.get("metadata") or {}),
        embedding=embedding,
    )
    record.validate()
    return record


def _hit(record: KnowledgeRecord, score: float, reasons: tuple[str, ...]) -> RetrievalHit:
    return RetrievalHit(
        retrieval_ref=record.retrieval_ref,
        record_id=record.record_id,
        version=record.version,
        kind=record.kind,
        lifecycle=record.lifecycle,
        title=record.title,
        content=record.content,
        score=round(score, 6),
        reasons=reasons,
        source_refs=record.source_refs,
        source_hash=record.source_hash,
        valid_from=record.valid_from,
        valid_to=record.valid_to,
        counterevidence_refs=record.counterevidence_refs,
        contradicts_refs=record.contradicts_refs,
        embedding=record.embedding,
    )


def _score(record: KnowledgeRecord, query_tokens: set[str], symbol_filter: set[str]) -> tuple[float, tuple[str, ...]]:
    title_tokens = _tokens(record.title)
    content_tokens = _tokens(record.content)
    tag_tokens = _tokens(" ".join(record.tags))
    record_symbols = {_normalize_symbol(item) for item in record.symbols if _normalize_symbol(item)}
    score = 0.0
    reasons: list[str] = []
    title_overlap = query_tokens.intersection(title_tokens)
    content_overlap = query_tokens.intersection(content_tokens)
    tag_overlap = query_tokens.intersection(tag_tokens)
    symbol_overlap = symbol_filter.intersection(record_symbols)
    if title_overlap:
        score += 3.0 * len(title_overlap)
        reasons.append(f"title:{','.join(sorted(title_overlap))}")
    if tag_overlap:
        score += 2.0 * len(tag_overlap)
        reasons.append(f"tags:{','.join(sorted(tag_overlap))}")
    if content_overlap:
        score += 1.0 * len(content_overlap)
        reasons.append(f"content:{','.join(sorted(content_overlap))}")
    if symbol_overlap:
        score += 8.0 * len(symbol_overlap)
        reasons.append(f"symbol:{','.join(sorted(symbol_overlap))}")
    lifecycle = record.lifecycle.upper()
    if lifecycle == "RATIFIED":
        score += 1.0
        reasons.append("lifecycle:ratified")
    elif lifecycle == "DISPUTED":
        score += 0.5
        reasons.append("lifecycle:disputed-preserved")
    if record.counterevidence_refs:
        score += 0.25
        reasons.append("counterevidence-linked")
    return score, tuple(reasons)


def _tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN.finditer(value)}


def _normalize_symbol(value: Any) -> str:
    return _text(value).upper().replace("$", "")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_time(value: str | None, label: str) -> datetime:
    raw = _text(value)
    if not raw:
        raise KnowledgeError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KnowledgeError(f"invalid {label}: {raw}") from exc
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lifecycle_rank(value: str) -> int:
    return {"RATIFIED": 0, "DISPUTED": 1, "OBSERVED": 2, "CANDIDATE": 3, "RETIRED": 4}.get(value.upper(), 9)
