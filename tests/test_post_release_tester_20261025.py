"""Post-release tester (AGENTS.md §29 PROPOSED): API checks at once after a release, browser sweep only outside the
§28.8 window and under the memory gate, nightly sweep once a day, 'broken' detectors only. Hermetic: temp roots,
stubbed HTTP, memory and sweeper; nothing reaches 127.0.0.1:7777."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import delivery_failure_alerts as DFA  # noqa: E402
from scripts.lib import post_release_tester as PRT  # noqa: E402

SHA = "c" * 40
MON_NOON = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)  # Mon 12:00 ET
MON_1630 = datetime(2026, 10, 26, 20, 30, tzinfo=timezone.utc)  # Mon 16:30 ET
MON_2135 = datetime(2026, 10, 27, 1, 35, tzinfo=timezone.utc)  # Mon 21:35 ET
SAT_NOON = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)


def _layout(tmp_path: Path, served: str = SHA) -> dict:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "deploy_receipt_history.jsonl").write_text(
        json.dumps({"mode": "promote", "ok": True, "sha": SHA, "deployed_sha": SHA, "at": MON_NOON.isoformat()}) + "\n"
    )
    rel = tmp_path / "releases" / "rel1"
    rel.mkdir(parents=True)
    (rel / "BUILD_SHA").write_text(served + "\n")
    (tmp_path / "releases" / "CURRENT").symlink_to(rel)
    return {"deploy": deploy, "releases": tmp_path / "releases"}


def _findings(out_root: Path, findings: list, coverage: list, aborted=None):
    d = out_root / "20261026T203000Z"
    d.mkdir(parents=True)
    (d / "findings.json").write_text(
        json.dumps({"routes": 5, "aborted": aborted, "findings": findings, "coverage": coverage})
    )
    (d / "summary.md").write_text("# fixture\n")


class Sweeper:
    def __init__(self, rc=0, findings=(), coverage=(), aborted=None, write=True):
        self.calls, self.rc, self.f, self.c, self.aborted, self.write = (
            [],
            rc,
            list(findings),
            list(coverage),
            aborted,
            write,
        )

    def __call__(self, extra, timeout):
        self.calls.append(dict(extra))
        if self.write:
            _findings(Path(extra["SWEEP_OUT_ROOT"]), self.f, self.c, self.aborted)
        return self.rc, ""


def _env(tmp_path, now, *, http=None, mem=None, sweeper=None, served=SHA):
    lay = _layout(tmp_path, served)
    calls = []

    def get(url, timeout):
        calls.append(url)
        if http:
            return http(url)
        return (200, b'{"ok": true}') if url.endswith("/health") else (200, b"<html>")

    env = PRT.Env(
        state_root=tmp_path / "state",
        deploy_state_dir=lay["deploy"],
        releases_base=lay["releases"],
        project_root=tmp_path / "proj",
        now=now,
        config=PRT.load_config(),
        http_get=get,
        memory=lambda: mem,
        sweep_runner=sweeper,
        sleep=lambda s: None,
    )
    return env, calls


def test_blackout_window():
    cfg = PRT.load_config()
    assert PRT.browser_blocked(MON_NOON, cfg) is True
    assert PRT.browser_blocked(MON_1630, cfg) is False
    assert PRT.browser_blocked(SAT_NOON, cfg) is False


def test_noon_release_runs_api_now_and_defers_browser_until_after_1615(tmp_path):
    sw = Sweeper()
    env, calls = _env(tmp_path, MON_NOON, sweeper=sw)
    r = PRT.tick(env, live=True)
    assert r["planned"] == ["api", "light"]
    assert r["results"]["api"]["status"] == "PASSED" and r["results"]["light"]["status"] == "DEFERRED"
    assert sw.calls == [] and [u.rsplit("7777", 1)[1] for u in calls] == ["/api/v2/health", "/v3/cio", "/v3/"]
    env.now = MON_1630
    r2 = PRT.tick(env, live=True)
    assert r2["planned"] == ["light"] and r2["results"]["light"]["status"] == "PASSED"
    assert sw.calls[0]["SWEEP_VIEWPORTS"] == "m412,m390" and "/v3/cio" in sw.calls[0]["SWEEP_ROUTES"]
    env.now = MON_1630.replace(minute=40)
    assert PRT.tick(env, live=True)["planned"] == []


def test_api_failure_and_served_sha_mismatch_fail(tmp_path):
    env, _ = _env(
        tmp_path,
        SAT_NOON,
        http=lambda u: (502, b"") if u.endswith("/health") else (200, b""),
        served="d" * 40,
        sweeper=Sweeper(),
    )
    r = PRT.tick(env, live=True, force=["api"])
    assert r["results"]["api"]["status"] == "FAILED"
    rec = json.loads((env.dir / "last_api.json").read_text())
    bad = {c["name"] for c in rec["checks"] if c["ok"] is False}
    assert bad == {"health", "served_sha"}


def test_health_must_say_ok_true(tmp_path):
    env, _ = _env(tmp_path, SAT_NOON, http=lambda u: (200, b'{"ok": false}'))
    assert PRT.tick(env, live=True, force=["api"])["results"]["api"]["status"] == "FAILED"


def test_memory_gate_defers_and_marks_nothing(tmp_path):
    sw = Sweeper()
    env, calls = _env(tmp_path, SAT_NOON, mem=1_400_000_000, sweeper=sw)
    r = PRT.tick(env, live=True)
    assert {v["status"] for v in r["results"].values()} == {"DEFERRED"} and calls == [] and sw.calls == []
    assert "api_sha" not in json.loads((env.dir / "state.json").read_text())


def test_light_sweep_judges_only_broken_kinds_and_15s_loads(tmp_path):
    findings = [
        {
            "route": "/v3/cio",
            "viewport": "m412",
            "kind": "console_error",
            "severity": "broken",
            "detail": "1 err",
            "samples": ["TypeError: x"],
        },
        {"route": "/v3/cio", "viewport": "m412", "kind": "expected_refusal", "severity": "expected", "detail": "403"},
        {"route": "/v3/cio", "viewport": "m412", "kind": "slow_load", "severity": "broken", "detail": "9s"},
        {"route": "/v3/cio", "viewport": "m390", "kind": "dead_button", "severity": "broken", "detail": "x"},
        {"route": "/v3/watch", "viewport": "m412", "kind": "money_format", "severity": "data", "detail": "x"},
    ]
    coverage = [
        {"route": "/v3/cio", "viewport": "m412", "load_ms": 9000},
        {"route": "/v3/risk", "viewport": "m390", "load_ms": 16500},
    ]
    env, _ = _env(tmp_path, SAT_NOON, sweeper=Sweeper(findings=findings, coverage=coverage))
    r = PRT.tick(env, live=True, force=["light"])
    assert r["results"]["light"]["status"] == "FAILED"
    rec = json.loads((env.dir / "last_light.json").read_text())
    assert sorted(b["kind"] for b in rec["broken"]) == ["console_error", "slow_load"]
    assert rec["summary_path"].endswith("summary.md")


@pytest.mark.parametrize(
    "rc,write,status", [(3, False, "DEFERRED"), (5, False, "UNAVAILABLE"), (1, False, "FAILED"), (2, True, "DEFERRED")]
)
def test_sweeper_exit_codes(tmp_path, rc, write, status):
    env, _ = _env(tmp_path, SAT_NOON, sweeper=Sweeper(rc=rc, write=write, aborted="memory" if rc == 2 else None))
    assert PRT.tick(env, live=True, force=["light"])["results"]["light"]["status"] == status


def test_sweeper_missing_is_unavailable_and_retried(tmp_path):
    env, _ = _env(tmp_path, SAT_NOON)
    r = PRT.tick(env, live=True)
    assert r["results"]["light"]["status"] == "UNAVAILABLE"
    assert "light" in PRT.plan(env, PRT.load_state(env), PRT.current_release(env))


def test_nightly_once_a_day_in_window(tmp_path):
    sw = Sweeper()
    env, _ = _env(tmp_path, MON_2135, sweeper=sw)
    st = {"api_sha": SHA, "light_sha": SHA}
    assert PRT.plan(env, st, {"sha": SHA}) == ["nightly"]
    assert PRT.plan(env, {**st, "nightly_date": "2026-10-26"}, {"sha": SHA}) == []
    env.now = MON_1630
    assert PRT.plan(env, st, {"sha": SHA}) == []
    env.now = MON_2135
    (env.dir).mkdir(parents=True)
    (env.dir / "state.json").write_text(json.dumps(st))
    r = PRT.tick(env, live=True)
    assert r["results"]["nightly"]["status"] == "PASSED" and "SWEEP_VIEWPORTS" not in sw.calls[0]


def test_dry_run_runs_nothing(tmp_path):
    sw = Sweeper()
    env, calls = _env(tmp_path, SAT_NOON, sweeper=sw)
    r = PRT.tick(env, live=False)
    assert r["planned"] == ["api", "light"] and calls == [] and sw.calls == [] and not env.dir.exists()


def test_failed_tester_receipt_is_paged_by_the_alert_lane(tmp_path):
    env, _ = _env(tmp_path, SAT_NOON, http=lambda u: (500, b""))
    PRT.tick(env, live=True, force=["api"])
    ctx = DFA.Context(
        state_root=env.state_root,
        release_state_dir=tmp_path / "rw",
        deploy_state_dir=tmp_path / "x",
        now=SAT_NOON,
        config=DFA.load_config(),
        systemd_timers=lambda: [],
    )
    inc = DFA.detect_post_release(ctx)
    assert len(inc) == 1 and inc[0].line.startswith(f"post-release api check FAILED on {SHA[:9]}")
