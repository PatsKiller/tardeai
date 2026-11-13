"""ANCHOR: STOP_COVERAGE_SNAPSHOT_LQ2968 — the stop-coverage lane reads the PERSISTED stop_lifecycle snapshot.

Synthetic fixtures only. No broker, no DB. Proves: fresh/stale/missing snapshot, uncovered position, a position in an
account the snapshot has no row for (unknown, not a gap), the paper/dust/exempt bars, the heartbeat saying
"unavailable", that nothing in the module can reach Schwab, and the consumer-side supersede of the legacy incident.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import stop_coverage_incidents as sci  # noqa: E402
from scripts.lib import home_incidents as hi  # noqa: E402

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)  # 10:00 ET Friday: in session
CFG = {"paper_accounts": ["paper_a"], "min_position_value_usd": 1000.0, "exclude_asset_types": ["option"],
       "exempt": [], "account_aliases": {}}


def snap(sym, acct="live_a", lifecycle="working", at=NOW - timedelta(seconds=300)):
    return {"account": acct, "symbol": sym, "lifecycle": lifecycle, "snapshot_at": at}


def pos(sym, acct="live_a", qty=10, mv=5000.0, at=NOW - timedelta(seconds=600), asset="EQUITY"):
    return {"account_key": acct, "symbol": sym, "qty": qty, "broker_market_value": mv, "as_of": at,
            "asset_type": asset, "is_cash": False}


def keyed(scan):
    return {r["symbol"]: r for r in scan["stops"]}


def test_working_stop_is_covered_and_missing_stop_is_a_gap():
    sc = sci.scan_from_snapshot([snap("AAA"), snap("OLD", lifecycle="filled")], [pos("AAA"), pos("BBB"), pos("OLD")],
                                now=NOW, cfg=CFG)
    k = keyed(sc)
    assert sc["ok"] and k["AAA"]["health"] == "ok" and not k["AAA"]["flags"]
    assert k["BBB"]["flags"] == ["unprotected"] and k["OLD"]["flags"] == ["unprotected"]  # a filled stop protects nothing
    p = sci.plan(sc, [], session_open=True)
    assert [g[1] for g in p["gaps"]] == ["BBB", "OLD"]


def test_stale_snapshot_makes_every_position_unavailable():
    old = NOW - timedelta(seconds=sci.MAX_AGE_SESSION_S + 1)
    sc = sci.scan_from_snapshot([snap("AAA", at=old)], [pos("AAA"), pos("BBB")], now=NOW, cfg=CFG)
    assert sc["ok"] is False and sc["reason"] == "snapshot_stale" and sc["snapshot_age_s"] == 901
    h = sci.account_hash("live_a")
    p = sci.plan(sc, [(h, "AAA")], session_open=True)          # an open incident is neither resolved nor re-opened
    assert not p["ok"] and p["gaps"] == [] and p["resolve"] == []


def test_snapshot_age_bar_is_900_in_session_and_5400_off_hours():
    at = NOW - timedelta(seconds=1000)
    assert sci.scan_from_snapshot([snap("A", at=at)], [pos("A")], now=NOW, cfg=CFG)["reason"] == "snapshot_stale"
    assert sci.scan_from_snapshot([snap("A", at=at)], [pos("A")], now=NOW, cfg=CFG, session_open=False)["ok"]
    at = NOW - timedelta(seconds=5401)
    assert sci.scan_from_snapshot([snap("A", at=at)], [pos("A")], now=NOW, cfg=CFG,
                                  session_open=False)["reason"] == "snapshot_stale"


def test_missing_snapshot_is_unavailable_not_all_uncovered():
    sc = sci.scan_from_snapshot([], [pos("AAA")], now=NOW, cfg=CFG)
    assert sc["ok"] is False and sc["reason"] == "snapshot_missing" and sc["stops"] == []


def test_positions_missing_or_stale_in_session_is_unavailable():
    assert sci.scan_from_snapshot([snap("A")], [], now=NOW, cfg=CFG)["reason"] == "positions_stale"
    old = NOW - timedelta(seconds=sci.POSITIONS_MAX_AGE_SESSION_S + 1)
    assert sci.scan_from_snapshot([snap("A")], [pos("A", at=old)], now=NOW, cfg=CFG)["reason"] == "positions_stale"


def test_account_without_any_snapshot_row_is_unknown_not_a_gap():
    sc = sci.scan_from_snapshot([snap("AAA")], [pos("AAA"), pos("ZZZ", acct="other_broker")], now=NOW, cfg=CFG)
    assert "ZZZ" not in keyed(sc)       # the Schwab-only snapshot says nothing about another broker


def test_paper_dust_option_and_exempt_are_not_checked():
    cfg = {**CFG, "exempt": [{"account": "live_a", "symbol": "EXE", "reason": "reviewed"}]}
    sc = sci.scan_from_snapshot([snap("AAA"), snap("X", acct="paper_a")],
                                [pos("AAA"), pos("DUST", mv=50.0), pos("OPT", asset="OPTION"), pos("EXE"),
                                 pos("PAP", acct="paper_a")], now=NOW, cfg=cfg)
    assert set(keyed(sc)) == {"AAA"}
    assert keyed(sci.scan_from_snapshot([snap("AAA")], [pos("NOVAL", mv=None)], now=NOW, cfg=CFG))["NOVAL"]["flags"]


def test_recovery_is_resolved_only_from_a_fresh_working_row():
    h = sci.account_hash("live_a")
    p = sci.plan(sci.scan_from_snapshot([snap("AAA")], [pos("AAA")], now=NOW, cfg=CFG), [(h, "AAA")])
    assert p["resolve"] == [(h, "AAA")]


class Conn:
    def __init__(self, rows=()):
        self.rows = list(rows)
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, p=()): pass
    def fetchall(self): return self.rows


def test_stale_run_with_apply_publishes_nothing():
    calls = []
    sc = sci.scan_from_snapshot([snap("AAA", at=NOW - timedelta(hours=3))], [pos("AAA")], now=NOW, cfg=CFG)
    out = sci.run(sc, conn=Conn(), publish=lambda *a, **k: calls.append(a), apply=True)
    assert calls == [] and out["ok"] is False and out["applied"] is False


def test_main_heartbeat_says_unavailable_and_keeps_old_ok_at(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    hb = sci.heartbeat_path()
    hb.parent.mkdir(parents=True, exist_ok=True)
    hb.write_text(json.dumps({"status": "ok", "ok_at": "2026-11-13T14:00:00+00:00"}))
    fake_db = type(sys)("db_adapter"); fake_db._get_conn = lambda: Conn()
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    rows = {sci.SNAPSHOT_SQL: [snap("AAA", at=datetime.now(timezone.utc) - timedelta(hours=3))],
            sci.POSITIONS_SQL: [pos("AAA", at=datetime.now(timezone.utc))]}
    monkeypatch.setattr(sci, "_fetch", lambda conn, sql: rows.get(sql, []))
    assert sci.main(["--apply"]) == 2
    doc = json.loads(hb.read_text())
    assert doc["status"] == "unavailable" and doc["reason"] == "snapshot_stale" and doc["ok_at"] == "2026-11-13T14:00:00+00:00"


def test_module_cannot_reach_a_broker():
    import ast
    tree = ast.parse(Path(sci.__file__).read_text())
    imported = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)} | \
               {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "stop_lifecycle_monitor" not in imported, imported   # the module whose scan() is the Schwab order read
    strings = " ".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                       and n is not tree.body[0].value)
    for banned in ("get_orders_raw", "place_order", "api.schwabapi", "/orders"):
        assert banned not in strings, banned


# ---- consumer-side supersede of the legacy incident ----------------------------------------------------------
def inc(producer, **kw):
    return {"incident_id": kw.get("i", 1), "alert_type": "position_unprotected", "source_producer": producer,
            "symbol": kw.get("symbol"), "first_seen_at": NOW - timedelta(days=12), "last_seen_at": NOW,
            "occurrence_count": 5, "digest_bucket": None, "severity": "critical", "source_system": "x",
            "blocks_trading_declared": None, "account_label": None, "payload_cause": None}


def _hb(tmp_path, monkeypatch, status="ok", age_s=60):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    p = Path(tmp_path) / "data" / "runtime" / hi.STRUCTURED_HEARTBEAT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"status": status, "ok_at": (NOW - timedelta(seconds=age_s)).isoformat()}))


def _build(rows):
    return hi.build(lambda sql, p=None, fetch="all": rows if "alert_incidents" in sql else {"events": 0}, now=NOW,
                    classes={})


def test_legacy_row_is_hidden_next_to_a_fresh_structured_producer(tmp_path, monkeypatch):
    _hb(tmp_path, monkeypatch)
    b = _build([inc("legacy_send_telegram", i=1), inc("stop_coverage_incidents", i=2, symbol="NEW")])
    assert [i["incident_id"] for i in b["items"]] == [2] and b["superseded_count"] == 1


def test_legacy_row_stays_when_the_structured_heartbeat_is_stale_failed_or_absent(tmp_path, monkeypatch):
    rows = [inc("legacy_send_telegram", i=1)]
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert len(_build(rows)["items"]) == 1                       # no heartbeat
    _hb(tmp_path, monkeypatch, age_s=901)
    assert len(_build(rows)["items"]) == 1                       # stale in session
    _hb(tmp_path, monkeypatch, status="unavailable")
    assert len(_build(rows)["items"]) == 1                       # last scan did not succeed
    assert _build(rows)["superseded_count"] == 0


def test_other_alert_types_are_never_superseded(tmp_path, monkeypatch):
    _hb(tmp_path, monkeypatch)
    r = inc("legacy_send_telegram"); r["alert_type"] = "something_else"
    assert len(_build([r])["items"]) == 1
