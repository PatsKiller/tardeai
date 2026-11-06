"""n8n 0.2c: the bundle restore drill's decisions, hermetic (no docker, no database)."""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts import n8n_bundle_restore_drill as d


def _add(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def _volume(cfg: bytes | None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        if cfg is not None:
            _add(tf, "config", cfg)
    return buf.getvalue()


def _bundle(path: Path, *, cfg: bytes | None = b'{"encryptionKey": "k"}', tamper: bool = False) -> Path:
    vol = _volume(cfg)
    dump = b"dump-bytes"
    members = {"volume/n8n-data.tar.gz": vol, "db/x.dump": dump}
    man = {"dump": "x.dump", "dump_workflow_count": 3, "credentials_count": 1,
           "members": {k: {"bytes": len(v), "sha256": d.hashlib.sha256(v).hexdigest()} for k, v in members.items()}}
    with tarfile.open(path, "w:gz") as tf:
        _add(tf, "MANIFEST.json", json.dumps(man).encode())
        for k, v in members.items():
            _add(tf, k, (v + b"x") if tamper and k == "db/x.dump" else v)
    return path


def test_intact_bundle_has_no_problems(tmp_path):
    stage = tmp_path / "s"
    stage.mkdir()
    man, problems = d.check_bundle(_bundle(tmp_path / "n8n_backup_1.tar.gz"), stage)
    assert problems == [] and man["dump_workflow_count"] == 3


def test_tampered_member_is_named(tmp_path):
    stage = tmp_path / "s"
    stage.mkdir()
    _, problems = d.check_bundle(_bundle(tmp_path / "b.tar.gz", tamper=True), stage)
    assert problems == ["member_mismatch:db/x.dump"]


def test_unreadable_bundle(tmp_path):
    bad = tmp_path / "b.tar.gz"
    bad.write_bytes(b"not a tar")
    stage = tmp_path / "s"
    stage.mkdir()
    assert d.check_bundle(bad, stage)[1] == ["bundle_unreadable:ReadError"]


@pytest.mark.parametrize("cfg,reason", [(b'{"encryptionKey": "k"}', "ok"), (None, "volume_config_missing_or_invalid"),
                                         (b'{"other": 1}', "volume_config_has_no_encryption_key"),
                                         (b'{"encryptionKey": ""}', "volume_config_has_no_encryption_key")])
def test_volume_key(tmp_path, cfg, reason):
    stage = tmp_path / "s"
    stage.mkdir()
    d.check_bundle(_bundle(tmp_path / "b.tar.gz", cfg=cfg), stage)
    key, got = d.volume_key(stage)
    assert got == reason and (key == "k") == (reason == "ok")


GOOD = {"restore_rc": 0, "restore_stderr_errors": 0, "workflow_count": 3, "key_word": "KEY_OK", "dropped": True}
MAN = {"dump_workflow_count": 3, "credentials_count": 1}


def _v(**over):
    facts = {**GOOD, **over.pop("facts", {})}
    return d.verdict(bundle_problems=over.pop("problems", []), key_reason=over.pop("key_reason", "ok"), facts=facts,
                     manifest=MAN, expect_credentials=True)


def test_all_good_passes():
    assert _v()["state"] == "PASSED"


@pytest.mark.parametrize("kw,failed", [
    ({"facts": {"restore_rc": 1}}, "db_restores"),
    ({"facts": {"restore_stderr_errors": 2}}, "db_restores"),
    ({"facts": {"workflow_count": 2}}, "workflows_match"),
    ({"facts": {"workflow_count": None}}, "workflows_match"),
    ({"facts": {"key_word": "KEY_BAD"}}, "key_decrypts"),
    ({"facts": {"key_word": "NO_CIPHERTEXT"}}, "key_decrypts"),
    ({"facts": {"dropped": False}}, "drill_db_dropped"),
    ({"key_reason": "volume_config_missing_or_invalid"}, "volume_has_config"),
    ({"problems": ["member_mismatch:db/x.dump"]}, "bundle_intact"),
])
def test_each_failure_is_named(kw, failed):
    v = _v(**kw)
    assert v["state"] == "FAILED" and failed in v["failures"]


def test_missing_fact_never_passes():
    v = d.verdict(bundle_problems=[], key_reason="ok", facts={}, manifest=MAN, expect_credentials=True)
    assert v["state"] == "FAILED"


def test_no_bundle_writes_a_failed_receipt(tmp_path):
    doc = d.apply(tmp_path)
    assert doc["state"] == "FAILED" and doc["failures"] == ["no_bundle_found"]
    on_disk = json.loads((tmp_path / d.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert on_disk["state"] == "FAILED" and "seconds" in on_disk
    assert (tmp_path / d.RECEIPT_NAME).stat().st_mode & 0o777 == 0o600
