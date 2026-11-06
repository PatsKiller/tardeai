"""n8n 0.2a: the n8n_snapshot_now.sh output contract. The backup itself is stubbed (a fake n8n_backup.py)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = {"ok": True, "drive": {"object": {"id": "abc123"}},
           "manifest": {"members": {"db/x.dump": {"bytes": 11}, "volume/n8n-data.tar.gz": {"bytes": 22},
                                    "workflows.json": {"bytes": 33}}}}


def _run(tmp_path: Path, receipt: dict, backup_rc: int = 0):
    root = tmp_path / "repo"
    (root / "scripts/ops").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/ops/n8n_snapshot_now.sh", root / "scripts/ops/n8n_snapshot_now.sh")
    (root / "scripts/n8n_backup.py").write_text(f"import sys\nprint('progress')\nsys.exit({backup_rc})\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "n8n_backup_last.json").write_text(json.dumps(receipt), encoding="utf-8")
    return subprocess.run(["bash", str(root / "scripts/ops/n8n_snapshot_now.sh")], capture_output=True, text=True,
                          env={**os.environ, "N8N_BACKUP_DIR": str(out)}, timeout=60, check=False)


def test_prints_one_json_line_with_the_four_keys(tmp_path):
    p = _run(tmp_path, RECEIPT)
    assert p.returncode == 0 and "progress" not in p.stdout
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"dump_bytes": 11, "volume_bytes": 22, "export_bytes": 33,
                                    "drive_link": "https://drive.google.com/file/d/abc123/view"}


@pytest.mark.parametrize("mutate", [lambda r: r.update(ok=False), lambda r: r.update(drive={}),
                                    lambda r: r["manifest"]["members"].pop("workflows.json")])
def test_incomplete_receipt_fails_with_no_stdout(tmp_path, mutate):
    r = json.loads(json.dumps(RECEIPT))
    mutate(r)
    p = _run(tmp_path, r)
    assert p.returncode != 0 and p.stdout.strip() == ""


def test_backup_failure_propagates(tmp_path):
    p = _run(tmp_path, RECEIPT, backup_rc=1)
    assert p.returncode != 0 and p.stdout.strip() == ""
