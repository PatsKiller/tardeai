"""A disk incident is dispatched to the fixer, never parked as needs_operator (operator 2026-11-03, item 4).

Operator: "The incident supervisor must never park a disk incident as 'needs a person'; it dispatches the fixer."
The incident that prompted it — INC-261103-jngkrp, source ``{watcher: lane_health, job: disk-hygiene}`` — was triaged
by the model as ``needs_operator`` at 05:52Z, blocked, and never revisited until 14:05Z. The route added here is
deterministic and runs BEFORE the model, so no model answer can park a disk lane.

The route is deliberately narrow: it matches the structured source fields (job / lane / watcher) exactly, and it runs
AFTER the refused scopes, so §0 and §28.14 item 4 refusals still win.

Synthetic only: temp ledger, stubbed model / runner / notifier / fixer; nothing touches production state.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import incident_supervisor as S  # noqa: E402
from scripts.lib import incidents as L  # noqa: E402

T0 = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))


def _d(tmp_path) -> Path:
    return tmp_path / "ledger"


def _scfg() -> dict:
    return json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text(encoding="utf-8"))


class Stub:
    def __init__(self, answers=()):
        self.answers, self.prompts, self.runs, self.sent, self.fixes = list(answers), [], [], [], []

    def deps(self):
        def model(p):
            self.prompts.append(p)
            a = self.answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a

        def run(argv, cwd, env, timeout):
            self.runs.append((argv, cwd, env))
            return 0, "ok"

        def notify(text, producer):
            self.sent.append(text)
            return True

        def fixer(req, apply):
            self.fixes.append(json.loads(Path(req).read_text(encoding="utf-8")))
            return {"rc": 0, "admitted": ["shf-1"],
                    "prs": ["https://github.com/PatsKiller/tardeai/pull/9999"], "summary": "ok"}

        return S.Deps(model=model, run=run, notify=notify, fixer=fixer)


def _cycle(tmp_path, stub, *, now=T0, apply=True):
    return S.cycle(d=_d(tmp_path), state_root=tmp_path / "state", release_root=tmp_path, cfg=_scfg(),
                   deps=stub.deps(), apply=apply, now=now,
                   environ={"HOME": "/h", "PATH": "/bin", "ANTHROPIC_API_KEY": "nope"}, root=ROOT)


def _disk_inc(tmp_path, *, watcher="lane_health", job="disk-hygiene", title="cron/lane outage: disk-hygiene missed its schedule"):
    r, _ = L.open_incident(source={"kind": "watcher", "watcher": watcher, "job": job}, title=title,
                           d=_d(tmp_path), now=T0)
    return r


def _needs_operator():
    return (json.dumps({"class": "needs_operator", "action": "a person needs to inspect the crontab/lane state directly",
                        "rationale": "the lane did not run"}), "anthropic")


# ---------------------------------------------------------------- the route


def test_a_disk_lane_incident_is_dispatched_to_the_fixer_and_the_model_is_never_asked(tmp_path):
    rec = _disk_inc(tmp_path)
    stub = Stub([_needs_operator()])  # would have parked it; it must never be consulted
    out = _cycle(tmp_path, stub)

    assert stub.prompts == [], "the disk route is deterministic; the model must not classify it"
    assert len(stub.fixes) == 1, "a disk incident must reach the fixer"
    assert out["dispatched"], "the hardened code_defect branch dispatched"
    assert out["blocked"] == [], "a disk incident is never parked as needs_operator"
    assert not any(b.get("why") == "needs_operator" for b in out["blocked"])

    req = stub.fixes[0]
    assert req["code_defect"]["evidence"]["incident_key"] == rec["id"]
    assert req["code_defect"]["route"] == "fix_pr_release", "the fixer opens a PR; it never merges or deploys"


def test_the_incident_that_parked_for_eight_hours_would_now_be_dispatched(tmp_path):
    """INC-261103-jngkrp: watcher lane_health, job disk-hygiene — the exact shape the supervisor blocked at 05:52Z."""
    _disk_inc(tmp_path, watcher="lane_health", job="disk-hygiene")
    stub = Stub([_needs_operator()])
    out = _cycle(tmp_path, stub)
    assert len(stub.fixes) == 1 and out["blocked"] == []


def test_a_non_disk_incident_the_model_would_park_is_still_parked(tmp_path):
    """Negative control: the route is narrow. A lane_health incident from another job keeps the model's verdict."""
    r, _ = L.open_incident(source={"kind": "watcher", "watcher": "lane_health", "job": "fixture-step"},
                           title="health tick step fixture-step failed (rc=2)", d=_d(tmp_path), now=T0)
    stub = Stub([_needs_operator()])
    out = _cycle(tmp_path, stub)
    assert stub.prompts, "a non-disk incident is still triaged by the model"
    assert stub.fixes == [] and out["dispatched"] == []
    assert out["blocked"] and out["blocked"][0]["id"] == r["id"] and out["blocked"][0]["why"] == "needs_operator"


def test_the_route_matches_structured_source_fields_only(tmp_path):
    cfg = _scfg()
    assert S.disk_incident_route({"source": {"kind": "watcher", "watcher": "lane_health", "job": "disk-hygiene"}}, cfg)
    assert S.disk_incident_route({"source": {"kind": "watcher", "watcher": "disk_health"}}, cfg)
    # a title that merely mentions a disk, with no structured disk lane, is NOT routed
    assert S.disk_incident_route({"title": "disk almost full: disk-hygiene is slow",
                                  "source": {"kind": "watcher", "watcher": "lane_health", "job": "other"}}, cfg) is None
    assert S.disk_incident_route({"source": {"kind": "agent", "session": "s1"}}, cfg) is None


def test_the_fixer_is_dispatched_once_per_disk_incident(tmp_path):
    _disk_inc(tmp_path)
    stub = Stub([_needs_operator()])
    _cycle(tmp_path, stub)
    out2 = _cycle(tmp_path, stub, now=T0.replace(hour=7))
    assert len(stub.fixes) == 1, "the fixer is dispatched once per episode; the hardened branch owns the skip"


def test_a_dry_run_dispatches_nothing_and_writes_no_request(tmp_path):
    rec = _disk_inc(tmp_path)
    stub = Stub([_needs_operator()])
    out = _cycle(tmp_path, stub, apply=False)
    assert stub.fixes == [] and stub.prompts == []
    assert rec["id"] in out["considered"]
    assert not (_d(tmp_path) / "fixer_requests" / f"{rec['id']}.json").exists()


def test_refused_scopes_still_win_over_the_disk_route(tmp_path):
    """§28.14 item 4 / §0 rails are not weakened: a refused scope blocks before the route can dispatch."""
    r, _ = L.open_incident(source={"kind": "watcher", "watcher": "lane_health", "job": "disk-hygiene"},
                           title="disk-hygiene lane failed near the broker export", d=_d(tmp_path), now=T0)
    stub = Stub([_needs_operator()])
    out = _cycle(tmp_path, stub)
    assert stub.fixes == [], "a refused scope must not reach the fixer through the disk route"
    assert out["blocked"] and out["blocked"][0]["why"].startswith("refused_scope:")
    assert out["blocked"][0]["id"] == r["id"]


def test_a_guard_named_lane_is_still_refused_by_the_section_28_14_scope(tmp_path):
    """The disk route does not disarm the `guard` term; a guard job is refused, as before."""
    _disk_inc(tmp_path, job="disk-pressure-guard", title="disk pressure guard lane failed")
    stub = Stub([_needs_operator()])
    out = _cycle(tmp_path, stub)
    assert stub.fixes == []
    assert out["blocked"] and out["blocked"][0]["why"].startswith("refused_scope:")

def test_the_classification_happens_before_any_model_call(tmp_path):
    """The route must be deterministic and must precede build_prompt: a disk incident is never classified by a model."""
    _disk_inc(tmp_path)
    stub = Stub([])          # any model call would IndexError on the empty answer list
    out = _cycle(tmp_path, stub)
    assert stub.prompts == []
    assert not any(s.get("why", "").startswith("daily model-call cap") for s in out["skipped"])


def test_a_refused_dispatch_is_blocked_loudly_never_a_silent_no_op(tmp_path):
    """A failed fixer dispatch must end in a recorded, visible state, not "considered and forgotten"."""
    rec = _disk_inc(tmp_path)
    stub = Stub([_needs_operator()])
    shipped = stub.deps()

    def refusing_fixer(req, apply):
        return {"rc": 2, "admitted": [], "prs": [], "summary": "self-heal refused: dark stage"}

    from scripts.lib import incident_supervisor as S
    deps = S.Deps(model=shipped.model, run=shipped.run, notify=shipped.notify, fixer=refusing_fixer)
    out = S.cycle(d=_d(tmp_path), state_root=tmp_path / "state", release_root=tmp_path, cfg=_scfg(), deps=deps,
                  apply=True, now=T0, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)
    assert stub.prompts == [], "still no model call"
    assert any(b.get("id") == rec["id"] for b in out["blocked"]), out
    assert not any(s.get("id") == rec["id"] and s.get("why") == "dry_run" for s in out["skipped"])
