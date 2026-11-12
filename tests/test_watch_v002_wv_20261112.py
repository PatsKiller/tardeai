"""LQ-20261107-2622: Watch v002 honesty fixes WV-01..WV-05 (synthetic, hermetic: no DB, no network, no broker).

Each item: a stale / unknown / failed state is shown with its cause, never a fake OK.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_v2  # noqa: E402
import api_v3_opportunities as opp  # noqa: E402
import api_v3_watch_commands as wcmd  # noqa: E402
from lib import stale_serve  # noqa: E402
from lib.data_broker import watch_domains, watch_intelligence, watch_review_status  # noqa: E402

NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)


def _db_down(*_a, **_k):
    raise api_v2._DbReadError("connection refused", unavailable=True)


# ── WV-01: a read that failed is UNKNOWN with a cause, never ok:true + empty ─────────────────────────────────


@pytest.mark.parametrize("handler,query", [
    (api_v2._sector_performance, {}),
    (api_v2._hermes_subject_intel_map, {"type": "ticker"}),
    (api_v2._watch_alerts_list, {}),
    (api_v2._watchpool_list, {}),
])
def test_wv01_failed_store_read_is_503_unknown_with_cause(monkeypatch, handler, query):
    monkeypatch.setattr(api_v2, "_db_required", _db_down)
    status, body = handler(query)
    assert status == 503 and body["ok"] is False and body["state"] == "UNKNOWN"
    assert body["cause"] == "connection refused" and body["retry_after_sec"] == 5


def test_wv01_pro_analyst_pills_unreadable_read_model_is_unknown_not_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(api_v2, "PROJECT_ROOT", tmp_path)
    status, body = api_v2._pro_analyst_pills({})
    assert status == 503 and body["ok"] is False and body["state"] == "UNKNOWN"
    assert "pro_analyst_pills_latest.json" in body["cause"] and body["pills"] == []


def test_wv01_opportunities_missing_projection_is_unknown_and_empty_projection_is_ok(monkeypatch, tmp_path):
    from lib.cio_opportunity_store import CIOOpportunityStore

    missing = CIOOpportunityStore(event_path=tmp_path / "e.jsonl", projection_path=tmp_path / "nope.json")
    monkeypatch.setattr(opp, "_store", lambda: missing)
    out = opp.get_list({})
    assert out["ok"] is False and out["state"] == "UNKNOWN" and out["cause"] == "projection file missing"
    assert out["items"] == [] and out["as_of"] is None

    (tmp_path / "bad.json").write_text("{not json")
    bad = CIOOpportunityStore(event_path=tmp_path / "e.jsonl", projection_path=tmp_path / "bad.json")
    monkeypatch.setattr(opp, "_store", lambda: bad)
    assert opp.get_list({})["cause"].startswith("projection unreadable")

    (tmp_path / "ok.json").write_text(json.dumps({"as_of": "2026-11-12T17:00:00+00:00", "items": {}}))
    ok = CIOOpportunityStore(event_path=tmp_path / "e.jsonl", projection_path=tmp_path / "ok.json")
    monkeypatch.setattr(opp, "_store", lambda: ok)
    out = opp.get_list({})
    assert out["ok"] is True and out["total"] == 0 and out["as_of"] == "2026-11-12T17:00:00+00:00"


def test_wv01_sector_performance_empty_snapshot_names_its_reason(monkeypatch):
    monkeypatch.setattr(api_v2, "_db_required", lambda *a, **k: [])
    body = api_v2._sector_performance({})
    assert body["ok"] is True and body["items"] == [] and body["as_of"] is None
    assert "no snapshot" in body["empty_reason"]


# ── WV-02: as_of is data time, never the request time ───────────────────────────────────────────────────────


def test_wv02_alerts_and_watchpool_carry_the_stores_newest_timestamp(monkeypatch):
    rows = [{"id": 1, "active": True, "created_at": "2026-11-10T10:00:00+00:00", "last_fired_at": None},
            {"id": 2, "active": False, "created_at": "2026-11-09T10:00:00+00:00",
             "last_fired_at": "2026-11-11T09:30:00+00:00"}]
    monkeypatch.setattr(api_v2, "_db_required", lambda *a, **k: rows)
    assert api_v2._watch_alerts_list({})["as_of"] == "2026-11-11T09:30:00+00:00"
    monkeypatch.setattr(api_v2, "_db_required", lambda *a, **k: [])
    assert api_v2._watch_alerts_list({})["as_of"] is None  # empty store: unknown, not "now"
    monkeypatch.setattr(api_v2, "_db_required",
                        lambda *a, **k: [{"current_status": "ACTIVE", "entered_at": "2026-11-08T14:00:00+00:00"}])
    assert api_v2._watchpool_list({})["as_of"] == "2026-11-08T14:00:00+00:00"


def test_wv02_subject_intel_map_as_of_is_the_newest_answer(monkeypatch):
    rows = [{"symbol": "ZZAA", "lane": "grok", "model": "m", "recommendation": "ok",
             "created_at": "2026-11-12T08:00:00+00:00"}]
    monkeypatch.setattr(api_v2, "_db_required", lambda *a, **k: rows)
    monkeypatch.setattr(api_v2, "_split_refusals", lambda r: (r, []))
    assert api_v2._hermes_subject_intel_map({"type": "ticker"})["as_of"] == "2026-11-12T08:00:00+00:00"


def _states(updated):
    st = {"status": "queued", "label": "queued", "open": True}
    if updated:
        st["queued_at"] = updated
    return {"ZZAA": st}


def test_wv02_review_status_as_of_is_row_time_and_request_time_is_served_at():
    out = watch_review_status.review_status(
        {"symbols": "ZZAA"}, priority_reader=lambda n: _states("2026-11-11T12:00:00+00:00"),
        stance_reader=lambda n: {}, now=NOW)
    assert out["as_of"] == "2026-11-11T12:00:00+00:00" and out["served_at"] == NOW.isoformat()
    assert out["as_of"] != out["served_at"]
    none = watch_review_status.review_status(
        {"symbols": "ZZAA"}, priority_reader=lambda n: _states(None), stance_reader=lambda n: {}, now=NOW)
    assert none["as_of"] is None and none["served_at"] == NOW.isoformat()


def test_wv02_symbol_intelligence_as_of_is_product_time_not_now():
    from lib import cio_symbol_intelligence as csi

    built = csi.assemble_symbol_intelligence("ZZAA", product={"as_of": "2026-11-10T01:02:03+00:00"})
    assert built["as_of"] == "2026-11-10T01:02:03+00:00" and built["served_at"] != built["as_of"]
    assert csi.assemble_symbol_intelligence("ZZAA")["as_of"] is None


# ── WV-03: a stale body says STALE with its age and cause at the top level ──────────────────────────────────


class _Clock:
    t = 1_900_000_000.0

    def __call__(self):
        return self.t


def _swr():
    clock = _Clock()
    jobs: list = []
    return stale_serve.StaleServe(None, clock=clock, spawn=jobs.append, fresh_s=60, max_stale_s=3600), clock, jobs


def test_wv03_stale_serve_marks_state_age_and_cause():
    s, clock, jobs = _swr()
    s.get("k", lambda: (200, {"ok": True, "v": 1}))
    status, fresh = s.get("k", lambda: (200, {"ok": True, "v": 2}))
    assert "state" not in fresh and "age_s" not in fresh and fresh["_swr"]["stale"] is False
    clock.t += 300
    status, stale = s.get("k", lambda: (200, {"ok": True, "v": 2}))
    assert status == 200 and stale["v"] == 1
    assert stale["state"] == "STALE" and stale["status"] == "STALE" and stale["age_s"] == 300.0
    assert stale["stale_cause"] == "refresh_in_progress"


def test_wv03_failed_refresh_names_its_cause_and_a_domain_status_is_not_clobbered():
    s, clock, jobs = _swr()
    s.get("k", lambda: (200, {"ok": True, "status": "HEALTHY"}))
    clock.t += 300

    def boom():
        raise TimeoutError("slow")

    s.get("k", boom)
    for j in jobs:
        j()
    clock.t += 1
    status, stale = s.get("k", boom)
    assert stale["state"] == "STALE" and stale["status"] == "HEALTHY"  # `status` is the body's own field
    assert stale["stale_cause"] == "TimeoutError"


# ── WV-04: the saved-list read targets tables that exist, and says so when it cannot read ───────────────────


def test_wv04_no_read_of_the_nonexistent_membership_table():
    src = (ROOT / "scripts" / "lib" / "data_broker" / "watch_domains.py").read_text()
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith(("#", '"""')))
    assert "FROM watchlist_list_membership" not in code and "FROM watchlist_groups" not in code
    assert "tos_watchlist_members" in watch_domains.MEMBERS_SQL and "tos_watchlists" in watch_domains.LISTS_SQL
    assert "removed_at IS NULL" in watch_domains.MEMBERS_SQL
    for sql in (watch_domains.LISTS_SQL, watch_domains.MEMBERS_SQL):
        assert "watchlist_list_membership" not in sql and "watchlist_groups" not in sql


def test_wv04_lists_read_ok_empty_and_unreadable_are_three_states(monkeypatch):
    monkeypatch.setattr(watch_domains, "_db_query", lambda sql, params=None, fetch="all": [
        {"id": "7", "label": "Swing", "n": 4, "list_updated_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
         "imported_at": datetime(2026, 11, 5, tzinfo=timezone.utc)}])
    got = watch_domains.saved_lists_status()
    assert got["readable"] is True and got["lists"][0]["count"] == 4 and got["as_of"].startswith("2026-11-05")
    monkeypatch.setattr(watch_domains, "_db_query", lambda *a, **k: [])
    assert watch_domains.saved_lists_status()["readable"] is True and watch_domains.saved_lists_canonical() == []

    def down(*a, **k):
        raise RuntimeError('relation "tos_watchlists" does not exist')

    monkeypatch.setattr(watch_domains, "_db_query", down)
    got = watch_domains.saved_lists_status()
    assert got["readable"] is False and "does not exist" in got["cause"] and got["lists"] == []
    members, cause = watch_domains.saved_list_membership_status("7")
    assert members == set() and cause == "RuntimeError"


def test_wv04_watch_lists_payload_is_unknown_when_unreadable_and_empty_when_empty(monkeypatch):
    monkeypatch.setattr(watch_intelligence, "_starred_set", lambda: set())
    monkeypatch.setattr(watch_domains, "_db_query", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    out = watch_intelligence.watch_lists()
    assert out["ok"] is False and out["quality_state"] == "UNKNOWN" and "db gone" in out["cause"]
    monkeypatch.setattr(watch_domains, "_db_query", lambda *a, **k: [])
    out = watch_intelligence.watch_lists()
    assert out["ok"] is True and out["quality_state"] == "EMPTY" and out["cause"] is None


# ── WV-05: a command is only done when its read-back agrees ─────────────────────────────────────────────────


class _Cur:
    def __init__(self, present):
        self.present, self.last = present, ""

    def execute(self, sql, params=None):
        self.last = sql

    def fetchone(self):
        return (1,) if self.present else None


class _Conn:
    def __init__(self, present):
        self.present = present

    def cursor(self):
        return _Cur(self.present)

    def commit(self):
        pass


def _star(monkeypatch, present, action):
    import db_adapter

    monkeypatch.setattr(db_adapter, "_get_conn", lambda: _Conn(present))
    return wcmd.post_star({"symbol": "zzaa", "action": action})


def test_wv05_star_confirmed_by_readback_is_ok(monkeypatch):
    out = _star(monkeypatch, True, "star")
    assert out["ok"] is True and out["starred"] is True
    out = _star(monkeypatch, False, "unstar")
    assert out["ok"] is True and out["starred"] is False


def test_wv05_star_lost_write_is_503_readback_mismatch(monkeypatch):
    out = _star(monkeypatch, False, "star")
    assert out["ok"] is False and out["error"] == "READBACK_MISMATCH" and out["http_status"] == 503
    assert "expected the symbol to be present" in out["detail"]


def test_wv05_unstar_that_did_not_remove_is_503_readback_mismatch(monkeypatch):
    out = _star(monkeypatch, True, "unstar")
    assert out["ok"] is False and out["error"] == "READBACK_MISMATCH" and "absent" in out["detail"]


def _mine(present, action="add", raises=False):
    def q(sql, params=None, fetch="all"):
        if "operator_starred_symbols" in sql:
            if raises:
                raise RuntimeError("down")
            return [{"present": 1}] if present else []
        return []

    return wcmd.post_mine_decision({"symbol": "ZZAA", "action": action}, db_execute=lambda s, p=None: None, db_query=q,
                                   by="tester")


def test_wv05_mine_readback_agrees_mismatches_or_is_unavailable():
    assert _mine(True)["ok"] is True
    assert _mine(False, "remove")["ok"] is True
    lost = _mine(False)
    assert lost["ok"] is False and lost["error"] == "READBACK_MISMATCH" and lost["http_status"] == 503
    kept = _mine(True, "remove")
    assert kept["ok"] is False and kept["error"] == "READBACK_MISMATCH"
    unknown = _mine(True, raises=True)
    assert unknown["ok"] is False and unknown["error"] == "READBACK_UNAVAILABLE" and unknown["http_status"] == 503


def test_wv05_mine_without_star_write_skips_the_readback():
    out = wcmd.post_mine_decision({"symbol": "ZZAA", "action": "add"}, db_execute=lambda s, p=None: None,
                                  db_query=lambda *a, **k: [], by="tester", star_write=False)
    assert out["ok"] is True and out["starred"] is None
