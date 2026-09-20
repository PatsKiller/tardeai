"""Command /api/v2/command must carry snapshot_source (OperatorNumberCensus M4)."""
from __future__ import annotations

import ast
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "scripts" / "api_v2.py"


def _morning_command_return_keys() -> set[str]:
    tree = ast.parse(API.read_text(encoding="utf-8"), filename=str(API))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_morning_command":
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Dict):
                    keys: set[str] = set()
                    for k in stmt.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.add(k.value)
                    if keys:
                        return keys
    raise AssertionError("_morning_command return dict not found")


def test_morning_command_names_snapshot_source():
    keys = _morning_command_return_keys()
    assert "snapshot_source" in keys
    assert "portfolio" in keys  # sanity: still the command payload
