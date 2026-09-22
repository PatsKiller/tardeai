"""A LONE chrome word must never bind an issuer through the company-name index.

THE MESSAGE THAT FOUND THIS (real, 2026-09-22, to the operator)
---------------------------------------------------------------
The operator asked about **S**. The reply carried Command Center / Finviz /
Yahoo links for **TROW** -- T. Rowe Price -- because the word "Price" appeared
in the prose. `S` itself resolved correctly (0.9, registry). The bleed was a
second symbol arriving from nowhere the operator had named.

WHY THE CHROME GUARD DID NOT CATCH IT -- THE SAME SHAPE, A THIRD TIME
---------------------------------------------------------------------
`operator_subject_resolver` has TWO resolvers behind one entry point:

    resolve_subjects
      -> _tickers()    bare-uppercase tokens  -- CONSULTS `_is_template_chrome`
      -> _companies()  capitalised names      -- did NOT

`is_template_chrome("PRICE")` was already True, and `_tickers` was already
using it (2026-09-22, the "ALERT in Command Center" fix). `_companies` guarded
only on `inbound_identity_tagger.GENERIC_NAME_TERMS`, whose 67 entries include
"research", "growth" and "value" but NOT "price". One chokepoint guarded, its
sibling left open -- the same lesson as `.claude` excluded from one of two
rsyncs, and `_legacy_send` discarding the id that 7 other sites attached.

WHY THE GUARD IS SCOPED TO A SINGLE WORD
-----------------------------------------
Measured against the live company index before writing it:

    "Price"            1 word   chrome=True    -> TROW     (must stop)
    "Data"             1 word   chrome=True    -> DAIO     (must stop)
    "T. Rowe Price"    3 words  chrome=False   -> None     (unaffected)
    "Energy Transfer"  2 words  chrome=False   -> ET       (MUST still bind)

A multi-word name is evidence of intent; one chrome word is not. Scoping the
guard this way is what keeps Energy Transfer -- a real issuer whose ticker is
the single most-abused chrome word in the ledger (2,586 false ET tags in 7
days) -- resolving from its NAME even while bare "ET" is suppressed.

NO BOOK ESCAPE HATCH, DELIBERATELY
-----------------------------------
`_tickers` lets a chrome word bind when the operator HOLDS it, because there
the token IS the symbol. Here the word is "Price" and the symbol is TROW:
holding TROW does not make "the price of the stock" a question about T. Rowe
Price. "$TROW" and the full name both still resolve, so nothing is unreachable.

THE NEGATIVE CONTROL, AND WHY IT IS REAL
-----------------------------------------
Every trap word below RESOLVES to a symbol in this test's injected index. A
guard that stops running therefore BINDS and these tests fail loudly, rather
than passing because the index happened to answer nothing.
`test_the_trap_index_really_does_resolve_those_words` is the positive control
that keeps those two outcomes distinguishable.

HERMETIC. The company-name index is injected; no database, no live registry,
no host paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import company_name_index as C  # noqa: E402
from scripts.lib import operator_subject_resolver as R  # noqa: E402

# Lone chrome words that a live index really does resolve to a real issuer.
TRAP = {"PRICE": "TROW", "DATA": "DAIO", "OPEN": "OPEN", "MOVE": "MOVE"}
# Multi-word issuers that must keep binding -- the guard must not be a mute.
REAL = {"ENERGY TRANSFER": "ET", "PALO ALTO NETWORKS": "PANW"}


@pytest.fixture(autouse=True)
def injected_index(monkeypatch):
    """Answer for every trap word, so a dead guard resolves and goes RED."""

    def resolve_name(name):
        up = " ".join(str(name or "").split()).upper()
        sym = TRAP.get(up) or REAL.get(up)
        if not sym:
            return None
        return {"symbol": sym, "matched_on": "exact", "description": f"{name} Incorporated"}

    monkeypatch.setattr(C, "resolve_name", resolve_name)
    # No book, no live registry: the guard is the only thing under test.
    monkeypatch.setattr(R, "_book_symbols", lambda: frozenset())


def _symbols(text):
    return {s.get("symbol") for s in R.resolve_subjects(text, registry={}) if s.get("symbol")}


def test_the_trap_index_really_does_resolve_those_words():
    """POSITIVE CONTROL: without the guard every trap word would bind."""
    for word, sym in TRAP.items():
        hit = C.resolve_name(word.title())
        assert hit and hit["symbol"] == sym, f"{word} must resolve, or the traps prove nothing"


@pytest.mark.parametrize("word", sorted(TRAP))
def test_a_lone_chrome_word_never_binds_an_issuer(word):
    text = f"What is the {word.title()} of the stock right now"
    assert TRAP[word] not in _symbols(text), (
        f"{word.title()!r} bound {TRAP[word]} -- the shared chrome guard is not running"
    )


def test_the_operators_real_question_binds_only_what_he_named():
    """The message that found this: S is the subject, TROW is not."""
    got = _symbols("how is S for entry on cyber give me CIO opinion")
    assert "TROW" not in got, f"TROW bled into a question about S: {got}"


def test_price_in_ordinary_prose_binds_nothing():
    assert _symbols("Price action looks weak into the close") == set()


@pytest.mark.parametrize("name,sym", sorted(REAL.items()))
def test_multi_word_issuers_still_bind(name, sym):
    """A guard that suppresses everything is not a fix."""
    text = f"what do you think of {name.title()} here"
    assert sym in _symbols(text), f"{name.title()} must still bind {sym}"


def test_energy_transfer_binds_by_name_even_though_bare_et_is_chrome():
    """The precise trade-off: the NAME resolves, the abused bare token does not."""
    assert "ET" in _symbols("Energy Transfer distribution coverage")
    assert "ET" not in _symbols("the call is at 13:02 ET today")


# ---------------------------------------------------------------------------
# A LONE INITIAL IS NOT A TICKER
#
# The same reply that bled TROW also bound T (AT&T) from "T. Rowe Price".
# `_UPPER_TOKEN` is [A-Z]{1,5}, so a lone initial and a lone ticker have the
# same shape. Suppressing single letters wholesale is not available: the
# identity registry holds 19 of the 26 as real symbols, and "how is S for
# entry on cyber" -- the question that started this tranche -- is one of them.
#
# The period is the signal. These pin BOTH directions, because a guard that
# silenced S would be a worse bug than the one it fixed.
# ---------------------------------------------------------------------------

INITIALS = {
    "T. Rowe Price outlook": "T",
    "J. P. Morgan view here": "J",
    "A. O. Smith numbers": "O",
    "E. W. Scripps coverage": "W",
}


@pytest.mark.parametrize("text,letter", sorted(INITIALS.items()))
def test_a_lone_initial_never_binds_a_ticker(text, letter):
    assert letter not in _symbols(text), (
        f"{text!r} bound {letter} -- an initial was read as a ticker"
    )


@pytest.mark.parametrize("text,letter", [
    ("how is S for entry on cyber give me CIO opinion", "S"),
    ("I own T for the dividend", "T"),
    ("what about F and GM here", "F"),
])
def test_a_genuine_lone_ticker_still_binds(text, letter):
    """NEGATIVE CONTROL: the guard must not silence the operator's own question."""
    assert letter in _symbols(text), (
        f"{text!r} lost {letter} -- the initial guard is over-reaching"
    )


def test_a_cashtag_always_wins_over_the_initial_guard():
    """The documented escape hatch for the one honest residue."""
    assert "T" in _symbols("$T yield looks fine")


def test_the_operators_real_reply_binds_S_and_nothing_else():
    """End to end on the message that found both defects in this file."""
    got = _symbols("how is S for entry on cyber give me CIO opinion")
    assert got == {"S"}, f"expected only S, got {got}"
