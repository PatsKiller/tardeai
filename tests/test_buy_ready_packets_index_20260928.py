"""Entry-alert index (2026-09-28): the Re-Entry page lane over the runner's buy-ready packets.
Hermetic: packets written to tmp_path in the served BuyReadyInstitutionalPacket@v2 shape."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib.buy_ready_packets_index import desk_disposition, index_packets, reward_risk, zone_position  # noqa: E402

NOW = datetime(2026, 9, 28, 17, 30, tzinfo=timezone.utc)


def _packet(sym, state, price, lo, hi, stop, target, rr, saved, alt_status="OPTIONS_ALT_NONE", alt_reason="NONE_QUALIFIED", qualified=0):
    return {"schema": "BuyReadyInstitutionalPacket@v2", "symbol": sym, "saved_at": saved,
            "equity": {"symbol": sym, "state": state, "price": price, "quote_age_h": 1.7, "entry_low": lo, "entry_high": hi,
                       "stop": stop, "target": target, "rr": rr, "plan_source": "reentry_desk", "catalyst": "Topline beat"},
            "options_alt": {"status": alt_status, "reason": alt_reason, "detail": "LIQUIDITY: spread 150% > 12%", "strategy": None},
            "options_alternatives": {"status": alt_reason, "chain_as_of": "2026-09-28T13:00:09+00:00",
                                     "alternatives": [{"strategy": "debit_call_vertical", "qualified": bool(qualified)}]},
            "cio_verdict": {"verdict": "MODIFY_OPTIONS_WANTED", "token": "MODIFY", "rationale": "elevated ATR"},
            "cio_review": {"status": "DRY_RUN", "mode": "dry", "as_of": "2026-09-28T13:00:11+00:00"}}


def test_zone_and_reward_risk_arithmetic():
    assert zone_position(2.155, 2.15, 2.22) == {"position": "in_zone", "distance_pct": 0.0}
    assert zone_position(73.32, 62.0, 66.0) == {"position": "above", "distance_pct": 11.1}
    assert zone_position(60.0, 62.0, 66.0) == {"position": "below", "distance_pct": 3.2}
    assert zone_position(None, 62.0, 66.0)["position"] == "unknown"
    assert reward_risk(2.65, 2.155, 2.07) == 5.82          # the alert's printed figure, at the current quote
    assert reward_risk(2.65, 2.22, 2.07) == 2.87           # the plan figure, at the zone top
    assert reward_risk(90.0, 73.32, 60.0) == 1.25 and reward_risk(90.0, 55.0, 60.0) is None


def test_index_lists_states_in_priority_with_zone_and_both_ratios(tmp_path):
    d = tmp_path / "pk"; d.mkdir()
    (d / "AXTI.json").write_text(json.dumps(_packet("AXTI", "ENTRY_NEAR", 73.32, 62.0, 66.0, 60.0, 90.0, 4.07, (NOW - timedelta(hours=3)).isoformat())))
    (d / "PEW.json").write_text(json.dumps(_packet("PEW", "BUY_READY", 2.155, 2.15, 2.22, 2.07, 2.65, 2.87, (NOW - timedelta(hours=4.5)).isoformat())))
    (d / "OLD.json").write_text(json.dumps(_packet("OLD", "BUY_READY", 10, 9, 11, 8, 14, 2.0, (NOW - timedelta(days=4)).isoformat())))
    (d / "junk.json").write_text("{not json")
    proposals = [{"id": "opt_axti_1", "symbol": "AXTI", "strategy": "long_call", "approvable": False, "severity": "blocked"}]
    dropped = [{"symbol": "PEW", "entry_state": "BUY_READY", "reason": "EDGE_BELOW", "edge_attempted": True}]
    out = index_packets(d, proposals=proposals, dropped=dropped, now=NOW)
    assert out["schema"] == "BuyReadyPacketIndex@v2" and out["count"] == 2 and out["counts"] == {"BUY_READY": 1, "ENTRY_NEAR": 1}
    assert [r["symbol"] for r in out["rows"]] == ["PEW", "AXTI"]                      # BUY_READY first
    assert out["stale"][0]["symbol"] == "OLD" and out["errors"] == ["junk.json: JSONDecodeError"]
    pew, axti = out["rows"]
    assert pew["zone"]["position"] == "in_zone" and pew["rr_plan"] == 2.87 and pew["rr_plan_entry"] == 2.22
    assert pew["rr_at_quote"] == 5.82 and pew["rr_at_quote_entry"] == 2.155
    assert pew["desk"] == {"status": "not_built", "reason": "EDGE_BELOW", "entry_state": "BUY_READY", "detail": {"edge_attempted": True}}
    assert axti["zone"] == {"position": "above", "distance_pct": 11.1} and axti["rr_at_quote"] == 1.25 and axti["rr_plan"] == 4.07
    assert axti["desk"]["status"] == "proposal" and axti["desk"]["proposal_id"] == "opt_axti_1"
    # repair 2026-09-28: the file's own status is never served; on a build without packet_view the verdict fails closed
    assert pew["options_alt"]["status"] in ("PACKET_UNVERIFIED", "STALE_PRE_FIX") and pew["options_alt"]["qualified_count"] == 0
    assert pew["options_alt"]["considered"] == 1 and pew["options_alt"]["claimed"]["status"] == "OPTIONS_ALT_NONE"
    assert pew["packet_age_h"] == 4.5 and pew["catalyst"] == "Topline beat" and pew["cio_verdict"]["token"] == "MODIFY"


def test_desk_disposition_is_exactly_one_of_three():
    assert desk_disposition("dxcm", [], [])["status"] == "not_in_desk_universe"
    assert desk_disposition("dxcm", [{"symbol": "DXCM", "id": "x"}], [{"symbol": "DXCM", "reason": "EDGE_BELOW"}])["status"] == "proposal"
    assert desk_disposition("dxcm", [], [{"symbol": "DXCM", "reason": "IV_UNKNOWN"}]) == {"status": "not_built", "reason": "IV_UNKNOWN", "entry_state": None, "detail": {}}


def test_missing_directory_is_empty_not_an_error(tmp_path):
    out = index_packets(tmp_path / "nowhere", now=NOW)
    assert out["count"] == 0 and out["rows"] == [] and out["errors"] == []


def test_index_preserves_portfolio_aware_action_context(tmp_path):
    d = tmp_path / "pk"; d.mkdir()
    packet = _packet("AXTI", "ENTRY_NEAR", 78.17, 71.5, 74.5, 67.5, 96.5, 3.14,
                     (NOW - timedelta(hours=1)).isoformat())
    packet.update({"decision_action": "WAIT_FOR_ENTRY_ZONE", "first_hard_block": None,
                   "time_horizon": None,
                   "ownership_context": {"held": True, "shares": 100.0,
                                          "pct_of_total_book": 0.62,
                                          "pct_of_invested_capital": 2.18,
                                          "ips_single_name_limit_pct": 8.0},
                   "cio_review_status": "UNREVIEWED", "cio_review_id": None})
    (d / "AXTI.json").write_text(json.dumps(packet))
    row = index_packets(d, now=NOW)["rows"][0]
    assert row["ownership_context"]["held"] is True
    assert row["ownership_context"]["shares"] == 100.0
    assert row["decision_action"] == "WAIT_FOR_ENTRY_ZONE"
    assert row["cio_review"]["status"] == "UNREVIEWED"
