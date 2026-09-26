"""PR fast core: test-impact selection and risk tiers (scripts/lib/test_impact.py).

2026-09-25 (operator: "faster feedback with appropriate governance"; budget 5
minutes wall clock on a GitHub runner). The pr profile runs a SELECTION; these
tests hold what may never be dropped from it and what must be listed when it is.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("test_impact_mod", ROOT / "scripts" / "lib" / "test_impact.py")
ti = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ti)
spec2 = importlib.util.spec_from_file_location("run_cio_hardening_ci", ROOT / "scripts" / "run_cio_hardening_ci.py")
ci = importlib.util.module_from_spec(spec2)
assert spec2.loader is not None
spec2.loader.exec_module(ci)

TIERS = ti.load_tiers()

# The sensitive paths PR #1232 (AGENTS.md 1.3.0, PROPOSED) lists in CODEOWNERS.
CODEOWNERS_1232 = [
    "AGENTS.md",
    "AI_WORK_POLICY.md",
    "CLAUDE.md",
    ".cursor/hooks/x.sh",
    ".github/workflows/x.yml",
    "docs/governance/x.md",
    "bin/guard",
    "scripts/lib/guard_remote_approval.py",
    "scripts/lib/guard_push_auth.py",
    ".githooks/pre-push",
    "scripts/check_no_secrets.py",
    "scripts/brokers/x.py",
    "scripts/schwab_transport.py",
    "scripts/moomoo/x.py",
    "scripts/active_trader/x.py",
    "scripts/lib/trading_session_grant.py",
    "scripts/validate_schwab_write_policy.py",
    "scripts/lib/cio_instrument_record.py",
    "config/data_source_authority.json",
    "scripts/lib/cio_memory_integration.py",
    "sql/x.sql",
    "migrations/x.sql",
]


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def test_glob_star_stays_in_one_directory_and_double_star_spans():
    assert ti.glob_to_re("scripts/*schwab*").match("scripts/schwab_transport.py")
    assert not ti.glob_to_re("scripts/*schwab*").match("scripts/lib/deep/schwab.py")
    assert ti.glob_to_re("docs/**").match("docs/a/b/c.md")
    assert ti.glob_to_re("**/*.md").match("README.md")
    assert ti.glob_to_re("**/*.md").match("a/b/README.md")


@pytest.mark.parametrize(
    ("path", "tier"),
    [
        ("AGENTS.md", "high"),
        ("docs/governance/ENGINEERING_STANDARD.md", "high"),
        ("sql/r10_m2_isolated_benchmark.sql", "high"),
        ("config/lane_registry.json", "high"),
        ("scripts/run_cio_hardening_ci.py", "high"),
        ("requirements.txt", "high"),
        ("docs/ops/RUNBOOK.md", "low"),
        ("README.txt", "low"),
        ("scripts/lib/comms_editor.py", "medium"),
        ("apps/command-center-v3/src/App.tsx", "medium"),
    ],
)
def test_classify(path, tier):
    assert ti.classify(path, TIERS)[0] == tier


def test_every_codeowners_path_is_high_risk():
    """CODEOWNERS (PR #1232) and the tiers must agree: an owned path is HIGH."""
    paths = list(CODEOWNERS_1232)
    co = ROOT / ".github" / "CODEOWNERS"
    if co.is_file():
        for line in co.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pat = line.split()[0].lstrip("/")
                paths.append(pat + "x.py" if pat.endswith("/") else pat)
    low = [p for p in paths if ti.classify(p, TIERS)[0] != "high"]
    assert low == []


def test_every_gate_named_in_the_tiers_exists():
    names = {n for n, _ in ci.GATES}
    named = set(TIERS["smoke_gates"]) | set(TIERS["low"]["gates"])
    for spec_ in TIERS["high"].values():
        named |= set(spec_["gates"])
    assert sorted(named - names) == []


def test_worst_case_mandatory_set_fits_the_budget():
    """Smoke + every HIGH category's gates must fit, or the 5-minute check cannot hold."""
    gf = dict(ci.GATES)
    hints = ci.load_duration_hints()
    gates = set(TIERS["smoke_gates"]) | {g for s in TIERS["high"].values() for g in s["gates"]}
    files = {p for g in gates for p in gf[g]}
    assert sum(hints.get(p, ci.DEFAULT_FILE_SECONDS) for p in files) <= TIERS["budget_seconds"]


def test_impact_map_follows_imports_paths_and_transitive_importers(tmp_path):
    root = _write(
        tmp_path,
        {
            "scripts/lib/__init__.py": "",
            "scripts/lib/b.py": "X = 1\n",
            "scripts/lib/a.py": "from lib import b\n",
            "scripts/c.py": "print(1)\n",
            "tests/test_a.py": "from scripts.lib.a import *\n",
            "tests/test_c.py": 'import subprocess\nsubprocess.run(["python3", "scripts/c.py"])\n',
            "tests/test_by_name.py": 'SPEC = "c.py"\n',
            "tests/test_other.py": "import os\n",
        },
    )
    m = ti.build_map(root)
    assert ti.impacted_tests(["scripts/lib/b.py"], m) == {"tests/test_a.py": 2}
    assert set(ti.impacted_tests(["scripts/c.py"], m)) == {"tests/test_c.py", "tests/test_by_name.py"}
    assert ti.impacted_tests(["tests/test_other.py"], m) == {"tests/test_other.py": 0}


def test_cache_is_rebuilt_when_a_file_changes(tmp_path):
    root = _write(tmp_path, {"scripts/x.py": "A = 1\n", "tests/test_x.py": "import x\n"})
    cache = tmp_path / "cache.json"
    _m, st = ti.load_map(root, cache)
    assert st == "rebuilt"
    _m, st = ti.load_map(root, cache)
    assert st == "cache"
    (root / "scripts" / "y.py").write_text("B = 2\n", encoding="utf-8")
    _m, st = ti.load_map(root, cache)
    assert st == "rebuilt"


def _sel(changed, **kw):
    gates = [
        ("smoke", ["tests/test_s.py"]),
        ("big", [f"tests/test_big{i}.py" for i in range(5)]),
        ("mid", ["tests/test_m.py"]),
    ]
    tiers = {
        "budget_seconds": kw.pop("budget", 100),
        "smoke_gates": ["smoke"],
        "high": {"policy": {"globs": ["AGENTS.md"], "gates": ["mid"]}},
        "low": {"globs": ["docs/**"], "gates": []},
    }
    rdeps = {"scripts/lib/core.py": [f"tests/test_big{i}.py" for i in range(5)] + ["tests/test_m.py"]}
    hints = {f"tests/test_big{i}.py": 30.0 for i in range(5)}
    return ti.select(changed, gates, impact_map={"rdeps": rdeps}, tiers=tiers, hints=hints, **kw)


def _files(sel):
    return {f for _n, fs in sel["gates"] for f in fs}


def test_docs_only_change_runs_smoke_only():
    sel = _sel(["docs/a.md"])
    assert sel["tier"] == "low"
    assert _files(sel) == {"tests/test_s.py"}


def test_over_budget_tests_are_deferred_and_listed_never_silently_dropped():
    sel = _sel(["scripts/lib/core.py"], budget=70)
    ran = _files(sel)
    reachable = {f"tests/test_big{i}.py" for i in range(5)} | {"tests/test_m.py"}
    assert (reachable & ran) | set(sel["deferred"]) == reachable
    assert sel["deferred"]  # 5 x 30 s cannot fit in 70 s
    assert sel["estimate_seconds"] <= 70


def test_high_path_runs_its_gates_even_over_budget():
    sel = _sel(["AGENTS.md"], budget=0)
    assert sel["tier"] == "high"
    assert "tests/test_m.py" in _files(sel)
    assert sel["high"] == {"policy": ["AGENTS.md"]}


def test_changed_test_file_always_runs():
    sel = _sel(["tests/test_big3.py"], budget=0)
    assert "tests/test_big3.py" in _files(sel)


def test_selection_json_round_trips():
    sel = _sel(["scripts/lib/core.py"])
    assert json.loads(json.dumps(sel, default=list))["tier"] == "medium"
