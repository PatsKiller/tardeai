"""Governed model job (plan tranche D, 2026-10-07): held-out fixtures for valid / invalid JSON / schema
miss / forbidden content / over-cap / outage / deadline / artifact problems. The governed call is a fake;
no provider is reached. Every failure is a typed refusal and the receipt never claims a send."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_model_job as M  # noqa: E402

NOW = dt.datetime(2026, 10, 7, 4, 30, tzinfo=dt.timezone.utc)
SCHEMAS = M.load_schemas()
GOOD = {"headline": "Two filings moved AMC and APO", "items": [{"symbol": "AMC", "change_guid": "d13460e0", "summary": "8-K filed", "why_it_matters": "guidance"}],
        "sources_cited": ["d13460e0"], "confidence_note": "artifact only", "recommendation": "NONE"}


def _root(tmp_path: Path) -> Path:
    (tmp_path / "data" / "runtime" / "provider_cost").mkdir(parents=True)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    return tmp_path


def _artifact(root: Path, body: dict, name: str = "material_changes_digest_input.json") -> dict:
    p = root / "data" / "runtime" / name
    raw = json.dumps(body).encode()
    p.write_bytes(raw)
    return {"store": "data/runtime", "ref": name, "sha256": hashlib.sha256(raw).hexdigest()}


def _job(root: Path, **over) -> dict:
    job = {"process_id": "n8n_material_digest_draft", "artifact_ref": _artifact(root, {"changes": [{"change_guid": "d13460e0", "symbol": "AMC"}]}),
           "correlation_id": "corr-md-0001", "deadline": (NOW + dt.timedelta(hours=1)).isoformat(),
           "output_schema_id": "material_change_digest_draft/v1"}
    job.update(over)
    return job


def bridge_success(answer=GOOD, *, process_id="n8n_material_digest_draft", request_id="corr-md-0001", reservation_id=4242,
                   mock=False, **tradeai_over):
    """Byte-shaped like a live bridge success: RealProvider.generate's body plus execute_governed_call Step 10's
    `_tradeai` block (cio_governed_model_bridge.py). Every governance field lives UNDER `_tradeai`; the top level
    carries only the OpenAI-compatible completion. This is the shape that was refused until 2026-10-08."""
    content = answer if isinstance(answer, str) else json.dumps(answer)
    return {
        "id": request_id, "object": "chat.completion", "created": 1759900000, "model": "deepseek-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 700, "completion_tokens": 200, "total_tokens": 900, "prompt_cache_hit_tokens": 0,
                  "prompt_cache_miss_tokens": 700},
        "_tradeai": {
            "real": not mock, "bridge_version": "P-1.2B" if not mock else "P-1.2A", "provider": "deepseek",
            "governance_pass": True, "provider_request_id": "prov-req-1", "latency_ms": 812, "provenance_hash": "ab" * 12,
            "bridge": "cio_governed", "process_id": process_id, "requested_policy": "FAST", "model_id": "deepseek-flash",
            "request_id": request_id, "reservation_id": reservation_id, "cost_estimate": 0.0013,
            "cost_basis": "provider_usage_x_registry_snapshot", "legacy_model_ids_rejected": True, "client_model_ignored": True,
            "mock": mock, "provider_request_journal": {"schema": "ProviderRequestJournal@v1", "semantic_key": "sk-" + "0" * 8,
                                                       "state": "COMPLETED"} if not mock else None,
            **tradeai_over,
        },
    }


def _ok_call(answer=GOOD, **tradeai_over):
    """The live nested shape (see bridge_success). Keyword overrides land in `_tradeai`."""
    seen = []

    def call(messages, *, process_id, response_format, request_id, task_type=None, **named):
        assert response_format == {"type": "json_object"} and "artifact sha256=" in messages[1]["content"]
        assert "password" not in json.dumps(messages).lower()
        seen.append({"process_id": process_id, "request_id": request_id, "task_type": task_type, **named})
        return bridge_success(answer, process_id=process_id, request_id=request_id, **tradeai_over)
    call.seen = seen
    return call


def _flat_call(answer=GOOD, **extra):
    """The pre-2026-10-08 fake: governance fields at the top level (kept as a fallback, never what the bridge sends)."""
    def call(messages, *, process_id, response_format, request_id, **_named):
        return {"governance_pass": True, "process_id": process_id, "reservation_id": 4242, "cost_estimate": 0.0013,
                "model_id": "deepseek-flash", "provider": "deepseek", "mock": False, "usage": {"total_tokens": 900},
                "choices": [{"message": {"content": answer if isinstance(answer, str) else json.dumps(answer)}}], **extra}
    return call


def test_valid_answer_is_artifact_written_with_a_joined_cost_receipt(tmp_path):
    root = _root(tmp_path)
    (root / "data/runtime/provider_cost/events.jsonl").write_text(json.dumps(
        {"event_id": "pce_1", "client_request_id": "corr-md-0001", "calculated_cost_usd": 0.0013, "model": "deepseek-flash",
         "input_tokens": 700, "output_tokens": 200, "reservation_id": "4242", "observed_at": NOW.isoformat(), "cost_source": "LOCAL_CALCULATED"}) + "\n")
    r = M.run_model_job(_job(root), governed_call=_ok_call(), now=NOW, root=root, schemas=SCHEMAS)
    assert r["state"] == "ARTIFACT_WRITTEN" and r["reason"] is None
    assert r["cost"]["reservation_id"] == 4242 and r["cost"]["settlement"] == "MEASURED" and r["cost"]["provider_cost_event"]["event_id"] == "pce_1"
    assert r["cost"]["model_id"] == "deepseek-flash" and r["cost"]["provider"] == "deepseek" and r["cost"]["cost_estimate_usd"] == 0.0013
    assert r["cost"]["mock"] is False and r["cost"]["bridge_request_id"] == "corr-md-0001"
    assert r["artifact_out"]["body"]["recommendation"] == "NONE" and r["outbound"] == "blocked" and r["effects"] == []
    out = M.write_receipt(r, root=root)
    assert json.loads(out.read_text())["correlation_id"] == "corr-md-0001"


def test_the_live_bridge_envelope_is_read_from_tradeai_and_the_flat_fake_still_works(tmp_path):
    """Defect 1 (2026-10-08): governance fields are nested under `_tradeai` on a live success; reading them top-level
    refused every live job as `governance_refused: governance_pass false` and then `no_cost_receipt`."""
    root = _root(tmp_path)
    live = bridge_success()
    assert "governance_pass" not in live and "reservation_id" not in live      # the top level really is bare
    assert M.governance_envelope(live) is live["_tradeai"]
    r = M.run_model_job(_job(root), governed_call=lambda *a, **k: live, now=NOW, root=root, schemas=SCHEMAS)
    assert (r["state"], r["reason"]) == ("ARTIFACT_WRITTEN", None), r
    assert r["cost"]["reservation_id"] == 4242 and r["cost"]["settlement"] == "NOT_MEASURED"
    flat = M.run_model_job(_job(root), governed_call=_flat_call(), now=NOW, root=root, schemas=SCHEMAS)
    assert flat["state"] == "ARTIFACT_WRITTEN" and flat["cost"]["reservation_id"] == 4242
    # a nested envelope that says governance did NOT pass is still refused; the top level cannot override it
    denied = dict(bridge_success(), governance_pass=True)
    denied["_tradeai"] = dict(denied["_tradeai"], governance_pass=False)
    r = M.run_model_job(_job(root), governed_call=lambda *a, **k: denied, now=NOW, root=root, schemas=SCHEMAS)
    assert (r["state"], r["reason"]) == ("REFUSED", "governance_refused")


def test_task_type_is_derived_from_the_process_server_side(tmp_path):
    """Defect 3 (2026-10-08): the gateway sent task type `model_job` for every job, so the bridge selected the digest
    process regardless of job.process_id. run_model_job now derives it from PROCESS_TASK_TYPE."""
    root = _root(tmp_path)
    assert M.PROCESS_TASK_TYPE == {"n8n_material_digest_draft": "model_job", "n8n_ops_summary_draft": "ops_summary"}
    call = _ok_call()
    r = M.run_model_job(_job(root), governed_call=call, now=NOW, root=root, schemas=SCHEMAS)
    assert r["state"] == "ARTIFACT_WRITTEN" and r["task_type"] == "model_job" and call.seen[-1]["task_type"] == "model_job"
    ops_answer = {"headline": "ops", "sections": [{"area": "lanes", "summary": "ok"}], "open_items": [], "sources_cited": ["x"],
                  "confidence_note": "artifact only", "recommendation": "NONE"}
    call = _ok_call(ops_answer)
    r = M.run_model_job(_job(root, process_id="n8n_ops_summary_draft", output_schema_id="ops_summary_draft/v1"),
                        governed_call=call, now=NOW, root=root, schemas=SCHEMAS)
    assert r["state"] == "ARTIFACT_WRITTEN" and r["task_type"] == "ops_summary" and call.seen[-1]["task_type"] == "ops_summary"
    assert "routing_policy" not in call.seen[-1]          # absent on the job → not passed
    # an unregistered process is a typed refusal BEFORE any call
    call = _ok_call()
    r = M.run_model_job(_job(root, process_id="alex_cio_synthesis"), governed_call=call, now=NOW, root=root, schemas=SCHEMAS)
    assert (r["state"], r["reason"], r["task_type"]) == ("REFUSED", "process_not_registered", None) and call.seen == []
    # the bridge's (nested) process_id is what process_mismatch compares
    other = lambda *a, **k: bridge_success(process_id="n8n_ops_summary_draft")
    r = M.run_model_job(_job(root), governed_call=other, now=NOW, root=root, schemas=SCHEMAS)
    assert (r["reason"], r["detail"]) == ("process_mismatch", "n8n_ops_summary_draft")


def test_routing_policy_is_a_named_pass_through_never_a_model(tmp_path):
    root = _root(tmp_path)
    call = _ok_call()
    r = M.run_model_job(_job(root, routing_policy="deepseek_only"), governed_call=call, now=NOW, root=root, schemas=SCHEMAS)
    assert r["state"] == "ARTIFACT_WRITTEN" and r["routing_policy"] == "deepseek_only"
    assert call.seen[-1]["routing_policy"] == "deepseek_only" and "model" not in call.seen[-1]


INLINE_SYSTEM = ('You draft a material_change_digest_draft/v1 for a human reviewer. Use ONLY the supplied artifact. Cite each source id '
                 "you use. Return one JSON object with exactly these keys: ['confidence_note', 'headline', 'items', 'recommendation', "
                 "'sources_cited']. Required: ['headline', 'items', 'sources_cited', 'confidence_note']. Never recommend an action; "
                 'if a recommendation key exists it must be "NONE". If the artifact does not support a claim, say so in confidence_note.')


def test_build_messages_without_a_template_is_byte_identical_to_the_2026_10_07_prompt():
    artifact = {"sha256": "f" * 64, "body": {"changes": [{"change_guid": "d13460e0", "symbol": "AMC"}]}}
    job = {"process_id": "n8n_material_digest_draft", "correlation_id": "corr-md-0001"}
    msgs = M.build_messages("material_change_digest_draft/v1", SCHEMAS["material_change_digest_draft/v1"], artifact, job)
    assert msgs == [{"role": "system", "content": INLINE_SYSTEM},
                    {"role": "user", "content": "correlation_id=corr-md-0001\nartifact sha256=" + "f" * 64 + "\n"
                                                + '{"changes": [{"change_guid": "d13460e0", "symbol": "AMC"}]}'}]


def test_templates_render_server_side_and_reproduce_the_inline_prompt_for_both_processes():
    templates = M.load_templates()
    assert "_invalid" not in templates, templates.get("_invalid")
    assert sorted(templates) == ["material_digest_draft.v1", "n8n_lane_failure_explainer@v1", "ops_summary_draft.v1"]
    for t in templates.values():
        assert t["schema"] == M.TEMPLATE_SCHEMA and t["version"] == 1 and t["max_artifact_bytes"] == 60_000
        assert "{{artifact}}" in t["user_template"] and "{{schema_keys}}" in t["system"]
    artifact = {"sha256": "e" * 64, "body": {"k": "{{artifact}} {{schema_keys}}"}}   # placeholders inside data must NOT expand
    for process_id, schema_id in (("n8n_material_digest_draft", "material_change_digest_draft/v1"),
                                  ("n8n_ops_summary_draft", "ops_summary_draft/v1")):
        tid = M.default_template_id(process_id, templates)
        assert templates[tid]["process_id"] == process_id
        job = {"process_id": process_id, "correlation_id": "corr-t-1"}
        inline = M.build_messages(schema_id, SCHEMAS[schema_id], artifact, job)
        rendered = M.build_messages(schema_id, SCHEMAS[schema_id], artifact, job, template_id=tid, templates=templates)
        assert rendered == inline, (tid, rendered)
        assert "{{artifact}} {{schema_keys}}" in rendered[1]["content"]
    assert M.default_template_id("alex_cio_synthesis", templates) is None


def test_unknown_or_foreign_templates_are_typed_refusals_before_any_call(tmp_path):
    root = _root(tmp_path)
    call = _ok_call()
    r = M.run_model_job(_job(root, template_id="nope.v9"), governed_call=call, now=NOW, root=root, schemas=SCHEMAS)
    assert (r["state"], r["reason"], r["template_id"]) == ("REFUSED", "unknown_template", "nope.v9")
    r = M.run_model_job(_job(root, template_id="ops_summary_draft.v1"), governed_call=call, now=NOW, root=root, schemas=SCHEMAS)
    assert r["reason"] == "template_mismatch" and "n8n_ops_summary_draft" in r["detail"]
    assert call.seen == []
    r = M.run_model_job(_job(root, template_id="material_digest_draft.v1"), governed_call=call, now=NOW, root=root, schemas=SCHEMAS)
    assert r["state"] == "ARTIFACT_WRITTEN" and r["template_id"] == "material_digest_draft.v1"
    # a malformed template file row is dropped with its cause, never rendered
    bad = {"templates": [{"schema": "N8nPromptTemplate@v1", "id": "x.v1", "version": 1, "process_id": "n8n_material_digest_draft",
                          "system": "{{secret}}", "user_template": "{{artifact}}", "max_artifact_bytes": 10},
                         {"schema": "N8nPromptTemplate@v1", "id": "y.v1", "version": 1, "process_id": "alex_cio_synthesis",
                          "system": "s", "user_template": "{{artifact}}", "max_artifact_bytes": 10}]}
    p = tmp_path / "t.json"; p.write_text(json.dumps(bad))
    loaded = M.load_templates(p)
    assert set(loaded) == {"_invalid"} and "unknown placeholders ['secret']" in loaded["_invalid"]["x.v1"]
    assert "not in PROCESS_TASK_TYPE" in loaded["_invalid"]["y.v1"]


def test_missing_cost_event_is_not_measured_not_invented(tmp_path):
    root = _root(tmp_path)
    r = M.run_model_job(_job(root), governed_call=_ok_call(), now=NOW, root=root, schemas=SCHEMAS)
    assert r["state"] == "ARTIFACT_WRITTEN" and r["cost"]["settlement"] == "NOT_MEASURED" and r["cost"]["provider_cost_event"] is None


def test_invalid_json_schema_miss_and_forbidden_content_are_typed_refusals(tmp_path):
    root = _root(tmp_path)
    r = M.run_model_job(_job(root), governed_call=_ok_call("{not json"), now=NOW, root=root, schemas=SCHEMAS)
    assert (r["state"], r["reason"]) == ("REFUSED", "invalid_json")
    r = M.run_model_job(_job(root), governed_call=_ok_call({"headline": "x" * 500, "items": []}), now=NOW, root=root, schemas=SCHEMAS)
    assert r["reason"] == "schema_invalid" and "sources_cited: required" in r["detail"]
    bad = dict(GOOD, recommendation="BUY")
    assert M.run_model_job(_job(root), governed_call=_ok_call(bad), now=NOW, root=root, schemas=SCHEMAS)["reason"] == "schema_invalid"
    sneaky = dict(GOOD, items=[{**GOOD["items"][0], "size": 100}])
    r = M.run_model_job(_job(root), governed_call=_ok_call(sneaky), now=NOW, root=root, schemas=SCHEMAS)
    assert r["reason"] in ("schema_invalid", "forbidden_content") and r["artifact_out"] is None


def test_over_cap_outage_and_governance_errors_never_fall_back(tmp_path):
    root = _root(tmp_path)
    def err(code, status):
        return lambda *a, **k: {"error": {"code": code, "status": status, "message": code}, "cost_estimate": 0.0, "governance_pass": False}
    assert M.run_model_job(_job(root), governed_call=err("DAILY_COST_CAP_EXCEEDED", 429), now=NOW, root=root, schemas=SCHEMAS)["reason"] == "over_cap"
    assert M.run_model_job(_job(root), governed_call=err("PROVIDER_TIMEOUT", 504), now=NOW, root=root, schemas=SCHEMAS)["reason"] == "provider_outage"
    r = M.run_model_job(_job(root), governed_call=err("PROCESS_NOT_REGISTERED", 400), now=NOW, root=root, schemas=SCHEMAS)
    assert r["reason"] == "governance_refused" and r["fallback"] == "none" and r["cost"] is None


def test_deadline_artifact_and_schema_preconditions(tmp_path):
    root = _root(tmp_path)
    calls = []
    spy = lambda *a, **k: (calls.append(1), _ok_call()(*a, **k))[1]
    assert M.run_model_job(_job(root, deadline=(NOW - dt.timedelta(minutes=1)).isoformat()), governed_call=spy, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "deadline_passed"
    assert M.run_model_job(_job(root, output_schema_id="nope/v9"), governed_call=spy, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "unknown_output_schema"
    assert M.run_model_job(_job(root, artifact_ref={"store": "config", "ref": "x.json"}), governed_call=spy, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "artifact_store_refused"
    assert M.run_model_job(_job(root, artifact_ref={"store": "data/runtime", "ref": "../../etc/passwd"}), governed_call=spy, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "artifact_store_refused"
    assert M.run_model_job(_job(root, artifact_ref={"store": "data/runtime", "ref": "missing.json"}), governed_call=spy, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "artifact_unresolved"
    ref = dict(_job(root)["artifact_ref"], sha256="0" * 64)
    assert M.run_model_job(_job(root, artifact_ref=ref), governed_call=spy, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "artifact_hash_mismatch"
    assert calls == []      # no provider call happened for any precondition refusal


def test_process_mismatch_and_missing_reservation_are_refused(tmp_path):
    root = _root(tmp_path)
    other = lambda *a, **k: bridge_success(process_id="alex_cio_synthesis")
    assert M.run_model_job(_job(root), governed_call=other, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "process_mismatch"
    nores = lambda *a, **k: bridge_success(reservation_id=None)
    assert M.run_model_job(_job(root), governed_call=nores, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "no_cost_receipt"
    mocked = lambda *a, **k: bridge_success(reservation_id=None, mock=True)      # the mock bridge has no reservation to join
    assert M.run_model_job(_job(root), governed_call=mocked, now=NOW, root=root, schemas=SCHEMAS)["state"] == "ARTIFACT_WRITTEN"


def test_registry_declares_the_digest_draft_process_with_a_small_cap():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    p = next(x for x in reg["processes"] if x["id"] == "n8n_material_digest_draft")
    assert p["advisory_only"] is True and p["fallback_allowed"] is False and p["tools_allowed"] is False
    assert p["daily_cost_cap_usd"] <= 0.10 and p["deepseek_allowed_policies"] == ["FAST"]
