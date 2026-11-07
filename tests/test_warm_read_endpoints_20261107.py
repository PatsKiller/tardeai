"""LQ-20261107-266: the warm-endpoints lane warms once per restart, writes proof, and never polls blindly.

ANCHOR: WARM_READ_ENDPOINTS_20261107

The lane exists because a restart empties every in-process cache in the API and the first operator page load
pays for all of them (measured: `[slow-request]` lines in logs/portfolio_server.log at the 20:47:57Z restart).
These tests pin the two properties that make it safe to leave running every two minutes:

* it decides from the server's own boot stamp, so a fire with nothing to do performs no HTTP request at all;
* every fire leaves a receipt, and a warm run additionally leaves the state file the next fire reads.

Fixtures are synthetic (the repo is PUBLIC): fake boot stamps, a fake opener, no live server and no real data.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import warm_read_endpoints as W  # noqa: E402

START = datetime(2026, 11, 7, 21, 0, 0, tzinfo=timezone.utc)


def _boot(tmp_path: Path, *, pid: int = 4242, started: datetime = START, sha: str = "0" * 40) -> Path:
    path = tmp_path / "portfolio_server_boot.json"
    path.write_text(json.dumps({
        "schema": "PortfolioServerBoot@v1",
        "authority": "READ_ONLY_ADVISORY",
        "process_started_at": started.isoformat(),
        "loaded_pin_sha": sha,
        "current_pin_sha": sha,
        "pid": pid,
        "port": 7777,
    }), encoding="utf-8")
    return path


class _Resp:
    def __init__(self, status: int = 200, body: bytes = b'{"ok": true}') -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *exc) -> None:
        return None


class _Opener:
    """Records every call; fails named paths; asserts the rail (GET only, no body) on the way through."""

    def __init__(self, *, fail: tuple[str, ...] = (), status: int = 200, body: bytes = b'{"ok": true}') -> None:
        self.urls: list[str] = []
        self.timeouts: list[float] = []
        self.fail = fail
        self.status = status
        self.body = body

    def __call__(self, url, data=None, timeout=None, **kwargs):
        assert data is None, "the warm lane is GET-only: no request body"
        assert not kwargs.get("method"), "the warm lane is GET-only: no method override"
        self.urls.append(str(url))
        self.timeouts.append(float(timeout))
        for bad in self.fail:
            if str(url).endswith(bad):
                raise TimeoutError("synthetic")
        return _Resp(self.status, self.body)

    def paths(self) -> list[str]:
        return [u.split("127.0.0.1:7777", 1)[-1] for u in self.urls]


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """A temp state root wired through TRADEAI_STATE_ROOT, so the receipt helper resolves there too."""
    state_root = tmp_path / "state"
    (state_root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state_root))
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)
    monkeypatch.setenv(W.BOOT_STAMP_ENV, str(_boot(tmp_path)))
    return state_root, tmp_path


def _run(ws, apply=True, now=START, **kw):
    state_root, tmp_path = ws
    return W.run(
        apply=apply,
        boot_stamp=kw.pop("boot_stamp", tmp_path / "portfolio_server_boot.json"),
        state_root=state_root,
        now=now,
        **kw,
    )


def _receipt(state_root: Path) -> dict:
    return json.loads((state_root / "data" / "runtime" / f"{W.LANE_ID}_last.json").read_text())


# ── rail: what this lane may ever call ────────────────────────────────────────────────────────────


def test_every_shipped_target_is_a_read_only_api_get():
    W._check_endpoint_rail()  # raises if any shipped path is a mutation route
    for ep in W.ENDPOINTS:
        assert ep.path.startswith("/api/")
        assert "?" not in ep.path
        assert ep.why.strip(), "every target says why it is on the list"


def test_the_rail_refuses_a_mutation_route():
    with pytest.raises(ValueError, match="mutation route"):
        W._check_endpoint_rail((W.Endpoint("/api/v2/recovery/run-now", "synthetic"),))
    with pytest.raises(ValueError, match="mutation route"):
        W._check_endpoint_rail((W.Endpoint("/api/v2/broker/place-order", "synthetic"),))


def test_a_non_loopback_base_is_refused_before_any_request(monkeypatch):
    opened = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened)
    with pytest.raises(ValueError, match="non-loopback"):
        W.run(apply=True, base="http://example.com", state_root=None)
    assert opened.urls == []


# ── a dry run reaches nothing and writes nothing ─────────────────────────────────────────────────


def test_dry_run_prints_the_plan_and_writes_nothing(workspace, monkeypatch):
    opened = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened)
    state_root, _ = workspace
    result = _run(workspace, apply=False)
    assert result["mode"] == "dry_run"
    assert result["decision"] == "restart" and result["warm"] is True
    assert len(result["endpoints"]) == len(W.ENDPOINTS)
    assert opened.urls == []
    assert not (state_root / "data" / "runtime" / f"{W.LANE_ID}_last.json").exists()
    assert not (state_root / "data" / "runtime" / W.STATE_NAME).exists()


# ── the warm itself ──────────────────────────────────────────────────────────────────────────────


def test_first_fire_after_a_restart_warms_every_target_and_records_the_identity(workspace, monkeypatch):
    opened = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened)
    state_root, _ = workspace
    result = _run(workspace)
    assert result["exit_code"] == 0
    assert opened.paths() == [ep.path for ep in W.ENDPOINTS]
    assert set(opened.timeouts) == {W.ENDPOINT_TIMEOUT_SEC}

    summary = result["summary"]
    assert summary["decision"] == "restart" and summary["warmed"] is True
    assert summary["cycles"] == 1
    assert [r["ok"] for r in summary["endpoints"]] == [True] * len(W.ENDPOINTS)
    assert all(isinstance(r["ms"], float) and r["bytes"] > 0 for r in summary["endpoints"])

    receipt = _receipt(state_root)
    assert receipt["status"] == "ok"
    assert receipt["produced_count"] == len(W.ENDPOINTS)
    assert receipt["schema"] == "LaneRunReceipt@v2"
    assert [e["path"] for e in receipt["summary"]["endpoints"]] == [ep.path for ep in W.ENDPOINTS]

    state = json.loads((state_root / "data" / "runtime" / W.STATE_NAME).read_text())
    assert state["boot_identity"] == f"4242:{START.isoformat()}"
    assert state["cycles"] == 1
    assert state["endpoints"] == [ep.path for ep in W.ENDPOINTS]


def test_a_restart_after_the_window_warms_again_and_resets_the_cycle_count(workspace, monkeypatch):
    monkeypatch.setattr(W, "_cc_urlopen", _Opener())
    _run(workspace)
    _run(workspace, now=START + timedelta(minutes=3))
    state = json.loads((workspace[0] / "data" / "runtime" / W.STATE_NAME).read_text())
    assert state["cycles"] == 2

    newer = _boot(workspace[1], pid=5151, started=START + timedelta(minutes=40), sha="1" * 40)
    opened = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened)
    result = _run(workspace, now=START + timedelta(minutes=41), boot_stamp=newer)
    assert result["summary"]["decision"] == "restart"
    assert result["summary"]["cycles"] == 1, "a new process is a new window, not the old cycle count"
    assert len(opened.urls) == len(W.ENDPOINTS)


# ── the no-op fires: the whole reason the lane can run every two minutes ─────────────────────────


def test_after_the_window_a_fire_does_no_http_work_and_still_leaves_a_receipt(workspace, monkeypatch):
    monkeypatch.setattr(W, "_cc_urlopen", _Opener())
    _run(workspace)

    opened = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened)
    result = _run(workspace, now=START + timedelta(minutes=11))
    assert result["summary"]["decision"] == "window_closed"
    assert result["summary"]["warmed"] is False
    assert result["exit_code"] == 0
    assert opened.urls == [], "a fire with nothing to do must not touch the API"

    receipt = _receipt(workspace[0])
    assert receipt["status"] == "ok"
    assert receipt["produced_count"] == 0
    assert receipt["empty_reason"] == "already_warm"
    assert receipt["summary"]["decision"] == "window_closed"


def test_a_second_warm_inside_the_interval_is_too_soon(workspace, monkeypatch):
    monkeypatch.setattr(W, "_cc_urlopen", _Opener())
    _run(workspace)
    opened = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened)
    result = _run(workspace, now=START + timedelta(seconds=30))
    assert result["summary"]["decision"] == "too_soon"
    assert opened.urls == []


def test_the_cycle_cap_stops_the_window_even_if_the_clock_lies(workspace, monkeypatch):
    # A start time in the future makes ``now - started_at`` negative, so the window never closes on its own.
    # The cycle cap is the rail that still bounds the lane; without it a clock skew would warm every fire.
    lying = _boot(workspace[1], started=START + timedelta(days=1))
    monkeypatch.setattr(W, "_cc_urlopen", _Opener())
    now = START
    for _ in range(W.WARM_MAX_CYCLES):
        result = _run(workspace, now=now, boot_stamp=lying)
        assert result["summary"]["warmed"] is True, result["summary"]["decision"]
        now += timedelta(minutes=2)
    opened = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened)
    result = _run(workspace, now=now, boot_stamp=lying)
    assert result["summary"]["decision"] == "cycle_cap"
    assert opened.urls == []


def test_an_unreadable_boot_stamp_warms_once_then_stops(workspace, monkeypatch):
    opened = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened)
    missing = workspace[1] / "absent.json"
    first = _run(workspace, boot_stamp=missing)
    assert first["summary"]["decision"] == "restart"
    assert len(opened.urls) == len(W.ENDPOINTS)

    opened2 = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened2)
    second = _run(workspace, boot_stamp=missing, now=START + timedelta(minutes=2))
    assert second["summary"]["decision"] == "boot_stamp_unreadable"
    assert opened2.urls == []


# ── a failed warm is not remembered, so the next fire retries ────────────────────────────────────


def test_one_failed_target_fails_the_run_and_leaves_no_state_to_hide_behind(workspace, monkeypatch):
    bad = W.ENDPOINTS[-1].path
    opened = _Opener(fail=(bad,))
    monkeypatch.setattr(W, "_cc_urlopen", opened)
    state_root, _ = workspace
    result = _run(workspace)
    assert result["exit_code"] == 1
    assert result["summary"]["failed"] == [bad]
    assert not (state_root / "data" / "runtime" / W.STATE_NAME).exists(), \
        "a partial warm must not be recorded as done"

    receipt = _receipt(state_root)
    assert receipt["status"] == "failed"
    assert receipt["produced_count"] == len(W.ENDPOINTS) - 1
    assert receipt["skipped_reasons"] == {bad: 1}
    row = next(r for r in receipt["summary"]["endpoints"] if r["path"] == bad)
    assert row["ok"] is False
    assert row["error"] == "TimeoutError"

    opened2 = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", opened2)
    retry = _run(workspace, now=START + timedelta(minutes=2))
    assert retry["summary"]["decision"] == "restart", "the retry is a full warm again"
    assert len(opened2.urls) == len(W.ENDPOINTS)


def test_a_non_200_answer_is_a_failure_not_a_warm(workspace, monkeypatch):
    monkeypatch.setattr(W, "_cc_urlopen", _Opener(status=503, body=b"{}"))
    result = _run(workspace)
    assert result["exit_code"] == 1
    assert result["summary"]["failed"] == [ep.path for ep in W.ENDPOINTS]
    assert not (workspace[0] / "data" / "runtime" / W.STATE_NAME).exists()


def test_only_the_first_post_restart_load_pays_the_cost(workspace, monkeypatch):
    """The lane's whole claim: the 30 s first load moves to the lane, and the next human load is cheap."""
    slow = _Opener(body=b"x" * 1024)
    monkeypatch.setattr(W, "_cc_urlopen", slow)
    first = _run(workspace)
    assert first["summary"]["warmed"] is True

    idle = _Opener()
    monkeypatch.setattr(W, "_cc_urlopen", idle)
    _run(workspace, now=START + timedelta(minutes=1))
    assert idle.urls == [], "within the interval the lane adds no load of its own"
