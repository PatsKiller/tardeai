"""A no-op runbook is recorded as evidence (the cap still applies until the routing change)."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from lib import incident_supervisor as S  # noqa: E402
SPEC = {"success_when": {"json": {"acted": {"not_empty": True}}}}


def _cfg():
    return json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text())

def test_empty_acted_is_a_no_op():
    assert S._action_took_effect(SPEC, json.dumps({"acted": []})) is False

def test_a_real_act_is_not_a_no_op():
    assert S._action_took_effect(SPEC, json.dumps({"acted": ["x"]})) is True

def test_without_a_contract_rc_semantics_hold():
    assert S._action_took_effect({}, "not json") is True


def _rec(*actions):
    # L.attempt() writes the detail keys at the top level of the row; mirror that shape.
    return {"attempts": [{"action": a, "actor": S.ACTOR, "at": f"2026-11-03T00:0{i}:00Z", **d}
                         for i, (a, d) in enumerate(actions)]}


def test_the_last_runbook_noop_is_detected():
    assert S._last_action_was_noop(_rec(("cron_self_heal", {"no_op": False}), ("cron_self_heal", {"no_op": True}))) is True


def test_a_real_action_after_a_noop_is_not_a_noop():
    assert S._last_action_was_noop(_rec(("cron_self_heal", {"no_op": True}), ("restart_unit", {"no_op": False}))) is False


def test_triage_rows_do_not_count_as_actions():
    assert S._last_action_was_noop(_rec(("cron_self_heal", {"no_op": True}), ("triage", {"no_op": True}))) is True


# ---------------------------------------------------------------- end-to-end: the cap route fires
def test_at_the_cap_a_noop_runbook_dispatches_the_fixer(tmp_path, monkeypatch):
    """Drive real cycle() rows — L.attempt() shape and all — with a no-op runbook and a stub fixer."""
    from datetime import datetime, timedelta, timezone
    from lib import incidents as L
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))
    root = ROOT
    cfg = json.loads((root / "config" / "incident_runbook_actions.json").read_text())
    t0 = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
    rec, _ = L.open_incident(source={"kind": "watcher", "watcher": "health_tick", "job": "fixture-step"},
                             title="health tick step fixture-step failed (rc=2)", d=tmp_path / "ledger", now=t0)
    answers, fixes = [], []

    def deps():
        def model(_p):
            return (json.dumps({"class": "runbook", "action": "cron_self_heal", "params": {}, "rationale": "r"}),
                    "anthropic")
        def run(_argv, _cwd, _env, _timeout):
            return 0, json.dumps({"acted": []})          # the runbook ran and acted on nothing
        def notify(_t, _p):
            return True
        def fixer(req, apply):
            fixes.append(json.loads(Path(req).read_text()))
            return {"rc": 0, "work_proven": True, "admitted": ["shf-1"],
                    "prs": ["https://example.invalid/pr/1"], "summary": "ok"}
        return S.Deps(model=model, run=run, notify=notify, fixer=fixer)

    for k in range(3):
        S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "state", release_root=root, cfg=cfg, deps=deps(),
                apply=True, now=t0 + timedelta(minutes=31 * k),
                environ={"HOME": "/h", "PATH": "/bin", "ANTHROPIC_API_KEY": "nope"}, root=root)
    # The three real attempt rows must carry the flat no_op the cap predicate reads.
    rows = [a for a in L.load_records(tmp_path / "ledger")[rec["id"]]["attempts"] if a.get("action") == "cron_self_heal"]
    assert len(rows) == 3 and all(r.get("no_op") is True for r in rows)

    out = S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "state", release_root=root, cfg=cfg, deps=deps(),
                  apply=True, now=t0 + timedelta(hours=3),
                  environ={"HOME": "/h", "PATH": "/bin", "ANTHROPIC_API_KEY": "nope"}, root=root)
    assert out["dispatched"] and out["dispatched"][0]["id"] == rec["id"], out
    assert fixes and fixes[0]["code_defect"]["evidence"]["incident_key"] == rec["id"]
    after = L.load_records(tmp_path / "ledger")[rec["id"]]
    assert any(a.get("action") == "fixer_dispatch" for a in after["attempts"])
    assert after["status"] != "blocked"


# ---------------------------------------------------------------- a live fix job owns the incident
def _capped_incident(tmp_path, monkeypatch, *, dispatch_hours_ago, ok=True):
    from datetime import datetime, timedelta, timezone
    from lib import incidents as L
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))
    t0 = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
    rec, _ = L.open_incident(source={"kind": "watcher", "watcher": "health_tick", "job": "fixture-step"},
                             title="health tick step fixture-step failed (rc=2)", d=tmp_path / "ledger", now=t0)
    for k in range(3):
        L.attempt(rec["id"], actor=S.ACTOR, action="cron_self_heal", result="rc=0",
                  ok=True, detail={"no_op": True}, d=tmp_path / "ledger", now=t0 + timedelta(minutes=k + 1))
    L.attempt(rec["id"], actor=S.ACTOR, action="fixer_dispatch", result="fixer rc=0",
              ok=ok, detail={"provider": "cap_route"}, d=tmp_path / "ledger",
              now=t0 + timedelta(hours=2) - timedelta(hours=dispatch_hours_ago))
    return rec, t0 + timedelta(hours=3)


def test_a_fresh_fixer_dispatch_does_not_page_a_person(tmp_path, monkeypatch):
    rec, when = _capped_incident(tmp_path, monkeypatch, dispatch_hours_ago=1)
    out = S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "state", release_root=ROOT, cfg=_cfg(),
                  deps=S.Deps(model=lambda p: (_ for _ in ()).throw(AssertionError("no model call")),
                              run=lambda *a, **k: (0, "ok"), notify=lambda *a, **k: True,
                              fixer=lambda *a, **k: {"rc": 0, "prs": []}),
                  apply=True, now=when, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)
    assert {"id": rec["id"], "why": "fixer job active"} in out["skipped"], out
    assert not out["blocked"] and not out["escalated"], out
    from lib import incidents as L
    assert L.load_records(tmp_path / "ledger")[rec["id"]]["status"] != "blocked"


def test_a_stale_or_failed_dispatch_still_reaches_a_person(tmp_path, monkeypatch):
    rec, when = _capped_incident(tmp_path, monkeypatch, dispatch_hours_ago=13)
    out = S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "state", release_root=ROOT, cfg=_cfg(),
                  deps=S.Deps(model=lambda p: (_ for _ in ()).throw(AssertionError("no model call")),
                              run=lambda *a, **k: (0, "ok"), notify=lambda *a, **k: True,
                              fixer=lambda *a, **k: {"rc": 0, "prs": []}),
                  apply=True, now=when, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)
    assert out["blocked"] and out["blocked"][0]["id"] == rec["id"], out
