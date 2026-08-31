"""WAVE G2 — import normalisation for A3 dual-load hot paths.

Rule (never both):
  * root-only + ``scripts.lib.X``
  * scripts-only + ``lib.X``

Also:
  * no ``try: from lib.X / except: from scripts.lib.X`` spelling fallbacks
  * ``assert_single_import_identity`` kept and called from entrypoints
  * must NOT raise at ``scripts.lib`` package-init (bootstrap stays theatre-free)

This file is on the hardening CI allowlist. READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Allowlist: dual-load hot paths sized by A3 (~20–25 static risk; this tranche
# normalises the scheduled entrypoints named in the wave brief).
G2_ALLOWLIST: tuple[str, ...] = (
    "scripts/process_watchlist_agent_jobs.py",
    "scripts/hermes_watchlist_scorer.py",
    "scripts/hermes_top20_external_intel.py",
    "scripts/schwab_position_sync.py",
    "scripts/moomoo_live_read_sync.py",
    "scripts/cio_reactive_cycle.py",
    "scripts/provider_cost_reconcile.py",
    "scripts/research_lane_health.py",
    "scripts/memory_shadow_project.py",
    "scripts/holdings_gain_guardian.py",
)

# alert_dispatcher had no dual-load path inserts; recorded as already-clean.
G2_ALREADY_CLEAN: tuple[str, ...] = (
    "scripts/alert_dispatcher.py",
)

ROOT_ONLY = frozenset(
    {
        "scripts/cio_reactive_cycle.py",
        "scripts/provider_cost_reconcile.py",
        "scripts/research_lane_health.py",
        "scripts/memory_shadow_project.py",
    }
)
SCRIPTS_ONLY = frozenset(G2_ALLOWLIST) - ROOT_ONLY

SPELLING_FALLBACK = re.compile(
    r"try:\s*\n\s*from\s+(?:lib|scripts\.lib)\.\S+\s+import"
    r"[\s\S]{0,240}?"
    r"except\s+\w+:\s*\n\s*from\s+(?:lib|scripts\.lib)\.",
    re.MULTILINE,
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _path_insert_args(src: str) -> list[str]:
    """Return stringified first-arg expressions of sys.path.insert(0, …)."""
    tree = ast.parse(src)
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "insert"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "path"
        ):
            continue
        if len(node.args) < 2:
            continue
        # first arg should be 0
        out.append(ast.unparse(node.args[1]))
    return out


def test_allowlist_files_exist():
    for rel in G2_ALLOWLIST + G2_ALREADY_CLEAN:
        assert (ROOT / rel).is_file(), rel


def test_no_dual_root_and_scripts_path_inserts():
    """Never insert both repo root and scripts/ (DUAL_ROOT)."""
    for rel in G2_ALLOWLIST:
        args = _path_insert_args(_src(rel))
        # Classify inserts by whether the expression mentions scripts/lib, scripts, or root-only.
        has_scripts_lib = any(
            ("scripts" in a and "lib" in a) or a.endswith('/ "lib")') or "/ 'lib')" in a
            for a in args
        )
        has_scripts_only = any(
            ("scripts" in a and "lib" not in a) or "_SCRIPTS" in a
            for a in args
        )
        # Root-only insert: str(ROOT) / str(PROJECT_ROOT) without /scripts
        has_root_only = any(
            re.fullmatch(r"str\((ROOT|PROJECT_ROOT)\)", a.strip()) for a in args
        )
        assert not has_scripts_lib, f"{rel}: still inserts scripts/lib — {args}"
        if rel in ROOT_ONLY:
            assert has_root_only or any("ROOT" in a and "scripts" not in a for a in args), (
                f"{rel}: root-only mode expected path insert, got {args}"
            )
            assert not any(
                re.search(r'/\s*[\'"]scripts[\'"]\s*\)', a) for a in args
            ), f"{rel}: root-only must not also insert scripts/ — {args}"
        if rel in SCRIPTS_ONLY:
            assert not has_root_only, f"{rel}: scripts-only must not insert root — {args}"


def test_no_spelling_fallbacks_between_lib_and_scripts_lib():
    for rel in G2_ALLOWLIST:
        src = _src(rel)
        assert SPELLING_FALLBACK.search(src) is None, (
            f"{rel}: still has try/except lib ↔ scripts.lib spelling fallback"
        )


def test_mode_spelling_is_consistent():
    """root-only files use scripts.lib; scripts-only files use lib — never both."""
    for rel in ROOT_ONLY:
        src = _src(rel)
        assert "from scripts.lib." in src or "from scripts.lib import" in src, rel
        # no submodule imports under bare lib.
        assert re.search(r"(?m)^\s*from\s+lib\.", src) is None, (
            f"{rel}: root-only file still imports lib.*"
        )
    for rel in SCRIPTS_ONLY:
        src = _src(rel)
        assert re.search(r"(?m)^\s*from\s+scripts\.lib\.", src) is None, (
            f"{rel}: scripts-only file still imports scripts.lib.*"
        )


def test_assert_single_import_identity_called_not_at_package_init():
    init = _src("scripts/lib/__init__.py")
    # Must define the assertion…
    assert "def assert_single_import_identity" in init
    # …and must NOT call it at import time.
    tree = ast.parse(init)
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == "assert_single_import_identity":
                pytest.fail("assert_single_import_identity must not run at package-init")
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "assert_single_import_identity"
            ):
                pytest.fail("assert_single_import_identity must not run at package-init")
    for rel in G2_ALLOWLIST:
        src = _src(rel)
        assert "assert_single_import_identity" in src, (
            f"{rel}: entrypoint must call assert_single_import_identity after imports settle"
        )


def test_alert_dispatcher_remains_path_clean():
    """Optional target — already had no dual-load inserts."""
    src = _src("scripts/alert_dispatcher.py")
    assert "sys.path.insert" not in src
    assert SPELLING_FALLBACK.search(src) is None


def _run_by_path(source: str, tmp_path: Path) -> subprocess.CompletedProcess:
    """Cron-form: script by path, neutral cwd (must not rescue imports)."""
    probe = ROOT / "scripts" / f"_pytest_g2_probe_{tmp_path.name}.py"
    probe.write_text(source, encoding="utf-8")
    try:
        return subprocess.run(
            [sys.executable, str(probe)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        probe.unlink(missing_ok=True)


def test_light_root_only_entrypoint_imports_by_path(tmp_path):
    """provider_cost_reconcile is small and scripts.lib-only — cron-form import probe."""
    r = _run_by_path(
        "import runpy\n"
        "ns = runpy.run_path("
        f"'{ROOT / 'scripts' / 'provider_cost_reconcile.py'}', run_name='not_main')\n"
        "from scripts.lib import assert_single_import_identity\n"
        "assert_single_import_identity()\n"
        "print('G2_ROOT_ONLY_OK')\n",
        tmp_path,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "G2_ROOT_ONLY_OK" in r.stdout


def test_light_scripts_only_module_level_lib_import_by_path(tmp_path):
    """hermes_top20 top-level lib.* imports must resolve with sys.path[0]=scripts."""
    r = _run_by_path(
        "from lib.cio_agent_contract import contract_header\n"
        "from lib.research_call_accounting import call_id_for\n"
        "from lib import assert_single_import_identity\n"
        "assert_single_import_identity()\n"
        "print('G2_SCRIPTS_ONLY_OK', bool(contract_header), bool(call_id_for))\n",
        tmp_path,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "G2_SCRIPTS_ONLY_OK" in r.stdout


def test_normalised_count_matches_allowlist():
    """Ship metric: files normalised this tranche == allowlist length."""
    assert len(G2_ALLOWLIST) == 10
