"""Command Center Tailscale-identity auth (2026-10-14, SPCX incident security review).

Hermetic: no network beyond 127.0.0.1 ephemeral ports opened by this test, no live token file,
no live decision log, api_v2 replaced by a recording fake (so a broken gate can never reach a real
route), env bootstrap stubbed so importing portfolio_server loads no credentials.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import cc_auth  # noqa: E402

ALLOWED = "john@jwwhiting.com"
TOKEN = "t" * 48


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for k in (cc_auth.ENFORCE_ENV, cc_auth.REPORT_ONLY_ENV, cc_auth.CONFIG_ENV):
        monkeypatch.delenv(k, raising=False)
    # never the host's live token file
    monkeypatch.setenv(cc_auth.TOKEN_FILE_ENV, str(tmp_path / "absent_cc_service_token"))


def _raw_committed() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "config" / "cc_auth.yaml").read_text(encoding="utf-8"))


def _cfg(tmp_path, *, report_only=False, enforce=True, step_up_mode=None, exempt=None, bypass=None,
         token_mode=0o600, write_token=True):
    raw = _raw_committed()
    sec = raw["cc_auth"]
    sec["enforce"] = enforce
    sec["report_only"] = report_only
    tok = tmp_path / "cc_service_token"
    if write_token:
        tok.write_text(TOKEN + "\n", encoding="utf-8")
        os.chmod(tok, token_mode)
    sec["service_token"]["file"] = str(tok)
    sec["decision_log"] = str(tmp_path / "decisions.jsonl")
    if exempt is not None:
        sec["service_exempt_paths"] = exempt
    if step_up_mode is not None:
        sec["step_up"]["mode"] = step_up_mode
    if bypass is not None:
        sec["step_up"]["service_token_bypass"] = bypass
    cfg = cc_auth.config_from_mapping(raw, source="test", apply_env=False)
    return cfg, cc_auth.ServiceTokenStore(cfg.token_file, cfg.token_min_length)


# ── committed config contract ───────────────────────────────────────────────

def test_committed_config_contract():
    cfg = cc_auth.load_config(ROOT / "config" / "cc_auth.yaml")
    assert cfg.load_error == ""
    assert cfg.enforce is True
    assert cfg.report_only is True  # rollout: packet step 6 flips it
    assert cfg.allowed_logins == frozenset({ALLOWED})
    assert cfg.identity_header == "Tailscale-User-Login"
    assert (cfg.service_host, cfg.service_port) == ("127.0.0.1", 7777)
    assert cfg.serve_proxy_enabled and cfg.serve_proxy_transport == "unix"
    assert (cfg.serve_proxy_host, cfg.serve_proxy_port) == ("127.0.0.1", 7779)  # tcp fallback
    assert cfg.step_up_mode == "enforce" and cfg.step_up_service_token_bypass is False
    import yaml
    committed_file = yaml.safe_load((ROOT / "config" / "cc_auth.yaml").read_text())["cc_auth"]["service_token"]["file"]
    assert committed_file.startswith("~/") and "trade-ai" not in committed_file  # outside the repo


def test_missing_config_fails_closed(tmp_path):
    cfg = cc_auth.load_config(tmp_path / "nope.yaml")
    assert cfg.load_error and cfg.enforce is True and cfg.report_only is False
    assert cfg.allowed_logins == frozenset()
    d = cc_auth.evaluate_request(cfg, "serve_proxy", "GET", "/", {"Tailscale-User-Login": ALLOWED},
                                 cc_auth.ServiceTokenStore(cfg.token_file))
    assert not d.allowed and d.status == 403


# ── step-up route inventory (exact list reported to the operator) ───────────

STEP_UP_EXPECTED = {
    ("POST", "/api/v2/broker-orders/pilot/arm"): "order_pilot",
    ("POST", "/api/v2/broker-orders/pilot/execute"): "order_pilot",
    ("POST", "/api/v2/broker-orders/pilot/cancel"): "order_pilot",
    ("POST", "/api/v2/broker-orders/approve"): "order_pilot",
    ("POST", "/api/v2/broker-orders/request-approval"): "order_pilot",
    ("POST", "/api/v2/broker-proposals/route"): "order_route",
    ("POST", "/api/v2/broker-proposals/route/confirm"): "order_route",
    ("POST", "/api/v2/broker-proposals/manual-submit"): "order_route",
    ("POST", "/api/v2/broker-proposals/promote-from-paper"): "order_route",
    ("POST", "/api/v2/snaptrade/trade/execute"): "order_execute",
    ("POST", "/api/v2/paper-trades/close"): "order_execute",
    ("POST", "/api/v2/atm/close-action"): "order_execute",
    ("POST", "/api/v2/paper-proposals/submit-paper"): "order_paper_submit",
    ("POST", "/api/v2/paper-proposals/submit-alpaca-paper"): "order_paper_submit",
    ("POST", "/api/v2/paper-proposals/submit-alpaca-paper-bracket"): "order_paper_submit",
    ("POST", "/api/v2/options/alpaca-paper/submit"): "order_paper_submit",
    ("POST", "/api/v2/options/alpaca-paper/promote-live-review"): "order_paper_submit",
    ("POST", "/api/v2/holdings/protective-stop"): "stop_change",
    ("POST", "/api/v2/holdings/protective-stop/confirm"): "stop_change",
    ("POST", "/api/v2/holdings/protective-stop/cancel"): "stop_change",
    ("POST", "/api/v2/holdings/synthetic-stop"): "stop_change",
    ("POST", "/api/v2/holdings/synthetic-stop/cancel"): "stop_change",
    ("POST", "/api/v2/atm/stop-trailing-control"): "stop_change",
    ("POST", "/api/v2/stop-confirmations/respond"): "stop_change",
    ("POST", "/api/v2/defense/intent/2fa"): "stop_change",
    ("POST", "/api/v2/admin/secrets"): "credential_change",
    ("POST", "/api/v2/admin/validate-secret"): "credential_change",
    ("POST", "/api/v2/admin/broker-account/api"): "credential_change",
    ("POST", "/api/v2/admin/brokers"): "credential_change",
    ("POST", "/api/v2/snaptrade/credentials"): "credential_change",
    ("POST", "/api/v2/broker-accounts/api-read-toggle"): "credential_change",
    ("POST", "/api/v2/admin/risk-config"): "risk_control_change",
    ("POST", "/api/v2/admin/broker-account/policy"): "risk_control_change",
    ("POST", "/api/v2/broker-accounts/automation-policy"): "risk_control_change",
    ("POST", "/api/v2/execution/kill-switches/disable"): "risk_control_change",
    ("POST", "/api/v2/live-trading-gate"): "risk_control_change",
    ("POST", "/api/v2/entry-desk/automation"): "risk_control_change",
    ("POST", "/api/v2/portfolio/stop-policy-migration"): "risk_control_change",
}

NOT_STEP_UP = [
    # Operator 2026-10-21 "Exempt reauth only": Schwab reauth left step-up (TOTP was never built).
    ("GET", "/api/v2/brokers/schwab/reauth-url"),
    ("POST", "/api/v2/brokers/schwab/exchange-code"),
    ("GET", "/api/v2/broker-orders/pilot/status"),
    ("POST", "/api/v2/broker-orders/pilot/preflight"),
    ("POST", "/api/v2/broker-orders/pilot/disarm"),  # safe direction stays available
    ("POST", "/api/v2/broker-orders/preview"),
    ("GET", "/api/v2/holdings/live-stops"),
    ("POST", "/api/v2/holdings/protective-stop/refresh-quote"),
    ("POST", "/api/v2/holdings/protective-stop/keep"),
    ("GET", "/api/v2/execution/kill-switches"),
    ("POST", "/api/v2/execution/kill-switches"),          # stop direction stays reachable
    ("POST", "/api/v2/execution/kill-switches/enable"),
    ("POST", "/api/v2/system/panic"),
    ("GET", "/api/v2/admin/risk-config"),
    ("GET", "/api/v2/brokers/schwab/token-health"),
    ("POST", "/api/v2/broker-orders/pilot/arm-extra"),
    ("POST", "/api/v3/watch/commands/star"),
]


def test_step_up_inventory_exact(tmp_path):
    cfg, _ = _cfg(tmp_path)
    for (method, path), action in STEP_UP_EXPECTED.items():
        assert cc_auth.step_up_action(cfg, method, path) == action, (method, path)
        assert cc_auth.step_up_action(cfg, method, path + "/") == action, "trailing slash must not bypass"
        assert cc_auth.step_up_action(cfg, method, path + "?x=1") == action
    for method, path in NOT_STEP_UP:
        assert cc_auth.step_up_action(cfg, method, path) is None, (method, path)


def test_step_up_routes_exist_in_router_source():
    """Every gated path is a real route string (guards against a typo silently gating nothing)."""
    src = (SCRIPTS / "api_v2.py").read_text(encoding="utf-8")
    for (_m, path) in STEP_UP_EXPECTED:
        if path in FORWARD_REGISTERED:
            assert f'"{path}"' not in src, f"{path} now exists — move it out of FORWARD_REGISTERED"
            continue
        assert f'"{path}"' in src, path


# Gated before the route exists (no HTTP kill-switch disable route on main as of 2026-10-14).
FORWARD_REGISTERED = {"/api/v2/execution/kill-switches/disable"}


def test_require_step_up_refuses():
    d = cc_auth.require_step_up(object(), "order_pilot")
    assert not d.allowed and d.status == 403 and d.reason == "step-up required — TOTP unlock not yet enabled"


# ── pure policy ─────────────────────────────────────────────────────────────

def test_rfc2047_login_decoded(tmp_path):
    cfg, store = _cfg(tmp_path)
    enc = "=?utf-8?q?john=40jwwhiting=2Ecom?="
    d = cc_auth.evaluate_request(cfg, "serve_proxy", "GET", "/api/x", {"Tailscale-User-Login": enc}, store)
    assert d.allowed and d.principal == f"tailnet:{ALLOWED}"


def test_token_file_with_loose_mode_rejected(tmp_path):
    cfg, store = _cfg(tmp_path, token_mode=0o644)
    d = cc_auth.evaluate_request(cfg, "service", "GET", "/api/x", {cfg.token_header: TOKEN}, store)
    assert not d.allowed and d.status == 401 and "chmod 600" in d.reason


def test_bearer_token_accepted(tmp_path):
    cfg, store = _cfg(tmp_path)
    d = cc_auth.evaluate_request(cfg, "service", "GET", "/api/x", {"Authorization": f"Bearer {TOKEN}"}, store)
    assert d.allowed and d.principal == "service-token"


def test_enforce_false_is_kill_switch_except_hard_protections(tmp_path):
    cfg, store = _cfg(tmp_path, enforce=False)
    so = {"Origin": "https://ms01-openclaw.tail163d14.ts.net"}
    d = cc_auth.evaluate_request(cfg, "serve_proxy", "POST", "/api/v2/broker-orders/pilot/arm", so, store)
    assert d.allowed and not d.would_deny  # identity + step-up off
    d = cc_auth.evaluate_request(cfg, "serve_proxy", "POST", "/api/v2/watchlist/x/refresh", {}, store)
    assert d.allowed  # ordinary CSRF follows the kill switch
    # ...but hard CSRF routes and the secret-write refusal do not
    d = cc_auth.evaluate_request(cfg, "serve_proxy", "POST", "/api/v2/broker-orders/pilot/arm", {}, store)
    assert not d.allowed and d.kind == "csrf"
    d = cc_auth.evaluate_request(cfg, "serve_proxy", "POST", "/api/v2/admin/secrets",
                                 {**so, "Tailscale-User-Login": ALLOWED}, store)
    assert not d.allowed and d.kind == "refused"


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv(cc_auth.REPORT_ONLY_ENV, "0")
    monkeypatch.setenv(cc_auth.TOKEN_FILE_ENV, str(tmp_path / "tok"))
    cfg = cc_auth.load_config(ROOT / "config" / "cc_auth.yaml")
    assert cfg.report_only is False and cfg.token_file == tmp_path / "tok"


def test_service_token_bypass_flag(tmp_path):
    cfg, store = _cfg(tmp_path, bypass=True)
    d = cc_auth.evaluate_request(cfg, "service", "POST", "/api/v2/broker-orders/pilot/arm",
                                 {cfg.token_header: TOKEN}, store)
    assert d.allowed
    # identity on the proxy listener never bypasses
    d2 = cc_auth.evaluate_request(cfg, "serve_proxy", "POST", "/api/v2/broker-orders/pilot/arm",
                                  {"Tailscale-User-Login": ALLOWED}, store)
    assert not d2.allowed and d2.status == 403


# ── client helper ───────────────────────────────────────────────────────────

def test_client_attaches_token_only_to_loopback_service_port(tmp_path, monkeypatch):
    from lib import cc_client
    tok = tmp_path / "tok"
    tok.write_text(TOKEN, encoding="utf-8")
    os.chmod(tok, 0o600)
    monkeypatch.setenv(cc_auth.TOKEN_FILE_ENV, str(tok))
    h = cc_auth.load_config().token_header
    assert cc_client.cc_headers("http://127.0.0.1:7777/api/v2/risk") == {h: TOKEN}
    assert cc_client.cc_headers("http://localhost:7777/api/x", {"A": "b"}) == {"A": "b", h: TOKEN}
    for other in ("http://127.0.0.1:7779/api/x", "http://example.com:7777/api/x",
                  "https://127.0.0.1:7777/api/x", "http://100.66.120.124:7777/api/x",
                  "http://127.0.0.1:11434/api/tags"):
        assert h not in cc_client.cc_headers(other), other
    req = cc_client.cc_request("http://127.0.0.1:7777/api/x", data=b"{}", method="POST")
    assert req.get_header(h.capitalize()) == TOKEN


def test_client_missing_token_sends_nothing(tmp_path, monkeypatch):
    from lib import cc_client
    monkeypatch.setenv(cc_auth.TOKEN_FILE_ENV, str(tmp_path / "absent"))
    assert cc_client.cc_headers("http://127.0.0.1:7777/api/x") == {}


# ── end to end through the real PortfolioHandler on two listeners ───────────

@pytest.fixture
def server_mod(monkeypatch):
    if "scripts.portfolio_server" not in sys.modules:
        fake_eb = types.ModuleType("env_bootstrap")
        fake_eb.load_env = lambda *a, **k: None  # never load host credentials into the test process
        monkeypatch.setitem(sys.modules, "env_bootstrap", fake_eb)
    import scripts.portfolio_server as server
    calls: list[tuple[str, str]] = []

    principals: list[str] = []

    def _fake_handle(path, method="GET", body=None, query=None):
        calls.append((method, path))
        principals.append(cc_auth.current_principal())
        return 200, {"ok": True, "fake": True, "path": path}

    monkeypatch.setattr(server, "_get_api_v2", lambda: types.SimpleNamespace(handle=_fake_handle))
    server._fake_calls = calls
    server._fake_principals = principals
    return server


@pytest.fixture
def listeners(server_mod, tmp_path, monkeypatch):
    started = []

    def _make(**kw):
        cfg, store = _cfg(tmp_path, **kw)
        monkeypatch.setattr(server_mod, "CC_AUTH_CONFIG", cfg)
        monkeypatch.setattr(server_mod, "CC_AUTH_TOKENS", store)
        ports = {}
        for role in ("service", "serve_proxy"):
            s = server_mod.ReusableHTTPServer(("127.0.0.1", 0), server_mod.PortfolioHandler)
            s.cc_listener_role = role
            threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
            started.append(s)
            ports[role] = s.server_address[1]
        return cfg, ports

    yield _make
    for s in started:
        s.shutdown()
        s.server_close()


SAME_ORIGIN = {"Origin": "https://ms01-openclaw.tail163d14.ts.net", "Sec-Fetch-Site": "same-origin"}
EVIL_ORIGIN = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}


def _req(port, path, *, method="GET", headers=None, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    base = {"Content-Type": ctype} if ctype else {}
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                               headers={**base, **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_proxied_allowed_login_200(listeners):
    cfg, p = listeners()
    st, body = _req(p["serve_proxy"], "/api/health", headers={"Tailscale-User-Login": ALLOWED})
    assert st == 200 and json.loads(body)["ok"] is True
    st, _ = _req(p["serve_proxy"], "/api/v2/risk", headers={"Tailscale-User-Login": "John@JWWhiting.com"})
    assert st == 200


@pytest.mark.parametrize("hdrs", [{}, {"Tailscale-User-Login": "mallory@example.com"},
                                  {"Tailscale-User-Login": ""}])
def test_proxied_missing_or_other_login_403(listeners, hdrs):
    cfg, p = listeners()
    st, body = _req(p["serve_proxy"], "/api/v2/risk", headers=hdrs)
    assert st == 403
    assert json.loads(body)["ok"] is False


def test_proxied_denial_is_html_page_for_browsers(listeners):
    cfg, p = listeners()
    st, body = _req(p["serve_proxy"], "/v3/", headers={"Accept": "text/html"})
    assert st == 403 and b"<h1" in body and b"Not authorized" in body


def test_proxy_listener_ignores_service_token(listeners):
    cfg, p = listeners()
    st, _ = _req(p["serve_proxy"], "/api/v2/risk", headers={cfg.token_header: TOKEN})
    assert st == 403


def test_direct_loopback_without_token_401(listeners, server_mod):
    cfg, p = listeners()
    st, _ = _req(p["service"], "/api/v2/risk")
    assert st == 401
    assert ("GET", "/api/v2/risk") not in server_mod._fake_calls


def test_direct_loopback_with_token_200(listeners, server_mod):
    cfg, p = listeners()
    st, body = _req(p["service"], "/api/v2/risk", headers={cfg.token_header: TOKEN})
    assert st == 200 and json.loads(body)["fake"] is True


def test_direct_loopback_wrong_token_401(listeners):
    cfg, p = listeners()
    st, _ = _req(p["service"], "/api/v2/risk", headers={cfg.token_header: "x" * 48})
    assert st == 401


def test_forged_tailscale_header_on_token_listener_ignored(listeners, server_mod):
    cfg, p = listeners()
    st, _ = _req(p["service"], "/api/v2/risk", headers={"Tailscale-User-Login": ALLOWED})
    assert st == 401
    assert ("GET", "/api/v2/risk") not in server_mod._fake_calls
    rows = [json.loads(l) for l in cfg.decision_log.read_text().splitlines()]
    assert rows[-1]["ignored_identity_header"] is True and rows[-1]["outcome"] == "deny"


def test_service_exempt_liveness_path(listeners):
    cfg, p = listeners()
    st, _ = _req(p["service"], "/api/health")
    assert st == 200
    st, _ = _req(p["service"], "/api/health", method="POST", body={})
    assert st == 401  # exemption is GET-only


@pytest.mark.parametrize("method,path", sorted(STEP_UP_EXPECTED))
def test_step_up_routes_403_even_with_valid_identity(listeners, server_mod, method, path):
    cfg, p = listeners()
    body = {} if method == "POST" else None
    st, raw = _req(p["serve_proxy"], path, method=method,
                   headers={"Tailscale-User-Login": ALLOWED, **SAME_ORIGIN}, body=body)
    assert st == 403
    want = cc_auth.REFUSED_MESSAGE if path == "/api/v2/admin/secrets" else cc_auth.STEP_UP_MESSAGE
    assert json.loads(raw)["error"] == want
    st2, _ = _req(p["service"], path, method=method, headers={cfg.token_header: TOKEN}, body=body)
    assert st2 == 403
    assert not [c for c in server_mod._fake_calls if c[1] == path], "gated route must never dispatch"


def test_step_up_still_refuses_in_report_only(listeners, server_mod):
    cfg, p = listeners(report_only=True)
    st, raw = _req(p["serve_proxy"], "/api/v2/broker-orders/pilot/arm", method="POST", body={},
                   headers={"Tailscale-User-Login": ALLOWED, **SAME_ORIGIN})
    assert st == 403 and json.loads(raw)["error"] == cc_auth.STEP_UP_MESSAGE
    assert not server_mod._fake_calls


def test_step_up_refuses_unauthenticated_report_only_traffic(listeners, server_mod):
    """report_only lets an unauthenticated caller through auth — it must still hit step-up."""
    cfg, p = listeners(report_only=True)
    st, raw = _req(p["service"], "/api/v2/holdings/protective-stop", method="POST", body={})  # no token
    assert st == 403 and json.loads(raw)["error"] == cc_auth.STEP_UP_MESSAGE
    st, raw = _req(p["serve_proxy"], "/api/v2/holdings/protective-stop", method="POST", body={},
                   headers=SAME_ORIGIN)  # no identity
    assert st == 403 and json.loads(raw)["error"] == cc_auth.STEP_UP_MESSAGE
    assert not server_mod._fake_calls


def test_report_only_logs_but_allows(listeners, server_mod):
    cfg, p = listeners(report_only=True)
    st1, _ = _req(p["service"], "/api/v2/risk")  # no token
    st2, _ = _req(p["serve_proxy"], "/api/v2/overview", headers={"Tailscale-User-Login": "mallory@example.com"})
    assert (st1, st2) == (200, 200)
    assert ("GET", "/api/v2/risk") in server_mod._fake_calls
    rows = [json.loads(l) for l in cfg.decision_log.read_text().splitlines()]
    outcomes = {(r["listener"], r["path"], r["outcome"], r["status"]) for r in rows}
    assert ("service", "/api/v2/risk", "would_deny", 401) in outcomes
    assert ("serve_proxy", "/api/v2/overview", "would_deny", 403) in outcomes
    assert TOKEN not in cfg.decision_log.read_text()


def test_unstamped_server_is_treated_as_service_listener(server_mod, tmp_path, monkeypatch):
    cfg, store = _cfg(tmp_path)
    monkeypatch.setattr(server_mod, "CC_AUTH_CONFIG", cfg)
    monkeypatch.setattr(server_mod, "CC_AUTH_TOKENS", store)
    s = server_mod.ReusableHTTPServer(("127.0.0.1", 0), server_mod.PortfolioHandler)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    try:
        st, _ = _req(s.server_address[1], "/api/v2/risk", headers={"Tailscale-User-Login": ALLOWED})
        assert st == 401
    finally:
        s.shutdown()
        s.server_close()


def test_serve_proxy_listener_refuses_non_loopback(server_mod, tmp_path):
    raw = _raw_committed()
    raw["cc_auth"]["listeners"]["serve_proxy"]["transport"] = "tcp"
    raw["cc_auth"]["listeners"]["serve_proxy"]["host"] = "0.0.0.0"
    cfg = cc_auth.config_from_mapping(raw, apply_env=False)
    assert server_mod._start_serve_proxy_listener(cfg) is None


def test_serve_proxy_listener_starts_with_role(server_mod, tmp_path):
    import socket
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        free = so.getsockname()[1]
    raw = _raw_committed()
    raw["cc_auth"]["listeners"]["serve_proxy"]["transport"] = "tcp"
    raw["cc_auth"]["listeners"]["serve_proxy"]["port"] = free
    cfg = cc_auth.config_from_mapping(raw, apply_env=False)
    sp = server_mod._start_serve_proxy_listener(cfg)
    try:
        assert sp is not None and sp.cc_listener_role == "serve_proxy"
        assert sp.server_address == ("127.0.0.1", free)
    finally:
        if sp is not None:
            sp.shutdown()
            sp.server_close()


# ── unix-socket serve_proxy listener (default transport) ───────────────────

import http.client  # noqa: E402
import socket as _socket  # noqa: E402
import stat as _stat  # noqa: E402


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=10)
        self._path = path

    def connect(self):
        self.sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(self._path)


def _unix_req(path_sock, path, headers=None):
    c = _UnixHTTPConnection(str(path_sock))
    try:
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


@pytest.fixture
def unix_sock_dir():
    import tempfile
    d = tempfile.mkdtemp(prefix="ccsock_", dir="/tmp")  # short path: sun_path limit
    yield Path(d)
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def _unix_cfg(tmp_path, sock, monkeypatch, server_mod):
    cfg, store = _cfg(tmp_path)
    raw = _raw_committed()
    raw["cc_auth"]["listeners"]["serve_proxy"]["unix_socket"] = str(sock)
    ucfg = cc_auth.config_from_mapping(raw, apply_env=False)
    monkeypatch.setattr(server_mod, "CC_AUTH_CONFIG", cfg)
    monkeypatch.setattr(server_mod, "CC_AUTH_TOKENS", store)
    return ucfg


def test_unix_socket_listener_0600_and_identity(server_mod, tmp_path, monkeypatch, unix_sock_dir):
    sock = unix_sock_dir / "sub" / "cc.sock"
    ucfg = _unix_cfg(tmp_path, sock, monkeypatch, server_mod)
    assert cc_auth.serve_proxy_target(ucfg) == f"unix:{sock}"
    sp = server_mod._start_serve_proxy_listener(ucfg)
    try:
        assert sp is not None and sp.cc_listener_role == "serve_proxy"
        assert _stat.S_ISSOCK(os.lstat(sock).st_mode)
        assert _stat.S_IMODE(os.lstat(sock).st_mode) == 0o600
        assert _stat.S_IMODE(os.stat(sock.parent).st_mode) == 0o700
        st, _ = _unix_req(sock, "/api/health", {"Tailscale-User-Login": ALLOWED})
        assert st == 200
        st, _ = _unix_req(sock, "/api/v2/risk", {"Tailscale-User-Login": "mallory@example.com"})
        assert st == 403
        st, _ = _unix_req(sock, "/api/v2/risk")
        assert st == 403
        # a second instance must not steal a live socket
        assert server_mod._start_serve_proxy_listener(ucfg) is None
    finally:
        if sp is not None:
            sp.shutdown()
            sp.server_close()


def test_unix_socket_replaces_stale_socket_but_not_a_file(server_mod, tmp_path, monkeypatch, unix_sock_dir):
    sock = unix_sock_dir / "cc.sock"
    stale = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    stale.bind(str(sock))
    stale.close()  # file remains, nothing listening
    ucfg = _unix_cfg(tmp_path, sock, monkeypatch, server_mod)
    sp = server_mod._start_serve_proxy_listener(ucfg)
    assert sp is not None
    sp.shutdown()
    sp.server_close()
    other = unix_sock_dir / "plain"
    other.write_text("keep me")
    ucfg2 = _unix_cfg(tmp_path, other, monkeypatch, server_mod)
    assert server_mod._start_serve_proxy_listener(ucfg2) is None
    assert other.read_text() == "keep me"


def test_unix_socket_unresolved_path_refused(monkeypatch):
    monkeypatch.delenv("CC_TEST_UNSET_DIR", raising=False)
    raw = _raw_committed()
    raw["cc_auth"]["listeners"]["serve_proxy"]["unix_socket"] = "${CC_TEST_UNSET_DIR}/cc.sock"
    cfg = cc_auth.config_from_mapping(raw, apply_env=False)
    assert cfg.serve_proxy_unix_socket is None and not cc_auth.serve_proxy_bind_ok(cfg)


def test_conftest_points_token_file_away_from_host():
    p = os.environ.get(cc_auth.TOKEN_FILE_ENV, "")
    assert p and not p.startswith(os.path.expanduser("~/.config/"))


def test_cc_urlopen_passthrough_keeps_test_doubles_working(monkeypatch):
    from lib import cc_client
    seen = []

    def fake(url, timeout=10):  # legacy double signature: no data kwarg, expects the raw URL
        seen.append((url, timeout))
        return "resp"

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert cc_client.cc_urlopen("http://127.0.0.1:7777/api/x", timeout=3) == "resp"
    assert seen == [("http://127.0.0.1:7777/api/x", 3)]


def test_cc_urlopen_adds_header_to_request(monkeypatch, tmp_path):
    from lib import cc_client
    tok = tmp_path / "tok"
    tok.write_text(TOKEN, encoding="utf-8")
    os.chmod(tok, 0o600)
    monkeypatch.setenv(cc_auth.TOKEN_FILE_ENV, str(tok))
    got = {}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: got.update(req=req, kw=kw))
    cc_client.cc_urlopen("http://127.0.0.1:7777/api/x", timeout=4)
    h = cc_auth.load_config().token_header
    assert got["req"].get_header(h.capitalize()) == TOKEN and got["kw"] == {"timeout": 4}
    r = urllib.request.Request("http://127.0.0.1:7777/api/y", data=b"{}", method="POST")
    cc_client.cc_urlopen(r)
    assert got["req"] is r and r.get_header(h.capitalize()) == TOKEN and got["kw"] == {}


# ── caller migration guard ──────────────────────────────────────────────────

import re as _re  # noqa: E402

_RAW_PY_CALL = _re.compile(r"(urllib\.request\.urlopen|\burlopen|requests\.(get|post))\(\s*f?[\"']http://(127\.0\.0\.1|localhost):7777")
_RAW_SH_CALL = _re.compile(r"(?<![\w$\"-])curl [^\n]*http://(127\.0\.0\.1|localhost):7777/(?!api/health\b|api/v2/health\b)")
_SH_GUARD_EXEMPT = {
    # interactive tmux `watch` pane (operator-run, not scheduled); report_only log surfaces it
    "linux_launchers/hermes_scalp_swarm_tmux.sh",
}


def test_no_raw_loopback_cc_calls_in_python():
    offenders = []
    for f in sorted(SCRIPTS.rglob("*.py")):
        rel = f.relative_to(ROOT).as_posix()
        if "/archive/" in rel or rel.endswith(("portfolio_server.py", "api_v2.py")):
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _RAW_PY_CALL.search(line) and "_cc_headers(" not in line:
                offenders.append(f"{rel}:{i}")
    assert not offenders, "use lib.cc_client (cc_urlopen / cc_headers): " + ", ".join(offenders)


def test_no_raw_loopback_cc_curl_in_shell():
    offenders = []
    for base in ("scripts", "linux_launchers"):
        for f in sorted((ROOT / base).rglob("*.sh")):
            rel = f.relative_to(ROOT).as_posix()
            if "/archive/" in rel or rel in _SH_GUARD_EXEMPT or rel.endswith("cc_curl.sh"):
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if not line.lstrip().startswith("#") and _RAW_SH_CALL.search(line):
                    offenders.append(f"{rel}:{i}")
    assert not offenders, "use scripts/cc_curl.sh: " + ", ".join(offenders)


# ── shell wrapper ───────────────────────────────────────────────────────────

def _run_cc_curl(tmp_path, url, token_present=True):
    import subprocess
    fakebin = tmp_path / "bin"
    fakebin.mkdir(exist_ok=True)
    fake = fakebin / "curl"
    # fake curl: print argv, and the contents of any -H @file
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'ARGV:%s\\n' \"$*\"\n"
        "while [ $# -gt 0 ]; do if [ \"$1\" = -H ] && [[ \"$2\" == @* ]]; then "
        "printf 'HDRFILE:%s' \"$(cat \"${2#@}\")\"; fi; shift; done\n")
    fake.chmod(0o755)
    tok = tmp_path / "shtok"
    if token_present:
        tok.write_text(TOKEN, encoding="utf-8")
        os.chmod(tok, 0o600)
    env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}", cc_auth.TOKEN_FILE_ENV: str(tok),
           "TRADEAI_PYTHON": sys.executable}
    r = subprocess.run(["bash", str(SCRIPTS / "cc_curl.sh"), "-s", url], capture_output=True, text=True,
                       env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_cc_curl_adds_header_via_file_not_argv(tmp_path):
    out = _run_cc_curl(tmp_path, "http://127.0.0.1:7777/api/v2/risk")
    argv = [l for l in out.splitlines() if l.startswith("ARGV:")][0]
    assert TOKEN not in argv
    assert f"HDRFILE:X-TradeAI-Service-Token: {TOKEN}" in out


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434/api/tags", "https://example.com/x",
                                 "http://127.0.0.1:77770/x", "http://evil.example:7777/x"])
def test_cc_curl_never_sends_token_elsewhere(tmp_path, url):
    out = _run_cc_curl(tmp_path, url)
    assert "HDRFILE" not in out and TOKEN not in out


def test_cc_curl_without_token_file_still_runs(tmp_path):
    out = _run_cc_curl(tmp_path, "http://127.0.0.1:7777/api/x", token_present=False)
    assert "ARGV:" in out and "HDRFILE" not in out


# ── WS4-02: secret-write route refused outright; actor = authenticated identity ─

SECRETS = "/api/v2/admin/secrets"
PROXIED_OK = {"Tailscale-User-Login": ALLOWED, **SAME_ORIGIN}


@pytest.mark.parametrize("kw", [{}, {"report_only": True}, {"enforce": False}, {"step_up_mode": "off"},
                                {"step_up_mode": "report_only"}, {"bypass": True}])
def test_secret_write_refused_on_both_listeners_in_every_mode(listeners, server_mod, kw):
    cfg, p = listeners(**kw)
    body = {"key": "TELEGRAM_BOT_TOKEN", "value": "x" * 40, "actor": "operator"}
    st, raw = _req(p["serve_proxy"], SECRETS, method="POST", headers=PROXIED_OK, body=body)
    assert st == 403 and json.loads(raw)["error"] == cc_auth.REFUSED_MESSAGE
    st, raw = _req(p["service"], SECRETS, method="POST", headers={cfg.token_header: TOKEN}, body=body)
    assert st == 403 and json.loads(raw)["error"] == cc_auth.REFUSED_MESSAGE
    assert not [c for c in server_mod._fake_calls if c[1] == SECRETS]
    rows = [json.loads(l) for l in cfg.decision_log.read_text().splitlines()]
    assert {r["kind"] for r in rows if r["path"] == SECRETS} == {"refused"}
    assert "x" * 40 not in cfg.decision_log.read_text()


def test_secret_read_listing_is_not_refused(listeners, server_mod):
    cfg, p = listeners()
    st, _ = _req(p["serve_proxy"], SECRETS, headers={"Tailscale-User-Login": ALLOWED})
    assert st == 200  # GET lists presence only (masked); the refusal is for writes


@pytest.fixture
def api_v2_mod(monkeypatch):
    if "api_v2" not in sys.modules:
        fake_dotenv = types.ModuleType("dotenv")
        fake_dotenv.load_dotenv = lambda *a, **k: False  # never load host credentials into the test
        monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    import api_v2
    writes = []
    fake_sa = types.ModuleType("secrets_admin")
    fake_sa.set_secret = lambda key, value, actor="": writes.append((key, actor)) or {"key": key, "masked": "****"}
    monkeypatch.setitem(sys.modules, "secrets_admin", fake_sa)
    api_v2._fake_secret_writes = writes
    yield api_v2
    cc_auth.set_request_principal("")


@pytest.mark.parametrize("principal", ["", "service-token", "disabled", "exempt"])
def test_secret_handler_refuses_without_operator_identity(api_v2_mod, principal):
    cc_auth.set_request_principal(principal)
    st, body = api_v2_mod.handle(SECRETS, method="POST", body={"key": "X_KEY", "value": "v" * 30, "actor": "operator"})
    assert st == 403 and body["ok"] is False
    assert api_v2_mod._fake_secret_writes == []


def test_secret_handler_actor_is_authenticated_identity_not_body(api_v2_mod):
    cc_auth.set_request_principal(f"tailnet:{ALLOWED}")
    st, body = api_v2_mod.handle(SECRETS, method="POST", body={"key": "X_KEY", "value": "v" * 30, "actor": "mallory"})
    assert st == 200
    assert api_v2_mod._fake_secret_writes == [("X_KEY", f"tailnet:{ALLOWED}")]


def test_gate_sets_request_principal(listeners, server_mod):
    cfg, p = listeners()
    _req(p["serve_proxy"], "/api/v2/risk", headers={"Tailscale-User-Login": ALLOWED})
    _req(p["service"], "/api/v2/overview", headers={cfg.token_header: TOKEN})
    assert server_mod._fake_principals == [f"tailnet:{ALLOWED}", "service-token"]


def test_report_only_would_deny_is_not_an_authenticated_principal(listeners, server_mod):
    cfg, p = listeners(report_only=True)
    _req(p["service"], "/api/v2/risk")  # no token, allowed by report_only
    _req(p["serve_proxy"], "/api/v2/watchlist/x/refresh", method="POST", body={},
         headers={"Tailscale-User-Login": ALLOWED, **EVIL_ORIGIN})  # csrf would_deny
    assert server_mod._fake_principals == ["", ""]


# ── WS4-03: CSRF + CORS ─────────────────────────────────────────────────────

NORMAL_POST = "/api/v2/watchlist/x/refresh"


@pytest.mark.parametrize("hdrs,why", [
    (EVIL_ORIGIN, "Origin not on allowlist"),
    ({"Sec-Fetch-Site": "cross-site"}, "Sec-Fetch-Site"),
    ({"Sec-Fetch-Site": "same-site"}, "Sec-Fetch-Site"),
    ({"Origin": "null"}, "Origin not on allowlist"),
    ({"Origin": "https://ms01-openclaw.tail163d14.ts.net.evil.example"}, "Origin not on allowlist"),
    ({}, "no Origin or Sec-Fetch-Site"),
])
def test_csrf_forged_post_with_operator_identity_refused(listeners, server_mod, hdrs, why):
    cfg, p = listeners()
    st, raw = _req(p["serve_proxy"], NORMAL_POST, method="POST", body={},
                   headers={"Tailscale-User-Login": ALLOWED, **hdrs})
    assert st == 403 and why in json.loads(raw)["error"]
    assert not server_mod._fake_calls


def test_csrf_same_origin_json_allowed(listeners, server_mod):
    cfg, p = listeners()
    st, _ = _req(p["serve_proxy"], NORMAL_POST, method="POST", body={"a": 1}, headers=PROXIED_OK)
    assert st == 200 and ("POST", NORMAL_POST) in server_mod._fake_calls
    st, _ = _req(p["serve_proxy"], NORMAL_POST, method="POST", raw=b"", headers=PROXIED_OK, ctype=None)
    assert st == 200  # body-less POST (UI buttons) needs no content type, but still same-origin


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", None])
def test_csrf_non_json_body_refused(listeners, server_mod, ctype):
    cfg, p = listeners()
    st, raw = _req(p["serve_proxy"], NORMAL_POST, method="POST", raw=b'{"a":1}', headers=PROXIED_OK, ctype=ctype)
    assert st == 403 and "Content-Type" in json.loads(raw)["error"]
    st, _ = _req(p["service"], NORMAL_POST, method="POST", raw=b'{"a":1}', headers={cfg.token_header: TOKEN}, ctype=ctype)
    assert st == 403
    assert not server_mod._fake_calls


def test_csrf_service_listener_scripts_without_origin_pass(listeners, server_mod):
    cfg, p = listeners()
    st, _ = _req(p["service"], NORMAL_POST, method="POST", body={}, headers={cfg.token_header: TOKEN})
    assert st == 200


def test_csrf_report_only_normal_route_logs_but_allows(listeners, server_mod):
    cfg, p = listeners(report_only=True)
    st, _ = _req(p["serve_proxy"], NORMAL_POST, method="POST", body={},
                 headers={"Tailscale-User-Login": ALLOWED, **EVIL_ORIGIN})
    assert st == 200
    rows = [json.loads(l) for l in cfg.decision_log.read_text().splitlines()]
    assert any(r["kind"] == "csrf" and r["outcome"] == "would_deny" for r in rows)


HARD = ["/api/v2/broker-orders/preview", "/api/v2/broker-orders/pilot/disarm", "/api/v2/admin/validate-secret",
        "/api/v2/execution/kill-switches/disable", "/api/v2/trading-lock/unlock", "/api/v3/x/unlock"]


@pytest.mark.parametrize("kw", [{"report_only": True}, {"enforce": False}])
@pytest.mark.parametrize("path", HARD)
def test_csrf_hard_routes_enforced_even_in_report_only_and_disabled(listeners, server_mod, kw, path):
    cfg, p = listeners(**kw)
    st, raw = _req(p["serve_proxy"], path, method="POST", body={},
                   headers={"Tailscale-User-Login": ALLOWED, **EVIL_ORIGIN})
    assert st == 403 and json.loads(raw)["error"].startswith("csrf:")
    st, _ = _req(p["serve_proxy"], path, method="POST", raw=b"{}", ctype="text/plain", headers=PROXIED_OK)
    assert st == 403
    assert not [c for c in server_mod._fake_calls if c[1] == path]


def test_hard_route_same_origin_reaches_handler_when_not_step_up(listeners, server_mod):
    cfg, p = listeners()
    st, _ = _req(p["serve_proxy"], "/api/v2/broker-orders/preview", method="POST", body={}, headers=PROXIED_OK)
    assert st == 200  # preview is read-only; same-origin JSON is fine


@pytest.mark.parametrize("path", ["/api/v2/execution/kill-switches/enable", "/api/v2/execution/kill-switches/engage",
                                  "/api/v2/system/panic", "/api/v3/panic"])
def test_stop_routes_stay_easy_same_origin_only(listeners, server_mod, path):
    cfg, p = listeners()
    # same-origin, even with a non-JSON body: reaches the handler, never step-up
    st, _ = _req(p["serve_proxy"], path, method="POST", raw=b"{}", ctype="text/plain", headers=PROXIED_OK)
    assert st == 200 and ("POST", path) in server_mod._fake_calls
    assert cc_auth.step_up_action(cfg, "POST", path) is None
    # cross-site is still refused
    st, _ = _req(p["serve_proxy"], path, method="POST", body={}, headers={"Tailscale-User-Login": ALLOWED, **EVIL_ORIGIN})
    assert st == 403


def test_kill_switch_disable_is_hard_and_step_up(tmp_path):
    cfg, store = _cfg(tmp_path)
    path = "/api/v2/execution/kill-switches/disable"
    assert cc_auth.csrf_class(cfg, "POST", path) == "hard"
    d = cc_auth.evaluate_request(cfg, "serve_proxy", "POST", path, {"Tailscale-User-Login": ALLOWED, **SAME_ORIGIN}, store)
    assert not d.allowed and d.kind == "step_up"


def test_form_route_cio_links_accept_same_origin_urlencoded(tmp_path):
    cfg, store = _cfg(tmp_path)
    path = "/v3/go/cio/abc123"
    form = {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": "5"}
    ok, _ = cc_auth.csrf_check(cfg, "serve_proxy", "POST", path, {**form, **SAME_ORIGIN})
    assert ok
    ok, why = cc_auth.csrf_check(cfg, "serve_proxy", "POST", path, {**form, **EVIL_ORIGIN})
    assert not ok
    ok, why = cc_auth.csrf_check(cfg, "service", "POST", path, form)  # no Origin even on loopback
    assert not ok and "no Origin" in why
    ok, _ = cc_auth.csrf_check(cfg, "serve_proxy", "POST", NORMAL_POST, {**form, **SAME_ORIGIN})
    assert not ok  # urlencoded only on form routes


def _req_headers(port, path, *, method="GET", headers=None):
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


def test_cors_echoes_only_allowlisted_origin_never_star(listeners):
    cfg, p = listeners()
    st, h = _req_headers(p["serve_proxy"], "/api/health", headers={"Tailscale-User-Login": ALLOWED, **SAME_ORIGIN})
    assert st == 200 and h.get("Access-Control-Allow-Origin") == SAME_ORIGIN["Origin"] and "Origin" in h.get("Vary", "")
    st, h = _req_headers(p["serve_proxy"], "/api/health", headers={"Tailscale-User-Login": ALLOWED, **EVIL_ORIGIN})
    assert "Access-Control-Allow-Origin" not in h
    st, h = _req_headers(p["serve_proxy"], "/api/health", method="OPTIONS", headers=EVIL_ORIGIN)
    assert "Access-Control-Allow-Origin" not in h
    st, h = _req_headers(p["serve_proxy"], "/api/health", method="OPTIONS", headers={"Origin": "http://localhost:7789"})
    assert h.get("Access-Control-Allow-Origin") == "http://localhost:7789"


def test_no_wildcard_cors_left_in_server_source():
    src = (SCRIPTS / "portfolio_server.py").read_text(encoding="utf-8")
    assert '"Access-Control-Allow-Origin", "*"' not in src
    assert b"Access-Control-Allow-Origin: *".decode() not in src
