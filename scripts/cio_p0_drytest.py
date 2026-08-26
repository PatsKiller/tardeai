#!/usr/bin/env python3
"""Dry-run P0 decision semantics + learning integrity. Never HTTP / Telegram.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    from scripts.lib.cio_alex_telegram import classify_actionability, format_cio_message
    from scripts.lib.cio_decision_semantics import (
        aggregate_position_decisions,
        assert_digest_capable,
        canonical_decision_digests,
    )
    from scripts.lib.cio_production_case import (
        DEFAULT_PATH,
        open_case_from_decision,
        record_disposition,
        record_note,
        record_outcome,
        materialize_case,
        score_case_darwin,
        case_id_for,
    )
    from scripts.lib.cio_nightly_reflection import reflect

    stale_trim = {
        "decision_id": "dec_dry_schd_p0",
        "symbol": "SCHD",
        "action": "TRIM",
        "stance_code": "TRIM",
        "why_now": "concentration above fire",
        "act_now": False,
        "action_label": "STALE_REFRESH_REQUIRED",
        "recommended_delta_usd": -44000,
        "operator_disposition": "REJECT",
        "operator_note": "making money and a staple anchor",
    }
    cls = classify_actionability(stale_trim)
    body = format_cio_message(stale_trim)
    assert cls["standing_recommendation"] == "TRIM"
    assert cls["current_action"] in {"WAIT", "REVALIDATE"}
    assert cls["act_now"] is False
    assert "MY CALL" not in body
    assert "STANDING VIEW" in body
    assert "CURRENT ACTION" in body

    rows = aggregate_position_decisions([
        {"symbol": "SCHD", "name": "Schwab US Dividend Equity ETF",
         "account": "ira", "current_value_usd": 100000, "recommended_delta_usd": -10000,
         "cio_stance": "TRIM", "why_now": "concentration fire"},
        {"symbol": "SCHD", "name": "Schwab US Dividend Equity ETF",
         "account": "taxable", "current_value_usd": 126000, "recommended_delta_usd": -34000,
         "cio_stance": "TRIM", "why_now": "concentration fire"},
    ], portfolio_value=1_282_947.74)
    assert rows, "aggregate empty"
    assert_digest_capable(rows[0])
    digs = canonical_decision_digests(
        rows[0]["symbol"], rows[0].get("stance_code") or "TRIM",
        rows[0]["recommended_delta_usd"], rows[0],
    )
    assert digs["input"] and digs["evidence"]

    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "cases.jsonl"
    import scripts.lib.cio_production_case as cs
    import scripts.lib.cio_nightly_reflection as rf
    old_cs, old_rf = cs.DEFAULT_PATH, rf.OUT_PATH
    cs.DEFAULT_PATH = tmp
    rf.OUT_PATH = tmp.parent / "reflect.json"
    try:
        dec = {
            "decision_id": "dec_dry_schd_p0",
            "symbol": "SCHD",
            "action": "TRIM",
            "decision_input_digest": digs["input"],
            "decision_evidence_digest": digs["evidence"],
            "why_now": "concentration fire",
        }
        opened = open_case_from_decision(dec, research={"decision_use_audit": {"signature_ok": True, "status": "OK"}})
        cid = opened["case_id"]
        assert cid == case_id_for("dec_dry_schd_p0", digs["input"], digs["evidence"])
        record_disposition("dec_dry_schd_p0", {"disposition": "reject", "note": "staple anchor"},
                           input_digest=digs["input"], evidence_digest=digs["evidence"])
        record_note("dec_dry_schd_p0", "making money and a staple anchor",
                    input_digest=digs["input"], evidence_digest=digs["evidence"])
        rec_out = record_outcome(
            "dec_dry_schd_p0",
            {"outcome_status": "PENDING_MATURATION"},
            input_digest=digs["input"], evidence_digest=digs["evidence"],
        )
        joined = materialize_case(cid)
        assert joined["decision_id"] == "dec_dry_schd_p0"
        unmatured = score_case_darwin(joined)
        assert unmatured.get("darwin_status") == "NOT_MATURED" or unmatured.get("eligible") is False
        ref = reflect(cases_path=tmp, out_path=tmp.parent / "reflect.json")
        assert ref["auto_promotions"] == 0
        assert ref["mutates_production"] is False
    finally:
        cs.DEFAULT_PATH = old_cs
        rf.OUT_PATH = old_rf

    print(json.dumps({
        "ok": True,
        "dry_run": True,
        "authority": "READ_ONLY_ADVISORY",
        "standing": cls["standing_recommendation"],
        "current_action": cls["current_action"],
        "act_now": cls["act_now"],
        "message_has_my_call": "MY CALL" in body,
        "digests_nonempty": True,
        "case_id": cid,
        "darwin_unmatured": unmatured.get("darwin_status"),
        "reflect_auto_promotions": 0,
        "broker_calls": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
