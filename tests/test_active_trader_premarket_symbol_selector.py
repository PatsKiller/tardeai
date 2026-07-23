"""Stage 5 harness — representative-symbol selector tests (pure, deterministic)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader.premarket_symbol_selector import (  # noqa: E402
    SelectionStatus, select_representative, BASELINE_SYMBOL,
)


def row(**kw):
    base = dict(symbol="US.MOVR", security_type="COMMON", price=8.0,
                premarket_change_pct=12.0, premarket_volume=500_000, premarket_turnover=4_000_000)
    base.update(kw)
    return base


def test_valid_common_stock_selected():
    r = select_representative([row()])
    assert r.status == SelectionStatus.SELECTED.value and r.representative == "US.MOVR"
    assert r.baseline == BASELINE_SYMBOL


def test_etf_and_etn_excluded():
    assert select_representative([row(symbol="US.SPY", security_type="ETF")]).status \
        == SelectionStatus.NO_QUALIFYING_CANDIDATE.value
    assert select_representative([row(symbol="US.OILN", security_type="ETN")]).status \
        == SelectionStatus.NO_QUALIFYING_CANDIDATE.value


def test_warrant_right_unit_option_excluded():
    for st in ("WARRANT", "RIGHT", "UNIT", "OPTION", "PREFERRED"):
        assert select_representative([row(symbol="US.X", security_type=st)]).status \
            == SelectionStatus.NO_QUALIFYING_CANDIDATE.value


def test_otc_excluded():
    assert select_representative([row(is_otc=True)]).status \
        == SelectionStatus.NO_QUALIFYING_CANDIDATE.value


def test_leveraged_inverse_name_excluded():
    assert select_representative([row(symbol="US.SOXL", name="Direxion Daily 3X Bull")]).status \
        == SelectionStatus.NO_QUALIFYING_CANDIDATE.value


def test_price_bounds():
    assert select_representative([row(price=0.80)]).status == SelectionStatus.NO_QUALIFYING_CANDIDATE.value
    assert select_representative([row(price=75.0)]).status == SelectionStatus.NO_QUALIFYING_CANDIDATE.value


def test_low_volume_and_small_gap_excluded():
    assert select_representative([row(premarket_volume=50_000)]).status \
        == SelectionStatus.NO_QUALIFYING_CANDIDATE.value
    assert select_representative([row(premarket_change_pct=2.0)]).status \
        == SelectionStatus.NO_QUALIFYING_CANDIDATE.value


def test_negative_gap_counts_by_absolute_value():
    assert select_representative([row(premarket_change_pct=-8.0)]).status \
        == SelectionStatus.SELECTED.value


def test_ties_deterministic_ordering():
    rows = [
        row(symbol="US.BBB", premarket_turnover=9_000_000, premarket_volume=800_000),
        row(symbol="US.AAA", premarket_turnover=9_000_000, premarket_volume=800_000),  # tie -> symbol asc
        row(symbol="US.CCC", premarket_turnover=5_000_000, premarket_volume=999_999),
    ]
    r1 = select_representative(rows)
    r2 = select_representative(list(reversed(rows)))
    assert r1.representative == "US.AAA" == r2.representative     # deterministic regardless of input order


def test_baseline_never_selected_as_representative():
    r = select_representative([row(symbol="US.AAPL", price=40.0)])
    assert r.status == SelectionStatus.NO_QUALIFYING_CANDIDATE.value


def test_malformed_and_empty_and_unavailable():
    assert select_representative(None).status == SelectionStatus.RANK_UNAVAILABLE.value
    assert select_representative("not-a-list").status == SelectionStatus.INVALID_SOURCE_DATA.value
    assert select_representative([]).status == SelectionStatus.NO_QUALIFYING_CANDIDATE.value
    assert select_representative([{"foo": "bar"}, 42]).status == SelectionStatus.INVALID_SOURCE_DATA.value
    # a good row mixed with malformed ones still selects (malformed skipped)
    assert select_representative([{"foo": "bar"}, row()]).status == SelectionStatus.SELECTED.value


def test_deterministic_output_repeatable():
    rows = [row(symbol="US.MOVR"), row(symbol="US.GAPR", premarket_turnover=8_000_000)]
    assert select_representative(rows).as_dict() == select_representative(rows).as_dict()
