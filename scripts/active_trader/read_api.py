"""Active Trader Stage 4 — additive /api/v3/active-trader READ plane.

Transport-independent core (`App.request`) + stdlib http.server development
wrapper (the repository's existing HTTP framework — portfolio_server.py uses
stdlib http.server; no Flask/FastAPI exists in requirements, and no package may
be added). A later stage can mount the same App into another process unchanged.

Hard properties:
  * every route is GET; non-GET → 405; nothing mutates state;
  * reads ONLY trade_ai_test (read-only role) + committed fixtures/snapshots;
  * environment SHADOW/SIMULATION only — LIVE is unrepresentable here;
  * dev server: disabled by default, loopback-only, refuses production DB;
  * responses use the required envelope; errors never leak internals;
  * test identity comes from the app factory, never from a bare header.
"""
from __future__ import annotations

import json
import sys as _sys
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

_scripts_dir = str(Path(__file__).resolve().parents[1])
if _scripts_dir not in _sys.path:            # direct-script execution bootstrap
    _sys.path.insert(0, _scripts_dir)

from active_trader.contracts import DEFAULTS, FLAG_REGISTRY
from active_trader.read_queries import (
    MAX_LIMIT, DEFAULT_LIMIT, QueryError, ReadStore, check_range, load_snapshot,
    make_cursor, normalize_symbol, parse_cursor, parse_date, parse_limit,
)

API_VERSION = "v3"
SERVICE = "active-trader-read"
ROUTE_PREFIX = "/api/v3/active-trader"
CONTRACT_VERSION = "stage4-v1.0"
MAX_WARNINGS = 20
MAX_SOURCES = 10
MAX_RESPONSE_BYTES = 1_500_000
GENERAL_RATE = 120          # per minute per identity
HEAVY_RATE = 30             # journal, rejections, parity, symbol detail
HEAVY_ROUTES = ("journal", "rejections", "parity", "symbol")

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = REPO_ROOT / "docs/implementation/active-trader/20260722-01/stage-02/live_probe_result.json"
CANDIDATES_PATH = REPO_ROOT / "tests/fixtures/active_trader_read_api_candidates.json"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False,
                 operator_action: str = "review request"):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.retryable, self.operator_action = retryable, operator_action


class RateLimiter:
    def __init__(self, now: Callable[[], float] = time.monotonic):
        self._hits: dict[tuple, deque] = defaultdict(deque)
        self._now = now

    def check(self, identity: str, route_class: str) -> None:
        limit = HEAVY_RATE if route_class == "heavy" else GENERAL_RATE
        key = (identity, route_class)
        now = self._now()
        dq = self._hits[key]
        while dq and now - dq[0] > 60.0:
            dq.popleft()
        if len(dq) >= limit:
            raise ApiError(429, "RATE_LIMITED", f"{route_class} read-rate limit exceeded",
                           retryable=True, operator_action="slow down; retry after backoff")
        dq.append(now)


class Metrics:
    def __init__(self):
        self.counters = defaultdict(int)
        self.latency_ms = defaultdict(list)

    def record(self, endpoint: str, status: int, ms: float, warnings: int):
        self.counters[f"requests.{endpoint}"] += 1
        self.counters[f"status.{status}"] += 1
        self.counters["warnings.total"] += warnings
        if status == 429:
            self.counters["rate_limited"] += 1
        self.latency_ms[endpoint].append(round(ms, 2))


class App:
    """Factory-built read-only application. Environment is SHADOW or SIMULATION."""

    def __init__(self, dsn: str, environment: str = "SHADOW",
                 identities: tuple = ("dev-operator",), allowed_origin: Optional[str] = None,
                 now: Optional[Callable[[], datetime]] = None,
                 snapshot_path: Path = SNAPSHOT_PATH, candidates_path: Path = CANDIDATES_PATH,
                 source_sha: str = "unknown"):
        if environment not in ("SHADOW", "SIMULATION"):
            raise ApiError(403, "ENVIRONMENT_FORBIDDEN",
                           "read API may only run in SHADOW or SIMULATION")
        if allowed_origin == "*":
            raise ApiError(403, "CORS_FORBIDDEN", "wildcard CORS is not permitted")
        self.env = environment
        self.identities = set(identities)
        self.allowed_origin = allowed_origin
        self.store = ReadStore(dsn)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.snapshot_path = snapshot_path
        self.candidates_path = candidates_path
        self.source_sha = source_sha
        self.limiter = RateLimiter()
        self.metrics = Metrics()
        self.started = time.monotonic()

    # ---------------------------------------------------------------- envelope
    def _envelope(self, request_id: str, data, sources: list, warnings: list) -> dict:
        return {"api_version": API_VERSION, "service": SERVICE, "environment": self.env,
                "request_id": request_id, "generated_at": self.now().isoformat(),
                "data_as_of": max([s.get("observed_at") or "" for s in sources] or [""]) or None,
                "source_sha": self.source_sha, "sources": sources[:MAX_SOURCES],
                "warnings": warnings[:MAX_WARNINGS], "data": data}

    def _error(self, request_id: str, err: ApiError) -> dict:
        return {"api_version": API_VERSION, "service": SERVICE, "request_id": request_id,
                "generated_at": self.now().isoformat(),
                "error": {"code": err.code, "message": err.message,
                          "retryable": err.retryable, "operator_action": err.operator_action},
                "warnings": []}

    def _db_source(self, table: str) -> dict:
        return {"source_name": f"lab:{table}", "source_type": "LAB_DATABASE",
                "observed_at": self.now().isoformat(), "expires_at": None,
                "freshness_state": "FRESH", "evidence_ref": None}

    # ---------------------------------------------------------------- request
    def request(self, method: str, path: str, query: Optional[dict] = None,
                headers: Optional[dict] = None) -> tuple[int, dict, dict]:
        query = query or {}
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        request_id = str(uuid.uuid4())
        t0 = time.monotonic()
        endpoint = "unknown"
        try:
            if not path.startswith(ROUTE_PREFIX):
                raise ApiError(404, "NOT_FOUND", "unknown route")
            sub = path[len(ROUTE_PREFIX):].strip("/")
            endpoint = (sub.split("/") or ["root"])[0] or "root"
            if method.upper() != "GET":
                raise ApiError(405, "METHOD_NOT_ALLOWED", "this API is read-only (GET only)")
            identity = headers.get("x-at-test-identity", "")
            if identity not in self.identities:
                raise ApiError(401, "UNAUTHENTICATED",
                               "development identity missing or not registered in the app factory")
            route_class = "heavy" if endpoint in HEAVY_ROUTES else "general"
            self.limiter.check(identity, route_class)
            data, sources, warnings = self._dispatch(sub, query)
            body = self._envelope(request_id, data, sources, warnings)
            raw = json.dumps(body, default=str)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ApiError(500, "RESPONSE_TOO_LARGE",
                               "response exceeded the size ceiling; narrow the query")
            out_headers = {"content-type": "application/json", "x-request-id": request_id}
            if self.allowed_origin and headers.get("origin") == self.allowed_origin:
                out_headers["access-control-allow-origin"] = self.allowed_origin
            self.metrics.record(endpoint, 200, (time.monotonic() - t0) * 1000, len(body["warnings"]))
            return 200, out_headers, body
        except ApiError as err:
            self.metrics.record(endpoint, err.status, (time.monotonic() - t0) * 1000, 0)
            return err.status, {"content-type": "application/json", "x-request-id": request_id}, \
                self._error(request_id, err)
        except QueryError as qe:
            err = ApiError(qe.status, qe.code, qe.message)
            self.metrics.record(endpoint, qe.status, (time.monotonic() - t0) * 1000, 0)
            return qe.status, {"content-type": "application/json", "x-request-id": request_id}, \
                self._error(request_id, err)
        except Exception:
            err = ApiError(500, "INTERNAL", "internal error", operator_action="check server logs")
            self.metrics.record(endpoint, 500, (time.monotonic() - t0) * 1000, 0)
            return 500, {"content-type": "application/json", "x-request-id": request_id}, \
                self._error(request_id, err)

    # ---------------------------------------------------------------- dispatch
    def _dispatch(self, sub: str, q: dict):
        parts = sub.split("/") if sub else []
        route = parts[0] if parts else ""
        if route == "health":
            return self._health()
        if route == "version":
            return self._version()
        if route == "session":
            return self._session()
        if route == "candidates":
            return self._candidates(q)
        if route == "symbol":
            if len(parts) != 2:
                raise ApiError(400, "INVALID_SYMBOL",
                               "symbol path must be /symbol/<symbol> with no extra segments")
            return self._symbol(parts[1])
        if route == "accounts":
            return self._accounts()
        if route == "brokers" and len(parts) == 1:
            return self._brokers()
        if route == "brokers" and parts[1:] == ["capabilities"]:
            return self._capabilities(q)
        if route == "rejections":
            return self._rejections(q)
        if route == "notifications":
            return self._notifications(q)
        if route == "orders":
            return self._orders(q)
        if route == "positions":
            return self._positions(q)
        if route == "journal":
            return self._journal(q)
        if route == "features":
            return self._features()
        if route == "parity":
            return self._parity()
        raise ApiError(404, "NOT_FOUND", "unknown route")

    # ---------------------------------------------------------------- handlers
    def _health(self):
        h = self.store.health()
        data = {"process_state": "RUNNING", "environment": self.env,
                "test_database": {"connected": True, **h},
                "source_sha": self.source_sha, "feature_mode": "READ_ONLY",
                "uptime_seconds": round(time.monotonic() - self.started, 1),
                "dependencies": {"lab_database": "OK",
                                 "snapshot": "OK" if self.snapshot_path.exists() else "UNAVAILABLE",
                                 "moomoo": "NOT_INSTALLED"},
                "production_access": "DISABLED"}
        return data, [self._db_source("health")], []

    def _version(self):
        data = {"architecture_version": "v3.3", "program_version": "v1.1",
                "api_version": API_VERSION, "contract_version": CONTRACT_VERSION,
                "code_sha": self.source_sha,
                "schema_migration_versions": self.store.migration_versions(),
                "contract_versions": {"classifier": "stage3-v1.0", "read_api": CONTRACT_VERSION},
                "build_time": None}
        return data, [self._db_source("active_trader_schema_migrations")], []

    def _session(self):
        s = self.store.session()
        if s is None:
            return ({"session_state": "NO_SESSION", "environment": self.env,
                     "selected_accounts": [], "authorization_state": "NONE"},
                    [self._db_source("active_trader_session_authorizations")],
                    [{"category": "UNAVAILABLE", "detail": "no session exists in the test projection"}])
        return s, [self._db_source("active_trader_session_authorizations")], []

    def _candidates(self, q):
        limit = parse_limit(q.get("limit"))
        offset = parse_cursor(q.get("cursor"))
        data, src = load_snapshot(self.candidates_path, self.now())
        rows = data.get("candidates", [])
        for f in ("state", "symbol", "broker"):
            if q.get(f):
                rows = [r for r in rows if str(r.get(f, "")).upper() == q[f].upper()]
        sort = q.get("sort", "symbol")
        if sort not in ("symbol", "state", "rvol"):
            raise QueryError(422, "INVALID_SORT", "sort must be one of symbol|state|rvol")
        rows = sorted(rows, key=lambda r: (r.get(sort) is None, r.get(sort)))
        page = rows[offset:offset + limit]
        warnings = [{"category": "UNAVAILABLE",
                     "detail": "microstructure fields unavailable before Stage 5 (Moomoo data plane)"}]
        if src["freshness_state"] in ("STALE", "AGING"):
            warnings.append({"category": "STALE", "detail": "candidate fixture is not fresh"})
        out = {"items": page,
               "next_cursor": make_cursor(offset + limit) if len(rows) > offset + limit else None}
        return out, [src], warnings

    def _symbol(self, raw_symbol):
        symbol = normalize_symbol(raw_symbol)
        cand, src = load_snapshot(self.candidates_path, self.now())
        match = next((c for c in cand.get("candidates", []) if c.get("symbol") == symbol), None)
        rejections = self.store.rejections({"symbol": symbol}, None, None, 10, 0)
        caps = self.store.capabilities({}, 50, 0, self.now())
        warnings = []
        if match is None:
            warnings.append({"category": "UNAVAILABLE",
                             "detail": f"{symbol} not in the candidate fixture; identity-only view"})
        warnings.append({"category": "NOT_INSTALLED",
                         "detail": "microstructure requires the Stage 5 Moomoo data plane"})
        data = {"symbol": symbol, "identity": match or {"symbol": symbol},
                "capital_structure": (match or {}).get("capital_structure", "UNAVAILABLE"),
                "participation": (match or {}).get("participation", "UNAVAILABLE"),
                "price_structure": (match or {}).get("price_structure", "UNAVAILABLE"),
                "microstructure": "UNAVAILABLE",
                "catalyst": (match or {}).get("catalyst", "UNAVAILABLE"),
                "eligibility": (match or {}).get("eligibility", "UNKNOWN"),
                "account_capability_rows": len(caps),
                "rejection_history": rejections, "source_conflicts": []}
        return data, [src, self._db_source("broker_rejection_events")], warnings

    def _accounts(self):
        snap, src = load_snapshot(self.snapshot_path, self.now())
        accounts = snap.get("projection", {}).get("accounts", [])
        discrepancies = snap.get("projection", {}).get("discrepancies", [])
        warnings = []
        if src["freshness_state"] != "FRESH":
            warnings.append({"category": "STALE", "detail": "discovery snapshot is not fresh"})
        if discrepancies:
            warnings.append({"category": "CONFLICT",
                             "detail": f"{len(discrepancies)} configuration discrepancies recorded"})
        items = [{"account_label": a["account_label"], "masked_account_id": a["masked_account_id"],
                  "broker": a["broker"], "environment": a["environment"],
                  "account_type": a["account_type"], "status": a["status"],
                  "read_state": a["read_state"], "authentication_state": a["authentication_state"],
                  "buying_power": a.get("evidence", {}).get("buying_power_present") and "PRESENT_IN_SNAPSHOT" or "UNAVAILABLE",
                  "positions_summary": "UNAVAILABLE", "open_orders_summary": "UNAVAILABLE",
                  "active_trader_eligible": a["broker"] in ("alpaca", "moomoo", "schwab"),
                  "capability_summary": {c["state"]: sum(1 for x in a.get("capabilities", [])
                                                        if x["state"] == c["state"])
                                         for c in a.get("capabilities", [])},
                  "observed_at": a.get("observed_at"), "expires_at": a.get("expires_at") or None}
                 for a in accounts]
        return ({"items": items, "discrepancies": discrepancies},
                [src, self._db_source("broker_account_capabilities")], warnings)

    def _brokers(self):
        snap, src = load_snapshot(self.snapshot_path, self.now())
        states = {b["broker"]: b for b in snap.get("broker_states", [])}
        data = {"alpaca": states.get("alpaca", {"connector_state": "UNAVAILABLE"}),
                "schwab": states.get("schwab", {"connector_state": "UNAVAILABLE"}),
                "moomoo": states.get("moomoo", {"connector_state": "NOT_INSTALLED",
                                                "account_discovery": "UNAVAILABLE"}),
                "excluded_from_active_trader_v1": ["snaptrade", "fidelity", "tastytrade"]}
        warnings = [{"category": "NOT_INSTALLED", "detail": "moomoo connector is not installed (Stage 5)"}]
        return data, [src], warnings

    def _capabilities(self, q):
        limit = parse_limit(q.get("limit"))
        offset = parse_cursor(q.get("cursor"))
        rows = self.store.capabilities(
            {k: q.get(k) for k in ("broker", "account", "capability", "state")},
            limit, offset, self.now())
        page = rows[:limit]
        warnings = []
        if any(r["expired"] for r in page):
            warnings.append({"category": "STALE",
                             "detail": "expired evidence resolves to UNKNOWN per Stage 2 contract"})
        return ({"items": page,
                 "next_cursor": make_cursor(offset + limit) if len(rows) > limit else None},
                [self._db_source("broker_account_capabilities")], warnings)

    def _rejections(self, q):
        limit = parse_limit(q.get("limit"))
        offset = parse_cursor(q.get("cursor"))
        frm, to = parse_date(q.get("from"), "from"), parse_date(q.get("to"), "to")
        check_range(frm, to)
        rows = self.store.rejections(
            {k: q.get(k) for k in ("broker", "account", "symbol", "normalized_code",
                                   "requires_operator", "requires_broker_call")},
            frm, to, limit, offset)
        page = rows[:limit]
        return ({"items": page,
                 "next_cursor": make_cursor(offset + limit) if len(rows) > limit else None},
                [self._db_source("broker_rejection_events")],
                [{"category": "REDACTED", "detail": "raw broker payloads are stored redacted"}])

    def _notifications(self, q):
        limit = parse_limit(q.get("limit"))
        offset = parse_cursor(q.get("cursor"))
        frm, to = parse_date(q.get("from"), "from"), parse_date(q.get("to"), "to")
        check_range(frm, to)
        rows = self.store.notifications({k: q.get(k) for k in ("status", "severity")},
                                        frm, to, limit, offset)
        page = rows[:limit]
        return ({"items": page,
                 "next_cursor": make_cursor(offset + limit) if len(rows) > limit else None},
                [self._db_source("active_trader_notification_events")], [])

    def _orders(self, q):
        limit = parse_limit(q.get("limit"))
        offset = parse_cursor(q.get("cursor"))
        rows = self.store.orders({k: q.get(k) for k in ("account", "broker", "symbol",
                                                        "state", "environment")}, limit, offset)
        page = rows[:limit]
        return ({"items": page,
                 "next_cursor": make_cursor(offset + limit) if len(rows) > limit else None},
                [self._db_source("active_trader_order_intents")],
                [{"category": "UNVERIFIED", "detail": "test/shadow projections; no live order refresh"}])

    def _positions(self, q):
        limit = parse_limit(q.get("limit"))
        offset = parse_cursor(q.get("cursor"))
        rows = self.store.positions(limit, offset)
        page = [r | {"cost_basis": "UNAVAILABLE", "mark": "UNAVAILABLE",
                     "mark_source": "UNAVAILABLE", "mark_timestamp": None,
                     "unrealized_pnl": "UNAVAILABLE", "realized_pnl": "UNAVAILABLE",
                     "total_pnl": "UNAVAILABLE", "mfe": "UNAVAILABLE", "mae": "UNAVAILABLE",
                     "runner_state": r["state"] if "RUNNER" in r["state"] else "NONE",
                     "working_orders": "UNAVAILABLE"} for r in rows[:limit]]
        return ({"items": page,
                 "next_cursor": make_cursor(offset + limit) if len(rows) > limit else None},
                [self._db_source("active_trader_position_states")],
                [{"category": "UNAVAILABLE", "detail": "marks/P&L require later market-data stages"}])

    def _journal(self, q):
        limit = parse_limit(q.get("limit"))
        offset = parse_cursor(q.get("cursor"))
        frm, to = parse_date(q.get("from"), "from"), parse_date(q.get("to"), "to")
        check_range(frm, to)
        rows = self.store.journal({k: q.get(k) for k in ("session", "symbol", "event_type")},
                                  frm, to, limit, offset)
        page = rows[:limit]
        return ({"items": page,
                 "next_cursor": make_cursor(offset + limit) if len(rows) > limit else None},
                [self._db_source("active_trader_journal_events")],
                [{"category": "REDACTED",
                  "detail": "journal returns replay REFERENCES only; raw replay is never inlined"}])

    def _features(self):
        db_rows = {(r["flag_name"], r["scope_key"]): r for r in self.store.feature_rows()}
        items = []
        for name in FLAG_REGISTRY:
            row = db_rows.get((name, "global"))
            items.append({"flag_name": name,
                          "production_effective_mode": DEFAULTS["production"][name].value,
                          "test_effective_mode": (row or {}).get("mode", DEFAULTS["test"][name].value),
                          "development_default": DEFAULTS["development"][name].value,
                          "version": (row or {}).get("version"),
                          "source": "lab_db" if row else "stage1_defaults"})
        assert all(i["production_effective_mode"] == "OFF" for i in items)
        return ({"items": items, "mutable_via_this_api": False},
                [self._db_source("active_trader_feature_flags")], [])

    def _parity(self):
        checks = self.store.parity_checks(50)
        data = {"parity_state": "BASELINE_ONLY" if checks else "NOT_STARTED",
                "note": "/v3-next does not exist yet; no UI parity is claimed",
                "checks": checks}
        return data, [self._db_source("active_trader_parity_checks")], \
            [{"category": "UNVERIFIED",
              "detail": "pre-/v3-next baseline; parity comparison begins at Stage 6+"}]


# ---------------------------------------------------------------- dev server

def main(argv=None) -> int:
    import argparse, os, sys
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8134)
    args = ap.parse_args(argv)

    if os.environ.get("ACTIVE_TRADER_READ_API_ENABLED", "").lower() != "true":
        print("read API disabled (set ACTIVE_TRADER_READ_API_ENABLED=true) — exiting without a listener")
        return 0
    env = os.environ.get("ACTIVE_TRADER_ENV", "")
    if env not in ("SHADOW", "SIMULATION"):
        print(f"ERROR: ACTIVE_TRADER_ENV must be SHADOW or SIMULATION (got {env!r})", file=sys.stderr)
        return 2
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("ERROR: non-loopback bind refused by policy", file=sys.stderr)
        return 2
    dsn = os.environ.get("ACTIVE_TRADER_READ_API_DSN", "")
    if not dsn:
        print("ERROR: ACTIVE_TRADER_READ_API_DSN missing (resolve via trade-ai-lab)", file=sys.stderr)
        return 2

    import subprocess
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                         cwd=REPO_ROOT).stdout.strip() or "unknown"
    app = App(dsn, environment=env, identities=(os.environ.get("ACTIVE_TRADER_TEST_IDENTITY",
                                                               "dev-operator"),), source_sha=sha)

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):  # no default access log (identifiers)
            pass

        def _serve(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            status, hdrs, body = app.request(self.command, u.path, q, dict(self.headers))
            raw = json.dumps(body, default=str).encode()
            self.send_response(status)
            for k, v in hdrs.items():
                self.send_header(k, v)
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"active-trader read API on http://{args.host}:{args.port}{ROUTE_PREFIX} env={env} (loopback only)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
