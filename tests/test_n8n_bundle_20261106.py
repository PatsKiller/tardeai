"""n8n backup bundle (n8n program 0.2a): policy view, verify-before-prune on Drive, receipt on failure.

Hermetic: synthetic tmp dirs and a FAKE Drive client. No docker, no gog, no gpg, no real Drive.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


be = _load("backup_enforcer", "scripts/backup_enforcer.py")
nb = _load("n8n_backup", "scripts/n8n_backup.py")


class FakeDrive:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.list_error: Exception | None = None
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
        return {"files": files, "complete": True}

    def md5(self, file_id: str) -> tuple[str, int]:
        data = self.objects[file_id]["data"]
        return hashlib.md5(data).hexdigest(), len(data)  # noqa: S324 -- Drive reports md5; this mirrors it

    def delete(self, file_id: str) -> None:
        self.deleted.append(self.objects.pop(file_id)["name"])


class Notes:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def __call__(self, text: str, priority: str) -> str:
        self.sent.append((text, priority))
        return "accepted"


def _policy(tmp: Path) -> dict:
    state = tmp / "state"
    return {
        "local_pg": {"dir": str(tmp / "db"), "pattern": "trade_ai_*.sql.gz", "keep_on_host": 1, "max_count": 1,
                     "min_bytes": 20, "max_total_bytes": 10**9, "skip_younger_than_s": 7200},
        "drive_db": {"folder_id": "DBFOLDER", "prefix": "db_backup", "keep_n": 1, "prune_enabled": True,
                     "account": "nobody@example.invalid", "gog_bin": str(tmp / "no-gog"),
                     "keyring_password_file": str(tmp / "no-keyring"), "list_max": 100, "command_timeout_s": 5},
        "drive_n8n": {"folder_id": "N8NFOLDER", "prefix": "n8n_backup", "keep_n": 1, "prune_enabled": True,
                      "ledger_path": str(state / "n8n_ledger.json")},
        "verification": {"gzip_timeout_s": 60, "drive_md5_timeout_s": 60, "drive_unreachable_grace_hours": 6,
                         "newest_unverified_grace_hours": 30, "alert_realert_minutes": 360,
                         "ledger_path": str(state / "db_ledger.json"), "ledger_max_records": 30,
                         "cache_path": str(state / "cache.json"), "cache_max_entries": 50,
                         "receipt_path": str(state / "receipt.json"),
                         "removals_log_path": str(state / "removals.jsonl"),
                         "lock_path": str(state / "enforcer.lock"), "fifo_dir": str(state / "fifo")},
    }


def _upload(tmp: Path, pol: dict, drive: FakeDrive, stamp: str, data: bytes) -> dict:
    """What n8n_backup.apply does after gog: host copy, a plaintext copy, the encrypted file, verify."""
    host = tmp / f"n8n_backup_{stamp}.tar.gz"
    host.write_bytes(data)
    plain = tmp / f"plain_{stamp}.tar.gz"
    plain.write_bytes(data)
    enc = tmp / f"n8n_backup_{stamp}.tar.gz.gpg"
    enc.write_bytes(b"ENC" + data)
    drive.put(enc.name, enc.read_bytes())
    return be.verify_upload(be.n8n_policy(pol), source=host, plaintext=plain, encrypted=enc, drive=drive,
                            notify=Notes(), alert_state_path=tmp / "alerts.json", condition=be.CONDITION_N8N_UPLOAD)


def test_n8n_policy_swaps_folder_prefix_and_ledger_but_keeps_the_rest(tmp_path):
    pol = _policy(tmp_path)
    view = be.n8n_policy(pol)
    assert view["drive_db"]["prefix"] == "n8n_backup" and view["drive_db"]["folder_id"] == "N8NFOLDER"
    assert view["drive_db"]["gog_bin"] == pol["drive_db"]["gog_bin"]  # inherited
    assert view["verification"]["ledger_path"].endswith("n8n_ledger.json")
    assert pol["drive_db"]["prefix"] == "db_backup" and pol["verification"]["ledger_path"].endswith("db_ledger.json")


def test_missing_drive_n8n_section_is_a_policy_error_not_a_default(tmp_path):
    pol = _policy(tmp_path)
    del pol["drive_n8n"]
    with pytest.raises(be.PolicyError):
        be.n8n_policy(pol)
    res = be.run_n8n_drive(pol, drive=FakeDrive())
    assert res["ok"] is False and res["refused"].startswith("policy_incomplete")


def test_verified_upload_then_retention_keeps_newest_two_and_deletes_the_oldest(tmp_path):
    pol, drive = _policy(tmp_path), FakeDrive()
    for stamp in ("20261101_030000", "20261102_030000", "20261103_030000"):
        assert _upload(tmp_path, pol, drive, stamp, b"bundle-" + stamp.encode())["ok"] is True
    res = be.run_n8n_drive(pol, drive=drive, notify=Notes(), alert_state_path=tmp_path / "alerts.json")
    assert res["ok"] is True
    assert drive.deleted == ["n8n_backup_20261101_030000.tar.gz.gpg"]
    assert sorted(o["name"] for o in drive.objects.values()) == [
        "n8n_backup_20261102_030000.tar.gz.gpg", "n8n_backup_20261103_030000.tar.gz.gpg"]


def test_unverified_newest_object_blocks_every_deletion(tmp_path):
    pol, drive = _policy(tmp_path), FakeDrive()
    assert _upload(tmp_path, pol, drive, "20261101_030000", b"old-1")["ok"]
    assert _upload(tmp_path, pol, drive, "20261102_030000", b"old-2")["ok"]
    drive.put("n8n_backup_20261103_030000.tar.gz.gpg", b"never-recorded")  # on Drive, not in the ledger
    notes = Notes()
    res = be.run_n8n_drive(pol, drive=drive, notify=notes, alert_state_path=tmp_path / "alerts.json")
    assert res["ok"] is False and res["refused"].startswith("newest_drive_unverified")
    assert drive.deleted == []
    assert notes.sent, "an unverified newest bundle must alert the operator"


def test_unreachable_drive_is_reported_and_alerted_not_treated_as_nothing_to_do(tmp_path):
    pol, drive = _policy(tmp_path), FakeDrive()
    drive.list_error = be.DriveError("gog drive ls timeout")
    notes = Notes()
    res = be.run_n8n_drive(pol, drive=drive, notify=notes, alert_state_path=tmp_path / "alerts.json")
    assert res["ok"] is False and res["refused"] == "drive_unreachable" and drive.deleted == []
    assert notes.sent


def test_db_and_n8n_ledgers_and_prefixes_do_not_cross(tmp_path):
    pol, drive = _policy(tmp_path), FakeDrive()
    assert _upload(tmp_path, pol, drive, "20261101_030000", b"n8n")["ok"]
    drive.put("db_backup_20261101_030000.sql.gz.gpg", b"a database dump")
    res = be.run_n8n_drive(pol, drive=drive, notify=Notes(), alert_state_path=tmp_path / "alerts.json")
    assert res["ok"] is True and drive.deleted == []
    assert [o["name"] for o in drive.objects.values() if o["name"].startswith("db_backup_")] == [
        "db_backup_20261101_030000.sql.gz.gpg"]


def test_size_or_md5_mismatch_on_drive_fails_the_upload_gate(tmp_path):
    pol, drive = _policy(tmp_path), FakeDrive()
    host = tmp_path / "n8n_backup_20261101_030000.tar.gz"
    host.write_bytes(b"x" * 50)
    plain = tmp_path / "plain.tar.gz"
    plain.write_bytes(b"x" * 50)
    enc = tmp_path / "n8n_backup_20261101_030000.tar.gz.gpg"
    enc.write_bytes(b"E" * 60)
    drive.put(enc.name, b"F" * 60)  # same size, different bytes
    res = be.verify_upload(be.n8n_policy(pol), source=host, plaintext=plain, encrypted=enc, drive=drive,
                           notify=Notes(), alert_state_path=tmp_path / "alerts.json",
                           condition=be.CONDITION_N8N_UPLOAD)
    assert res["ok"] is False and res["reason"] == "drive_md5_mismatch"
    assert not (tmp_path / "state" / "n8n_ledger.json").exists()  # nothing recorded for a bad copy


def test_wrong_prefix_is_refused_before_anything_is_read(tmp_path):
    pol, drive = _policy(tmp_path), FakeDrive()
    f = tmp_path / "db_backup_20261101_030000.tar.gz"
    f.write_bytes(b"x")
    res = be.verify_upload(be.n8n_policy(pol), source=f, plaintext=f, encrypted=f, drive=drive, notify=Notes(),
                           alert_state_path=tmp_path / "alerts.json", condition=be.CONDITION_N8N_UPLOAD)
    assert res["ok"] is False and res["reason"] == "drive_name_prefix_mismatch"


def test_apply_failure_writes_a_receipt_with_the_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(nb, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(nb, "PASS_FILE", tmp_path / "no-such-passphrase")
    doc = nb.apply(no_drive=False)
    assert doc["ok"] is False and doc["reason"] == "passphrase_file_missing"
    receipt = json.loads((tmp_path / "out" / nb.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt["schema"] == nb.SCHEMA and receipt["ok"] is False and receipt["reason"] == "passphrase_file_missing"


def test_prune_host_keeps_only_the_newest_bundles(tmp_path):
    for i in range(1, 6):
        (tmp_path / f"n8n_backup_2026110{i}_030000.tar.gz").write_bytes(b"x")
    gone = nb.prune_host(tmp_path, 3)
    assert sorted(gone) == ["n8n_backup_20261101_030000.tar.gz", "n8n_backup_20261102_030000.tar.gz"]
    assert len(list(tmp_path.glob("n8n_backup_*.tar.gz"))) == 3


def test_volume_export_refuses_an_archive_without_the_encryption_key_config(tmp_path, monkeypatch):
    import subprocess

    def fake_run(cmd, *, timeout=600, stdout=subprocess.PIPE):
        if cmd[0] == "docker":
            src = tmp_path / "src"
            src.mkdir(exist_ok=True)
            (src / "storage").mkdir(exist_ok=True)
            (src / "storage" / "x").write_text("x", encoding="utf-8")
            res = subprocess.run(["tar", "-C", str(src), "-czf", "-", "."], stdout=stdout, stderr=subprocess.PIPE,
                                 check=False)
            return res
        return subprocess.run(cmd, stdout=stdout, stderr=subprocess.PIPE, timeout=timeout, check=False)

    monkeypatch.setattr(nb, "_run", fake_run)
    with pytest.raises(nb.BackupError, match="volume_tar_missing_config"):
        nb.export_volume(tmp_path / "vol.tar.gz")
    (tmp_path / "src" / "config").write_text("{}", encoding="utf-8")
    facts = nb.export_volume(tmp_path / "vol.tar.gz")
    assert facts["members"] >= 2 and facts["bytes"] > 0
