"""Read-only Watch card source for the conflict resolver (gap (g) 2026-10-25).

Pins: the reader's transitive closure (DD01 audit, scripts/audit_lane_transitive_capabilities.py) and its AGENTS.md
23.3 sender/broker scan (scripts/lib/advisory_lane_guard.py) are clean; every database statement is a SELECT;
the review authorization matches watch_domains; stored desk snapshot, packets and synthesis feed the adapters.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.conflicts import watch_source as W  # noqa: E402
from scripts.lib.conflicts.adapters import evaluate_inputs, security_inputs  # noqa: E402

NOW = datetime(2026, 10, 22, 17, tzinfo=timezone.utc)
FORBIDDEN_MODULES = ("watch_intelligence", "watchlist_intelligence", "watch_domains", "watch_decision",
                     "reentry_decision_desk", "live_projection", "shadow_decision_service", "decision_action_policy",
                     "db_adapter", "positions_sync", "market_quote_provider", "telegram_alert", "api_v2")


def test_transitive_closure_reaches_no_broker_order_sender_or_notifier():
    import audit_lane_transitive_capabilities as A
    resolver = A.Resolver(ROOT)
    order, parent = resolver.closure(ROOT / "scripts/lib/conflicts/watch_source.py")
    caps = {cap: A._chain(mod, parent) for mod in order for cap in resolver.info(mod).caps}
    for cap in (*A.FORBIDDEN, "chokepoint_send", "db_write", "subprocess"):
        assert cap not in caps, (cap, caps.get(cap))
    names = {p.stem for p in order}
    assert not names & set(FORBIDDEN_MODULES), names & set(FORBIDDEN_MODULES)
    assert len(order) < 40


def test_23_3_guard_scan_is_clean():
    from scripts.lib import advisory_lane_guard as G
    report = G.scan_entry("scripts/lib/conflicts/watch_source.py")
    assert not report.is_sender and report.problems() == [] and not report.broker_modules


def test_default_priority_is_read_from_the_watch_source_of_truth():
    from scripts.lib.watchlist_intelligence import DEFAULT_PRIORITY
    assert list(W.default_priority()) == list(DEFAULT_PRIORITY)


class FakeDB:
    def __init__(self, tables, fail=()):
        self.tables, self.fail, self.statements = tables, set(fail), []

    def __call__(self, sql, params=None):
        self.statements.append(" ".join(sql.split()))
        for name, rows in self.tables.items():
            if name in sql:
                if name in self.fail:
                    raise RuntimeError("relation unavailable")
                return rows(params) if callable(rows) else rows
        return []


def review(symbol, verdict, completed, **extra):
    raw = {"symbol": symbol, "agent_id": "cio", "status": "COMPLETE", "verdict": verdict, "authorization_event_id": "auth-1",
           "process_id": "p", "provider": "deepseek", "model": "deepseek-flash", "provider_request_id": f"req-{symbol}",
           "input_hash": "h", "artifact_id": f"a-{symbol}", "artifact_hash": "ah", "started_at": completed,
           "completed_at": completed, "requested_policy": "PRO_THINK", "executed_policy": "PRO_THINK",
           "fallback_used": False}
    raw.update(extra)
    return raw


def state_root(tmp_path, *, artifacts=(), quarantine=(), desk=None):
    base = tmp_path / "data/runtime/watchlist_intelligence"
    for kind, rows in (("artifacts", artifacts), ("quarantine", quarantine)):
        (base / kind).mkdir(parents=True, exist_ok=True)
        for raw in rows:
            (base / kind / f"{raw['symbol']}_cio.json").write_text(json.dumps(raw))
    if desk is not None:
        (tmp_path / "data/runtime/reentry_decision_desk_latest.json").write_text(json.dumps(desk))
    return tmp_path


def packets(params):
    symbols = set(params[0])
    rows = {"AAA": {"data_state": "STALE"}, "BBB": {"data_state": "UNAVAILABLE"}, "HELD": {"data_state": "STALE"}}
    return [{"s": s, "packet_id": f"pk-{s}", "generated_at": NOW - timedelta(days=1), "packet": json.dumps(p)}
            for s, p in rows.items() if s in symbols]


def database(**extra):
    tables = {
        "FROM operator_starred_symbols": [{"s": "STAR", "at": NOW - timedelta(days=3)}],
        "FROM screener_find_pins": [{"s": "SCRN"}],
        "watch_directives": [{"s": "DIRX", "at": NOW - timedelta(days=5)}],
        "FROM watchlist_events": [{"s": "DIRX", "event_type": "watch_mine_removed", "created_at": NOW - timedelta(days=1)}],
        "FROM llm_consumption_log": lambda params: [{"provider_request_id": r} for r in params[0] if r != "req-UNL"],
        "FROM decision_packets": packets,
        "FROM watchlist_final_synthesis": [{"s": "AAA", "recommendation": "buy", "confidence": 0.7,
                                            "updated_at": NOW - timedelta(days=20)}],
        "LIMIT %s": [{"s": "AAA"}, {"s": "543354104"}, {"s": "BBB"}],
    }
    tables.update(extra)
    return tables


def test_reader_is_select_only_and_mirrors_the_watch_universe(tmp_path):
    db = FakeDB(database())
    root = state_root(tmp_path, desk={"generated_at": NOW.isoformat(), "rows": [
        {"symbol": "DESK", "intel": {"state": "NEAR", "action": "WATCH"}, "price_as_of": NOW.isoformat(),
         "plan_as_of": (NOW - timedelta(days=1)).isoformat(), "held": False}]})
    state = W.read_watch_state(db, root=root, now=NOW, held_symbols={"HELD"})
    assert all(sql.startswith("SELECT") for sql in db.statements), db.statements
    assert state["schema"] == "WatchConflictSource@v1" and state["gaps"] == []
    universe = state["watch_universe"]
    assert universe[:len(W.default_priority())] == list(W.default_priority())
    assert {"STAR", "HELD", "SCRN", "AAA", "BBB"} <= set(universe)
    assert "DIRX" not in universe                      # removed from My Watchlist after its last reason
    assert "543354104" not in universe                 # CUSIP settlement ids never join
    assert "DESK" in state["symbols"] and state["reentry"]["DESK"]["plan_as_of"]


def test_trade_ai_from_stored_packets_with_current_holdings_first(tmp_path):
    state = W.read_watch_state(FakeDB(database()), root=state_root(tmp_path), now=NOW, held_symbols={"HELD"})
    cards = state["cards"]
    assert cards["AAA"]["trade_ai_state"] == "STALE" and cards["AAA"]["trade_ai_as_of"]
    assert cards["BBB"]["trade_ai_state"] == "DATA_UNAVAILABLE"
    assert cards["HELD"]["trade_ai_state"] == "MANAGING"
    assert cards["STAR"]["trade_ai_state"] == "DATA_UNAVAILABLE" and cards["STAR"]["trade_ai_as_of"] is None
    # Synthesis is passed raw with its own time; R1 (not the reader) decides it is stale.
    assert cards["AAA"]["decision"]["inputs"]["synthesis"] == "BUY"


def test_review_authorization_matches_watch_domains(tmp_path, monkeypatch):
    from scripts.lib.data_broker import watch_domains as WD
    linked = {"req-AAA", "req-BBB", "req-QQQ", "req-MIS"}
    monkeypatch.setattr(WD, "_db_query", lambda sql, params=None, fetch="all":
                        {"id": 1} if params and params[0] in linked else None)
    samples = [review("AAA", "HOLD", NOW.isoformat()),
               review("BBB", "AVOID", NOW.isoformat(), authorization_event_id=None, operator_approved=True),
               review("UNL", "BUY", NOW.isoformat()),
               review("MIS", "BUY", NOW.isoformat(), artifact_hash=""),
               review("FAL", "BUY", NOW.isoformat(), fallback_used=None),
               review("QQQ", "SELL", NOW.isoformat(), status="QUARANTINED")]
    for raw in samples:
        ours = W.review_disposition(raw, linked_request_ids=linked)
        theirs = WD._disposition_from_candidate(dict(raw), agent="cio")
        assert ours["status"] == theirs["status"], raw["symbol"]
        if ours["status"] == "COMPLETE":
            assert ours["verdict"] == theirs["verdict"] and ours["completed_at"] == theirs["completed_at"]
    root = state_root(tmp_path, artifacts=[review("AAA", "HOLD", NOW.isoformat()), review("UNL", "BUY", NOW.isoformat())],
                      quarantine=[review("BBB", "SELL", NOW.isoformat())])
    reviews = W.cio_reviews(FakeDB(database()), root, ["AAA", "UNL", "BBB", "ZZZ"], {})
    assert reviews["AAA"]["status"] == "COMPLETE" and reviews["AAA"]["verdict"] == "HOLD"
    assert reviews["UNL"] == {"status": "NOT_RUN", "reason_code": "CONSUMPTION_REQUEST_ID_UNLINKED"}
    assert reviews["BBB"]["reason_code"] == "QUARANTINED" and reviews["ZZZ"]["reason_code"] == "NOT_SCHEDULED"


def test_failed_source_is_a_reported_gap_never_an_empty_truth(tmp_path):
    state = W.read_watch_state(FakeDB(database(), fail={"FROM decision_packets", "FROM operator_starred_symbols"}),
                               root=state_root(tmp_path), now=NOW, held_symbols=set())
    assert any(g.startswith("decision_packets") for g in state["gaps"])
    assert any(g.startswith("starred") for g in state["gaps"])
    assert any(g.startswith("reentry_snapshot") for g in state["gaps"])       # no snapshot stored
    assert {c["trade_ai_state"] for c in state["cards"].values()} == {"DATA_UNAVAILABLE"}


def test_cards_feed_the_adapters_and_a_stale_synthesis_is_superseded_not_dropped(tmp_path):
    state = W.read_watch_state(FakeDB(database()), root=state_root(tmp_path), now=NOW, held_symbols=set())
    bundle = security_inputs(security_guid="g-aaa", symbol="AAA", held=False, card=state["cards"]["AAA"],
                             canonical={"source": "CIO record", "stance": "WATCH", "as_of": (NOW - timedelta(hours=1)).isoformat()})
    findings = evaluate_inputs(bundle, now=NOW)
    (superseded,) = [f for f in findings if f.kind == "SUPERSEDED"]
    assert superseded.rule == "R1" and superseded.sides[0]["source"] == "watchlist_final_synthesis"
    assert superseded.action == "none"                 # no running producer writes the synthesis (R1 registry)


def test_readonly_query_opens_a_read_only_session(monkeypatch):
    calls = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            calls["sql"] = sql

        def fetchall(self):
            return [{"s": "X"}]

    class Conn:
        def set_session(self, **kw):
            calls["session"] = kw

        def cursor(self, cursor_factory=None):
            return Cursor()

        def close(self):
            calls["closed"] = True

    fake = type(sys)("psycopg2")
    fake.extras = type(sys)("psycopg2.extras")
    fake.extras.RealDictCursor = object
    fake.connect = lambda **kw: calls.setdefault("connect", kw) and Conn()
    monkeypatch.setitem(sys.modules, "psycopg2", fake)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake.extras)
    monkeypatch.setenv("DB_PASSWORD", "fixture-not-a-secret")
    query = W.readonly_query()
    assert query("SELECT 1") == [{"s": "X"}]
    assert calls["session"] == {"readonly": True, "autocommit": True}
    assert "default_transaction_read_only=on" in calls["connect"]["options"]
    query.close()
    assert calls["closed"]
