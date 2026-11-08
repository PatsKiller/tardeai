"""LQ-20261107-406: the sector engine must not date its states by a benchmark bar that is absent.

``compute_states`` intersects every sector's dates with SPY's, so SPY having no 2026-11-06 bar
did not raise anything — it silently made "today" 2026-11-05 for all 11 sectors, and the 17:25
run re-upserted 11-05 while ``/v3/defense/classic`` reported "STALE AS OF 2026-11-05". The
engine now fills the missing session bars before it computes, on its own connection, and only
where no bar exists. These tests pin the ordering and the fail-soft direction: a fill that
cannot run degrades to a printed line, never to a crashed engine or a silent one.
"""

from __future__ import annotations

import sys
import types
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import sector_momentum_engine as sme  # noqa: E402
import price_db_sync as pds  # noqa: E402  (the module the engine imports inside _ensure_session_closes)


class FakeConn:
    def __init__(self):
        self.committed = 0
        self.closed = False

    def cursor(self, *a, **k):
        return FakeCursor()

    def commit(self):
        self.committed += 1

    def close(self):
        self.closed = True


class FakeCursor:
    rowcount = 0

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def close(self):
        pass


# ── the fill itself ─────────────────────────────────────────────────────────


def test_the_fill_is_fail_soft_and_says_so(monkeypatch, capsys):
    def boom(**_kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(pds, "sync_session_closes", boom)

    res = sme._ensure_session_closes(apply=True)

    assert res["ok"] is False and "connection refused" in res["reason"]
    err = capsys.readouterr().err
    assert "session closes: skipped" in err and "RuntimeError" in err


def test_a_dry_run_asks_for_the_plan_and_never_for_the_write(monkeypatch, capsys):
    calls = []

    def fake(**_kw):
        calls.append(_kw)
        return {"ok": True, "session": "2026-11-06", "would_write": ["SPY", "XLK"],
                "has_bar": [], "outliers": [], "no_quote": [], "written": 0}

    monkeypatch.setattr(pds, "sync_session_closes", fake)

    sme._ensure_session_closes(apply=False)

    assert calls == [{"dry_run": True}]
    out = capsys.readouterr().out
    assert "would write 2" in out and "2026-11-06" in out


def test_an_applied_fill_reports_what_it_wrote(monkeypatch, capsys):
    calls = []

    def fake(**_kw):
        calls.append(_kw)
        return {"ok": True, "session": "2026-11-06", "would_write": ["SPY"],
                "has_bar": ["RSP"], "outliers": [], "no_quote": [], "written": 1}

    monkeypatch.setattr(pds, "sync_session_closes", fake)

    sme._ensure_session_closes(apply=True)

    assert calls == [{"dry_run": False}]
    assert "wrote 1" in capsys.readouterr().out


def test_a_session_that_cannot_be_resolved_is_reported_not_raised(monkeypatch, capsys):
    monkeypatch.setattr(pds, "sync_session_closes", lambda **_kw: {
        "ok": False, "session": None, "reason": "2026-11-07 is a weekend", "written": 0})

    res = sme._ensure_session_closes(apply=True)

    assert res["ok"] is False
    assert "no closed session" in capsys.readouterr().err


# ── wiring: the fill runs before the states are computed, and not at all for a dry run ──


def _run_main(monkeypatch, tmp_path, argv):
    import db_adapter

    order: list[str] = []
    conn = FakeConn()
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    monkeypatch.setattr(sme, "ROOT", tmp_path)
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sme, "_book_weights", lambda: {})
    monkeypatch.setattr(sme, "market_state_line", lambda *_a: "")
    monkeypatch.setattr(sme, "compute_market", lambda _cur: {"styles": [], "state_line": ""})
    monkeypatch.setattr(sme, "_ensure_session_closes",
                        lambda **_kw: order.append("fill") or {"ok": True})
    monkeypatch.setattr(sme, "compute_states",
                        lambda _cur, **_kw: order.append("states") or [])

    stub = types.ModuleType("industry_momentum")
    stub.decide_sector_notifications = lambda alerts, session=None: {"send": [], "suppressed": []}
    stub.emit_telegram = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "industry_momentum", stub)

    monkeypatch.setattr(sys, "argv", ["sector_momentum_engine.py", *argv])
    rc = sme.main()
    return rc, order


def test_the_fill_runs_before_compute_states(monkeypatch, tmp_path):
    rc, order = _run_main(monkeypatch, tmp_path, ["--dry-run"])
    assert rc == 0
    assert order == ["fill", "states"]


def test_the_engine_dry_run_passes_apply_false(monkeypatch, tmp_path):
    seen = []

    def spy(**kw):
        seen.append(kw)
        return {"ok": True}

    import db_adapter

    monkeypatch.setattr(db_adapter, "_get_conn", lambda: FakeConn())
    monkeypatch.setattr(sme, "ROOT", tmp_path)
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sme, "_book_weights", lambda: {})
    monkeypatch.setattr(sme, "market_state_line", lambda *_a: "")
    monkeypatch.setattr(sme, "compute_market", lambda _cur: {"styles": [], "state_line": ""})
    monkeypatch.setattr(sme, "compute_states", lambda _cur, **_kw: [])
    monkeypatch.setattr(sme, "_ensure_session_closes", spy)
    stub = types.ModuleType("industry_momentum")
    stub.decide_sector_notifications = lambda alerts, session=None: {"send": [], "suppressed": []}
    stub.emit_telegram = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "industry_momentum", stub)
    monkeypatch.setattr(sys, "argv", ["sector_momentum_engine.py", "--dry-run"])

    sme.main()

    assert seen == [{"apply": False}]
