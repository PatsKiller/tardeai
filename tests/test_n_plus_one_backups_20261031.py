"""Backups: one dump on the host, N+1 on Drive, verified before anything is removed.

AGENTS.md §0 rule 6 (d), §24.15; DSN-20261030-workspace-lifecycle P4-T1 / P4-T2.

Hermetic: synthetic tmp dirs and a FAKE Drive client only. No real Drive, no gog, no credentials.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NOW = 1_900_000_000.0
DAY = 86_400


def _load():
    spec = importlib.util.spec_from_file_location("backup_enforcer_n1", REPO / "scripts" / "backup_enforcer.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


be = _load()


class FakeDrive:
    """In-memory stand-in for GogDrive: objects are {id: {"name", "data"}}."""

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.md5_calls = 0
        self.list_error: Exception | None = None
        self.complete = True
        self._n = 0

    def put(self, name: str, data: bytes) -> str:
        self._n += 1
        fid = f"fake{self._n:04d}"
        self.objects[fid] = {"name": name, "data": data, "modifiedTime": f"2030-01-01T00:00:{self._n:02d}Z"}
        return fid

    def list(self, prefix: str) -> dict:
        if self.list_error is not None:
            raise self.list_error
        files = [{"id": i, "name": o["name"], "size": len(o["data"]), "modifiedTime": o["modifiedTime"]}
                 for i, o in self.objects.items() if o["name"].startswith(prefix + "_")]
        return {"files": files, "complete": self.complete}

    def md5(self, file_id: str) -> tuple[str, int]:
        self.md5_calls += 1
        data = self.objects[file_id]["data"]
        return hashlib.md5(data).hexdigest(), len(data)  # noqa: S324

    def delete(self, file_id: str) -> None:
        self.deleted.append(self.objects.pop(file_id)["name"])


class Notes:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def __call__(self, text: str, priority: str) -> str:
        self.sent.append((text, priority))
        return "accepted"


def _policy(tmp: Path, backups: Path, **over) -> dict:
    state = tmp / "state"
    pol = {
        "local_pg": {"dir": str(backups), "pattern": "trade_ai_*.sql.gz", "keep_on_host": 1, "max_count": 1,
                     "min_bytes": 20, "max_total_bytes": 10**9, "skip_younger_than_s": 7200},
        "drive_db": {"folder_id": "FOLDER", "prefix": "db_backup", "keep_n": 1, "prune_enabled": True,
                     "account": "nobody@example.invalid", "gog_bin": str(tmp / "no-gog"),
                     "keyring_password_file": str(tmp / "no-keyring"), "list_max": 100, "command_timeout_s": 5},
        "verification": {"gzip_timeout_s": 60, "drive_md5_timeout_s": 60, "drive_unreachable_grace_hours": 6,
                         "newest_unverified_grace_hours": 30, "alert_realert_minutes": 360,
                         "ledger_path": str(state / "ledger.json"), "ledger_max_records": 30,
                         "cache_path": str(state / "cache.json"), "cache_max_entries": 50,
                         "receipt_path": str(state / "receipt.json"),
                         "removals_log_path": str(state / "removals.jsonl"),
                         "lock_path": str(state / "enforcer.lock"), "fifo_dir": str(state / "fifo")},
    }
    for section, vals in over.items():
        pol[section].update(vals)
    return pol


def _dump(path: Path, age_s: float, *, seed: str, corrupt: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = gzip.compress((f"-- fixture dump {seed}\n" * 50).encode())
    if corrupt:
        payload = payload[:-12] + b"\x00" * 12
    path.write_bytes(payload)
    os.utime(path, (NOW - age_s, NOW - age_s))
    return path


def _offsite(pol: dict, drive: FakeDrive, dump: Path, tmp: Path, *, stamp: str, notes: Notes | None = None,
             alert_state: Path | None = None) -> dict:
    """What backup_secrets_state.sh db does: copy, 'encrypt', upload, then --verify-upload."""
    work = tmp / f"work_{stamp}"
    work.mkdir()
    plain = work / f"db_backup_{stamp}.sql.gz"
    shutil.copy2(dump, plain)
    enc = work / f"db_backup_{stamp}.sql.gz.gpg"
    enc.write_bytes(b"CIPHERTEXT:" + hashlib.sha256(plain.read_bytes() + stamp.encode()).digest() * 8)
    drive.put(enc.name, enc.read_bytes())
    return be.verify_upload(pol, source=dump, plaintext=plain, encrypted=enc, drive=drive,
                            notify=notes or Notes(), alert_state_path=alert_state or tmp / "alerts.json")


def _run(pol, drive, tmp, *, dry_run=False, notes=None, now=NOW):
    return be.run(pol, dry_run=dry_run, now=now, drive=drive, notify=notes or Notes(),
                  alert_state_path=tmp / "alerts.json")


@pytest.fixture()
def host(tmp_path):
    backups = tmp_path / "db_backups"
    (backups / "archive").mkdir(parents=True)
    (backups / "archive" / "TRIPWIRE.txt").write_text("archived dumps\n")
    older_archive = _dump(backups / "archive" / "trade_ai_20300101_023000.sql.gz", 3 * DAY, seed="a")
    older_top = _dump(backups / "trade_ai_20300102_023000.sql.gz", 2 * DAY, seed="b")
    newest = _dump(backups / "trade_ai_20300103_023000.sql.gz", 5 * 3600, seed="c")
    return {"dir": backups, "older": [older_archive, older_top], "newest": newest}


# ── host ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_removes_older_host_dumps_only_after_gzip_and_drive_verify(tmp_path, host):
    pol, drive, notes = _policy(tmp_path, host["dir"]), FakeDrive(), Notes()
    up = _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    assert up["ok"] is True and up["reason"] == "verified"
    res = _run(pol, drive, tmp_path, notes=notes)
    assert res["local"]["verification"]["verified"] is True
    assert res["local"]["verification"]["gzip"]["result"] == "ok"
    assert all(not p.exists() for p in host["older"])
    assert host["newest"].exists()
    assert (host["dir"] / "archive" / "TRIPWIRE.txt").is_file()
    assert res["local"]["remaining_full"] == 1 and res["ok"] is True
    receipt = json.loads(Path(pol["verification"]["receipt_path"]).read_text())
    assert {r["path"] for r in receipt["local"]["removed"]} == {str(p) for p in host["older"]}
    log = Path(pol["verification"]["removals_log_path"]).read_text().splitlines()
    assert len(log) == 2 and all(json.loads(line)["successor"] == str(host["newest"]) for line in log)
    assert notes.sent == []


def test_dry_run_reports_would_remove_and_writes_nothing(tmp_path, host):
    pol, drive = _policy(tmp_path, host["dir"]), FakeDrive()
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    cache = Path(pol["verification"]["cache_path"])
    before = cache.read_text()
    res = _run(pol, drive, tmp_path, dry_run=True)
    assert all(p.exists() for p in host["older"])
    assert {r["action"] for r in res["local"]["removed"]} == {"would_remove"}
    assert not Path(pol["verification"]["receipt_path"]).exists()
    assert cache.read_text() == before


@pytest.mark.parametrize("break_it, reason", [
    ("md5", "drive_md5_mismatch"),
    ("missing", "drive_object_missing"),
    ("size", "drive_size_mismatch"),
])
def test_keeps_older_dumps_when_drive_copy_is_wrong_or_missing(tmp_path, host, break_it, reason):
    pol, drive, notes = _policy(tmp_path, host["dir"]), FakeDrive(), Notes()
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    (fid, obj), = drive.objects.items()
    if break_it == "md5":
        obj["data"] = bytes(reversed(obj["data"]))  # same size, different bytes
        obj["modifiedTime"] = "2030-02-01T00:00:00Z"  # a replaced object is a new cache identity
    elif break_it == "missing":
        del drive.objects[fid]
    else:
        obj["data"] = obj["data"] + b"x"
    res = _run(pol, drive, tmp_path, notes=notes, now=NOW + 2 * DAY)  # past the pending grace
    assert all(p.exists() for p in host["older"]) and host["newest"].exists()
    assert res["local"]["refused"] == reason
    assert res["local"]["removed"] == []
    assert res["conditions"][be.CONDITION_HOST]["alertable"] is True
    assert len(notes.sent) == 1 and reason in notes.sent[0][0]
    assert json.loads(Path(pol["verification"]["receipt_path"]).read_text())["local"]["refused"] == reason


def test_newest_not_yet_offsite_waits_out_grace_then_alerts(tmp_path, host):
    pol, drive, notes = _policy(tmp_path, host["dir"]), FakeDrive(), Notes()
    res = _run(pol, drive, tmp_path, notes=notes)  # newest is 5 h old, no upload record yet
    assert res["local"]["refused"] == "no_upload_record"
    assert all(p.exists() for p in host["older"])
    assert res["conditions"][be.CONDITION_HOST]["state"] == "pending_offsite"
    assert notes.sent == []
    res = _run(pol, drive, tmp_path, notes=notes, now=NOW + 2 * DAY)
    assert res["conditions"][be.CONDITION_HOST]["state"] == "no_upload_record"
    assert len(notes.sent) == 1


def test_drive_errors_remove_nothing_and_alert_only_after_grace(tmp_path, host):
    pol, drive, notes = _policy(tmp_path, host["dir"]), FakeDrive(), Notes()
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    drive.list_error = be.DriveError("gog drive ls rc=1")
    res = _run(pol, drive, tmp_path, notes=notes)
    assert all(p.exists() for p in host["older"])
    assert res["local"]["refused"] == "drive_unreachable"
    assert res["conditions"][be.CONDITION_DRIVE]["state"] == "drive_unreachable_within_grace"
    assert notes.sent == []
    res = _run(pol, drive, tmp_path, notes=notes, now=NOW + 7 * 3600)
    assert res["conditions"][be.CONDITION_DRIVE]["state"] == "drive_unreachable"
    assert all(p.exists() for p in host["older"])
    assert len(notes.sent) == 2  # host + drive conditions, once each
    _run(pol, drive, tmp_path, notes=notes, now=NOW + 8 * 3600)
    assert len(notes.sent) == 2  # deduped while unchanged


def test_corrupt_newest_dump_blocks_removal_and_gzip_result_is_cached(tmp_path, monkeypatch):
    backups = tmp_path / "db_backups"
    older = _dump(backups / "trade_ai_20300101_023000.sql.gz", 2 * DAY, seed="a")
    newest = _dump(backups / "trade_ai_20300102_023000.sql.gz", 5 * 3600, seed="b", corrupt=True)
    pol, drive, notes = _policy(tmp_path, backups), FakeDrive(), Notes()
    calls = []
    real = be.subprocess.run

    def counting(cmd, *a, **k):
        if cmd[:2] == ["gzip", "-t"]:
            calls.append(cmd)
        return real(cmd, *a, **k)

    monkeypatch.setattr(be.subprocess, "run", counting)
    res = _run(pol, drive, tmp_path, notes=notes)
    assert res["local"]["refused"] == "newest_gzip_failed"
    assert older.exists() and newest.exists()
    assert notes.sent and notes.sent[0][1] == "P1"
    _run(pol, drive, tmp_path, notes=notes)
    assert len(calls) == 1  # second hourly pass reads the cache (device+inode+size+mtime)
    assert len(notes.sent) == 1


def test_never_touches_holds_symlinks_hardlinks_partials_young_or_outside(tmp_path, host):
    d = host["dir"]
    hold = d / "hold-prerecovery"
    hold_dump = _dump(hold / "trade_ai_20290101_023000.sql.gz", 30 * DAY, seed="h")
    m5 = d / "m5_pre_migration_20300101T000000"
    m5_dump = _dump(m5 / "trade_ai_20290102_023000.sql.gz", 30 * DAY, seed="m")
    outside = _dump(tmp_path / "elsewhere" / "trade_ai_20290103_023000.sql.gz", 30 * DAY, seed="o")
    link = d / "trade_ai_20290104_023000.sql.gz"
    link.symlink_to(outside)
    hard_src = _dump(tmp_path / "elsewhere" / "hl_src.sql.gz", 30 * DAY, seed="l")
    hard = d / "archive" / "trade_ai_20290105_023000.sql.gz"
    os.link(hard_src, hard)
    part = _dump(d / "trade_ai_20290106_023000.sql.gz.part", 30 * DAY, seed="p")
    dir_named_like_dump = d / "trade_ai_20290107_023000.sql.gz"
    dir_named_like_dump.mkdir()
    young = _dump(d / "trade_ai_20300104_023000.sql.gz", 600, seed="y")  # newer than newest, still young
    pol, drive = _policy(tmp_path, d), FakeDrive()
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    res = _run(pol, drive, tmp_path)
    assert all(not p.exists() for p in host["older"])
    for p in (hold_dump, m5_dump, outside, hard, hard_src, part, young, host["newest"]):
        assert p.exists(), p
    assert link.is_symlink() and dir_named_like_dump.is_dir()
    assert (d / "archive" / "TRIPWIRE.txt").is_file()
    reasons = {Path(p["path"]).name: p["reason"] for p in res["local"]["protected"]}
    assert reasons[link.name] == "symlink"
    assert reasons[hard.name] == "hardlinked"
    assert reasons[dir_named_like_dump.name] == "directory"
    assert reasons[young.name] == "young"


def test_candidate_changed_after_inventory_is_kept(tmp_path, host, monkeypatch):
    pol, drive = _policy(tmp_path, host["dir"]), FakeDrive()
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    real_verify = be.verify_newest_offsite

    def verify_then_touch(*a, **k):
        out = real_verify(*a, **k)
        os.utime(host["older"][0], (NOW - 100_000, NOW - 100_000))  # a writer changed it meanwhile
        return out

    monkeypatch.setattr(be, "verify_newest_offsite", verify_then_touch)
    res = _run(pol, drive, tmp_path)
    assert host["older"][0].exists() and not host["older"][1].exists()
    assert res["local"]["removal_errors"][0]["error"].startswith("RemovalRefused")
    assert res["conditions"][be.CONDITION_HOST]["state"] == "removal_error"


def test_policy_without_verification_block_removes_nothing(tmp_path, host):
    pol = _policy(tmp_path, host["dir"])
    del pol["verification"]
    notes = Notes()
    res = _run(pol, FakeDrive(), tmp_path, notes=notes)
    assert res["refused"].startswith("policy_incomplete")
    assert all(p.exists() for p in host["older"])
    assert len(notes.sent) == 1


# ── Drive N+1 ─────────────────────────────────────────────────────────────────────────────────────────────────

def _drive_history(drive: FakeDrive, stamps: list[str]) -> None:
    for s in stamps:
        drive.put(f"db_backup_{s}.sql.gz.gpg", f"old ciphertext {s}".encode())


def test_drive_keeps_n_plus_one_and_deletes_older_after_newest_verified(tmp_path, host):
    pol, drive = _policy(tmp_path, host["dir"]), FakeDrive()
    _drive_history(drive, ["20291201_031000", "20291208_031000", "20291215_031000"])
    drive.put("env_backup_20291201_031000.tar.gz.gpg", b"other family")  # other prefixes are never touched
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    res = _run(pol, drive, tmp_path)
    assert res["drive_db"]["newest"]["verified"] is True
    assert sorted(drive.deleted) == ["db_backup_20291201_031000.sql.gz.gpg", "db_backup_20291208_031000.sql.gz.gpg"]
    names = sorted(o["name"] for o in drive.objects.values())
    assert names == ["db_backup_20291215_031000.sql.gz.gpg", "db_backup_20300103_031000.sql.gz.gpg",
                     "env_backup_20291201_031000.tar.gz.gpg"]
    assert res["conditions"][be.CONDITION_DRIVE]["state"] == "ok"


def test_drive_deletes_nothing_when_newest_unverified_or_listing_incomplete(tmp_path, host):
    pol, drive, notes = _policy(tmp_path, host["dir"]), FakeDrive(), Notes()
    _drive_history(drive, ["20291201_031000", "20291208_031000", "20291215_031000"])  # no ledger for any
    res = _run(pol, drive, tmp_path, notes=notes)
    assert drive.deleted == []
    assert res["drive_db"]["refused"] == "newest_drive_unverified:no_upload_record"
    assert res["conditions"][be.CONDITION_DRIVE]["alertable"] is True
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    drive.complete = False
    res = _run(pol, drive, tmp_path, notes=notes)
    assert drive.deleted == [] and res["drive_db"]["refused"] == "drive_listing_incomplete"


def test_drive_md5_is_streamed_once_per_object_then_cached(tmp_path, host):
    pol, drive = _policy(tmp_path, host["dir"]), FakeDrive()
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    assert drive.md5_calls == 1
    _run(pol, drive, tmp_path)
    _run(pol, drive, tmp_path)
    assert drive.md5_calls == 1


def test_prune_disabled_verifies_but_never_deletes(tmp_path, host):
    pol, drive = _policy(tmp_path, host["dir"], drive_db={"prune_enabled": False}), FakeDrive()
    _drive_history(drive, ["20291201_031000", "20291208_031000"])
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    res = _run(pol, drive, tmp_path)
    assert drive.deleted == [] and res["drive_db"]["refused"] == "prune_disabled"


# ── uploader (P4-T2) ──────────────────────────────────────────────────────────────────────────────────────────

def _upload_files(tmp: Path, dump: Path, stamp: str) -> tuple[Path, Path]:
    work = tmp / f"up_{stamp}"
    work.mkdir()
    plain = work / f"db_backup_{stamp}.sql.gz"
    shutil.copy2(dump, plain)
    enc = work / f"db_backup_{stamp}.sql.gz.gpg"
    enc.write_bytes(b"CIPHER" * 100)
    return plain, enc


@pytest.mark.parametrize("case, reason", [
    ("match", "verified"),
    ("md5", "drive_md5_mismatch"),
    ("size", "drive_size_mismatch"),
    ("missing", "drive_object_missing"),
    ("dup", "drive_object_ambiguous"),
    ("plain", "plaintext_copy_mismatch"),
])
def test_uploader_cli_exits_nonzero_unless_drive_object_matches(tmp_path, host, monkeypatch, capsys, case, reason):
    pol, drive = _policy(tmp_path, host["dir"]), FakeDrive()
    plain, enc = _upload_files(tmp_path, host["newest"], "20300103_031000")
    data = enc.read_bytes()
    if case == "md5":
        data = data[:-1] + b"X"
    elif case == "size":
        data = data + b"X"
    if case != "missing":
        drive.put(enc.name, data)
    if case == "dup":
        drive.put(enc.name, data)
    if case == "plain":
        plain.write_bytes(b"truncated copy")
    monkeypatch.setattr(be, "_load_policy", lambda: pol)
    monkeypatch.setattr(be, "GogDrive", lambda *a, **k: drive)
    monkeypatch.setattr(be, "default_notify", Notes())
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "alerts.json"))
    rc = be.main(["--verify-upload", "--source", str(host["newest"]), "--plaintext", str(plain),
                  "--encrypted", str(enc)])
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == reason
    assert rc == (0 if case == "match" else 1)
    ledger = be.load_ledger(Path(pol["verification"]["ledger_path"]))
    assert len(ledger["records"]) == (1 if case == "match" else 0)
    assert all(p.exists() for p in host["older"])  # the uploader never removes host dumps


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.mark.parametrize("upload_rc, verify_rc", [(0, 0), (0, 1), (3, 0)])
def test_backup_script_db_target_fails_closed_and_never_prunes(tmp_path, upload_rc, verify_rc):
    home = tmp_path / "home"
    creds = home / ".openclaw" / "credentials"
    creds.mkdir(parents=True)
    (creds / "env_data_backup.pass").write_text("fixture-pass\n")
    (creds / "gog_keyring_password").write_text("fixture-keyring\n")
    _dump(home / "db_backups" / "trade_ai_20300103_023000.sql.gz", 5 * 3600, seed="s")
    calls = tmp_path / "gog_calls.log"
    (home / ".local" / "bin").mkdir(parents=True)
    _exe(home / ".local" / "bin" / "gog",
         f'#!/usr/bin/env bash\necho "$*" >> "{calls}"\n'
         f'if [ "$2" = "upload" ]; then echo "id\tFAKE"; exit {upload_rc}; fi\n')
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    _exe(fakebin / "gpg", '#!/usr/bin/env bash\nout=""; prev=""\n'
         'for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\ncp "${@: -1}" "$out"\n')
    proj = tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "backup_secrets_state.sh", proj / "scripts" / "backup_secrets_state.sh")
    verify_log = tmp_path / "verify.log"
    (proj / "scripts" / "backup_enforcer.py").write_text(
        f"import sys\nopen({str(verify_log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\nsys.exit({verify_rc})\n")
    env = {"HOME": str(home), "PATH": f"{fakebin}:/usr/bin:/bin", "LANG": "C.UTF-8", "TMPDIR": str(tmp_path)}
    proc = subprocess.run(["bash", str(proj / "scripts" / "backup_secrets_state.sh"), "db"], env=env, cwd=proj,
                          capture_output=True, text=True, timeout=60)
    log = calls.read_text() if calls.exists() else ""
    assert " rm " not in f" {log} " and "drive ls" not in log  # db retention is never the script's
    if upload_rc:
        assert proc.returncode != 0 and not verify_log.exists()
    else:
        assert "--verify-upload" in verify_log.read_text()
        assert "--encrypted" in verify_log.read_text()
        assert proc.returncode == (0 if verify_rc == 0 else 1)
    assert (home / "db_backups" / "trade_ai_20300103_023000.sql.gz").exists()


# ── alerting ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_alert_raised_once_then_cleared_on_recovery(tmp_path, host):
    pol, drive, notes = _policy(tmp_path, host["dir"]), FakeDrive(), Notes()
    _offsite(pol, drive, host["newest"], tmp_path, stamp="20300103_031000")
    (fid, obj), = drive.objects.items()
    good = obj["data"]
    obj["data"], obj["modifiedTime"] = bytes(reversed(good)), "2030-02-01T00:00:00Z"
    for _ in range(3):
        _run(pol, drive, tmp_path, notes=notes)
    assert len(notes.sent) == 1 and "drive_md5_mismatch" in notes.sent[0][0]
    obj["data"], obj["modifiedTime"] = good, "2030-02-02T00:00:00Z"
    res = _run(pol, drive, tmp_path, notes=notes)
    assert res["conditions"][be.CONDITION_HOST]["state"] == "ok"
    assert len(notes.sent) == 2 and "recovered" in notes.sent[1][0]
    _run(pol, drive, tmp_path, notes=notes)
    assert len(notes.sent) == 2
    assert all(not p.exists() for p in host["older"])


def test_policy_file_declares_one_on_host_and_n_plus_one_on_drive():
    import yaml

    pol = yaml.safe_load((REPO / "config" / "backup_policy.yaml").read_text())
    local, drive, ver = be.load_sections(pol)
    assert local["keep_on_host"] == 1 == local["max_count"]
    assert drive["keep_n"] == 1
    assert ver["newest_unverified_grace_hours"] > 0 and ver["drive_unreachable_grace_hours"] > 0
