"""Sprint 8H-2 b2 · Re-Entry: name the three readiness populations (DR-R02), give every row its own
evidence clocks (DR-R04), and keep eligibility scoped and Unverified (DR-X01, UI half).

The page showed "3 ready of 25 event candidates", "36 current packets" and "275 packets older than 48 h"
without saying what each counted. It showed desk-level source clocks but no per-candidate packet, quote,
resistance or expiry time, so a fresh holdings price could make an unpriced candidate look current. And
the header's AUTO BLOCKED state sat beside BUY_READY packets with no statement of which scope each
described. Synthetic symbols and values only (the repository is public).
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


def panel(payload, tab, pid):
    return next(p for p in payload["tabs"][tab]["panels"] if p["id"] == pid)


def row(panel_doc, rid):
    return next(r for r in panel_doc["rows"] if r["id"] == rid)


def fields(panel_doc, rid):
    return dict((f["label"], f["value"]) for f in row(panel_doc, rid)["detail"]["fields"])


def packets(n_current=2, n_stale=3):
    rows = []
    for i in range(n_current):
        sym = f"ZZ{i:02d}"
        rows.append({
            "symbol": sym, "account": "acct_a", "state": "BUY_READY",
            "entry_low": 10.0, "entry_high": 11.5, "price": 10.75, "stop": 9.1, "target": 14.0,
            "rr_plan": 2.6, "saved_at": (NOW - timedelta(hours=3 + i)).isoformat(),
            "packet_age_h": 3.0 + i, "packet_trading_age_h": 3.0 + i, "quote_age_h": 0.5,
            "cio_review": {"status": "approve", "mode": "dry", "as_of": (NOW - timedelta(hours=2 + i)).isoformat()},
        })
    stale = [{"symbol": f"OLD{i}", "state": "BUY_READY", "saved_at": (NOW - timedelta(hours=60 + i)).isoformat(),
              "packet_age_h": 60.0 + i, "packet_trading_age_h": 60.0 + i} for i in range(n_stale)]
    return {"rows": rows, "stale": stale, "max_age_h": 48, "max_age_basis": "trading_days",
            "as_of": NOW.isoformat(), "count": len(rows)}


def build(tmp_path, packets_doc, resist=None):
    prefs = [{"key": "portfolio.reentry.event-classifications.v1", "value": {}},
             {"key": "portfolio.reentry.resistance.v1",
              "value": {"generated_at": (NOW - timedelta(hours=2)).isoformat(), "symbol_count": len(resist or {}),
                        "symbols": resist or {}}}]
    db = lambda sql, params=None: prefs if "FROM ui_prefs" in sql else []  # noqa: E731
    return desk.reentry_payload(root=tmp_path, db_query=db, now=NOW, packets=packets_doc, truth={},
                                stances={}, exits={"ok": True, "rows": []}, states=REG)


# ── DR-R02 · the three populations ────────────────────────────────────────────────────────────────────────────
def test_dr_r02_the_three_populations_are_named_with_unit_rule_and_dedupe(tmp_path):
    out = build(tmp_path, packets())
    pops = panel(out, "ready-now", "populations")
    event, current, history = row(pops, "pop-event"), row(pops, "pop-current"), row(pops, "pop-history")
    # each population says what it is, in its own unit
    assert "packet" in fields(pops, "pop-current")["Unit"]
    assert "candidate" in fields(pops, "pop-event")["Unit"]
    assert "packet" in fields(pops, "pop-history")["Unit"]
    # the current population counts packets AND instruments (one packet per symbol and account)
    assert current["value"] == "2 packets · 2 instruments", current["value"]
    assert "symbol" in fields(pops, "pop-current")["Dedupe"]
    # the history population names the window it is outside of
    assert history["value"] == "3 older than 48 h", history["value"]
    assert "trading" in fields(pops, "pop-history")["Rule"]
    # the event population is a DIFFERENT source: this projection does not read it and says so
    assert event["value"] == "not read by this desk"
    assert event["href"].endswith("tab=event")
    # and no overlap is claimed between the two sources
    assert row(pops, "pop-overlap")["value"] == "not counted"


def test_dr_r02_two_accounts_hold_one_instrument_but_two_packets(tmp_path):
    doc = packets(n_current=1)
    second = dict(doc["rows"][0], account="acct_b")
    doc["rows"].append(second)
    out = build(tmp_path, doc)
    pops = panel(out, "ready-now", "populations")
    # one packet per (symbol, account): the same name in two accounts is two packets, one instrument
    assert row(pops, "pop-current")["value"] == "2 packets · 1 instrument"


def test_dr_r02_visible_rows_plus_the_more_row_reconcile_to_the_current_count(tmp_path):
    out = build(tmp_path, packets(n_current=14))
    ready = panel(out, "ready-now", "ready")
    more = row(ready, "pkt-more")
    drawn = [r for r in ready["rows"] if r["id"].startswith("pkt-") and r["id"] not in ("pkt-more", "pkt-alert")]
    assert len(drawn) == desk.MAX_ROWS
    # 12 drawn + 2 more = 14 current packets, and the population row states the same total
    assert more["label"] == "2 more current packets"
    assert row(panel(out, "ready-now", "populations"), "pop-current")["value"] == "14 packets · 14 instruments"
    assert fields(panel(out, "ready-now", "populations"), "pop-current")["Shown here"] == "12 of 14 — 2 more listed below"


def test_dr_r02_an_unreadable_packet_index_states_no_population_count(tmp_path):
    out = build(tmp_path, None)
    pops = panel(out, "ready-now", "populations")
    # nothing was read: no population may print a zero as if it had counted one
    assert row(pops, "pop-current")["value"] == "not on file"
    assert row(pops, "pop-history")["value"] == "not on file"


# ── DR-R04 · per-candidate clocks ────────────────────────────────────────────────────────────────────────────
def test_dr_r04_each_row_carries_its_packet_quote_resistance_and_expiry_evidence(tmp_path):
    out = build(tmp_path, packets(), resist={"ZZ00": {"state": "TESTING", "resistance": 12.0, "distance_pct": 1.2,
                                                      "as_of": (NOW - timedelta(hours=19)).isoformat()}})
    f = fields(panel(out, "ready-now", "ready"), "pkt-ZZ00")
    assert f["Packet saved"].startswith("Sat Nov 14")
    assert f["Packet evaluated"].startswith("Sat Nov 14") and "not" not in f["Packet evaluated"]
    # the quote's age is published but its timestamp is not — say which one is missing
    assert "0.5" in f["Quote age"] and "timestamp not recorded" in f["Quote age"]
    assert f["Quote session / source"] == "not published"
    # the level carries its own evidence time from the resistance cache
    assert "12.00" in f["Resistance level"] and "TESTING" in f["Resistance level"]
    assert f["Level evidence time"].startswith("Fri Nov 13")
    # a current row states how much of the window it has used
    assert "current" in f["Expiry"] and "48" in f["Expiry"]
    # zone distance is qualified: the identity/basis it would need is not published
    assert "basis" in f["Zone distance basis"]


def test_dr_r04_an_unpriced_candidate_cannot_look_fresh(tmp_path):
    doc = packets(n_current=1)
    doc["rows"][0].update({"price": None, "quote_age_h": None, "entry_low": None, "entry_high": None})
    out = build(tmp_path, doc)
    f = fields(panel(out, "ready-now", "ready"), "pkt-ZZ00")
    assert f["Quote price"] == "not recorded in the packet"
    assert f["Quote age"] == "not recorded in the packet"
    # a fresher holdings price is a different clock; the row never borrows it
    assert f["Quote session / source"] == "not published"


def test_dr_r04_a_row_without_a_level_names_the_missing_evidence(tmp_path):
    out = build(tmp_path, packets())
    f = fields(panel(out, "ready-now", "ready"), "pkt-ZZ01")
    assert f["Resistance level"] == "no level on file"
    assert f["Level evidence time"] == "not on file"


# ── DR-X01 · eligibility scopes, Unverified by default ───────────────────────────────────────────────────────
def test_dr_x01_eligibility_is_scoped_and_unverified_until_a_gate_result_is_published(tmp_path):
    out = build(tmp_path, packets())
    elig = panel(out, "ready-now", "eligibility")
    assert row(elig, "elig-global")["value"] == "Unverified"
    assert row(elig, "elig-instrument")["value"] == "Unverified"
    # the packet's own state is a source signal, never an eligibility verdict
    assert row(elig, "elig-action")["value"] == "source signal only"
    det = fields(elig, "elig-global")
    assert det["Authoritative result"] == "not published"
    assert "LQ-2141" in det["Owner"]
    # no candidate is called clear or blocked from the global state
    txt = str(elig).lower()
    assert "blocked" not in txt and "not eligible" not in txt
    assert "a packet state is a source signal, not a gate result" in txt
    # and every candidate row says which scope its eligibility is missing for
    f = fields(panel(out, "ready-now", "ready"), "pkt-ZZ00")
    assert f["Eligibility (this action)"] == "Unverified — no gate result is published"
