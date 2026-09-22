"""Every producer's message carries its subject, stamped once at the chokepoint.

WHY
---
`communication_events.subject_guid` was written by exactly ONE caller —
`telegram_alert._tag_outbound`, which back-fills it with an UPDATE *after*
`publish_communication` has already returned. Every producer that publishes any
other way (the gateway-owned path in `_send_via_comms_gateway`, and ~40 direct
`publish_communication` call sites) wrote a row with no subject at all.

Measured 2026-09-22 on the live ledger:

    OUTBOUND events ................................. 54,676
      carrying subject_guid ......................... 8,786   (16.1%)
    INBOUND events .................................. 252
      carrying subject_guid ......................... 1

and a random 3,000-row sample of the UNTAGGED outbound remainder still contains
watchpool alerts ("⚡ Watchpool: COIX"), watch-alert crossings, revalidation
notices and material-change digests that name their ticker in the first line —
identity that was available on the message and simply never read.

THE FAILURE THIS MUST NOT REPEAT
--------------------------------
Tagging every producer is only safe if the guards hold, because the 2026-09-21
incident was this exact machinery pointed at machine boilerplate:

    ⚠️ AUTO-RETRY PAUSED (will re-arm): health:pipeline_freshness:<component>
    After <n> retries; autonomous re-arm in 30m.

"After" resolved to AFTER (a real ticker) via matched_via="ticker_alias" and was
recorded as the PRIMARY subject of 28,934 messages; 44,665 of 77,667 links in
the whole spine (57.5%) came from that one template.

So these tests run the REAL resolver against an ISOLATED registry in which the
template words ARE registered entities. A guard that stops working therefore
RESOLVES rather than silently missing, and the test fails. That is the negative
control: no stub can absorb the failure.

NO DATABASE. `_db_conn` is pinned to None so the ledger writes to the in-memory
store — a unit test must never insert into the live communication_events table —
and the registry is a temp file, never the production one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_outbound_identity as OI  # noqa: E402
from scripts.lib import inbound_identity_tagger as TAGGER  # noqa: E402
from scripts.lib.comms.client import (  # noqa: E402
    memory_store_snapshot,
    publish_communication,
    reset_memory_store,
)
from scripts.lib.comms.event import CommunicationEvent  # noqa: E402
from scripts.lib.identity_registry import empty_registry, register, save  # noqa: E402

CLIENT_SRC = ROOT / "scripts" / "lib" / "comms" / "client.py"

#: The live escalation template that produced the 2026-09-21 spine corruption.
TEMPLATE_ALERT = (
    "⚠️ AUTO-RETRY PAUSED (will re-arm): health:pipeline_freshness:watchlist_items\n"
    "Live price data is stale.\n"
    "After 17 retries; autonomous re-arm in 30m."
)
#: A real live watchpool alert — one of the messages the ledger left untagged.
WATCHPOOL_ALERT = "⚡ *Watchpool: COIX*\nStrategy: momentum_scalp | NEAR TRIGGER\nScore: 60 | Age: 0d | TTL: 2d"
#: A real live approval request. It names no security; "PR" is a pull request.
APPROVAL_ALERT = "🔐 *Approval requested*\n*Scope:* `git-push`\n*Window:* 30 min\nPR #1183"

#: Registered on purpose: every word below is template chrome or ops jargon, and
#: each is also a real symbol. If a guard stops running, the resolver answers and
#: the assertions below fail loudly instead of passing for the wrong reason.
TRAP_SYMBOLS = ("AFTER", "PRICE", "OPEN", "LIVE", "DATA", "CHECK", "PR", "CI", "API", "SMA", "CASH")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Temp registry + no database. Nothing here touches production state."""
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    doc = empty_registry()
    register(doc, {"symbol": "COIX", "company": "Coinllectibles Inc", "identifiers": {"cusip": "19260Q100"}})
    register(doc, {"symbol": "AES", "company": "AES Corp", "identifiers": {"cusip": "00130H105"}})
    for sym in TRAP_SYMBOLS:
        register(doc, {"symbol": sym, "company": f"{sym.title()} Holdings Inc"})
    save(doc)

    # A unit test that finds a live Postgres would otherwise WRITE to the
    # production ledger; the in-memory store is the assertion surface here.
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)
    reset_memory_store()
    yield doc
    reset_memory_store()


def _publish(body: str, **kw) -> CommunicationEvent:
    event = CommunicationEvent(
        direction="OUTBOUND",
        event_type="operator_message",
        message_class="ops",
        producer="tests.chokepoint_identity",
        subject_key=f"test:{body[:32]}",
        retention_class="operational_30d",
        sanitized_body=body,
        short_summary=body[:160],
        **kw,
    )
    result = publish_communication(event)
    assert result.ok, result.errors
    return event


# ---------------------------------------------------------------- the wiring


def test_a_producer_that_never_tags_still_publishes_a_subject():
    """THE regression test. Remove the chokepoint stamp and this fails.

    This producer is not telegram_alert and calls no tagger of its own — which
    describes ~40 live call sites and every producer not yet written.
    """
    event = _publish(WATCHPOOL_ALERT)
    assert event.subject_guid, "publish_communication did not read the subject off the message"


def test_the_subject_reaches_the_persisted_row_not_just_the_object():
    """Stamped BEFORE persist, so the INSERT carries it and nothing can lose it."""
    event = _publish(WATCHPOOL_ALERT)
    rows = [r for r in memory_store_snapshot().values() if r.get("event_id") == event.event_id]
    assert rows, "event was not persisted"
    assert rows[0]["subject_guid"] == event.subject_guid


def test_the_stamped_guid_is_the_registry_guid_not_an_invention(isolated):
    """Read-only from the identity spine: the value must come FROM the registry."""
    event = _publish(WATCHPOOL_ALERT)
    assert event.subject_guid == isolated["by_symbol"]["COIX"]


def test_a_producer_that_knows_its_subject_is_never_second_guessed():
    event = _publish(WATCHPOOL_ALERT, subject_guid="producer-supplied-guid")
    assert event.subject_guid == "producer-supplied-guid"


def test_publish_still_succeeds_when_identity_is_unavailable(monkeypatch):
    """Identity is an enrichment on the operator's live path, never a gate."""

    def boom(*_a, **_k):
        raise RuntimeError("registry on fire")

    monkeypatch.setattr(OI, "primary_subject_guid", boom)
    event = _publish(WATCHPOOL_ALERT)
    assert event.subject_guid is None


# -------------------------------------------------- the 2026-09-21 guardrails


def test_template_chrome_is_not_bound_to_an_issuer():
    """AFTER, PRICE, OPEN, LIVE, DATA and CHECK are all registered in this test's
    registry. The tagger must still refuse every one of them."""
    assert OI.primary_subject_guid(TEMPLATE_ALERT) is None
    event = _publish(TEMPLATE_ALERT)
    assert event.subject_guid is None, "machine boilerplate bound an issuer — this is the 57.5%-of-the-spine defect"


def test_the_trap_registry_really_does_resolve_those_words(isolated):
    """Positive control for the test above.

    Without this, a guard that stopped working AND a registry that answered
    nothing would look identical: both produce None. An explicit cashtag carries
    deliberate intent and is the one way these words may still resolve.
    """
    assert OI.primary_subject_guid("$AFTER is the name I mean") == isolated["by_symbol"]["AFTER"]


def test_ops_jargon_that_is_also_a_ticker_is_refused():
    """ "PR #1183" is a pull request. Measured 2026-09-22: it resolved to a real
    entity on live approval messages."""
    assert OI.primary_subject_guid(APPROVAL_ALERT) is None


def test_sentence_case_prose_never_becomes_the_subject_of_a_template():
    """The chokepoint accepts matched_via="ticker" only.

    "After"/"Price"/"Open" bind through ticker_ALIAS, which is how the incident
    happened. Excluding that kind is the structural half of the fix; the word
    lists are the measured half.
    """
    tag = OI.tag_text("After the open, Price action was quiet.")
    assert all(r["matched_via"] != "ticker" for r in tag["resolved"])
    assert OI.primary_subject_guid("After the open, Price action was quiet.") is None


def test_the_first_symbol_in_a_machine_template_becomes_the_subject(isolated):
    """A mention is not what a message is about.

    "COIX crossed 50-day SMA … Price: $253" names three registered entities in
    this registry (COIX, SMA, PRICE). Only the first real one may be stamped —
    filing a technicals alert under a moving-average label is the same class of
    error as filing it under Mastercard.
    """
    guid = OI.primary_subject_guid("📊 *COIX crossed 50-day SMA (above ↑)* Price: 253.00")
    assert guid == isolated["by_symbol"]["COIX"]


def test_an_explicit_cashtag_outranks_a_bare_token(isolated):
    """`extract_candidates` reads cashtags before bare uppercase runs, because a
    cashtag is deliberate intent rather than a token that happens to be caps.
    Pinned so the ordering is a decision, not an accident."""
    guid = OI.primary_subject_guid("*COIX* update — peers $AES unchanged")
    assert guid == isolated["by_symbol"]["AES"]


# ------------------------------------------------------ structural invariants
# These run with or without a registry: they pin the SHAPE of the fix so a later
# refactor cannot quietly move the stamp back after persist, or widen the match
# kinds back to the ones that caused the incident.


def test_the_stamp_runs_before_persist_inside_publish_communication():
    src = CLIENT_SRC.read_text(encoding="utf-8")
    body = src.split("def publish_communication(", 1)[1]
    assert "_stamp_subject_identity(event)" in body, "the chokepoint stamp is gone"
    stamp_at = body.index("_stamp_subject_identity(event)")
    persist_at = min(body.index("_persist_db("), body.index("_persist_memory("))
    assert stamp_at < persist_at, "identity must be on the row that is INSERTed"


def test_the_chokepoint_accepts_explicit_tickers_only():
    assert OI._CHOKEPOINT_MATCH_KINDS == ("ticker",), (
        "ticker_alias is sentence-case prose in a machine template; admitting it "
        "is what made one alert 57.5% of the identity spine"
    )


def test_the_measured_guard_lists_are_still_on_this_path():
    for word in TRAP_SYMBOLS:
        assert word in TAGGER._TEMPLATE_CHROME, f"{word} left the template-chrome guard"
    assert TAGGER._MIN_BARE_TICKER_LEN >= 2, "P&L yields P and L, both real tickers"
    assert "CIO" in TAGGER._STOPWORDS and "ETF" in TAGGER._STOPWORDS
    # The single-token refusal that the alias path was missing on 2026-09-21.
    src = Path(TAGGER.__file__).read_text(encoding="utf-8")
    assert 'if " " not in name.strip() and (up in _TEMPLATE_CHROME or up in _STOPWORDS):' in src
