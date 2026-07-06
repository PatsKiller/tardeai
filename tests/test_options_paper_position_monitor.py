#!/usr/bin/env python3
"""PR1 — options paper position monitor tests.

Covers: hybrid ingest (upsert_from_queue_fill, mark_closed, orphan ERROR),
unrealized P/L math, advisory label thresholds, snapshot/alert writes,
run_monitor dry-run, migration idempotency, reconcile hook wiring.

    .venv/bin/python -m pytest tests/test_options_paper_position_monitor.py -q
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import alpaca_paper as ap  # noqa: E402
from lib.options_pipeline import paper_positions as pp  # noqa: E402
from lib.options_pipeline import paper_position_monitor as mon  # noqa: E402
from lib.options_pipeline import paper_position_alerts as ppa  # noqa: E402

RTX_PROPOSAL = {
    "id": "opt_deep_itm_call_RTX_paper_model_160p0000_20260918",
    "strategy": "deep_itm_call",
    "symbol": "RTX",
    "underlying": "RTX",
    "side": "BUY",
    "option_type": "call",
    "strike": 160.0,
    "expiration": "2026-09-18",
    "contracts": 1,
    "premium": 40.62,
    "alpaca_paper_enabled": True,
}
OCC = "RTX260918C00160000"


class MonitoredFakeDB:
    """Stateful executor for options_monitored_positions + queue rows."""

    def __init__(self, queue_rows=(), positions=()):
        self.queue = {r["proposal_id"]: copy.deepcopy(r) for r in queue_rows}
        self.positions = {p["proposal_id"]: copy.deepcopy(p) for p in positions}
        self._next_id = max([p.get("id", 0) for p in self.positions.values()] + [0]) + 1
        self.snapshots: list[dict] = []
        self.alerts: list[dict] = []
        self.calls = []

    def __call__(self, sql, params=None, fetch=None):
        s = " ".join(sql.split())
        self.calls.append({"sql": s, "params": params, "fetch": fetch})

        # queue (alpaca reconcile)
        if s.startswith("SELECT") and "FROM options_approval_queue" in s and "WHERE proposal_id=%s" in s:
            r = self.queue.get(params[0])
            return copy.deepcopy(r) if r else None
        if s.startswith("SELECT") and "FROM options_approval_queue" in s and "WHERE status=%s" in s:
            return [copy.deepcopy(r) for r in self.queue.values() if r["status"] == params[0]]
        if s.startswith("UPDATE options_approval_queue SET status=%s"):
            to_status, patch_json, pid, from_status = params
            r = self.queue.get(pid)
            if not r or r["status"] != from_status:
                return None
            r["status"] = to_status
            r["meta"] = {**(r.get("meta") or {}), **json.loads(patch_json)}
            return {"id": r.get("id", 1)}
        if s.startswith("UPDATE options_approval_queue SET meta ="):
            patch_json, pid = params
            r = self.queue.get(pid)
            if r:
                r["meta"] = {**(r.get("meta") or {}), **json.loads(patch_json)}
            return True

        # monitored positions — orphan ERROR row
        if "INSERT INTO options_monitored_positions" in s and "underlying_symbol" in s and len(params) <= 11:
            pid, broker, symbol, underlying, option_symbol, status, paper_only, live_eligible, meta_json = params[:9]
            existing = self.positions.get(pid)
            if existing:
                existing.update({
                    "option_symbol": option_symbol,
                    "symbol": symbol or existing.get("symbol"),
                    "underlying_symbol": underlying or existing.get("underlying_symbol"),
                    "status": status,
                    "meta_json": {**(existing.get("meta_json") or {}),
                                   **(json.loads(meta_json) if isinstance(meta_json, str) else meta_json)},
                })
            else:
                self.positions[pid] = {
                    "id": self._next_id,
                    "proposal_id": pid,
                    "broker": broker,
                    "symbol": symbol,
                    "underlying_symbol": underlying,
                    "option_symbol": option_symbol,
                    "status": status,
                    "paper_only": paper_only,
                    "live_eligible": live_eligible,
                    "meta_json": json.loads(meta_json) if isinstance(meta_json, str) else meta_json,
                }
                self._next_id += 1
            return True
        if "INSERT INTO options_monitored_positions" in s:
            pid = params[0]
            existing = self.positions.get(pid)
            if existing:
                existing.update({
                    "alpaca_order_id": params[3],
                    "entry_fill_price": params[15] or existing.get("entry_fill_price"),
                    "status": params[27] if existing.get("status") != pp.STATUS_CLOSED else existing["status"],
                    "updated_at": "now",
                })
            else:
                self.positions[pid] = {
                    "id": self._next_id,
                    "proposal_id": pid,
                    "broker": params[1],
                    "execution_route": params[2],
                    "alpaca_order_id": params[3],
                    "symbol": params[5],
                    "underlying_symbol": params[6],
                    "option_symbol": params[7],
                    "strategy": params[8],
                    "strike": params[11],
                    "expiration": params[12],
                    "contracts": params[13],
                    "entry_fill_price": params[15],
                    "entry_debit_credit": params[16],
                    "status": params[27],
                    "paper_only": params[28],
                    "meta_json": json.loads(params[30]) if isinstance(params[30], str) else params[30],
                }
                self._next_id += 1
            return True
        if s.startswith("SELECT * FROM options_monitored_positions WHERE proposal_id = %s"):
            r = self.positions.get(params[0])
            return copy.deepcopy(r) if r else None
        if "FROM options_monitored_positions" in s and "WHERE status = %s" in s and "broker = %s" not in s:
            return [copy.deepcopy(r) for r in self.positions.values()
                    if r.get("status") == params[0]][: params[1]]
        if "FROM options_monitored_positions" in s and "WHERE id = %s" in s:
            for r in self.positions.values():
                if r.get("id") == params[0]:
                    return copy.deepcopy(r)
            return None
        if "SELECT option_symbol FROM options_monitored_positions" in s and "option_symbol IS NOT NULL" in s:
            return [{"option_symbol": r.get("option_symbol")}
                    for r in self.positions.values() if r.get("option_symbol")]
        if "JOIN options_monitored_positions" in s and "options_monitored_alerts" in s:
            return None
        if "FROM options_approval_queue" in s and "ILIKE" in s:
            needle = str((params or [""])[0]).strip("%").upper()
            out = []
            for r in self.queue.values():
                blob = json.dumps(r).upper()
                if needle in blob:
                    out.append(copy.deepcopy(r))
            return out
        if "FROM options_approval_queue" in s and "status LIKE 'ALPACA_PAPER" in s:
            return [copy.deepcopy(r) for r in self.queue.values()
                    if str(r.get("status") or "").startswith("ALPACA_PAPER")]
        if "FROM options_approval_queue" in s and "alpaca_json" in s:
            return [copy.deepcopy(r) for r in self.queue.values()
                    if "alpaca_json" in json.dumps(r.get("meta") or {})]
        if s.startswith("UPDATE options_monitored_positions"):
            pid = params[2] if "closed_reason" in str(params[1]) else params[-1]
            if "closed_reason" in str(params[1]):
                pid = params[2]
                r = self.positions.get(pid)
                if r and r.get("status") == pp.STATUS_OPEN:
                    r["status"] = pp.STATUS_CLOSED
                    return {"id": r["id"]} if "RETURNING" in s else True
                return None
            return True
        if "INSERT INTO options_monitored_position_snapshots" in s:
            self.snapshots.append({"params": params})
            return True
        if "INSERT INTO options_monitored_alerts" in s:
            self.alerts.append({"params": params})
            return True
        if "SELECT id FROM options_monitored_alerts" in s:
            return None
        if s.startswith("UPDATE options_monitored_alerts"):
            return True
        if "SELECT unrealized_pnl FROM options_monitored_position_snapshots" in s:
            return []
        raise AssertionError(f"MonitoredFakeDB unexpected SQL: {s[:140]}")


def _queue_row(status, meta=None):
    return {"id": 1, "proposal_id": RTX_PROPOSAL["id"], "symbol": "RTX",
            "strategy": "deep_itm_call", "status": status,
            "proposal_json": RTX_PROPOSAL,
            "meta": meta or {}}


def _submitted_row(status=None):
    return _queue_row(status or ap.STATE_SUBMITTED, {
        "alpaca_json": {
            "request": ap.build_order_request(occ_symbol=OCC, limit_price=40.62),
            "response": {"id": "ord-42"},
        }})


# ── paper_positions ───────────────────────────────────────────────────────────

def test_upsert_from_queue_fill_creates_open_position():
    db = MonitoredFakeDB(queue_rows=[_submitted_row()])
    fill = {"price": 40.10, "filled_at": "2026-07-06T14:31:00Z"}
    row = _submitted_row()
    row["status"] = ap.STATE_FILLED
    row["meta"]["alpaca_json"]["fill"] = fill
    res = pp.upsert_from_queue_fill(row, fill=fill, executor=db)
    assert res["ok"] and res["proposal_id"] == RTX_PROPOSAL["id"]
    pos = db.positions[RTX_PROPOSAL["id"]]
    assert pos["status"] == pp.STATUS_OPEN
    assert pos["entry_fill_price"] == 40.10
    assert pos["execution_route"] == "alpaca_paper"
    assert pos["entry_debit_credit"] == "debit"


def test_mark_closed_updates_open_position():
    db = MonitoredFakeDB(positions=[{
        "id": 7, "proposal_id": RTX_PROPOSAL["id"], "status": pp.STATUS_OPEN,
    }])
    res = pp.mark_closed(RTX_PROPOSAL["id"], executor=db)
    assert res["ok"]
    assert db.positions[RTX_PROPOSAL["id"]]["status"] == pp.STATUS_CLOSED


def test_underlying_from_occ_parses_root():
    assert pp.underlying_from_occ(OCC) == "RTX"
    assert pp.underlying_from_occ("") == ""


def test_upsert_orphan_error_creates_error_row():
    db = MonitoredFakeDB()
    res = pp.upsert_orphan_error(option_symbol=OCC, broker="alpaca",
                                 message="no queue lineage", executor=db)
    assert res["ok"] and res["status"] == pp.STATUS_ERROR and res.get("created")
    row = db.positions[f"orphan_alpaca_{OCC}"]
    assert row["underlying_symbol"] == "RTX"


def test_orphan_scan_links_pending_queue_row_not_error(monkeypatch):
    fill_meta = {
        "alpaca_json": {
            "request": {"symbol": OCC},
            "fill": {"price": 40.10, "filled_at": "2026-07-06T14:31:00Z"},
        }}
    row = _queue_row("pending", fill_meta)
    db = MonitoredFakeDB(queue_rows=[row])

    class FakeClient:
        def list_positions(self):
            return [{"symbol": OCC, "asset_class": "us_option"}]

    report: dict = {"warnings": []}
    ap._scan_alpaca_orphan_positions(FakeClient(), db, report)
    assert RTX_PROPOSAL["id"] in db.positions
    assert db.positions[RTX_PROPOSAL["id"]]["status"] == pp.STATUS_OPEN
    assert not report.get("orphans")


# ── P/L + advisory ────────────────────────────────────────────────────────────

def test_compute_unrealized_pnl_debit_and_credit():
    debit_pos = {"entry_fill_price": 2.50, "contracts": 1, "entry_debit_credit": "debit"}
    pnl, pct = mon.compute_unrealized_pnl(debit_pos, 3.00)
    assert pnl == 50.0 and pct == 20.0
    credit_pos = {"entry_fill_price": 1.20, "contracts": 1, "entry_debit_credit": "credit"}
    pnl2, pct2 = mon.compute_unrealized_pnl(credit_pos, 0.80)
    assert pnl2 == 40.0 and pct2 == pytest.approx(33.33, abs=0.1)


def test_generate_advisory_profit_target():
    pos = {"strategy": "deep_itm_call", "entry_iv": 0.30}
    quote = {"ok": True, "bid": 4.0, "ask": 4.2, "spread_pct": 4.9, "dte": 45,
             "iv": 0.28, "delta": 0.82}
    cfg = mon.load_config()
    label, reason, flags = mon.generate_advisory_label(pos, quote, pnl_pct=30.0, cfg=cfg)
    assert label == mon.ADVICE_CLOSE
    assert "Profit target" in reason
    assert any(f["code"] == "profit_target" for f in flags)


def test_generate_advisory_stale_quote():
    label, reason, _ = mon.generate_advisory_label(
        {"strategy": "atm_call"}, {"ok": False, "error": "chain down"}, 0.0, mon.load_config())
    assert label == mon.ADVICE_STALE


def test_generate_advisory_wide_spread():
    pos = {"strategy": "default"}
    quote = {"ok": True, "bid": 1.0, "ask": 1.5, "spread_pct": 20.0, "dte": 30}
    label, _, flags = mon.generate_advisory_label(pos, quote, 5.0, mon.load_config())
    assert label == mon.ADVICE_WATCH
    assert any(f["code"] == "wide_spread" for f in flags)


# ── PR2 alerts / telegram ─────────────────────────────────────────────────────

def test_format_telegram_lifecycle_fill():
    pos = {"symbol": "RTX", "underlying_symbol": "RTX", "strategy": "deep_itm_call",
           "execution_route": "alpaca_paper", "contracts": 1, "entry_fill_price": 40.10}
    msg = ppa.format_telegram_message(
        pos, ppa.LIFECYCLE_FILLED, "filled", extra={"fill_price": 40.10})
    assert ppa.ALERT_PREFIX in msg
    assert "ALPACA PAPER FILLED" in msg
    assert "*RTX*" in msg


def test_dispatch_alert_writes_ui_and_telegram(monkeypatch):
    db = MonitoredFakeDB()
    sent = []

    def fake_tg(body):
        sent.append(body)
        return True

    monkeypatch.setattr(ppa, "send_telegram", fake_tg)
    pos = {"id": 5, "proposal_id": RTX_PROPOSAL["id"], "symbol": "RTX",
           "underlying_symbol": "RTX", "strategy": "deep_itm_call",
           "execution_route": "alpaca_paper", "broker": "alpaca"}
    cfg = {"alert_ui_enabled": True, "alert_telegram_enabled": True,
           "telegram_dedupe_minutes": 60}
    out = ppa.dispatch_alert(pos, "consider_close_paper", "Profit target advisory (30%)",
                             cfg=cfg, executor=db, advice_label="CONSIDER_CLOSE_PAPER",
                             unrealized_pnl=210.0, unrealized_pnl_pct=30.0, mark=50.25)
    assert out["ui"] and out["telegram"]
    assert len(db.alerts) == 1
    assert ppa.ALERT_PREFIX in sent[0]


def test_dispatch_alert_dedupes_telegram(monkeypatch):
    db = MonitoredFakeDB()

    def fake_dedupe(position_id, alert_type, *, cfg, executor, option_symbol=None, proposal_id=None):
        return True

    monkeypatch.setattr(ppa, "should_dedupe_telegram", fake_dedupe)
    monkeypatch.setattr(ppa, "send_telegram", lambda m: True)
    pos = {"id": 5, "proposal_id": RTX_PROPOSAL["id"], "symbol": "RTX",
           "underlying_symbol": "RTX", "strategy": "deep_itm_call",
           "execution_route": "alpaca_paper", "broker": "alpaca"}
    cfg = {"alert_ui_enabled": True, "alert_telegram_enabled": True}
    out = ppa.dispatch_alert(pos, "data_stale", "chain down", cfg=cfg, executor=db)
    assert out["ui"] and out["deduped"] and not out["telegram"]


def test_telegram_router_classifies_options_close_as_p0():
    from telegram_alert_router import classify_alert
    msg = ppa.format_telegram_message(
        {"symbol": "RTX", "strategy": "deep_itm_call", "execution_route": "alpaca_paper"},
        ppa.LIFECYCLE_CLOSED, "closed", extra={"pnl": 375.0})
    assert classify_alert(msg) == "P0_INTERRUPT"


# ── monitor run ───────────────────────────────────────────────────────────────

def test_monitor_position_dry_run_no_writes(monkeypatch):
    db = MonitoredFakeDB()
    pos = {"id": 1, "proposal_id": RTX_PROPOSAL["id"], "symbol": "RTX",
           "underlying_symbol": "RTX", "strike": 160.0, "expiration": "2026-09-18",
           "option_type": "call", "side": "BUY", "contracts": 1,
           "entry_fill_price": 40.10, "entry_debit_credit": "debit", "strategy": "deep_itm_call"}
    monkeypatch.setattr(mon, "fetch_schwab_chain_quote", lambda *a, **k: {
        "ok": True, "bid": 42.0, "ask": 42.4, "mid": 42.2, "mark": 42.2,
        "spread_pct": 0.9, "dte": 40, "iv": 0.25, "delta": 0.78,
        "underlying_price": 175.0, "source": "schwab_chain"})
    out = mon.monitor_position(pos, cfg=mon.load_config(), executor=db, dry_run=True)
    assert out["quote_ok"] and out["unrealized_pnl"] == 210.0
    assert db.snapshots == [] and db.alerts == []


def test_run_monitor_writes_snapshot_and_alert(monkeypatch):
    monkeypatch.setattr(ppa, "send_telegram", lambda m: True)
    db = MonitoredFakeDB(positions=[{
        "id": 3, "proposal_id": RTX_PROPOSAL["id"], "status": pp.STATUS_OPEN,
        "symbol": "RTX", "underlying_symbol": "RTX", "strike": 160.0,
        "expiration": "2026-09-18", "option_type": "call", "side": "BUY",
        "contracts": 1, "entry_fill_price": 40.10, "entry_debit_credit": "debit",
        "strategy": "deep_itm_call", "broker": "alpaca", "execution_route": "alpaca_paper",
    }])
    monkeypatch.setattr(mon, "fetch_schwab_chain_quote", lambda *a, **k: {
        "ok": True, "bid": 50.0, "ask": 50.5, "mid": 50.25, "mark": 50.25,
        "spread_pct": 1.0, "dte": 40, "iv": 0.25, "delta": 0.85,
        "underlying_price": 180.0, "source": "schwab_chain"})
    report = mon.run_monitor(dry_run=False, cfg={"enabled": True, "max_positions_per_run": 10,
                                                  "brokers": {"alpaca": {"reconcile_on_run": False}}},
                             executor=db, skip_hours_check=True)
    assert report["count"] == 1
    assert len(db.snapshots) == 1
    assert report["monitored"][0]["advice_label"] == mon.ADVICE_CLOSE


# ── reconcile hook ────────────────────────────────────────────────────────────

PAPER_ENV = {
    "ALPACA_PAPER_BASE_URL": "https://paper-api.alpaca.markets",
    "ALPACA_API_KEY": "PKTESTKEY",
    "ALPACA_SECRET_KEY": "testsecret",
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeHTTP:
    def __init__(self, responses=None):
        self.responses = responses or {}

    def post(self, url, headers=None, json=None, timeout=None):
        return self.responses.get(("POST", url), FakeResponse({"id": "ord-1"}))

    def get(self, url, headers=None, timeout=None, params=None):
        return self.responses.get(("GET", url), FakeResponse({}, 404))


def _client(http=None):
    return ap.AlpacaPaperOptionsClient(env=dict(PAPER_ENV), http=http or FakeHTTP())


def test_ensure_monitored_backfills_filled_row_without_registry():
    row = _submitted_row(ap.STATE_FILLED)
    row["meta"]["alpaca_json"]["fill"] = {"price": 40.10, "filled_at": "2026-07-06T14:31:00Z"}
    db = MonitoredFakeDB(queue_rows=[row])
    res = pp.ensure_monitored_for_filled_queue_row(row, executor=db)
    assert res["ok"] is True
    assert RTX_PROPOSAL["id"] in db.positions
    assert db.positions[RTX_PROPOSAL["id"]]["status"] == pp.STATUS_OPEN
    again = pp.ensure_monitored_for_filled_queue_row(row, executor=db)
    assert again.get("skipped") is True


def test_reconcile_fill_upserts_monitored_position():
    db = MonitoredFakeDB(queue_rows=[_submitted_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({("GET", f"{base}/v2/orders/ord-42"): FakeResponse(
        {"id": "ord-42", "status": "filled", "filled_avg_price": "40.10",
         "filled_qty": "1", "filled_at": "2026-07-06T14:31:00Z"})})
    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=lambda *a, **k: {"ok": True})
    assert RTX_PROPOSAL["id"] in db.positions
    assert db.positions[RTX_PROPOSAL["id"]]["status"] == pp.STATUS_OPEN
    assert res.get("monitored_positions")


def test_reconcile_close_marks_monitored_position_closed():
    row = _submitted_row(ap.STATE_FILLED)
    row["meta"]["alpaca_json"]["fill"] = {"price": 40.10, "filled_at": "2026-07-06T14:31:00Z"}
    db = MonitoredFakeDB(
        queue_rows=[row],
        positions=[{"id": 9, "proposal_id": RTX_PROPOSAL["id"], "status": pp.STATUS_OPEN}],
    )
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({
        ("GET", f"{base}/v2/positions/{OCC}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/orders"): FakeResponse([
            {"id": "ord-77", "side": "sell", "status": "filled",
             "filled_avg_price": "43.85", "filled_at": "2026-07-20T15:00:00Z"}]),
    })
    ap.reconcile_fills(executor=db, client=_client(http),
                       record_outcome_fn=lambda *a, **k: {"ok": True})
    assert db.positions[RTX_PROPOSAL["id"]]["status"] == pp.STATUS_CLOSED


# ── migration shape ───────────────────────────────────────────────────────────

MIGRATION = ROOT / "migrations" / "2026_07_07_options_monitored_positions.sql"


def test_migration_additive_and_idempotent():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS options_monitored_positions" in sql
    assert "CREATE TABLE IF NOT EXISTS options_monitored_position_snapshots" in sql
    assert "CREATE TABLE IF NOT EXISTS options_monitored_alerts" in sql
    up = sql.upper()
    assert "DROP TABLE" not in up and "TRUNCATE" not in up
    for st in ("OPEN", "CLOSED", "ERROR"):
        assert f"'{st}'" in sql