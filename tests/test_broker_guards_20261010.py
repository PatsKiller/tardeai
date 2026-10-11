"""Broker guards (n8nmat/broker-guards, operator-approved 2026-10-10): GAP 5, GAP 13, GAP 14.

GAP 5  check_data_source_authority.py counted direct reads of projection-owned stores only in the hub
       (scripts/api_v2.py), so scheduled lanes that bypass the data broker were invisible. The lane scan
       counts them, the ceilings recorded on 2026-10-10 may only fall, and every bypass is listed.
GAP 13 finviz_throttle's state lived under the code checkout (``__file__``-relative), so a git worktree or an
       agent run had a private throttle (RC1). It now resolves through production_state_root(), and a code
       checkout is never the state root while the persistent-state marker exists.
GAP 14 CUSIP-like identifiers (12507E201) were sent to Finviz as tickers and cached as symbols. One shared
       validator (lib/provider_ticker_guard.py) runs before every Finviz request path.

Hermetic: tmp roots, fake HOME, stubbed HTTP, no DB, no network, no credential, no .env read.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:  # pragma: no cover - environment dependent; nothing here connects
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must not connect")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)

import check_data_source_authority as gate  # noqa: E402
from lib import provider_ticker_guard as ptg  # noqa: E402

COVERS = [
    "scripts/check_data_source_authority.py",
    "scripts/finviz_throttle.py",
    "scripts/lib/provider_ticker_guard.py",
    "scripts/finviz_enrichment.py",
    "scripts/scalp_catalyst_bulk.py",
    "scripts/external_market_data_ingest.py",
]


# ════════════════════════════════ GAP 5 — lane direct reads ════════════════════════════════

def _auth(writer="scripts/lib/writers/market_quotes_writer.py"):
    return {"domains": [
        {"domain": "quote_price", "store": {"table": "market_quotes"}, "projection": "market_quote", "writer": writer},
        {"domain": "macro", "store": {"table": "fred_economic_series"}, "writer": None},  # no projection: not counted
    ]}


def _tree(tmp_path: Path) -> Path:
    s = tmp_path / "scripts"
    (s / "lib").mkdir(parents=True)
    (s / "brokers").mkdir()
    (s / "lib" / "__init__.py").write_text("")
    (s / "lane_a.py").write_text("from lib.helper import x\nQ = 'SELECT price FROM market_quotes'\n")
    (s / "lib" / "helper.py").write_text("P = 'data/state/ticker_enrichment_cache.json'\n")
    (s / "lane_writer.py").write_text("Q = 'SELECT 1 FROM market_quotes'\n")  # declared writer: not a bypass
    (s / "lane_clean.py").write_text("from lib.data_broker import market_quote\n")
    (s / "lane_retired.py").write_text("Q = 'SELECT * FROM market_quotes'\n")
    (s / "brokers" / "order_pilot.py").write_text("Q = 'SELECT * FROM market_quotes'\n")
    (s / "finviz_enrichment.py").write_text("CACHE = 'data/state/ticker_enrichment_cache.json'\n")  # the writer
    return tmp_path


def _registry():
    return {"lanes": [
        {"lane_id": "a", "state": "ACTIVE", "scheduler": {"kind": "cron", "match": "cd ~/x && python3 scripts/lane_a.py --apply"}},
        {"lane_id": "w", "state": "ACTIVE", "scheduler": {"kind": "cron", "command_text": ".venv/bin/python lane_writer.py"}},
        {"lane_id": "c", "state": "PAUSED", "scheduler": {"kind": "systemd"}, "exec_start": "/usr/bin/python3 .../lane_clean.py"},
        {"lane_id": "r", "state": "RETIRED", "scheduler": {"kind": "cron", "match": "scripts/lane_retired.py"}},
        {"lane_id": "b", "state": "ACTIVE", "scheduler": {"kind": "cron", "match": "scripts/brokers/order_pilot.py"}},
        {"lane_id": "f", "state": "ACTIVE", "scheduler": {"kind": "cron", "match": "scripts/finviz_enrichment.py"}},
        {"lane_id": "x", "state": "ACTIVE", "scheduler": {"kind": "cron", "match": "linux_launchers/run_other.sh"}},
    ]}


def test_lane_scripts_resolves_tokens_and_skips_retired_and_broker_files(tmp_path):
    root = _tree(tmp_path)
    entry, unresolved = gate.lane_scripts(_registry(), root)
    assert set(entry) == {"scripts/lane_a.py", "scripts/lane_writer.py", "scripts/lane_clean.py",
                          "scripts/finviz_enrichment.py"}
    assert "scripts/lane_retired.py" not in entry          # RETIRED lanes are not scheduled
    assert "scripts/brokers/order_pilot.py" not in entry   # execution file set is never opened (§0 rule 2)
    assert "linux_launchers/run_other.sh" in unresolved    # said, not silently dropped


def test_lane_scan_counts_bypasses_including_imported_lib_modules(tmp_path):
    root = _tree(tmp_path)
    auth = _auth(writer="scripts/lane_writer.py")
    out = gate.lane_scan(auth, _registry(), root)
    assert out["direct_reads"] == {"market_quotes": 1}           # lane_a only; the writer reading its own table is not
    assert out["raw_cache_reads"] == {"ticker_enrichment_cache.json": 1}  # lib/helper.py via lane_a; writer excluded
    by = {(b["file"], b["store"]): b for b in out["bypasses"]}
    assert by[("scripts/lane_a.py", "market_quotes")]["read_path"] == "market_quote"
    helper = by[("scripts/lib/helper.py", "ticker_enrichment_cache.json")]
    assert helper["via"] == ["scripts/lane_a.py"] and helper["lanes"] == ["a"]
    assert helper["read_path"] == "finviz_enrichment_snapshot"
    assert out["scanned"]["entrypoints"] == 4 and out["scanned"]["lib_modules"] == 1


def test_compare_lane_baseline_rise_absent_key_and_no_baseline():
    byp = [{"file": "scripts/a.py", "store": "market_quotes"}, {"file": "scripts/b.py", "store": "market_quotes"}]
    f = gate.compare_lane_baseline("LANE_DIRECT_READ_ROSE", {"market_quotes": 2}, {"market_quotes": 1}, byp)
    assert f and f[0]["now"] == 2 and f[0]["baseline"] == 1 and f[0]["files"] == ["scripts/a.py", "scripts/b.py"]
    assert gate.compare_lane_baseline("X", {"market_quotes": 1}, {"market_quotes": 1}, byp) == []
    assert gate.compare_lane_baseline("X", {"news_articles": 1}, {}, byp)[0]["baseline"] == 0  # absent key = 0
    assert gate.compare_lane_baseline("X", {"market_quotes": 9}, None, byp) == []              # older baseline file


def test_repo_lane_counts_sit_at_or_under_the_recorded_ceilings():
    baseline = json.loads(gate.BASELINE.read_text())
    assert baseline["lane_scan"]["measured_on"] == "2026-10-10"
    auth = json.loads(gate.AUTHORITY.read_text())
    out = gate.lane_scan(auth, json.loads(gate.LANE_REGISTRY.read_text()))
    for key, cur in (("lane_direct_reads", out["direct_reads"]), ("lane_raw_cache_reads", out["raw_cache_reads"])):
        ceil = baseline[key]
        # a store without a recorded ceiling has a ceiling of 0 (a newly projection-owned table must record its debt)
        rose = {k: (v, ceil.get(k, 0)) for k, v in cur.items() if v > int(ceil.get(k, 0))}
        assert not rose, f"{key} rose above the 2026-10-10 ceiling: {rose}"
    # existing ceilings are untouched by GAP 5 (they may only fall; this branch raised none)
    assert baseline["direct_reads"]["market_quotes"] == 13 and baseline["writers"]["news_articles"] == 1
    # pre-recorded for PR #1678 (social_posts becomes projection-owned there); not counted on main
    assert baseline["lane_direct_reads"]["social_posts"] == 7


def test_gate_json_reports_every_bypass_and_no_lane_finding():
    env = {**os.environ, "TRADE_AI_CI": "1"}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_data_source_authority.py"), "--json"],
                       capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=300)
    rep = json.loads(r.stdout)
    assert not [f for f in rep["findings"] if f["check"] == "LANE_DIRECT_READ_ROSE"]
    assert rep["lane_bypasses"] and all({"file", "store", "lanes", "read_path"} <= set(b) for b in rep["lane_bypasses"])
    n_table = sum(1 for b in rep["lane_bypasses"] if b["kind"] == "table")
    assert n_table == sum(rep["lane_direct_reads"].values())


def test_write_baseline_never_raises_a_lane_ceiling(tmp_path, monkeypatch):
    base = tmp_path / "baseline.json"
    prior = json.loads(gate.BASELINE.read_text())
    prior["lane_direct_reads"] = {"market_quotes": 1}
    prior["lane_raw_cache_reads"] = {"ticker_enrichment_cache.json": 0}
    base.write_text(json.dumps(prior))
    monkeypatch.setattr(gate, "BASELINE", base)
    monkeypatch.setattr(gate, "lane_scan", lambda auth, reg, root=None: {
        "direct_reads": {"market_quotes": 5, "news_articles": 2},
        "raw_cache_reads": {"ticker_enrichment_cache.json": 3}, "bypasses": [],
        "scanned": {"entrypoints": 0, "lib_modules": 0, "unresolved": []}})
    monkeypatch.setattr(sys, "argv", ["check_data_source_authority.py", "--write-baseline", "--json"])
    gate.main()
    written = json.loads(base.read_text())
    assert written["lane_direct_reads"] == {"market_quotes": 1, "news_articles": 2}  # kept at 1; new key starts at now
    assert written["lane_raw_cache_reads"] == {"ticker_enrichment_cache.json": 0}
    assert written["lane_scan"] == prior["lane_scan"]


def test_lane_exclusions_cover_the_broker_execution_file_set():
    rules = {r["id"]: r for r in json.loads((ROOT / "config" / "agents_guard_hook_rules.json").read_text())["rules"]}
    paths = [g.replace("**/", "").replace("/**", "/") for g in rules["broker.execution_code_edit"]["path_globs"]]
    paths += rules["broker.order_invoke"]["execution_entrypoints"]
    for p in paths:
        assert gate._lane_excluded(p) or gate._lane_excluded(p + "x.py"), p


# ════════════════════════════════ GAP 13 — throttle state root ════════════════════════════════

def _throttle_path(cwd: Path, home: Path, **env) -> str:
    """Import finviz_throttle in a fresh interpreter (module-level _STATE) and print where it resolved."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("TRADEAI_")}
    e.update(HOME=str(home), TRADE_AI_CI="1", **env)
    code = (f"import sys; sys.path.insert(0, {str(ROOT / 'scripts')!r}); import finviz_throttle as f; "
            "print(f._STATE); print(f._LOCK)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(cwd), env=e, timeout=60)
    assert r.returncode == 0, r.stderr
    state, lock = r.stdout.split()
    assert lock == state[: -len(".json")] + ".lock"
    return state


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    ps = home / "trade-ai-releases" / "persistent-state"
    ps.mkdir(parents=True)
    (ps / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    worktree = tmp_path / "wt"
    (worktree / "scripts").mkdir(parents=True)
    release = home / "trade-ai-releases" / "portfolio-server" / "rel-1"
    (release / "scripts").mkdir(parents=True)
    return home, ps, worktree, release


def test_throttle_is_shared_across_cron_cwd_executor_and_worktree(fake_home, tmp_path):
    home, ps, worktree, release = fake_home
    want = str(ps / "data" / "state" / "finviz_throttle.json")
    assert _throttle_path(ROOT, home) == want                                  # cron: cwd = a code checkout
    assert _throttle_path(tmp_path, home) == want                              # any other cwd
    assert _throttle_path(worktree, home, TRADEAI_ROOT=str(worktree)) == want  # agent worktree as TRADEAI_ROOT
    assert _throttle_path(release, home, TRADEAI_ROOT=str(release)) == want    # executor code_root = a release
    assert not (ps / "data").exists()                                          # resolving writes nothing


def test_throttle_honours_an_explicit_state_root(fake_home, tmp_path):
    home, _ps, _wt, _rel = fake_home
    explicit = tmp_path / "state-root"
    assert _throttle_path(ROOT, home, TRADEAI_STATE_ROOT=str(explicit)) == str(
        explicit / "data" / "state" / "finviz_throttle.json")


def test_throttle_without_marker_falls_back_to_production_state_root(tmp_path):
    home = tmp_path / "bare-home"
    home.mkdir()
    # no marker, no CURRENT: production_state_root() falls back to the repo; that is all a bare CI box has
    assert _throttle_path(tmp_path, home) == str(ROOT / "data" / "state" / "finviz_throttle.json")


def test_throttle_status_names_its_state_path(monkeypatch, tmp_path):
    import finviz_throttle

    monkeypatch.setattr(finviz_throttle, "_STATE", tmp_path / "t.json")
    assert finviz_throttle.status()["state_path"] == str(tmp_path / "t.json")


# ════════════════════════════════ GAP 14 — provider ticker guard ════════════════════════════════

@pytest.mark.parametrize("sym,profile,ok,reason", [
    ("AAPL", "finviz", True, "ok"), (" brk-b ", "finviz", True, "ok"), ("BF.B", "finviz", True, "ok"),
    ("AMAGX", "finviz", True, "ok"), ("T", "finviz", True, "ok"),
    ("12507E201", "finviz", False, "cusip_like"),   # the identifier found in watchlist_items
    ("037833100", "finviz", False, "cusip_like"), ("G1151C101", "finviz", False, "cusip_like"),
    ("US0378331005", "finviz", False, "isin_like"), ("", "finviz", False, "empty"), (None, "finviz", False, "empty"),
    ("ABCDEF", "finviz", False, "not_ticker_shape"), ("^VIX", "finviz", False, "not_ticker_shape"),
    ("BTC-USD", "finviz", False, "not_ticker_shape"),
    ("^VIX", "quote", True, "ok"), ("BTC-USD", "quote", True, "ok"), ("12507E201", "quote", False, "cusip_like"),
])
def test_classify(sym, profile, ok, reason):
    assert ptg.classify(sym, profile) == (ok, reason)


def test_partition_normalizes_dedups_and_names_rejects():
    ok, rej = ptg.partition(["aapl", "12507E201", "AAPL", " msft"])
    assert ok == ["AAPL", "MSFT"] and rej == [{"symbol": "12507E201", "reason": "cusip_like"}]
    with pytest.raises(ValueError):
        ptg.classify("AAPL", "nope")


@pytest.fixture
def fe(monkeypatch, tmp_path):
    import finviz_enrichment as fe

    calls: list[str] = []

    class _Resp:
        ok, status_code, headers = True, 200, {}
        text = '"Ticker","Price"\n"AAPL","1"\n'

    monkeypatch.setattr(fe, "_load_env", lambda root: None)  # never loads a secret render or .env
    monkeypatch.setenv("FINVIZ_API_TOKEN", "test-token-not-real")
    monkeypatch.setattr(fe.requests, "get", lambda url, **k: calls.append(url) or _Resp())
    monkeypatch.setattr(fe.time, "sleep", lambda s: None)
    monkeypatch.setitem(sys.modules, "finviz_throttle",
                        types.SimpleNamespace(acquire=lambda *a, **k: 0, cooldown=lambda *a, **k: None))
    return fe, calls, tmp_path


def test_fetch_view_never_sends_a_cusip(fe):
    mod, calls, root = fe
    mod._fetch_view(["AAPL", "12507E201"], 111, root, col_map={"Ticker": "ticker", "Price": "price"})
    assert len(calls) == 1 and "t=AAPL&" in calls[0] and "12507E201" not in calls[0]
    calls.clear()
    assert mod._fetch_view(["12507E201"], 111, root) == {} and calls == []  # nothing valid -> no request


def test_enrich_tickers_neither_requests_nor_caches_a_cusip(fe, monkeypatch):
    mod, calls, root = fe
    seen: list[list[str]] = []
    saved: dict = {}
    monkeypatch.setattr(mod, "_fetch_view", lambda tickers, view, r, **k: seen.append(list(tickers)) or {})
    monkeypatch.setattr(mod, "save_cache", lambda cache, r: saved.update(cache))
    out = mod.enrich_tickers(["AAPL", "12507E201"], project_root=str(root), views=[111])
    assert seen == [["AAPL"]] and "12507E201" not in saved and "AAPL" in saved
    assert out["12507E201"] == {"symbol": "12507E201", "rejected_non_ticker": "cusip_like"}
    assert mod._RUN_STATS["rejected_non_ticker"] == 1 and mod._RUN_STATS["symbols"] == 2


def test_scalp_catalyst_bulk_finviz_chunk_drops_cusips(monkeypatch):
    import scalp_catalyst_bulk as scb

    urls: list[str] = []

    class _R:
        status_code, ok, text = 200, True, ""

    monkeypatch.setenv("FINVIZ_API_TOKEN", "test-token-not-real")
    cfg = {"finviz_timezone": "America/New_York", "finviz_per_symbol": 3, "finviz_batch_size": 20,
           "finviz_news_url": "https://elite.finviz.com/news_export.ashx", "finviz_news_view": 3}
    stats = {"finviz_calls": 0}
    scb._finviz_articles(["AAPL", "12507E201"], cfg, lambda url, **k: urls.append(url) or _R(), stats)
    assert len(urls) == 1 and "12507E201" not in urls[0] and stats["finviz_refused_non_ticker"] == 1


def test_finviz_quote_fallback_refuses_a_cusip(monkeypatch):
    import external_market_data_ingest as emdi

    monkeypatch.setattr(emdi, "finviz_get", lambda *a, **k: pytest.fail("a CUSIP reached Finviz"))
    assert emdi._finviz_quote("12507E201") == {}


def _func_src(rel: str, name: str) -> str:
    src = (ROOT / rel).read_text()
    node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, node)


@pytest.mark.parametrize("rel,func,guard,request_marker", [
    # pinned statically: importing these modules reads PROJECT_ROOT/.env or a secret render at import time
    ("scripts/symbol_enrichment.py", "fetch_finviz_deep", "_ticker_classify(symbol", "resolve_secret"),
    ("scripts/finviz_news.py", "fetch_finviz_news", "_ticker_classify(ticker", "requests.get"),
    ("scripts/portfolio_technical.py", "_finviz_cookie_batch", "_ticker_partition(tickers", "quote.ashx?t={ticker}"),
    ("scripts/market_context.py", "_fetch_finviz_quotes", "_ticker_partition(stock_symbols", "export.ashx"),
    ("scripts/social_scalp_scanner.py", "fetch_finviz_base", "_ticker_partition(symbols", "export?v=111"),
])
def test_guard_precedes_the_finviz_request(rel, func, guard, request_marker):
    body = _func_src(rel, func)
    assert guard in body and request_marker in body
    assert body.index(guard) < body.index(request_marker), f"{rel}:{func} requests Finviz before the ticker guard"
