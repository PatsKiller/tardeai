import sys
from pathlib import Path


sys.path.insert(0, str(Path("scripts").resolve()))

from sector_momentum_engine_v4 import breadth_v4  # noqa: E402


class Cursor:
    def __init__(self, members, rows):
        self.members = members
        self.rows = rows
        self.calls = []
        self.connection = self

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.members if len(self.calls) == 1 else self.rows

    def rollback(self):
        raise AssertionError("rollback should not run in successful tests")


def test_membership_query_is_uncapped_and_deterministic():
    members = [(f"S{i}",) for i in range(10)]
    rows = [(f"S{i}", 110, 100, 20) for i in range(8)]
    cur = Cursor(members, rows)

    pct, covered, total, quality = breadth_v4(cur, "Technology")

    assert "LIMIT" not in cur.calls[0][0].upper()
    assert "ORDER BY upper(m.symbol)" in cur.calls[0][0]
    assert pct == 100
    assert covered == 8
    assert total == 10
    assert quality == "ok"


def test_breadth_is_withheld_when_coverage_ratio_is_too_low():
    members = [(f"S{i}",) for i in range(20)]
    rows = [(f"S{i}", 110, 100, 20) for i in range(10)]
    pct, covered, total, quality = breadth_v4(Cursor(members, rows), "Technology")

    assert pct is None
    assert covered == 10
    assert total == 20
    assert quality == "insufficient_membership_coverage"


def test_breadth_uses_exact_twenty_session_rows_only():
    source = Path("scripts/sector_momentum_engine_v4.py").read_text()
    normalized = " ".join(source.split())
    assert "WHERE session_n = 20" in source
    assert "covered screener-membership measure" in normalized
    assert "not official ETF constituent breadth" in normalized
