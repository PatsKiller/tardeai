"""Failure evidence must survive the scheduler → receipt → output projection."""

from datetime import datetime, timezone
from pathlib import Path

from scripts.lib.scheduler_operations import build_projection, parse_crontab, read_run_ledger

NOW = datetime(2026, 10, 8, 22, tzinfo=timezone.utc)


def lane(kind="cron", state="ACTIVE", signal=None):
    return {
        "lane_id": "test-lane",
        "owner": "platform",
        "state": state,
        "scheduler": {
            "kind": kind,
            "expression": "*/5 * * * *" if kind == "cron" else "wf-1",
            "match": "scripts/test_lane.py",
        },
        "expected_cadence_hours": 5 / 60,
        "output_signal": signal or {"kind": "file_mtime", "path": "data/result.json"},
        "consumer": "ops",
    }


def observations(cron_text=None, workflows=None):
    return {
        "cron": {
            "measured": cron_text is not None,
            "as_of": NOW.isoformat(),
            "entries": parse_crontab(cron_text or ""),
        },
        "systemd": {"measured": False, "units": {}},
        "n8n": {"measured": workflows is not None, "workflows": workflows or []},
        "openclaw": {"measured": False, "jobs": []},
    }


def project(tmp_path, rows, obs, runs=None):
    return build_projection(
        {"lanes": rows}, obs, root=tmp_path, now=NOW, runs=runs or [], runs_measured=runs is not None
    )


def test_denied_cron_is_not_an_empty_success(tmp_path):
    row = project(tmp_path, [lane()], observations())["rows"][0]
    assert row["runtime_state"] == "NOT_MEASURED"
    assert row["scheduler_drift"] is None
    assert row["failures_24h"] is None


def test_successful_scheduler_cannot_hide_stale_output(tmp_path):
    run = {
        "lane_id": "test-lane",
        "run_id": "r-1",
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "requested_at": NOW.isoformat(),
        "started_at": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
        "duration_s": 1,
    }
    row = project(tmp_path, [lane()], observations("*/5 * * * * python scripts/test_lane.py"), [run])["rows"][0]
    assert row["runtime_state"] == "SILENT"
    assert row["last_exit"] == 0


def test_latest_failure_beats_older_success(tmp_path):
    runs = [
        {
            "lane_id": "test-lane",
            "mode": "live",
            "state": "RUN_DONE",
            "finished_at": "2026-10-08T21:59:00Z",
            "exit_code": 0,
        },
        {"lane_id": "test-lane", "mode": "live", "state": "RUN_FAILED", "finished_at": NOW.isoformat(), "exit_code": 1},
    ]
    row = project(tmp_path, [lane()], observations("*/5 * * * * python scripts/test_lane.py"), runs)["rows"][0]
    assert row["runtime_state"] == "RUN_FAILED"
    assert row["failures_24h"] == 1


def test_shadow_success_does_not_prove_business_execution(tmp_path):
    runs = [
        {"lane_id": "test-lane", "mode": "dry_run", "state": "RUN_DONE", "finished_at": NOW.isoformat(), "exit_code": 0}
    ]
    row = project(tmp_path, [lane()], observations("*/5 * * * * python scripts/test_lane.py"), runs)["rows"][0]
    assert row["last_completed"] is None
    assert row["completion_ratio"] is None
    assert row["timeline"][0]["mode"] == "dry_run"


def test_disabled_n8n_workflow_is_orphaned(tmp_path):
    row = project(tmp_path, [lane("n8n")], observations("", [{"id": "wf-1", "active": False}]))["rows"][0]
    assert row["runtime_state"] == "ORPHANED"
    assert row["scheduler_drift"] is True


def test_lock_skip_is_not_completion(tmp_path):
    run = {
        "lane_id": "test-lane",
        "mode": "live",
        "state": "RUN_SKIPPED_LOCK",
        "finished_at": NOW.isoformat(),
        "exit_code": 0,
    }
    row = project(tmp_path, [lane()], observations("*/5 * * * * python scripts/test_lane.py"), [run])["rows"][0]
    assert row["runtime_state"] == "RUN_SKIPPED_LOCK"
    assert row["lock_skips_24h"] == 1
    assert row["completed_fires_24h"] == 0


def test_same_command_twice_is_duplicate_even_if_locked(tmp_path):
    text = "*/5 * * * * flock -n /tmp/test.lock python scripts/test_lane.py\n*/10 * * * * flock -n /tmp/test.lock python scripts/test_lane.py"
    row = project(tmp_path, [lane()], observations(text))["rows"][0]
    assert row["duplicate_scheduler"] is True
    assert row["runtime_state"] == "DRIFT"


def test_unregistered_entry_is_visible(tmp_path):
    rows = project(tmp_path, [], observations("*/5 * * * * python scripts/unknown.py"))["rows"]
    assert len(rows) == 1
    assert rows[0]["declared_state"] == "UNDECLARED"
    assert rows[0]["runtime_state"] == "ORPHANED"
    assert rows[0]["owner"] is None


def test_separately_declared_noncolliding_windows_are_benign(tmp_path):
    first = lane()
    first["scheduler"]["expression"] = "5 12 * * MON-FRI"
    second = lane()
    second["lane_id"] = "close"
    second["scheduler"]["expression"] = "10 16 * * MON-FRI"
    obs = observations(
        "5 12 * * MON-FRI flock -n /tmp/test.lock python scripts/test_lane.py\n10 16 * * MON-FRI flock -n /tmp/test.lock python scripts/test_lane.py"
    )
    rows = project(tmp_path, [first, second], obs)["rows"]
    assert all(r["duplicate_scheduler"] is False for r in rows)


def test_no_signal_has_reason_and_never_proven_health(tmp_path):
    row = project(
        tmp_path,
        [lane(signal={"kind": "none", "reason": "no host artifact"})],
        observations("*/5 * * * * python scripts/test_lane.py"),
    )["rows"][0]
    assert row["runtime_state"] == "NO_SIGNAL"
    assert row["health_reason"] == "no host artifact"


def test_cron_timezone_environment_and_reboot_are_preserved():
    rows = parse_crontab(
        "CRON_TZ=UTC\nPATH=/bin\n# */2 * * * * ignored\n@reboot daemon\n*/5 9-16 * * MON-FRI python x.py\nCRON_TZ=America/New_York\n0 9 * * * python y.py"
    )
    assert len(rows) == 3
    assert rows[0]["expression"] == "@reboot"
    assert rows[1]["timezone"] == "UTC"
    assert rows[2]["timezone"] == "America/New_York"


def test_missing_ledger_does_not_create_database(tmp_path):
    path = tmp_path / "absent.sqlite"
    rows, measured, reason = read_run_ledger(path)
    assert rows == [] and not measured
    assert not path.exists()


def test_terminal_run_without_receipt_does_not_prove_done(tmp_path):
    run = {
        "lane_id": "test-lane",
        "mode": "live",
        "state": "RUN_DONE",
        "finished_at": NOW.isoformat(),
        "exit_code": 0,
        "receipt": None,
    }
    row = project(tmp_path, [lane()], observations("*/5 * * * * python scripts/test_lane.py"), [run])["rows"][0]
    assert row["completed_fires_24h"] == 0


def test_paused_lane_running_is_drift(tmp_path):
    row = project(tmp_path, [lane(state="PAUSED")], observations("*/5 * * * * python scripts/test_lane.py"))["rows"][0]
    assert row["runtime_state"] == "DRIFT"


def test_runtime_code_root_is_not_guessed_from_api_root(tmp_path):
    dev = tmp_path / "dev"
    row = project(tmp_path, [lane()], observations(f"*/5 * * * * cd {dev} && python scripts/test_lane.py"))["rows"][0]
    assert row["code_sha"] is None
    assert row["code_root"] == str(dev)
    assert row["code_root_evidence"] == "OBSERVED_HOST"


def test_expired_snapshot_cannot_prove_live_scheduler(tmp_path):
    obs = observations("*/5 * * * * python scripts/test_lane.py")
    obs["cron"]["as_of"] = "2026-10-07T22:00:00Z"
    row = project(tmp_path, [lane()], obs)["rows"][0]
    assert row["runtime_state"] == "NOT_MEASURED"
    assert row["scheduler_drift"] is None


def test_unregistered_n8n_workflow_is_visible(tmp_path):
    rows = project(tmp_path, [], observations("", [{"id": "wf-new", "name": "unknown job", "active": True}]))["rows"]
    assert rows[0]["scheduler_type"] == "n8n"
    assert rows[0]["runtime_state"] == "ORPHANED"
    assert rows[0]["owner"] is None


def test_n8n_metadata_reader_uses_read_only_transaction(monkeypatch):
    from scripts.lib import scheduler_operations as ops

    calls = []

    def read(argv):
        calls.append(argv)
        return {"measured": True, "stdout": 'BEGIN\nSET\n[{"id":"wf-1","active":false}]\nCOMMIT\n'}

    monkeypatch.setattr(ops, "_read_command", read)
    result = ops.collect_n8n()
    assert result["workflows"][0]["active"] is False
    query = calls[0][-1]
    assert "BEGIN READ ONLY" in query
    assert "credentials_entity" not in query
    assert "execution_data" not in query


def test_failed_metadata_query_remains_unknown(monkeypatch):
    from scripts.lib import scheduler_operations as ops

    monkeypatch.setattr(ops, "_read_command", lambda argv: {"measured": False, "stdout": "", "reason": "exit:1"})
    result = ops.collect_n8n()
    assert not result["measured"]
    assert result["reason"] == "exit:1"


def test_command_redaction_hides_inline_secret():
    from scripts.lib.scheduler_operations import redact_command

    raw = "TOKEN=sample-private-value run --password another-private-value https://user:private@host/path"
    safe = redact_command(raw)
    assert "sample-private-value" not in safe
    assert "another-private-value" not in safe
    assert "user:private" not in safe


def test_failed_service_behind_active_timer_is_not_healthy(tmp_path):
    l = lane("systemd")
    l["scheduler"]["expression"] = "test.timer"
    obs = observations("")
    obs["systemd"] = {
        "measured": True,
        "units": {
            "test.timer": {"ActiveState": "active", "LoadState": "loaded"},
            "test.service": {"ActiveState": "failed", "LoadState": "loaded", "WorkingDirectory": "/CURRENT"},
        },
    }
    assert project(tmp_path, [l], obs)["rows"][0]["runtime_state"] == "RUN_FAILED"


def test_running_unit_with_missing_definition_is_drift(tmp_path):
    l = lane("systemd")
    l["scheduler"]["expression"] = "test.service"
    obs = observations("")
    obs["systemd"] = {"measured": True, "units": {"test.service": {"ActiveState": "active", "LoadState": "not-found"}}}
    assert project(tmp_path, [l], obs)["rows"][0]["runtime_state"] == "DRIFT"


def test_cron_inventory_keeps_reboot_and_estimates_weekdays_without_completions():
    from scripts.report_scheduler_inventory import cron_analysis

    result = cron_analysis("*/5 * * * * job\n@reboot daemon\n0 9 * * MON-FRI work", start=NOW)
    assert result["counts"]["job_lines"] == 3
    assert result["estimated_fires_7d"] == 7 * 288 + 5
    assert result["jobs"][1]["estimated_fires_7d"] == 0
    assert result["estimate_class"] == "SOURCE_ONLY"


def test_legacy_monitors_declare_no_signal_reason():
    import json

    registry = json.loads((Path(__file__).resolve().parents[1] / "config/lane_registry.json").read_text())
    rows = [r for r in registry["lanes"] if r["lane_id"] in ("n8n-monitor-trade-ai", "n8n-monitor-dof")]
    assert len(rows) == 2
    assert all(
        r["output_signal"]["kind"] == "none" and "NO_SIGNAL_WITH_REASON" in r["output_signal"]["reason"] for r in rows
    )


def test_receipt_and_fresh_output_prove_live_run(tmp_path):
    import os

    out = tmp_path / "data/result.json"
    out.parent.mkdir()
    out.write_text('{"ok":true}')
    os.utime(out, (NOW.timestamp(), NOW.timestamp()))
    run = {
        "lane_id": "test-lane",
        "run_id": "run-1",
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "requested_at": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
        "receipt": {
            "schema": "RunReceipt@v1",
            "lane_id": "test-lane",
            "finished_at": NOW.isoformat(),
            "run_id": "run-1",
            "state": "RUN_DONE",
            "mode": "live",
            "exit_code": 0,
            "code_sha": "b" * 40,
        },
    }
    row = project(tmp_path, [lane()], observations("*/5 * * * * python scripts/test_lane.py"), [run])["rows"][0]
    assert row["runtime_state"] == "LIVE"
    assert row["code_sha"] == "b" * 40
    assert row["completion_ratio"] is None
    assert row["observed_completion_ratio"] == 1


def test_metadata_failure_cannot_create_workflow_success(monkeypatch):
    from scripts.lib import scheduler_operations as ops

    monkeypatch.setattr(ops, "_read_command", lambda argv: {"measured": True, "stdout": "bad-json"})
    assert ops.collect_n8n()["measured"] is False


def _api_route(monkeypatch, method="GET", projection=None, query=None):
    from scripts.lib import scheduler_operations as ops

    source = (Path(__file__).resolve().parents[1] / "scripts/api_v2.py").read_text()
    start = source.index('    if base_path == "/api/v2/scheduler-operations":')
    end = source.index("    # n8n coordination ledger projection", start)

    def load(**kwargs):
        if isinstance(projection, Exception):
            raise projection
        return projection

    monkeypatch.setattr(ops, "load_projection", load)
    scope = {"base_path": "/api/v2/scheduler-operations", "method": method, "query": query, "_db_query": lambda sql: None}
    exec("def route():\n" + source[start:end], scope)
    return scope["route"]()


def test_api_projection_is_additive_and_post_refused(monkeypatch):
    fixture = {"schema": "SchedulerOperations@v1", "rows": []}
    assert _api_route(monkeypatch, projection=fixture) == (200, {"ok": True, "data": fixture})
    assert _api_route(monkeypatch, method="POST", projection=RuntimeError("should not execute")) == (
        405,
        {"ok": False, "error": "read_only"},
    )


def test_api_slices_for_jobs_page(monkeypatch):
    fixture = {"schema": "SchedulerOperations@v1", "rows": [
        {"lane_id": "x", "runtime_state": "DRIFT", "timeline": [{"run_id": "1"}]},
        {"lane_id": "y", "runtime_state": "LIVE", "timeline": []}]}
    status, body = _api_route(monkeypatch, projection=fixture, query={"view": "checks"})
    assert status == 200 and body["data"]["schema"] == "SchedulerChecks@v1"
    assert [r["lane_id"] for r in body["data"]["rows"]] == ["x"] and "timeline" not in body["data"]["rows"][0]
    status, body = _api_route(monkeypatch, projection=fixture, query={"lane": "x"})
    assert status == 200 and body["data"]["row"]["timeline"] == [{"run_id": "1"}]


def test_api_failure_never_echoes_sensitive_exception_text(monkeypatch):
    status, body = _api_route(monkeypatch, projection=RuntimeError("private-value"))
    assert status == 503 and body["error"] == "RuntimeError"
    assert "private-value" not in str(body)


def test_retired_system_scope_service_running_is_drift(tmp_path):
    l = lane("systemd", "RETIRED", {"kind": "none", "reason": "retired runtime"})
    l["scheduler"] = {"kind": "systemd", "scope": "system", "expression": "ollama.service"}
    obs = observations("")
    obs["systemd"] = {
        "measured": True,
        "units": {"system:ollama.service": {"Id": "ollama.service", "LoadState": "loaded", "ActiveState": "active"}},
    }
    assert project(tmp_path, [l], obs)["rows"][0]["runtime_state"] == "DRIFT"


def test_partial_lock_telemetry_does_not_invent_24h_zeros_or_run_proof(tmp_path):
    obs = observations("*/5 * * * * python scripts/test_lane.py")
    obs["lock_telemetry"] = {
        "measured": True,
        "complete_window": False,
        "groups": {
            "test": {
                "commands": ["python scripts/test_lane.py"],
                "started": 2,
                "completed": 2,
                "skips": 1,
                "failures": 0,
                "durations": [1, 2],
                "ambiguous": 0,
            }
        },
    }
    row = project(tmp_path, [lane()], obs)["rows"][0]
    assert row["lock_skips_24h"] is None and row["failures_24h"] is None
    assert row["p95_runtime_s"] == 2
    assert row["slo_verdict"] == "LOCK_SKIP_GT_5_PERCENT"
    assert not row["run_proven"]


def test_lock_event_reader_does_not_echo_command_secrets(tmp_path):
    import json
    from scripts.lib.scheduler_operations import read_lock_metrics

    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(
            {"ts": NOW.isoformat(), "component": "x", "command": "TOKEN=private-value run", "event_type": "started"}
        )
        + "\n"
    )
    result = read_lock_metrics(path, NOW)
    assert "private-value" not in str(result)
    assert not result["complete_window"]


def test_one_missing_unit_cannot_hide_remaining_installed_units(tmp_path, monkeypatch):
    from scripts.lib import scheduler_operations as ops

    def read(argv):
        if "list-unit-files" in argv:
            return {
                "measured": True,
                "stdout": "tradeai-first.service enabled\ntradeai-second.service enabled\n",
                "as_of": NOW.isoformat(),
            }
        if "show" in argv and "tradeai-first.service" in argv:
            return {
                "measured": False,
                "stdout": "Id=tradeai-first.service\nLoadState=not-found\nActiveState=active\n",
                "reason": "exit:1",
            }
        if "show" in argv and "tradeai-second.service" in argv:
            return {"measured": True, "stdout": "Id=tradeai-second.service\nLoadState=loaded\nActiveState=active\n"}
        return {"measured": False, "stdout": "", "reason": "unavailable"}

    monkeypatch.setattr(ops, "_read_command", read)
    result = ops.collect_host(openclaw_path=tmp_path / "absent.json")
    assert set(result["systemd"]["units"]) == {"tradeai-first.service", "tradeai-second.service"}
    assert result["systemd"]["coverage"] == "COMPLETE"


def test_mismatched_or_future_receipt_never_proves_live(tmp_path):
    import os

    out = tmp_path / "data/result.json"
    out.parent.mkdir()
    out.write_text("{}")
    os.utime(out, (NOW.timestamp(), NOW.timestamp()))
    base = {
        "lane_id": "test-lane",
        "run_id": "run-1",
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "requested_at": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
    }
    for bad in (
        {"lane_id": "other"},
        {"run_id": "other"},
        {"mode": "dry_run"},
        {"schema": "Unknown"},
        {"exit_code": 1},
        {"finished_at": "2027-01-01T00:00:00Z"},
        {"finished_at": "2026-10-01T22:00:00Z"},
        {"lock_skipped": True},
        {"timed_out": True},
    ):
        receipt = {
            "schema": "RunReceipt@v1",
            "lane_id": "test-lane",
            "run_id": "run-1",
            "mode": "live",
            "state": "RUN_DONE",
            "exit_code": 0,
            "finished_at": NOW.isoformat(),
        }
        row = project(
            tmp_path,
            [lane()],
            observations("*/5 * * * * python scripts/test_lane.py"),
            [{**base, "receipt": {**receipt, **bad}}],
        )["rows"][0]
        assert row["runtime_state"] != "LIVE", bad
        assert row["completed_fires_24h"] == 0, bad


def test_database_signal_keeps_database_evidence_class(tmp_path):
    row = project(
        tmp_path,
        [lane(signal={"kind": "db_max", "table": "runtime_receipts", "column": "finished_at"})],
        observations("*/5 * * * * python scripts/test_lane.py"),
    )["rows"][0]
    # Supply a read-only query adapter only for the projection, never run the lane.
    result = build_projection(
        {"lanes": [lane(signal={"kind": "db_max", "table": "runtime_receipts", "column": "finished_at"})]},
        observations("*/5 * * * * python scripts/test_lane.py"),
        root=tmp_path,
        now=NOW,
        db_query=lambda q: [(NOW,)],
    )
    assert result["rows"][0]["output_evidence_class"] == "OBSERVED_DB"
    assert row["output_evidence_class"] == "NOT_MEASURED"


def test_fresh_shared_output_cannot_mask_an_old_run_receipt(tmp_path):
    import os

    out = tmp_path / "data/result.json"
    out.parent.mkdir()
    out.write_text("{}")
    os.utime(out, (NOW.timestamp(), NOW.timestamp()))
    old = "2026-10-01T22:00:00Z"
    receipt = {
        "schema": "RunReceipt@v1",
        "run_id": "old",
        "lane_id": "test-lane",
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "finished_at": old,
    }
    run = {
        "run_id": "old",
        "lane_id": "test-lane",
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "requested_at": old,
        "finished_at": old,
        "receipt": receipt,
    }
    row = project(tmp_path, [lane()], observations("*/5 * * * * python scripts/test_lane.py"), [run])["rows"][0]
    assert row["runtime_state"] != "LIVE"
    assert row["run_freshness"] == "STALE"


def test_n8n_and_openclaw_schedule_objects_render_as_operator_expressions(tmp_path):
    obs = observations(
        "",
        [
            {
                "id": "wf-new",
                "active": True,
                "schedules": [{"interval": [{"field": "cronExpression", "expression": "*/5 * * * *"}]}],
            }
        ],
    )
    obs["openclaw"] = {
        "measured": True,
        "jobs": [
            {
                "id": "job-new",
                "enabled": True,
                "schedule": {"kind": "cron", "expr": "0 9 * * 1-5", "tz": "America/New_York"},
            }
        ],
    }
    rows = project(tmp_path, [], obs)["rows"]
    assert next(r for r in rows if r["scheduler_type"] == "n8n")["schedule"] == "*/5 * * * *"
    assert next(r for r in rows if r["scheduler_type"] == "openclaw")["schedule"] == "0 9 * * 1-5 (America/New_York)"


def test_inventory_current_directory_is_not_proof_of_child_execution_pin(tmp_path):
    from scripts.report_scheduler_inventory import normalize

    current = tmp_path / "CURRENT"
    result = project(tmp_path, [lane()], observations(f"*/5 * * * * cd {current} && python scripts/test_lane.py"))
    row = normalize(result, {"lanes": [lane()]}, {"lanes": []}, {"units": []})[0]
    assert row["current_pinned"] is None
    assert row["declared_current_root"] is True


def test_own_declared_multi_window_cadence_is_not_a_duplicate(tmp_path):
    """Several windows joined by " + " are one lane's cadence; 19 healthy lanes read DRIFT on 2026-11-07."""
    multi = lane()
    multi["scheduler"]["expression"] = "45 20 * * 1-5 + 45 2 * * *"
    text = (
        "45 20 * * 1-5 flock -n /tmp/test.lock python scripts/test_lane.py\n"
        "45 2 * * * flock -n /tmp/test.lock python scripts/test_lane.py"
    )
    row = project(tmp_path, [multi], observations(text))["rows"][0]
    assert row["duplicate_scheduler"] is False
    assert "duplicate_reason" not in row
    assert row["runtime_state"] != "DRIFT"


def test_host_line_at_an_undeclared_window_is_a_duplicate(tmp_path):
    single = lane()
    single["scheduler"]["expression"] = "45 20 * * 1-5"
    text = (
        "45 20 * * 1-5 flock -n /tmp/test.lock python scripts/test_lane.py\n"
        "45 2 * * * flock -n /tmp/test.lock python scripts/test_lane.py"
    )
    row = project(tmp_path, [single], observations(text))["rows"][0]
    assert row["duplicate_scheduler"] is True
    assert "45 2 * * *" in row["duplicate_reason"]
    assert row["runtime_state"] == "DRIFT"


def test_host_requested_run_does_not_make_a_cron_lane_n8n_scheduled(tmp_path):
    """The coordination ledger also records host callers and dry runs; only live n8n work is double scheduling."""
    base = {
        "lane_id": "test-lane",
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "requested_at": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
    }
    text = "*/5 * * * * python scripts/test_lane.py"

    host_run = dict(base, requested_by="host:cc-wave-c")
    row = project(tmp_path, [lane()], observations(text), [host_run])["rows"][0]
    assert row["duplicate_scheduler"] is False

    shadow = dict(base, requested_by="n8n:workflow:tradeai-dispatcher", mode="dry_run")
    row = project(tmp_path, [lane()], observations(text), [shadow])["rows"][0]
    assert row["duplicate_scheduler"] is False

    n8n_run = dict(base, requested_by="n8n:workflow:tradeai-dispatcher")
    row = project(tmp_path, [lane()], observations(text), [n8n_run])["rows"][0]
    assert row["duplicate_scheduler"] is True
    assert "n8n" in row["duplicate_reason"]


def test_an_orphaned_cron_lane_fired_by_n8n_is_moved_not_doubled(tmp_path):
    """No crontab line now + n8n runs = the lane moved; calling it 'scheduled twice' hides the registry fix."""
    run = {
        "lane_id": "test-lane",
        "mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
        "requested_at": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
        "requested_by": "n8n:workflow:tradeai-dispatcher",
    }
    row = project(tmp_path, [lane()], observations("*/5 * * * * python scripts/other.py"), [run])["rows"][0]
    assert row["duplicate_scheduler"] is False
    assert row["runtime_state"] == "ORPHANED"


def test_inactive_lane_on_the_shared_dispatcher_is_not_reported_running(tmp_path):
    """The dispatcher's own active flag is not this lane's registration: agent_nudge read DRIFT while PAUSED."""
    paused = lane(kind="n8n", state="PAUSED")
    paused["scheduler"].update({"expression": "dispatcher", "match": ""})
    obs = observations("", [{"id": "tradeai-dispatcher", "active": True, "schedules": []}])
    rows = project(tmp_path, [paused], obs)["rows"]
    row = next(r for r in rows if r["lane_id"] == "test-lane")
    assert row["runtime_state"] == "EXPECTED_SILENT"
    assert "shared n8n dispatcher" in row["health_reason"]
    assert not any(r["lane_id"] == "unregistered-n8n-tradeai-dispatcher" for r in rows)


def test_event_lane_claims_the_openclaw_job_it_names(tmp_path):
    """An event row naming its OpenClaw job owns that job; four reminder lanes stood beside an 'unowned' copy."""
    event = lane(kind="event")
    event["scheduler"].update({"expression": "openclaw-cron:job-1", "match": "job-1"})
    obs = observations("")
    obs["openclaw"] = {
        "measured": True,
        "jobs": [
            {"id": "job-1", "enabled": True, "schedule": {"kind": "cron", "expr": "0 15 * * 1-5", "tz": "America/New_York"}}
        ],
    }
    rows = project(tmp_path, [event], obs)["rows"]
    assert [r["lane_id"] for r in rows] == ["test-lane"]
    row = rows[0]
    assert row["schedule"] == "0 15 * * 1-5 (America/New_York)"
    assert row["scheduler_observations"] == [
        {"id": "job-1", "kind": "openclaw", "enabled": True, "schedule": {"kind": "cron", "expr": "0 15 * * 1-5", "tz": "America/New_York"}}
    ]

    obs["openclaw"]["jobs"][0]["enabled"] = False
    row = project(tmp_path, [event], obs)["rows"][0]
    assert row["runtime_state"] == "ORPHANED"
