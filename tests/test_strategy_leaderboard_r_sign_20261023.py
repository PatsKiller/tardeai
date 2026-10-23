"""Strategy leaderboard flags Live R when stored r_multiple disagrees in sign with pnl.

Site validation 2026-10-22 (served f7c1e96cb): /v3/strategy showed reit_income at Live R -1.93 with
one closed trade at +$298.86 (100% win), and pullback_macd_reversal at +1.73R with -$1,806 total.
The leaderboard's Live R is avg(paper_trades.r_multiple); a closed trade can keep a stale
r_multiple. The endpoint now counts sign conflicts and marks avg_r_suspect.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _stub(monkeypatch, live_rows):
    import api_v2

    def fake(sql, *a, **k):
        if "FROM paper_trades" in sql and "GROUP BY strategy_id" in sql:
            assert "r_sign_conflicts" in sql
            return live_rows
        return None if k.get("fetch") == "one" else []

    monkeypatch.setattr(api_v2, "_db_query", fake)
    return api_v2


def _row(sid, n, wins, total, avg_r, conflicts):
    return {"strategy_id": sid, "n": n, "wins": wins, "win_rate": round(100 * wins / n, 1), "avg_pnl": total / n,
            "total_pnl": total, "avg_pct": 1.0, "avg_r": avg_r, "r_sign_conflicts": conflicts}


def test_conflicting_live_r_is_flagged(monkeypatch):
    api = _stub(monkeypatch, [_row("reit_income", 1, 1, 298.86, -1.93, 1), _row("fib", 2, 2, 482.8, 2.03, 0)])
    out = api._strategy_leaderboard()
    rows = {r["strategy_id"]: r for r in (out.get("leaderboard") or out.get("data", {}).get("leaderboard") or [])}
    assert rows["reit_income"]["live"]["avg_r_suspect"] is True
    assert rows["reit_income"]["live"]["r_sign_conflicts"] == 1
    assert rows["fib"]["live"]["avg_r_suspect"] is False


def test_rows_without_the_new_column_do_not_break(monkeypatch):
    r = _row("old", 3, 2, 10.0, 0.5, 0)
    r.pop("r_sign_conflicts")
    api = _stub(monkeypatch, [r])
    out = api._strategy_leaderboard()
    rows = out.get("leaderboard") or out.get("data", {}).get("leaderboard") or []
    assert rows and rows[0]["live"]["avg_r_suspect"] is False
