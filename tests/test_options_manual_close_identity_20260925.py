#!/usr/bin/env python3
"""Alpaca paper manual-close is retired — Options Desk is Schwab-only (2026-09-25).

The 2026-09-25 identity fix (OCC symbol on record-outcome meta) still matters for
any future Schwab close path, but the Alpaca UI/API lane now returns 403
``options_desk_schwab_only`` before any state-machine work. These tests pin that
refusal so a silent re-enable cannot ship.

    .venv/bin/python -m pytest tests/test_options_manual_close_identity_20260925.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PID = "opt_deep_itm_call_RTX_paper_model_160p0000_20260918_d20260720"


@pytest.fixture(scope="module")
def api():
    import api_v2

    return api_v2


def test_alpaca_record_outcome_refuses_schwab_only(api):
    st, res = api._options_alpaca_record_outcome({"proposal_id": PID, "exit_premium": 33.91})
    assert st == 403
    assert res["ok"] is False
    assert res["reason"] == "options_desk_schwab_only"


def test_alpaca_record_outcome_refuses_even_with_expiry_context(api):
    st, res = api._options_alpaca_record_outcome(
        {
            "proposal_id": PID,
            "exit_premium": 33.91,
            "exit_reason": "expired_itm_exercised",
            "closed_at": "2026-09-18T20:00:00Z",
            "notes": "should never reach record_outcome",
        }
    )
    assert st == 403
    assert res["reason"] == "options_desk_schwab_only"


def test_alpaca_mark_ready_and_submit_also_refuse(api):
    st1, r1 = api._options_alpaca_mark_ready({"proposal_id": PID})
    st2, r2 = api._options_alpaca_submit({"proposal_id": PID, "confirm": True})
    st3, r3 = api._options_alpaca_reconcile({})
    assert (st1, st2, st3) == (403, 403, 403)
    assert r1["reason"] == r2["reason"] == r3["reason"] == "options_desk_schwab_only"


def test_contract_fields_from_meta_still_parses_occ_for_schwab_paths():
    """Identity helper used by Schwab/ledger closes — keep the OCC parse green."""
    from lib.options_pipeline.validation import contract_fields_from_meta

    f = contract_fields_from_meta(
        {"occ_symbol": "RTX260918C00160000", "contracts": "1"},
        symbol="RTX",
    )
    assert (f["strike"], f["expiration"], f["option_type"]) == (160.0, "2026-09-18", "call")
