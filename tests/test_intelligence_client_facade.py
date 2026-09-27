"""Hermetic tests for scripts/lib/intelligence_client.py (Wave 1 tranche 1, shadow reads + receipts).

Everything is injected; no store, DSN, host path or network is touched. Paths are assembled
under tmp_path (check_test_host_paths forbids literal host paths).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import intelligence_client as ic  # noqa: E402

NOW = dt.datetime(2026, 9, 27, 18, 0, tzinfo=dt.timezone.utc)


def _loaders(tmp_path, *, thesis_age_h=24.0, facts_fail=False, resolve=True, contradictions=None,
             research_objects=None, hermes_completed=None, hermes_results=None):
    def resolve_subject(sym):
        return {"security_guid": "11111111-2222-3333-4444-555555555555", "issuer_guid": "iss-1", "identity_status": "CONFIRMED"} if resolve else None

    def facts(symbols, guids):
        if facts_fail:
            raise RuntimeError("provider down")
        return {"retrieval_status": "OK", "supporting": [
            {"memory_id": "mem_a", "memory_type": "CASE_SUMMARY", "subject_guid": guids[0] if guids else None,
             "symbols": symbols, "confidence": 0.7, "as_of": (NOW - dt.timedelta(hours=5)).isoformat(),
             "status": "ACTIVE", "source_refs": ["res_1"]},
            {"memory_id": "mem_b", "memory_type": "RESEARCH_NOTE", "as_of": (NOW - dt.timedelta(days=45)).isoformat(),
             "status": "ACTIVE", "contradicts": ["mem_z"]}],
            "counter_memory": [], "conflicts": [{"memory_id": "mem_b", "reason": "x"}]}

    def instrument(sym):
        return {"subject_key": f"HELD:{sym}", "next_research_question": "what changed?", "last_outcome": {"outcome": "win"},
                "beliefs": [{"belief_key": "k1", "population": "held", "horizon": "20d", "recommendation": "hold",
                             "sample_size": 7, "successful": 5, "success_rate": 0.71, "revision": 2, "as_of": NOW.isoformat()}]}

    def thesis(sym):
        return {"thesis_id": f"symbol_{sym.lower()}", "version": 24, "thesis_version": f"symbol_{sym.lower()}@v24", "status": "active",
                "stance": "watch", "summary": "Payments network with pricing power", "evidence_for": ["a", "b"],
                "counter_evidence": [], "invalidation_conditions": ["regulatory cap"], "updated_ts": (NOW - dt.timedelta(hours=thesis_age_h)).isoformat()}

    return ic.Loaders(resolve_subject=resolve_subject, facts=facts, instrument=instrument, thesis=thesis,
                      contradictions=(lambda s: contradictions or []), research_objects=(lambda s: research_objects or []),
                      hermes_completed=(lambda fp: hermes_completed), hermes_results=(lambda s: hermes_results or []),
                      now=lambda: NOW, release_sha="testsha")


def _env(tmp_path):
    return {"TRADEAI_MEMORY_CONTEXTS_PATH": str(tmp_path / "ctx.jsonl"),
            "TRADEAI_RETRIEVAL_RECEIPTS_PATH": str(tmp_path / "rr.jsonl"),
            "TRADEAI_INTELLIGENCE_MODE": "SHADOW"}


def _rows(p: Path):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def test_behavior_fields_match_the_rail():
    from cio_instrument_record import BEHAVIOR_FIELDS
    assert tuple(BEHAVIOR_FIELDS) == ic.behavior_fields()


def test_open_context_shape_and_receipt(tmp_path):
    env = _env(tmp_path)
    ctx = ic.open_context({"lane_id": "test-lane", "agent_id": "cio"}, "DECIDE", ["v"], loaders=_loaders(tmp_path), env=env)
    assert ctx["schema"] == ic.SCHEMA_CONTEXT and ctx["context_id"].startswith("ctx_")
    assert ctx["subjects"][0]["guid"].startswith("SEC:") and ctx["subjects"][0]["symbol"] == "V"
    assert [f["fact_id"] for f in ctx["facts"]] == ["mem_a", "mem_b"]
    fa, fb = ctx["facts"]
    assert fa["freshness_state"] == "CURRENT" and fb["freshness_state"] == "STALE"
    assert fb["contradiction_state"] == "OPEN" and fa["contradiction_state"] == "NONE"
    assert ctx["thesis"]["version"] == 24 and ctx["thesis"]["freshness_state"] == "CURRENT"
    assert ctx["beliefs"][0]["success_rate"] == 0.71 and ctx["next_research_question"] == "what changed?"
    assert ctx["degraded"] is False and ctx["memory_behavior_influence"] == 0
    assert ctx["prior_decisions"]["state"] == "UNMEASURED" and ctx["lessons_state"] == "NONE_PROMOTED"
    rows = _rows(tmp_path / "ctx.jsonl")
    assert len(rows) == 1 and rows[0]["event"] == "OPENED" and rows[0]["context_id"] == ctx["context_id"]
    for k in ic.behavior_fields():
        assert k not in json.dumps(ctx)


def test_shadow_degrades_when_a_loader_fails(tmp_path):
    env = _env(tmp_path)
    ctx = ic.open_context({"lane_id": "l"}, "DECIDE", ["V"], loaders=_loaders(tmp_path, facts_fail=True), env=env)
    assert ctx["degraded"] is True and "facts" in ctx["failed_classes"]
    assert any(r.startswith("FACTS_UNAVAILABLE") for r in ctx["degraded_reasons"])
    assert ctx["thesis"]["version"] == 24  # other classes still loaded


def test_enforced_decide_fails_closed_and_writes_refusal(tmp_path):
    env = _env(tmp_path)
    with pytest.raises(ic.MemoryUnavailable):
        ic.open_context({"lane_id": "l"}, "DECIDE", ["V"], mode="ENFORCED", loaders=_loaders(tmp_path, facts_fail=True), env=env)
    rows = _rows(tmp_path / "ctx.jsonl")
    assert rows[-1]["event"] == "REFUSED" and rows[-1]["disposition"] == "HOLD_MEMORY_UNAVAILABLE"


def test_enforced_monitor_degrades_instead_of_refusing(tmp_path):
    env = _env(tmp_path)
    ctx = ic.open_context({"lane_id": "health"}, "MONITOR", ["V"], mode="ENFORCED", loaders=_loaders(tmp_path, facts_fail=True), env=env)
    assert ctx["degraded"] is True


def test_unresolved_symbol_is_degraded_in_shadow_and_refused_in_enforced(tmp_path):
    env = _env(tmp_path)
    ctx = ic.open_context({"lane_id": "l"}, "ADVISE", ["zzzz"], loaders=_loaders(tmp_path, resolve=False), env=env)
    assert ctx["subjects"][0]["identity_status"] == "UNRESOLVED" and "IDENTITY_UNRESOLVED:ZZZZ" in ctx["degraded_reasons"]
    with pytest.raises(ic.MemoryUnavailable):
        ic.open_context({"lane_id": "l"}, "ADVISE", ["zzzz"], mode="ENFORCED", loaders=_loaders(tmp_path, resolve=False), env=env)


def test_namespaced_subjects_pass_through(tmp_path):
    ctx = ic.open_context({"lane_id": "l"}, "CURATE", ["DEC:abc"], loaders=_loaders(tmp_path), env=_env(tmp_path))
    assert ctx["subjects"][0]["identity_status"] == "NAMESPACED" and ctx["thesis"] == {}


def test_bad_inputs():
    with pytest.raises(ValueError):
        ic.open_context({"lane_id": "l"}, "GAMBLE", ["V"], loaders=ic.Loaders(now=lambda: NOW), write_receipt=False)
    with pytest.raises(ValueError):
        ic.open_context({}, "DECIDE", ["V"], loaders=ic.Loaders(now=lambda: NOW), write_receipt=False)


def test_ladder_hit_fresh_from_thesis_and_shadow_still_generates(tmp_path):
    env = _env(tmp_path)
    ctx = ic.open_context({"lane_id": "hermes-cio-worker"}, "RESEARCH", ["V"], loaders=_loaders(tmp_path), env=env)
    calls = []
    out = ic.retrieve_or_generate(ctx, {"text": "bull case?", "question_class": "bull"},
                                  generator=lambda c, q, r: calls.append(r["receipt_id"]) or "generated text",
                                  loaders=_loaders(tmp_path), env=env)
    assert out["decision"] == "HIT_FRESH" and out["generated"] is True and out["answer"] == "generated text"
    rec = out["receipt"]
    assert rec["schema"] == ic.SCHEMA_RETRIEVAL and rec["mode"] == "SHADOW" and rec["generation_reason"] == "SHADOW"
    assert [s["step"] for s in rec["ladder"]] == [1, 2, 3, 4, 5, 6, 7]
    assert rec["ladder"][1]["hit"] is True and rec["ladder"][6]["note"] == "not_installed"
    assert "symbol_v@v24" in rec["reused_refs"]
    assert _rows(tmp_path / "rr.jsonl")[0]["receipt_id"] == rec["receipt_id"] and calls == [rec["receipt_id"]]


def test_ladder_enforced_hit_fresh_answers_from_record_without_generating(tmp_path):
    env = {**_env(tmp_path), "TRADEAI_INTELLIGENCE_MODE": "ENFORCED"}
    ctx = ic.open_context({"lane_id": "l"}, "RESEARCH", ["V"], loaders=_loaders(tmp_path), env=env)
    out = ic.retrieve_or_generate(ctx, {"text": "thesis?", "question_class": "thesis"}, generator=lambda c, q, r: "SHOULD NOT RUN",
                                  loaders=_loaders(tmp_path), env=env)
    assert out["decision"] == "HIT_FRESH" and out["generated"] is False and out["answer"]["from_record"] is True


def test_ladder_stale_partial_and_miss(tmp_path):
    env = _env(tmp_path)
    # stale thesis → HIT_STALE
    ctx = ic.open_context({"lane_id": "l"}, "RESEARCH", ["V"], loaders=_loaders(tmp_path, thesis_age_h=31 * 24), env=env)
    out = ic.retrieve_or_generate(ctx, {"text": "bull?", "question_class": "bull"}, loaders=_loaders(tmp_path, thesis_age_h=31 * 24), env=env)
    assert out["decision"] == "HIT_STALE" and out["generated"] is False
    # no thesis field but evidence exists → HIT_PARTIAL
    ro = [{"research_object_id": "ro_1", "url": "https://example.test/a", "title": "t"}]
    out = ic.retrieve_or_generate(ctx, {"text": "catalysts?", "question_class": "catalyst"}, loaders=_loaders(tmp_path, research_objects=ro), env=env)
    assert out["decision"] == "HIT_PARTIAL" and out["receipt"]["ladder"][4]["refs"] == ["https://example.test/a"]
    # nothing → MISS with a full ladder
    ctx2 = ic.open_context({"lane_id": "l"}, "RESEARCH", ["DEC:only"], loaders=_loaders(tmp_path), env=env)
    out = ic.retrieve_or_generate(ctx2, {"text": "x", "question_class": "catalyst"}, loaders=_loaders(tmp_path), env=env)
    assert out["decision"] == "MISS" and len(out["receipt"]["ladder"]) == 7


def test_ladder_fingerprint_hit_is_step_one(tmp_path):
    env = _env(tmp_path)
    done = {"research_id": "res_9", "completed_ts": (NOW - dt.timedelta(hours=2)).isoformat()}
    ctx = ic.open_context({"lane_id": "l"}, "RESEARCH", ["V"], loaders=_loaders(tmp_path, thesis_age_h=40 * 24), env=env)
    out = ic.retrieve_or_generate(ctx, {"text": "q", "question_class": "catalyst", "fingerprint": "sha256:abc"},
                                  loaders=_loaders(tmp_path, thesis_age_h=40 * 24, hermes_completed=done), env=env)
    assert out["decision"] == "HIT_FRESH" and out["receipt"]["ladder"][0]["hit"] and "res_9" in out["receipt"]["reused_refs"]


def test_commit_records_and_refuses_behavior_fields(tmp_path):
    env = _env(tmp_path)
    ctx = ic.open_context({"lane_id": "l"}, "DECIDE", ["V"], loaders=_loaders(tmp_path), env=env)
    row = ic.commit(ctx, {"kind": "DECIDED", "ref": "dec_1"}, deltas=[{"subject_guid": "SEC:x", "class": "COMPANY", "value": "stance=watch"}],
                    influence={"changed_decision": False}, env=env)
    assert row["event"] == "COMMITTED" and row["deltas_applied"] is False and row["influence"]["consulted"] is True
    assert _rows(tmp_path / "ctx.jsonl")[-1]["context_id"] == ctx["context_id"]
    with pytest.raises(ic.BehaviorWriteRefused):
        ic.commit(ctx, {"kind": "DECIDED"}, deltas=[{"subject_guid": "SEC:x", "size_usd": 1000}], env=env)
    with pytest.raises(ic.BehaviorWriteRefused):
        ic.commit(ctx, {"kind": "DECIDED", "detail": {"nested": [{"stop": 33.5}]}}, env=env)


def test_resolve_mode_defaults_to_shadow():
    assert ic.resolve_mode({}) == "SHADOW" and ic.resolve_mode({"TRADEAI_INTELLIGENCE_MODE": "enforced"}) == "ENFORCED"
    assert ic.resolve_mode({"TRADEAI_INTELLIGENCE_MODE": "bogus"}) == "SHADOW"


def test_shadow_helpers_never_raise_and_record(tmp_path):
    env = _env(tmp_path)
    ctx = ic.shadow_open("hermes-cio-worker", ["V"], question={"text": "bull?", "question_class": "bull"}, env=env)
    # default loaders are used here (no injection) → identity/facts may degrade in a hermetic env, but never raise
    assert ctx is None or (ctx["mode"] == "SHADOW" and ctx["purpose"] == "RESEARCH")
    assert ic.shadow_open("l", [], env=env) is None
    ctx2 = ic.open_context({"lane_id": "l"}, "RESEARCH", ["V"], loaders=_loaders(tmp_path), env=env)
    rec = ic.observe_generation(ctx2, {"text": "bull?", "question_class": "bull"}, loaders=_loaders(tmp_path), env=env)
    assert rec["generated"] is True and rec["generation_reason"] == "SHADOW_CALLER" and rec["decision"] == "HIT_FRESH"
    assert ic.shadow_commit(None, {"kind": "X"}) is None
    assert ic.shadow_commit(ctx2, {"kind": "RESEARCHED", "ref": "res_1"}, env=env)["event"] == "COMMITTED"
    assert ic.shadow_commit(ctx2, {"kind": "RESEARCHED", "size_usd": 5}, env=env) is None
    assert _rows(tmp_path / "ctx.jsonl")[-1]["event"] == "REFUSED"


def test_contradictions_are_capped_but_counted(tmp_path):
    env = _env(tmp_path)
    many = [{"candidate_id": f"contra_{i}", "left_symbol": "V", "right_symbol": "V", "status": "CANDIDATE"} for i in range(300)]
    ctx = ic.open_context({"lane_id": "l"}, "DECIDE", ["V"], loaders=_loaders(tmp_path, contradictions=many), env=env)
    assert len(ctx["open_contradictions"]) == ic.CONTRADICTIONS_IN_CONTEXT and ctx["open_contradictions_count"] == 300
    assert ctx["open_contradictions_truncated"] is True and ctx["contradiction_state"] == "OPEN"
    assert len(json.dumps(ctx)) < 40_000
