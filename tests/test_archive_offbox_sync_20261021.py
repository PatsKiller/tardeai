"""Off-box copy of the retention archives to Google Drive (operator D9 = (a), 2026-10-21).

scripts/archive_offbox_sync.py copies every archive file under <state>/archive/ to
Trade_AI_Backups/archive/<area>/<YYYYMM>/ on Drive, gpg-encrypted exactly as scripts/backup_secrets_state.sh does.
These tests prove, with a fake uploader and a fake encryptor in tmp_path (no gog, no gpg, no credentials, no Drive):

* dry run is the default and writes nothing (no manifest, no receipt, no uploader call);
* --apply uploads, verifies each upload before marking it done, and is incremental (a second run uploads nothing;
  a changed file is uploaded again as a new version);
* a failed verification or a failed upload is recorded and the rest of the run continues;
* the per-run byte bound defers the rest, and the next run resumes;
* the local archive is never deleted or modified;
* the Drive folder, account, gog binary and passphrase files are the ones backup_secrets_state.sh uses.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import archive_offbox_sync as aos  # noqa: E402

COVERS = ["scripts/archive_offbox_sync.py", "config/lane_registry.json", "scripts/lib/retention_tripwire.py"]

OLD = time.time() - 7200  # older than the in-flight guard


class FakeEncryptor:
    """Stands in for gpg: writes a deterministic, different byte string."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def encrypt(self, src: Path, dst: Path) -> None:
        self.calls.append(src)
        dst.write_bytes(b"ENC:" + Path(src).read_bytes())


class FakeUploader:
    """Records uploads; `stat` reports what Drive would. `corrupt` / `explode` name files to fail."""

    def __init__(self, corrupt: tuple[str, ...] = (), explode: tuple[str, ...] = ()) -> None:
        self.files: dict[str, dict] = {}
        self.folders: dict[tuple, str] = {}
        self.corrupt = corrupt
        self.explode = explode
        self.n = 0

    def ensure_folder(self, parts, cache):
        key = "/".join(parts)
        if key not in cache:
            self.folders[tuple(parts)] = cache[key] = f"folder-{len(self.folders)}"
        return cache[key]

    def upload(self, local: Path, name: str, parent_id: str) -> dict:
        if any(x in name for x in self.explode):
            raise RuntimeError("upload failed")
        self.n += 1
        fid = f"file-{self.n}"
        data = Path(local).read_bytes()
        size = len(data) - (1 if any(x in name for x in self.corrupt) else 0)
        self.files[fid] = {"name": name, "parent": parent_id, "size": size,
                           "md5": hashlib.md5(data).hexdigest(), "data": data}
        return {"id": fid}

    def stat(self, file_id: str) -> dict:
        f = self.files[file_id]
        return {"size": f["size"], "md5": f["md5"] if f["size"] == len(f["data"]) else "0" * 32}


def _put(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (OLD, OLD))
    return path


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for k in ("TRADEAI_RUN_ID", "TRADEAI_RUN_ATTEMPT", "TRADEAI_RUN_MODE", "TRADEAI_CODE_SHA"):
        monkeypatch.delenv(k, raising=False)
    arch = tmp_path / "state" / "archive"
    _put(arch / "db_retention" / "news_articles" / "20261012T051517Z.jsonl.gz", b"a" * 100)
    _put(arch / "db_retention" / "news_articles" / "20261012T051517Z.jsonl.gz.manifest.json", b"{}")
    _put(arch / "db_retention" / "news_articles" / "TRIPWIRE.jsonl", b'{"x":1}\n')
    _put(arch / "db_trim" / "20261021T005807Z" / "rows_symbol_profiles.jsonl.gz", b"b" * 50)
    _put(arch / "comms_lifecycle" / "communication_events" / "c.jsonl.gz", b"c" * 30)
    return {
        "arch": arch,
        "manifest": tmp_path / "state" / "data" / "runtime" / "archive_offbox_manifest.json",
        "receipt": tmp_path / "state" / "data" / "runtime" / "archive-offbox-sync_last.json",
        "tmp": tmp_path / "enc",
    }


def _snapshot(arch: Path) -> dict[str, tuple[str, int]]:
    return {p.relative_to(arch).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(arch.rglob("*")) if p.is_file()}


def _run(t, *, apply, uploader=None, encryptor=None, **kw):
    lines: list[str] = []
    res = aos.run(archive_root=t["arch"], manifest_path=t["manifest"], apply=apply, uploader=uploader,
                  encryptor=encryptor, receipt_path=t["receipt"], tmp_dir=t["tmp"], out=lines.append, **kw)
    return res, lines


def test_dry_run_is_default_lists_pending_and_writes_nothing(tree):
    assert aos.build_parser().parse_args([]).apply is False
    up, enc = FakeUploader(), FakeEncryptor()
    before = _snapshot(tree["arch"])
    res, lines = _run(tree, apply=False, uploader=up, encryptor=enc)
    assert res["mode"] == "dry_run"
    assert res["pending_files"] == 5
    assert res["pending_bytes"] == 100 + 2 + 8 + 50 + 30
    assert res["would_upload_files"] == 5
    assert res["by_area"]["db_retention"]["files"] == 3
    assert any("would upload" in ln for ln in lines)
    assert not tree["manifest"].exists() and not tree["receipt"].exists()
    assert up.n == 0 and enc.calls == [] and up.folders == {}
    assert _snapshot(tree["arch"]) == before


def test_apply_uploads_verifies_and_is_incremental(tree):
    up, enc = FakeUploader(), FakeEncryptor()
    before = _snapshot(tree["arch"])
    res, _ = _run(tree, apply=True, uploader=up, encryptor=enc)
    assert res["exit"] == 0 and res["uploaded_files"] == 5 and res["failures"] == []
    man = json.loads(tree["manifest"].read_text())
    assert man["schema"] == aos.MANIFEST_SCHEMA
    e = man["files"]["db_retention/news_articles/20261012T051517Z.jsonl.gz"]
    assert e["sha256"] == hashlib.sha256(b"a" * 100).hexdigest()
    assert e["size"] == 100 and e["uploaded_at"] and e["verified"] is True
    assert e["drive_name"] == "news_articles__20261012T051517Z.jsonl.gz.gpg"
    assert e["drive_folder"].startswith("Trade_AI_Backups/archive/db_retention/")
    assert re.fullmatch(r"Trade_AI_Backups/archive/db_retention/\d{6}", e["drive_folder"])
    assert e["enc_size"] == 104
    # receipt: LaneRunReceipt@v2 with the output fields
    rc = json.loads(tree["receipt"].read_text())
    assert rc["schema"] == "LaneRunReceipt@v2" and rc["status"] == "ok"
    assert rc["produced_count"] == 5 and rc["lane_id"] == aos.LANE_ID
    # second run: nothing pending, nothing uploaded
    res2, _ = _run(tree, apply=True, uploader=up, encryptor=enc)
    assert res2["uploaded_files"] == 0 and up.n == 5
    assert json.loads(tree["receipt"].read_text())["empty_reason"] == "nothing_pending"
    # an appended (mutable) file is uploaded again as a new version, the old one kept in history
    trip = tree["arch"] / "db_retention" / "news_articles" / "TRIPWIRE.jsonl"
    _put(trip, b'{"x":1}\n{"x":2}\n')
    res3, _ = _run(tree, apply=True, uploader=up, encryptor=enc)
    assert res3["uploaded_files"] == 1 and up.n == 6
    man = json.loads(tree["manifest"].read_text())
    t = man["files"]["db_retention/news_articles/TRIPWIRE.jsonl"]
    assert t["sha256"] == hashlib.sha256(b'{"x":1}\n{"x":2}\n').hexdigest()
    assert len(t["versions"]) == 1 and t["drive_name"] != t["versions"][0]["drive_name"]
    # never delete: every local archive file is still there, untouched (except the one the test appended)
    after = _snapshot(tree["arch"])
    assert set(after) == set(before)
    for rel, v in before.items():
        if not rel.endswith("TRIPWIRE.jsonl"):
            assert after[rel] == v


def test_failed_verification_is_not_marked_done_and_rest_continue(tree):
    up, enc = FakeUploader(corrupt=("rows_symbol_profiles",), explode=("communication_events",)), FakeEncryptor()
    res, _ = _run(tree, apply=True, uploader=up, encryptor=enc)
    assert res["exit"] == 1
    assert res["uploaded_files"] == 3
    stages = {f["path"]: f["stage"] for f in res["failures"]}
    assert stages == {"db_trim/20261021T005807Z/rows_symbol_profiles.jsonl.gz": "verify",
                      "comms_lifecycle/communication_events/c.jsonl.gz": "upload"}
    man = json.loads(tree["manifest"].read_text())
    assert "db_trim/20261021T005807Z/rows_symbol_profiles.jsonl.gz" not in man["files"]
    assert "comms_lifecycle/communication_events/c.jsonl.gz" not in man["files"]
    rc = json.loads(tree["receipt"].read_text())
    assert rc["status"] == "failed" and rc["produced_count"] == 3
    assert len(rc["summary"]["failures"]) == 2
    # the failed files are retried next run
    res2, _ = _run(tree, apply=True, uploader=FakeUploader(), encryptor=enc)
    assert res2["uploaded_files"] == 2 and res2["exit"] == 0


def test_byte_bound_defers_and_next_run_resumes(tree):
    up, enc = FakeUploader(), FakeEncryptor()
    res, _ = _run(tree, apply=True, uploader=up, encryptor=enc, max_bytes=120)
    assert 0 < res["uploaded_files"] < 5 and res["uploaded_bytes"] <= 120
    assert res["deferred_files"] == 5 - res["uploaded_files"]
    done = res["uploaded_files"]
    for _ in range(5):
        r, _ = _run(tree, apply=True, uploader=up, encryptor=enc, max_bytes=120)
        done += r["uploaded_files"]
    assert done == 5 and up.n == 5
    assert len(json.loads(tree["manifest"].read_text())["files"]) == 5


def test_oversized_single_file_still_progresses(tree):
    up, enc = FakeUploader(), FakeEncryptor()
    res, _ = _run(tree, apply=True, uploader=up, encryptor=enc, max_bytes=10, areas=["db_retention"])
    assert res["uploaded_files"] == 1  # never starves on a file larger than the bound


def test_in_flight_file_is_skipped(tree):
    fresh = tree["arch"] / "db_trim" / "new.jsonl.gz"
    fresh.write_bytes(b"x")
    res, _ = _run(tree, apply=False)
    assert res["skipped_reasons"].get("too_new") == 1
    assert res["pending_files"] == 5


def test_symlink_is_skipped_not_followed(tree, tmp_path):
    outside = _put(tmp_path / "outside.txt", b"secret")
    (tree["arch"] / "db_trim" / "link").symlink_to(outside)
    res, _ = _run(tree, apply=False)
    assert res["skipped_reasons"].get("not_regular_file") == 1


def test_no_delete_calls_in_source():
    src = (ROOT / "scripts" / "archive_offbox_sync.py").read_text()
    for bad in ("shutil.rmtree", "os.remove(", "drive rm", "drive delete", '"rm"', '"delete"', "--permanent"):
        assert bad not in src, bad
    # the only unlink is of our own temp ciphertext
    assert src.count(".unlink(") == 1


def test_mechanism_matches_backup_secrets_state():
    sh = (ROOT / "scripts" / "backup_secrets_state.sh").read_text()

    def val(name):
        m = re.search(rf'^{name}="([^"]+)"', sh, re.M)
        assert m, name
        return m.group(1).replace("$HOME", str(Path.home()))

    assert val("DRIVE_FOLDER") == aos.DRIVE_ROOT_FOLDER_ID
    assert val("ACCT") == aos.DRIVE_ACCOUNT
    assert val("GOG") == str(aos.GOG)
    assert val("PASS_FILE") == str(aos.PASS_FILE)
    assert val("GOG_KEYRING_PW_FILE") == str(aos.GOG_KEYRING_PW_FILE)
    assert "--cipher-algo AES256" in sh and aos.GPG_ARGS[aos.GPG_ARGS.index("--cipher-algo") + 1] == "AES256"


def test_tripwire_allowlists_the_copier_and_registry_row():
    from scripts.lib import retention_tripwire as rt

    assert "scripts/archive_offbox_sync.py" in rt.ALLOWLIST_REL
    rows = json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]
    row = next(r for r in rows if r["lane_id"] == aos.LANE_ID)
    assert row["scheduler"] == {"kind": "systemd", "expression": "tradeai-archive-offbox-sync.timer"}
    assert row["state"] == "NEVER_SCHEDULED" and row["state_since"] and row["state_reason"]
    assert row["output_signal"]["path"] == "data/runtime/archive-offbox-sync_last.json"
    pk = ROOT / "docs" / "ops" / "packets" / "archive-offbox-20261021"
    timer = (pk / "tradeai-archive-offbox-sync.timer").read_text()
    assert "OnCalendar=*-*-* 03:30:00" in timer
    service = (pk / "tradeai-archive-offbox-sync.service").read_text()
    assert "archive_offbox_sync.py --apply" in service
    for needle in rt.NEEDLES:  # an installed unit must not trip the nightly reference scan
        assert needle not in service and needle not in timer
    install = (pk / "install.sh").read_text()
    assert "--apply" in install and "DRY RUN" in install
