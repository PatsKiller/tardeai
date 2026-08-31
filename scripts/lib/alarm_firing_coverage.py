"""C1 — which send_telegram call sites are covered by a firing test.

An alarm that has never been observed firing is indistinguishable from no alarm.
This makes the uncovered set a NAMED NUMBER rather than an omission.

Coverage is declared, not inferred: a test module lists the files it exercises in a
module-level COVERS list. Inferring coverage from import graphs would over-report --
importing a module is not firing its alarm, and that conflation is the defect.
"""
from __future__ import annotations

import ast
from pathlib import Path

TRANSPORT = "send_telegram"


def call_sites(scripts_dir: Path) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for path in sorted(Path(scripts_dir).rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                f = n.func
                nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
                if nm == TRANSPORT:
                    try:
                        rel = str(path.relative_to(Path(scripts_dir).parent))
                    except ValueError:
                        rel = str(path)
                    out.append((rel, n.lineno))
    return out


def declared_covers(tests_dir: Path) -> set[str]:
    """Files declared covered by a firing test, via a module-level COVERS list."""
    covered: set[str] = set()
    for path in sorted(Path(tests_dir).glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "COVERS" for t in node.targets):
                continue
            if isinstance(node.value, (ast.List, ast.Tuple)):
                for el in node.value.elts:
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        covered.add(el.value)
    return covered


def summary(scripts_dir: Path, tests_dir: Path) -> dict:
    sites = call_sites(scripts_dir)
    covered_files = declared_covers(tests_dir)
    covered = [s for s in sites if s[0] in covered_files]
    uncovered = [s for s in sites if s[0] not in covered_files]
    return {
        "transport": TRANSPORT,
        "sites_total": len(sites),
        "files_total": len({f for f, _ in sites}),
        "sites_covered": len(covered),
        "sites_uncovered": len(uncovered),
        "covered_files": sorted(covered_files),
        "uncovered": uncovered,
    }
