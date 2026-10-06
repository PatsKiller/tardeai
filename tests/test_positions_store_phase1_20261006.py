"""Positions store phase 1 (shadow) + the 2026-10-06 Schwab/moomoo validation fixes.

Operator 2026-10-06: "yes start phase 1 and fix all of it". Validated live against Schwab at 10:15 ET:
PL showed 1,000 sh at a $1,766 cost (+944%) because the basis check compared accounts against each other
and REVERTED the sync's correct rebase; V Roth kept an April CSV lot over the broker's basis; PFLT waited
4 days for a reinvestment click; moomoo's sync wrote without the holdings lock and every write since 09-28
was lost. Fakes only: no network, no database, no broker, no token store.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import positions_sync as ps  # noqa: E402

D = dt.date
UTC = dt.timezone.utc
STORE_TABLES = ("position_snapshots", "positions_current", "position_lots", "realized_lots", "positions_sync_runs")


# ── lots ────────────────────────────────────────────────────────────────────

def _t(i, day, action, sym, qty, amount=0.0, price=0.0, acct="schwab_taxable"):
    return {"id": i, "trade_date": day, "account": acct, "symbol": sym, "action": action, "quantity": qty,
            "price": price, "amount": amount, "fees": 0.0}


def test_fifo_lots_and_realized_from_the_broker_ledger():
    open_lots, realized = ps.build_lots([
        _t(1, D(2026, 10, 5), "Buy", "PL", 100, amount=-1766.0, price=17.66),
        _t(2, D(2026, 10, 6), "Buy", "PL", 900, amount=-16632.0, price=18.48),
        _t(3, D(2026, 10, 7), "Sell", "PL", 150, amount=2850.0),
    ])
    assert [(l["qty_open"], round(l["unit_cost"], 2)) for l in open_lots] == [(850.0, 18.48)]
    assert [(r["qty"], r["cost"], r["realized_pl"]) for r in realized] == [
        (100.0, 1766.0, pytest.approx(1900.0 - 1766.0)), (50.0, 924.0, pytest.approx(950.0 - 924.0))]


def test_transfer_in_has_unknown_basis_and_never_a_guessed_zero():
    open_lots, realized = ps.build_lots([
        _t(1, D(2025, 7, 18), "Security Transfer", "UBER", 409),
        _t(2, D(2026, 1, 14), "Sell", "UBER", 409, amount=34614.94),
    ])
    assert open_lots == []
    assert realized[0]["cost"] is None and realized[0]["realized_pl"] is None and not realized[0]["basis_known"]


def test_selling_shares_the_ledger_never_saw_is_basis_unknown():
    _, realized = ps.build_lots([_t(1, D(2026, 2, 5), "Sell", "TSLA", 145, amount=57353.13)])
    assert realized[0]["proceeds"] == 57353.13 and realized[0]["cost"] is None


# ── run assembly: atomic promotion ─────────────────────────────────────────

def _ok(cash, rows=(), source="schwab_api"):
    return {"ok": True, "cash": cash, "equity": None, "positions": list(rows), "source": source,
            "captured_at": dt.datetime(2026, 10, 6, 14, 15, tzinfo=UTC)}


REQ = ["schwab_rollover_ira", "schwab_roth_ira", "schwab_taxable"]


def test_a_required_account_failing_makes_the_run_partial_and_never_current():
    reads = {"schwab_rollover_ira": _ok(1.0), "schwab_roth_ira": {"ok": False, "error": "401", "captured_at": None},
             "schwab_taxable": _ok(2.0)}
    plan = ps.plan_run(reads, REQ, [])
    assert plan["status"] == "partial" and not plan["promote"]
    assert plan["accounts_failed"] == {"schwab_roth_ira": "401"}


def test_an_optional_account_failing_still_promotes_the_required_ones():
    reads = {k: _ok(1.0) for k in REQ}
    reads["moomoo_taxable_live"] = {"ok": False, "error": "OpenD down", "captured_at": None}
    plan = ps.plan_run(reads, REQ, [])
    assert plan["status"] == "complete" and plan["promote"]
    assert "moomoo_taxable_live" not in plan["accounts_ok"]
    assert {c["symbol"] for c in plan["current"]} == {"CASH"}


def test_every_account_gets_a_cash_row_and_positions_carry_no_price_field():
    reads = {k: _ok(500.0) for k in REQ}
    reads["schwab_rollover_ira"] = _ok(777901.28, [{"symbol": "PL", "qty": 1000.0, "avg_cost": 18.398,
                                                    "cost_basis_total": 18398.0, "broker_market_value": 18643.5}])
    plan = ps.plan_run(reads, REQ, [])
    pl = next(c for c in plan["current"] if c["symbol"] == "PL")
    assert pl["cost_basis_total"] == 18398.0 and "price" not in pl and "current_price" not in pl
    assert sum(1 for c in plan["current"] if c["is_cash"]) == 3


def test_lot_check_flags_where_ledger_lots_do_not_reproduce_the_broker():
    cur = [{"account_key": "schwab_rollover_ira", "symbol": "SCHG", "qty": 2000.0, "cost_basis_total": 72735.0,
            "is_cash": False}]
    lots = [{"account_key": "schwab_rollover_ira", "symbol": "SCHG", "qty_open": 12000.0, "unit_cost": None}]
    assert ps.lot_checks(cur, lots, 0.001, 1.0)[0]["issues"][0].startswith("ledger lots qty 12000")


# ── shadow diff + freshness ────────────────────────────────────────────────

def test_shadow_diff_maps_the_roth_label_and_finds_basis_and_phantoms():
    store = {"holdings": [
        {"account": "schwab_roth", "symbol": "V", "shares": 130.4985, "cost_basis": 39951.37},
        {"account": "schwab_taxable", "symbol": "PFLT", "shares": 12.0071, "cost_basis": 119.12},
        {"account": "schwab_taxable", "symbol": "ZZZ", "shares": 5, "cost_basis": 1.0},
    ]}
    cur = [{"account_key": "schwab_roth_ira", "symbol": "V", "qty": 130.4985, "cost_basis_total": 40125.75, "is_cash": False},
           {"account_key": "schwab_taxable", "symbol": "PFLT", "qty": 12.1461, "cost_basis_total": 121.03, "is_cash": False}]
    out = {(d["account_key"], d["symbol"]): d["issue"] for d in ps.shadow_diff(cur, store, 0.001, 1.0)}
    assert "cost store 40125.75" in out[("schwab_roth_ira", "V")]
    assert "qty store 12.1461" in out[("schwab_taxable", "PFLT")]
    assert out[("schwab_taxable", "ZZZ")] == "PHANTOM_IN_HOLDINGS_JSON"


def test_freshness_contract_30_minutes_in_market_hours():
    cfg = ps.load_sync_config()
    now = dt.datetime(2026, 10, 6, 15, 0, tzinfo=UTC)          # 11:00 ET, a Tuesday
    assert not ps.freshness(now - dt.timedelta(minutes=20), cfg, now)["stale"]
    assert ps.freshness(now - dt.timedelta(minutes=45), cfg, now)["stale"]
    assert ps.freshness(None, cfg, now)["stale"]


def test_config_rules_present():
    cfg = ps.load_sync_config()
    assert cfg["required_accounts"] == REQ and cfg["stale_after_minutes_market"] == 30
    import yaml
    pos = yaml.safe_load((ROOT / "config" / "portfolio_positions.yaml").read_text())["positions"]
    assert pos["cost_basis_truth"] == "broker" and pos["share_drift_drip_auto"] is True


# ── one writer ──────────────────────────────────────────────────────────────

def test_only_positions_sync_writes_the_store_tables():
    pat = re.compile(r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE)\s+(" + "|".join(STORE_TABLES) + r")\b", re.I)
    writers = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "scripts").rglob("*.py")
                     if pat.search(p.read_text(encoding="utf-8", errors="ignore")))
    assert writers == ["scripts/positions_sync.py"]


def test_migration_is_additive_only():
    sql = (ROOT / "migrations" / "2026_10_06_positions_store_phase1.sql").read_text()
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE|ALTER)\b", body, re.I)
    for t in STORE_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {t}" in body


# ── fix: basis check compares the SAME account (PL revert, 2026-10-06) ──────

class _Cur:
    def __init__(self, log): self.log = log
    def execute(self, sql, params=None): self.log.append(params)


class _Conn:
    def __init__(self): self.log = []
    def cursor(self): return _Cur(self.log)
    def commit(self): pass


def test_basis_check_is_per_account_and_uses_the_broker_average(tmp_path, monkeypatch):
    import schwab_position_sync as sps
    stored = {"holdings": [
        {"account": "schwab_rollover_ira", "symbol": "PL", "shares": 100, "cost_basis": 1766.0},
        {"account": "schwab_rollover_ira", "symbol": "V", "shares": 0.7963, "cost_basis": 277.89},
        {"account": "schwab_roth", "symbol": "V", "shares": 130.4985, "cost_basis": 39951.37},
    ]}
    hp = tmp_path / "holdings.json"
    hp.write_text(json.dumps(stored))
    monkeypatch.setattr(sps, "HOLDINGS_PATH", hp)
    conn = _Conn()
    monkeypatch.setattr(sps, "_conn", lambda: conn)
    new = {"holdings": [
        {"account": "schwab_rollover_ira", "symbol": "PL", "shares": 1000, "broker_avg_price": 18.398, "cost_basis": 18398.0},
        {"account": "schwab_rollover_ira", "symbol": "V", "shares": 0.7963, "broker_avg_price": 348.976516, "cost_basis": 277.89},
        {"account": "schwab_roth", "symbol": "V", "shares": 130.4985, "broker_avg_price": 307.480546, "cost_basis": 39951.37},
    ]}
    flags = sps.check_basis_divergence(new, "schwab_rollover_ira", label="schwab_rollover_ira")
    # PL flagged against ITS OWN account's stored $1,766; V rollover NOT compared with the Roth's $39,951.
    assert [(f["symbol"], f["account"], f["broker_total"]) for f in flags] == [("PL", "schwab_rollover_ira", 18398.0)]


def test_broker_truth_rebases_instead_of_reverting(tmp_path, monkeypatch):
    import schwab_position_sync as sps
    monkeypatch.setattr(sps, "_cost_basis_truth", lambda: "broker")
    src = Path(sps.__file__).read_text()
    blk = src[src.index("truth = _cost_basis_truth()"):src.index("    backup = None")]
    assert 'p["cost_basis"] = fl[k]["broker_total"]' in blk and 'if truth == "broker"' in blk


# ── fix: reinvestment drift applied from broker data (PFLT) ────────────────

def test_drip_increase_is_auto_applied_and_logged(monkeypatch):
    import share_reconciliation as sr
    monkeypatch.setattr(sr, "drip_auto_enabled", lambda: True)
    fields, ev = sr.stamp_broker_qty({"shares": 12.0071, "system_shares": 12.0071}, 12.1461,
                                     account_key="schwab_taxable", symbol="PFLT", name="PENNANTPARK")
    assert fields["shares"] == 12.1461 and fields["share_drift_status"] == "auto_applied"
    assert ev["auto_resolved"] and ev["drift_amount"] == pytest.approx(0.139)


def test_drip_auto_off_keeps_the_approval_flow(monkeypatch):
    import share_reconciliation as sr
    monkeypatch.setattr(sr, "drip_auto_enabled", lambda: False)
    fields, ev = sr.stamp_broker_qty({"shares": 12.0071}, 12.1461, account_key="schwab_taxable", symbol="PFLT")
    assert fields["shares"] == 12.0071 and fields["share_drift_status"] == "pending" and not ev.get("auto_resolved")


def test_auto_resolved_events_are_logged_not_opened_as_tasks(monkeypatch):
    import share_reconciliation as sr
    seen = []
    monkeypatch.setattr(sr, "record_auto_resolution", lambda ev: seen.append(("auto", ev["symbol"])) or 1)
    monkeypatch.setattr(sr, "upsert_open_drift", lambda ev: seen.append(("task", ev["symbol"])) or 1)
    assert sr.process_sync_events([{"symbol": "PFLT", "auto_resolved": True}, {"symbol": "XLB"}]) == 2
    assert seen == [("auto", "PFLT"), ("task", "XLB")]


# ── fix: V Roth — broker basis outranks a stale CSV lot ─────────────────────

def test_csv_lot_no_longer_outranks_the_broker_when_truth_is_broker():
    src = (ROOT / "scripts" / "sync_basis_from_broker.py").read_text()
    assert 'not (basis_truth == "broker" and have_api)' in src


# ── fix: every holdings.json read-modify-write takes the shared lock ────────

@pytest.mark.parametrize("path", ["scripts/moomoo_live_read_sync.py", "scripts/schwab_position_sync.py",
                                  "scripts/sync_basis_from_broker.py", "scripts/alpaca_live_read_sync.py"])
def test_holdings_writers_take_the_write_lock(path):
    assert "holdings_write_lock()" in (ROOT / path).read_text()


def test_moomoo_merge_runs_inside_the_lock(monkeypatch):
    import moomoo_live_read_sync as m
    import lib.holdings_write_lock as hwl
    events = []

    @contextlib.contextmanager
    def fake_lock():
        events.append("lock")
        yield
        events.append("unlock")

    monkeypatch.setattr(hwl, "holdings_write_lock", fake_lock)
    monkeypatch.setattr(m, "_merge_locked", lambda rows, **kw: events.append(("merge", kw["dry_run"])) or {"ok": True})
    m._merge([], dry_run=False, preserve_prior_cash=False)
    assert events == ["lock", ("merge", False), "unlock"]


def test_table_dust_threshold_comes_from_config():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    assert "_dust_usd = _pp_cfg_dust_usd()" in src and "< 50 and not p.get(\"is_cash\")" not in src
