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
        if s.startswith("INSERT INTO ui_prefs") and "RETURNING value" in s:   # the atomic home.last_seen upsert
            new = json.loads(params[1])
            old = self.rows.get(params[0])
            if old is not None:
                new = {**new, "previous_seen_at": old.get("seen_at")}
            self.rows[params[0]] = new
            return {"value": new}
        if s.startswith("INSERT INTO ui_prefs"):
            self.rows[params[0]] = json.loads(params[1])
            return None
        raise AssertionError(s)


@pytest.fixture()
def prefs(monkeypatch):
    import scripts.api_v2 as api

    fake = FakePrefs()
    monkeypatch.setattr(api, "_db_query", fake)
    monkeypatch.setattr(api, "_db_query_raising", fake)
    return api, fake


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _post(api, value):
    return api._ui_prefs_set({"key": "home.last_seen", "value": value})


def test_absent_key_is_the_stated_24h_fallback(prefs):
    api, _ = prefs
    r = api._ui_prefs_get({"key": "home.last_seen"})["read"]
    assert r["status"] == "NOT_RECORDED" and r["window_basis"] == "fallback_24h"
    assert r["last_visit_recorded"] is False and r["seen_at"] is None and "not recorded" in r["fallback_text"]


def test_a_second_post_moves_seen_to_previous(prefs):
    api, fake = prefs
    assert _post(api, {"device": "phone"})["ok"]
    first = fake.rows["home.last_seen"]["seen_at"]
    assert fake.rows["home.last_seen"]["previous_seen_at"] is None
    assert _post(api, {"device": "desktop"})["ok"]
    v = fake.rows["home.last_seen"]
    assert v["previous_seen_at"] == first and v["device"] == "desktop"
    assert HL.parse_ts(v["seen_at"]) >= HL.parse_ts(first)
    r = api._ui_prefs_get({"key": "home.last_seen"})["read"]
    assert r["status"] == "RECORDED" and r["window_basis"] == "last_visit" and r["last_visit_recorded"] is True
    assert r["previous_seen_at"] == first and r["device"] == "desktop" and isinstance(r["age_sec"], int)


def test_a_client_cannot_set_previous_seen_at_or_seen_at(prefs):
    api, fake = prefs
    _post(api, {"device": "phone"})
    stored_seen = fake.rows["home.last_seen"]["seen_at"]
    forged = "2020-01-01T00:00:00+00:00"
    assert _post(api, {"device": "phone", "previous_seen_at": forged, "seen_at": forged})["ok"]
    v = fake.rows["home.last_seen"]
    assert v["previous_seen_at"] == stored_seen            # copied from the server's stored seen_at
    assert v["seen_at"] != forged and HL.parse_ts(v["seen_at"]).year >= 2026   # server now(), not the client


@pytest.mark.parametrize("bad", ["yesterday", 5, None, {}, {"device": "toaster"}, {"seen_at": "2026-11-11T10:00:00+00:00"}])
def test_garbage_is_rejected_and_nothing_is_stored(prefs, bad):
    api, fake = prefs
    out = _post(api, bad)
    assert out["ok"] is False and "home.last_seen" not in fake.rows


def test_a_corrupt_stored_value_is_unknown_with_fallback_not_a_guess(prefs):
    api, fake = prefs
    fake.rows["home.last_seen"] = {"seen_at": "garbage"}
    r = api._ui_prefs_get({"key": "home.last_seen"})["read"]
    assert r["status"] == "UNKNOWN" and r["seen_at"] is None and "unreadable" in r["reason"]
    assert r["window_basis"] == "fallback_24h" and r["last_visit_recorded"] is False
    # and the next post still works: it starts a clean window (previous unreadable -> None)
    assert _post(api, {"device": "phone"})["ok"]
    r2 = api._ui_prefs_get({"key": "home.last_seen"})["read"]
    assert r2["status"] == "RECORDED" and r2["previous_seen_at"] is None     # the garbage is never served as a time


def test_other_keys_are_untouched(prefs):
    api, fake = prefs
    assert api._ui_prefs_set({"key": "watch.layout", "value": {"anything": [1, 2]}})["ok"]
    out = api._ui_prefs_get({"key": "watch.layout"})
    assert "read" not in out and out["value"] == {"anything": [1, 2]}


# ----------------------------------------------------------------------------- home/incidents
CLASSES = {
    "position_unprotected": {"category": "Unprotected Position", "priority": "P0", "blocks_trading_default": True,
                             "owner": "risk", "ttl_h": 1, "cause": "no working stop", "home_visible": True},
    "data_integrity": {"category": "Data Integrity", "priority": "P1", "blocks_trading_default": False,
                       "owner": "data", "ttl_h": 24, "home_visible": True},
    "job_telemetry": {"priority": "INFO", "home_visible": False},
}


def _inc(**kw):
    base = dict(incident_id="i1", alert_type="position_unprotected", digest_bucket="RISK", severity="critical",
                symbol="AAA", source_system="stop_monitor", source_producer=None,
                first_seen_at=NOW - timedelta(hours=2), last_seen_at=NOW - timedelta(minutes=5),
                occurrence_count=4, blocks_trading_declared=None, account_label="acct-A", payload_cause=None)
    base.update(kw)
    return base


def _db(rows=None, exc=None, events=12, seen=None, exc_events=None):
    def q(sql, params=None, fetch="all"):
        if seen is not None:
            seen.append((sql, params))
        if "FROM alert_events" in sql:
            if exc_events:
                raise exc_events
            return None if events is None else {"events": events}
        if exc:
            raise exc
        return rows
    return q


def test_item_matches_the_spec_shape():
    out = HI.build(_db([_inc()]), now=NOW, classes=CLASSES)
    assert out["schema"] == "HomeIncidents@v1" and out["state"] == "OK" and out["reason"] is None
    assert out["counts"] == {"P0": 1, "P1": 0, "UNCLASSIFIED": 0, "blocks_trading": 1}
    i = out["items"][0]
    for k in ("incident_id", "category", "priority", "blocks_trading", "symbol", "account_label", "first_seen_at",
              "last_seen_at", "failed_checks", "owner", "cause", "stale_condition"):
        assert k in i
    assert (i["category"], i["priority"], i["owner"], i["cause"]) == ("Unprotected Position", "P0", "risk", "no working stop")
    assert i["failed_checks"] == 4 and i["failing_for_s"] == 7200 and i["account_label"] == "acct-A"
    assert i["blocks_trading"] is True              # class default
    assert out["snapshot"]["age_s"] == 0 and out["served_at"]


def test_an_unmapped_class_is_unclassified_shown_and_counted():
    out = HI.build(_db([_inc(incident_id="x", alert_type="mystery_alert")]), now=NOW, classes=CLASSES)
    i = out["items"][0]
    assert i["priority"] == "UNCLASSIFIED" and i["category"] == "mystery_alert" and i["owner"] == "UNREGISTERED"
    assert i["stale_condition"] is None and i["blocks_trading"] is False
    assert out["counts"]["UNCLASSIFIED"] == 1 and out["counts"]["P0"] == 0


def test_no_registry_file_marks_everything_unclassified():
    out = HI.build(_db([_inc()]), now=NOW, classes={})
    assert out["registry"] == "absent" and out["items"][0]["priority"] == "UNCLASSIFIED"


def test_past_ttl_is_stale_condition_and_within_ttl_is_not():
    old = HI.build(_db([_inc(last_seen_at=NOW - timedelta(hours=3))]), now=NOW, classes=CLASSES)["items"][0]
    fresh = HI.build(_db([_inc(last_seen_at=NOW - timedelta(minutes=10))]), now=NOW, classes=CLASSES)["items"][0]
    assert old["stale_condition"] is True and fresh["stale_condition"] is False
    assert old["last_seen_age_s"] == 10800 and old["ttl_h"] == 1


def test_sort_is_p0_then_blocks_trading_then_first_seen():
    rows = [
        _inc(incident_id="p1_old", alert_type="data_integrity", first_seen_at=NOW - timedelta(hours=20)),
        _inc(incident_id="p1_block", alert_type="data_integrity", blocks_trading_declared=True, first_seen_at=NOW - timedelta(hours=2)),
        _inc(incident_id="p0_new", first_seen_at=NOW - timedelta(hours=1)),
        _inc(incident_id="p0_old", first_seen_at=NOW - timedelta(hours=9)),
        _inc(incident_id="uncl", alert_type="zzz", first_seen_at=NOW - timedelta(hours=30)),
    ]
    got = [i["incident_id"] for i in HI.build(_db(rows), now=NOW, classes=CLASSES)["items"]]
    assert got == ["p0_old", "p0_new", "p1_block", "p1_old", "uncl"]


def test_a_payload_declaration_beats_the_class_default_both_ways():
    rows = [_inc(incident_id="no", blocks_trading_declared=False),
            _inc(incident_id="yes", alert_type="data_integrity", blocks_trading_declared="true")]
    flags = {i["incident_id"]: i["blocks_trading"] for i in HI.build(_db(rows), now=NOW, classes=CLASSES)["items"]}
    assert flags == {"no": False, "yes": True}


def test_non_visible_classes_are_hidden_and_counted_as_hidden():
    out = HI.build(_db([_inc(alert_type="job_telemetry", incident_id="t"), _inc()]), now=NOW, classes=CLASSES)
    assert [i["incident_id"] for i in out["items"]] == ["i1"] and out["hidden_count"] == 1


def test_read_failure_is_unknown_with_null_counts_never_an_empty_list():
    out = HI.build(_db(exc=RuntimeError("connection already closed")), now=NOW, classes=CLASSES)
    assert out["state"] == "UNKNOWN" and out["counts"] is None and out["items"] is None and "RuntimeError" in out["reason"]
    assert HI.build(_db(None), now=NOW, classes=CLASSES)["state"] == "UNKNOWN"


def test_read_timeout_is_timed_out():
    out = HI.build(_db(exc=Exception("canceling statement due to statement timeout")), now=NOW, classes=CLASSES)
    assert out["state"] == "TIMED_OUT" and out["counts"] is None and out["items"] is None


def test_clean_read_with_no_rows_is_ok_zero():
    out = HI.build(_db([]), now=NOW, classes=CLASSES)
    assert out["state"] == "OK" and out["items"] == [] and out["counts"]["P0"] == 0


def test_data_integrity_24h_is_a_field_with_state_and_failure_is_not_zero():
    ok = HI.build(_db([]), now=NOW, classes=CLASSES)["data_integrity_24h"]
    assert ok["state"] == "OK" and ok["value"]["events"] == 12 and ok["age_s"] == 0
    bad = HI.build(_db([], events=None), now=NOW, classes=CLASSES)["data_integrity_24h"]
    assert bad["state"] == "UNKNOWN" and bad["value"] is None
    to = HI.build(_db([], exc_events=Exception("statement timeout")), now=NOW, classes=CLASSES)
    assert to["state"] == "OK" and to["data_integrity_24h"]["state"] == "TIMED_OUT"


def test_registry_loader_tolerates_missing_and_corrupt_files(tmp_path):
    assert HI.load_classes(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert HI.load_classes(bad) == {}
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"incident_classes": {"x": {"owner": "o"}, "junk": 3}}))
    assert HI.load_classes(ok) == {"x": {"owner": "o"}}


def test_the_queries_are_read_only_open_production_and_bounded():
    seen = []
    HI.build(_db([], seen=seen), now=NOW, classes=CLASSES)
    for sql, _ in seen:
        s = " ".join(sql.split()).upper()
        assert "SET LOCAL STATEMENT_TIMEOUT" in s
        assert not any(w in s for w in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER "))
    s0, p0 = seen[0]
    s0 = " ".join(s0.split()).upper()
    assert "STATUS = 'OPEN'" in s0 and "NOT I.SYNTHETIC" in s0 and "ENVIRONMENT = 'PRODUCTION'" in s0 and p0 == (HI.MAX_ROWS,)
    assert "ALERT_TYPE = 'DATA_INTEGRITY'" in " ".join(seen[1][0].split()).upper()


def test_the_route_is_registered_and_returns_the_lib_body(monkeypatch):
    import scripts.api_v2 as api

    monkeypatch.setattr(api, "_db_query_raising", _db([_inc()]))
    from lib import home_incidents as route_hi   # the module the route imports

    monkeypatch.setattr(route_hi, "load_classes", lambda *a, **k: CLASSES)
    out = api._home_incidents()
    assert out["schema"] == HI.SCHEMA and out["counts"]["P0"] == 1
    assert '"/api/v2/home/incidents": lambda: _home_incidents()' in Path(api.__file__).read_text()


# ----------------------------------------------------------------------------- C1: auth on the home.last_seen write
def _ctx(principal="tailnet:op@example.test", listener="serve_proxy", csrf=(True, ""), logins=("op@example.test",)):
    from scripts.lib import home_approvals_api as haa

    return haa.Ctx(principal=lambda: principal, listener=lambda: listener, csrf=lambda m, p: csrf,
                   allowed_logins=logins, can_read=lambda: False, clock=lambda: NOW)


def test_gate_admits_only_the_operators_signed_in_session():
    import scripts.api_v2 as api

    assert api._home_last_seen_gate(_ctx()) == (200, None)
    for bad in (_ctx(principal=""), _ctx(principal="service-token"), _ctx(principal="agent:cc-sonnet-3"),
                _ctx(principal="tailnet:someone@else.test"), _ctx(listener="direct")):
        status, body = api._home_last_seen_gate(bad)
        assert status == 403 and body["ok"] is False and body["code"] == "NOT_OPERATOR"


def test_gate_refuses_a_failed_csrf_check():
    import scripts.api_v2 as api

    status, body = api._home_last_seen_gate(_ctx(csrf=(False, "csrf: no request context")))
    assert status == 403 and body["code"] == "CSRF_REFUSED"


def test_unauthenticated_post_is_refused_and_stores_nothing(prefs):
    """Through the HTTP edge with no cc_auth request context at all: refused, fail-closed, nothing written."""
    api, fake = prefs
    status, body = api.handle("/api/v2/ui/prefs", "POST", {"key": "home.last_seen", "value": {"device": "phone"}})
    assert status == 403 and body["ok"] is False
    assert "home.last_seen" not in fake.rows


def test_an_authorised_post_reaches_the_handler(prefs, monkeypatch):
    api, fake = prefs
    monkeypatch.setattr(api, "_home_last_seen_gate", lambda ctx=None: (200, None))
    status, body = api.handle("/api/v2/ui/prefs", "POST", {"key": "home.last_seen", "value": {"device": "phone"}})
    assert status == 200 and body["ok"] and fake.rows["home.last_seen"]["device"] == "phone"


def test_other_keys_are_not_gated(prefs):
    api, fake = prefs
    status, _ = api.handle("/api/v2/ui/prefs", "POST", {"key": "watch.layout", "value": {"a": 1}})
    assert status == 200 and fake.rows["watch.layout"] == {"a": 1}


def test_key_spelled_with_padding_is_still_gated(prefs):
    api, fake = prefs
    status, _ = api.handle("/api/v2/ui/prefs", "POST", {"key": "  home.last_seen ", "value": {"device": "phone"}})
    assert status == 403 and "home.last_seen" not in fake.rows


# ----------------------------------------------------------------------------- 30-60 s cache
def test_incidents_ok_body_is_cached_and_a_failure_is_not(monkeypatch):
    import scripts.api_v2 as api
    from lib import home_incidents as route_hi

    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append(sql)
        return [] if "alert_incidents" in sql else {"events": 0}

    api._HOME_INCIDENTS_CACHE.clear()
    monkeypatch.setattr(api, "_db_query_raising", q)
    monkeypatch.setattr(route_hi, "load_classes", lambda *a, **k: CLASSES)
    a = api._home_incidents()
    n = len(calls)
    b = api._home_incidents()
    assert b["snapshot"]["computed_at"] == a["snapshot"]["computed_at"] and len(calls) == n   # served from cache, no new reads
    api._HOME_INCIDENTS_CACHE.clear()
    monkeypatch.setattr(api, "_db_query_raising", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert api._home_incidents()["state"] == "UNKNOWN"
    monkeypatch.setattr(api, "_db_query_raising", q)
    assert api._home_incidents()["state"] == "OK"                    # the failure was not pinned
    api._HOME_INCIDENTS_CACHE.clear()
    assert 30 <= route_hi.CACHE_TTL_S <= 60


# ----------------------------------------------------------------------------- operator P0/P1 classes (DECISIONS-20261111)
def test_decision_classes_in_a_registry_sort_p0_before_p1_and_unmapped_last():
    classes = {"protection_gap": {"category": "Protection Gap", "priority": "P0", "blocks_trading_default": True, "owner": "defense", "ttl_h": 1},
               "late_scheduler": {"category": "Late Scheduler", "priority": "P1", "owner": "os", "ttl_h": 2}}
    rows = [_inc(incident_id="s", alert_type="late_scheduler"), _inc(incident_id="u", alert_type="new_unseen"),
            _inc(incident_id="g", alert_type="protection_gap")]
    out = HI.build(_db(rows), now=NOW, classes=classes)
    assert [i["incident_id"] for i in out["items"]] == ["g", "s", "u"]
    assert out["counts"] == {"P0": 1, "P1": 1, "UNCLASSIFIED": 1, "blocks_trading": 1}


# ----------------------------------------------------------------------------- LQ-2186 F1/F2/F3
def test_upsert_is_one_atomic_statement_copying_previous_in_sql(prefs):
    api, fake = prefs
    seen = []
    orig = fake.__call__

    def spy(sql, params=None, fetch="all"):
        seen.append(" ".join(sql.split()))
        return orig(sql, params, fetch)
    api._db_query_raising = spy
    out = api._ui_prefs_set({"key": "home.last_seen", "value": {"device": "phone"}})
    assert out["ok"] and out["value"]["device"] == "phone"
    assert len(seen) == 1 and "ON CONFLICT (key) DO UPDATE" in seen[0] and "ui_prefs.value -> 'seen_at'" in seen[0]
    assert "RETURNING value" in seen[0]


def test_failed_write_returns_503_through_the_http_edge(prefs, monkeypatch):
    api, fake = prefs
    monkeypatch.setattr(api, "_home_last_seen_gate", lambda ctx=None: (200, None))
    monkeypatch.setattr(api, "_db_query_raising", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    status, body = api.handle("/api/v2/ui/prefs", "POST", {"key": "home.last_seen", "value": {"device": "phone"}})
    assert status == 503 and body["ok"] is False and body["code"] == "STORE_UNAVAILABLE"


def test_restamp_computes_ages_at_serve_time():
    body = HI.build(_db([]), now=NOW, classes=CLASSES)
    later = NOW + timedelta(seconds=30)
    out = HI.restamp(body, 30, now=later)
    assert out["served_at"] == later.isoformat() and out["snapshot"]["age_s"] == 30
    assert out["data_integrity_24h"]["age_s"] == 30 and body["snapshot"]["age_s"] == 0   # original untouched


def test_failure_bodies_name_owner_and_source():
    out = HI.build(_db(exc=RuntimeError("x")), now=NOW, classes=CLASSES)
    assert out["owner"] == "UNREGISTERED" and out["source_id"] == "alert_incidents"
