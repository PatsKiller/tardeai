"""Pre-import guard for n8n workflow JSON (2026-10-10, n8n install audit V8 F3).

premarket-data-pipeline-shadow (f4553ff360e21a9f) was imported from generated/pending/ without rendering
--relay-url: its Set node still held http://RELAY_HOST:18092, the operator's manual run 1554 failed
`getaddrinfo EAI_AGAIN relay_host`, and its lane is not in config/n8n_run_allowlist.json, so the gateway
would refuse it anyway. 16 such workflows were imported. Nothing checked a file before import.
Fixtures only: no docker, no n8n.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_n8n_import_ready as G  # noqa: E402

RELAY = "http://172.19.0.1:18092"


def _wf(*, wid="a" * 16, lane="lane-a", url=RELAY, active=False, error_wf=None, kind=None, manual=False):
    meta = {"generator": "scripts/n8n_workflow_templates.py"}
    if lane is not None:
        meta["lane_id"] = lane
    if kind is not None:
        meta["kind"] = kind
    settings = {"executionOrder": "v1", "timezone": "America/New_York"}
    if error_wf:
        settings["errorWorkflow"] = error_wf
    if manual:
        settings["saveManualExecutions"] = True
    return {
        "id": wid,
        "name": f"{lane or kind}-wf",
        "active": active,
        "meta": meta,
        "settings": settings,
        "nodes": [
            {
                "name": "Relay constants",
                "type": "n8n-nodes-base.set",
                "parameters": {"assignments": {"assignments": [{"name": "TRADEAI_N8N_RUN_URL", "value": url}]}},
            },
            {
                "name": "POST relay /run",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"url": "={{ $json.TRADEAI_N8N_RUN_URL }}/run"},
            },
        ],
        "connections": {},
    }


def _write(tmp_path: Path, docs: dict[str, dict], name: str = "stage") -> Path:
    d = tmp_path / name
    d.mkdir()
    for name, doc in docs.items():
        (d / name).write_text(json.dumps(doc), encoding="utf-8")
    return d


ALLOW = {"lane-a", "lane-b"}


def _check(path, **kw):
    kw.setdefault("relay_url", RELAY)
    kw.setdefault("allowlisted", ALLOW)
    return G.check_paths([path], **kw)


def _codes(results):
    return sorted({c for r in results for c in r["refusals"]})


def test_a_rendered_allowlisted_inactive_workflow_passes(tmp_path):
    res = _check(_write(tmp_path, {"lane-a.json": _wf()}))
    assert [r["ok"] for r in res] == [True]
    assert G.exit_code(res) == 0


def test_the_screenshot_case_is_refused_for_placeholder_and_allowlist(tmp_path):
    doc = _wf(wid="f4553ff360e21a9f", lane="premarket-data-pipeline", url="http://RELAY_HOST:18092")
    res = _check(_write(tmp_path, {"premarket-data-pipeline-shadow.json": doc}))
    assert _codes(res) == ["lane_not_allowlisted", "placeholder_unsubstituted", "relay_url_mismatch"]
    assert G.exit_code(res) == 1


def test_a_relay_url_other_than_the_granted_one_is_refused(tmp_path):
    res = _check(_write(tmp_path, {"x.json": _wf(url="http://10.0.0.9:18092")}))
    assert _codes(res) == ["relay_url_mismatch"]


def test_an_active_flag_in_the_file_is_refused(tmp_path):
    res = _check(_write(tmp_path, {"x.json": _wf(active=True)}))
    assert "active_in_file" in _codes(res)


def test_a_per_lane_file_without_provenance_is_refused(tmp_path):
    res = _check(_write(tmp_path, {"x.json": _wf(lane=None)}))
    assert "no_lane_or_kind" in _codes(res)


def test_generic_workflows_need_no_lane_but_their_error_workflow_must_be_known(tmp_path):
    docs = {
        "d.json": _wf(wid="tradeai-dispatcher", lane=None, kind="dispatcher", error_wf="tradeai-incident-router"),
        "i.json": _wf(wid="tradeai-incident-router", lane=None, kind="incident_router"),
    }
    assert G.exit_code(_check(_write(tmp_path, docs))) == 0
    lone = _wf(wid="tradeai-dispatcher", lane=None, kind="dispatcher", error_wf="tradeai-incident-router")
    solo = _write(tmp_path, {"d.json": lone}, name="solo")
    assert "error_workflow_unknown" in _codes(_check(solo))
    assert G.exit_code(_check(solo, known_ids={"tradeai-incident-router"})) == 0


def test_save_manual_executions_is_a_warning_not_a_refusal(tmp_path):
    res = _check(_write(tmp_path, {"x.json": _wf(manual=True)}))
    assert res[0]["ok"] is True and "save_manual_executions_true" in res[0]["warnings"]


def test_directory_scan_matches_n8n_separate_top_level_only_and_skips_index(tmp_path):
    d = _write(tmp_path, {"lane-a.json": _wf(), "INDEX.json": {"lanes": []}})
    (d / "pending").mkdir()
    (d / "pending" / "bad.json").write_text(json.dumps(_wf(url="http://RELAY_HOST:18092")), encoding="utf-8")
    res = _check(d)
    assert [Path(r["file"]).name for r in res] == ["lane-a.json"]


def test_unreadable_input_cannot_run(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert G.main([str(tmp_path / "broken.json"), "--relay-url", RELAY]) == 2
    assert G.main([str(tmp_path / "missing-dir"), "--relay-url", RELAY]) == 2


def test_the_committed_pending_shadows_are_refused_against_the_real_allowlist():
    pending = ROOT / "docs/implementation/n8n-parallel/workflows/generated/pending"
    doc = pending / "premarket-data-pipeline-shadow.json"
    res = G.check_paths([doc], relay_url=RELAY, allowlisted=G.load_allowlisted_lanes())
    assert "placeholder_unsubstituted" in _codes(res) and "lane_not_allowlisted" in _codes(res)


def test_main_reports_json_and_exit_code(tmp_path, capsys):
    d = _write(tmp_path, {"lane-a.json": _wf(lane="not-allowed")})
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"lanes": [{"lane_id": "lane-a"}]}), encoding="utf-8")
    assert G.main([str(d), "--relay-url", RELAY, "--allowlist", str(allow), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["refused"] == 1 and out["files"][0]["refusals"] == ["lane_not_allowlisted"]
