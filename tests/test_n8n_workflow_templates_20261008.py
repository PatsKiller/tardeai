"""n8n workflow generator: deterministic, node-type allowlist, N1 complete, INDEX shape.

The generated files under docs/implementation/n8n-parallel/workflows/generated/ are what
the operator imports; the generator's --check mode is what keeps them honest in CI.
No live host path is spelled out here (check_test_host_paths); everything renders to tmp_path.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import n8n_workflow_templates as gen

ROOT = Path(__file__).resolve().parent.parent
N1_LANES = {
    "n8n-pilot-dispatch",
    "n8n-incident-fanin",
    "n8n-research-intake-consumer",
    "crontab-snapshot-for-health-agent",
    "n8n-lab-watchdog",
    "lane-governance-packet-weekly",
    "maturity-remeasure",
    "n8n-monitor-trade-ai",
    "n8n-monitor-dof",
}


def _all_workflows(out: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.rglob("*.json")) if p.name != "INDEX.json"]


def test_render_is_deterministic_and_check_passes(tmp_path):
    out = tmp_path / "generated"
    assert gen.main(["--lanes", "all", "--out", str(out)]) == 0
    first = {p.relative_to(out): p.read_bytes() for p in out.rglob("*.json")}
    assert gen.main(["--lanes", "all", "--out", str(out)]) == 0
    second = {p.relative_to(out): p.read_bytes() for p in out.rglob("*.json")}
    assert first == second, "a second run must not change a single byte (INDEX keeps generated_at)"
    assert gen.main(["--lanes", "all", "--out", str(out), "--check"]) == 0
    # byte conventions: 2-space indent, sorted keys, trailing newline
    sample = next(p for p in out.glob("*.json") if p.name != "INDEX.json").read_text(encoding="utf-8")
    assert sample.endswith("}\n") and sample.startswith('{\n  "active": false')


def test_check_fails_on_a_stale_or_missing_file(tmp_path):
    out = tmp_path / "generated"
    gen.main(["--lanes", "N1", "--out", str(out)])
    victim = out / "n8n-lab-watchdog.json"
    victim.write_text(victim.read_text(encoding="utf-8").replace('"active": false', '"active": true'), encoding="utf-8")
    assert gen.main(["--lanes", "N1", "--out", str(out), "--check"]) == 1
    victim.unlink()
    assert gen.main(["--lanes", "N1", "--out", str(out), "--check"]) == 1


def test_committed_files_match_the_generator():
    """The repo copy is regenerated after every generator edit (code_sha pins it)."""
    out = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "generated"
    diffs = gen.check(out, gen.select_lanes("all"), gen.RELAY_URL_PLACEHOLDER)
    assert diffs == [], diffs


def test_node_type_allowlist_and_chain_shape(tmp_path):
    out = tmp_path / "generated"
    gen.main(["--lanes", "all", "--out", str(out)])
    wfs = _all_workflows(out)
    assert len(wfs) == 2 * len(gen.LANES)
    forbidden = {"executeCommand", "ssh", "emailSend", "telegram", "openAi", "vectorStore", "agent", "lmChat"}
    gated = {lane["lane_id"] for lane in gen.LANES if lane.get("after")}
    four = {
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.set",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
    }
    assert gen.UNGATED_NODE_TYPES == four
    assert gen.ALLOWED_NODE_TYPES == four | {"n8n-nodes-base.if", "n8n-nodes-base.wait"}
    for wf in wfs:
        types = [n["type"] for n in wf["nodes"]]
        assert set(types) <= gen.ALLOWED_NODE_TYPES, (wf["name"], types)
        for t in types:
            assert not any(f.lower() in t.lower() for f in forbidden), t
        assert wf["active"] is False
        assert wf["settings"]["timezone"] == "America/New_York"
        lane_id = wf["meta"]["lane_id"]
        if lane_id in gated:
            assert set(types) == gen.ALLOWED_NODE_TYPES, (wf["name"], types)
            assert wf["meta"]["after"] == next(l["after"] for l in gen.LANES if l["lane_id"] == lane_id)
            continue
        assert set(types) == four, (wf["name"], types)
        assert len(types) == 4
        # linear chain: schedule -> set -> http -> code
        names = [n["name"] for n in wf["nodes"]]
        for src, dst in zip(names, names[1:]):
            assert wf["connections"][src]["main"][0][0]["node"] == dst
        assert names[-1] not in wf["connections"]


def test_http_node_follows_the_relay_contract(tmp_path):
    out = tmp_path / "generated"
    gen.main(["--lanes", "N1", "--out", str(out)])
    for wf in _all_workflows(out):
        http = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
        assert http["typeVersion"] == 4.2
        p = http["parameters"]
        assert p["method"] == "POST"
        assert p["url"] == "={{ $json.TRADEAI_N8N_RUN_URL }}/run"
        assert p["genericAuthType"] == "httpHeaderAuth"
        assert http["credentials"]["httpHeaderAuth"]["name"] == "tradeai-run-relay"
        assert p["options"]["timeout"] == 10_000
        assert p["options"]["response"]["response"]["fullResponse"] is True
        jb = p["jsonBody"]
        mode = "dry_run" if wf["name"].endswith("-shadow") else "live"
        # an n8n expression: the relay needs workflow_id + execution_id to mint the idempotent run id
        assert jb.startswith("={{ JSON.stringify({") and jb.endswith("}) }}")
        assert f"lane_id: {json.dumps(wf['meta']['lane_id'])}" in jb and f"mode: {json.dumps(mode)}" in jb
        assert f"requested_by: {json.dumps(wf['name'])}" in jb
        assert "workflow_id: String($workflow.id)" in jb and "execution_id: String($execution.id)" in jb
        # no IP anywhere in the workflow; the base URL is the Set-node placeholder
        text = json.dumps(wf)
        assert "172." not in text and "127.0.0.1" not in text
        setnode = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.set")
        assignment = setnode["parameters"]["assignments"]["assignments"][0]
        assert assignment["name"] == "TRADEAI_N8N_RUN_URL"
        assert assignment["value"] == "http://RELAY_HOST:18092"
        code = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.code")["parameters"]["jsCode"]
        assert wf["meta"]["lane_id"] in code and "'REQUESTED'" in code and "duplicate === true" in code
        assert "throw new Error" in code


def test_every_n1_lane_present_with_valid_cron_and_two_files(tmp_path):
    out = tmp_path / "generated"
    gen.main(["--lanes", "N1", "--out", str(out)])
    index = json.loads((out / "INDEX.json").read_text(encoding="utf-8"))
    got = {row["lane_id"] for row in index["lanes"]}
    assert got == N1_LANES
    for row in index["lanes"]:
        assert row["tranche"] == "N1" and row["committed"] is True
        assert (out / row["shadow_file"]).exists() and (out / row["live_file"]).exists()
        assert "/" not in row["shadow_file"], "N1 is committed at the top level, not under pending/"
        for expr in row["schedule"]:
            assert gen.validate_cron(expr) == [], (row["lane_id"], expr)


def test_every_lane_in_the_table_has_a_valid_cron_and_a_source():
    seen = set()
    for lane in gen.LANES:
        assert lane["lane_id"] not in seen, f"duplicate lane {lane['lane_id']}"
        seen.add(lane["lane_id"])
        assert lane["tranche"] in gen.TRANCHES
        assert lane["fidelity"] in {"EXACT", "APPROXIMATE", "PROPOSED", "ONE_SHOT"}
        assert lane["source"], lane["lane_id"]
        assert lane["cron"], lane["lane_id"]
        for expr in lane["cron"]:
            assert gen.validate_cron(expr) == [], (lane["lane_id"], expr)
        if lane["fidelity"] != "EXACT":
            assert lane.get("note"), f"{lane['lane_id']} is {lane['fidelity']} and must say why"


def test_registry_cron_rows_agree_with_the_table():
    """For lanes with a kind=cron registry row the first five tokens of scheduler.expression are the cron."""
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]
    rows = {r["lane_id"]: r for r in reg}
    checked = 0
    for lane in gen.LANES:
        row = rows.get(lane["lane_id"])
        if not row or row.get("scheduler", {}).get("kind") != "cron" or row.get("state") != "ACTIVE":
            continue
        expr = " ".join(row["scheduler"]["expression"].split()[:5])
        assert expr == lane["cron"][0], (lane["lane_id"], expr, lane["cron"])
        checked += 1
    assert checked >= 15


def test_index_shape(tmp_path):
    out = tmp_path / "generated"
    gen.main(["--lanes", "all", "--out", str(out)])
    index = json.loads((out / "INDEX.json").read_text(encoding="utf-8"))
    assert index["schema"] == "N8nWorkflowSet@v1"
    assert set(index) >= {"generated_at", "code_sha", "lanes", "lane_count", "lanes_by_tranche", "node_types"}
    assert index["lane_count"] == len(gen.LANES) == len(index["lanes"])
    assert index["lanes_by_tranche"]["N1"] == 9
    assert sum(index["lanes_by_tranche"].values()) == index["lane_count"]
    for row in index["lanes"]:
        assert set(row) >= {
            "lane_id",
            "tranche",
            "schedule",
            "shadow_file",
            "live_file",
            "schedule_source",
            "schedule_fidelity",
        }
        if row["tranche"] not in gen.COMMITTED_TRANCHES:
            assert row["shadow_file"].startswith("pending/") and row["committed"] is False
    # pipeline stage order is recorded for the N2 chains
    stages = [r for r in index["lanes"] if r.get("pipeline") == "after_close"]
    assert [r["stage_order"] for r in sorted(stages, key=lambda r: r["stage_order"])] == [1, 2, 3]


@pytest.mark.parametrize(
    "oncal, cron",
    [
        ("*-*-* 01:15:00", "15 1 * * *"),
        ("Sun *-*-* 03:00:00", "0 3 * * 0"),
        ("*-*-01 06:00:00", "0 6 1 * *"),
        ("Mon-Fri 07:40", "40 7 * * 1-5"),
        ("Sun 18:00", "0 18 * * 0"),
        ("Tue..Sat *-*-* 07:45:00", "45 7 * * 2-6"),
        ("*-*-* *:07,37:00", "7,37 * * * *"),
        ("*-*-* *:12:00", "12 * * * *"),
        ("Sun *-*-01..07 06:30:00", "30 6 1-7 * 0"),
    ],
)
def test_oncalendar_conversion(oncal, cron):
    assert gen.oncalendar_to_cron(oncal) == cron


def test_cron_validation_rejects_bad_shapes():
    assert gen.validate_cron("0 9 L * *")
    assert gen.validate_cron("* * * *")
    assert gen.validate_cron("61 * * * *")
    assert gen.validate_cron("*/15 * * * *") == []
    assert gen.validate_cron("25 6-18/3 * * 1-5") == []


N2_AFTER = {
    "after-close-pipeline-broker-truth": "after-close-pipeline-close-capture",
    "after-close-pipeline-planning": "after-close-pipeline-broker-truth",
    "hermes-learning-pipeline-tune": "hermes-learning-pipeline-learn",
    "hermes-overnight-pipeline-night": "hermes-overnight-pipeline-close",
}
_IP = re.compile(r"\d+\.\d+\.\d+\.\d+")


def _assert_gated(wf: dict, lane_id: str, after: str, mode: str) -> None:
    assert wf["meta"]["lane_id"] == lane_id and wf["meta"]["mode"] == mode and wf["meta"]["after"] == after
    names = [n["name"] for n in wf["nodes"]]
    assert names == [
        "Schedule",
        "Relay constants",
        "GET predecessor last",
        "Evaluate predecessor",
        "Predecessor ready",
        "Wait retry",
        "POST relay /run",
        "Assert REQUESTED",
    ]
    conn = wf["connections"]
    assert conn["Schedule"]["main"][0][0]["node"] == "Relay constants"
    assert conn["Relay constants"]["main"][0][0]["node"] == "GET predecessor last"
    assert conn["GET predecessor last"]["main"][0][0]["node"] == "Evaluate predecessor"
    assert conn["Evaluate predecessor"]["main"][0][0]["node"] == "Predecessor ready"
    assert conn["Predecessor ready"]["main"][0][0]["node"] == "POST relay /run"
    assert conn["Predecessor ready"]["main"][1][0]["node"] == "Wait retry"
    assert conn["Wait retry"]["main"][0][0]["node"] == "GET predecessor last"
    assert conn["POST relay /run"]["main"][0][0]["node"] == "Assert REQUESTED"
    assert "Assert REQUESTED" not in conn
    get = next(n for n in wf["nodes"] if n["name"] == "GET predecessor last")
    post = next(n for n in wf["nodes"] if n["name"] == "POST relay /run")
    assert get["parameters"]["method"] == "GET"
    assert get["parameters"]["url"] == "={{ $json.TRADEAI_N8N_RUN_URL }}/runs/" + after + "/last"
    assert get["credentials"]["httpHeaderAuth"]["name"] == "tradeai-run-relay"
    assert post["parameters"]["method"] == "POST"
    assert post["parameters"]["url"] == "={{ $json.TRADEAI_N8N_RUN_URL }}/run"
    assert post["credentials"]["httpHeaderAuth"]["name"] == "tradeai-run-relay"
    wait = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.wait")
    assert wait["parameters"]["amount"] == 60 and wait["parameters"]["unit"] == "seconds"
    code = next(n for n in wf["nodes"] if n["name"] == "Evaluate predecessor")["parameters"]["jsCode"]
    assert f"const MAX_GATE_RETRIES = {gen.MAX_GATE_RETRIES};" in code
    assert gen.MAX_GATE_RETRIES == 5
    assert "attempt > MAX_GATE_RETRIES" in code
    assert "throw new Error" in code and lane_id in code
    assert "RUN_DONE" in code and "America/New_York" in code
    assert "new Date().toISOString()" in code
    assert re.search(r"20\d{2}-\d{2}-\d{2}", code) is None
    lane = next(row for row in gen.LANES if row["lane_id"] == lane_id)
    crosses = gen.predecessor_crosses_midnight(lane, after)
    assert f"const CROSSES_MIDNIGHT = {'true' if crosses else 'false'};" in code
    assert "previousEtDay" in code
    jb = post["parameters"]["jsonBody"]
    assert jb.startswith("={{ JSON.stringify({") and jb.endswith("}) }}")
    assert f"lane_id: {json.dumps(lane_id)}" in jb and f"mode: {json.dumps(mode)}" in jb
    assert "workflow_id: String($workflow.id)" in jb and "execution_id: String($execution.id)" in jb


def test_n2_gated_chain_shadow_and_live(tmp_path):
    out = tmp_path / "generated"
    assert gen.main(["--lanes", "N2", "--out", str(out)]) == 0
    for lane_id, after in N2_AFTER.items():
        for mode, filename in (("dry_run", f"{lane_id}-shadow.json"), ("live", f"{lane_id}.json")):
            wf = json.loads((out / "pending" / filename).read_text(encoding="utf-8"))
            _assert_gated(wf, lane_id, after, mode)
    pre = json.loads((out / "pending" / "premarket-data-pipeline.json").read_text(encoding="utf-8"))
    assert [n["type"] for n in pre["nodes"]] == [
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.set",
        "n8n-nodes-base.httpRequest",
        "n8n-nodes-base.code",
    ]
    assert "after" not in pre["meta"]
    assert len(pre["nodes"]) == 4


def test_n2_files_have_no_ip_literal_and_only_four_after_edges(tmp_path):
    out = tmp_path / "generated"
    gen.main(["--lanes", "N2", "--out", str(out)])
    for path in (out / "pending").glob("*.json"):
        assert _IP.search(path.read_text(encoding="utf-8")) is None, path.name
    lanes = {lane["lane_id"]: lane.get("after") for lane in gen.LANES}
    assert {k: v for k, v in lanes.items() if v} == N2_AFTER
    doc = json.loads((ROOT / "config" / "n8n_migration_tranches.json").read_text(encoding="utf-8"))
    got = {}
    for tranche, body in doc["tranches"].items():
        for row in body["lanes"]:
            if "after" in row:
                assert tranche == "N2"
                got[row["lane_id"]] = row["after"]
    assert got == N2_AFTER
    index = json.loads((out / "INDEX.json").read_text(encoding="utf-8"))
    by_id = {row["lane_id"]: row for row in index["lanes"]}
    for lane_id, after in N2_AFTER.items():
        assert by_id[lane_id]["after"] == after
    assert "after" not in by_id["premarket-data-pipeline"]
    assert "after" not in by_id["portfolio-backup-cadence"]


def test_only_the_overnight_edge_crosses_midnight():
    flags = {
        lane["lane_id"]: gen.predecessor_crosses_midnight(lane, lane["after"])
        for lane in gen.LANES
        if lane.get("after")
    }
    assert flags == {
        "after-close-pipeline-broker-truth": False,
        "after-close-pipeline-planning": False,
        "hermes-learning-pipeline-tune": False,
        "hermes-overnight-pipeline-night": True,
    }


def test_overnight_gate_accepts_the_previous_et_evening():
    """23:13 ET close is the previous America/New_York date when night runs at 02:20 ET."""
    node = shutil.which("node")
    assert node, "node is required to execute the generated gate"
    lane = next(row for row in gen.LANES if row["lane_id"] == "hermes-overnight-pipeline-night")
    code = gen._gate_js(
        lane["lane_id"],
        lane["after"],
        "live",
        crosses_midnight=gen.predecessor_crosses_midnight(lane, lane["after"]),
    )
    harness = (
        """
const cases = JSON.parse(process.argv[1]);
function run(nowIso, finishedAt) {
  const RealDate = Date;
  global.Date = class extends RealDate {
    constructor(...args) { super(...(args.length ? args : [nowIso])); }
    static now() { return new RealDate(nowIso).getTime(); }
  };
  global.$input = { first: () => ({ json: { statusCode: 200, body: { last: { state: 'RUN_DONE', finished_at: finishedAt } } } }) };
  global.$ = (name) => {
    if (name === 'Wait retry') throw new Error('first attempt');
    if (name === 'Relay constants') return { first: () => ({ json: { TRADEAI_N8N_RUN_URL: 'http://relay.example:18092' } }) };
    throw new Error(name);
  };
  const out = (function() { %s })();
  global.Date = RealDate;
  return out[0].json.gate_ok;
}
const results = cases.map((row) => run(row.now, row.finished));
process.stdout.write(JSON.stringify(results));
"""
        % code
    )
    # 2026-10-09 02:20 ET (EDT, UTC-4) and the 23:13 ET close on 2026-10-08.
    cases = [
        {"now": "2026-10-09T06:20:00Z", "finished": "2026-10-09T03:13:00Z"},
        {"now": "2026-10-09T06:20:00Z", "finished": "2026-10-08T03:13:00Z"},
        {"now": "2026-10-09T06:20:00Z", "finished": "2026-10-09T20:00:00Z"},
    ]
    proc = subprocess.run([node, "-e", harness, json.dumps(cases)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [True, False, True]
    same_day = next(row for row in gen.LANES if row["lane_id"] == "hermes-learning-pipeline-tune")
    same_code = gen._gate_js(
        same_day["lane_id"],
        same_day["after"],
        "live",
        crosses_midnight=False,
    )
    same_harness = harness.replace(code, same_code, 1)
    # learn is 10:50 ET the same morning; an evening finish the day before must not open the gate.
    same_cases = [
        {"now": "2026-10-08T21:00:00Z", "finished": "2026-10-08T14:50:00Z"},
        {"now": "2026-10-08T21:00:00Z", "finished": "2026-10-08T03:13:00Z"},
    ]
    proc = subprocess.run(
        [node, "-e", same_harness, json.dumps(same_cases)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [True, False]


def test_cli_rejects_unknown_tranche(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "n8n_workflow_templates.py"), "--lanes", "N9", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "unknown tranche" in proc.stderr
