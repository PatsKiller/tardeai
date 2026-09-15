"""E-10 (2026-09-15): the daily actual-spend cap is checked every day from the report receipt."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "health_agent.py").read_text()
tree = ast.parse(SRC)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "spend_receipt_finding")
ns: dict = {"datetime": datetime}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "health_agent_spend", "exec"), ns)
check = ns["spend_receipt_finding"]
NOW = datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc)
OK = {"ran_at": "2026-09-15T11:05:03+00:00", "key": "daily:2026-09-14", "sent": True, "usd": 0.740255}


def test_the_2026_09_15_receipt_proves_the_policy():
    assert check(OK, NOW, 2.0) is None


def test_over_cap_is_named():
    assert "exceeded" in check(dict(OK, usd=2.31), NOW, 2.0)["reason"]


def test_a_stale_or_unsent_or_missing_receipt_is_not_proof():
    assert "ago" in check(dict(OK, ran_at="2026-09-13T11:05:03+00:00"), NOW, 2.0)["reason"]
    assert "not sent" in check(dict(OK, sent=False), NOW, 2.0)["reason"]
    assert check(None, NOW, 2.0)["reason"] == "no daily spend report receipt"


def test_registered():
    i = SRC.index("COLLECTORS = [")
    assert "collect_llm_spend_receipt," in SRC[i:i + 300]
