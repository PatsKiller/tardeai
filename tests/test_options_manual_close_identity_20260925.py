#!/usr/bin/env python3
"""The operator manual-close endpoint records an outcome WITH contract identity.

2026-09-25: the first manually recorded paper outcome (RTX 160C exp 2026-09-18,
expired ITM and exercised) landed in options_paper_outcomes with no
contract_guid, because POST /api/v2/options/alpaca-paper/record-outcome passed a
meta without the OCC symbol — the only thing record_outcome derives identity
from. The reconcile caller always passed it. Hermetic: api_v2 handler called
directly, alpaca_paper and record_outcome monkeypatched, no DB.

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


def _fake_lane(monkeypatch, *, status="ALPACA_PAPER_FILLED", legs=None):
    from lib.options_pipeline import alpaca_paper as ap
    from lib.options_pipeline import validation as val

    calls = {"transitions": [], "record": None}
    row = {"proposal_id": PID, "status": status, "strategy": "deep_itm_call", "symbol": "RTX", "meta": {}}
    request = {"qty": "1", "side": "buy", "symbol": "RTX260918C00160000"} if legs is None else {"qty": "1", "legs": legs}
    aj = {"request": request, "response": {"id": "order-1"},
          "fill": {"price": 36.9, "filled_at": "2026-07-20T19:19:01Z"}}
    monkeypatch.setattr(ap, "get_queue_row", lambda pid, *a, **k: dict(row) if pid == PID else None)
    monkeypatch.setattr(ap, "_alpaca_meta", lambda r: dict(aj))

    def _transition(pid, to_status, **kw):
        calls["transitions"].append((pid, to_status))
        return {"ok": True}

    monkeypatch.setattr(ap, "transition", _transition)

    def _record(pid, **kw):
        calls["record"] = {"pid": pid, **kw}
        return {"ok": True, "proposal_id": pid}

    monkeypatch.setattr(val, "record_outcome", _record)
    return calls


def test_manual_close_passes_the_occ_symbol_so_identity_can_be_derived(api, monkeypatch):
    calls = _fake_lane(monkeypatch)
    st, res = api._options_alpaca_record_outcome({"proposal_id": PID, "exit_premium": 33.91})
    assert st == 200 and res["ok"] is True and res["status"] == "OUTCOME_RECORDED"
    assert res["pnl"] == -299.0 and res["outcome"] == "loss"
    rec = calls["record"]
    assert rec["meta"]["occ_symbol"] == "RTX260918C00160000"
    assert rec["meta"]["contracts"] == "1"
    assert rec["meta"]["source"] == "operator_manual_ui"
    assert rec["exit_reason"] == "manual"
    assert [t[1] for t in calls["transitions"]] == ["ALPACA_PAPER_CLOSED", "OUTCOME_RECORDED"]
    # and record_outcome really can mint from that meta (registry-independent check of the parse)
    from lib.options_pipeline.validation import contract_fields_from_meta
    f = contract_fields_from_meta(rec["meta"], symbol="RTX")
    assert (f["strike"], f["expiration"], f["option_type"]) == (160.0, "2026-09-18", "call")


def test_manual_close_accepts_expiry_context_without_inventing_it(api, monkeypatch):
    calls = _fake_lane(monkeypatch)
    st, res = api._options_alpaca_record_outcome({
        "proposal_id": PID, "exit_premium": 33.91,
        "exit_reason": "expired_itm_exercised", "closed_at": "2026-09-18T20:00:00Z",
        "notes": "expired deep ITM; exercised into RTX 100 sh; settled at intrinsic on the expiry close",
    })
    assert st == 200
    rec = calls["record"]
    assert rec["exit_reason"] == "expired_itm_exercised"
    assert rec["closed_at"] == "2026-09-18T20:00:00Z"
    assert rec["notes"].startswith("expired deep ITM")
    assert rec["pnl"] == -299.0 and rec["entry_debit"] == 3690.0 and rec["exit_value"] == 3391.0


def test_manual_close_of_a_spread_joins_the_legs(api, monkeypatch):
    calls = _fake_lane(monkeypatch, legs=[{"symbol": "V261017C00385000"}, {"symbol": "V261017C00400000"}])
    st, _ = api._options_alpaca_record_outcome({"proposal_id": PID, "exit_premium": 1.0})
    assert st == 200
    assert calls["record"]["meta"]["occ_symbol"] == "V261017C00385000,V261017C00400000"


def test_manual_close_still_refuses_without_a_fill_price(api, monkeypatch):
    from lib.options_pipeline import alpaca_paper as ap
    _fake_lane(monkeypatch)
    monkeypatch.setattr(ap, "_alpaca_meta", lambda r: {"request": {"symbol": "RTX260918C00160000"}, "fill": {}})
    st, res = api._options_alpaca_record_outcome({"proposal_id": PID, "exit_premium": 33.91})
    assert st == 409 and "fill price" in res["reason"]
