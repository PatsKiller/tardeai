"""Every module a notification path imports must actually exist.

`open_trade_monitor.send_telegram` imported `telegram_bot`, a module present in
no tree. A bare `except Exception` caught the ImportError and logged it at
warning level, so STOP_HIT_CLOSE, TIME_STOP_CLOSE, TRAILING_STOP and NEAR_TARGET
were undeliverable from 2026-05-25 to 2026-08-31 -- 581 identical failures, one
distinct cause, nobody paged.

The operator received 40 copies of the "monitoring" alert, sent by a different
function in the same file that works, and zero copies of "your stop was hit and
I closed the position".

A test that only imports the module would not have caught it: the broken import
is INSIDE a function, inside a try. This resolves the imports by name.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "scripts" / "open_trade_monitor.py"

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _function_local_imports(path: Path) -> list[tuple[str, int]]:
    """Every `from X import ...` that sits inside a function body."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, int]] = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                out.append((node.module, node.lineno))
    return out


def test_every_function_local_import_in_the_monitor_resolves():
    """The regression. A name that does not resolve is a silent dead notification."""
    unresolvable = []
    for mod, lineno in _function_local_imports(MONITOR):
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            unresolvable.append(f"{MONITOR.name}:{lineno} -> {mod} ({exc})")
    assert not unresolvable, "unresolvable imports on a notification path: " + "; ".join(unresolvable)


def test_the_detector_can_see_a_broken_import():
    """Guard the guard: prove the check fails on a name that does not exist.

    Without this the assertion above would pass against a file whose imports
    were all removed, which is not the property being asserted.
    """
    with pytest.raises(ImportError):
        importlib.import_module("telegram_bot_that_does_not_exist")


def test_the_stop_path_sender_is_importable_and_callable():
    from telegram_alert import send_telegram

    assert callable(send_telegram)


def test_the_dead_module_is_not_referenced_anywhere_in_the_monitor():
    src = MONITOR.read_text(encoding="utf-8")
    assert "from telegram_bot import" not in src, "the dead import is back"
