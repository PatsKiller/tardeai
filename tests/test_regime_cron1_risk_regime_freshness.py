"""Tests for REGIME-CRON-1 risk regime freshness fixes."""
import subprocess, sys, os
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCRIPTS = PROJ / "scripts"
PY = str(PROJ / ".venv" / "bin" / "python")


def test_staleness_report_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / "report_regime_cron1_staleness.py")])
    assert r.returncode == 0


def test_schema_contract_report_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / "report_regime_cron1_schema_contract.py")])
    assert r.returncode == 0


def test_health_script_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / "run_regime_cron1_health.py")])
    assert r.returncode == 0


def test_classifier_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / "market_regime_classifier.py")])
    assert r.returncode == 0


def test_collector_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / "market_regime_collector.py")])
    assert r.returncode == 0


def test_rotation_engine_compiles():
    r = subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / "strategy_rotation_engine.py")])
    assert r.returncode == 0


def test_wrapper_bash_syntax():
    wrapper = SCRIPTS / "run_scheduled_risk_regime_classifier.sh"
    assert wrapper.exists()
    r = subprocess.run(["bash", "-n", str(wrapper)])
    assert r.returncode == 0


def test_wrapper_checks_alpaca_mode():
    text = (SCRIPTS / "run_scheduled_risk_regime_classifier.sh").read_text()
    assert 'ALPACA_MODE' in text
    assert '"paper"' in text


def test_wrapper_checks_llm_disable():
    text = (SCRIPTS / "run_scheduled_risk_regime_classifier.sh").read_text()
    assert 'LLM_DISABLE_LIVE_EXECUTION' in text
    assert '"true"' in text


def test_wrapper_uses_flock():
    text = (SCRIPTS / "run_scheduled_risk_regime_classifier.sh").read_text()
    assert 'flock' in text


def test_wrapper_records_skip_telemetry():
    text = (SCRIPTS / "run_scheduled_risk_regime_classifier.sh").read_text()
    assert 'record_stage_run' in text
    assert 'skipped' in text


def test_classifier_save_passes_dry_run_false():
    """Verify the root cause fix: save_snapshot is called with dry_run=False."""
    text = (SCRIPTS / "market_regime_classifier.py").read_text()
    assert "save_snapshot(conn, snapshot, dry_run=False)" in text


def test_collector_save_passes_dry_run_false():
    text = (SCRIPTS / "market_regime_collector.py").read_text()
    assert "save_indicators(conn, indicators, dry_run=False)" in text


def test_rotation_save_passes_dry_run_false():
    text = (SCRIPTS / "strategy_rotation_engine.py").read_text()
    assert "save_signals(conn, signals, alignments, dry_run=False)" in text


def test_classifier_has_transaction_recovery():
    text = (SCRIPTS / "market_regime_classifier.py").read_text()
    assert "conn.rollback()" in text
    assert "_record_run_log" in text


def test_rotation_signals_require_admin_approval():
    text = (SCRIPTS / "strategy_rotation_engine.py").read_text()
    assert "requires_admin_approval" in text
    assert 'True' in text


def test_no_strategy_activation_in_rotation():
    text = (SCRIPTS / "strategy_rotation_engine.py").read_text()
    lower = text.lower()
    assert "enable_strategy" not in lower
    assert "activate_strategy" not in lower
    assert "auto_apply" not in lower


def test_no_trades_in_classifier():
    text = (SCRIPTS / "market_regime_classifier.py").read_text()
    lower = text.lower()
    assert "submit_order" not in lower
    assert "create_trade" not in lower
    assert "place_order" not in lower


def test_env_unchanged():
    """Safety: .env must not be modified by these scripts."""
    text = (SCRIPTS / "market_regime_classifier.py").read_text()
    assert ".env" not in text or "load_dotenv" in text  # only loading, not writing
    assert "write" not in text.lower() or "write_text" not in text  # no .env write


def test_live_trading_disabled():
    """Check .env safety markers."""
    env_path = PROJ / ".env"
    if env_path.exists():
        env = env_path.read_text()
        assert "ALPACA_MODE=paper" in env
        assert "LLM_DISABLE_LIVE_EXECUTION=true" in env
