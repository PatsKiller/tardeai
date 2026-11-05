"""yfinance-info-snapshot owner lane + prospectus fund block wiring (operator 2026-10-26: "Yahoo Finance feed … switched
on: yes"). Synthetic symbols only (ZZ*), stub DB, mocked provider; no network, no psycopg2, no production state."""
from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import yfinance_info_snapshot_refresh as yfr  # noqa: E402

NOW = datetime(2026, 10, 26, 9, 40, tzinfo=timezone.utc)
LID = "yfinance-info-snapshot"


# ── fakes ────────────────────────────────────────────────────────────────────────────────────────────────────────
class FakeCursor:
    def __init__(self, db):
        self.db, self.description, self._rows, self.rowcount = db, None, [], 0

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.db.statements.append((s, params))
        self.description, self._rows, self.rowcount = None, [], 0
        if "to_regclass" in s:
            self._set(["present"], [(self.db.table,)])
        elif s.startswith("SELECT symbol, fetched_at, status") and "FROM yfinance_info_snapshot" in s:
            if not self.db.table:
                raise RuntimeError('relation "yfinance_info_snapshot" does not exist')
            want = set(params[0])
            self._set(["symbol", "fetched_at", "status", "quote_type", "payload", "payload_keys", "error"],
                      [(k, v["fetched_at"], v["status"], None, v.get("payload") or {}, 0, None)
                       for k, v in self.db.rows.items() if k in want])
        elif s.startswith("INSERT INTO yfinance_info_snapshot"):
            if self.db.readonly:
                raise RuntimeError("cannot execute INSERT in a read-only transaction")
            sym, fetched_at, status = params[0], params[1], params[2]
            self.db.rows[sym] = {"fetched_at": fetched_at, "status": status, "payload": json.loads(params[4])}
            self.rowcount = 1
        elif "FROM operator_starred_symbols" in s:
            self._set(["s", "at", "ref", "label"], [(w, None, None, None) for w in self.db.watch])
        else:
            self._set(["s", "at", "ref", "label"], [])

    def _set(self, cols, rows):
        self.description = [(c,) for c in cols]
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, *, table=True, watch=(), rows=None):
        self.table, self.watch, self.rows = table, list(watch), dict(rows or {})
        self.statements, self.readonly, self.commits = [], False, 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _args(**kw):
    base = dict(ok_hours=20.0, negative_hours=168.0, max_symbols=300, sleep=0.25, probe=3)
    base.update(kw)
    return argparse.Namespace(**base)


def _state(tmp_path, held=("ZZA", "ZZB"), prospectus=("ZZP",)):
    st = tmp_path / "state"
    (st / "data/portfolios/state").mkdir(parents=True)
    (st / "data/portfolios/state/holdings.json").write_text(json.dumps({"holdings": [
        *[{"symbol": s, "shares": 10, "account": "fixture_brokerage"} for s in held],
        {"symbol": "ZZC", "shares": 0, "account": "fixture_brokerage"},
        {"symbol": "SPAXX", "shares": 100, "account": "fixture_brokerage", "is_cash": True},
    ]}))
    (st / "data/prospectus").mkdir(parents=True)
    (st / "data/prospectus/universe.json").write_text(json.dumps({"items": [{"symbol": s} for s in prospectus]}))
    return st


def _fetch_ok(calls):
    def fetch(sym):
        calls.append(sym)
        if sym == "ZZF":
            return {"status": "ok", "quote_type": "ETF", "payload": {"quoteType": "ETF", "totalAssets": 1.5e9,
                                                                       "_house_fund": {"top_holdings": []}}}
        return {"status": "ok", "quote_type": "EQUITY", "payload": {"quoteType": "EQUITY", "longName": f"{sym} Corp"}}
    return fetch


@pytest.fixture(autouse=True)
def _runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)


def _receipt(tmp_path):
    p = tmp_path / "state/data/runtime" / f"{LID}_last.json"
    return json.loads(p.read_text()) if p.exists() else None


# ── universe ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_universe_is_holdings_watch_prospectus_through_the_ticker_guard(tmp_path):
    st = _state(tmp_path)
    conn = FakeConn(watch=["ZZW", "ZZA", "12507E201"])
    uni, status = yfr.build_universe(st, db_query=yfr.query_fn(conn))
    assert sorted(uni) == ["ZZA", "ZZB", "ZZP", "ZZW"]  # no zero-share, no cash, no CUSIP
    assert uni["ZZA"] == ["held", "watch"] and uni["ZZP"] == ["prospectus"]
    assert status["held"] == "ok (2)" and status["prospectus"] == "ok (1)"


def test_unreadable_source_is_reported_not_fatal(tmp_path):
    st = _state(tmp_path)
    uni, status = yfr.build_universe(st, db_query=None)
    assert "ZZA" in uni and status["watch"].startswith("unreadable")


# ── due windows ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_due_windows_and_negative_cache():
    stored = {"ZZA": {"status": "ok", "age_hours": 5}, "ZZB": {"status": "ok", "age_hours": 30},
              "ZZC": {"status": "no_profile", "age_hours": 100}, "ZZD": {"status": "error", "age_hours": 200}}
    due, fresh = yfr.due_symbols(["ZZA", "ZZB", "ZZC", "ZZD", "ZZE"], stored, now=NOW, ok_hours=20, negative_hours=168)
    assert due == ["ZZB", "ZZD", "ZZE"] and fresh == 2


def test_fetch_many_paces_and_stops_on_throttle():
    sleeps, seen = [], []

    def fetch(sym):
        seen.append(sym)
        if sym == "ZZC":
            raise yfr.RateLimited("429 Too Many Requests")
        return {"status": "ok", "payload": {"quoteType": "EQUITY"}}

    rows, skipped = yfr.fetch_many(["ZZA", "ZZB", "ZZC", "ZZD"], fetch, sleep_s=1.0, now_fn=lambda: NOW,
                                   sleep_fn=sleeps.append)
    assert [r["symbol"] for r in rows] == ["ZZA", "ZZB"] and seen == ["ZZA", "ZZB", "ZZC"]
    assert skipped == {"rate_limited": 2} and sleeps == [1.0, 1.0]


def test_throttle_detection():
    assert yfr._is_throttle(RuntimeError("YFRateLimitError: Too Many Requests. Rate limited."))
    assert not yfr._is_throttle(KeyError("quoteType"))


# ── run: dry vs apply ────────────────────────────────────────────────────────────────────────────────────────────
def test_dry_run_writes_nothing_and_probes_at_most_three(tmp_path, capsys):
    st = _state(tmp_path, held=("ZZA", "ZZB", "ZZF", "ZZG"))
    conn, calls = FakeConn(watch=["ZZW"]), []
    rc = yfr.run(apply=False, state=st, connect=lambda ro: (setattr(conn, "readonly", ro) or conn),
                 fetch=_fetch_ok(calls), args=_args(), now_fn=lambda: NOW, sleep_fn=lambda s: None)
    assert rc == 0 and conn.readonly is True and len(calls) == 3
    assert not any(s.startswith("INSERT") for s, _ in conn.statements) and conn.commits == 0
    assert _receipt(tmp_path) is None
    assert "DRY-RUN" in capsys.readouterr().out


def test_apply_writes_through_single_writer_and_v2_receipt(tmp_path):
    st = _state(tmp_path, held=("ZZA", "ZZF"))
    fresh_at = NOW - timedelta(hours=2)
    conn, calls = FakeConn(watch=["ZZW"], rows={"ZZW": {"fetched_at": fresh_at, "status": "ok",
                                                         "payload": {"quoteType": "EQUITY"}}}), []
    rc = yfr.run(apply=True, state=st, connect=lambda ro: conn, fetch=_fetch_ok(calls), args=_args(),
                 now_fn=lambda: NOW, sleep_fn=lambda s: None)
    assert rc == 0 and sorted(calls) == ["ZZA", "ZZF", "ZZP"]  # ZZW fresh -> not fetched
    assert conn.commits == 1 and conn.rows["ZZF"]["payload"]["totalAssets"] == 1.5e9
    r = _receipt(tmp_path)
    assert r["status"] == "ok" and r["produced_count"] == 3 and r["attempted_count"] == 3
    assert r["skipped_reasons"] == {"fresh": 1} and r["output_fields"] == "LaneRunReceipt@v2"


def test_apply_nothing_due_is_allowed_empty(tmp_path):
    st = _state(tmp_path, held=("ZZA",), prospectus=())
    conn = FakeConn(rows={"ZZA": {"fetched_at": NOW - timedelta(hours=1), "status": "ok", "payload": {"a": 1}}})
    rc = yfr.run(apply=True, state=st, connect=lambda ro: conn, fetch=_fetch_ok([]), args=_args(),
                 now_fn=lambda: NOW, sleep_fn=lambda s: None)
    r = _receipt(tmp_path)
    assert rc == 0 and r["produced_count"] == 0 and r["empty_reason"] == "nothing_due"


def test_run_cap_limits_fetches_held_first(tmp_path):
    st = _state(tmp_path, held=("ZZH",), prospectus=("ZZA", "ZZB"))
    conn, calls = FakeConn(), []
    yfr.run(apply=True, state=st, connect=lambda ro: conn, fetch=_fetch_ok(calls), args=_args(max_symbols=1),
            now_fn=lambda: NOW, sleep_fn=lambda s: None)
    assert calls == ["ZZH"] and _receipt(tmp_path)["skipped_reasons"]["over_run_cap"] == 2


def test_missing_table_is_unconfigured_exit_1(tmp_path):
    st = _state(tmp_path)
    conn = FakeConn(table=False)
    rc = yfr.run(apply=True, state=st, connect=lambda ro: conn, fetch=_fetch_ok([]), args=_args(),
                 now_fn=lambda: NOW, sleep_fn=lambda s: None)
    r = _receipt(tmp_path)
    assert rc == 1 and r["status"] == "failed" and r["summary"]["failure_kind"] == "unconfigured"


def test_db_unreachable_is_dependency_unavailable(tmp_path):
    def boom(ro):
        raise OSError("connection refused")

    rc = yfr.run(apply=True, state=_state(tmp_path), connect=boom, fetch=_fetch_ok([]), args=_args(),
                 now_fn=lambda: NOW, sleep_fn=lambda s: None)
    assert rc == 1 and _receipt(tmp_path)["summary"]["failure_kind"] == "dependency_unavailable"


def test_every_fetch_throttled_fails(tmp_path):
    def fetch(sym):
        raise yfr.RateLimited("429")

    rc = yfr.run(apply=True, state=_state(tmp_path), connect=lambda ro: FakeConn(), fetch=fetch, args=_args(),
                 now_fn=lambda: NOW, sleep_fn=lambda s: None)
    assert rc == 1 and _receipt(tmp_path)["summary"]["failure_kind"] == "dependency_unavailable"


def test_parse_defaults_dry_and_bounds():
    a = yfr.parse([])
    assert not a.apply and a.max_symbols == 300 and a.sleep == 1.0 and a.probe == 3
    with pytest.raises(SystemExit):
        yfr.parse(["--sleep", "0"])
    with pytest.raises(SystemExit):
        yfr.parse(["--apply", "--dry-run"])


def test_yfinance_fetch_shapes(monkeypatch):
    import types

    class T:
        def __init__(self, sym):
            self.sym = sym

        @property
        def info(self):
            if self.sym == "ZZX":
                return {}
            return {"quoteType": "ETF", "totalAssets": 2e9, "fundFamily": "Fixture Funds", "nan": float("nan")}

        @property
        def funds_data(self):
            return types.SimpleNamespace(top_holdings=None, description="The fund tracks the Fixture Aerospace Index.",
                                         fund_overview={"family": "Fixture Funds"})

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    ok = yfr.yfinance_fetch("ZZF")
    assert ok["status"] == "ok" and "nan" not in ok["payload"]
    assert ok["payload"]["_house_fund"]["description"].startswith("The fund tracks")
    assert yfr.yfinance_fetch("ZZX")["status"] == "no_profile"


# ── prospectus fund block ────────────────────────────────────────────────────────────────────────────────────────
class _Bundle:
    def __init__(self):
        self.symbol, self.facts, self.blocks, self.context = "ZZF", [], {}, {}

    def add(self, kind, label, **kw):
        self.facts.append({"kind": kind, "label": label, **kw})
        return f"f{len(self.facts)}"


class _Src:
    def __init__(self, rows=None, raise_missing=False):
        self.rows, self.raise_missing = rows or [], raise_missing

    def db(self):
        def q(sql, params=None, fetch="all"):
            if "yfinance_info_snapshot" in sql:
                if self.raise_missing:
                    raise RuntimeError('relation "yfinance_info_snapshot" does not exist')
                return self.rows
            return []
        return q


def _yf_row(age_h=5, **payload):
    base = {"quoteType": "ETF", "totalAssets": 2.5e9, "fundFamily": "Fixture Funds", "fundInceptionDate": 1136073600,
            "_house_fund": {"description": "The fund seeks to track the Fixture Select Aerospace Index, which ...",
                            "top_holdings": [{"symbol": "ZZH1", "name": "One", "weight_pct": 5.5},
                                             {"symbol": "ZZH2", "name": "Two", "weight_pct": 4.0}]}}
    base.update(payload)
    return {"symbol": "ZZF", "fetched_at": NOW - timedelta(hours=age_h), "status": "ok", "quote_type": "ETF",
            "payload": base, "payload_keys": len(base), "error": None}


def _profile(src, lookthrough=None):
    from lib.prospectus import etf_profile as ep

    b = _Bundle()
    yf = ep.yfinance_snapshot(src, "ZZF", now=NOW)
    return ep.fund_profile(b, src, {}, {"label": None}, lookthrough=lookthrough, last=None, yf=yf), b, yf


def test_fund_block_reads_aum_issuer_inception_index_and_top_holdings_from_snapshot():
    fp, b, _ = _profile(_Src([_yf_row()]))
    assert fp["aum_usd"] == 2.5e9 and fp["issuer"] == "Fixture Funds" and fp["inception_date"] == "2006-01-01"
    assert fp["index_tracked"] == "Fixture Select Aerospace Index"
    assert [r["name"] for r in fp["top_holdings"]] == ["ZZH1", "ZZH2"]
    assert fp["top_holdings_source"].startswith("yfinance_info_snapshot")
    labels = {f["label"]: f for f in b.facts}
    assert labels["Fund assets under management $"]["source"].startswith("yfinance_info_snapshot")
    assert not any("assets under management" in g for g in fp["gaps"])


def test_house_lookthrough_still_wins_for_top_holdings():
    lt = {"fund": {"top_holdings": {"ZZL1": 9.0}, "fetched_date": "2026-10-20"}}
    fp, _, _ = _profile(_Src([_yf_row()]), lookthrough=lt)
    assert [r["name"] for r in fp["top_holdings"]] == ["ZZL1"] and fp["top_holdings_source"].startswith("fund look")


@pytest.mark.parametrize("src", [_Src(raise_missing=True), _Src([]), _Src([_yf_row(age_h=24 * 40)]),
                                 _Src([{**_yf_row(), "status": "no_profile", "payload": {}}])])
def test_missing_table_row_stale_or_negative_degrades_to_gaps(src):
    fp, _, yf = _profile(src)
    assert "gap" in yf and fp["aum_usd"] is None and fp["issuer"] is None and fp["index_tracked"] is None
    assert any(g.startswith("assets under management") for g in fp["gaps"])
    assert fp["top_holdings"] == []


def test_fund_table_rows():
    from lib.prospectus import extensions

    fp, _, _ = _profile(_Src([_yf_row()]))
    rows = dict(extensions.fund_tables({"blocks": {"fund_profile": {**fp, "category": "x"}}})[0]["rows"])
    assert rows["Issuer · inception"] == "Fixture Funds · 2006-01-01"
    assert rows["Index tracked"] == "Fixture Select Aerospace Index"


# ── config pins ──────────────────────────────────────────────────────────────────────────────────────────────────
def _row(path, key="lanes", id_key="lane_id"):
    return next(x for x in json.loads((ROOT / path).read_text())[key] if x.get(id_key) == LID)


def test_registry_allowlist_contract_are_shadow():
    reg = _row("config/lane_registry.json")
    assert reg["scheduler"]["kind"] == "n8n" and reg["scheduler"]["stage"] == "shadow"
    assert reg["dispatch"]["mode"] == "dry_run" and reg["dispatch"]["class"] == "ingest"
    al = _row("config/n8n_run_allowlist.json")
    assert al["live_arg"] is None and al["dry_run_arg"] == ["--dry-run"]
    assert al["command"] == ["$PY", "scripts/yfinance_info_snapshot_refresh.py"]
    hc = _row("config/n8n_health_contracts.json", key="contracts", id_key="id")
    assert hc["stage"] == "shadow" and hc["expected_output"]["empty_allowed_reasons"] == ["nothing_due"]


def test_registry_domain_names_the_writer_and_migration():
    d = next(x for x in json.loads((ROOT / "config/data_source_authority.json").read_text())["domains"]
             if x["domain"] == "yfinance_info_snapshot")
    assert d["writer"] == "scripts/lib/writers/yfinance_info_snapshot_writer.py"
    assert (ROOT / "migrations/2026_10_10_yfinance_info_snapshot.sql").exists()


def test_closure_no_broker_sender_model():
    tree = ast.parse((ROOT / "scripts/yfinance_info_snapshot_refresh.py").read_text())
    mods = {(n.module or "") for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    bad = ("broker", "order", "telegram", "send", "notif", "llm", "openai", "anthropic", "active_trader")
    assert not [m for m in mods if any(b in m.lower().replace("data_broker", "") for b in bad)]  # the data broker is a read layer
    src = (ROOT / "scripts/yfinance_info_snapshot_refresh.py").read_text()
    assert "INSERT INTO" not in src  # the single declared writer owns the statement
