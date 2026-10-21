"""Platform health (2026-10-21): GET /api/v2/system/platform-health — hermetic.

Every probe is fed fakes (subprocess runner, disk usage, DB reader, HTTP, clock); nothing touches docker, systemd,
the host disk, the n8n ledger or a database. Asserts: a failed / denied / slow probe is UNKNOWN with value None
(never OK, never 0), thresholds band correctly, per-probe and total time caps hold, the cache holds 30 s, and the
module never uses shell=True.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import platform_health as ph  # noqa: E402

NOW = datetime(2026, 10, 21, 13, 0, 0, tzinfo=timezone.utc)


def proc(stdout="", stderr="", rc=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=rc)


DU = SimpleNamespace


def make_deps(tmp_path, runner=None, **kw):
    cfg = tmp_path / "disk.json"
    cfg.write_text(json.dumps({"monitor": {"warn_pct": 80.0, "critical_pct": 90.0}}))
    base = dict(
        runner=runner or (lambda *a, **k: proc()),
        disk_usage=lambda p: DU(total=100, used=50, free=50),
        db_query=lambda *a, **k: {"size_bytes": 10 * 1024**3, "connections": 40, "max_connections": 200},
        http_get=lambda url, t: (200, '{"status":"ok"}'),
        loadavg=lambda: (1.0, 1.0, 1.0),
        cpu_count=lambda: 16,
        meminfo=lambda: "MemTotal: 1000000 kB\nMemAvailable: 500000 kB\n",
        now=lambda: NOW,
        state_root=tmp_path / "state",
        ledger_path=tmp_path / "ledger.sqlite",
        backup_dir=tmp_path / "db_backups",
        disk_config=cfg,
        probe_timeout_s=2.0,
    )
    base.update(kw)
    return ph.Deps(**base)


def by_id(items):
    return {i["id"]: i for i in items}


# ── the route exists (red before this change) ────────────────────────────────


def test_route_registered_and_handler_present():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    assert re.search(r'"/api/v2/system/platform-health":\s*_system_platform_health\b', src)
    assert "def _system_platform_health(" in src


def test_module_never_uses_shell_true():
    src = (ROOT / "scripts" / "lib" / "platform_health.py").read_text()
    assert "shell=True" not in src
    assert "os.system(" not in src and "os.popen(" not in src


# ── docker / n8n ─────────────────────────────────────────────────────────────


def test_docker_permission_denied_is_unknown_not_ok(tmp_path):
    def runner(argv, **kw):
        assert isinstance(argv, list) and kw.get("timeout") == 2.0 and "shell" not in kw
        return proc(stderr="permission denied while trying to connect to the Docker daemon socket", rc=1)

    items = ph.probe_n8n_containers(make_deps(tmp_path, runner))
    assert {i["status"] for i in items} == {"UNKNOWN"}
    assert all(i["value"] is None and "permission denied" in i["reason"] for i in items)


def test_docker_timeout_is_unknown(tmp_path):
    def runner(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    items = ph.probe_n8n_containers(make_deps(tmp_path, runner))
    assert [i["status"] for i in items] == ["UNKNOWN", "UNKNOWN"]


def test_containers_running_ok_with_uptime_and_unhealthy_crit(tmp_path):
    up = json.dumps({"Status": "running", "StartedAt": "2026-10-16T13:00:00Z"})
    sick = json.dumps({"Status": "running", "StartedAt": "2026-10-20T13:00:00Z", "Health": {"Status": "unhealthy"}})
    items = by_id(ph.probe_n8n_containers(make_deps(tmp_path, lambda a, **k: proc(stdout=up + "\n" + sick + "\n"))))
    n8n, db = items["n8n.container.m8m-n8n"], items["n8n.container.m8m-n8n-db"]
    assert n8n["status"] == "OK" and "up 5d" in n8n["value"] and n8n["detail"]["uptime_s"] == 5 * 86400
    assert db["status"] == "CRIT"


def test_container_exited_is_crit_and_missing_container_crit(tmp_path):
    ex = json.dumps({"Status": "exited", "StartedAt": "2026-10-16T13:00:00Z"})
    items = by_id(ph.probe_n8n_containers(make_deps(
        tmp_path, lambda a, **k: proc(stdout=ex + "\n", stderr="Error: No such object: m8m-n8n-db", rc=1))))
    assert items["n8n.container.m8m-n8n"]["status"] == "CRIT"
    assert items["n8n.container.m8m-n8n-db"]["status"] == "CRIT"
    assert items["n8n.container.m8m-n8n-db"]["value"] == "absent"


def test_healthz_refused_is_crit_timeout_unknown(tmp_path):
    import urllib.error

    def refused(url, t):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    def slow(url, t):
        raise urllib.error.URLError("timed out")

    assert ph.probe_n8n_healthz(make_deps(tmp_path))[0]["status"] == "OK"
    assert ph.probe_n8n_healthz(make_deps(tmp_path, http_get=refused))[0]["status"] == "CRIT"
    assert ph.probe_n8n_healthz(make_deps(tmp_path, http_get=slow))[0]["status"] == "UNKNOWN"


def test_active_workflows_count_and_failure(tmp_path):
    ok = ph.probe_n8n_active_workflows(make_deps(tmp_path, lambda a, **k: proc(stdout="17\n")))[0]
    assert ok["status"] == "OK" and ok["value"] == 17
    bad = ph.probe_n8n_active_workflows(make_deps(tmp_path, lambda a, **k: proc(stderr="boom", rc=1)))[0]
    assert bad["status"] == "UNKNOWN" and bad["value"] is None


def _ledger(path, requested_at):
    c = sqlite3.connect(path)
    c.execute("create table runs (requested_at text, state text, verdict text, lane_id text)")
    if requested_at:
        c.execute("insert into runs values (?, 'RUN_DONE', 'ok', 'scalp-hot-list')", (requested_at,))
    c.commit()
    c.close()


@pytest.mark.parametrize("age_min,expected", [(4, "OK"), (20, "WARN"), (90, "CRIT")])
def test_dispatcher_age_bands(tmp_path, age_min, expected):
    _ledger(tmp_path / "ledger.sqlite", (NOW - timedelta(minutes=age_min)).isoformat())
    assert ph.probe_n8n_dispatcher(make_deps(tmp_path))[0]["status"] == expected


def test_dispatcher_ledger_absent_is_unknown(tmp_path):
    it = ph.probe_n8n_dispatcher(make_deps(tmp_path))[0]
    assert it["status"] == "UNKNOWN" and it["value"] is None


def test_dispatcher_ledger_is_opened_read_only(tmp_path):
    p = tmp_path / "ledger.sqlite"
    _ledger(p, NOW.isoformat())
    before = p.stat().st_mtime_ns
    ph.probe_n8n_dispatcher(make_deps(tmp_path))
    assert p.stat().st_mtime_ns == before
    assert not (tmp_path / "ledger.sqlite-wal").exists()


# ── host units ───────────────────────────────────────────────────────────────


def _show_block(unit, load="loaded", active="active", sub="running", ts="@1792587304", restarts="0"):
    return (f"Id={unit}\nLoadState={load}\nActiveState={active}\nSubState={sub}\n"
            f"ActiveEnterTimestamp={ts}\nNRestarts={restarts}\n")


def test_units_use_real_tradeai_ids_and_band(tmp_path):
    seen = {}

    def runner(argv, **kw):
        seen["argv"] = argv
        blocks = []
        for u in ph.ALWAYS_ON_UNITS:
            if u == "tradeai-ops-agent.service":
                blocks.append(_show_block(u, active="failed", sub="failed"))
            elif u == "tradeai-lab-postgres.service":
                blocks.append(_show_block(u, load="not-found", active="inactive", sub="dead", ts=""))
            elif u == "tradeai-health-agent.service":
                blocks.append(_show_block(u, active="activating", sub="auto-restart"))
            else:
                blocks.append(_show_block(u, restarts="2"))
        return proc(stdout="\n".join(blocks))

    items = by_id(ph.probe_units(make_deps(tmp_path, runner)))
    assert "tradeai-cio-telegram.service" in seen["argv"] and "cio-telegram.service" not in seen["argv"]
    assert items["unit.portfolio-server"]["status"] == "OK"
    assert "2 restart" in items["unit.portfolio-server"]["value"]
    assert items["unit.tradeai-ops-agent"]["status"] == "CRIT"
    assert items["unit.tradeai-health-agent"]["status"] == "WARN"
    lab = items["unit.tradeai-lab-postgres"]
    assert lab["status"] == "UNKNOWN" and lab["value"] is None and "not-found" in lab["reason"]


def test_units_systemctl_failure_is_unknown_for_every_unit(tmp_path):
    items = ph.probe_units(make_deps(tmp_path, lambda a, **k: proc(stderr="Failed to connect to bus", rc=1)))
    assert len(items) == len(ph.ALWAYS_ON_UNITS)
    assert {i["status"] for i in items} == {"UNKNOWN"}


def test_failed_units_named(tmp_path):
    out = "tradeai-portfolio-backup-cadence.service loaded failed failed TradeAI backup\n"
    it = ph.probe_failed_units(make_deps(tmp_path, lambda a, **k: proc(stdout=out)))[0]
    assert it["status"] == "WARN" and it["value"] == 1
    assert it["detail"]["units"] == ["tradeai-portfolio-backup-cadence.service"]
    clean = ph.probe_failed_units(make_deps(tmp_path, lambda a, **k: proc(stdout="")))[0]
    assert clean["status"] == "OK" and clean["value"] == 0
    denied = ph.probe_failed_units(make_deps(tmp_path, lambda a, **k: proc(rc=1)))[0]
    assert denied["status"] == "UNKNOWN" and denied["value"] is None


# ── disk / cpu / memory ──────────────────────────────────────────────────────


@pytest.mark.parametrize("used,expected", [(79, "OK"), (80, "WARN"), (89, "WARN"), (90, "CRIT"), (97, "CRIT")])
def test_disk_bands_follow_disk_hygiene_config(tmp_path, used, expected):
    deps = make_deps(tmp_path, disk_usage=lambda p: DU(total=100, used=used, free=100 - used))
    items = by_id(ph.probe_disk(deps))
    assert items["host.disk.root"]["status"] == expected


def test_disk_thresholds_read_from_repo_config():
    warn, crit, _ = ph.disk_thresholds(ph.DISK_CONFIG)
    cfg = json.loads(ph.DISK_CONFIG.read_text())["monitor"]
    assert (warn, crit) == (float(cfg["warn_pct"]), float(cfg["critical_pct"]))


def test_disk_failure_is_unknown(tmp_path):
    def boom(p):
        raise PermissionError(p)

    items = ph.probe_disk(make_deps(tmp_path, disk_usage=boom))
    assert {i["status"] for i in items} == {"UNKNOWN"} and all(i["value"] is None for i in items)


def test_cpu_and_memory_bands(tmp_path):
    assert ph.probe_cpu(make_deps(tmp_path, loadavg=lambda: (30, 30, 30)))[0]["status"] == "WARN"
    assert ph.probe_cpu(make_deps(tmp_path, loadavg=lambda: (60, 60, 60)))[0]["status"] == "CRIT"
    assert ph.probe_cpu(make_deps(tmp_path, cpu_count=lambda: None))[0]["status"] == "UNKNOWN"
    low = "MemTotal: 1000000 kB\nMemAvailable: 100000 kB\n"
    assert ph.probe_memory(make_deps(tmp_path, meminfo=lambda: low))[0]["status"] == "WARN"
    assert ph.probe_memory(make_deps(tmp_path, meminfo=lambda: "garbage"))[0]["status"] == "UNKNOWN"


# ── backup ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("age_h,expected", [(25, "OK"), (27, "WARN"), (51, "CRIT")])
def test_backup_age_bands(tmp_path, age_h, expected):
    import os

    d = tmp_path / "db_backups"
    d.mkdir()
    f = d / "trade_ai_20261020_023000.sql.gz"
    f.write_bytes(b"x")
    t = (NOW - timedelta(hours=age_h)).timestamp()
    os.utime(f, (t, t))
    (d / "trade_ai_20261021_023000.sql.gz.part").write_bytes(b"in flight")  # not a finished dump
    assert ph.probe_backup_artifact(make_deps(tmp_path))[0]["status"] == expected


def test_backup_dir_absent_unknown_empty_crit(tmp_path):
    assert ph.probe_backup_artifact(make_deps(tmp_path))[0]["status"] == "UNKNOWN"
    (tmp_path / "db_backups").mkdir()
    assert ph.probe_backup_artifact(make_deps(tmp_path))[0]["status"] == "CRIT"


def test_backup_unit_failed_result_is_warn(tmp_path):
    out = "LoadState=loaded\nActiveState=failed\nResult=exit-code\nExecMainStatus=1\nExecMainExitTimestamp=@1792565528\n"
    it = ph.probe_backup_unit(make_deps(tmp_path, lambda a, **k: proc(stdout=out)))[0]
    assert it["status"] == "WARN" and it["detail"]["result"] == "exit-code"
    ok = out.replace("failed", "inactive").replace("exit-code", "success").replace("=1", "=0")
    assert ph.probe_backup_unit(make_deps(tmp_path, lambda a, **k: proc(stdout=ok)))[0]["status"] == "OK"


# ── Postgres ─────────────────────────────────────────────────────────────────


def test_postgres_unreachable_is_unknown_not_zero(tmp_path):
    it = ph.probe_postgres(make_deps(tmp_path, db_query=lambda *a, **k: None))[0]
    assert it["status"] == "UNKNOWN" and it["value"] is None and it["detail"] == {}


def test_postgres_select_is_read_only_and_bands(tmp_path):
    seen = {}

    def q(sql, params=None, fetch=None):
        seen["sql"] = sql
        return {"size_bytes": 5 * 1024**3, "connections": 170, "max_connections": 200}

    it = ph.probe_postgres(make_deps(tmp_path, db_query=q))[0]
    assert it["status"] == "WARN" and it["detail"]["connections"] == 170
    assert "statement_timeout" in seen["sql"]
    assert not re.search(r"\b(insert|update|delete|drop|alter|create|truncate|grant)\b", seen["sql"], re.I)


# ── time caps, never-raise, cache ────────────────────────────────────────────


def test_slow_probe_is_unknown_and_total_budget_holds(tmp_path):
    def slow(deps):
        time.sleep(1.0)
        return [ph._item("x.slow", "x", "slow", "test", "OK", 1, None, None)]

    def boom(deps):
        raise RuntimeError("kaboom")

    def fast(deps):
        return [ph._item("x.fast", "x", "fast", "test", "OK", 1, None, None)]

    deps = make_deps(tmp_path, probe_timeout_s=0.2)
    probes = [(slow, [("x.slow", "x", "slow", "test")]), (boom, [("x.boom", "x", "boom", "test")]),
              (fast, [("x.fast", "x", "fast", "test")])]
    t0 = time.monotonic()
    out = ph.collect(deps, total_budget_s=0.5, probes=probes)
    assert time.monotonic() - t0 < 0.9
    items = by_id(out["items"])
    assert items["x.slow"]["status"] == "UNKNOWN" and items["x.slow"]["value"] is None
    assert items["x.boom"]["status"] == "UNKNOWN" and "kaboom" in items["x.boom"]["reason"]
    assert items["x.fast"]["status"] == "OK"
    assert out["counts"]["UNKNOWN"] == 2


def test_hung_db_probe_does_not_block_the_response(tmp_path):
    def hung(*a, **k):
        time.sleep(1.5)
        return {"size_bytes": 1, "connections": 1, "max_connections": 10}

    deps = make_deps(tmp_path, db_query=hung, probe_timeout_s=0.3)
    t0 = time.monotonic()
    out = ph.collect(deps, total_budget_s=1.0, probes=[(ph.probe_postgres, [ph.PG_SPEC])])
    assert time.monotonic() - t0 < 0.8
    assert out["items"][0]["status"] == "UNKNOWN" and out["items"][0]["value"] is None
    time.sleep(1.3)  # let the DB worker drain before the next test uses it


def test_full_collect_with_everything_failing_is_all_unknown_never_ok(tmp_path):
    def runner(argv, **kw):
        raise OSError("no such binary")

    def http(url, t):
        raise OSError("down")

    deps = make_deps(tmp_path, runner, db_query=lambda *a, **k: None, http_get=http,
                     disk_usage=lambda p: (_ for _ in ()).throw(OSError()), loadavg=lambda: 1 / 0,
                     meminfo=lambda: "")
    out = ph.collect(deps)
    assert out["items"], "every probe still yields rows"
    assert {i["status"] for i in out["items"]} <= {"UNKNOWN", "CRIT"}
    assert all(i["value"] is None for i in out["items"] if i["status"] == "UNKNOWN")
    assert out["overall"] != "OK"
    ids = {i["id"] for i in out["items"]}
    assert "postgres.main" in ids and "unit.portfolio-server" in ids and "backup.cadence_unit" in ids


def test_every_item_has_the_contract_fields(tmp_path):
    out = ph.collect(make_deps(tmp_path))
    for it in out["items"]:
        assert set(it) >= {"status", "value", "as_of", "source", "reason"}
        assert it["status"] in ph.STATUSES


def test_cache_holds_30s(tmp_path):
    ph._reset_cache()
    calls = {"n": 0}

    def q(*a, **k):
        calls["n"] += 1
        return {"size_bytes": 1, "connections": 1, "max_connections": 10}

    clock = {"t": 1000.0}
    deps = make_deps(tmp_path, db_query=q)
    a = ph.get_platform_health(deps=deps, clock=lambda: clock["t"])
    clock["t"] += 29
    b = ph.get_platform_health(deps=deps, clock=lambda: clock["t"])
    assert a["cached"] is False and b["cached"] is True and calls["n"] == 1
    clock["t"] += 2
    c = ph.get_platform_health(deps=deps, clock=lambda: clock["t"])
    assert c["cached"] is False and calls["n"] == 2
    ph._reset_cache()
