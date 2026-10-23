"""Held after the sale (ANCHOR CIO_HELD_AFTER_SALE_20261023).

Silo audit 2026-10-23 (docs/ops/CIO_MEMORY_SILO_AUDIT_2026-10-23.md, PR #1995, P1-3). Measured: NAVN sold 500 @ 26.02 on
2026-10-22 15:59 ET (trade_transactions); the schwab_rollover_ira sync no-opped ("no Schwab login token") until
2026-10-23 09:07 ET, so holdings.json kept NAVN and the CIO curator kept advising ADD / owned with no cross-check.

Pins: positions_context MARKS a holding whose broker sell is newer than the holdings snapshot (never changes
``owned`` — §26.5 / §0 rule 5); the opportunity assessment carries the conflict with both facts and says so in its
rationale; suppressing ADD/HOLD advice on it is behind position_conflict.suppress_add_hold (default false — §17,
changes what Home ranks). Hermetic: tmp holdings file, injected db_query.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib.data_broker import opportunity as OPP  # noqa: E402
from scripts.lib.data_broker import positions_context as PC  # noqa: E402

UTC = timezone.utc


def _holdings(tmp: Path, *, shares=500.0, state_as_of="2026-10-22T00:00:00+00:00", sym="NAVN") -> Path:
    p = tmp / "holdings.json"
    p.write_text(json.dumps({
        "as_of": "2026-10-23", "positions_built_at": "2026-10-23 08:52:01 ET",
        "portfolio_totals": {"total_value": 100000.0},
        "account_summaries": {"schwab_rollover_ira": {"state_as_of": state_as_of}},
        "holdings": [{"symbol": sym, "account": "schwab_rollover_ira", "shares": shares, "avg_cost": 25.64,
                      "current_price": 26.0}]}))
    return p


def _fills(*rows):
    def q(sql, params=None):
        if "max(trade_date)" in sql:
            sells = [r for r in rows if r[1].startswith("sell")]
            return [{"s": "NAVN", "last_sell": max(r[2] for r in sells).date()}] if sells else []
        if "FROM trade_transactions" in sql:
            return [{"s": "NAVN", "action": a, "trade_time": t, "trade_date": t.date(), "quantity": qn}
                    for (_, a, t, qn) in rows]
        return []
    return q


BUY = ("NAVN", "buy", datetime(2026, 10, 19, 15, 1, 4, tzinfo=UTC), 500)
SELL = ("NAVN", "sell", datetime(2026, 10, 22, 19, 59, 21, tzinfo=UTC), 500)


def _ctx(tmp, q, today=date(2026, 10, 23), **kw):
    return PC.get_positions_context(q, ["NAVN"], today=today, holdings_path=_holdings(tmp, **kw))["NAVN"]


def test_navn_shape_is_marked_and_owned_is_left_as_the_store_says(tmp_path):
    pc = _ctx(tmp_path, _fills(BUY, SELL))
    assert pc["owned"] is True                                    # never resolved here
    sas = pc["sold_after_snapshot"]
    assert sas["sell_quantity"] == 500 and sas["covers_position"] is True and sas["rebought_after"] is False
    assert sas["snapshot_resolution"] == "date" and sas["sell_source"] == "trade_transactions"
    assert sas["last_sell_at"].startswith("2026-10-22T19:59:21")


def test_same_day_partial_sale_on_a_synced_account_is_not_marked(tmp_path):
    trim = ("NAVN", "sell", datetime(2026, 10, 23, 14, 0, tzinfo=UTC), 250)
    pc = _ctx(tmp_path, _fills(trim), state_as_of="2026-10-23T00:00:00+00:00", shares=250.0)
    assert "sold_after_snapshot" not in pc


def test_yesterdays_trim_of_an_old_position_before_todays_sync_is_not_marked(tmp_path):
    trim = ("NAVN", "sell", datetime(2026, 10, 22, 15, 0, tzinfo=UTC), 500)   # half of an old 1,000-share position
    assert "sold_after_snapshot" not in _ctx(tmp_path, _fills(trim))


def test_rebought_after_the_sale_is_not_marked(tmp_path):
    rebuy = ("NAVN", "buy", datetime(2026, 10, 22, 19, 59, 50, tzinfo=UTC), 500)
    assert "sold_after_snapshot" not in _ctx(tmp_path, _fills(BUY, SELL, rebuy))


def test_a_sale_on_a_later_day_than_the_snapshot_is_marked_even_when_partial(tmp_path):
    trim = ("NAVN", "sell", datetime(2026, 10, 23, 14, 0, tzinfo=UTC), 100)
    pc = _ctx(tmp_path, _fills(trim), state_as_of="2026-10-21T00:00:00+00:00")
    assert pc["sold_after_snapshot"]["covers_position"] is False


def test_a_timed_snapshot_marks_any_later_sale(tmp_path):
    trim = ("NAVN", "sell", datetime(2026, 10, 23, 14, 0, tzinfo=UTC), 100)
    pc = _ctx(tmp_path, _fills(trim), state_as_of="2026-10-23T13:30:04+00:00")
    assert pc["sold_after_snapshot"]["snapshot_resolution"] == "time"
    pc2 = _ctx(tmp_path, _fills(trim), state_as_of="2026-10-23T14:30:00+00:00")
    assert "sold_after_snapshot" not in pc2


def test_no_db_or_a_failing_ledger_marks_nothing(tmp_path):
    assert "sold_after_snapshot" not in _ctx(tmp_path, None)

    def boom(sql, params=None):
        raise RuntimeError("down")
    assert "sold_after_snapshot" not in _ctx(tmp_path, boom)


def _ctx_for_classify(pc):
    return {"position": pc, "on_watchlist": True}


@pytest.fixture()
def cfg(monkeypatch):
    base = json.loads(json.dumps(OPP.load_config()))
    monkeypatch.setattr(OPP, "load_config", lambda: base)
    return base


def test_assessment_carries_the_conflict_and_says_so_switch_off_by_default(tmp_path, cfg):
    assert (cfg.get("position_conflict") or {}).get("suppress_add_hold") is False   # shipped OFF (§17)
    pc = _ctx(tmp_path, _fills(BUY, SELL))
    out = OPP.classify(_ctx_for_classify(pc), 83.7, {"rr": 4.8})
    assert out["stance"] == "ADD" and out["position_status"] == "owned"            # not silently resolved
    c = out["position_conflict"]
    assert c["field"] == "held" and c["resolved"] is False
    assert [v["source"] for v in c["values"]] == ["holdings_accounts", "trade_transactions"]
    assert out["stance_rationale"].startswith("Position unconfirmed — a sale of 500 sh")
    assert "stance_suppressed" not in out


def test_operator_switch_suppresses_add_on_the_conflicted_position(tmp_path, cfg):
    cfg["position_conflict"] = {"suppress_add_hold": True}
    pc = _ctx(tmp_path, _fills(BUY, SELL))
    out = OPP.classify(_ctx_for_classify(pc), 83.7, {"rr": 4.8})
    assert out["stance"] == "WATCH" and out["stance_suppressed"]["from"] == "ADD"


def test_an_unconflicted_holding_is_unchanged(tmp_path, cfg):
    pc = _ctx(tmp_path, _fills(BUY))
    out = OPP.classify(_ctx_for_classify(pc), 83.7, {"rr": 4.8})
    assert "position_conflict" not in out and not out["stance_rationale"].startswith("Position unconfirmed")


def test_gate_file_registers_this_test():
    gate = json.loads((ROOT / "config/ci_gates/cio_held_after_sale_20261023.json").read_text())
    assert "tests/test_cio_held_after_sale_20261023.py" in gate["files"]
