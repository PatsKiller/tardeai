"""LQ-20261107-2142 / 2147: Home reads. ``home.last_seen`` in /api/v2/ui/prefs and GET /api/v2/home/incidents.

Home v010 (APPROVED 2026-11-11): Unknown never reads as OK; every value carries age + threshold; a P1 does
not block trading unless it declares it. Synthetic rows and an in-memory fake of the two tables only."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import home_incidents as HI  # noqa: E402
from scripts.lib import home_last_seen as HL  # noqa: E402

NOW = datetime(2026, 11, 11, 23, 0, tzinfo=timezone.utc)


def _iso(delta_min):
    return (NOW - timedelta(minutes=delta_min)).isoformat()


# ----------------------------------------------------------------------------- home.last_seen
class FakePrefs:
    def __init__(self):
        self.rows = {}

    def __call__(self, sql, params=None, fetch="all"):
        s = " ".join(sql.split())
        if s.startswith("SELECT value, updated_at FROM ui_prefs"):
            r = self.rows.get(params[0])
            return {"value": r, "updated_at": NOW} if r is not None else None
        if s.startswith("SELECT value FROM ui_prefs"):
            r = self.rows.get(params[0])
            return {"value": r} if r is not None else None
        if s.startswith("INSERT INTO ui_prefs"):
            self.rows[params[0]] = json.loads(params[1])
            return None
        raise AssertionError(s)


@pytest.fixture()
def prefs(monkeypatch):
    import scripts.api_v2 as api

    fake = FakePrefs()
    monkeypatch.setattr(api, "_db_query", fake)
    return api, fake


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def test_first_read_is_not_recorded_with_a_stated_fallback(prefs):
    api, _ = prefs
    out = api._ui_prefs_get({"key": "home.last_seen"})
    assert out["read"]["status"] == "NOT_RECORDED" and out["read"]["seen_at"] is None
    assert out["read"]["fallback"]["window_hours"] == 24 and "not recorded" in out["read"]["fallback"]["text"]


def test_write_then_read_round_trips_with_age(prefs):
    api, fake = prefs
    assert api._ui_prefs_set({"key": "home.last_seen", "value": {"seen_at": _now_iso(), "client": "phone"}})["ok"]
    out = api._ui_prefs_get({"key": "home.last_seen"})
    assert out["read"]["status"] == "RECORDED" and out["read"]["client"] == "phone"
    assert isinstance(out["read"]["age_sec"], int) and out["read"]["age_sec"] < 60


@pytest.mark.parametrize("bad", [
    "yesterday", 5, None, {"seen_at": "2026-11-11T10:00:00"},            # no zone
    {"seen_at": "not a time"}, {"seen_at": _now_iso(), "extra": 1},       # unknown field
    {"seen_at": _now_iso(), "client": "toaster"},
    {"seen_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},   # future
    {"seen_at": "1999-01-01T00:00:00+00:00"},
])
def test_garbage_is_rejected_and_nothing_is_stored(prefs, bad):
    api, fake = prefs
    out = api._ui_prefs_set({"key": "home.last_seen", "value": bad})
    assert out["ok"] is False and "home.last_seen" not in fake.rows


def test_a_stale_tab_cannot_rewind_the_anchor(prefs):
    api, fake = prefs
    newer = datetime.now(timezone.utc)
    older = newer - timedelta(hours=3)
    api._ui_prefs_set({"key": "home.last_seen", "value": {"seen_at": newer.isoformat()}})
    out = api._ui_prefs_set({"key": "home.last_seen", "value": {"seen_at": older.isoformat()}})
    assert out["ok"] and out.get("unchanged") is True
    assert HL.parse_ts(fake.rows["home.last_seen"]["seen_at"]) == newer


def test_a_corrupt_stored_value_is_unknown_not_a_guess(prefs):
    api, fake = prefs
    fake.rows["home.last_seen"] = {"seen_at": "garbage"}
    r = api._ui_prefs_get({"key": "home.last_seen"})["read"]
    assert r["status"] == "UNKNOWN" and r["seen_at"] is None and "unreadable" in r["reason"]


def test_other_keys_are_untouched(prefs):
    api, fake = prefs
    assert api._ui_prefs_set({"key": "watch.layout", "value": {"anything": [1, 2]}})["ok"]
    out = api._ui_prefs_get({"key": "watch.layout"})
    assert "read" not in out and out["value"] == {"anything": [1, 2]}


# ----------------------------------------------------------------------------- home/incidents
def _inc(**kw):
    base = dict(incident_id="i1", alert_type="stop_unprotected", digest_bucket="RISK", severity="critical",
                status="open", symbol="AAA", source_system="stop_monitor", source_producer=None,
                operator_action_required=True, first_seen_at=NOW - timedelta(hours=2), last_seen_at=NOW - timedelta(minutes=5),
                occurrence_count=7, acknowledged_at=None, blocks_trading_declared=None)
    base.update(kw)
    return base


def _db(rows=None, exc=None, seen=None):
    def q(sql, params=None, fetch="all"):
        if seen is not None:
            seen.append((sql, params))
        if exc:
            raise exc
        return rows
    return q


def test_row_carries_category_severity_first_seen_count_and_ages():
    out = HI.build(_db([_inc()]), now=NOW, registry={})
    assert out["status"] == "OK" and out["open_count"] == 1
    i = out["incidents"][0]
    assert (i["category"], i["severity"], i["count"]) == ("stop_unprotected", "critical", 7)
    assert i["first_seen_age_sec"] == 7200 and i["last_seen_age_sec"] == 300
    assert i["stale_after_sec"] == HI.STALE_AFTER_SEC and i["stale"] is False


def test_an_incident_not_reobserved_within_the_threshold_is_flagged_stale_not_dropped():
    out = HI.build(_db([_inc(last_seen_at=NOW - timedelta(hours=5))]), now=NOW, registry={})
    assert out["open_count"] == 1 and out["incidents"][0]["stale"] is True


def test_a_failed_read_is_unknown_never_an_empty_list():
    out = HI.build(_db(exc=RuntimeError("connection already closed")), now=NOW, registry={})
    assert out["status"] == "UNKNOWN" and out["incidents"] is None and out["open_count"] is None
    assert "RuntimeError" in out["reason"]
    assert HI.build(_db(None), now=NOW, registry={})["status"] == "UNKNOWN"


def test_a_clean_read_with_no_rows_is_ok_zero():
    out = HI.build(_db([]), now=NOW, registry={})
    assert out["status"] == "OK" and out["open_count"] == 0 and out["incidents"] == []


def test_blocks_trading_only_when_the_incident_declares_it():
    rows = [_inc(incident_id="a", severity="warning"),
            _inc(incident_id="b", severity="warning", blocks_trading_declared=True),
            _inc(incident_id="c", severity="warning", blocks_trading_declared="true"),
            _inc(incident_id="d", severity="critical", blocks_trading_declared=False)]
    out = HI.build(_db(rows), now=NOW, registry={})
    flags = {i["incident_id"]: i["blocks_trading"] for i in out["incidents"]}
    assert flags == {"a": False, "b": True, "c": True, "d": False}
    assert out["blocks_trading_count"] == 2


def test_cause_source_owner_are_unknown_without_the_registry_and_named_with_it():
    bare = HI.build(_db([_inc()]), now=NOW, registry={})["incidents"][0]
    assert (bare["cause"], bare["source"], bare["owner"]) == ("UNKNOWN",) * 3
    reg = {"stop_unprotected": {"cause": "stop lane late", "source": "stop-monitor", "owner": "ops"}}
    got = HI.build(_db([_inc()]), now=NOW, registry=reg)
    assert (got["incidents"][0]["cause"], got["incidents"][0]["owner"]) == ("stop lane late", "ops")
    partial = HI.build(_db([_inc()]), now=NOW, registry={"stop_unprotected": {"owner": "ops"}})["incidents"][0]
    assert partial["owner"] == "ops" and partial["cause"] == "UNKNOWN"


def test_registry_loader_tolerates_missing_and_corrupt_files(tmp_path):
    assert HI.load_registry(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert HI.load_registry(bad) == {}
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"types": {"x": {"owner": "o"}, "junk": 3}}))
    assert HI.load_registry(ok) == {"x": {"owner": "o"}}


def test_most_severe_first_then_oldest():
    rows = [_inc(incident_id="w", severity="warning"), _inc(incident_id="c2", severity="critical", first_seen_at=NOW - timedelta(hours=1)),
            _inc(incident_id="c1", severity="critical", first_seen_at=NOW - timedelta(hours=9))]
    assert [i["incident_id"] for i in HI.build(_db(rows), now=NOW, registry={})["incidents"]] == ["c1", "c2", "w"]


def test_the_query_is_read_only_open_production_and_bounded():
    seen = []
    HI.build(_db([], seen=seen), now=NOW, registry={})
    sql, params = seen[0]
    s = " ".join(sql.split()).upper()
    assert s.startswith("SELECT") and not any(w in s for w in ("INSERT ", "UPDATE ", "DELETE "))
    assert "STATUS = 'OPEN'" in s and "NOT I.SYNTHETIC" in s and "ENVIRONMENT = 'PRODUCTION'" in s and params == (HI.MAX_ROWS,)


def test_the_route_is_registered_and_returns_the_lib_body(monkeypatch):
    import scripts.api_v2 as api

    monkeypatch.setattr(api, "_db_query", _db([_inc()]))
    out = api._home_incidents()
    assert out["schema"] == HI.SCHEMA and out["open_count"] == 1
    assert "/api/v2/home/incidents" in Path(api.__file__).read_text()
