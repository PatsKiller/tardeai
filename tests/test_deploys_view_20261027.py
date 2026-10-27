"""Deploys status (2026-10-27): GET /api/v2/ops/deploys = latest DeployOnMainReceipt@v1 + the deploy STOP latch.

Replaces the retired release-train summary on Home (operator directive 2026-10-27). Pinned here: the latest receipt is
read from <TRADEAI_STATE_ROOT>/data/runtime/deploy_on_main/latest.json; a missing or malformed receipt is null with an
error (never a fabricated ok); recent receipts are newest first and skip latest.json; the STOP read-back is
deploy_stop.status(); only GET is answered. Hermetic: tmp state root and STOP dir; no git, systemd or network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import deploys_view as DV  # noqa: E402

RECEIPT = {"schema": "DeployOnMainReceipt@v1", "as_of": "2031-03-10T14:00:00Z", "path": "poller",
           "outcome": "verified", "main_sha": "a" * 40, "current_sha_before": "b" * 9, "current_sha_after": "a" * 9,
           "reason": "", "detail": {}}


def _env(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    stop_dir = tmp_path / "release_window"
    stop_dir.mkdir()
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(stop_dir))
    return DV.receipts_dir()


def test_no_receipt_is_null_with_reason_never_ok(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    out = DV.build()
    assert out["schema"] == "DeploysStatus@v1"
    assert out["latest"] is None and "no receipt yet" in out["latest_error"]
    assert out["recent"] == []
    assert out["stop"]["latch"]["status"] == "ABSENT" and out["stop_effective"] is False


def test_latest_and_recent_newest_first(tmp_path, monkeypatch):
    rdir = _env(tmp_path, monkeypatch)
    rdir.mkdir(parents=True)
    for i, outcome in enumerate(("noop", "deploy_failed", "verified")):
        row = {**RECEIPT, "outcome": outcome, "as_of": f"2031-03-10T14:0{i}:00Z"}
        (rdir / f"20310310T140{i}00Z_poller_{outcome}.json").write_text(json.dumps(row), encoding="utf-8")
    (rdir / "latest.json").write_text(json.dumps(RECEIPT), encoding="utf-8")
    (rdir / "20310310T150000Z_poller_garbage.json").write_text("{not json", encoding="utf-8")
    out = DV.build()
    assert out["latest"]["outcome"] == "verified" and out["latest_error"] is None
    assert [r["outcome"] for r in out["recent"]] == ["verified", "deploy_failed", "noop"]


def test_wrong_schema_latest_is_unreadable(tmp_path, monkeypatch):
    rdir = _env(tmp_path, monkeypatch)
    rdir.mkdir(parents=True)
    (rdir / "latest.json").write_text(json.dumps({"schema": "Other@v1"}), encoding="utf-8")
    out = DV.build()
    assert out["latest"] is None and "unreadable" in out["latest_error"]


def test_stop_latch_set_is_effective(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    (tmp_path / "release_window" / "STOP.json").write_text(json.dumps({"reason": "hold"}), encoding="utf-8")
    assert DV.build()["stop_effective"] is True


def test_handle_routes_get_only(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    assert DV.handle("/api/v2/ops/other", "GET") is None
    st, body = DV.handle("/api/v2/ops/deploys/", "GET")
    assert st == 200 and body["ok"] is True and body["data"]["schema"] == "DeploysStatus@v1"
    assert DV.handle("/api/v2/ops/deploys", "POST")[0] == 405


def test_view_is_read_only_and_names_no_train():
    src = (ROOT / "scripts" / "lib" / "deploys_view.py").read_text(encoding="utf-8")
    for banned in ("write_text", "subprocess", "unlink", "release_train_"):
        assert banned not in src
