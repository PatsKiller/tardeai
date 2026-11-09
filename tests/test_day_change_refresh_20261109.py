"""LQ-20261107-1645 — the day-change total follows the marks, not one lane's cadence.

ANCHOR: DAY_CHANGE_REFRESH_20261109

Measured on the live line 2026-11-09, read-only: the operator's Today P&L read the SAME value at two marks
minutes apart while ``positions_current`` re-marked between them (one position moved, the total did not).
``holdings[].day_change`` was written only by the 15-minute ``portfolio-repricer``; the export that runs after
every ``positions-sync --apply`` CARRIED it, and the surfaces labelled the figure with the export's own clock.
So the total was a function of one lane's cadence, and a reader could not tell a quiet book from a frozen one.

These tests pin both halves:
  A. the writer that publishes a mark re-prices the number computed from it — two syncs whose marks differ
     publish two different totals, and each row says which mark it was computed from;
  B. every row the writer may not re-price is CARRIED and counted by reason (intraday fills, no prior close, a
     stale prior close, a mark older than the value it would replace) — never rebased, never zeroed;
  C. the frozen guard names a total that did not follow its marks, and the bounded per-export ring lets the
     frozen-output contract judge three consecutive syncs (source kind ``jsonl_history``).

Synthetic fixtures only (public repo): no real symbol, price, account or total.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# The same assertions run against another revision's exporter, so the fail-before is reproducible:
#   HOLDINGS_EXPORT_UNDER_TEST=/tmp/base_holdings_export.py pytest tests/test_day_change_refresh_20261109.py
_EXPORT_PATH = Path(os.environ.get("HOLDINGS_EXPORT_UNDER_TEST") or ROOT / "scripts/holdings_export.py")
_spec = importlib.util.spec_from_file_location("holdings_export_day_change_under_test", _EXPORT_PATH)
he = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = he
_spec.loader.exec_module(he)

SYNC_1 = datetime(2026, 11, 9, 18, 15, tzinfo=timezone.utc)
SYNC_2 = SYNC_1 + timedelta(minutes=15)
QUOTE_AT = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)
ACCOUNT = "acct_a"
RUN_ID = 901


def _position_row(symbol, *, qty, value, as_of, **extra):
    row = {"account_key": ACCOUNT, "symbol": symbol, "broker": "schwab", "qty": qty,
           "broker_market_value": value, "is_cash": False, "asset_type": "EQUITY", "source": "schwab_api",
           "as_of": as_of, "sync_run_id": RUN_ID, "cost_basis_total": 100.0, "avg_cost": 10.0}
    row.update(extra)
    return row


def _quotes(symbols, *, price, reference_close, inserted_at=QUOTE_AT):
    return {s: {"price": price, "reference_close": reference_close, "inserted_at": inserted_at,
                "bar_end": inserted_at, "session": "regular", "reference_basis": "prior_session_close",
                "change_pct": 1.0, "feed": "sip"} for s in symbols}


def _carried_row(symbol, *, shares, market_value, price, day_change, day_change_pct, mark_at, **extra):
    row = {"symbol": symbol, "account": ACCOUNT, "account_id": ACCOUNT, "account_key": ACCOUNT,
           "is_cash": False, "shares": shares, "system_shares": shares, "quantity": shares,
           "market_value": market_value, "price": price, "current_price": price, "cost_basis": 100.0,
           "gain_loss": 1.0, "gain_loss_pct": 1.0, "day_change": day_change, "day_change_pct": day_change_pct,
           "canonical_mark": price, "canonical_mark_ingested_at": mark_at.isoformat(),
           "broker_day_pl": 1.0, "portfolio_pct": 1.0}
    row.update(extra)
    return row


def _total(rows, key):
    """Sum of a numeric field over the rows that have one; a missing value is skipped, never read as zero."""
    return sum(v for r in rows if isinstance(v := r.get(key), (int, float)))


def _prior(rows, *, day_change_total, marks_fp=None):
    return {"holdings": rows,
            "portfolio_totals": {"total_value": _total(rows, "market_value"),
                                 "day_change": day_change_total},
            "account_summaries": {ACCOUNT: {"account_key": ACCOUNT,
                                            "total_value": _total(rows, "market_value")}},
            "export_provenance": {"day_change_marks_fp": marks_fp} if marks_fp else {},
            "positions_fingerprint": "prior", "positions_built_at": "2026-11-09T00:00:00Z"}


def _render(rows, *, quotes, prior, now):
    summaries = {ACCOUNT: {"account_key": ACCOUNT, "total_value": _total(rows, "broker_market_value")}}
    return he.render_document(rows, generated_at=now, quotes=quotes, profiles={}, lookthrough={},
                              gaps=[], account_summaries=summaries, aliases={}, prior=prior)


def _two_syncs():
    """Sync 1 marks AAA at 105.00; sync 2 at 106.00. Prior close 100.00, ten shares."""
    prior = _prior([_carried_row("AAA", shares=10.0, market_value=1050.0, price=105.0,
                                 day_change=50.0, day_change_pct=5.0, mark_at=SYNC_1)],
                   day_change_total=50.0)
    quotes = _quotes(["AAA"], price=105.0, reference_close=100.0)
    first = _render([_position_row("AAA", qty=10.0, value=1050.0, as_of=SYNC_1)], quotes=quotes,
                    prior=prior, now=SYNC_1)
    second = _render([_position_row("AAA", qty=10.0, value=1060.0, as_of=SYNC_2)], quotes=quotes,
                     prior=first, now=SYNC_2)
    return prior, quotes, first, second


# ── A. the total follows the marks ──────────────────────────────────────────────────────────────
def test_two_syncs_with_different_marks_publish_different_totals():
    """The ticket's proof: two syncs, different marks -> different total."""
    _prior_doc, _q, first, second = _two_syncs()
    assert first["portfolio_totals"]["day_change"] == 50.0
    assert second["portfolio_totals"]["day_change"] == 60.0, (
        "the second sync marked AAA at 106.00 and the total did not move: the day P&L is following a "
        "writer's cadence instead of the marks")
    assert second["portfolio_totals"]["day_change"] != first["portfolio_totals"]["day_change"]
    row = second["holdings"][0]
    assert row["day_change"] == 60.0 and row["day_change_pct"] == 6.0
    assert row["day_change_source"] == "positions_sync_mark"
    assert row["day_change_as_of"] == "2026-11-09T18:30:00Z"
    assert row["day_change_mark_price"] == 106.0 and row["day_change_prior_close"] == 100.0


def test_the_carried_behaviour_is_what_froze_the_total(monkeypatch):
    """Fail-before: restore the pre-fix behaviour (carry the repricer's value) and the total freezes."""
    monkeypatch.setattr(he, "_refresh_day_change", lambda *a, **kw: "carried")
    _prior_doc, _q, first, second = _two_syncs()
    assert second["portfolio_totals"]["day_change"] == first["portfolio_totals"]["day_change"] == 50.0, (
        "with the refresh disabled the total must reproduce the freeze — otherwise this test proves nothing")


def test_the_row_says_which_mark_it_was_computed_from():
    _prior_doc, _q, first, second = _two_syncs()
    row = second["holdings"][0]
    assert he._carried_day_change_clock(row) == SYNC_2
    # The document-level stamp is written where the totals are finalised (build_document), so the surfaces
    # can date the figure by the OLDEST mark summed into it instead of by the export's own clock.
    he._stamp_day_change(second, first)
    assert second["portfolio_totals"]["day_change_as_of"] == "2026-11-09T18:30:00Z"


# ── B. every refusal is carried and counted ────────────────────────────────────────────────────
def _one_row(**carried):
    prior = _prior([_carried_row("AAA", shares=carried.pop("shares", 10.0),
                                 market_value=carried.pop("market_value", 1050.0),
                                 price=carried.pop("price", 105.0),
                                 day_change=carried.pop("day_change", 50.0),
                                 day_change_pct=carried.pop("day_change_pct", 5.0),
                                 mark_at=carried.pop("mark_at", SYNC_1), **carried)],
                   day_change_total=50.0)
    return _render([_position_row("AAA", qty=10.0, value=1060.0, as_of=SYNC_2)],
                   quotes=_quotes(["AAA"], price=105.0, reference_close=100.0), prior=prior, now=SYNC_2), prior


def test_an_intraday_fills_row_is_carried_never_rebased():
    """A share bought today earns from its fill, not the prior close: the prior close is the wrong basis."""
    doc, _prior_row = _one_row(day_change=12.34, day_change_basis="intraday_fills")
    row = doc["holdings"][0]
    assert row["day_change"] == 12.34
    assert doc["export_provenance"]["day_change_rows"] == {"carried_other_basis": 1}


def test_a_row_with_no_prior_close_is_carried_and_counted():
    prior = _prior([_carried_row("AAA", shares=10.0, market_value=1050.0, price=105.0, day_change=50.0,
                                 day_change_pct=5.0, mark_at=SYNC_1)], day_change_total=50.0)
    doc = _render([_position_row("AAA", qty=10.0, value=1060.0, as_of=SYNC_2)], quotes={},
                  prior=prior, now=SYNC_2)
    assert doc["holdings"][0]["day_change"] == 50.0
    assert doc["export_provenance"]["day_change_rows"] == {"carried_no_prior_close": 1}


def test_a_mark_older_than_the_value_it_would_replace_is_not_used():
    """The fresher writer keeps the number: a 15:00 reprice beats a 14:45 broker mark."""
    doc, _prior_row = _one_row(mark_at=SYNC_2 + timedelta(minutes=5))
    assert doc["holdings"][0]["day_change"] == 50.0
    assert doc["export_provenance"]["day_change_rows"] == {"carried_older_mark": 1}


def test_a_stale_prior_close_does_not_publish_a_multi_day_move():
    prior = _prior([_carried_row("AAA", shares=10.0, market_value=1050.0, price=105.0, day_change=50.0,
                                 day_change_pct=5.0, mark_at=SYNC_1)], day_change_total=50.0)
    stale = _quotes(["AAA"], price=105.0, reference_close=90.0,
                    inserted_at=SYNC_2 - timedelta(days=he.MAX_PRIOR_CLOSE_AGE_DAYS + 1))
    doc = _render([_position_row("AAA", qty=10.0, value=1060.0, as_of=SYNC_2)], quotes=stale,
                  prior=prior, now=SYNC_2)
    assert doc["holdings"][0]["day_change"] == 50.0
    assert doc["export_provenance"]["day_change_rows"] == {"carried_stale_prior_close": 1}


def test_cash_has_no_day_change_to_recompute():
    prior = _prior([_carried_row("CASH", shares=10.0, market_value=10.0, price=1.0, day_change=0.0,
                                 day_change_pct=0.0, mark_at=SYNC_1, is_cash=True)], day_change_total=0.0)
    doc = _render([_position_row("CASH", qty=10.0, value=10.0, as_of=SYNC_2, is_cash=True)],
                  quotes={}, prior=prior, now=SYNC_2)
    assert doc["holdings"][0]["day_change"] == 0.0
    assert doc["export_provenance"]["day_change_rows"] == {"cash": 1}


def test_recomputing_drops_the_broker_check_that_described_the_replaced_mark():
    prior = _prior([_carried_row("AAA", shares=10.0, market_value=1050.0, price=105.0, day_change=50.0,
                                 day_change_pct=5.0, mark_at=SYNC_1,
                                 day_change_broker_check={"ok": True, "ours_at_broker_mark": 49.9})],
                   day_change_total=50.0)
    doc = _render([_position_row("AAA", qty=10.0, value=1060.0, as_of=SYNC_2)],
                  quotes=_quotes(["AAA"], price=105.0, reference_close=100.0), prior=prior, now=SYNC_2)
    row = doc["holdings"][0]
    assert "day_change_broker_check" not in row
    assert row["day_change_broker_pl_diff"] == 59.0      # 60.00 computed vs 1.00 the broker reported


# ── C. the frozen guard and the per-export ring ────────────────────────────────────────────────
def test_the_frozen_guard_names_a_total_that_did_not_follow_its_marks():
    document = {"holdings": [{"symbol": "AAA", "day_change": 50.0}], "gaps": [],
                "portfolio_totals": {"day_change": 50.0},
                "export_provenance": {"day_change_marks_fp": "bbb"}}
    prior = {"portfolio_totals": {"day_change": 50.0},
             "export_provenance": {"day_change_marks_fp": "aaa"}}
    he._stamp_day_change(document, prior)
    assert document["portfolio_totals"]["day_change_frozen"] is True
    assert any(g.startswith("day_change_frozen:") for g in document["gaps"])


def test_a_moving_total_is_not_reported_frozen():
    document = {"holdings": [{"symbol": "AAA", "day_change": 60.0}], "gaps": [],
                "portfolio_totals": {"day_change": 60.0},
                "export_provenance": {"day_change_marks_fp": "bbb"}}
    prior = {"portfolio_totals": {"day_change": 50.0},
             "export_provenance": {"day_change_marks_fp": "aaa"}}
    he._stamp_day_change(document, prior)
    assert document["portfolio_totals"]["day_change_frozen"] is False
    assert document["gaps"] == []


def test_a_quiet_book_is_not_reported_frozen():
    """Same fingerprint and same total is STABLE INPUTS, not FROZEN — the marks did not move."""
    document = {"holdings": [], "gaps": [], "portfolio_totals": {"day_change": 50.0},
                "export_provenance": {"day_change_marks_fp": "aaa"}}
    prior = {"portfolio_totals": {"day_change": 50.0}, "export_provenance": {"day_change_marks_fp": "aaa"}}
    he._stamp_day_change(document, prior)
    assert document["portfolio_totals"]["day_change_frozen"] is False


def _ring(tmp_path, records, *, contract=None):
    path = tmp_path / he.DAY_CHANGE_HISTORY
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def test_the_monitor_reads_the_ring_and_calls_the_incident_frozen(tmp_path, monkeypatch):
    """Three syncs, the marks moved, the total did not: the contract's own verdict must be FROZEN."""
    import frozen_output_monitor as mon

    records = [{"at": (SYNC_1 + timedelta(minutes=15 * i)).isoformat().replace("+00:00", "Z"),
                "day_change": 50.0, "marks_fp": f"marks-{i}"} for i in range(3)]
    path = _ring(tmp_path, records)
    contract = {"lane_id": "positions-sync", "k": 3,
                "source": {"kind": "jsonl_history", "path": str(path), "time_column": "at", "window_days": 14},
                "output_fields": ["day_change"], "input_fields": ["marks_fp"]}
    monkeypatch.setattr(mon, "ROOT", tmp_path)
    contract["source"]["path"] = path.name
    history = mon.load_jsonl_history(contract, now=SYNC_2)
    assert len(history) == 3 and all(h["input_fp"] != history[0]["input_fp"] or i == 0
                                     for i, h in enumerate(history))
    from lib import frozen_output as fo
    assert fo.evaluate(history, 3)["verdict"] == "FROZEN"


def test_the_monitor_reads_a_moving_total_as_ok(tmp_path, monkeypatch):
    import frozen_output_monitor as mon
    from lib import frozen_output as fo

    records = [{"at": (SYNC_1 + timedelta(minutes=15 * i)).isoformat().replace("+00:00", "Z"),
                "day_change": 50.0 + i, "marks_fp": f"marks-{i}"} for i in range(3)]
    path = _ring(tmp_path, records)
    monkeypatch.setattr(mon, "ROOT", tmp_path)
    contract = {"lane_id": "positions-sync", "k": 3,
                "source": {"kind": "jsonl_history", "path": path.name, "time_column": "at", "window_days": 14},
                "output_fields": ["day_change"], "input_fields": ["marks_fp"]}
    assert fo.evaluate(mon.load_jsonl_history(contract, now=SYNC_2), 3)["verdict"] == "OK"


def test_the_contract_file_registers_the_ring_and_rejects_an_escaping_path():
    from lib import frozen_output as fo

    doc = json.loads((ROOT / "config" / "frozen_output_contracts.json").read_text(encoding="utf-8"))
    assert fo.validate_document(doc) == []
    contract = next(c for c in doc["contracts"] if c["lane_id"] == "positions-sync")
    assert contract["source"]["kind"] == "jsonl_history"
    assert contract["source"]["path"] == f"data/portfolios/state/{he.DAY_CHANGE_HISTORY}"
    bad = json.loads(json.dumps(contract))
    bad["source"]["path"] = "../../etc/passwd"
    assert any("source.path" in e for e in fo.validate_contract(bad))


def test_the_repricer_clears_the_syncs_day_change_provenance():
    """Whichever writer last computed the value owns its stamp; a stale one would date the number wrongly."""
    import ast

    tree = ast.parse((ROOT / "scripts" / "portfolio_repricer.py").read_text(encoding="utf-8"))
    defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    calls = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    assert "_clear_day_change_provenance" in defs
    assert calls.count("_clear_day_change_provenance") == 2, (
        "both day-change write branches (NAV and live) must clear the sync's provenance")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
