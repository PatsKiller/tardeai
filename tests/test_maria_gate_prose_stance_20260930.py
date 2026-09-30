"""Maria gate: stance is read in PROSE mode (2026-09-30).

Replaying Maria's 17 distinct replies from 7 days through the served gate: 5 held, 4 falsely
("Watchlist add -> FAILED" read as BUY; a sober "nothing to act on" summary held because another
name was mentioned; lone letters C/H held). With prose mode: 1 held — the one reply that suggested
a starter position with no CIO decision on file. Card/publisher reads (prose=False) are unchanged.
Fixtures are synthetic, shaped on those replies."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_telegram_stance_gate as SG  # noqa: E402

STATUS_REPORT = ("Did both, and hit a wall.\n1. Watchlist add -> FAILED (3 attempts, all timed out). NFLX is not in the "
                 "watchlist.\n2. I can go check the desk queue later.")
ANALYST_QUOTE = "QURE: street view — Wainwright: Buy, $70 target; RBC: Buy, PT raised. Nothing to act on in the house data."
STARTER = ("S (SentinelOne) — ARR growth steady, Purple AI is the up-sell story.\n\n"
           "Margins improved and FCF turned positive last quarter, per the filing. Other items: the Dec earnings date "
           "and the operating-leverage story both matter for the next leg, and the watchlist refresh is pending.\n\n"
           "If it clears your bar, I'd buy a small first tranche and let the research loop give you the data.")
QUESTION = "S sits on support. Are you leaning buy-the-dip or buy-the-breakout so I tune the alerts?"


def test_status_reports_and_analyst_quotes_are_not_a_buy_in_prose():
    assert SG.infer_message_stance(STATUS_REPORT, "NFLX", prose=True) is None
    assert SG.infer_message_stance(ANALYST_QUOTE, "QURE", prose=True) is None
    # the card reading (prose=False) still sees them — publishers keep the old contract
    assert SG.infer_message_stance(STATUS_REPORT, "NFLX") == "bullish"


def test_an_explicit_suggestion_far_from_the_ticker_counts_for_the_primary_subject_only():
    assert SG.infer_message_stance(STARTER, "S", prose=True) is None                 # not near the ticker
    assert SG.infer_message_stance(STARTER, "S", prose=True, primary=True) == "bullish"
    assert SG.infer_message_stance(STARTER, "FCF", prose=True) is None


def test_asking_the_operators_preference_is_not_a_recommendation():
    assert SG.infer_message_stance(QUESTION, "S", prose=True, primary=True) is None


def test_upper_case_card_tokens_and_explicit_phrases_still_count_near_the_ticker():
    assert SG.infer_message_stance("NVDA — BUY on the pullback to the 50-day.", "NVDA", prose=True) == "bullish"
    assert SG.infer_message_stance("For MCD I'd trim into strength here.", "MCD", prose=True) == "bearish"
    assert SG.infer_message_stance("You should buy AAPL at the zone low.", "AAPL", prose=True) == "bullish"
    assert SG.infer_message_stance("SCHD plan: buy-limit in zone, stop $33.", "SCHD", prose=True) == "bullish"


def test_a_lone_letter_inside_words_is_not_the_symbol_in_prose():
    assert SG.infer_message_stance("the c-suite will BUY time; h/t to the team", "C", prose=True) is None


def test_the_maria_gate_uses_prose_mode():
    src = (ROOT / "scripts" / "lib" / "maria_outbound_gate.py").read_text(encoding="utf-8")
    assert "SG.infer_message_stance(window, sym, prose=True)" in src
    assert "prose=True, primary=True" in src and "idx == 0" in src


def test_starter_size_is_a_sizing_flag_not_a_stance():
    """maria_outbound_gate keeps sizing language on the receipt as a sizing flag (09-23 design)."""
    txt = "S — if it clears your bar, small starter size, and let the research loop run."
    assert SG.infer_message_stance(txt, "S", prose=True, primary=True) is None
