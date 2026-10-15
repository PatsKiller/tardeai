"""scripts/offbox_deadman.py — the heartbeat that leaves the host (WS3-18, WS3-20; 2026-10-15).

Every test uses a tmp state root and a stub requester. No test opens a socket: the dry run never calls the
requester (asserted with one that raises), and live runs get a stub."""

from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import offbox_deadman as D  # noqa: E402

T0 = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)
URL = "https://ping.example.invalid/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"
CFG = D.load_config()


def _never(*_a, **_k):
    raise AssertionError("no network in a dry run")


def _healthy(root: Path, now: datetime = T0, **over) -> None:
    rt = root / "data" / "runtime"
    rt.mkdir(parents=True, exist_ok=True)
    docs = {
        "incident_notifier_last.json": {"as_of": now.isoformat(), "ok": True, "status": "OK"},
        "n8n_incident_fanin_last.json": {"as_of": now.isoformat(), "ok": True},
        "heartbeat-watch_last.json": {"finished_at": now.isoformat(), "status": "ok", "summary": {"stale": []}},
    }
    for name, doc in docs.items():
        (rt / name).write_text(json.dumps({**doc, **over.get(name, {})}), encoding="utf-8")


class Stub:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    def __call__(self, method, url, body, timeout):
        self.calls.append((method, url, body, timeout))
        return self.results.pop(0) if self.results else {"ok": True, "status": 200}


def test_config_names_a_secret_env_var_and_three_checks():
    assert CFG["ping_url_env"] == "TRADEAI_OFFBOX_DEADMAN_PING_URL"
    assert {c["name"] for c in CFG["checks"]} == {"incident_notifier", "incident_fanin", "heartbeat_watch"}
    assert "http" not in json.dumps(CFG).replace("healthchecks.io-class", "")  # no URL value in git


def test_dry_run_without_url_prints_the_would_be_request_and_opens_nothing(tmp_path):
    _healthy(tmp_path)
    r = D.run(live=False, env={}, now=T0, cfg=CFG, requester=_never, root=tmp_path)
    assert r["ok"] and r["outcome"] == {"status": "DRY_RUN", "network": False}
    assert r["ping_url_configured"] is False
    assert r["request"] == {"kind": "success", "method": "GET", "url": D.PLACEHOLDER, "body": None}


def test_dry_run_with_url_still_opens_nothing_and_redacts(tmp_path):
    _healthy(tmp_path)
    r = D.run(live=False, env={CFG["ping_url_env"]: URL}, now=T0, cfg=CFG, requester=_never, root=tmp_path)
    assert r["outcome"]["network"] is False
    assert r["request"]["url"] == "https://ping.example.invalid/…90ab" and "0f1e2d3c" not in json.dumps(r)


@pytest.mark.parametrize(
    "name,over,reason",
    [
        (
            "incident_notifier",
            {"incident_notifier_last.json": {"as_of": (T0 - timedelta(minutes=40)).isoformat()}},
            "stale:",
        ),
        ("incident_notifier", {"incident_notifier_last.json": {"ok": False, "status": "FAILED"}}, "not_ok:"),
        ("incident_fanin", {"n8n_incident_fanin_last.json": {"as_of": "garbage"}}, "no_timestamp"),
        (
            "heartbeat_watch",
            {"heartbeat-watch_last.json": {"summary": {"stale": ["incident-notifier"]}}},
            "summary.stale=",
        ),
    ],
)
def test_a_failed_check_sends_fail_with_the_reason(tmp_path, name, over, reason):
    _healthy(tmp_path, **over)
    stub = Stub([{"ok": True, "status": 200}])
    r = D.run(live=True, env={CFG["ping_url_env"]: URL}, now=T0, cfg=CFG, requester=stub, root=tmp_path)
    method, url, body, _ = stub.calls[0]
    assert (method, url) == ("POST", URL + "/fail")
    assert f"- {name}: {reason}" in body.decode("utf-8")
    assert r["outcome"]["status"] == "PINGED" and r["request"]["kind"] == "fail"


def test_missing_receipt_is_a_failure_not_silence(tmp_path):
    r = D.run(live=False, env={}, now=T0, cfg=CFG, requester=_never, root=tmp_path)
    assert r["request"]["kind"] == "fail"
    assert all(c["reason"].startswith("unreadable:") for c in r["checks"])


def test_no_checks_configured_is_a_failure(tmp_path):
    r = D.run(live=False, env={}, now=T0, cfg={**CFG, "checks": []}, requester=_never, root=tmp_path)
    assert r["request"]["kind"] == "fail" and r["checks"][0]["reason"] == "no_checks_configured"


def test_live_success_pings_get_once(tmp_path):
    _healthy(tmp_path)
    stub = Stub([{"ok": True, "status": 200}])
    r = D.run(live=True, env={CFG["ping_url_env"]: URL}, now=T0, cfg=CFG, requester=stub, root=tmp_path)
    assert stub.calls == [("GET", URL, None, float(CFG["timeout_s"]))]
    assert r["ok"] and r["outcome"]["status"] == "PINGED"


def test_live_without_url_is_not_configured_and_not_ok(tmp_path):
    _healthy(tmp_path)
    r = D.run(live=True, env={}, now=T0, cfg=CFG, requester=_never, root=tmp_path)
    assert r["ok"] is False and r["outcome"] == {"status": "NOT_CONFIGURED", "network": False}


def test_live_transport_failure_retries_then_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(D.time, "sleep", lambda _s: None)
    _healthy(tmp_path)
    stub = Stub([{"ok": False, "status": None, "error": "URLError"}] * 5)
    r = D.run(live=True, env={CFG["ping_url_env"]: URL}, now=T0, cfg=CFG, requester=stub, root=tmp_path)
    assert len(stub.calls) == 1 + CFG["retries"]
    assert r["ok"] is False and r["outcome"]["status"] == "FAILED" and r["outcome"]["error"] == "URLError"


def test_main_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    _healthy(tmp_path)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.delenv(CFG["ping_url_env"], raising=False)
    monkeypatch.setattr(D, "_urllib_request", _never)
    before = sorted(p.name for p in (tmp_path / "data" / "runtime").iterdir())
    assert D.main(["--dry-run"]) == 0
    assert sorted(p.name for p in (tmp_path / "data" / "runtime").iterdir()) == before
    assert json.loads(capsys.readouterr().out)["outcome"]["status"] == "DRY_RUN"


def test_independent_of_n8n_the_main_bot_and_postgres():
    tree = ast.parse((ROOT / "scripts" / "offbox_deadman.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    stdlib = {
        "__future__",
        "argparse",
        "json",
        "os",
        "socket",
        "sys",
        "time",
        "urllib",
        "datetime",
        "pathlib",
        "typing",
        "zoneinfo",  # 2026-10-15 business-heartbeat windows (stdlib)
    }
    assert {m.split(".")[0] for m in mods} <= stdlib, mods  # nothing local: no n8n, gateway, bot, editor or DB
