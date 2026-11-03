"""A dispatch that ran no work must not hide an incident from a person.

The fixer exits 0 for "not armed", "busy" and "nothing to do". Recording any of those as a healthy
fix job let a later cycle suppress paging for ``fixer_active_hours`` (12h) with no job running.

The contract (2026-11-03 reviews):
* proof is scoped to the incident: the factory reads the request file's ``code_defect.defect_id``;
  a job belongs to this request only when an ``admitted[]`` row carries that defect_id;
* only that job's ``attempted`` outcome in the POSITIVE working-state set proves work
  (fixing / fix_ready_local / fix_pr_opened / fix_deployed / output_recovered / incident_resolved);
  ``not_armed:``, ``no_backend:``, ``no_rails:``, ``not_claimed:``, ``dry_run_planned``,
  ``fix_failed``, ``fix_refused`` and ``fix_interrupted`` are NOT work;
* at the code_defect site a no-work or failed dispatch is BLOCKED and ESCALATED on the same cycle;
* a fresh proven-ok dispatch suppresses; a failed one pages; a reopen starts a new episode and may
  dispatch again; an undelivered page retries; a different reason class still pages.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from lib import incident_supervisor as S  # noqa: E402
from lib import incidents as L  # noqa: E402

T0 = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
VERDICT = {"class": "code_defect", "action": "fix the defect in the named function",
           "params": {}, "rationale": "the evidence names a code defect"}

POSITIVE = ("fixing", "fix_ready_local", "fix_pr_opened", "fix_deployed",
            "output_recovered", "incident_resolved")
NEGATIVE = ("not_armed:no active grant", "no_backend:none installed", "no_rails:AGENTS rails missing",
            "not_claimed:another cycle owns the lane", "dry_run_planned",
            "fix_failed", "fix_refused", "fix_interrupted")


# ---------------------------------------------------------------- the real factory's reading
def _request(defect_id: str, *, episode: int = 1, incident_key: str = "INC-test") -> dict:
    return {"_why": "test dispatch",
            "code_defect": {"schema": "N8nCodeDefect@v1", "consumer": "claude_code_iterative_fix",
                            "consumer_status": "pending_consumer", "kind": "code_defect",
                            "defect_id": defect_id, "lane": "incident-x", "signature": "sig-0123456789",
                            "episode": episode, "failure_class": "code_error",
                            "failure_kind": "code_error:incident",
                            "evidence": {"incident_key": incident_key}}}


def _factory(tmp_path, *, defect_id="cd-incident", stdout=None, report=None, rc=0):
    """Run the REAL default_fixer_factory against one request file and one fixer stdout."""
    req = tmp_path / "request.json"
    req.write_text(json.dumps(_request(defect_id)))
    payload = stdout if stdout is not None else json.dumps(report)

    class P:
        returncode = rc

        def __init__(self):
            self.stdout, self.stderr = payload, ""

    class SP:
        TimeoutExpired = S.subprocess.TimeoutExpired

        @staticmethod
        def run(*_a, **_k):
            return P()

    real = S.subprocess
    S.subprocess = SP
    try:
        fx = S.default_fixer_factory(
            {"policy": {"fixer": {"script": "scripts/self_heal_fixer.py", "timeout_s": 60}}}, "python", ROOT)
        return fx(req, True)
    finally:
        S.subprocess = real


def _report(defect_id, *, job_id="shf-1", outcome="fix_ready_local", admitted_defect=None,
            admitted=True, busy=False):
    doc = {"mode": "apply", "busy": busy}
    doc["admitted"] = ([{"job_id": job_id, "lane": "incident-x", "state": "fix_requested",
                         "defect_id": admitted_defect if admitted_defect is not None else defect_id}]
                       if admitted else [])
    doc["attempted"] = [{"job_id": job_id, "outcome": outcome}] if admitted else []
    return doc


def test_a_job_for_a_different_defect_is_not_this_requests_work(tmp_path):
    """The fixer's queue is global and oldest-first: another incident's job must never prove work."""
    res = _factory(tmp_path, defect_id="cd-mine",
                   report=_report("cd-other", admitted_defect="cd-other", outcome="fix_ready_local"))
    assert res["work_proven"] is False and S._dispatch_ok(res) is False


@pytest.mark.parametrize("outcome", POSITIVE)
def test_this_requests_job_with_a_working_outcome_proves_work(tmp_path, outcome):
    res = _factory(tmp_path, defect_id="cd-mine", report=_report("cd-mine", outcome=outcome))
    assert res["rc"] == 0
    assert res["work_proven"] is True, res
    assert S._dispatch_ok(res) is True


@pytest.mark.parametrize("outcome", NEGATIVE)
def test_a_refusal_or_terminal_failure_is_not_work(tmp_path, outcome):
    res = _factory(tmp_path, defect_id="cd-mine", report=_report("cd-mine", outcome=outcome))
    assert res["work_proven"] is False, res
    assert S._dispatch_ok(res) is False


def test_a_matching_admission_without_an_attempt_is_not_work(tmp_path):
    """Admission happens before arming; a crash or refusal before the attempt must page, not hide."""
    res = _factory(tmp_path, defect_id="cd-mine", report=_report("cd-mine", admitted=True, outcome=""))
    # an empty outcome is not in the positive set
    assert res["work_proven"] is False


def test_a_positive_outcome_from_a_job_not_admitted_for_this_request_is_not_work(tmp_path):
    doc = {"mode": "apply",
           "admitted": [{"job_id": "j-mine", "defect_id": "cd-mine", "lane": "incident-x"},
                        {"job_id": "j-other", "defect_id": "cd-other", "lane": "incident-y"}],
           "attempted": [{"job_id": "j-mine", "outcome": "fix_failed"},
                         {"job_id": "j-other", "outcome": "fix_ready_local"}]}
    res = _factory(tmp_path, defect_id="cd-mine", report=doc)
    assert res["work_proven"] is False, res


def test_a_busy_cycle_is_not_work_even_though_it_exits_zero(tmp_path):
    res = _factory(tmp_path, defect_id="cd-mine", report=_report("cd-mine", busy=True))
    assert res["work_proven"] is False and S._dispatch_ok(res) is False


def test_a_nonzero_exit_is_never_work(tmp_path):
    res = _factory(tmp_path, defect_id="cd-mine", report=_report("cd-mine", outcome="fix_ready_local"), rc=1)
    assert res["rc"] == 1 and S._dispatch_ok(res) is False


def test_malformed_report_rows_do_not_crash_the_factory(tmp_path):
    res = _factory(tmp_path, defect_id="cd-mine",
                   report={"mode": "apply", "admitted": "shf-1",
                           "attempted": ["x", None, {"job_id": 7, "outcome": "fix_ready_local"}],
                           "skipped": ["x", None]})
    assert res["work_proven"] is False


def test_unparseable_output_is_not_work(tmp_path):
    res = _factory(tmp_path, defect_id="cd-mine", stdout="not json at all")
    assert res["work_proven"] is False and S._dispatch_ok(res) is False


# ---------------------------------------------------------------- end to end: the REAL report shape
class _FixerProcess:
    """Stands in for the fixer subprocess. It echoes the request it was given, like the real fixer."""

    TimeoutExpired = S.subprocess.TimeoutExpired

    def __init__(self, report_fn, *, rc=0):
        self.report_fn = report_fn
        self.rc = rc
        self.requests: list[dict] = []

    def run(self, argv, **_kw):
        req = Path(argv[argv.index("--incident") + 1]) if "--incident" in argv else None
        self.requests.append(json.loads(req.read_text()) if req and req.exists() else {})
        payload = json.dumps(self.report_fn(req))

        class P:
            returncode = self.rc
            stdout = payload
            stderr = ""

        return P()


def _report_shape(req, *, outcome="fix_ready_local", escalate_first_episode=False):
    """The REAL fixer report: admitted rows carry defect_id; attempted rows carry job_id + outcome."""
    doc = json.loads(Path(req).read_text())
    cd = doc["code_defect"]
    episode = int(cd.get("episode") or 1)
    job_id = f"shf-episode-{episode}"
    use = "not_armed:no active git-push guard grant" if (escalate_first_episode and episode == 1) else outcome
    return {"mode": "apply",
            "admitted": [{"job_id": job_id, "lane": cd["lane"], "state": "fix_requested",
                          "defect_id": cd["defect_id"]}],
            "attempted": [{"job_id": job_id, "outcome": use}]}


def _setup(tmp_path, monkeypatch):
    from lib import incidents as L
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))
    cfg = json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text())
    rec, created = L.open_incident(
        source={"kind": "watcher", "watcher": "health_tick", "job": "fixture-step"},
        title="health tick step fixture-step failed (rc=2)", d=tmp_path / "ledger", now=T0)
    assert created
    return cfg, rec


def _model(_prompt):
    return (json.dumps(VERDICT), "anthropic")


def _deps(fixer, *, model=_model, notify=True):
    pages: list[str] = []

    def _notify(text, _producer):
        pages.append(text)
        return notify(text) if callable(notify) else bool(notify)

    return S.Deps(model=model, run=lambda *_a, **_k: (0, "ok"), notify=_notify, fixer=fixer), pages


def _cycle(tmp_path, cfg, deps, now):
    return S.cycle(d=tmp_path / "ledger", state_root=tmp_path / "state", release_root=ROOT, cfg=cfg,
                   deps=deps, apply=True, now=now, environ={"HOME": "/h", "PATH": "/bin"}, root=ROOT)


def _factory_for(cfg):
    return S.default_fixer_factory(cfg, "python", ROOT)


def _escalations(row):
    return row.get("escalations") or []


def test_a_code_defect_dispatch_that_did_no_work_blocks_and_pages_on_the_same_cycle(tmp_path, monkeypatch):
    """Revert the block/page at the code_defect site -> blocked/escalated empty, status stays fixing."""
    cfg, rec = _setup(tmp_path, monkeypatch)
    fake = _FixerProcess(lambda req: _report_shape(req, escalate_first_episode=True))
    monkeypatch.setattr(S, "subprocess", fake)
    deps, pages = _deps(_factory_for(cfg))
    out = _cycle(tmp_path, cfg, deps, T0)

    assert fake.requests and fake.requests[0]["code_defect"]["episode"] == 1
    assert rec["id"] in [b["id"] for b in out["blocked"]], out
    esc = [e for e in out["escalated"] if e["id"] == rec["id"]]
    assert esc and esc[-1]["delivered"] is True, out
    assert pages and rec["id"] in pages[-1]
    row = L.load_records(tmp_path / "ledger")[rec["id"]]
    assert row["status"] == "blocked"
    dispatch = [a for a in row["attempts"] if a.get("action") == "fixer_dispatch"]
    assert dispatch and dispatch[-1].get("ok") is False, dispatch
    assert any(e.get("delivered") is True for e in _escalations(row))


def test_a_failed_dispatch_pages_a_person(tmp_path, monkeypatch):
    """rc != 0 is never work: record the failed dispatch, block and page in the same cycle."""
    cfg, rec = _setup(tmp_path, monkeypatch)
    fake = _FixerProcess(lambda req: _report_shape(req, outcome="fix_ready_local"), rc=2)
    monkeypatch.setattr(S, "subprocess", fake)
    deps, pages = _deps(_factory_for(cfg))
    out = _cycle(tmp_path, cfg, deps, T0)

    assert any(d["id"] == rec["id"] and d["rc"] == 2 for d in out["dispatched"]), out
    assert rec["id"] in [b["id"] for b in out["blocked"]], out
    esc = [e for e in out["escalated"] if e["id"] == rec["id"]]
    assert esc and esc[-1]["delivered"] is True, out
    assert pages
    row = L.load_records(tmp_path / "ledger")[rec["id"]]
    assert row["status"] == "blocked"
    dispatch = [a for a in row["attempts"] if a.get("action") == "fixer_dispatch"]
    assert dispatch and dispatch[-1].get("ok") is False
    m = re.search(r"rc=(-?\d+)", dispatch[-1].get("result") or "")
    assert m and int(m.group(1)) != 0, dispatch[-1]


def test_a_fresh_working_dispatch_suppresses_paging_on_the_next_cycle(tmp_path, monkeypatch):
    """31 min is past the 30-min model cooldown but inside the 12h fixer window: only the fresh-ok
    dispatch guard can prevent a block/page here."""
    cfg, rec = _setup(tmp_path, monkeypatch)
    fake = _FixerProcess(lambda req: _report_shape(req, outcome="fix_ready_local"))
    monkeypatch.setattr(S, "subprocess", fake)
    deps, pages = _deps(_factory_for(cfg))
    out1 = _cycle(tmp_path, cfg, deps, T0)
    assert not out1["blocked"] and not out1["escalated"], out1
    assert fake.requests and fake.requests[0]["code_defect"]["episode"] == 1

    calls = {"n": 0}

    def model(_p):
        calls["n"] += 1
        return (json.dumps(VERDICT), "anthropic")

    deps2, pages2 = _deps(_factory_for(cfg), model=model)
    out2 = _cycle(tmp_path, cfg, deps2, T0 + timedelta(minutes=31))
    assert not out2["blocked"], out2
    assert not out2["escalated"], out2
    assert not pages2, "a fresh proven-ok dispatch must not page"
    assert [s for s in out2["skipped"] if s["id"] == rec["id"]], out2
    assert len(fake.requests) == 1, "a fresh dispatch must not be re-dispatched"
    assert L.load_records(tmp_path / "ledger")[rec["id"]]["status"] != "blocked"


def test_a_reopened_incident_can_dispatch_again_in_a_new_episode(tmp_path, monkeypatch):
    """A transient refusal must not be permanent: a reopen starts episode 2, and the request must carry
    a new defect_id (the fixer keeps one job per defect_id forever)."""
    cfg, rec = _setup(tmp_path, monkeypatch)
    fake = _FixerProcess(lambda req: _report_shape(req, escalate_first_episode=True))
    monkeypatch.setattr(S, "subprocess", fake)
    deps, _ = _deps(_factory_for(cfg))
    out1 = _cycle(tmp_path, cfg, deps, T0)
    assert rec["id"] in [b["id"] for b in out1["blocked"]], out1

    L.append_event({"kind": "reopen", "incident_id": rec["id"], "actor": "operator",
                    "detail": {"evidence": "condition still failing: operator approved a retry"}},
                   d=tmp_path / "ledger", now=T0 + timedelta(minutes=1))
    assert L.load_records(tmp_path / "ledger")[rec["id"]]["episode"] == 2

    deps2, _ = _deps(_factory_for(cfg))
    out2 = _cycle(tmp_path, cfg, deps2, T0 + timedelta(minutes=31))
    assert [d for d in out2["dispatched"] if d["id"] == rec["id"]], out2
    assert len(fake.requests) == 2, fake.requests
    assert fake.requests[1]["code_defect"]["episode"] == 2
    assert fake.requests[1]["code_defect"]["defect_id"] != fake.requests[0]["code_defect"]["defect_id"]
    row = L.load_records(tmp_path / "ledger")[rec["id"]]
    dispatch = [a for a in row["attempts"] if a.get("action") == "fixer_dispatch"]
    assert len(dispatch) == 2 and dispatch[-1].get("ok") is True, dispatch


def test_a_failed_page_is_retried_on_the_next_cycle(tmp_path, monkeypatch):
    """A send that returned delivered=False must not suppress every future page (once-per-incident is
    only once per DELIVERED reason class)."""
    cfg, rec = _setup(tmp_path, monkeypatch)
    fake = _FixerProcess(lambda req: _report_shape(req))
    monkeypatch.setattr(S, "subprocess", fake)
    deliveries = [False, True]

    def notify(_text):
        return deliveries[min(len(pages_seen), 1)]

    pages_seen: list[str] = []

    def _notify(text, _producer):
        pages_seen.append(text)
        return deliveries[len(pages_seen) - 1]

    def no_model(_p):
        raise RuntimeError("model unavailable")

    deps = S.Deps(model=no_model, run=lambda *_a, **_k: (0, "ok"), notify=_notify, fixer=_factory_for(cfg))
    out1 = _cycle(tmp_path, cfg, deps, T0 + timedelta(minutes=61))
    first = [e for e in out1["escalated"] if e["id"] == rec["id"]]
    assert first and first[-1]["delivered"] is False, out1

    deps2 = S.Deps(model=no_model, run=lambda *_a, **_k: (0, "ok"), notify=_notify, fixer=_factory_for(cfg))
    out2 = _cycle(tmp_path, cfg, deps2, T0 + timedelta(minutes=92))
    second = [e for e in out2["escalated"] if e["id"] == rec["id"]]
    assert second and second[-1]["delivered"] is True, out2
    assert len(pages_seen) == 2, pages_seen
    row = L.load_records(tmp_path / "ledger")[rec["id"]]
    assert [e["delivered"] for e in _escalations(row)] == [False, True], _escalations(row)


def test_the_cap_page_fires_after_a_time_box_escalation_with_a_different_reason(tmp_path, monkeypatch):
    """The once-per-incident guard used to swallow the cap page because the 60-min time box always
    recorded its escalation first. A different reason class must still page."""
    cfg, rec = _setup(tmp_path, monkeypatch)
    ledger = tmp_path / "ledger"
    for k in range(3):
        L.attempt(rec["id"], actor=S.ACTOR, action="cron_self_heal", result="rc=0", ok=True,
                  detail={"no_op": True}, d=ledger, now=T0 + timedelta(minutes=k + 1))
    # a prior fixer dispatch that proved no work keeps the cap on the person path
    L.attempt(rec["id"], actor=S.ACTOR, action="fixer_dispatch", result="fixer rc=0", ok=False,
              detail={"provider": "code_defect"}, d=ledger, now=T0 + timedelta(minutes=5))
    L.escalate(rec["id"], actor=S.ACTOR, reason="unresolved 61 min", delivered=True, key="time_box",
               d=ledger, now=T0 + timedelta(minutes=61))

    pages: list[str] = []

    def _notify(text, _producer):
        pages.append(text)
        return True

    deps = S.Deps(model=lambda _p: (_ for _ in ()).throw(AssertionError("no model call at the cap")),
                  run=lambda *_a, **_k: (0, "ok"), notify=_notify, fixer=_factory_for(cfg))
    out = _cycle(tmp_path, cfg, deps, T0 + timedelta(hours=3))

    assert rec["id"] in [b["id"] for b in out["blocked"]], out
    esc = [e for e in out["escalated"] if e["id"] == rec["id"]]
    assert esc and esc[-1]["delivered"] is True, out
    assert pages, "the cap page must actually send"
    row = L.load_records(ledger)[rec["id"]]
    reasons = [e.get("reason") for e in _escalations(row)]
    assert len(reasons) >= 2 and reasons[-1] != "unresolved 61 min", reasons
    assert row["status"] == "blocked"


# ---------------------------------------------------------------- non-UTF8 robustness (contract B)
def test_a_non_utf8_fixer_report_is_a_failed_dispatch_and_pages(tmp_path, monkeypatch):
    """A byte the report cannot decode is not a healthy report. S.cycle must not raise; the dispatch is
    recorded as failed (rc != 0) and the incident is blocked and paged.

    The report otherwise names THIS request's defect with a positive outcome, so the invalid byte is the
    only reason to distrust it: decoding with replacement and then believing the outcome would record a
    12h "fixer active" suppression for a job whose report was corrupt.
    """
    cfg, rec = _setup(tmp_path, monkeypatch)
    script = tmp_path / "emit_bad_bytes.py"
    script.write_text(
        "import json, sys\n"
        "req = json.load(open(sys.argv[sys.argv.index('--incident') + 1]))\n"
        "cd = req['code_defect']\n"
        "doc = {'mode': 'apply', 'note': '',\n"
        "       'admitted': [{'job_id': 'shf-1', 'defect_id': cd['defect_id'],\n"
        "                     'lane': cd['lane'], 'state': 'fix_requested'}],\n"
        "       'attempted': [{'job_id': 'shf-1', 'outcome': 'fix_ready_local'}]}\n"
        "raw = json.dumps(doc).encode()\n"
        "raw = raw.replace(b'\"note\": \"\"', b'\"note\": \"\\xff\"')\n"
        "assert b'\\xff' in raw\n"
        "sys.stdout.buffer.write(raw + b'\\n')\n"
        "sys.stdout.buffer.flush()\n")
    cfg = {**cfg, "policy": {**cfg["policy"],
                             "fixer": {**cfg["policy"]["fixer"], "script": str(script)}}}
    deps, pages = _deps(S.default_fixer_factory(cfg, sys.executable, ROOT))

    out = _cycle(tmp_path, cfg, deps, T0)       # must not raise

    assert rec["id"] in [b["id"] for b in out["blocked"]], out
    esc = [e for e in out["escalated"] if e["id"] == rec["id"]]
    assert esc and esc[-1]["delivered"] is True, out
    assert pages
    row = L.load_records(tmp_path / "ledger")[rec["id"]]
    dispatch = [a for a in row["attempts"] if a.get("action") == "fixer_dispatch"]
    assert dispatch and dispatch[-1].get("ok") is False, dispatch
    m = re.search(r"rc=(-?\d+)", dispatch[-1].get("result") or "")
    assert m and int(m.group(1)) != 0, dispatch[-1]


# ---------------------------------------------------------------- repaired state machine (2026-11-03)
def test_the_incident_rails_and_their_gate_tests_are_refused_by_the_fixers_diff_guard():
    """The fixer's own guard must refuse the incident rails and the tests that gate them.

    Same shape as the launcher guard test (test_self_heal_deepseek_wiring_20261103): prove the MATCHER
    refuses each path, not merely that the string sits in a config list.
    """
    from lib import self_heal_fixer as F
    cfg = json.loads((ROOT / "config" / "self_heal_fixer.json").read_text())
    for rel in ("scripts/incident_requeue.py",
                "scripts/lib/incident_supervisor.py",
                "tests/test_incident_requeue_20261103.py",
                "tests/test_incident_dispatch_evidence_20261103.py",
                "tests/test_incident_supervisor_noop_evidence_20261103.py"):
        assert F._match_any(rel, cfg["diff_guard"]["refuse_paths"]) is not None, rel
    for rel in ("scripts/incident_requeue.py", "scripts/lib/incident_supervisor.py"):
        why = F.lane_refusal("any-lane", rel, cfg)
        assert why and why.startswith("lane_refused:protected_script:"), why


def test_an_episode_that_delivered_the_same_key_does_not_suppress_the_next_episode(tmp_path, monkeypatch):
    """Escalation dedupe is episode-scoped: episode 1 delivered, reopen, episode 2 fails -> page again.

    Revert ``_current_escalations`` to return every escalation -> no episode-2 page and the test fails.
    """
    cfg, rec = _setup(tmp_path, monkeypatch)
    fake = _FixerProcess(lambda req: _report_shape(req, outcome="not_armed:no active grant"))
    monkeypatch.setattr(S, "subprocess", fake)
    deps1, pages1 = _deps(_factory_for(cfg))
    out1 = _cycle(tmp_path, cfg, deps1, T0)

    assert rec["id"] in [b["id"] for b in out1["blocked"]], out1
    first = [e for e in out1["escalated"] if e["id"] == rec["id"]]
    assert first and first[-1]["delivered"] is True, out1
    assert len(pages1) == 1, pages1

    L.append_event({"kind": "reopen", "incident_id": rec["id"], "actor": "operator",
                    "detail": {"evidence": "the same fault recurred; a person approved one retry"}},
                   d=tmp_path / "ledger", now=T0 + timedelta(minutes=1))
    assert L.load_records(tmp_path / "ledger")[rec["id"]]["episode"] == 2

    deps2, pages2 = _deps(_factory_for(cfg))
    out2 = _cycle(tmp_path, cfg, deps2, T0 + timedelta(minutes=31))

    second = [e for e in out2["escalated"] if e["id"] == rec["id"]]
    assert second and second[-1]["delivered"] is True, out2
    assert len(pages2) == 1, "episode 2 must send its own page"
    assert [r["code_defect"]["episode"] for r in fake.requests] == [1, 2], fake.requests
    esc = L.load_records(tmp_path / "ledger")[rec["id"]]["escalations"]
    assert [e["delivered"] for e in esc] == [True, True], esc
    # the SAME reason class: only episode scoping can distinguish them
    assert esc[0]["key"] == esc[1]["key"] == "fixer_dispatch_failed", esc


def test_a_blocked_incident_retries_only_an_undelivered_page(tmp_path, monkeypatch):
    """A blocked incident whose last page was not delivered gets the send retried, nothing else.

    Revert the delivery-only ``retries`` loop -> no second send and the test fails.
    """
    cfg, rec = _setup(tmp_path, monkeypatch)
    fake = _FixerProcess(lambda req: _report_shape(req, outcome="not_armed:no active grant"))
    monkeypatch.setattr(S, "subprocess", fake)
    deps1, pages1 = _deps(_factory_for(cfg), notify=False)
    out1 = _cycle(tmp_path, cfg, deps1, T0)

    assert rec["id"] in [b["id"] for b in out1["blocked"]], out1
    assert len(pages1) == 1
    row = L.load_records(tmp_path / "ledger")[rec["id"]]
    assert row["status"] == "blocked"
    assert [e["delivered"] for e in _escalations(row)] == [False], _escalations(row)
    dispatched_before = len(fake.requests)

    model_calls = {"n": 0}

    def no_model(_p):
        model_calls["n"] += 1
        raise AssertionError("a delivery retry must not re-run the model")

    deps2, pages2 = _deps(_factory_for(cfg), model=no_model)
    out2 = _cycle(tmp_path, cfg, deps2, T0 + timedelta(minutes=1))

    assert len(pages2) == 1, "the undelivered page is attempted again"
    assert rec["id"] in [e["id"] for e in out2["escalated"]], out2
    assert out2["escalated"][-1]["delivered"] is True, out2
    assert model_calls["n"] == 0, "the retry must not re-triage"
    assert len(fake.requests) == dispatched_before, "the retry must not re-dispatch"
    row = L.load_records(tmp_path / "ledger")[rec["id"]]
    assert row["status"] == "blocked", "a delivery retry does not change the incident's state"
    assert [e["delivered"] for e in _escalations(row)] == [False, True], _escalations(row)

    deps3, pages3 = _deps(_factory_for(cfg), model=no_model)
    _cycle(tmp_path, cfg, deps3, T0 + timedelta(minutes=2))
    assert pages3 == [], "once delivered, there is nothing to retry"
    assert model_calls["n"] == 0


def _open_budget_incidents(tmp_path, n, *, tag="budget"):
    recs = []
    for i in range(n):
        rec, created = L.open_incident(
            source={"kind": "watcher", "watcher": "health_tick", "job": f"{tag}-step-{i}"},
            title=f"health tick step {tag}-step-{i} failed (rc=2)",
            fingerprint=f"fp-{tag}-{i}", d=tmp_path / "ledger", now=T0)
        assert created
        recs.append(rec)
    return recs


def test_a_small_cycle_budget_defers_the_overflow_and_drains_it_next_cycle(tmp_path, monkeypatch):
    """The cycle budget dispatches what fits, defers the rest, and preserves the queue.

    Revert the budget check (always return the fixer timeout) -> every incident dispatches, nothing
    is deferred, and the timeout/budget assertions fail.
    """
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))
    cfg = json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text())
    budget_s = 2.0
    cfg["policy"]["cycle_budget_s"] = budget_s
    cfg["policy"]["cycle_budget_margin_s"] = 0.0
    cfg["policy"]["cycle_budget_floor_s"] = 0.2
    cfg["policy"]["fixer"]["timeout_s"] = 100.0
    recs = _open_budget_incidents(tmp_path, 3)

    dispatch_calls: list[dict] = []

    def slow_fixer(req, apply, timeout=None):
        doc = json.loads(Path(req).read_text())
        dispatch_calls.append({"id": doc["code_defect"]["evidence"]["incident_key"],
                               "at": time.monotonic(), "timeout": timeout})
        time.sleep(1.0)  # consume most of the cycle budget
        return {"rc": 0, "work_proven": True, "admitted": ["shf-budget"], "prs": [], "summary": "ok"}

    started = time.monotonic()
    deps1 = S.Deps(model=_model, run=lambda *_a, **_k: (0, "ok"),
                   notify=lambda *_a, **_k: True, fixer=slow_fixer)
    out1 = _cycle(tmp_path, cfg, deps1, T0 + timedelta(minutes=1))
    elapsed = time.monotonic() - started

    dispatched = {d["id"] for d in out1["dispatched"]}
    deferred = {s["id"] for s in out1["skipped"] if s.get("why") == "deferred: cycle budget"}
    assert dispatched, out1
    assert deferred, out1
    assert dispatched.isdisjoint(deferred), out1
    assert dispatched | deferred == {r["id"] for r in recs}, out1
    assert recs[-1]["id"] in deferred, out1
    # every dispatch receives a timeout bounded by what is left of the cycle budget
    assert len(dispatch_calls) == len(dispatched)
    for call in dispatch_calls:
        assert call["timeout"] is not None, call
        assert 0 < call["timeout"] <= budget_s, call
        assert call["timeout"] <= budget_s - (call["at"] - started) + 0.1, call
    # the cycle itself stays inside the budget (the fixer honours its own timeout in production)
    assert elapsed <= budget_s + 0.6, elapsed

    # Queue-drain preserved: the deferred incidents are still unresolved and dispatch next cycle.
    second_calls: list[str] = []

    def fast_fixer(req, apply, timeout=None):
        doc = json.loads(Path(req).read_text())
        second_calls.append(doc["code_defect"]["evidence"]["incident_key"])
        return {"rc": 0, "work_proven": True, "admitted": ["shf-next"], "prs": [], "summary": "ok"}

    deps2 = S.Deps(model=_model, run=lambda *_a, **_k: (0, "ok"),
                   notify=lambda *_a, **_k: True, fixer=fast_fixer)
    out2 = _cycle(tmp_path, cfg, deps2, T0 + timedelta(minutes=32))

    assert set(second_calls) == deferred, (second_calls, deferred)
    assert {d["id"] for d in out2["dispatched"]} == deferred, out2
    rows = L.load_records(tmp_path / "ledger")
    for iid in deferred:
        assert rows[iid]["status"] in L.UNRESOLVED, rows[iid]["status"]
