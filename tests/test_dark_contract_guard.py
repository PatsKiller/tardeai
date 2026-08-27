"""The gate must reach the same verdict everywhere.

The first CI run of this guard failed on commits that passed locally. Cause:
`scheduled_scripts()` shelled out to `crontab -l`, so a script scheduled on the
developer's machine was skipped locally and flagged in CI, where no crontab
exists. It also matched commented-out cron lines, counting a switched-off job
as scheduled. Inputs are now repo-only.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts/check_dark_contracts.py"


def _guard():
    spec = importlib.util.spec_from_file_location("dark_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_guard_reads_nothing_outside_the_repo():
    """No subprocess, no crontab, no $HOME -- or the verdict moves per machine."""
    src = GUARD.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {n.names[0].name.split(".")[0]
                for n in ast.walk(tree) if isinstance(n, ast.Import)}
    imported |= {n.module.split(".")[0]
                 for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "subprocess" not in imported, "shelling out makes the gate machine-dependent"

    # Check CODE, not prose: the module docstring explains the crontab history
    # on purpose, and a raw text search hits its own explanation -- the same
    # self-reference trap that made the guard report `inherited: 0`.
    code = "\n".join(
        ast.unparse(n) for n in tree.body
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str))
    )
    for banned in ("crontab", "Path.home", "os.environ", "getenv"):
        assert banned not in code, f"{banned} makes the verdict machine-dependent"


def test_a_scheduled_entrypoint_is_excused_by_declaration():
    g = _guard()
    assert g.declared_module_string("scripts/build_lesson_candidates.py",
                                    "SCHEDULED_ENTRYPOINT")
    assert g.declared_module_string("scripts/resolve_due_checkpoints.py",
                                    "SCHEDULED_ENTRYPOINT")


def test_a_disabled_job_is_not_treated_as_scheduled():
    """research_lane_health's cron line is commented out; the crontab-reading
    version counted it as wired. It must be declared dark, not scheduled."""
    g = _guard()
    assert g.declared_module_string("scripts/research_lane_health.py",
                                    "SCHEDULED_ENTRYPOINT") is None
    assert g.declared_reason("scripts/research_lane_health.py")


def test_the_gate_is_green_on_this_tree():
    assert _guard().audit()["new"] == []


def test_the_gate_still_fails_on_a_new_dark_contract(tmp_path, monkeypatch):
    """A guard that can only pass is not a guard."""
    g = _guard()
    probe = ROOT / "scripts/lib/_dark_guard_probe_tmp.py"
    probe.write_text('SCHEMA = "ProbeContract@v1"\n', encoding="utf-8")
    try:
        new = {r["module"] for r in g.audit()["new"]}
        assert "scripts/lib/_dark_guard_probe_tmp.py" in new
    finally:
        probe.unlink()
    assert g.audit()["new"] == []
