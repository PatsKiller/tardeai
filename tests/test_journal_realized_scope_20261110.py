"""The realized tile's priced total does not absorb sells with no cost basis.

Synthetic figures only. Nothing here reads a ledger, a broker, or the overview route.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.journal_realized_scope import realized_scope  # noqa: E402


def test_unknown_basis_proceeds_stay_out_of_the_priced_total():
    out = realized_scope(priced=40, unpriced_count=3, unpriced_proceeds=15.5, unpriced_known=True)
    assert out == {"priced_realized": 40.0, "unpriced_count": 3, "unpriced_proceeds": 15.5}


def test_a_failed_unpriced_read_is_not_reported_as_zero():
    out = realized_scope(priced=40, unpriced_count=0, unpriced_proceeds=0, unpriced_known=False)
    assert out["priced_realized"] == 40.0
    assert out["unpriced_count"] is None
    assert out["unpriced_proceeds"] is None


def test_a_measured_zero_stays_zero():
    out = realized_scope(priced=0, unpriced_count=0, unpriced_proceeds=0, unpriced_known=True)
    assert out == {"priced_realized": 0.0, "unpriced_count": 0, "unpriced_proceeds": 0.0}


def test_an_unpriced_priced_total_stays_unknown():
    out = realized_scope(priced=None, unpriced_count=1, unpriced_proceeds=8, unpriced_known=True)
    assert out["priced_realized"] is None
    assert out["unpriced_proceeds"] == 8.0


def test_overview_journal_publishes_the_scope_from_the_helper():
    """The overview journal dict carries the three fields, taken from the helper, not literals."""
    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        wanted = {"priced_realized", "unpriced_count", "unpriced_proceeds", "realized_pnl"}
        if not wanted <= set(keys):
            continue
        found = True
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or key.value not in wanted - {"realized_pnl"}:
                continue
            assert isinstance(value, ast.Subscript), key.value
            assert isinstance(value.value, ast.Name) and value.value.id == "_realized_scope"
    assert found, "overview journal does not publish the realized-scope fields"


def _tsx_code(name: str) -> str:
    raw = (ROOT / "apps" / "command-center-v3" / "src" / name).read_text(encoding="utf-8")
    return "\n".join(line for line in raw.splitlines() if not line.strip().startswith("//"))


def test_the_realized_tile_states_scope_even_when_quiet_provenance_is_off():
    code = _tsx_code("components/MetricStrip.tsx")
    assert "realizedScopeNote(" in code
    assert "asOfNote: [realizedScopeText," in code
    home = _tsx_code("components/decision/HomeDecision.tsx")
    assert "realizedScopeNote(" in home
