"""The OUTBOUND link/footer renderer must use the SAME chrome list as inbound.

THE MESSAGE THAT FOUND THIS (real, 2026-09-22 13:02, to the operator)
---------------------------------------------------------------------
    ALERT in Command Center (https://.../v3/watch/intelligence/ALERT) ·
    Finviz (https://finviz.com/quote.ashx?t=ALERT) · Yahoo (.../quote/ALERT) ·
    DY in Command Center (...) ...
    Trade-AI · ID 7bb93171 · ALERT:373d9b16 DY:b441e4b4

DY's tag was correct. "ALERT" is not a ticker: symbol_profiles held ZERO rows
for it. The word came from this system's own title template, which
`telegram_rich.entry_alert` renders as "READY ENTRY ALERT - DY (advisory)" --
which is also why ALERT sorted BEFORE DY in the footer.

WHY THE INBOUND GUARD DID NOT CATCH IT
--------------------------------------
`inbound_identity_tagger._TEMPLATE_CHROME` already contained "ALERT", and it
was working. The bad tag came from a DIFFERENT path that never consulted it:

    comms_editor.edit
      -> comms_editor.subjects
        -> operator_subject_resolver.resolve_subjects
          -> _tickers(): bare-uppercase loop, filtered by its OWN `_STOP` list

`_STOP` is a second, hand-written list. It contains EOD but not ALERT, OPEN,
PRICE, QUOTE, LIVE, MOVE, DATA, GAP or CHECK. Two lists for one job, and they
had already diverged. This is the Phase 3 lesson repeating: one chokepoint
guarded, a second one not.

Measured on the live ledger the same day -- 7 days of communication_events:

    events carrying a subject_guid ............ 7,104
      bound to a CHROME word .................. 3,515   (49.5%)
    ET 2,586 · ALERT 564 · FIX 169 · NONE 108 · PR 18 · QUOTE 16 · ...

THE NEGATIVE CONTROL, AND WHY IT IS REAL
----------------------------------------
Every trap word below is REGISTERED as a real entity in this test's isolated
registry. A guard that stops running therefore RESOLVES and these tests fail
loudly, instead of passing because the registry happened to answer nothing.
`test_the_trap_registry_really_does_resolve_those_words` is the positive
control that keeps the two cases distinguishable.

A guard that suppresses everything is not a fix, so DY and BAX must STILL tag,
an explicit $cashtag must still bind, and a chrome word the operator actually
HOLDS must still bind.

HERMETIC. No database, no live registry, no host paths: the registry is a temp
file, the ledger and receipts are temp files, and the instrument check is
injected. `get_live_project_root()` is never reached.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import comms_editor as CE  # noqa: E402
from scripts.lib import inbound_identity_tagger as TAGGER  # noqa: E402
from scripts.lib import operator_subject_resolver as OSR  # noqa: E402
from scripts.lib.identity_registry import empty_registry, register, save  # noqa: E402

COVERS = [
    "scripts/lib/comms_editor.py",
    "scripts/lib/inbound_identity_tagger.py",
    "scripts/lib/operator_subject_resolver.py",
]

NOW = datetime(2026, 9, 22, 13, 2, tzinfo=timezone.utc)

#: The exact title `telegram_rich.entry_alert` renders. This is the live string.
ENTRY_ALERT_TITLE = "READY ENTRY ALERT — DY (advisory)"

#: Chrome words that are ALSO registered entities in this test. Each one is a
#: word this system prints about itself, and each was measured binding an issuer
#: on live outbound messages.
TRAP_CHROME = ("ALERT", "ET", "QUOTE", "EOD", "FIX", "NONE", "OPEN", "PRICE", "DATA", "CHECK")

#: Genuine tickers. DY is the one the real message got RIGHT.
REAL_SYMBOLS = ("DY", "BAX")

#: Guard 2 must never be what makes a guard-1 test pass, so guard-1 tests inject
#: UNKNOWN (None) -- which keeps every symbol. If the chrome guard is reverted,
#: ALERT survives and the assertion fails, which is the point.
UNKNOWN_INSTRUMENTS = lambda syms: None  # noqa: E731


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Temp registry in which every trap word IS a real entity. No database."""
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    doc = empty_registry()
    for sym in REAL_SYMBOLS:
        register(doc, {"symbol": sym, "company": f"{sym} Industries Inc"})
    for sym in TRAP_CHROME:
        register(doc, {"symbol": sym, "company": f"{sym.title()} Holdings Inc"})
    save(doc)
    return doc


def _resolved(text: str, book=()) -> list[str]:
    """Symbols the OUTBOUND path would bind (a guid is required for a link)."""
    return [r["symbol"] for r in OSR.resolve_subjects(text, book=list(book))
            if r.get("symbol") and r.get("guid")]


# ------------------------------------------------------------ the live defect


def test_the_real_message_no_longer_tags_alert(isolated):
    """THE regression test. Revert the guard and ALERT comes back."""
    assert _resolved(ENTRY_ALERT_TITLE) == ["DY"], "ALERT is not a ticker"


def test_the_real_message_still_tags_dy_with_the_right_guid(isolated):
    """DY was CORRECT in the live message and must stay correct.

    A guard that killed the chrome by suppressing the whole line would pass the
    test above and be a worse bug than the one it fixed.
    """
    subs = CE.subjects(ENTRY_ALERT_TITLE, instruments=UNKNOWN_INSTRUMENTS)
    assert subs == [{"symbol": "DY", "guid": isolated["by_symbol"]["DY"]}]


def test_no_quote_links_are_built_for_alert(isolated, tmp_path):
    """The operator's actual complaint: Command Center / Finviz / Yahoo for ALERT."""
    d = CE.edit(ENTRY_ALERT_TITLE, chat_id="1", now=NOW,
                ledger=CE.DuplicateLedger(tmp_path / "ledger.json"),
                editor_mode="live", instruments=UNKNOWN_INSTRUMENTS)
    assert "/v3/watch/intelligence/ALERT" not in d.text
    assert "finviz.com/quote.ashx?t=ALERT" not in d.text
    assert "finance.yahoo.com/quote/ALERT" not in d.text
    assert "ALERT in Command Center" not in d.text
    # ... while the genuine symbol keeps all three.
    assert "/v3/watch/intelligence/DY" in d.text
    assert "finviz.com/quote.ashx?t=DY" in d.text
    assert "finance.yahoo.com/quote/DY" in d.text


def test_the_footer_carries_dy_and_not_alert(isolated, tmp_path):
    """Footer was "ID 7bb93171 · ALERT:373d9b16 DY:b441e4b4"."""
    d = CE.edit(ENTRY_ALERT_TITLE, chat_id="1", now=NOW,
                ledger=CE.DuplicateLedger(tmp_path / "ledger.json"),
                editor_mode="live", instruments=UNKNOWN_INSTRUMENTS)
    footer = d.text.split("\n")[-1]
    assert f"DY:{isolated['by_symbol']['DY'][:8]}" in footer
    assert "ALERT:" not in footer


# -------------------------------------------------- one list, not two


def test_both_paths_read_the_same_chrome_list():
    """The whole point. Two lists WILL diverge -- these two already had."""
    for word in TRAP_CHROME:
        assert TAGGER.is_template_chrome(word), f"{word} left the shared chrome list"
    assert not TAGGER.is_template_chrome("DY")
    assert not TAGGER.is_template_chrome("BAX")


def test_the_resolver_delegates_and_does_not_keep_a_second_list():
    """A copied list is the defect, not the fix.

    `operator_subject_resolver` must consult the tagger rather than re-spell the
    words. If someone pastes "ALERT" back into a local frozenset here, the
    lists can drift again and this fails.
    """
    src = Path(OSR.__file__).read_text(encoding="utf-8")
    assert "_is_template_chrome(tok)" in src, "the bare-uppercase path lost the shared guard"
    assert "is_template_chrome" in src
    assert '"ALERT"' not in src and "'ALERT'" not in src, "a second chrome list is growing here"


def test_the_inbound_path_is_unchanged():
    """Inbound was already correct and must stay correct."""
    assert "ALERT" not in TAGGER.extract_candidates("Any read on the ALERT pipeline?")
    assert "DY" in TAGGER.extract_candidates("what is DY doing")


# ------------------------------------------- fail OPEN for genuine tickers


def test_genuine_tickers_still_tag(isolated):
    """RED if the guard over-reaches. Suppressing everything is not a fix."""
    assert _resolved("DY entry zone update") == ["DY"]
    assert _resolved("BAX crossed support") == ["BAX"]
    assert _resolved("DY and BAX both moved") == ["DY", "BAX"]


def test_the_trap_registry_really_does_resolve_those_words(isolated):
    """Positive control.

    Without this, "the guard works" and "the registry answered nothing" look
    identical -- both produce []. An explicit $cashtag is deliberate intent and
    is the documented way these words may still bind.
    """
    assert _resolved("$ALERT is the name I mean") == ["ALERT"]
    assert _resolved("$ET distribution raised") == ["ET"]


def test_a_chrome_word_the_operator_actually_holds_still_binds(isolated):
    """ET is timezone chrome in "13:02 ET" and Energy Transfer in a book.

    The operator's OWN book is the fail-open path: never suppress a name the
    operator actually holds in order to kill boilerplate.
    """
    assert _resolved("ET distribution raised", book=["ET"]) == ["ET"]
    assert _resolved("as of 13:02 ET", book=[]) == []


def test_machine_boilerplate_binds_nothing(isolated):
    for text in ("EOD OPEN TRADE REPORT", "QUOTE refresh FIX applied",
                 "NONE of the CHECK runs completed", "PRICE DATA unavailable"):
        assert _resolved(text) == [], text


# ------------------------------- guard 2: instrument existence (drift insurance)


def test_a_symbol_with_no_instrument_gets_no_quote_links(isolated):
    """Second guard, behind the shared list.

    ALERT had 0 rows in symbol_profiles. A word not yet ON the chrome list must
    still not be handed quote links, because a quote link is a claim that the
    thing is tradeable.
    """
    subs = CE.subjects("DY and BAX", instruments=lambda syms: {"DY"})
    assert [s["symbol"] for s in subs] == ["DY"]


def test_unknown_instrument_evidence_fails_open(isolated):
    """None is UNKNOWN, not "nothing exists".

    No database must never strip every link from every message.
    """
    subs = CE.subjects("DY and BAX", instruments=lambda syms: None)
    assert [s["symbol"] for s in subs] == ["DY", "BAX"]


def test_a_raising_instrument_check_fails_open(isolated):
    def boom(_syms):
        raise RuntimeError("database on fire")

    assert [s["symbol"] for s in CE.subjects("DY and BAX", instruments=boom)] == ["DY", "BAX"]


def test_known_instruments_reports_unknown_rather_than_empty(monkeypatch):
    """The DB-backed default must return None on failure, never set()."""
    def boom(*_a, **_k):
        raise RuntimeError("no database here")

    monkeypatch.setattr(CE, "default_db_query", boom)
    assert CE.known_instruments(["DY"]) is None
    # Nothing to ask about is genuinely empty, not unknown.
    assert CE.known_instruments([]) == set()


def test_known_instruments_accepts_profile_or_narrative_evidence(monkeypatch):
    """Either surface is enough -- a real ticker with no symbol_profiles row
    (measured: TAP, HIT) must not be suppressed when the spine knows it."""
    seen = {}

    def fake(sql, params=None, fetch="all"):
        seen["sql"] = sql
        return [{"symbol": "DY"}]

    monkeypatch.setattr(CE, "default_db_query", fake)
    assert CE.known_instruments(["DY", "BAX"]) == {"DY"}
    assert "symbol_profiles" in seen["sql"] and "narrative_subjects" in seen["sql"]
