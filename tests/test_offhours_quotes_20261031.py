"""Market Risk Engine off-hours quotes: Schwab market data into market_quotes_extended (2026-10-31, stacked on #2384).

scripts/lib/offhours_quotes.py + scripts/market_quotes_offhours_schwab.py (OFF by default until the operator approves
the schedule; AGENTS.md 28.2.0 ratified on PR #2407). Alpaca extended prints are #2384's producer; this PR adds DIA,
RSP, SOXX and XLK to its universe (config/market_quotes_extended.json).

Proves:
  * session tagging: rows follow #2384's contract exactly -- premarket/afterhours via market_quotes_extended.session_of,
    bar_end = the trade instant (tz-aware UTC), the right reference close and date per session; overnight, regular and
    non-trading-day prints are refused, never stored or relabelled; every row passes the store's writer validate();
  * the universe is read from config (#2384's symbol list + the engine's large-cap list), never hardcoded;
  * the store is market_quotes_extended through its single writer, never market_quotes;
  * the Schwab path is off by default, stops before any Schwab/DB module, refuses a non-market-data URL, refuses
    --apply while the §7A domain is proposed, and never reaches an order capability (lane capability scanner +
    function-level reach walk);
  * a dry run writes nothing.

Hermetic: fixtures only, no network, no DB, no credential, no live state. Schedules nothing.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import offhours_quotes as oq  # noqa: E402
from lib.writers.market_quotes_extended_writer import validate  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "offhours_quotes"
AH_FX = FX / "schwab_quotes_afterhours_20261029.json"
PM_FX = FX / "schwab_quotes_premarket_20261030.json"
SCHWAB_ENTRY = ROOT / "scripts" / "market_quotes_offhours_schwab.py"
LIB = ROOT / "scripts" / "lib" / "offhours_quotes.py"


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _ms(s: str) -> int:
    return int(_t(s).timestamp() * 1000)


@pytest.fixture()
def cfg():
    return oq.load_config()


def _rows(path: Path, cfg):
    doc = json.loads(path.read_text())
    return doc, *oq.schwab_rows(doc["quotes"], _t(doc["now"]), cfg)


# ── timestamps and session tagging ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-29T21:58:12.123456789Z", "2026-10-29T21:58:12.123456+00:00"),
    ("2026-10-29T21:59:30.5Z", "2026-10-29T21:59:30.500000+00:00"),
    ("2026-10-29T17:50:00-04:00", "2026-10-29T21:50:00+00:00"),
    (1793317750000, "2026-10-29T23:49:10+00:00"),
])
def test_parse_ts_is_precise_and_utc(raw, expected):
    got = oq.parse_ts(raw)
    assert got is not None and got.utcoffset() == timedelta(0) and got.isoformat() == expected


@pytest.mark.parametrize("raw", [None, "", "yesterday", "2026-10-29T21:50:00", 0, -5, True, float("nan")])
def test_parse_ts_refuses_ambiguous(raw):
    assert oq.parse_ts(raw) is None


def test_afterhours_rows_follow_store_contract(cfg):
    doc, rows, skipped = _rows(AH_FX, cfg)
    assert [r["symbol"] for r in rows] == ["/ES", "QQQ"]
    r = rows[1]
    assert validate(r) is None  # the store's own writer accepts it unchanged
    assert r["session"] == "afterhours" and str(r["session_date"]) == "2026-10-29"
    assert r["bar_end"] == oq.parse_ts(doc["quotes"]["QQQ"]["extended"]["tradeTime"])  # the trade instant, exactly
    assert r["bar_end"].tzinfo is not None and r["bar_end"] - r["bar_start"] == timedelta(milliseconds=1)
    assert r["price"] == 610.85  # extended block wins over quote.lastPrice
    # after-hours moves from the SAME day's close (#2384 review), never quote.closePrice (the previous day)
    assert r["reference_close"] == 615.0 and str(r["reference_date"]) == "2026-10-29"
    assert r["reference_basis"] == "schwab_regular_market_last_price_dated" and r["change_pct"] == -0.6748
    assert r["feed"] == "schwab"
    # weekday futures after-hours (review of #2423, F6): measured from that day's settlement when Schwab dates it
    es = rows[0]
    assert es["session"] == "afterhours" and es["reference_close"] == 6850.0 and str(es["reference_date"]) == "2026-10-29"
    assert es["reference_basis"] == "schwab_quote_close_price_settle_dated" and validate(es) is None
    reasons = {s["symbol"]: s["reason"] for s in skipped}
    assert reasons == {"/NQ": "no_dated_reference_for_afterhours", "$VIX": "no_dated_reference_for_afterhours",
                       "$SPX": "stale_trade", "SPY": "no_trade_price_or_time", "/RTY": "not_a_quote"}


def test_premarket_rows_reference_previous_session(cfg):
    doc, rows, skipped = _rows(PM_FX, cfg)
    by = {r["symbol"]: r for r in rows}
    assert set(by) == {"/ES", "QQQ"}
    for sym, r in by.items():
        assert validate(r) is None
        assert r["session"] == "premarket" and str(r["session_date"]) == "2026-10-30"
        assert str(r["reference_date"]) == "2026-10-29"  # previous NYSE session
        q = doc["quotes"][sym]
        assert r["bar_end"] == oq.parse_ts((q.get("extended") or q["quote"])["tradeTime"])
    assert by["/ES"]["reference_basis"] == "schwab_quote_close_price_settle_dated"
    assert by["QQQ"]["reference_basis"] == "schwab_regular_market_last_price_dated"
    assert by["/ES"]["change_pct"] == round(100 * (6760.5 - 6850.0) / 6850.0, 4)
    # no dated close in the payload: refused, never measured against an assumed previous close (review of #2416 F4)
    assert {s["symbol"]: s["reason"] for s in skipped} == {
        "NVDA": "no_dated_reference_for_premarket", "/NQ": "no_dated_reference_for_premarket",
        "$VIX": "no_dated_reference_for_premarket"}


def test_premarket_after_holiday_uses_last_session(cfg):
    # Friday 2026-11-27 pre-market: the previous NYSE session is Wednesday 11-25 (Thanksgiving closed).
    p = {"/ES": {"quote": {"lastPrice": 6800.0, "closePrice": 6820.0, "tradeTime": _ms("2026-11-27T08:00:00-05:00"),
                           "settleTime": _ms("2026-11-25T16:00:00-05:00")}}}
    rows, _ = oq.schwab_rows(p, _t("2026-11-27T08:05:00-05:00"), cfg)
    assert str(rows[0]["reference_date"]) == "2026-11-25"


@pytest.mark.parametrize("ts", [
    # weekday overnight, Sunday 18:00 futures open and the small hours are stored since
    # migrations/2026_10_31_market_quotes_extended_overnight.sql (tests/test_market_quotes_overnight_20261031.py)
    "2026-10-29T11:00:00-04:00",   # regular session
    "2026-10-31T12:00:00-04:00",   # Saturday
    "2026-10-30T21:00:00-04:00",   # Friday 20:00+: no overnight session into the weekend
    "2026-11-01T17:30:00-05:00",   # Sunday before the 18:00 futures open
])
def test_prints_outside_store_sessions_are_refused(ts, cfg):
    p = {"/ES": {"quote": {"lastPrice": 6800.0, "closePrice": 6820.0, "tradeTime": _ms(ts)}}}
    rows, skipped = oq.schwab_rows(p, _t(ts) + timedelta(minutes=2), cfg)
    assert rows == [] and skipped[0]["reason"] == "session_not_in_store_contract"


def test_stale_and_future_prints_refused(cfg):
    p = {"QQQ": {"assetMainType": "EQUITY", "quote": {"closePrice": 615.0},
                 "extended": {"lastPrice": 600.0, "tradeTime": _ms("2026-10-30T07:00:00-04:00")}}}
    assert oq.schwab_rows(p, _t("2026-10-30T08:00:00-04:00"), cfg)[1][0]["reason"] == "stale_trade"
    assert oq.schwab_rows(p, _t("2026-10-30T06:00:00-04:00"), cfg)[1][0]["reason"] == "future_timestamp"


@pytest.mark.parametrize("ts,ok", [
    ("2026-11-01T17:45:00-05:00", False), ("2026-11-01T18:00:00-05:00", True), ("2026-11-02T03:00:00-05:00", True),
    ("2026-11-02T11:00:00-05:00", False), ("2026-11-02T19:00:00-05:00", True), ("2026-11-06T09:15:00-05:00", True),
    ("2026-11-06T09:30:00-05:00", False), ("2026-11-07T12:00:00-05:00", False),
])
def test_schwab_window(ts, ok, cfg):
    assert oq.schwab_window(_t(ts), cfg)[0] is ok


# ── universe from config ────────────────────────────────────────────────────────────────────────────


def test_universe_union_of_config_sources(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"symbols": ["qqq", "SPY"]}))
    (tmp_path / "p.yaml").write_text("extended_hours:\n  heavyweights: [NVDA, QQQ]\n")
    cfg = {"universe": {"sources": [{"file": "a.json", "key": "symbols"},
                                    {"file": "p.yaml", "key": "extended_hours.heavyweights"},
                                    {"file": "p.yaml", "key": "no.such"}, {"file": "gone.json", "key": "x"}]}}
    syms, prov = oq.resolve_universe(cfg, root=tmp_path)
    assert syms == ["QQQ", "SPY", "NVDA"]
    assert prov["missing_refs"][0] == "p.yaml:no.such" and prov["missing_refs"][1].startswith("gone.json:x")


def test_shipped_universe_reads_2384_list_and_engine_policy(cfg):
    srcs = cfg["universe"]["sources"]
    assert {"file": "config/market_quotes_extended.json", "key": "symbols"} in srcs
    assert {"file": "config/market_risk_policy.yaml", "key": "extended_hours.heavyweights"} in srcs
    syms, prov = oq.resolve_universe(cfg)
    assert prov["missing_refs"] == []
    ext = json.loads((ROOT / "config" / "market_quotes_extended.json").read_text())["symbols"]
    for etf in ("QQQ", "SPY", "IWM", "DIA", "RSP", "SMH", "SOXX", "XLK"):  # the Alpaca universe extension
        assert etf in ext and etf in syms
    assert syms[: len(ext)] == ext


def test_no_symbol_list_hardcoded_in_code():
    for path in (LIB, SCHWAB_ENTRY):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                vals = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                assert not {"QQQ", "SPY", "/ES", "$SPX"} & vals, path.name


# ── the store: market_quotes_extended only ──────────────────────────────────────────────────────────


def test_never_writes_market_quotes():
    for path in (LIB, SCHWAB_ENTRY):
        src = path.read_text()
        assert "market_quotes_writer" not in src and "write_market_quotes" not in src
        assert "INSERT INTO" not in src.upper()
    assert "from lib.writers.market_quotes_extended_writer import write_extended_quotes" in SCHWAB_ENTRY.read_text()


def test_apply_refuses_while_domain_proposed(cfg):
    on = {**cfg, "schwab": {**cfg["schwab"], "enabled": True}}

    def boom(*_a, **_k):
        raise AssertionError("fetched or wrote while the store's domain is proposed")
    r = oq.run(cfg=on, now=_t("2026-10-30T08:00:00-04:00"), fetch=boom, write=boom, dry_run=False,
               promoted=lambda: False)
    assert r["status"] == "refused_domain_proposed"


def test_apply_writes_through_the_extended_writer(cfg):
    doc = json.loads(PM_FX.read_text())
    on = {**cfg, "schwab": {**cfg["schwab"], "enabled": True}}
    got = []
    r = oq.run(cfg=on, now=_t(doc["now"]), fetch=lambda s: doc["quotes"], dry_run=False, promoted=lambda: True,
               write=lambda rows: got.extend(rows) or {"inserted": len(rows), "rejected": []})
    assert r["status"] == "ok" and r["inserted"] == 2 and all(validate(x) is None for x in got)


# ── Schwab: off by default, never reaches an order capability ───────────────────────────────────────


def test_schwab_switch_is_on_and_off_still_stops_everything(cfg):
    # Operator 2026-11-01 ~13:45 ET "enable schwab" (AGENTS.md 29.2.0 §24.11); the off path must still stop every call.
    assert cfg["schwab"]["enabled"] is True
    assert "29.2.0" in cfg["schwab"]["requires_policy"]
    off = {**cfg, "schwab": {**cfg["schwab"], "enabled": False}}

    def boom(*_a, **_k):
        raise AssertionError("fetch/write must not run while the switch is off")
    r = oq.run(cfg=off, now=_t("2026-10-30T08:00:00-04:00"), fetch=boom, write=boom, dry_run=False,
               promoted=lambda: True)
    assert r["status"] == "disabled" and r["inserted"] == 0


def test_schwab_apply_stops_before_schwab_modules(monkeypatch, capsys):
    import market_quotes_offhours_schwab as ent

    def boom(*_a, **_k):
        raise AssertionError("live path reached while disabled")
    real = ent.oq.load_config()
    off = {**real, "schwab": {**real["schwab"], "enabled": False}}
    monkeypatch.setattr(ent.oq, "load_config", lambda *_a: off)
    monkeypatch.setattr(ent, "live_fetch", boom)
    monkeypatch.setattr(ent, "_write", boom)
    for name in ("schwab_token_manager", "schwab_transport"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    assert ent.main(["--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "disabled"
    assert "schwab_token_manager" not in sys.modules and "schwab_transport" not in sys.modules


def test_schwab_dry_run_is_fixtures_only(capsys):
    import market_quotes_offhours_schwab as ent

    assert ent.main(["--dry-run"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"


def test_schwab_url_rail(cfg):
    import market_quotes_offhours_schwab as ent

    assert ent.marketdata_url(cfg) == "https://api.schwabapi.com/marketdata/v1/quotes"
    for bad in ("https://api.schwabapi.com/trader/v1/", "https://api.schwabapi.com/v1/oauth/",
                "https://evil.example/marketdata/v1/"):
        with pytest.raises(ValueError):
            ent.marketdata_url({"schwab": {"marketdata_base_url": bad}})


def test_schwab_probe_makes_no_live_call(cfg, monkeypatch):
    import market_quotes_offhours_schwab as ent

    monkeypatch.setattr(ent, "live_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("live call")))
    p = ent.probe(cfg)
    assert p["enabled"] is True and p["live_call_made"] is False and p["url_rail_ok"] is True
    assert p["store"] == "market_quotes_extended"
    assert p["symbols"][:7] == [*cfg["schwab"]["futures"], *cfg["schwab"]["indices"]]


ORDER_NAMES = {"place_order", "submit_order", "cancel_order", "replace_order"}
FORBIDDEN_IMPORTS = ("schwab_transport", "brokers", "alpaca_trade_api", "schwab.client")


def test_own_modules_import_no_broker_execution_code():
    for path in (LIB, SCHWAB_ENTRY):
        tree = ast.parse(path.read_text())
        mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not [m for m in mods if m.startswith(FORBIDDEN_IMPORTS)], (path.name, mods)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not names & ORDER_NAMES


def _scan(entry: str) -> dict:
    import audit_lane_transitive_capabilities as cap

    res = cap.Resolver()
    p = ROOT / entry
    order, parent = res.closure(p)
    eager, _ = res.closure(p, eager_only=True)
    caps: dict[str, list[list[str]]] = {}
    for mod in order:
        for c in res.info(mod).caps:
            caps.setdefault(c, []).append(cap._chain(mod, parent))
    return {"caps": caps, "eager": {c for m in eager for c in res.info(m).caps}}


def test_capability_scanner_schwab_entry():
    s = _scan("scripts/market_quotes_offhours_schwab.py")
    assert "direct_sender" not in s["caps"]
    assert not {"order_placement", "broker_module", "direct_sender"} & s["eager"]  # nothing forbidden at start
    # Lazy static reach to the order surface exists only via the token manager's live_probe or the shared
    # db_adapter chain (operator ruling DD01 2026-10-15), never through this lane's own code; the walk below proves
    # the token-manager functions this lane calls do not reach it.
    own = {"scripts/market_quotes_offhours_schwab.py", "scripts/lib/offhours_quotes.py"}
    for chain in s["caps"].get("order_placement", []):
        assert chain[1] in {"scripts/schwab_token_manager.py", "scripts/db_adapter.py"} or chain[1] in own, chain
        assert not (set(chain[1:]) & own), chain


TM = ROOT / "scripts" / "schwab_token_manager.py"
CALLED = {"canonical_token_key", "health", "get_access_token", "is_auth_failure", "record_auth_failure"}


def test_called_token_manager_functions_never_reach_order_code():
    tree = ast.parse(TM.read_text())
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert CALLED <= set(fns), "token manager public read API changed"
    module_level = ast.Module(body=[n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))],
                              type_ignores=[])
    todo, seen, lazy_mods, bodies = list(CALLED) + ["_load_broker_secrets_env"], set(), set(), [module_level]
    while todo:
        name = todo.pop()
        if name in seen or name not in fns:
            continue
        seen.add(name)
        bodies.append(fns[name])
        todo += [n.func.id for n in ast.walk(fns[name])
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in fns]
    for body in bodies:
        for n in ast.walk(body):
            if isinstance(n, ast.Import):
                lazy_mods |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                lazy_mods.add(n.module)
            assert not (isinstance(n, ast.Name) and n.id in ORDER_NAMES)
            assert not (isinstance(n, ast.Attribute) and n.attr in ORDER_NAMES)
    assert "live_probe" not in seen  # the one function that imports schwab_transport is not on this path
    assert not [m for m in lazy_mods if m.startswith(FORBIDDEN_IMPORTS)], sorted(lazy_mods)
    import audit_lane_transitive_capabilities as cap
    res = cap.Resolver()
    for m in sorted(lazy_mods):
        for p in res.resolve(TM, m, 0, None):
            eager, _ = res.closure(p, eager_only=True)
            assert not any("order_placement" in res.info(e).caps for e in eager), (m, p)


# ── dry runs write nothing ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fx,n", [(AH_FX, 2), (PM_FX, 2)])
def test_schwab_dry_run_writes_nothing(fx, n, monkeypatch, capsys):
    import market_quotes_offhours_schwab as ent

    def boom(*_a, **_k):
        raise AssertionError("dry run reached live code")
    monkeypatch.setattr(ent, "_write", boom)
    monkeypatch.setattr(ent, "live_fetch", boom)
    doc = json.loads(fx.read_text())
    assert ent.main(["--dry-run", "--fixture", str(fx), "--now", doc["now"]]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "dry_run" and out["inserted"] == 0 and out["config_enabled"] is True
    assert out["store"] == "market_quotes_extended" and len(out["rows"]) == n


def test_run_requires_writer_when_not_dry(cfg):
    doc = json.loads(PM_FX.read_text())
    on = {**cfg, "schwab": {**cfg["schwab"], "enabled": True}}
    with pytest.raises(ValueError):
        oq.run(cfg=on, now=_t(doc["now"]), fetch=lambda s: doc["quotes"], write=None, dry_run=False,
               promoted=lambda: True)


def test_feed_label_comes_from_config(tmp_path):
    src = (ROOT / "config" / "market_risk_offhours_quotes.yaml").read_text()
    assert "\n  feed: schwab" in src
    bad = tmp_path / "c.yaml"
    bad.write_text(src.replace("\n  feed: schwab", "\n  feed: ''"))
    with pytest.raises(oq.ConfigError):
        oq.load_config(bad)
