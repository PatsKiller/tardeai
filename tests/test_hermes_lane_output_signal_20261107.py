"""QUALITY ROUND 2 items 1-2 (2026-11-07): two hermes lanes declared an artifact the grader could not resolve.

`scripts/lib/run_quality.gather` resolves a lane's `output_signal.path` as
`persistent_state_root / path`, and only treats the result as the lane's output when the resolved path is under
`data/` or `logs/`. Both scripts wrote their report ONLY into the checkout's `docs/…` directory, so the resolved
path was `None`, the check read `declared output file is missing`, and the lane graded EMPTY on a run that had,
in fact, written its report at that very minute.

These tests pin the coupling (module constant == registry declaration), the served-copy write, and that the
dry run still writes nothing. Everything runs against temporary directories; the repo is public, so no host
path appears in any committed string.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

CASES = [
    # module (no .py), lane id, dry-run argv, write callable name
    ("hermes_backlog_health_check", "hermes-backlog-health-check", ["--dry-run"], "write_summary"),
    ("hermes_autonomous_librarian_backlog_loop", "hermes-librarian-backlog-loop", ["--dry-run"], "write_report"),
]


def _load(name: str):
    spec = importlib.util.spec_from_file_location("qr2_" + name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _registry_row(lane_id: str) -> dict:
    doc = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    rows = [r for r in doc["lanes"] if r["lane_id"] == lane_id]
    assert len(rows) == 1, lane_id
    return rows[0]


@pytest.fixture(scope="module")
def modules():
    return {name: _load(name) for name, *_ in CASES}


@pytest.mark.parametrize("name,lane_id,argv,writer", CASES)
def test_the_module_declares_the_path_the_registry_declares(modules, name, lane_id, argv, writer):
    module = modules[name]
    signal = _registry_row(lane_id)["output_signal"]
    assert signal["kind"] in {"file_mtime", "json_key"}
    assert signal["path"] == module.RESULT_REL, (signal["path"], module.RESULT_REL)
    assert signal["path"].endswith("/" + module.RESULT_NAME)
    # The declared path must be one the grader can resolve: relative, under data/ (or logs/), never a home path.
    rel = Path(signal["path"])
    assert not rel.is_absolute() and not str(rel).startswith("~"), signal["path"]
    assert rel.parts[0] in {"data", "logs"}, signal["path"]


@pytest.mark.parametrize("name,lane_id,argv,writer", CASES)
def test_the_writer_puts_the_declared_artifact_where_the_grader_looks(
    modules, tmp_path, monkeypatch, name, lane_id, argv, writer
):
    module = modules[name]
    state = tmp_path / "state"
    # The state-root parent exists on the host (durable_write_targets skips a target whose parent is absent and
    # whose root carries no provisioning stamp), so create it here the same way.
    (state / Path(module.RESULT_REL).parent).mkdir(parents=True, exist_ok=True)
    (state / "PERSISTENT_STATE_ROOT.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(state))

    targets = module.result_targets()
    assert targets, "no write target resolved"
    served, *rest = targets
    assert served == state / module.RESULT_REL, served

    docs = tmp_path / "docs_copy"
    payload = {"synthetic": True, "lane": lane_id}
    written = getattr(module, writer)(payload, targets=[served], docs_dir=docs)

    assert str(served) in written and str(docs / module.RESULT_NAME) in written
    assert json.loads(served.read_text(encoding="utf-8")) == payload
    assert json.loads((docs / module.RESULT_NAME).read_text(encoding="utf-8")) == payload
    # This is the exact predicate run_quality.gather applies before it will read an mtime at all.
    base = state.resolve()
    assert served.resolve().is_relative_to(base / "data") or served.resolve().is_relative_to(base / "logs")


@pytest.mark.parametrize("name,lane_id,argv,writer", CASES)
def test_the_dry_run_writes_nothing(modules, tmp_path, monkeypatch, name, lane_id, argv, writer):
    module = modules[name]
    state = tmp_path / "state"
    (state / Path(module.RESULT_REL).parent).mkdir(parents=True, exist_ok=True)
    (state / "PERSISTENT_STATE_ROOT.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(state))
    monkeypatch.chdir(tmp_path)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}

    assert module.main(list(argv)) == 0
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert after - before == set(), "the dry run wrote files"
    assert not (state / module.RESULT_REL).exists(), "the dry run wrote the declared artifact"


@pytest.mark.parametrize("name,lane_id,argv,writer", CASES)
def test_the_old_declarations_are_the_ones_the_grader_could_not_resolve(modules, name, lane_id, argv, writer):
    """Guard the shape of the defect itself: these are the two declarations that produced the EMPTY grade."""
    module = modules[name]
    current = module.RESULT_REL
    for broken in (f"~/{current}", f"docs/{current}"):
        rel = Path(broken)
        resolvable = (
            not rel.is_absolute()
            and not str(rel).startswith("~")
            and rel.parts[0] in {"data", "logs"}
        )
        assert resolvable is False, broken
    assert Path(current).parts[0] == "data"
