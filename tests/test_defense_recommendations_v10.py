from pathlib import Path


SOURCE = Path("scripts/defense_recommendations_v10.py").read_text()
POLICY = Path("config/defense_account_exposure.json").read_text()


def test_v10_is_additive_and_delegates_non_rotate_paths():
    assert "import defense_recommendations as base" in SOURCE
    assert "base.rotate_in = rotate_in_v10" in SOURCE
    assert "return base.main()" in SOURCE
    assert "protect, trim, hedge" in SOURCE


def test_v10_uses_account_specific_exposure_and_sizing():
    assert "account_sector_exposure" in SOURCE
    assert "build_account_sizing" in SOURCE
    assert "current_account_weight_pct" in SOURCE
    assert '"account_sizing": account_sizing' in SOURCE
    assert '"dollars_by_account": dollars_by_account' in SOURCE
    assert "max_capacity = max" not in SOURCE
    assert "current_weight_pct=float(sector_row.get(\"book_pct\")" not in SOURCE


def test_v10_withholds_accounts_with_excess_unmapped_exposure():
    assert "max_unmapped_pct" in SOURCE
    assert "unmapped_pct" in SOURCE
    assert "return None" in SOURCE
    assert '"max_unmapped_pct": 5.0' in POLICY


def test_v10_requires_complete_stock_and_close_industry_gates():
    assert "stock_quality_assessment" in SOURCE
    assert "requires_close_confirmed_industry" in SOURCE
    assert 'if not quality["passed"]' in SOURCE
    assert "ETF only; no stock passed complete close-industry and evidence rails" in SOURCE


def test_v10_is_advisory_and_has_no_execution_clients():
    forbidden = (
        "import subprocess",
        "from subprocess",
        "import requests",
        "import psycopg2",
        "place_order",
        "submit_order",
        "approve_order",
        "systemctl",
    )
    for token in forbidden:
        assert token not in SOURCE
    assert "nothing self-executes" in SOURCE
