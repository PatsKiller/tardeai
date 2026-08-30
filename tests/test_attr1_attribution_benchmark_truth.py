"""Tests for ATTR-1 attribution benchmark truth layer."""
import subprocess, sys, json

import pytest
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCRIPTS = PROJ / "scripts"
STATE = PROJ / "data" / "portfolios" / "state"


def test_data_availability_report_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / "report_attr1_data_availability.py")])
    assert r.returncode == 0


def test_attribution_script_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / "portfolio_performance_attribution.py")])
    assert r.returncode == 0


def test_benchmark_report_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / "report_attr1_benchmark_alpha.py")])
    assert r.returncode == 0


def test_attribution_file_exists():
    assert (STATE / "performance_attribution.json").exists()


def test_attribution_has_real_data():
    data = json.loads((STATE / "performance_attribution.json").read_text())
    assert data.get("has_data") is True


def test_alpha_is_internally_consistent_with_its_own_cagrs():
    """alpha_annualized must equal port_cagr - bench_cagr in the same file.

    NAMING NOTE. This was called `test_no_fake_alpha` and its docstring claimed
    alpha "must be computed from real CAGR values, not hardcoded". It cannot
    show that. All three numbers are read from
    data/portfolios/state/performance_attribution.json, so the test asks the
    artifact to vouch for itself: a wholly fabricated but internally consistent
    file passes. Measured 2026-08-30 against the deployed tree -- port_cagr
    16.85, bench_cagr 16.77, alpha 0.08 -- it passed on a file four days stale.

    What it does prove is worth keeping: the producer did not derive alpha by
    some other route than the difference it reports. It is named for that now.
    Detecting a fabricated CAGR needs the producer re-run against the snapshot
    and price stores, which this test does not do.
    """
    data = json.loads((STATE / "performance_attribution.json").read_text())
    alpha = data.get("alpha_annualized")
    if alpha is None:
        # Previously an `if ... is not None:` wrapper, so a null alpha made the
        # whole test pass silently -- the "no fake alpha" gate was green
        # precisely when there was no alpha to check. Skip states that.
        pytest.skip("alpha_annualized is null; nothing to check")
    port = data.get("port_cagr")
    bench = data.get("bench_cagr")
    assert port is not None and bench is not None, "Alpha exists but CAGR values are null"
    expected = round(port - bench, 2)
    assert abs(alpha - expected) < 0.1, f"Alpha {alpha} != port-bench {expected}"


def test_benchmark_cagr_declares_enough_history():
    """A bench_cagr must be accompanied by a snapshot_count that supports it.

    Same caveat as above, stated rather than implied: snapshot_count is the
    artifact's own claim about its input depth, not a count taken from the
    snapshot store. This rejects a file that admits to thin history; it cannot
    reject one that misreports it.
    """
    data = json.loads((STATE / "performance_attribution.json").read_text())
    if data.get("bench_cagr") is None:
        pytest.skip("bench_cagr is null; nothing to check")
    assert data.get("snapshot_count", 0) >= 30, "Benchmark CAGR with insufficient data"


def test_insufficient_history_returns_reason():
    """When data insufficient, note field must explain."""
    data = json.loads((STATE / "performance_attribution.json").read_text())
    assert data.get("note"), "Attribution note/reason field is empty"


def test_benchmark_prices_cached():
    """Benchmark symbols must be in price cache."""
    cache = json.loads((STATE / "price_cache.json").read_text())
    for sym in ["SPY", "ITA", "AGG"]:
        assert cache.get(sym), f"{sym} missing from price cache"
        assert len(cache[sym]) > 100, f"{sym} has insufficient price history"


def test_yfinance_multiindex_fix():
    """The MultiIndex flatten fix must be present."""
    text = (SCRIPTS / "portfolio_performance_attribution.py").read_text()
    assert "iloc[:, 0]" in text, "Missing yfinance MultiIndex flatten fix"


def test_ui_no_silent_na():
    """Attribution UI must show 'Unavailable' not bare N/A or em dash for missing fields."""
    text = (PROJ / "apps" / "command-center-v2" / "src" / "pages" / "Attribution.tsx").read_text()
    assert "Unavailable" in text, "UI should show 'Unavailable' for missing fields"
    assert "unavailableReason" in text, "UI should compute and show unavailable reason"


def test_no_trades_created():
    text = (SCRIPTS / "portfolio_performance_attribution.py").read_text()
    lower = text.lower()
    assert "submit_order" not in lower
    assert "create_trade" not in lower


def test_env_safety():
    env = (PROJ / ".env").read_text()
    assert "ALPACA_MODE=paper" in env
    assert "LLM_DISABLE_LIVE_EXECUTION=true" in env
