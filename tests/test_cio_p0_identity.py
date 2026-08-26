"""P0-3 — aggregated decisions always carry input + evidence digests.

New rows are DIGEST_CAPABLE (exact match required). Empty catalog digests
remain LEGACY_DECISION_ID_ONLY (compat). No broker / Telegram / deploy.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import api_v3_cio as cio  # noqa: E402
from scripts.lib import cio_capital_plan as cp  # noqa: E402
from scripts.lib import cio_decision_semantics as ds  # noqa: E402

DID = "dec_aaaabbbbccccdddd"
IN_DIGEST = "11111111111111111111111111111111"
EV_DIGEST = "22222222222222222222222222222222"
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _schd_pair() -> list[dict]:
    """Two-account SCHD-like pair (IRA + taxable) with a TRIM signal."""
    return [
        {
            "symbol": "SCHD",
            "name": "Schwab U.S. Dividend Equity ETF",
            "cio_stance": "TRIM",
            "why_now": "Advisory TRIM — SCHD",
            "current_value_usd": 100_000.0,
            "recommended_delta_usd": -10_000.0,
            "risk": "concentration > cap",
            "account": "schwab_rollover_ira",
        },
        {
            "symbol": "SCHD",
            "name": "Schwab U.S. Dividend Equity ETF",
            "cio_stance": "TRIM",
            "why_now": "Advisory TRIM — SCHD",
            "current_value_usd": 20_000.0,
            "recommended_delta_usd": -2_000.0,
            "risk": "within single-name cap",
            "account": "schwab_taxable",
        },
    ]


@pytest.fixture
def iso_capable(tmp_path, monkeypatch):
    path = tmp_path / "decision_dispositions.jsonl"
    catalog = {
        DID: {
            "decision_id": DID,
            "decision_input_digest": IN_DIGEST,
            "decision_evidence_digest": EV_DIGEST,
            "symbol": "SCHD",
            "account": "schwab_rollover_ira",
            "action": "Trim",
        }
    }
    monkeypatch.setattr(cio, "_DISPOSITION_PATH", path)
    monkeypatch.setattr(cio, "load_known_decision_catalog", lambda: dict(catalog))
    return {"path": path, "catalog": catalog}


@pytest.fixture
def iso_legacy(tmp_path, monkeypatch):
    path = tmp_path / "decision_dispositions.jsonl"
    catalog = {
        DID: {
            "decision_id": DID,
            "decision_input_digest": "",
            "decision_evidence_digest": "",
            "symbol": "SCHD",
            "account": "schwab_rollover_ira",
            "action": "Trim",
        }
    }
    monkeypatch.setattr(cio, "_DISPOSITION_PATH", path)
    monkeypatch.setattr(cio, "load_known_decision_catalog", lambda: dict(catalog))
    return {"path": path, "catalog": catalog}


def test_07_new_aggregated_decision_has_input_digest():
    rows = ds.aggregate_position_decisions(_schd_pair(), portfolio_value=1_000_000.0)
    assert len(rows) == 1
    ds.assert_digest_capable(rows[0])
    inp = rows[0]["decision_input_digest"]
    assert inp and _HEX32.match(inp)
    cards = ds.sanitize_decisions_now(_schd_pair(), portfolio_value=1_000_000.0)
    assert cards
    assert cards[0]["decision_input_digest"]
    assert cards[0]["decision_input_digest"] == inp


def test_08_new_aggregated_decision_has_evidence_digest():
    rows = ds.aggregate_position_decisions(_schd_pair(), portfolio_value=1_000_000.0)
    assert len(rows) == 1
    ds.assert_digest_capable(rows[0])
    ev = rows[0]["decision_evidence_digest"]
    assert ev and _HEX32.match(ev)
    assert ev != rows[0]["decision_input_digest"]
    cards = ds.sanitize_decisions_now(_schd_pair(), portfolio_value=1_000_000.0)
    assert cards
    assert cards[0]["decision_evidence_digest"] == ev


def test_09_wrong_input_digest_mismatch_when_digest_capable(iso_capable):
    known = iso_capable["catalog"][DID]
    assert cio.classify_decision_identity(known) == cio.IDENTITY_DIGEST_CAPABLE
    res = cio.post_decision_disposition(DID, {
        "disposition": "ack",
        "decision_id": DID,
        "decision_input_digest": "deadbeef" * 4,
        "decision_evidence_digest": EV_DIGEST,
    })
    assert res["ok"] is False
    assert res["error"] == "digest_mismatch"
    assert res["field"] == "decision_input_digest"
    assert res.get("decision_identity") == cio.IDENTITY_DIGEST_CAPABLE


def test_10_wrong_evidence_digest_fails(iso_capable):
    res = cio.post_decision_disposition(DID, {
        "disposition": "ack",
        "decision_id": DID,
        "decision_input_digest": IN_DIGEST,
        "decision_evidence_digest": "cafebabe" * 4,
    })
    assert res["ok"] is False
    assert res["error"] == "digest_mismatch"
    assert res["field"] == "decision_evidence_digest"


def test_11_empty_catalog_digests_legacy_compat(iso_legacy):
    known = iso_legacy["catalog"][DID]
    assert cio.classify_decision_identity(known) == cio.IDENTITY_LEGACY_DECISION_ID_ONLY
    assert cio.new_decision_digestless_rejected(known) is True
    res = cio.post_decision_disposition(DID, {
        "disposition": "ack",
        "decision_id": DID,
        "decision_input_digest": "anythingatall0123456789abcdef01",
        "decision_evidence_digest": "",
    })
    assert res["ok"] is True, res
    entry = res["disposition"]
    assert entry["identity_class"] == cio.IDENTITY_LEGACY_DECISION_ID_ONLY
    assert entry["decision_identity"] == cio.IDENTITY_LEGACY_DECISION_ID_ONLY
    assert entry["authority"] == "READ_ONLY_ADVISORY"


def test_exact_match_both_digests_pass(iso_capable):
    res = cio.post_decision_disposition(DID, {
        "disposition": "ack",
        "decision_id": DID,
        "decision_input_digest": IN_DIGEST,
        "decision_evidence_digest": EV_DIGEST,
        "symbol": "SCHD",
        "action": "Trim",
    })
    assert res["ok"] is True, res
    entry = res["disposition"]
    assert entry["decision_input_digest"] == IN_DIGEST
    assert entry["decision_evidence_digest"] == EV_DIGEST
    assert entry["identity_class"] == cio.IDENTITY_DECISION_ID
    assert entry["decision_identity"] == cio.IDENTITY_DIGEST_CAPABLE


def test_aggregate_schd_two_account_pair_yields_digests():
    rows = ds.aggregate_position_decisions(_schd_pair(), portfolio_value=1_000_000.0)
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "SCHD"
    assert row["account_count"] == 2
    assert abs(float(row["current_value_usd"]) - 120_000.0) < 0.02
    ds.assert_digest_capable(row)
    expected = ds.canonical_decision_digests(
        row["symbol"], row["stance_code"], row["recommended_delta_usd"], row,
    )
    assert row["decision_input_digest"] == expected["input"]
    assert row["decision_evidence_digest"] == expected["evidence"]
    # Same recipe as capital-plan (single hash function).
    assert expected["input"] == cp._decision_digest(
        row["symbol"], row["stance_code"], row["recommended_delta_usd"], row,
    )
    assert expected["evidence"] == cp._decision_digest(
        row["symbol"], row["stance_code"], row["recommended_delta_usd"], row,
        extra="evidence",
    )


def test_assert_digest_capable_fails_when_missing():
    with pytest.raises(AssertionError):
        ds.assert_digest_capable({"symbol": "SCHD", "decision_id": DID})
    with pytest.raises(AssertionError):
        ds.assert_digest_capable({
            "symbol": "SCHD",
            "decision_input_digest": IN_DIGEST,
            "decision_evidence_digest": "",
        })


def test_catalog_classifies_without_stripping():
    capable = cio.catalog_from_position_decisions([{
        "decision_id": DID,
        "decision_input_digest": IN_DIGEST,
        "decision_evidence_digest": EV_DIGEST,
        "symbol": "SCHD",
    }])
    assert capable[DID]["decision_input_digest"] == IN_DIGEST
    assert capable[DID]["decision_evidence_digest"] == EV_DIGEST
    assert capable[DID]["decision_identity"] == cio.IDENTITY_DIGEST_CAPABLE
    assert cio.new_decision_digestless_rejected(capable[DID]) is False

    legacy = cio.catalog_from_position_decisions([{
        "decision_id": DID,
        "decision_input_digest": "",
        "decision_evidence_digest": "",
        "symbol": "SCHD",
    }])
    assert legacy[DID]["decision_input_digest"] == ""
    assert legacy[DID]["decision_identity"] == cio.IDENTITY_LEGACY_DECISION_ID_ONLY
    assert cio.new_decision_digestless_rejected(legacy[DID]) is True
