"""check_test_host_paths: new live-host paths in tests fail; the baseline only shrinks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_test_host_paths", ROOT / "scripts" / "check_test_host_paths.py")
chk = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(chk)

LIVE = "/home/johnclaw/" + "trade-ai-releases/portfolio-server/CURRENT"  # split so this file never matches itself


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


def test_repo_has_no_new_violations():
    assert chk.new_violations(chk.scan(), chk.load_baseline()) == []


def test_new_file_with_live_path_fails(tmp_path):
    root = _repo(tmp_path, {"tests/test_new.py": f'P = "{LIVE}"\n'})
    assert chk.new_violations(chk.scan(root), {}) == ["tests/test_new.py: 1 live-host path(s), baseline allows 0"]


def test_more_occurrences_than_baseline_fails_and_fewer_passes(tmp_path):
    root = _repo(tmp_path, {"tests/test_old.py": f'A = "{LIVE}"\nB = "{LIVE}"\n'})
    assert chk.new_violations(chk.scan(root), {"tests/test_old.py": 1})
    assert chk.new_violations(chk.scan(root), {"tests/test_old.py": 2}) == []
    assert chk.new_violations(chk.scan(root), {"tests/test_old.py": 5}) == []


def test_tmp_path_style_paths_are_not_flagged(tmp_path):
    root = _repo(tmp_path, {"tests/test_ok.py": 'P = tmp_path / "trade-ai-releases" / "CURRENT"\n'})
    assert chk.scan(root) == {}
