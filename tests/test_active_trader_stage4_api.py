"""Stage 4 read-API tests — app factory + direct App.request test client.

Requires ACTIVE_TRADER_READ_API_DSN (read-only lab identity) and
ACTIVE_TRADER_TEST_DATABASE_DSN (write identity, fixture loading only).
Skipped with explicit reasons when absent. No live broker calls.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

RO_DSN = os.environ.get("ACTIVE_TRADER_READ_API_DSN", "")
RW_DSN = os.environ.get("ACTIVE_TRADER_TEST_DATABASE_DSN", "")
pytestmark = pytest.mark.skipif(
    not (RO_DSN and RW_DSN),
    reason="lab DSNs not set (read-only + write identities required; never runs on production)")

psycopg2 = pytest.importorskip("psycopg2")

from active_trader.read_api import ApiError, App, ROUTE_PREFIX  # noqa: E402

IDENTITY = {"x-at-test-identity": "test-op"}
ROUTES = ["health", "version", "session", "candidates", "symbol/TESTA", "accounts",
          "brokers", "brokers/capabilities", "rejections", "notifications", "orders",
          "positions", "journal", "features", "parity"]


@pytest.fixture(scope="module", autouse=True)
def fixtures_loaded():
    env = {**os.environ, "ACTIVE_TRADER_TEST_DATABASE_DSN": RW_DSN}
    for cmd in (["scripts/active_trader/migrate.py", "up"],
                ["scripts/active_trader/load_read_fixtures.py"]):
        r = subprocess.run([sys.executable, str(REPO / cmd[0]), *cmd[1:]],
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr + r.stdout


@pytest.fixture(scope="module")
def app():
    a = App(RO_DSN, environment="SHADOW", identities=("test-op",), source_sha="test-sha")
    yield a
    a.store.close()


def get(app, path, query=None, headers=IDENTITY, method="GET"):
    return app.request(method, f"{ROUTE_PREFIX}/{path}" if path else ROUTE_PREFIX,
                       query or {}, headers)


# ---------------- 17.1 routing
def test_every_required_route_returns_200(app):
    for route in ROUTES:
        status, hdrs, body = get(app, route)
        assert status == 200, f"{route}: {status} {body.get('error')}"
        assert body["api_version"] == "v3" and body["service"] == "active-trader-read"


def test_unknown_route_and_prefix_exact(app):
    assert get(app, "does-not-exist")[0] == 404
    status, _, _ = app.request("GET", "/api/v3/other-thing/health", {}, IDENTITY)
    assert status == 404


def test_trailing_slash_tolerated(app):
    status, _, _ = app.request("GET", f"{ROUTE_PREFIX}/health/", {}, IDENTITY)
    assert status == 200


def test_all_non_get_methods_405(app):
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for route in ("health", "features", "notifications", "orders"):
            status, _, body = get(app, route, method=method)
            assert status == 405 and body["error"]["code"] == "METHOD_NOT_ALLOWED"


# ---------------- 17.2 environment and startup
def test_live_environment_unrepresentable():
    with pytest.raises(ApiError, match="SHADOW or SIMULATION"):
        App(RO_DSN, environment="LIVE")


def test_simulation_environment_allowed():
    a = App(RO_DSN, environment="SIMULATION", identities=("t",))
    assert get(a, "health", headers={"x-at-test-identity": "t"})[2]["environment"] == "SIMULATION"
    a.store.close()


def test_production_database_refused():
    from active_trader.migrate import MigrationError
    with pytest.raises(MigrationError):
        App("postgresql://u:p@localhost:5432/trade_ai", environment="SHADOW")
    with pytest.raises(MigrationError):
        App("", environment="SHADOW")           # missing DSN — no fallback


def test_dev_server_default_disabled_and_bind_policy():
    env = {**os.environ, "ACTIVE_TRADER_READ_API_ENABLED": ""}
    r = subprocess.run([sys.executable, str(REPO / "scripts/active_trader/read_api.py")],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0 and "disabled" in r.stdout and "exiting" in r.stdout
    env2 = {**os.environ, "ACTIVE_TRADER_READ_API_ENABLED": "true",
            "ACTIVE_TRADER_ENV": "LIVE"}
    r2 = subprocess.run([sys.executable, str(REPO / "scripts/active_trader/read_api.py")],
                        capture_output=True, text=True, env=env2, timeout=30)
    assert r2.returncode == 2 and "SHADOW or SIMULATION" in r2.stderr
    env3 = {**os.environ, "ACTIVE_TRADER_READ_API_ENABLED": "true",
            "ACTIVE_TRADER_ENV": "SHADOW", "ACTIVE_TRADER_READ_API_DSN": RO_DSN}
    r3 = subprocess.run([sys.executable, str(REPO / "scripts/active_trader/read_api.py"),
                         "--host", "0.0.0.0"], capture_output=True, text=True, env=env3, timeout=30)
    assert r3.returncode == 2 and "non-loopback" in r3.stderr


# ---------------- 17.3 authentication and CORS
def test_missing_and_forged_identity_rejected(app):
    assert get(app, "health", headers={})[0] == 401
    assert get(app, "health", headers={"x-at-test-identity": "forged-header-user"})[0] == 401


def test_cors_disabled_by_default_and_localhost_profile(app):
    _, hdrs, _ = get(app, "health", headers={**IDENTITY, "origin": "http://127.0.0.1:5173"})
    assert "access-control-allow-origin" not in hdrs
    a = App(RO_DSN, environment="SHADOW", identities=("t",),
            allowed_origin="http://127.0.0.1:5173")
    _, h2, _ = get(a, "health", headers={"x-at-test-identity": "t",
                                         "origin": "http://127.0.0.1:5173"})
    assert h2["access-control-allow-origin"] == "http://127.0.0.1:5173"
    _, h3, _ = get(a, "health", headers={"x-at-test-identity": "t",
                                         "origin": "http://evil.example"})
    assert "access-control-allow-origin" not in h3
    a.store.close()
    with pytest.raises(ApiError, match="wildcard"):
        App(RO_DSN, environment="SHADOW", allowed_origin="*")


# ---------------- 17.4 response contracts
def test_success_and_error_envelopes(app):
    status, hdrs, body = get(app, "accounts")
    for key in ("api_version", "service", "environment", "request_id", "generated_at",
                "data_as_of", "source_sha", "sources", "warnings", "data"):
        assert key in body, key
    assert hdrs["x-request-id"] == body["request_id"]
    src = body["sources"][0]
    for key in ("source_name", "source_type", "observed_at", "expires_at",
                "freshness_state", "evidence_ref"):
        assert key in src, key
    status, _, err = get(app, "symbol/../etc")
    assert status == 400
    for key in ("error", "request_id", "generated_at", "warnings"):
        assert key in err
    assert set(err["error"]) == {"code", "message", "retryable", "operator_action"}


def test_no_internal_leakage_on_500(app, monkeypatch):
    monkeypatch.setattr(app.store, "health", lambda: 1 / 0)
    status, _, body = get(app, "health")
    assert status == 500 and body["error"]["message"] == "internal error"
    assert "Traceback" not in json.dumps(body) and "psycopg2" not in json.dumps(body)


# ---------------- 17.5 pagination and filtering
def test_cursor_pagination_deterministic(app):
    s1, _, b1 = get(app, "brokers/capabilities", {"limit": "2"})
    assert s1 == 200 and len(b1["data"]["items"]) == 2 and b1["data"]["next_cursor"]
    s2, _, b2 = get(app, "brokers/capabilities", {"limit": "2",
                                                  "cursor": b1["data"]["next_cursor"]})
    assert s2 == 200
    ids = lambda b: [(i["broker"], i["account_label"], i["capability"]) for i in b["data"]["items"]]
    assert not set(ids(b1)) & set(ids(b2))          # no overlap, deterministic ordering


def test_invalid_pagination_and_filters(app):
    assert get(app, "brokers/capabilities", {"limit": "0"})[0] == 422
    assert get(app, "brokers/capabilities", {"limit": "999"})[0] == 422
    assert get(app, "brokers/capabilities", {"cursor": "not-a-cursor"})[0] == 422
    assert get(app, "candidates", {"sort": "evil"})[0] == 422
    assert get(app, "rejections", {"from": "not-a-date"})[0] == 422
    assert get(app, "rejections", {"from": "2020-01-01T00:00:00Z",
                                   "to": "2026-01-01T00:00:00Z"})[0] == 422  # excessive range
    assert get(app, "rejections", {"from": "2026-02-01T00:00:00Z",
                                   "to": "2026-01-01T00:00:00Z"})[0] == 422  # to < from


def test_sql_injection_strings_stay_values(app):
    s, _, body = get(app, "rejections", {"symbol": "'; DROP TABLE broker_rejection_events;--"})
    assert s == 200 and body["data"]["items"] == []
    s2, _, _ = get(app, "orders", {"account": "x' OR '1'='1"})
    assert s2 == 200
    conn = psycopg2.connect(RW_DSN)
    cur = conn.cursor()
    cur.execute("""SELECT count(*) FROM information_schema.tables
                   WHERE table_name = 'broker_rejection_events'""")
    assert cur.fetchone()[0] == 1                   # table intact (not dropped)
    conn.close()


def test_symbol_validation(app):
    for bad in ("bad/../x", "AB CD", "a" * 20, "%2e%2e", "TE\x00ST"):
        assert get(app, f"symbol/{bad}")[0] == 400, bad
    assert get(app, "symbol/testa")[0] == 200       # conservative normalization upcases


# ---------------- 17.6 data integrity
def test_masked_ids_and_no_secrets_anywhere(app):
    bodies = [get(app, r)[2] for r in ("accounts", "orders", "positions")]
    # every account-identifier field served by the API is masked
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("masked_account_id", "account_number", "accountNumber"):
                    assert k == "masked_account_id", f"raw id field {k} served"
                    assert str(v).startswith("***"), f"unmasked identifier {v!r}"
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    for b in bodies:
        walk(b)
    blob = json.dumps(bodies, default=str)
    for word in ("postgresql://", "SCHWAB_APP", "refresh_token", "Bearer ",
                 "APCA-API", "BWS_", "authorization:"):
        assert word not in blob


def test_stale_capability_resolves_unknown(app):
    s, _, body = get(app, "brokers/capabilities", {"account": "fixture_acct",
                                                   "capability": "BRACKET_ORDER"})
    row = body["data"]["items"][0]
    assert row["recorded_state"] == "SUPPORTED" and row["effective_state"] == "UNKNOWN" \
        and row["expired"] is True
    assert any(w["category"] == "STALE" for w in body["warnings"])


def test_moomoo_not_installed_and_exclusions(app):
    s, _, body = get(app, "brokers")
    assert body["data"]["moomoo"]["connector_state"] == "NOT_INSTALLED"
    assert body["data"]["excluded_from_active_trader_v1"] == ["snaptrade", "fidelity", "tastytrade"]
    assert any(w["category"] == "NOT_INSTALLED" for w in body["warnings"])


def test_unknown_market_data_not_fabricated(app):
    s, _, body = get(app, "candidates")
    testb = next(c for c in body["data"]["items"] if c["symbol"] == "TESTB")
    assert testb["participation"] == "UNAVAILABLE" and testb["market_cap"] is None
    s2, _, sym = get(app, "symbol/TESTB")
    assert sym["data"]["microstructure"] == "UNAVAILABLE"


def test_parity_makes_no_ui_claim(app):
    s, _, body = get(app, "parity")
    assert body["data"]["parity_state"] in ("NOT_APPLICABLE", "NOT_STARTED", "BASELINE_ONLY")
    assert "no UI parity" in body["data"]["note"]


def test_journal_replay_references_only(app):
    s, _, body = get(app, "journal")
    assert s == 200
    for item in body["data"]["items"]:
        ref = item.get("replay_segment_ref")
        assert ref is None or ref.startswith("replay://")
    assert any(w["category"] == "REDACTED" for w in body["warnings"])


def test_session_and_features(app):
    s, _, body = get(app, "session")
    assert body["data"]["session_state"] in ("AUTHORIZED", "PENDING", "NO_SESSION")
    if body["data"]["session_state"] != "NO_SESSION":
        assert len(body["data"]["authorization_short_hash"]) <= 12
    s2, _, feats = get(app, "features")
    assert feats["data"]["mutable_via_this_api"] is False
    assert all(i["production_effective_mode"] == "OFF" for i in feats["data"]["items"])


# ---------------- 17.7 read-only database identity
def test_api_identity_cannot_write():
    conn = psycopg2.connect(RO_DSN)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM active_trader_journal_events")
    assert cur.fetchone()[0] >= 0                   # SELECT works
    for sql in ("INSERT INTO active_trader_parity_checks (parity_check_id, check_kind, matched) "
                "VALUES ('00000000-0000-4000-8000-00000000ffff','x',true)",
                "UPDATE broker_account_capabilities SET notes='hacked'",
                "DELETE FROM broker_rejection_events",
                "CREATE TABLE should_fail (id int)"):
        with pytest.raises(psycopg2.Error):
            cur.execute(sql)
        conn.rollback()
    cur.execute("SHOW statement_timeout")
    assert cur.fetchone()[0] == "5s"
    cur.execute("SELECT current_setting('default_transaction_read_only')")
    assert cur.fetchone()[0] == "on"
    conn.close()


# ---------------- 17.8 rate and resource controls
def test_rate_limits(app):
    a = App(RO_DSN, environment="SHADOW", identities=("rl",))
    h = {"x-at-test-identity": "rl"}
    for _ in range(30):
        assert get(a, "parity", headers=h)[0] in (200, 429)
    assert get(a, "parity", headers=h)[0] == 429            # heavy 30/min exhausted
    assert get(a, "health", headers=h)[0] == 200            # general pool separate
    for _ in range(119):
        get(a, "health", headers=h)
    assert get(a, "health", headers=h)[0] == 429            # general 120/min exhausted
    a.store.close()


def test_response_size_bound(app, monkeypatch):
    import active_trader.read_api as m
    monkeypatch.setattr(m, "MAX_RESPONSE_BYTES", 200)
    status, _, body = get(app, "accounts")
    assert status == 500 and body["error"]["code"] == "RESPONSE_TOO_LARGE"
    monkeypatch.undo()
