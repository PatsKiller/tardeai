"""E-03 (2026-09-15): /api/v2/health says the verdict, not just a transport 200."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "api_v2.py").read_text()


def _headline():
    tree = ast.parse(SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "health_headline")
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "api_v2_health_headline", "exec"), ns)
    return ns["health_headline"]


def test_unhealthy_snapshot_is_named_unhealthy_with_its_score_and_counts():
    h = _headline()({"status": "unhealthy", "overall_score": 64, "counts": {"critical": 15, "warning": 20}})
    assert h == {"healthy": False, "headline": "UNHEALTHY 64/100 — 15 critical, 20 warning"}


def test_only_a_healthy_status_is_healthy():
    assert _headline()({"status": "healthy", "overall_score": 92, "counts": {}})["healthy"] is True
    assert _headline()({})["headline"].startswith("UNKNOWN ?/100")


def test_the_dashboard_attaches_the_headline():
    body = SRC[SRC.index("def _health_agent_dashboard():"):]
    body = body[: body.index("\ndef ", 10)]
    assert "snap.update(health_headline(snap))" in body
