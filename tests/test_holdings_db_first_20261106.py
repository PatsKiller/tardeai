"""Database-first holdings (operator 2026-11-06, "go with all three").

(a) the export renders every field and key the readers use — the PARITY test greps the reader modules and
    fails on any field they access that the export does not render;
(b) positions_sync --apply chains the export under the shared holdings lock (the Schwab sync's full
    ISO-8601 stamp ships separately: that file is an always-held broker path);
(c) lib/holdings_document serves the export's render from the DB, the file only as the stated fallback.

Synthetic fixtures only (public repo): no real symbol, value, account number or capture.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# HOLDINGS_EXPORT_UNDER_TEST lets the parity proof run the SAME assertions against another revision's
# exporter (the PR shows it failing on origin/main). Default: this tree's.
_EXPORT_PATH = Path(os.environ.get("HOLDINGS_EXPORT_UNDER_TEST") or ROOT / "scripts/holdings_export.py")
_spec = importlib.util.spec_from_file_location("holdings_export_db_first_under_test", _EXPORT_PATH)
he = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = he
_spec.loader.exec_module(he)

NOW = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)   # 11:00 ET, market open
AS_OF = NOW - timedelta(minutes=5)
RUN_ID = 7

# ── the readers (Home / API and the libraries they call) ─────────────────────────────────────────
READER_MODULES = (
    "scripts/api_v2.py",
    "scripts/lib/cio_truth.py",
    "scripts/lib/data_broker/portfolio_snapshot.py",
    "scripts/lib/data_broker/risk_snapshot.py",
    "scripts/lib/data_broker/advisory_desk.py",
    "scripts/lib/portfolio_positions.py",
    "scripts/lib/holding_day_change.py",
    "scripts/lib/account_state.py",
    "scripts/lib/book_map_rows.py",
    "scripts/lib/cio_canonical_quote.py",
    "scripts/lib/cio_financial_truth_gate.py",
    "scripts/lib/portfolio_aggregate_contract.py",
    "scripts/lib/holdings_universe.py",
    "scripts/lib/positions_read_model.py",
)

# Key NAMES of the served holdings.json (inventory taken 2026-11-06; names only, no values).
INVENTORY_TOP = (
    "_freshness_note", "_rebuild", "account_summaries", "aggregate_published_at", "as_of", "closed_today",
    "data_as_of", "data_as_of_account", "generated_at", "holdings", "last_repriced", "lookthrough_as_of",
    "overlap_analysis", "owner", "portfolio_totals", "positions_built_at", "positions_fingerprint",
    "reprice_source", "resolved_sector_contributors", "resolved_sector_underlyings", "resolved_sectors",
    "resolved_sectors_by_account", "updated_at",
)
INVENTORY_ROW = (
    "_basis_rebased_from", "_rebuild_source", "account", "account_id", "account_scope", "analytical_market_value",
    "analytical_unrealized_pl_usd", "as_of", "asset_type", "avg_cost", "basis_partial", "basis_status",
    "broker_actual_shares", "broker_avg_price", "broker_day_pl", "broker_day_pl_at", "broker_day_pl_price",
    "broker_ingested_at", "broker_market_value", "broker_position_as_of", "broker_position_as_of_at",
    "broker_position_price", "broker_shares", "broker_source", "bucket", "business_date", "calculation_version",
    "canonical_mark", "canonical_mark_as_of", "canonical_mark_ingested_at", "canonical_mark_source",
    "canonical_mark_type", "conflict_reason", "conflicted", "contract_version", "cost_basis", "cost_basis_source",
    "cost_basis_total", "current_price", "current_price_is_alias_of", "day_change", "day_change_broker_check",
    "day_change_pct", "delisted", "entitlement_state", "freshness_state", "gain_loss", "gain_loss_pct",
    "implied_price_from_mv", "is_cash", "last_reconciled_at", "last_reconciliation_source", "lots_shares",
    "market_session", "market_value", "mv_basis", "name", "normalized_at", "observation", "official_close",
    "official_close_as_of", "portfolio_pct", "price", "price_field_role", "price_source", "provider_observed_at",
    "quality_state", "quantity", "received_at", "share_drift", "share_drift_status", "shares", "shares_synced_at",
    "source", "source_identity", "symbol", "system_shares", "updated_at",
)
INVENTORY_TOTALS = (
    "as_of", "basis_complete", "basis_note", "basis_unsourced_rows", "day_change", "day_change_note",
    "day_change_pct", "excluded_count", "last_pipeline_run", "note", "total_cash", "total_cash_source",
    "total_cash_written_at", "total_cost", "total_cost_basis", "total_gain", "total_gain_pct",
    "total_mv_excluded", "total_mv_with_cost", "total_value", "total_value_recomputed_at_write",
)
INVENTORY_SUMMARY = (
    "account_state", "as_of", "cash", "day_change", "day_change_pct", "display_name", "holdings_count",
    "last_repriced", "positions", "state", "state_as_of", "state_reason", "total_gain", "total_gain_pct",
    "total_value", "value",
)
#: Fields the export derives itself for a row with no previous row: never a carried value.
FLOOR_ROW = ("symbol", "account", "account_id", "shares", "quantity", "market_value", "price", "current_price",
             "is_cash", "cost_basis", "day_change", "day_change_pct", "gain_loss", "broker_position_as_of",
             "broker_position_as_of_at", "as_of", "updated_at", "broker_market_value", "broker_actual_shares")


def _reader_source() -> str:
    return "\n".join((ROOT / m).read_text(encoding="utf-8") for m in READER_MODULES)


def reader_used(keys) -> list[str]:
    src = _reader_source()
    return [k for k in keys if re.search(r"""["']%s["']""" % re.escape(k), src)]


# ── a synthetic database ─────────────────────────────────────────────────────────────────────────
def db_positions():
    def row(account, symbol, qty, cost, avg, value, cash=False, asset="EQUITY"):
        return {"account_key": account, "symbol": symbol, "broker": account.split("_", 1)[0], "qty": qty,
                "cost_basis_total": cost, "avg_cost": avg, "broker_market_value": value, "is_cash": cash,
                "asset_type": "CASH" if cash else asset, "source": "schwab_api", "as_of": AS_OF,
                "sync_run_id": RUN_ID}
    return [
        row("schwab_roth_ira", "AAA", 10.0, 500.0, 50.0, 1200.0),
        row("schwab_roth_ira", "CASH", 300.0, 300.0, 1.0, 300.0, cash=True),
        row("schwab_rollover_ira", "BBB", 5.0, 400.0, 80.0, 450.0),
        row("schwab_rollover_ira", "CASH", 1000.0, 1000.0, 1.0, 1000.0, cash=True),
        row("schwab_taxable", "CCC", 2.0, 150.0, 75.0, 200.0),
        row("alpaca_taxable_live", "CASH", 50.0, 50.0, 1.0, 50.0, cash=True),
    ]


class FakeDB:
    """positions_current + receipt + enrichment tables, answering the SQL the exporter issues."""

    def __init__(self, positions=None, *, binding=True, quotes=True, fail=False):
        self.positions = positions if positions is not None else db_positions()
        self.binding = binding
        self.quotes = quotes
        self.fail = fail
        self.queries: list[str] = []

    def query(self, sql, params=None, fetch="all"):
        self.queries.append(sql)
        if self.fail:
            return None
        low = " ".join(sql.split()).lower()
        if "from positions_sync_runs" in low:
            if "select status" in low:
                return [{"status": "complete"}, {"status": "complete"}]
            if not self.binding:
                return []
            return [{"run_id": RUN_ID, "finished_at": NOW - timedelta(minutes=4),
                     "accounts_ok": sorted({p["account_key"] for p in self.positions}), "accounts_failed": {},
                     "position_rows": len(self.positions)}]
        if "sum(broker_market_value)" in low:
            return [{"sum": sum(p["broker_market_value"] for p in self.positions)}]
        if "from positions_current" in low:
            return [dict(p) for p in self.positions]
        if "from market_quotes_extended" in low:
            return ([{"symbol": "CCC", "price": 101.0, "bar_end": NOW, "inserted_at": NOW, "session": "regular",
                      "reference_close": 100.0, "reference_basis": "prior_session_close", "change_pct": 1.0,
                      "feed": "sip"}] if self.quotes else [])
        if "to_regclass" in low:
            return [{"to_regclass": None}]
        return []


class FakeConn:
    """A DB-API connection over FakeDB (independent of lib.holdings_document, so the parity proof can run
    the same test against an exporter revision that predates that module)."""

    def __init__(self, db: FakeDB):
        self.db = db

    def cursor(self):
        db = self.db

        class _Cur:
            description: list = []
            _rows: list = []

            def execute(self, sql, params=None):
                result = db.query(sql, params)
                if result is None:
                    raise RuntimeError("connection refused")
                cols = list(result[0].keys()) if result else []
                self.description = [(c,) for c in cols]
                self._rows = [tuple(r.get(c) for c in cols) for r in result]

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0] if self._rows else None

        return _Cur()


# ── a synthetic previous document carrying every inventory key ───────────────────────────────────
def _full_row(account, symbol, *, shares, value, cash=False):
    row = {k: f"carried:{k}" for k in INVENTORY_ROW}
    row.update({"account": account, "account_id": account, "symbol": symbol, "is_cash": cash,
                "shares": shares, "system_shares": shares, "quantity": shares, "broker_actual_shares": shares,
                "market_value": value, "price": round(value / shares, 4), "current_price": round(value / shares, 4),
                "cost_basis": 111.0, "gain_loss": 1.0, "gain_loss_pct": 1.0, "day_change": 2.5,
                "day_change_pct": 0.2, "portfolio_pct": 1.0, "broker_market_value": 1.0,
                "broker_position_as_of": "2026-10-01", "broker_position_as_of_at": "2026-10-01T15:00:00+00:00",
                "as_of": "2026-10-01", "account_key": "stale-key", "asset_type": None,
                "broker_day_pl": 3.0, "broker_day_pl_price": 9.0, "broker_day_pl_at": "2026-11-03T15:50:00+00:00",
                "canonical_mark": 120.0, "share_drift_status": "aligned", "share_drift": 0})
    return row


def prior_document():
    top = {k: f"carried:{k}" for k in INVENTORY_TOP}
    top.update({"closed_today": {}, "resolved_sectors": [{"sector": "Synthetic", "value": 1.0}],
                "resolved_sectors_by_account": {}, "resolved_sector_contributors": {},
                "resolved_sector_underlyings": {}, "overlap_analysis": {"overlaps": []}, "_rebuild": {}})
    holdings = [
        _full_row("schwab_roth", "AAA", shares=10.0, value=1210.0),
        _full_row("schwab_roth", "CASH", shares=300.0, value=300.0, cash=True),
        # Sticky system shares: the share policy kept 4.9 while the broker says 5 — the export must not decide.
        _full_row("schwab_rollover_ira", "BBB", shares=4.9, value=441.0),
        _full_row("schwab_rollover_ira", "CASH", shares=1000.0, value=1000.0, cash=True),
        _full_row("alpaca_taxable_live", "CASH", shares=50.0, value=50.0, cash=True),
        _full_row("schwab_taxable", "ZZZ", shares=3.0, value=30.0),        # sold: not in the DB any more
        _full_row("offline_brokerage", "DDD", shares=1.0, value=10.0),     # an account the DB never syncs
    ]
    summary = {k: f"carried:{k}" for k in INVENTORY_SUMMARY}
    top.update({
        "holdings": holdings,
        "portfolio_totals": {k: f"carried:{k}" for k in INVENTORY_TOTALS} | {"total_value": 3041.0},
        "account_summaries": {a: dict(summary, total_value=1.0) for a in
                              ("schwab_roth", "schwab_rollover_ira", "schwab_taxable", "alpaca_taxable_live")},
        "positions_fingerprint": "different", "positions_built_at": "2026-10-01T00:00:00Z",
    })
    return top


def export_with_prior(tmp_path, prior=None, db=None):
    state = tmp_path / "state"
    store = he.store_path(state)
    store.parent.mkdir(parents=True, exist_ok=True)
    if prior is not None:
        store.write_text(json.dumps(prior), encoding="utf-8")
    he.export(conn=FakeConn(db or FakeDB()), state_root=state, store=store, now=NOW)
    return json.loads(store.read_text(encoding="utf-8"))


# ── (a) parity ───────────────────────────────────────────────────────────────────────────────────
def test_the_reader_grep_finds_the_fields_the_lead_named():
    used_rows = set(reader_used(INVENTORY_ROW))
    used_top = set(reader_used(INVENTORY_TOP))
    # The fields named in the 2026-11-06 measurement must be reachable by this grep, or the parity test
    # below would pass on an export that lacks them.
    assert {"broker_day_pl", "broker_day_pl_at", "canonical_mark", "broker_market_value", "basis_status",
            "analytical_market_value", "bucket"} <= used_rows
    assert {"resolved_sectors", "resolved_sectors_by_account", "data_as_of", "data_as_of_account",
            "last_repriced", "positions_built_at"} <= used_top
    assert len(used_rows) >= 50 and len(used_top) >= 15


def test_parity_every_reader_field_is_rendered(tmp_path):
    doc = export_with_prior(tmp_path, prior_document())
    missing_top = [k for k in reader_used(INVENTORY_TOP) if k not in doc]
    rows_by_key = {(r["account"], r["symbol"]): r for r in doc["holdings"]}
    carried = [rows_by_key[k] for k in (("schwab_roth", "AAA"), ("schwab_rollover_ira", "BBB"))]
    missing_row = sorted({k for r in carried for k in reader_used(INVENTORY_ROW) if k not in r})
    missing_totals = [k for k in reader_used(INVENTORY_TOTALS) if k not in doc["portfolio_totals"]]
    roth = doc["account_summaries"].get("schwab_roth") or {}
    missing_summary = [k for k in reader_used(INVENTORY_SUMMARY) if k not in roth]
    assert not (missing_top or missing_row or missing_totals or missing_summary), (
        f"export lacks reader fields: top={missing_top} row={missing_row} "
        f"totals={missing_totals} summary={missing_summary}")


def test_parity_the_whole_served_inventory_survives_an_export(tmp_path):
    """Stronger than the grep: nothing any writer put on the served document is erased by an export."""
    doc = export_with_prior(tmp_path, prior_document())
    assert [k for k in INVENTORY_TOP if k not in doc] == []
    for key in (("schwab_roth", "AAA"), ("schwab_rollover_ira", "BBB"), ("schwab_roth", "CASH")):
        row = next(r for r in doc["holdings"] if (r["account"], r["symbol"]) == key)
        assert [k for k in INVENTORY_ROW if k not in row] == [], key
    assert [k for k in INVENTORY_TOTALS if k not in doc["portfolio_totals"]] == []


# ── (a) ownership: DB facts win, other writers' fields are carried, nothing is invented ──────────
def test_db_owned_facts_always_win_over_the_previous_document(tmp_path):
    doc = export_with_prior(tmp_path, prior_document())
    aaa = next(r for r in doc["holdings"] if r["symbol"] == "AAA")
    assert aaa["broker_market_value"] == 1200.0 and aaa["broker_actual_shares"] == 10.0
    assert aaa["account_key"] == "schwab_roth_ira" and aaa["asset_type"] == "EQUITY"
    assert aaa["broker_position_as_of"] == "2026-11-03T15:55:00Z" == aaa["broker_position_as_of_at"]
    assert aaa["cost_basis_total"] == 500.0 and aaa["sync_run_id"] == RUN_ID
    # carried: the repricer's mark and the broker's day P/L stay; the reader name `cost_basis` keeps the
    # basis shield's value, the DB's broker figure is cost_basis_total.
    assert aaa["market_value"] == 1210.0 and aaa["canonical_mark"] == 120.0 and aaa["broker_day_pl"] == 3.0
    assert aaa["cost_basis"] == 111.0


def test_the_share_policy_is_carried_not_decided_by_the_export(tmp_path):
    doc = export_with_prior(tmp_path, prior_document())
    bbb = next(r for r in doc["holdings"] if r["symbol"] == "BBB")
    assert bbb["shares"] == 4.9 and bbb["system_shares"] == 4.9 and bbb["quantity"] == 4.9
    assert bbb["broker_actual_shares"] == 5.0 and bbb["broker_shares"] == 5.0


def test_a_sold_position_is_dropped_and_an_unsynced_account_is_carried_and_named(tmp_path):
    doc = export_with_prior(tmp_path, prior_document())
    keys = {(r["account"], r["symbol"]) for r in doc["holdings"]}
    assert ("schwab_taxable", "ZZZ") not in keys
    assert ("offline_brokerage", "DDD") in keys
    assert any("offline_brokerage" in g for g in doc["gaps"])


def test_a_new_position_renders_the_floor_and_invents_nothing(tmp_path):
    doc = export_with_prior(tmp_path, prior_document())
    ccc = next(r for r in doc["holdings"] if r["symbol"] == "CCC")
    assert [k for k in FLOOR_ROW if k not in ccc] == []
    assert ccc["account"] == "schwab_taxable" and ccc["shares"] == 2.0 and ccc["market_value"] == 200.0
    assert ccc["price"] == 101.0 and ccc["day_change"] == 2.0 and ccc["cost_basis"] == 150.0
    assert "name" not in ccc and "bucket" not in ccc            # never invented


def test_no_previous_document_renders_from_the_db_alone_and_says_so(tmp_path):
    doc = export_with_prior(tmp_path, None)
    assert {r["symbol"] for r in doc["holdings"]} == {"AAA", "CASH", "BBB", "CCC"}
    for r in doc["holdings"]:
        assert [k for k in FLOOR_ROW if k not in r] == [], r["symbol"]
    assert "resolved_sectors" not in doc and "last_repriced" not in doc     # enricher keys: absent, not invented
    assert any("no usable previous document" in g for g in doc["gaps"])
    assert doc["export_provenance"]["prior_used"] is False


def test_the_roth_keeps_the_store_label_and_nothing_else_is_renamed(tmp_path):
    doc = export_with_prior(tmp_path, None)
    accounts = {r["account"] for r in doc["holdings"]}
    assert accounts == {"schwab_roth", "schwab_rollover_ira", "schwab_taxable", "alpaca_taxable_live"}
    assert set(doc["account_summaries"]) >= accounts
    from lib.account_display import canonical_key
    assert canonical_key("schwab_roth") == "schwab_roth_ira"     # canonical readers still join the Roth


def test_the_three_writers_agree_on_the_roth_label():
    import positions_sync
    tree = ast.parse((ROOT / "scripts/schwab_position_sync.py").read_text(encoding="utf-8"))
    sync_map = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_HOLDINGS_ACCT" for t in n.targets))
    assert he.HOLDINGS_LABELS == sync_map
    assert {v: k for k, v in positions_sync.HOLDINGS_ACCOUNT_ALIASES.items()} == he.HOLDINGS_LABELS


def test_totals_are_the_repricers_and_the_alert_checks_the_broker_values(tmp_path):
    doc = export_with_prior(tmp_path, prior_document())
    totals = doc["portfolio_totals"]
    assert totals["total_value"] == round(sum(r["market_value"] for r in doc["holdings"]), 2)
    db_total = sum(p["broker_market_value"] for p in db_positions())
    assert totals["broker_market_value_total"] == db_total
    # The repricer's valuation differs from the broker's by the mark; that is not a P1.
    assert totals["total_value"] != db_total
    store = he.store_path(tmp_path / "state")
    sent = []
    out = he.maybe_alert_stale(store=store, state_root=tmp_path / "state", now=NOW + timedelta(minutes=1),
                               send=lambda *a, **k: sent.append(a) or True, conn=FakeConn(FakeDB()))
    assert out["status"] == "fresh" and sent == []


def test_positions_built_at_moves_only_when_the_position_list_changes(tmp_path):
    first = export_with_prior(tmp_path, prior_document())
    assert first["positions_built_at"] == "2026-11-03T15:56:00Z"      # list changed: the run's finish time
    store = he.store_path(tmp_path / "state")
    he.export(conn=FakeConn(FakeDB()), state_root=tmp_path / "state", store=store, now=NOW + timedelta(minutes=15))
    second = json.loads(store.read_text(encoding="utf-8"))
    assert second["positions_built_at"] == first["positions_built_at"]
    assert second["generated_at"] != first["generated_at"]


def test_a_full_iso_broker_stamp_parses_to_the_instant():
    from lib.account_state import parse_time
    assert parse_time("2026-11-03T15:55:00Z") == datetime(2026, 11, 3, 15, 55, tzinfo=timezone.utc)
    assert parse_time("2026-11-03") == datetime(2026, 11, 3, tzinfo=timezone.utc)   # what date-only fabricated


# ── (b) the sync is the writer ───────────────────────────────────────────────────────────────────
class _Lock:
    def __init__(self):
        self.entered = 0

    def __call__(self):
        @contextmanager
        def _cm():
            self.entered += 1
            yield
        return _cm()


def test_export_holdings_writes_under_the_lock_after_a_promoted_run(tmp_path):
    import positions_sync
    lock = _Lock()
    state = tmp_path / "state"
    state.mkdir()
    receipt = positions_sync.export_holdings(dry_run=False, exporter=he, connect=lambda: FakeConn(FakeDB()),
                                             lock=lock, alert=False, state_root=state, now=NOW)
    assert receipt["ok"] and lock.entered == 1
    assert json.loads(he.store_path(state).read_text())["sync_run_id"] == RUN_ID


def test_a_refused_export_is_reported_and_never_raises_into_the_sync(tmp_path):
    import positions_sync
    state = tmp_path / "state"
    state.mkdir()
    receipt = positions_sync.export_holdings(dry_run=False, exporter=he, connect=lambda: FakeConn(FakeDB(binding=False)),
                                             lock=_Lock(), alert=False, state_root=state, now=NOW)
    assert receipt["ok"] is False and "no complete, promoted" in receipt["refused"]
    assert not he.store_path(state).exists()


def test_main_exports_only_after_a_promoted_run(monkeypatch):
    import positions_sync
    calls = []
    monkeypatch.setattr(positions_sync, "export_holdings", lambda **k: calls.append(k) or {"ok": True})

    class _C:
        def cursor(self):
            class _K:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            return _K()

        def rollback(self):
            pass

    monkeypatch.setattr(positions_sync, "_conn", lambda: _C())
    monkeypatch.setattr(positions_sync, "load_ledger", lambda cur, cfg: [])
    monkeypatch.setattr(positions_sync, "open_run", lambda conn: 1)
    monkeypatch.setattr(positions_sync, "write_run", lambda *a, **k: None)
    ok = {"ok": True, "cash": 1.0, "equity": 1.0, "positions": [], "source": "fake",
          "captured_at": NOW}
    monkeypatch.setattr(positions_sync, "read_accounts", lambda accts, readers=None: {a: dict(ok) for a in accts})
    assert positions_sync.main(["--apply"]) == 0 and calls == [{"dry_run": False}]
    calls.clear()
    monkeypatch.setattr(positions_sync, "read_accounts",
                        lambda accts, readers=None: {a: ({"ok": False, "error": "x", "captured_at": NOW}
                                                         if a == "schwab_taxable" else dict(ok)) for a in accts})
    assert positions_sync.main(["--apply"]) == 1 and calls == []        # partial run: no export


# ── (c) the readers read the DB ──────────────────────────────────────────────────────────────────
def _hd():
    from lib import holdings_document
    holdings_document.clear_cache()
    return holdings_document


def _write_prior(tmp_path):
    store = he.store_path(tmp_path / "state")
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(prior_document()), encoding="utf-8")
    return store


def test_db_first_serves_the_exports_render(tmp_path):
    hd = _hd()
    store = _write_prior(tmp_path)
    before = store.read_bytes()
    doc = hd.load_document(store, db_query=FakeDB().query, now=NOW, use_cache=False)
    assert doc["document_source"] == "positions_current" and doc["document_fallback_reason"] is None
    assert doc["sync_run_id"] == RUN_ID and [k for k in reader_used(INVENTORY_TOP) if k not in doc] == []
    assert store.read_bytes() == before                     # a read never writes


def test_an_unreachable_db_falls_back_to_the_file_and_says_so(tmp_path):
    hd = _hd()
    store = _write_prior(tmp_path)
    doc = hd.load_document(store, db_query=FakeDB(fail=True).query, now=NOW, use_cache=False)
    assert doc["document_source"] == "holdings_json_fallback"
    assert doc["document_fallback_reason"].startswith("database unreachable")
    assert doc["holdings"][0]["broker_position_as_of"] == "2026-10-01"     # the file's own clock, not borrowed


def test_a_db_that_answers_but_cannot_bind_a_run_falls_back_with_the_reason(tmp_path):
    hd = _hd()
    store = _write_prior(tmp_path)
    doc = hd.load_document(store, db_query=FakeDB(binding=False).query, now=NOW, use_cache=False)
    assert doc["document_source"] == "holdings_json_fallback"
    assert "render refused" in doc["document_fallback_reason"]


def test_a_non_production_store_never_reaches_the_live_db(tmp_path, monkeypatch):
    hd = _hd()
    store = _write_prior(tmp_path)
    monkeypatch.setattr(hd, "default_db_query", lambda: pytest.fail("the live DB was reached for a fixture"))
    doc = hd.load_document(store, now=NOW, use_cache=False)
    assert doc["document_source"] == "holdings_json" and doc["document_fallback_reason"] is None


def test_the_production_store_uses_the_served_query_helper(tmp_path, monkeypatch):
    hd = _hd()
    store = _write_prior(tmp_path)
    db = FakeDB()
    monkeypatch.setattr(hd, "_is_production_store", lambda path: True)
    monkeypatch.setattr(hd, "default_db_query", lambda: db.query)
    doc = hd.load_document(store, now=NOW, use_cache=False)
    assert doc["document_source"] == "positions_current" and db.queries


def test_portfolio_for_names_its_source(tmp_path):
    hd = _hd()
    from lib.cio_truth import portfolio_for
    store = _write_prior(tmp_path)
    served = portfolio_for(hd.load_document(store, db_query=FakeDB().query, now=NOW, use_cache=False), now=NOW)
    assert served["document_source"] == "positions_current"
    roth = next(a for a in served["accounts"] if a["account_id"] == "schwab_roth_ira")
    assert roth["total_usd"] == 1510.0
    fallback = portfolio_for(hd.load_document(store, db_query=FakeDB(fail=True).query, now=NOW, use_cache=False),
                             now=NOW)
    assert fallback["document_source"] == "holdings_json_fallback" and fallback["document_fallback_reason"]


def test_the_cache_serves_copies(tmp_path):
    hd = _hd()
    store = _write_prior(tmp_path)
    db = FakeDB()
    first = hd.load_document(store, db_query=db.query, now=NOW)
    first["holdings"].clear()
    n = len(db.queries)
    second = hd.load_document(store, db_query=db.query, now=NOW)
    assert second["holdings"] and len(db.queries) == n


def test_an_unresolvable_production_root_is_a_stated_fallback(tmp_path, monkeypatch):
    hd = _hd()
    store = _write_prior(tmp_path)
    monkeypatch.setattr(hd, "_is_production_store", lambda path: None)
    monkeypatch.setattr(hd, "default_db_query", lambda: pytest.fail("the DB was read without a resolved root"))
    doc = hd.load_document(store, now=NOW, use_cache=False)
    assert doc["document_source"] == "holdings_json_fallback"
    assert "could not be resolved" in doc["document_fallback_reason"]
