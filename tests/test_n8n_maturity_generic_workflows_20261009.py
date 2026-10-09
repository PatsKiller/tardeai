"""N8N Maturity B5.6: the six generic, registry-driven workflows (design 02 §4, §6–§11, §15).

Static checks only. Everything renders to tmp_path except the committed-set comparison, which
reads docs/implementation/n8n-maturity/workflows/. config/lane_registry.json and
config/n8n_run_allowlist.json are read, never written. Nothing is imported into n8n.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from scripts import n8n_workflow_templates as gen

ROOT = Path(__file__).resolve().parent.parent
COMMITTED = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows"
EXPECTED_IDS = {
    "tradeai-dispatcher",
    "tradeai-event-router",
    "tradeai-heartbeat-watcher",
    "tradeai-incident-router",
    "tradeai-digest-scheduler",
    "tradeai-approval-router",
}
CRON_RE = re.compile(r"^\s*(\S+\s+){4}\S+\s*$")
CRON_FIELD_RE = re.compile(r"^[\d*/,\-]+$")
SECRET_RE = re.compile(r"(?i)(bearer\s+[a-z0-9]|sk-[a-z0-9]{8}|api[_-]?key|password|secret|token=)")


def _workflows(out: Path) -> dict[str, dict]:
    return {
        p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*.json")) if p.name != "INDEX.json"
    }


def _strings(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k, path + ("<key>",))
            yield from _strings(v, path + (k,))
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, path)
    elif isinstance(obj, str):
        yield path, obj


def _is_cron(s: str) -> bool:
    return bool(CRON_RE.match(s)) and all(CRON_FIELD_RE.match(f) for f in s.split())


def _known_lane_ids() -> set[str]:
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    ids = {row["lane_id"] for row in reg["lanes"] if row.get("lane_id")}
    lanes = allow.get("lanes") or []
    if isinstance(lanes, dict):
        ids |= set(lanes)
    else:
        ids |= {row["lane_id"] for row in lanes if isinstance(row, dict) and row.get("lane_id")}
    ids |= {lane["lane_id"] for lane in gen.LANES}
    return ids


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("generic")
    assert gen.main(["build-generic", "--out", str(out)]) == 0
    return out


def test_exactly_six_files_with_stable_ids(rendered):
    wfs = _workflows(rendered)
    assert len(wfs) == 6
    assert {wf["id"] for wf in wfs.values()} == EXPECTED_IDS
    for name, wf in wfs.items():
        assert name == f"{wf['id']}.json" and wf["name"] == wf["id"]
    assert set(gen.GENERIC_KINDS) == {
        "dispatcher",
        "event-router",
        "heartbeat-watcher",
        "incident-router",
        "digest-scheduler",
        "approval-router",
    }


def test_byte_deterministic_and_check(tmp_path, rendered):
    first = {p.name: p.read_bytes() for p in rendered.glob("*.json")}
    again = tmp_path / "again"
    assert gen.main(["build-generic", "--out", str(again)]) == 0
    assert {p.name: p.read_bytes() for p in again.glob("*.json")} == first
    assert gen.main(["build-generic", "--out", str(again), "--check"]) == 0
    for kind in gen.GENERIC_KINDS:
        assert gen.build_generic(kind) == gen.build_generic(kind)
    # one changed byte fails --check; a missing file fails --check
    victim = again / "tradeai-dispatcher.json"
    victim.write_bytes(victim.read_bytes().replace(b'"active": false', b'"active": true'))
    assert gen.main(["build-generic", "--out", str(again), "--check"]) == 1
    victim.unlink()
    assert gen.main(["build-generic", "--out", str(again), "--check"]) == 1


def test_committed_set_matches_the_generator():
    assert gen.main(["build-generic", "--out", str(COMMITTED), "--check"]) == 0
    assert len(_workflows(COMMITTED)) == 6


def test_unknown_kind_refused():
    with pytest.raises(ValueError):
        gen.build_generic("per-lane")


def test_node_types_allowlisted_and_forbidden_absent(rendered):
    assert not (gen.GENERIC_ALLOWED_NODE_TYPES & gen.GENERIC_FORBIDDEN_NODE_TYPES)
    # the per-lane allowlist is not widened by the generic set
    assert gen.ALLOWED_NODE_TYPES == gen.UNGATED_NODE_TYPES | {"n8n-nodes-base.if", "n8n-nodes-base.wait"}
    banned = re.compile(r"(?i)(executecommand|ssh|postgres|mysql|sql|mongo|redis|telegram|email|gmail|langchain|agent)")
    for name, wf in _workflows(rendered).items():
        for node in wf["nodes"]:
            assert node["type"] in gen.GENERIC_ALLOWED_NODE_TYPES, (name, node["type"])
            assert node["type"] not in gen.GENERIC_FORBIDDEN_NODE_TYPES
            assert not banned.search(node["type"]), (name, node["type"])
            if node["type"] == "n8n-nodes-base.code":
                assert "require(" not in node["parameters"]["jsCode"]
                assert "$env" not in node["parameters"]["jsCode"]
        names = [n["name"] for n in wf["nodes"]]
        assert len(names) == len(set(names))
        ids = [n["id"] for n in wf["nodes"]]
        assert len(ids) == len(set(ids))
        # every connection names a real node
        for src, out in wf["connections"].items():
            assert src in names
            for branch in out["main"]:
                for edge in branch:
                    assert edge["node"] in names


def test_run_bodies_carry_only_the_five_keys(rendered):
    seen = 0
    for name, wf in _workflows(rendered).items():
        for node in wf["nodes"]:
            if node["type"] != "n8n-nodes-base.httpRequest":
                continue
            p = node["parameters"]
            assert node["credentials"] == {"httpHeaderAuth": {"id": gen.CREDENTIAL_NAME, "name": gen.CREDENTIAL_NAME}}
            assert node["retryOnFail"] is True and node["maxTries"] == 2
            if p["url"].endswith("/run"):
                seen += 1
                keys = re.findall(r"(\w+):", p["jsonBody"].split("JSON.stringify(", 1)[1])
                assert tuple(keys) == gen.RUN_BODY_KEYS, (name, keys)
                assert p["method"] == "POST" and node["waitBetweenTries"] == 2000
            elif p["url"].endswith("/event"):
                keys = re.findall(r"(\w+):", p["jsonBody"].split("JSON.stringify(", 1)[1])
                assert tuple(keys) == gen.EVENT_BODY_KEYS
                assert wf["id"] == gen.INCIDENT_ROUTER_ID
            else:
                assert p["method"] == "GET" and "jsonBody" not in p
    assert seen == 6


def test_validate_due_asserts_schema_and_drops_fields(rendered):
    for wf in _workflows(rendered).values():
        code = next(n for n in wf["nodes"] if n["name"] == gen.GN_VALIDATE)["parameters"]["jsCode"]
        assert '"DueResponse@v1"' in code
        assert "due.source !== SOURCE" in code
        assert "{ lane_id: lane, mode: it.mode, idempotency_key: it.idempotency_key }" in code
        batch = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.splitInBatches")
        assert batch["parameters"]["batchSize"] == 5
        pace = next(n for n in wf["nodes"] if n["name"] == gen.GN_PACE)
        assert pace["parameters"] == {"amount": 1, "unit": "seconds"}
        stop = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.stopAndError")
        assert "lane_id" in stop["parameters"]["errorMessage"] and "reason" in stop["parameters"]["errorMessage"]


def test_relay_url_is_the_bridge_ip_in_one_set_node(rendered):
    for name, wf in _workflows(rendered).items():
        sets = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.set"]
        assert len(sets) == 1
        values = [a["value"] for a in sets[0]["parameters"]["assignments"]["assignments"]]
        assert values == ["http://172.19.0.1:18092"]
        hits = [s for _, s in _strings(wf) if "18092" in s or "http://" in s]
        assert hits == ["http://172.19.0.1:18092"], (name, hits)
        for node in wf["nodes"]:
            if node["type"] == "n8n-nodes-base.httpRequest":
                assert node["parameters"]["url"].startswith("={{ $('Relay').first().json.TRADEAI_N8N_RUN_URL }}/")


def test_settings_error_workflow_and_inactive(rendered):
    for wf in _workflows(rendered).values():
        s = wf["settings"]
        assert wf["active"] is False
        assert s["timezone"] == "America/New_York"
        assert s["saveDataErrorExecution"] == "all"
        if wf["id"] == "tradeai-incident-router":
            assert "errorWorkflow" not in s
            assert any(n["type"] == "n8n-nodes-base.errorTrigger" for n in wf["nodes"])
        else:
            assert s["errorWorkflow"] == "tradeai-incident-router"
            assert not any(n["type"] == "n8n-nodes-base.errorTrigger" for n in wf["nodes"])
    assert gen.build_generic("dispatcher")["settings"]["executionTimeout"] == 50


def test_no_lane_constants_beyond_the_system_filters(rendered):
    known = _known_lane_ids()
    assert len(known) > 100
    allowed = set(gen.SYSTEM_FILTER_LANES)
    assert allowed == {
        "heartbeat-watch",
        "incident-fanin",
        "incident-notify",
        "approval-escalate",
        "n8n-workflow-error",
    }
    found_system: set[str] = set()
    for name, wf in _workflows(rendered).items():
        for _, s in _strings(wf):
            for lane in known | allowed:
                if re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(lane) + r"(?![A-Za-z0-9_-])", s):
                    assert lane in allowed, (name, lane, s[:120])
                    found_system.add(lane)
    assert found_system == allowed
    # each system filter lives only in the workflow the design gives it
    by_wf = {wf["id"]: json.dumps(wf) for wf in _workflows(rendered).values()}
    assert "lane=heartbeat-watch" in by_wf["tradeai-heartbeat-watcher"]
    assert "/runs/heartbeat-watch/last?mode=live" in by_wf["tradeai-heartbeat-watcher"]
    assert "lane=incident-fanin,incident-notify" in by_wf["tradeai-incident-router"]
    assert "n8n-workflow-error" in by_wf["tradeai-incident-router"]
    assert "lane=approval-escalate" in by_wf["tradeai-approval-router"]
    for wid in ("tradeai-dispatcher", "tradeai-event-router", "tradeai-digest-scheduler"):
        assert "lane=" not in by_wf[wid]


def test_no_cron_outside_schedule_triggers(rendered):
    expected = {
        "tradeai-dispatcher": "* * * * *",
        "tradeai-event-router": "* * * * *",
        "tradeai-heartbeat-watcher": "*/5 * * * *",
        "tradeai-incident-router": "* * * * *",
        "tradeai-digest-scheduler": "*/5 * * * *",
        "tradeai-approval-router": "*/5 * * * *",
    }
    for wf in _workflows(rendered).values():
        crons = []
        for node in wf["nodes"]:
            for path, s in _strings(node):
                if _is_cron(s):
                    assert node["type"] == "n8n-nodes-base.scheduleTrigger", (wf["id"], node["name"], s)
                    assert path[-1] == "expression"
                    crons.append(s)
        assert crons == [expected[wf["id"]]]


def test_no_paths_commands_or_secrets(rendered):
    for name, wf in _workflows(rendered).items():
        text = json.dumps(wf)
        assert "/home/" not in text and "$HOME" not in text and "/tmp/" not in text
        # meta and the Code-node banner name the generator; nothing else may name a script
        behaviour = json.dumps([wf["nodes"], wf["connections"], wf["settings"]]).replace(
            "scripts/n8n_workflow_templates.py build-generic", ""
        )
        assert ".py" not in behaviour and ".sh" not in behaviour
        for _, s in _strings(wf):
            assert not SECRET_RE.search(s), (name, s[:120])
        for node in wf["nodes"]:
            for cred in (node.get("credentials") or {}).values():
                assert cred == {"id": gen.CREDENTIAL_NAME, "name": gen.CREDENTIAL_NAME}


def test_index_lists_six_with_shas(rendered):
    index = json.loads((rendered / "INDEX.json").read_text(encoding="utf-8"))
    assert index["schema"] == "N8nGenericWorkflowSet@v1"
    assert "generated_at" not in index
    rows = index["workflows"]
    assert {r["id"] for r in rows} == EXPECTED_IDS

    for r in rows:
        assert r["sha256"] == hashlib.sha256((rendered / r["file"]).read_bytes()).hexdigest()
        assert r["active"] is False and r["triggers"] and "POST /run" in r["relay_calls"]
