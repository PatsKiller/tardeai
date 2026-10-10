"""R1 shadow-on-cron row shape and the `dispatcher` / `tradeai-dispatcher` naming (2026-10-10, Agent F).

COVERS = ["scripts/lib/lane_dispatch.py", "scripts/lib/lane_stage_clamp.py", "scripts/pipelines/cutover/_cutover.py"]

The failure this guards against (Agent A finding, 2026-10-10): AGENTS.md §23.11's dispatcher row (`scheduler.kind
"n8n"`, `scheduler.expression "dispatcher"`) cannot exist while the lane's cron line is live — it fails
CRON_PRESENT_WHILE_SCHEDULER_N8N and the inactive-n8n-row check — so the §23.12 shadow step is a cron row with a
`dispatch` block in mode dry_run and `scheduler.stage "shadow"` (wave 1, n8nmat/dispatch-shadow-wave1). 4.3.0
§23.18 (c) admits the R1 classes (ingest / llm / learn) only on an expression-"dispatcher" row, so no R1 lane could
shadow. `lane_dispatch.r1_class_admission` now also accepts that cron shadow shape, but:

* only once the amendment that rewrites §23.18 (c) is ratified (`R1_SHADOW_SHAPE_STATUS`, flipped only by the
  ratifying edit and pinned to the AGENTS.md version row here);
* only at stage shadow, only dispatch.mode dry_run, and only with a null allowlist `live_arg` (no live argv exists);
* every other R1 condition still applies (dispatch_eligible / forbidden tokens, no daemon, dry_run_arg,
  LaneRunReceipt@v1, no broker credential, the governed bridge for llm), and broker / order / stop / positions /
  secret / daemon lanes stay refused under every class;
* canary and cutover are unchanged: they still need the dispatcher row.

Naming: `dispatcher` is the row expression (code, §23.11, the 4.1.0 and 4.3.0 tests); `tradeai-dispatcher` is the
dispatcher's n8n workflow id (workflows/INDEX.json). Design 02 §12.2 wrote the workflow id as the expression. A row
carrying it is refused by the gate, reported by the registry check, clamped to dry_run by the executor, and refused
as `_cutover.py --workflow-id`; `--workflow-id dispatcher` now leaves the row at stage cutover.

Hermetic: synthetic rows and allowlist entries; the repo's config files are only read. No socket, no crontab, no DB.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_stage_clamp as SC  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402
from tests import test_n8n_lane_cutover_20261008 as CT  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
REGISTRY_DOC = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
WORKFLOW_INDEX = json.loads(
    (ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "INDEX.json").read_text(encoding="utf-8")
)
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")
RECEIPT = "data/runtime/r1-shadow-lane_last.json"
BRIDGE = {"via": "cio-governed-bridge", "process_id": "multi_tier_trade_reviewer"}
PROCS = {"multi_tier_trade_reviewer"}
GOOD_CMD = {
    "ingest": ["$PY", "scripts/market_regime_classifier.py"],
    "learn": ["$PY", "scripts/agent_calibration_engine.py"],
    "llm": ["$PY", "scripts/multi_tier_trade_reviewer.py", "--tier", "overnight"],
}
RETRY = {"ingest": "none", "learn": "none", "llm": "llm-transient"}


def _cron_shadow(
    klass: str,
    command: list[str] | None = None,
    *,
    lane: str = "r1-shadow-lane",
    live=None,
    dry=("--dry-run",),
    env=(),
    stage: str = "shadow",
    mode: str = "dry_run",
):
    """A wave-1-shaped shadow row (kind cron, stage shadow, dispatch dry_run) and its allowlist entry."""
    command = list(command or GOOD_CMD[klass])
    row = {
        "lane_id": lane,
        "scheduler": {
            "kind": "cron",
            "expression": "30 2 * * *",
            "match": " ".join(command[1:]),
            "stage": stage,
            "wave": "D3",
        },
        "output_signal": {"kind": "json_key", "path": RECEIPT, "key": "ok_at"},
        "dispatch": {
            "mode": mode,
            "cron": ["30 2 * * *"],
            "tz": "America/New_York",
            "wave": "W3",
            "class": klass,
            "priority": 5,
            "retry_policy": RETRY.get(klass, "transient-2"),
        },
        "state": "ACTIVE",
    }
    entry = {
        "lane_id": lane,
        "command": command,
        "lock": f"/tmp/{lane}.lock",
        "lock_kind": "flock",
        "timeout_s": 600,
        "dry_run_arg": list(dry) if dry is not None else None,
        "live_arg": None if live is None else list(live),
        "market_gate": False,
        "output_signal": RECEIPT,
        "env_names": list(env),
    }
    if klass == "llm":
        entry["llm_route"] = dict(BRIDGE)
    argv = {lane: " ".join([*entry["command"], *(entry["dry_run_arg"] or []), *(entry["live_arg"] or [])])}
    return row, entry, argv


def _admit(row, entry, argv, *, shape="ACTIVE", status="ACTIVE"):
    return LD.r1_class_admission(
        row, entry, status=status, allowlist_argv=argv, exceptions={}, process_ids=PROCS, shadow_shape_status=shape
    )


def _dispatcher_row(klass: str, stage: str = "shadow"):
    row, entry, argv = _cron_shadow(klass, live=("--apply",) if klass != "llm" else ())
    row["scheduler"] = {
        "kind": "n8n",
        "expression": "dispatcher",
        "cadence": "30 2 * * *",
        "match": row["scheduler"]["match"],
        "wave": "W3",
        "stage": stage,
    }
    return row, entry, argv


def _row_status(version: str) -> str | None:
    m = re.search(rf"^\| {re.escape(version)} \| \d{{4}}-\d{{2}}-\d{{2}} \| (PROPOSED|ACTIVE)\b", AGENTS, re.M)
    return m.group(1) if m else None


# ------------------------------------------------------------------------------------ the policy pin


def test_shadow_shape_status_matches_the_agents_version_row():
    """The code cannot admit the cron shadow shape ahead of the vote: ACTIVE only when AGENTS.md carries an ACTIVE
    row for R1_SHADOW_SHAPE_POLICY_VERSION; otherwise PROPOSED."""
    assert LD.R1_SHADOW_SHAPE_POLICY_VERSION == "4.4.0"
    assert LD.R1_SHADOW_SHAPE_STATUS == (_row_status("4.4.0") or "PROPOSED")


def test_before_ratification_the_cron_shadow_row_is_refused_as_4_3_0_says():
    row, entry, argv = _cron_shadow("ingest")
    ok, why = _admit(row, entry, argv, shape="PROPOSED")
    assert not ok and why.startswith("shadow_on_cron_not_ratified"), why
    if LD.R1_SHADOW_SHAPE_STATUS != "ACTIVE":
        ok, why = LD.r1_class_admission(row, entry, allowlist_argv=argv, exceptions={}, process_ids=PROCS)
        assert not ok and "shadow_on_cron_not_ratified" in why, why


def test_r1_status_still_comes_first():
    row, entry, argv = _cron_shadow("learn")
    ok, why = _admit(row, entry, argv, status="PROPOSED")
    assert not ok and why.startswith("r1_not_ratified"), why


# ------------------------------------------------------------------------ admitted: the shadow shape


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
def test_cron_shadow_row_is_admitted_for_every_r1_class_once_ratified(klass):
    row, entry, argv = _cron_shadow(klass)
    assert _admit(row, entry, argv) == (True, f"r1_admitted:{klass}")
    assert LD.r1_shadow_on_cron_shape(row, status="ACTIVE") == (True, "shadow_on_cron")


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
@pytest.mark.parametrize("stage", sorted(LD.R1_STAGES))
def test_dispatcher_rows_are_unchanged(klass, stage):
    row, entry, argv = _dispatcher_row(klass, stage)
    for shape in ("PROPOSED", "ACTIVE"):
        assert _admit(row, entry, argv, shape=shape) == (True, f"r1_admitted:{klass}")


def test_pre_r1_cron_shadow_rows_are_unchanged():
    """Wave 1's rows (monitor/report/...) never depended on the R1 gate's row shape."""
    row, entry, argv = _cron_shadow("monitor", ["$PY", "scripts/job_coverage_monitor.py"])
    for shape in ("PROPOSED", "ACTIVE"):
        assert _admit(row, entry, argv, shape=shape) == (True, "pre_r1_class")


# ---------------------------------------------- refused: anything but shadow / dry_run / no live argv


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
@pytest.mark.parametrize(
    ("mutate", "why"),
    [
        (lambda r, e: r["scheduler"].update(stage="canary"), "shadow_on_cron:stage"),
        (lambda r, e: r["scheduler"].update(stage="cutover"), "shadow_on_cron:stage"),
        (lambda r, e: r["scheduler"].pop("stage"), "shadow_on_cron:stage"),
        (lambda r, e: r["dispatch"].update(mode="live"), "dispatch.mode 'live'"),
        (lambda r, e: r["dispatch"].update(mode="off"), "dispatch.mode 'off'"),
        (lambda r, e: e.update(live_arg=[]), "shadow_on_cron_live_arg_not_null"),
        (lambda r, e: e.update(live_arg=["--apply"]), "shadow_on_cron_live_arg_not_null"),
        (lambda r, e: r["scheduler"].update(expression="dispatcher"), "is not a 5-field cron"),
        (lambda r, e: r["scheduler"].update(expression="@daily"), "is not a 5-field cron"),
        (lambda r, e: e.update(dry_run_arg=None), "no_dry_run_arg"),
        (lambda r, e: e.update(dry_run_arg=[]), "no_dry_run_arg"),
        (
            lambda r, e: r.update(output_signal={"kind": "file_mtime", "path": "logs/x.log"}),
            "output_signal_not_a_lane_receipt",
        ),
        (lambda r, e: e.update(output_signal="data/runtime/other_last.json"), "allowlist_output_signal_mismatch"),
        (lambda r, e: e.update(env_names=["DB_HOST", "SCHWAB_APP_KEY"]), "broker_credential_env:SCHWAB_APP_KEY"),
        (lambda r, e: e.update(env_names=["ALPACA_API_KEY_ID"]), "broker_credential_env"),
        (lambda r, e: r.update(stay_on_cron={"class": "operator", "reason": "x"}), "stay_on_cron"),
        (lambda r, e: r.update(recommendation="KEEP_ON_CRON"), "keep_on_cron"),
        (lambda r, e: r.update(watch={"stay_behind": True}), "stay_behind"),
        (lambda r, e: r["scheduler"].update(match="tradeai-foo.service"), "systemd_service_lane"),
    ],
)
def test_cron_shadow_row_keeps_every_condition(klass, mutate, why):
    row, entry, argv = _cron_shadow(klass)
    mutate(row, entry)
    ok, reason = _admit(row, entry, argv)
    assert not ok and why in reason, (klass, reason)


def test_cron_shadow_row_with_no_allowlist_entry_is_refused():
    row, _entry, argv = _cron_shadow("ingest", lane="r1-shadow-unlisted-xyz")
    ok, why = LD.r1_class_admission(
        row, None, status="ACTIVE", allowlist_argv={}, exceptions={}, shadow_shape_status="ACTIVE"
    )
    assert not ok and why == "not_allowlisted", why


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
@pytest.mark.parametrize(
    ("command", "dry", "why"),
    [
        (["$PY", "scripts/schwab_place_order.py"], ("--dry-run",), "forbidden_token"),
        (["$PY", "scripts/submit_orders.py"], ("--dry-run",), "forbidden_token"),
        (["$PY", "scripts/unified_stop_supervisor.py"], ("--dry-run",), "forbidden_token"),
        (["$PY", "scripts/schwab_position_sync.py"], ("--dry-run",), "forbidden_token"),
        (["$PY", "scripts/alpaca_paper_executor.py"], ("--dry-run",), "forbidden_token"),
        (["$PY", "scripts/render_env.py"], ("--dry-run",), "forbidden_token"),
        (["bash", "scripts/sm-render.sh"], ("--dry-run",), "forbidden_token"),
        (["$PY", "scripts/bin_guard_grant.py"], ("--dry-run",), "forbidden_token"),
        (["$PY", "scripts/send_telegram_proposal_alert.py"], ("--dry-run",), "forbidden_token"),
        (["$PY", "scripts/foo_ingest.py"], ("--dry-run", "--daemon"), "daemon_flag"),
        (["$PY", "scripts/foo_ingest.py", "--loop"], ("--dry-run",), "daemon_flag"),
        (["$PY", "scripts/foo_ingest.py"], ("--dry-run", "--watch=30"), "daemon_flag"),
        (["$PY", "scripts/foo_ingest.py", "--serve"], ("--dry-run",), "daemon_flag"),
    ],
)
def test_never_eligible_lanes_stay_refused_in_the_shadow_shape(klass, command, dry, why):
    """§23.14 / §0 rails 1-2: the new shape relaxes nothing for broker, order, stop, positions, secret, guard,
    sender or daemon lanes, even when every other condition holds."""
    row, entry, argv = _cron_shadow(klass, command, dry=dry)
    ok, reason = _admit(row, entry, argv)
    assert not ok and why in reason, (klass, command, reason)


@pytest.mark.parametrize(
    ("route", "extra", "why"),
    [
        (None, [], "llm_route_not_governed_bridge"),
        ({"via": "llm_lane", "process_id": "multi_tier_trade_reviewer"}, [], "llm_route_not_governed_bridge"),
        ({"via": "cio-governed-bridge", "process_id": "unregistered"}, [], "llm_process_unregistered"),
        (BRIDGE, ["--model", "deepseek-v4-pro"], "llm_argv_selects_provider"),
        (BRIDGE, ["--provider", "anthropic"], "llm_argv_selects_provider"),
    ],
)
def test_llm_shadow_row_still_needs_the_governed_bridge(route, extra, why):
    row, entry, argv = _cron_shadow("llm", [*GOOD_CMD["llm"], *extra])
    if route is None:
        entry.pop("llm_route")
    else:
        entry["llm_route"] = dict(route)
    ok, reason = _admit(row, entry, argv)
    assert not ok and why in reason, reason


def test_send_stays_refused_in_the_shadow_shape():
    row, entry, argv = _cron_shadow("send", ["$PY", "scripts/report_digest.py"])
    assert _admit(row, entry, argv) == (False, "class_gated:send")


def test_other_scheduler_kinds_are_not_the_shadow_shape():
    for kind in ("systemd", "n8n", None):
        row, entry, argv = _cron_shadow("ingest")
        row["scheduler"]["kind"] = kind
        ok, why = _admit(row, entry, argv)
        assert not ok and why == "not_a_dispatcher_row", (kind, why)
        assert LD.r1_shadow_on_cron_shape(row, status="ACTIVE") == (False, "shadow_on_cron:not_a_cron_row")


# ------------------------------------------------------------- the due computation honours the gate


NOW = datetime(2026, 10, 10, 6, 31, tzinfo=timezone.utc)  # 02:31 America/New_York, one minute after 30 2 * * *


@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
def test_compute_due_emits_the_cron_shadow_lane_only_once_ratified_and_only_dry_run(klass, monkeypatch):
    row, entry, _argv = _cron_shadow(klass)
    allow = {row["lane_id"]: entry}
    monkeypatch.setattr(LD, "R1_STATUS", "ACTIVE")
    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "PROPOSED")
    monkeypatch.setattr(LD, "load_llm_process_ids", lambda path=None: frozenset(PROCS))
    monkeypatch.setattr(LD, "load_run_allowlist_argv", lambda path=None: {})
    resp = D.compute_due([row], allow, POLICIES, None, NOW)
    assert resp["items"] == []
    assert [e["code"] for e in resp["errors"]] == ["class_not_permitted"]
    assert "shadow_on_cron_not_ratified" in resp["errors"][0]["detail"]

    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "ACTIVE")
    resp = D.compute_due([row], allow, POLICIES, None, NOW)
    assert resp["errors"] == [], resp["errors"]
    assert [i["lane_id"] for i in resp["items"]] == [row["lane_id"]]
    assert {i["mode"] for i in resp["items"]} == {"dry_run"}


# --------------------------------------------------------------------------- dispatcher vs tradeai-dispatcher


def test_the_names_are_what_the_code_and_the_workflow_index_say():
    assert LD.DISPATCHER_EXPRESSION == "dispatcher"
    assert LD.DISPATCHER_WORKFLOW_ID == "tradeai-dispatcher"
    ids = json.dumps(WORKFLOW_INDEX)
    assert '"tradeai-dispatcher"' in ids, "the dispatcher's workflow id moved; update DISPATCHER_WORKFLOW_ID"
    assert SC.DISPATCHER_EXPRESSIONS == {LD.DISPATCHER_EXPRESSION, LD.DISPATCHER_WORKFLOW_ID}
    assert '`scheduler.expression = "dispatcher"`' in AGENTS


@pytest.mark.parametrize("kind", ["n8n", "cron"])
@pytest.mark.parametrize("klass", sorted(LD.R1_ADMITTED_CLASSES))
def test_workflow_id_as_expression_is_refused_by_name(kind, klass):
    row, entry, argv = _dispatcher_row(klass, "shadow")
    row["scheduler"].update(kind=kind, expression="tradeai-dispatcher")
    for shape in ("PROPOSED", "ACTIVE"):
        ok, why = _admit(row, entry, argv, shape=shape)
        assert not ok and why.startswith("workflow_id_as_expression:tradeai-dispatcher"), why


def test_registry_check_reports_the_workflow_id_as_expression_for_any_class():
    row, _e, _a = _cron_shadow("monitor", ["$PY", "scripts/job_coverage_monitor.py"])
    row["scheduler"].update(kind="n8n", expression="tradeai-dispatcher")
    issues = LD.validate_dispatch_block(row)
    assert any(i.code == LD.ISSUE_BAD_BLOCK and "tradeai-dispatcher" in i.detail for i in issues), issues
    bare = {"lane_id": "x", "scheduler": {"kind": "n8n", "expression": "tradeai-dispatcher"}}
    assert [i.code for i in LD.validate_dispatch_block(bare)] == [LD.ISSUE_BAD_BLOCK]
    ok_row = {"lane_id": "x", "scheduler": {"kind": "n8n", "expression": "dispatcher", "stage": "shadow"}}
    assert LD.validate_dispatch_block(ok_row) == []


def test_stage_clamp_fails_closed_on_the_workflow_id_as_expression():
    rows = [
        {"lane_id": "a", "scheduler": {"kind": "n8n", "expression": "tradeai-dispatcher"}},
        {"lane_id": "b", "scheduler": {"kind": "n8n", "expression": "dispatcher"}},
        {"lane_id": "c", "scheduler": {"kind": "n8n", "expression": "wf-abc123"}},
        {"lane_id": "d", "scheduler": {"kind": "cron", "expression": "0 2 * * *", "stage": "shadow"}},
    ]
    assert SC.clamp_mode("a", "live", rows)["effective_mode"] == "dry_run"
    assert SC.clamp_mode("a", "live", rows)["reason"] == "dispatcher_row_without_stage"
    assert SC.clamp_mode("b", "live", rows)["effective_mode"] == "dry_run"
    assert SC.clamp_mode("c", "live", rows)["effective_mode"] == "live"  # per-lane workflow: unchanged
    assert SC.clamp_mode("d", "live", rows)["reason"] == "stage_shadow"  # the cron shadow row is clamped


def test_real_registry_carries_no_workflow_id_expression_and_no_dispatch_issue():
    for row in REGISTRY_DOC["lanes"]:
        assert (row.get("scheduler") or {}).get("expression") != "tradeai-dispatcher", row["lane_id"]
    assert LD.registry_dispatch_errors(REGISTRY_DOC) == []
    for row in REGISTRY_DOC["lanes"]:
        if (row.get("dispatch") or {}).get("class") in LD.R1_ADMITTED_CLASSES:
            assert LD.r1_class_admission(copy.deepcopy(row))[0], row["lane_id"]


# ------------------------------------------------------------------------------------------- _cutover.py


def test_cutover_refuses_the_workflow_id_as_expression(tmp_path):
    root = CT._code_root(tmp_path)
    fake, store = CT._fake_crontab(tmp_path)
    before = "\n".join([CT.OTHER, CT.LINE]) + "\n"
    store.write_text(before)
    reg_before = (root / "config" / "lane_registry.json").read_bytes()
    r = CT._run(
        "cutover_lane.sh", CT.LANE, "--workflow-id", "tradeai-dispatcher", "--apply", env=CT._env(tmp_path, fake, root)
    )
    assert r.returncode == 2, r.stdout + r.stderr
    assert "--workflow-id dispatcher" in r.stdout
    assert store.read_text() == before and (root / "config" / "lane_registry.json").read_bytes() == reg_before


def test_cutover_of_a_dispatcher_lane_lands_at_stage_cutover_and_keeps_its_wave(tmp_path):
    rows = CT._rows()
    lane = next(r for r in rows if r["lane_id"] == CT.LANE)
    lane["scheduler"].update(stage="shadow", wave="D3")
    root = CT._code_root(tmp_path, rows=rows)
    fake, store = CT._fake_crontab(tmp_path)
    store.write_text("\n".join([CT.OTHER, CT.LINE]) + "\n")
    r = CT._run("cutover_lane.sh", CT.LANE, "--workflow-id", "dispatcher", env=CT._env(tmp_path, fake, root))
    assert r.returncode == 0, r.stdout + r.stderr
    assert CT._last(tmp_path)["scheduler_after"] == {
        "kind": "n8n",
        "expression": "dispatcher",
        "match": CT.MATCH,
        "cadence": "*/8 * * * *",
        "stage": "cutover",
        "wave": "D3",
    }


def test_cutover_with_a_per_lane_workflow_id_is_unchanged(tmp_path):
    root = CT._code_root(tmp_path)
    fake, store = CT._fake_crontab(tmp_path)
    store.write_text("\n".join([CT.OTHER, CT.LINE]) + "\n")
    r = CT._run("cutover_lane.sh", CT.LANE, "--workflow-id", "wf-abc123", env=CT._env(tmp_path, fake, root))
    assert r.returncode == 0, r.stdout + r.stderr
    assert CT._last(tmp_path)["scheduler_after"] == {
        "kind": "n8n",
        "expression": "wf-abc123",
        "match": CT.MATCH,
        "cadence": "*/8 * * * *",
    }
