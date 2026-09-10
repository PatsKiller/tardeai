"""Phase 7: what the desk SAYS must carry identity too.

AGENTS.md §7 has always said "Tagging is TWO-WAY — inbound questions carry
identity too". Only the inbound half was built. Measured 2026-09-10: 604 outbound
events, ZERO carrying a subject_guid, 14 citing any source, 518 produced by
telegram_alert.send_telegram against 14 by agent:cio. The operator received 604
messages the system could not connect to the 49,094 research rows behind them.
"""
from __future__ import annotations

from scripts.lib.cio_outbound_identity import subjects_from_tag, tag_text


def _tag(resolved, topics=None):
    return {"resolved": resolved, "topics": topics or [], "unresolved_mentions": []}


# --- THE regression: a field label that is also a company name ----------------

def test_a_company_name_match_is_NEVER_a_subject_outbound():
    """"Strategy: momentum_scalp" must not tag MSTR.

    MicroStrategy renamed itself to "Strategy", so the company-name index is
    RIGHT and the usage is a template field label. Left unguarded, every
    watchpool alert carries MSTR and "what has the desk said about MSTR" returns
    hundreds of messages about other securities. Found on a real live alert.
    """
    subs = subjects_from_tag(_tag([
        {"symbol": "COIX", "matched_via": "ticker", "matched_text": "COIX"},
        {"symbol": "MSTR", "matched_via": "company_name", "matched_text": "Strategy"},
    ]))
    assert [s["value"] for s in subs] == ["COIX"]


def test_explicit_tickers_and_aliases_are_kept():
    subs = subjects_from_tag(_tag([
        {"symbol": "AES", "matched_via": "ticker", "matched_text": "AES"},
        {"symbol": "NVDA", "matched_via": "ticker_alias", "matched_text": "NVDA"},
    ]))
    assert [s["value"] for s in subs] == ["AES", "NVDA"]


# --- subject vs mention -------------------------------------------------------

def test_the_first_security_is_the_subject_and_the_rest_are_mentions():
    """An alert about one name that lists peers is about the first one."""
    subs = subjects_from_tag(_tag([
        {"symbol": "COIX", "matched_via": "ticker"},
        {"symbol": "XLE", "matched_via": "ticker"},
        {"symbol": "SLB", "matched_via": "ticker"},
    ]))
    assert subs[0]["relationship"] == "subject"
    assert [s["relationship"] for s in subs[1:]] == ["mentioned", "mentioned"]


def test_topics_are_THEME_mentions_never_subjects():
    """§17A: a theme must never be given a security guid; and a passing topic
    word is not what a message is about."""
    subs = subjects_from_tag(_tag([{"symbol": "AES", "matched_via": "ticker"}],
                                  topics=["energy transition"]))
    theme = [s for s in subs if s["entity_type"] == "THEME"]
    assert theme and theme[0]["relationship"] == "mentioned"


def test_a_message_about_no_security_tags_nothing():
    """"pipeline stale" is an ops message. Tagging it to anything is worse than
    leaving it untagged."""
    assert subjects_from_tag(tag_text("pipeline stale")) == []


# --- degradation --------------------------------------------------------------

def test_tagging_degrades_rather_than_raising():
    """Alerting is the operator's live path; identity is an enrichment on it.
    The opposite priority to a paid provider call, deliberately."""
    out = tag_text(None)
    assert out.get("resolved") == []


def test_real_alert_shapes_resolve_to_the_right_single_subject():
    cases = {
        "Material change — 1 name(s) worth a look\n\nAES — new catalyst": "AES",
        "PRE-MARKET CATALYST (08:31)\n\nPRE-MARKET: MOBX": "MOBX",
    }
    for msg, expected in cases.items():
        subs = subjects_from_tag(tag_text(msg))
        assert subs and subs[0]["value"] == expected and subs[0]["relationship"] == "subject"
