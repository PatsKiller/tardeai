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

#: BOTH public sending entrypoints count. send_telegram_with_id is not a second
#: transport -- telegram_alert.py:636 defines it as "send_telegram(), plus the
#: provider message id it already had", and its docstring says send_telegram's
#: own contract is deliberately untouched.
#:
#: Matching only the bare name made six real alarm sites INVISIBLE the moment
#: delivery provenance was wired into them (2026-09-22): the denominator fell
#: 188 -> 182, and five of the six lost sites were UNCOVERED ones still listed
#: in config/alarm_firing_baseline.txt. Coverage therefore "improved" because
#: the measured thing disappeared, which is the exact failure this module was
#: written to make impossible. A denominator that shrinks when code is edited
#: is not a denominator.
#:
#: send_telegram_document is counted too, by operator decision 2026-09-22. It had
#: NEVER been counted -- not on any branch -- so its 4 call sites were alarms
#: nobody could see were untested. Including it is a deliberate WIDENING of the
#: ratchet (188 -> 192), not a repair, and it was taken as an explicit decision
#: rather than left as a silent omission. It sends a document to the operator
#: over the same transport; "the alarm is a PDF" is not a reason to stop counting
#: whether it was ever observed firing.
TRANSPORT = ("send_telegram", "send_telegram_with_id", "send_telegram_document")


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
                if nm in TRANSPORT:
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


def is_covered(site: tuple[str, int], declared: set[str]) -> bool:
    """A site is covered by a whole-file entry, or by an exact `file:line` entry.

    SITE-LEVEL EXISTS BECAUSE FILE-LEVEL OVERSTATES. open_trade_monitor is honestly
    a whole file: nine of its ten sites funnel through one wrapper, so testing the
    wrapper covers them. alpaca_stop_manager is not: four sites sit in three
    different functions, and testing two of them while declaring the file covered
    would claim four alarms had been observed firing when two had. Partial coverage
    is declared per site.
    """
    path, lineno = site
    return path in declared or f"{path}:{lineno}" in declared


def summary(scripts_dir: Path, tests_dir: Path) -> dict:
    sites = call_sites(scripts_dir)
    covered_files = declared_covers(tests_dir)
    covered = [s for s in sites if is_covered(s, covered_files)]
    uncovered = [s for s in sites if not is_covered(s, covered_files)]
    return {
        "transport": TRANSPORT,
        "sites_total": len(sites),
        "files_total": len({f for f, _ in sites}),
        "sites_covered": len(covered),
        "sites_uncovered": len(uncovered),
        "covered_files": sorted(covered_files),
        "uncovered": uncovered,
    }
