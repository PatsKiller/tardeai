"""SetupReadiness@v1 — one "driven by / ready / missing" object for every surface (operator 2026-10-23, SAIQ).

Hermetic: fixtures only; no store, network, provider, Telegram or broker.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import momentum_setup_evidence as mse  # noqa: E402
from lib import unified_momentum_alert as um  # noqa: E402
from lib.scanner_candidate_projection import build_candidate_projection  # noqa: E402

NOW = datetime(2026, 10, 23, 13, 0, tzinfo=timezone.utc)  # 09:00 ET
HERMES_NONE = {"status": "NONE_FOUND", "catalyst_type": "no_clear_catalyst", "researched_at": "2026-10-23T08:25:52.8"}


def _saiq(**changes):
    row = {
        "symbol": "SAIQ",
        "price": 6.64,
        "float_m": "2.21",
        "rvol": 12.84,
        "gap_pct": "24.22",
        "change_pct": "25.76",
        "decision": "MANUAL_REVIEW",
        "scan_run_date": "2026-10-23",
        "catalyst": "WISeSat.Space and SEALSQ Advance Satellite Cybersecurity Hardening",
        "catalyst_source": "yahoo_finance",
        "catalyst_verified": False,
        "catalyst_confidence": 0.0,
        "persisted_at": "2026-10-23T08:52:23-04:00",
    }
    row.update(changes)
    return row


def _evidence(row):
    return mse.build_setup_evidence(row, now=NOW, observed_at="2026-10-23T12:52:23+00:00", source_name="TRADE_AI")


def test_saiq_unverified_headline_is_not_ready_and_names_what_is_missing():
    r = mse.setup_readiness(_evidence(_saiq()), hermes=HERMES_NONE)
    assert r["schema"] == "SetupReadiness@v1"
    assert r["status"] == "NOT_READY" and r["ready"] is False
    assert (r["passed"], r["required"]) == (4, 5)
    assert r["catalyst"]["status"] == "UNVERIFIED_HEADLINE"
    assert r["catalyst"]["text"].startswith("WISeSat")  # kept, but labelled
    assert len(r["missing"]) == 1 and r["missing"][0].startswith("verified catalyst: unverified headline")
    assert "Hermes 08:25: no clear catalyst" in r["missing"][0]
    assert "needs 5/5, has 4/5" in r["summary"]
    ids = [d["id"] for d in r["driven_by"]]
    assert ids == ["price", "float", "rvol", "gap", "catalyst"]


def test_format_readiness_is_two_plain_lines_with_values_and_thresholds():
    lines = mse.format_readiness(mse.setup_readiness(_evidence(_saiq()), hermes=HERMES_NONE))
    assert lines[0].startswith("Driven by: price 6.64 (1–25) ✓")
    assert "float 2.21M (≤ 20M) ✓" in lines[0] and "RVOL 12.8x (≥ 5x) ✓" in lines[0]
    assert lines[1].startswith("Ready: NO — needs 5/5, has 4/5")
    assert not any(c in "".join(lines) for c in "<>*`[]")


def test_verified_catalyst_and_all_facts_is_ready():
    row = _saiq(
        catalyst_verified=True,
        catalyst_url="https://news.example/x",
        catalyst_published_at="2026-10-23T11:00:00+00:00",
        catalyst_verification_method="PRIMARY_PUBLICATION",
    )
    r = mse.setup_readiness(_evidence(row))
    assert r["status"] == "READY" and r["catalyst"]["status"] == "VERIFIED" and r["missing"] == []
    assert mse.format_readiness(r)[1].startswith("Ready: YES")


def test_veto_reasons_block_ready_and_are_reported_not_recomputed():
    row = _saiq(
        catalyst_verified=True,
        catalyst_url="https://news.example/x",
        catalyst_published_at="2026-10-23T11:00:00+00:00",
        catalyst_verification_method="PRIMARY_PUBLICATION",
    )
    r = mse.setup_readiness(_evidence(row), veto_reasons=["BELOW_PM_VWAP", "L2_ASK_HEAVY"])
    assert r["ready"] is False and r["blockers"] == ["BELOW_PM_VWAP", "L2_ASK_HEAVY"]
    assert "Active Trader veto: below pm vwap, l2 ask heavy" in r["summary"]


def test_reported_verified_without_proof_is_still_an_unverified_headline():
    r = mse.setup_readiness(_evidence(_saiq(catalyst_verified=True, catalyst_confidence=1.0)))
    assert r["catalyst"]["status"] == "UNVERIFIED_HEADLINE"
    assert "no source URL" in r["catalyst"]["reason"]


def test_catalyst_verdict_vocabulary():
    assert mse.catalyst_verdict(None, None)["status"] == "UNKNOWN"
    assert mse.catalyst_verdict({}, HERMES_NONE)["status"] == "NONE_FOUND"
    found = mse.catalyst_verdict({}, {"status": "FOUND", "catalyst_type": "contract", "summary": "Gov contract"})
    assert found["status"] == "HERMES_FOUND" and found["text"] == "Gov contract" and not found["verified"]
    assert set(mse.CATALYST_VERDICTS) >= {"VERIFIED", "UNVERIFIED_HEADLINE"}


def test_no_evidence_is_unknown_never_ready():
    r = mse.setup_readiness(None)
    assert r["status"] == "UNKNOWN" and r["ready"] is None
    assert mse.format_readiness(None) == ["Ready: UNKNOWN — no same-session momentum evidence"]


def test_unified_alert_prints_the_same_readiness_and_labels_the_headline():
    ev = um.UnifiedAlertEvent(
        symbol="SAIQ",
        state="WATCH",
        ts_epoch=NOW.timestamp(),
        origin="active_trader",
        catalyst_title=_saiq()["catalyst"],
        catalyst_origin="yahoo_finance",
        evidence=_evidence(_saiq()),
    )
    um.enrich_catalyst(ev, lookup=lambda s, d: HERMES_NONE)
    text = um.render(ev)
    assert "Catalyst: UNVERIFIED headline — WISeSat" in text
    want = mse.format_readiness(mse.setup_readiness(_evidence(_saiq()), hermes=HERMES_NONE))
    for line in want:
        assert line.replace("*", "") in text
    assert text.rstrip().endswith(um.ADVISORY_LINE)
    assert "evidence" not in um._event_json(ev)


def test_projection_observation_carries_the_same_readiness():
    cache = {
        "run_date": "2026-10-23",
        "tickers": [_saiq(run_id="2026-10-23::0700", observed_at="2026-10-23T12:52:23+00:00")],
    }
    proj = build_candidate_projection(cache, [], now=NOW, catalyst_lookup=lambda s, d: HERMES_NONE)
    obs = [o for c in proj["candidates"] for o in (c.get("trade_ai") or {}).get("observations") or []]
    assert obs and obs[0]["readiness"]["catalyst"]["status"] == "UNVERIFIED_HEADLINE"
    assert obs[0]["readiness"] == mse.setup_readiness(obs[0]["setup_evidence"], hermes=HERMES_NONE)


def test_scanner_rows_carry_setup_readiness_with_hermes_from_the_state_root(tmp_path, monkeypatch):
    import api_v2  # noqa: PLC0415

    state = tmp_path / "trade-ai-releases" / "persistent-state"
    (state / "data/hermes/momentum_catalysts").mkdir(parents=True)
    (state / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    today = datetime.now(mse.ET).date().isoformat()
    (state / f"data/hermes/momentum_catalysts/{today}_catalysts.jsonl").write_text(
        '{"symbol": "SAIQ", "research_timestamp": "2026-10-23T08:25:52.8", "catalyst_type": "no_clear_catalyst"}\n'
    )
    monkeypatch.setattr(api_v2.Path, "home", classmethod(lambda cls: tmp_path))
    build = api_v2._scanner_readiness_builder({"stale": False})
    row = build(_saiq(observed_at=datetime.now(timezone.utc).isoformat(), scan_run_date=today))
    r = row["setup_readiness"]
    assert r["schema"] == "SetupReadiness@v1" and r["catalyst"]["status"] == "UNVERIFIED_HEADLINE"
    assert r["catalyst"]["hermes_status"] == "NONE_FOUND"
    # A row that cannot be annotated is returned unchanged, never dropped.
    assert build("not-a-row") == "not-a-row"
