"""Conflict-engine producers R9 (wash windows), R10 (option outcomes) and R12 (pending fills / ownership) over
STORED state (operator 2026-10-25: "I need you to fix everything that's missing before deployment."). Every store is
a fake SELECT answering real-row shapes; no database, no broker, no credential."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.conflicts import producers  # noqa: E402
from scripts.lib.conflicts.adapters import evaluate_inputs, security_inputs_from_truth  # noqa: E402
from tests.test_wash_sale_canonical_20261025 import NFLX, PFLT, SCHD, SPCX  # noqa: E402

NOW = datetime(2026, 10, 25, 18, tzinfo=timezone.utc)          # Sunday: no trading-day staleness noise
AT = (NOW - timedelta(hours=40)).isoformat()                   # Friday 10:00 ET evidence
ET = timezone(timedelta(hours=-4))
GUIDS = {"SPCX": "guid-spcx", "PFLT": "guid-pflt", "NFLX": "guid-nflx", "SCHD": "guid-schd", "DT": "guid-dt"}
SNAPSHOT = datetime(2026, 10, 23, 16, 52, 21, tzinfo=ET)       # holdings.json row updated_at, real 2026-10-23 sync
# Canonical holdings document rows (real shape: date-only broker_position_as_of + the sync's updated_at).
HOLDINGS = {"holdings": [
    {"account": "schwab_taxable", "symbol": "SPCX", "shares": 200.0, "broker_position_as_of": "2026-10-23",
     "as_of": "2026-10-23", "updated_at": "2026-10-23T20:52:20.072544+00:00"},
    {"account": "schwab_rollover_ira", "symbol": "SPCX", "shares": 700.0, "broker_position_as_of": "2026-10-23",
     "as_of": "2026-10-23", "updated_at": "2026-10-23T20:52:21.645221+00:00"},
    {"account": "moomoo_taxable_live", "symbol": "CASH", "is_cash": True, "as_of": "2026-10-23"}]}   # no sync time


def resolve(symbol):
    guid = GUIDS.get(symbol)
    return {"security_guid": guid, "identity_status": "CONFIRMED" if guid else "UNRESOLVED"}


def truth(symbol, stance, *, held, diagnostics=(), protection=()):
    return {"security_guid": GUIDS[symbol], "symbol": symbol,
            "canonical": {"source": "CIO record", "value": stance, "as_of": AT, "subject_id": GUIDS[symbol]},
            "context": {"held": held, "concentration_policy": {"weight_pct": 1, "limit_pct": 12,
                                                               "instrument_class": "single_stock"}},
            "saved_diagnostics": list(diagnostics), "protection_inputs": list(protection)}


class Store:
    """Answers the producers' SELECTs from fixture tables; records every statement (SELECT only)."""

    def __init__(self, transactions=(), options=(), fail=()):
        self.transactions, self.options = list(transactions), list(options)
        self.fail, self.sql = set(fail), []

    def __call__(self, sql, params=None):
        self.sql.append(sql)
        assert sql.lstrip().upper().startswith("SELECT")
        if "FROM trade_transactions WHERE upper(symbol)" in sql:
            if "wash" in self.fail:
                raise RuntimeError("relation unavailable")
            return [r for r in self.transactions if r["symbol"] in params[0]]
        if "options_strategy_positions" in sql:
            if "options" in self.fail:
                raise RuntimeError("relation unavailable")
            return [r for r in self.options if r["status"] in params[0]]
        if "trade_transactions" in sql:
            return [r for r in self.transactions if r["trade_date"] >= params[0]
                    and str(r["action"]).lower().startswith(("buy", "sell"))]
        raise AssertionError(sql)


def run(truths, store, now=NOW, holdings=HOLDINGS):
    bundles = [security_inputs_from_truth(t) for t in truths]
    bundles, summary = producers.attach(bundles, now=now, holdings=holdings, query=store, resolve_identity=resolve)
    return {b.subject.label: evaluate_inputs(b, now=now) for b in bundles}, summary, bundles


def flags(fs):
    return [f for f in fs if f.kind in {"CONFLICT", "NEEDS_OPERATOR", "GATE", "DATA_ERROR"}]


# ── R9 ─────────────────────────────────────────────────────────────────────────────────────────────────────

# Pending-fill-free history (the 10-23 IRA buy predates the 10-23 16:54 snapshot).
@pytest.mark.parametrize("symbol,rows,stance,held,expect", [
    ("SPCX", SPCX, "ADD", True, ("GATE", "BLOCKED")),           # loss sale: ADD gated in every account
    ("SPCX", SPCX, "RE_ENTER", False, ("GATE", "BLOCKED")),
    ("SPCX", SPCX, "HOLD", True, None),                          # gate applies to buys only
    ("PFLT", PFLT, "BUY", False, ("GATE", "UNKNOWN")),           # basis not on file → unknown, never clear
    ("NFLX", NFLX, "BUY", False, None),                          # IRA-only sales open no window
    ("SCHD", SCHD, "BUY", False, None),                          # (sale 09-08 is outside the window today)
])
def test_r9_wash_gate_table(symbol, rows, stance, held, expect):
    out, summary, bundles = run([truth(symbol, stance, held=held)], Store(rows))
    r9 = [f for f in out[symbol] if f.rule == "R9"]
    if expect is None:
        assert r9 == []
        return
    assert [(f.kind, f.sides[0]["value"]) for f in r9] == [(expect[0], expect[1])]
    assert r9[0].never_auto and r9[0].tier == 1 and r9[0].key.endswith(":R9:all_accounts")
    wash = next(i for i in bundles[0].inputs if i.source == "wash_sale")
    assert wash.subject_id == GUIDS[symbol] and wash.metadata["accounts_gated"] == "all"


def test_r9_gain_inside_the_house_hold_is_clear_for_the_resolver():
    out, summary, _ = run([truth("SCHD", "BUY", held=False)], Store(SCHD), now=datetime(2026, 9, 20, 18, tzinfo=timezone.utc))
    assert not any(f.rule == "R9" for f in out["SCHD"])
    assert summary["wash_windows"] == {"HOUSE_HOLD_NO_LOSS": ["SCHD"]}


def test_r9_unreadable_store_is_an_unknown_gate_and_a_visible_gap_never_a_silent_clear():
    out, summary, _ = run([truth("SPCX", "ADD", held=True)], Store(SPCX, fail={"wash"}))
    assert any(f.rule == "R9" and f.kind == "GATE" for f in out["SPCX"])
    assert any(f.kind == "DATA_ERROR" and "wash-window producer unavailable" in f.summary for f in out["SPCX"])
    assert summary["gaps"] == ["wash-window producer unavailable: RuntimeError"]


# ── R10 ────────────────────────────────────────────────────────────────────────────────────────────────────

def option(underlying, strategy_type, *, status="open", source="broker_sync", quality="ok", recommendation=None):
    return {"strategy_position_id": 41, "broker": "schwab", "account_key": "schwab_rollover_ira",
            "strategy_type": strategy_type, "underlying": underlying, "status": status, "source": source,
            "opened_at": datetime(2026, 10, 1, 10, tzinfo=ET), "updated_at": datetime(2026, 10, 23, 16, tzinfo=ET),
            "data_quality_status": quality, "recommendation": recommendation,
            "recommendation_at": datetime(2026, 10, 23, 16, 5, tzinfo=ET) if recommendation else None}


@pytest.mark.parametrize("stance,held,row,rule", [
    ("EXIT", True, option("DT", "long_call"), "R10"),                                   # long call vs equity EXIT
    ("HOLD", True, option("DT", "long_call", recommendation="CLOSE"), None),            # option CLOSE ≠ equity stance
    ("ADD", True, option("DT", "covered_call", recommendation="ROLL"), None),
    ("EXIT", True, option("DT", "long_call", source="paper_lane"), None),               # paper never a side
    ("EXIT", True, option("DT", "long_call", status="closed"), None),                   # outcome, not a position
    ("EXIT", True, option("DT", "long_call", quality="ambiguous"), None),               # R14: no opinion
])
def test_r10_option_positions_are_never_equity_stances(stance, held, row, rule):
    out, summary, bundles = run([truth("DT", stance, held=held)], Store(options=[row]))
    rules = {f.rule for f in flags(out["DT"])}
    if rule:
        r10 = next(f for f in out["DT"] if f.rule == "R10")
        assert r10.kind == "NEEDS_OPERATOR" and r10.never_auto and summary["option_claims"] == 1
        assert {s["source"] for s in r10.sides} == {"CIO record", "option_position"}
    else:
        assert rules <= {"R1"} and not any(f.rule in {"R10", "U7", "R11", "R8"} for f in out["DT"])
        assert not any(s["source"] == "option_position" for f in out["DT"] for s in f.sides)


# ── R12 ────────────────────────────────────────────────────────────────────────────────────────────────────

def fill(action, hh, mm, day="2026-10-23", account="schwab_taxable", symbol="DT"):
    y, m, d = map(int, day.split("-"))
    return {"account": account, "symbol": symbol, "action": action, "trade_date": date(y, m, d),
            "trade_time": datetime(y, m, d, hh, mm, tzinfo=ET), "quantity": Decimal("100"), "price": Decimal("63.0")}


@pytest.mark.parametrize("rows,pending", [
    ([fill("Buy", 17, 30)], True),                                       # recorded after the 16:52 sync
    ([fill("Sell", 12, 50)], False),                                     # already in the synced positions
    ([{**fill("Buy", 0, 0, day="2026-10-24"), "trade_time": None}], True),   # date only, next day
    ([{**fill("Buy", 0, 0), "trade_time": None}], False),                    # date only, same day: reflected
])
def test_r12_fill_after_the_positions_snapshot_freezes_the_name(rows, pending):
    out, summary, bundles = run([truth("DT", "ADD", held=True)], Store(rows))
    r12 = [f for f in out["DT"] if f.rule == "R12"]
    if pending:
        assert [f.kind for f in r12] == ["DATA_ERROR"] and r12[0].never_auto and r12[0].tier == 1
        assert bundles[0].subject.context["pending_fill"] is True and summary["pending_fills"] == 1
        assert not any(f.rule in {"U7", "R11", "R6", "R13"} for f in out["DT"]), "evaluation frozen"
    else:
        assert r12 == [] and summary["pending_fills"] == 0


def test_holdings_snapshot_is_the_brokers_sync_stamp_never_a_date_only_field():
    snaps = producers.holdings_snapshots(HOLDINGS)
    assert snaps == {"schwab_taxable": datetime(2026, 10, 23, 20, 52, 20, 72544, tzinfo=timezone.utc),
                     "schwab_rollover_ira": datetime(2026, 10, 23, 20, 52, 21, 645221, tzinfo=timezone.utc)}


def test_r12_no_holdings_sync_time_at_all_is_a_visible_gap_never_a_silent_pass():
    out, summary, _ = run([truth("DT", "ADD", held=True)], Store([fill("Buy", 17, 30)]), holdings={"holdings": []})
    assert summary["gaps"] == ["pending-fill producer unavailable: LookupError"]
    assert any(f.kind == "DATA_ERROR" and "pending-fill producer unavailable" in f.summary for f in out["DT"])


def test_r12_fill_in_an_account_without_a_snapshot_is_a_visible_gap_for_that_name_only():
    rows = [fill("Buy", 17, 30, account="moomoo_taxable_live")]
    out, summary, _ = run([truth("DT", "ADD", held=True), truth("NFLX", "WATCH", held=False)], Store(rows))
    assert any(f.kind == "DATA_ERROR" and "no positions snapshot for moomoo_taxable_live" in f.summary for f in out["DT"])
    assert not any("positions snapshot" in f.summary for f in out["NFLX"])


NAVN_HELD = {"id": "conflict-held", "field": "held", "resolved": False,
             "sides": [{"source": "positions[holdings.json]", "value": "held", "as_of": "2026-10-23T16:54:03-04:00"},
                       {"source": "schwab_round_trips srt:607228 exit fill", "value": "closed",
                        "as_of": "2026-10-22T15:59:21-04:00"}]}
NAVN_STANCE = {"id": "conflict-sae", "field": "stance_after_exit", "resolved": False,
               "sides": [{"source": "cio_opportunity_projection", "value": "ADD", "as_of": "2026-10-23T09:00:00-04:00"},
                         {"source": "schwab_round_trips srt:607228", "value": "exited",
                          "as_of": "2026-10-22T15:59:21-04:00"}]}


@pytest.mark.parametrize("diagnostic,flagged", [(NAVN_HELD, True), (NAVN_STANCE, True),
                                                ({**NAVN_HELD, "resolved": True}, False),
                                                ({**NAVN_HELD, "field": "cost_basis"}, False)])
def test_r12_stance_or_position_vs_fill_is_an_ownership_data_error(diagnostic, flagged):
    out, summary, _ = run([truth("DT", "ADD", held=True, diagnostics=[diagnostic])], Store())
    r12 = [f for f in out["DT"] if f.rule == "R12"]
    if flagged:
        assert len(r12) == 1 and r12[0].kind == "DATA_ERROR" and r12[0].never_auto and r12[0].owner == "positions owner"
        assert r12[0].summary.startswith("Ownership disagrees with a recorded fill")
        assert not any(f.rule in {"U7", "R11", "R6"} for f in out["DT"])
        assert summary["ownership_facts"] == 1
    else:
        assert r12 == []


def test_r12_ownership_and_pending_fill_findings_are_never_resolvable(tmp_path):
    from scripts.lib.conflicts.ledger import DECISION_SCHEMA, ConflictLedger
    out, _, bundles = run([truth("DT", "ADD", held=True, diagnostics=[NAVN_HELD])], Store([fill("Buy", 17, 30)]))
    hard = [f for f in out["DT"] if f.rule == "R12"]
    assert len(hard) == 2
    ledger = ConflictLedger(tmp_path, memory_writer=lambda e: True)
    ledger.reconcile(bundles[0].subject, hard, at=NOW, apply=True)
    for key in ledger.records():
        decision = {"schema": DECISION_SCHEMA, "actor_kind": "operator", "actor": "op", "chosen_side": "ADD",
                    "reason": "x", "evidence_refs": ["x"], "expires_at": (NOW + timedelta(days=1)).isoformat()}
        with pytest.raises(ValueError):
            ledger.transition(key, "decided", at=NOW, decision=decision, apply=False)


# ── identity, read-only, runner wiring ──────────────────────────────────────────────────────────────────────

def test_producer_rows_join_by_confirmed_guid_only():
    # GLAS is UNRESOLVED in the registry (EXCEPTIONS_MATRIX R16): its option row never joins any bundle by label.
    out, summary, bundles = run([truth("DT", "EXIT", held=True)], Store(options=[option("GLAS", "long_call"),
                                                                                  option("DT", "long_call")]))
    assert summary["unresolved_symbols"] == ["GLAS"] and summary["option_claims"] == 1
    assert [i.metadata["strategy_type"] for i in bundles[0].inputs if i.source == "option_position"] == ["long_call"]
    assert all(i.subject_id == GUIDS["DT"] for i in bundles[0].inputs if i.source == "option_position")


def test_producers_issue_select_statements_only():
    store = Store(SPCX, options=[option("DT", "long_call")])
    run([truth("SPCX", "ADD", held=True), truth("DT", "EXIT", held=True)], store)
    assert len(store.sql) == 3 and all(s.lstrip().upper().startswith("SELECT") for s in store.sql)
    src = (ROOT / "scripts/lib/conflicts/producers.py").read_text()
    for forbidden in ("place_order", "schwab_transport", "broker_adapter", "INSERT", "UPDATE ", "DELETE",
                      "positions_current"):   # governed positions_store: no unapproved reader
        assert forbidden not in src


def test_runner_attaches_producers_on_the_collected_path_only(tmp_path, monkeypatch):
    import json
    import scripts.conflict_resolver as cr
    seen = {}
    real_attach = producers.attach
    monkeypatch.setattr(cr, "collect_inputs", lambda root, now: [security_inputs_from_truth(truth("SPCX", "ADD", held=True))])

    def fake_attach(bundles, *, now, root):
        seen["bundles"], seen["root"] = len(bundles), root
        return real_attach(bundles, now=now, holdings=HOLDINGS, query=Store(SPCX), resolve_identity=resolve)
    monkeypatch.setattr(producers, "attach", fake_attach)
    assert cr.main(["--dry-run", "--state-root", str(tmp_path / "absent")]) == 0
    assert seen == {"bundles": 1, "root": str(tmp_path / "absent")} and not (tmp_path / "absent").exists()
    fixture = tmp_path / "f.json"
    fixture.write_text(json.dumps({"subjects": []}))
    seen.clear()
    assert cr.main(["--dry-run", "--state-root", str(tmp_path / "absent"), "--input-file", str(fixture)]) == 0
    assert seen == {}, "replay fixtures are never enriched from live stores"
