"""LQ-20261107-1613 (re-opened 2026-11-10, audit C3): the regime responds to market-wide trend and breadth.

After the scanner proxies stopped scoring, trend_state and breadth_state were hard-coded `not_measured`, so the label
was a function of the VIX bucket alone and confidence sat at 0.17 on every snapshot without term structure. On
2026-11-10 05:51 ET the snapshot read `risk_on_trend 0.17, trend not_measured, breadth not_measured` while the Market
Risk Engine's own observations said technical STRESS (85) and breadth WARN (49.5).

These pins: the collector records the engine's technical and breadth observations as indicators with their age; a
stale, missing or UNKNOWN observation is `not_measured` with its reason, never a value; the classifier maps them to
trend/breadth states and scores them from config; and the outputs change when those inputs change (the G8 bar).
Synthetic engine snapshots and indicator rows only.

LQ-1826 review r2: with the engine at technical STRESS the label must not publish `risk_on_trend` on ANY breadth
state or VIX bucket (M1 — at `risk_off: 2` the dominant (STRESS, CALM) pair tied 2-2 and `max()`'s dict order won
it for risk_on_trend beside `trend_state=bearish`, and scripts/api_v2.py derived the opposite answer from the same
row), and a configured score label that is not a regime is named rather than silently unscored (N1). The file is
registered as CiGate@v1 `market_regime_mre_inputs_lq1613_20261110` (M2).
"""
from __future__ import annotations

import copy
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import market_regime_classifier as mrc  # noqa: E402
import market_regime_collector as coll  # noqa: E402
from lib.market_regime import mre_inputs  # noqa: E402
from test_market_regime_classifier_snapshot_20261031 import FakeConn, _row  # noqa: E402

NOW = datetime(2026, 11, 10, 10, 51, 43, tzinfo=timezone.utc)  # 05:51 ET, the C3 snapshot's run
CFG_PATH = ROOT / "config" / "market_regime_classifier.yaml"

#: snapshot 241's other inputs (11-10 05:51 ET): VIX normal, no term structure, scanner context
BASE_241 = [
    _row("finviz_health", "risk_on", None, "healthy"),
    _row("gap_volatility_proxy", "high_vol", 9.23),
    _row("market_session", "neutral", None, "premarket"),
    _row("news_sentiment_proxy", "neutral", 3.71),
    _row("scan_breadth_24h", "broad", 85),
    _row("scan_score_avg", "bearish", 22.1),
    _row("vix_close", "normal", 19.76),
]


@pytest.fixture(autouse=True)
def _session(monkeypatch):
    fake = types.ModuleType("market_session")
    fake.current_market_session = lambda: "regular"
    monkeypatch.setitem(sys.modules, "market_session", fake)


def _engine(tech="STRESS", breadth="WARN", age_min=6, tech_score=85.0, breadth_score=49.5):
    as_of = (NOW - timedelta(minutes=age_min)).isoformat()
    return {
        "schema": "MarketRiskSnapshot@v1",
        "as_of": as_of,
        "categories": [
            {"category": "technical", "state": tech, "score": tech_score, "detail": "synthetic", "as_of": as_of},
            {"category": "breadth", "state": breadth, "score": breadth_score, "detail": "synthetic", "as_of": as_of},
            {"category": "volatility", "state": "CALM", "score": 10.0, "as_of": as_of},
        ],
    }


def _cfg():
    return mre_inputs.load_config(CFG_PATH)


def _ind(engine, cfg=None):
    inds, missing = mre_inputs.collect(engine, NOW, cfg or _cfg(), "SNAP_t", lambda: "IND_t")
    return {i["indicator_key"]: i for i in inds}, missing


def _rows_from(inds):
    return [_row(k, i["signal"], i.get("value"), i.get("value_text")) for k, i in inds.items()]


def _classify(rows, cfg=None):
    return mrc.classify(FakeConn(by_snapshot={"S": rows}, latest="S"), cfg=cfg)


def _snap(tech, breadth, base=BASE_241):
    inds, _ = _ind(_engine(tech, breadth))
    return _classify(base + _rows_from(inds))


# --- collector side ------------------------------------------------------------------------------------------------


def test_the_engine_observations_become_two_indicators_with_their_age():
    inds, missing = _ind(_engine("STRESS", "WARN", age_min=6))
    assert set(inds) == {"mre_technical", "mre_breadth"} and missing == []
    t, b = inds["mre_technical"], inds["mre_breadth"]
    assert (t["signal"], t["value"], t["indicator_group"]) == ("STRESS", 85.0, "trend")
    assert (b["signal"], b["value"], b["indicator_group"]) == ("WARN", 49.5, "breadth")
    assert t["freshness_seconds"] == 360 and t["payload"]["as_of"] == _engine()["categories"][0]["as_of"]
    assert t["source_key"] == "market_risk_engine:technical"


def test_a_stale_observation_is_not_measured_with_its_age_never_a_value():
    inds, missing = _ind(_engine(age_min=142))
    for key in ("mre_technical", "mre_breadth"):
        assert inds[key]["signal"] == "not_measured" and inds[key]["value"] is None
        assert inds[key]["value_text"] == "stale:142m"
    assert "mre_technical_stale:142m" in missing


def test_unknown_state_missing_category_and_no_file_are_named():
    eng = _engine(tech="UNKNOWN")
    eng["categories"] = [c for c in eng["categories"] if c["category"] != "breadth"]
    inds, missing = _ind(eng)
    assert inds["mre_technical"]["signal"] == "not_measured" and inds["mre_technical"]["value_text"] == "state:UNKNOWN"
    assert inds["mre_breadth"]["signal"] == "not_measured" and inds["mre_breadth"]["value_text"] == "no_category"
    inds, missing = mre_inputs.collect(None, NOW, _cfg(), "S", lambda: "I", reason="file_missing")
    assert {i["signal"] for i in inds} == {"not_measured"} and "mre_breadth_not_measured:file_missing" in missing


def test_the_collector_reads_the_engine_file_from_the_runtime_dir(tmp_path):
    (tmp_path / "market_risk_latest.json").write_text(json.dumps(_engine("CALM", "CALM")))
    inds, missing = coll.collect_market_risk_engine("SNAP_t", NOW, _cfg(), runtime_dir=tmp_path)
    assert {i["indicator_key"]: i["signal"] for i in inds} == {"mre_technical": "CALM", "mre_breadth": "CALM"}
    inds, missing = coll.collect_market_risk_engine("SNAP_t", NOW, _cfg(), runtime_dir=tmp_path / "absent")
    assert {i["signal"] for i in inds} == {"not_measured"} and any("file_missing" in m for m in missing)
    (tmp_path / "market_risk_latest.json").write_text("{not json")
    inds, missing = coll.collect_market_risk_engine("SNAP_t", NOW, _cfg(), runtime_dir=tmp_path)
    assert {i["signal"] for i in inds} == {"not_measured"} and any("unreadable" in m for m in missing)


# --- classifier side -----------------------------------------------------------------------------------------------


def test_the_11_10_snapshot_replayed_no_longer_reads_risk_on_with_trend_unmeasured():
    """05:51 ET inputs + the engine's STRESS/WARN at that time: the label leaves risk_on_trend, states are measured."""
    snap = _snap("STRESS", "WARN")
    assert snap["trend_state"] == "bearish" and snap["breadth_state"] == "narrow"
    assert snap["risk_appetite_state"] == "bearish"
    assert snap["regime_label"] != "risk_on_trend"
    assert snap["inputs"]["mre_technical"] == "STRESS" and snap["inputs"]["mre_breadth"] == "WARN"


def _display_and_flag(snap):
    """scripts/api_v2.py:892 (the display string) and :897 (risk_off), verbatim, from the snapshot row."""
    now = str(snap["regime_label"]).replace("_", " ")
    ts = str(snap.get("trend_state") or "").strip()
    now += (f" {ts}" if ts else "") + (f" {int(float(snap['confidence']) * 100)}%"
                                       if snap.get("confidence") is not None else "")
    return now, any(w in now.lower() for w in ("off", "bear", "defensive"))


def test_technical_stress_with_calm_breadth_is_not_risk_on():
    """LQ-1826 M1 exactly: (technical STRESS, breadth CALM) is the dominant engine pair — 477 of 538 receipts,
    11-03..11-10. At `mre_technical.STRESS: {risk_off: 2}` the scores tie 2-2 against the vix `normal` bonus and
    `max()` resolves the tie by dict order to risk_on_trend while trend_state says bearish; scripts/api_v2.py:892
    then prints "risk on trend bearish" and :897 derives risk_off=True from the same row (Rule 9: the UI may not
    contradict reality; one payload, two answers). The label and the trend must agree on direction."""
    snap = _snap("STRESS", "CALM")
    assert snap["trend_state"] == "bearish" and snap["breadth_state"] == "broad"
    assert snap["regime_label"] != "risk_on_trend", snap["summary"]
    display, flag = _display_and_flag(snap)
    assert "risk on" not in display, display
    assert flag is True  # the cautious reading and the label agree: risk_off is the label
    assert not (snap["trend_state"] == "bearish" and snap["regime_label"] == "risk_on_trend")


@pytest.mark.parametrize("breadth", ["CALM", "IMPROVING", "WARN", "STRESS"])
@pytest.mark.parametrize("vix", ["extreme", "high", "normal", "low"])
def test_technical_stress_never_publishes_risk_on_trend_on_any_breadth_or_vix(breadth, vix):
    """The invariant, not one row: with the engine at technical STRESS, no breadth state and no VIX bucket can
    produce a risk-on label beside trend_state=bearish."""
    inds, _ = _ind(_engine("STRESS", breadth))
    base = [r for r in BASE_241 if r[0] != "vix_close"] + [_row("vix_close", vix, 19.76)]
    snap = _classify(base + _rows_from(inds))
    assert snap["inputs"]["mre_technical"] == "STRESS"
    assert snap["trend_state"] == "bearish"
    assert snap["regime_label"] != "risk_on_trend", (breadth, vix, snap["confidence"])
    display, _ = _display_and_flag(snap)
    assert "risk on" not in display, (breadth, vix, display)


def test_the_configured_stress_weight_exceeds_the_largest_risk_on_bonus():
    """Config intent, so a later weight edit cannot silently re-open M1: the STRESS risk_off weight must exceed
    the largest risk_on_trend total the breadth config adds (plus the VIX bucket's at most +1)."""
    cfg = _cfg()
    stress = int(cfg["scores"]["mre_technical"]["STRESS"].get("risk_off", 0))
    best_breadth = max(int(p.get("risk_on_trend", 0)) for p in cfg["scores"]["mre_breadth"].values())
    assert stress > best_breadth + 1, f"technical STRESS {stress} could tie or lose to risk_on_trend"


def test_a_score_label_that_is_not_a_regime_is_named_and_scores_nothing(tmp_path):
    """LQ-1826 N1: `{risk_of: 2}` used to load cleanly, record the state and add zero points in silence."""
    doc = yaml.safe_load(CFG_PATH.read_text())
    alt = copy.deepcopy(doc)
    alt["scores"]["mre_technical"]["WARN"] = {"risk_of": 9}
    p = tmp_path / "badlabel.yaml"
    p.write_text(yaml.safe_dump(alt))
    inds, _ = _ind(_engine("WARN", "CALM"))
    snap = _classify(BASE_241 + _rows_from(inds), cfg=mre_inputs.load_config(p))
    assert snap["trend_state"] == "weakening"
    assert "bad_label:risk_of" in snap["missing_data"]


def test_outputs_change_whenever_the_engine_inputs_change():
    """The G8 bar as a test: a 30-step input series; every input change moves label, confidence or a state."""
    states = ["CALM", "IMPROVING", "WARN", "STRESS"]
    series = [(states[i % 4], states[(i // 4) % 4]) for i in range(30)]
    outs = [_snap(t, b) for t, b in series]
    for (a_in, a), (b_in, b) in zip(zip(series, outs), zip(series[1:], outs[1:])):
        if a_in != b_in:
            ka = (a["regime_label"], a["confidence"], a["trend_state"], a["breadth_state"])
            kb = (b["regime_label"], b["confidence"], b["trend_state"], b["breadth_state"])
            assert ka != kb, (a_in, b_in, ka)
    assert len({o["regime_label"] for o in outs}) >= 3
    assert len({o["confidence"] for o in outs}) >= 3


def test_calm_and_stress_markets_get_opposite_labels_under_the_same_vix():
    calm, stress = _snap("CALM", "CALM"), _snap("STRESS", "STRESS")
    assert calm["regime_label"] in ("risk_on_trend", "broad_momentum")
    assert stress["regime_label"] == "risk_off"
    assert calm["confidence"] != 0.17 or stress["confidence"] != 0.17


def test_without_engine_rows_the_states_stay_not_measured_and_are_named():
    snap = _classify(BASE_241)
    assert snap["trend_state"] == "not_measured" and snap["breadth_state"] == "not_measured"
    assert "no_mre_technical" in snap["missing_data"] and "no_mre_breadth" in snap["missing_data"]
    # LQ-20261113-3048 reverses the old "named, not stale" pin: with trend and breadth unmeasured the label rests on
    # the VIX bucket alone, and a one-leg label is stale (tests/test_market_regime_legs_lq3048_20261113.py).
    assert snap["stale_data"] is True


def test_a_not_measured_engine_row_scores_nothing_and_names_its_reason():
    inds, _ = _ind(_engine(age_min=500))
    snap = _classify(BASE_241 + _rows_from(inds))
    base = _classify(BASE_241)
    assert (snap["regime_label"], snap["confidence"]) == (base["regime_label"], base["confidence"])
    assert snap["trend_state"] == "not_measured"
    assert "mre_technical:stale:500m" in snap["missing_data"]


def test_weights_and_floor_come_from_config(tmp_path):
    doc = yaml.safe_load(CFG_PATH.read_text())
    alt = copy.deepcopy(doc)
    alt["scores"]["mre_technical"]["STRESS"] = {"high_volatility": 9}
    alt["confidence_floor"] = 40
    p = tmp_path / "alt.yaml"
    p.write_text(yaml.safe_dump(alt))
    cfg = mre_inputs.load_config(p)
    inds, _ = _ind(_engine("STRESS", "WARN"))
    snap = _classify(BASE_241 + _rows_from(inds), cfg=cfg)
    assert snap["regime_label"] == "high_volatility"
    assert snap["confidence"] == round((9 - 1) / 40, 2)


def test_a_config_with_the_wrong_schema_is_refused(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("schema: Nope@v0\n")
    with pytest.raises(mre_inputs.ConfigError):
        mre_inputs.load_config(p)
