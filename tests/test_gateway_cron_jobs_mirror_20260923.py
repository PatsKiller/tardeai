"""Stage 4: gateway cron jobs.json atomic flush + bak/migrated recovery.

Hermetic — uses tmp_path only. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import gateway_cron_jobs_mirror as gcm  # noqa: E402

COVERS = [
    "scripts/lib/gateway_cron_jobs_mirror.py",
    "scripts/recover_gateway_cron_jobs_mirror.py",
]


def test_atomic_flush_creates_jobs_json(tmp_path: Path) -> None:
    payload = {"version": 1, "jobs": [{"id": "a9c337e0-test", "name": "remind"}]}
    written = gcm.atomic_write_jobs_json(payload, cron_dir=tmp_path)
    assert written == tmp_path / "jobs.json"
    assert written.is_file()
    loaded = json.loads(written.read_text(encoding="utf-8"))
    assert loaded["jobs"][0]["id"] == "a9c337e0-test"
    # No leftover temps
    assert not list(tmp_path.glob(".jobs.json.*.tmp"))


def test_flush_jobs_mirror_dry_run_writes_nothing(tmp_path: Path) -> None:
    out = gcm.flush_jobs_mirror(
        [{"id": "x"}],
        cron_dir=tmp_path,
        dry_run=True,
    )
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert not (tmp_path / "jobs.json").exists()


def test_recover_from_migrated_when_primary_missing(tmp_path: Path) -> None:
    migrated = tmp_path / "jobs.json.migrated"
    migrated.write_text(
        json.dumps({"version": 1, "jobs": [{"id": "from-migrated"}]}),
        encoding="utf-8",
    )
    report = gcm.recover_jobs_json_if_missing(cron_dir=tmp_path, dry_run=False)
    assert report.ok is True
    assert report.action == "recovered"
    assert report.recovered_from == str(migrated)
    primary = tmp_path / "jobs.json"
    assert primary.is_file()
    assert json.loads(primary.read_text())["jobs"][0]["id"] == "from-migrated"


def test_recover_prefers_migrated_when_content_matches_bak(tmp_path: Path) -> None:
    """Same content: prefer .migrated path as recovered_from. Differing content refuses (§0.5)."""
    payload = {"version": 1, "jobs": [{"id": "same"}]}
    (tmp_path / "jobs.json.bak").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "jobs.json.migrated").write_text(json.dumps(payload), encoding="utf-8")
    report = gcm.recover_jobs_json_if_missing(cron_dir=tmp_path)
    assert report.ok is True
    assert "migrated" in (report.recovered_from or "")
    assert json.loads((tmp_path / "jobs.json").read_text())["jobs"][0]["id"] == "same"


def test_divergent_candidates_refuse_without_operator_pick(tmp_path: Path) -> None:
    (tmp_path / "jobs.json.migrated").write_text(
        json.dumps({"version": 1, "jobs": [{"id": "A"}]}),
        encoding="utf-8",
    )
    (tmp_path / "jobs.json.bak").write_text(
        json.dumps({"version": 1, "jobs": [{"id": "B"}]}),
        encoding="utf-8",
    )
    report = gcm.recover_jobs_json_if_missing(cron_dir=tmp_path)
    assert report.ok is False
    assert report.divergent is True
    assert report.action == "divergent_candidates"
    assert not (tmp_path / "jobs.json").exists()


def test_operator_pick_resolves_divergence(tmp_path: Path) -> None:
    bak = tmp_path / "jobs.json.bak"
    bak.write_text(json.dumps({"version": 1, "jobs": [{"id": "B"}]}), encoding="utf-8")
    (tmp_path / "jobs.json.migrated").write_text(
        json.dumps({"version": 1, "jobs": [{"id": "A"}]}),
        encoding="utf-8",
    )
    report = gcm.recover_jobs_json_if_missing(
        cron_dir=tmp_path,
        operator_pick=str(bak),
    )
    assert report.ok is True
    assert json.loads((tmp_path / "jobs.json").read_text())["jobs"][0]["id"] == "B"


def test_recover_accepts_migrated_dot_n(tmp_path: Path) -> None:
    """Doctor archives as jobs.json.migrated.2 — must be a recovery candidate."""
    src = tmp_path / "jobs.json.migrated.2"
    src.write_text(
        json.dumps({"version": 1, "jobs": [{"id": "from-migrated-2"}]}),
        encoding="utf-8",
    )
    report = gcm.recover_jobs_json_if_missing(
        cron_dir=tmp_path,
        operator_pick=str(src),
    )
    assert report.ok is True
    assert report.action == "recovered"
    assert json.loads((tmp_path / "jobs.json").read_text())["jobs"][0]["id"] == "from-migrated-2"

    (tmp_path / "jobs.json").write_text(
        json.dumps({"version": 1, "jobs": []}),
        encoding="utf-8",
    )
    report = gcm.recover_jobs_json_if_missing(cron_dir=tmp_path)
    assert report.action == "already_present"
    assert report.ok is True
