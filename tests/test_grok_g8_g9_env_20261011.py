"""G8–G9 env narrowing (2026-10-11).

Hermetic: temp env files with synthetic values. Never opens a real .env, never prints a value
from the process environment except the fixtures this file wrote.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from scripts.lib.cio_production_eligibility import (  # noqa: E402
    PROJECT_ROOT,
    _STATE_ROOT_ENV_NAMES,
    cio_state_root,
)
from scripts.lib.env_bootstrap import is_broker_name  # noqa: E402

DB = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
BROKER = (
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_MODE", "SCHWAB_APP_KEY", "SCHWAB_APP_SECRET",
    "SNAPTRADE_USER_SECRET", "MOOMOO_TRADE_PWD", "IBKR_ACCOUNT", "TRADING_MODE",
)
OTHER = ("TELEGRAM_BOT_TOKEN", "BWS_ACCESS_TOKEN", "OPENAI_API_KEY")


def _fake_env(path: Path) -> None:
    lines = ["# synthetic", "BWS_ACCESS_TOKEN='fixture-bws'"]
    lines += [f"{n}=fixture-{n}" for n in DB + BROKER + OTHER if n != "BWS_ACCESS_TOKEN"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _added(fn):
    """Run fn against a process env with the fixture names removed, then put the env back.

    The loader writes os.environ directly, which monkeypatch does not undo.
    """
    saved = dict(os.environ)
    for name in DB + BROKER + OTHER:
        os.environ.pop(name, None)
    try:
        before = set(os.environ)
        fn()
        return set(os.environ) - before, os.environ.get("DB_PASSWORD")
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.mark.parametrize(
    "env,expect",
    [
        ({}, None),
        ({"MATURITY_CONTROL_ROOT": "/tmp/g8-maturity"}, "/tmp/g8-maturity"),
        ({"TRADEAI_ROOT": "/tmp/g8-tradeai", "MATURITY_CONTROL_ROOT": "/tmp/g8-maturity"}, "/tmp/g8-tradeai"),
        ({"CIO_STATE_ROOT": "/tmp/g8-cio", "TRADEAI_ROOT": "/tmp/g8-tradeai"}, "/tmp/g8-cio"),
        ({"CIO_STATE_ROOT": "   ", "TRADEAI_ROOT": "/tmp/g8-tradeai"}, "/tmp/g8-tradeai"),
        ({"CIO_STATE_ROOT": ""}, None),
    ],
)
def test_cio_state_root_keeps_first_nonempty_then_checkout(monkeypatch, env, expect):
    for name in _STATE_ROOT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    got = cio_state_root()
    assert got == (PROJECT_ROOT if expect is None else Path(expect))


def test_every_cio_state_root_caller_passes_no_arguments():
    """The function takes no arguments. Callers keep that shape, so the precedence above is their behaviour."""
    bad = []
    for base in (ROOT / "scripts", ROOT / "tests"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "cio_state_root" not in text:
                continue
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                if name == "cio_state_root" and (node.args or node.keywords):
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert bad == []


def test_state_root_reads_are_literals():
    import test_n8n_executor_env_allowlist_20261009 as P7

    path = ROOT / "scripts/lib/cio_production_eligibility.py"
    reads = P7._env_reads(path, set())
    assert {"CIO_STATE_ROOT", "TRADEAI_ROOT", "MATURITY_CONTROL_ROOT"} <= reads
    assert "os.environ.get(key)" not in path.read_text(encoding="utf-8")


def test_no_report_lane_that_imports_eligibility_is_enforce_eligible():
    """Re-run of the import-closure rule. The literal reads clear the unresolved-read failure.
    A lane is enforce-eligible only at <=10 modules with every literal covered by env_names.
    Measured set is empty: those closures stay above 10, so none is flipped and the pin stays 17.
    """
    import test_n8n_executor_env_allowlist_20261009 as P7
    from scripts import n8n_run_executor as X

    eligible = []
    touched = []
    still_this_file = []
    for lane, entry in sorted(P7.LANES.items()):
        if entry.get("env_allowlist_mode") != "report":
            continue
        scripts = [P7.ROOT / t for t in entry["command"] if str(t).endswith(".py")]
        visited: set = set()
        try:
            reads = set().union(*(P7._env_reads(p, visited) for p in scripts))
            completed = True
        except AssertionError as exc:
            reads = set()
            completed = False
            if "cio_production_eligibility.py" in str(exc):
                still_this_file.append(lane)
        rels = {str(p.relative_to(P7.ROOT)) for p in visited}
        if not any(r.endswith("scripts/lib/cio_production_eligibility.py") for r in rels):
            continue
        touched.append((lane, len(visited), completed))
        if not completed:
            continue
        if entry.get("lock_kind", "safe_flock") == "safe_flock":
            reads |= {"PROJECT_ROOT", "SAFE_FLOCK_LOG_DIR"}
        extra = reads - X.CHILD_ENV_BASE_NAMES - set(entry.get("env_names") or [])
        if len(visited) <= 10 and not extra:
            eligible.append(lane)
    assert still_this_file == []
    assert len(touched) >= 28
    assert eligible == []
    assert min(n for _, n, _ in touched) > 10


@pytest.mark.parametrize(
    "module,root_is_path",
    [
        ("hermes_news_bridge", False),
        ("hermes_topic_monitor_bridge", False),
        ("catalyst_momentum_engine", True),
    ],
)
def test_narrowed_loader_never_copies_a_broker_name(module, root_is_path, monkeypatch, tmp_path):
    _fake_env(tmp_path / ".env")
    mod = __import__(module)
    monkeypatch.setattr(mod, "ROOT", tmp_path if root_is_path else str(tmp_path))
    load = mod.load_env if module != "catalyst_momentum_engine" else mod._load_env
    added, password = _added(load)
    assert added == set(DB)
    assert password == "fixture-DB_PASSWORD"
    assert not any(is_broker_name(name) for name in added)
