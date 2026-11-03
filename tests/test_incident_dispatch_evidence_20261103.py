"""A dispatch that ran no work must not hide an incident from a person.

The fixer exits 0 for "not armed", "busy" and "nothing to do". Recording that as a healthy fix job
let the fresh-dispatch guard suppress paging for fixer_active_hours (12h) with no job running.
Proven work means: a job was admitted this cycle, or an existing active job owns the signature.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from lib import incident_supervisor as S  # noqa: E402


# ---------------------------------------------------------------- classification
def test_a_zero_exit_with_no_admitted_job_is_not_work():
    assert S._dispatch_ok({"rc": 0, "admitted": []}) is False
    assert S._dispatch_ok({"rc": 0}) is False


def test_a_busy_cycle_is_not_work_even_though_it_exits_zero():
    assert S._dispatch_ok({"rc": 0, "admitted": [], "work_proven": False, "busy": True}) is False


def test_an_admitted_job_is_work():
    assert S._dispatch_ok({"rc": 0, "admitted": ["shf-1"]}) is True


def test_an_existing_active_job_is_work():
    assert S._dispatch_ok({"rc": 0, "admitted": [], "work_proven": True}) is True


def test_a_failed_dispatch_is_never_work():
    assert S._dispatch_ok({"rc": 1, "admitted": ["shf-1"]}) is False


# ---------------------------------------------------------------- the real factory's reading
def _factory_with(stdout: str, rc: int = 0):
    class P:
        returncode = rc

        def __init__(self):
            self.stdout, self.stderr = stdout, ""

    class SP:
        @staticmethod
        def run(*a, **k):
            return P()

    mod = S
    real = mod.subprocess
    mod.subprocess = SP
    try:
        fx = mod.default_fixer_factory(
            {"policy": {"fixer": {"script": "scripts/self_heal_fixer.py"}}}, "python", ROOT)
        return fx(Path("/tmp/req.json"), True)
    finally:
        mod.subprocess = real


def test_the_factory_reads_a_not_armed_run_as_no_work():
    """The REAL shape: the fixer admits the job first, then refuses because the lane is not armed.

    ``admitted`` non-empty is therefore not proof; only the attempted outcome distinguishes a run
    that did work from one that was refused before any model call."""
    res = _factory_with(json.dumps({"mode": "apply",
                                    "admitted": [{"job_id": "j1", "lane": "x", "state": "fix_requested"}],
                                    "attempted": [{"job_id": "j1", "outcome": "not_armed:no active git-push guard grant"}]}))
    assert res["rc"] == 0 and res["admitted"] == ["j1"]
    assert res["work_proven"] is False and S._dispatch_ok(res) is False


def test_the_factory_reads_a_busy_cycle_as_no_work():
    res = _factory_with(json.dumps({"mode": "apply", "busy": True, "why": "another cycle holds the lock"}))
    assert res["work_proven"] is False


def test_an_admission_without_an_attempt_is_not_work():
    """Admission then a crash/refusal before any attempt must page, not hide."""
    res = _factory_with(json.dumps({"mode": "apply", "admitted": [{"job_id": "shf-1", "lane": "x"}], "attempted": []}))
    assert res["admitted"] == ["shf-1"] and res["work_proven"] is False


def test_an_admitted_job_with_a_real_attempt_outcome_is_work():
    res = _factory_with(json.dumps({"mode": "apply", "admitted": [{"job_id": "shf-1", "lane": "x"}],
                                    "attempted": [{"job_id": "shf-1", "outcome": "fix_ready_local"}]}))
    assert res["work_proven"] is True and S._dispatch_ok(res) is True


def test_a_dedupe_reason_is_not_proof_of_work():
    """``fix_requested`` counts as ACTIVE, so a stuck not-armed job keeps matching ``deduped:active``.
    The skip reason cannot prove the existing job is doing work; it must not suppress a page."""
    res = _factory_with(json.dumps({"mode": "apply", "admitted": [],
                                    "skipped": [{"lane": "x", "why": "deduped:active:shf-9"}]}))
    assert res["work_proven"] is False and S._dispatch_ok(res) is False


def test_malformed_report_rows_do_not_crash_the_factory():
    res = _factory_with(json.dumps({"mode": "apply", "admitted": "shf-1",
                                    "attempted": ["x", None, {"job_id": 7, "outcome": "fix_ready_local"}],
                                    "skipped": ["x", None]}))
    assert res["work_proven"] is False


def test_unparseable_output_is_not_work():
    res = _factory_with("not json at all")
    assert res["work_proven"] is False


# ---------------------------------------------------------------- end to end: who gets paged
def _cap_route_dispatch(tmp_path, monkeypatch, fixer_result):
    from datetime import datetime, timedelta, timezone
    from lib import incidents as L
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))
    cfg = json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text())
    t0 = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
    rec, _ = L.open_incident(source={"kind": "watcher", "watcher": "health_tick", "job": "fixture-step"},
                             title="health tick step fixture-step failed (rc=2)", d=tmp_path / "ledger", now=t0)

    def deps():
        return S.Deps(model=lambda _p: (json.dumps({"class": "runbook", "action": "cron_self_heal",
                                                    "params": {}, "rationale": "r"}), "anthropic"),
                      run=lambda *a, **k: (0, json.dumps({"acted": []})),
                      notify=lambda *a, **k: True,
                      fixer=lambda *a, **k: dict(fixer_result))
    for k in range(3):
        S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "state", release_root=ROOT, cfg=cfg, deps=deps(),
                apply=True, now=t0 + timedelta(minutes=31 * k),
                environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)
    out = S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "state", release_root=ROOT, cfg=cfg, deps=deps(),
                  apply=True, now=t0 + timedelta(hours=3), environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)
    assert out["dispatched"], out
    return rec, cfg


def test_a_dispatch_that_admitted_nothing_pages_a_person_on_the_next_cycle(tmp_path, monkeypatch):
    rec, cfg = _cap_route_dispatch(tmp_path, monkeypatch, {"rc": 0, "admitted": [], "work_proven": False, "summary": "busy"})
    from lib import incidents as L
    from datetime import datetime, timedelta, timezone
    when = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)     # one cycle later, still within 12h
    out = S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "state", release_root=ROOT, cfg=cfg,
                  deps=S.Deps(model=lambda p: (_ for _ in ()).throw(AssertionError("no model call")),
                              run=lambda *a, **k: (0, "ok"), notify=lambda *a, **k: True,
                              fixer=lambda *a, **k: {"rc": 0}),
                  apply=True, now=when, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)
    assert rec["id"] in [b["id"] for b in out["blocked"]], out
    assert L.load_records(tmp_path / "ledger")[rec["id"]]["status"] == "blocked"


def test_a_dispatch_that_admitted_a_job_still_suppresses_paging(tmp_path, monkeypatch):
    rec, cfg = _cap_route_dispatch(tmp_path, monkeypatch, {"rc": 0, "admitted": ["shf-1"], "work_proven": True})
    from datetime import datetime, timezone
    when = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)
    out = S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "state", release_root=ROOT, cfg=cfg,
                  deps=S.Deps(model=lambda p: (_ for _ in ()).throw(AssertionError("no model call")),
                              run=lambda *a, **k: (0, "ok"), notify=lambda *a, **k: True,
                              fixer=lambda *a, **k: {"rc": 0}),
                  apply=True, now=when, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)
    assert {"id": rec["id"], "why": "fixer job active"} in out["skipped"], out
    assert not out["blocked"], out
