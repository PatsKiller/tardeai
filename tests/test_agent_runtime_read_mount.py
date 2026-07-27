"""Lane A — the read-only agent-runtime HTTP MOUNT boundary.

Proves the production mount (`read_http.dispatch` + the `agent_runtime_read_boot`
feature gate + the coordinated deploy script) keeps its zero-authority contract:

  * the HTTP route matchers exactly cover the canonical READ_ROUTES table;
  * every route is GET-only (non-GET -> 405);
  * a disconnected reader -> honest 503 zero-authority envelope;
  * a connected reader -> zero authority, real data, empty != fixture;
  * secret-bearing reader rows fail closed (no leak);
  * superuser / privileged DB roles are rejected (and do not crash the host);
  * the read SQL contains no mutating statements and never commits;
  * the feature gate defaults DISABLED;
  * the read module imports no driver / subprocess / http client / secret store;
  * the coordinated deploy script defaults to dry-run and rolls back backend+static.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

# NOTE: import via the `agent_runtime.*` package path (scripts/ is on sys.path via
# conftest) so these classes share identity with the ones agent_runtime_read_boot
# resolves at runtime inside portfolio_server — otherwise isinstance() checks would
# compare two distinct copies of the same class.
import agent_runtime_read_boot as boot
from agent_runtime import read_http
from agent_runtime.read_api import READ_ROUTES, ReadOnlyAgentRuntimeAPI
from agent_runtime.read_postgres import PostgresAgentRuntimeReader
from agent_runtime.persistence import RuntimeIdentityError

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = "ta:run:0123456789abcdef0123456789abcdef"

NON_GET_METHODS = ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeReader:
    """Minimal in-memory AgentRuntimeReader with clean rows."""

    def list_runs(self, *, limit, offset, agent_id=None, status=None):
        rows = [{"run_id": RUN, "agent_id": "tradeai.agent.sentinel", "status": "COMPLETED", "environment": "SHADOW"}]
        if agent_id is not None:
            rows = [r for r in rows if r["agent_id"] == agent_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return rows[offset:offset + limit]

    def get_run(self, run_id):
        return {"run_id": run_id, "status": "COMPLETED"}

    def list_artifacts(self, run_id):
        return [{"artifact_id": "art_1"}]

    def list_retrieval_evidence(self, run_id):
        return [{"sequence": 1, "event_type": "RETRIEVAL_COMPLETED"}]

    def list_tool_calls(self, run_id):
        return [{"tool_call_id": "tool_1", "decision": "ALLOW"}]

    def list_reviews(self, run_id):
        return [{"review_id": "rev_1", "verdict": "PASS"}]

    def list_scores(self, run_id):
        return [{"score_id": "score_1"}]

    def list_monitoring_events(self, run_id):
        return [{"sequence": 1, "event_type": "RUN_CREATED"}]


class EmptyReader(FakeReader):
    def list_runs(self, *, limit, offset, agent_id=None, status=None):
        return []


class LeakyReader(FakeReader):
    def list_tool_calls(self, run_id):
        return [{"tool_call_id": "t1", "api_token": "leaked-value"}]


def _api(reader=None):
    return ReadOnlyAgentRuntimeAPI(reader or FakeReader())


def _sample_path(route) -> str:
    return route.path.replace("{run_id}", RUN)


# --------------------------------------------------------------------------- #
# Route table <-> HTTP dispatcher parity
# --------------------------------------------------------------------------- #
def test_http_matchers_exactly_cover_the_canonical_route_table():
    matcher_ops = [route.operation for route, _ in read_http.ROUTE_MATCHERS]
    assert matcher_ops == [route.operation for route in READ_ROUTES]
    # every declared path is matched by exactly one matcher, and to its own route
    for route in READ_ROUTES:
        matched, params = read_http._match(_sample_path(route))
        assert matched is route, f"{route.path} did not resolve to its own operation"
        if "{run_id}" in route.path:
            assert params.get("run_id") == RUN


def test_every_route_dispatches_to_the_matching_api_operation():
    api = _api()
    for route in READ_ROUTES:
        status, body = read_http.dispatch(api, "GET", _sample_path(route), {})
        assert status == 200, route.path
        assert body["read_only"] is True
        assert all(v is False for v in body["authority"].values())


# --------------------------------------------------------------------------- #
# GET-only enforcement
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", NON_GET_METHODS)
def test_all_routes_are_get_only_non_get_is_405(method):
    api = _api()
    for route in READ_ROUTES:
        status, body = read_http.dispatch(api, method, _sample_path(route), {})
        assert status == 405, f"{method} {route.path} should be 405"
        assert body["read_only"] is True
        assert all(v is False for v in body["authority"].values())
        assert body["data"] is None


def test_unknown_agent_runtime_path_is_404_not_a_write():
    status, body = read_http.dispatch(_api(), "GET", "/api/v3/agent-runtime/bogus", {})
    assert status == 404 and body["read_only"] is True


def test_non_agent_runtime_path_is_not_owned():
    assert read_http.dispatch(_api(), "GET", "/api/v2/holdings", {}) is None


# --------------------------------------------------------------------------- #
# Disconnected reader -> honest 503
# --------------------------------------------------------------------------- #
def test_disconnected_reader_returns_honest_503_envelope():
    for route in READ_ROUTES:
        status, body = read_http.dispatch(None, "GET", _sample_path(route), {})
        assert status == 503
        assert body["read_only"] is True
        assert body["data"] is None
        assert all(v is False for v in body["authority"].values())


# --------------------------------------------------------------------------- #
# Connected reader -> zero authority; empty != fixture
# --------------------------------------------------------------------------- #
def test_connected_reader_has_zero_authority():
    status, body = read_http.dispatch(_api(), "GET", "/api/v3/agent-runtime/runs", {"limit": ["5"]})
    assert status == 200
    assert body["read_only"] is True
    assert body["kind"] == "runs"
    assert all(v is False for v in body["authority"].values())
    assert isinstance(body["data"], list) and body["data"][0]["run_id"] == RUN


def test_empty_connected_data_is_not_the_fixture():
    status, body = read_http.dispatch(_api(EmptyReader()), "GET", "/api/v3/agent-runtime/runs", {})
    assert status == 200
    assert body["read_only"] is True
    assert body["data"] == []  # honest empty listing, not a hardcoded fixture snapshot
    assert body["contract"] == "agent-runtime-command-center-read-api-v1"


def test_bounded_limit_is_clamped_and_bad_pagination_fails_closed():
    # oversized limit is clamped to MAX_LIMIT and still returns a valid listing
    status, body = read_http.dispatch(_api(), "GET", "/api/v3/agent-runtime/runs", {"limit": ["100000"]})
    assert status == 200 and body["read_only"] is True
    # non-numeric pagination fails closed with no data leak
    status, body = read_http.dispatch(_api(), "GET", "/api/v3/agent-runtime/runs", {"limit": ["abc"]})
    assert status == 400 and body["data"] is None and body["read_only"] is True


# --------------------------------------------------------------------------- #
# Secret-bearing rows fail closed
# --------------------------------------------------------------------------- #
def test_secret_bearing_rows_fail_closed_with_no_leak():
    status, body = read_http.dispatch(_api(LeakyReader()), "GET", f"/api/v3/agent-runtime/runs/{RUN}/tool-calls", {})
    assert status != 200
    assert body["read_only"] is True and body["data"] is None
    assert "leaked-value" not in json.dumps(body)


# --------------------------------------------------------------------------- #
# Privileged DB roles rejected — and it does not crash the host
# --------------------------------------------------------------------------- #
class _RoleCursor:
    def __init__(self, conn):
        self.conn = conn
        self._r = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SET TRANSACTION READ ONLY"):
            self.conn.read_only = True
        elif s.startswith("SELECT current_user, rolsuper"):
            self._r = [(self.conn.user, *self.conn.flags)]

    def fetchone(self):
        return self._r[0] if self._r else None

    def fetchall(self):
        return list(self._r)

    def close(self):
        pass


class _RoleConn:
    def __init__(self, user, flags):
        self.user, self.flags = user, flags
        self.read_only = False
        self.commits = 0

    def cursor(self):
        return _RoleCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _role_factory(user, flags):
    return lambda: _RoleConn(user, flags)


def test_superuser_reader_is_rejected_at_the_reader_and_yields_503_not_a_crash():
    # direct reader assertion: superuser flag is rejected
    reader = PostgresAgentRuntimeReader(_role_factory("agentic_runtime_lab_ro", (True, False, False, False, False)))
    with pytest.raises(RuntimeIdentityError):
        reader.get_run(RUN)
    # non-allowlisted role rejected
    reader2 = PostgresAgentRuntimeReader(_role_factory("postgres", (False, False, False, False, False)))
    with pytest.raises(RuntimeIdentityError):
        reader2.get_run(RUN)
    # through the mount: a privileged reader collapses to the honest 503, never a crash
    api = ReadOnlyAgentRuntimeAPI(
        PostgresAgentRuntimeReader(_role_factory("agentic_runtime_lab_ro", (False, True, False, False, False)))
    )
    status, body = read_http.dispatch(api, "GET", "/api/v3/agent-runtime/runs", {})
    assert status == 503 and body["read_only"] is True and body["data"] is None


# --------------------------------------------------------------------------- #
# Read SQL has no mutations; API cannot commit
# --------------------------------------------------------------------------- #
def test_read_postgres_source_has_no_mutating_sql():
    src = (ROOT / "scripts" / "agent_runtime" / "read_postgres.py").read_text().upper()
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE ", "ALTER ", "GRANT ", "CREATE "):
        assert verb not in src, f"read reader must not contain mutating SQL: {verb.strip()}"
    assert "SET TRANSACTION READ ONLY" in src
    assert ".COMMIT(" not in src and "CONN.COMMIT" not in src


def test_reader_never_commits_through_the_mount():
    conns = []

    class _Cur:
        def __init__(self, c):
            self.c = c
            self._r = []

        def execute(self, sql, params=()):
            s = " ".join(sql.split())
            if s.startswith("SET TRANSACTION READ ONLY"):
                self.c.read_only = True
            elif s.startswith("SELECT current_user, rolsuper"):
                self._r = [("agentic_runtime_lab_ro", False, False, False, False, False)]
            elif "FROM AGENTIC_RUNTIME.AGENT_RUNS" in s.upper():
                self._r = []

        def fetchall(self):
            return list(self._r)

        def fetchone(self):
            return self._r[0] if self._r else None

        def close(self):
            pass

    class _Conn:
        def __init__(self):
            self.read_only = False
            self.commits = 0
            conns.append(self)

        def cursor(self):
            return _Cur(self)

        def commit(self):
            self.commits += 1

        def rollback(self):
            pass

        def close(self):
            pass

    api = ReadOnlyAgentRuntimeAPI(PostgresAgentRuntimeReader(lambda: _Conn()))
    status, _ = read_http.dispatch(api, "GET", "/api/v3/agent-runtime/runs", {})
    assert status == 200
    assert conns and all(c.commits == 0 for c in conns), "read path must never commit"


# --------------------------------------------------------------------------- #
# Feature gate defaults disabled
# --------------------------------------------------------------------------- #
def test_gate_defaults_disabled_and_requires_dsn():
    assert boot.build_api(env={}) is None  # gate unset -> disabled
    assert boot.build_api(env={"AGENT_RUNTIME_READ_API": "0"}) is None  # explicit off
    assert boot.build_api(env={"AGENT_RUNTIME_READ_API": "1"}) is None  # on but no DSN -> still None
    # on + DSN + injected reader -> a real ReadOnlyAgentRuntimeAPI (no driver needed)
    api = boot.build_api(
        env={"AGENT_RUNTIME_READ_API": "1", "AGENT_RUNTIME_READ_DSN": "postgresql://reader@localhost/trade_ai"},
        reader_factory=lambda dsn: FakeReader(),
    )
    assert isinstance(api, ReadOnlyAgentRuntimeAPI)


def test_boot_handle_with_gate_off_returns_503():
    boot.reset_for_test()
    result = boot.handle("GET", "/api/v3/agent-runtime/runs", {})
    assert result is not None
    status, body = result
    assert status == 503 and body["read_only"] is True
    boot.reset_for_test()


# --------------------------------------------------------------------------- #
# Authority scan — no driver / subprocess / http client / secret store
# --------------------------------------------------------------------------- #
def test_read_plane_modules_import_no_forbidden_authority():
    forbidden = re.compile(r"^\s*(?:import|from)\s+(psycopg2|subprocess|requests|keyring)\b", re.M)
    pkg = ROOT / "scripts" / "agent_runtime"
    for py in pkg.glob("*.py"):
        text = py.read_text()
        hit = forbidden.search(text)
        assert hit is None, f"{py.name} imports forbidden authority: {hit.group(1) if hit else ''}"
    # read_http specifically owns the framework-neutral surface
    assert not forbidden.search((pkg / "read_http.py").read_text())


# --------------------------------------------------------------------------- #
# No permissive CORS in the dedicated emitter
# --------------------------------------------------------------------------- #
def test_agent_runtime_emitter_is_same_origin_no_permissive_cors():
    server_src = (ROOT / "scripts" / "portfolio_server.py").read_text()
    emitter = server_src.split("def _send_agent_runtime_json", 1)[1].split("def _content_type_for_path", 1)[0]
    # No actual permissive-CORS header emission (prose in the docstring is fine).
    assert 'send_header("Access-Control-Allow-Origin"' not in emitter, "read emitter must not send permissive CORS"
    assert "no-store" in emitter


# --------------------------------------------------------------------------- #
# Coordinated deploy script: dry-run default + backend/static rollback
# --------------------------------------------------------------------------- #
def test_coordinated_deploy_script_defaults_dry_run_and_rolls_back_both():
    script = ROOT / "scripts" / "agent_runtime" / "deploy_read_mount.sh"
    text = script.read_text()
    assert "set -euo pipefail" in text
    assert "--dry-run" in text and "EXECUTE=0" in text  # dry-run by default
    assert 'HEAD_SHA' in text and "!= expected" in text and "refuse to deploy" in text
    # backups of BOTH backend and static
    assert "BACKEND_BACKUP" in text and "STATIC_BACKUP" in text
    # explicit operator acknowledgement before any restart
    assert "operator acknowledgement" in text.lower() and "read -r ACK" in text
    # exactly ONE named service restart
    assert text.count("systemctl restart") <= 3  # swap + rollback + rollback-verify only
    assert "RESTART_SERVICE" in text
    # rollback restores backend AND static, then re-verifies health
    rb = text.split("rollback()", 1)[1].split("# ---- swap", 1)[0]
    assert "restored backend" in rb and "restored static" in rb and "post-rollback health" in rb
    # smokes present
    lower = text.lower()
    assert "index health smoke" in lower and "/v3/agents" in text and "authority-envelope smoke" in lower

    forbidden_migration = ("psql -f", "alembic", "migrate ", "createrole", "create role")
    for bad in forbidden_migration:
        assert bad not in lower, f"deploy must not perform DB migration/role work: {bad}"
