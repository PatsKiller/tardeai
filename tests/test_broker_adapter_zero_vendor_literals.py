"""Regression guard for broker_adapter.py's "zero vendor string literals" claim.

Audit finding L4 (docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md): the claim was
already true in the dispatch code, but the docstring itself named two real
vendors ("Adding Schwab/IBKR later is a drop-in file") one paragraph after
claiming to name none. Fixed to a generic placeholder; this test makes the
claim mechanically checkable so it can't silently regress.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "scripts" / "broker_adapter.py").read_text()


def test_no_vendor_names_anywhere_in_broker_adapter():
    lowered = SRC.lower()
    for vendor in ("schwab", "alpaca", "snaptrade", "ibkr", "fidelity", "moomoo", "futu"):
        assert vendor not in lowered, f"{vendor!r} found in broker_adapter.py — HARD RULE violated"
