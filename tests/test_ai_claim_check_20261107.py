"""LQ-20261107-154 — AI claim check: deterministic data checks, the closed claim protocol, and the lane receipt.

Every fixture is synthetic (``AAA``/``BBB``, a scratch state root). No model is called, no database is touched: the
model is an injected callable, which is the whole point of the design — the LLM proposes, this code disposes.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import n8n_ai_claim_check as lane
from scripts.lib import ai_claim_check as acc

NOW = datetime(2026, 11, 7, 15, tzinfo=timezone.utc)
LANE_DIR = Path("data/lane")


def _target(**over):
    t = {"id": "lane-a", "kind": "jsonl_dir", "path": str(LANE_DIR), "file_glob": "*_rows.jsonl",
         "natural_key": ["symbol", "as_of"], "required": ["symbol", "as_of", "summary"],
         "timestamp_field": "as_of", "max_age_h": 24, "ranges": {"confidence": [0, 1]},
         "count_matches": {"source_count": "sources"}, "claim_field": "summary",
         "source_text_fields": ["sources[].title"], "max_claim_records": 25}
    t.update(over)
    return t


def _row(symbol="AAA", as_of=None, summary="AAA raised guidance.", confidence=0.5, source_count=1, sources=None,
         **extra):
    row = {"symbol": symbol, "as_of": (as_of or NOW).isoformat(), "summary": summary, "confidence": confidence,
           "source_count": source_count,
           "sources": ([{"title": "AAA raised guidance", "content": "AAA raised guidance for the year."}]
                       if sources is None else sources)}
    row.update(extra)
    return row


def _write(root: Path, rows, name="2026-11-07_rows.jsonl") -> Path:
    d = root / LANE_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _verdict(answer, quotes=None):
    """A model callable answering ``answer`` for every claim, quoting ``quotes[i]`` for the i-th claim."""
    def call(payload):
        n = len(payload["claims"])
        return {"claims": [answer(i) for i in range(n)]}
    return call


def _supported(i):
    return {"verdict": "supported", "evidence_quote": "AAA raised guidance"}


def test_null_duplicate_out_of_range_and_count_disagreement_are_each_reported(tmp_path):
    _write(tmp_path, [
        _row(),
        _row(),                                              # duplicate natural key
        _row(symbol="BBB", summary=None),                     # null required field
        _row(symbol="CCC", confidence=1.7),                   # out of range
        _row(symbol="DDD", source_count=3),                   # declares 3 sources, carries 1
    ])
    result = acc.check_target(_target(claim_field=None), tmp_path, now=NOW)
    kinds = sorted(f["kind"] for f in result["findings"])
    assert kinds == ["count_disagrees", "duplicate_key", "null_field", "out_of_range"], kinds
    assert result["verdict"] == "FAIL"
    assert result["checked"] == 5


def test_a_stale_artifact_is_information_not_a_failing_finding(tmp_path):
    _write(tmp_path, [_row(as_of=NOW - timedelta(days=3))])
    result = acc.check_target(_target(claim_field=None), tmp_path, now=NOW)
    assert [f["kind"] for f in result["findings"]] == ["stale"]
    assert result["verdict"] == "PASS", "an old artifact is a lane question, not a data defect"


def test_a_missing_artifact_is_a_failing_finding_with_no_records_read(tmp_path):
    result = acc.check_target(_target(), tmp_path, now=NOW)
    assert result["verdict"] == "FAIL" and result["checked"] == 0
    assert result["findings"][0]["kind"] == "missing_artifact"


def test_verbatim_supported_claims_pass_and_the_quote_is_recorded(tmp_path):
    _write(tmp_path, [_row(summary="AAA raised guidance.")])
    result = acc.check_target(_target(), tmp_path, now=NOW, model=_verdict(_supported))
    assert result["verdict"] == "PASS"
    assert result["claims"] == [{"record": 0, "key": f"AAA|{NOW.isoformat()}", "claim": "AAA raised guidance.",
                                 "verdict": "supported", "quote": "AAA raised guidance"}]


def test_an_invented_quote_is_a_hallucination_whatever_the_model_claimed(tmp_path):
    _write(tmp_path, [_row()])
    model = _verdict(lambda i: {"verdict": "supported", "evidence_quote": "AAA beat earnings by 40%"})
    result = acc.check_target(_target(), tmp_path, now=NOW, model=model)
    assert [(c["verdict"], c["why"]) for c in result["claims"]] == [("HALLUCINATION", "evidence_not_verbatim")]
    assert result["verdict"] == "FAIL" and result["claim_verdicts"]["disputed"] == 1


def test_a_refuted_claim_with_a_real_quote_fails_the_target(tmp_path):
    _write(tmp_path, [_row(summary="AAA cut guidance.")])   # the stored source says it RAISED it
    model = _verdict(lambda i: {"verdict": "refuted", "evidence_quote": "AAA raised guidance"})
    result = acc.check_target(_target(), tmp_path, now=NOW, model=model)
    assert result["claims"][0]["verdict"] == "refuted"
    assert result["verdict"] == "FAIL", "prose the stored sources contradict must never grade green"


def test_no_model_and_a_malformed_answer_are_unverifiable_never_a_pass(tmp_path):
    _write(tmp_path, [_row()])
    without = acc.check_target(_target(), tmp_path, now=NOW)
    assert [(c["verdict"], c["why"]) for c in without["claims"]] == [("unverifiable", "model_unavailable")]
    assert without["verdict"] == "UNVERIFIABLE"
    cases = [
        ({"claims": [{"verdict": "true", "evidence_quote": "AAA raised guidance"}]}, "verdict_not_in_vocabulary"),
        ({"claims": [{"verdict": "supported"}]}, "no_evidence_quote"),
        ({"claims": []}, "model_did_not_answer"),
        ({"claims": [{"verdict": "supported", "evidence_quote": "   "}]}, "no_evidence_quote"),
    ]
    for answer, why in cases:
        result = acc.check_target(_target(), tmp_path, now=NOW, model=lambda payload, a=answer: a)
        assert (result["claims"][0]["verdict"], result["claims"][0]["why"]) == ("unverifiable", why), why


def test_a_model_that_raises_is_recorded_as_evidence_and_the_run_survives(tmp_path):
    _write(tmp_path, [_row(), _row(symbol="BBB")])

    def boom(payload):
        raise RuntimeError("model_unavailable:ManualApprovalRequired")

    result = acc.check_target(_target(), tmp_path, now=NOW, model=boom)
    assert result["checked"] == 2
    assert {c["why"] for c in result["claims"]} == {"model_unavailable:ManualApprovalRequired"}
    assert result["verdict"] == "UNVERIFIABLE"


def test_claim_free_records_are_skipped_and_the_cap_is_reported_not_silent(tmp_path):
    rows = [_row(symbol=f"S{i:02d}") for i in range(10)]
    rows.append(_row(symbol="NOCAT", catalyst_type="no_clear_catalyst"))
    _write(tmp_path, rows)
    result = acc.check_target(_target(claim_skip_when={"catalyst_type": ["no_clear_catalyst"]},
                                      max_claim_records=3), tmp_path, now=NOW)
    assert (result["claim_records"], result["claim_records_skipped"]) == (3, 7)
    assert sum(1 for c in result["claims"] if c["key"].startswith("NOCAT")) == 0


def test_three_claims_at_most_are_taken_per_record(tmp_path):
    _write(tmp_path, [_row(summary="One. Two. Three. Four.")])
    result = acc.check_target(_target(), tmp_path, now=NOW)
    assert [c["claim"] for c in result["claims"]] == ["One.", "Two.", "Three."]


def test_the_lane_writes_verdicts_and_a_v2_receipt_with_one_row_per_target(tmp_path):
    _write(tmp_path, [_row()])
    cfg = tmp_path / "targets.json"
    cfg.write_text(json.dumps({"schema": acc.TARGETS_SCHEMA, "targets": [
        _target(id="lane-a"), _target(id="lane-missing", path="data/absent")]}))
    assert lane.main(["--no-model", "--targets", str(cfg), "--state-root", str(tmp_path)]) == 0
    doc = json.loads(acc.verdicts_path(tmp_path).read_text())
    assert (doc["schema"], doc["counts"]["targets"], doc["counts"]["missing_artifacts"]) == (acc.SCHEMA, 2, 1)
    assert doc["verdict"] == "FAIL", "a target whose artifact is missing fails the document"
    receipt = json.loads((tmp_path / "data/runtime/ai-claim-check_last.json").read_text())
    assert receipt["schema"] == "LaneRunReceipt@v2" and receipt["status"] == "ok"
    assert (receipt["produced_count"], receipt["attempted_count"]) == (2, 2)
    assert receipt["skipped_reasons"] == {"missing_artifact": 1} and receipt["empty_reason"] is None
    written = tmp_path / acc.VERDICTS_FILE
    assert receipt["output_evidence"][0]["sha256"] == acc.sha256_file(written)


def test_dry_run_reads_and_writes_nothing(tmp_path, capsys):
    _write(tmp_path, [_row()])
    cfg = tmp_path / "targets.json"
    cfg.write_text(json.dumps({"schema": acc.TARGETS_SCHEMA, "targets": [_target()]}))
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert lane.main(["--dry-run", "--targets", str(cfg), "--state-root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (out["mode"], out["targets"], out["readable"]) == ("dry_run", 1, 1)
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before, "a dry run writes nothing"


def test_an_unusable_targets_file_is_a_typed_failure_not_a_green_run(tmp_path):
    cfg = tmp_path / "targets.json"
    cfg.write_text(json.dumps({"schema": "SomethingElse", "targets": []}))
    assert lane.main(["--targets", str(cfg), "--state-root", str(tmp_path)]) == 2
    receipt = json.loads((tmp_path / "data/runtime/ai-claim-check_last.json").read_text())
    assert (receipt["status"], receipt["empty_reason"], receipt["attempted_count"]) == ("failed", "targets_unusable", 0)


def test_a_target_with_no_records_is_empty_not_produced(tmp_path):
    (tmp_path / LANE_DIR).mkdir(parents=True)
    (tmp_path / LANE_DIR / "2026-11-07_rows.jsonl").write_text("", encoding="utf-8")
    cfg = tmp_path / "targets.json"
    cfg.write_text(json.dumps({"schema": acc.TARGETS_SCHEMA, "targets": [_target(claim_field=None)]}))
    assert lane.main(["--no-model", "--targets", str(cfg), "--state-root", str(tmp_path)]) == 0
    receipt = json.loads((tmp_path / "data/runtime/ai-claim-check_last.json").read_text())
    assert (receipt["produced_count"], receipt["attempted_count"], receipt["status"]) == (1, 1, "ok")
    assert json.loads(acc.verdicts_path(tmp_path).read_text())["targets"][0]["checked"] == 0
