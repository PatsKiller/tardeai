"""L2 subject-grounded memory — required controls for INTEGRATION_CANDIDATE.

Covers identity compatibility, subject isolation, decay boundaries, contradictions,
resolver hard-negatives, cache invalidation, empty store, and with/without grounding.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.memory_decay import DecayPolicy  # noqa: E402
from scripts.lib.memory_grounding import (  # noqa: E402
    GroundingContractError,
    SubjectGroundedMemorySelector,
    assert_no_behavior_writes,
    build_grounded_judgment_input,
    compare_with_without_memory,
    influence_metrics,
)
from scripts.lib.memory_subject_resolver import (  # noqa: E402
    ResolverFailure,
    assert_positive_control,
    normalize_memory_id,
    normalize_subject_fields,
    row_subject_disposition,
)

NOW = datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)
SG_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SG_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SG_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def _as_of(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "mem.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def _selector(path: Path, **kw) -> SubjectGroundedMemorySelector:
    policy = kw.pop("policy", DecayPolicy(half_life_hours=336.0, min_influence=0.01))
    return SubjectGroundedMemorySelector(path, policy=policy, source_revision="testrev", include_fact_text=True, **kw)


def _lookup(mapping: dict[str, str | None]):
    def _fn(symbol: str) -> dict:
        g = mapping.get(str(symbol).upper())
        if g is None and str(symbol).upper() not in mapping:
            return {
                "subject_guid": None,
                "identity_lookup": "UNRESOLVED",
                "identity_lookup_failed": False,
            }
        if g is None:
            return {
                "subject_guid": None,
                "identity_lookup": "UNRESOLVED",
                "identity_lookup_failed": False,
            }
        return {
            "subject_guid": g,
            "identity_lookup": "RESOLVED",
            "identity_lookup_failed": False,
        }

    return _fn


# ── B1 identity compatibility ───────────────────────────────────────────────


def test_memory_id_alias_alone():
    assert normalize_memory_id({"memory_id": "m1"}).memory_id == "m1"
    assert normalize_memory_id({"memory_id": "m1"}).error is None


def test_fact_id_alias_alone():
    assert normalize_memory_id({"fact_id": "f1"}).memory_id == "f1"


def test_id_alias_alone():
    assert normalize_memory_id({"id": "i1"}).memory_id == "i1"


def test_conflicting_ids_fail_closed():
    r = normalize_memory_id({"memory_id": "a", "fact_id": "b"})
    assert r.memory_id is None
    assert r.error == "conflicting_ids"


def test_agreeing_aliases_ok():
    r = normalize_memory_id({"memory_id": "x", "fact_id": "x", "id": "x"})
    assert r.memory_id == "x"
    assert r.error is None


def test_subject_guid_and_uuid_shaped_subject_compat():
    r = normalize_subject_fields({"subject_guid": SG_A, "subject": SG_A})
    assert r.subject_guid == SG_A
    assert r.error is None


def test_title_subject_is_not_treated_as_guid():
    r = normalize_subject_fields({"subject": "Program 3 canary thesis"})
    assert r.subject_guid is None
    assert r.source_subject_or_symbol == "Program 3 canary thesis"
    assert r.error is None


def test_conflicting_subject_fields_fail_closed():
    r = normalize_subject_fields({"subject_guid": SG_A, "subject": SG_B})
    assert r.error == "conflicting_subjects"
    assert r.subject_guid is None


# ── Subject isolation ────────────────────────────────────────────────────────


def test_missing_subject_does_not_load_globally(tmp_path):
    rows = [
        {"memory_id": "m1", "subject": "title only", "content": "a", "as_of": _as_of(10)},
        {"memory_id": "m2", "subject": "another title", "content": "b", "as_of": _as_of(10)},
        {"memory_id": "m3", "subject_guid": SG_A, "content": "c", "as_of": _as_of(10)},
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert [f.memory_id for f in sel.selected] == ["m3"]
    assert sel.rejected.unresolved_subject == 2
    assert sel.rejected.wrong_subject == 0


def test_wrong_subject_isolation_two_subjects(tmp_path):
    rows = [
        {"memory_id": "ma", "subject_guid": SG_A, "content": "A", "as_of": _as_of(5)},
        {"memory_id": "mb", "subject_guid": SG_B, "content": "B", "as_of": _as_of(5)},
        {"memory_id": "mc", "subject_guid": SG_C, "content": "C", "as_of": _as_of(5)},
    ]
    path = _write(tmp_path, rows)
    a = _selector(path).select(SG_A, now=NOW)
    b = _selector(path).select(SG_B, now=NOW)
    assert [f.memory_id for f in a.selected] == ["ma"]
    assert [f.memory_id for f in b.selected] == ["mb"]
    assert a.rejected.wrong_subject == 2
    assert b.rejected.wrong_subject == 2
    # Different subjects → different selections
    assert {f.memory_id for f in a.selected} != {f.memory_id for f in b.selected}


def test_symbol_resolve_match(tmp_path):
    rows = [
        {"memory_id": "m1", "symbols": ["AES"], "content": "x", "as_of": _as_of(12)},
        {"memory_id": "m2", "symbols": ["NVDA"], "content": "y", "as_of": _as_of(12)},
    ]
    lookup = _lookup({"AES": SG_A, "NVDA": SG_B})
    sel = _selector(_write(tmp_path, rows), lookup=lookup).select(SG_A, now=NOW)
    assert [f.memory_id for f in sel.selected] == ["m1"]
    assert sel.rejected.wrong_subject == 1


def test_ambiguous_symbols_fail_closed(tmp_path):
    rows = [
        {
            "memory_id": "m1",
            "symbols": ["AES", "NVDA"],
            "content": "multi",
            "as_of": _as_of(12),
        }
    ]
    lookup = _lookup({"AES": SG_A, "NVDA": SG_B})
    sel = _selector(_write(tmp_path, rows), lookup=lookup).select(SG_A, now=NOW)
    assert sel.selected == []
    assert sel.rejected.ambiguous_subject == 1


# ── Duplicates / timestamps ──────────────────────────────────────────────────


def test_duplicate_ids_rejected(tmp_path):
    rows = [
        {"memory_id": "dup", "subject_guid": SG_A, "content": "a", "as_of": _as_of(5)},
        {"memory_id": "dup", "subject_guid": SG_A, "content": "b", "as_of": _as_of(6)},
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert len(sel.selected) == 1
    assert sel.rejected.duplicate_id == 1


def test_duplicate_content_rejected(tmp_path):
    rows = [
        {"memory_id": "m1", "subject_guid": SG_A, "content": "same", "as_of": _as_of(5)},
        {"memory_id": "m2", "subject_guid": SG_A, "content": "same", "as_of": _as_of(6)},
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert len(sel.selected) == 1
    assert sel.rejected.duplicate_content == 1


def test_malformed_timestamp(tmp_path):
    rows = [
        {"memory_id": "m1", "subject_guid": SG_A, "content": "x", "as_of": "not-a-date"},
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert sel.selected == []
    assert sel.rejected.malformed_timestamp == 1


def test_future_timestamp(tmp_path):
    rows = [
        {
            "memory_id": "m1",
            "subject_guid": SG_A,
            "content": "x",
            "as_of": (NOW + timedelta(hours=5)).isoformat().replace("+00:00", "Z"),
        }
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert sel.selected == []
    assert sel.rejected.future_timestamp == 1


# ── Decay boundary / ordering ────────────────────────────────────────────────


def test_boundary_ages_around_168h_no_disappearance(tmp_path):
    rows = [
        {"memory_id": "h167", "subject_guid": SG_A, "content": "a", "as_of": _as_of(167)},
        {"memory_id": "h168", "subject_guid": SG_A, "content": "b", "as_of": _as_of(168)},
        {"memory_id": "h169", "subject_guid": SG_A, "content": "c", "as_of": _as_of(169)},
        {"memory_id": "h432", "subject_guid": SG_A, "content": "d", "as_of": _as_of(432)},
    ]
    policy = DecayPolicy(half_life_hours=336.0, min_influence=0.001)
    sel = _selector(_write(tmp_path, rows), policy=policy).select(SG_A, now=NOW)
    ids = {f.memory_id for f in sel.selected}
    assert ids == {"h167", "h168", "h169", "h432"}
    assert sel.cliff_applied is False
    for f in sel.selected:
        assert f.decay_weight > 0
        assert f.age_seconds > 0
    # Monotonic with age among equal confidence
    by_id = {f.memory_id: f for f in sel.selected}
    assert by_id["h167"].decay_weight >= by_id["h168"].decay_weight
    assert by_id["h168"].decay_weight >= by_id["h169"].decay_weight
    assert by_id["h169"].decay_weight >= by_id["h432"].decay_weight


def test_stable_ordering_and_tie_break(tmp_path):
    # Same observed_at → same age/weight → tie-break by memory_id
    rows = [
        {"memory_id": "m_b", "subject_guid": SG_A, "content": "1", "as_of": _as_of(10)},
        {"memory_id": "m_a", "subject_guid": SG_A, "content": "2", "as_of": _as_of(10)},
        {"memory_id": "m_c", "subject_guid": SG_A, "content": "3", "as_of": _as_of(10)},
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert [f.memory_id for f in sel.selected] == ["m_a", "m_b", "m_c"]


# ── Contradictions ───────────────────────────────────────────────────────────


def test_contradictory_facts_remain_visible(tmp_path):
    rows = [
        {
            "memory_id": "m1",
            "subject_guid": SG_A,
            "content": "claim",
            "as_of": _as_of(8),
            "status": "CONFIRMED",
            "contradicts": ["m2"],
        },
        {
            "memory_id": "m2",
            "subject_guid": SG_A,
            "content": "counter",
            "as_of": _as_of(9),
            "status": "QUARANTINED",
        },
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    # Quarantined visible but not in influence set
    assert any(f.memory_id == "m2" for f in sel.contradiction_visible)
    assert sel.rejected.contradiction_quarantine >= 1
    # Non-quarantine contradicted fact still selected with explicit state
    assert any(f.memory_id == "m1" for f in sel.selected)
    m1 = next(f for f in sel.selected if f.memory_id == "m1")
    assert m1.contradiction_state == "contradicted_by"


# ── Resolver hard negative ───────────────────────────────────────────────────


def test_resolver_failure_is_hard_negative_not_published_zero(tmp_path):
    rows = [
        {"memory_id": "m1", "symbols": ["AES"], "content": "x", "as_of": _as_of(5)},
    ]

    def boom(_symbol: str) -> dict:
        raise ResolverFailure("simulated LOOKUP_FAILED")

    # row_subject_disposition raises via resolve path — selector must surface failure
    def failing_lookup(symbol: str) -> dict:
        raise ResolverFailure("simulated LOOKUP_FAILED")

    # Patch at disposition by using a lookup that raises ResolverFailure through
    # resolve_symbol_guid — our resolve_symbol_guid only raises on LOOKUP_FAILED dict
    # or import. So return LOOKUP_FAILED shape via custom that raises:
    from scripts.lib import memory_subject_resolver as msr

    def raise_lookup(symbol: str) -> dict:
        raise ResolverFailure("simulated LOOKUP_FAILED")

    # Override resolve path: disposition calls resolve_symbol_guid which calls lookup;
    # if lookup raises ResolverFailure it propagates... actually resolve_symbol_guid
    # catches only via _default_lookup. Custom lookup that raises will propagate from
    # resolve_symbol_guid → disposition → select.
    # But resolve_symbol_guid does: got = fn(symbol) without try — good, propagates.

    sel = _selector(_write(tmp_path, rows), lookup=raise_lookup).select(SG_A, now=NOW)
    assert sel.resolver_failure is not None
    assert sel.grounded is False
    # Must NOT look like an honest empty store
    assert sel.empty_store is False


def test_positive_control_refuses_zero():
    def bad(_s: str) -> dict:
        return {"subject_guid": None, "identity_lookup": "UNRESOLVED", "identity_lookup_failed": False}

    with pytest.raises(ResolverFailure):
        assert_positive_control(bad)


# ── Mixed schema / cache / empty ─────────────────────────────────────────────


def test_mixed_schema_versions_tracked_not_auto_malformed(tmp_path):
    rows = [
        {
            "memory_id": "m1",
            "subject_guid": SG_A,
            "content": "ok",
            "as_of": _as_of(5),
            "schema_version": "1.0",
        },
        {
            "memory_id": "m2",
            "subject_guid": SG_A,
            "content": "also",
            "as_of": _as_of(6),
            "schema_version": "99.0-experimental",
        },
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert len(sel.selected) == 2
    assert sel.rejected.mixed_schema == 1
    assert sel.rejected.malformed_row == 0


def test_cache_invalidation_on_policy_revision(tmp_path):
    rows = [
        {"memory_id": "m1", "subject_guid": SG_A, "content": "x", "as_of": _as_of(400)},
    ]
    path = _write(tmp_path, rows)
    p1 = DecayPolicy(half_life_hours=336.0, min_influence=0.5)  # 400h may be below floor
    p2 = DecayPolicy(half_life_hours=336.0, min_influence=0.01)
    s1 = SubjectGroundedMemorySelector(path, policy=p1, source_revision="r1")
    r1 = s1.select(SG_A, now=NOW)
    s2 = SubjectGroundedMemorySelector(path, policy=p2, source_revision="r1")
    r2 = s2.select(SG_A, now=NOW)
    assert r1.cache_key != r2.cache_key
    # Same selector, change source revision → different key
    s3 = SubjectGroundedMemorySelector(path, policy=p2, source_revision="r2")
    r3 = s3.select(SG_A, now=NOW)
    assert r2.cache_key != r3.cache_key


def test_empty_store_valid_not_grounded(tmp_path):
    path = _write(tmp_path, [])
    sel = _selector(path).select(SG_A, now=NOW)
    assert sel.empty_store is True
    assert sel.grounded is False
    assert sel.selected == []
    assert sel.resolver_failure is None


# ── GroundedJudgmentInput + comparator + mutation controls ───────────────────


def test_build_grounded_input_and_with_without_changes_next_question(tmp_path):
    rows = [
        {
            "memory_id": "m1",
            "subject_guid": SG_A,
            "content": "fixture thesis note",
            "as_of": _as_of(40),
            "status": "CONFIRMED",
            "confidence": 0.9,
            "source_kind": "durable",
            "schema_version": "1.0",
        }
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert sel.grounded
    cmp = compare_with_without_memory(sel, baseline_question="what changed since last wake?")
    assert cmp["field"] == "next_question"
    assert cmp["field_changed"] is True
    assert cmp["proven_grounding"] is True
    assert cmp["with_memory"]["next_question"] != cmp["without_memory"]["next_question"]

    gj = build_grounded_judgment_input(
        sel,
        symbol="AES",
        source_sha="aa43a8c9e61e963030fa15009c975f1de88da85a",
        epoch_id="l1l3-epoch-test",
        schedule_slot="2026-09-11T04:00:00Z",
        correlation_id=str(uuid.uuid4()),
        include_fact_text=True,
    )
    assert gj["schema"] == "GroundedJudgmentInput@v1"
    assert gj["grounded"] is True
    assert gj["retrieval"]["cliff_applied"] is False
    assert gj["retrieval"]["returned"] == 1
    assert gj["memory_facts"][0]["decay_weight"] > 0
    assert gj["memory_facts"][0]["age_hours"] == pytest.approx(40.0)
    metrics = influence_metrics(sel)
    assert metrics["selected_memory_fact_ids"] == ["m1"]
    assert metrics["cliff_applied"] is False


def test_no_behavior_portfolio_field_writable():
    payload = {
        "schema": "GroundedJudgmentInput@v1",
        "subject": {"subject_guid": SG_A},
        "memory_facts": [],
        "retrieval": {"cliff_applied": False},
        "grounded": False,
    }
    assert_no_behavior_writes(payload)
    with pytest.raises(GroundingContractError):
        assert_no_behavior_writes({**payload, "quantity": 10})


def test_mutation_breaks_caller_facing_contract(tmp_path):
    """If cliff_applied is forced true, build must refuse."""
    rows = [
        {"memory_id": "m1", "subject_guid": SG_A, "content": "x", "as_of": _as_of(5)},
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    sel.cliff_applied = True  # mutate
    with pytest.raises(GroundingContractError):
        build_grounded_judgment_input(
            sel,
            source_sha="abc",
            epoch_id="e",
            schedule_slot="2026-09-11T04:00:00Z",
            correlation_id="c",
        )


def test_legacy_field_name_not_labeled_malformed(tmp_path):
    """Parse-valid row with memory_id (legacy vs fact_id) is not malformed."""
    rows = [
        {"memory_id": "legacy", "subject_guid": SG_A, "content": "ok", "as_of": _as_of(3)},
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert sel.rejected.malformed_row == 0
    assert [f.memory_id for f in sel.selected] == ["legacy"]


def test_expired_by_policy_non_age(tmp_path):
    rows = [
        {
            "memory_id": "m1",
            "subject_guid": SG_A,
            "content": "gone",
            "as_of": _as_of(5),
            "status": "RETRACTED",
        },
        {
            "memory_id": "m2",
            "subject_guid": SG_A,
            "content": "live",
            "as_of": _as_of(5),
            "status": "CONFIRMED",
        },
    ]
    sel = _selector(_write(tmp_path, rows)).select(SG_A, now=NOW)
    assert [f.memory_id for f in sel.selected] == ["m2"]
    assert sel.rejected.expired_by_policy == 1


def test_disposition_helpers_explicit_guid_wins():
    row = {"subject_guid": SG_A, "symbols": ["NVDA"]}
    assert row_subject_disposition(row, SG_A, lookup=_lookup({"NVDA": SG_B})) == "match"
    assert row_subject_disposition(row, SG_B, lookup=_lookup({"NVDA": SG_B})) == "cross"
