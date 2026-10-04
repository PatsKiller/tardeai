"""AlertQuality@v1 has a real producer (operator decision 2026-10-03).

score_alerts now scores what the delivery ledger and the comms editor recorded;
scripts/score_alert_quality.py runs it per completed ET day and persists one row
through the operator-artifact store. An unreadable ledger is UNAVAILABLE, never 0.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.score_alert_quality as saq  # noqa: E402
from scripts.lib.cio_r13_institution import score_alerts  # noqa: E402


def _d(status, pid=None, event_type="operator_message", producer="telegram_alert.send_telegram", **kw):
    return {"status": status, "provider_message_id": pid, "event_type": event_type, "producer": producer,
            "subject_guid": kw.get("subject_guid"), "decision_ids": kw.get("decision_ids", [])}


def _r(fp, ts, send, held=None, dup=None, syms=(), mode="live"):
    return {"fingerprint": fp, "ts": ts, "send": send, "held_reason": held, "duplicate_of": dup, "mode": mode,
            "cio_disagreements": [{"symbol": s} for s in syms]}


def test_delivery_counts_separate_confirmed_from_claimed():
    q = score_alerts(deliveries=[
        _d("SENT", "55441"), _d("LEGACY_DELIVERED", "55442"), _d("LEGACY_DELIVERED"), _d("SUPPRESSED"),
        _d("RESERVED"), _d("RESERVED", event_type="callback_query", producer="telegram_inbound"),
    ], editor_receipts=[], day="2026-10-02")
    d = q["delivery"]
    assert q["schema"] == "AlertQuality@v1" and q["basis"] == "ledgers"
    assert (d["attempts"], d["delivered_confirmed"], d["delivered_unconfirmed"], d["suppressed"], d["in_flight"]) == (5, 2, 1, 1, 1)
    assert d["confirmed_delivery_rate"] == 0.4
    assert "callback_query" not in q["by_event_type"]


def test_empty_day_is_unmeasured_not_zero():
    q = score_alerts(deliveries=[], editor_receipts=[], day="2026-10-02")
    assert q["delivery"]["confirmed_delivery_rate"] is None
    assert q["editor"]["false_positive_cio_hold_rate"] is None
    assert q["outcomes"]["status"].startswith("UNMEASURED")


def test_editor_counts_messages_once_and_flags_single_letter_holds():
    receipts = [
        _r("a", "2026-10-02T14:00:01", True), _r("a", "2026-10-02T14:00:01.5", True),   # two chats, one message
        _r("b", "2026-10-02T15:00:00", False, dup="x"),
        _r("c", "2026-10-02T16:00:00", False, held="cio_disagreement", syms=("B",)),
        _r("d", "2026-10-02T16:05:00", False, held="cio_disagreement", syms=("NVDA",)),
        _r("e", "2026-10-02T17:00:00", False, held="cio_disagreement", syms=("D",), mode="shadow"),
    ]
    e = score_alerts(deliveries=[], editor_receipts=receipts, day="2026-10-02")["editor"]
    assert (e["messages"], e["sent"], e["held_duplicate"], e["held_cio_disagreement"]) == (4, 1, 1, 2)
    assert e["false_positive_cio_holds"] == 1 and e["false_positive_cio_hold_rate"] == 0.5


def test_outcomes_are_scored_only_for_decision_attached_alerts():
    q = score_alerts(deliveries=[_d("SENT", "1", decision_ids=["dec_a"]), _d("SENT", "2", decision_ids=["dec_b"])],
                     editor_receipts=[], decision_outcomes={"dec_a": {"verdict": "favourable"}}, day="2026-10-02")
    o = q["outcomes"]
    assert (o["favourable"], o["pending"], o["favourable_rate"], o["status"]) == (1, 1, 1.0, "MEASURED")


def test_rows_mode_still_works():
    q = score_alerts([{"notification_class": "SUPPRESSED"}, {"status": "DELIVERED"}])
    assert q["suppression_rate"] == 0.5


def _receipts_file(tmp_path: Path, rows) -> Path:
    p = tmp_path / "receipts.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def test_unreadable_ledger_leaves_the_day_unavailable(tmp_path):
    out = saq.score_day(date(2026, 10, 2), query=lambda *a, **k: None,
                        receipts_path=_receipts_file(tmp_path, []), checkpoints_path=tmp_path / "none.jsonl")
    assert out["status"] == "UNAVAILABLE" and "delivery ledger" in out["reason"]
    out = saq.score_day(date(2026, 10, 2), query=lambda *a, **k: [], receipts_path=tmp_path / "missing.jsonl",
                        checkpoints_path=tmp_path / "none.jsonl")
    assert out["status"] == "UNAVAILABLE" and "editor receipts" in out["reason"]


def test_score_day_reads_decision_ids_and_checkpoint_outcomes(tmp_path):
    rows = [{"status": "SENT", "provider_message_id": "9", "producer": "p", "event_type": "operator_message",
             "subject_guid": None, "payload_text": '{"decision_id": "dec_up"}'}]
    cps = tmp_path / "cp.jsonl"
    cps.write_text(json.dumps({"decision_id": "dec_up", "recommendation": "BUY", "outcome_id": "o", "change_pct": 3.1}) + "\n",
                   encoding="utf-8")
    receipts = _receipts_file(tmp_path, [_r("a", "2026-10-02T15:00:00+00:00", True)])
    q = saq.score_day(date(2026, 10, 2), query=lambda *a, **k: rows, receipts_path=receipts, checkpoints_path=cps)
    assert q["delivery"]["decision_attached_delivered"] == 1
    assert q["outcomes"]["favourable"] == 1 and q["outcomes"]["status"] == "MEASURED"
    assert q["editor"]["sent"] == 1


def test_apply_persists_one_row_per_completed_day_and_writes_the_receipt(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(saq, "score_day", lambda day: score_alerts(deliveries=[], editor_receipts=[], day=day.isoformat()))
    monkeypatch.setattr(saq, "record_alert_quality", lambda row, **kw: calls.append(kw) or {"written": True})
    monkeypatch.setattr(saq, "RECEIPT", tmp_path / "alert_quality_last.json")
    today = datetime.now(saq.ET).date().isoformat()
    assert saq.main(["--apply", "--days", "2"]) == 0
    assert [c["artifact_id"] for c in calls] == sorted(c["artifact_id"] for c in calls) and len(calls) == 2
    assert all(c["evidence_class"] == "LEDGER_DERIVED" for c in calls)
    assert json.loads((tmp_path / "alert_quality_last.json").read_text())["days"]
    calls.clear()
    assert saq.main(["--apply", "--day", today]) == 0
    assert calls == []  # an incomplete day is never written
