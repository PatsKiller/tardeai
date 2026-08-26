"""R17.1 cash checkpoint identity. No fake security_guid. No digest/decision_id churn."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.lib.cio_institutional_learning import identity_safe_subject
from scripts.lib.r17_checkpoint_binding import (
    PORTFOLIO_CASH_ENTITY,
    bind_material_decision,
    canonical_checkpoint_subject,
    semantic_checkpoint_key,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
EXPECTED_HORIZONS = 3  # 1_session, 5_sessions, event-relative


def _cash(*, decision_id: str, digest: str, status: str = "ABOVE_BAND", action: str = "HOLD_CASH",
          policy_version: str = "cash_v1", deploy_now: float = 0.0, account_id: str = "CONSOLIDATED",
          run_id: str = "run-1", observed_at: str = "2026-08-26T12:00:00+00:00",
          receipt_id: str = "rcpt-1") -> dict:
    return {
        "decision_id": decision_id,
        "run_id": run_id,
        "observed_at": observed_at,
        "receipt_id": receipt_id,
        "symbol": "CASH",
        "action": action,
        "standing_recommendation": action,
        "current_action": action,
        "decision_evidence_digest": digest,
        "decision_input_digest": digest + "-in",
        "cash_posture": {
            "cash_posture_status": status,
            "digest": digest,
            "cash_total_usd": 123456.78 + abs(hash(digest)) % 50,
            "policy_version": policy_version,
        },
        "capital": {"deploy_now": deploy_now, "free_investable": 100000},
        "act_now": action == "DEPLOY_CASH",
        "policy_version": policy_version,
        "account_id": account_id,
        "entity_type": PORTFOLIO_CASH_ENTITY,
        "producer_id": "material_scan",
    }


def _position(*, decision_id: str, symbol: str, action: str, digest: str, guid: str) -> dict:
    return {
        "decision_id": decision_id,
        "symbol": symbol,
        "action": action,
        "standing_recommendation": action,
        "current_action": action,
        "security_guid": guid,
        "decision_evidence_digest": digest,
        "run_id": "run-x",
        "observed_at": "2026-08-26T12:00:00+00:00",
        "receipt_id": "r-x",
    }


def test_cash_never_mints_security_guid() -> None:
    d = _cash(decision_id="dec_cash_aaa", digest="rot-1")
    assert identity_safe_subject(d) is None
    sub = canonical_checkpoint_subject(d)
    assert sub["entity_type"] == PORTFOLIO_CASH_ENTITY
    assert sub["subject_guid"] is None
    assert sub["never_minted_security_guid"] is True
    assert sub["subject_id"] == "PORTFOLIO_CASH:CONSOLIDATED"
    assert "NVDA" not in sub["subject_id"]
    assert sub["subject_id"].startswith("PORTFOLIO_CASH:")


def test_rotating_technical_fields_are_semantic_duplicates() -> None:
    base = _cash(decision_id="dec_cash_aaa", digest="rot-1")
    variants = [
        dict(base, decision_id="dec_cash_bbb"),
        dict(base, run_id="run-999"),
        dict(base, observed_at="2099-01-01T00:00:00+00:00"),
        dict(base, receipt_id="rcpt-zzzz"),
        dict(base, decision_evidence_digest="totally-different"),
    ]
    k0 = semantic_checkpoint_key(base, "1_session")
    for v in variants:
        assert semantic_checkpoint_key(v, "1_session") == k0


def test_cash_replay_1000_identical_scans(tmp_path: Path) -> None:
    first = bind_material_decision(
        tmp_path, _cash(decision_id="dec_cash_0", digest="d0"), source_sha="sha", now=NOW,
    )
    assert first["wrote_n"] == EXPECTED_HORIZONS
    for i in range(1, 1000):
        out = bind_material_decision(
            tmp_path, _cash(decision_id=f"dec_cash_{i}", digest=f"d{i}"),
            source_sha="sha", now=NOW,
        )
        assert out["wrote_n"] == 0
        assert out["skipped_n"] == EXPECTED_HORIZONS
        assert all(s["reason"] == "semantic_duplicate" for s in out["skipped"])
    lines = [ln for ln in (tmp_path / "data/cio/outcome_checkpoints.jsonl").read_text().splitlines() if ln.strip()]
    assert len(lines) == EXPECTED_HORIZONS


def test_cash_replay_10000_stress(tmp_path: Path) -> None:
    t0 = time.perf_counter()
    first = bind_material_decision(
        tmp_path, _cash(decision_id="dec_cash_0", digest="d0"), source_sha="sha", now=NOW,
    )
    assert first["wrote_n"] == EXPECTED_HORIZONS
    for i in range(1, 10000):
        out = bind_material_decision(
            tmp_path, _cash(decision_id=f"dec_cash_{i}", digest=f"d{i}",
                            run_id=f"run-{i}", receipt_id=f"r-{i}",
                            observed_at=f"2026-08-26T12:00:{i % 50:02d}+00:00"),
            source_sha="sha", now=NOW,
        )
        assert out["wrote_n"] == 0
        assert all(s["reason"] == "semantic_duplicate" for s in out["skipped"])
    elapsed = time.perf_counter() - t0
    lines = [ln for ln in (tmp_path / "data/cio/outcome_checkpoints.jsonl").read_text().splitlines() if ln.strip()]
    assert len(lines) == EXPECTED_HORIZONS
    assert elapsed < 60.0


def test_mixed_generation_sequence(tmp_path: Path) -> None:
    def burst(n: int, **kw):
        wrote = skip = 0
        tag = kw.pop("tag", "x")
        for i in range(n):
            out = bind_material_decision(
                tmp_path, _cash(decision_id=f"dec_{tag}_{i}", digest=f"d{i}", **kw),
                source_sha="sha", now=NOW,
            )
            wrote += out["wrote_n"]
            skip += out["skipped_n"]
        return wrote, skip

    w1, s1 = burst(2000, status="ABOVE_BAND", policy_version="v1", tag="a")
    w2, s2 = burst(2000, status="WITHIN_BAND", policy_version="v1", tag="b")
    w3, s3 = burst(2000, status="WITHIN_BAND", policy_version="v2", tag="c")
    assert w1 == EXPECTED_HORIZONS and s1 == 2000 * EXPECTED_HORIZONS - EXPECTED_HORIZONS
    assert w2 == EXPECTED_HORIZONS
    assert w3 == EXPECTED_HORIZONS
    lines = [ln for ln in (tmp_path / "data/cio/outcome_checkpoints.jsonl").read_text().splitlines() if ln.strip()]
    assert len(lines) == 3 * EXPECTED_HORIZONS


def test_true_material_changes_create_checkpoints(tmp_path: Path) -> None:
    cases = [
        _cash(decision_id="c1", digest="d", status="ABOVE_BAND"),
        _cash(decision_id="c2", digest="d", status="WITHIN_BAND"),
        _cash(decision_id="c3", digest="d", status="BELOW_BAND"),
        _cash(decision_id="c4", digest="d", status="BELOW_BAND", action="DEPLOY_CASH", deploy_now=1.0),
        _cash(decision_id="c5", digest="d", status="BELOW_BAND", action="DEPLOY_CASH", deploy_now=1.0, policy_version="v2"),
        _cash(decision_id="c6", digest="d", status="BELOW_BAND", action="DEPLOY_CASH", deploy_now=1.0, policy_version="v2", account_id="IRA"),
    ]
    keys = {semantic_checkpoint_key(c, "1_session") for c in cases}
    assert len(keys) == len(cases)
    wrote = 0
    for c in cases:
        wrote += bind_material_decision(tmp_path, c, source_sha="sha", now=NOW, horizons=("1_session",))["wrote_n"]
    assert wrote == len(cases)


def test_other_decision_classes_not_broken(tmp_path: Path) -> None:
    classes = [
        ("HOLD", "NOC", "sec-noc"),
        ("TRIM", "NOC", "sec-noc"),
        ("WAIT", "RTX", "sec-rtx"),
        ("RE_ENTER", "SCHD", "sec-schd"),
        ("WATCH", "AMD", "sec-amd"),
    ]
    for action, sym, guid in classes:
        a = _position(decision_id=f"dec_{action}_1", symbol=sym, action=action, digest="g1", guid=guid)
        b = dict(a, decision_id=f"dec_{action}_2", run_id="other", receipt_id="z")
        r1 = bind_material_decision(tmp_path, a, source_sha="sha", now=NOW, horizons=("1_session",))
        r2 = bind_material_decision(tmp_path, b, source_sha="sha", now=NOW, horizons=("1_session",))
        assert r1["wrote_n"] == 1, action
        assert r2["wrote_n"] == 0, action
        assert r2["skipped"][0]["reason"] == "semantic_duplicate"
    # TRIM vs HOLD on same security is a real recommendation change
    hold = _position(decision_id="h", symbol="NOC", action="HOLD", digest="g", guid="sec-noc")
    trim = _position(decision_id="t", symbol="NOC", action="TRIM", digest="g", guid="sec-noc")
    assert semantic_checkpoint_key(hold, "1_session") != semantic_checkpoint_key(trim, "1_session")
