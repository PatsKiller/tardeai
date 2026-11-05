"""The cycle budget bounds the WHOLE cycle, not one fixer dispatch (reviewer cc4, 2026-11-03).

Synthetic only: temp ledger, temp state root, temp release root, a fake monotonic clock and fully
stubbed model/run/notify/fixer dependencies. No real sleeps, no network, no subprocess.

Each test names, in its docstring, which gate removal makes it fail.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from lib import incident_supervisor as S  # noqa: E402
from lib import incidents as L  # noqa: E402

T0 = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)


class Clock:
    """A fake monotonic clock: mutable ``.now``, callable, advanced only by the stubs."""

    def __init__(self, start: float = 0.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def fresh_clock() -> Clock:
    """Every cycle starts its own t=0; a shared clock would make cycle 2 look budget-spent."""
    return Clock()


def cfg():
    # The REAL allowlist and policy; the gates must work against the shipped timeouts.
    return json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text())


def ledger_for(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))
    return tmp_path / "ledger"


def open_tick(ledger: Path, job: str, *, offset_s: int = 0, title: str = None) -> dict:
    rec, created = L.open_incident(
        source={"kind": "watcher", "watcher": "health_tick", "job": job},
        title=title or f"health tick step {job} failed (rc=2)",
        fingerprint=L.fingerprint_of("cycle-budget-test", job),
        d=ledger, now=T0 + timedelta(seconds=offset_s),
    )
    assert created, rec
    return rec


def run_cycle(ledger: Path, tmp_path: Path, deps: S.Deps, now: datetime, clock: Clock) -> dict:
    return S.cycle(d=ledger, state_root=tmp_path / "state", release_root=tmp_path / "release",
                   cfg=cfg(), deps=deps, apply=True, now=now,
                   environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT, clock=clock)


def code_defect(_prompt: str) -> tuple[str, str]:
    return (json.dumps({"class": "code_defect", "action": "fix the defect",
                        "params": {}, "rationale": "r"}), "anthropic")


def test_a_model_call_that_cannot_finish_is_deferred(tmp_path, monkeypatch):
    """Remove the ``before model`` gate and incident 2 gets triaged (model called twice, no deferral).

    Also covers the queue draining on a later cycle with a fresh clock.
    """
    ledger = ledger_for(tmp_path, monkeypatch)
    inc1 = open_tick(ledger, "fixer-step", offset_s=0)
    inc2 = open_tick(ledger, "second-step", offset_s=1)

    model_calls: list[str] = []
    run_calls: list[list] = []

    def model(prompt: str) -> tuple[str, str]:
        model_calls.append(prompt)
        return code_defect(prompt)

    def slow_fixer(_req, _apply, timeout=None):
        assert timeout is not None and timeout > 0
        clock.advance(7400)  # 7500 budget - 7400 elapsed - 300 margin = -200s spendable
        return {"rc": 0, "work_proven": True, "admitted": ["shf-1"], "prs": [], "summary": "ok"}

    def run(argv, cwd, env, timeout):
        run_calls.append(argv)
        return 0, "ok"

    clock = fresh_clock()
    deps = S.Deps(model=model, run=run, notify=lambda *a, **k: True, fixer=slow_fixer)
    out = run_cycle(ledger, tmp_path, deps, T0 + timedelta(seconds=2), clock)

    assert [d["id"] for d in out["dispatched"]] == [inc1["id"]], out
    assert {"id": inc2["id"], "why": "deferred: cycle budget", "stage": "before model"} in [
        {k: s[k] for k in ("id", "why", "stage")} for s in out["skipped"] if "stage" in s], out
    assert len(model_calls) == 1, "the model must never be called for incident 2"
    assert run_calls == [], "no runbook action ran"
    rec2 = L.load_records(ledger)[inc2["id"]]
    assert rec2["status"] in L.UNRESOLVED, rec2
    rows = [a for a in rec2["attempts"] if a.get("actor") == S.ACTOR and a.get("action") == "triage"]
    assert any(r.get("result") == "deferred: cycle budget" and r.get("deferred_at") == "before model"
               for r in rows), rows

    # A later cycle with a fresh clock and a fast fixer drains the deferred incident.
    model_calls.clear()

    def fast_fixer(_req, _apply, timeout=None):
        return {"rc": 0, "work_proven": True, "admitted": ["shf-2"], "prs": [], "summary": "ok"}

    deps2 = S.Deps(model=model, run=run, notify=lambda *a, **k: True, fixer=fast_fixer)
    out2 = run_cycle(ledger, tmp_path, deps2, T0 + timedelta(minutes=10), fresh_clock())
    assert inc2["id"] in [d["id"] for d in out2["dispatched"]], out2


def test_a_runbook_that_cannot_fit_is_deferred_without_starving_the_incident(tmp_path, monkeypatch):
    """Remove the ``before runbook`` gate and the runner is called in cycle 1 (partial-state risk).

    Remove the ``_is_budget_deferral`` cooldown exclusion and cycle 2 skips incident 2 as
    ``cooldown`` even though the deferral ran nothing.
    """
    ledger = ledger_for(tmp_path, monkeypatch)
    inc1 = open_tick(ledger, "fixer-step", offset_s=0)
    inc2 = open_tick(ledger, "fixture-step", offset_s=1)

    model_calls: list[str] = []
    run_calls: list[list] = []

    def model(prompt: str) -> tuple[str, str]:
        model_calls.append(prompt)
        if inc2["id"] in prompt:
            return (json.dumps({"class": "runbook", "action": "health_tick_step_once",
                                "params": {"step": "fixture-step"}, "rationale": "r"}), "anthropic")
        return code_defect(prompt)

    def slow_fixer(_req, _apply, timeout=None):
        clock.advance(6601)  # 7500 - 6601 - 300 = 599s: enough for a 120s model, not a 600s action
        return {"rc": 0, "work_proven": True, "admitted": ["shf-1"], "prs": [], "summary": "ok"}

    def run(argv, cwd, env, timeout):
        run_calls.append(argv)
        return 0, "ok"

    clock = fresh_clock()
    deps = S.Deps(model=model, run=run, notify=lambda *a, **k: True, fixer=slow_fixer)
    out = run_cycle(ledger, tmp_path, deps, T0 + timedelta(seconds=2), clock)

    assert inc1["id"] in [d["id"] for d in out["dispatched"]], out
    assert inc2["id"] in [s["id"] for s in out["skipped"]
                          if s.get("why") == "deferred: cycle budget" and s.get("stage") == "before runbook"], out
    assert run_calls == [], "the 600s action must not start with 599s spendable"
    assert L.load_records(ledger)[inc2["id"]]["status"] in L.UNRESOLVED

    # Cycle 2, inside the 30-minute model cooldown window: the deferral must not have started it.
    deps2 = S.Deps(model=model, run=run, notify=lambda *a, **k: True,
                   fixer=lambda _r, _a, timeout=None: {"rc": 0, "work_proven": True,
                                                       "admitted": ["x"], "prs": [], "summary": "ok"})
    out2 = run_cycle(ledger, tmp_path, deps2, T0 + timedelta(minutes=10), fresh_clock())

    assert [a["action"] for a in out2["actions"]] == ["health_tick_step_once"], out2
    assert len(run_calls) == 1, "cycle 2 must run the action exactly once"
    assert run_calls[0][1:] == ["scripts/health_tick.py", "--once", "--step", "fixture-step"], run_calls
    assert not [s for s in out2["skipped"] if s["id"] == inc2["id"] and s["why"] == "cooldown"], out2


def test_refused_scope_still_blocks_and_pages_when_the_budget_is_spent(tmp_path, monkeypatch):
    """Move the budget gates ahead of the refused-scope path and incident 2 is deferred instead of
    blocked: no ``blocked`` entry, no page. The deterministic path must survive a spent budget.
    """
    ledger = ledger_for(tmp_path, monkeypatch)
    inc1 = open_tick(ledger, "fixer-long", offset_s=0)
    inc2 = open_tick(ledger, "broker-order", offset_s=1,
                     title="broker order route failed (rc=2)")

    pages: list[tuple[str, str]] = []

    def slow_fixer(_req, _apply, timeout=None):
        clock.advance(7400)  # spendable is now negative
        return {"rc": 0, "work_proven": True, "admitted": ["shf-1"], "prs": [], "summary": "ok"}

    clock = fresh_clock()
    deps = S.Deps(model=code_defect, run=lambda *a, **k: (0, "ok"),
                  notify=lambda text, producer, priority="P2": pages.append((text, producer)) or True,
                  fixer=slow_fixer)
    out = run_cycle(ledger, tmp_path, deps, T0 + timedelta(seconds=2), clock)

    assert inc1["id"] in [d["id"] for d in out["dispatched"]], out
    blocked = [b for b in out["blocked"] if b["id"] == inc2["id"]]
    assert blocked and blocked[0]["why"].startswith("refused_scope:"), out
    escalated = [e for e in out["escalated"] if e["id"] == inc2["id"]]
    assert escalated and escalated[0]["delivered"] is True, out
    assert len(pages) == 1, pages
    assert inc2["id"] not in [s["id"] for s in out["skipped"]
                              if s.get("why") == "deferred: cycle budget"], out
    assert L.load_records(ledger)[inc2["id"]]["status"] == "blocked"
