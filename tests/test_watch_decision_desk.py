"""Watch MAIN Decision Desk unit checks (no DB required)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.data_broker.watch_decision_desk import (
    build_watch_advisory,
    derive_setup_state,
    _cio_blocks,
    _is_ticket_pending,
    _ticket_state,
)


def _fresh() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ticket(**kwargs: str) -> dict[str, str]:
    base = {
        "deterministic": "NOT RUN",
        "reconciled": "NOT RUN",
        "local": "NOT RUN",
        "grok": "NOT RUN",
        "chatgpt": "NOT RUN",
    }
    base.update(kwargs)
    return base


def test_propose_ready_when_go_ticket_pass_and_price():
    out = derive_setup_state(
        admitted="GO",
        ticket=_ticket(deterministic="PASS"),
        price=50.0,
        rsi=55.0,
        as_of=_fresh(),
    )
    assert out["now"] == "GO"
    assert out["desk_state"] == "PROPOSE-READY"
    assert out["actionable"] is True
    assert out["data_gap"] is None


def test_ticket_fail_demotes_to_nogo():
    out = derive_setup_state(
        admitted="GO",
        ticket=_ticket(deterministic="FAIL"),
        price=50.0,
        rsi=55.0,
        as_of=_fresh(),
    )
    assert out["now"] == "NOGO"
    assert out["actionable"] is False


def test_data_gap_rsi_missing():
    out = derive_setup_state(
        admitted="GO",
        ticket=_ticket(deterministic="PASS"),
        price=50.0,
        rsi=None,
        as_of=_fresh(),
    )
    assert out["data_gap"] == "rsi_missing"
    assert out["desk_state"] == "DATA GAP"


def test_ticket_pending_stays_go():
    out = derive_setup_state(
        admitted="GO",
        ticket=_ticket(deterministic="NOT RUN"),
        price=50.0,
        rsi=55.0,
        as_of=_fresh(),
    )
    assert out["now"] == "GO"
    assert out["desk_state"] == "TICKET PENDING"
    assert out["ticket_pending"] is True
    assert _is_ticket_pending(_ticket(deterministic="NOT RUN"))


def test_fund_volume_criterion_na():
    adv = build_watch_advisory(
        symbol="FCNTX",
        desk_state="PROPOSE-READY",
        price=20.0,
        entry_low=19.0,
        entry_high=21.0,
        stop=18.0,
        target=25.0,
        rr=2.5,
        rsi=50.0,
        sma_20=19.5,
        sma_50=19.0,
        sma_200=18.0,
        sma20_pct=2.0,
        sma50_pct=5.0,
        sma200_pct=10.0,
        macd_signal="BULLISH",
        instrument_type="mutualfund",
        resistance={"state": "ABOVE", "level": 19.0},
        catalyst=None,
        earnings_date=None,
        ticket=_ticket(deterministic="PASS", local="PASS", grok="PASS", chatgpt="PASS"),
        book_equity=1_000_000,
        why=["Fund on MAIN — look-through advisory"],
        lookthrough={"fund_name": "Fidelity Contrafund", "sector_weights": {"Tech": 30}},
        price_age_h=2.0,
    )
    vol = next(c for c in adv["criteria"] if c["id"] == "volume")
    assert vol["met"] is True
    assert "N/A" in vol["detail"]
    assert adv["lookthrough"] is not None


def test_stale_quote_marks_stale_state():
    old = (datetime.now(timezone.utc) - timedelta(hours=120)).isoformat()
    out = derive_setup_state(
        admitted="GO",
        ticket=_ticket(deterministic="PASS"),
        price=50.0,
        rsi=55.0,
        as_of=old,
    )
    assert out["stale"] is True
    assert out["desk_state"] == "STALE"


def test_cio_avoid_blocks_propose_ready():
    out = derive_setup_state(
        admitted="GO",
        ticket=_ticket(deterministic="PASS"),
        price=366.0,
        rsi=55.0,
        as_of=_fresh(),
        cio_blocked=True,
    )
    assert out["now"] == "NOGO"
    assert out["desk_state"] == "NOGO"
    assert out["actionable"] is False
    assert out["cio_blocked"] is True
    assert any("CIO" in w for w in out["why"])


def test_trust_degraded_blocks_propose_ready():
    out = derive_setup_state(
        admitted="GO",
        ticket=_ticket(deterministic="PASS"),
        price=366.0,
        rsi=55.0,
        as_of=_fresh(),
        trust_degraded=True,
    )
    assert out["now"] == "GO"
    # Trust is not quote-stale — strip PROPOSE-READY only
    assert out["desk_state"] == "GO"
    assert out["actionable"] is False
    assert out["trust_degraded"] is True


def test_cio_blocks_reads_research_card_or_synthesis():
    assert _cio_blocks({"latest_recommendation": "AVOID", "synthesis_recommendation": "ADD"})
    assert _cio_blocks({"latest_recommendation": "ADD", "synthesis_recommendation": "SELL"})
    assert not _cio_blocks({"latest_recommendation": "ADD", "synthesis_recommendation": "ADD"})


def test_ticket_state_from_packet():
    packet = {
        "current_actionable_plan": {
            "ticket_validation": {"state": "PASS"},
        },
        "ticket_review": {
            "reconciled": {"state": "NOT RUN"},
            "reviews": {
                "local": {"verdict": "PASS"},
                "grok": {"verdict": "NOT RUN"},
            },
        },
    }
    ts = _ticket_state(packet)
    assert ts["deterministic"] == "PASS"
    assert ts["local"] == "PASS"
    assert ts["grok"] == "NOT RUN"


def test_advisory_no_llm_prose_fields():
    adv = build_watch_advisory(
        symbol="DXCM",
        desk_state="TICKET PENDING",
        price=80.0,
        entry_low=78.0,
        entry_high=82.0,
        stop=75.0,
        target=90.0,
        rr=2.0,
        rsi=48.0,
        sma_20=79.0,
        sma_50=77.0,
        sma_200=70.0,
        sma20_pct=1.0,
        sma50_pct=3.0,
        sma200_pct=12.0,
        macd_signal="NEUTRAL",
        instrument_type="equity",
        resistance={"state": "TESTING", "level": 81.0},
        catalyst={"verified": True, "headline": "FDA clearance"},
        earnings_date="2099-01-01",
        ticket=_ticket(deterministic="NOT RUN"),
        book_equity=1_240_000,
        why=["Setup GO — run critics"],
        price_age_h=1.0,
    )
    assert adv["desk_state"] == "TICKET PENDING"
    assert isinstance(adv["criteria"], list)
    assert len(adv["criteria"]) >= 8
    assert all("label" in c and "met" in c for c in adv["criteria"])
