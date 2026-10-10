"""Refactor wave 2 (cron -> n8n, 2026-10-10), bucket V4: portfolio report / enrichment lanes.

- scripts/portfolio_lookthrough_themes.py (cron L484): state resolves through persistent_state_root;
  --dry-run writes neither cache nor report and calls no LLM; a run without --grok keeps the previous
  narrative; empty holdings exit 1; real runs leave portfolio-lookthrough-themes_last.json.
- scripts/fee_efficiency_analyzer.py (cron L549): --dry-run wins over --emit and cannot reach
  save_alert_event; data errors exit 1; --emit runs leave fee-efficiency-analyzer_last.json.
- scripts/watchlist_enrichment_sweep.py (cron L447): --dry-run used to call enrich_tickers (Finviz fetch +
  cache write) and the yfinance fallback that backfills market_quotes; now it reads cached enrichment only.
Hermetic: tmp state dirs, fake connections and modules, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fee_efficiency_analyzer as fea  # noqa: E402
import portfolio_lookthrough_themes as plt_  # noqa: E402
import watchlist_enrichment_sweep as wes  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402

_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "TRUNCATE")


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rowcount, self.description = conn, 1, None
        self._one, self._all = (0,), []

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.conn.sql.append(norm)
        res = (self.conn.responder(norm, params) if self.conn.responder else None) or {}
        self._one, self._all = res.get("one", (0,)), res.get("all", [])
        self.rowcount = res.get("rowcount", 1)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._all)

    def close(self):
        pass


class FakeConn:
    def __init__(self, responder=None):
        self.responder = responder
        self.sql, self.commits, self.readonly, self.closed = [], 0, None, False

    def cursor(self, *a, **k):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def set_session(self, readonly=None, **k):
        self.readonly = readonly

    def close(self):
        self.closed = True

    def writes(self):
        return [s for s in self.sql if s.split()[0].upper() in _WRITE_VERBS]


def _boom(*a, **k):
    raise AssertionError("dry run reached a write / LLM / fetch path")


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


def _receipt(state, lane):
    return json.loads((state / "data" / "runtime" / f"{lane}_last.json").read_text())


def _dry_line(text):
    line = next(ln for ln in text.splitlines() if ln.startswith("DRY-RUN "))
    return json.loads(line[len("DRY-RUN ") :])


# ── portfolio_lookthrough_themes ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def lt_state(tmp_path, monkeypatch):
    sd = tmp_path / "pstate"
    sd.mkdir()
    holdings = [
        {"symbol": "NVDA", "market_value": 60_000, "account": "ira"},
        {"symbol": "XOM", "market_value": 40_000, "account": "taxable"},
    ]
    (sd / "holdings.json").write_text(json.dumps({"holdings": holdings}))
    monkeypatch.setattr(plt_, "STATE", sd)
    monkeypatch.setattr(plt_, "HOLD_CACHE", sd / "fund_holdings_cache.json")
    monkeypatch.setattr(plt_, "CONSTITUENTS", sd / "index_constituents.json")
    monkeypatch.setattr(plt_, "_state_write_targets", lambda: [sd])
    monkeypatch.setattr(
        plt_, "_advisories", lambda themes, top, total, ips_max=None: [{"severity": "low", "title": "t", "detail": "d"}]
    )
    return sd


def test_lookthrough_dry_run_writes_nothing_and_calls_no_llm(lt_state, monkeypatch, capsys):
    monkeypatch.setattr(plt_, "grok_narrative", _boom)
    monkeypatch.setattr(plt_, "agent_advisories", _boom)
    monkeypatch.setattr(plt_, "_write_state_json", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert plt_.main(["--dry-run", "--grok"]) == 0
    assert sorted(p.name for p in lt_state.iterdir()) == ["holdings.json"]
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["portfolio_total"] == 100_000 and rep["summary"]["llm"] == "skipped (dry run)"
    assert any(w.endswith("lookthrough_themes.json") for w in rep["would_write"])


def test_lookthrough_real_run_without_grok_keeps_previous_narrative(lt_state, monkeypatch, _state):
    (lt_state / "lookthrough_themes.json").write_text(
        json.dumps({"grok_narrative": "prior read", "grok_generated_at": "2026-10-09T11:40:00+00:00"})
    )
    monkeypatch.setattr(plt_, "grok_narrative", _boom)
    assert plt_.main(["--json"]) == 0
    doc = json.loads((lt_state / "lookthrough_themes.json").read_text())
    assert doc["grok_narrative"] == "prior read" and doc["grok_generated_at"].startswith("2026-10-09")
    assert doc["portfolio_total"] == 100_000 and (lt_state / "fund_holdings_cache.json").exists()
    rec = _receipt(_state, "portfolio-lookthrough-themes")
    assert rec["status"] == "ok" and rec["summary"]["portfolio_total"] == 100_000


def test_lookthrough_grok_unavailable_is_said_not_hidden(lt_state, monkeypatch, _state):
    monkeypatch.setattr(plt_, "grok_narrative", lambda r: "")
    monkeypatch.setattr(plt_, "agent_advisories", lambda r: [])
    assert plt_.main(["--grok", "--json"]) == 0
    doc = json.loads((lt_state / "lookthrough_themes.json").read_text())
    assert doc["grok_status"] == "unavailable"
    assert _receipt(_state, "portfolio-lookthrough-themes")["summary"]["grok_status"] == "unavailable"


def test_lookthrough_empty_holdings_exits_1(lt_state, monkeypatch, _state):
    (lt_state / "holdings.json").write_text(json.dumps({"holdings": []}))
    assert plt_.main(["--json"]) == 1
    assert _receipt(_state, "portfolio-lookthrough-themes")["status"] == "failed"


def test_lookthrough_state_resolves_through_persistent_root(monkeypatch, tmp_path):
    import lib.persistent_state_root as psr

    monkeypatch.setattr(psr, "resolve_durable_dir", lambda rel, root=None: tmp_path / "served" / rel)
    assert plt_._state_dir() == tmp_path / "served" / "data/portfolios/state"


# ── fee_efficiency_analyzer ──────────────────────────────────────────────────────────────────────────
@pytest.fixture
def fee_env(tmp_path, monkeypatch):
    hp = tmp_path / "holdings.json"
    hp.write_text(
        json.dumps(
            {
                "holdings": [
                    {"symbol": "FCNTX", "account": "ira", "market_value": 50_000},
                    {"symbol": "SCHD", "account": "ira", "market_value": 10_000},
                ]
            }
        )
    )
    monkeypatch.setattr(fea, "_holdings_path", lambda: hp)

    def responder(sql, params):
        if sql.startswith("SELECT symbol, instrument_type"):
            return {"all": [("FCNTX", "mutual_fund", 0.0147, 10.5, 0.1), ("SCHD", "etf", 0.0006, 14.9, 3.5)]}
        return None

    conn = FakeConn(responder)
    monkeypatch.setattr(fea, "_conn", lambda: conn)
    sent = []
    monkeypatch.setitem(
        sys.modules, "alert_event_writer", types.SimpleNamespace(save_alert_event=lambda **k: sent.append(k))
    )
    return {"hp": hp, "conn": conn, "sent": sent}


@pytest.mark.parametrize("argv", [["--emit", "--dry-run"], ["--dry-run"]])
def test_fee_dry_run_cannot_emit(fee_env, monkeypatch, capsys, argv):
    monkeypatch.setitem(sys.modules, "alert_event_writer", types.SimpleNamespace(save_alert_event=_boom))
    monkeypatch.setattr(fea, "emit_findings", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert fea.main(argv) == 0
    assert fee_env["conn"].readonly is True and fee_env["conn"].writes() == []
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert out["flagged_count"] == 1 and out["would_emit"] == (1 if "--emit" in argv else 0)
    assert _dry_line(cap.err)["summary"]["data_errors"] == []


def test_fee_emit_run_writes_receipt(fee_env, _state):
    assert fea.main(["--emit"]) == 0
    assert len(fee_env["sent"]) == 1 and fee_env["sent"][0]["symbol"] == "FCNTX"
    rec = _receipt(_state, "fee-efficiency-analyzer")
    assert rec["status"] == "ok" and rec["summary"]["emitted"] == 1


def test_fee_unreadable_holdings_exit_1(fee_env, _state):
    fee_env["hp"].write_text("{not json")
    assert fea.main(["--emit"]) == 1
    rec = _receipt(_state, "fee-efficiency-analyzer")
    assert rec["status"] == "failed" and rec["summary"]["data_errors"] == ["holdings unreadable: JSONDecodeError"]


def test_fee_emit_failure_exit_1(fee_env, monkeypatch, _state):
    def fail(**k):
        raise RuntimeError("alert_events down")

    monkeypatch.setitem(sys.modules, "alert_event_writer", types.SimpleNamespace(save_alert_event=fail))
    assert fea.main(["--emit"]) == 1
    assert _receipt(_state, "fee-efficiency-analyzer")["summary"]["emit_error"] == "RuntimeError"


# ── watchlist_enrichment_sweep ───────────────────────────────────────────────────────────────────────
@pytest.fixture
def sweep_env(monkeypatch):
    def responder(sql, params):
        if sql.startswith("SELECT wi.symbol FROM watchlist_items"):
            return {"all": [("AAA",), ("BBB",)]}
        if sql.startswith("SELECT symbol FROM watchlist_items"):
            return {"all": []}
        if sql.startswith("SELECT price, day_change_pct FROM market_quotes"):
            return {"one": None}
        if sql.startswith("UPDATE watchlist_items"):
            return {"rowcount": 1 if params[-1] != "BBB" else 0}
        return None

    conn = FakeConn(responder)
    monkeypatch.setattr(wes, "_conn", lambda: conn)
    monkeypatch.setattr(wes, "is_off_hours_et", lambda: False)
    monkeypatch.setattr(wes, "daily_priority_sql_params", lambda project_root=None: ())
    monkeypatch.setattr(wes, "sql_daily_priority_exists", lambda col: "TRUE")
    fetched = []
    monkeypatch.setitem(
        sys.modules,
        "finviz_enrichment",
        types.SimpleNamespace(
            enrich_tickers=lambda batch, project_root=None: fetched.append(batch),
            get_enriched=lambda s, project_root=None: {"rsi": "55", "sma50_pct": "2", "sma200_pct": "5"},
        ),
    )
    monkeypatch.setitem(
        sys.modules, "open_trades_intelligence", types.SimpleNamespace(_trend_label=lambda a, b: "bullish")
    )
    monkeypatch.setitem(sys.modules, "setup_quality_prior", types.SimpleNamespace(rsi_band=lambda r: "mid"))
    monkeypatch.setitem(sys.modules, "directive_promotion", types.SimpleNamespace(classify_tradeable=lambda s, t: []))
    monkeypatch.setitem(
        sys.modules,
        "price_db_sync",
        types.SimpleNamespace(sync_quotes_to_ticker_prices=lambda syms: fetched.append(("sync", syms))),
    )
    return {"conn": conn, "fetched": fetched}


def test_sweep_dry_run_reads_cache_only(sweep_env, monkeypatch, capsys):
    monkeypatch.setitem(
        sys.modules,
        "finviz_enrichment",
        types.SimpleNamespace(enrich_tickers=_boom, get_enriched=lambda s, project_root=None: {"rsi": "55"}),
    )
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_boom))
    monkeypatch.setitem(sys.modules, "price_db_sync", types.SimpleNamespace(sync_quotes_to_ticker_prices=_boom))
    import lib.writers.market_quotes_writer as mqw

    monkeypatch.setattr(mqw, "write_market_quotes", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert wes.main(["--once", "--dry-run"]) == 0
    assert sweep_env["conn"].readonly is True and sweep_env["conn"].writes() == []
    assert sweep_env["conn"].commits == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"] == {"selected": 2, "would_update": 2}


def test_price_without_fetch_never_calls_yfinance(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_boom))
    conn = FakeConn(lambda sql, params: {"one": None})
    assert wes._price(conn, "NEWIPO", allow_fetch=False) == (None, None)
    assert conn.writes() == []


def test_sweep_real_run_receipt_and_exit(sweep_env, monkeypatch, _state):
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=lambda s: types.SimpleNamespace(info={})))
    assert wes.main(["--once"]) == 0
    assert sweep_env["fetched"][0] == ["AAA", "BBB"]  # the Finviz refresh still runs on a real run
    rec = _receipt(_state, "watchlist-enrichment-sweep")
    assert rec["status"] == "ok" and rec["summary"] == {"selected": 2, "enriched": 1}


def test_sweep_selected_but_none_updated_exits_1(sweep_env, monkeypatch, _state):
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=lambda s: types.SimpleNamespace(info={})))
    sweep_env["conn"].responder = (
        lambda base: lambda sql, params: {"rowcount": 0} if sql.startswith("UPDATE") else base(sql, params)
    )(sweep_env["conn"].responder)
    assert wes.main(["--once"]) == 1
    assert _receipt(_state, "watchlist-enrichment-sweep")["status"] == "failed"
