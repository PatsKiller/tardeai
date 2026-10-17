"""n8n fabric process hermes-learning (2026-10-15; AGENTS.md §23.23): the first business process on the fabric.

Static: the generated process workflow equals a fresh render and verifies against INDEX.json; it is inactive, uses only
fabric-allowed nodes, makes no relay call of its own, calls only the PUBLISHED Run Lane sub-workflow by id, saves
successes and names tradeai-fabric-error; its Schedule Triggers equal the stage runner's cron slots; every step is wired
in the manifest's dependency order (Merge for fan-in). Host side: each runnable step is its own allowlisted lane (shadow,
dry run only, the step command's own lock and timeout), a registry row the generic dispatcher never emits, a REVIEWED
health contract and an effect key; each BLOCKED step has a reason and no allowlist entry. Behaviour: the generated
Code nodes run under node.js and the whole graph is interpreted (stop-on-failure, blocked, partial, manual all-stages).
Runner: the cron stage runner claims the same effect keys only with PIPELINE_EFFECT_CLAIM=1 AND cron_claim true, and a
refused claim runs nothing. Imports nothing into n8n; tmp_path ledgers only."""

from __future__ import annotations

import copy
import json
import shlex
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))
from support import n8n_cutover_waves as CW  # noqa: E402
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import n8n_workflow_templates as T  # noqa: E402
from scripts.lib import effect_claim as E  # noqa: E402
from scripts.lib import lane_stage_clamp as C  # noqa: E402
from scripts.pipelines import pipeline_manifest as PM  # noqa: E402
from tests.pipeline_runner_fixtures import runner_env, sandbox_runner  # noqa: E402

FABRIC_DIR = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "fabric"
WID = "tradeai-fabric-hermes-learning"
PROCESS = "hermes-learning"
SPEC = json.loads((ROOT / "config" / "n8n_fabric_processes.json").read_text(encoding="utf-8"))["processes"][PROCESS]
MANIFEST = json.loads((ROOT / SPEC["manifest"]).read_text(encoding="utf-8"))
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
ALLOW_LANES = {e["lane_id"]: e for e in ALLOW["lanes"]}
REG = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
EFFECTS = json.loads((ROOT / "config" / "n8n_effect_keys.json").read_text(encoding="utf-8"))
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"]}
STEPS = {st["id"]: (stage, st) for stage, s in MANIFEST["stages"].items() for st in s["steps"]}
RUNNABLE = [sid for sid, s in SPEC["steps"].items() if not s["blocked"]]
BLOCKED = [sid for sid, s in SPEC["steps"].items() if s["blocked"]]
#: Graph hash of the generated process workflow (INDEX.json). A change here is a reviewed graph change: the imported
#: copy stops verifying and the packet re-imports it.
PROCESS_GRAPH_PIN = "f1d0984c64b0"  # cutover PR-2 (2026-10-15): MODE live (was 44c35ad3374f)
#: The fabric policy hash Build 1 shipped (5aa61048d / 494adde71): adding a process workflow must not move it, or the
#: four imported fabric workflows stop verifying.
POLICY_PIN = "c6750b96ada49f816798bf3714ad390616b1b32769fdcbcc54e0635e32caf31f"


def _wf() -> dict:
    return json.loads((FABRIC_DIR / f"{WID}.json").read_text(encoding="utf-8"))


def _node(wf: dict, name: str) -> dict:
    return next(n for n in wf["nodes"] if n["name"] == name)


def _preds(wf: dict) -> dict[str, list[tuple[str, int, int]]]:
    """dst -> [(src, src_output, dst_input)]."""
    out: dict[str, list[tuple[str, int, int]]] = {}
    for src, c in wf["connections"].items():
        for k, outs in enumerate(c["main"]):
            for edge in outs:
                out.setdefault(edge["node"], []).append((src, k, edge["index"]))
    return out


# ── generator, manifest pins ─────────────────────────────────────────────────────────────────────────────────────


def test_generator_check_is_clean_and_the_process_is_in_the_manifest():
    assert T.main(["build-fabric", "--check"]) == 0
    idx = json.loads((FABRIC_DIR / "INDEX.json").read_text(encoding="utf-8"))
    row = next(r for r in idx["workflows"] if r["id"] == WID)
    wf = _wf()
    assert row["kind"] == T.PROCESS_KIND == wf["meta"]["kind"]
    assert row["graph_sha256"] == wf["meta"]["graph_sha256"] == T.graph_hash(wf)
    assert row["graph_sha256"].startswith(PROCESS_GRAPH_PIN)
    assert row["relay_calls"] == [] and row["active"] is False and row["error_workflow"] == T.FABRIC_ERROR_ID
    assert idx["policy_sha256"] == T.policy_hash() == wf["meta"]["policy_sha256"] == POLICY_PIN


def test_trusted_deployer_verifies_a_reexport_and_refuses_a_direct_relay_call(tmp_path):
    wf = _wf()
    exported = copy.deepcopy(wf)
    exported.pop("meta")
    exported["active"] = True  # a published export; activation is the grant's business
    for n in exported["nodes"]:
        n["position"] = [0, 0]
    p = tmp_path / "export.json"
    p.write_text(json.dumps(exported), encoding="utf-8")
    assert T.verify_fabric([p], FABRIC_DIR / "INDEX.json")["ok"] is True
    bad = copy.deepcopy(exported)
    bad["nodes"].append(
        {"name": "sneak", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "parameters": {"url": "x"}}
    )
    p.write_text(json.dumps(bad), encoding="utf-8")
    res = T.verify_fabric([p], FABRIC_DIR / "INDEX.json")
    assert res["ok"] is False
    assert {"process_http_node:sneak", "graph_hash_mismatch"} <= set(res["workflows"][0]["problems"])


@pytest.mark.parametrize(
    "mutate,problem",
    [
        (lambda s: s["steps"]["outcome_grader"].update(depends_on=["tag_engine"]), "not an earlier"),
        (lambda s: s["steps"]["autonomous_self_tune"].update(depends_on=["outcome_grader"]), "not an earlier"),
        (lambda s: s["steps"]["tag_engine"].update(depends_on=["config_governor"]), "not an earlier"),
        (lambda s: s["steps"].pop("tag_engine"), "spec steps"),
        (lambda s: s.update(mode="maybe"), "mode must be"),
        (lambda s: s["steps"]["outcome_learning"].update(blocked=""), "blocked must be"),
        (lambda s: s.update(default_max_attempts=3), "exceeds the execution timeout"),
    ],
)
def test_process_plan_refuses_an_inconsistent_spec(mutate, problem):
    spec = copy.deepcopy(SPEC)
    mutate(spec)
    with pytest.raises(ValueError, match=problem):
        T.process_plan(PROCESS, spec, MANIFEST)


def test_registered_in_the_cio_hardening_gates():
    from scripts import run_cio_hardening_ci as CI

    gates = dict(CI.GATES)
    files = gates["n8n_fabric_hermes_learning_20261015"]
    assert "tests/test_n8n_fabric_hermes_learning_20261015.py" in files
    for f in files:
        assert (ROOT / f).is_file(), f


# ── graph ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_inactive_allowed_nodes_error_workflow_and_saved_successes():
    wf = _wf()
    assert wf["active"] is False and wf["id"] == WID
    types = {n["type"] for n in wf["nodes"]}
    assert types <= T.FABRIC_ALLOWED_NODE_TYPES and not types & T.FABRIC_FORBIDDEN_NODE_TYPES
    assert "n8n-nodes-base.httpRequest" not in types  # every host call goes through Run Lane
    assert T.validate_fabric_workflow(wf, {WID, T.FABRIC_ERROR_ID}) == [] and T.process_problems(wf) == []
    s = wf["settings"]
    assert s["errorWorkflow"] == T.FABRIC_ERROR_ID
    assert s["saveDataSuccessExecution"] == "all" and s["saveDataErrorExecution"] == "all"
    assert s["executionTimeout"] == T.PROCESS_EXECUTION_TIMEOUT_S
    assert not any(n.get("credentials") for n in wf["nodes"])  # no credential at all: Run Lane holds the relay key
    for n in wf["nodes"]:
        if n["type"] == "n8n-nodes-base.code":
            js = n["parameters"]["jsCode"]
            assert "$env" not in js and "require(" not in js and "fetch(" not in js and "this.helpers" not in js


def test_triggers_are_the_stage_cron_slots_plus_one_manual_trigger():
    wf = _wf()
    scheds = {n["name"]: n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger"}
    assert set(scheds) == {f"Schedule {st}" for st in MANIFEST["stages"]}
    for stage, sdoc in MANIFEST["stages"].items():
        expr = scheds[f"Schedule {stage}"]["parameters"]["rule"]["interval"][0]["expression"]
        runner_lane = SPEC["runner_lanes"][stage]
        # identical to the manifest slot (the effect-key slot <date>T<HHMM>); the stage runner's cron line equals it,
        # except the learn line moved to 11:20 by operator decision D1 (2026-10-15 cutover README: retention runs
        # after n8n's grader; the effect slot stays the manifest minute)
        assert expr == sdoc["proposed_schedule"]
        cron_expr = REG[runner_lane]["scheduler"]["expression"]
        # ... and the tune line moved to 17:20 by the tune cutover (2026-10-17) so n8n's 17:00 fire claims first
        assert cron_expr == {"learn": "20 11 * * *", "tune": "20 17 * * *"}.get(stage, sdoc["proposed_schedule"])
        assert f"--stage {stage}" in REG[runner_lane]["scheduler"]["command_text"]
    assert wf["settings"]["timezone"] == "America/New_York"
    manual = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.manualTrigger"]
    assert [n["name"] for n in manual] == [T.PN_MANUAL]
    other = {n["type"] for n in wf["nodes"]} - {"n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.manualTrigger"}
    assert not {t for t in other if t.endswith("Trigger") or t == "n8n-nodes-base.webhook"}


def test_every_step_calls_run_lane_by_id_and_waits():
    wf = _wf()
    runs = {n["name"]: n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.executeWorkflow"}
    assert set(runs) == {f"Run {sid}" for sid in STEPS}
    for n in runs.values():
        p = n["parameters"]
        assert p["source"] == "database" and p["workflowId"] == {"__rl": True, "value": T.RUN_LANE_ID, "mode": "id"}
        assert p["options"]["waitForSubWorkflow"] is True
        assert set(p["workflowInputs"]["value"]) == {
            "lane_id",
            "mode",
            "idempotency_key",
            "max_attempts",
            "outcome_timeout_s",
            "process_id",
        }


def test_dependency_order_and_merge_fan_in():
    wf, preds = _wf(), _preds(_wf())
    for sid, s in SPEC["steps"].items():
        stage = STEPS[sid][0]
        order = [st["id"] for st in MANIFEST["stages"][stage]["steps"]]
        for d in s["depends_on"]:
            assert order.index(d) < order.index(sid), (sid, d)  # the shell runner's serial order stays topological
        gate_in = {src for src, _, _ in preds[f"Gate {sid}"]}
        if not s["depends_on"]:
            assert gate_in <= {T.PN_ROUTE} | {f"Then {st}?" for st in MANIFEST["stages"]}, (sid, gate_in)
        elif len(s["depends_on"]) == 1:
            assert gate_in == {f"Result {s['depends_on'][0]}"}, (sid, gate_in)
        else:
            assert gate_in == {f"Join {sid}"}
            join = preds[f"Join {sid}"]
            assert sorted(i for _, _, i in join) == list(range(len(s["depends_on"])))
            assert {src for src, _, _ in join} == {f"Result {d}" for d in s["depends_on"]}
            assert _node(wf, f"Join {sid}")["parameters"]["numberInputs"] == len(s["depends_on"])
        # Gate -> Run? -> (Run -> Result | Result): the step is called only through its Gate
        assert {src for src, _, _ in preds[f"Run? {sid}"]} == {f"Gate {sid}"}
        assert preds[f"Run {sid}"] == [(f"Run? {sid}", 0, 0)]
        assert sorted(preds[f"Result {sid}"]) == sorted([(f"Run {sid}", 0, 0), (f"Run? {sid}", 1, 0)])
    for stage, sdoc in MANIFEST["stages"].items():
        ids = [st["id"] for st in sdoc["steps"]]
        terminals = [i for i in ids if not any(i in SPEC["steps"][j]["depends_on"] for j in ids)]
        done_in = {src for src, _, _ in preds[f"Done {stage}"]}
        if len(terminals) > 1:
            assert done_in == {f"Join {stage}"}
            join = preds[f"Join {stage}"]
            assert {src for src, _, _ in join} == {f"Result {t}" for t in terminals}
            assert sorted(i for _, _, i in join) == list(range(len(terminals)))
            assert _node(wf, f"Join {stage}")["parameters"]["numberInputs"] == len(terminals)
        else:
            assert done_in == {f"Result {terminals[0]}"}


def test_learn_dag_is_the_reviewed_one():
    deps = {sid: s["depends_on"] for sid, s in SPEC["steps"].items()}
    assert deps == {
        "outcome_grader": [],
        "tag_engine": ["outcome_grader"],
        "outcome_feedback_agent": ["tag_engine"],
        "outcome_learning": ["outcome_grader"],
        "score_history_retention": ["outcome_grader"],
        "config_governor": ["outcome_learning"],
        "autonomous_self_tune": [],
    }
    assert SPEC["mode"] == "live"  # hermes-learning cutover PR-2 (2026-10-15); tune lane stays shadow (clamped)


# ── host side: lanes, allowlist, registry, contracts, effect keys ───────────────────────────────────────────────


def _step_argv(cmd: str) -> list[str]:
    toks = shlex.split(cmd)
    i = toks.index("$PY")
    return toks[i + 1 :]


@pytest.mark.parametrize("sid", RUNNABLE)
def test_runnable_step_is_a_shadow_lane_with_the_step_lock_and_timeout(sid):
    stage, st = STEPS[sid]
    lane = SPEC["steps"][sid]["lane_id"]
    e = ALLOW_LANES[lane]
    # cutover PR-2 (2026-10-15): four learn lanes carry cutover_live_arg at stage canary; the held outcome_feedback_agent
    # (sender token gate; follow-up after gate alignment) stays shadow. Tune cutover (2026-10-17): the tune lane too.
    learn = sid != "outcome_feedback_agent"
    assert e["live_arg"] == (SPEC["steps"][sid]["cutover_live_arg"] if learn else None)
    assert e["dry_run_arg"] is not None
    assert e["command"][0] == "$PY" and e["market_gate"] is False
    locks = PM.lock_paths(st["command"])
    assert locks == [e["lock"]], (locks, e["lock"])
    assert e["lock_kind"] == ("safe_flock" if "safe_flock.sh" in st["command"] else "flock")
    assert e["timeout_s"] == PM.timeout_seconds(st["timeout"])
    # the live argv later = the step's own argv: command + --apply (dry run = command + dry_run_arg, no --apply). A
    # split step's lane adds its declared lane_extra_args (none since the 2026-10-17 tune cutover: autonomous_self_tune
    # runs the cron step's own argv, both halves, because the cron step is skipped whole once n8n owns the effect).
    extra = list(SPEC["steps"][sid].get("lane_extra_args") or [])
    assert sorted(e["command"][1:] + ["--apply"]) == sorted(_step_argv(st["command"]) + extra)
    assert "--apply" not in e["command"] + e["dry_run_arg"]
    row = REG[lane]
    sched = row["scheduler"]
    assert sched["kind"] == "n8n" and sched["expression"] == WID
    assert sched["stage"] == ("canary" if learn else "shadow")
    # match names the process step, never a crontab line: the script's retired cron row keeps its own line
    assert sched["process_step"] == sid and sched["match"] == f"{WID}:{sid}"
    assert "dispatch" not in row  # the generic dispatcher never emits a process step
    assert row["state"] == "NEVER_SCHEDULED" and row["state_reason"] and row["output_signal"]["kind"]
    assert C.clamp_mode(lane, "live", list(REG.values()))["effective_mode"] == ("live" if learn else "dry_run")
    c = CONTRACTS[lane]
    assert c["status"] == "REVIEWED" and c["stage"] == "shadow" and c["workflow_id"] == WID
    fx = EFFECTS["lanes"][lane]
    assert fx == {
        "process": lane,
        "input_version": SPEC["input_version"],
        "pipeline": MANIFEST["pipeline"],
        "stage": stage,
        "step_id": sid,
        # hermes-learning cutover PR-1 (2026-10-15): cron_claim true for the five LEARN step lanes; tune cutover
        # (2026-10-17): the tune step too
        "cron_claim": True,
    }


def test_effect_config_loads_for_the_executor_and_the_runner_claims_the_learn_and_tune_steps():
    cfg = E.load_effect_config(ROOT / "config" / "n8n_effect_keys.json")
    # 2026-10-15 n8n cutover waves arm their own lanes (tests/support/n8n_cutover_waves.py); the hermes steps are these.
    assert set(cfg) - set(CW.ARMED) == {SPEC["steps"][s]["lane_id"] for s in RUNNABLE}
    # cutover PR-1 (2026-10-15): the learn stage claims its five runnable steps (only when the cron line also sets
    # PIPELINE_EFFECT_CLAIM=1); tune cutover (2026-10-17): the tune stage claims its one step the same way
    learn = {SPEC["steps"][s]["lane_id"] for s in RUNNABLE if STEPS[s][0] == "learn"}
    assert len(learn) == 5
    assert len(PM.effect_spec(MANIFEST, "learn", EFFECTS)) == 5
    assert PM.effect_spec(MANIFEST, "tune", EFFECTS) == [
        ("autonomous_self_tune", "hermes-learning-autonomous-self-tune", SPEC["input_version"])]


@pytest.mark.parametrize("sid", BLOCKED)
def test_blocked_step_has_a_reason_and_no_runnable_entry(sid):
    lane = SPEC["steps"][sid]["lane_id"]
    assert lane not in ALLOW_LANES and lane not in EFFECTS["lanes"] and lane not in REG
    reason = ALLOW["blocked_reasons"][lane]
    assert SPEC["steps"][sid]["blocked"] in reason and sid in reason


def test_blocked_reasons_match_the_scripts():
    # 2026-10-15 unblock (tests/test_hermes_learning_unblock_20261015.py): tag_engine, outcome_feedback_agent and the
    # learn half of autonomous_self_tune are shadow lanes now. score_history_retention stays EXCLUDED: destructive
    # retention on cron, an operator decision.
    src = {sid: (ROOT / _step_argv(STEPS[sid][1]["command"])[0]).read_text(encoding="utf-8") for sid in BLOCKED}
    assert "DELETE FROM hermes_score_history" in src["score_history_retention"]
    assert "OPERATOR DECISION" in SPEC["steps"]["score_history_retention"]["blocked"]
    assert set(BLOCKED) == {"score_history_retention"}
    assert set(RUNNABLE) == {
        "outcome_grader", "tag_engine", "outcome_feedback_agent", "outcome_learning", "config_governor",
        "autonomous_self_tune",
    }


# ── behaviour: the generated graph, interpreted (node.js runs the Code nodes) ───────────────────────────────────

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node.js not on PATH")
HARNESS = r"""
const fs = require('fs');
const spec = JSON.parse(fs.readFileSync(0, 'utf8'));
const custom = {};
const items = spec.input.map((j) => ({ json: j }));
globalThis.$input = { first: () => items[0] || { json: {} }, all: () => items };
globalThis.$ = (name) => {
  if (!(name in spec.nodes)) throw new Error("Referenced node is unexecuted: " + name);
  return { first: () => ({ json: spec.nodes[name] }), last: () => ({ json: spec.nodes[name] }) };
};
const FMT = { 'yyyyLLdd': spec.date, "yyyyLLdd'T'HHmm": spec.date + 'T' + spec.hhmm };
globalThis.$now = { setZone: (tz) => ({ toFormat: (f) => { if (!(f in FMT)) throw new Error('fmt ' + f); return FMT[f]; } }) };
globalThis.$execution = { id: '77', customData: { set: (k, v) => { custom[k] = v; } } };
globalThis.$workflow = { id: 'wf-1' };
(async () => {
  try {
    const fn = new Function('return (async () => {' + spec.code + '\n})();');
    const out = await fn();
    process.stdout.write(JSON.stringify({ ok: true, out: out.map((i) => i.json), custom }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(e.message), custom }));
  }
})();
"""


def _js(code: str, items: list[dict], nodes: dict, date="20261015", hhmm="0932") -> dict:
    proc = subprocess.run(
        [NODE, "-e", HARNESS],
        input=json.dumps({"code": code, "input": items, "nodes": nodes, "date": date, "hhmm": hhmm}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _run_lane_stub(item: dict, statuses: dict[str, str], calls: list) -> dict:
    calls.append(item)
    status = statuses.get(item["lane_id"], "success")
    return {
        "schema": "RunLaneResult@v1",
        "lane_id": item["lane_id"],
        "mode": item["mode"],
        "run_id": item["idempotency_key"],
        "status": status,
        "reason": None if status == "success" else "exit_1",
        "attempts": 1,
        "exit_code": 0 if status == "success" else 1,
        "duration_s": 1.5,
        "dead_letter": status == "failed",
    }


def simulate(start: str, statuses: dict[str, str] | None = None, *, hhmm="0932") -> dict:
    """Interpret the generated workflow from one trigger, depth-first like n8n's v1 execution order: Code nodes
    run in node.js, If/Switch evaluate their (fixed, generated) expressions, Merge waits for every input, and
    Execute Workflow -> Run Lane is a stub answering the status the test chose per lane."""
    wf = _wf()
    nodes = {n["name"]: n for n in wf["nodes"]}
    statuses = statuses or {}
    out: dict[str, dict] = {}  # node -> first output item (what $(name).first() returns)
    merges: dict[str, dict[int, list]] = {}
    calls: list = []
    error = None
    custom: dict = {}
    stack = [(start, [{}], 0)]
    executed = []
    while stack and error is None:
        name, items, idx = stack.pop()
        n = nodes[name]
        t = n["type"]
        if t == "n8n-nodes-base.merge":
            merges.setdefault(name, {})[idx] = items
            if len(merges[name]) < n["parameters"]["numberInputs"]:
                continue
            items = [i for k in sorted(merges[name]) for i in merges[name][k]]
        executed.append(name)
        outputs: list[list] = []
        if t in ("n8n-nodes-base.manualTrigger", "n8n-nodes-base.scheduleTrigger"):
            outputs = [[{}]]
        elif t == "n8n-nodes-base.code":
            r = _js(n["parameters"]["jsCode"], items, out, hhmm=hhmm)
            custom.update(r.get("custom") or {})
            if not r["ok"]:
                error = (name, r["error"])
                break
            outputs = [r["out"]]
        elif t == "n8n-nodes-base.if":
            left = n["parameters"]["conditions"]["conditions"][0]["leftValue"]
            if left == "={{ $json.run === true }}":
                truth = [i.get("run") is True for i in items]
            else:
                assert left == "={{ $('Process context').first().json.stage === 'all' }}", left
                truth = [out["Process context"]["stage"] == "all" for _ in items]
            outputs = [[i for i, b in zip(items, truth) if b], [i for i, b in zip(items, truth) if not b]]
        elif t == "n8n-nodes-base.switch":
            keys = [r["outputKey"] for r in n["parameters"]["rules"]["values"]]
            outputs = [[] for _ in range(len(keys) + 1)]
            for i in items:
                outputs[keys.index(i["stage"]) if i["stage"] in keys else len(keys)].append(i)
        elif t == "n8n-nodes-base.merge":
            outputs = [items]
        elif t == "n8n-nodes-base.executeWorkflow":
            outputs = [[_run_lane_stub(i, statuses, calls) for i in items]]
        else:
            raise AssertionError(f"unexpected node type {t}")
        if outputs and outputs[0]:
            out[name] = outputs[0][0]
        elif len(outputs) > 1:
            for o in outputs:
                if o:
                    out[name] = o[0]
                    break
        pushes = []
        for k, o in enumerate(outputs):
            if not o:
                continue
            for edge in (wf["connections"].get(name, {}).get("main") or [[]] * len(outputs))[k]:
                pushes.append((edge["node"], o, edge["index"]))
        stack.extend(reversed(pushes))
    return {"out": out, "calls": calls, "error": error, "custom": custom, "executed": executed}


def _lane(sid: str) -> str:
    return SPEC["steps"][sid]["lane_id"]


@needs_node
def test_scheduled_learn_runs_the_runnable_steps_in_order_and_records_the_blocked():
    r = simulate("Schedule learn")
    assert r["error"] is None, r["error"]
    called = [c["lane_id"] for c in r["calls"]]
    # manifest order (n8n v1 runs branches one after another; the stage runner's serial order stays valid)
    assert called == [_lane(s) for s in ("outcome_grader", "tag_engine", "outcome_feedback_agent", "outcome_learning",
                                         "config_governor")]
    for c in r["calls"]:
        assert c["mode"] == "live" and c["process_id"] == PROCESS  # cutover PR-2: spec mode live
        assert c["idempotency_key"] == f"p:{c['lane_id']}:live:20261015T1050"  # the stage slot, not the minute
        assert c["max_attempts"] == SPEC["default_max_attempts"]
    res = r["out"][T.PN_ASSERT]
    assert res["schema"] == T.PROCESS_RESULT_SCHEMA and res["stage"] == "learn" and res["slot"] == "20261015T1050"
    assert res["overall"] == "partial" and res["failed_steps"] == []
    by = {s["step_id"]: s for s in res["steps"]}
    assert [s["step_id"] for s in res["steps"]] == [st["id"] for st in MANIFEST["stages"]["learn"]["steps"]]
    for sid in ("outcome_grader", "tag_engine", "outcome_feedback_agent", "outcome_learning", "config_governor"):
        assert by[sid]["status"] == "success" and by[sid]["run_id"].startswith("p:")
    assert by["score_history_retention"]["status"] == "blocked" and by["score_history_retention"]["run_id"] is None
    assert r["custom"]["process_id"] == PROCESS and r["custom"]["overall"] == "partial"
    assert "Gate autonomous_self_tune" not in r["executed"]  # the tune stage is its own schedule


@needs_node
def test_a_failed_step_stops_its_downstream_and_fails_the_execution():
    r = simulate("Schedule learn", {_lane("outcome_learning"): "failed"})
    assert r["error"] is not None and r["error"][0] == T.PN_ASSERT
    assert "failed step(s) outcome_learning" in r["error"][1]
    called = [c["lane_id"] for c in r["calls"]]
    assert _lane("config_governor") not in called  # downstream of the failure: never requested
    res = r["out"][T.PN_RESULT]
    by = {s["step_id"]: s for s in res["steps"]}
    assert res["overall"] == "failed" and res["first_failed_step"] == "outcome_learning"
    assert by["config_governor"]["status"] == "skipped_upstream"
    assert by["config_governor"]["reason"] == "outcome_learning:failed"
    assert by["outcome_grader"]["status"] == "success"
    assert r["custom"]["failed_steps"] == "outcome_learning"


@needs_node
def test_a_failed_root_skips_every_dependent_but_not_independent_stages():
    r = simulate("Manual run", {_lane("outcome_grader"): "failed"})
    # the independent tune stage still runs: autonomous_self_tune (learn half) depends on nothing in learn
    assert [c["lane_id"] for c in r["calls"]] == [_lane("outcome_grader"), _lane("autonomous_self_tune")]
    res = r["out"][T.PN_RESULT]
    by = {s["step_id"]: s for s in res["steps"]}
    assert by["outcome_learning"]["status"] == "skipped_upstream"
    assert by["tag_engine"]["status"] == "skipped_upstream"
    assert by["outcome_feedback_agent"]["reason"] == "tag_engine:skipped_upstream"
    assert by["config_governor"]["reason"] == "outcome_learning:skipped_upstream"
    assert by["autonomous_self_tune"]["status"] == "success"  # the manual run still covered the tune stage
    assert res["stage"] == "all" and res["overall"] == "failed" and r["error"][0] == T.PN_ASSERT


@needs_node
def test_skipped_lock_and_refusal_are_data():
    r = simulate("Schedule learn", {_lane("outcome_grader"): "skipped_lock"})
    res = r["out"][T.PN_ASSERT]
    assert res["overall"] == "partial" and r["error"] is None
    assert {s["step_id"]: s["status"] for s in res["steps"]}["outcome_learning"] == "skipped_upstream"
    r = simulate("Schedule learn", {_lane("config_governor"): "refused_policy"})
    assert r["error"] is not None and r["out"][T.PN_RESULT]["failed_steps"] == ["config_governor"]


@needs_node
def test_manual_run_covers_both_stages_with_its_own_minute_slot():
    r = simulate("Manual run", hhmm="0932")
    assert r["error"] is None, r["error"]
    res = r["out"][T.PN_ASSERT]
    assert res["stage"] == "all" and res["trigger"] == "manual" and res["slot"] == "20261015T0932"
    assert [s["step_id"] for s in res["steps"]] == [
        st["id"] for stage in MANIFEST["stages"].values() for st in stage["steps"]
    ]
    assert all(c["idempotency_key"].endswith(":live:20261015T0932") for c in r["calls"])


@needs_node
def test_scheduled_tune_covers_only_tune():
    r = simulate("Schedule tune")
    res = r["out"][T.PN_ASSERT]
    assert res["stage"] == "tune" and res["slot"] == "20261015T1700"
    assert [c["lane_id"] for c in r["calls"]] == [_lane("autonomous_self_tune")]
    assert r["calls"][0]["idempotency_key"] == f"p:{_lane('autonomous_self_tune')}:live:20261015T1700"
    assert [s["step_id"] for s in res["steps"]] == ["autonomous_self_tune"]
    assert res["steps"][0]["status"] == "success" and res["overall"] == "ok"


@needs_node
def test_gate_refuses_a_missing_dependency_result_as_not_run():
    code = _node(_wf(), "Gate config_governor")["parameters"]["jsCode"]
    ctx = {"process_id": PROCESS, "stage": "learn", "trigger": "schedule", "mode": "dry_run", "slot": "20261015T1050"}
    r = _js(code, [{}], {"Process context": ctx})
    assert r["ok"] and r["out"][0]["run"] is False and r["out"][0]["reason"] == "outcome_learning:not_run"
    r = _js(code, [{}], {"Process context": ctx, "Result outcome_learning": {"status": "success"}})
    assert r["out"][0]["run"] is True
    assert r["out"][0]["idempotency_key"] == "p:hermes-learning-config-governor:dry_run:20261015T1050"


# ── runner effect-claim compatibility ───────────────────────────────────────────────────────────────────────────

RUNNER = ROOT / "scripts" / "pipelines" / "run_hermes_pipeline.sh"


def _sandbox(tmp_path: Path) -> Path:
    runner = sandbox_runner(tmp_path, RUNNER)
    lib = tmp_path / "scripts" / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    # effect_claim.py's CLI closure: the ledger and the gateway module it reads EDGES from (stdlib-only at import)
    for name in ("effect_claim.py", "n8n_coordination_ledger.py", "n8n_coordination_gateway.py"):
        shutil.copyfile(ROOT / "scripts" / "lib" / name, lib / name)
    return runner


def _manifest(tmp_path: Path, marker: Path, *, rc: int = 0) -> Path:
    cmd = f"echo x >> {marker}" + ("" if rc == 0 else f"; exit {rc}")
    m = {
        "schema": PM.MANIFEST_SCHEMA,
        "pipeline": "fxpipe",
        "stages": {
            "learn": {
                "proposed_schedule": "50 10 * * *",
                "steps": [
                    {"id": "claimed", "cron_line": 1, "command": cmd, "timeout": "10s"},
                    {"id": "plain", "cron_line": 2, "command": f"echo p >> {marker}.plain", "timeout": "10s"},
                ],
            }
        },
    }
    p = tmp_path / "fxpipe.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return p


def _effect_cfg(tmp_path: Path, *, cron_claim: bool) -> Path:
    p = tmp_path / "effect_keys.json"
    p.write_text(
        json.dumps(
            {
                "schema": "N8nEffectKeys@v1",
                "lanes": {
                    "fx-claimed": {
                        "process": "fx-claimed",
                        "input_version": "v1",
                        "pipeline": "fxpipe",
                        "stage": "learn",
                        "step_id": "claimed",
                        "cron_claim": cron_claim,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return p


def _set_owner(ledger: Path, owner: str, expect: int | None) -> None:
    args = ["--ledger", str(ledger), "set-owner", "--process", "fx-claimed", "--owner", owner, "--by", "test"]
    if expect is not None:
        args += ["--expect-epoch", str(expect)]
    assert E.main(args) == 0


def _runner(tmp_path: Path, manifest: Path, *, claim: bool, cfg: Path, ledger: Path, apply=True):
    env = runner_env(tmp_path)
    env.update(
        {
            "PIPELINE_EFFECT_CONFIG": str(cfg),
            "PIPELINE_EFFECT_LEDGER": str(ledger),
            "PIPELINE_EFFECT_DATE": "20261015",
        }
    )
    if claim:
        env["PIPELINE_EFFECT_CLAIM"] = "1"
    cmd = ["bash", str(_sandbox(tmp_path)), "--manifest", str(manifest), "--project-root", str(tmp_path)]
    cmd += ["--stage", "learn", "--apply" if apply else "--dry-run"]
    return subprocess.run(cmd, cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120)


def _summary(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "data" / "runtime" / "pipeline_fxpipe_learn_last.json").read_text())


def _claim_row(ledger: Path, key: str):
    conn = sqlite3.connect(str(ledger))
    try:
        return conn.execute("SELECT state, scheduler FROM effect_claims WHERE effect_key = ?", (key,)).fetchone()
    finally:
        conn.close()


KEY = "fx:fx-claimed:20261015T1050:v1"


def test_slot_is_the_same_string_cron_and_n8n_compute():
    assert PM.effect_slot(MANIFEST, "learn", "20261015") == "20261015T1050"
    assert PM.effect_slot(MANIFEST, "tune", "20261015") == "20261015T1700"
    for st in T.process_workflow_plans()[WID]["stages"]:
        assert PM.stage_slot_hhmm(MANIFEST, st["stage"]) == st["slot_hhmm"]
    assert E.effect_key("fx-claimed", PM.effect_slot(MANIFEST, "learn", "20261015"), "v1") == KEY
    # the n8n process sends the same slot for a scheduled stage (Process context: date + the stage cron minute)
    js = _node(_wf(), T.PN_CTX)["parameters"]["jsCode"]
    assert '"learn": "1050"' in js and '"tune": "1700"' in js


def test_switch_off_is_byte_for_byte_the_old_runner(tmp_path):
    marker = tmp_path / "ran"
    ledger = tmp_path / "ledger.sqlite"
    r = _runner(
        tmp_path, _manifest(tmp_path, marker), claim=False, cfg=_effect_cfg(tmp_path, cron_claim=True), ledger=ledger
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == "x\n" and not ledger.exists()  # nothing read, nothing claimed
    assert "[effect]" not in r.stdout
    assert all("effect_key" not in s for s in _summary(tmp_path)["steps"])


def test_cron_claim_false_claims_nothing_even_with_the_switch_on(tmp_path):
    marker = tmp_path / "ran"
    ledger = tmp_path / "ledger.sqlite"
    r = _runner(
        tmp_path, _manifest(tmp_path, marker), claim=True, cfg=_effect_cfg(tmp_path, cron_claim=False), ledger=ledger
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == "x\n" and "claiming steps: none" in r.stdout


def test_cron_owner_claims_runs_finishes_done_and_refuses_the_same_slot_twice(tmp_path):
    marker, ledger = tmp_path / "ran", tmp_path / "ledger.sqlite"
    _set_owner(ledger, "cron", None)
    man, cfg = _manifest(tmp_path, marker), _effect_cfg(tmp_path, cron_claim=True)
    r = _runner(tmp_path, man, claim=True, cfg=cfg, ledger=ledger)
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == "x\n"
    steps = {s["id"]: s for s in _summary(tmp_path)["steps"]}
    assert steps["claimed"]["status"] == "ok" and steps["claimed"]["effect_key"] == KEY
    assert "effect_key" not in steps["plain"] and steps["plain"]["status"] == "ok"
    assert _claim_row(ledger, KEY) == ("DONE", "cron")
    # the same business slot again (a re-run, or n8n having done it): refused, nothing runs, the rest still runs
    r = _runner(tmp_path, man, claim=True, cfg=cfg, ledger=ledger)
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == "x\n"
    steps = {s["id"]: s for s in _summary(tmp_path)["steps"]}
    assert steps["claimed"]["status"] == "skipped_effect" and steps["claimed"]["rc"] == E.REFUSED_EXIT
    assert steps["plain"]["status"] == "ok" and _summary(tmp_path)["overall_status"] == "ok"


def test_n8n_owner_fences_the_cron_runner(tmp_path):
    marker, ledger = tmp_path / "ran", tmp_path / "ledger.sqlite"
    _set_owner(ledger, "cron", None)
    _set_owner(ledger, "n8n", 1)  # the cutover's one recorded act
    r = _runner(
        tmp_path, _manifest(tmp_path, marker), claim=True, cfg=_effect_cfg(tmp_path, cron_claim=True), ledger=ledger
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert not marker.exists() and _claim_row(ledger, KEY) is None
    assert {s["id"]: s for s in _summary(tmp_path)["steps"]}["claimed"]["status"] == "skipped_effect"
    # and the n8n side claims the very same key (executor EffectGate: scheduler n8n, same process/slot/version)
    store = E._open_store(str(ledger))
    import time

    assert store.claim(KEY, scheduler="n8n", now=time.time()).ok is True


def test_no_owner_row_fails_closed(tmp_path):
    marker, ledger = tmp_path / "ran", tmp_path / "ledger.sqlite"
    r = _runner(
        tmp_path, _manifest(tmp_path, marker), claim=True, cfg=_effect_cfg(tmp_path, cron_claim=True), ledger=ledger
    )
    assert r.returncode == 0 and not marker.exists()
    assert {s["id"]: s for s in _summary(tmp_path)["steps"]}["claimed"]["status"] == "skipped_effect"


def test_a_failed_step_finishes_failed_and_is_held_until_released(tmp_path):
    marker, ledger = tmp_path / "ran", tmp_path / "ledger.sqlite"
    _set_owner(ledger, "cron", None)
    cfg = _effect_cfg(tmp_path, cron_claim=True)
    r = _runner(tmp_path, _manifest(tmp_path, marker, rc=3), claim=True, cfg=cfg, ledger=ledger)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _claim_row(ledger, KEY) == ("FAILED", "cron"), r.stdout + r.stderr
    # 2026-10-15 (audit DD05): the failed step may have written before its non-zero exit, so the slot is HELD until an
    # operator release (after checking the target); the second run is refused and does not execute.
    r = _runner(tmp_path, _manifest(tmp_path, marker), claim=True, cfg=cfg, ledger=ledger)
    assert marker.read_text() == "x\n" and _claim_row(ledger, KEY) == ("FAILED", "cron"), r.stdout + r.stderr
    from scripts.lib.effect_claim import EffectClaimStore
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger

    EffectClaimStore(CoordinationLedger(ledger)).release(KEY, by="t", now=1.0, note="target checked")
    r = _runner(tmp_path, _manifest(tmp_path, marker), claim=True, cfg=cfg, ledger=ledger)
    assert marker.read_text() == "x\nx\n" and _claim_row(ledger, KEY) == ("DONE", "cron")


def test_dry_run_never_claims(tmp_path):
    marker, ledger = tmp_path / "ran", tmp_path / "ledger.sqlite"
    _set_owner(ledger, "cron", None)
    r = _runner(
        tmp_path,
        _manifest(tmp_path, marker),
        claim=True,
        cfg=_effect_cfg(tmp_path, cron_claim=True),
        ledger=ledger,
        apply=False,
    )
    assert r.returncode == 0 and not marker.exists() and _claim_row(ledger, KEY) is None


def test_unreadable_config_with_the_switch_on_refuses_the_stage(tmp_path):
    marker, ledger = tmp_path / "ran", tmp_path / "ledger.sqlite"
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "nope"}', encoding="utf-8")
    r = _runner(tmp_path, _manifest(tmp_path, marker), claim=True, cfg=bad, ledger=ledger)
    assert r.returncode == 65 and not marker.exists()


def test_real_hermes_manifest_plans_identically_with_the_switch_on(tmp_path):
    """The committed config has cron_claim false everywhere: the real learn stage dry-runs the same 6 steps."""
    r = _runner(
        tmp_path,
        ROOT / SPEC["manifest"],
        claim=True,
        cfg=ROOT / "config" / "n8n_effect_keys.json",
        ledger=tmp_path / "l.sqlite",
        apply=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("[DRY_RUN] would run") == len(MANIFEST["stages"]["learn"]["steps"])
