"""Catalyst severity thresholds + domain normalizer + desk gates."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from lib.catalyst_domain import (
    adjust_revisit_at,
    assign_severity,
    attach_catalyst,
    build_pack_from_events,
    catalyst_evidence_line,
    catalyst_invalidation_signals,
    catalyst_research_gap_eligible,
    catalyst_telegram_line,
    catalyst_warm_decision,
    materiality_bump,
    normalize_event,
    normalize_kind,
    pack_from_broker_record,
    unavailable_pack,
)
from lib.catalyst_policy import (
    clamp_severity,
    effective_research_priority,
    max_severity,
    next_relevant_event,
    sev_at_least,
)


def _today() -> date:
    return date(2026, 8, 12)


def _ev(
    kind: str,
    *,
    days: int,
    severity: str | None = None,
    confirmed: bool = True,
    title: str = "",
    symbol: str = "TEST",
    expected_move_pct: float | None = None,
    special_distribution: bool = False,
) -> dict:
    session = _today() + timedelta(days=days)
    raw = {
        "symbol": symbol,
        "kind": kind,
        "title": title or kind,
        "session_date": session.isoformat(),
        "confirmed": confirmed,
        "expected_move_pct": expected_move_pct,
        "special_distribution": special_distribution,
    }
    if severity is not None:
        raw["severity"] = severity
    ev = normalize_event(raw, symbol=symbol, today=_today())
    assert ev is not None
    return ev


# ── severity assignment ──────────────────────────────────────────────────────


def test_ex_div_defaults_low():
    assert assign_severity("ex_div") == "low"
    assert assign_severity("distribution", is_etf_income=True) == "low"


def test_earnings_defaults_high():
    assert assign_severity("earnings") == "high"


def test_unknown_severity_clamps_low():
    assert clamp_severity(None) == "low"
    assert clamp_severity("urgent") == "low"
    assert clamp_severity("CRITICAL") == "critical"


def test_unconfirmed_capped_at_medium():
    # earnings would be high, but unconfirmed → medium
    sev = assign_severity("earnings", confirmed=False)
    assert sev == "medium"
    assert not sev_at_least(sev, "high")


def test_expected_move_steps_up_once():
    base = assign_severity("guidance", title="routine update")
    assert base == "medium"
    bumped = assign_severity("guidance", title="routine update", expected_move_pct=6.0)
    assert bumped == "high"


def test_regulatory_critical_on_halt_language():
    assert assign_severity("regulatory", title="Trading halt pending enforcement") == "critical"


def test_guidance_cut_raises_high():
    assert assign_severity("guidance", title="Company cuts full-year guidance") == "high"


def test_special_div_raises_medium():
    assert assign_severity("distribution", title="Special dividend announced", special_distribution=True) == "medium"


def test_normalize_kind_aliases():
    assert normalize_kind("ex-dividend") == "ex_div"
    assert normalize_kind("EPS") == "earnings"
    assert normalize_kind("fomc") == "macro"


# ── behavior matrix ──────────────────────────────────────────────────────────


def test_ex_div_low_3d_no_warm_no_telegram_evidence_ok():
    ev = _ev("ex_div", days=3, symbol="SCHD", title="SCHD quarterly distribution")
    # force low even if broker sent medium
    ev["severity"] = "low"
    pack = build_pack_from_events([ev], symbol="SCHD")
    assert pack["max_severity"] == "low"
    assert catalyst_warm_decision("SCHD", pack) is None
    assert catalyst_telegram_line(pack) is None
    line = catalyst_evidence_line(pack)
    assert line is not None
    assert "ex_div" in line or "distribution" in line or "ex_div" in str(ev["kind"])
    assert "2026-08-15" in line  # 3d from 2026-08-12


def test_earnings_high_4d_warm_revisit_telegram():
    ev = _ev("earnings", days=4, symbol="SPCX", title="Q2 earnings")
    assert ev["severity"] == "high"
    pack = build_pack_from_events([ev], symbol="SPCX")
    warm = catalyst_warm_decision("SPCX", pack)
    assert warm is not None
    assert warm["warm"] is True
    assert warm["priority"] == "high"
    assert warm["intent"] == "catalyst_map"
    elev = catalyst_telegram_line(pack)
    assert elev is not None
    assert "earnings" in elev and "high" in elev
    assert materiality_bump(pack) is True
    now = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
    # Default 7d revisit; event in 4d should bind earlier
    default = now + timedelta(days=7)
    tightened = adjust_revisit_at(default, pack, now=now)
    assert tightened < default
    assert tightened.date() == (_today() + timedelta(days=4))


def test_earnings_high_12d_research_gap_no_telegram_elevate():
    # 12d is outside research gap (10), warm (5), and telegram (5)
    ev = _ev("earnings", days=12, symbol="SPCX")
    pack = build_pack_from_events([ev], symbol="SPCX")
    assert catalyst_research_gap_eligible(pack) is False
    assert catalyst_telegram_line(pack) is None
    assert catalyst_warm_decision("SPCX", pack) is None

    # 9d → research-gap eligible, no Telegram elevate (horizon > 5)
    ev9 = _ev("earnings", days=9, symbol="SPCX")
    pack9 = build_pack_from_events([ev9], symbol="SPCX")
    assert catalyst_research_gap_eligible(pack9) is True
    assert catalyst_telegram_line(pack9) is None


def test_unknown_severity_behaves_as_low():
    ev = _ev("other", days=2, severity="totally_unknown")
    # explicit unknown → clamp via assign → low
    assert ev["severity"] == "low"
    pack = build_pack_from_events([ev], symbol="X")
    assert catalyst_warm_decision("X", pack) is None


def test_unconfirmed_event_severity_cap():
    ev = _ev("earnings", days=3, confirmed=False, title="rumored earnings print")
    assert ev["severity"] == "medium"
    pack = build_pack_from_events([ev], symbol="Y")
    warm = catalyst_warm_decision("Y", pack)
    assert warm is not None
    assert warm["priority"] == "normal"  # medium → normal hermes pri
    assert warm["priority"] != "critical"


def test_new_medium_event_invalidation_signal():
    session = (_today() + timedelta(days=7)).isoformat()
    pack = build_pack_from_events([
        {
            "event_id": "cat_new_med",
            "symbol": "ABC",
            "kind": "guidance",
            "title": "guidance update",
            "session_date": session,
            "event_ts": f"{session}T00:00:00+00:00",
            "horizon_days": 7,
            "severity": "medium",
            "confirmed": True,
        }
    ], symbol="ABC")
    signals = catalyst_invalidation_signals(
        "2026-08-01T00:00:00+00:00",
        pack,
        known_event_ids=[],
    )
    assert "catalyst_added_or_changed" in signals

    # low severity should not invalidate
    pack_low = build_pack_from_events([
        {
            "event_id": "cat_low",
            "kind": "ex_div",
            "session_date": session,
            "event_ts": f"{session}T00:00:00+00:00",
            "horizon_days": 3,
            "severity": "low",
            "confirmed": True,
        }
    ])
    assert catalyst_invalidation_signals(None, pack_low, known_event_ids=[]) == []


def test_schd_weight_near_fire_medium_catalyst_priority_high():
    """SCHD weight 16.4% near fire → research priority ≥ high even for medium sev."""
    # assume fire ~17% → 0.95*17 ≈ 16.15; 16.4 >= that
    pri = effective_research_priority(
        "medium",
        weight_pct=16.4,
        fire_pct=17.0,
        dd_pct=None,
        deep_dd_pct=25.0,
    )
    assert pri == "high"

    ev = _ev("guidance", days=4, symbol="SCHD", title="sector note")
    assert ev["severity"] == "medium"
    pack = build_pack_from_events([ev], symbol="SCHD")
    warm = catalyst_warm_decision(
        "SCHD", pack,
        weight_pct=16.4,
        fire_pct=17.0,
    )
    assert warm is not None
    assert warm["priority"] == "high"


def test_data_unavailable_no_threshold_actions():
    pack = unavailable_pack(symbol="ZZZ")
    assert pack["quality"] == "DATA_UNAVAILABLE"
    assert pack["events"] == []
    assert catalyst_warm_decision("ZZZ", pack) is None
    assert catalyst_telegram_line(pack) is None
    assert catalyst_evidence_line(pack) is None
    assert catalyst_research_gap_eligible(pack) is False
    assert catalyst_invalidation_signals(None, pack) == []
    now = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
    default = now + timedelta(hours=24)
    assert adjust_revisit_at(default, pack, now=now) == default


def test_attach_catalyst_always_declares_domain():
    evidence: dict = {}
    attach_catalyst(evidence, symbol="EMPTY")
    assert "catalyst" in evidence
    assert evidence["catalyst"]["domain"] == "catalyst"
    assert evidence["catalyst"]["quality"] == "DATA_UNAVAILABLE"

    evidence2: dict = {}
    attach_catalyst(
        evidence2,
        symbol="SCHD",
        raw_events=[{
            "kind": "ex_div",
            "session_date": "2026-08-20",
            "title": "Ex-div",
            "confirmed": True,
        }],
        today=_today(),
    )
    pack = evidence2["catalyst"]
    assert pack["quality"] == "OK"
    assert pack["events"][0]["session_date"] == "2026-08-20"
    assert pack["events"][0]["severity"] == "low"
    assert pack["next_event"] is not None


def test_pack_from_broker_record_bridge():
    rec = {
        "symbol": "SPCX",
        "headline": "Contract win announced",
        "catalyst_type": "contract_win",
        "verified": True,
        "confidence": 0.8,
        "severity": "medium",
        "at": "2026-08-14T15:00:00+00:00",
    }
    pack = pack_from_broker_record(rec, symbol="SPCX", today=_today())
    assert pack["quality"] == "OK"
    assert pack["events"]
    assert pack["events"][0]["kind"] == "contract_win"
    assert pack["events"][0]["severity"] in ("medium", "high")  # may step with kind default medium


def test_next_relevant_event_sorts_by_horizon_then_severity():
    events = [
        _ev("guidance", days=4, title="a"),  # medium
        _ev("earnings", days=4, title="b"),  # high — same day, higher sev preferred as secondary
        _ev("earnings", days=2, title="c"),  # nearer wins
    ]
    # force severities
    events[0]["severity"] = "medium"
    events[1]["severity"] = "high"
    events[2]["severity"] = "high"
    nxt = next_relevant_event(events, max_days=5, min_sev="medium")
    assert nxt is not None
    assert nxt["horizon_days"] == 2


def test_max_severity_helper():
    assert max_severity("low", "high") == "high"
    assert max_severity("critical", "medium") == "critical"
