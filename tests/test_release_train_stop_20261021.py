"""Release Train v2 — Command Center STOP RELEASES (2026-10-21, Phase 2 STOP pulled forward).

POST /api/v2/coordination/release-train/stop SETS the STOP latch scripts/release_window.py obeys
(<TRADEAI_RELEASE_WINDOW_STATE_DIR>/STOP.json). Pinned here:
  * auth required: only an authenticated tailnet operator principal (never a service token, never report-only);
  * CSRF required and ENFORCED: the gate's hard route (even report_only / enforce:false) and the handler's own
    command_csrf_check; no step-up (the operator declined TOTP);
  * actor from the server principal, never the body;
  * set-only: every clear / resume shaped request is refused, an existing latch is never overwritten or removed;
  * idempotent per key; append-only audit row per attempt;
  * the latch is in exactly the format release_window.Runner treats as SET (REFUSED_STOP_LATCHED), and the
    host CLI clear-stop still clears it (resume stays host-CLI-only, decision D3).

Hermetic: tmp_path state dir via TRADEAI_RELEASE_WINDOW_STATE_DIR, temp cc_auth config and token, ephemeral
127.0.0.1 listeners, dotenv/env_bootstrap stubbed, psycopg2 stubbed when absent. No git, no GitHub, no systemd,
no release directory, no broker, no kill switch.
"""

from __future__ import annotations

import ast
import fcntl
import json
import os
import sys
import threading
import types
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must not open a database")

    _pg.connect = _no_connect
    sys.modules.setdefault("psycopg2", _pg)

from lib import cc_auth  # noqa: E402
from lib import release_train_stop as rts  # noqa: E402

import release_window as RW  # noqa: E402

ALLOWED = "john@jwwhiting.com"
OPERATOR = f"tailnet:{ALLOWED}"
TOKEN = "t" * 48
STOP = "/api/v2/coordination/release-train/stop"
ORIGIN = "https://ms01-openclaw.tail163d14.ts.net"
SAME_ORIGIN = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
EVIL_ORIGIN = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
JSON_CT = {"Content-Type": "application/json", "Content-Length": "64"}
REASON = "bad batch in flight, hold releases"


def _key(n: int = 1) -> str:
    return f"cc-stop-test-key-{n:04d}-abcdef"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for k in (cc_auth.ENFORCE_ENV, cc_auth.REPORT_ONLY_ENV, cc_auth.CONFIG_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(cc_auth.TOKEN_FILE_ENV, str(tmp_path / "absent_cc_service_token"))
    sd = tmp_path / "release_window"
    monkeypatch.setenv(rts.STATE_DIR_ENV, str(sd))
    yield sd
    cc_auth.set_request_principal("")
    cc_auth.set_request_context(None, None)


def _browser(principal=OPERATOR, headers=None):
    cc_auth.set_request_principal(principal)
    cc_auth.set_request_context("serve_proxy", {**JSON_CT, **(SAME_ORIGIN if headers is None else headers)})


def _audit(sd: Path) -> list[dict]:
    p = sd / "cc_stop" / "audit.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


@pytest.fixture
def api_v2_mod(monkeypatch):
    if "api_v2" not in sys.modules:
        fake_dotenv = types.ModuleType("dotenv")
        fake_dotenv.load_dotenv = lambda *a, **k: False  # never load host credentials into the test
        monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    import api_v2

    return api_v2


def _post(api, body, path=STOP, method="POST"):
    return api.handle(path, method=method, body=body)


# ── auth ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("principal", ["", "service-token", "disabled", "exempt", "preflight"])
def test_auth_required_operator_identity(api_v2_mod, _env, principal):
    _browser(principal)
    st, body = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    assert st == 403 and body["ok"] is False and body["refusal"] == "NO_OPERATOR_IDENTITY"
    assert not (_env / "STOP.json").exists()
    rows = _audit(_env)
    assert rows[-1]["event"] == "refused" and rows[-1]["refusal"] == "NO_OPERATOR_IDENTITY"


# ── CSRF ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "headers",
    [
        EVIL_ORIGIN,
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {},  # no Origin and no Sec-Fetch-Site
        {"Sec-Fetch-Site": "none"},  # not positive same-origin proof without an Origin
        {**SAME_ORIGIN, "Content-Type": "text/plain"},
    ],
)
def test_csrf_required_in_handler(api_v2_mod, _env, headers):
    _browser(OPERATOR, headers)
    st, body = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    assert st == 403 and body["refusal"] == "CSRF"
    assert not (_env / "STOP.json").exists()


def test_csrf_fails_closed_without_gate_context(api_v2_mod, _env):
    cc_auth.set_request_principal(OPERATOR)
    cc_auth.set_request_context(None, None)
    st, body = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    assert st == 403 and body["refusal"] == "CSRF" and "context" in body["error"]


def test_committed_config_hard_route_and_no_step_up():
    cfg = cc_auth.load_config(ROOT / "config" / "cc_auth.yaml")
    assert cfg.report_only is True  # the default the STOP route must NOT inherit
    assert cc_auth.csrf_class(cfg, "POST", STOP) == "hard"
    assert cc_auth.csrf_class(cfg, "POST", "/api/v2/coordination/release-train/resume") == "hard"
    assert cc_auth.step_up_action(cfg, "POST", STOP) is None
    assert cc_auth.refused_action(cfg, "POST", STOP) is None
    assert cc_auth.step_up_blocks_route(cfg, "POST", STOP) is None


# ── end to end through the real PortfolioHandler gate ───────────────────────────────────────────


def _cfg(tmp_path, *, report_only=False, enforce=True):
    import yaml

    raw = yaml.safe_load((ROOT / "config" / "cc_auth.yaml").read_text(encoding="utf-8"))
    sec = raw["cc_auth"]
    sec["enforce"], sec["report_only"] = enforce, report_only
    tok = tmp_path / "cc_service_token"
    tok.write_text(TOKEN + "\n", encoding="utf-8")
    os.chmod(tok, 0o600)
    sec["service_token"]["file"] = str(tok)
    sec["decision_log"] = str(tmp_path / "decisions.jsonl")
    cfg = cc_auth.config_from_mapping(raw, source="test", apply_env=False)
    return cfg, cc_auth.ServiceTokenStore(cfg.token_file, cfg.token_min_length)


@pytest.fixture
def listeners(monkeypatch, tmp_path, api_v2_mod):
    if "scripts.portfolio_server" not in sys.modules:
        fake_eb = types.ModuleType("env_bootstrap")
        fake_eb.load_env = lambda *a, **k: None  # never load host credentials into the test process
        monkeypatch.setitem(sys.modules, "env_bootstrap", fake_eb)
    import scripts.portfolio_server as server

    calls: list[tuple[str, str]] = []

    def _handle(path, method="GET", body=None, query=None):
        calls.append((method, path))
        return api_v2_mod.handle(path, method=method, body=body, query=query)

    monkeypatch.setattr(server, "_get_api_v2", lambda: types.SimpleNamespace(handle=_handle))
    started = []

    def _make(**kw):
        cfg, store = _cfg(tmp_path, **kw)
        monkeypatch.setattr(server, "CC_AUTH_CONFIG", cfg)
        monkeypatch.setattr(server, "CC_AUTH_TOKENS", store)
        ports = {}
        for role in ("service", "serve_proxy"):
            s = server.ReusableHTTPServer(("127.0.0.1", 0), server.PortfolioHandler)
            s.cc_listener_role = role
            threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
            started.append(s)
            ports[role] = s.server_address[1]
        return ports, calls

    yield _make
    for s in started:
        s.shutdown()
        s.server_close()


def _req(port, path, *, method="POST", headers=None, body=None, ctype="application/json"):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method, headers={"Content-Type": ctype, **(headers or {})}
    )
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


@pytest.mark.parametrize("kw", [{"report_only": True}, {"enforce": False}])
def test_gate_enforces_csrf_even_in_report_only(listeners, _env, kw):
    ports, calls = listeners(**kw)
    st, body = _req(
        ports["serve_proxy"],
        STOP,
        body={"reason": REASON, "idempotency_key": _key()},
        headers={"Tailscale-User-Login": ALLOWED, **EVIL_ORIGIN},
    )
    assert st == 403 and body["error"].startswith("csrf:")
    assert ("POST", STOP) not in calls
    assert not (_env / "STOP.json").exists()


def test_report_only_unauthenticated_reaches_handler_and_is_refused(listeners, _env):
    ports, calls = listeners(report_only=True)
    st, body = _req(
        ports["serve_proxy"], STOP, body={"reason": REASON, "idempotency_key": _key()}, headers=SAME_ORIGIN
    )  # no Tailscale-User-Login: report_only lets it through the gate
    assert ("POST", STOP) in calls
    assert st == 403 and body["refusal"] == "NO_OPERATOR_IDENTITY"
    assert not (_env / "STOP.json").exists()


def test_service_token_is_not_an_operator(listeners, _env):
    ports, _ = listeners()
    st, body = _req(
        ports["service"],
        STOP,
        body={"reason": REASON, "idempotency_key": _key()},
        headers={"X-TradeAI-Service-Token": TOKEN, **SAME_ORIGIN},
    )
    assert st == 403 and body["refusal"] == "NO_OPERATOR_IDENTITY"


def test_end_to_end_operator_stop_no_step_up_actor_from_server(listeners, _env):
    ports, _ = listeners()
    st, body = _req(
        ports["serve_proxy"],
        STOP,
        body={"reason": REASON, "idempotency_key": _key(), "actor": "mallory"},
        headers={"Tailscale-User-Login": ALLOWED, **SAME_ORIGIN},
    )
    assert st == 200, body
    assert body["outcome"] == "STOP_SET" and body["phase"] == "acknowledged"
    assert body["actor"] == OPERATOR and body["latch"]["body"]["actor"] == OPERATOR
    st, status = _req(ports["serve_proxy"], STOP, method="GET", headers={"Tailscale-User-Login": ALLOWED})
    status = status["data"]
    assert st == 200 and status["latch"]["status"] == "SET" and status["phase"] == "stopped"


# ── actor, reason, key ───────────────────────────────────────────────────────────────────────────


def test_actor_taken_from_server_not_body(api_v2_mod, _env):
    _browser()
    st, body = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key(), "actor": "mallory"})
    assert st == 200 and body["actor"] == OPERATOR
    latch = json.loads((_env / "STOP.json").read_text(encoding="utf-8"))
    assert latch["actor"] == OPERATOR and "mallory" not in json.dumps(latch)
    row = _audit(_env)[-1]
    assert row["actor"] == OPERATOR and row["body_actor_ignored"] is True


@pytest.mark.parametrize("reason", [None, "", "   ", "short", 42, "x" * 501])
def test_reason_required(api_v2_mod, _env, reason):
    _browser()
    st, body = _post(api_v2_mod, {"reason": reason, "idempotency_key": _key()})
    assert st == 400 and body["refusal"] == "REASON_REQUIRED"
    assert not (_env / "STOP.json").exists()


@pytest.mark.parametrize("key", [None, "", "short", "has spaces in the key!!", "x" * 129, 12345678901234567])
def test_idempotency_key_required(api_v2_mod, _env, key):
    _browser()
    st, body = _post(api_v2_mod, {"reason": REASON, "idempotency_key": key})
    assert st == 400 and body["refusal"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert not (_env / "STOP.json").exists()


# ── set-only ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/api/v2/coordination/release-train/resume", "POST", {"reason": REASON, "idempotency_key": _key(9)}),
        ("/api/v2/coordination/release-train/clear", "POST", {"reason": REASON, "idempotency_key": _key(9)}),
        ("/api/v2/coordination/release-train/clear-stop", "POST", {"reason": REASON, "idempotency_key": _key(9)}),
        ("/api/v2/coordination/release-train", "POST", {"action": "resume"}),
        (STOP, "DELETE", {}),
        (STOP, "PUT", {"reason": REASON, "idempotency_key": _key(9)}),
        (STOP, "POST", {"action": "clear", "reason": REASON, "idempotency_key": _key(9)}),
        (STOP, "POST", {"action": "resume", "reason": REASON, "idempotency_key": _key(9)}),
        (STOP, "POST", {"resume": True, "reason": REASON, "idempotency_key": _key(9)}),
        (STOP, "POST", {"clear": True, "reason": REASON, "idempotency_key": _key(9)}),
    ],
)
def test_set_only_clear_or_resume_refused(api_v2_mod, _env, path, method, body):
    _browser()
    st, first = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    assert st == 200
    latch_before = (_env / "STOP.json").read_bytes()
    st, res = _post(api_v2_mod, body, path=path, method=method)
    assert st == 400 and res["refusal"] == "SET_ONLY" and res["ok"] is False
    assert "clear-stop" in res["resume"]["command"]
    assert (_env / "STOP.json").read_bytes() == latch_before  # still SET, untouched
    assert _audit(_env)[-1]["refusal"] == "SET_ONLY"


def test_set_only_refusal_when_no_latch_writes_nothing(api_v2_mod, _env):
    _browser()
    st, res = _post(
        api_v2_mod, {"reason": REASON, "idempotency_key": _key()}, path="/api/v2/coordination/release-train/resume"
    )
    assert st == 400 and res["refusal"] == "SET_ONLY"
    assert not (_env / "STOP.json").exists()


def test_module_has_no_clear_or_resume_function():
    names = {n for n in dir(rts) if not n.startswith("_")}
    assert not [
        n
        for n in names
        if any(w in n.lower() for w in ("clear_stop", "resume", "unlatch", "unstop")) and callable(getattr(rts, n))
    ]
    src = (SCRIPTS / "lib" / "release_train_stop.py").read_text(encoding="utf-8")
    assert "unlink(" not in src and "os.remove" not in src and "rmtree" not in src  # never deletes


def test_existing_runner_latch_is_kept_byte_for_byte(api_v2_mod, _env):
    state = RW.State(_env)
    state.write(
        state.latch,
        {
            "latched_at": "2026-10-21T16:00:00Z",
            "window_id": "2026-10-21-1730",
            "outcome": "ROLLED_BACK",
            "candidate": "abc",
            "detail": "runner latch",
        },
    )
    before = state.latch.read_bytes()
    _browser()
    st, body = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    assert st == 200 and body["outcome"] == "ALREADY_STOPPED" and body["phase"] == "acknowledged"
    assert state.latch.read_bytes() == before
    assert _audit(_env)[-1]["existing_latch_outcome"] == "ROLLED_BACK"


def test_unreadable_latch_is_archived_never_deleted(api_v2_mod, _env):
    _env.mkdir(parents=True)
    (_env / "STOP.json").write_text("{corrupt", encoding="utf-8")
    _browser()
    st, body = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    assert st == 200 and body["outcome"] == "STOP_SET"
    arch = Path(body["archived_unreadable_latch"])
    assert arch.read_text(encoding="utf-8") == "{corrupt"
    assert rts.read_latch(RW.State(_env))[0] == "SET"


# ── idempotency + audit ──────────────────────────────────────────────────────────────────────────


def test_idempotent_same_key(api_v2_mod, _env):
    _browser()
    st1, a = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    latch1 = (_env / "STOP.json").read_bytes()
    st2, b = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    assert st1 == st2 == 200
    assert a["stop_id"] == b["stop_id"] and a["outcome"] == "STOP_SET" and b["replayed"] is True
    assert (_env / "STOP.json").read_bytes() == latch1
    assert len(list((_env / "cc_stop" / "latches").glob("*.json"))) == 1
    st3, c = _post(api_v2_mod, {"reason": REASON + " (different)", "idempotency_key": _key()})
    assert st3 == 409 and c["refusal"] == "IDEMPOTENCY_KEY_REUSED"
    assert [r["event"] for r in _audit(_env)] == ["stop_set", "replayed", "refused"]


def test_new_key_while_stopped_is_already_stopped(api_v2_mod, _env):
    _browser()
    _, a = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key(1)})
    st, b = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key(2)})
    assert st == 200 and b["outcome"] == "ALREADY_STOPPED" and b["stop_id"] == a["stop_id"]


def test_audit_row_is_append_only_and_complete(api_v2_mod, _env):
    _browser("")
    _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key(1)})
    first = (_env / "cc_stop" / "audit.jsonl").read_text(encoding="utf-8")
    _browser()
    _, res = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key(2)})
    text = (_env / "cc_stop" / "audit.jsonl").read_text(encoding="utf-8")
    assert text.startswith(first)  # appended, never rewritten
    row = json.loads(text.splitlines()[-1])
    assert row["event"] == "stop_set" and row["actor"] == OPERATOR and row["reason"] == REASON
    assert row["stop_id"] == res["stop_id"] and row["latch_status_before"] == "ABSENT"
    assert row["latch_status_after"] == "SET" and row["acknowledged_at"]
    assert row["idempotency_key_sha256"] and _key(2) not in text  # the key itself is never stored


# ── the latch format release_window.py reads as SET ─────────────────────────────────────────────


def test_latch_is_set_for_release_window_runner(api_v2_mod, _env):
    _browser()
    st, body = _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    assert st == 200
    state = RW.State(_env)
    assert state.latch == _env / "STOP.json"
    runner = RW.Runner(None, state, env={})
    w, refusal = runner._preconditions(datetime(2026, 10, 21, 21, 30, tzinfo=timezone.utc), None)
    assert w is None and refusal["outcome"] == "REFUSED_STOP_LATCHED"
    assert refusal["latch"]["stop_id"] == body["stop_id"]
    assert runner.status()[1]["latch"]["reason"] == REASON
    if callable(getattr(state, "read_latch", None)):  # Phase 0 fail-closed reader, when served
        assert state.read_latch()[0] == "SET"


def test_host_cli_clear_stop_still_clears_it(api_v2_mod, _env):
    _browser()
    _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    host = types.SimpleNamespace(now=lambda: datetime(2026, 10, 21, 22, 0, tzinfo=timezone.utc))
    code, out = RW.Runner(host, RW.State(_env), env={}).clear_stop("operator reviewed, resume")
    assert code == 0 and out["outcome"] == "STOP_CLEARED"
    s = rts.status()
    assert s["latch"]["status"] == "ABSENT" and s["phase"] == "running"


# ── status read-back ─────────────────────────────────────────────────────────────────────────────


def test_status_get_absent_then_stopped(api_v2_mod, _env):
    st, res = api_v2_mod.handle(STOP, method="GET")
    assert st == 200 and res["data"]["latch"]["status"] == "ABSENT" and res["data"]["phase"] == "running"
    assert res["data"]["separate_from_trading_kill_switch"] is True
    assert "clear-stop" in res["data"]["resume"]["command"]
    _browser()
    _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    st, res = api_v2_mod.handle(STOP, method="GET")
    assert res["data"]["latch"]["status"] == "SET" and res["data"]["phase"] == "stopped"
    assert res["data"]["audit_tail"][-1]["event"] == "stop_set"


@pytest.mark.skipif(not Path("/proc/locks").exists(), reason="needs /proc/locks")
def test_status_settling_while_a_window_holds_the_run_lock(api_v2_mod, _env):
    _browser()
    _post(api_v2_mod, {"reason": REASON, "idempotency_key": _key()})
    with open(_env / ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        s = rts.status()
        assert s["window_run_lock"] == "HELD" and s["phase"] == "settling"
    assert rts.status()["phase"] == "stopped"


def test_unreadable_latch_status_is_not_running(_env):
    _env.mkdir(parents=True)
    (_env / "STOP.json").write_text("[]", encoding="utf-8")
    s = rts.status()
    assert s["latch"]["status"] == "UNREADABLE" and s["phase"] == "unknown"


# ── release STOP is not the trading kill switch ─────────────────────────────────────────────────


def test_release_stop_never_touches_trading_kill_switch():
    src = (SCRIPTS / "lib" / "release_train_stop.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not [m for m in imported if "kill" in m or "trading_lock" in m or "broker" in m or "execution" in m]
    assert "kill-switches/" not in src.replace("/api/v2/execution/kill-switches/*", "")
