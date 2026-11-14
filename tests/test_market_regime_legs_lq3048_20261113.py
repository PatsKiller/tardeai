"""LQ-20261113-3048 (Combined Home A06): an unmeasured core regime leg is missing evidence, not a neutral vote.

The label weighs three core legs: volatility (the VIX bucket), trend and breadth (the Market Risk Engine). Until now
the trend/breadth gaps were appended to `missing_data` AFTER the stale check, so a label resting on the VIX bucket
alone published `fresh` at full confidence. On 2026-11-13 05:51 ET the latest snapshot read `risk_on_trend 0.17`,
trend and breadth `not_measured`, stale_data false, and the Home REGIME tile showed a confident dot.

These pins:
- confidence is scaled by the share of measured core legs;
- fewer than two measured legs is stale (never a confident current verdict on one leg);
- any unmeasured core leg makes the snapshot `incomplete`; all three measured is `fresh`;
- the measured and unmeasured legs are recorded in `inputs` and named in the summary;
- a missing context input (term structure) alone still does not make a snapshot stale.

Synthetic indicator rows and engine snapshots only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import market_regime_classifier as mrc  # noqa: E402,F401
from lib.market_regime import mre_inputs  # noqa: E402
from test_market_regime_classifier_snapshot_20261031 import _row  # noqa: E402
from test_market_regime_mre_inputs_lq1613_20261110 import (  # noqa: E402,F401
    BASE_241,
    _classify,
    _engine,
    _ind,
    _rows_from,
    _session,
)

NO_VIX = [r for r in BASE_241 if r[0] != "vix_close"]


def _with_engine(tech, breadth, base=BASE_241):
    inds, _ = _ind(_engine(tech, breadth))
    return _classify(base + _rows_from(inds))


# --- the 11-13 05:51 ET shape: one leg -------------------------------------------------------------------------------


def test_a_label_on_the_vix_bucket_alone_is_stale_not_fresh():
    snap = _classify(BASE_241)
    assert (snap["volatility_state"], snap["trend_state"], snap["breadth_state"]) == (
        "neutral", "not_measured", "not_measured")
    assert snap["stale_data"] is True
    assert snap["data_freshness_state"] == "stale"
    assert "core_legs:1_of_3" in snap["missing_data"]


def test_one_leg_confidence_is_a_third_of_the_margin():
    # VIX normal alone: risk_on_trend 1 vs 0 over the floor. Before: 0.17 (11-13 05:51 ET). Now a third of it.
    snap = _classify(BASE_241)
    floor = mre_inputs.load_config()["confidence_floor"]
    assert snap["regime_label"] == "risk_on_trend"
    assert snap["confidence"] == round((1 / max(1, floor)) / 3, 2)
    assert snap["confidence"] < 0.17


def test_the_legs_are_recorded_and_named():
    snap = _classify(BASE_241)
    assert snap["inputs"]["_core_legs_measured"] == ["volatility"]
    assert snap["inputs"]["_core_legs_not_measured"] == ["trend", "breadth"]
    assert "legs 1/3" in snap["summary"] and "not measured: trend, breadth" in snap["summary"]


def test_no_leg_at_all_is_stale():
    inds, _ = _ind(_engine("UNKNOWN", "UNKNOWN"))
    snap = _classify(NO_VIX + _rows_from(inds))
    assert snap["volatility_state"] == "unknown"
    assert snap["stale_data"] is True and snap["data_freshness_state"] == "stale"
    assert snap["confidence"] == 0
    assert "core_legs:0_of_3" in snap["missing_data"]


def test_trend_alone_without_vix_is_also_one_leg():
    inds, _ = _ind(_engine("STRESS", "UNKNOWN"))
    snap = _classify(NO_VIX + _rows_from(inds))
    assert snap["trend_state"] == "bearish" and snap["breadth_state"] == "not_measured"
    assert snap["inputs"]["_core_legs_measured"] == ["trend"]
    assert snap["stale_data"] is True


# --- two legs: incomplete, not stale ---------------------------------------------------------------------------------


def test_two_legs_are_incomplete_with_two_thirds_confidence():
    inds, _ = _ind(_engine("STRESS", "UNKNOWN"))
    snap = _classify(BASE_241 + _rows_from(inds))
    assert snap["inputs"]["_core_legs_measured"] == ["volatility", "trend"]
    assert snap["inputs"]["_core_legs_not_measured"] == ["breadth"]
    assert snap["stale_data"] is False
    assert snap["data_freshness_state"] == "incomplete"
    assert not any(m.startswith("core_legs:") for m in snap["missing_data"])
    # risk_off 3 (STRESS) vs risk_on_trend 1 (VIX normal): margin 2 over max(4, floor), scaled by 2/3
    floor = mre_inputs.load_config()["confidence_floor"]
    assert snap["regime_label"] == "risk_off"
    assert snap["confidence"] == round((3 - 1) / max(4, floor) * 2 / 3, 2)
    assert "legs 2/3" in snap["summary"] and "not measured: breadth" in snap["summary"]


# --- three legs: fresh, unscaled -------------------------------------------------------------------------------------


def test_three_legs_are_fresh_and_confidence_is_unscaled():
    snap = _with_engine("STRESS", "WARN")
    floor = mre_inputs.load_config()["confidence_floor"]
    assert snap["inputs"]["_core_legs_measured"] == ["volatility", "trend", "breadth"]
    assert snap["inputs"]["_core_legs_not_measured"] == []
    assert snap["stale_data"] is False and snap["data_freshness_state"] == "fresh"
    assert "legs 3/3)" in snap["summary"] and "not measured" not in snap["summary"]
    assert 0 < snap["confidence"] <= 1 and floor > 0


def test_a_missing_term_structure_alone_does_not_make_three_legs_stale():
    snap = _with_engine("CALM", "CALM")
    assert "no_term_structure" in snap["missing_data"]
    assert snap["stale_data"] is False and snap["data_freshness_state"] == "fresh"


def test_measuring_more_legs_never_lowers_staleness_order():
    one = _classify(BASE_241)
    inds2, _ = _ind(_engine("CALM", "UNKNOWN"))
    two = _classify(BASE_241 + _rows_from(inds2))
    three = _with_engine("CALM", "CALM")
    order = {"stale": 0, "incomplete": 1, "fresh": 2}
    assert [order[s["data_freshness_state"]] for s in (one, two, three)] == [0, 1, 2]


def test_a_stale_engine_row_is_an_unmeasured_leg():
    inds, _ = _ind(_engine("STRESS", "WARN", age_min=500))
    snap = _classify(BASE_241 + _rows_from(inds))
    assert snap["trend_state"] == "not_measured" and snap["breadth_state"] == "not_measured"
    assert snap["stale_data"] is True and "core_legs:1_of_3" in snap["missing_data"]


def test_an_unknown_vix_signal_is_not_a_measured_leg():
    rows = NO_VIX + [_row("vix_close", "garbled", 19.0)]
    inds, _ = _ind(_engine("CALM", "CALM"))
    snap = _classify(rows + _rows_from(inds))
    assert snap["volatility_state"] == "unknown"
    assert snap["inputs"]["_core_legs_not_measured"] == ["volatility"]
    assert snap["data_freshness_state"] == "incomplete"


def test_context_gaps_still_do_not_count_toward_the_old_three_gap_rule(monkeypatch):
    # Two counted gaps (finviz degraded, market closed) plus a missing term structure, with all three legs measured:
    # the term structure stays context and the snapshot is not stale. Counting it would make three gaps.
    monkeypatch.setattr(sys.modules["market_session"], "current_market_session", lambda: "closed")
    rows = [r for r in BASE_241 if r[0] != "finviz_health"] + [_row("finviz_health", "risk_off", None, "degraded")]
    inds, _ = _ind(_engine("CALM", "CALM"))
    snap = _classify(rows + _rows_from(inds))
    assert {"finviz_degraded", "market_closed", "no_term_structure"} <= set(snap["missing_data"])
    assert snap["inputs"]["_core_legs_not_measured"] == []
    assert snap["stale_data"] is False and snap["data_freshness_state"] == "fresh"


# --- LQ-20261113-3061 (review 3048 C2): the classifier and the page agree on what "unmeasured" means ------------------


def _page_unmeasured_set() -> set[str]:
    import re

    src = (ROOT / "apps/command-center-v3/src/lib/homeRegime.ts").read_text(encoding="utf-8")
    m = re.search(r"^const UNMEASURED = new Set\(\[(.*?)\]\)", src, re.M)
    assert m, "homeRegime.ts no longer declares `const UNMEASURED = new Set([...])` on one line"
    return set(re.findall(r"'([^']*)'", m.group(1)))


def test_the_page_and_the_classifier_share_one_unmeasured_list():
    assert _page_unmeasured_set() == set(mrc.UNMEASURED_STATES)


def test_every_placeholder_in_any_case_or_padding_is_unmeasured():
    for v in [None, "", "  ", "UNKNOWN", "Not_Measured", "not measured", " N/A ", "None"]:
        assert mrc.leg_unmeasured(v), repr(v)
    for v in ["neutral", "bearish", "narrow", "high_vol"]:
        assert not mrc.leg_unmeasured(v), v
