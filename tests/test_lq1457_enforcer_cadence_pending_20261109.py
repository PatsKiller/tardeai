"""LQ-1457: a missing upload record during the backup cadence is pending, not a failure.

ANCHOR: LQ1457_BACKUP_ENFORCER_CADENCE_PENDING_20261109

The 03:00 ET enforcer paged because the cadence had already uploaded the newest Drive
object and had not yet written the ledger row (that write is --verify-upload, at the
end of the run). Retention is unchanged: an unverified newest still refuses removal.
Hermetic: synthetic tmp dirs and a fake Drive. No gog, no database, no credentials.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import tests.test_n_plus_one_backups_20261031 as n1

REPO = Path(__file__).resolve().parents[1]


def _load_fresh():
    """Load the enforcer by path so this file does not depend on a prior import stub."""
    name = "backup_enforcer_lq1457"
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "backup_enforcer.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


be = _load_fresh()
# The shared fixtures loaded their own copy. Point them at this one so a patch is visible.
n1.be = be


def _cadence(*, active: bool, start: float, end: float | None) -> dict:
    return {"active": active, "started_at": start, "ended_at": end}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _host(tmp_path):
    """Same book as the N+1 host fixture, without calling that fixture."""
    backups = tmp_path / "db_backups"
    (backups / "archive").mkdir(parents=True)
    (backups / "archive" / "TRIPWIRE.txt").write_text("archived dumps\n")
    older_archive = n1._dump(backups / "archive" / "trade_ai_20300101_023000.sql.gz", 3 * n1.DAY, seed="a")
    older_top = n1._dump(backups / "trade_ai_20300102_023000.sql.gz", 2 * n1.DAY, seed="b")
    newest = n1._dump(backups / "trade_ai_20300103_023000.sql.gz", 5 * 3600, seed="c")
    return {"dir": backups, "older": [older_archive, older_top], "newest": newest}


def _run(pol, drive, tmp, *, cadence, now=n1.NOW, dry_run=True, notes=None):
    return be.run(pol, dry_run=dry_run, now=now, drive=drive, notify=notes or n1.Notes(),
                  alert_state_path=tmp / "alerts.json", cadence=cadence)


def test_parser_treats_an_active_unit_as_open_and_a_failed_show_as_inactive():
    text = (
        "ActiveState=active\n"
        "ExecMainStartTimestamp=Mon 2026-11-09 07:30:00 UTC\n"
        "ExecMainExitTimestamp=Mon 2026-11-09 06:12:00 UTC\n"
    )
    got = be.parse_cadence_show(text)
    assert got["active"] is True
    assert got["started_at"] == pytest.approx(datetime(2026, 11, 9, 7, 30, tzinfo=timezone.utc).timestamp())
    assert got["ended_at"] is None  # a previous exit does not close the open run
    assert be.read_cadence_run(show=lambda: (_ for _ in ()).throw(OSError("no unit"))) == {
        "active": False, "started_at": None, "ended_at": None,
    }


def test_active_cadence_drive_object_without_a_record_is_pending_and_removes_nothing(tmp_path):
    host = _host(tmp_path)
    pol, drive = n1._policy(tmp_path, host["dir"]), n1.FakeDrive()
    n1._drive_history(drive, ["20291201_031000", "20291208_031000", "20291215_031000"])
    fid = drive.put("db_backup_20300103_040000.sql.gz.gpg", b"uploaded this run, ledger not written yet")
    drive.objects[fid]["modifiedTime"] = _iso(n1.NOW - 600)  # inside the run, newest by name
    start = n1.NOW - 1800
    res = _run(pol, drive, tmp_path, cadence=_cadence(active=True, start=start, end=None), now=n1.NOW)
    assert drive.deleted == []
    assert res["drive_db"]["refused"] == "newest_drive_unverified:no_upload_record"
    assert res["drive_db"]["deleted"] == []
    assert res["local"]["removed"] == []
    assert all(p.exists() for p in host["older"]) and host["newest"].exists()
    drive_cond = res["conditions"][be.CONDITION_DRIVE]
    assert drive_cond["state"] == "pending_offsite"
    assert drive_cond["alertable"] is False
    assert res["alertable"] is False


def test_finished_run_with_no_record_still_fails(tmp_path):
    host = _host(tmp_path)
    pol, drive = n1._policy(tmp_path, host["dir"]), n1.FakeDrive()
    n1._drive_history(drive, ["20291201_031000", "20291208_031000", "20291215_031000"])
    fid = drive.put("db_backup_20300103_040000.sql.gz.gpg", b"uploaded, run ended, ledger never written")
    drive.objects[fid]["modifiedTime"] = _iso(n1.NOW - 600)
    start, end = n1.NOW - 1800, n1.NOW - 60
    res = _run(pol, drive, tmp_path, cadence=_cadence(active=False, start=start, end=end), now=n1.NOW)
    assert drive.deleted == []
    assert res["drive_db"]["refused"] == "newest_drive_unverified:no_upload_record"
    assert res["conditions"][be.CONDITION_DRIVE]["state"] == "newest_drive_unverified"
    assert res["conditions"][be.CONDITION_DRIVE]["alertable"] is True
    assert res["alertable"] is True


def test_record_newer_than_the_dump_inside_the_run_is_pending(tmp_path):
    host = _host(tmp_path)
    pol, drive = n1._policy(tmp_path, host["dir"]), n1.FakeDrive()
    n1._drive_history(drive, ["20291201_031000", "20291208_031000", "20291215_031000"])
    fid = drive.put("db_backup_20300103_040000.sql.gz.gpg", b"name does not match the in-run record")
    drive.objects[fid]["modifiedTime"] = _iso(n1.NOW - 900)
    ledger_path = Path(pol["verification"]["ledger_path"])
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    uploaded = _iso(n1.NOW - 120)  # newer than the object, inside [NOW-1800, NOW-60]
    ledger_path.write_text(json.dumps({
        "records": [{
            "uploaded_at": uploaded,
            "source": {"name": "trade_ai_other.sql.gz"},
            "drive": {"name": "db_backup_other.sql.gz.gpg", "size": 1, "md5": "abc"},
        }],
    }))
    start = n1.NOW - 1800
    end = n1.NOW - 60
    res = _run(pol, drive, tmp_path, cadence=_cadence(active=False, start=start, end=end), now=n1.NOW)
    assert res["drive_db"]["refused"] == "newest_drive_unverified:no_upload_record"
    assert res["drive_db"]["deleted"] == []
    assert drive.deleted == []
    assert res["conditions"][be.CONDITION_DRIVE]["state"] == "pending_offsite"
    assert res["conditions"][be.CONDITION_DRIVE]["alertable"] is False


def test_an_older_drive_object_still_fails_while_a_new_cadence_is_active(tmp_path):
    host = _host(tmp_path)
    pol, drive = n1._policy(tmp_path, host["dir"]), n1.FakeDrive()
    n1._drive_history(drive, ["20291201_031000", "20291208_031000"])
    fid = drive.put("db_backup_20300103_040000.sql.gz.gpg", b"newest name, but from before this run")
    drive.objects[fid]["modifiedTime"] = _iso(n1.NOW - 10 * n1.DAY)
    res = _run(
        pol, drive, tmp_path,
        cadence=_cadence(active=True, start=n1.NOW - 1800, end=None),
        now=n1.NOW,
    )
    assert res["conditions"][be.CONDITION_DRIVE]["state"] == "newest_drive_unverified"
    assert res["conditions"][be.CONDITION_DRIVE]["alertable"] is True
    assert drive.deleted == []


def test_local_dump_from_the_active_run_stays_pending_past_the_grace_and_keeps_older(tmp_path):
    backups = tmp_path / "db_backups"
    (backups / "archive").mkdir(parents=True)
    run_now = n1.NOW
    grace_s = 30 * 3600
    # _dump sets mtime to NOW - age_s. 31h is past the 30h grace and inside a run that started 40h ago.
    newest = n1._dump(backups / "trade_ai_20300105_023000.sql.gz", grace_s + 3600, seed="new")
    older = n1._dump(backups / "trade_ai_20300104_023000.sql.gz", 50 * 3600, seed="old")
    assert newest.stat().st_mtime == pytest.approx(run_now - (grace_s + 3600))
    pol, drive = n1._policy(tmp_path, backups), n1.FakeDrive()
    res = _run(
        pol, drive, tmp_path,
        cadence=_cadence(active=True, start=run_now - 40 * 3600, end=None),
        now=run_now,
    )
    assert res["local"]["refused"] == "no_upload_record"
    assert res["local"]["removed"] == []
    assert newest.exists() and older.exists()
    assert res["conditions"][be.CONDITION_HOST]["state"] == "pending_offsite"
    assert res["conditions"][be.CONDITION_HOST]["alertable"] is False
    bare = _run(pol, drive, tmp_path, cadence=None, now=run_now)
    assert bare["conditions"][be.CONDITION_HOST]["state"] == "no_upload_record"
    assert bare["conditions"][be.CONDITION_HOST]["alertable"] is True
    assert newest.exists() and older.exists()


def test_a_verified_newest_still_removes_older_dumps_when_the_cadence_is_active(tmp_path):
    host = _host(tmp_path)
    pol, drive = n1._policy(tmp_path, host["dir"]), n1.FakeDrive()
    up = n1._offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    assert up["ok"] is True
    res = _run(
        pol, drive, tmp_path,
        cadence=_cadence(active=True, start=n1.NOW - 1800, end=None),
        dry_run=False,
    )
    assert res["local"]["verification"]["verified"] is True
    assert all(not p.exists() for p in host["older"])
    assert host["newest"].exists()
    assert res["conditions"][be.CONDITION_HOST]["state"] == "ok"


def test_dry_run_cli_exits_zero_while_the_cadence_is_active_and_one_when_the_record_is_missing(tmp_path, monkeypatch, capsys):
    host = _host(tmp_path)
    pol = n1._policy(tmp_path, host["dir"])
    seed = n1.FakeDrive()
    n1._drive_history(seed, ["20291201_031000", "20291208_031000", "20291215_031000"])
    fid = seed.put("db_backup_20300103_040000.sql.gz.gpg", b"cli object")
    seed.objects[fid]["modifiedTime"] = _iso(n1.NOW - 600)

    class Factory(n1.FakeDrive):
        def __init__(self, *_a, **_k):
            self.__dict__.update(seed.__dict__)

    monkeypatch.setattr(be, "GogDrive", Factory)
    monkeypatch.setattr(be, "_load_policy", lambda: pol)
    monkeypatch.setattr(be, "read_cadence_run", lambda: _cadence(active=True, start=n1.NOW - 1800, end=None))
    monkeypatch.setattr(be.time, "time", lambda: n1.NOW)
    assert be.main(["--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["alertable"] is False
    assert out["conditions"][be.CONDITION_DRIVE]["state"] == "pending_offsite"
    assert not Path(pol["verification"]["receipt_path"]).exists()
    assert seed.deleted == []

    monkeypatch.setattr(be, "read_cadence_run", lambda: {"active": False, "started_at": None, "ended_at": None})
    assert be.main(["--dry-run"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["alertable"] is True
    assert out["conditions"][be.CONDITION_DRIVE]["state"] == "newest_drive_unverified"
    assert not Path(pol["verification"]["receipt_path"]).exists()
    assert seed.deleted == []
