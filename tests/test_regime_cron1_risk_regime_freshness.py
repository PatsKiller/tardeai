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


def test_env_is_never_written_at_runtime(tmp_path, monkeypatch):
    """BEHAVIOURAL canary for the same rule, and the reason it exists is the AST half's blind spot.

    ``test_env_unchanged`` reads the module's syntax tree, which catches a write spelled in this file — a literal
    ``Path(".env").write_text(...)`` or a name bound to one. It cannot see a write that happens somewhere else:
    ``dotenv.set_key(...)``, a helper module the script imports, a path built by concatenation, an alias, ``os.replace``
    or a subprocess redirect. Those are exactly the false negatives a reviewer named at PR 2700.

    So this runs the real module in a temp tree whose ``.env`` is a sentinel, with every write primitive wrapped, and
    asserts two things: the sentinel comes back byte-identical, and no write primitive was handed a ``.env``-shaped path.
    The AST half is the fast first line; this half is the proof.

    What each half proves:
      * AST  — for any write written in this file, the target is not ``.env`` (static, instant, no execution).
      * canary — for everything the module actually does when it is loaded, nothing touched ``.env`` at runtime,
        whatever spelling or indirection was used.
    Importing is the boundary: the module's import-time work (including ``load_dotenv``) is exercised; ``main()`` is not
    run here because it reads live state, so a write added inside ``main`` is covered by the AST half only.
    """
    import builtins
    import importlib.util
    import os as _os
    from pathlib import Path as _Path

    # set_key lives on `dotenv.main`; a venv without the package leaves only the write-primitive spies, which the
    # set_key mutation below demonstrates are not the whole story either.
    try:
        from dotenv import main as _dotenv_main
    except ImportError:  # pragma: no cover - the project venv has python-dotenv
        _dotenv_main = None

    source = (SCRIPTS / "market_regime_classifier.py").read_text()
    (tmp_path / "scripts").mkdir()
    target = tmp_path / "scripts" / "market_regime_classifier.py"
    target.write_text(source)
    sentinel = b"ALPACA_MODE=paper\nSENTINEL=do-not-touch\n"
    env_path = tmp_path / ".env"
    env_path.write_bytes(sentinel)

    touched: list[str] = []
    ENVISH = re.compile(r"(?:^|[\\/])[.]env(?:[\\/]|$)|['\"]\.env['\"]|[.]env[.]", re.I)

    def note(args, kwargs):
        for value in list(args) + list(kwargs.values()):
            if isinstance(value, (str, bytes)) or hasattr(value, "__fspath__"):
                try:
                    text = _os.fspath(value)
                except TypeError:
                    continue
                text = text.decode() if isinstance(text, bytes) else str(text)
                if ENVISH.search(text):
                    touched.append(text)

    real_open = builtins.open

    def spy_open(file, mode="r", *a, **k):
        # `load_dotenv` legitimately OPENS .env for reading; only a write mode is an offence, so a read is ignored
        # rather than recorded — otherwise the canary would fail on the module's normal behaviour.
        writing = any(ch in str(mode) for ch in "wax+")
        if writing:
            note((file,), {})
            if isinstance(file, (str, _os.PathLike)) and ENVISH.search(_os.fspath(file)):
                raise AssertionError(f"the module opened {_os.fspath(file)!r} for writing")
        return real_open(file, mode, *a, **k)

    real_write_text = _Path.write_text
    real_write_bytes = _Path.write_bytes

    def spy_write_text(self, *a, **k):
        note((self,), {})
        if ENVISH.search(str(self)):
            raise AssertionError(f"the module wrote {self}")
        return real_write_text(self, *a, **k)

    def spy_write_bytes(self, *a, **k):
        note((self,), {})
        if ENVISH.search(str(self)):
            raise AssertionError(f"the module wrote {self}")
        return real_write_bytes(self, *a, **k)

    real_replace, real_write = _os.replace, _os.write

    def spy_replace(src, dst, *a, **k):
        note((src, dst), {})
        if ENVISH.search(str(src)) or ENVISH.search(str(dst)):
            raise AssertionError(f"the module replaced {src} -> {dst}")
        return real_replace(src, dst, *a, **k)

    real_set_key = _dotenv_main.set_key if _dotenv_main is not None and hasattr(_dotenv_main, "set_key") else None

    def spy_set_key(dotenv_path=None, *a, **k):
        note((dotenv_path,), {})
        raise AssertionError(f"the module called set_key on {dotenv_path!r}")

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(_Path, "write_text", spy_write_text)
    monkeypatch.setattr(_Path, "write_bytes", spy_write_bytes)
    monkeypatch.setattr(_os, "replace", spy_replace)
    if real_set_key is not None:
        monkeypatch.setattr(_dotenv_main, "set_key", spy_set_key)

    spec = importlib.util.spec_from_file_location("_canary_market_regime_classifier", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    assert env_path.read_bytes() == sentinel, "the module modified .env when it was loaded"
    assert not touched, f"the module handed a .env-shaped path to a write primitive: {touched}"


def test_live_trading_disabled():
    """Check .env safety markers."""
    env_path = PROJ / ".env"
    if env_path.exists():
        env = env_path.read_text()
        assert "ALPACA_MODE=paper" in env
        assert "LLM_DISABLE_LIVE_EXECUTION=true" in env
