"""ANCHOR: MARKET_OUTLOOK_ENGINE_20261108 — LQ-20261107-966, Market Outlook Engine v1.

The six behaviours the design (§2, §4.6, §5 WU-2) names as must-prove, on synthetic fixtures only (public repo):
an UNKNOWN category is renormalised out and never read as zero; the band hysteresis needs two evaluations or a jump;
the MRE tier caps the stance; the FOMC window blocks a new RISK_ON; a banned feed is refused rather than scored; and
every record carries the policy file's own sha256.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.lib.market_outlook import CATEGORY_KEYS, SCHEMA_RECORD
from scripts.lib.market_outlook import brief as brief_mod
from scripts.lib.market_outlook import calendar as cal_mod
from scripts.lib.market_outlook import categories as cat_mod
from scripts.lib.market_outlook import confidence as conf_mod
from scripts.lib.market_outlook import levels as lvl_mod
from scripts.lib.market_outlook import normalize as nz
from scripts.lib.market_outlook import policy as policy_mod
from scripts.lib.market_outlook import record as rec_mod
from scripts.lib.market_outlook import regime as regime_mod
from scripts.lib.market_outlook import scoring
from scripts.lib.market_outlook.sources import Bundle

ET = ZoneInfo("America/New_York")
SUNDAY = datetime(2026, 11, 8, 20, 0, tzinfo=ET)  # the design's own evaluation instant (§4.3)


@pytest.fixture(scope="module")
def policy():
    return policy_mod.load_policy()


def _bars(n: int = 260, start: float = 100.0, drift: float = 0.0012, wiggle: float = 0.6) -> list[dict]:
    """``n`` weekday bars ending on Friday 2026-11-06 — the last closed session before the Sunday evaluation."""
    end = datetime(2026, 11, 6).date()
    days = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    out = []
    px = start
    for i, day in enumerate(days):
        px = px * (1.0 + drift) + wiggle * math.sin(i / 5.0)
        out.append(
            {
                "date": day.isoformat(),
                "close": round(px, 4),
                "high": round(px * 1.01, 4),
                "low": round(px * 0.99, 4),
                "source": "alpaca",
                "as_of": f"{day.isoformat()}T17:00:00-05:00",
            }
        )
    return out


def _equity_bundle() -> Bundle:
    """Five index proxies with full daily history and nothing else: exactly one category can be measured."""
    return Bundle(
        as_of=SUNDAY.isoformat(),
        bars={s: _bars() for s in ("SPY", "QQQ", "DIA", "IWM", "RSP")},
    )


def _ctx(bundle: Bundle, policy: dict, **kw) -> cat_mod.BuildContext:
    return cat_mod.BuildContext(bundle=bundle, policy=policy, now=kw.pop("now", SUNDAY), **kw)


# ── 1. UNKNOWN renormalisation ----------------------------------------------------------------------------------
def test_unknown_category_is_renormalised_out_never_zero(policy):
    cats = cat_mod.build_categories(_ctx(_equity_bundle(), policy))
    by_key = {c.key: c for c in cats}
    assert by_key["futures"].state == "UNKNOWN"
    assert by_key["cash_indices"].measured and by_key["cash_indices"].coverage == 1.0

    score = scoring.compute(cats, policy, None)
    # only cash_indices is measured, so S is exactly that category's own sub-score on the -100..+100 scale
    assert score.score == pytest.approx(100.0 * by_key["cash_indices"].subscore, abs=1e-9)
    assert score.unknown and "futures" in score.unknown
    # and the UNKNOWN category is named with a reason, not a silent zero
    assert by_key["futures"].reason_unknown and "coverage 0.00" in by_key["futures"].reason_unknown
    assert "no /ES print" in by_key["futures"].reason_unknown or "print" in by_key["futures"].reason_unknown


def test_a_fully_unmeasured_run_states_unknown_not_zero(policy):
    empty = Bundle(as_of=SUNDAY.isoformat())
    score = scoring.compute(cat_mod.build_categories(_ctx(empty, policy)), policy, None)
    assert score.score is None and score.band is None
    assert any("UNKNOWN rather than a zero" in a for a in score.adjustments)


# ── 2. hysteresis -----------------------------------------------------------------------------------------------
def test_hysteresis_needs_two_evaluations(policy):
    prior = {"band": "NEUTRAL", "score": 23.0}
    held = scoring.resolve_band(26.0, policy, prior=prior, history=[])
    assert held == "NEUTRAL"  # one evaluation in the new band is not enough and |dS| is under the jump threshold

    prior_two = {"band": "NEUTRAL", "score": 26.0}
    assert scoring.resolve_band(26.0, policy, prior=prior_two, history=[]) == "RISK_ON"


def test_a_large_jump_moves_the_band_at_once(policy):
    assert scoring.resolve_band(30.0, policy, prior={"band": "NEUTRAL", "score": 5.0}, history=[]) == "RISK_ON"


def test_rise_from_defensive_cannot_skip_a_band(policy):
    band = scoring.resolve_band(30.0, policy, prior={"band": "DEFENSIVE", "score": -20.0}, history=[])
    assert band == "NEUTRAL"  # capped at one band per weekly cycle


# ── 3. MRE cap and FOMC window ----------------------------------------------------------------------------------
def test_mre_tier_caps_the_stance(policy):
    reg = regime_mod.Regime(mre_tier="ORANGE")
    assert scoring.resolve_band(45.0, policy, prior=None, regime=reg, history=[]) == "DEFENSIVE"
    reg_yellow = regime_mod.Regime(mre_tier="YELLOW")
    assert scoring.resolve_band(45.0, policy, prior=None, regime=reg_yellow, history=[]) == "NEUTRAL"


def test_red_shock_forces_risk_off(policy):
    reg = regime_mod.Regime(mre_tier="RED", red_shock=True)
    assert scoring.resolve_band(50.0, policy, prior=None, regime=reg, history=[]) == "RISK_OFF"


def test_fomc_window_blocks_a_new_risk_on(policy):
    assert scoring.resolve_band(30.0, policy, prior=None, fomc_window=True, history=[]) == "NEUTRAL"
    # an existing RISK_ON is not revoked by the window
    assert scoring.resolve_band(30.0, policy, prior={"band": "RISK_ON", "score": 28.0}, history=[], fomc_window=True) == "RISK_ON"


def test_fomc_window_comes_from_the_calendar(policy):
    items = [
        {"date_et": "2026-11-10", "time_et": "14:00", "event": "fomc_decision", "impact": "HIGH", "impact_weight": 1.0},
        {"date_et": "2026-12-09", "time_et": "14:00", "event": "fomc_decision", "impact": "HIGH", "impact_weight": 1.0},
    ]
    active, detail = cal_mod.fomc_window(items, policy, datetime(2026, 11, 9, 9, 0, tzinfo=ET))
    assert active and "2026-11-10" in detail
    inactive, _ = cal_mod.fomc_window(items[1:], policy, datetime(2026, 11, 9, 9, 0, tzinfo=ET))
    assert not inactive


# ── 4. banned feeds are refused, never scored -------------------------------------------------------------------
def test_banned_feed_is_refused_not_scored(policy):
    bundle = Bundle(
        as_of=SUNDAY.isoformat(),
        regime={
            "vix_close": {"value": 24.9, "feed": "yahoo_finance", "as_of": "2026-11-06T16:05:00-05:00"},
            "vix9d_close": {"value": 26.1, "feed": "yahoo_finance", "as_of": "2026-11-06T16:05:00-05:00"},
            "vix3m_close": {"value": 23.4, "feed": "yahoo_finance", "as_of": "2026-11-06T16:05:00-05:00"},
        },
    )
    vol = policy_mod.category(policy, "volatility")
    term = next(i for i in vol["indicators"] if i["key"] == "term")
    res = cat_mod._term_structure(term, _ctx(bundle, policy), "market_regime_indicators")
    assert res.normalized is None and not res.available
    assert "banned feed" in (res.refused_reason or "")

    reg = regime_mod.resolve(bundle, policy, SUNDAY, CATEGORY_KEYS)
    assert reg.vix_value is None and reg.vix_source is None
    assert any("refused" in n for n in reg.notes)


def test_clean_fred_vix_is_used_when_the_regime_table_is_banned(policy):
    bundle = Bundle(
        as_of=SUNDAY.isoformat(),
        fred={"VIXCLS": [{"date": "2026-11-06", "value": 24.9, "as_of": "2026-11-06T18:00:00+00:00"}]},
        regime={"vix_close": {"value": 30.0, "feed": "yfinance", "as_of": "2026-11-06T16:05:00-05:00"}},
    )
    reg = regime_mod.resolve(bundle, policy, SUNDAY, CATEGORY_KEYS)
    assert reg.vix_value == 24.9 and reg.vix_source == "fred:VIXCLS" and reg.vix_band == "MID"


# ── 5. policy hash stamping -------------------------------------------------------------------------------------
def test_policy_version_is_the_file_hash():
    path = policy_mod.POLICY_PATH
    assert policy_mod.policy_version(path) == hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_record_stamps_the_policy_version_and_snapshot_hash(policy):
    bundle = _equity_bundle()
    cats = cat_mod.build_categories(_ctx(bundle, policy))
    score = scoring.compute(cats, policy, None)
    confidence = conf_mod.compute(cats, policy, SUNDAY, u_event=0.85)
    record = rec_mod.build(
        now=SUNDAY, mode="sunday", seq=1, policy_version=policy_mod.policy_version(),
        score=score, confidence=confidence, regime=regime_mod.Regime(),
        categories=cats, scenarios={}, levels=lvl_mod.key_levels(bundle, policy),
        catalysts=[], what_would_change_view=[], actions_template={}, prior_record_id=None,
    )
    assert record["schema"] == SCHEMA_RECORD
    assert record["policy_version"] == policy_mod.policy_version()
    assert rec_mod.validate(record) == []
    assert len(record["categories"]) == 11
    assert record["inputs_snapshot_hash"] == rec_mod.snapshot_hash(cats)
    # the hash is over the evidence, so a changed indicator changes it
    cats[0].indicators[0].normalized = -0.999
    assert rec_mod.snapshot_hash(cats) != record["inputs_snapshot_hash"]


def test_record_rejects_a_renamed_field(policy):
    bundle = _equity_bundle()
    cats = cat_mod.build_categories(_ctx(bundle, policy))
    record = rec_mod.build(
        now=SUNDAY, mode="sunday", seq=1, policy_version=policy_mod.policy_version(),
        score=scoring.compute(cats, policy, None),
        confidence=conf_mod.compute(cats, policy, SUNDAY),
        regime=regime_mod.Regime(), categories=cats, scenarios={}, levels={},
        catalysts=[], what_would_change_view=[], actions_template={}, prior_record_id=None,
    )
    record["categories"][0]["sub_score"] = record["categories"][0].pop("subscore")
    assert any("sub_score" in p for p in rec_mod.validate(record))


# ── 6. the brief names every UNKNOWN and its reason -------------------------------------------------------------
def test_brief_lists_every_unknown_with_its_reason(policy):
    bundle = _equity_bundle()
    cats = cat_mod.build_categories(_ctx(bundle, policy))
    score = scoring.compute(cats, policy, None)
    confidence = conf_mod.compute(cats, policy, SUNDAY)
    record = rec_mod.build(
        now=SUNDAY, mode="sunday", seq=1, policy_version=policy_mod.policy_version(),
        score=score, confidence=confidence, regime=regime_mod.Regime(),
        categories=cats, scenarios=scoring.scenarios(score.score or 0.0, None, {"SPX": 2.0}, policy),
        levels=lvl_mod.key_levels(bundle, policy), catalysts=[], what_would_change_view=[],
        actions_template={"band": score.band}, prior_record_id=None,
    )
    text = brief_mod.render_text(
        record=record, categories=cats, score=score, confidence=confidence, regime=regime_mod.Regime(),
        levels={}, catalysts=[], triggers=[], policy=policy, mode="sunday", dry_run=True,
    )
    unknown = [c for c in cats if c.state == "UNKNOWN"]
    assert unknown
    assert f"UNKNOWN ({len(unknown)})" in text
    for c in unknown:
        assert f"· {c.key}:" in text
        assert c.reason_unknown.split(";")[0] in text
    assert "DRY RUN: nothing was written" in text


# ── 7. the anchor is the cash close, never an ETF times a factor ----------------------------------------------
def test_a_missing_cash_close_is_not_measured_and_not_an_etf_factor(policy):
    bundle = _equity_bundle()
    levels = lvl_mod.key_levels(bundle, policy)
    spy_close = bundle.bars["SPY"][-1]["close"]
    factor = policy["levels"]["etf_to_index"]["SPX"]
    spx = levels["SPX"]
    assert spx["basis"] == "not_measured"
    assert spx["anchor"] is None
    assert spx["anchor"] != pytest.approx(spy_close * factor, rel=1e-4)
    assert spx["support"] == [] and spx["resistance"] == []
    assert "not measured" in spx["note"]


def test_the_anchor_is_the_stored_cash_close_not_the_etf_factor(policy):
    bundle = _equity_bundle()
    bundle.extended = [
        {"symbol": "$SPX", "price": 7376.86, "feed": "schwab", "session": "overnight",
         "bar_start": "2026-11-08T20:00:00-05:00", "bar_end": "2026-11-08T20:00:00-05:00"},
        {"symbol": "$SPX", "price": 100.0, "feed": "yfinance", "session": "overnight",
         "bar_end": "2026-11-08T21:00:00-05:00"},
    ]
    levels = lvl_mod.key_levels(bundle, policy)
    spx = levels["SPX"]
    assert spx["basis"] == "cash"
    assert spx["anchor"] == 7376.86
    assert spx["source"] == "schwab"
    assert spx["as_of"] == "2026-11-08T20:00:00-05:00"
    assert spx["proxy"] is None
    spy_close = bundle.bars["SPY"][-1]["close"]
    assert spx["anchor"] != pytest.approx(spy_close * policy["levels"]["etf_to_index"]["SPX"], rel=1e-3)
    # The producer record carries the cash close. The brief does not recompute it.
    from scripts.lib.market_outlook_brief import _anchor
    assert _anchor({"key_levels": {"SPX": spx}}, "SPX") == 7376.86
    cats = cat_mod.build_categories(_ctx(bundle, policy))
    built = rec_mod.build(
        now=SUNDAY, mode="sunday", seq=1, policy_version=policy_mod.policy_version(),
        score=scoring.compute(cats, policy, None),
        confidence=conf_mod.compute(cats, policy, SUNDAY, u_event=0.85),
        regime=regime_mod.Regime(), categories=cats, scenarios={}, levels=levels,
        catalysts=[], what_would_change_view=[], actions_template={}, prior_record_id=None,
    )
    assert built["key_levels"]["SPX"]["anchor"] == 7376.86
    assert built["key_levels"]["SPX"]["as_of"] == "2026-11-08T20:00:00-05:00"
    assert built["key_levels"]["COMPX"]["basis"] == "not_measured"
    assert built["key_levels"]["COMPX"]["anchor"] is None


# ── 8. the write path: validation first, then ON CONFLICT DO NOTHING --------------------------------------------
class _FakeCursor:
    def __init__(self, rowcount: int = 1):
        self.executed: list[tuple[str, list]] = []
        self.rowcount = rowcount

    def execute(self, sql, params):
        self.executed.append((sql, params))


def test_writer_refuses_an_invalid_record_and_inserts_a_valid_one(policy):
    from scripts.lib.writers import market_outlook_writer as w

    bundle = _equity_bundle()
    cats = cat_mod.build_categories(_ctx(bundle, policy))
    record = rec_mod.build(
        now=SUNDAY, mode="sunday", seq=1, policy_version=policy_mod.policy_version(),
        score=scoring.compute(cats, policy, None),
        confidence=conf_mod.compute(cats, policy, SUNDAY),
        regime=regime_mod.Regime(), categories=cats, scenarios={}, levels={},
        catalysts=[], what_would_change_view=[], actions_template={}, prior_record_id=None,
    )
    cur = _FakeCursor()
    receipt = w.write_records(cur, [record, {**record, "record_id": "broken", "categories": []}])
    assert receipt["inserted"] == 1 and receipt["accepted"] == 1
    assert len(receipt["rejected"]) == 1 and "categories" in receipt["rejected"][0]["reason"]
    assert "ON CONFLICT (record_id) DO NOTHING" in cur.executed[0][0]
    assert json.loads(cur.executed[0][1][-1])["record_id"] == record["record_id"]


def test_cio_payload_is_built_from_the_record(policy):
    from scripts.lib.writers import market_outlook_writer as w

    cats = cat_mod.build_categories(_ctx(_equity_bundle(), policy))
    record = rec_mod.build(
        now=SUNDAY, mode="sunday", seq=3, policy_version=policy_mod.policy_version(),
        score=scoring.compute(cats, policy, None),
        confidence=conf_mod.compute(cats, policy, SUNDAY),
        regime=regime_mod.Regime(), categories=cats, scenarios={}, levels={},
        catalysts=[], what_would_change_view=[], actions_template={}, prior_record_id=None,
    )
    payload = w.cio_payload(record)
    assert payload["symbol"] == "MARKET" and payload["strategy_type"] == "market_outlook"
    assert payload["group_id"] == record["record_id"] == "outlook:2026-11-08:sunday:3"
    assert payload["action"] == record["band"]
    assert payload["metadata"]["policy_version"] == policy_mod.policy_version()


# ── 9. --apply writes the runtime mirror under the state root, atomically ---------------------------------------
def test_runtime_mirror_is_written_under_the_state_root(tmp_path, policy):
    import scripts.market_outlook_evaluate as cli

    cats = cat_mod.build_categories(_ctx(_equity_bundle(), policy))
    record = rec_mod.build(
        now=SUNDAY, mode="sunday", seq=1, policy_version=policy_mod.policy_version(),
        score=scoring.compute(cats, policy, None),
        confidence=conf_mod.compute(cats, policy, SUNDAY),
        regime=regime_mod.Regime(), categories=cats, scenarios={}, levels={},
        catalysts=[], what_would_change_view=[], actions_template={}, prior_record_id=None,
    )
    written = cli._write_runtime(tmp_path, {"record": record, "problems": []})
    assert len(written) == 3
    latest = json.loads((tmp_path / "data" / "runtime" / "market_outlook" / "latest.json").read_text())
    assert latest["record"]["record_id"] == record["record_id"]
    run_last = json.loads((tmp_path / "data" / "runtime" / "market_outlook" / "run_last.json").read_text())
    assert run_last["record_id"] == record["record_id"] and run_last["band"] == record["band"]
    # no .tmp file survives the atomic replace
    assert not list((tmp_path / "data" / "runtime" / "market_outlook").glob("*.tmp"))


# ── 10. the event tilt IS tau (LQ-985 review finding 1) ---------------------------------------------------------
def test_event_tilt_passes_tau_through_un_rescaled(policy):
    """§2.6: tau = -0.15 * max impact, and tau IS category 10's signal (§2.10: CPI HIGH -> tau -0.15 -> C10 ~ -0.15).

    Dividing tau by ``tilt_per_impact`` turned -0.15 into a full -1.00 and overstated the S penalty ~7 points."""
    items = [
        {
            "date_et": "2026-11-10",
            "time_et": "08:30",
            "event": "cpi",
            "name": "CPI",
            "impact": "HIGH",
            "impact_weight": 1.0,
        }
    ]
    tau, detail = cal_mod.tilt(items, policy, SUNDAY)
    assert tau == pytest.approx(-0.15)  # a HIGH catalyst two sessions out
    assert cal_mod.tilt([], policy, SUNDAY)[0] == 0.0  # nothing scheduled -> no tilt, never a guess

    # the raw normalizer agrees with the spec's own numbers
    assert nz.event_tilt_state(tau, policy["events"])[0] == pytest.approx(-0.15)
    # ...and so does the indicator the events category actually builds
    ev = policy_mod.category(policy, "events")
    spec = next(i for i in ev["indicators"] if i["key"] == "event_tilt")
    res = cat_mod._event_tilt(spec, _ctx(_equity_bundle(), policy, tilt=tau, tilt_detail=detail), "macro_calendar")
    assert res.normalized == pytest.approx(-0.15)

    # end to end: with only the catalyst measured, C10 is tau itself (the surprise leg is unmeasured here)
    cats = cat_mod.build_categories(_ctx(_equity_bundle(), policy, tilt=tau, tilt_detail=detail))
    events = next(c for c in cats if c.key == "events")
    assert events.state == "PARTIAL" and events.coverage == pytest.approx(0.60)
    assert events.subscore == pytest.approx(-0.15, abs=1e-6)


# ── 11. band boundaries are the spec's own table (LQ-985 review) ------------------------------------------------
@pytest.mark.parametrize(
    "score,band",
    [
        (25.0, "RISK_ON"),  # RISK-ON: S >= +25
        (24.99, "NEUTRAL"),  # NEUTRAL: -10 < S < +25
        (-10.0, "DEFENSIVE"),  # DEFENSIVE: -35 < S <= -10 (the boundary belongs to the defensive side)
        (-9.99, "NEUTRAL"),
        (-35.0, "RISK_OFF"),  # RISK-OFF: S <= -35
        (-34.99, "DEFENSIVE"),
    ],
)
def test_band_boundaries_follow_the_spec_table(policy, score, band):
    assert scoring.band_of(score, policy) == band


# ── 12. confidence: every factor is in the product (LQ-985 review) ---------------------------------------------
def _synthetic_cat(key: str, weight: float, sub: float | None, *, as_of: str | None = None) -> cat_mod.CategoryResult:
    if sub is None:
        return cat_mod.CategoryResult(
            key=key, title=key, weight_prior=weight, weight_effective=weight, subscore=None,
            coverage=0.0, state="UNKNOWN",
        )
    return cat_mod.CategoryResult(
        key=key, title=key, weight_prior=weight, weight_effective=weight, subscore=sub, coverage=1.0,
        state="COLLECTED",
        indicators=[
            cat_mod.IndicatorResult(
                key=f"{key}_i", label=key, type="trend", weight=1.0, normalized=sub,
                as_of=as_of or SUNDAY.isoformat(),
            )
        ],
    )


def test_each_confidence_factor_moves_the_product(policy):
    agree = [_synthetic_cat("a", 30.0, 0.5), _synthetic_cat("b", 70.0, 0.5)]
    base = conf_mod.compute(agree, policy, SUNDAY, u_event=1.0, hitrate=1.0)
    assert (base.coverage, base.freshness, base.agreement) == (1.0, 1.0, 1.0)
    assert base.value == pytest.approx(1.0) and base.band == "HIGH"

    # agreement: categories that disagree pull the product down (floored at 0.3)
    disagree = [_synthetic_cat("a", 50.0, 1.0), _synthetic_cat("b", 50.0, -1.0)]
    c_agr = conf_mod.compute(disagree, policy, SUNDAY, u_event=1.0, hitrate=1.0)
    assert c_agr.agreement == pytest.approx(0.3) and c_agr.value == pytest.approx(0.3)

    # freshness: the same evidence read nine days old decays the product with it
    old = "2026-10-30T16:00:00-04:00"
    stale = [_synthetic_cat("a", 30.0, 0.5, as_of=old), _synthetic_cat("b", 70.0, 0.5, as_of=old)]
    c_fresh = conf_mod.compute(stale, policy, SUNDAY, u_event=1.0, hitrate=1.0)
    assert c_fresh.freshness < 1.0
    assert c_fresh.value == pytest.approx(c_fresh.freshness)

    # event risk and the trailing hit rate, each alone
    assert conf_mod.compute(agree, policy, SUNDAY, u_event=0.85, hitrate=1.0).value == pytest.approx(0.85)
    assert conf_mod.compute(agree, policy, SUNDAY, u_event=1.0, hitrate=0.75).value == pytest.approx(0.75)

    # coverage: one 30-weight category measured out of 100 (the weight test below pins the arithmetic)
    partial = [_synthetic_cat("a", 30.0, 0.5), _synthetic_cat("b", 70.0, None)]
    c_cov = conf_mod.compute(partial, policy, SUNDAY, u_event=1.0, hitrate=1.0)
    assert c_cov.coverage == pytest.approx(0.30) and c_cov.value == pytest.approx(0.30)


def test_coverage_is_measured_by_prior_weight_not_by_count(policy):
    # two of the three categories are measured, but they carry 10 + 20 of the 100 points: coverage is 0.30, not 2/3
    cats = [
        _synthetic_cat("a", 10.0, 0.4),
        _synthetic_cat("b", 20.0, 0.1),
        _synthetic_cat("c", 70.0, None),
    ]
    conf = conf_mod.compute(cats, policy, SUNDAY, u_event=1.0, hitrate=1.0)
    assert conf.coverage == pytest.approx(0.30)
    assert conf.coverage != pytest.approx(2.0 / 3.0)


# ── 13. confidence band edges and the U_event floor (LQ-985 mutation survivors) ----------------------------------
@pytest.mark.parametrize(
    "weight,band",
    [(70.0, "HIGH"), (69.9, "MODERATE"), (45.0, "MODERATE"), (44.9, "LOW")],
)
def test_confidence_band_edges_are_inclusive_at_the_stated_thresholds(policy, weight, band):
    # one measured category of this weight: coverage is the whole product (freshness, agreement, U, hitrate all 1.0)
    conf = conf_mod.compute([_synthetic_cat("a", weight, 0.5)], policy, SUNDAY, u_event=1.0, hitrate=1.0)
    assert conf.value == pytest.approx(weight / 100.0)
    assert conf.band == band  # HIGH >= 0.70, MODERATE >= 0.45


def test_u_event_is_floored_not_compounded_away(policy):
    # six HIGH events inside the horizon: 0.85^6 = 0.377 would sink confidence; the floor holds it at 0.60 (§2.6)
    items = [
        {"date_et": "2026-11-09", "time_et": "08:30", "event": f"high_{i}", "impact": "HIGH", "impact_weight": 1.0}
        for i in range(6)
    ]
    u, named = cal_mod.u_event(items, policy, SUNDAY, 2)
    assert len(named) == 6
    assert u == pytest.approx(policy["events"]["u_event_floor"]) == pytest.approx(0.60)


# ── 14. --hitrate is refused with --apply (LQ-985 review) -------------------------------------------------------
def test_hitrate_override_is_refused_with_apply(capsys):
    import scripts.market_outlook_evaluate as cli

    code = cli.main(["--hitrate", "0.9", "--apply"])
    assert code == 2
    err = capsys.readouterr().err
    assert "--hitrate cannot be combined with --apply" in err


def test_record_reads_use_a_read_only_connection(monkeypatch):
    """The prior/grades/sequence SELECTs must not hold a read-write session (they run before --apply decides)."""
    import scripts.market_outlook_evaluate as cli
    from scripts.lib.market_outlook import sources

    app, peer = object(), object()
    monkeypatch.setattr(sources, "_app_conn", lambda: app)
    monkeypatch.setattr(sources, "_peer_conn", lambda: peer)
    assert cli._read_conn("app") is app
    assert cli._read_conn("peer") is peer
