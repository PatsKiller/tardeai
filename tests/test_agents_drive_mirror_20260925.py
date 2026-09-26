"""AGENTS.md Drive mirror: update by pinned stable id, never create a duplicate.

`gog drive upload --parent` CREATES a file; only `--replace=<id>` updates in
place (gog v0.12.0 help). The script used to call `--parent` whenever one
AGENTS.md already existed. These tests drive the script against a fake gog
broker that records every call and serves ls / upload / download.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mirror_agents_md_to_drive.sh"

FAKE = r"""#!/usr/bin/env bash
# fake gog broker: argv = drive <verb> ...
echo "$*" >> "$FAKE_LOG"
verb="$2"
case "$verb" in
  ls) cat "$FAKE_LISTING" ;;
  upload)
    if printf '%s' "$*" | grep -q -- '--replace'; then
      id=$(printf '%s' "$*" | sed -E 's/.*--replace ([^ ]+).*/\1/')
    else id="NEWLY-CREATED-ID"; fi
    cp "$3" "$FAKE_DRIVE_STORE"
    printf '{"file":{"id":"%s"}}' "${FAKE_RETURN_ID:-$id}" ;;
  download)
    out=$(printf '%s' "$*" | sed -E 's/.*--output ([^ ]+).*/\1/')
    cp "${FAKE_DOWNLOAD_SRC:-$FAKE_DRIVE_STORE}" "$out" ;;
  *) echo "unexpected verb $verb" >&2; exit 9 ;;
esac
"""


@pytest.fixture()
def env(tmp_path: Path):
    broker = tmp_path / "fake_broker.sh"
    broker.write_text(FAKE)
    broker.chmod(0o755)
    src = tmp_path / "AGENTS.md"
    src.write_text("```\nPolicy-Version:      9.9.9\n```\nbody\n")
    e = {
        **os.environ,
        "TRADEAI_AGENT": "claude_code",
        "AGENTS_MIRROR_GOG_BROKER": str(broker),
        "AGENTS_MIRROR_SRC": str(src),
        "AGENTS_MIRROR_MANIFEST": str(tmp_path / "manifest.json"),
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_LISTING": str(tmp_path / "listing.json"),
        "FAKE_DRIVE_STORE": str(tmp_path / "drive_copy.md"),
    }
    return tmp_path, e


def _listing(tmp: Path, ids: list[str]) -> None:
    (tmp / "listing.json").write_text(json.dumps({"files": [{"id": i, "name": "AGENTS.md"} for i in ids]}))


def _manifest(tmp: Path, file_id: str) -> None:
    (tmp / "manifest.json").write_text(json.dumps({"drive_file_id": file_id}))


def _run(e: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], env=e, capture_output=True, text=True, cwd=str(ROOT))


def _calls(tmp: Path) -> str:
    p = tmp / "calls.log"
    return p.read_text() if p.exists() else ""


def test_pinned_id_is_replaced_in_place_and_verified(env):
    tmp, e = env
    _listing(tmp, ["PINNED"])
    _manifest(tmp, "PINNED")
    r = _run(e)
    assert r.returncode == 0, r.stderr
    calls = _calls(tmp)
    assert "--replace PINNED" in calls and "--parent" not in calls.split("upload", 1)[1].split("\n")[0]
    assert "VERIFIED BYTE_EXACT" in r.stdout
    m = json.loads((tmp / "manifest.json").read_text())
    assert m["drive_file_id"] == "PINNED" and m["verification"] == "BYTE_EXACT"


def test_duplicate_copies_refuse_without_upload(env):
    tmp, e = env
    _listing(tmp, ["A", "B"])
    _manifest(tmp, "A")
    r = _run(e)
    assert r.returncode != 0 and "operator must resolve" in r.stderr
    assert "upload" not in _calls(tmp)


def test_listing_disagreeing_with_manifest_refuses(env):
    tmp, e = env
    _listing(tmp, ["OTHER"])
    _manifest(tmp, "PINNED")
    r = _run(e)
    assert r.returncode != 0 and "refusing to guess" in r.stderr
    assert "upload" not in _calls(tmp)


def test_existing_copy_without_manifest_is_not_duplicated(env):
    tmp, e = env
    _listing(tmp, ["EXISTS"])
    r = _run(e)
    assert r.returncode != 0 and "no manifest drive_file_id" in r.stderr
    assert "upload" not in _calls(tmp)


def test_first_copy_needs_explicit_flag(env):
    tmp, e = env
    _listing(tmp, [])
    assert _run(e).returncode != 0
    r = _run({**e, "AGENTS_MIRROR_CREATE_FIRST": "1"})
    assert r.returncode == 0, r.stderr
    assert "--parent" in _calls(tmp)


def test_replace_returning_a_different_id_stops(env):
    tmp, e = env
    _listing(tmp, ["PINNED"])
    _manifest(tmp, "PINNED")
    r = _run({**e, "FAKE_RETURN_ID": "SURPRISE"})
    assert r.returncode != 0 and "expected the pinned" in r.stderr


def test_byte_mismatch_does_not_write_manifest(env):
    tmp, e = env
    _listing(tmp, ["PINNED"])
    _manifest(tmp, "PINNED")
    wrong = tmp / "wrong.md"
    wrong.write_text("different bytes\n")
    r = _run({**e, "FAKE_DOWNLOAD_SRC": str(wrong)})
    assert r.returncode != 0 and "BYTE MISMATCH" in r.stderr
    assert json.loads((tmp / "manifest.json").read_text()) == {"drive_file_id": "PINNED"}


def test_committed_manifest_pins_the_governed_file():
    m = json.loads((ROOT / "docs" / "ops" / "AGENTS_DRIVE_MIRROR_MANIFEST.json").read_text())
    assert m["drive_file_id"] and m["drive_path"].endswith("governance/agent-policy/AGENTS.md")
    assert m["verification"] in {"BYTE_EXACT", "OBSERVED_MISMATCH"}
