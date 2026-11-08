"""LQ-20261107-1121 — the brief accepts the engine's own ``MarketOutlookRecord@v1`` record.

The two work units gave ``scenarios.*_range`` different meanings: the engine writes the 1- and 2-ATR
band as percent multiples of the anchor close (``{low_1atr, high_1atr, low_2atr, high_2atr}``), the
brief printed a ``[low, high]`` pair of absolute levels. ``key_levels`` rows are ``{level, source,
distance_pct}`` objects, and a thin side carries one level, not three; the digest is bare 64-hex.
At the fold head the brief refused the engine's own record with twelve errors, so the 20:00 ET brief
could not be produced from the engine at all.

Every value here is invented (synthetic index levels, invented catalysts, invented digest) because
this repository is public. What the tests pin is the *shape* the engine really emits and the mapping
the brief now applies to it:

  * the ATR dict becomes the absolute pair of its 1-ATR band, ``anchor * (1 + multiple/100)``, where
    the anchor is recovered from any level's ``level / (1 + distance_pct/100)``;
  * a thin level side renders what exists plus ``n/a`` - it is stated, never a refusal;
  * a bare 64-hex digest is read as the ``sha256:`` digest it is.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import market_outlook_brief as mob  # noqa: E402

DIGEST = hashlib.sha256(b"synthetic-engine-record").hexdigest()
BASIS = "etf_derived"
CATEGORY_KEYS = tuple(mob.CATEGORY_TITLES)


def _level(level: float, distance_pct: float, source: str) -> dict:
    """One engine level row: the index-space level and its percent distance from the proxy close."""
    return {"level": level, "source": source, "distance_pct": distance_pct}


def _atr_band(atr_pct: float) -> dict:
    """The engine's scenario range for one index: percent multiples of the anchor close."""
    return {"low_1atr": -atr_pct, "high_1atr": atr_pct,
            "low_2atr": -2.0 * atr_pct, "high_2atr": 2.0 * atr_pct}


def _category(key: str, subscore, state: str, weight: int) -> dict:
    indicators = []
    if state == "UNKNOWN":
        indicators = [{"key": f"{key}_probe", "raw": None, "normalized": None, "as_of": None,
                       "source": "synthetic", "stale": True,
                       "refused_reason": f"no synthetic reading for {key}"}]
    return {"key": key, "weight_prior": weight, "weight_effective": weight,
            "subscore": None if state == "UNKNOWN" else subscore,  # an unmeasured reading is null
            "coverage": 0.0 if state == "UNKNOWN" else 0.6,
            "state": state, "indicators": indicators}


def engine_record() -> dict:
    """A record with the engine's exact field shapes and invented values.

    Anchors (recoverable from the first support level): SPX 6000, NDX 21000, RUT 2400.
    """
    states = ["COLLECTED"] * 8 + ["UNKNOWN"] * 3
    categories = [
        _category(key, round(-0.4 + 0.1 * index, 2), states[index], 100 - index)
        for index, key in enumerate(CATEGORY_KEYS)
    ]
    return {
        "schema": "MarketOutlookRecord@v1",
        "record_id": "outlook:2026-11-09:sunday:1",
        "as_of": "2026-11-09T01:00:00+00:00",
        "mode": "sunday",
        "session_clock": "Sunday @ 2026-11-08T20:00:00-05:00",
        "engine_commit": "0000000",
        "policy_version": "synthetic",
        "score": -18.74,
        "band": "DEFENSIVE",
        "confidence": {"value": 0.18, "band": "LOW", "coverage": 0.92, "freshness": 0.81,
                       "agreement": 0.56, "u_event": 0.85, "hitrate": 0.5},
        "regime": {"vix_band": "HIGH", "vix_value": 28.18, "vix_source": "synthetic",
                   "mre_tier": "RED", "mre_score": 59.584, "mre_as_of": "2026-11-06",
                   "episode_id": None},
        "categories": categories,
        "scenarios": {
            name: {"prob": prob,
                   "spx_range": _atr_band(3.0),
                   "ndx_range": _atr_band(2.5),
                   "rut_range": _atr_band(2.0),
                   "triggers": [f"synthetic {name} trigger"]}
            for name, prob in (("base", 0.47), ("bull", 0.16), ("bear", 0.37))
        },
        "method": "synthetic",
        "key_levels": {
            "SPX": {"support": [_level(5940.0, -1.0, "dma50"), _level(5880.0, -2.0, "prior_week_low"),
                                _level(5820.0, -3.0, "dma200")],
                    "resistance": [_level(6060.0, 1.0, "prior_week_high"), _level(6120.0, 2.0, "round_number"),
                                   _level(6180.0, 3.0, "dma50")],
                    "basis": BASIS},
            "NDX": {"support": [_level(20790.0, -1.0, "dma50")],
                    "resistance": [_level(21210.0, 1.0, "prior_week_high"), _level(21420.0, 2.0, "round_number"),
                                   _level(21630.0, 3.0, "dma200")],
                    "basis": BASIS},
            "RUT": {"support": [_level(2376.0, -1.0, "dma50")],
                    "resistance": [_level(2424.0, 1.0, "prior_week_high")],
                    "basis": BASIS},
        },
        "catalysts": [
            {"date_et": "2026-11-10", "time_et": "08:30", "event": "Synthetic CPI", "impact": "HIGH",
             "consensus": "0.3% m/m", "prior": "0.4% m/m", "held_flag_per_account_id": []},
            {"date_et": "2026-11-12", "time_et": "08:30", "event": "Synthetic claims", "impact": "LOW",
             "consensus": "220k", "prior": "218k", "held_flag_per_account_id": []},
        ],
        "what_would_change_view": [
            {"trigger": "SPX closes below", "threshold": "5820", "status": "NOT"},
            {"trigger": "VIX term structure inverts fully", "threshold": "VIX9D > VIX > VIX3M", "status": "NOT"},
        ],
        "actions_template": {"band": "DEFENSIVE", "tranche_release": "none", "reserve_floor": "5%",
                             "exposure_note": "synthetic protective stance; nothing here sizes or orders"},
        "prior_record_id": None,
        "inputs_snapshot_hash": DIGEST,
        "delivery": {"email": None, "text": None, "telegram": None},
    }


def policy() -> dict:
    return mob.load_policy()


# ------------------------------------------------------------------- the contract the engine emits
def test_the_engines_own_record_shape_validates():
    assert mob.validate_record(engine_record()) == []


def test_the_bare_digest_is_the_sha256_digest():
    record = engine_record()
    assert mob.validate_record(record) == []          # bare hex is accepted as it stands
    assert mob.normalize_record(record)["inputs_snapshot_hash"] == f"sha256:{DIGEST}"
    broken = copy.deepcopy(record)
    broken["inputs_snapshot_hash"] = "not-a-digest"
    assert any("inputs_snapshot_hash" in e for e in mob.validate_record(broken))


# ------------------------------------------------------------------- the ATR band becomes absolute
def test_the_atr_dict_becomes_the_absolute_one_atr_pair():
    """SPX anchor 6000, 1 ATR 3.0% -> [5820.0, 6180.0]; the 2-ATR band is not the band rendered."""
    base = mob.normalize_record(engine_record())["scenarios"]["base"]
    assert base["spx_range"] == [5820.0, 6180.0]
    assert base["ndx_range"] == [20475.0, 21525.0]    # anchor 21000, 1 ATR 2.5%
    assert base["rut_range"] == [2352.0, 2448.0]      # anchor 2400, 1 ATR 2.0%
    assert base["spx_range"] != [5640.0, 6360.0]      # not the 2-ATR band


def test_an_already_absolute_pair_passes_through():
    record = engine_record()
    record["scenarios"]["base"]["spx_range"] = [5950, 6050]
    assert mob.normalize_record(record)["scenarios"]["base"]["spx_range"] == [5950, 6050]
    assert mob.validate_record(record) == []


def test_a_band_with_no_anchor_is_na_not_a_refusal():
    """Without levels there is no anchor; the band prints n/a and the rest of the brief still renders."""
    record = engine_record()
    record["key_levels"]["SPX"] = {"support": [], "resistance": [], "basis": None}
    assert mob.validate_record(record) == []
    normalized = mob.normalize_record(record)
    assert normalized["scenarios"]["base"]["spx_range"] == [None, None]
    html = mob.render_html(normalized, policy=policy())
    assert "n/a-n/a" in html


# ------------------------------------------------------------------- thin level sides are stated
def test_a_thin_level_side_renders_what_exists_plus_na():
    normalized = mob.normalize_record(engine_record())
    assert normalized["key_levels"]["NDX"]["support"] == [20790.0, None, None]
    assert normalized["key_levels"]["RUT"]["resistance"] == [2424.0, None, None]
    assert mob.validate_record(normalized) == []      # a real engine record with thin sides is not refused
    rows = {name: (support, resistance) for name, support, resistance, _basis in mob._key_levels_rows(normalized)}
    assert rows["NDX"][0] == "20790, n/a, n/a"
    assert rows["RUT"][1] == "2424, n/a, n/a"
    assert rows["SPX"][0] == "5940, 5880, 5820"       # a full side is unchanged


def test_a_level_side_the_record_does_not_carry_is_still_refused():
    record = engine_record()
    del record["key_levels"]["SPX"]["support"]
    assert any("key_levels.SPX.support" in e for e in mob.validate_record(record))


# ------------------------------------------------------------------- the whole brief from the engine
def test_the_engine_record_renders_all_eleven_sections(tmp_path):
    path = tmp_path / "engine-record.json"
    path.write_text(json.dumps(engine_record()), encoding="utf-8")
    record = mob.load_record_file(path)
    assert record["inputs_snapshot_hash"] == f"sha256:{DIGEST}"
    html = mob.render_html(record, policy=policy())
    titles = ["The view", "Cross-asset scorecard", "Levels that matter", "This week&#x27;s catalysts",
              "Overnight so far", "Positioning", "What would change our view", "What we do",
              "Last week&#x27;s call", "Not measured"]
    positions = [html.index(f">{title}</h2>") for title in titles]
    assert positions == sorted(positions)
    assert "S -19" in html and "DEFENSIVE" in html
    # Every rendering shows the derived absolute band and states the thin side, not a blank or a zero.
    for rendering in (html, mob.render_email_text(record, policy=policy()),
                      mob.render_telegram(record, policy=policy())):
        assert "5820" in rendering and "6180" in rendering
        assert "n/a" in rendering
    assert any(rendering.count("20790") for rendering in
               (html, mob.render_email_text(record, policy=policy()),
                mob.render_telegram(record, policy=policy())))
    assert mob.render_text(record, policy=policy(), max_chars=300).startswith("OUTLOOK")


def test_normalization_is_idempotent_and_copies():
    original = engine_record()
    frozen = copy.deepcopy(original)
    once = mob.normalize_record(original)
    twice = mob.normalize_record(once)
    assert once == twice
    assert original == frozen                          # copy-on-write: the input is untouched


def test_a_brief_shaped_record_is_unchanged(tmp_path):
    """The existing sample fixture already uses the brief's shape; normalization must not move it."""
    fixture = Path(__file__).with_name("fixtures") / "market_weekly_outlook_record_sample.json"
    doc = json.loads(fixture.read_text(encoding="utf-8"))
    assert mob.normalize_record(doc) == doc
