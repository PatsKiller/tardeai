"""LQ-20261107-297 — a lane the n8n dispatcher only runs in a dry mode cannot write its output signal.

``prospectus-build`` (and 16 other lanes at 2026-11-07) is ``scheduler.kind: n8n`` with
``dispatch.mode: dry_run``: the dispatcher passes the dry argv, ``prospectus_window.py`` returns before
``write_receipt``, so ``data/runtime/prospectus-build_last.json`` is never refreshed. The detector raised one
``NO_OUTPUT`` breach per lane per day (182 OPEN rows) for a promotion state, and ``n8n_self_heal`` could never
close it because no later run can ever be live.

The exemption is narrow on purpose: ONLY ``scheduler.kind == "n8n"`` counts. ``investment-costs`` is scheduled
by cron with a stale ``dispatch.mode: dry_run`` and really runs live — silencing it would hide a real outage.
Hermetic: pure ``detect()`` calls and one ``main()`` dry run over a tmp code root and tmp state root.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import supervisor_breach_detector as sbd  # noqa: E402

COVERS = ["scripts/supervisor_breach_detector.py"]
NOW = dt.datetime(2026, 11, 7, 15, 0, tzinfo=dt.timezone.utc)
SLA = {"max_run_s": 900, "max_silence_s": 7200}
OLD = (NOW - dt.timedelta(days=10)).isoformat()


def _lane(lane_id, *, sched_kind="n8n", mode="dry_run", cadence=0.25, signal_kind="json_key"):
    sched = {"kind": sched_kind, "expression": "dispatcher" if sched_kind == "n8n" else "*/15 * * * *"}
    lane = {
        "lane_id": lane_id,
        "state": "ACTIVE",
        "expected_cadence_hours": cadence,
        "scheduler": sched,
        "output_signal": {"kind": signal_kind, "path": f"data/runtime/{lane_id}_last.json", "key": "ok_at"},
    }
    if mode is not None:
        lane["dispatch"] = {"mode": mode, "cron": ["*/15 * * * *"], "class": "report", "priority": 5}
    return lane


def _run(lane, last_output_at=OLD, readable=True):
    def observe(sig):
        return {"last_output_at": last_output_at, "readable": readable}

    diag: dict = {}
    rows = sbd.detect(
        lanes=[lane],
        sla_by_lane={lane["lane_id"]: dict(SLA)},
        heartbeats={},
        observe=observe,
        now=NOW,
        diagnostics=diag,
    )
    return rows, diag


# ── the predicate ───────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["dry_run", "dry-run", "dryRun", "dryrun", "preflight", "rehearsal", "plan", "shadow"])
def test_n8n_dry_modes_qualify(mode):
    lane = _lane("prospectus-build", mode=mode)
    assert sbd.dispatch_never_live(lane) == mode.strip().lower()


@pytest.mark.parametrize("mode", ["live", "on", None, "enabled"])
def test_n8n_live_modes_do_not_qualify(mode):
    assert sbd.dispatch_never_live(_lane("x", mode=mode)) is None


@pytest.mark.parametrize("kind", ["cron", "systemd", "none"])
def test_other_schedulers_never_qualify_even_with_a_dry_dispatch_mode(kind):
    """investment-costs: scheduler cron, dispatch.mode dry_run, and its cron line really runs live."""
    assert sbd.dispatch_never_live(_lane("investment-costs", sched_kind=kind, mode="dry_run")) is None


# ── detect(): the defect and its controls ──────────────────────────────────────────────────────────────


def test_n8n_dry_run_lane_raises_no_output_breach_and_is_reported_in_diagnostics():
    lane = _lane("prospectus-build")
    rows, diag = _run(lane)
    assert [r for r in rows if r["kind"] == "NO_OUTPUT"] == []
    entry = diag["dry_run_dispatch"]["prospectus-build"]
    assert entry["dispatch_mode"] == "dry_run"
    assert entry["observed"]["last_output_at"] == OLD
    assert entry["signal"] == lane["output_signal"]


def test_n8n_dry_run_lane_with_no_signal_at_all_is_still_not_a_breach():
    rows, diag = _run(_lane("prospectus-build"), last_output_at=None)
    assert [r for r in rows if r["kind"] == "NO_OUTPUT"] == []
    assert diag["dry_run_dispatch"]["prospectus-build"]["observed"]["last_output_at"] is None


def test_n8n_dry_run_lane_with_unreadable_signal_is_not_a_breach():
    rows, diag = _run(_lane("prospectus-build"), last_output_at=None, readable=False)
    assert [r for r in rows if r["kind"] == "NO_OUTPUT"] == []
    assert diag["dry_run_dispatch"]["prospectus-build"]["observed"]["readable"] is False


def test_shadow_dispatch_lane_is_not_a_breach():
    rows, diag = _run(_lane("calibration-shadow-harness", mode="shadow"))
    assert [r for r in rows if r["kind"] == "NO_OUTPUT"] == []
    assert "calibration-shadow-harness" in diag["dry_run_dispatch"]


def test_n8n_live_lane_still_raises_no_output():
    rows, _ = _run(_lane("active-trader-motion-watchdog", mode="live"))
    assert [r["kind"] for r in rows] == ["NO_OUTPUT"]


def test_cron_lane_with_a_stale_dry_dispatch_mode_still_raises_no_output():
    """The field is not the execution path for a cron lane — investment-costs must keep paging."""
    rows, diag = _run(_lane("investment-costs", sched_kind="cron", mode="dry_run"))
    assert [r["kind"] for r in rows] == ["NO_OUTPUT"]
    assert diag.get("dry_run_dispatch") == {}


def test_systemd_lane_with_a_dry_dispatch_mode_still_raises_no_output():
    rows, _ = _run(_lane("unit-run-snapshot", sched_kind="systemd", mode="dry_run"))
    assert [r["kind"] for r in rows] == ["NO_OUTPUT"]


def test_dry_run_lane_that_did_produce_is_also_quiet_and_keeps_the_observation():
    rows, diag = _run(_lane("prospectus-build"), last_output_at=(NOW - dt.timedelta(minutes=5)).isoformat())
    assert rows == []
    assert diag["dry_run_dispatch"]["prospectus-build"]["observed"]["last_output_at"].endswith("+00:00")


# ── main(): the run summary carries the count, so "not breaching" never reads as "producing" ───────────


def test_main_dry_run_summary_reports_the_dry_dispatch_lanes(tmp_path, monkeypatch, capsys):
    code = tmp_path / "code"
    (code / "config").mkdir(parents=True)
    state = tmp_path / "state"
    rt = state / "data" / "runtime"
    rt.mkdir(parents=True)
    lanes = [_lane("prospectus-build"), _lane("investment-costs", sched_kind="cron", mode="dry_run")]
    # pytest's tmp_path: a fresh directory owned by this test, never a live store.
    reg_p = code / "config" / "lane_registry.json"
    reg_p.write_text(json.dumps({"lanes": lanes}))  # nosemgrep: tq-py-nonatomic-store-write -- tmp_path
    seed_p = rt / "supervisor_sla_seed.json"
    seed_p.write_text(  # nosemgrep: tq-py-nonatomic-store-write -- tmp_path
        json.dumps({"rows": [{"lane_id": lane["lane_id"], "max_run_s": 900} for lane in lanes]})
    )
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_HEARTBEAT_DIR", str(tmp_path / "hb"))
    monkeypatch.setattr(sbd, "_read_only_db_query", lambda: None)
    fake_db = type(sys)("db_adapter")
    fake_db._get_conn = lambda: (_ for _ in ()).throw(RuntimeError("no db in tests"))
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    import supervisor_heartbeat as hbmod

    monkeypatch.setattr(hbmod, "beat", lambda *a, **k: {"pg": "skipped"})
    monkeypatch.setattr(
        sbd,
        "_slow_checks_due",
        lambda runtime_dir, now, mode: ({"freshness_contracts": False, "input_starvation": False}, {}),
    )
    monkeypatch.setattr(sbd, "detect_input_starvation", lambda **k: [])
    monkeypatch.setattr(sbd, "detect_freshness", lambda **k: [])
    monkeypatch.setattr(sys, "argv", ["supervisor_breach_detector.py", "--root", str(code), "--dry-run"])
    assert sbd.main() == 0
    out = capsys.readouterr().out
    doc, _end = json.JSONDecoder().raw_decode(out[out.index("{") :])
    assert doc["dry_run_dispatch"]["lanes"] == 1
    assert doc["dry_run_dispatch"]["by_mode"] == {"dry_run": 1}
    assert list(doc["dry_run_dispatch"]["signal_reads"]) == ["prospectus-build"]
    # the cron lane is still graded: probe reads nothing in this tmp state root
    assert doc["by_kind"] == {"NO_OUTPUT": 1}
