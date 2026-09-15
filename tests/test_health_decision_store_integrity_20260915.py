"""E-04 / E-05 (2026-09-15): the verdict store and proposal expiry are watched, not audited once."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "health_agent.py").read_text()


def _fns(*names):
    tree = ast.parse(SRC)
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    ns: dict = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), "health_agent_pure", "exec"), ns)
    return [ns[n] for n in names]


verdict_store_finding, expire_on_arrival_finding = _fns("verdict_store_finding", "expire_on_arrival_finding")
IN_ZONE = {"symbol": "AVAV", "entry_low": 149.0, "entry_high": 155.0, "price": 153.29}
ABOVE = {"symbol": "LMT", "entry_low": 400.0, "entry_high": 410.0, "price": 450.0}


def test_long_empty_run_with_a_name_in_zone_fires():
    f = verdict_store_finding([{"verdicts": []}] * 120, [IN_ZONE, ABOVE])
    assert f == {"empty_run": 120, "in_zone": ["AVAV"]}


def test_empty_is_fine_when_nothing_is_in_zone_or_a_verdict_is_recent():
    assert verdict_store_finding([{"verdicts": []}] * 500, [ABOVE]) is None
    assert verdict_store_finding([{"verdicts": []}] * 50 + [{"verdicts": [{"symbol": "AVAV"}]}] + [{"verdicts": []}] * 20,
                                 [IN_ZONE]) is None


def test_expire_on_arrival_share():
    assert expire_on_arrival_finding(1156, 1075) == {"created": 1156, "expired_within_1h": 1075, "share": 0.93}
    assert expire_on_arrival_finding(40, 5) is None
    assert expire_on_arrival_finding(4, 4) is None


def test_the_collector_is_registered():
    i = SRC.index("COLLECTORS = [")
    assert "collect_decision_store_integrity," in SRC[i:i + 400]
