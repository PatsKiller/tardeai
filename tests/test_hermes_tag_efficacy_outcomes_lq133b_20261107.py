"""ANCHOR: HERMES_TAG_EFFICACY_OUTCOMES_LQ133B_20261107. LQ-20261107-133b — the
tag engine counted "a watch directive surfaced" as a hit, so 97% of rows scored as
successes and every tag's lift was noise.

Live observations from the 2026-11-07 audit and the table (read-only):

* ``hermes_outcome_ledger`` research rows: directive_hit 18,171, proposal 3,604,
  none 2,001, trade 2 — and ``hermes_tag_efficacy`` reported hit_rate 0.88-0.99
  on every tag against base_rate 0.969, flagging momentum_scalp on a lift of
  -0.3 points and swing_breakout on -1.2 points.
* The same ledger carries a graded outcome for 20,835 research rows
  (``outcome_ret_20d``) — a real result the metric ignored.

The metric is now the 20-session win rate on graded outcomes, and a tag is
flagged only on credible evidence: sample, a minimum effect, and a one-sided
two-proportion z-test. Hermetic: pure function, no database, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_tag_engine as TE  # noqa: E402

ANCHOR = "HERMES_TAG_EFFICACY_OUTCOMES_LQ133B_20261107"


def _row(tag, ledger_n, outcome_n, wins, actioned=0, directive=0):
    return {"tag": tag, "ledger_n": ledger_n, "outcome_n": outcome_n, "wins": wins,
            "actioned_hits": actioned, "directive_hits": directive}


def _stats(rows, min_n=15, min_effect=0.05, alpha=0.05):
    return TE.efficacy_stats(rows, min_n=min_n, min_effect=min_effect, alpha=alpha)


# ── what a hit means ──────────────────────────────────────────────────────────────────────────────────────────

def test_a_directive_hit_is_engagement_not_a_win():
    # 18,000 rows where a directive surfaced, only 100 graded outcomes, half of them good
    s = _stats([_row("general_research", 18000, 100, 50, actioned=200, directive=17800),
                _row("swing", 100, 100, 50)])
    gr = next(t for t in s["tags"] if t["tag"] == "general_research")
    assert gr["n"] == 100 and gr["hits"] == 50 and gr["hit_rate"] == 0.5
    assert gr["directive_hits"] == 17800 and gr["actioned"] == 200
    assert gr["hit_rate"] != round((17800 + 200) / 18000, 3)   # the old 0.97 never comes back


def test_an_ungraded_row_is_neither_a_win_nor_a_loss():
    s = _stats([_row("quiet", 500, 0, 0), _row("graded", 500, 500, 250)])
    quiet = next(t for t in s["tags"] if t["tag"] == "quiet")
    assert quiet["n"] == 0 and quiet["hit_rate"] is None and quiet["lift"] is None
    assert quiet["flagged"] is False
    assert "n<15" in quiet["flag_reason"]


def test_the_sample_is_the_graded_outcomes_not_the_ledger_rows():
    s = _stats([_row("t", ledger_n=7000, outcome_n=120, wins=60)])
    t = s["tags"][0]
    assert t["ledger_n"] == 7000 and t["n"] == 120


def test_the_base_rate_is_the_pooled_win_rate_of_the_graded_rows():
    s = _stats([_row("a", 1000, 300, 120), _row("b", 1000, 100, 30)])
    assert s["base_rate"] == round((120 + 30) / 400, 3) == 0.375


# ── what earns a flag ────────────────────────────────────────────────────────────────────────────────────────

def test_a_credibly_worse_tag_is_flagged():
    s = _stats([_row("bad", 5000, 1500, 300), _row("rest", 5000, 20000, 7000)])
    bad = next(t for t in s["tags"] if t["tag"] == "bad")
    assert bad["flagged"] is True and s["flagged"] == ["bad"]
    assert bad["p_value"] < 0.05 and bad["lift"] < -0.05


def test_engagement_does_not_move_the_metric():
    # same graded outcomes, 25x different engagement: the old metric separated these two,
    # the new one cannot — because "a directive surfaced" is not a result
    s = _stats([_row("chatty", 5000, 200, 70, actioned=4800, directive=100),
                _row("quiet", 200, 200, 70, actioned=0, directive=0)])
    chatty, quiet = s["tags"]
    assert chatty["hit_rate"] == quiet["hit_rate"] == 0.35
    assert chatty["lift"] == quiet["lift"]
    assert not chatty["flagged"] and not quiet["flagged"]


def test_a_significant_gap_below_the_effect_floor_is_not_flagged():
    # 50,000 graded rows, a 2.7-point gap, p far below alpha — and still not worth acting on
    s = _stats([_row("tiny", 200000, 100000, 47000), _row("rest", 900000, 1000000, 500000)])
    tiny = next(t for t in s["tags"] if t["tag"] == "tiny")
    assert tiny["lift"] < 0 and tiny["lift"] > -0.05
    assert tiny["p_value"] is not None and tiny["p_value"] < 0.05
    assert tiny["flagged"] is False and "lift>-0.05" in tiny["flag_reason"]


def test_an_outperforming_tag_is_never_flagged():
    s = _stats([_row("good", 5000, 2000, 900), _row("rest", 5000, 20000, 5000)])
    good = next(t for t in s["tags"] if t["tag"] == "good")
    assert good["flagged"] is False and good["lift"] > 0


def test_a_tag_below_the_sample_floor_is_reported_but_not_flagged():
    s = _stats([_row("small", 100, 14, 0), _row("rest", 5000, 20000, 6000)])
    small = next(t for t in s["tags"] if t["tag"] == "small")
    assert small["n"] == 14 and small["flagged"] is False
    assert "n<15" in small["flag_reason"]


def test_a_flag_needs_three_reasons_cleared_not_one():
    # a good-looking gap on a small sample is still not credible
    s = _stats([_row("small_good", 200, 20, 10), _row("rest", 5000, 20000, 7000)], min_n=50)
    sb = next(t for t in s["tags"] if t["tag"] == "small_good")
    assert sb["flagged"] is False and "n<50" in sb["flag_reason"]
    assert sb["flag_reason"].count(",") >= 1        # more than one gate failed


# ── the test statistic ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("z,expected", [(0.0, 0.5), (1.6449, 0.05), (-1.6449, 0.95), (1.96, 0.025)])
def test_the_one_sided_normal_tail(z, expected):
    assert TE._normal_sf(z) == pytest.approx(expected, abs=1e-3)


def test_the_statistic_is_monotone():
    assert TE._normal_sf(-3) > TE._normal_sf(-1) > TE._normal_sf(0) > TE._normal_sf(2)


# ── configuration ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_config_carries_the_three_gates():
    cfg = yaml.safe_load((ROOT / "config" / "hermes_tag_engine.yaml").read_text())
    eff = cfg["efficacy"]
    assert eff["min_samples_per_tag"] == 15
    assert eff["min_effect"] == 0.05 and 0 < eff["alpha"] <= 0.05


def test_the_engine_never_touches_a_broker():
    src = (ROOT / "scripts" / "hermes_tag_engine.py").read_text()
    for banned in ("place_order", "import broker", "from broker", "ib_insync", "alpaca"):
        assert banned not in src
