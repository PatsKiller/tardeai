"""Wave 4 tranche 1 — one agent registry, one model chooser (shadow), DEC/ACT projection, ladder L4/L5 (shadow), worker contract."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_registry as ar  # noqa: E402
import model_chooser as mc  # noqa: E402
import worker_contract as wc  # noqa: E402
import memory_influence as mi  # noqa: E402


# ── registry ──────────────────────────────────────────────────────────────────

def test_registry_absorbs_every_hardcoded_agent_list():
    from cio_event_bus import AGENT_EVENT_ROUTING
    from persistent_agent_wake import KNOWN_AGENTS
    known = ar.known_ids()
    assert known, "config/agent_registry.json must load"
    def ids_of(path):
        if not path.exists():
            return []
        d = json.loads(path.read_text())
        a = d.get("agents", d)
        return [k for k in (a.keys() if isinstance(a, dict) else [x.get("id") or x.get("agent_id") for x in a])
                if k and not str(k).startswith(("schema", "_", "version", "as_of", "authority"))]
    for lists in (AGENT_EVENT_ROUTING.keys(), KNOWN_AGENTS, ids_of(ROOT / "config" / "agents.json"), ids_of(ROOT / "config" / "agent_runtime_mvl.json")):
        for aid in lists:
            assert ar.canonical(aid), f"agent id {aid!r} is not an alias in config/agent_registry.json"
    assert ar.canonical("alex") == "cio" and ar.canonical("maria_research") == "maria" and ar.canonical("guardian") == "risk_agent"
    assert "cio" in ar.wake_eligible() and "risk_agent" not in ar.wake_eligible()
    assert ar.model_caller("tax_agent") == "ledger"


def test_bus_routing_is_shadow_by_default_and_registry_when_flagged(tmp_path, monkeypatch):
    from cio_event_bus import CIOEventBus
    bus = CIOEventBus(bus_path=str(tmp_path / "data" / "cio" / "bus.jsonl"), cursor_path=str(tmp_path / "data" / "cio" / "cur.jsonl"))
    monkeypatch.setenv("TRADEAI_AGENT_REGISTRY_ROUTING_RECEIPTS", str(tmp_path / "routing.jsonl"))
    monkeypatch.delenv("TRADEAI_AGENT_REGISTRY_ROUTING", raising=False)
    static = bus.route_to_agents("thesis.changed")
    assert static == ["alex"]                                            # unchanged in SHADOW
    reg = ar.subscribers("thesis.changed")
    assert "cio" in reg and "maria" in reg
    rows = [json.loads(l) for l in (tmp_path / "routing.jsonl").read_text().splitlines()]
    assert rows and rows[-1]["static"] == ["alex"] and "maria" in rows[-1]["registry"]
    monkeypatch.setenv("TRADEAI_AGENT_REGISTRY_ROUTING", "1")
    assert bus.route_to_agents("thesis.changed") == sorted(reg)
    assert not any("memory.delta" in (a.get("bus_events") or []) for a in ar.agents())   # fan-out owns memory.delta, not agent wakes


# ── chooser ───────────────────────────────────────────────────────────────────

def _reg(tmp_path):
    p = tmp_path / "procs.json"
    p.write_text(json.dumps({"processes": [
        {"id": "judge", "allowed_lanes": ["fast", "deepseek-flash", "deepseek-flash"], "deepseek_default_policy": "FAST", "lane_policy": "deepseek_only"},
        {"id": "reader", "allowed_lanes": ["grok", "deepseek-flash"], "deepseek_default_policy": "FAST", "lane_policy": "oauth_first"}]}))
    return {"TRADEAI_LLM_PROCESS_REGISTRY": str(p), "TRADEAI_MODEL_CHOOSER_RECEIPTS_PATH": str(tmp_path / "mc.jsonl")}


def test_chooser_shadow_advise_enforce(tmp_path):
    env = _reg(tmp_path)
    c = mc.choose("judge", requested_lane="grok", env=env)
    assert c["registered"] and c["lane"] == "fast" and c["allowed_lanes"] == ["fast", "deepseek-flash"] and "not in allowed" in c["reason"]
    assert mc.choose("reader", env=env)["lane"] == "grok"               # free lane first when the policy permits
    assert mc.choose("judge", env=env)["lane"] == "fast"                 # deepseek_only never gets a free lane
    assert mc.choose("nope", requested_lane="grok", env=env)["registered"] is False
    assert mc.choose("reader", requested_lane="deepseek-flash", budget_state={"paid_exhausted": True}, env=env)["lane"] == "grok"
    use, ch = mc.apply("judge", "grok", env=env)
    assert use == "grok" and ch["disagree"] and ch["mode"] == "shadow"  # shadow keeps the caller's lane
    rows = [json.loads(l) for l in (tmp_path / "mc.jsonl").read_text().splitlines()]
    assert rows[-1]["schema"] == "ModelChoice@v1" and rows[-1]["used_lane"] == "grok"
    use, _ = mc.apply("reader", None, env={**env, "TRADEAI_MODEL_CHOOSER": "advise"})
    assert use == "grok"
    use, _ = mc.apply("judge", "grok", env={**env, "TRADEAI_MODEL_CHOOSER": "enforce"})
    assert use == "fast"
    use, _ = mc.apply("judge", "deepseek-flash", env={**env, "TRADEAI_MODEL_CHOOSER": "enforce"})
    assert use == "deepseek-flash"                                       # an allowed caller lane is never overridden


# ── projector: decisions + actions ────────────────────────────────────────────

def test_projector_projects_decisions_and_actions(tmp_path, monkeypatch):
    import gir_projector as gp
    cio = tmp_path / "data" / "cio"; cio.mkdir(parents=True); (tmp_path / "data" / "runtime").mkdir()
    reg = {"entities": {"e1": {"security_guid": "sg1", "ticker_alias": "DELL", "active": True, "identity_status": "CONFIRMED"}}, "by_symbol": {}}
    (tmp_path / "data" / "runtime" / "identity_registry.json").write_text(json.dumps(reg))
    (cio / "options_theses.jsonl").write_text(
        json.dumps({"event_type": "OPTIONS_THESIS_VERSION", "position_guid": "p1", "symbol": "DELL"}) + "\n"
        + json.dumps({"event_type": "OPTIONS_THESIS_DECISION", "position_guid": "p1", "decision_guid": "dec_1", "outcome": "MONITOR_ONLY", "recorded_at": "2026-09-27T23:22:13+00:00"}) + "\n"
        + json.dumps({"event_type": "OPTIONS_THESIS_DECISION", "position_guid": "p1", "decision_guid": "dec_2", "outcome": "HOLD", "supersedes": "dec_1", "recorded_at": "2026-09-28T00:00:00+00:00"}) + "\n")
    (cio / "cio_action_ledger.jsonl").write_text(
        json.dumps({"event_type": "CIO_ACTION_CREATED", "stream_id": "cio-action-1", "occurred_at": "t", "actor_id": "cio_run_worker",
                    "payload": {"cio_action_id": "cio-action-1", "title": "AVOID DELL", "status": "OPEN", "affected_symbols": [], "origin_run_id": "run-9", "cio_decision_id": "dec_2"}}) + "\n"
        + json.dumps({"event_type": "CIO_ACTION_UPDATED", "stream_id": "cio-action-1", "payload": {}}) + "\n")
    import types
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: (_ for _ in ()).throw(RuntimeError("no db"))))
    pj = gp.build(tmp_path, env={})
    assert pj.counts["decisions_projected"] == 2 and pj.counts["actions_projected"] == 1 and pj.counts["cio_decisions_unavailable"] == "RuntimeError"
    rels = {(e["from_guid"], e["to_guid"], e["relation"]) for e in pj.edges.values()}
    assert ("DEC:dec_1", "SEC:sg1", "DECIDED_ON") in rels and ("DEC:dec_2", "DEC:dec_1", "SUPERSEDES") in rels
    assert ("ACT:cio-action-1", "DEC:dec_2", "CAUSED_BY") in rels and ("ACT:cio-action-1", "RUN:run-9", "CAUSED_BY") in rels
    assert ("ACT:cio-action-1", "SEC:sg1", "TRIGGERED") in rels        # symbol recovered from the title when affected_symbols is empty
    assert pj.entities["DEC:dec_1"]["class"] == "DECISION" and pj.entities["ACT:cio-action-1"]["kind"] == "ACTION"
    fp = gp._source_fingerprints(tmp_path, {})
    assert "options_theses" in fp and "cio_action_ledger" in fp


# ── ladder L4/L5 shadow ───────────────────────────────────────────────────────

def test_ladder_l4_l5_shadow_records_without_paging(tmp_path, monkeypatch):
    import supervisor_breach_detector as sbd
    rt = tmp_path / "data" / "runtime"; rt.mkdir(parents=True); (tmp_path / "data" / "governance").mkdir()
    now = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
    old = (now - dt.timedelta(hours=5)).isoformat()
    hist = [{"breach_id": "b1", "lane_id": "L", "kind": "SILENT", "detected_at": old}] + \
           [{"breach_id": f"b{i}", "lane_id": "M", "kind": "NO_OUTPUT", "detected_at": (now - dt.timedelta(days=i)).isoformat()} for i in (1, 2, 3)]
    (rt / "supervisor_breaches.jsonl").write_text("".join(json.dumps(h) + "\n" for h in hist))
    paged = []
    import types
    monkeypatch.setitem(sys.modules, "telegram_alert", types.SimpleNamespace(send_telegram=lambda msg, **kw: paged.append(msg)))
    rows = [{"breach_id": "b1", "lane_id": "L", "kind": "SILENT", "detected_at": old, "level": 1},
            {"breach_id": "b9", "lane_id": "M", "kind": "NO_OUTPUT", "detected_at": now.isoformat(), "level": 1}]
    sla = {"L": {"ladder_max": 5}, "M": {"ladder_max": 5}}
    out = sbd._ladder_l4_l5(rows, sla, now, rt, live=False)
    assert out["l4_candidates"] == 1 and out["l5_candidates"] == 1 and out["l4_paged"] == 0 and out["l5_proposed"] == 0 and not paged
    recs = [json.loads(l) for l in (rt / "supervisor_ladder_receipts.jsonl").read_text().splitlines()]
    assert {r["breach_id"]: r["level"] for r in recs} == {"b1": 4, "b9": 5} and recs[0]["mode"] == "shadow"
    assert sbd._ladder_l4_l5(rows, {"L": {"ladder_max": 3}, "M": {"ladder_max": 3}}, now, rt, live=False)["l4_candidates"] == 0  # ladder_max caps it
    out2 = sbd._ladder_l4_l5(rows, sla, now, rt, live=True)
    assert out2["l4_paged"] == 1 and paged and "supervisor L4" in paged[0] and out2["l5_proposed"] == 1
    assert (tmp_path / "data" / "governance" / "orchestration_proposals.jsonl").exists()


# ── worker contract ───────────────────────────────────────────────────────────

def test_worker_lease_vocabulary_and_reclaim(tmp_path):
    env = {"TRADEAI_LEASES_DIR": str(tmp_path / "leases")}
    assert wc.canonical_status("processing") == "RUNNING" and wc.canonical_status("IN_FLIGHT") == "RUNNING" and wc.canonical_status("superseded") == "ABANDONED"
    assert wc.canonical_status("weird") == "QUEUED" and wc.canonical_status("DONE") == "DONE"
    with wc.lease("lane-a", env=env, heartbeat=False) as w:
        w.claimed(3); w.done(2); w.failed("boom")
        w.status("i1", "processing")
        with pytest.raises(wc.LeaseHeld):
            with wc.lease("lane-a", env=env, heartbeat=False):
                pass
    row = json.loads((tmp_path / "leases" / "lane-a.json").read_text())
    assert row["released_at"] and row["outcome"] == "FAILED" and row["work"] == {"claimed": 3, "done": 2, "failed": 1}
    # a stale lease (expired TTL) is reclaimed and the reclaim is recorded
    stale = {**row, "released_at": None, "expires_at": "2020-01-01T00:00:00+00:00", "lease_id": "lease_old"}
    (tmp_path / "leases" / "lane-a.json").write_text(json.dumps(stale))
    with wc.lease("lane-a", env=env, heartbeat=False) as w2:
        assert w2.reclaimed_from["lease_id"] == "lease_old" and w2.reclaimed_from["why"] == "ttl expired"


def test_weighted_mode_adds_the_weighting_instruction(tmp_path):
    pol = tmp_path / "pol.json"
    pol.write_text(json.dumps({"influence": {"default": "SHADOW", "surfaces": {"options_advisory": "WEIGHTED", "research": "ADVISORY"}}}))
    env = {"TRADEAI_MEMORY_INFLUENCE_POLICY": str(pol)}
    ctx = {"context_id": "c", "as_of": "t", "subjects": [{"symbol": "V"}], "thesis": {"version": 1, "summary": "s", "thesis_id": "t"}}
    assert "MEMORY WEIGHT" in mi.render("options_advisory", ctx, env) and "MBI_BEHAVIOR = 0" in mi.render("options_advisory", ctx, env)
    assert "MEMORY WEIGHT" not in mi.render("research", ctx, env)
