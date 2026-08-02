"""Data Broker indicator refresh unit checks (no network / no DB writes)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.data_broker import indicator_refresh as ir


def test_invalidate_indicator_snapshot(tmp_path, monkeypatch):
    snap = tmp_path / "indicator_snapshot.json"
    snap.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(ir, "SNAPSHOT_PATH", snap)
    assert ir.invalidate_indicator_snapshot() is True
    assert not snap.exists()


def test_refresh_indicators_invokes_producer_and_invalidates(tmp_path, monkeypatch):
    snap = tmp_path / "indicator_snapshot.json"
    snap.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ir, "SNAPSHOT_PATH", snap)
    monkeypatch.setattr(ir, "PROJECT_ROOT", tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "indicator_cache_refresh.py").write_text("# stub\n", encoding="utf-8")

    proc = MagicMock(returncode=0, stdout="Refresh complete: 3/3", stderr="")
    with patch("lib.data_broker.indicator_refresh.subprocess.run", return_value=proc) as run:
        out = ir.refresh_indicators(operator_desks=True, limit=10, sleep_ms=100, timeout_s=30)

    assert out["ok"] is True
    assert out["snapshot_invalidated"] is True
    assert not snap.exists()
    cmd = run.call_args.args[0]
    assert "indicator_cache_refresh.py" in " ".join(cmd)
    assert "--operator-desks" in cmd
    assert "reentry_decision_desk" in " ".join(out.get("consumers") or [])
