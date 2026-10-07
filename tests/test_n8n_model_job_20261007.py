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


def _ok_call(answer=GOOD, **extra):
    def call(messages, *, process_id, response_format, request_id):
        assert response_format == {"type": "json_object"} and "artifact sha256=" in messages[1]["content"]
        assert "password" not in json.dumps(messages).lower()
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
    assert r["artifact_out"]["body"]["recommendation"] == "NONE" and r["outbound"] == "blocked" and r["effects"] == []
    out = M.write_receipt(r, root=root)
    assert json.loads(out.read_text())["correlation_id"] == "corr-md-0001"


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
    other = lambda *a, **k: dict(_ok_call()(*a, **k), process_id="alex_cio_synthesis")
    assert M.run_model_job(_job(root), governed_call=other, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "process_mismatch"
    nores = lambda *a, **k: dict(_ok_call()(*a, **k), reservation_id=None)
    assert M.run_model_job(_job(root), governed_call=nores, now=NOW, root=root, schemas=SCHEMAS)["reason"] == "no_cost_receipt"


def test_registry_declares_the_digest_draft_process_with_a_small_cap():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    p = next(x for x in reg["processes"] if x["id"] == "n8n_material_digest_draft")
    assert p["advisory_only"] is True and p["fallback_allowed"] is False and p["tools_allowed"] is False
    assert p["daily_cost_cap_usd"] <= 0.10 and p["deepseek_allowed_policies"] == ["FAST"]
