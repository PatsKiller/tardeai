"""Drive mirror decision fixtures — no network, no credentials."""
from __future__ import annotations

from scripts.lib.agents_drive_mirror_policy import decide_mirror_action, sha256_bytes


def test_create_when_zero_matches():
    d = decide_mirror_action(matching_files=[], stable_file_id=None,
                             local_sha="abc", remote_sha="abc", readback_ok=True)
    assert d.action == "create"


def test_update_stable_id():
    d = decide_mirror_action(
        matching_files=[{"id": "fid1", "name": "AGENTS.md"}],
        stable_file_id="fid1", local_sha="abc", remote_sha="abc", readback_ok=True)
    assert d.action == "update" and d.file_id == "fid1"


def test_stop_on_duplicates():
    d = decide_mirror_action(
        matching_files=[{"id": "a"}, {"id": "b"}],
        stable_file_id=None, local_sha="abc", remote_sha="abc", readback_ok=True)
    assert d.action == "stop_duplicate"


def test_reject_hash_mismatch():
    d = decide_mirror_action(
        matching_files=[{"id": "fid1"}], stable_file_id="fid1",
        local_sha="aaa", remote_sha="bbb", readback_ok=True)
    assert d.action == "reject_hash_mismatch"


def test_reject_readback_failure():
    d = decide_mirror_action(
        matching_files=[{"id": "fid1"}], stable_file_id="fid1",
        local_sha="aaa", remote_sha=None, readback_ok=False)
    assert d.action == "reject_readback"


def test_sha256_bytes_stable():
    assert sha256_bytes(b"hello") == sha256_bytes(b"hello")
    assert sha256_bytes(b"hello") != sha256_bytes(b"world")
