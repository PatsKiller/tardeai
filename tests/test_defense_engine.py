"""DefenseProjection@v1 (design defense/v001): schema guard, synthetic projection, dry run, D2 triggers, D4 drop.

Synthetic tickers and values only (the repo is public).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import defense_engine as de  # noqa: E402
from lib.market_risk.contract import BEHAVIOR_FIELDS  # noqa: E402

NOW = datetime(2030, 1, 7, 15, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float = 0.0) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _mr(stressed=30.0, lagging=1, tech_pct=25.0, shock="SECTOR", stale=False) -> dict:
    return {
        "as_of": _iso(0.2), "stale": stale, "tier": "ORANGE", "score": 62.5,
        "shock_type": {"class": shock},
        "hedge": {"verdict": "watch", "thresholds": {"trigger_book_pct": 10, "index_trigger_lagging_sectors": 4},
                  "lagging_count": lagging, "stressed_pct_invested": stressed,
                  "stressed_breakdown": [{"key": "semis", "label": "Semis", "state": "STRESS", "usd": 1000.0,
                                          "pct_invested": tech_pct},
                                         {"key": "energy", "label": "Energy", "state": "WEAK", "usd": 100.0,
                                          "pct_invested": 2.0}]},
        "book_exposure": {"rows": [{"symbol": "ZZAA", "account_label": "Acct A", "value_usd": 1000.0,
                                    "stressed_share": 1.0, "usd_exposed": 1000.0, "stop_distance_pct": 3.0,
                                    "stance": "review", "material": True}],
                          "groups": [], "unmapped": [], "cash_pct_book": 40.0, "stressed_pct_invested": stressed},
        "deep_brief": {"generated_at": _iso(1), "facts": [
            {"id": "f1", "section": "next",
             "text": "SPY next 5 sessions: median -0.4%, 10th pct -3.1%, 90th pct 2.2%, lower in 56% of cases (n=41)"},
            {"id": "f2", "section": "next", "text": "A further drop followed in 38% of cases"}]},
    }


def _truth() -> dict:
    return {"generated_at": _iso(0.1), "positions": {"rows": [
        {"symbol": "ZZAA", "account_label": "Acct A", "market_value": 1000.0, "stop_category": "resting",
         "counted": True, "distance_to_stop_pct": 3.0},
        {"symbol": "ZZBB", "account_label": "Acct B", "market_value": 500.0, "stop_category": "none",
         "counted": True, "distance_to_stop_pct": None}]}}


def _recs() -> dict:
    return {"generated_at": _iso(2), "mode": "advisory", "groups": {
        "protect": [{"id": "p1", "title": "TRIM ZZAA", "instruments": [{"symbol": "ZZAA"}]},
                    {"id": "p2", "title": "MOVE-OUT ZZGONE", "instruments": [{"symbol": "ZZGONE"}]},
                    {"id": "p3", "title": "PUT HEDGES · status", "instruments": []}],
        "short_side": [{"title": "HEDGE · ZZQ"}]}}


def _build(**kw) -> dict:
    args = dict(mr=_mr(), truth=_truth(), recs=_recs(), now=NOW,
                policy_tiers={"blue": {"min_score": 25}, "yellow": {"min_score": 40},
                              "orange": {"min_score": 60}, "red": {"min_score": 75}})
    args.update(kw)
    return de.build_projection(**args)


# ── schema guard ─────────────────────────────────────────────────────────────

def _keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def test_projection_carries_no_size_order_share_or_level_field():
    doc = _build()
    bad = _keys(doc) & (set(BEHAVIOR_FIELDS) | set(de.FORBIDDEN_KEYS))
    assert not bad, bad
    assert doc["schema"] == de.SCHEMA and doc["read_only"] is True and doc["financial_action"] is False


@pytest.mark.parametrize("key", sorted(de.FORBIDDEN_KEYS | set(BEHAVIOR_FIELDS)))
def test_assert_advisory_refuses_every_forbidden_key(key):
    with pytest.raises(ValueError):
        de.assert_advisory({"exposure": {"rows": [{key: 1}]}})


def test_every_section_carries_as_of_and_stale_reason():
    doc = _build()
    for name in ("tier", "exposure", "stops", "hedge_readiness", "playbook", "base_rates", "cash_alternatives",
                 "sector_posture", "recommendations", "watch_next", "industries"):
        assert "as_of" in doc[name] and "stale_reason" in doc[name], name
    for row in doc["narrative"]["where_we_stand"]:
        assert {"as_of", "stale_reason", "text"} <= set(row)
    for s in doc["sources"]:
        assert {"as_of", "stale_reason", "state"} <= set(s)


def test_projection_with_nothing_on_file_states_why():
    doc = de.build_projection(mr=None, truth=None, now=NOW)
    assert doc["stale_reason"] == "Market Risk engine not on file"
    assert all(v["trigger"] is None for v in doc["hedge_readiness"]["inverse_triggers"].values())
    json.dumps(doc, default=str)


def test_synthetic_projection_content():
    doc = _build()
    assert doc["tier"]["tier"] == "ORANGE"
    assert [r["symbol"] for r in doc["base_rates"]["rows"]] == ["SPY"]
    assert doc["base_rates"]["rows"][0]["median_pct"] == -0.4 and doc["base_rates"]["further_drop_pct"] == 38.0
    assert [d["symbols"] for d in doc["recommendations"]["dropped_unheld"]] == [["ZZGONE"]]
    assert doc["narrative"]["headline"] and doc["narrative"]["what_to_do"]
    hr = doc["hedge_readiness"]
    assert hr["readiness"] == "NOT NOW" and hr["met_count"] == 1 and hr["stale_reason"] is None
    step = next(s for s in doc["narrative"]["what_to_do"] if s["id"] == "index-hedge")
    assert step["title"] == "Index hedge: not indicated."


def test_hedge_readiness_conditions_met_and_unknown():
    assert de.build_projection(mr=_mr(lagging=6), truth=_truth(), now=NOW)["hedge_readiness"]["readiness"] == "CONDITIONS MET"
    mr = _mr()
    mr["hedge"]["lagging_count"] = None
    assert de.build_projection(mr=mr, truth=_truth(), now=NOW)["hedge_readiness"]["readiness"] == "UNKNOWN"


# ── D2: look-through inverse triggers ────────────────────────────────────────

def test_inverse_triggers_qqq_fires_on_tech_share_index_needs_breadth():
    t = de.inverse_triggers(_mr(stressed=30.0, lagging=1, tech_pct=25.0), de.config(None))
    assert t["QQQ"]["trigger"] is True and t["QQQ"]["inverse"] == "PSQ"
    assert t["SPY"]["trigger"] is False and t["SPY"]["exposure_pct"] == 30.0


def test_inverse_triggers_index_fires_on_breadth_or_systemic_shock():
    assert de.inverse_triggers(_mr(lagging=5), de.config(None))["SPY"]["trigger"] is True
    assert de.inverse_triggers(_mr(lagging=0, shock="SYSTEMIC"), de.config(None))["IWM"]["trigger"] is True
    assert de.inverse_triggers(_mr(stressed=5.0, lagging=9), de.config(None))["DIA"]["trigger"] is False


def test_inverse_triggers_unknown_never_false():
    for t in (de.inverse_triggers(None, de.config(None)),
              de.inverse_triggers(_mr(), de.config(None), stale_reason="engine 9 h old")):
        assert all(v["trigger"] is None for v in t.values())


def test_thesis_inputs_from_projection_fresh_stale_missing():
    doc = _build()
    trig, expo, why = de.thesis_inputs_from_projection(doc, NOW + timedelta(hours=1), max_age_hours=26)
    assert why is None and trig["QQQ"] is True and expo["SPY"] == 30.0
    assert de.thesis_inputs_from_projection(doc, NOW + timedelta(hours=30), max_age_hours=26)[2]
    assert de.thesis_inputs_from_projection(None, NOW, max_age_hours=26) == ({}, {}, "defense engine projection not on file")


# ── D4: names no longer held ─────────────────────────────────────────────────

def test_drop_unheld_cards_keeps_held_status_and_other_groups():
    kept, dropped = de.drop_unheld_cards(_recs()["groups"], {"ZZAA"})
    assert [c["id"] for c in kept["protect"]] == ["p1", "p3"]
    assert kept["short_side"] == _recs()["groups"]["short_side"]
    assert dropped == [{"group": "protect", "id": "p2", "title": "MOVE-OUT ZZGONE", "symbols": ["ZZGONE"]}]


def test_drop_unheld_cards_unknown_holdings_drops_nothing():
    kept, dropped = de.drop_unheld_cards(_recs()["groups"], None)
    assert dropped == [] and len(kept["protect"]) == 3
    assert de.held_symbols({}) is None


# ── builder script: dry run writes nothing ───────────────────────────────────

def test_builder_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    import defense_engine_build as deb
    monkeypatch.setattr(deb, "load_market_risk", lambda root: (_mr(), None))
    monkeypatch.setattr(deb, "load_truth", lambda root: (_truth(), None))
    assert deb.main(["--dry-run", "--root", str(tmp_path)]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["schema"] == de.SCHEMA
    assert "nothing written" in cap.err
    assert not (tmp_path / de.OUT_REL).exists()
    assert list(tmp_path.rglob("*")) == []


def test_builder_writes_atomically(tmp_path, monkeypatch):
    import defense_engine_build as deb
    monkeypatch.setattr(deb, "load_market_risk", lambda root: (_mr(), None))
    monkeypatch.setattr(deb, "load_truth", lambda root: (_truth(), None))
    assert deb.main(["--root", str(tmp_path)]) == 0
    doc = json.loads((tmp_path / de.OUT_REL).read_text())
    assert doc["schema"] == de.SCHEMA
    assert [p.name for p in (tmp_path / "data" / "runtime").iterdir()] == ["defense_engine_latest.json"]


def test_engine_module_is_pure():
    import ast
    tree = ast.parse((ROOT / "scripts/lib/defense_engine.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__", "re", "datetime", "typing", "market_risk.contract", "lib.market_risk.contract"}, imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("place_order", "subprocess", "write_text", "write_bytes", "unlink", "mkdir", "commit", "open",
                      "read_text", "urlopen", "requests"):
        assert forbidden not in names, forbidden
