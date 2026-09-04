#!/usr/bin/env python3
"""Stop coverage must be computed over ONE population, with everything named.

Measured on live data 2026-09-03, the served Risk surface said 0.39% protected.
Recomputed from the same rows it publishes, the answer is 11.92% — a thirty-fold
understatement with two independent causes:

  * four BROKER-VERIFIED stops (V, SCHD, DIV, BAH, $72,782.66) read as "NO STOP"
    because the aggregate is built from the planned-stops file alone;
  * the percentage divides by the whole portfolio ($1,299,166.67) while the parts
    it sums are the risk-included subset ($653,205.34).

No network, broker, order or production path is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.protection_truth import (  # noqa: E402
    BROKER_VERIFIED,
    PLANNED_ONLY,
    UNKNOWN,
    UNPROTECTED,
    classify_position,
    protection_truth,
)


def pos(symbol, mv, **kw):
    return {"symbol": symbol, "account": kw.pop("account", "acct_a"), "market_value": mv, **kw}


#: The live shape that produced the defect.
LIVE = [
    pos("AMANX", 5066.75, has_stop=True, broker_protected=False, stop_source="planned"),
    pos("V", 49710.61, has_stop=True, broker_protected=True, stop_source="broker"),
    pos("SCHD", 14188.37, has_stop=True, broker_protected=True, stop_source="broker"),
    pos("DIV", 8206.52, has_stop=True, broker_protected=True, stop_source="broker"),
    pos("BAH", 677.16, has_stop=True, broker_protected=True, stop_source="broker"),
    *[pos(f"X{i}", 57535.593, has_stop=False, broker_protected=False, stop_source="none") for i in range(10)],
]
LEGACY = {"pct_protected": 0.39, "total_protected_mv": 5066.75, "total_unprotected_mv": 648138.59}


# ── classification ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "row,expected",
    [
        ({"broker_protected": True, "stop_source": "broker", "has_stop": True}, BROKER_VERIFIED),
        ({"broker_protected": False, "stop_source": "planned", "has_stop": True}, PLANNED_ONLY),
        ({"broker_protected": False, "stop_source": "none", "has_stop": False}, UNPROTECTED),
        ({"has_stop": False, "stop_source": ""}, UNPROTECTED),
        ({"stop_price": 12.5, "has_stop": None, "stop_source": ""}, PLANNED_ONLY),
    ],
)
def test_each_protection_class_is_reachable(row, expected):
    assert classify_position(row)[0] == expected


def test_a_row_with_no_stop_facts_is_unknown_not_unprotected():
    """The rule that matters: absence of evidence is not evidence of absence."""
    cls, why = classify_position({"symbol": "Z", "market_value": 100})
    assert cls == UNKNOWN
    assert "no stop facts" in why


def test_a_broker_stop_is_never_downgraded_to_unprotected():
    """The exact live defect: broker_protected=True rendering as NO STOP."""
    for row in ({"broker_protected": True}, {"stop_source": "broker"}):
        assert classify_position(row)[0] == BROKER_VERIFIED


# ── aggregation ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def live():
    return protection_truth(LIVE, legacy=LEGACY)


def test_broker_verified_market_value_is_counted(live):
    assert live["counts"][BROKER_VERIFIED] == 4
    assert live["market_value"][BROKER_VERIFIED] == pytest.approx(72782.66, abs=0.01)


def test_numerator_and_denominator_come_from_the_same_population(live):
    parts = sum(live["market_value"][c] for c in live["market_value"])
    assert parts == pytest.approx(live["denominator_market_value"], abs=0.05)
    assert live["coverage"]["denominator"] == "market value of every risk-included position"


def test_the_recomputed_percentage_is_the_honest_one(live):
    assert live["coverage"]["any_stop_pct_of_included"] == pytest.approx(11.92, abs=0.02)
    assert live["coverage"]["broker_verified_pct_of_included"] == pytest.approx(11.14, abs=0.02)


def test_the_legacy_disagreement_is_published_not_resolved(live):
    cmp = live["legacy_comparison"]
    assert cmp["verdict"] == "DISAGREES"
    assert cmp["agrees_on_protected_mv"] is False
    assert cmp["legacy_denominator_matches_its_own_parts"] is False
    assert cmp["legacy_implied_denominator"] == pytest.approx(1299166.67, abs=1.0)
    assert set(cmp["broker_verified_symbols_the_legacy_figure_omits"]) == {"V", "SCHD", "DIV", "BAH"}
    assert cmp["why"]


def test_unknown_is_in_neither_the_covered_nor_the_uncovered_figure():
    rows = [
        pos("A", 100, has_stop=True, broker_protected=True, stop_source="broker"),
        pos("B", 100, has_stop=False, stop_source="none"),
        pos("C", 100),  # no stop facts at all
    ]
    r = protection_truth(rows)
    assert r["counts"][UNKNOWN] == 1
    assert r["coverage"]["unknown_market_value"] == 100.0
    assert r["coverage"]["unknown_excluded_from_both"] is True
    # 100 covered of 300 included; of the 200 decidable it is 50%.
    assert r["coverage"]["any_stop_pct_of_included"] == pytest.approx(33.33, abs=0.02)
    assert r["coverage"]["any_stop_pct_of_decidable"] == pytest.approx(50.0, abs=0.02)


def test_risk_excluded_rows_leave_the_denominator():
    rows = [
        pos("A", 100, has_stop=True, broker_protected=True, stop_source="broker"),
        pos("B", 900, has_stop=False, stop_source="none", risk_excluded=True),
    ]
    r = protection_truth(rows)
    assert r["population"]["risk_included"] == 1
    assert r["population"]["risk_excluded"] == 1
    assert r["denominator_market_value"] == 100.0
    assert r["coverage"]["any_stop_pct_of_included"] == 100.0


def test_empty_is_unavailable_not_zero_percent():
    r = protection_truth([])
    assert r["status"] == "UNAVAILABLE"
    assert "unknown, not zero" in r["reason"]
    assert "coverage" not in r, "an unavailable reading must not publish a percentage"


def test_scope_and_truncation_are_explicit():
    rows = [pos(f"S{i}", 10, account=f"acct_{i % 3}", has_stop=False, stop_source="none") for i in range(60)]
    r = protection_truth(rows, max_list=25)
    assert r["population"]["account_count"] == 3
    assert r["population"]["scope"] == "ALL_ACCOUNTS"
    assert r["list_truncated"] is True
    assert r["list_shown"] == 25
    assert r["list_total"] == 60
    assert len(r["positions"]) == 25

    single = protection_truth([pos("S", 10, account="only", has_stop=False, stop_source="none")])
    assert single["population"]["scope"] == "only"
    assert single["list_truncated"] is False


def test_observation_metadata_is_carried_through():
    r = protection_truth(LIVE, observation={"source": "/api/v2/risk", "as_of": "2026-09-03"})
    assert r["observation"]["source"] == "/api/v2/risk"


def test_the_contract_is_registered_and_fails_closed():
    src = (ROOT / "scripts" / "api_v2.py").read_text(errors="replace")
    assert '"/api/v2/risk/protection-truth"' in src
    assert "def _protection_truth()" in src
    fn = src[src.index("def _protection_truth()") :]
    fn = fn[: fn.index("\ndef ")]
    assert "UNAVAILABLE" in fn and "reason" in fn, "the route must fail closed with a reason"


def test_the_module_is_read_only():
    src = (ROOT / "scripts" / "lib" / "protection_truth.py").read_text()
    for banned in ("requests.", "urlopen", "write_text", "subprocess", "place_order", "_db_write"):
        assert banned not in src, f"read-only module contains {banned}"
