"""Paper/broker-adjacent child steps resolve their interpreter without assuming the release ships a .venv (2026-10-09).

Follow-up to tests/test_cron_venv_resolver_20261009.py under the operator's execution-engineering grant
(remote_request_id dc66eb4b6db5107e: "fix the paper scripts too, grant approved"). Code-only: the four scripts built
`<code_root>/.venv/bin/python`, which no release directory has. Also telegram_command_handler's inner `import os` made
`os` function-local, so the run_promoter command raised UnboundLocalError (ruff F823).
Static checks only: nothing is imported that touches a broker, and nothing is launched.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ["paper_trade_closer", "paper_trade_monitor", "alpaca_paper_adapter", "broker_promote_oversight"]
RELEASE_RELATIVE = re.compile(r'str\(\s*\w+\s*/\s*"\.venv/bin/python"')


def _src(name: str) -> str:
    return (ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")


def test_paper_scripts_use_the_shared_resolver():
    for name in PAPER:
        src = _src(name)
        assert not RELEASE_RELATIVE.search(src), name
        assert "def _child_python(code_root)" in src and "from lib.live_project_root import venv_python" in src, name
        assert src.count("_child_python(") >= 2, name


def test_helper_is_top_level_and_parses():
    for name in PAPER:
        tree = ast.parse(_src(name))
        assert any(isinstance(n, ast.FunctionDef) and n.name == "_child_python" for n in tree.body), name


def test_telegram_handler_never_shadows_os():
    tree = ast.parse(_src("telegram_command_handler"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Import):
                    assert all(a.name != "os" or a.asname for a in inner.names), (node.name, inner.lineno)
