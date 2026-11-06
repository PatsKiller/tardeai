"""Market-risk projection for the Command Center (DSN-20261031-market-risk-ui).

Pins: without an engine snapshot the projection says not_evaluated / NOT_EVALUATED and never infers a tier from the one
live source (the P0 options-flow block); with a MarketRiskSnapshot@v1 it passes tier, score, five contributors, episode
and book through and marks staleness by age; the Home banner rule is evaluated-and-ORANGE/RED only; acknowledgment is
written to the episode ledger and refused when no episode is open. Hermetic: dicts only.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import market_risk_projection as mp  # noqa: E402

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
RADAR = {
    "captured_at": "2026-10-29T14:00:03+00:00",
    "options_flow": {
        "priority": "P1",
        "session": "regular",
        "findings": [
            {"symbol": "QQQ", "state": "STRESS", "pc_vol_ratio": 3.309, "pc_vol_factor": 3.4},
            {"symbol": "SPY", "state": "WARN"},
        ],
    },
}
SNAP = {
    "schema": "MarketRiskSnapshot@v1",
    "tier": "RED",
    "score": 83,
    "as_of": "2026-10-30T08:45:00+00:00",
    "contributors": [{"name": f"c{i}", "points": p} for i, p in enumerate([18, 17, 15, 14, 11, 7])],
    "categories": [{"name": "breadth", "state": "STRESS"}],
    "confirming": {"n": 6, "of": 9},
    "episode": {"id": "EP-1", "tier": "RED", "opened_at": "2026-10-29T22:15:00+00:00", "repeats": 3, "max_repeats": 12},
    "book": {"vulnerability": 78},
    "probabilities": [{"horizon": "24h", "down": 0.64}],
    "history": [{"as_of": "x", "score": 1, "tier": "GREEN"}] * 40,
}


def test_no_snapshot_is_not_evaluated_and_never_a_tier():
    out = mp.build(None, RADAR, now=NOW)
    assert out["state"] == "not_evaluated" and out["tier"] == "NOT_EVALUATED" and out["score"] is None
    assert out["sources"]["options_flow"]["findings"][0]["symbol"] == "QQQ"
    assert out["sources"]["options_flow"]["age_hours"] == 19.0
    assert mp.banner_visible(out) is False
    assert "P2-T1" in out["reason"]


def test_a_snapshot_passes_through_and_caps_contributors_at_five():
    out = mp.build(SNAP, RADAR, now=NOW)
    assert out["state"] == "evaluated" and out["tier"] == "RED" and out["score"] == 83
    assert [c["points"] for c in out["contributors"]] == [18, 17, 15, 14, 11]
    assert out["episode"]["id"] == "EP-1" and out["book"]["vulnerability"] == 78
    assert len(out["history"]) == 30 and out["age_hours"] == 0.25 and out["stale"] is False
    assert mp.banner_visible(out) is True


def test_an_old_snapshot_is_stale_and_shows_no_banner():
    out = mp.build(dict(SNAP, as_of="2026-10-30T06:00:00+00:00"), None, now=NOW)
    assert out["state"] == "stale" and out["stale"] is True and mp.banner_visible(out) is False


def test_unknown_tier_or_wrong_schema_never_renders_as_a_tier():
    out = mp.build(dict(SNAP, tier="PURPLE"), None, now=NOW)
    assert out["tier"] == "NOT_EVALUATED"
    assert mp.build({"schema": "Other@v1", "tier": "RED"}, None, now=NOW)["state"] == "not_evaluated"


def test_green_and_yellow_show_no_banner():
    for tier in ("GREEN", "BLUE", "YELLOW"):
        assert mp.banner_visible(mp.build(dict(SNAP, tier=tier), None, now=NOW)) is False
    assert mp.banner_visible(mp.build(dict(SNAP, tier="ORANGE"), None, now=NOW)) is True


def test_ack_writes_the_episode_ledger_and_refuses_without_an_open_episode(tmp_path):
    from lib.market_risk import escalation as esc

    store = tmp_path / "episodes.json"
    code, body = mp.ack_outcome(mp.build(None, None, now=NOW), {"episode_id": "EP-1"}, actor="tailnet:op", path=store)
    assert code == 409 and "no open" in body["error"]
    pol = {"escalation": {"opens_at": ["ORANGE", "RED"]}}
    ep = esc.observe({"tier": "RED", "score": 83, "observations": []}, now=NOW, policy=pol, path=store)["episode"]
    code, body = mp.ack_outcome(mp.build(SNAP, None, now=NOW), {"episode_id": "EP-9"}, actor="tailnet:op", path=store)
    assert code == 409 and "EP-9" in body["error"]
    code, body = mp.ack_outcome(mp.build(None, None, now=NOW), {"episode_id": ep["id"]}, actor="", path=store)
    assert code == 403
    code, body = mp.ack_outcome(
        mp.build(None, None, now=NOW, episode=ep), {"episode_tier": "RED"}, actor="tailnet:op", path=store, now=NOW
    )
    assert code == 200 and body["episode"]["status"] == "ACKED" and body["episode"]["acknowledged_by"] == "tailnet:op"


# ── CIO wiring (operator 2026-10-31: "The CIO agent needs to know about everything, including this market information") ──


def test_market_context_carries_the_projection_as_a_field_and_a_summary_line():
    from scripts.lib.cio_market_context_state import build_market_context_state

    proj = mp.build(SNAP, RADAR, now=NOW)
    state = build_market_context_state(
        regime_snapshot={"regime_label": "high_volatility"}, fred_rows=[], market_risk=proj, evaluated_at=NOW
    )
    f = state["fields"]["market_risk"]
    assert f["state"] == "VERIFIED" and f["source"] == "market_risk_projection"
    assert f["value"]["tier"] == "RED" and f["value"]["score"] == 83 and len(f["value"]["contributors"]) == 5
    assert state["market_risk"]["line"].startswith("Market risk: RED 83/100 — c0")
    assert "market_risk" not in state["unavailable_fields"], "a distinct state, never an outage"


def test_market_context_without_an_engine_is_not_evaluated_not_unavailable():
    from scripts.lib.cio_market_context_state import build_market_context_state

    for proj in (None, mp.build(None, RADAR, now=NOW)):
        state = build_market_context_state(regime_snapshot=None, fred_rows=[], market_risk=proj, evaluated_at=NOW)
        f = state["fields"]["market_risk"]
        assert f["state"] == "NOT_EVALUATED"
        assert "market_risk" not in state["unavailable_fields"] and "market_risk" not in state["stale_fields"]
        assert state["market_risk"]["tier"] == "NOT_EVALUATED"
    with_flow = build_market_context_state(
        regime_snapshot=None, fred_rows=[], market_risk=mp.build(None, RADAR, now=NOW), evaluated_at=NOW
    )
    assert with_flow["fields"]["market_risk"]["value"]["options_flow"][0]["symbol"] == "QQQ"


def test_stale_projection_marks_the_field_stale():
    from scripts.lib.cio_market_context_state import build_market_context_state

    proj = mp.build(dict(SNAP, as_of="2026-10-30T06:00:00+00:00"), None, now=NOW)
    state = build_market_context_state(regime_snapshot=None, fred_rows=[], market_risk=proj, evaluated_at=NOW)
    assert state["fields"]["market_risk"]["state"] == "STALE"


def test_temperament_title_names_an_evaluated_tier_and_never_an_unevaluated_one():
    from scripts.lib.cio_investment_product import build_temperament

    base = dict(
        regime={"label": "risk_on_trend", "as_of": "x"},
        holdings={},
        fs_rows=[],
        lessons={},
        infl={
            "gates": {"lesson_mode": "off", "financial_senses_mode": "off"},
            "memory_mode": "cognition",
            "memory_behavior_influence": 0,
        },
    )
    t = build_temperament(**base, market_risk=mp.build(SNAP, None, now=NOW))
    # PR #2342 (CIO overlay): an evaluated ORANGE/RED turns the posture defensive (operator §11 item 3).
    assert t["title"] == "RISK ON TREND — DEFENSIVE — ENTRIES HELD, REVIEW STOPS · MARKET RISK RED 83/100"
    assert t["market_risk"]["tier"] == "RED" and t["market_risk"]["top"] == "c0"
    t2 = build_temperament(**base, market_risk=mp.build(None, None, now=NOW))
    assert t2["title"] == "RISK ON TREND — SELECTIVE RISK" and t2["market_risk"]["tier"] == "NOT_EVALUATED"
    t3 = build_temperament(**base)
    assert t3["title"] == "RISK ON TREND — SELECTIVE RISK"
