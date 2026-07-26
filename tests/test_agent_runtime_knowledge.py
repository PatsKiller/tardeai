from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.agent_runtime.contracts import canonical_hash
from scripts.agent_runtime.knowledge import (
    EmbeddingProvenance,
    KnowledgeError,
    KnowledgeIndex,
    KnowledgeRecord,
    record_from_mapping,
)
from scripts.agent_runtime.sentinel import inspect_ticket
from scripts.agent_runtime.watch_artifact import adapt_watch_item


NOW = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)


def record(
    record_id: str,
    *,
    kind: str = "LESSON",
    lifecycle: str = "RATIFIED",
    title: str = "Stop direction integrity",
    content: str = "For a long ticket, the stop remains below entry and deterministic validation is sovereign.",
    valid_from: str = "2026-01-01T00:00:00+00:00",
    valid_to: str | None = None,
    symbols: tuple[str, ...] = (),
    tags: tuple[str, ...] = ("ticket", "integrity", "stop"),
    counterevidence_refs: tuple[str, ...] = (),
    contradicts_refs: tuple[str, ...] = (),
    embedding: EmbeddingProvenance | None = None,
    version: int = 1,
    metadata=None,
) -> KnowledgeRecord:
    source = {"record_id": record_id, "version": version, "title": title, "content": content}
    return KnowledgeRecord(
        record_id=record_id,
        version=version,
        kind=kind,
        lifecycle=lifecycle,
        title=title,
        content=content,
        source_refs=(f"source:{record_id}",),
        source_hash=canonical_hash(source),
        valid_from=valid_from,
        valid_to=valid_to,
        tags=tags,
        symbols=symbols,
        counterevidence_refs=counterevidence_refs,
        contradicts_refs=contradicts_refs,
        metadata=metadata or {},
        embedding=embedding,
    )


def test_default_retrieval_enforces_temporal_and_lifecycle_boundaries() -> None:
    active = record("active", symbols=("SCHG",))
    disputed = record(
        "disputed",
        lifecycle="DISPUTED",
        title="Disputed SCHG pullback lesson",
        content="The prior pullback rule has counterevidence and should remain visible as disputed.",
        symbols=("SCHG",),
        counterevidence_refs=("case:counter:v1",),
    )
    candidate = record("candidate", lifecycle="CANDIDATE", symbols=("SCHG",))
    retired = record("retired", lifecycle="RETIRED", symbols=("SCHG",))
    expired = record("expired", valid_to="2026-06-01T00:00:00+00:00", symbols=("SCHG",))
    future = record("future", valid_from="2026-08-01T00:00:00+00:00", symbols=("SCHG",))
    other_symbol = record("other", symbols=("JEPQ",))
    index = KnowledgeIndex([active, disputed, candidate, retired, expired, future, other_symbol])

    bundle = index.search("SCHG ticket integrity pullback", as_of=NOW, symbols=("SCHG",))
    refs = bundle.retrieval_refs
    assert "lesson:active:v1" in refs
    assert "lesson:disputed:v1" in refs
    assert "lesson:candidate:v1" not in refs
    assert "lesson:retired:v1" not in refs
    assert "lesson:expired:v1" not in refs
    assert "lesson:future:v1" not in refs
    assert "lesson:other:v1" not in refs
    assert bundle.excluded_counts["future"] == 1
    assert bundle.excluded_counts["expired"] == 1
    assert bundle.excluded_counts["lifecycle"] == 2
    assert bundle.excluded_counts["symbol"] == 1


def test_retrieval_is_deterministic_and_preserves_disputed_counterevidence() -> None:
    ratified = record("ratified", symbols=("SCHG",), version=2)
    disputed = record(
        "disputed",
        lifecycle="DISPUTED",
        title="Stop direction integrity disputed",
        symbols=("SCHG",),
        counterevidence_refs=("case:known-bad:v1",),
    )
    index = KnowledgeIndex([disputed, ratified])
    first = index.search("SCHG stop direction integrity", as_of=NOW, symbols=("SCHG",))
    second = index.search("SCHG stop direction integrity", as_of=NOW, symbols=("SCHG",))
    assert first.bundle_hash == second.bundle_hash
    assert first.retrieval_refs == second.retrieval_refs
    hit = next(item for item in first.hits if item.lifecycle == "DISPUTED")
    assert hit.counterevidence_refs == ("case:known-bad:v1",)
    assert "lifecycle:disputed-preserved" in hit.reasons


def test_find_contradictions_returns_active_linked_records() -> None:
    base = record("base", symbols=("SCHG",))
    contradiction = record(
        "contradiction",
        kind="CASE",
        lifecycle="OBSERVED",
        title="Counterexample to stop lesson",
        content="A source record contradicts the prior lesson and must be reviewed.",
        symbols=("SCHG",),
        contradicts_refs=(base.retrieval_ref,),
    )
    unrelated = record("unrelated", kind="CASE", lifecycle="OBSERVED", symbols=("SCHG",))
    index = KnowledgeIndex([base, contradiction, unrelated])
    found = index.find_contradictions((base.retrieval_ref,), as_of=NOW)
    assert [item.record_id for item in found] == ["contradiction"]


def test_embedding_provenance_is_all_or_nothing() -> None:
    good = record(
        "embedded",
        embedding=EmbeddingProvenance(provider="ollama", model="qwen3-embedding", version="8b-v1", vector_ref="vector:embedded"),
    )
    good.validate()
    bad = record(
        "bad-embedding",
        embedding=EmbeddingProvenance(provider="ollama", model="", version="8b-v1", vector_ref="vector:bad"),
    )
    with pytest.raises(KnowledgeError, match="embedding provenance"):
        bad.validate()


def test_candidate_can_be_retrieved_only_when_explicitly_requested() -> None:
    candidate = record("candidate", lifecycle="CANDIDATE", symbols=("SCHG",))
    index = KnowledgeIndex([candidate])
    default = index.search("SCHG ticket integrity", as_of=NOW, symbols=("SCHG",))
    explicit = index.search("SCHG ticket integrity", as_of=NOW, symbols=("SCHG",), lifecycles=("CANDIDATE",))
    assert default.hits == ()
    assert explicit.retrieval_refs == ("lesson:candidate:v1",)


def test_secret_like_metadata_is_rejected() -> None:
    compromised = record("compromised", metadata={"api_key": "must-not-enter-retrieval"})
    with pytest.raises(ValueError, match="secret-like field"):
        compromised.validate()


def test_record_mapping_requires_versioned_embedding_provenance() -> None:
    raw = {
        "record_id": "mapped",
        "version": 1,
        "kind": "CASE",
        "lifecycle": "OBSERVED",
        "title": "Mapped case",
        "content": "A fully provenance-bound case.",
        "source_refs": ["case-source:mapped"],
        "source_hash": "a" * 64,
        "valid_from": "2026-01-01T00:00:00+00:00",
        "embedding": {"provider": "ollama", "model": "embed", "version": "v1", "vector_ref": "vector:mapped"},
    }
    mapped = record_from_mapping(raw)
    assert mapped.embedding is not None
    assert mapped.embedding.version == "v1"


def watch_item():
    return {
        "id": "watch-1",
        "symbol": "SCHG",
        "profile_sector": "Large Blend",
        "price": 33.4,
        "rsi": 45.3,
        "trend_state": "neutral",
        "last_enriched_at": "2026-07-23T13:30:00+00:00",
        "decision_packet": {
            "current_actionable_plan": {
                "state": "READY",
                "ticket_validation": {"state": "PASS", "proposal_allowed": True, "hard_failures": []},
                "mechanics": {"entry": 34.1, "stop": 33.6, "target": 35.5, "direction": "LONG"},
            }
        },
    }


def test_watch_retrieval_binds_artifact_and_sentinel_findings() -> None:
    adapter = adapt_watch_item(watch_item(), now=NOW)
    report = inspect_ticket(adapter.artifact.sentinel_ticket(), adapter.source_validation, now=NOW)
    index = KnowledgeIndex(
        [
            record("schg-case", kind="CASE", lifecycle="OBSERVED", title="SCHG historical ticket outcome", content="SCHG prior ticket integrity outcome and pullback evidence.", symbols=("SCHG",)),
            record("general-lesson", title="Ticket integrity lesson", content="Deterministic validation remains sovereign for every ticket."),
        ]
    )
    context = index.retrieve_for_watch(adapter.artifact, report, as_of=NOW)
    assert context.artifact_hash == adapter.artifact.artifact_hash
    assert context.sentinel_findings == ()
    assert "SCHG" in context.query
    assert "case:schg-case:v1" in context.bundle.retrieval_refs
    assert len(context.bundle.bundle_hash) == 64
