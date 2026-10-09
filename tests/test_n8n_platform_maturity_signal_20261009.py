"""N8nPlatformMaturity@v1 signal dimensions (4 observability, 5 alert delivery, 10 reliability) — hermetic.

Fixtures live under tmp_path (state root + repo checkout); every command goes through a fake runner; ``now`` is
fixed. Covers scoring from fixtures, missing evidence (0 + UNVERIFIED) and the 8.0 gate boundaries.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))

from n8n_maturity import core, dims_signal  # noqa: E402

NOW = dt.datetime(2026, 10, 9, 20, 0, tzinfo=dt.timezone.utc)
REAL_CONFIG = json.loads((PROJ / "config" / "n8n_platform_maturity.json").read_text(encoding="utf-8"))
SIGNAL_DIMS = ("observability", "alert_delivery", "reliability")


def _config(dims=None, **top):
    """The real config file, with per-dimension keys and top-level keys overridden for the test."""
    cfg = copy.deepcopy(REAL_CONFIG)
    for d, kv in (dims or {}).items():
        cfg["dimensions"].setdefault(d, {}).update(kv)
    cfg.update(top)
    return cfg


def _iso(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


class FakeHost:
    """Fake read-only runner. Unknown commands fail (rc 1)."""

    def __init__(self, *, timer_active=True, exec_start="argv[]=python scripts/research_lane_health.py --alert",
                 crontab=None, docker_ps="m8m-n8n n8nio/n8n:2.43.0\nm8m-n8n-db postgres:16.15-alpine\n",
                 n8n_errors="0", journal="", journal_rc=0, failed_units="", failed_rc=0):
        self.timer_active, self.exec_start, self.crontab = timer_active, exec_start, crontab
        self.docker_ps, self.n8n_errors, self.journal, self.journal_rc = docker_ps, n8n_errors, journal, journal_rc
        self.failed_units, self.failed_rc = failed_units, failed_rc
        self.calls: list[list[str]] = []

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        if argv[:3] == ["systemctl", "--user", "show"]:
            if argv[3].endswith(".timer"):
                return 0, f"ActiveState={'active' if self.timer_active else 'inactive'}\n", ""
            return 0, f"ExecStart={{ {self.exec_start} }}\n", ""
        if argv[:2] == ["crontab", "-l"]:
            return (0, self.crontab, "") if self.crontab is not None else (1, "", "no crontab")
        if argv[:2] == ["docker", "ps"]:
            return (0, self.docker_ps, "") if self.docker_ps is not None else (1, "", "no docker")
        if argv[:2] == ["docker", "exec"]:
            return (0, self.n8n_errors + "\n", "") if self.n8n_errors is not None else (1, "", "psql failed")
        if argv[0] == "journalctl":
            return self.journal_rc, self.journal, ""
        if argv[:4] == ["systemctl", "--user", "list-units", "--failed"]:
            return self.failed_rc, self.failed_units, ""
        return 1, "", "unexpected"


def _probe(tmp_path, host=None, dims=None, config=None):
    root, proj = tmp_path / "state", tmp_path / "proj"
    root.mkdir(exist_ok=True)
    proj.mkdir(exist_ok=True)
    return core.Probe(root=root, proj=proj, now=NOW, config=config if config is not None else _config(dims),
                      runner=host or FakeHost())


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


# ── observability fixtures ──────────────────────────────────────────────────

def _registry(tmp_path, n_signal: int, n_none: int, extra_retired: int = 1):
    lanes = [{"lane_id": f"s{i}", "state": "ACTIVE", "expected_cadence_hours": 1,
              "output_signal": {"kind": "file_mtime", "path": "x"}} for i in range(n_signal)]
    lanes += [{"lane_id": f"n{i}", "state": "ACTIVE", "expected_cadence_hours": 1,
               "output_signal": {"kind": "none"}} for i in range(n_none)]
    lanes += [{"lane_id": f"r{i}", "state": "RETIRED", "expected_cadence_hours": 1,
               "output_signal": {"kind": "none"}} for i in range(extra_retired)]
    _write(tmp_path / "proj" / "config" / "lane_registry.json", {"lanes": lanes})
    return lanes


def _monitor(tmp_path, lanes, *, age_hours=0.1, unverifiable=()):
    rows = []
    for r in lanes:
        kind = r["output_signal"]["kind"]
        v = "UNVERIFIABLE" if kind == "none" or r["lane_id"] in unverifiable else "LIVE"
        rows.append({"lane_id": r["lane_id"], "verdict": v})
    _write(tmp_path / "state" / "data" / "runtime" / "research_lane_health.json",
           {"as_of": _iso(age_hours), "lanes": {"lane-registry": {"lane": "lane-registry", "as_of": _iso(age_hours),
                                                                  "declared": len(rows), "lanes": rows,
                                                                  "firing": []}}})


def test_observability_full_coverage_scores_10_and_passes(tmp_path):
    lanes = _registry(tmp_path, 10, 0)
    _monitor(tmp_path, lanes)
    r = dims_signal.observability(_probe(tmp_path))
    assert r["score"] == 10.0 and r["gate"]["pass"] and r["status"] == core.VERIFIED
    assert r["metrics"]["lanes_in_scope"] == 10 and r["metrics"]["covered"] == 10


def test_observability_partial_is_linear_and_retired_lanes_out_of_scope(tmp_path):
    lanes = _registry(tmp_path, 8, 2, extra_retired=3)
    _monitor(tmp_path, lanes, unverifiable={"s0"})
    r = dims_signal.observability(_probe(tmp_path))
    # in scope 10 ACTIVE; covered = 7 (s0 unjudged, n0/n1 no signal) → 8.0 * 0.7
    assert r["metrics"]["lanes_in_scope"] == 10 and r["metrics"]["covered"] == 7
    assert r["score"] == pytest.approx(5.6) and not r["gate"]["pass"]


def test_observability_gate_boundary_one_lane_short_fails(tmp_path):
    lanes = _registry(tmp_path, 99, 1)
    _monitor(tmp_path, lanes)
    r = dims_signal.observability(_probe(tmp_path))
    assert r["score"] == pytest.approx(7.92) and not r["gate"]["pass"]


def test_observability_stale_or_unscheduled_monitor_covers_nothing(tmp_path):
    lanes = _registry(tmp_path, 5, 0)
    _monitor(tmp_path, lanes, age_hours=3)
    assert dims_signal.observability(_probe(tmp_path))["score"] == 0.0
    _monitor(tmp_path, lanes)
    r = dims_signal.observability(_probe(tmp_path, FakeHost(exec_start="argv[]=python research_lane_health.py")))
    assert r["score"] == 0.0 and not r["gate"]["pass"]
    assert any("alert flag" in n for n in r["notes"])


def test_observability_crontab_fallback(tmp_path):
    lanes = _registry(tmp_path, 4, 0)
    _monitor(tmp_path, lanes)
    host = FakeHost(timer_active=False, crontab="*/15 * * * * python scripts/research_lane_health.py --alert\n")
    r = dims_signal.observability(_probe(tmp_path, host))
    assert r["score"] == 10.0 and r["evidence"][-1]["via"] == "crontab"
    host = FakeHost(timer_active=False, crontab="# */15 * * * * python scripts/research_lane_health.py --alert\n")
    assert dims_signal.observability(_probe(tmp_path, host))["score"] == 0.0


def test_observability_missing_evidence(tmp_path):
    r = dims_signal.observability(_probe(tmp_path))
    assert r["score"] == 0.0 and r["status"] == core.UNVERIFIED and not r["gate"]["pass"]
    _registry(tmp_path, 3, 0)
    r = dims_signal.observability(_probe(tmp_path))
    assert r["score"] == 0.0 and r["status"] == core.PARTIAL


# ── alert delivery fixtures ─────────────────────────────────────────────────

def _sends(tmp_path, ok: int, bad: int, *, extra=()):
    rows = [{"at": _iso(1 + i * 0.01), "ok": True, "identity": f"id{i}", "kind": "k", "message_id": 9}
            for i in range(ok)]
    rows += [{"at": _iso(2 + i * 0.01), "ok": False, "reason": "INTERDICTED_TEST_OR_FLAG", "identity": f"b{i}",
              "kind": "daily_heartbeat"} for i in range(bad)]
    rows += [{"at": _iso(48), "ok": True, "identity": "old"}]  # outside the window
    rows += list(extra)
    _jsonl(tmp_path / "state" / "data" / "cio" / "system_telegram_sends.jsonl", rows)


def _fanin(tmp_path, incidents, *, age_hours=0.05):
    _write(tmp_path / "state" / "data" / "runtime" / "n8n_incident_fanin_last.json",
           {"as_of": _iso(age_hours), "open": len(incidents), "incidents": incidents})


P1_DELIVERED = {"severity": "P1", "idempotency_key": "inc-ok", "delivered_at": _iso(0.1)}


def test_alert_delivery_all_green_passes(tmp_path):
    _sends(tmp_path, 100, 0)
    _fanin(tmp_path, [{"severity": "P3", "idempotency_key": "x"}, P1_DELIVERED])
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["score"] == 10.0 and r["gate"]["pass"] and r["metrics"]["p1p2_open"] == 1
    assert "message_id" not in json.dumps(r["evidence"])


def test_alert_delivery_gate_boundary_99_percent(tmp_path):
    _sends(tmp_path, 99, 1)
    _fanin(tmp_path, [P1_DELIVERED])
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["metrics"]["ok_rate_pct"] == 99.0 and r["gate"]["pass"] and r["score"] >= 8.0
    _sends(tmp_path, 98, 2)
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert not r["gate"]["pass"] and r["score"] == pytest.approx((8.0 * 0.98 / 0.99 + 10) / 2, abs=0.01)


def test_alert_delivery_interdicted_and_undelivered_p1_scores_zero(tmp_path):
    _sends(tmp_path, 0, 50)
    _fanin(tmp_path, [{"severity": "P1", "idempotency_key": "inc-1", "ops": [{"op": "accept_event",
                                                                             "state": "ARTIFACT_WRITTEN"}]},
                      {"severity": "P2", "idempotency_key": "inc-2"}])
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["score"] == 0.0 and not r["gate"]["pass"] and r["status"] == core.VERIFIED
    assert r["metrics"]["p1p2_open"] == 2 and r["metrics"]["p1p2_delivered"] == 0
    assert r["evidence"][0]["reasons"] == {"INTERDICTED_TEST_OR_FLAG": 50}


def test_alert_delivery_p1p2_delivered_by_field_or_ledger(tmp_path):
    _sends(tmp_path, 10, 0, extra=[{"at": _iso(0.5), "ok": True, "identity": "incident:inc-2"}])
    _fanin(tmp_path, [{"severity": "P1", "idempotency_key": "inc-1", "delivered_at": _iso(0.1)},
                      {"severity": "P2", "idempotency_key": "inc-2"},
                      {"severity": "P2", "idempotency_key": "inc-3"}])
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["metrics"]["p1p2_delivered"] == 2 and not r["gate"]["pass"]
    assert r["score"] == pytest.approx((10 + 8.0 * 2 / 3) / 2, abs=0.01)


def test_alert_delivery_identity_basis(tmp_path):
    rows = [{"at": _iso(3), "ok": False, "identity": "hb"}, {"at": _iso(2), "ok": True, "identity": "hb"}]
    _jsonl(tmp_path / "state" / "data" / "cio" / "system_telegram_sends.jsonl", rows)
    _fanin(tmp_path, [P1_DELIVERED])
    r = dims_signal.alert_delivery(_probe(tmp_path, dims={"alert_delivery": {"ok_rate_basis": "identity"}}))
    assert r["metrics"]["ok_rate_pct"] == 100.0 and r["gate"]["pass"]


def test_alert_delivery_missing_and_stale_evidence(tmp_path):
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["score"] == 0.0 and r["status"] == core.UNVERIFIED and not r["gate"]["pass"]
    _sends(tmp_path, 100, 0)
    _fanin(tmp_path, [], age_hours=5)
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["status"] == core.PARTIAL and r["score"] == 5.0 and not r["gate"]["pass"]


# ── reliability fixtures ────────────────────────────────────────────────────

def _ledger(tmp_path, rows):
    p = tmp_path / "state" / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT,"
                " finished_at TEXT, exit_code INTEGER)")
    for i, (state, code, hours_ago) in enumerate(rows):
        con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                    (f"r{i}", "lane", "live", state, _iso(hours_ago), _iso(hours_ago), code))
    con.commit()
    con.close()


def test_reliability_all_green_passes(tmp_path):
    _ledger(tmp_path, [("RUN_DONE", 0, 1)] * 100 + [("RUN_SKIPPED_LOCK", 1, 1), ("RUN_FAILED", 1, 30)])
    r = dims_signal.reliability(_probe(tmp_path))
    assert r["score"] == 10.0 and r["gate"]["pass"] and r["status"] == core.VERIFIED
    assert r["metrics"]["runs_success"] == 100 and r["metrics"]["runs_failure"] == 0


def test_reliability_gate_boundary_and_n8n_errors_count_as_failures(tmp_path):
    _ledger(tmp_path, [("RUN_DONE", 0, 1)] * 99 + [("RUN_FAILED", 1, 2)])
    r = dims_signal.reliability(_probe(tmp_path))
    assert r["metrics"]["run_success_pct"] == 99.0 and r["gate"]["pass"]
    r = dims_signal.reliability(_probe(tmp_path, FakeHost(n8n_errors="1")))
    assert not r["gate"]["pass"] and r["metrics"]["n8n_errors"] == 1
    assert r["metrics"]["sub_scores"]["run_success"] == pytest.approx(8.0 * (99 / 101) / 0.99, abs=0.01)


def test_reliability_kills_and_failed_units(tmp_path):
    _ledger(tmp_path, [("RUN_DONE", 0, 1)] * 10)
    journal = ("2026-10-09T06:54:58-04:00 h systemd[1]: portfolio-server.service: Main process exited, code=killed, "
               "status=9/KILL\n2026-10-09T08:55:51-04:00 h systemd[1]: portfolio-server.service: Main process "
               "exited, code=exited, status=143/n/a\n")
    failed = ("ubuntu-report.path loaded failed failed x\nmcporter-token-refresh.service loaded failed failed y\n"
              "snap.firmware-updater.firmware-notifier.service loaded failed failed z\n")
    host = FakeHost(journal=journal, failed_units=failed)
    r = dims_signal.reliability(_probe(tmp_path, host))
    assert r["metrics"]["api_sigkills"] == 1 and r["metrics"]["failed_units"] == ["mcporter-token-refresh.service"]
    assert r["score"] == pytest.approx((10 + 6.4 + 6.4) / 3, abs=0.01) and not r["gate"]["pass"]
    jc = next(a for a in host.calls if a[0] == "journalctl")
    assert jc[jc.index("--since") + 1] == "2026-10-08 20:00:00 UTC"
    psql = next(a for a in host.calls if a[:2] == ["docker", "exec"])
    assert psql[4] == "m8m-n8n-db" and core.is_read_only(psql)
    assert psql == dims_signal.n8n_error_argv("m8m-n8n-db", "n8n", "n8n", ["error", "crashed"],
                                              (NOW - dt.timedelta(hours=24)).isoformat())


def test_reliability_missing_evidence(tmp_path):
    host = FakeHost(docker_ps=None, journal_rc=1, failed_rc=1)
    r = dims_signal.reliability(_probe(tmp_path, host))
    assert r["score"] == 0.0 and r["status"] == core.UNVERIFIED and not r["gate"]["pass"]
    r = dims_signal.reliability(_probe(tmp_path, FakeHost(docker_ps=None)))  # no ledger, host green
    assert r["status"] == core.PARTIAL and not r["gate"]["pass"]
    assert r["score"] == pytest.approx(20 / 3, abs=0.01)


def test_count_score():
    assert dims_signal.count_score(0, 5, 8.0) == 10.0
    assert dims_signal.count_score(1, 5, 8.0) == pytest.approx(6.4)
    assert dims_signal.count_score(5, 5, 8.0) == 0.0 and dims_signal.count_score(9, 5, 8.0) == 0.0
    assert dims_signal.count_score(1, 5, 7.0) == pytest.approx(5.6)


def test_collectors_registered():
    assert set(dims_signal.COLLECTORS) == {"observability", "alert_delivery", "reliability"}


def test_rate_score_gate_boundaries():
    rs = dims_signal.rate_score
    assert rs(1.0, 1.0, 8.0) == 10.0
    assert rs(0.99, 1.0, 8.0) == pytest.approx(7.92)
    assert rs(0.99, 0.99, 8.0) == pytest.approx(8.0)
    assert rs(0.995, 0.99, 8.0) == pytest.approx(9.0)
    assert rs(1.0, 0.99, 8.0) == 10.0
    assert rs(None, 0.99, 8.0) == 0.0
    assert rs(0.99, 0.99, 7.5) == pytest.approx(7.5)


# ── review blockers: read-only argv, config-only thresholds, empty inputs never pass ──────────

def _green_fixtures(tmp_path):
    lanes = _registry(tmp_path, 4, 0)
    _monitor(tmp_path, lanes)
    _sends(tmp_path, 10, 0)
    _fanin(tmp_path, [P1_DELIVERED])
    _ledger(tmp_path, [("RUN_DONE", 0, 1)] * 10)


def test_every_argv_issued_is_read_only(tmp_path):
    _green_fixtures(tmp_path)
    host = FakeHost(crontab="*/15 * * * * python scripts/research_lane_health.py --alert\n", timer_active=False)
    p = _probe(tmp_path, host)
    for fn in dims_signal.COLLECTORS.values():
        fn(p)
    assert any(a[:2] == ["docker", "exec"] for a in host.calls)
    assert any(a[0] == "journalctl" for a in host.calls)
    assert host.calls and all(core.is_read_only(a) for a in host.calls), \
        [a for a in host.calls if not core.is_read_only(a)]


def test_psql_argv_uses_core_shape_and_safe_sql():
    argv = dims_signal.n8n_error_argv("m8m-n8n-db", "n8n", "n8n", ["error", "crash'ed; DROP"], NOW.isoformat())
    assert argv[:5] == ["docker", "exec", "-e", f"PGOPTIONS={core.PG_READ_ONLY_OPTIONS}", "m8m-n8n-db"]
    assert core.is_read_only(argv) and core.is_safe_sql(argv[-1])


def test_undiscoverable_container_name_is_refused_not_run(tmp_path):
    _ledger(tmp_path, [("RUN_DONE", 0, 1)] * 10)
    host = FakeHost(docker_ps="evil;name-n8n postgres:16\n")
    r = dims_signal.reliability(_probe(tmp_path, host))
    assert r["metrics"]["n8n_errors"] is None
    assert not any(a[:2] == ["docker", "exec"] for a in host.calls)


@pytest.mark.parametrize("dim,key", [("observability", "monitor_max_age_hours"), ("observability", "gate_coverage"),
                                     ("alert_delivery", "gate_ok_rate"), ("alert_delivery", "fanin_max_age_hours"),
                                     ("reliability", "gate_success_rate"), ("reliability", "count_zero_at"),
                                     ("reliability", "n8n_db_user")])
def test_missing_threshold_raises_config_error(tmp_path, dim, key):
    _green_fixtures(tmp_path)
    cfg = _config()
    del cfg["dimensions"][dim][key]
    with pytest.raises(core.ConfigError):
        dims_signal.COLLECTORS[dim](_probe(tmp_path, config=cfg))


def test_missing_gate_score_raises_config_error(tmp_path):
    _green_fixtures(tmp_path)
    cfg = _config()
    del cfg["gate_score"]
    for fn in dims_signal.COLLECTORS.values():
        with pytest.raises(core.ConfigError):
            fn(_probe(tmp_path, config=cfg))


def test_real_config_carries_every_key_the_collectors_read(tmp_path):
    _green_fixtures(tmp_path)
    for dim in SIGNAL_DIMS:
        assert dims_signal.COLLECTORS[dim](_probe(tmp_path, config=copy.deepcopy(REAL_CONFIG)))["id"] == dim


def test_gate_score_comes_from_config(tmp_path):
    lanes = _registry(tmp_path, 8, 2)
    _monitor(tmp_path, lanes)
    r = dims_signal.observability(_probe(tmp_path, config=_config(gate_score=7.0)))
    assert r["score"] == pytest.approx(7.0 * 0.8)


def test_window_hours_from_config(tmp_path):
    _sends(tmp_path, 0, 0)  # only the 48 h-old ok row
    _fanin(tmp_path, [P1_DELIVERED])
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["metrics"]["send_rows"] == 0 and r["metrics"]["window_hours"] == 24
    r = dims_signal.alert_delivery(_probe(tmp_path, dims={"alert_delivery": {"window_hours": 72}}))
    assert r["metrics"]["send_rows"] == 1 and r["metrics"]["window_hours"] == 72
    r = dims_signal.alert_delivery(_probe(tmp_path, config=_config(window_hours=72)))
    assert r["metrics"]["window_hours"] == 72


def test_observability_no_lanes_in_scope_is_unverified(tmp_path):
    _write(tmp_path / "proj" / "config" / "lane_registry.json",
           {"lanes": [{"lane_id": "r", "state": "RETIRED", "output_signal": {"kind": "file_mtime"}}]})
    r = dims_signal.observability(_probe(tmp_path))
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0 and not r["gate"]["pass"]


def test_observability_one_stale_or_future_monitor_receipt_is_not_alive(tmp_path):
    lanes = _registry(tmp_path, 5, 0)
    _monitor(tmp_path, lanes, age_hours=1.01)  # just past monitor_max_age_hours (1.0)
    r = dims_signal.observability(_probe(tmp_path))
    assert r["metrics"]["monitor_alive"] is False and r["score"] == 0.0 and not r["gate"]["pass"]
    _monitor(tmp_path, lanes, age_hours=-2)  # dated in the future: not proof of a live monitor
    r = dims_signal.observability(_probe(tmp_path))
    assert r["metrics"]["monitor_alive"] is False and r["score"] == 0.0


def test_alert_delivery_no_open_p1p2_is_unproven_not_100(tmp_path):
    _sends(tmp_path, 100, 0)
    _fanin(tmp_path, [{"severity": "P3", "idempotency_key": "x"}])
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["status"] == core.PARTIAL and r["score"] == 5.0 and not r["gate"]["pass"]
    assert any("no open P1/P2" in n for n in r["notes"])


def test_alert_delivery_stale_fanin_receipt_does_not_count_as_delivered(tmp_path):
    _sends(tmp_path, 100, 0)
    _fanin(tmp_path, [P1_DELIVERED], age_hours=1.5)
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["status"] == core.PARTIAL and r["score"] == 5.0 and not r["gate"]["pass"]
    _fanin(tmp_path, [P1_DELIVERED], age_hours=-3)  # future-dated
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["score"] == 5.0 and not r["gate"]["pass"]


def test_alert_delivery_empty_ledger_window_is_unproven(tmp_path):
    _jsonl(tmp_path / "state" / "data" / "cio" / "system_telegram_sends.jsonl", [])
    _fanin(tmp_path, [P1_DELIVERED])
    r = dims_signal.alert_delivery(_probe(tmp_path))
    assert r["metrics"]["ok_rate_pct"] is None and r["status"] == core.PARTIAL and not r["gate"]["pass"]


def test_reliability_no_runs_in_window_is_unproven(tmp_path):
    _ledger(tmp_path, [("RUN_DONE", 0, 30)])  # outside the 24 h window
    r = dims_signal.reliability(_probe(tmp_path))
    assert r["metrics"]["run_success_pct"] is None and r["metrics"]["sub_scores"]["run_success"] is None
    assert r["status"] == core.PARTIAL and not r["gate"]["pass"]


def test_deterministic(tmp_path):
    _green_fixtures(tmp_path)
    a = [fn(_probe(tmp_path)) for fn in dims_signal.COLLECTORS.values()]
    b = [fn(_probe(tmp_path)) for fn in dims_signal.COLLECTORS.values()]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
