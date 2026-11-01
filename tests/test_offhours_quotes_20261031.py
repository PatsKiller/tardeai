"""Market Risk Engine off-hours quote collector (2026-10-31).

scripts/lib/offhours_quotes.py + scripts/external_market_data_ingest.py --quotes-offhours (Alpaca, IEX) +
scripts/market_quotes_offhours_schwab.py (Schwab market data, OFF by default; AGENTS.md 28.2.0 / PR #2407 pending).

Proves:
  * session tagging: every row's fetched_at is the quote's OWN trade timestamp (tz-aware UTC), and its session tag
    (premarket / regular / after_hours / overnight / closed / weekend / holiday) derives from that timestamp;
  * the universe is read from config (fixed proxies + the engine's large-cap list from the policy file), never
    hardcoded, and a missing policy key is named, not filled;
  * the Schwab path is off by default, stops before any Schwab/DB module is touched, refuses a non-market-data URL,
    and never reaches an order capability (lane capability scanner + a function-level reach walk);
  * a dry run writes nothing (the DB connection and the writer raise if touched).

Hermetic: fixtures only, no network, no DB, no credential, no live state. Schedules nothing.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import offhours_quotes as oq  # noqa: E402
from lib.writers.market_quotes_writer import coerce_quote_row  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "offhours_quotes"
ALPACA_FX = FX / "alpaca_snapshots_afterhours_20261029.json"
SCHWAB_FX = FX / "schwab_quotes_afterhours_20261029.json"
SCHWAB_ENTRY = ROOT / "scripts" / "market_quotes_offhours_schwab.py"
LIB = ROOT / "scripts" / "lib" / "offhours_quotes.py"


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s)


@pytest.fixture()
def cfg():
    return oq.load_config()


# ── session tagging ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-29T21:58:12.123456789Z", "2026-10-29T21:58:12.123456+00:00"),
    ("2026-10-29T21:59:30.5Z", "2026-10-29T21:59:30.500000+00:00"),
    ("2026-10-29T21:50:00Z", "2026-10-29T21:50:00+00:00"),
    ("2026-10-29T17:50:00-04:00", "2026-10-29T21:50:00+00:00"),
    (1793317750000, "2026-10-29T23:49:10+00:00"),
])
def test_parse_ts_is_precise_and_utc(raw, expected):
    got = oq.parse_ts(raw)
    assert got is not None and got.utcoffset().total_seconds() == 0
    assert got.isoformat() == expected


@pytest.mark.parametrize("raw", [None, "", "yesterday", "2026-10-29T21:50:00", 0, -5, True, float("nan")])
def test_parse_ts_refuses_ambiguous(raw):
    assert oq.parse_ts(raw) is None  # naive or junk timestamps are skipped, never guessed


@pytest.mark.parametrize("ts,tag", [
    ("2026-10-29T08:15:00-04:00", "premarket"),
    ("2026-10-29T11:00:00-04:00", "regular"),
    ("2026-10-29T16:00:00-04:00", "after_hours"),
    ("2026-10-29T19:59:00-04:00", "after_hours"),
    ("2026-10-29T21:00:00-04:00", "overnight"),   # Thursday night before Friday's session
    ("2026-10-30T02:00:00-04:00", "overnight"),   # small hours of a trading day
    ("2026-10-30T21:00:00-04:00", "closed"),      # Friday night: Saturday is not a trading day
    ("2026-11-01T18:30:00-05:00", "overnight"),   # Sunday evening futures open before Monday
    ("2026-10-31T12:00:00-04:00", "weekend"),
    ("2026-11-26T12:00:00-05:00", "holiday"),     # Thanksgiving
])
def test_session_tag_from_timestamp(ts, tag, cfg):
    assert oq.session_tag(_t(ts), cfg) == tag


def test_alpaca_rows_carry_trade_time_and_session(cfg):
    doc = json.loads(ALPACA_FX.read_text())
    rows, skipped = oq.alpaca_rows(doc["snapshots"], _t(doc["now"]), cfg)
    by = {r["row"]["symbol"]: r for r in rows}
    assert set(by) == {"QQQ", "SPY", "NVDA"}
    for sym, r in by.items():
        raw_t = doc["snapshots"][sym]["latestTrade"]["t"]
        assert r["row"]["fetched_at"] == oq.parse_ts(raw_t)  # the trade's own time, not the write time
        assert r["row"]["fetched_at"].tzinfo is not None
        assert r["session"] == "after_hours" == oq.session_tag(r["row"]["fetched_at"], cfg)
        coerced = coerce_quote_row(r["row"], source="alpaca")  # the one writer accepts every row unchanged
        assert coerced["fetched_at"] == r["row"]["fetched_at"]
    reasons = {s["symbol"]: s["reason"] for s in skipped}
    assert reasons == {"XLK": "stale_trade", "DIA": "no_trade_price_or_time", "IWM": "no_trade_price_or_time"}


def test_regular_session_trade_is_not_relabelled(cfg):
    snap = {"Q": {"latestTrade": {"p": 10.0, "t": "2026-10-29T19:59:59Z"}}}  # 15:59:59 ET
    rows, skipped = oq.alpaca_rows(snap, _t("2026-10-29T16:15:00-04:00"), cfg)
    assert rows == [] and skipped[0]["reason"] == "session_regular"


def test_schwab_rows_prefer_extended_block_and_tag_sessions(cfg):
    doc = json.loads(SCHWAB_FX.read_text())
    rows, skipped = oq.schwab_rows(doc["quotes"], _t(doc["now"]), cfg)
    by = {r["row"]["symbol"]: r for r in rows}
    assert set(by) == {"/ES", "/NQ", "$VIX", "QQQ"}
    assert by["QQQ"]["row"]["price"] == 610.85  # extended.lastPrice, not quote.lastPrice
    assert by["QQQ"]["row"]["fetched_at"] == oq.parse_ts(doc["quotes"]["QQQ"]["extended"]["tradeTime"])
    assert by["/ES"]["row"]["fetched_at"] == oq.parse_ts(doc["quotes"]["/ES"]["quote"]["tradeTime"])
    assert all(r["session"] == "after_hours" for r in rows)
    assert {s["symbol"]: s["reason"] for s in skipped} == {
        "$SPX": "stale_trade", "SPY": "no_trade_price_or_time", "/RTY": "not_a_quote"}


def test_overnight_futures_row_is_tagged_overnight(cfg):
    ms = int(_t("2026-11-01T19:10:00-05:00").timestamp() * 1000)  # Sunday evening
    payload = {"/ES": {"quote": {"lastPrice": 6800.0, "closePrice": 6820.0, "tradeTime": ms}}}
    rows, _ = oq.schwab_rows(payload, _t("2026-11-01T19:15:00-05:00"), cfg)
    assert rows[0]["session"] == "overnight"


def test_alpaca_prev_close_has_one_implementation():
    import external_market_data_ingest as emdi

    snap = {"dailyBar": {"t": "2026-10-28T04:00:00Z", "c": 5.0}, "prevDailyBar": {"t": "2026-10-27T04:00:00Z", "c": 4.0}}
    now = _t("2026-10-29T07:00:00-04:00")
    assert emdi._alpaca_prev_close(snap, now) == oq.alpaca_prev_close(snap, now) == 5.0
    assert oq.alpaca_prev_close(snap, _t("2026-10-28T18:00:00-04:00")) == 4.0
    src = (ROOT / "scripts" / "external_market_data_ingest.py").read_text()
    assert "prevDailyBar" not in src.split("def _alpaca_prev_close", 1)[1].split("\ndef ", 1)[0]


# ── windows ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ts,ok", [
    ("2026-10-29T16:00:00-04:00", True), ("2026-10-29T20:00:00-04:00", True), ("2026-10-29T20:15:00-04:00", False),
    ("2026-10-29T04:00:00-04:00", True), ("2026-10-29T09:30:00-04:00", True), ("2026-10-29T09:45:00-04:00", False),
    ("2026-10-29T12:00:00-04:00", False), ("2026-10-31T17:00:00-04:00", False), ("2026-11-26T17:00:00-05:00", False),
])
def test_alpaca_window(ts, ok, cfg):
    assert oq.alpaca_window(_t(ts), cfg)[0] is ok


@pytest.mark.parametrize("ts,ok", [
    ("2026-11-01T17:45:00-05:00", False), ("2026-11-01T18:00:00-05:00", True), ("2026-11-02T03:00:00-05:00", True),
    ("2026-11-02T11:00:00-05:00", False), ("2026-11-02T19:00:00-05:00", True), ("2026-11-06T09:15:00-05:00", True), ("2026-11-06T09:30:00-05:00", False),
    ("2026-11-06T09:45:00-05:00", False), ("2026-11-07T12:00:00-05:00", False),
])
def test_schwab_window(ts, ok, cfg):
    assert oq.schwab_window(_t(ts), cfg)[0] is ok


# ── universe from config ────────────────────────────────────────────────────────────────────────────


def test_universe_read_from_config_and_policy(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "policy.yaml").write_text("extended_hours:\n  heavyweights: [nvda, MSFT, QQQ]\n")
    cfg = {"universe": {"symbols": ["QQQ", "spy"], "policy_file": "config/policy.yaml",
                        "include_from_policy": ["extended_hours.heavyweights", "no.such.key"]}}
    syms, prov = oq.resolve_universe(cfg, root=tmp_path)
    assert syms == ["QQQ", "SPY", "NVDA", "MSFT"]
    assert prov["included"] == {"extended_hours.heavyweights": ["NVDA", "MSFT", "QQQ"]}
    assert prov["missing_refs"] == ["no.such.key"]


def test_shipped_config_universe_and_policy_ref(cfg):
    assert cfg["universe"]["symbols"] == ["QQQ", "SPY", "IWM", "DIA", "RSP", "SMH", "SOXX", "XLK"]
    assert cfg["universe"]["policy_file"] == "config/market_risk_policy.yaml"
    assert "extended_hours.heavyweights" in cfg["universe"]["include_from_policy"]
    syms, prov = oq.resolve_universe(cfg)
    assert syms[:8] == cfg["universe"]["symbols"]
    assert set(prov["missing_refs"]) | set(prov["included"]) == set(cfg["universe"]["include_from_policy"])


def test_no_symbol_list_hardcoded_in_code():
    for path in (LIB, SCHWAB_ENTRY):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                vals = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                assert not {"QQQ", "SPY", "/ES", "$SPX"} & set(vals), f"{path.name}: hardcoded symbols {vals}"


def test_run_uses_resolved_universe(cfg, tmp_path):
    seen = []
    doc = json.loads(ALPACA_FX.read_text())
    r = oq.run("alpaca", cfg=cfg, now=_t(doc["now"]), fetch=lambda s: seen.append(list(s)) or doc["snapshots"],
               write=None, dry_run=True)
    assert seen and seen[0] == r["symbols"] and seen[0][:8] == cfg["universe"]["symbols"]


# ── Schwab: off by default, never reaches an order capability ───────────────────────────────────────


def test_schwab_switch_defaults_off(cfg):
    assert cfg["schwab"]["enabled"] is False
    assert "28.2.0" in cfg["schwab"]["requires_policy"]

    def boom(*_a, **_k):
        raise AssertionError("fetch/write must not run while the switch is off")
    r = oq.run("schwab", cfg=cfg, now=_t("2026-10-29T21:00:00-04:00"), fetch=boom, write=boom, dry_run=False)
    assert r["status"] == "disabled" and r["written"] == 0


def test_schwab_apply_stops_before_schwab_modules(monkeypatch, capsys):
    import market_quotes_offhours_schwab as ent

    def boom(*_a, **_k):
        raise AssertionError("live path reached while disabled")
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
    assert p["enabled"] is False and p["live_call_made"] is False and p["url_rail_ok"] is True
    assert p["symbols"][:7] == [*cfg["schwab"]["futures"], *cfg["schwab"]["indices"]]


ORDER_NAMES = {"place_order", "submit_order", "cancel_order", "replace_order"}
FORBIDDEN_IMPORTS = ("schwab_transport", "brokers", "alpaca_trade_api", "schwab.client")


def _own_imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_own_modules_import_no_broker_execution_code():
    for path in (LIB, SCHWAB_ENTRY):
        mods = _own_imports(path)
        assert not [m for m in mods if m.startswith(FORBIDDEN_IMPORTS)], (path.name, mods)
        names = {n.id for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Attribute)}
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
    eager_caps = {c for m in eager for c in res.info(m).caps}
    return {"caps": caps, "eager": eager_caps}


def test_capability_scanner_schwab_entry():
    s = _scan("scripts/market_quotes_offhours_schwab.py")
    assert "direct_sender" not in s["caps"]
    # Nothing forbidden loads when the lane starts.
    assert not {"order_placement", "broker_module", "direct_sender"} & s["eager"]
    # Static (lazy) reach to the order surface exists ONLY through the token manager's own module (its live_probe
    # lazily imports schwab_transport) -- never through this lane's code. The function-level walk below proves the
    # token-manager functions this lane calls do not reach it.
    for chain in s["caps"].get("order_placement", []):
        assert chain[1] == "scripts/schwab_token_manager.py", chain


def test_capability_scanner_ingest_lane_unchanged():
    s = _scan("scripts/external_market_data_ingest.py")
    assert set(s["caps"]) == {"db_write", "network_http"}  # same as main before this change


# Function-level reach: the token-manager functions the Schwab lane calls, followed through same-module calls and
# function-local imports. None may import broker execution code or name an order function.
TM = ROOT / "scripts" / "schwab_token_manager.py"
CALLED = {"canonical_token_key", "get_access_token", "is_auth_failure", "record_auth_failure"}


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_called_token_manager_functions_never_reach_order_code():
    tree = ast.parse(TM.read_text())
    fns = _functions(tree)
    assert CALLED <= set(fns), "token manager public read API changed"
    module_level = ast.Module(body=[n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))],
                              type_ignores=[])
    todo, seen, lazy_mods = list(CALLED) + ["_load_broker_secrets_env"], set(), set()
    bodies = [module_level]
    while todo:
        name = todo.pop()
        if name in seen or name not in fns:
            continue
        seen.add(name)
        bodies.append(fns[name])
        for n in ast.walk(fns[name]):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in fns:
                todo.append(n.func.id)
    for body in bodies:
        for n in ast.walk(body):
            if isinstance(n, ast.Import):
                lazy_mods |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                lazy_mods.add(n.module)
            if isinstance(n, ast.Name):
                assert n.id not in ORDER_NAMES
            if isinstance(n, ast.Attribute):
                assert n.attr not in ORDER_NAMES
    assert "live_probe" not in seen  # the one function that imports schwab_transport is not on this path
    assert not [m for m in lazy_mods if m.startswith(FORBIDDEN_IMPORTS)], sorted(lazy_mods)
    # Repo modules imported on that path must not load order code at import time either.
    import audit_lane_transitive_capabilities as cap
    res = cap.Resolver()
    for m in sorted(lazy_mods):
        for p in res.resolve(TM, m, 0, None):
            eager, _ = res.closure(p, eager_only=True)
            assert not any("order_placement" in res.info(e).caps for e in eager), (m, p)


# ── dry runs write nothing ──────────────────────────────────────────────────────────────────────────


def test_alpaca_dry_run_writes_nothing(monkeypatch, capsys):
    import external_market_data_ingest as emdi

    def boom(*_a, **_k):
        raise AssertionError("dry run touched the DB or the writer")
    monkeypatch.setattr(emdi, "_get_conn", boom)
    monkeypatch.setattr(emdi, "write_market_quotes", boom)
    monkeypatch.setattr(emdi, "_alpaca_creds", boom)
    r = emdi.ingest_alpaca_offhours_quotes(dry_run=True, fixture=str(ALPACA_FX), now=_t("2026-10-29T18:00:00-04:00"))
    assert r["status"] == "dry_run" and r["written"] == 0 and len(r["rows"]) == 3
    assert all(row["session"] == "after_hours" for row in r["rows"])
    assert '"status": "dry_run"' in capsys.readouterr().out


def test_alpaca_apply_writes_through_the_one_writer(monkeypatch):
    import external_market_data_ingest as emdi

    calls = []

    class Conn:
        def cursor(self): return object()
        def commit(self): calls.append("commit")
        def close(self): calls.append("close")

    class Rc:
        rows_accepted = 3
        rejected = []

    monkeypatch.setattr(emdi, "_get_conn", lambda: Conn())
    monkeypatch.setattr(emdi, "write_market_quotes",
                        lambda cur, rows, source: calls.append((source, [r["fetched_at"] for r in rows])) or Rc())
    r = emdi.ingest_alpaca_offhours_quotes(fixture=str(ALPACA_FX), now=_t("2026-10-29T18:00:00-04:00"))
    assert r["status"] == "ok" and r["written"] == 3
    assert calls[0][0] == "alpaca" and all(t.tzinfo for t in calls[0][1]) and calls[-1] == "close"


def test_alpaca_outside_window_fetches_nothing(cfg):
    r = oq.run("alpaca", cfg=cfg, now=_t("2026-10-29T12:00:00-04:00"),
               fetch=lambda s: (_ for _ in ()).throw(AssertionError("fetched")), write=None, dry_run=False)
    assert r["status"] == "outside_window"


def test_schwab_dry_run_writes_nothing(monkeypatch, capsys):
    import market_quotes_offhours_schwab as ent

    def boom(*_a, **_k):
        raise AssertionError("dry run reached live code")
    monkeypatch.setattr(ent, "_write", boom)
    monkeypatch.setattr(ent, "live_fetch", boom)
    assert ent.main(["--dry-run", "--fixture", str(SCHWAB_FX), "--now", "2026-10-29T19:50:00-04:00"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "dry_run" and out["written"] == 0 and out["config_enabled"] is False
    assert {r["symbol"] for r in out["rows"]} == {"/ES", "/NQ", "$VIX", "QQQ"}


def test_run_requires_writer_when_not_dry(cfg):
    doc = json.loads(ALPACA_FX.read_text())
    with pytest.raises(ValueError):
        oq.run("alpaca", cfg=cfg, now=_t(doc["now"]), fetch=lambda s: doc["snapshots"], write=None, dry_run=False)
