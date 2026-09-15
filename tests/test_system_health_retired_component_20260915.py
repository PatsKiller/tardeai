"""2026-09-15: the self-heal must not re-run a lane whose cron was disabled (cio_decision_engine)."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "system_health_agent.py").read_text()


def _components():
    tree = ast.parse(SRC)
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "MONITORED_COMPONENTS" for t in targets):
                return ast.literal_eval(node.value)
    raise AssertionError("MONITORED_COMPONENTS not found")


def test_the_decision_engine_is_retired_and_has_no_retry():
    comp = next(c for c in _components() if c["component"] == "cio_decision_engine")
    assert comp.get("retired") and not comp.get("retry_cmd")


def test_retired_components_are_skipped_before_any_check_or_retry():
    i = SRC.index("for comp in MONITORED_COMPONENTS:")
    head = SRC[i:i + 200]
    assert 'if comp.get("retired"):' in head and "continue" in head


def test_no_retry_cmd_targets_a_script_whose_cron_is_commented_out():
    assert not any("cio_decision_engine.py" in str(c.get("retry_cmd") or "") for c in _components())
