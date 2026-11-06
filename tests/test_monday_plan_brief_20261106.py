"""Next-session plan brief (PKG-SELLOFF-INTEL-20261106 A). Synthetic fixtures only: no holdings, no live data.

ANCHOR: MONDAY_PLAN_BRIEF_20261106
"""
from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import monday_plan_brief as m  # noqa: E402

NOW = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)  # Sunday 18:00 ET


def _snapshot() -> dict:
    return {
        "as_of": "2026-11-06T21:00:00Z",
        "tier": "ORANGE",
        "reentry_watch": {
            "_stages_contract": "ReentryStages@v2",
            "ZZAA": {  # every condition met, verdict present
                "as_of": "2026-11-06",
                "conditions": [{"key": "a", "met": True, "text": "cond a"}, {"key": "b", "met": True, "text": "cond b"}],
                "stages": {"verdict": "Confirmed"},
                "base_rate": {"n": 4, "beat_waiting": 3, "rate": 0.75, "horizon_sessions": 20},
            },
            "ZZBB": {  # no verdict from the backend, partly met
                "as_of": "2026-11-06",
                "conditions": [{"key": "a", "met": True, "text": "cond a"}, {"key": "b", "met": False, "text": "cond b"}],
            },
            "ZZCC": {"as_of": "2026-11-06", "conditions": [], "stages": {}},  # nothing evaluated
        },
        "sectors": {
            "benchmark": {"symbol": "SPY", "r5": -2.0},
            "groups": [
                {"label": "Group One", "symbols": ["AAA1"], "state": "STRESS", "r5": -9.0, "rs5": -7.0, "dd20": -15.0},
                {"label": "Group Two", "symbols": ["BBB2"], "state": "WEAK", "r5": -3.0, "rs5": -1.0, "dd20": -21.0},
                {"label": "Group Three", "symbols": ["CCC3"], "state": "RESILIENT", "r5": 4.0, "rs5": 6.0, "dd20": -1.0},
            ],
        },
    }


def _deep_brief() -> dict:
    return {
        "source": "built_on_demand",
        "text": "\n".join([
            "MARKET RISK DEEP BRIEF - ORANGE",
            "",
            "What's happening",
            "- Volatility: VIX 27.0 ≥ 25.0 [now-a]",
            "",
            "What usually happens next",
            "- Matched 40 past trading days [hist-a]",
            "",
            "Your exposure",
            "- Positions driving book vulnerability: ZZAA (stop 3.0% away), ZZBB [pos-a]",
            "",
            "Advisory. No order, size or stop level is implied; the decision is yours.",
        ]),
        "facts": [
            {"id": "hist-a", "section": "next", "text": "Matched 40 past trading days 2016-2025"},
            {"id": "hist-i", "section": "next", "text": "Nearest past setups: 2022-10-13; 2020-03-23"},
            {"id": "now-a", "section": "now", "text": "Volatility"},
        ],
    }


CAL = [
    {"fact_id": "best_six_months", "title": "best six months", "reproduced": True, "evidence_grade": "B"},
    {"fact_id": "pre_holiday", "title": "pre holiday", "reproduced": False, "evidence_grade": "C",
     "notes": "monthly series cannot express it"},
    {"fact_id": "september_weakness", "title": "september weakness", "reproduced": True, "evidence_grade": "B"},
]
OPPS = [{"symbol": f"ZQ{i}", "sector": "Testing", "conviction": 50 + i, "stance": "WATCH", "upside_pct": 10.0} for i in range(8)]


@pytest.fixture()
def roots(tmp_path: Path):
    state = tmp_path / "state"
    (state / "data" / "runtime" / "market_risk").mkdir(parents=True)
    _write_snapshot(state, _snapshot())
    data = tmp_path / "project"
    data.mkdir()
    return data, state


def _write_snapshot(state: Path, snap: dict) -> None:
    """Write the synthetic snapshot the way the engine does: temp file, then os.replace."""
    import os

    target = state / "data" / "runtime" / "market_risk" / "latest.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap))
    os.replace(tmp, target)


def _build(roots, **kw):
    data, state = roots
    kw.setdefault("deep_brief_loader", _deep_brief)
    kw.setdefault("calendar_rows", CAL)
    kw.setdefault("opportunity_items", OPPS)
    return m.build(now=NOW, data_root=data, state_root=state, **kw)


def test_brief_carries_every_section_and_the_footer(roots):
    text = _build(roots)
    assert "Plan for the next session: Monday 2026-11-09" in text
    assert "What usually happens next (matched past days" in text
    assert "- Matched 40 past trading days 2016-2025" in text
    assert "Nearest past setups: 2022-10-13; 2020-03-23" in text
    assert "Calendar facts for November" in text
    assert "- best six months: reproduced, evidence B" in text
    assert "- pre holiday: NOT reproduced, evidence C" in text
    assert "september weakness" not in text  # not a November fact
    assert "Re-entry watch (status only):" in text
    assert text.rstrip().endswith(m.FOOTER)


def test_deep_brief_body_drops_duplicate_disclaimer_and_stop_distance(roots):
    text = _build(roots)
    assert "What usually happens next\n" not in text  # the block is shown once, from the facts
    assert "[hist-a]" not in text
    assert "stop level" not in text and "stop 3.0% away" not in text
    assert "ZZAA, ZZBB [pos-a]" in text
    assert "VIX 27.0 >= 25.0" in text  # the comparison survives typographic folding


def test_reentry_never_defaults_a_verdict_or_claims_all_met(roots):
    text = _build(roots)
    assert "- ZZAA: all 2 conditions met" in text
    assert "Confirmed" not in text and "stage" not in text.split("Re-entry watch")[1].split("Stressed")[0]
    assert "- ZZBB: 1 of 2 conditions met" in text
    assert "- ZZCC: conditions not evaluated" in text
    assert "beat waiting 20 sessions in 3 of 4 past setups (75%)" in text


def test_stressed_groups_sorted_by_drawdown_and_resilient_excluded(roots):
    text = _build(roots)
    two, one = text.index("- Group Two (BBB2) weak"), text.index("- Group One (AAA1) stress")
    assert two < one
    assert "off 20d high -21.0%" in text
    assert "Group Three" not in text


def test_implausible_group_move_says_data_check_failed(roots):
    data, state = roots
    snap = _snapshot()
    snap["sectors"]["groups"].append(
        {"label": "Bad Bar", "symbols": ["DDD4"], "state": "STRESS", "r5": -42.8, "rs5": -40.3, "dd20": -50.0})
    snap["sectors"]["groups"].append(
        {"label": "Deep Real", "symbols": ["EEE5"], "state": "STRESS", "r5": -24.0, "rs5": -20.0, "dd20": -40.0})
    _write_snapshot(state, snap)
    text = _build(roots)
    assert "- Bad Bar (DDD4) stress: data check failed" in text
    assert "-42.8" not in text and "-50.0" not in text
    assert "- Deep Real (EEE5) stress: 5d -24.0%" in text  # a March-2020-sized move still prints


def test_implausible_52w_distance_in_deep_brief_is_withheld(roots):
    db = {"source": "stored", "text": "- Technical: SOXX -79.4% off 52w high; QQQ -12.0% off 52w high [now-c]",
          "facts": []}
    text = _build(roots, deep_brief_loader=lambda: db)
    assert "SOXX distance from 52w high: data check failed" in text
    assert "-79.4" not in text
    assert "QQQ -12.0% off 52w high" in text


def test_top_five_opportunities_by_conviction(roots):
    text = _build(roots)
    assert "Top 5 on the opportunity board by conviction:" in text
    assert "- ZQ7 " in text and "- ZQ3 " in text and "- ZQ2 " not in text


def test_unreadable_sources_say_so_and_never_read_as_zero(tmp_path: Path):
    def boom():
        raise RuntimeError("reader down")

    text = m.build(now=NOW, data_root=tmp_path, state_root=tmp_path / "missing",
                   deep_brief_loader=boom, calendar_rows=[], opportunity_items=[])
    assert "Deep brief: unavailable (reader down)" in text
    assert "Re-entry watch: unavailable (no market-risk snapshot)" in text
    assert "Stressed groups: unavailable (no market-risk snapshot)" in text
    assert "Top opportunities: unavailable" in text
    assert "- none of the tracked calendar facts applies" in text


def test_deep_brief_unavailable_reason_is_shown(roots):
    text = _build(roots, deep_brief_loader=lambda: {"source": "unavailable", "reason": "no engine snapshot"})
    assert "Deep brief: unavailable (no engine snapshot)" in text


def test_sizing_or_stop_wording_refuses_the_brief(roots):
    bad = {"source": "stored", "text": "Set a stop at 41.", "facts": []}
    with pytest.raises(ValueError):
        _build(roots, deep_brief_loader=lambda: bad)


def test_next_session_skips_weekend_and_holiday():
    assert m.next_session(date(2026, 11, 6)) == date(2026, 11, 9)  # Friday -> Monday
    assert m.next_session(date(2026, 11, 25)) == date(2026, 11, 27)  # Thanksgiving 2026-11-26


def _patch_build(monkeypatch, text="BRIEF"):
    monkeypatch.setattr(m, "build", lambda **kw: text)


def test_dry_run_prints_and_sends_nothing(monkeypatch, capsys):
    _patch_build(monkeypatch)
    monkeypatch.setattr(m, "send", lambda t: pytest.fail("dry run must not send"))
    assert m.main(["--dry-run"]) == 0
    assert capsys.readouterr().out.strip() == "BRIEF"


def test_live_run_goes_through_the_telegram_chokepoint(monkeypatch, capsys):
    calls = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda text, **kw: calls.append((text, kw)) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    _patch_build(monkeypatch)
    assert m.main([]) == 0
    assert calls == [("BRIEF", {"priority": "P2", "producer": "monday_plan_brief"})]
    assert json.loads(capsys.readouterr().out)["accepted"] is True


def test_guard_refusal_exits_2(monkeypatch):
    def refuse(**kw):
        raise ValueError("sizing text")

    monkeypatch.setattr(m, "build", refuse)
    monkeypatch.setattr(m, "send", lambda t: pytest.fail("refused brief must not send"))
    assert m.main(["--dry-run"]) == 2


def test_source_makes_no_http_or_broker_call():
    import ast

    src = (ROOT / "scripts" / "monday_plan_brief.py").read_text(encoding="utf-8")
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    banned = ("requests", "urllib", "http", "httpx", "aiohttp", "socket", "schwab", "alpaca", "moomoo", "order")
    assert not [mm for mm in mods if any(b in mm.lower() for b in banned)], mods
    for needle in ("place_order", "7777", "http://", "https://"):
        assert needle not in src, needle
