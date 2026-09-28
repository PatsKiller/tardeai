"""Wave 3 tranche 1 — cognitive checkpoints, lesson promotion queue, memory influence ladder, contradiction adjudicator."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import cognitive_checkpoint as ck  # noqa: E402
import contradiction_adjudicator as ca  # noqa: E402
import intelligence_client as ic  # noqa: E402
import lesson_promotion as lp  # noqa: E402
import memory_influence as mi  # noqa: E402


def _env(tmp_path, **extra):
    e = {"TRADEAI_CIO_DIR": str(tmp_path / "cio"), "TRADEAI_MEMORY_CONTEXTS_PATH": str(tmp_path / "ctx.jsonl"),
         "TRADEAI_RETRIEVAL_RECEIPTS_PATH": str(tmp_path / "rr.jsonl"), "TRADEAI_MEMORY_DELTA_BUS": "0"}
    e.update(extra)
    return e


# ── checkpoints ───────────────────────────────────────────────────────────────

def test_checkpoint_write_chain_restore_and_kill_switch(tmp_path):
    env = _env(tmp_path)
    r1 = ck.write("cio", lane_id="persistent-wake", task_ref="WAKE:w1", subjects=["g1"], context_id="c1", env=env,
                  considered=[{"option": "trim", "verdict": "ruled_out", "reason": "no evidence"}],
                  waiting_on=[{"kind": "RESEARCH", "ref": "hermes:1", "deadline": "2026-01-01T00:00:00+00:00"}, {"kind": "OUTCOME", "ref": "o1"}],
                  next_action={"kind": "REVIEW", "ref": "w1"})
    r2 = ck.write("cio", lane_id="persistent-wake", task_ref="WAKE:w1", subjects=["g1"], env=env)
    assert r1["step"] == 1 and r2["step"] == 2 and r2["hash_prev"] == r1["hash_self"]
    assert r1["considered"][0]["verdict"] == "RULED_OUT" and ck.write("cio", lane_id="l", task_ref="w2", env=env)["task_ref"] == "CTX:w2"
    ok, n, why = ck.verify_chain("cio", env=env)
    assert ok and n == 3 and why is None
    res = ck.restore("cio", task_ref="WAKE:w1", env=env, now=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc))
    assert res["checkpoint"]["checkpoint_id"] == r2["checkpoint_id"] and res["next_action"] is None
    res1 = ck.restore("cio", env=env)
    assert res1["checkpoint"]["task_ref"] == "CTX:w2"
    first = ck.restore("cio", task_ref="WAKE:w1", env=env)  # r2 has no waits; r1 did → use r1 via limit
    assert first["receipt"]["schema"] == "ResumeReceipt@v1"
    assert (tmp_path / "cio" / "agent_checkpoints" / "resume_receipts.jsonl").exists()
    off = {**env, "TRADEAI_COGNITIVE_CHECKPOINT": "0"}
    assert ck.write("cio", lane_id="l", task_ref="x", env=off) is None and ck.restore("cio", env=off) is None


def test_facade_commit_writes_a_checkpoint_and_shadow_open_attaches_resume(tmp_path, monkeypatch):
    env = _env(tmp_path)
    ctx = ic.open_context({"lane_id": "persistent-wake", "agent_id": "cio"}, "DECIDE", ["V"], loaders=ic.Loaders(), env=env)
    ic.commit(ctx, {"kind": "DECIDED", "ref": "wake-1"}, env=env)
    row = ck.last("cio", env=env)
    assert row and row["task_ref"] == "WAKE:wake-1" and row["context_id"] == ctx["context_id"] and row["provisional_view"] == "wake-1"
    mon = ic.open_context({"lane_id": "health", "agent_id": "health"}, "MONITOR", ["V"], loaders=ic.Loaders(), env=env)
    ic.commit(mon, {"kind": "OBSERVED", "ref": "m"}, env=env)
    assert ck.last("health", env=env) is None                       # monitors never checkpoint
    monkeypatch.setattr(ic, "default_loaders", lambda root=None, env=None: ic.Loaders())
    ctx2 = ic.shadow_open("persistent-wake", ["V"], "DECIDE", agent_id="cio", env=env)
    assert ctx2["resumed_from"] == row["checkpoint_id"] and ctx2["resume"]["waiting_open"] == 0
    ic.set_current_context(None)


# ── lessons ───────────────────────────────────────────────────────────────────

def test_lesson_queue_gather_enqueue_decide_and_loader(tmp_path):
    cio = tmp_path / "cio"; rt = tmp_path / "runtime"; cio.mkdir(); rt.mkdir()
    (cio / "lesson_candidates.jsonl").write_text(json.dumps({"schema": "LessonCandidate@v2", "lesson_id": "lc1", "scope": "options", "task_class": "review",
                                                            "statement": "Do not roll a covered call into an earnings week without the 8-K on file.", "symbols": ["DELL"]}) + "\n")
    (rt / "advisory_kb_lessons.jsonl").write_text(json.dumps({"lesson_id": "kb1", "status": "ratified", "ratified_by": "iris_auto_safe",
                                                              "statement": "Idle cash above the IPS band is a decision, not a default."}) + "\n"
                                                  + json.dumps({"lesson_id": "kb2", "status": "retired", "statement": "retired lesson text here"}) + "\n")
    (cio / "aif_memory.jsonl").write_text(json.dumps({"kind": "PROCEDURAL_HINT", "memory_id": "m1", "content": "short"}) + "\n")  # too short → dropped
    env = _env(tmp_path)
    cands = lp.gather(env=env)
    assert {c["source"] for c in cands} == {"lesson_candidates", "advisory_kb_ratified"} and all(c["status"] == "CANDIDATE" for c in cands)
    dry = lp.enqueue(env=env)
    assert dry["new"] == 2 and dry["written"] == 0 and not lp.queue_path(env=env).exists()
    assert lp.enqueue(env=env, apply=True)["written"] == 2 and lp.enqueue(env=env, apply=True)["new"] == 0
    assert lp.promoted(env=env) == []                                  # nothing promoted → nothing reaches a context
    pid = [c for c in cands if c["source"] == "lesson_candidates"][0]["procedure_id"]
    with pytest.raises(PermissionError):
        lp.decide(pid, "PROMOTED", by="iris:auto", env=env)
    lp.decide(pid, "PROMOTED", by="operator:mine:typed", env=env)
    assert [p["procedure_id"] for p in lp.promoted(env=env, symbol="DELL")] == [pid]
    assert lp.promoted(env=env, symbol="NOC") == []                    # symbol-scoped lesson stays with its symbol
    items = lp.package_items(env=env)
    assert len(items) == 1 and items[0]["title"].startswith("PROMOTE")
    # the façade carries only PROMOTED procedures
    loaders = ic.Loaders(resolve_subject=lambda s: {"security_guid": "g", "ticker_alias": s}, lessons=lambda s: lp.promoted(env=env, symbol=s))
    ctx = ic.open_context({"lane_id": "l"}, "RESEARCH", ["DELL"], loaders=loaders, env=env)
    assert ctx["lessons_state"] == "PROMOTED_PRESENT" and ctx["lessons"][0]["procedure_id"] == pid
    ctx2 = ic.open_context({"lane_id": "l"}, "RESEARCH", ["NOC"], loaders=loaders, env=env)
    assert ctx2["lessons_state"] == "NONE_PROMOTED"


# ── influence ladder ──────────────────────────────────────────────────────────

def _policy(tmp_path, **surfaces):
    p = tmp_path / "pol.json"
    p.write_text(json.dumps({"influence": {"default": "SHADOW", "surfaces": surfaces}}))
    return str(p)


def test_influence_mode_render_and_receipt(tmp_path):
    pol = _policy(tmp_path, research="ADVISORY", watchlists="SHADOW")
    env = {"TRADEAI_MEMORY_INFLUENCE_POLICY": pol}
    assert mi.mode_for("research", env) == "ADVISORY" and mi.mode_for("watchlists", env) == "SHADOW" and mi.mode_for("nope", env) == "SHADOW"
    assert mi.mode_for("research", {**env, "TRADEAI_INTELLIGENCE_MODE": "SHADOW"}) == "SHADOW"
    ctx = {"context_id": "c", "as_of": "t", "subjects": [{"symbol": "V"}], "facts": [{"claim": "backlog $95B", "source": "8-K", "fact_id": "f1"}],
           "thesis": {"version": 3, "summary": "network effects", "thesis_id": "th1"}, "beliefs": [{"claim": "moat holds", "state": "REFUTED"}],
           "lessons": [{"kind": "LESSON", "statement": "wait for the filing", "promoted_at": "2026-09-27", "decided_by": "operator:mine"}],
           "open_contradictions_count": 2, "contradiction_state": "OPEN"}
    block = mi.advisory_block(ctx)
    assert block.startswith("=== MEMORY SAYS") and "flags: CONTESTED, RECONSIDER" in block and "backlog $95B" in block and "wait for the filing" in block
    assert mi.render("research", ctx, env) == block and mi.render("watchlists", ctx, env) == ""      # SHADOW never renders
    assert mi.advisory_block({"facts": [], "thesis": {}}) == ""
    inf = mi.influence_for(ctx, "research", rendered=True, env=env)
    assert inf["mode"] == "ADVISORY" and inf["mir"] is True and inf["memory_content_present"] and inf["changed_decision"] is False
    shadow = mi.influence_for(ctx, "watchlists", rendered=False, env=env)
    assert shadow["mode"] == "SHADOW" and shadow["mir"] is False and shadow["would_render"] is True


def test_facade_surface_records_influence_and_renders_only_at_advisory(tmp_path, monkeypatch):
    pol = _policy(tmp_path, research="ADVISORY", watchlists="SHADOW")
    env = _env(tmp_path, TRADEAI_MEMORY_INFLUENCE_POLICY=pol)
    loaders = ic.Loaders(resolve_subject=lambda s: {"security_guid": "g", "ticker_alias": s}, thesis=lambda s: {"thesis_id": "t", "version": 1, "summary": "s"})
    monkeypatch.setattr(ic, "default_loaders", lambda root=None, env=None: loaders)
    r = ic.shadow_open("hermes-cio-worker", ["V"], "RESEARCH", surface="research", env=env)
    assert r["influence_mode"] == "ADVISORY" and r["advisory_rendered"] and "MEMORY SAYS" in r["advisory_block"]
    row = ic.shadow_commit(r, {"kind": "RESEARCHED", "ref": "x"}, env=env)
    assert row["influence"]["mode"] == "ADVISORY" and row["influence"]["mir"] is True and row["influence"]["surface"] == "research"
    w = ic.shadow_open("watchlist-agent-alex", ["V"], "RESEARCH", surface="watchlists", env=env)
    assert w["influence_mode"] == "SHADOW" and not w["advisory_rendered"] and w["advisory_block"] == "" and w["advisory_would_render"] is True
    row2 = ic.shadow_commit(w, {"kind": "RESEARCHED", "ref": "y"}, env=env)
    assert row2["influence"]["mode"] == "SHADOW" and row2["influence"]["mir"] is False and row2["influence"]["would_render"] is True
    ic.set_current_context(None)


# ── adjudicator ───────────────────────────────────────────────────────────────

def _cand(cid, l, r, ls="DELL", rs="DELL"):
    return {"schema": "ResearchContradictionCandidate@v1", "candidate_id": cid, "status": "CANDIDATE", "left_artifact_id": l, "right_artifact_id": r,
            "left_symbol": ls, "right_symbol": rs, "shared_context": ["sector:tech"], "opposition": {"left_classification": "STRENGTHENS", "right_classification": "WEAKENS"},
            "evidence_refs": ["e1"]}


def test_adjudicator_selects_unjudged_parses_and_fails_closed(tmp_path, monkeypatch):
    cands = [_cand("c1", "a", "b"), _cand("c2", "c", "d"), _cand("c3", "e", "f", "NOC", "NOC")]
    sel = ca.select_pairs(cands, already={"c2"}, max_pairs=5)
    assert {c["candidate_id"] for c in sel} == {"c1", "c3"}
    assert len(ca.select_pairs(cands, already=set(), max_pairs=1)) == 1
    v = ca.parse_verdict('{"verdict": "left", "confidence": 1.7, "rationale": "r", "decisive_evidence_refs": ["e1"]}')
    assert v["verdict"] == "LEFT" and v["confidence"] == 1.0
    bad = ca.parse_verdict("no json here")
    assert bad["verdict"] == "UNRESOLVED" and bad["schema_invalid"]
    ok = ca.parse_verdict('prose then {"verdict": "NOT_A_CONTRADICTION", "confidence": 0.8, "rationale": "different horizons"} trailing')
    assert ok["verdict"] == "NOT_A_CONTRADICTION"
    # Tier-2 gate: unknown spend → denied (fail-closed); disabled → denied
    class Pol:
        tier2_enabled = True
        def tier2_denial(self, *, spent_today_usd, now, judge_provider):
            return None if spent_today_usd is not None else "DENIED_SPEND_UNKNOWN"
    import types
    monkeypatch.setitem(sys.modules, "tiered_validation", types.SimpleNamespace(TierPolicy=types.SimpleNamespace(from_env=lambda env: Pol())))
    monkeypatch.setitem(sys.modules, "llm_consumption", types.SimpleNamespace(ledger_paid_usd_today=lambda pid: (_ for _ in ()).throw(RuntimeError("no ledger"))))
    assert ca.tier2_gate({}, dt.datetime.now(dt.timezone.utc)) == "DENIED_SPEND_UNKNOWN"
    monkeypatch.setitem(sys.modules, "llm_consumption", types.SimpleNamespace(ledger_paid_usd_today=lambda pid: 0.10))
    assert ca.tier2_gate({}, dt.datetime.now(dt.timezone.utc)) is None
    text, prov = ca.judge(ca.build_request(cands[0], "left text", "right text"), call_fn=lambda prompt: ('{"verdict":"RIGHT","confidence":0.6,"rationale":"x"}', {"model": "m"}))
    assert ca.parse_verdict(text)["verdict"] == "RIGHT" and prov["model"] == "m"


def test_verdicts_close_pairs_in_facade_and_projector(tmp_path):
    cio = tmp_path / "data" / "cio"; cio.mkdir(parents=True); (tmp_path / "data" / "runtime").mkdir()
    (cio / "research_contradiction_candidates.jsonl").write_text("".join(json.dumps(_cand(c, "a", "b")) + "\n" for c in ("c1", "c2", "c3")))
    (cio / "contradiction_verdicts.jsonl").write_text(json.dumps({"schema": "ContradictionVerdict@v1", "candidate_id": "c1", "verdict": "LEFT"}) + "\n"
                                                      + json.dumps({"schema": "ContradictionVerdict@v1", "candidate_id": "c2", "verdict": "UNRESOLVED"}) + "\n")
    env = {"TRADEAI_CIO_DIR": str(cio), "TRADEAI_MEMORY_CONTEXTS_PATH": str(tmp_path / "ctx.jsonl"), "TRADEAI_RETRIEVAL_RECEIPTS_PATH": str(tmp_path / "rr.jsonl")}
    loaders = ic.default_loaders(tmp_path, env)
    ids = {c["candidate_id"] for c in loaders.contradictions("DELL")}
    assert ids == {"c2", "c3"}                                          # LEFT closes c1; UNRESOLVED keeps c2 open
    import gir_projector as gp
    reg = {"entities": {"e1": {"security_guid": "sg1", "ticker_alias": "DELL", "active": True, "identity_status": "CONFIRMED"}}, "by_symbol": {}}
    (tmp_path / "data" / "runtime" / "identity_registry.json").write_text(json.dumps(reg))
    pj = gp.build(tmp_path, env={})
    assert pj.counts["contradictions_projected"] == 3 and pj.counts["contradictions_resolved"] == 1
    assert pj.envelopes["SEC:sg1"]["contradictions"] == {"state": "OPEN", "open": 2, "resolved": 1}
    assert pj.envelopes["CONTRA:c1"]["contradictions"]["state"] == "RESOLVED" and pj.envelopes["CONTRA:c2"]["contradictions"]["state"] == "OPEN"
    assert "contradiction_verdicts" in gp._source_fingerprints(tmp_path, {})


def test_facts_off_subject_are_counted_not_carried(tmp_path):
    env = _env(tmp_path)
    def facts(symbols, guids):
        return {"supporting": [{"memory_id": "m1", "symbols": ["V"], "memory_type": "CASE_SUMMARY"},
                               {"memory_id": "m2", "symbols": ["XLB"], "memory_type": "CASE_SUMMARY"},
                               {"memory_id": "m3", "subject_guid": "g", "memory_type": "RESEARCH_REFERENCE"},
                               {"memory_id": "m4", "memory_type": "OPERATOR_EXPLICIT_PREFERENCE"}]}
    loaders = ic.Loaders(resolve_subject=lambda s: {"security_guid": "g", "ticker_alias": s}, facts=facts)
    ctx = ic.open_context({"lane_id": "l"}, "RESEARCH", ["V"], loaders=loaders, env=env)
    assert ctx["fact_ids"] == ["m1", "m3", "m4"] and ctx["facts_off_subject"] == 1
