"""Wave 2 tranche 3 — single write path adapter, citation index rows, edge fan-out work items."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import research_index_writer as riw  # noqa: E402
import research_write_path as rwp  # noqa: E402
import edge_fanout_consumer as efc  # noqa: E402


def _env(tmp_path, **extra):
    pol = tmp_path / "policy.json"
    pol.write_text(json.dumps({"write_path": {"default": "SHADOW", "adapters": {"hermes-external": "LIVE", "watchlist-agent": "SHADOW"}}}))
    e = {"TRADEAI_MEMORY_INFLUENCE_POLICY": str(pol), "TRADEAI_WRITE_PATH_RECEIPTS_PATH": str(tmp_path / "wp.jsonl")}
    e.update(extra)
    return e


def test_mode_resolution_family_default_and_kill_switch(tmp_path):
    env = _env(tmp_path)
    assert rwp.mode_for("hermes-external-chatgpt", env) == "LIVE"
    assert rwp.mode_for("watchlist-agent-alex", env) == "SHADOW"
    assert rwp.mode_for("options-cio-review", env) == "SHADOW"          # unlisted → default
    assert rwp.mode_for("hermes-external-chatgpt", {**env, "TRADEAI_INTELLIGENCE_MODE": "SHADOW"}) == "SHADOW"  # global kill switch wins
    assert rwp.mode_for("options-cio-review", {**env, "TRADEAI_WRITE_PATH_MODE": "LIVE"}) == "LIVE"


def test_shadow_submit_records_receipt_and_touches_no_store(tmp_path, monkeypatch):
    env = _env(tmp_path)
    called = []
    monkeypatch.setattr(rwp, "_lib", lambda name: (_ for _ in ()).throw(AssertionError(f"SHADOW must not import {name}")) if name in ("research_thesis_delta", "cio_product_reassessment") else __import__(name))
    ctx = {"context_id": "ctx_abc", "retrieval_receipt_id": "rr_1", "degraded": False}
    out = rwp.submit("watchlist-agent-alex", "dell", {"summary": "Backlog $95B", "recommendation": "hold"}, research_id="res-1", ctx=ctx, env=env)
    assert out["ok"] and out["mode"] == "SHADOW" and out["accepted"] is False and out["context_id"] == "ctx_abc"
    assert not called
    rows = rwp.read_receipts(env=env)
    assert len(rows) == 1 and rows[0]["schema"] == "WritePathReceipt@v1"
    r = rows[0]
    assert r["outcome"] == "SHADOW_RECORDED" and r["symbol"] == "DELL" and r["classification"] == "NO_NEW_INFO"
    assert r["context_id"] == "ctx_abc" and r["retrieval_receipt_id"] == "rr_1" and r["memory_context_miss"] is False
    assert r["would_call"] == "research_thesis_delta.accept_research_result" and r["memory_behavior_influence"] == 0


def test_normalize_never_upgrades_classification_and_defaults_unstructured(tmp_path):
    p = rwp.normalize({"answer": "x", "classification": "bogus", "stance": "BUY"}, symbol="V", lane_id="l")
    assert p["classification"] == "NO_NEW_INFO" and p["summary"] == "x" and p["recommendation"] == "BUY"
    p2 = rwp.normalize({"summary": "y", "classification": "weakens", "evidence": {"a": 1}}, symbol="V", lane_id="l")
    assert p2["classification"] == "WEAKENS" and p2["evidence"] == [{"a": 1}]


def test_live_submit_calls_the_single_writer_and_stamps_provenance(tmp_path, monkeypatch):
    env = _env(tmp_path)
    seen = {}

    class FakeRTD:
        @staticmethod
        def accept_research_result(symbol, result, *, prompt_context, research_id, root=None, provider=None, model=None, trigger=None, **kw):
            seen.update({"symbol": symbol, "result": result, "research_id": research_id, "trigger": trigger})
            return {"ok": True, "version_published": False, "publish_suppressed_reason": "no_material_change"}

    class FakeRPC:
        @staticmethod
        def build_research_prompt_context(symbol, *, question, root=None):
            return {"symbol": symbol, "standing_thesis": {}}

    real = rwp._lib
    monkeypatch.setattr(rwp, "_lib", lambda n: {"research_thesis_delta": FakeRTD, "research_prompt_context": FakeRPC}.get(n) or real(n))
    out = rwp.submit("hermes-external-chatgpt", "V", {"summary": "s", "classification": "STRENGTHENS"}, research_id="42",
                     ctx={"context_id": "ctx_1"}, env=env)
    assert out["mode"] == "LIVE" and out["accepted"] is True
    assert seen["symbol"] == "V" and seen["research_id"] == "42" and seen["result"]["context_id"] == "ctx_1"
    assert seen["result"]["memory_context_miss"] is False and seen["result"]["classification"] == "STRENGTHENS"
    row = rwp.read_receipts(env=env)[-1]
    assert row["outcome"] == "ACCEPTED" and row["mode"] == "LIVE"


def test_submit_never_raises_into_the_producer(tmp_path, monkeypatch):
    env = _env(tmp_path)
    monkeypatch.setattr(rwp, "normalize", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = rwp.submit("aec-thesis-fact", "V", {"summary": "s"}, research_id="x", env=env)
    assert out["ok"] is False and "RuntimeError" in out["error"]
    assert rwp.read_receipts(env=env)[-1]["outcome"] == "ERROR"


def test_stamp_provenance_prefers_ctx_then_current_context(monkeypatch):
    r = rwp.stamp_provenance({}, {"context_id": "c1", "retrieval_receipt": {"receipt_id": "rr9"}, "degraded": True})
    assert r["context_id"] == "c1" and r["retrieval_receipt_id"] == "rr9" and r["memory_context_miss"] is False and r["memory_context_degraded"] is True
    import intelligence_client as ic
    ic.set_current_context({"context_id": "c2", "retrieval_receipt": "rr2"})
    try:
        r2 = rwp.stamp_provenance({})
        assert r2["context_id"] == "c2" and r2["retrieval_receipt_id"] == "rr2"
    finally:
        ic.set_current_context(None)
    r3 = rwp.stamp_provenance({})
    assert r3["context_id"] is None and r3["memory_context_miss"] is True


# ── citation index ────────────────────────────────────────────────────────────

def test_canonical_url_and_index_rows():
    a = riw.canonical_url("HTTP://WWW.Example.com:80/a/b/?utm_source=x&b=2&a=1#frag")
    b = riw.canonical_url("https://example.com/a/b?a=1&b=2")
    assert a == b == "https://example.com/a/b?a=1&b=2"
    now = dt.datetime(2026, 9, 28, 1, 0, tzinfo=dt.timezone.utc)
    delta = {"delta_id": "rtd_1", "structured_answers": {"thesis": "t", "catalysts": "c"},
             "source_refs": ["https://a.com/x?utm_medium=m", {"url": "https://b.com/y"}, "not a url"]}
    rows = riw.rows_for(delta, subject_guid="g1", answered_at=now)
    classes = [(r["question_class"], r["horizon"]) for r in rows]
    assert ("thesis", "default") in classes and ("catalysts", "default") in classes and ("invalidation", "default") not in classes
    cites = [r for r in rows if r["question_class"] == "citation"]
    assert len(cites) == 2 and all(r["horizon"].endswith(":2026-09-28") for r in cites)
    assert {r["answer_ref"] for r in cites} == {"https://a.com/x", "https://b.com/y"}
    assert all(r["tenant_id"] == riw.TENANT for r in rows)
    assert riw.rows_for(delta, subject_guid="") == []            # unresolved subject → nothing to index
    assert riw.rows_for({"structured_answers": {}}, subject_guid="g") == []  # no ref → nothing


def test_index_delta_is_fail_soft_without_a_database(monkeypatch):
    monkeypatch.setattr(riw, "_conn", lambda env: None)
    out = riw.index_delta({"delta_id": "rtd_2"}, subject_guid="g1", env={})
    assert out["pg"] == "absent" and out["rows"] == 1 and out["written"] == 0
    assert riw.index_delta({"delta_id": "rtd_2"}, subject_guid="g1", env={"TRADEAI_RESEARCH_INDEX": "0"})["pg"] == "skipped"
    assert riw.latest("g1", "thesis", env={}) is None and riw.cited_urls("g1", env={}) == []


# ── edge fan-out ──────────────────────────────────────────────────────────────

def test_subjects_for_handles_namespaced_guids_and_symbol_fallback():
    g = "1527f991-a8d0-5d42-a52d-fb8878beb0cc"
    assert efc.subjects_for({"payload": {"subjects": [f"SEC:{g}", "THESIS:x", g]}}) == [g]
    assert efc.subjects_for({"payload": {"symbol": "XAR"}}, lambda s: {"security_guid": g}) == [g]
    assert efc.subjects_for({"payload": {"symbol": "XAR"}}, lambda s: None) == []


def test_work_items_are_idempotent_and_route_from_edges():
    g = "1527f991-a8d0-5d42-a52d-fb8878beb0cc"
    ev = {"event_id": "evt1", "event_type": "thesis.changed", "payload": {"symbol": "XAR"}}
    nb = [{"guid": "ACCOUNT:ira", "depth": 1, "class": "OPERATIONAL", "kind": "ACCOUNT"},
          {"guid": "BELIEF:HELD:XAR:b1", "depth": 1, "class": "AGENT", "kind": "BELIEF"},
          {"guid": "CONTRA:c1", "depth": 1, "class": "RISK", "kind": "CONTRADICTION"},
          {"guid": "SEC:other", "depth": 2, "class": "COMPANY", "kind": "SECURITY"},
          {"guid": "EVENT:e1", "depth": 1, "class": "MARKET", "kind": "EVENT"}]
    now = dt.datetime(2026, 9, 28, tzinfo=dt.timezone.utc)
    items = efc.work_items(ev, g, nb, now)
    kinds = [(i["kind"], i.get("target")) for i in items]
    assert kinds[0] == ("reproject", None) and items[0]["events"] == ["EVENT:e1"]
    assert ("notify", "ACCOUNT:ira") in kinds and ("notify", "BELIEF:HELD:XAR:b1") in kinds
    assert ("reproject", "SEC:other") in kinds and ("notify", "cio") in kinds
    again = efc.work_items(ev, g, nb, now + dt.timedelta(hours=1))
    assert [i["idempotency_key"] for i in again] == [i["idempotency_key"] for i in items]
    assert all(i["schema"] == "EdgeFanoutWorkItem@v1" and i["memory_behavior_influence"] == 0 for i in items)
    # no neighbourhood (no DSN) → subject-only reproject item, never nothing
    assert [i["kind"] for i in efc.work_items(ev, g, [], now)] == ["reproject"]


def test_traverse_is_empty_without_a_connection():
    assert efc.traverse(None, "g") == []


def test_projector_treats_dirty_file_as_a_source_and_marks_it_consumed(tmp_path):
    import gir_projector as gp
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    dirty = tmp_path / "data" / "runtime" / "gir_projector_dirty.json"
    state = tmp_path / "state.json"
    env = {}
    needed, cur, prev = gp.incremental_needed(tmp_path, state, env)
    assert needed and cur["gir_projector_dirty"] is None
    state.write_text(json.dumps({"sources": cur}))
    assert gp.incremental_needed(tmp_path, state, env)[0] is False
    dirty.write_text(json.dumps({"schema": "GirProjectorDirty@v1", "ts": "t", "subjects": ["g1"]}))
    assert gp.incremental_needed(tmp_path, state, env)[0] is True
    gp._consume_dirty(dirty, dt.datetime(2026, 9, 28, tzinfo=dt.timezone.utc))
    d = json.loads(dirty.read_text())
    assert d["consumed_at"] and d["consumed_subjects"] == 1 and dirty.exists()
