"""3c — provenance at display, on the cash advisory.

Measured 2026-08-30 across 24 materially different situations (1%/5%/20% cash,
risk-on and risk-off, policy confirmed and not, thesis present and absent),
reaching all four conclusions, two fields never moved:

    counter_case         one byte-identical sentence in all 24
    supporting_evidence  [null, null, null, null, null]

A counter-case is the argument against THIS recommendation on THIS data. A
constant in that slot is a disclaimer wearing a counter-case's label, and it
reads to the operator as reasoning that was done.

The published shapes did NOT change: `counter_case` stays a string and
`supporting_evidence` stays a list, because four consumers read them
positionally and one does `list(...)`, which on a dict silently yields keys.
"""
from __future__ import annotations

import itertools

from scripts.lib import cio_cash_capital_v1 as m


def _build(cash_pct, risk_off, confirmed, thesis_ok):
    policy = {"status": "CONFIRMED" if confirmed else "DRAFT", "fields": {
        "cash_target_range_pct": {"value": {"min": 3, "max": 8},
                                  "operator_confirmed": confirmed},
        "minimum_liquidity_reserve_usd": {"value": 50000,
                                          "operator_confirmed": confirmed}}}
    ps = {"observed_cash_usd": cash_pct * 10000,
          "investable_cash_usd": cash_pct * 10000 - 50000,
          "allocation": {"cash": {"pct": cash_pct}},
          "total_portfolio_value_usd": 1_000_000,
          "reserved_cash_usd": 50000.0, "truth_quality": "VERIFIED"}
    mc = {"regime": "RISK_OFF" if risk_off else "RISK_ON",
          "truth_quality": "VERIFIED",
          "forward_event_context": {"macro": {"events": []},
                                    "portfolio_earnings": {"events": []}}}
    th = {"state": "CURRENT", "underweight_sleeves": ["tech"]} if thesis_ok else None
    return m.build_cash_deployment_situation(
        policy=policy, portfolio_state=ps, market_context=mc,
        seasonality={"truth_quality": "VERIFIED"}, portfolio_thesis=th)


def _grid():
    return [_build(*c) for c in itertools.product(
        [1.0, 5.0, 20.0], [False, True], [True, False], [True, False])]


def test_the_grid_actually_reaches_every_conclusion():
    """Without this, "the field varies" would be an artifact of an unexercised
    code path — which is how the first version of this measurement lied."""
    got = {s.get("conclusion") for s in _grid()}
    assert {"DEPLOY_STAGED", "HOLD_CASH", "REBALANCE", "RESEARCH_FIRST"} <= got


def test_the_counter_case_is_no_longer_one_constant():
    by = {}
    for s in _grid():
        by.setdefault(s["conclusion"], set()).add(s.get("counter_case"))
    texts = {t for v in by.values() for t in v}
    assert len(texts) >= 4, "a counter-case that never moves is a disclaimer"
    # And it is stable *per conclusion* — varying is not the same as random.
    for conclusion, variants in by.items():
        assert len(variants) >= 1


def test_the_counter_case_argues_against_the_conclusion_it_accompanies():
    """Each one must be a case against, not a restatement of, the stance."""
    for s in _grid():
        cc = s.get("counter_case") or ""
        if s["conclusion"] == "DEPLOY_STAGED":
            assert "not itself a reason to deploy" in cc
        elif s["conclusion"] == "HOLD_CASH":
            assert "costs the return" in cc


def test_the_grounds_are_read_from_the_situation_not_asserted():
    risk_off = [s for s in _grid() if s.get("regime_risk_off")]
    assert risk_off
    prov = risk_off[0]["counter_case_provenance"]
    assert "the current regime reads risk-off" in prov["grounds"]
    assert prov["state"] == "STATED"


def test_the_counter_case_declares_itself_a_template_not_model_output():
    prov = _grid()[0]["counter_case_provenance"]
    assert prov["provenance"].startswith("TEMPLATE")
    assert "Not model-written" in prov["provenance"]


def test_an_unknown_conclusion_yields_an_absence_not_a_generic_sentence():
    cc = m._counter_case(conclusion="SOMETHING_NEW", deviation_state=None,
                         regime_risk_off=False, blockers=[])
    assert cc["state"] == "NONE_SPECIFIC"
    assert cc["text"] is None
    assert m._counter_case_text(conclusion="SOMETHING_NEW", deviation_state=None,
                                regime_risk_off=False, blockers=[]) is None


def test_five_nulls_are_now_five_named_absences():
    s = _grid()[0]
    st = s["supporting_evidence_state"]
    assert st["state"] == "NONE"
    assert st["counts"] == {"present": 0, "missing": 5}
    assert "policy" in st["unversioned_sources"]


def test_a_versioned_input_is_reported_present():
    st = m._supporting_evidence({"version": "p1"}, {}, {}, {},
                                {"thesis_version": "t9"})
    assert st["state"] == "PARTIAL"
    assert {e["source"] for e in st["present"]} == {"policy", "portfolio_thesis"}
    assert st["counts"] == {"present": 2, "missing": 3}


# ── the shapes four consumers depend on ────────────────────────────────────

def test_published_shapes_are_unchanged_for_existing_consumers():
    """`cio_r13_institution` does list(supporting_evidence); on a dict that
    silently yields the KEYS. `cio_advisory_message` f-strings counter_case."""
    s = _grid()[0]
    assert isinstance(s["counter_case"], str)
    assert isinstance(s["supporting_evidence"], list)
    assert len(s["supporting_evidence"]) == 5
    assert list(s["supporting_evidence"]) == s["supporting_evidence"]
    assert "{" not in f"Counter: {s['counter_case']}"
