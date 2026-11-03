"""Hermetic tests for the Step 3 W0 positions read model.

No DB, no broker, no live store. A fake read-only connection exercises the SQL contract.
"""
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import positions_read_model as m  # noqa: E402

NOW = datetime(2026, 11, 3, 16, 30, tzinfo=timezone.utc)

# (sync_run_id, account_key, broker, symbol, qty, cost_basis_total, avg_cost,
#  broker_market_value, is_cash, asset_type, source, captured_at)
ROW_COLS = m._SNAPSHOT_COLS
DEFAULT_ACCOUNTS = ["schwab_taxable", "schwab_roth_ira"]


def _row(run, key, symbol, qty, mv, *, cash=False, basis=100.0, as_of=NOW):
    return (run, key, "schwab" if key.startswith("schwab") else "alpaca", symbol, qty,
            basis, (basis / qty if qty and basis is not None else None), mv,
            cash, "CASH" if cash else "EQUITY", "positions_sync", as_of)


def _detail(rows):
    """The per-account position counts a real receipt carries (non-cash rows per account)."""
    out: dict[str, dict] = {}
    for r in rows:
        key = r[1]
        out.setdefault(key, {"positions": 0})
        if not r[8]:
            out[key]["positions"] += 1
    return out


def _receipt(run, rows, *, status="complete", promoted=True, accounts_ok=None, accounts_failed=None,
             accounts=None):
    return (run, status, promoted, rows, NOW, NOW,
            DEFAULT_ACCOUNTS if accounts_ok is None else accounts_ok,
            {} if accounts_failed is None else accounts_failed,
            accounts)


RUN641 = {
    641: [
        _row(641, "schwab_taxable", "AAA", 10, 1200.0),
        _row(641, "schwab_roth_ira", "BBB", 2, 80.0),
        _row(641, "schwab_taxable", "CASH", 1, 500.0, cash=True, basis=500.0),
    ]
}
RUN638 = {
    638: [
        _row(638, "schwab_taxable", "AAA", 10, 1100.0),
        _row(638, "schwab_roth_ira", "BBB", 2, 70.0),
    ]
}


class FakeCursor:
    def __init__(self, pointer, receipts, snapshots):
        self.pointer = pointer
        self.receipts = receipts
        self.snapshots = snapshots
        self.executed = []
        self._result = None

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()).lower(), params))
        s = " ".join(sql.split()).lower()
        if s.startswith("begin") or s.startswith("commit") or s.startswith("rollback"):
            self._result = None
        elif "from positions_current" in s:
            self._result = [(v,) for v in self.pointer]
        elif "from positions_sync_runs" in s:
            hit = self.receipts.get(int(params[0]))
            self._result = [hit] if hit else []
        elif "from position_snapshots" in s:
            self._result = list(self.snapshots.get(int(params[0]), []))
        else:
            self._result = []

    def fetchall(self):
        return list(self._result or [])

    def fetchone(self):
        rows = self._result or []
        return rows[0] if rows else None


class FakeConn:
    def __init__(self, pointer, receipts, snapshots):
        self._cur = FakeCursor(pointer, receipts, snapshots)

    def cursor(self):
        return self._cur

    def rollback(self):
        pass


class BoomConn:
    def cursor(self):
        raise RuntimeError("db down")


def _conn(pointer=(641,), snapshots=None, receipts=None):
    snapshots = snapshots if snapshots is not None else RUN641
    receipts = receipts if receipts is not None else {
        run: _receipt(run, len(rows), accounts_ok=sorted(_detail(rows)), accounts=_detail(rows))
        for run, rows in snapshots.items()
    }
    return FakeConn(list(pointer), receipts, snapshots)


def _export(tmp_path, doc, name="holdings_export.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


# ── healthy path: one run, run+as_of on every result ─────────────────────────

def test_rows_totals_clock_share_one_run_and_carry_as_of():
    conn = _conn(snapshots=RUN641)
    r = m.rows(conn_factory=lambda: conn)
    assert r["available"] is True and r["source"] == "db"
    assert r["sync_run_id"] == 641 and r["as_of"] == NOW.isoformat()
    assert r["count"] == 3 and all(x["sync_run_id"] == 641 for x in r["rows"])
    assert r["coverage"]["rows"] == 3 and "schwab_roth_ira" in r["coverage"]["accounts"]

    conn = _conn(snapshots=RUN641)
    t = m.totals(conn_factory=lambda: conn)
    assert t["available"] is True and t["sync_run_id"] == 641 and t["as_of"] == NOW.isoformat()
    assert t["total_value"] == 1780.0 and t["total_cash"] == 500.0 and t["invested"] == 1280.0

    conn = _conn(snapshots=RUN641)
    c = m.clock(conn_factory=lambda: conn)
    assert c["available"] is True and c["sync_run_id"] == 641 and c["as_of"] == NOW.isoformat()


# ── 0-byte / corrupt export: available false, never an empty book ────────────

def test_zero_byte_export_is_unavailable_not_empty(tmp_path):
    p = tmp_path / "holdings_export.json"
    p.write_bytes(b"")
    assert m.load_export(p) is None
    out = m.rows(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
    assert out["available"] is False
    assert "rows" not in out, "an unavailable result must not carry an empty rows list as data"
    assert out["reason"].startswith("db_unreachable")


def test_corrupt_export_is_unavailable(tmp_path):
    p = tmp_path / "holdings_export.json"
    p.write_text("{not json")
    out = m.totals(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
    assert out["available"] is False and out["reason"].startswith("db_unreachable")


def test_export_with_no_positions_is_unavailable(tmp_path):
    p = _export(tmp_path, {"sync_run_id": 641, "as_of": NOW.isoformat(), "holdings": []})
    out = m.rows(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
    assert out["available"] is False and out["export"] == "has_no_positions"


def test_valid_export_is_stamped_backup_with_run_and_as_of(tmp_path):
    p = _export(tmp_path, {
        "sync_run_id": 641, "as_of": NOW.isoformat(),
        "holdings": [{"account": "schwab_roth_ira", "symbol": "BBB", "qty": 2,
                      "broker_market_value": 80.0, "is_cash": False}],
    })
    out = m.rows(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
    assert out["available"] is True and out["source"] == "backup" and out["from_backup"] is True
    assert out["sync_run_id"] == 641 and out["as_of"] == NOW.isoformat()


def test_explicit_run_is_never_served_from_a_different_export_run(tmp_path):
    # codex counterexample: pin 638, backup is run 999 -> must be unavailable, not relabelled.
    p = _export(tmp_path, {
        "sync_run_id": 999, "as_of": NOW.isoformat(),
        "holdings": [{"account": "schwab_taxable", "symbol": "AAA", "qty": 10,
                      "broker_market_value": 1100.0}],
    })
    out = m.rows(sync_run_id=638, conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")),
                 export_path=p)
    assert out["available"] is False and out["reason"] == "export_run_mismatch"
    assert out["requested_sync_run_id"] == 638 and out["export_sync_run_id"] == 999
    assert "rows" not in out


def test_export_accepts_step1_shares_and_rebuild_run(tmp_path):
    p = _export(tmp_path, {
        "_rebuild": {"run": 641}, "as_of": NOW.isoformat(),
        "holdings": [{"account": "schwab_taxable", "symbol": "AAA", "shares": 10,
                      "market_value": 1200.0}],
    })
    out = m.rows(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
    assert out["available"] is True and out["sync_run_id"] == 641
    assert out["rows"][0]["qty"] == 10 and out["rows"][0]["broker_market_value"] == 1200.0


# ── the Roth mapping ─────────────────────────────────────────────────────────

def test_roth_is_not_split_or_dropped():
    conn = _conn(snapshots=RUN641)
    t = m.totals(conn_factory=lambda: conn)
    accounts = {a["account"]: a for a in t["accounts"]}
    assert "schwab_roth_ira" not in accounts, "the DB key leaked as a separate account"
    assert "schwab_roth" in accounts, "the Roth disappeared"
    roth = accounts["schwab_roth"]
    assert roth["account_keys"] == ["schwab_roth_ira"]
    assert roth["total_value"] == 80.0 and roth["rows"] == 1
    assert len(t["accounts"]) == 2, "Roth must join taxable as its own single account"

    conn = _conn(snapshots=RUN641)
    r = m.rows(conn_factory=lambda: conn)
    roth_rows = [x for x in r["rows"] if x["account"] == "schwab_roth"]
    assert len(roth_rows) == 1 and roth_rows[0]["account_key"] == "schwab_roth_ira"

    conn = _conn(snapshots=RUN641)
    by_label = m.rows(account="schwab_roth", conn_factory=lambda: conn)
    assert by_label["count"] == 1 and by_label["rows"][0]["symbol"] == "BBB"

    conn = _conn(snapshots=RUN641)
    by_key = m.rows(account="schwab_roth_ira", conn_factory=lambda: conn)
    assert by_key["count"] == 1 and by_key["rows"][0]["account"] == "schwab_roth"


# ── run isolation: two runs are never mixed ─────────────────────────────────

def test_explicit_run_never_reads_the_latest_pointer_or_another_run():
    conn = _conn(pointer=(641,), snapshots={**RUN641, **RUN638})
    out = m.rows(sync_run_id=638, conn_factory=lambda: conn)
    assert out["available"] is True and out["sync_run_id"] == 638
    assert {x["sync_run_id"] for x in out["rows"]} == {638}
    assert [x["symbol"] for x in out["rows"]] == ["AAA", "BBB"]
    assert out["rows"][0]["broker_market_value"] == 1100.0, "served run 641's row for a 638 request"
    assert not any("positions_current" in sql for sql, _ in conn._cur.executed), \
        "an explicit run must not consult the latest pointer"


def test_two_runs_requested_in_turn_are_never_mixed():
    conn = _conn(snapshots={**RUN641, **RUN638})
    a = m.totals(sync_run_id=638, conn_factory=lambda: conn)
    conn2 = _conn(snapshots={**RUN641, **RUN638})
    b = m.totals(sync_run_id=641, conn_factory=lambda: conn2)
    assert a["sync_run_id"] == 638 and b["sync_run_id"] == 641
    assert a["total_value"] == 1170.0 and b["total_value"] == 1780.0
    assert a["as_of"] and b["as_of"]


def test_mixed_latest_pointer_is_unavailable():
    conn = _conn(pointer=(640, 641), snapshots=RUN641)
    out = m.rows(conn_factory=lambda: conn)
    assert out["available"] is False and out["reason"] == "mixed_latest_pointer"
    assert out["pointer_runs"] == [640, 641]


def test_no_latest_pointer_is_unavailable():
    out = m.rows(conn_factory=lambda: _conn(pointer=()))
    assert out["available"] is False and out["reason"] == "no_latest_pointer"


def test_snapshot_row_count_mismatch_is_unavailable():
    receipts = {641: _receipt(641, 4, accounts=_detail(RUN641[641]))}  # receipt says 4, snapshot has 3
    out = m.rows(conn_factory=lambda: _conn(receipts=receipts))
    assert out["available"] is False and out["reason"] == "snapshot_rows_mismatch"
    assert out["receipt_rows"] == 4 and out["snapshot_rows"] == 3


def test_snapshot_account_outside_receipt_coverage_is_unavailable():
    # The fixture rows include the Roth, but the receipt claims only one account.
    receipts = {641: _receipt(641, 3, accounts_ok=["schwab_taxable"],
                              accounts={"schwab_taxable": {"positions": 1}})}
    out = m.rows(conn_factory=lambda: _conn(receipts=receipts))
    assert out["available"] is False and out["reason"] == "snapshot_account_not_in_receipt"
    assert out["missing_accounts"] == ["schwab_roth_ira"]


def test_failed_accounts_receipt_is_unavailable():
    receipts = {641: _receipt(641, 3, accounts_failed={"schwab_roth_ira": "fetch timeout"})}
    out = m.totals(conn_factory=lambda: _conn(receipts=receipts))
    assert out["available"] is False and out["reason"] == "run_has_failed_accounts"


def test_receipt_without_account_coverage_is_unavailable():
    receipts = {641: _receipt(641, 3, accounts_ok=[])}
    out = m.rows(conn_factory=lambda: _conn(receipts=receipts))
    assert out["available"] is False and out["reason"] == "run_has_no_account_coverage"


def test_run_not_promoted_is_unavailable():
    receipts = {641: _receipt(641, 3, promoted=False)}
    out = m.totals(conn_factory=lambda: _conn(receipts=receipts))
    assert out["available"] is False and out["reason"] == "run_not_promoted"


def test_run_with_no_positions_is_unavailable():
    out = m.rows(conn_factory=lambda: _conn(snapshots={641: []},
                                            receipts={641: _receipt(641, 0)}))
    assert out["available"] is False and out["reason"] == "run_has_no_positions"


def test_no_sync_receipt_is_unavailable():
    out = m.rows(conn_factory=lambda: _conn(receipts={}))
    assert out["available"] is False and out["reason"] == "no_sync_receipt"


def test_reachable_db_invalid_state_does_not_fall_back_to_export(tmp_path):
    # A valid export exists, but the DB is reachable and says "no pointer": report the DB state.
    p = _export(tmp_path, {
        "sync_run_id": 641, "as_of": NOW.isoformat(),
        "holdings": [{"account": "schwab_taxable", "symbol": "AAA", "qty": 10,
                      "broker_market_value": 1200.0}],
    })
    out = m.rows(conn_factory=lambda: _conn(pointer=()), export_path=p)
    assert out["available"] is False and out["reason"] == "no_latest_pointer"
    assert out.get("source") is None and "rows" not in out


def test_non_finite_market_value_is_unavailable():
    rows = {641: [
        _row(641, "schwab_taxable", "AAA", 10, 1200.0),
        _row(641, "schwab_taxable", "BAD", 1, math.inf),
    ]}
    out = m.rows(conn_factory=lambda: _conn(snapshots=rows))
    assert out["available"] is False and out["reason"] == "snapshot_row_numeric_invalid"


def test_missing_market_value_is_unavailable():
    rows = {641: [
        _row(641, "schwab_taxable", "AAA", 10, 1200.0),
        _row(641, "schwab_taxable", "BAD", 1, None),
    ]}
    out = m.totals(conn_factory=lambda: _conn(snapshots=rows))
    assert out["available"] is False and out["reason"] == "snapshot_row_numeric_invalid"


def test_db_unreachable_is_unavailable(tmp_path):
    out = m.totals(conn_factory=lambda: BoomConn(), export_path=tmp_path / "missing.json")
    assert out["available"] is False and out["reason"].startswith("db_unreachable")
    assert "rows" not in out and "accounts" not in out


def test_num_rejects_infinity():
    assert m._num(math.inf) is None and m._num(-math.inf) is None and m._num(math.nan) is None
    assert m._num("12.5") == 12.5 and m._num(None) is None


# ── read-only proof ─────────────────────────────────────────────────────────

def test_only_read_only_statements_are_issued():
    conn = _conn(snapshots=RUN641)
    m.rows(conn_factory=lambda: conn)
    verbs = set()
    for sql, _ in conn._cur.executed:
        verbs.add(sql.split()[0])
    assert verbs <= {"select", "begin", "rollback", "commit"}, verbs
    assert not any(v in ("insert", "update", "delete", "alter", "drop", "create") for v in verbs)
    assert any(sql.startswith("begin isolation level repeatable read read only")
               for sql, _ in conn._cur.executed)


# ── producer-shaped document ────────────────────────────────────────────────

def test_document_is_load_store_shaped_with_provenance():
    conn = _conn(snapshots=RUN641)
    out = m.document(conn_factory=lambda: conn)
    assert out["available"] is True and out["source"] == "db" and out["from_backup"] is False
    assert out["sync_run_id"] == 641 and out["as_of"] == NOW.isoformat()
    doc = out["doc"]
    assert doc["sync_run_id"] == 641 and doc["as_of"] == NOW.isoformat()
    by = {h["symbol"]: h for h in doc["holdings"]}
    assert by["AAA"]["account"] == "schwab_individual" and by["AAA"]["price"] == 120.0
    assert by["BBB"]["account"] == "schwab_roth"
    assert by["BBB"]["account_key"] == "schwab_roth_ira"
    assert by["CASH"]["is_cash"] is True and by["CASH"]["price"] == 1.0


def test_document_carries_producer_totals_and_account_summaries():
    conn = _conn(snapshots=RUN641)
    doc = m.document(conn_factory=lambda: conn)["doc"]
    pt = doc["portfolio_totals"]
    assert pt["total_value"] == 1780.0 and pt["total_cash"] == 500.0
    assert pt["basis_complete"] is True and pt["basis_unsourced_rows"] == 0
    assert pt["total_cost_basis"] == 200.0
    assert pt["total_gain"] == 1080.0
    summaries = doc["account_summaries"]
    assert set(summaries) == {"schwab_individual", "schwab_roth"}
    assert summaries["schwab_roth"]["value"] == 80.0 and summaries["schwab_roth"]["positions"] == 1
    assert summaries["schwab_individual"]["cash"] == 500.0


def test_document_basis_incomplete_leaves_totals_null():
    rows = {641: [
        _row(641, "schwab_taxable", "AAA", 10, 1200.0),
        _row(641, "schwab_roth_ira", "BBB", 2, 80.0, basis=None),
    ]}
    conn = _conn(snapshots=rows)
    doc = m.document(conn_factory=lambda: conn)["doc"]
    pt = doc["portfolio_totals"]
    assert pt["basis_complete"] is False and pt["basis_unsourced_rows"] == 1
    assert pt["total_cost_basis"] is None and pt["total_gain"] is None


def test_document_export_fallback_is_producer_shaped(tmp_path):
    p = _export(tmp_path, {
        "sync_run_id": 641, "as_of": NOW.isoformat(),
        "holdings": [{"account": "schwab_roth_ira", "symbol": "BBB", "shares": 2,
                      "market_value": 80.0, "cost_basis": 100.0}],
    })
    out = m.document(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
    assert out["available"] is True and out["source"] == "backup"
    assert set(out["doc"]["account_summaries"]) == {"schwab_roth"}
    assert out["doc"]["portfolio_totals"]["total_value"] == 80.0


def test_cash_by_symbol_counts_as_cash():
    rows = {641: [
        _row(641, "schwab_taxable", "SPAXX", 1, 250.0),   # is_cash False, cash by symbol
        _row(641, "schwab_taxable", "AAA", 10, 1200.0),
    ]}
    receipts = {641: _receipt(641, 2, accounts_ok=sorted(_detail(rows[641])), accounts=_detail(rows[641]))}
    conn = _conn(snapshots=rows, receipts=receipts)
    t = m.totals(conn_factory=lambda: conn)
    assert t["total_cash"] == 250.0 and t["total_value"] == 1450.0

    conn = _conn(snapshots=rows, receipts=receipts)
    d = m.document(conn_factory=lambda: conn)
    spaxx = next(h for h in d["doc"]["holdings"] if h["symbol"] == "SPAXX")
    assert spaxx["is_cash"] is True and spaxx["price"] == 1.0


# ── 2026-11-03 reviews: fallback shape, receipt coverage, canonical labels ─────────────────

def _receipt_detail(run, rows, accounts, *, accounts_ok=None):
    ok = sorted(accounts) if accounts_ok is None else accounts_ok
    return (run, "complete", True, rows, NOW, NOW, ok, {}, accounts)


def test_export_sync_run_id_must_be_an_integer(tmp_path):
    for bad in ("abc", "641.9", {"x": 1}):
        p = _export(tmp_path, {"sync_run_id": bad, "holdings": [
            {"account": "schwab_taxable", "symbol": "AAA", "qty": 1, "market_value": 10.0}]})
        out = m.rows(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
        assert out["available"] is False and out["export"] == "sync_run_id_invalid", bad
        assert "rows" not in out


def test_export_member_must_be_an_object(tmp_path):
    p = _export(tmp_path, {"sync_run_id": 641, "holdings": [
        {"account": "schwab_taxable", "symbol": "AAA", "qty": 1, "market_value": 10.0}, 17]})
    out = m.rows(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
    assert out["available"] is False and out["export"] == "member_not_object"
    assert out["invalid_rows"] == [1] and "rows" not in out


def test_unavailable_numeric_result_has_no_rows_key():
    rows = {641: [_row(641, "schwab_taxable", "AAA", 10, 1200.0),
                  _row(641, "schwab_taxable", "BAD", 1, math.inf)]}
    out = m.rows(conn_factory=lambda: _conn(snapshots=rows))
    assert out["available"] is False and out["reason"] == "snapshot_row_numeric_invalid"
    assert "rows" not in out and out["invalid_rows"]


def test_receipt_account_positions_must_match_the_snapshot():
    accounts = {"schwab_taxable": {"positions": 1}, "schwab_roth_ira": {"positions": 5}}
    out = m.rows(conn_factory=lambda: _conn(receipts={641: _receipt_detail(641, 3, accounts)}))
    assert out["available"] is False and out["reason"] == "snapshot_account_positions_mismatch"
    assert out["accounts"][0]["account"] == "schwab_roth_ira"


def test_receipt_account_views_must_name_the_same_accounts():
    accounts = {"schwab_taxable": {"positions": 1}}
    r = _receipt_detail(641, 3, accounts, accounts_ok=["schwab_taxable", "schwab_roth_ira"])
    out = m.rows(conn_factory=lambda: _conn(receipts={641: r}))
    assert out["available"] is False and out["reason"] == "receipt_account_views_disagree"


def test_zero_position_account_is_allowed():
    accounts = {"schwab_taxable": {"positions": 1}, "schwab_roth_ira": {"positions": 1},
                "empty_acct": {"positions": 0}}
    out = m.rows(conn_factory=lambda: _conn(receipts={641: _receipt_detail(641, 3, accounts)}))
    assert out["available"] is True and out["count"] == 3


def test_default_export_is_step1_holdings_file():
    assert m.default_export_path().as_posix().endswith("/data/portfolios/state/holdings.json")


def test_account_labels_come_from_the_canonical_config():
    assert m.label_for("schwab_roth_ira") == "schwab_roth"
    assert m.label_for("schwab_rollover_ira") == "schwab_rollover"
    assert m.label_for("schwab_taxable") == "schwab_individual"
    assert m.label_for("tradeai_automated") == "alpaca_paper"


def test_receipt_without_account_detail_is_unavailable():
    # JSONB can be null/wrong type; without the per-account proof, completeness is not claimed.
    out = m.rows(conn_factory=lambda: _conn(receipts={641: _receipt(641, 3, accounts=None)}))
    assert out["available"] is False and out["reason"] == "receipt_account_detail_missing"


def test_export_run_id_must_be_an_exact_integer(tmp_path):
    for bad in (641.9, float("inf"), 10 ** 400):
        p = _export(tmp_path, {"sync_run_id": bad, "holdings": [
            {"account": "schwab_taxable", "symbol": "AAA", "qty": 1, "market_value": 10.0}]})
        out = m.rows(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
        assert out["available"] is False and out["export"] == "sync_run_id_invalid", bad


def test_export_rebuild_must_be_an_object(tmp_path):
    p = _export(tmp_path, {"_rebuild": "corrupt", "holdings": [
        {"account": "schwab_taxable", "symbol": "AAA", "qty": 1, "market_value": 10.0}]})
    out = m.rows(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
    assert out["available"] is False and out["export"] == "no_sync_run_id"


def test_export_huge_share_count_is_unavailable_not_a_crash(tmp_path):
    p = _export(tmp_path, {"sync_run_id": 641, "holdings": [
        {"account": "schwab_taxable", "symbol": "AAA", "qty": 10 ** 400, "market_value": 10.0}]})
    out = m.rows(conn_factory=lambda: (_ for _ in ()).throw(RuntimeError("db down")), export_path=p)
    assert out["available"] is False and out["export"] == "numeric_invalid"
