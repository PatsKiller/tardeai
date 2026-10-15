"""Hermetic tests for scripts/report_n8n_env_enforce_readiness.py (audit 2026-10-15 DD02).

Every case builds a tiny fake repo under tmp_path: a stub executor declaring CHILD_ENV_BASE_NAMES, lane scripts and
an allowlist. Nothing reads the real env, a credential, the network or the live allowlist (except the last test,
which only runs the analyzer over the committed tree and checks coverage, never a verdict).
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import report_n8n_env_enforce_readiness as R  # noqa: E402

EXECUTOR_STUB = textwrap.dedent(
    """
    ENV_BOUND_NAMES_ENV = "TRADEAI_ENV_BOUND_NAMES"
    CHILD_ENV_BASE_NAMES = frozenset({"PATH", "HOME", ENV_BOUND_NAMES_ENV})
    """
)


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    (tmp_path / "scripts" / "lib").mkdir(parents=True)
    (tmp_path / "scripts" / "n8n_run_executor.py").write_text(EXECUTOR_STUB, encoding="utf-8")
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


def _lane(lane_id: str, script: str, names: list[str], mode: str = "report", **extra) -> dict:
    return {
        "lane_id": lane_id,
        "command": extra.pop("command", ["$PY", script]),
        "env_names": names,
        "env_allowlist_mode": mode,
        "lock": "/tmp/x.lock",
        "lock_kind": extra.pop("lock_kind", "flock"),
        **extra,
    }


def _one(tmp_path: Path, files: dict[str, str], lane: dict) -> dict:
    root = _repo(tmp_path, files)
    report = R.build_report(root, {"as_of": "t", "lanes": [lane]})
    return report["lanes"][0]


def test_base_names_are_read_from_the_executor_source(tmp_path):
    root = _repo(tmp_path, {})
    assert R._executor_base_names(root) == {"PATH", "HOME", "TRADEAI_ENV_BOUND_NAMES"}


def test_declared_literal_reads_are_ready_now(tmp_path):
    r = _one(
        tmp_path,
        {
            "scripts/a.py": 'import os\nX = os.getenv("DB_HOST")\nY = os.environ["DB_USER"]\nZ = os.environ.get("HOME")\n'
        },
        _lane("a", "scripts/a.py", ["DB_HOST", "DB_USER"]),
    )
    assert r["verdict"] == "READY_NOW" and r["flip_candidate"] and r["reasons"] == []


def test_missing_required_and_defaulted_names_block(tmp_path):
    r = _one(
        tmp_path,
        {"scripts/a.py": 'import os\nX = os.environ["SECRET_X"]\nY = os.getenv("OPT_Y", "1")\n'},
        _lane("a", "scripts/a.py", []),
    )
    assert r["verdict"] == "BLOCKED"
    assert r["missing_required"] == ["SECRET_X"] and r["missing_defaulted"] == ["OPT_Y"]
    assert {"missing_required_names", "missing_defaulted_names"} <= set(r["reasons"])


def test_constant_resolved_name_counts_as_literal(tmp_path):
    r = _one(
        tmp_path,
        {"scripts/a.py": 'import os\nK = "DB_HOST"\nv = os.getenv(K)\n'},
        _lane("a", "scripts/a.py", ["DB_HOST"]),
    )
    assert r["verdict"] == "READY_NOW"


def test_dynamic_read_blocks(tmp_path):
    r = _one(
        tmp_path,
        {"scripts/a.py": "import os\ndef f(k):\n    return os.environ.get(k)\n"},
        _lane("a", "scripts/a.py", []),
    )
    assert "dynamic_env_reads" in r["reasons"] and r["dynamic_reads"] == 1


def test_whole_file_loaders_block(tmp_path):
    body = (
        "import os\nfrom dotenv import load_dotenv\nload_dotenv()\nos.environ.update({})\n"
        "for k, v in []:\n    os.environ[k] = v\n"
    )
    r = _one(tmp_path, {"scripts/a.py": body}, _lane("a", "scripts/a.py", []))
    assert "unbounded_env_loader" in r["reasons"] and len(r["unbounded_loader_sites"]) == 3


def test_setdefault_narrowed_by_env_keys_is_not_a_loader(tmp_path):
    body = 'import os\n_ENV_KEYS = frozenset({"DB_PASSWORD"})\nfor k in []:\n    os.environ.setdefault(k, "")\n'
    r = _one(tmp_path, {"scripts/a.py": body}, _lane("a", "scripts/a.py", ["DB_PASSWORD"]))
    assert r["verdict"] == "READY_NOW"


def test_checkout_env_file_fallback_is_a_residual_not_a_block(tmp_path):
    body = 'import os\nfrom pathlib import Path\npw = os.environ.get("DB_PASSWORD") or Path(".env").read_text()\n'
    r = _one(tmp_path, {"scripts/a.py": body}, _lane("a", "scripts/a.py", ["DB_PASSWORD"]))
    assert r["verdict"] == "READY_WITH_RESIDUAL"
    assert r["residuals"] == ["checkout_env_file_fallback"]
    assert not r["flip_candidate"] and r["flip_candidate_with_residual"]


def test_closure_follows_absolute_lazy_and_relative_imports(tmp_path):
    files = {
        "scripts/a.py": "def f():\n    from lib import b\n",
        "scripts/lib/b.py": "from .c import thing\n",
        "scripts/lib/c.py": 'import os\nthing = os.getenv("DEEP_NAME")\n',
    }
    r = _one(tmp_path, files, _lane("a", "scripts/a.py", []))
    assert r["closure_modules"] == 3
    assert r["missing_defaulted"] == ["DEEP_NAME"]  # the EF-1 class: a relative import the old test skipped


def test_env_bootstrap_is_bounded_and_not_descended(tmp_path):
    files = {
        "scripts/a.py": "from lib import env_bootstrap\nenv_bootstrap.load_env()\n",
        "scripts/lib/env_bootstrap.py": "import os\nfor k in []:\n    os.environ[k] = 'v'\n",
    }
    r = _one(tmp_path, files, _lane("a", "scripts/a.py", []))
    assert r["verdict"] == "READY_NOW" and r["closure_modules"] == 2


def test_spawned_script_literals_are_counted_not_descended(tmp_path):
    files = {
        "scripts/a.py": 'ARGV = ["python", "scripts/b.py"]\n',
        "scripts/b.py": 'import os\nos.environ["NEVER_SEEN"]\n',
    }
    r = _one(tmp_path, files, _lane("a", "scripts/a.py", []))
    assert r["spawn_refs"] == 1 and r["missing_required"] == []


def test_inline_env_and_safe_flock_names(tmp_path):
    files = {"scripts/a.py": 'import os\nos.environ["SCALP_HOT_TIER"]\n'}
    lane = _lane(
        "a",
        "scripts/a.py",
        [],
        command=["env", "SCALP_HOT_TIER=1", "$PY", "scripts/a.py"],
        lock_kind="safe_flock",
    )
    r = _one(tmp_path, files, lane)
    assert r["missing_required"] == ["PROJECT_ROOT", "SAFE_FLOCK_LOG_DIR"]  # the safe_flock wrapper's names


def test_enforced_lane_that_is_blocked_is_flagged(tmp_path):
    r = _one(
        tmp_path, {"scripts/a.py": 'import os\nos.environ["X_NAME"]\n'}, _lane("a", "scripts/a.py", [], mode="enforce")
    )
    assert r["enforced_but_blocked"] and not r["flip_candidate"]


def test_missing_env_names_list_blocks(tmp_path):
    lane = _lane("a", "scripts/a.py", [])
    lane.pop("env_names")
    r = _one(tmp_path, {"scripts/a.py": "x = 1\n"}, lane)
    assert "env_names_missing" in r["reasons"]


def test_outputs_are_names_only_and_the_diff_is_a_proposal(tmp_path):
    root = _repo(tmp_path, {"scripts/a.py": 'import os\nos.getenv("DB_HOST")\n'})
    allow = {"schema": "N8nRunAllowlist@v1", "as_of": "t", "lanes": [_lane("a", "scripts/a.py", ["DB_HOST"])]}
    (root / "config").mkdir()
    (root / "config" / "n8n_run_allowlist.json").write_text(json.dumps(allow), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    rc = R.main(
        [
            "--root",
            str(root),
            "--json",
            str(out / "r.json"),
            "--markdown",
            str(out / "r.md"),
            "--diff",
            str(out / "r.diff"),
        ]
    )
    assert rc == 0
    rep = json.loads((out / "r.json").read_text())
    assert rep["schema"] == R.SCHEMA and rep["summary"]["flip_candidates"] == ["a"]
    diff = (out / "r.diff").read_text()
    assert diff.startswith("# PROPOSED — not applied") and '+  "env_allowlist_mode": "enforce",' in diff
    assert "READY_NOW" in (out / "r.md").read_text()
    # never the allowlist itself
    assert json.loads((root / "config" / "n8n_run_allowlist.json").read_text()) == allow


def test_committed_tree_measurement_covers_every_allowlist_lane():
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    report = R.build_report(ROOT)
    assert {r["lane_id"] for r in report["lanes"]} == {e["lane_id"] for e in allow["lanes"]}
    assert report["summary"]["enforce"] + report["summary"]["report"] == len(allow["lanes"])
    for r in report["lanes"]:
        assert r["verdict"] in {"READY_NOW", "READY_WITH_RESIDUAL", "BLOCKED"}
