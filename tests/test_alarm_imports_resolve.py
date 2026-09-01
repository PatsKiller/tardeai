"""C2 — every symbol imported on an alarm path must resolve.

Two incidents, months apart, same defect:

  from telegram_alert import send_alert   -- send_alert has never existed
  from telegram_bot   import ...          -- telegram_bot exists nowhere

Both sat inside bare `except` blocks, so the ImportError was swallowed and the
alarm reported to nobody: 171 firings during a 24-day signal outage, and
STOP_HIT_CLOSE silent for 98 days.

This check is static (AST only). It never imports repository modules, because
importing a script executes it.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# A module is on an "alarm path" if its name carries one of these. Discovery by
# symbol, not a hand-maintained list of alarms -- a hand-kept list is the next
# thing to go stale.
ALARM_HINTS = ("alert", "notify", "telegram", "escalat", "notification")


def _local_modules() -> dict[str, Path]:
    return {p.stem: p for p in SCRIPTS.rglob("*.py")}


def _toplevel_names(path: Path) -> set[str] | None:
    """Names a module defines at top level, determined without importing it."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.If):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
    return names


def unresolved_alarm_imports(scripts_dir: Path = SCRIPTS) -> list[tuple[str, int, str, str]]:
    """(file, line, module, symbol) for every alarm-path import that cannot resolve."""
    mods = {p.stem: p for p in scripts_dir.rglob("*.py")}
    bad: list[tuple[str, int, str, str]] = []
    for path in sorted(scripts_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            mod = node.module.split(".")[-1]
            if not any(h in mod.lower() for h in ALARM_HINTS):
                continue
            try:
                rel = str(path.relative_to(ROOT))
            except ValueError:
                rel = str(path)   # scanning a tmp tree (the positive controls)
            target = mods.get(mod)
            if target is None:
                # MISSING MODULE, not merely a missing symbol. An earlier version of
                # this detector skipped here -- which is exactly the telegram_bot case
                # it exists to catch. Only flag local-looking modules so third-party
                # packages are not reported.
                if "." not in node.module and importlib.util.find_spec(node.module) is None:
                    for alias in node.names:
                        bad.append((rel, node.lineno, mod, alias.name + "  [MODULE MISSING]"))
                continue
            names = _toplevel_names(target)
            if names is None:
                continue
            for alias in node.names:
                if alias.name != "*" and alias.name not in names:
                    bad.append((rel, node.lineno, mod, alias.name))
    return bad


def test_no_unresolved_alarm_imports():
    bad = unresolved_alarm_imports()
    assert not bad, "alarm-path imports that cannot resolve:\n" + "\n".join(
        f"  {f}:{ln}  from {m} import {s}" for f, ln, m, s in bad
    )


def test_positive_control_detector_catches_a_missing_symbol(tmp_path):
    """A detector that cannot fail proves nothing. Reproduce the send_alert defect."""
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "telegram_alert.py").write_text("def send_telegram(msg):\n    return True\n")
    (d / "caller.py").write_text("def go():\n    from telegram_alert import send_alert\n    send_alert('x')\n")
    bad = unresolved_alarm_imports(d)
    assert any(s == "send_alert" for _, _, _, s in bad), f"detector missed it: {bad}"


def test_positive_control_detector_catches_a_missing_module(tmp_path):
    """The telegram_bot case: the module itself does not exist anywhere."""
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "caller.py").write_text(
        "def go():\n    from telegram_bot_does_not_exist import notify\n    notify('x')\n"
    )
    bad = unresolved_alarm_imports(d)
    assert any("MODULE MISSING" in s for _, _, _, s in bad), f"detector missed it: {bad}"


def test_positive_control_detector_is_quiet_on_a_clean_tree(tmp_path):
    """And it must not cry wolf, or the gate gets disabled."""
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "telegram_alert.py").write_text("def send_telegram(msg):\n    return True\n")
    (d / "caller.py").write_text("def go():\n    from telegram_alert import send_telegram\n    send_telegram('x')\n")
    assert unresolved_alarm_imports(d) == []
