"""An empty Fidelity stop registry means every GTC was cancelled.

2026-10-03: 7 closed positions (ARKX, DXCM, SCHG, CSCO, DIVI, QCOM, ANET) were
removed from config/fidelity_rollover_stops.json. Two paths would have kept them:
an empty list fell back to a baked-in stop list, and sync_stops returned early on
no rows without retiring anything. Records only: nothing here talks to a broker.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import fidelity_stop_sync as fss  # noqa: E402


def _config(tmp_path: Path, monkeypatch, stops):
    path = tmp_path / "fidelity_rollover_stops.json"
    if stops is not None:
        path.write_text(json.dumps({"account": "fidelity_rollover_ira", "stops": stops}), encoding="utf-8")
    monkeypatch.setattr(fss, "FIDELITY_STOPS_CONFIG", path)
    return path


def test_empty_registry_yields_no_stops_and_no_fallback(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, [])
    assert fss.default_fidelity_rollover_stops() == []
    assert fss.configured_stops_account() == "fidelity_rollover_ira"


def test_missing_registry_still_uses_the_fallback(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, None)
    assert fss.default_fidelity_rollover_stops()  # fallback list is non-empty
    assert fss.configured_stops_account() is None


class _Cur:
    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return []


class _Conn:
    committed = False

    def cursor(self):
        return _Cur()

    def commit(self):
        self.committed = True


def _stub_db(monkeypatch):
    conn = _Conn()
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    monkeypatch.setattr(fss, "record_sync_run", lambda report: None)
    return conn


def test_empty_registry_retires_the_accounts_stops(monkeypatch):
    conn = _stub_db(monkeypatch)
    calls = []
    monkeypatch.setattr(fss, "deactivate_stale_stops",
                        lambda cur, acct, syms: calls.append((acct, set(syms))) or ["ARKX", "QCOM"])
    report = fss.sync_stops([], apply=True, retire_account="fidelity_rollover_ira")
    assert calls == [("fidelity_rollover_ira", set())]
    assert report["retired"] == ["ARKX", "QCOM"]
    assert conn.committed


def test_empty_rows_without_an_account_still_do_nothing(monkeypatch):
    _stub_db(monkeypatch)
    monkeypatch.setattr(fss, "deactivate_stale_stops", lambda *a: (_ for _ in ()).throw(AssertionError("retired")))
    assert fss.sync_stops([], apply=True)["note"] == "no rows"
    assert fss.sync_stops([], apply=False, retire_account="fidelity_rollover_ira")["note"] == "no rows"


def test_live_registry_no_longer_lists_the_closed_positions():
    data = json.loads((ROOT / "config" / "fidelity_rollover_stops.json").read_text())
    closed = {"ARKX", "DXCM", "SCHG", "CSCO", "DIVI", "QCOM", "ANET"}
    assert not closed & {str(s.get("symbol")).upper() for s in data.get("stops") or []}
