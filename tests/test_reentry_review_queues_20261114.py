"""DR-R05 / DR-R06 (sprint 8H-2 b3): the whole current queue lives in this workspace, and the exit and level
gaps are named review queues rather than counts with a Classic detour.

Before: two-thirds of the current packet queue needed the Classic page, the visible order was undeclared, two
accounts holding one symbol produced one row ID, and "Stopped out (saved by you) 5" named none of the five.
Synthetic symbols, accounts and values only (the repository is public).
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


def packets(symbols):
    rows = [{"symbol": s, "account": "acct_a", "state": "BUY_READY", "entry_low": 10.0, "entry_high": 11.0,
             "price": 10.5, "saved_at": (NOW - timedelta(hours=i + 1)).isoformat(),
             "packet_age_h": i + 1, "packet_trading_age_h": i + 1, "quote_age_h": 0.5} for i, s in enumerate(symbols)]
    return {"rows": rows, "stale": [], "max_age_h": 48, "as_of": NOW.isoformat(), "count": len(rows)}


EXITS = {"ok": True, "rows": [
    {"event_key": "k-a", "symbol": "ZZAA", "account": "acct_a", "trade_date": "2026-11-10",
     "proceeds_usd": 1200.0, "event_status": None},
    {"event_key": "k-b", "symbol": "ZZBB", "account": "acct_a", "trade_date": "2026-11-09",
     "proceeds_usd": 800.0, "event_status": "open"},
    {"event_key": "k-c", "symbol": "ZZCC", "account": "acct_b", "trade_date": "2026-11-08",
     "proceeds_usd": 400.0, "event_status": None},
    {"event_key": "k-d", "symbol": "ZZDD", "account": "acct_b", "trade_date": "2026-11-07",
     "proceeds_usd": 300.0, "event_status": None},
]}
CLASSES = {
    "k-a": {"eventType": "stopped_out", "reason": "hit the planned stop"},
    "k-d": {"eventType": "stopped_out", "reason": "trailing stop"},
    "k-b": {"eventType": "trimmed", "reason": "trimmed into strength"},
}
RESIST = {"ZZDD": {"state": "UNAVAILABLE", "as_of": (NOW - timedelta(hours=4)).isoformat()},
          "ZZAA": {"state": "TESTING", "resistance": 12.0, "distance_pct": 2.0,
                   "as_of": (NOW - timedelta(hours=20)).isoformat()}}


def build(tmp_path, packets_doc, exits=EXITS, classes=CLASSES, resist=RESIST):
    prefs = [{"key": "portfolio.reentry.event-classifications.v1", "value": classes},
             {"key": "portfolio.reentry.resistance.v1",
              "value": {"generated_at": (NOW - timedelta(hours=2)).isoformat(), "symbol_count": len(resist),
                        "symbols": resist}}]
    db = lambda sql, params=None: prefs if "FROM ui_prefs" in sql else []  # noqa: E731
    return desk.reentry_payload(root=tmp_path, db_query=db, now=NOW, packets=packets_doc, truth={},
                                stances={}, exits=exits, states=REG)


def panel(payload, tab, pid):
    return next(p for p in payload["tabs"][tab]["panels"] if p["id"] == pid)


def row(panel_doc, rid):
    return next(r for r in panel_doc["rows"] if r["id"] == rid)


def fields(panel_doc, rid):
    return dict((f["label"], f["value"]) for f in row(panel_doc, rid)["detail"]["fields"])


NON_PACKET = ("pkt-alert", "pkt-more", "pkt-controls")


def packet_rows(panel_doc):
    return [r for r in panel_doc["rows"] if r["id"].startswith("pkt-") and r["id"] not in NON_PACKET]


def rows_text(panel_doc, rid):
    return " ".join(str(f["value"]) for f in row(panel_doc, rid)["detail"]["fields"])


# ── DR-R05 · the complete current queue in this workspace ─────────────────────────────────────────────────────
def test_dr_r05_every_current_packet_is_listed_here_with_no_classic_detour(tmp_path):
    doc = build(tmp_path, packets([f"ZZ{i:02d}" for i in range(14)]))
    ready = panel(doc, "ready-now", "ready")
    listed = packet_rows(ready)
    assert len(listed) == 14, f"{len(listed)} of 14 current packets are reachable"
    # no "N more" row: nothing is pushed to Classic while the full queue fits the view
    assert not any(r["id"] == "pkt-more" for r in ready["rows"])


def test_dr_r05_the_visible_order_is_declared_and_unique_per_packet(tmp_path):
    doc = packets(["ZZAA", "ZZBB"])
    doc["rows"].append(dict(doc["rows"][0], account="acct_b"))  # one instrument, two account packets
    doc["rows"].reverse()  # the read model's order is not the displayed order
    out = build(tmp_path, doc)
    ready = panel(out, "ready-now", "ready")
    ids = [r["id"] for r in packet_rows(ready)]
    assert len(ids) == len(set(ids)) == 3, f"row IDs collide: {ids}"
    # newest packet first: ZZAA was saved an hour before ZZBB, and its two account packets lead
    assert ids[:2] == ["pkt-ZZAA-acct_a", "pkt-ZZAA-acct_b"] and ids[2] == "pkt-ZZBB", ids
    # the order is stated where a reader can see it
    assert "newest" in (ready["sub"] or "").lower() or "newest" in str(fields(panel(out, "ready-now", "populations"), "pop-current"))


def test_dr_r05_two_accounts_are_two_rows_not_one(tmp_path):
    doc = packets(["ZZAA"])
    doc["rows"].append(dict(doc["rows"][0], account="acct_b"))
    out = build(tmp_path, doc)
    ready = panel(out, "ready-now", "ready")
    labels = [r["label"] for r in packet_rows(ready)]
    assert len(labels) == 2 and labels[0] == labels[1]  # same instrument name, two packets
    accounts = {fields(ready, r["id"]).get("Account") for r in packet_rows(ready)}
    assert accounts == {"acct_a", "acct_b"}, accounts


def test_dr_r05_a_queue_beyond_the_cap_says_what_is_not_listed(tmp_path):
    n = desk.QUEUE_CAP + 3
    out = build(tmp_path, packets([f"ZZ{i:03d}" for i in range(n)]))
    ready = panel(out, "ready-now", "ready")
    more = row(ready, "pkt-more")
    assert "3" in more["label"] and "not listed" in more["label"].lower()
    assert fields(panel(out, "ready-now", "populations"), "pop-current")["Shown here"].startswith(f"{desk.QUEUE_CAP} of {n}")


def test_dr_r05_search_and_filters_are_named_as_not_published(tmp_path):
    out = build(tmp_path, packets(["ZZAA"]))
    ready = panel(out, "ready-now", "ready")
    assert row(ready, "pkt-controls")["value"] == "not published"
    assert "NEEDS BACKEND" in rows_text(ready, "pkt-controls")


# ── DR-R06 · named review queues ──────────────────────────────────────────────────────────────────────────────
def test_dr_r06_the_stopped_out_queue_names_each_record(tmp_path):
    doc = build(tmp_path, packets(["ZZAA"]))
    q = panel(doc, "exits-review", "exits-stopped")
    ids = [r["id"] for r in q["rows"]]
    assert ids == ["exit-review-k-a", "exit-review-k-d"], ids
    f = fields(q, "exit-review-k-a")
    assert f["Exit ID"] == "k-a" and f["Symbol"] == "ZZAA" and f["Account"] == "acct_a"
    assert f["Exit date"] == "2026-11-10"
    assert f["Your reason"] == "hit the planned stop"
    assert f["Classification"] == "stopped out"
    assert f["Next step"], "a review queue row with no next step is a dead end"


def test_dr_r06_the_classification_counts_state_their_relations(tmp_path):
    doc = build(tmp_path, packets(["ZZAA"]))
    cls = panel(doc, "ready-now", "classification")
    # 2 stopped out of 3 classified, 3 classified of 4 sells, 1 unclassified
    assert row(cls, "cls-stopped")["value"] == "2 of 3 classified exits"
    assert row(cls, "cls-saved")["value"] == "3 of 4 sells classified"
    assert row(cls, "cls-unclassified")["value"] == "1 exit has no saved classification"
    # the subsets are stated in words, not left for the reader to infer
    assert "subset" in rows_text(cls, "cls-stopped").lower()


def test_dr_r06_each_sold_name_without_a_level_is_a_row(tmp_path):
    doc = build(tmp_path, packets(["ZZAA"]))
    q = panel(doc, "resistance-levels", "levels-missing")
    ids = [r["id"] for r in q["rows"]]
    # ZZAA has a TESTING level; ZZBB, ZZCC and ZZDD do not (ZZDD's record says UNAVAILABLE)
    assert ids == ["no-level-ZZBB", "no-level-ZZCC", "no-level-ZZDD"], ids
    f = fields(q, "no-level-ZZDD")
    assert f["Level record"] == "UNAVAILABLE" and f["Level evidence time"].startswith("Sat Nov 14")
    assert fields(q, "no-level-ZZBB")["Level record"] == "no record"
    assert "NEEDS BACKEND" in rows_text(q, "no-level-ZZBB") or "Classic" in rows_text(q, "no-level-ZZBB")


def test_dr_r06_an_unreadable_exit_history_is_not_an_empty_queue(tmp_path):
    out = build(tmp_path, packets(["ZZAA"]), exits=None)
    q = panel(out, "exits-review", "exits-stopped")
    cls = panel(out, "ready-now", "classification")
    # nothing was read: no queue claims "0 stopped out", and no row is invented
    assert q["rows"] == [] and q["gap"]
    assert row(cls, "cls-stopped")["value"] == "not on file"
    # and no detail borrows a zero: "0 of 0 sells" would be a count that was never taken
    assert "0 of 0" not in str(cls) and "not on file" in str(cls["rows"][0]["detail"])


def test_dr_r06_a_quantity_the_read_model_does_not_publish_is_named(tmp_path):
    doc = build(tmp_path, packets(["ZZAA"]))
    f = fields(panel(doc, "exits-review", "exits-stopped"), "exit-review-k-a")
    # build_history publishes proceeds, never shares sold: the row says so instead of deriving one
    assert f["Quantity"].startswith("not published")
    assert "shares" in f["Quantity"]  # it names why: the model has proceeds, not shares
