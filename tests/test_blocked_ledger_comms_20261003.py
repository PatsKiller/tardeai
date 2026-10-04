"""Counterfactual ledger for blocked ideas, and the comms editor's ticker misfires.

Operator-approved 2026-10-03 (Policy Review P3 + comms fix). The ledger records
what blocked ideas did afterwards, by gate, without fabricating prices. The editor
had held messages over "tickers" B (51), D (50) and ONE, including an operator
approval request.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import comms_editor as ce  # noqa: E402
from scripts.lib import counterfactual_ledger as cl  # noqa: E402

T0 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)  # Mon 10:00 ET


def _db(proposal_rows=(), review_rows=(), prices=()):
    def q(sql, params=None, fetch="all"):
        if "auto_proposal_decisions" in sql:
            return list(proposal_rows)
        if "cio_decisions" in sql:
            return list(review_rows)
        if "ticker_prices" in sql:
            return list(prices)
        return []
    return q


def _snap(sym, day: int, close: float):
    d = (T0 + timedelta(days=day)).date()
    return {"symbol": sym, "price_date": d, "close_price": close,
            "created_at": datetime(d.year, d.month, d.day, 11, 20, tzinfo=timezone.utc)}


# ── ledger ───────────────────────────────────────────────────────────────────


def test_rechecks_of_one_symbol_day_collapse_and_approvals_are_not_blocks():
    rows = [{"symbol": "INSG", "strategy_id": "momentum_scalp", "decision": "SKIPPED_PREPROMOTION",
             "reason_codes": [], "created_at": T0 + timedelta(minutes=30 * i)} for i in range(5)]
    reviews = [{"decision_id": "d1", "symbol": "DELL", "action": "MONITOR_ONLY", "action_class": "options_thesis_review", "created_at": T0},
               {"decision_id": "d2", "symbol": "DELL", "action": "APPROVE", "action_class": "options_thesis_review", "created_at": T0}]
    blocks = cl.collect_blocks(_db(rows, reviews), since=T0 - timedelta(days=1))
    gates = sorted(b["gate"] for b in blocks)
    assert gates == ["momentum_scalp:SKIPPED_PREPROMOTION", "options_review:MONITOR_ONLY"]
    assert next(b for b in blocks if b["symbol"] == "INSG")["rechecks"] == 5


def _calendar(days):
    return [_snap("SPY", d, 500.0 + d) for d in days]


def test_measure_returns_pending_and_stale_never_fabricated():
    days = list(range(0, 8))  # sessions day0..day7
    prices = cl.load_prices(_db(prices=_calendar(days) + [_snap("INSG", 0, 10.0), _snap("INSG", 1, 11.0),
                                                       _snap("INSG", 5, 10.0)]),
                            ["INSG"], since=T0 - timedelta(days=1))
    block = {"symbol": "INSG", "gate": "g", "blocked_at": (T0 + timedelta(hours=2)).isoformat()}
    row = cl.measure(block, prices)
    h = row["horizons"]
    assert h["1"]["status"] == "MEASURED" and h["1"]["return_pct"] == 10.0
    assert h["1"]["relative_pct"] is not None
    assert h["5"]["status"] == "STALE_IDENTICAL"  # equals the base: copy-forward suspected
    assert h["20"]["status"] == "PENDING"


def test_no_snapshot_at_block_time_is_pending():
    prices = cl.load_prices(_db(prices=_calendar(range(0, 3))), ["ZZZ"], since=T0)
    row = cl.measure({"symbol": "ZZZ", "gate": "g", "blocked_at": T0.isoformat()}, prices)
    assert {h["status"] for h in row["horizons"].values()} == {"PENDING"}
    assert row["base"] is None


def test_summary_counts_cost_and_benefit():
    rows = [{"gate": "g", "horizons": {"5": {"status": "MEASURED", "return_pct": r}}} for r in (12.0, -20.0, -8.0, 1.0)]
    rows.append({"gate": "g", "horizons": {"5": {"status": "PENDING"}}})
    s = cl.summarize(rows)[0]
    assert (s["measured"], s["pending"], s["cost_good_moves_blocked"], s["benefit_losers_avoided"]) == (4, 1, 1, 2)
    assert s["median_return_pct"] == -3.5


def test_store_appends_only_changed_measurements(tmp_path):
    path = tmp_path / "ledger.jsonl"
    row = {"block_id": "cf_1", "gate": "g", "symbol": "X", "blocked_at": T0.isoformat(),
           "base": {"date": "d", "close": 1.0}, "horizons": {"1": {"status": "PENDING"}}}
    assert cl.append_rows([row], path=path) == 1
    assert cl.append_rows([row], path=path) == 0
    row2 = {**row, "horizons": {"1": {"status": "MEASURED", "return_pct": 3.0}}}
    assert cl.append_rows([row2], path=path) == 1
    latest = cl.latest_rows(path)
    assert latest["cf_1"]["horizons"]["1"]["status"] == "MEASURED"
    assert len(path.read_text().splitlines()) == 2


def test_api_reports_no_ledger_then_live(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api

    path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CIO_COUNTERFACTUAL_LEDGER_JSONL", str(path))
    assert api.get_cio_counterfactuals({})["status"] == "NO_LEDGER_YET"
    cl.append_rows([{"block_id": "cf_2", "gate": "g", "symbol": "X", "blocked_at": T0.isoformat(),
                     "base": None, "horizons": {"5": {"status": "MEASURED", "return_pct": -6.0}}}], path=path)
    out = api.get_cio_counterfactuals({"limit": ["5"]})
    assert out["status"] == "LIVE" and out["row_count"] == 1
    assert out["summary"][0]["benefit_losers_avoided"] == 1


# ── comms editor ─────────────────────────────────────────────────────────────


def test_word_tickers_need_a_marker():
    subs = [{"symbol": s, "guid": f"g-{s}"} for s in ("B", "D", "ONE", "PR", "NVDA")]
    keep = [s["symbol"] for s in ce.unambiguous_subjects("grade B, plan D, edit ONE line, see PR 12, NVDA", subs)]
    assert keep == ["NVDA"]
    assert [s["symbol"] for s in ce.unambiguous_subjects("watch $ONE today", subs[2:3])] == ["ONE"]
    assert [s["symbol"] for s in ce.unambiguous_subjects("ticker ONE looks strong", subs[2:3])] == ["ONE"]
    assert [s["symbol"] for s in ce.unambiguous_subjects("subject g-ONE", subs[2:3])] == ["ONE"]


def _edit(text, tmp_path, *, now=None):
    ledger = ce.DuplicateLedger(tmp_path / "dupes.json")
    resolve = lambda t: [{"symbol": "NVDA", "guid": "guid-nvda"}, {"symbol": "ONE", "guid": "guid-one"}]  # noqa: E731
    stances = {"NVDA": "SELL", "ONE": "TRIM"}
    db = lambda sql, params=None, fetch="all": [  # noqa: E731
        {"symbol": sym, "action": stances[sym], "status": "proposed", "created_at": "2026-10-03T00:00:00"}
        for sym in (params[0] if params else []) if sym in stances]
    return ce.edit(text, chat_id="1", now=now, ledger=ledger, db_query=db, resolve=resolve, editor_mode="live"), ledger


def test_real_disagreement_still_held(tmp_path):
    decision, _ = _edit("NVDA strong buy now", tmp_path)
    assert decision.held_reason == "cio_disagreement"


def test_word_ticker_no_longer_causes_a_hold(tmp_path):
    decision, _ = _edit("Please edit ONE crontab line, it's a strong buy for the pipeline", tmp_path)
    assert decision.held_reason is None


def test_operator_approval_request_is_never_held(tmp_path):
    text = "🔐 *Approval requested*\n*Reason:* NVDA strong buy research\n`/approve AB12CD`\n`/deny AB12CD`"
    decision, _ = _edit(text, tmp_path)
    assert decision.held_reason is None
    assert ce.is_operator_approval_request(text)
    assert not ce.is_operator_approval_request("Approval requested but no code")


def test_duplicates_are_still_held(tmp_path):
    now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    first, ledger = _edit("Morning brief: markets calm", tmp_path, now=now)
    ce.commit(first, chat_id="1", now=now, ledger=ledger, receipts=tmp_path / "receipts.jsonl")
    again = ce.edit("Morning brief: markets calm", chat_id="1", now=now + timedelta(minutes=5), ledger=ledger,
                    db_query=lambda *a, **k: [], resolve=lambda t: [], editor_mode="live")
    assert again.duplicate_of and not again.send
