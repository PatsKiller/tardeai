"""An unreadable identity spine must not look like an unregistered entity.

`resolve_entity` consults the registry before falling back to the symbol.
The fallback is right -- an outage must not block a lineage write, and it must
never mint a plausible GUID for the wrong company. But the failure was silent,
so two different states both surfaced as entity_type=UNRESOLVED:

    the registry says this symbol is unknown   -> fixed by registering it
    the registry could not be read at all      -> an outage; registering nothing helps

Only one of those is actionable by the operator, and they were indistinguishable.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_canonical_identity import (  # noqa: E402
    ENTITY_SECURITY, ENTITY_UNRESOLVED, resolve_entity,
)


def test_an_unreadable_registry_is_marked_not_silently_unresolved(monkeypatch):
    import scripts.lib.identity_registry as reg
    monkeypatch.setattr(reg, "load_cached",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("registry gone")))

    out = resolve_entity({"symbol": "NVDA"})
    assert out["subject_guid"] is None, "never mint a GUID when the spine is unreadable"
    assert out["entity_type"] == ENTITY_UNRESOLVED
    assert "OSError" in out["identity_lookup_failed"]


def test_a_genuinely_unregistered_symbol_carries_no_failure_marker(monkeypatch):
    """The marker means 'could not look up', not 'looked up and found nothing'."""
    import scripts.lib.identity_registry as reg
    monkeypatch.setattr(reg, "load_cached", lambda *a, **k: {})
    monkeypatch.setattr(reg, "lookup_symbol", lambda doc, sym: None)

    out = resolve_entity({"symbol": "ZZZZ"})
    assert out["entity_type"] == ENTITY_UNRESOLVED
    assert "identity_lookup_failed" not in out, (
        "an unregistered entity is a fact, not an outage")


def test_a_registered_symbol_still_resolves(monkeypatch):
    import scripts.lib.identity_registry as reg
    monkeypatch.setattr(reg, "load_cached", lambda *a, **k: {})
    monkeypatch.setattr(reg, "lookup_symbol",
                        lambda doc, sym: {"subject_guid": "guid-123"})

    out = resolve_entity({"symbol": "NVDA"})
    assert out["subject_guid"] == "guid-123"
    assert out["entity_type"] == ENTITY_SECURITY
    assert "identity_lookup_failed" not in out


def test_the_no_mint_guarantee_survives_a_failure(monkeypatch):
    import scripts.lib.identity_registry as reg
    monkeypatch.setattr(reg, "load_cached",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = resolve_entity({"symbol": "AAPL"})
    assert out["never_minted_security_guid"] is True
