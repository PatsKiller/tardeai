"""Tests for REGIME-CRON-1 risk regime freshness fixes."""
import re, subprocess, sys, os
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
    """Safety: .env must not be WRITTEN by this script — loading it is fine, and so is writing output files.

    The old form banned the substring `write_text` anywhere in the module, so a legitimate
    `Path(args.output_json).write_text(...)` (market_regime_classifier.py:422/:435, PR 2313) turned main red. Relaxing it
    to "no writes at all" would have deleted the guard; this asserts the property that actually matters instead: no write
    — `write_text`, `write_bytes`, `open(..., 'w')` — may target a `.env`-shaped path.

    It reads the module's syntax tree rather than its text, so a write of the output file and a write of `.env` are
    distinguishable, and it stays strict on the dangerous case: a write whose own expression names `.env`, or which is
    handed a name bound to a `.env` literal, fails.
    """
    import ast

    source = (SCRIPTS / "market_regime_classifier.py").read_text()
    tree = ast.parse(source)

    ENVISH = re.compile(r"(?:^|[\\/])[.]env(?:[\\/]|$)|['\"]\.env['\"]|[.]env[.]", re.I)

    def is_write(call: ast.Call) -> bool:
        fn = call.func
        name = getattr(fn, "attr", None) or getattr(fn, "id", None)
        if name in ("write_text", "write_bytes"):
            return True
        if name == "open":
            for arg in call.args[1:2] + [k.value for k in call.keywords if k.arg == "mode"]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and any(c in arg.value for c in "wax+"):
                    return True
        return False

    # Names bound to a `.env`-shaped literal anywhere in the module.
    env_names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        # A name bound to a `.env` literal AND a name bound to something like `Path(".env")` are both `.env` handles.
        segment = ast.get_source_segment(source, node.value) or ""
        literal = isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) and ENVISH.search(node.value.value)
        if literal or ENVISH.search(segment):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    env_names.add(target.id)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_write(node):
            continue
        segment = ast.get_source_segment(source, node) or ""
        if ENVISH.search(segment):
            offenders.append((node.lineno, segment.splitlines()[0][:120]))
            continue
        # The RECEIVER can be the `.env` handle too: `env_path.write_text(...)`, where `env_path = Path(".env")`.
        for arg in [node.func] + list(node.args) + [k.value for k in node.keywords]:
            for inner in ast.walk(arg):
                if isinstance(inner, ast.Name) and inner.id in env_names:
                    offenders.append((node.lineno, f"write through {inner.id}"))
                elif isinstance(inner, ast.Constant) and isinstance(inner.value, str) and ENVISH.search(inner.value):
                    offenders.append((node.lineno, inner.value[:80]))

    assert not offenders, f"market_regime_classifier.py writes a .env-shaped path: {offenders}"


def test_live_trading_disabled():
    """Check .env safety markers."""
    env_path = PROJ / ".env"
    if env_path.exists():
        env = env_path.read_text()
        assert "ALPACA_MODE=paper" in env
        assert "LLM_DISABLE_LIVE_EXECUTION=true" in env
