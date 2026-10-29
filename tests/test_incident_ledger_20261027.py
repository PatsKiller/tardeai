"""Incident ledger + watchers + supervisor + Ops API (operator 2026-10-27).

Synthetic only: every test uses a temp ledger (TRADEAI_INCIDENTS_DIR / explicit dirs), temp state roots and stubbed
model, runner, Telegram, fixer and gh/git. Nothing here touches production state (AGENTS.md §24.6) or imports psycopg2.
"""
from __future__ import annotations

# Alarm firing coverage (tests/test_alarm_coverage.py): the P1 and the daily brief are injected below and asserted to
# reach the Telegram chokepoint (scripts/telegram_alert.send_telegram, stubbed at the transport boundary).
COVERS = ["scripts/lib/incident_supervisor.py", "scripts/incident_daily_brief.py"]

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import incident_supervisor as S  # noqa: E402
from scripts.lib import incident_watchers as W  # noqa: E402
from scripts.lib import incidents as L  # noqa: E402
from scripts.lib import incidents_view as V  # noqa: E402

T0 = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_INCIDENTS_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))


def _d(tmp_path) -> Path:
    return tmp_path / "ledger"


def _open(d, title="boom", **kw):
    kw.setdefault("source", {"kind": "agent", "session": "s1"})
    return L.open_incident(title=title, d=d, now=kw.pop("now", T0), **kw)


# ---------------------------------------------------------------- ledger


def test_ids_survive_comms_editor_fingerprint_and_are_valid():
    from scripts.lib import comms_editor

    iid = L.make_id("fp-x", T0)
    assert L.valid_id(iid) and iid.startswith("INC-261027-")
    a, b = L.make_id("fp-a", T0), L.make_id("fp-b", T0)
    assert a != b
    # the 2026-10-26/27 trap: hex runs and timestamps are normalised away — incident ids are not
    assert comms_editor.fingerprint(f"[P1] Incident {a}: x") != comms_editor.fingerprint(f"[P1] Incident {b}: x")


def test_open_dedupes_by_fingerprint_and_fold_matches_index(tmp_path):
    d = _d(tmp_path)
    r1, c1 = _open(d, fingerprint="fp-1")
    r2, c2 = _open(d, fingerprint="fp-1", now=T0 + timedelta(minutes=5))
    assert c1 and not c2 and r1["id"] == r2["id"]
    idx = json.loads((d / "index.json").read_text())
    assert idx["schema"] == L.INDEX_SCHEMA and idx["summary"]["counts"]["open"] == 1
    assert idx == L.rebuild_index(d, now=L.parse_ts(idx["generated_at"]))


def test_lifecycle_attempt_fix_and_recurrence(tmp_path):
    d = _d(tmp_path)
    r, _ = _open(d, fingerprint="fp-2")
    r = L.attempt(r["id"], actor="s1", action="rerun", result="rc=1", ok=False, d=d, now=T0)
    assert r["status"] == "fixing" and r["attempts"][0]["action"] == "rerun"
    with pytest.raises(L.LedgerError):
        L.fix(r["id"], actor="s1", fix_refs=[], d=d)
    r = L.fix(r["id"], actor="s1", fix_refs=[L.parse_ref("#2232"), L.parse_ref("commit:abc1234")], d=d, now=T0)
    assert r["status"] == "fixed" and r["fix_refs"][0] == {"kind": "pr", "ref": "2232"}
    with pytest.raises(L.LedgerError):
        L.attempt(r["id"], actor="s1", action="x", result="y", d=d)
    r2, created = _open(d, fingerprint="fp-2", now=T0 + timedelta(hours=1))
    assert created and r2["recurrence_of"] == r["id"] and r2["id"] != r["id"]


def test_block_needs_handoff_and_events_append_only(tmp_path):
    d = _d(tmp_path)
    r, _ = _open(d)
    with pytest.raises(L.LedgerError):
        L.block(r["id"], actor="s1", blocked_reason="x", handoff="", d=d)
    L.block(r["id"], actor="s1", blocked_reason="needs grant", handoff="operator: grant X", d=d)
    before = (d / "events.jsonl").read_text()
    L.update(r["id"], actor="s1", note="still waiting", d=d)
    after = (d / "events.jsonl").read_text()
    assert after.startswith(before) and len(after.splitlines()) == len(before.splitlines()) + 1


def test_torn_tail_line_is_skipped_not_repaired(tmp_path):
    d = _d(tmp_path)
    _open(d)
    with open(d / "events.jsonl", "a") as fh:
        fh.write('{"schema": "IncidentEvent@v1", "kind": "op')
    assert len(L.load_records(d)) == 1


def test_cli_open_fix_list_and_check(tmp_path):
    env = {**os.environ, "TRADEAI_INCIDENTS_DIR": str(_d(tmp_path)), "AGENT_CLAIM_SESSION": "sess-x"}
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / a[0]), *a[1:]], capture_output=True,
                                    text=True, env=env, cwd=str(ROOT))
    out = run("incident.py", "open", "--title", "pytest failed in x", "--where", "tests/x.py", "--json")
    assert out.returncode == 0, out.stderr
    iid = json.loads(out.stdout)["id"]
    chk = run("check_open_incidents.py", "--session", "sess-x")
    assert chk.returncode == 1 and iid in chk.stdout
    assert run("check_open_incidents.py", "--session", "sess-x", "--warn-only").returncode == 0
    assert run("incident.py", "fix", iid, "--ref", "pr:1").returncode == 0
    assert run("check_open_incidents.py", "--session", "sess-x").returncode == 0
    lst = run("incident.py", "list", "--status", "all", "--json")
    assert json.loads(lst.stdout)[0]["status"] == "fixed"
    bad = run("incident.py", "fix", iid, "--ref", "nonsense")
    assert bad.returncode == 2


def test_seed_is_idempotent(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib

    cli = importlib.import_module("scripts.incident")
    doc = json.loads((ROOT / "config" / "incident_seed_20261027.json").read_text())
    d = _d(tmp_path)
    assert all(r["action"] == "would_seed" for r in cli.seed(doc, d, apply=False))
    rows = cli.seed(doc, d, apply=True)
    assert [r["status"] for r in rows] == ["fixed"] * 3
    recs = L.load_records(d)
    assert {r["fix_refs"][0]["ref"] for r in recs.values()} == {"2231", "2232"}
    assert all(r["action"] == "skip_existing" for r in cli.seed(doc, d, apply=True))


def test_seed_and_fixtures_carry_no_real_holdings():
    # public repo (2026-10-25): no tickers, quantities or account data in committed fixtures
    txt = (ROOT / "config" / "incident_seed_20261027.json").read_text()
    for word in ("shares", "account", "position", "NVDA", "TSLA", "$"):
        assert word not in txt


# ---------------------------------------------------------------- watchers


def _cfg():
    return json.loads((ROOT / "config" / "incident_watchers.json").read_text())


def _wr(tmp_path, cfg, *, now, gh=None, git=None, llm=None, apply=True, only=None):
    return W.run(state_root=tmp_path / "state", incidents_dir=_d(tmp_path), cfg=cfg, apply=apply, now=now,
                 gh=gh or (lambda a: (1, "no gh")), git=git or (lambda r, a: (0, "")), llm_queue=llm or (lambda: None),
                 only=only)


def _receipt(dirp: Path, stamp: str, outcome: str, main="a" * 40, cur="b" * 9, reason="deploy_rc=1"):
    dirp.mkdir(parents=True, exist_ok=True)
    t = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    (dirp / f"{stamp}_poller_{outcome}.json").write_text(json.dumps({
        "schema": "DeployOnMainReceipt@v1", "as_of": L.iso(t), "outcome": outcome, "reason": reason, "main_sha": main,
        "current_sha_before": cur, "detail": {"log_tail": "release grant expired"}}))


def test_deploy_failure_streak_opens_with_sha_and_auto_resolves(tmp_path):
    rd = tmp_path / "state" / "data/runtime/deploy_on_main"
    for i in range(3):
        _receipt(rd, f"20261027T13{i:02d}00Z", "deploy_failed")
    out = _wr(tmp_path, _cfg(), now=T0, only=["deploy_failures"])
    assert len(out["opened"]) == 1 and "aaaaaaaaaaaa" in out["opened"][0]["title"]
    # same streak next tick: no duplicate
    assert _wr(tmp_path, _cfg(), now=T0 + timedelta(minutes=5), only=["deploy_failures"])["opened"] == []
    _receipt(rd, "20261027T140500Z", "verified", cur="a" * 9)
    out = _wr(tmp_path, _cfg(), now=T0 + timedelta(minutes=10), only=["deploy_failures"])
    assert len(out["resolved"]) == 1
    rec = list(L.load_records(_d(tmp_path)).values())[0]
    assert rec["status"] == "fixed" and rec["resolution"] == "auto_resolved"


def test_deploy_stuck_after_30_min(tmp_path):
    rd = tmp_path / "state" / "data/runtime/deploy_on_main"
    _receipt(rd, "20261027T132000Z", "refuse", reason="global_release_lock_busy")
    _receipt(rd, "20261027T135800Z", "refuse", reason="global_release_lock_busy")
    out = _wr(tmp_path, _cfg(), now=T0, only=["deploy_stuck"])
    assert len(out["opened"]) == 1 and "not live after 40 min" in out["opened"][0]["title"]


def test_gap_resolves_nothing(tmp_path):
    rd = tmp_path / "state" / "data/runtime/deploy_on_main"
    for i in range(3):
        _receipt(rd, f"20261027T13{i:02d}00Z", "deploy_failed")
    _wr(tmp_path, _cfg(), now=T0, only=["deploy_failures"])
    for p in rd.iterdir():
        p.unlink()
    rd.rmdir()
    out = _wr(tmp_path, _cfg(), now=T0 + timedelta(minutes=5), only=["deploy_failures"])
    assert out["watchers"]["deploy_failures"]["gap"] and out["resolved"] == []


def test_dry_run_writes_nothing(tmp_path):
    rd = tmp_path / "state" / "data/runtime/deploy_on_main"
    for i in range(3):
        _receipt(rd, f"20261027T13{i:02d}00Z", "deploy_failed")
    out = _wr(tmp_path, _cfg(), now=T0, apply=False, only=["deploy_failures"])
    assert len(out["would_open"]) == 1 and not _d(tmp_path).exists()


def test_other_watchers(tmp_path):
    st = tmp_path / "state" / "data" / "runtime"
    st.mkdir(parents=True)
    (st / "health_tick_last.json").write_text(json.dumps({"as_of": L.iso(T0), "failed": ["fixture-step"], "broken": [],
                                                          "timed_out": [], "steps": [{"step_id": "fixture-step", "rc": 2}]}))
    (st / "expected_services_last_run.json").write_text(json.dumps({"ran_at": L.iso(T0), "off_items": ["MISSING:x.service"]}))
    (st / "research_lane_health.json").write_text(json.dumps({"as_of": L.iso(T0), "lanes": {"fixture-lane": {"ok": False, "firing": ["r1"]}, "ok-lane": {"ok": True}}}))
    q = tmp_path / "state" / "data" / "prospectus"
    q.mkdir(parents=True)
    (q / "queue.json").write_text(json.dumps({"items": [{"symbol": "ZZZ1", "state": "running", "started_at": L.iso(T0 - timedelta(hours=3))},
                                                        {"symbol": "ZZZ2", "state": "running", "started_at": L.iso(T0 - timedelta(minutes=5))}]}))
    pc = st / "provider_cost"
    pc.mkdir()
    pc.joinpath("anthropic_credit.jsonl").write_text("\n".join(json.dumps({"event": "fallback", "reason": "CREDIT_PROCESS_CAP",
                                                                           "at": L.iso(T0 - timedelta(minutes=i))}) for i in range(4)) + "\n")
    runs = [{"headSha": "c" * 40, "status": "completed", "conclusion": "failure", "workflowName": "ci-x", "url": "u",
             "createdAt": L.iso(T0), "event": "push"}]
    gh = lambda a: (0, json.dumps(runs))
    git_calls = []
    git = lambda repo, a: (git_calls.append(a) or (0, " M scripts/x.py\n"))
    cfg = _cfg()
    out = _wr(tmp_path, cfg, now=T0, gh=gh, git=git, llm=lambda: {"pending": 500})
    titles = " | ".join(r["title"] for r in out["opened"])
    for needle in ("fixture-step failed", "MISSING:x.service", "lane fixture-lane", "ZZZ1", "main CI red: ci-x",
                   "CREDIT_PROCESS_CAP x4", "LLM deferral backlog 500"):
        assert needle in titles, needle
    assert "ZZZ2" not in titles and "ok-lane" not in titles
    assert "canonical checkout dirty" not in titles  # first sighting only
    out = _wr(tmp_path, cfg, now=T0 + timedelta(minutes=31), gh=gh, git=git, llm=lambda: {"pending": 500},
              only=["dirty_checkout"])
    assert "canonical checkout dirty for 31 min" in out["opened"][0]["title"]
    assert all(c[0] == "status" for c in git_calls)


def test_default_gh_and_git_are_read_only():
    with pytest.raises(ValueError):
        W.default_gh(["pr", "merge", "1"])
    with pytest.raises(ValueError):
        W.default_gh(["api", "-X", "POST", "repos/x"])
    with pytest.raises(ValueError):
        W.default_git("/tmp", ["stash"])


# ---------------------------------------------------------------- supervisor


def _scfg():
    return json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text())


class Stub:
    def __init__(self, answers):
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
            self.fixes.append(json.loads(Path(req).read_text()))
            return {"rc": 0, "admitted": ["shf-1"], "prs": ["https://github.com/PatsKiller/tardeai/pull/9999"], "summary": "ok"}

        return S.Deps(model=model, run=run, notify=notify, fixer=fixer)


def _cycle(tmp_path, stub, *, now=T0, apply=True, environ=None):
    return S.cycle(d=_d(tmp_path), state_root=tmp_path / "state", release_root=tmp_path, cfg=_scfg(), deps=stub.deps(),
                   apply=apply, now=now, environ=environ or {"HOME": "/h", "PATH": "/bin", "ANTHROPIC_API_KEY": "nope"},
                   root=ROOT)


def _watch_inc(tmp_path, watcher="health_tick", title="health tick step fixture-step failed (rc=2)", job="fixture-step", now=T0):
    r, _ = L.open_incident(source={"kind": "watcher", "watcher": watcher, "job": job}, title=title, d=_d(tmp_path), now=now)
    return r


def test_runbook_action_runs_allowlisted_argv_with_scrubbed_env(tmp_path):
    r = _watch_inc(tmp_path)
    stub = Stub([(json.dumps({"class": "runbook", "action": "health_tick_step_once", "params": {"step": "fixture-step"},
                              "rationale": "flake"}), "anthropic")])
    out = _cycle(tmp_path, stub)
    assert out["actions"] == [{"id": r["id"], "action": "health_tick_step_once", "rc": 0}]
    argv, cwd, env = stub.runs[0]
    assert argv[-3:] == ["--once", "--step", "fixture-step"] and "ANTHROPIC_API_KEY" not in env
    rec = L.load_records(_d(tmp_path))[r["id"]]
    assert rec["status"] == "fixing" and rec["attempts"][0]["provider"] == "anthropic"
    assert "health_tick_step_once" in stub.prompts[0] and "RUNBOOKS" in stub.prompts[0]


@pytest.mark.parametrize("answer, why", [
    ({"class": "runbook", "action": "rm_rf_everything", "params": {}}, "not in the allowlist"),
    ({"class": "runbook", "action": "stale_lock_reconcile", "params": {}}, "disabled"),
    ({"class": "runbook", "action": "health_tick_step_once", "params": {"step": "x; rm -rf /"}}, "fails"),
    ({"class": "runbook", "action": "deploy_on_main_dry_run", "params": {}}, "does not apply"),
])
def test_model_cannot_widen_the_allowlist(tmp_path, answer, why):
    _watch_inc(tmp_path)
    stub = Stub([(json.dumps({**answer, "rationale": "r"}), "anthropic")])
    out = _cycle(tmp_path, stub)
    assert stub.runs == [] and why in out["skipped"][0]["why"]


def test_refused_scope_never_calls_model_and_escalates_once(tmp_path):
    r = _watch_inc(tmp_path, watcher="lane_health", title="lane broker-stop-reconcile unhealthy", job="broker-stop-reconcile")
    stub = Stub([])
    _cycle(tmp_path, stub)
    _cycle(tmp_path, stub, now=T0 + timedelta(hours=2))
    rec = L.load_records(_d(tmp_path))[r["id"]]
    assert stub.prompts == [] and rec["status"] == "blocked" and len(stub.sent) == 1
    assert r["id"] in stub.sent[0] and "refused scope" in stub.sent[0]


def test_code_defect_dispatches_fixer_once_with_contract(tmp_path):
    r = _watch_inc(tmp_path, watcher="main_ci", title="main CI red: ci-x failure on cccc", job="ci-x")
    stub = Stub([(json.dumps({"class": "code_defect", "action": "fix tests/test_x.py", "rationale": "assert"}), "anthropic"),
                 (json.dumps({"class": "code_defect", "action": "again", "rationale": "r"}), "anthropic")])
    _cycle(tmp_path, stub)
    _cycle(tmp_path, stub, now=T0 + timedelta(minutes=45))
    assert len(stub.fixes) == 1
    cd = stub.fixes[0]["code_defect"]
    assert cd["schema"] == "N8nCodeDefect@v1" and cd["consumer"] == "claude_code_iterative_fix" and cd["kind"] == "code_defect"
    assert cd["defect_id"] == f"cd-{r['id']}" and cd["lane"].startswith("incident-")
    rec = L.load_records(_d(tmp_path))[r["id"]]
    assert rec["fix_refs"] == [{"kind": "pr", "ref": "https://github.com/PatsKiller/tardeai/pull/9999"}]
    # the fixer's own intake accepts the request (its contract, its parser)
    from scripts.lib import self_heal_fixer as F
    fcfg = json.loads((ROOT / "config" / "self_heal_fixer.json").read_text())
    assert F.code_defects([stub.fixes[0]], None, fcfg)[0]["defect_id"] == cd["defect_id"]


def test_needs_operator_blocks_with_handoff_and_one_p1(tmp_path):
    r = _watch_inc(tmp_path, watcher="deploy_stuck", title="main aaaa not live after 40 min", job="deploy-on-main")
    stub = Stub([(json.dumps({"class": "needs_operator", "action": "operator: renew the deploy delegation", "rationale": "expired"}), "anthropic")])
    _cycle(tmp_path, stub)
    rec = L.load_records(_d(tmp_path))[r["id"]]
    assert rec["status"] == "blocked" and rec["handoff"] == "operator: renew the deploy delegation"
    assert len(stub.sent) == 1 and r["id"] in stub.sent[0] and "/v3/ops/incidents?detail=" in stub.sent[0]


def test_fallback_provider_is_read_only_and_deepseek_is_discarded(tmp_path):
    r = _watch_inc(tmp_path)
    ans = json.dumps({"class": "runbook", "action": "health_tick_step_once", "params": {"step": "fixture-step"}, "rationale": "r"})
    stub = Stub([(ans, "grok"), (ans, "deepseek")])
    _cycle(tmp_path, stub)
    _cycle(tmp_path, stub, now=T0 + timedelta(minutes=31))
    rec = L.load_records(_d(tmp_path))[r["id"]]
    assert stub.runs == [] and [a["action"] for a in rec["attempts"]] == ["triage_readonly", "triage"]
    assert "refused provider deepseek" in rec["attempts"][1]["result"]


def test_time_box_and_attempt_cap(tmp_path):
    r = _watch_inc(tmp_path, now=T0 - timedelta(minutes=61))
    ans = (json.dumps({"class": "runbook", "action": "cron_self_heal", "params": {}, "rationale": "r"}), "anthropic")
    stub = Stub([ans, ans, ans])
    for k in range(3):
        _cycle(tmp_path, stub, now=T0 + timedelta(minutes=31 * k))
    assert len(stub.sent) == 1 and "unresolved" in stub.sent[0]  # time box: once
    out = _cycle(tmp_path, stub, now=T0 + timedelta(hours=3))
    rec = L.load_records(_d(tmp_path))[r["id"]]
    assert rec["status"] == "blocked" and "max attempts" in rec["blocked_reason"] and len(stub.runs) == 3
    assert out["blocked"][0]["why"].startswith("max attempts") and len(stub.sent) == 1  # already escalated


def test_model_failure_and_dry_run(tmp_path):
    r = _watch_inc(tmp_path)
    stub = Stub([RuntimeError("CREDIT_PROCESS_CAP")])
    out = _cycle(tmp_path, stub, apply=False)
    assert stub.prompts == [] and "would call model" in out["skipped"][0]["why"]
    _cycle(tmp_path, stub)
    rec = L.load_records(_d(tmp_path))[r["id"]]
    assert "model unavailable" in rec["attempts"][0]["result"] and rec["status"] == "open"


def test_preserve_refuses_while_paths_are_fresh(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "x.py").write_text("x")
    cfg = {**_scfg(), "canonical_repo": str(repo)}
    rec = {"source": {"watcher": "dirty_checkout"}, "evidence": ["path:scripts/x.py"]}
    chosen, why = S.validate_action({"action": "preserve_dirty_checkout", "params": {}}, rec, cfg)
    assert chosen is None and "changed within 60 min" in why
    old = (T0 - timedelta(hours=3)).timestamp()
    os.utime(repo / "scripts" / "x.py", (old, old))
    chosen, why = S.validate_action({"action": "preserve_dirty_checkout", "params": {}}, rec, cfg)
    assert chosen and why == "ok"


def test_runbook_config_never_names_a_forbidden_tool():
    cfg = _scfg()
    joined = json.dumps([a.get("argv") for a in cfg["actions"].values()]).lower()
    for bad in ("merge", "push", "promote", "--apply\", \"--repo", "place_order", "rm -", "git reset", "release_window"):
        assert bad not in joined, bad
    assert "deepseek" in cfg["policy"]["never_providers"]


def test_process_registration_sonnet_dollar_cap_no_deepseek():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text())
    row = next(p for p in reg["processes"] if p["id"] == "incident_supervisor")
    assert row["daily_cost_cap_usd"] == 1.0 and row["anthropic_first"] is True and "deepseek" not in row["allowed_lanes"]
    pol = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text())
    prow = pol["policies"]["default"]["processes"]["incident_supervisor"]
    assert "deepseek" not in json.dumps(prow)
    credit = json.loads((ROOT / "config" / "anthropic_credit_policy.json").read_text())
    from scripts.lib import anthropic_routing
    tier = anthropic_routing.tier_for("FAST", process_id="incident_supervisor", policy=credit)
    assert credit["models"][tier] == "claude-sonnet-5-5" and credit["per_call_caps_usd"][tier]


# ---------------------------------------------------------------- API


class FakeLedger:
    def __init__(self):
        self.rows = []

    def incident_decision(self, actor, body):
        row = {"at": "2026-10-27T14:00:00Z", "hash_self": "h" * 64, "actor": actor, **body}
        self.rows.append(row)
        return row


def test_api_get_list_detail_and_operator_posts(tmp_path):
    d = _d(tmp_path)
    r, _ = _open(d, title="fixture incident")
    st, body = V.handle("/api/v2/ops/incidents", "GET", d=d)
    assert st == 200 and body["data"]["incidents"][0]["id"] == r["id"]
    st, body = V.handle(f"/api/v2/ops/incidents/{r['id']}", "GET", d=d)
    assert st == 200 and body["data"]["events"][0]["kind"] == "open"
    assert V.handle("/api/v2/ops/incidents/nope", "GET", d=d)[0] == 400
    assert V.handle("/api/v2/other", "GET", d=d) is None
    led = FakeLedger()
    agent = lambda: (None, lambda m, p: (True, ""), led)
    assert V.handle(f"/api/v2/ops/incidents/{r['id']}/ack", "POST", body={}, d=d, operator_ctx=agent)[1]["error"] == "AGENT_CALLER_REFUSED"
    nocsrf = lambda: ("tailnet:op", lambda m, p: (False, "x"), led)
    assert V.handle(f"/api/v2/ops/incidents/{r['id']}/ack", "POST", body={}, d=d, operator_ctx=nocsrf)[1]["error"] == "CSRF_REFUSED"
    op = lambda: ("tailnet:op", lambda m, p: (True, ""), led)
    st, body = V.handle(f"/api/v2/ops/incidents/{r['id']}/ack", "POST", body={"request_id": "req-12345678"}, d=d, operator_ctx=op)
    assert st == 200 and body["data"]["incident"]["acknowledged"]["decision_ref"].startswith("operator_decisions:")
    st, body = V.handle(f"/api/v2/ops/incidents/{r['id']}/close", "POST", body={"request_id": "req-22345678", "comment": "dup"},
                        d=d, operator_ctx=op)
    assert st == 200 and body["data"]["incident"]["status"] == "closed"
    assert [x["decision"] for x in led.rows] == ["ACKNOWLEDGE", "CLOSE_WONT_FIX"]
    assert V.handle(f"/api/v2/ops/incidents/{r['id']}/close", "POST", body={"request_id": "req-32345678", "comment": "x"},
                    d=d, operator_ctx=op)[0] == 409


def test_decision_ledger_incident_decision_gate_and_idempotency(tmp_path):
    from scripts.lib import operator_approvals as core

    blocked = core.DecisionLedger(tmp_path / "gov" / "operator_decisions.jsonl", approved=lambda: False)
    with pytest.raises(core.Refused) as e:
        blocked.incident_decision("tailnet:op", {"decision": "ACKNOWLEDGE", "incident_id": "INC-261027-kmpqrs", "request_id": "req-12345678"})
    assert e.value.code == "STORE_APPROVAL_PENDING"
    led = core.DecisionLedger(tmp_path / "gov" / "operator_decisions.jsonl", approved=lambda: True)
    body = {"decision": "CLOSE_WONT_FIX", "incident_id": "INC-261027-kmpqrs", "request_id": "req-12345678", "comment": "dup"}
    a = led.incident_decision("tailnet:op", body)
    assert led.incident_decision("tailnet:op", body) == a and a["effect"] == "RECORD_ONLY"
    with pytest.raises(core.Refused):
        led.incident_decision("tailnet:op", {**body, "comment": ""})
    with pytest.raises(core.Refused):
        led.incident_decision("tailnet:op", {**body, "incident_id": "INC-1"})
    assert len(led.rows()) == 1


def test_daily_brief_line_carries_date_and_link(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib

    brief = importlib.import_module("scripts.incident_daily_brief")
    d = _d(tmp_path)
    _open(d, title="fixture one", now=T0 - timedelta(hours=2))
    line = brief.brief_line(L.load_records(d), now=T0)
    assert line.startswith("Incidents Tue Oct 27: 1 open") and "2h00m" in line and "/v3/ops/incidents" in line


def test_units_are_host_timers_and_supervisor_has_no_merge_or_promote():
    units = ROOT / "config" / "systemd" / "incidents"
    names = sorted(p.name for p in units.iterdir())
    assert names == sorted(f"tradeai-incident-{n}.{k}" for n in ("watchers", "supervisor", "daily") for k in ("service", "timer"))
    assert "OnCalendar=*:0/5" in (units / "tradeai-incident-watchers.timer").read_text()
    assert "OnCalendar=*:2/10" in (units / "tradeai-incident-supervisor.timer").read_text()
    assert "08:00:00 America/New_York" in (units / "tradeai-incident-daily.timer").read_text()
    src = (ROOT / "scripts" / "lib" / "incident_supervisor.py").read_text()
    for bad in ('"merge"', "gh pr merge", "promote", "git push"):
        assert bad not in src.split('"""', 2)[-1], bad


# ---------------------------------------------------------------- alarm firing (chokepoint reached)


def _capture_send(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import scripts.telegram_alert as ta

    sent = []

    def fake_send(message, *a, **kw):
        sent.append({"message": message, **kw})
        return True

    monkeypatch.setattr(ta, "send_telegram", fake_send)
    return sent


def test_p1_reaches_the_telegram_chokepoint_with_incident_id(tmp_path, monkeypatch):
    sent = _capture_send(monkeypatch)
    r = _watch_inc(tmp_path, watcher="deploy_stuck", title="main aaaa not live after 40 min", job="deploy-on-main")
    stub = Stub([(json.dumps({"class": "needs_operator", "action": "operator: renew", "rationale": "r"}), "anthropic")])
    deps = stub.deps()
    deps.notify = S.default_notify  # the real notifier, down to send_telegram
    S.cycle(d=_d(tmp_path), state_root=tmp_path / "state", release_root=tmp_path, cfg=_scfg(), deps=deps, apply=True,
            now=T0, environ={}, root=ROOT)
    assert len(sent) == 1 and sent[0]["priority"] == "P1" and r["id"] in sent[0]["message"]
    assert sent[0]["producer"] == f"incident_supervisor:{r['id']}"
    assert L.load_records(_d(tmp_path))[r["id"]]["escalations"][0]["delivered"] is True


def test_daily_brief_reaches_the_telegram_chokepoint(tmp_path, monkeypatch):
    sent = _capture_send(monkeypatch)
    import importlib

    brief = importlib.import_module("scripts.incident_daily_brief")
    _open(_d(tmp_path), title="fixture one")
    assert brief.main(["--apply"]) == 0
    assert len(sent) == 1 and sent[0]["message"].startswith("Incidents ") and sent[0]["priority"] == "P2"
