"""LQ-20261113-3077 (A09): /api/v2/ops/deploys names the SERVED release (its own BUILD_SHA + when CURRENT was flipped to it),
separately from the poller's last receipt. Hermetic: a tmp release layout; no git, systemd, network or credential."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import deploys_view as DV  # noqa: E402

SHA = "7b0cc18d05cb892e8da50f8acadcfa3e340ebdd9"


def _layout(tmp_path: Path, *, sha=SHA, link=True, point_at_other=False) -> Path:
    base = tmp_path / "portfolio-server"
    rel = base / "7b0cc18d0-live-integration-20261113-175348"
    rel.mkdir(parents=True)
    if sha is not None:
        (rel / "BUILD_SHA").write_text(sha + "\n")
    (rel / "BUILD_STAMPED_AT").write_text("2026-11-13T22:56:46Z\n")
    if link:
        other = base / "older-release"
        other.mkdir()
        (base / "CURRENT").symlink_to(other if point_at_other else rel)
        os.utime(base / "CURRENT", (1_794_000_000, 1_794_000_000), follow_symlinks=False)
    return rel


def test_served_release_reports_its_own_build_sha_and_activation(tmp_path):
    out = DV.served_release(_layout(tmp_path))
    assert out["sha"] == SHA and out["error"] is None
    assert out["is_current"] is True
    assert out["stamped_at"] == "2026-11-13T22:56:46Z"
    assert out["activated_at"] == "2026-11-06T21:20:00Z"   # the CURRENT symlink's own mtime, not the release dir's
    assert out["release"].startswith("7b0cc18d0")


def test_a_missing_build_sha_is_none_with_a_reason_never_a_guess(tmp_path):
    out = DV.served_release(_layout(tmp_path, sha=None))
    assert out["sha"] is None and "BUILD_SHA" in out["error"]


def test_missing_current_link_is_named_and_not_inferred(tmp_path):
    out = DV.served_release(_layout(tmp_path, link=False))
    assert out["sha"] == SHA and out["activated_at"] is None and out["is_current"] is None
    assert "CURRENT" in out["error"]


def test_a_release_that_is_not_what_current_points_at_is_flagged(tmp_path):
    assert DV.served_release(_layout(tmp_path, point_at_other=True))["is_current"] is False


def test_build_carries_served_beside_the_poller_receipt_and_never_merges_them(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    stop = tmp_path / "rw"
    stop.mkdir()
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(stop))
    rdir = DV.receipts_dir()
    rdir.mkdir(parents=True)
    (rdir / "latest.json").write_text('{"schema": "DeployOnMainReceipt@v1", "outcome": "deploy_failed", "main_sha": "9c21372aa5ef", "as_of": "2026-11-11T22:30:03Z"}')
    out = DV.build(release_root=_layout(tmp_path))
    assert out["served"]["sha"] == SHA
    assert out["latest"]["main_sha"] == "9c21372aa5ef" and out["latest"]["outcome"] == "deploy_failed"
    assert out["served"]["sha"] != out["latest"]["main_sha"]


def test_default_root_is_the_release_this_module_was_loaded_from():
    out = DV.served_release()
    assert out["release"] == ROOT.name


def test_the_panel_delegates_to_the_rendered_rows_component():
    # The rows themselves are pinned by a render test (src/components/home/DeploysServed.test.mjs); here only the wiring.
    src = (ROOT / "apps/command-center-v3/src/components/home/DeploysPanel.tsx").read_text()
    assert "<DeploysSummaryRows s={s} />" in src


def test_the_route_envelope_carries_served(tmp_path, monkeypatch):
    # review 3080 R3: GET /api/v2/ops/deploys itself, not only build()
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    stop = tmp_path / "rw"
    stop.mkdir()
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(stop))
    status, body = DV.handle("/api/v2/ops/deploys", "GET")
    assert status == 200 and body["ok"] is True
    served = body["data"]["served"]
    assert set(served) == {"sha", "release", "stamped_at", "activated_at", "is_current", "error"}
    assert served["release"] == ROOT.name
    assert DV.handle("/api/v2/ops/deploys", "POST")[0] == 405
