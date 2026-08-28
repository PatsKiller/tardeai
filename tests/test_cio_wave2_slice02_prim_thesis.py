"""Wave 2 slice 02: PRIM sandbox/paper-trade thesis promotes to CIO, not ignored."""
from __future__ import annotations

from scripts.lib.symbol_thesis_mint_gate import (
    BLOCK_EMPTY,
    BLOCK_ERROR,
    BLOCK_EXEC,
    evaluate_mint_eligibility,
    mint_blockers_for_research,
    sandbox_to_cio_thesis_text,
)
from scripts.lib.cio_investment_product import build_product


PRIM_SANDBOX = (
    "As the external challenge analyst, I cannot approve, promote, or recommend "
    "executing this PRIM paper-trade proposal, but I can provide a strict "
    "pre-approval critique of the setup. PRIM at 86.17 entry, 79.55 stop, and "
    "102.72 target shows a clean arithmetic 2.5 R:R on paper, but the realism of "
    "that payoff depends on breakout quality, not just distance between levels. "
    "The packet itself shows weak support quality, with PRIM carrying a composite "
    "score of 48.6 and rank #157. My living thesis is that the stated R:R is "
    "likely optimistic rather than impossible, because weak momentum setups often "
    "suffer from path dependency: they can tag the stop through normal volatility "
    "long before they ever have a chance to realize the headline target. The "
    "strongest bear case is that the prior rally already pulled forward the "
    "entire rerating narrative, so what remains is a stock vulnerable to fade. "
    "On the catalyst question, I think there is no fresh earnings or backlog "
    "print that makes 102.72 easy."
)
PRIM_DISSENT = (
    "The strongest counter-view is that the prior rally was the beginning of a "
    "genuine rerating rather than a temporary squeeze, and that improving utility "
    "or energy infrastructure backlog could allow PRIM to trend to 102.72."
)
GOOD_DIRECT = (
    "SCHD remains an income ballast. Dividend yield and sector mix still fit the "
    "held role. Invalidation is a cut that breaks the distribution thesis or a "
    "sustained drawdown versus the equity sleeve. Earnings season is not a "
    "catalyst here; the 10-K payout record is. Hold unless the role changes."
)


def test_papertrade_is_sandbox_not_a_blocker():
    blockers = mint_blockers_for_research(PRIM_SANDBOX)
    assert BLOCK_EMPTY not in blockers
    assert "research_is_proposal_challenge_not_symbol_thesis" not in blockers
    assert blockers == []


def test_sandbox_good_thesis_would_mint_current():
    elig = evaluate_mint_eligibility("PRIM", PRIM_SANDBOX, PRIM_DISSENT)
    assert elig["from_sandbox"] is True
    assert elig["would_mint"] is True
    assert elig["would_mint_state"] in {"CURRENT", "THIN"}
    assert elig["blockers"] == []
    assert "Not an order" in elig["cio_body"]
    assert "PRIM" in elig["cio_body"]
    assert "living thesis" in elig["cio_body"].lower()


def test_sandbox_to_cio_drops_execute_wrapper_keeps_thesis():
    body = sandbox_to_cio_thesis_text("PRIM", PRIM_SANDBOX)
    assert "living thesis" in body.lower()
    assert "Not an order" in body
    assert "cannot approve, promote, or recommend executing" not in body.lower()


def test_error_and_empty_still_skip():
    assert mint_blockers_for_research("[ERROR] COST_CAP_EXCEEDED: daily request cap") == [BLOCK_ERROR]
    assert mint_blockers_for_research("AVOID_FOR_NOW") == [BLOCK_EMPTY]
    exec_txt = (
        "PRIM looks fine. Place a buy order at 86.17 and route to Schwab now. "
        "This is broker-ready. " + ("x" * 40)
    )
    assert BLOCK_EXEC in mint_blockers_for_research(exec_txt)


def test_non_sandbox_good_thesis_still_mints():
    elig = evaluate_mint_eligibility("SCHD", GOOD_DIRECT)
    assert elig["from_sandbox"] is False
    assert elig["would_mint"] is True


def test_new_position_if_unavailable_without_living_thesis(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    (tmp_path / "data" / "cio").mkdir(parents=True)

    def fake_thesis(sym, **k):
        return {
            "has_current_symbol_thesis": False,
            "thesis_state": "RESEARCH_REQUIRED",
            "thesis_unavailable_reason": "missing_symbol_thesis",
        }

    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_attach.thesis_fields_for_symbol", fake_thesis,
    )
    queue = {"items": [{"symbol": "PRIM", "source": "defense", "state": "WATCH"}]}
    p = build_product(root=tmp_path, queue=queue, previously_traded=[], holdings={})
    rows = {r["symbol"]: r for r in p["action_book"]["NEW_POSITION_IF"]}
    assert rows["PRIM"]["thesis_status"] == "UNAVAILABLE"
    assert not rows["PRIM"].get("why_owned_or_watched")
