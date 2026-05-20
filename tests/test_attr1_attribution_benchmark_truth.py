"""Tests for ATTR-1 attribution benchmark truth layer."""
import subprocess, sys, json
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


def test_no_fake_alpha():
    """Alpha must be computed from real CAGR values, not hardcoded."""
    data = json.loads((STATE / "performance_attribution.json").read_text())
    if data.get("alpha_annualized") is not None:
        # Alpha = port_cagr - bench_cagr
        port = data.get("port_cagr")
        bench = data.get("bench_cagr")
        assert port is not None and bench is not None, "Alpha exists but CAGR values are null"
        expected = round(port - bench, 2)
        assert abs(data["alpha_annualized"] - expected) < 0.1, f"Alpha {data['alpha_annualized']} != port-bench {expected}"


def test_no_fake_benchmark():
    """Benchmark CAGR must come from real price data."""
    data = json.loads((STATE / "performance_attribution.json").read_text())
    if data.get("bench_cagr") is not None:
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
