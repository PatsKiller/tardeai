"""DR-R03 (sprint 8H-2 b3): a buy-ready candidate that the book already holds must show the holding.

The capture had ANET as BUY_READY while the Portfolio held 200 shares in the Rollover IRA, and the candidate
row said nothing about it — "Names you sold" left open whether the packet was a rebuild of a reduced position
or a duplicate entry. The candidate row now names every position the holdings record carries for the symbol,
with that position's own account, shares, value and observation clock, or states that the holdings read was
unavailable. It never calls a name fully exited: matching a packet to exits needs the canonical
instrument/account join (position_snapshot_id, matched exit ids and quantities) that is not published, so the
exit match is an explicit Unverified. Synthetic symbols, accounts and values only (the repository is public).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import desks_a as desk  # noqa: E402

NOW = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)
REG = {"cio-entry-state": "ACTIVE", "portfolio-repricer": "ACTIVE", "watch-alerts-eval": "ACTIVE"}


def packet(symbol, account="acct_a", saved_hours=1):
    return {"symbol": symbol, "account": account, "state": "BUY_READY", "entry_low": 10.0, "entry_high": 11.0,
            "price": 10.5, "saved_at": (NOW - timedelta(hours=saved_hours)).isoformat(),
            "packet_age_h": saved_hours, "packet_trading_age_h": saved_hours, "quote_age_h": 0.5}


def packets(*rows):
    rows = list(rows)
    return {"rows": rows, "stale": [], "max_age_h": 48, "as_of": NOW.isoformat(), "count": len(rows)}


def position(symbol, shares=200, value=39458.0, account_label="Schwab Rollover IRA (synthetic)",
             account_id="schwab_rollover_ira", as_of="2026-11-14T14:55:00Z"):
    return {"symbol": symbol, "account_id": account_id, "account_label": account_label, "shares": shares,
            "market_value": value, "is_cash": False, "is_loan": False,
            "position_clock": {"as_of": as_of, "status": "FRESH"}}


def build(tmp_path, packets_doc, truth=None):
    truth = {} if truth is None else truth
    db = lambda sql, params=None: []  # noqa: E731 -- no ui_prefs in this fixture
    return desk.reentry_payload(root=tmp_path, db_query=db, now=NOW, packets=packets_doc, truth=truth,
                                stances={}, exits={"ok": True, "rows": []}, states=REG)


def ready(payload):
    return next(p for p in payload["tabs"]["ready-now"]["panels"] if p["id"] == "ready")


def row(panel_doc, rid):
    return next(r for r in panel_doc["rows"] if r["id"] == rid)


def fields(panel_doc, rid):
    return dict((f["label"], f["value"]) for f in row(panel_doc, rid)["detail"]["fields"])


def held_fields(f):
    return {k: v for k, v in f.items() if k.startswith("Currently held")}


def test_dr_r03_a_held_candidate_names_its_existing_position(tmp_path):
    doc = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": [position("ZZAA")]}})
    panel = ready(doc)
    f = fields(panel, "pkt-ZZAA")
    assert f["Holding state"] == "Currently held — 1 account", f["Holding state"]
    held = held_fields(f)
    assert len(held) == 1, held
    label, value = next(iter(held.items()))
    assert "Schwab Rollover IRA (synthetic)" in label, label
    assert "200 sh" in value and "$39,458" in value, value
    # the position's OWN observation clock, not the packet's (saved 18:00Z) or the desk's
    assert "Sat Nov 14 9:55 ET" in value, value


def test_dr_r03_the_candidate_row_marks_the_holding_before_any_sheet_is_opened(tmp_path):
    doc = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": [position("ZZAA")]}})
    r = row(ready(doc), "pkt-ZZAA")
    assert "held 200 sh" in r["label"], r["label"]
    # an unheld name is not marked, so the marker means something
    doc2 = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": []}})
    assert "held" not in row(ready(doc2), "pkt-ZZAA")["label"], row(ready(doc2), "pkt-ZZAA")["label"]


def test_dr_r03_two_accounts_are_two_named_positions_never_summed(tmp_path):
    rows = [position("ZZAA", shares=120, value=23000.0, account_label="Account A (synthetic)", account_id="a"),
            position("ZZAA", shares=80, value=16458.0, account_label="Account B (synthetic)", account_id="b")]
    doc = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": rows}})
    f = fields(ready(doc), "pkt-ZZAA")
    assert f["Holding state"] == "Currently held — 2 accounts", f["Holding state"]
    held = held_fields(f)
    assert len(held) == 2, held
    joined = " ".join(held.values())
    assert "120 sh" in joined and "80 sh" in joined, joined
    assert "200 sh" not in joined.replace("120 sh", "").replace("80 sh", ""), f"shares summed across accounts: {joined}"
    assert "held in 2 accounts" in row(ready(doc), "pkt-ZZAA")["label"], row(ready(doc), "pkt-ZZAA")["label"]


def test_dr_r03_an_unheld_name_is_not_described_as_fully_exited(tmp_path):
    doc = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": []}})
    f = fields(ready(doc), "pkt-ZZAA")
    assert "no position in the holdings record" in f["Holding state"], f["Holding state"]
    assert "not proof" in f["Holding state"], f["Holding state"]


def test_dr_r03_an_unreadable_holdings_record_is_unverified_not_unheld(tmp_path):
    doc = build(tmp_path, packets(packet("ZZAA")), {})
    f = fields(ready(doc), "pkt-ZZAA")
    assert "unverified" in f["Holding state"], f["Holding state"]
    assert "could not be read" in f["Holding state"], f["Holding state"]
    assert "no position" not in f["Holding state"], "an unreadable read claims the name is unheld"
    # a malformed block is the same fact as a missing one
    bad = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": "n/a"}})
    assert "could not be read" in fields(ready(bad), "pkt-ZZAA")["Holding state"]


def test_dr_r03_the_exit_match_names_the_join_it_needs(tmp_path):
    doc = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": [position("ZZAA")]}})
    f = fields(ready(doc), "pkt-ZZAA")
    match = f["Exit match"]
    assert match.startswith("unverified"), match
    assert "position_snapshot_id" in match, match
    assert "by symbol" in match, f"the row does not say it refuses a symbol-only match: {match}"


def test_dr_r03_a_zero_share_or_cash_row_is_not_a_holding(tmp_path):
    cash = position("ZZAA", shares=50, value=50.0)
    cash["is_cash"] = True
    rows = [position("ZZAA", shares=0, value=0.0), cash]
    doc = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": rows}})
    f = fields(ready(doc), "pkt-ZZAA")
    assert "no position in the holdings record" in f["Holding state"], f["Holding state"]
    assert not held_fields(f), held_fields(f)


def test_dr_r03_a_position_with_no_observation_clock_says_so(tmp_path):
    pos = position("ZZAA")
    pos["position_clock"] = {"as_of": None, "status": "UNKNOWN"}
    doc = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": [pos]}})
    value = next(iter(held_fields(fields(ready(doc), "pkt-ZZAA")).values()))
    assert "observation time not published" in value, value
    assert "None" not in value


def test_dr_r03_the_holding_fields_are_attributed_and_lose_no_packet_field(tmp_path):
    doc = build(tmp_path, packets(packet("ZZAA")), {"positions": {"rows": [position("ZZAA")]}})
    r = row(ready(doc), "pkt-ZZAA")
    f = fields(ready(doc), "pkt-ZZAA")
    assert "cio_truth" in str(r["detail"]["source"]) and "positions" in str(r["detail"]["source"]), r["detail"]["source"]
    assert f["Entry zone"] == "$10.00–$11.00", f.get("Entry zone")
    assert f["Account"] == "acct_a"
