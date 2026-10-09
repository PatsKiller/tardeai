"""Hermetic tests for the phone status endpoint: no tailnet bind, no live receipts, no host paths."""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import phone_status_endpoint as P

KEY = "s3cr3t-phone-key-" + "q" * 40
PREV = "previous-phone-key-" + "z" * 40
TS_IP = "100.66.120.124"
PEER = "100.101.102.103"
NOW = 1_791_600_000.0
NOW_DT = datetime.fromtimestamp(NOW, tz=timezone.utc)


class Clock:
    def __init__(self, t: float = NOW) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _iso(seconds_ago: float) -> str:
    return (NOW_DT - timedelta(seconds=seconds_ago)).isoformat()


def fake_state(tmp_path: Path, *, pending: int = 2) -> tuple[dict[str, str], P.Sources]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    state = tmp_path / "state"
    runtime = state / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "n8n_lab_watchdog_last.json").write_text(json.dumps({"ok": True, "checked_at": _iso(60)}))
    (runtime / "n8n_incident_fanin_last.json").write_text(
        json.dumps({"open": 7, "by_severity": {"P1": 1, "P2": 2, "P3": 4}, "as_of": _iso(120),
                    "incidents": [{"detail": "x" * 5000}]})
    )
    gov = state / "data" / "governance"
    gov.mkdir(parents=True)
    db = sqlite3.connect(gov / "n8n_coordination_ledger.sqlite")
    db.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, exit_code INT, duration_s REAL,"
               " requested_by TEXT, caller_id TEXT, requested_at TEXT, started_at TEXT, finished_at TEXT)")
    rows = [("r1", "lane-a", _iso(3600)), ("r2", "lane-a", _iso(7200)), ("r3", "lane-b", _iso(600)),
            ("r4", "lane-old", _iso(3 * 86400))]
    for rid, lane, fin in rows:
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (rid, lane, "dry_run", "RUN_FAILED", 1, 0.1, "n8n", "n8n", fin, fin, fin))
    db.execute("INSERT INTO runs VALUES ('r5','lane-ok','dry_run','RUN_DONE',0,0.1,'n8n','n8n',?,?,?)",
               (_iso(60),) * 3)
    db.commit()
    db.close()
    release = tmp_path / "release"
    (release / "config").mkdir(parents=True)
    (release / "BUILD_SHA").write_text("0123456789abcdef0123456789abcdef01234567\n")
    lanes = [{"lane_id": f"w{i}", "scheduler": {"kind": "n8n"}, "state": "ACTIVE"} for i in range(3)]
    lanes += [{"lane_id": "c1", "scheduler": {"kind": "cron"}, "state": "ACTIVE"},
              {"lane_id": "w9", "scheduler": {"kind": "n8n"}, "state": "RETIRED"}]
    (release / "config" / "lane_registry.json").write_text(json.dumps({"lanes": lanes}))
    approvals = tmp_path / "approvals"
    approvals.mkdir()
    reqs = [{"request_id": f"req-{i}", "scope": "config-write", "reason": "SECRET-REASON",
             "code_sha256": "f" * 64, "status": "PENDING", "expires_at": NOW + 600} for i in range(pending)]
    reqs += [{"request_id": "req-exp", "status": "PENDING", "expires_at": NOW - 5, "code_sha256": "e" * 64},
             {"request_id": "req-ok", "status": "APPROVED", "expires_at": NOW + 600}]
    (approvals / "remote_requests.json").write_text(json.dumps({"schema": "x", "requests": reqs}))
    environ = {"TRADEAI_STATE_ROOT": str(state), "GUARD_APPROVALS_DIR": str(approvals), P.KEY_ENV: KEY}
    return environ, P.Sources(environ, release_root=release)


def app(tmp_path, clock=None, **extra):
    environ, src = fake_state(tmp_path)
    environ.update(extra)
    return P.PhoneStatus(environ=environ, sources=src, clock=clock or Clock())


def headers(key=KEY, ts=None, nonce="nonce-0001", alg="hmac-sha256", path=P.STATUS_PATH):
    ts = str(int(NOW if ts is None else ts))
    return {"X-Phone-Ts": ts, "X-Phone-Nonce": nonce, "X-Phone-Alg": alg,
            "X-Phone-Sig": P.sign(key.encode(), ts, nonce, path, alg)}


# ------------------------------------------------------------------------------------------------ bind

def test_bind_accepts_only_this_hosts_tailscale_ip():
    P.guard_bind(TS_IP, 18093, TS_IP)


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1", "172.19.0.1", "192.168.1.10", "8.8.8.8",
                                  "100.66.120.125", "100.128.0.1", "::", "fd7a:115c:a1e0::1", "ms01", ""])
def test_bind_refuses_every_non_tailscale_or_other_tailnet_address(host):
    with pytest.raises(ValueError, match="phone_bad_bind"):
        P.guard_bind(host, 18093, TS_IP)


@pytest.mark.parametrize("port", [80, 443, 1023, 7777, 5678, 18090, 70000])
def test_bind_refuses_privileged_blocked_and_invalid_ports(port):
    with pytest.raises(ValueError, match="phone_bad_bind"):
        P.guard_bind(TS_IP, port, TS_IP)


def test_bind_refuses_when_tailscale_is_down():
    with pytest.raises(ValueError, match="phone_bad_bind"):
        P.guard_bind(TS_IP, 18093, None)
    with pytest.raises(ValueError, match="phone_bad_bind"):
        P.resolve_host("auto", None)
    assert P.resolve_host("auto", TS_IP + "\n") == TS_IP


def test_tailscale_ipv4_reads_first_line_and_never_raises():
    ok = lambda *a, **k: SimpleNamespace(returncode=0, stdout=TS_IP + "\n")  # noqa: E731
    bad = lambda *a, **k: SimpleNamespace(returncode=1, stdout="")  # noqa: E731

    def boom(*a, **k):
        raise FileNotFoundError("tailscale")

    assert P.tailscale_ipv4(ok) == TS_IP
    assert P.tailscale_ipv4(bad) is None
    assert P.tailscale_ipv4(boom) is None


def test_main_refuses_a_non_tailscale_host_before_listening(capsys):
    assert P.main(["--host", "0.0.0.0"], tailscale=lambda: TS_IP) == 2
    assert json.loads(capsys.readouterr().out) == {"ok": False, "reason": "phone_bad_bind"}
    assert P.main(["--host", "auto"], tailscale=lambda: None) == 2


def test_dry_run_builds_a_summary_without_a_listener_and_without_the_key(tmp_path, capsys, monkeypatch):
    environ, _ = fake_state(tmp_path)
    for k, v in environ.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv(P.KEY_ENV)
    assert P.main(["--dry-run"], tailscale=lambda: TS_IP) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["key_present"] is False and out["host"] == TS_IP


# ------------------------------------------------------------------------------------------------ auth

def test_missing_or_short_key_refuses_startup(tmp_path):
    environ, src = fake_state(tmp_path)
    for value in ("", "short"):
        environ[P.KEY_ENV] = value
        with pytest.raises(ValueError, match="phone_missing_secret"):
            P.PhoneStatus(environ=environ, sources=src)
    environ[P.KEY_ENV] = KEY
    environ[P.KEY_PREVIOUS_ENV] = "short"
    with pytest.raises(ValueError, match="phone_missing_secret"):
        P.PhoneStatus(environ=environ, sources=src)


@pytest.mark.parametrize("alg", P.ALGS)
def test_valid_signature_is_served_for_both_algorithms(tmp_path, alg):
    status, body = app(tmp_path).handle("GET", P.STATUS_PATH, PEER, headers(alg=alg))
    assert status == 200
    assert json.loads(body)["schema"] == "PhoneStatus@v1"


def test_envelope_matches_the_shortcut_recipe_text(tmp_path):
    # The Shortcut builds KEY \n TS \n NONCE \n GET \n PATH \n KEY and runs Generate Hash (SHA-256).
    import hashlib
    text = f"{KEY}\n{int(NOW)}\nnonce-0001\nGET\n{P.STATUS_PATH}\n{KEY}"
    assert hashlib.sha256(text.encode()).hexdigest() == P.sign(KEY.encode(), str(int(NOW)), "nonce-0001",
                                                                P.STATUS_PATH, "sha256-envelope")


def test_previous_key_is_accepted_during_rotation(tmp_path):
    a = app(tmp_path, **{P.KEY_PREVIOUS_ENV: PREV})
    assert a.handle("GET", P.STATUS_PATH, PEER, headers(key=PREV))[0] == 200


@pytest.mark.parametrize("mutate", [
    lambda h: h.update({"X-Phone-Sig": "0" * 64}),
    lambda h: h.pop("X-Phone-Sig"),
    lambda h: h.update({"X-Phone-Nonce": "bad nonce!"}),
    lambda h: h.update({"X-Phone-Ts": "12ab"}),
    lambda h: h.update({"X-Phone-Alg": "md5"}),
    lambda h: h.update(headers(key="w" * 48)),
])
def test_bad_signature_or_malformed_headers_are_refused(tmp_path, mutate):
    h = headers()
    mutate(h)
    status, body = app(tmp_path).handle("GET", P.STATUS_PATH, PEER, h)
    assert status == 401 and json.loads(body)["reason"] == "phone_bad_auth"


def test_signature_is_bound_to_the_path(tmp_path):
    h = headers(path="/phone/other")
    status, body = app(tmp_path).handle("GET", P.STATUS_PATH, PEER, h)
    assert status == 401


@pytest.mark.parametrize("skew,ok", [(-60, True), (60, True), (-61, False), (61, False), (-3600, False)])
def test_plus_minus_sixty_second_window(tmp_path, skew, ok):
    status, body = app(tmp_path).handle("GET", P.STATUS_PATH, PEER, headers(ts=NOW + skew))
    assert (status == 200) is ok
    if not ok:
        assert json.loads(body)["reason"] == "phone_stale_ts"


def test_a_nonce_is_single_use(tmp_path):
    a = app(tmp_path)
    h = headers()
    assert a.handle("GET", P.STATUS_PATH, PEER, h)[0] == 200
    status, body = a.handle("GET", P.STATUS_PATH, PEER, h)
    assert status == 401 and json.loads(body)["reason"] == "phone_replay"
    assert a.handle("GET", P.STATUS_PATH, PEER, headers(nonce="nonce-0002"))[0] == 200


def test_unauthenticated_requests_never_enter_the_nonce_cache(tmp_path):
    a = app(tmp_path)
    h = headers()
    h["X-Phone-Sig"] = "0" * 64
    a.handle("GET", P.STATUS_PATH, PEER, h)
    assert a.guard.nonces == {}


def test_nonces_expire_after_twice_the_window(tmp_path):
    clock = Clock()
    a = app(tmp_path, clock=clock)
    assert a.handle("GET", P.STATUS_PATH, PEER, headers())[0] == 200
    clock.t = NOW + 2 * P.WINDOW_S + 1
    assert a.handle("GET", P.STATUS_PATH, PEER, headers(ts=clock.t, nonce="nonce-0003"))[0] == 200
    assert "nonce-0001" not in a.guard.nonces


def test_per_client_rate_limit_counts_failed_attempts_too(tmp_path):
    a = app(tmp_path)
    bad = headers()
    bad["X-Phone-Sig"] = "0" * 64
    for _ in range(P.PER_CLIENT_PER_MIN):
        assert a.handle("GET", P.STATUS_PATH, PEER, bad)[0] == 401
    status, body = a.handle("GET", P.STATUS_PATH, PEER, headers())
    assert status == 429 and json.loads(body)["reason"] == "phone_rate_limited"
    assert a.handle("GET", P.STATUS_PATH, "100.64.0.9", headers(nonce="nonce-other"))[0] == 200


def test_global_rate_limit(tmp_path):
    a = app(tmp_path)
    bad = headers()
    bad["X-Phone-Sig"] = "0" * 64
    for i in range(P.GLOBAL_PER_MIN):
        a.handle("GET", P.STATUS_PATH, f"100.64.1.{i % 250}", bad)
    assert a.handle("GET", P.STATUS_PATH, "100.64.9.9", headers())[0] == 429


@pytest.mark.parametrize("peer", ["127.0.0.1", "192.168.1.5", "8.8.8.8", "not-an-ip", "::1"])
def test_non_tailnet_peers_are_refused_before_auth(tmp_path, peer):
    status, body = app(tmp_path).handle("GET", P.STATUS_PATH, peer, headers())
    assert status == 403 and json.loads(body)["reason"] == "phone_bad_peer"


@pytest.mark.parametrize("method,path,code", [("POST", P.STATUS_PATH, 405), ("DELETE", P.STATUS_PATH, 405),
                                              ("GET", "/phone/approve", 404), ("GET", "/phone/status?x=1", 404)])
def test_only_get_phone_status_exists(tmp_path, method, path, code):
    assert app(tmp_path).handle(method, path, PEER, headers(path=path))[0] == code


# --------------------------------------------------------------------------------------------- payload

def test_summary_fields_come_from_the_receipts(tmp_path):
    _, src = fake_state(tmp_path)
    s = P.build_summary(src, now=NOW_DT)
    assert s["n8n"] == {"healthy": True, "age_s": 60, "workflows_registered": 3}
    assert s["run_failed_24h"]["count"] == 3
    assert s["run_failed_24h"]["lanes"] == ["lane-b", "lane-a"]
    assert s["incidents"] == {"open": 7, "p1": 1, "p2": 2, "age_s": 120}
    assert s["guard"] == {"pending_requests": 2}
    assert s["release"] == {"served_sha": "0123456789ab"}
    assert isinstance(s["disk"]["used_pct"], float)
    assert s["missing"] == []


def test_stale_watchdog_is_not_healthy(tmp_path):
    _, src = fake_state(tmp_path)
    src.watchdog.write_text(json.dumps({"ok": True, "checked_at": _iso(P.WATCHDOG_STALE_S + 1)}))
    assert P.build_summary(src, now=NOW_DT)["n8n"]["healthy"] is False


def test_missing_sources_are_named_not_guessed(tmp_path):
    src = P.Sources({"TRADEAI_STATE_ROOT": str(tmp_path / "nowhere"), "GUARD_APPROVALS_DIR": str(tmp_path / "na")},
                    release_root=tmp_path / "norelease")
    s = P.build_summary(src, now=NOW_DT)
    assert set(s["missing"]) >= {"n8n_watchdog", "lane_registry", "coordination_ledger", "incident_fanin",
                                 "guard_requests", "build_sha"}
    assert s["guard"]["pending_requests"] is None and s["n8n"]["healthy"] is None


def test_payload_is_at_most_two_kilobytes_even_with_many_long_lanes(tmp_path):
    _, src = fake_state(tmp_path)
    s = P.build_summary(src, now=NOW_DT)
    s["run_failed_24h"]["lanes"] = ["x" * 48] * P.MAX_LANES
    assert len(P.encode_bounded(s)) <= P.MAX_PAYLOAD
    s["run_failed_24h"]["lanes"] = ["y" * 400] * 40
    body = P.encode_bounded(s)
    assert len(body) <= P.MAX_PAYLOAD and json.loads(body)["truncated"] is True
    status, served = app(tmp_path / "served").handle("GET", P.STATUS_PATH, PEER, headers())
    assert status == 200 and len(served) <= P.MAX_PAYLOAD


def test_no_secret_or_guard_code_material_in_any_response(tmp_path):
    a = app(tmp_path, **{P.KEY_PREVIOUS_ENV: PREV})
    outputs = [a.handle("GET", P.STATUS_PATH, PEER, headers())[1]]
    bad = headers(nonce="nonce-0009")
    bad["X-Phone-Sig"] = "0" * 64
    outputs.append(a.handle("GET", P.STATUS_PATH, PEER, bad)[1])
    outputs.append(a.receipt.read_bytes())
    for out in outputs:
        text = out.decode()
        for needle in (KEY, PREV, "SECRET-REASON", "f" * 64, "e" * 64, "req-0", "req-exp", "config-write",
                       "code_sha256", "request_id"):
            assert needle not in text, needle


# ------------------------------------------------------------------------------------------------ http

def test_real_http_listener_refuses_a_loopback_peer(tmp_path):
    """The handler wiring over a real socket; loopback is not a tailnet peer, so it is refused."""
    a = app(tmp_path)
    server = P.PhoneServer(("127.0.0.1", 0), P.handler_for(a))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}{P.STATUS_PATH}"
        req = urllib.request.Request(url, headers=headers())
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        assert err.value.code == 403
        assert json.loads(err.value.read()) == {"state": "REFUSED", "reason": "phone_bad_peer"}
    finally:
        server.shutdown()
        server.server_close()


def test_unit_file_binds_auto_on_the_tailnet_and_is_not_installed_by_the_repo():
    root = Path(__file__).resolve().parents[1]
    unit = (root / "config/systemd/user/tradeai-phone-status.service").read_text()
    assert "--host auto" in unit and "0.0.0.0" not in unit.split("[Service]")[1]
    assert "After=" in unit and "tailscaled.service" in unit
    services = json.loads((root / "config/expected_services.json").read_text())
    assert any(u.get("unit") == "tradeai-phone-status.service" for u in services["units"])
