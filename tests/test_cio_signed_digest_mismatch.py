"""Signed CIO action links must apply when the catalog is decision_id-only."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.api_v3_cio import _digests_match, _VALID_DISPOSITIONS, post_decision_disposition
from scripts.lib.cio_material_scan import _canonical_decisions


def test_digest_capable_requires_exact_pair():
    # LEGACY decision-id-only catalog rows (empty digest) still accept token
    # hashes — keyed by decision_id, not by exact generated content.
    assert _digests_match("", "") is True
    assert _digests_match("1e855bdb25f63ceb", "") is True
    # DIGEST_CAPABLE rows (non-empty catalog digest) require an exact pair;
    # a missing supplied digest fails closed (409) — no empty/self-signed bypass.
    assert _digests_match("", "abc") is False
    assert _digests_match("1e855bdb25f63ceb", "1e855bdb25f63ceb") is True
    assert _digests_match("1e855bdb25f63ceb", "deadbeef") is False


def test_rate_is_a_valid_disposition():
    assert "rate" in _VALID_DISPOSITIONS
    assert {"ack", "defer", "done", "reject", "rate"} <= _VALID_DISPOSITIONS


def test_canonical_decisions_copy_catalog_digests_not_invent():
    plan = {
        "position_decisions": [{
            "symbol": "SCHD",
            "stance": "Trim",
            "stance_code": "TRIM",
            "decision_id": "dec_5866156741de9046",
            "current_value_usd": 226513.15,
            "recommended_delta_usd": -44334.57,
            "why_now": "Advisory TRIM — SCHD concentration above single-name fire.",
            "decision_input_digest": "",
            "decision_evidence_digest": "",
            "act_now": False,
            "action_label": "STALE_REFRESH_REQUIRED",
        }]
    }
    got = _canonical_decisions(plan)
    assert got
    assert got[0]["decision_input_digest"] == ""
    assert got[0]["decision_evidence_digest"] == ""


def test_reject_applies_when_catalog_has_no_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.api_v3_cio.load_known_decision_catalog",
        lambda: {
            "dec_5866156741de9046": {
                "decision_id": "dec_5866156741de9046",
                "decision_input_digest": "",
                "decision_evidence_digest": "",
                "symbol": "SCHD",
                "action": "Trim",
            }
        },
    )
    monkeypatch.setattr("scripts.api_v3_cio._DISPOSITION_PATH", tmp_path / "disp.jsonl")
    res = post_decision_disposition("dec_5866156741de9046", {
        "decision_id": "dec_5866156741de9046",
        "disposition": "reject",
        "decision_input_digest": "",
        "decision_evidence_digest": "1e855bdb25f63ceb",
    })
    assert res.get("ok") is True, res
    assert res["disposition"]["disposition"] == "reject"
