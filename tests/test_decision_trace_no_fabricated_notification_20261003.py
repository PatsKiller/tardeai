"""A decision trace never claims a notification outcome it did not observe.

emit_decision_payload stamped every trace with the literal
``notification={"sent": False, "channel": None}`` -- all 2,509 natural decisions on
prod read "not sent" whether or not anything was ever evaluated. The key is now
omitted; a reader that needs a notification outcome must find a real record.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.agent_decision_payload import build_decision_payload, emit_decision_payload  # noqa: E402
from scripts.lib.agent_run_trace import trace_digest, validate_trace  # noqa: E402


def test_emitted_trace_and_payload_carry_no_fabricated_notification(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    path = tmp_path / "agent_run_traces.jsonl"
    payload = build_decision_payload(decision_id="dec_adv_X_1", wake_id="wake_x", symbol="XYZ",
                                     surface="advisory", current_action="HOLD")
    out = emit_decision_payload(payload, flags={"AGENT_DECISION_PAYLOAD": 1}, path=path)
    assert out["emitted"] is True, out

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    trace = rows[0]
    assert "notification" not in trace
    assert "notification" not in trace["decision"]
    assert '"sent"' not in json.dumps(trace)
    ok, errors = validate_trace(trace)
    assert ok, errors
    assert trace_digest(trace).startswith("trh_")
