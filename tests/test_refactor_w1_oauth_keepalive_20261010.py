"""n8n refactor wave 1 (W2), 2026-10-10 — oauth_lane_keepalive.py (cron:L501).

``--dry-run`` is reachability only: Grok/ChatGPT via the proxies' read-only /health, never a generate (the
real run's generate is an LLM call that rolls the token). It shares ``_evaluate`` with the real run and
returns before the status file, the Telegram send and the receipt. A real run exits 1 when a lane that was
healthy before is not ok now, and writes a LaneRunReceipt@v1. The in-script send is unchanged (follow-up).
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import oauth_lane_keepalive as oak  # noqa: E402
from lib import oauth_lane_status as ols  # noqa: E402

COVERS = ["scripts/oauth_lane_keepalive.py"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    status = rt / "oauth_lane_status.json"
    status.write_text(json.dumps({"grok": {"last_ok": 1, "ok": True}, "chatgpt": {"last_ok": 1, "ok": True}}))
    monkeypatch.setattr(oak, "STATUS_FILE", status)
    health = {"grok": True, "chatgpt": True}
    monkeypatch.setattr(
        ols,
        "_probe_health",
        lambda lane, timeout=5.0: {"ready": health[lane], "status": "ready" if health[lane] else "session expired"},
    )
    sent = []
    fake = type(sys)("telegram_alert")
    fake.send_telegram = lambda text, **kw: sent.append(text) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    gen = type(sys)("llm_lane")
    gen.generate = lambda *a, **k: pytest.fail("generate reached")
    monkeypatch.setitem(sys.modules, "llm_lane", gen)
    return {"root": tmp_path, "rt": rt, "status": status, "health": health, "sent": sent}


def test_dry_run_no_generate_no_status_write_no_send_no_receipt(env, monkeypatch, capsys):
    before = (env["status"].read_bytes(), env["status"].stat().st_mtime_ns)
    monkeypatch.setattr(oak, "_ping_lane", lambda lane: pytest.fail(f"_ping_lane({lane}) reached"))
    monkeypatch.setattr(oak, "_save_status", lambda s: pytest.fail("status write reached"))
    import lib.lane_last_receipt as llr

    monkeypatch.setattr(llr, "write_lane_receipt", lambda *a, **k: pytest.fail("receipt reached"))
    assert oak.main(["grok,chatgpt", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert '"mode": "dry_run"' in out and "no generate" in out
    assert (env["status"].read_bytes(), env["status"].stat().st_mtime_ns) == before
    assert env["sent"] == [] and sorted(p.name for p in env["rt"].iterdir()) == ["oauth_lane_status.json"]


def test_dry_run_mutation_tested_a_stale_lane_changes_the_report(env, capsys):
    oak.main(["grok,chatgpt", "--dry-run"])
    healthy = json.loads(capsys.readouterr().out.split("\n(dry run —")[0])
    env["health"]["chatgpt"] = False
    oak.main(["grok,chatgpt", "--dry-run"])
    stale = json.loads(capsys.readouterr().out.split("\n(dry run —")[0])
    assert healthy["regressions"] == [] and healthy["would_exit"] == 0 and healthy["would_alert"] == 0
    assert stale["regressions"] == ["chatgpt"] and stale["would_exit"] == 1 and stale["would_alert"] == 1


def test_source_order_dry_run_returns_before_any_side_effect():
    src = inspect.getsource(oak.main)
    i = src.index("return dry_run(lanes)")
    for effect in ("_ping_lane", "_save_status(state)", "send_telegram", "write_lane_receipt("):
        assert i < src.index(effect), effect
    d = inspect.getsource(oak.dry_run)
    assert "_reach_lane" in d and "_save_status" not in d and "send_telegram" not in d
    assert ".generate(" not in inspect.getsource(oak._reach_lane)


def test_real_run_regression_exits_1_and_receipt_carries_ok_at(env, monkeypatch):
    results = {"grok": (True, "rolled token (ping ok)"), "chatgpt": (True, "rolled token (ping ok)")}
    monkeypatch.setattr(oak, "_ping_lane", lambda lane: results[lane])
    assert oak.main(["grok,chatgpt"]) == 0
    rc_path = env["rt"] / "oauth_lane_keepalive_last.json"
    ok_at = json.loads(rc_path.read_text())["ok_at"]
    assert ok_at
    results["chatgpt"] = (False, "session expired — re-login required")
    assert oak.main(["grok,chatgpt"]) == 1
    rc = json.loads(rc_path.read_text())
    assert rc["status"] == "failed" and rc["ok_at"] == ok_at and rc["summary"]["regressions"] == ["chatgpt"]
    assert len(env["sent"]) == 1  # the send itself is unchanged: one deduped alert
    st = json.loads(env["status"].read_text())
    assert st["chatgpt"]["ok"] is False and st["chatgpt"]["consec_fail"] == 1


def test_a_never_set_up_lane_is_not_a_failure(env, monkeypatch):
    monkeypatch.setattr(oak, "_ping_lane", lambda lane: (False, "nous portal not logged in"))
    assert oak.main(["hermes"]) == 0
    assert env["sent"] == []


def test_status_file_resolves_under_the_state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert oak._runtime_dir() == tmp_path / "data" / "runtime"
    assert 'ROOT / "data" / "runtime" / "oauth_lane_status.json"' not in Path(oak.__file__).read_text()


def test_dry_run_allowlist_argv_is_dispatcher_eligible():
    from tests.test_agents_policy_4_1_0_amendment import dispatcher_eligible

    entry = {
        "lane_id": "oauth-lane-keepalive",
        "command": ["$PY", "scripts/oauth_lane_keepalive.py"],
        "dry_run_arg": ["--dry-run"],
        "live_arg": [],
    }
    assert dispatcher_eligible(entry) == (True, "ok")
