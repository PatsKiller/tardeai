"""Proves the global comms production-DB guard actually fires.

The guard exists because 14 test files have written to the live database, one at
a time, each mitigated only after the fact. A guard that cannot be shown to fire
is not protection (AGENTS.md §16).
"""
import importlib
import pkgutil

import pytest

COMMS = "scripts.lib.comms"


def _modules_with_db_conn():
    pkg = importlib.import_module(COMMS)
    out = []
    for m in pkgutil.iter_modules(pkg.__path__):
        try:
            mod = importlib.import_module(f"{COMMS}.{m.name}")
        except Exception:
            continue
        if hasattr(mod, "_db_conn"):
            out.append(mod)
    return out


def test_guard_covers_every_comms_module_with_db_conn():
    mods = _modules_with_db_conn()
    assert mods, "expected comms modules exposing _db_conn"
    for mod in mods:
        assert mod._db_conn() is None, (
            f"{mod.__name__}._db_conn returned a live connection under the guard"
        )


def test_guard_is_dynamic_not_a_hardcoded_list():
    """A module added tomorrow must be guarded without editing conftest."""
    names = {m.__name__.rsplit(".", 1)[-1] for m in _modules_with_db_conn()}
    # the six known at the time the guard was written
    assert {"client", "delivery", "agent_contracts",
            "librarian", "subject_memory", "inbound"} <= names


def test_emit_receipt_persists_to_memory_not_production():
    """The exact 2026-09-05 path that wrote evt_42 to the live database."""
    from scripts.lib.comms.agent_contracts import (
        emit_consumption_receipt,
        reset_agent_contracts_memory,
    )
    reset_agent_contracts_memory()
    r = emit_consumption_receipt(
        "darwin", event_id="evt_guard_probe",
        purpose="decision_context", policy_decision="allow",
    )
    assert r.persisted == "memory", (
        "receipt persisted somewhere other than memory — the guard did not hold"
    )
    reset_agent_contracts_memory()


@pytest.mark.allow_production_db
def test_marker_opts_out_of_the_guard():
    """The escape hatch must actually restore real behaviour, or tests that
    genuinely need a database would silently assert against a stub."""
    import scripts.lib.comms.agent_contracts as ac
    assert ac._db_conn.__name__ != "<lambda>", (
        "allow_production_db marker did not restore the real _db_conn"
    )
