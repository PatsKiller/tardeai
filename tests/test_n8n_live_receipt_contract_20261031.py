"""Two lanes admitted live on 2026-10-30 could never pass the n8n output check (breakers opened the same day).

* conflict-resolver: allowlist ``output_receipt: v2`` but its health contract had no ``expected_output`` rule, so
  every LIVE run ended RUN_FAILED output_unverifiable (``rule_missing``).
* cio-prospect-shadow: wrote a plain receipt dict, never the per-attempt LaneRunReceipt@v2 copy, so every LIVE run
  ended RUN_FAILED output_unverifiable (``attempt_receipt_missing``).
Hermetic: tmp state root, synthetic build doc, no DB, no n8n.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scripts.cio_prospect_shadow_build as shadow
from scripts import n8n_run_executor as ex
from scripts.lib import n8n_output_verdict as ov

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def _rules():
    return ex.parse_expected_outputs((ROOT / "config/n8n_health_contracts.json").read_bytes())


def _allow():
    return ex.parse_allowlist((ROOT / "config/n8n_run_allowlist.json").read_bytes())


def test_every_live_enforced_lane_has_an_expected_output_rule():
    rules, allow = _rules(), _allow()
    enforced = sorted(lane for lane, e in allow.items() if e.get("output_receipt") == "v2")
    missing = [lane for lane in enforced if lane not in rules]
    assert "conflict-resolver" in enforced
    assert missing == [], f"output_receipt v2 lanes without an expected_output rule: {missing}"


def test_prospect_shadow_live_run_writes_a_verifiable_attempt_receipt(tmp_path, monkeypatch):
    run_id = "d:cio-prospect-shadow:live:20261031T1000"
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    monkeypatch.setenv("TRADEAI_CODE_SHA", SHA)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    doc = {"counts": {"prospects": 3, "conflicts": 1}, "store_status": {"mode": "shadow"}, "prospects": []}
    monkeypatch.setattr(shadow, "persist_company_facts", lambda *a, **k: {"written": 0}, raising=False)
    monkeypatch.setattr(shadow.builder, "build", lambda *a, **k: doc)
    monkeypatch.setattr(shadow.builder, "compare", lambda *a, **k: {"summary": {}})
    monkeypatch.setattr(shadow, "summary", lambda d: {"prospects": d["counts"]["prospects"]})
    monkeypatch.setattr(shadow, "_watch_list", lambda *_: ([], "fixture"))
    started = datetime.now(timezone.utc) - timedelta(seconds=1)
    rc = shadow.main(["--write-shadow", "--state-root", str(tmp_path)])
    finished = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert rc == 0
    attempt = tmp_path / "data/runtime/lane_attempts/cio-prospect-shadow" / (run_id.replace(":", "_") + ".json")
    assert attempt.exists(), "no per-attempt receipt: the executor reports attempt_receipt_missing"
    rec = json.loads(attempt.read_text())
    verdict = ov.evaluate(
        _rules()["cio-prospect-shadow"],
        rec,
        run_id=run_id,
        lane_id="cio-prospect-shadow",
        mode="live",
        attempt=1,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        code_sha=SHA,
    )
    assert verdict["verdict"] == "produced", verdict
    last = json.loads((tmp_path / "data/runtime/cio-prospect-shadow_last.json").read_text())
    assert last["produced_count"] == 3 and last["summary"]["conflicts"] == 1
