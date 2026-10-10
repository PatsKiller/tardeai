"""Refactor wave 3 (cron -> n8n, 2026-10-10), bucket X2: Aegis ingest + Hermes discovery lanes.

- aegis_social_sentiment / aegis_transcript_discovery / aegis_nightly_ingestion (cron L289 L291 L308): new cli()
  with --dry-run (READ ONLY db_adapter session, no external fetch, no _db_write, no receipt); real runs leave a
  LaneRunReceipt@v1; exit 1 when Postgres is unavailable or every step/write failed, not on one soft failure.
  main() still returns a dict (aegis_overnight.py calls it).
- hermes_tag_lift / analyst_signal / industry_novelty discovery CLIs (L684-L686): existing --dry-run cannot reach
  the lib writers; real --run leaves a receipt; a crash writes a failed receipt and re-raises.
- hermes_discovery_scorecard (L832): --dry-run writes neither JSON file; DB unavailable -> exit 1, no all-zero card.
- siem_to_hermes_backlog (L835): --dry-run wins over --apply; preview dedupe runs on a READ ONLY connection.
Hermetic: fake db_adapter / connections / modules, TRADEAI_STATE_ROOT = tmp. No DB, network or LLM.
"""

from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the real
# driver is absent, so the dry-run safety tests still run in CI instead of being skipped.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import aegis_nightly_ingestion as ani  # noqa: E402
import aegis_social_sentiment as ass  # noqa: E402
import aegis_transcript_discovery as atd  # noqa: E402
import hermes_analyst_signal_discovery as hasd  # noqa: E402
import hermes_discovery_scorecard as hds  # noqa: E402
import hermes_industry_novelty_discovery as hind  # noqa: E402
import hermes_tag_lift_discovery as htl  # noqa: E402
import siem_to_hermes_backlog as s2h  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402
from lib.hermes_discovery import analyst_signals, feedback, inbox, industry_novelty, tag_lift  # noqa: E402

_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "TRUNCATE")


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._one = None

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.conn.sql.append(norm)
        self._one = self.conn.one_for(norm, params)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, filed=()):
        self.filed = set(filed)
        self.sql, self.commits, self.readonly, self.closed = [], 0, None, False

    def one_for(self, sql, params):
        if "FROM hermes_research_intelligence" in sql and params:
            return (1,) if any(dk in params[1] for dk in self.filed) else None
        return None

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
    raise AssertionError("dry run reached a write / external fetch / receipt path")


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


@pytest.fixture
def fake_db(monkeypatch):
    """A fake db_adapter module: _get_conn returns one FakeConn; _execute answers SELECT 1."""
    conn = FakeConn()
    mod = types.ModuleType("db_adapter")
    mod.USE_DB = True
    mod._get_conn = lambda: conn
    mod._execute = lambda sql, params=None, fetch=None: {"ok": 1} if "SELECT 1" in sql else []
    monkeypatch.setitem(sys.modules, "db_adapter", mod)
    return conn


def _receipt_file(state, lane):
    return state / "data" / "runtime" / f"{lane}_last.json"


def _receipt(state, lane):
    return json.loads(_receipt_file(state, lane).read_text())


def _seed_ok_receipt(state, lane):
    p = _receipt_file(state, lane)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": llr.SCHEMA, "lane_id": lane, "ok_at": "2026-10-01T00:00:00+00:00"}))


def _dry_line(text):
    line = next(ln for ln in text.splitlines() if ln.startswith("DRY-RUN "))
    return json.loads(line[len("DRY-RUN ") :])


UNIVERSE = [{"symbol": "AAA", "reasons": ["holding"]}, {"symbol": "BBB", "reasons": ["watchlist"]}]


def _aegis_env(monkeypatch, mod, db_ok=True):
    monkeypatch.setattr(ani, "resolve_universe", lambda: [dict(u) for u in UNIVERSE])
    monkeypatch.setattr(
        mod,
        "_db_query",
        lambda sql, params=None, fetch="all": ({"ok": 1} if db_ok else None) if "SELECT 1" in sql else [],
    )


# ── aegis_nightly_ingestion ──────────────────────────────────────────────────────────────────────────


def test_nightly_dry_run_no_write_no_yahoo_no_receipt(monkeypatch, capsys, fake_db, _state):
    _aegis_env(monkeypatch, ani)
    monkeypatch.setattr(ani, "fetch_finviz_batch", lambda syms: {"AAA": {"price": 10.0, "rsi": 50, "_source": "f"}})
    monkeypatch.setattr(ani, "_db_write", _boom)
    monkeypatch.setattr(ani, "fetch_yahoo_batch", _boom)
    monkeypatch.setattr(ani.requests, "get", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert ani.cli(["--dry-run"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["lane_id"] == "aegis-nightly-ingestion"
    assert rep["summary"]["would_write_rows"] == 2
    assert rep["summary"]["would_fetch_yahoo"] == 1  # BBB has no Finviz data
    assert rep["summary"]["readonly_session"] is True and fake_db.readonly is True
    assert not _receipt_file(_state, "aegis-nightly-ingestion").exists()


def test_nightly_dry_run_report_varies_with_state(monkeypatch, capsys, fake_db):
    _aegis_env(monkeypatch, ani)
    monkeypatch.setattr(ani, "fetch_finviz_batch", lambda syms: {})
    monkeypatch.setattr(ani, "_db_write", _boom)
    ani.cli(["--dry-run"])
    assert _dry_line(capsys.readouterr().out)["summary"]["would_fetch_yahoo"] == 2
    monkeypatch.setattr(ani, "resolve_universe", lambda: [])
    ani.cli(["--dry-run"])
    assert _dry_line(capsys.readouterr().out)["summary"]["would_write_rows"] == 0


def test_nightly_real_run_writes_ok_receipt(monkeypatch, fake_db, _state):
    _aegis_env(monkeypatch, ani)
    monkeypatch.setattr(ani, "fetch_finviz_batch", lambda syms: {})
    monkeypatch.setattr(ani, "fetch_yahoo_batch", lambda syms, fv: {})
    writes = []
    monkeypatch.setattr(ani, "_db_write", lambda sql, params=None: writes.append(sql) or True)
    assert ani.cli([]) == 0
    assert len(writes) == 2 and "INSERT INTO aegis_symbol_snapshot_nightly" in writes[0]
    r = _receipt(_state, "aegis-nightly-ingestion")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["written"] == 2


def test_nightly_all_writes_failed_exit_1_keeps_previous_ok_at(monkeypatch, fake_db, _state):
    _seed_ok_receipt(_state, "aegis-nightly-ingestion")
    _aegis_env(monkeypatch, ani)
    monkeypatch.setattr(ani, "fetch_finviz_batch", lambda syms: {})
    monkeypatch.setattr(ani, "fetch_yahoo_batch", lambda syms, fv: {})
    monkeypatch.setattr(ani, "_db_write", lambda sql, params=None: False)
    assert ani.cli([]) == 1
    r = _receipt(_state, "aegis-nightly-ingestion")
    assert r["status"] == "failed" and r["exit"] == 1 and r["ok_at"] == "2026-10-01T00:00:00+00:00"


def test_nightly_one_failed_write_is_soft(monkeypatch, fake_db, _state):
    _aegis_env(monkeypatch, ani)
    monkeypatch.setattr(ani, "fetch_finviz_batch", lambda syms: {})
    monkeypatch.setattr(ani, "fetch_yahoo_batch", lambda syms, fv: {})
    results = iter([True, False])
    monkeypatch.setattr(ani, "_db_write", lambda sql, params=None: next(results))
    assert ani.cli([]) == 0
    assert _receipt(_state, "aegis-nightly-ingestion")["summary"]["written"] == 1


def test_nightly_db_unavailable_exit_1(monkeypatch, fake_db, _state):
    _aegis_env(monkeypatch, ani, db_ok=False)
    monkeypatch.setattr(ani, "_db_write", _boom)
    assert ani.cli([]) == 1
    assert _receipt(_state, "aegis-nightly-ingestion")["error"] == "db_unavailable"
    assert ani.cli(["--dry-run"]) == 1  # a dry run that cannot read is not a pass


def test_nightly_crash_writes_failed_receipt_and_reraises(monkeypatch, fake_db, _state):
    _seed_ok_receipt(_state, "aegis-nightly-ingestion")
    _aegis_env(monkeypatch, ani)

    def crash(syms):
        raise ValueError("cache broken")

    monkeypatch.setattr(ani, "fetch_finviz_batch", crash)
    with pytest.raises(ValueError):
        ani.cli([])
    r = _receipt(_state, "aegis-nightly-ingestion")
    assert r["status"] == "failed" and r["error"] == "ValueError" and r["ok_at"] == "2026-10-01T00:00:00+00:00"


def test_nightly_main_still_returns_dict_for_aegis_overnight(monkeypatch, fake_db):
    _aegis_env(monkeypatch, ani)
    monkeypatch.setattr(ani, "fetch_finviz_batch", lambda syms: {})
    monkeypatch.setattr(ani, "fetch_yahoo_batch", lambda syms, fv: {})
    monkeypatch.setattr(ani, "_db_write", lambda sql, params=None: True)
    out = ani.main()
    assert isinstance(out, dict) and out["written"] == 2 and "error" not in out


# ── aegis_social_sentiment ───────────────────────────────────────────────────────────────────────────


def test_social_dry_run_no_fetch_no_write_no_receipt(monkeypatch, capsys, fake_db, _state):
    _aegis_env(monkeypatch, ass)
    for name in ("fetch_reddit_mentions", "fetch_stocktwits_mentions", "fetch_brave_social", "persist_sentiment"):
        monkeypatch.setattr(ass, name, _boom)
    monkeypatch.setattr(ass, "_db_write", _boom)
    monkeypatch.setattr(ass.requests, "get", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert ass.cli(["--dry-run"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["lane_id"] == "aegis-social-sentiment"
    assert rep["summary"]["would_fetch_stocktwits_streams"] == 2
    assert rep["summary"]["would_fetch_reddit_pages"] == len(ass.SUBREDDITS)
    assert fake_db.readonly is True
    assert not _receipt_file(_state, "aegis-social-sentiment").exists()


class _Resp:
    def __init__(self, code, payload):
        self.status_code, self._p = code, payload

    def json(self):
        return self._p


def _social_http(monkeypatch, reddit_code=403, st_code=200):
    def get(url, **k):
        if "reddit" in url:
            return _Resp(reddit_code, {})
        msg = {"body": "AAA to the moon", "entities": {"sentiment": {"basic": "Bullish"}}, "likes": {"total": 3}}
        return _Resp(st_code, {"messages": [msg]})

    monkeypatch.setattr(ass.requests, "get", get)
    monkeypatch.setattr(ass.time, "sleep", lambda s: None)


def test_social_real_run_writes_ok_receipt(monkeypatch, fake_db, _state):
    _aegis_env(monkeypatch, ass)
    _social_http(monkeypatch)
    monkeypatch.setattr(ass, "_db_write", lambda sql, params=None: True)
    assert ass.cli([]) == 0  # reddit 403 on every subreddit is a soft failure: StockTwits answered
    r = _receipt(_state, "aegis-social-sentiment")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["written"] == 2


def test_social_no_source_fetched_exit_1(monkeypatch, fake_db, _state):
    _seed_ok_receipt(_state, "aegis-social-sentiment")
    _aegis_env(monkeypatch, ass)
    _social_http(monkeypatch, reddit_code=403, st_code=429)
    monkeypatch.setattr(ass, "_db_write", _boom)
    assert ass.cli([]) == 1
    r = _receipt(_state, "aegis-social-sentiment")
    assert r["error"] == "no_source_fetched" and r["ok_at"] == "2026-10-01T00:00:00+00:00"


def test_social_all_writes_failed_exit_1(monkeypatch, fake_db, _state):
    _aegis_env(monkeypatch, ass)
    _social_http(monkeypatch)
    monkeypatch.setattr(ass, "_db_write", lambda sql, params=None: False)
    assert ass.cli([]) == 1
    assert _receipt(_state, "aegis-social-sentiment")["error"] == "all_writes_failed"


def test_social_crash_failed_receipt(monkeypatch, fake_db, _state):
    _aegis_env(monkeypatch, ass)

    def crash(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(ass, "fetch_reddit_mentions", crash)
    with pytest.raises(RuntimeError):
        ass.cli([])
    assert _receipt(_state, "aegis-social-sentiment")["status"] == "failed"


# ── aegis_transcript_discovery ───────────────────────────────────────────────────────────────────────


def _transcript_rows(monkeypatch):
    monkeypatch.setattr(
        atd,
        "fetch_db_youtube_transcripts",
        lambda symbols, max_per_symbol=2, lookback_days=14: [
            {"symbol": "AAA", "source_family": "youtube", "title": "AAA call", "summary": "s"}
        ],
    )
    monkeypatch.setattr(
        atd,
        "enrich_from_article_index",
        lambda symbols: [{"symbol": "BBB", "source_family": "article_index", "title": "t"}],
    )


def test_transcript_dry_run_db_reads_only(monkeypatch, capsys, fake_db, _state):
    _aegis_env(monkeypatch, atd)
    _transcript_rows(monkeypatch)
    monkeypatch.setenv("AEGIS_BRAVE_ENABLED", "1")  # even when Brave is on, the dry run must not query it
    monkeypatch.setattr(atd, "BRAVE_KEY", "fake-key")
    for name in (
        "persist_transcripts",
        "persist_discovery",
        "_db_write",
        "fetch_brave_discovery",
        "_governed_brave_web",
    ):
        monkeypatch.setattr(atd, name, _boom)
    monkeypatch.setattr(atd.requests, "get", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert atd.cli(["--dry-run"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["would_write_transcripts"] == 2
    assert rep["summary"]["would_query_brave"] > 0
    assert fake_db.readonly is True
    assert not _receipt_file(_state, "aegis-transcript-discovery").exists()


def test_transcript_real_run_receipt_and_all_failed(monkeypatch, fake_db, _state):
    _aegis_env(monkeypatch, atd)
    _transcript_rows(monkeypatch)
    monkeypatch.delenv("AEGIS_BRAVE_ENABLED", raising=False)
    monkeypatch.setattr(atd, "_db_write", lambda sql, params=None: True)
    assert atd.cli([]) == 0
    r = _receipt(_state, "aegis-transcript-discovery")
    assert r["status"] == "ok" and r["summary"]["transcripts"] == 2
    ok_at = r["ok_at"]
    monkeypatch.setattr(atd, "_db_write", lambda sql, params=None: False)
    assert atd.cli([]) == 1
    r = _receipt(_state, "aegis-transcript-discovery")
    assert r["error"] == "all_writes_failed" and r["ok_at"] == ok_at


def test_transcript_zero_records_is_exit_0(monkeypatch, fake_db, _state):
    _aegis_env(monkeypatch, atd)
    monkeypatch.delenv("AEGIS_BRAVE_ENABLED", raising=False)
    monkeypatch.setattr(atd, "_db_write", _boom)
    assert atd.cli([]) == 0
    assert _receipt(_state, "aegis-transcript-discovery")["summary"]["to_write"] == 0


@pytest.mark.parametrize(
    "mod,forbidden",
    [
        (ani, ("fetch_yahoo_batch(", "merge_and_persist(")),
        (ass, ("fetch_reddit_mentions(", "fetch_stocktwits_mentions(", "fetch_brave_social(", "persist_sentiment(")),
        (atd, ("persist_transcripts(", "fetch_brave_discovery(", "persist_discovery(")),
    ],
)
def test_aegis_dry_branch_returns_before_fetch_and_write_in_source(mod, forbidden):
    src = inspect.getsource(mod.main)
    dry = src.index("if dry_run:")
    ret = src.index("return {**summary", dry)
    for f in forbidden:
        assert ret < src.index(f), f
    assert src.index("_enforce_readonly_db() if dry_run") < src.index("_db_available()")
    cli = inspect.getsource(mod.cli)
    assert cli.index("if args.dry_run:") < cli.index("write_lane_receipt")


# ── hermes discovery CLIs (L684-L686) ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cli_mod,lib_mod,lane",
    [
        (htl, tag_lift, "hermes-tag-lift-discovery"),
        (hasd, analyst_signals, "hermes-analyst-signal-discovery"),
        (hind, industry_novelty, "hermes-industry-novelty-discovery"),
    ],
)
def test_hermes_cli_dry_run_report_no_receipt(monkeypatch, capsys, fake_db, _state, cli_mod, lib_mod, lane):
    seen = {}

    def fake_run(**k):
        seen.update(k)
        return {"dry_run": True, "would_upsert": 3, "tags_analyzed": 4, "scanned_symbols": 5, "scanned_sectors": 6}

    monkeypatch.setattr(lib_mod, "run_discovery", fake_run)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    monkeypatch.setattr(sys, "argv", ["x", "--run", "--json", "--dry-run"])
    assert cli_mod.main() == 0
    assert seen["dry_run"] is True
    out = capsys.readouterr()
    json.loads(out.out)  # stdout stays pure JSON for the --json consumer
    rep = _dry_line(out.err)
    assert rep["lane_id"] == lane and rep["summary"]["readonly_session"] is True
    assert fake_db.readonly is True
    assert not _receipt_file(_state, lane).exists()


@pytest.mark.parametrize(
    "cli_mod,lib_mod,lane",
    [
        (htl, tag_lift, "hermes-tag-lift-discovery"),
        (hasd, analyst_signals, "hermes-analyst-signal-discovery"),
        (hind, industry_novelty, "hermes-industry-novelty-discovery"),
    ],
)
def test_hermes_cli_real_run_receipt_and_crash(monkeypatch, _state, cli_mod, lib_mod, lane):
    monkeypatch.setattr(lib_mod, "run_discovery", lambda **k: {"dry_run": False, "upserted": 2, "tags_analyzed": 1})
    monkeypatch.setattr(sys, "argv", ["x", "--run", "--json"])
    assert cli_mod.main() == 0
    r = _receipt(_state, lane)
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["upserted"] == 2
    ok_at = r["ok_at"]

    def crash(**k):
        raise ValueError("label normalizes to empty key: A")

    monkeypatch.setattr(lib_mod, "run_discovery", crash)
    with pytest.raises(ValueError):
        cli_mod.main()
    r = _receipt(_state, lane)
    assert r["status"] == "failed" and r["error"] == "ValueError" and r["ok_at"] == ok_at


def test_hermes_cli_usage_exit_2(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x"])
    for m in (htl, hasd, hind):
        assert m.main() == 2


def test_tag_lift_all_deltas_failed_exit_1(monkeypatch, _state):
    rep = {"weight_deltas_planned": 2, "weight_deltas_applied": 0, "upserted": 0}
    monkeypatch.setattr(tag_lift, "run_discovery", lambda **k: dict(rep))
    monkeypatch.setattr(sys, "argv", ["x", "--run", "--json"])
    assert htl.main() == 1
    assert _receipt(_state, "hermes-tag-lift-discovery")["error"] == "all_weight_deltas_failed"
    rep["weight_deltas_applied"] = 1  # one delta landing = soft failure, exit 0
    assert htl.main() == 0


def _payload(ctype="TREND_CANDIDATE"):
    return {
        "candidate_type": ctype,
        "label": "Uranium miners",
        "summary": "s",
        "signals": {},
        "meta": {
            "direction": "up",
            "recurrence_count": 4,
            "tag_lift_json": {"useful_outcome_count": 6, "lift_ratio": 1.5},
        },
    }


def test_tag_lift_lib_dry_run_cannot_reach_writers(monkeypatch):
    monkeypatch.setattr(tag_lift, "_execute", lambda *a, **k: [])
    monkeypatch.setattr(
        tag_lift,
        "plan_actions",
        lambda *a, **k: {
            "weight_deltas": [{"kind": "tag", "trend_key": "x", "delta": 0.1, "reason": "r"}],
            "candidates": [_payload()],
        },
    )
    monkeypatch.setattr(feedback, "apply_weight_delta", _boom)
    monkeypatch.setattr(inbox, "upsert_candidate", _boom)
    rep = tag_lift.run_discovery(dry_run=True)
    assert rep["weight_deltas_planned"] == 1 and rep["candidates_planned"] == 1 and rep["upserted"] == 0


def test_analyst_lib_dry_run_cannot_reach_upsert(monkeypatch):
    monkeypatch.setattr(analyst_signals, "_execute", lambda *a, **k: [])
    monkeypatch.setattr(analyst_signals, "build_ticker_payloads", lambda *a, **k: [_payload("TICKER_CANDIDATE")])
    monkeypatch.setattr(analyst_signals, "build_sector_payloads", lambda *a, **k: [_payload()])
    monkeypatch.setattr(inbox, "upsert_candidate", _boom)
    rep = analyst_signals.run_discovery(dry_run=True)
    assert rep["effective_dry_run"] is True and rep["would_upsert"] == 2 and rep["upserted"] == 0


def test_novelty_lib_dry_run_cannot_reach_upsert(monkeypatch):
    monkeypatch.setattr(industry_novelty, "_execute", lambda *a, **k: [])
    monkeypatch.setattr(industry_novelty, "build_payloads", lambda *a, **k: [_payload("GAP_CANDIDATE")])
    monkeypatch.setattr(inbox, "upsert_candidate", _boom)
    rep = industry_novelty.run_discovery(dry_run=True)
    assert rep["effective_dry_run"] is True and rep["would_upsert"] == 1 and rep["upserted"] == 0


@pytest.mark.parametrize("cli_mod", [htl, hasd, hind])
def test_hermes_cli_dry_branch_before_receipt_in_source(cli_mod):
    src = inspect.getsource(cli_mod.main)
    dry = src.index("if args.dry_run:")
    assert dry < src.index("run_discovery(dry_run=True") < src.index("run_discovery(dry_run=False")
    assert src.index("run_discovery(dry_run=True") < src.index("write_lane_receipt")


# ── hermes_discovery_scorecard (L832) ────────────────────────────────────────────────────────────────

CARD = {"totals": {"candidates": 7}, "intake": {"new_candidates_7d": 2}, "do_no_harm": {"recommendation": "steady"}}


def _scorecard_env(monkeypatch, tmp_path):
    monkeypatch.setattr(hds, "SCORECARD_PATH", tmp_path / "rt" / "hermes_discovery_scorecard.json")
    monkeypatch.setattr(hds, "OUTCOME_FEED_PATH", tmp_path / "rt" / "hermes_discovery_outcome_feed.json")
    monkeypatch.setattr(hds, "build_scorecard", lambda: dict(CARD))


def test_scorecard_dry_run_writes_neither_file(monkeypatch, capsys, fake_db, tmp_path, _state):
    _scorecard_env(monkeypatch, tmp_path)
    monkeypatch.setattr(hds, "_atomic_write", _boom)
    monkeypatch.setattr(hds, "write_outcome_feed", _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert hds.main(["--dry-run"]) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"]["candidates_total"] == 7 and rep["summary"]["recommendation"] == "steady"
    assert str(hds.SCORECARD_PATH) in rep["would_write"]
    assert fake_db.readonly is True
    assert not (tmp_path / "rt").exists()
    assert not _receipt_file(_state, "hermes-discovery-scorecard").exists()


def test_scorecard_real_run_writes_files_and_receipt(monkeypatch, fake_db, tmp_path, _state):
    _scorecard_env(monkeypatch, tmp_path)
    assert hds.main([]) == 0
    assert json.loads(hds.SCORECARD_PATH.read_text())["totals"]["candidates"] == 7
    assert hds.OUTCOME_FEED_PATH.exists()
    r = _receipt(_state, "hermes-discovery-scorecard")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["recommendation"] == "steady"


def test_scorecard_db_unavailable_exit_1_no_zero_card(monkeypatch, fake_db, tmp_path, _state):
    _seed_ok_receipt(_state, "hermes-discovery-scorecard")
    _scorecard_env(monkeypatch, tmp_path)
    sys.modules["db_adapter"]._execute = lambda *a, **k: None
    monkeypatch.setattr(hds, "build_scorecard", _boom)
    assert hds.main([]) == 1
    assert not hds.SCORECARD_PATH.exists()
    r = _receipt(_state, "hermes-discovery-scorecard")
    assert r["status"] == "failed" and r["error"] == "db_unavailable" and r["ok_at"] == "2026-10-01T00:00:00+00:00"
    assert hds.main(["--dry-run"]) == 1


def test_scorecard_crash_failed_receipt(monkeypatch, fake_db, tmp_path, _state):
    _scorecard_env(monkeypatch, tmp_path)

    def crash(path, payload):
        raise OSError("No space left on device")

    monkeypatch.setattr(hds, "_atomic_write", crash)
    with pytest.raises(OSError):
        hds.main([])
    assert _receipt(_state, "hermes-discovery-scorecard")["error"] == "OSError"


def test_scorecard_dry_branch_returns_before_writes_in_source():
    src = inspect.getsource(hds.main)
    dry = src.index("if args.dry_run:")
    ret = src.index("return 0", dry)
    assert ret < src.index("_atomic_write(SCORECARD_PATH") and ret < src.index("write_outcome_feed(card)")
    assert ret < src.index("write_lane_receipt")


# ── siem_to_hermes_backlog (L835) ────────────────────────────────────────────────────────────────────


def _siem_env(monkeypatch, n_groups=2):
    events = []
    for g in range(n_groups):
        for _ in range(6):
            events.append(
                {
                    "dedupe_key": f"PIPELINE_FAILURE:sys:job{g}",
                    "severity": "P1",
                    "event_type": "PIPELINE_FAILURE",
                    "component": f"job{g}",
                    "raw_message_excerpt": "x",
                }
            )
    monkeypatch.setitem(
        sys.modules, "normalize_tradeai_alerts", types.SimpleNamespace(normalize=lambda days, dry_run: (events, {}))
    )


class _RC:
    def __init__(self, ids, rejected=0):
        self.ids, self.rows_rejected = ids, rejected


def _writer(monkeypatch, fn):
    mod = types.ModuleType("lib.writers.hermes_research_writer")
    mod.write_research_rows = fn
    monkeypatch.setitem(sys.modules, "lib.writers.hermes_research_writer", mod)


@pytest.mark.parametrize("argv", [["--apply", "--max", "5", "--dry-run"], ["--max", "5"]])
def test_siem_dry_run_wins_over_apply(monkeypatch, capsys, _state, argv):
    _siem_env(monkeypatch)
    conn = FakeConn(filed={"job0"})
    monkeypatch.setattr(s2h, "_connect", lambda: conn)
    _writer(monkeypatch, _boom)
    monkeypatch.setattr(llr, "write_lane_receipt", _boom)
    assert s2h.main(argv) == 0
    rep = _dry_line(capsys.readouterr().out)
    assert rep["summary"] == {"candidates": 2, "would_insert": 1, "would_skip_duplicate": 1, "max": 5}
    assert conn.readonly is True and conn.commits == 0 and not conn.writes()
    assert not _receipt_file(_state, "siem-to-hermes-backlog").exists()


def test_siem_dry_run_varies_with_max(monkeypatch, capsys):
    _siem_env(monkeypatch, n_groups=3)
    monkeypatch.setattr(s2h, "_connect", lambda: FakeConn())
    s2h.main(["--dry-run", "--max", "1"])
    assert _dry_line(capsys.readouterr().out)["summary"]["would_insert"] == 1
    s2h.main(["--dry-run", "--max", "5"])
    assert _dry_line(capsys.readouterr().out)["summary"]["would_insert"] == 3


def test_siem_real_run_inserts_and_writes_receipt(monkeypatch, _state):
    _siem_env(monkeypatch)
    conn = FakeConn(filed={"job0"})
    monkeypatch.setattr(s2h, "_connect", lambda: conn)
    rows = []
    _writer(monkeypatch, lambda cur, r, producer: rows.extend(r) or _RC([101]))
    assert s2h.main(["--apply", "--max", "5"]) == 0
    assert len(rows) == 1 and conn.commits == 1
    r = _receipt(_state, "siem-to-hermes-backlog")
    assert r["status"] == "ok" and r["summary"]["inserted"] == 1 and r["summary"]["duplicates"] == 1


def test_siem_all_rejected_exit_1_and_crash(monkeypatch, _state):
    _seed_ok_receipt(_state, "siem-to-hermes-backlog")
    _siem_env(monkeypatch)
    monkeypatch.setattr(s2h, "_connect", lambda: FakeConn())
    _writer(monkeypatch, lambda cur, r, producer: _RC([], rejected=1))
    assert s2h.main(["--apply"]) == 1
    r = _receipt(_state, "siem-to-hermes-backlog")
    assert r["error"] == "all_candidates_rejected" and r["ok_at"] == "2026-10-01T00:00:00+00:00"

    def no_db():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(s2h, "_connect", no_db)
    with pytest.raises(RuntimeError):
        s2h.main(["--apply"])
    assert _receipt(_state, "siem-to-hermes-backlog")["error"] == "RuntimeError"


def test_siem_source_ordering():
    gen = inspect.getsource(s2h.generate_backlog)
    assert gen.index("if dry_run or not candidates:") < gen.index("_connect()") < gen.index("write_research_rows")
    main = inspect.getsource(s2h.main)
    assert "live = args.apply and not args.dry_run" in main
    assert main.index("if not live:") < main.index("dry_run=False") < main.index("write_lane_receipt(LANE_ID")
    prev = inspect.getsource(s2h.preview_backlog)
    assert prev.index("enforce_readonly(conn)") < prev.index("_already_filed")
    assert "write_research_rows" not in prev and "commit" not in prev
