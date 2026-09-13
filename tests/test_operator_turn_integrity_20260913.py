"""The conversation ledger must record what was said, about whom, exactly once.

Two defects, found by reading the ledger after the first real operator exchange
on 2026-09-13.

1. A GENERIC WORD BOUND AN ISSUER. The desk answered a question about Walmart
   with a reply opening "Research on file (stop_curation):". The word "Research"
   resolved through the broker name index to Research Frontiers Inc (REFR) and
   was filed with identity_status=CONFIRMED. The turn was recorded against
   REFR's subject as well as WMT's -- a confident binding to a company nobody
   mentioned, which pollutes every subject-scoped read of REFR afterwards.

   The module already carried two stopword lists for exactly this class
   ("You" -> Clear Secure, "On" -> ON Semiconductor, both caught on an earlier
   test). "Research" simply was not in one.

2. A SIDE-EFFECTING CALL WAS RETRIED ON TypeError. cio_converse_core._send
   discovered whether send_fn accepted `reply_to` by calling it and catching
   TypeError -- but a TypeError raised INSIDE the send is indistinguishable
   from a signature mismatch, so the except branch re-called a function that
   had already delivered a message to the operator.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.inbound_identity_tagger import (  # noqa: E402
    GENERIC_NAME_TERMS,
    _is_generic_term,
    tag_inbound,
)

AGENT_REPLY = (
    "Research on file (stop_curation):\n"
    "- WMT 2026-09-11 Grok stop R:R review: No active protection; stop is "
    "cancelled and coverage closed. — 3.9% downside risk."
)


_FAKE_REGISTRY: dict = {"_fake": True}


def _fake_resolve(doc, token):
    """Registry stand-in: only WMT is a known ticker/alias.

    The real registry and the broker name index live on the host. On a CI
    runner both are absent, so tag_inbound resolved nothing and the assertion
    `'WMT' in set()` failed for a reason unrelated to the defect under test.
    The fakes make the two paths explicit: WMT resolves as a TICKER, and
    "Research" would resolve as a COMPANY NAME to REFR -- which is exactly the
    substitution the guard must refuse.
    """
    if str(token).upper() == "WMT":
        return {"symbol": "WMT", "subject_guid": "guid-wmt", "issuer_guid": "iss-wmt", "identity_status": "CONFIRMED"}
    if str(token).upper() == "REFR":
        return {
            "symbol": "REFR",
            "subject_guid": "guid-refr",
            "issuer_guid": "iss-refr",
            "identity_status": "CONFIRMED",
        }
    return None


def _fake_resolve_name(name):
    """Broker name index stand-in: the real index maps 'Research' -> REFR and 'Walmart' -> WMT."""
    hits = {"research": {"symbol": "REFR"}, "walmart": {"symbol": "WMT"}}
    return hits.get(str(name).strip().casefold())


@pytest.fixture
def resolvers(monkeypatch):
    import lib.research_identity as RI

    monkeypatch.setattr(RI, "resolve", _fake_resolve)
    monkeypatch.setattr(RI, "load_registry", lambda: _FAKE_REGISTRY)
    fake_idx = type(sys)("lib.company_name_index")
    fake_idx.resolve_name = _fake_resolve_name
    monkeypatch.setitem(sys.modules, "lib.company_name_index", fake_idx)


def _symbols(text: str) -> set[str]:
    return {r["symbol"] for r in (tag_inbound(text, registry=_FAKE_REGISTRY).get("resolved") or [])}


# ── 1. the false binding ─────────────────────────────────────────────────────


def test_the_agent_reply_no_longer_binds_research_frontiers(resolvers):
    """The exact text that produced the REFR row.

    With the fakes, 'Research' WOULD resolve to REFR through the company-name
    path if nothing stopped it. The guard must stop it; the WMT ticker must
    still come through.
    """
    syms = _symbols(AGENT_REPLY)
    assert "REFR" not in syms, (
        "the word 'Research' must not bind Research Frontiers Inc; it is prose, "
        "and it was filed CONFIRMED against a company nobody mentioned"
    )
    assert "WMT" in syms, "the real subject must still resolve"


def test_the_subject_still_resolves_from_the_operators_question(resolvers):
    assert "WMT" in _symbols("What a analyst saying about Walmart right now is it a buy and what's the target")


def test_negative_control_without_the_guard_research_would_bind_refr(resolvers, monkeypatch):
    """Prove the fakes reproduce the defect: disable the guard and REFR appears."""
    import lib.inbound_identity_tagger as tagger

    monkeypatch.setattr(tagger, "_is_generic_term", lambda name: False)
    assert "REFR" in _symbols(AGENT_REPLY), (
        "with the guard off, 'Research' must bind REFR -- else this test proves nothing"
    )


@pytest.mark.parametrize("name", ["Research", "Technology", "Holdings", "Capital", "Global"])
def test_generic_words_are_refused(name):
    assert _is_generic_term(name)


@pytest.mark.parametrize("name", ["Walmart", "Visa", "Norfolk Southern", "Northrop Grumman", "Research Frontiers"])
def test_real_names_are_not_refused(name):
    """Including the real company whose bare word caused this.

    Refusing "Research" must not refuse "Research Frontiers" -- the guard is an
    exact whole-string match, not a substring.
    """
    assert not _is_generic_term(name)


def test_the_guard_is_case_insensitive_and_whitespace_tolerant():
    for v in ("research", "RESEARCH", "  Research  "):
        assert _is_generic_term(v)


def test_the_guard_only_gates_company_name_not_ticker_matches():
    """A ticker match is a different claim with different evidence.

    "V" resolving to Visa must survive, whatever the name list says.
    """
    assert "V" not in GENERIC_NAME_TERMS
    assert not _is_generic_term("V")


# ── 2. the retried side effect ───────────────────────────────────────────────


def test_send_fn_signature_is_inspected_not_discovered_by_exception():
    """A delivery must never be retried because of a TypeError.

    Reads the source: _send is a closure built per-call, so the guarantee is
    structural rather than reachable through a single invocation.
    """
    src = (ROOT / "scripts" / "lib" / "cio_converse_core.py").read_text()
    assert "_send_takes_reply_to" in src, "the signature must be resolved once, up front"
    assert "except TypeError:\n            return send_fn(" not in src, (
        "re-calling send_fn inside an except TypeError re-delivers a message that may already have reached the operator"
    )


def test_a_send_that_raises_typeerror_is_reported_not_repeated():
    """The regression, exercised end to end through the real processor."""
    from lib.cio_converse_core import process_operator_message

    calls = []

    def exploding_send(chat_id, body, reply_to=None):
        calls.append(body)
        raise TypeError("something inside the transport, not the signature")

    process_operator_message(
        channel="telegram",
        chat_id="999001",
        message_id="t-typeerror",
        text="What are the latest analyst predictions on Walmart",
        user_id="999001",
        username="test",
        allowlist={"999001"},
        converse_on=True,
        dry_run=False,
        send_fn=exploding_send,
    )
    assert len(calls) <= 1, f"send_fn was called {len(calls)} times; a failing delivery must be reported, never retried"


def test_a_send_fn_without_reply_to_is_still_supported():
    """The behaviour the old except-branch existed to provide."""
    from lib.cio_converse_core import process_operator_message

    calls = []

    def narrow_send(chat_id, body):
        calls.append(body)
        return {"ok": True, "message_id": "1"}

    assert "reply_to" not in inspect.signature(narrow_send).parameters
    process_operator_message(
        channel="telegram",
        chat_id="999002",
        message_id="t-narrow",
        text="What are the latest analyst predictions on Walmart",
        user_id="999002",
        username="test",
        allowlist={"999002"},
        converse_on=True,
        dry_run=False,
        send_fn=narrow_send,
    )
    # It must not raise; whether it answers depends on evidence, not signature.
