"""Releases & Schedules projection (GET /api/v2/ops/releases-schedules), operator-approved 2026-10-22.

Hermetic (AGENTS.md §24.6): every path is under ``tmp_path`` (releases base, deploy state, release-window state,
ledger, registry, live-lane list), TRADEAI_STATE_ROOT points at ``tmp_path``, git / crontab / readiness readers are
injected, and the queue's ``db_query`` is a stub. No network, no live DB, no production state root, no send.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import releases_schedules_view as R  # noqa: E402

NOW = datetime(2026, 10, 22, 19, 0, tzinfo=timezone.utc)  # 15:00 ET
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_MAIN = "c" * 40


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", raising=False)
    R.clear_cache()
    yield
    R.clear_cache()


def _release(base: Path, name: str, sha: str) -> Path:
    d = base / name
    d.mkdir(parents=True)
    for pin in ("BUILD_SHA", "GIT_SHA", "SOURCE_COMMIT"):
        (d / pin).write_text(sha + "\n")
    return d


def _ledger(path: Path, rows: list[tuple], dead: list[tuple] = ()) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT, "
              "started_at TEXT, finished_at TEXT, exit_code INTEGER, receipt_json TEXT)")
    c.execute("CREATE TABLE dead_letters (slot_key TEXT PRIMARY KEY, lane_id TEXT, dead_at TEXT, last_state TEXT, "
              "last_reason TEXT, released_at TEXT)")
    c.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)", rows)
    c.executemany("INSERT INTO dead_letters VALUES (?,?,?,?,?,?)", dead)
    c.commit()
    c.close()
    return path


def _git(head: str = SHA_MAIN, subjects: dict | None = None):
    subjects = subjects or {}

    def run(args):
        if args[0] == "rev-parse":
            return 0, head + "\n"
        if args[:2] == ["log", "-1"]:
            return 0, "2026-10-22T15:25:39-04:00\x1fMerge pull request #1927 from x/y\n"
        if args[0] == "log":
            rng = args[-1]
            if rng in subjects:
                return 0, "\n".join(subjects[rng]) + "\n"
            return 128, ""
        raise AssertionError(args)
    return run


@pytest.fixture
def host(tmp_path):
    base = tmp_path / "releases"
    old = _release(base, "aaaaaaaaa-main-exact-phase2-20261022-084212", SHA_A)
    new = _release(base, "bbbbbbbbb-main-exact-phase2-20261022-110850", SHA_B)
    (base / "CURRENT").symlink_to(new)
    (base / "ACTIVE_RELEASE").write_text(str(new.resolve()) + "\n")
    (base / "EXPECTED_RELEASE").write_text(str(new.resolve()) + "\n")
    dep = tmp_path / "deploy"
    (dep / "release_pins").mkdir(parents=True)
    (dep / "release_pins" / "apply-20261022T124319774974Z.json").write_text(json.dumps(
        {"schema": "ReleasePinReceipt@v1", "mode": "apply", "at": "2026-10-22T12:43:19+00:00",
         "target_release": str(old), "from_release": ""}))
    (dep / "release_pins" / "apply-20261022T151109676387Z.json").write_text(json.dumps(
        {"schema": "ReleasePinReceipt@v1", "mode": "apply", "at": "2026-10-22T15:11:09+00:00",
         "target_release": str(new), "from_release": ""}))
    (dep / "deploy_receipt.json").write_text(json.dumps(
        {"ok": True, "mode": "promote", "health": "ok", "at": "2026-10-22T15:11:31+00:00", "deployed_sha": SHA_B,
         "rolled_back": False, "readback_errors": [], "prev_release": str(old), "extra": "promote_ok"}))
    (dep / "post_merge_ci.json").write_text(json.dumps(
        {"ok": True, "candidate_sha": SHA_B, "checks": [
            {"name": "agent-governance", "status": "completed", "conclusion": "success",
             "updated_at": "2026-10-22T14:34:07Z"}]}))
    rw = tmp_path / "state" / "data" / "runtime" / "release_window"
    rw.mkdir(parents=True)
    today = "2026-10-22T"
    ledger = _ledger(tmp_path / "state" / "data" / "governance" / "n8n_coordination_ledger.sqlite", [
        ("r1", "heartbeat-watch", "live", "RUN_DONE", today + "18:55:00+00:00", None, today + "18:55:05+00:00", 0, "{}"),
        ("r2", "heartbeat-watch", "live", "RUN_DONE", today + "18:50:00+00:00", None, None, 0, "{}"),
        ("r3", "watchlist-enrichment-sweep", "live", "RUN_TIMEOUT", today + "15:00:00+00:00", None, None, 124,
         json.dumps({"reason": "executor_lost", "env_allowlist": {"dropped_names": ["SECRET_NAME"]}})),
        ("r4", "data-gap-resolver", "dry_run", "RUN_SKIPPED_LOCK", today + "16:00:00+00:00", None, None, 75, "{}"),
        ("r5", "old-lane", "live", "RUN_FAILED", "2026-10-21T20:00:00+00:00", None, None, 1, "{}"),
    ], dead=[("k1", "some-lane", "2026-10-22T10:00:00+00:00", "RUN_FAILED", "boom", None),
             ("k2", "some-lane", "2026-10-21T10:00:00+00:00", "RUN_FAILED", "boom", "2026-10-21T11:00:00+00:00")])
    registry = tmp_path / "lane_registry.json"
    registry.write_text(json.dumps({"lanes": [
        {"lane_id": "cost-basis-sync", "state": "ACTIVE",
         "scheduler": {"kind": "cron", "expression": "33 16 * * 1-5", "match": "scripts/cost_basis_sync.py"}},
        {"lane_id": "entry-plans", "state": "ACTIVE",
         "scheduler": {"kind": "cron", "expression": "35 17 * * 1-5", "match": "scripts/entry_plans.py",
                       "stage": "shadow"}},
        {"lane_id": "heartbeat-watch", "state": "ACTIVE",
         "scheduler": {"kind": "n8n", "expression": "wf1", "cadence": "*/5 * * * *"}},
        {"lane_id": "retired-lane", "state": "RETIRED",
         "scheduler": {"kind": "n8n", "expression": "wf2", "cadence": "*/5 * * * *"}},
    ]}))
    live = tmp_path / "n8n-live-lanes.env"
    live.write_text("SOME_SECRET=never-read\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch,other\n")
    paths = {"releases_base": base, "deploy_state_dir": dep, "canonical_source": tmp_path / "canonical",
             "release_window_state_dir": rw, "ledger": ledger, "live_lanes_env": live, "registry": registry}
    crontab = ("SHELL=/bin/bash\n"
               "35 17 * * 1-5 cd $P && python scripts/entry_plans.py >> logs/x.log 2>&1\n"
               "*/5 * * * * cd $P && python scripts/watchdog.py\n"
               "# PAUSED 2026-10-14 schwab-app-deactivated 33 16 * * 1-5 cd $P && python scripts/cost_basis_sync.py\n"
               "# a plain comment 0 1 * * * nothing\n")
    readiness = {"schema": "ReleaseTrainReadiness@v1", "state": "OK", "as_of": NOW.isoformat(),
                 "stop": {"state": "ABSENT", "effective_stop": False}, "armed": False, "shadow_enabled": True,
                 "delegation": {"state": "PAUSED", "source": "test"}, "policy_version": "t",
                 "shadow_coverage": [{"slot": "1800", "last_requested_at": None, "request_id": None,
                                      "receipt_state": None}]}
    git = _git(subjects={f"{SHA_B}..{SHA_MAIN}": ["Merge pull request #1927 from a/b", "fix x (#1934)"],
                         f"{SHA_A}..{SHA_B}": ["Merge pull request #1918 from a/b"]})
    return {"paths": paths, "crontab": lambda: (crontab, "crontab", None, None), "readiness": lambda: readiness,
            "git": git, "rw": rw, "dep": dep, "base": base}


def _build(host, **kw):
    return R.build(lambda *a, **k: None, now=NOW, paths=host["paths"], git=host["git"],
                   crontab_reader=host["crontab"], readiness=host["readiness"], **kw)


def test_full_projection_reads_every_fixture_source(host):
    d = _build(host)
    assert d["schema"] == "ReleasesSchedules@v1" and d["authority"] == "READ_ONLY_ADVISORY"
    sv = d["serving"]["value"]
    assert sv["sha"] == SHA_B and sv["pins_agree"] is True and sv["since_basis"] == "deploy_receipt.at"
    nx = d["next_release"]["value"]
    assert nx["sha"] == SHA_MAIN and nx["commits_ahead"] == 2 and nx["prs_since_serving"] == [1927, 1934]
    assert nx["ci"]["state"] == "UNAVAILABLE" and "not main HEAD" in nx["ci"]["reason"]
    hist = d["history"]["value"]["releases"]
    assert [r["sha"] for r in hist] == [SHA_B, SHA_A]
    assert hist[0]["prs"] == [1918] and hist[0]["verify"]["ok"] is True and hist[0]["serving"] is True
    assert hist[1]["verify"] is None and "not retained" in hist[1]["verify_reason"]
    assert hist[1]["prs"] is None and hist[1]["prs_reason"]


def test_kpis_and_n8n_today_from_ledger(host):
    d = _build(host)
    td = d["n8n_today"]["value"]
    assert td["total"] == 4  # r5 is yesterday ET and excluded
    assert td["by_mode"] == {"live": 3, "dry_run": 1}
    assert td["errors_total"] == 1 and td["skips_total"] == 1
    assert td["errors"][0]["lane"] == "watchlist-enrichment-sweep" and td["errors"][0]["reason"] == "executor_lost"
    assert "SECRET_NAME" not in json.dumps(d)  # receipt env names never leave the ledger
    assert td["dead_letters"] == {"available": True, "unreleased": 1, "recent": td["dead_letters"]["recent"]}
    assert td["busiest"][0] == {"lane": "heartbeat-watch", "runs": 2, "errors": 0, "skips": 0}
    k = {x["key"]: x for x in d["kpis"]}
    assert k["serving"]["value"] == SHA_B[:9] and k["n8n_runs"]["value"] == 4
    assert k["n8n_errors"]["value"] == "1 · 1"
    assert k["next_window"]["value"] == "18:00" and "SHADOW" in k["next_window"]["detail"]


def test_windows_state_and_reason_from_host_gate(host):
    w = _build(host)["windows"]["value"]
    assert w["windows"][0]["local_time"] == "18:00"
    assert all(x["state"] == "SHADOW" and "simulate only" in x["reason"] for x in w["windows"])
    stopped = dict(host["readiness"]())
    stopped["stop"] = {"state": "SET", "effective_stop": True}
    w2 = R.read_windows(NOW, rw_state_dir=host["rw"], readiness=lambda: stopped)["value"]
    assert {x["state"] for x in w2["windows"]} == {"STOPPED"}
    off = dict(host["readiness"]())
    off["shadow_enabled"] = False
    w3 = R.read_windows(NOW, rw_state_dir=host["rw"], readiness=lambda: off)["value"]
    assert {x["state"] for x in w3["windows"]} == {"OFF"}


def test_timeline_merges_cron_paused_and_n8n(host):
    tl = _build(host)["timeline"]["value"]
    assert tl["crontab"]["active_lines"] == 2 and tl["crontab"]["paused_lines"] == 1
    disc = {(r["lane"], r["runner"], r["stage"]) for r in tl["rows"]}
    assert ("cost-basis-sync", "cron", "PAUSED") in disc
    paused = next(r for r in tl["rows"] if r["stage"] == "PAUSED")
    assert paused["paused_since"] == "2026-10-14" and paused["paused_note"] == "schwab-app-deactivated"
    assert paused["at"] == "2026-10-22T20:33:00+00:00"
    assert ("entry-plans", "cron", "LIVE") in disc and ("entry-plans", "n8n", "SHADOW") in disc
    rec = {(r["lane"], r["runner"]): r for r in tl["recurring"]}
    assert rec[("heartbeat-watch", "n8n")]["stage"] == "LIVE" and rec[("heartbeat-watch", "n8n")]["in_relay_live_list"]
    assert rec[("heartbeat-watch", "n8n")]["cadence_label"] == "every 5 min"
    assert rec[("heartbeat-watch", "n8n")]["last_run"]["state"] == "RUN_DONE"
    assert ("watchdog.py", "cron") in rec
    assert not any(r["lane"] == "retired-lane" for r in tl["rows"] + tl["recurring"])
    assert "never-read" not in json.dumps(tl)


def test_parse_crontab_paused_and_env_lines():
    active, paused = R.parse_crontab("A=1\n@hourly cmd one\n0 9 * * 1-5 cmd two\n"
                                     "# PAUSED 2026-10-15 note words (grant x) */15 9-16 * * 1-5 cmd three\n# x\n")
    assert [a["schedule"] for a in active] == ["@hourly", "0 9 * * 1-5"]
    assert paused == [{"since": "2026-10-15", "note": "note words (grant x)", "schedule": "*/15 9-16 * * 1-5",
                       "command": "cmd three"}]


def test_unavailable_sources_are_null_never_zero(host, tmp_path):
    paths = dict(host["paths"], releases_base=tmp_path / "nope", ledger=tmp_path / "nope.sqlite",
                 deploy_state_dir=tmp_path / "nodeploy", registry=tmp_path / "noreg.json")
    d = R.build(lambda *a, **k: None, now=NOW, paths=paths, git=lambda a: (128, ""),
                crontab_reader=lambda: ("", "none", "crontab -l denied", None), readiness=host["readiness"])
    for key in ("serving", "next_release", "n8n_today", "timeline", "history", "queue"):
        assert d[key]["freshness"] == "UNAVAILABLE", key
        assert d[key]["value"] is None and d[key]["reason"], key
    k = {x["key"]: x for x in d["kpis"]}
    for key in ("serving", "next_release", "n8n_runs", "n8n_errors"):
        assert k[key]["value"] is None and k[key]["freshness"] == "UNAVAILABLE", key
    assert d["status"] == "DEGRADED"


def test_release_errors_window_refusal_rollback_and_stop(host):
    wdir = host["rw"] / "windows"
    wdir.mkdir()
    (wdir / "2026-10-22T1200.json").write_text(json.dumps(
        {"outcome": "STOP_CI_PENDING", "started_at": "2026-10-22T16:00:00+00:00", "detail": "exact-SHA CI running"}))
    (wdir / "2026-10-21T1730.json").write_text(json.dumps({"outcome": "RELEASED", "started_at": "2026-10-21T21:30:00+00:00"}))
    (host["dep"] / "release_pins" / "rollback-20261022T170000000000Z.json").write_text(json.dumps(
        {"mode": "rollback", "at": "2026-10-22T17:00:00+00:00", "target_release": "/x/a-1", "from_release": "/x/b-2"}))
    ci = json.loads((host["dep"] / "post_merge_ci.json").read_text())
    ci["checks"].append({"name": "cio-production-hardening-ci", "status": "completed", "conclusion": "timed_out",
                         "updated_at": "2026-10-22T14:02:00Z"})
    (host["dep"] / "post_merge_ci.json").write_text(json.dumps(ci))
    stop = {"state": "SET", "effective_stop": True, "latched_at": "2026-10-22T18:00:00+00:00", "latch_reason": "verify"}
    v = R.read_release_errors(host["dep"], host["rw"], NOW, stop=stop)["value"]
    kinds = [r["kind"] for r in v["rows"]]
    assert "window stop_ci_pending" in kinds and "rollback" in kinds and "main CI timed_out" in kinds
    assert "release STOP SET" in kinds and not any("released" in k for k in kinds)
    assert v["not_covered"]


def test_handle_route_get_only_and_cache(host, monkeypatch):
    calls = []
    monkeypatch.setattr(R, "build", lambda db: calls.append(1) or {"schema": R.SCHEMA})
    assert R.handle("/api/v2/ops/other", "GET", {}, None) is None
    assert R.handle(R.ROUTE, "POST", {}, None)[0] == 405
    s1, b1 = R.handle(R.ROUTE, "GET", {}, None)
    s2, b2 = R.handle(R.ROUTE + "/", "GET", {}, None)
    assert s1 == s2 == 200 and b1["data"]["cache"] == "MISS" and b2["data"]["cache"] == "HIT" and len(calls) == 1


def test_api_v2_wires_route_before_generic_handlers():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    i = src.index('if base_path.rstrip("/") == "/api/v2/ops/releases-schedules":')
    assert i < src.index("# Inference Layers routes") < src.index("handler = ROUTES.get(base_path)")


def test_module_is_read_only():
    src = (ROOT / "scripts" / "lib" / "releases_schedules_view.py").read_text(encoding="utf-8")
    for bad in ("write_text(", "open(\"w", "INSERT ", "UPDATE ", "DELETE ", "requests.", "urllib", "place_order",
                "telegram", "\"fetch\"", "git push", "gh api"):
        assert bad not in src, bad
    assert "mode=ro" in src and "PRAGMA query_only" in src


def test_git_runner_refuses_non_read_subcommands(tmp_path):
    run = R.git_runner(tmp_path)
    for args in (["fetch"], ["push"], ["checkout", "x"], []):
        with pytest.raises(ValueError):
            run(args)


def test_no_production_paths_touched(host):
    d = _build(host)
    blob = json.dumps(d)
    assert str(Path.home() / "trade-ai-releases") not in blob
    assert os.environ["TRADEAI_STATE_ROOT"].startswith(str(host["base"].parent))


def test_stale_fetch_marks_next_release_stale(host, tmp_path):
    canonical = tmp_path / "canon"
    (canonical / ".git").mkdir(parents=True)
    fh = canonical / ".git" / "FETCH_HEAD"
    fh.write_text("x")
    old = (NOW - timedelta(hours=10)).timestamp()
    os.utime(fh, (old, old))
    f = R.read_next_release(canonical, host["dep"], SHA_B, NOW, git=host["git"])
    assert f["freshness"] == "STALE" and f["age_s"] == 36000
    os.utime(fh, (NOW.timestamp() - 60,) * 2)
    assert R.read_next_release(canonical, host["dep"], SHA_B, NOW, git=host["git"])["freshness"] == "OK"
