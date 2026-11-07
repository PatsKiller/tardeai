"""LQ-20261107-60 — wire_advisory_lessons: OCC option symbols must not overflow varchar(10), a SQL error must
count as a failure (not a silent zero), and an upsert must keep created_at. Fake DB only; no connection."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import wire_advisory_lessons as wal  # noqa: E402


def _row(trade_id, symbol, lane="grok"):
    return {"adv_id": trade_id, "lane": lane, "symbol": symbol, "recommendation": "LESSON: hold too long | GRADE: C",
            "trigger_reason": f"paper_postmortem:{trade_id}", "trade_id": trade_id, "strategy_id": "swing",
            "exit_reason": "target", "close_date": "2026-11-06", "pnl": 10.0, "dollar_risk": 20.0,
            "prop_origin": "automated", "prop_disc": ""}


def _fake(monkeypatch, rows, insert_result=lambda params: {"id": 1}):
    inserts = []

    def _db(sql, params=None, fetch="all"):
        if sql.lstrip().upper().startswith("SELECT"):
            return rows
        inserts.append((sql, params))
        return insert_result(params)

    monkeypatch.setattr(wal, "_db", _db)
    monkeypatch.setattr(wal.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "ok", ""))
    return inserts


def test_occ_contract_stores_underlying_and_keeps_contract_in_text():
    assert wal._store_symbol("RTX260918C00160000") == ("RTX", "RTX260918C00160000")
    assert wal._store_symbol("aapl") == ("AAPL", None)
    assert wal._store_symbol("BRK.B") == ("BRK.B", None)


def test_occ_row_is_written_with_fitting_symbol_and_contract_in_text(monkeypatch, capsys):
    inserts = _fake(monkeypatch, [_row(186, "RTX260918C00160000")])
    rc = wal._execute()
    assert rc == 0
    (_, params), = inserts
    assert params[1] == "RTX" and len(params[1]) <= wal.SYMBOL_MAX
    assert "(contract RTX260918C00160000)" in params[9]


def test_sql_error_is_counted_as_failure_not_silent_zero(monkeypatch, capsys):
    _fake(monkeypatch, [_row(1, "AAPL"), _row(2, "MSFT")], insert_result=lambda p: None if p[0] == 2 else {"id": 9})
    rc = wal._execute()
    out = capsys.readouterr().out
    assert rc == 1
    assert "wired 1 external lesson(s), 1 skipped" in out


def test_non_occ_symbol_too_long_is_skipped_and_counted(monkeypatch, capsys):
    inserts = _fake(monkeypatch, [_row(3, "WAYTOOLONGSYM")])
    rc = wal._execute()
    assert rc == 1 and inserts == []
    assert "symbol_too_long" in capsys.readouterr().out


def test_upsert_keeps_created_at():
    src = Path(wal.__file__).read_text(encoding="utf-8")
    assert "created_at=now()" not in src
