"""schwab_position_sync: damaged store is 'no snapshot' to read, but a write keeps its baseline.

Operator execution-engineering grant 43212811c2fe4b17aade58299fea22ef (2026-11-03), mocks/fixtures only:
no live broker call, no credential read, no flag, no order route. Every connection/alert/hook is a fake.
"""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import schwab_position_sync as S  # noqa: E402

REQUIRED = ["schwab_taxable", "schwab_roth", "schwab_rollover_ira"]


def _row(sym, acct, shares, mv, *, cash=False, basis=1000.0):
    return {"symbol": sym, "account": acct, "account_id": acct, "shares": shares,
            "market_value": mv, "price": (mv / shares if shares else 1.0), "is_cash": cash,
            "cost_basis": mv if cash else basis, "cost_basis_total": mv if cash else basis,
            "avg_cost": (1.0 if cash or not shares else basis / shares)}


def _book():
    return {"holdings": [
        _row("AAA", "schwab_taxable", 100, 60000.0),
        _row("CASH", "schwab_taxable", 20000, 20000.0, cash=True),
        _row("BBB", "schwab_roth", 100, 40000.0),
        _row("CASH", "schwab_roth", 12000, 12000.0, cash=True),
        _row("CCC", "schwab_rollover_ira", 1000, 500000.0),
        _row("CASH", "schwab_rollover_ira", 200000, 200000.0, cash=True),
    ]}


@pytest.fixture
def store(tmp_path, monkeypatch):
    hp = tmp_path / "holdings.json"
    monkeypatch.setattr(S, "HOLDINGS_PATH", hp)
    monkeypatch.setattr(S, "_record", lambda *a, **k: None)
    monkeypatch.setattr(S, "_alert", lambda *a, **k: None)
    # Every post-write hook is a fake: no DB, no broker, no other store.
    monkeypatch.setitem(sys.modules, "holdings_change_trigger",
                        types.SimpleNamespace(check_and_enqueue=lambda **k: {}))
    monkeypatch.setitem(sys.modules, "sync_portfolio_watchlist_membership",
                        types.SimpleNamespace(sync_portfolio_watchlist_membership=lambda d: {}))
    ct = types.ModuleType("lib.cost_basis_transfer")
    ct.process_holdings_change = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "lib.cost_basis_transfer", ct)
    return hp


def _backup(hp, doc=None):
    p = hp.parent / (hp.name + ".bak-test")
    p.write_text(json.dumps(doc or _book()))
    return p


# ── (a) READ path: empty/corrupt is 'no snapshot', never a crash ──────────────────────────

def test_read_diff_on_empty_store_is_no_snapshot(store):
    store.write_bytes(b"")
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=True)
    assert out["status"] == "no_snapshot" and out["wrote"] is False and out["store_state"] == "empty"


def test_read_diff_on_corrupt_store_is_no_snapshot(store):
    store.write_text("{not json")
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=True)
    assert out["status"] == "no_snapshot" and out["store_state"] == "unparseable"


def test_read_diff_on_absent_store_is_no_holdings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "HOLDINGS_PATH", tmp_path / "missing.json")
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=True)
    assert out["status"] == "no_holdings_file" and out["store_state"] == "absent"


# ── (b) WRITE path: no baseline at all -> refuse; a backup/candidate -> guards stay live ──

def test_write_without_any_baseline_is_refused(store):
    store.write_bytes(b"")
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["status"] == "rejected_no_baseline" and out["wrote"] is False
    assert store.read_bytes() == b""          # nothing written over the damaged store


def test_write_uses_the_backup_baseline_and_preserves_other_accounts(store, monkeypatch):
    store.write_bytes(b"")
    _backup(store)
    new_roth = _row("BBB", "schwab_roth", 100, 41000.0)
    cash_roth = _row("CASH", "schwab_roth", 12500, 12500.0, cash=True)
    monkeypatch.setattr(S, "_build_account_rows", lambda label, live, existing: ([new_roth], []))
    monkeypatch.setattr(S, "_cash_rows_for_account", lambda label, hold, key, st: [cash_roth])
    out = S._sync_rows("schwab_roth_ira", "schwab_roth", [], object(), dry_run=False)
    assert out["wrote"] is True, out
    assert out["baseline_source"].startswith("backup:")
    doc = json.loads(store.read_text())
    accounts = {h["account"] for h in doc["holdings"]}
    assert {"schwab_taxable", "schwab_roth", "schwab_rollover_ira"} <= accounts, \
        "the write must not drop the accounts it did not sync"
    assert any(h["symbol"] == "BBB" and h["market_value"] == 41000.0 for h in doc["holdings"])


def test_write_that_drops_non_synced_accounts_is_refused(store, monkeypatch):
    store.write_bytes(b"")
    _backup(store)                            # baseline has all three governed accounts
    candidate = {"holdings": [_row("BBB", "schwab_roth", 100, 41000.0)]}   # only the synced account
    out = S.protected_holdings_write(candidate, source="test_drop", target_path=str(store),
                                     baseline=_book())
    assert out["wrote"] is False and out["reason_code"] == "INCOMPLETE_ACCOUNTS", out
    assert store.read_bytes() == b"", "a refused write must leave the store untouched"


def test_protected_write_uses_an_explicit_caller_baseline(store):
    store.write_bytes(b"")
    out = S.protected_holdings_write(_book(), source="test_caller", target_path=str(store), baseline=_book())
    assert out["wrote"] is True and out["baseline_source"] == "caller", out
    assert store.exists() and json.loads(store.read_text())["holdings"]
