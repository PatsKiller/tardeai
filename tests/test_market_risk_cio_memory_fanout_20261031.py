"""CIO memory, watchlist-first candidate tiers and research fan-out (operator 2026-10-31: "make sure that the CIO is
memorizing all of this ... look first for stuff that we already researched that's on the watch list or our short list
... click off separate Hermes searches and Brave and you.com searches").

Hermetic: temp state roots, fake DB connection, the spine and providers stubbed. No network, no live stores.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone

from scripts.lib.market_risk import cio_memory_fanout as F
from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import rotation_advice as R
from scripts.lib.market_risk.policy import load_policy

POLICY = load_policy()
NOW = datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)
GROUPS = {
    "energy": {
        "label": "Energy",
        "kind": "sector",
        "symbols": ["XLE"],
        "class": "LEADERSHIP_CONFIRMED",
        "evidence": ["relative to SPY: +13.5% over 20"],
    },
    "tech": {"label": "Technology", "kind": "sector", "symbols": ["XLK"], "class": "NEUTRAL", "evidence": []},
}


def _items():
    fresh = {"analyst": "2026-10-27T10:00:00+00:00", "quote": "2026-10-30T20:00:00+00:00"}
    old = {"analyst": "2026-08-01T10:00:00+00:00", "quote": "2026-10-30T20:00:00+00:00"}
    return [
        {"symbol": "AAA", "sector": "Energy", "conviction": 80, "stance": "WATCH", "inputs_as_of": fresh},
        {"symbol": "BBB", "sector": "Energy", "conviction": 75, "stance": "WATCH", "inputs_as_of": old},
        {"symbol": "CCC", "sector": "Energy", "conviction": None, "momentum_score": 70},
        {"symbol": "DDD", "sector": "Energy", "conviction": None, "momentum_score": 20},
    ]


def _tiers(watchlist=None, records=None):
    return F.tiered_candidates(
        "energy",
        group_symbols=["XLE"],
        opportunity_items=_items(),
        watchlist={"AAA": {}} if watchlist is None else watchlist,
        instrument_records=records or {},
        group_of=lambda it: R.group_of(it, GROUPS),
        policy=POLICY,
        now=NOW,
    )


def test_watchlist_first_then_researched_then_new_leaders():
    t = _tiers()
    assert [r["symbol"] for r in t["tier1"]] == ["AAA"]
    assert [r["symbol"] for r in t["tier2"]] == ["BBB"]
    assert [r["symbol"] for r in t["tier3"]] == ["CCC"]  # DDD below the momentum floor: not a leader
    assert t["tier3"][0]["needs_research"] is True


def test_short_list_counts_as_tier1():
    t = _tiers(watchlist={}, records={"BBB": {"kind": "WATCH"}})
    assert [r["symbol"] for r in t["tier1"]] == ["BBB"]


def test_research_age_ignores_market_data_and_flags_stale():
    t = _tiers()
    aaa, bbb = t["tier1"][0], t["tier2"][0]
    assert 3 < aaa["research_age_days"] < 5 and not aaa["research_stale"]  # 10-27 analyst, not the 10-30 quote
    assert bbb["research_stale"] is True


def _trigs():
    prev = {
        "leadership": {"energy": "NEUTRAL"},
        "shock_type": None,
        "tier": "YELLOW",
        "reentry": {"SPCX": "RE_ENTER_IF"},
    }
    cur = {
        "as_of": "2026-10-30",
        "leadership": {"energy": "LEADERSHIP_CONFIRMED", "tech": "NEUTRAL"},
        "shock_type": "SECTOR",
        "tier": "ORANGE",
        "reentry": {"SPCX": "RE_ENTER"},
    }
    return F.triggers(prev, cur), cur


def test_triggers_cover_every_transition_and_nothing_else():
    trigs, _ = _trigs()
    kinds = sorted(t["kind"] for t in trigs)
    assert kinds == ["leadership_transition", "reentry_flip", "shock_type_change", "tier_change"]
    assert (
        F.triggers(
            {"leadership": {"energy": "LEADERSHIP_CONFIRMED"}}, {"leadership": {"energy": "LEADERSHIP_CONFIRMED"}}
        )
        == []
    )


BRAVE_OK = {"daily_used": 20, "daily_limit": 300}


def test_research_plan_routes_to_existing_lanes_with_caps():
    trigs, _ = _trigs()
    plan = F.plan_research(
        trigs, groups=GROUPS, tiers_by_group={"energy": _tiers()}, policy=POLICY, brave_status=BRAVE_OK
    )
    labels = {(j["kind"], j["label"]) for j in plan["hermes"]}
    assert (
        ("sector", "Energy") in labels and ("ticker", "CCC") in labels and ("ticker", "BBB") in labels
    )  # stale re-research
    assert ("ticker", "AAA") not in labels  # fresh research is not repeated
    assert all(j["trigger_id"].startswith("mrt_") for j in plan["hermes"] + plan["brave"])
    assert {j["symbol"] for j in plan["brave"]} >= {"XLE", "SPY", "SPCX"}
    assert plan["youcom"] and all("unavailable" in j["status"] for j in plan["youcom"])
    c.assert_no_behavior_fields(plan)


def test_brave_fails_closed_and_respects_headroom():
    trigs, _ = _trigs()
    none = F.plan_research(trigs, groups=GROUPS, tiers_by_group={}, policy=POLICY, brave_status=None)
    assert none["brave"] == []
    tight = F.plan_research(
        trigs, groups=GROUPS, tiers_by_group={}, policy=POLICY, brave_status={"daily_used": 299, "daily_limit": 300}
    )
    assert tight["brave"] == []  # inside the reserve left for every other caller


def test_trigger_dedupe_skips_already_enqueued():
    trigs, _ = _trigs()
    plan = F.plan_research(
        trigs, groups=GROUPS, tiers_by_group={}, policy=POLICY, brave_status=BRAVE_OK, already={t["id"] for t in trigs}
    )
    assert plan["hermes"] == [] and plan["brave"] == []


def test_memory_plan_passes_memory_admission_rules():
    from scripts.lib.agent_memory_governance import is_forbidden_authoritative

    trigs, cur = _trigs()
    mem = F.plan_memory(
        trigs,
        groups=GROUPS,
        cur=cur,
        exits=[{"symbol": "SPCX", "date": "2026-10-30", "stressed_groups": ["Technology"]}],
        tiers_by_group={"energy": _tiers()},
        snapshot_ref="data/runtime/market_risk_latest.json",
        policy=POLICY,
    )
    targets = sorted(m["target"] for m in mem)
    assert targets.count("aif_memory") == 2 and "sector_record" in targets and "spine" in targets
    for m in mem:
        if m["target"] == "aif_memory":
            assert not is_forbidden_authoritative(m["record"]["content"])
            assert m["record"]["source_refs"]


def test_apply_memory_writes_and_the_cio_recalls_the_episode(tmp_path, monkeypatch):
    spine_calls = []
    spine = types.ModuleType("scripts.lib.cross_asset.security_research_spine")
    spine.upsert_research_memory = lambda sym, **kw: spine_calls.append((sym, kw)) or {"ok": True}
    monkeypatch.setitem(sys.modules, "scripts.lib.cross_asset.security_research_spine", spine)
    trigs, cur = _trigs()
    mem = F.plan_memory(
        trigs,
        groups=GROUPS,
        cur=cur,
        exits=[{"symbol": "ZZZQ", "date": "2026-10-30"}],
        tiers_by_group={"energy": _tiers()},
        snapshot_ref="snap.json",
        policy=POLICY,
    )
    receipts = F.apply_memory(mem, root=tmp_path)
    assert all(not r.get("error") for r in receipts), receipts
    from scripts.lib.agent_durable_memory import DurableJsonlMemoryProvider

    found = DurableJsonlMemoryProvider(tmp_path / "data" / "cio" / "aif_memory.jsonl").search(
        query="market regime episode", top_k=5
    )
    assert any("SECTOR" in (r.get("content") or "") for r in found.get("records") or found.get("memories") or []), found
    from scripts.lib import cio_instrument_record as ir

    rec = ir.InstrumentRecordStore(tmp_path / ir.DEFAULT_PATH).load(ir.subject_key("SECTOR", "Energy"))
    assert rec and "Energy" in rec["next_research_question"] and rec["lessons"][-1]["event"] == "leadership_transition"
    assert spine_calls and spine_calls[0][1]["tags"] == ["market_risk"] and spine_calls[0][1]["silo"] == "cio"


def test_ask_the_cio_recalls_market_risk_spine_items(monkeypatch):
    from scripts.lib import cio_ask_memory as am
    from scripts.lib.cio_ask_contract import EntityRef

    spine = types.ModuleType("scripts.lib.cross_asset.security_research_spine")
    spine.load_latest = lambda sym, path=None: {
        "subject_guid": None,
        "contributions": [
            {
                "ts": "2026-10-31",
                "kind": "market_risk.event",
                "summary": "SPCX exited during a SECTOR selloff",
                "artifact_id": "mrt_1",
                "tags": ["market_risk"],
            },
            {"ts": "2026-10-30", "kind": "x", "summary": "unrelated", "artifact_id": "x1", "tags": ["other"]},
        ],
    }
    monkeypatch.setitem(sys.modules, "scripts.lib.cross_asset.security_research_spine", spine)
    items = am.SpineAskMemory().recall(entity=EntityRef(name="SPCX", symbol="SPCX"))
    assert [i["ref"] for i in items] == ["mrt_1"]


def test_apply_research_uses_the_single_writer_and_governed_producer(monkeypatch):
    calls = {}

    class Cur:
        pass

    class Conn:
        def cursor(self):
            return Cur()

        def commit(self):
            calls["commit"] = True

        def close(self):
            calls["close"] = True

    w = types.ModuleType("scripts.lib.writers.watch_directives_writer")

    def wwd(cur, rows, *, source, on_duplicate):
        calls["rows"] = rows
        calls["source"] = source
        return types.SimpleNamespace(rows_in=len(rows), rows_written=len(rows), rejects=[])

    w.write_watch_directives = wwd
    monkeypatch.setitem(sys.modules, "scripts.lib.writers.watch_directives_writer", w)
    g = types.ModuleType("scripts.lib.governed_research_producer")
    g.produce_research = lambda targets: (
        calls.setdefault("brave", targets) and types.SimpleNamespace(ok=True, outcome="ok", errors=[])
    )
    monkeypatch.setitem(sys.modules, "scripts.lib.governed_research_producer", g)
    trigs, _ = _trigs()
    plan = F.plan_research(
        trigs, groups=GROUPS, tiers_by_group={"energy": _tiers()}, policy=POLICY, brave_status=BRAVE_OK
    )
    out = F.apply_research(plan, conn_factory=Conn, policy=POLICY)
    assert calls["source"] == "market_risk_rotation" and calls["commit"] and calls["close"]
    assert all(r["hermes_enabled"] and "[trigger mrt_" in r["rationale"] for r in calls["rows"])
    assert calls["brave"] and out["youcom"].startswith("unavailable")
