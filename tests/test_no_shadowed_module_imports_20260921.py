"""A function-local import must not shadow a module-level one.

WHAT THIS CAUGHT
----------------
`scripts/claude_escalation_handler.py` imported `datetime` at module level (:27)
and AGAIN inside `_verify_remediation` (:295, added 2026-08-08 in f0446ff33 --
a commit whose subject was "Health Agent comprehensive audit ... remediation").

Python binds a name assigned anywhere in a function as local for the WHOLE
function, so that second import made every earlier `datetime` reference in the
function raise UnboundLocalError -- including the one in an `except` handler,
which therefore propagated out of `process_queue`.

The blast radius was six weeks of silence. `_verify_remediation` is what decides
whether a remediation actually worked; it could never return, so no escalation
was ever marked cleared, so every item climbed to MAX_RETRIES and paged
"AUTO-RETRY PAUSED" forever. Measured 2026-09-21: 13 components exhausting at a
flat 78/hour, 1,608 operator notifications that day, 40,444 lifetime, and a
68 MB log. The retries themselves were fine -- 2,370 succeeded since 09-15. It
was the VERIFICATION of those retries that could not run.

WHY THE TEST IS STRUCTURAL AND NOT A UNIT TEST ON ONE FUNCTION
--------------------------------------------------------------
Twice today a fix closed the tested cases and left the class open. A test that
only asserts `_verify_remediation` works would pass again the next time someone
adds a convenience import to a different function. This asserts the property:
no function-local import may rebind a name the module already imported.

Negative control: re-add `from datetime import datetime, timezone` inside any
function of a scanned file and this test fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Files whose runtime failure is silent and operator-facing. Widen deliberately;
#: a shadow in any of these costs alerting, not just a traceback.
#:
#: SCOPE, measured 2026-09-21 across all 2,711 files under scripts/:
#:   171 bare function-local re-imports shadow a module-level name
#:   162 of those are BENIGN -- the local import precedes every use
#:     4 load the name before the local import (the fatal signature)
#:     1 was a live bug: claude_escalation_handler:295
#:
#: The other 3 line-order candidates (api_v2.py:52224, crawl_v3_dashboard.py:94,
#: telegram_command_handler.py:1173, portfolio_orchestrator.py:1040) are refuted
#: by production: those functions run constantly and their logs contain ZERO
#: UnboundLocalError. Line order is only a PROXY for execution order -- the early
#: use and the local import sit on branches that do not run in the same call.
#:
#: So this list is deliberately NOT the whole repo. Scanning 79 files would turn
#: a ratchet into 170 failures that are mostly inert, and a gate that cries wolf
#: gets disabled. Widen it when a file's alerting path matters, not by default.
#:
#: Note for anyone tempted to "adopt the alias idiom" repo-wide: it is not the
#: house convention. Only 4 re-imports are aliased against 171 bare. health_agent
#: is the exception, not the rule.
SCANNED = [
    "scripts/claude_escalation_handler.py",
    "scripts/pipeline_freshness_monitor.py",
    "scripts/telegram_alert.py",
    "scripts/disk_pressure_guard.py",
    "scripts/agent_worktree_retention.py",
]


def _imported_names(node: ast.AST) -> set[str]:
    """Names bound by import statements directly under `node`."""
    out: set[str] = set()
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Import):
            for a in child.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(child, ast.ImportFrom):
            for a in child.names:
                out.add(a.asname or a.name)
    return out


def _nested_import_names(fn: ast.AST) -> dict[str, int]:
    """Every name bound by an import ANYWHERE inside a function, with its line.

    Walks the whole subtree on purpose: the 2026-08-08 defect sat three levels
    deep (try -> if -> import) and a shallow child scan would have missed it,
    while Python's scoping does not care how deep it is.
    """
    out: dict[str, int] = {}
    for node in ast.walk(fn):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                name = (a.asname or a.name).split(".")[0]
                out.setdefault(name, node.lineno)
    return out


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


@pytest.mark.parametrize("rel", SCANNED)
def test_no_function_shadows_a_module_level_import(rel: str) -> None:
    path = ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} not present in this tree")

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_level = _imported_names(tree)

    offenders = []
    for fn in _functions(tree):
        for name, lineno in _nested_import_names(fn).items():
            if name in module_level:
                offenders.append(f"{rel}:{lineno} `{name}` in {fn.name}() "
                                 f"shadows the module-level import")

    assert not offenders, (
        "a function-local import rebinds a module-level name, which makes that "
        "name local for the ENTIRE function and raises UnboundLocalError on every "
        "earlier use:\n  " + "\n  ".join(offenders)
    )


def test_the_detector_can_actually_fail() -> None:
    """Positive control: prove this test would have caught the real defect.

    A detector that has never failed is indistinguishable from no detector --
    the same rule the alarm-firing ratchet applies to alerts.
    """
    source = (
        "from datetime import datetime\n"
        "def f():\n"
        "    try:\n"
        "        if True:\n"
        "            from datetime import datetime\n"
        "            return datetime.now()\n"
        "    except Exception:\n"
        "        return datetime.now()\n"
    )
    tree = ast.parse(source)
    module_level = _imported_names(tree)
    found = [
        name
        for fn in _functions(tree)
        for name in _nested_import_names(fn)
        if name in module_level
    ]
    assert found == ["datetime"], f"detector failed to see the shadow: {found}"


def _load_handler_from_this_tree():
    """Load THIS tree's handler by path, never whatever sys.modules already holds.

    Found the hard way: with `importorskip`, this test PASSED alone and FAILED in
    a batch. A sibling test (test_escalation_verify_autonomy.py) imports
    `claude_escalation_handler` first, from a different tree, and the cached
    module wins -- so the test silently asserted against a copy chosen by test
    ORDERING rather than the file under test. In CI it would have gone green by
    luck. A check whose subject depends on import order is not a check.
    """
    import importlib.util
    import sys

    path = ROOT / "scripts" / "claude_escalation_handler.py"
    if not path.is_file():  # pragma: no cover
        pytest.skip("handler not present in this tree")
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("_handler_under_test", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - environmental
        pytest.skip(f"handler not importable here: {type(exc).__name__}: {exc}")
    assert module.__file__ == str(path), f"loaded the wrong copy: {module.__file__}"
    return module


def test_verify_remediation_survives_the_session_branch() -> None:
    """Behavioural control: the exact call that crashed must not raise.

    Production traceback, 2026-09-21:
      File "claude_escalation_handler.py", line 309, in _verify_remediation
        today = datetime.now().date().isoformat()
      UnboundLocalError: cannot access local variable 'datetime'
    """
    handler = _load_handler_from_this_tree()

    # The component string is load-bearing. _finding_type_from_component() is
    # `health:category:type -> type` and returns "" for anything not starting
    # with "health:", which short-circuits to no_verify_unknown_component and
    # never reaches the crashing branch. A first draft of this test passed
    # "test:<ftype>" and was therefore vacuous -- it went green against the
    # unpatched file. These are real component strings, observed in the live
    # Tier1 queue.
    for ftype in ("trade_ai_session_stale", "trade_ai_session_missing",
                  "orchestrator_setups_stale"):
        component = f"health:pipeline_freshness:{ftype}"
        assert handler._finding_type_from_component(component) == ftype, \
            "component shape no longer reaches the branch this test pins"
        try:
            handler._verify_remediation({"component": component})
        except UnboundLocalError as exc:  # pragma: no cover - the bug itself
            pytest.fail(f"{component}: {exc}")
        except Exception:
            # Any OTHER failure is environmental (no DB, no queue file) and is
            # not what this test pins. Only UnboundLocalError is the defect.
            pass
