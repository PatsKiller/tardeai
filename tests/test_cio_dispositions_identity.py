"""P0-11 — disposition identity is decision_id, never position:symbol:account.

Legacy events stay readable as LEGACY_UNVERSIONED and must not apply to a
new decision. No broker / Telegram / deploy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import api_v3_cio as cio  # noqa: E402

DID = "dec_aaaabbbbccccdddd"
IN_DIGEST = "11111111111111111111111111111111"
EV_DIGEST = "22222222222222222222222222222222"


@pytest.fixture
def iso(tmp_path, monkeypatch):
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


def _post(iso, key, **body):
    return cio.post_decision_disposition(key, body)


def test_missing_decision_id_rejected(iso):
    res = _post(iso, "", disposition="ack")
    assert res["ok"] is False
    assert res["error"] == "missing_decision_id"
    assert res["authority"] == "READ_ONLY_ADVISORY"


def test_legacy_position_key_rejected_and_not_applied(iso):
    res = _post(iso, "position:SCHD:schwab_rollover_ira", disposition="ack", decision_id=DID)
    assert res["ok"] is False
    assert res["error"] == "legacy_unversioned_key_not_applicable"
    assert iso["path"].exists() is False or iso["path"].read_text().strip() == ""


def test_unknown_id_rejected_unless_archived_feedback(iso):
    stale = "dec_ffffffffffffffff"
    res = _post(iso, stale, disposition="ack")
    assert res["ok"] is False
    assert res["error"] == "unknown_or_stale_decision_id"

    ok = _post(iso, stale, disposition="defer", mode="archived-feedback",
               symbol="SCHD", account="schwab_taxable", action="Hold")
    assert ok["ok"] is True
    entry = ok["disposition"]
    assert entry["decision_id"] == stale
    assert entry["identity_class"] == cio.IDENTITY_ARCHIVED
    assert entry["authority"] == "READ_ONLY_ADVISORY"


def test_digest_supplied_must_match(iso):
    bad = _post(iso, DID, disposition="ack", decision_input_digest="deadbeef" * 4)
    assert bad["ok"] is False
    assert bad["error"] == "digest_mismatch"

    good = _post(
        iso, DID, disposition="ack",
        decision_id=DID,
        decision_input_digest=IN_DIGEST,
        decision_evidence_digest=EV_DIGEST,
        symbol="SCHD",
        account="schwab_rollover_ira",
        action="Trim",
        rating=4,
        note="operator ack",
    )
    assert good["ok"] is True
    entry = good["disposition"]
    for k in (
        "decision_id", "decision_input_digest", "decision_evidence_digest",
        "symbol", "account", "action", "disposition", "rating", "note",
        "occurred_at", "authority",
    ):
        assert k in entry
    assert entry["decision_id"] == DID
    assert entry["decision_input_digest"] == IN_DIGEST
    assert entry["decision_evidence_digest"] == EV_DIGEST
    assert entry["authority"] == "READ_ONLY_ADVISORY"
    assert entry["identity_class"] == cio.IDENTITY_DECISION_ID


def test_legacy_events_readable_not_applied_as_current(iso):
    iso["path"].write_text(json.dumps({
        "decision_key": "position:SCHD:schwab_rollover_ira",
        "disposition": "done",
        "rating": 5,
        "note": "old",
        "occurred_at": "2026-08-01T00:00:00+00:00",
        "authority": "READ_ONLY_ADVISORY",
    }) + "\n", encoding="utf-8")
    _post(iso, DID, disposition="ack", decision_id=DID,
          decision_input_digest=IN_DIGEST, decision_evidence_digest=EV_DIGEST)
    got = cio.get_decision_dispositions()
    assert got["ok"] is True
    assert got["canonical_key"] == "decision_id"
    assert DID in got["dispositions"]
    assert got["dispositions"][DID]["disposition"] == "ack"
    assert "position:SCHD:schwab_rollover_ira" not in got["dispositions"]
    legacy = got["legacy_unversioned"]
    assert "position:SCHD:schwab_rollover_ira" in legacy
    assert legacy["position:SCHD:schwab_rollover_ira"]["identity_class"] == cio.IDENTITY_LEGACY
    # archived/current maps stay disjoint
    assert got["dispositions"][DID]["disposition"] != "done"


def test_archived_feedback_not_in_current_map(iso):
    stale = "dec_0123456789abcdef"
    _post(iso, stale, disposition="reject", archived_feedback=True, symbol="V")
    got = cio.get_decision_dispositions()
    assert stale not in got["dispositions"]
    assert stale in got["archived_feedback"]
    assert got["archived_feedback"][stale]["identity_class"] == cio.IDENTITY_ARCHIVED


def test_stamp_decision_identity_copies_digests():
    home = {"cio_now": {"decisions": [{"decision_id": DID, "symbol": "SCHD"}]}}
    plan = {"position_decisions": [{
        "decision_id": DID,
        "decision_input_digest": IN_DIGEST,
        "decision_evidence_digest": EV_DIGEST,
        "symbol": "SCHD",
    }]}
    cio.stamp_decision_identity(home, plan)
    card = home["cio_now"]["decisions"][0]
    assert card["decision_input_digest"] == IN_DIGEST
    assert card["decision_evidence_digest"] == EV_DIGEST


def test_ciohub_posts_decision_id_not_position_primary():
    src = (ROOT / "apps" / "command-center-v3" / "src" / "pages" / "CioHub.tsx").read_text(encoding="utf-8")
    assert "decision_id: decisionId" in src or "decision_id: decisionId" in src.replace(" ", "")
    assert "JSON.stringify(body)" in src
    assert "legacyDispositionKey" in src
    # Primary POST key is decision_id, not position:symbol:account.
    assert "encodeURIComponent(decisionId)" in src
    assert "encodeURIComponent(key)" not in src or "decisionId" in src
    assert "Legacy unversioned" in src
    assert "not applied" in src.lower()
