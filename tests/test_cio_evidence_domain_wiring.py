"""The evidence gate blocked 54 of 55 CIO runs. None of it was the gate's fault.

Three REQUIRED domains resolved DATA_UNAVAILABLE for three different wiring
reasons, and the fail-closed gate correctly refused to synthesise without them.
These tests pin the wiring, not the gate: the gate's behaviour is unchanged and
must stay unchanged.
"""
from __future__ import annotations

import ast
from pathlib import Path



ROOT = Path(__file__).resolve().parent.parent


def _module_functions(relpath: str) -> set[str]:
    tree = ast.parse((ROOT / relpath).read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_snapshot_collector_name_exists_on_the_adapter_module():
    """The snapshot resolves collectors by exact name via getattr.

    `cio_financial_snapshot` asked this module for `get_watch_intelligence`.
    The module defined `list_watch_intelligence` and
    `project_watch_intelligence_for_cio` but never that name, so getattr
    returned None, no collector was registered, and the domain reported
    `watch_intelligence_collector_not_resolved_at_runtime` on every run while
    25 live cards sat behind it.
    """
    snapshot = (ROOT / "scripts/lib/cio_financial_snapshot.py").read_text(encoding="utf-8")
    assert '"watch_intelligence": "get_watch_intelligence"' in snapshot, (
        "the snapshot's expected collector name changed; update this guard"
    )
    assert "get_watch_intelligence" in _module_functions(
        "scripts/lib/data_broker/watch_intelligence.py"
    ), "snapshot resolves get_watch_intelligence by name; it must exist on the module"


def test_every_external_adapter_function_actually_exists():
    """Guard the whole mapping, not just the one that was broken.

    A name in `_EXTERNAL_ADAPTER_FUNCTIONS` with no matching function fails
    silently — `except (ImportError, AttributeError): pass` — and the domain
    simply reports unavailable forever. That is how this one survived.
    """
    import re

    src = (ROOT / "scripts/lib/cio_financial_snapshot.py").read_text(encoding="utf-8")
    modules = dict(re.findall(
        r'"(\w+)":\s*"(scripts\.lib\.data_broker\.\w+)"', src))
    functions = dict(re.findall(r'"(\w+)":\s*"(get_\w+)"', src))

    # Same defect, NOT fixed in this tranche and deliberately named rather than
    # silently excluded: `analyst_detail` and `reentry_decision_desk` have no
    # zero-arg collector, and `catalyst_record.get_catalyst_record(db_query,
    # symbol)` requires arguments the snapshot never passes. None of the three is
    # REQUIRED for the run purposes that are currently blocked, and writing
    # wrappers for adapters whose data path is unverified would trade a visible
    # gap for a plausible-looking empty one. This guard still fails on any NEW
    # instance.
    known_broken = {"analyst_actions", "reentry"}

    missing = []
    for domain, fn_name in functions.items():
        if domain in known_broken:
            continue
        module_path = modules.get(domain)
        if not module_path:
            continue
        relpath = module_path.replace(".", "/") + ".py"
        if not (ROOT / relpath).exists():
            missing.append(f"{domain}: module {relpath} absent")
            continue
        if fn_name not in _module_functions(relpath):
            missing.append(f"{domain}: {relpath} has no {fn_name}()")

    assert not missing, "external adapter collectors that will never resolve: " + "; ".join(missing)


def test_wake_dispatch_passes_the_stores_the_snapshot_collects_from():
    """health_data_quality and operator_profile come only from these stores.

    The snapshot collects them from the objects handed to CIORunWorker. The
    production wake-dispatch entrypoint passed neither, so both REQUIRED domains
    were DATA_UNAVAILABLE on every run — the gate was being asked about stores
    nobody gave it.
    """
    src = (ROOT / "scripts/cio_wake_dispatch_entrypoint.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    call = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "CIORunWorker"):
            call = node
            break
    assert call is not None, "CIORunWorker construction not found"
    kwargs = {kw.arg for kw in call.keywords}

    assert "health_boundary" in kwargs, "health_data_quality has no source without this"
    assert "operator_profile" in kwargs, "operator_profile has no source without this"


def test_store_construction_is_fail_soft():
    """A store that cannot be built must leave its domain unavailable.

    Falling back to None reproduces the pre-existing behaviour — the gate blocks
    honestly. What must never happen is a fabricated store that reports a domain
    available when it has no data behind it.
    """
    src = (ROOT / "scripts/cio_wake_dispatch_entrypoint.py").read_text(encoding="utf-8")
    segment = src.split("CIOHealthBoundary()", 1)[1][:400]
    assert "except Exception" in segment
    assert "= None" in segment


def test_the_gate_itself_is_untouched():
    """This work fixes producers. Weakening the gate would be the wrong fix.

    The gate blocks on any REQUIRED domain that is missing, stale, errored or
    conflicted. If that changes, these domain fixes stop being a safety-neutral
    change and this test should fail loudly.
    """
    src = (ROOT / "scripts/lib/cio_run_worker.py").read_text(encoding="utf-8")
    gate = src.split("def _check_evidence_gate", 1)[1].split("\n    def ", 1)[0]

    assert 'state == "DATA_UNAVAILABLE"' in gate
    assert 'elif state == "STALE"' in gate
    assert "missing_required or stale_required or error_required" in gate
