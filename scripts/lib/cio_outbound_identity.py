#!/usr/bin/env python3
"""Tag what the desk SAYS, not just what it is asked — the other half of §7.

AGENTS.md §7 carries a heading: "Tagging is TWO-WAY — inbound questions carry
identity too". Only the inbound half was ever built. `inbound_identity_tagger`
resolves an operator message to subjects; nothing did the same for the messages
the desk sends.

The cost, measured 2026-09-10:

    outbound communication_events            604
      carrying subject_guid                    0
      citing any authoritative source         14
    produced by telegram_alert.send_telegram 518
    produced by agent:cio                     14

So the operator received 604 messages that the system could not connect to the
49,094 research rows it had produced -- every one of which DOES carry a
subject_guid. Research was real, and arrived as "AES -- worth a look" with no way
to reach what was found. The operator's own summary of this was "fragmented",
and the measurement agrees.

This module resolves an outbound message to its subjects and links it, so that:
  * the message joins the same rollup as the research behind it;
  * `wake_comms_history.prior_comm_events` finally returns something, which is
    what makes the agent aware of what it has already said (Phase 5 wired that
    port against a column that was NULL on every row);
  * "what did we tell the operator about this name" becomes answerable.

REUSES the inbound extractor rather than writing a second one. Two extractors
would drift, and a symbol resolved one way inbound and another way outbound is
worse than no resolution: it silently splits a subject's history in half.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. Tagging a message never changes
its content, its routing, or whether it is sent.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "OutboundIdentityTag@v1"


def tag_text(text: str) -> dict[str, Any]:
    """Resolve message text to subjects. Writes nothing, never raises.

    Degrades to an empty tag: a message that cannot be resolved must still be
    sent. Alerting is the operator's live path and identity is an enrichment on
    it -- the opposite priority to a paid provider call.
    """
    try:
        try:
            from scripts.lib.inbound_identity_tagger import tag_inbound
        except ImportError:  # SCRIPTS_ONLY callers
            from lib.inbound_identity_tagger import tag_inbound  # type: ignore
        return tag_inbound(str(text or ""))
    except Exception:
        return {"schema": SCHEMA, "resolved": [], "unresolved_mentions": [],
                "topics": [], "degraded": True}


#: Outbound messages are machine-generated templates. Only an EXPLICIT ticker
#: counts. Company-name resolution is correct for inbound operator prose ("what
#: about Apple?") and actively wrong here, because template FIELD LABELS collide
#: with company names.
#:
#: The case that found this, on a real live alert:
#:
#:     "⚡ Watchpool: COIX\nStrategy: momentum_scalp | NEAR TRIGGER"
#:      -> COIX  via ticker        correct
#:      -> MSTR  via company_name  from the word "Strategy"
#:
#: MicroStrategy renamed itself to "Strategy", so the company-name index is
#: RIGHT and the usage is a field label. Every watchpool alert would have been
#: tagged with MSTR, and a rollup of "what has the desk said about MSTR" would
#: have returned hundreds of messages about other securities entirely -- the
#: exact class of quiet corruption this contract exists to prevent.
_OUTBOUND_MATCH_KINDS = ("ticker", "ticker_alias")


def subjects_from_tag(tag: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a resolved tag into narrative-subject specs.

    The FIRST resolved security is the subject; the rest are mentions. A
    watchpool alert about one name that happens to mention two peers is about the
    first one, and flattening that to three co-subjects would make every rollup
    noisier than the truth.

    Topics become THEME mentions, never subjects: §17A is explicit that a theme
    must never be given a security guid, and the converse holds -- a passing
    topic word is not what the message is about.
    """
    out: list[dict[str, Any]] = []
    kept = [r for r in (tag.get("resolved") or [])
            if r.get("matched_via") in _OUTBOUND_MATCH_KINDS]
    for i, r in enumerate(kept):
        sym = r.get("symbol")
        if not sym:
            continue
        out.append({"entity_type": "SECURITY", "value": sym,
                    "relationship": "subject" if i == 0 else "mentioned"})
    for topic in (tag.get("topics") or [])[:3]:
        out.append({"entity_type": "THEME", "value": topic, "relationship": "mentioned"})
    return out


def tag_outbound_event(cur, event_id: str, text: str, *,
                       author_agent_id: str = "cio") -> dict[str, Any]:
    """Stamp one outbound event with its subjects and link it. Never raises.

    Writes `communication_events.subject_guid` -- a column that has existed since
    the settlement migration and was NULL on all 604 live rows -- and the
    corresponding `narrative_subjects` rows.
    """
    report: dict[str, Any] = {"event_id": event_id, "linked": 0, "subject_guid": None}
    try:
        from scripts.lib.cio_narrative_write import write_narrative

        tag = tag_text(text)
        subjects = subjects_from_tag(tag)
        report["unresolved_mentions"] = tag.get("unresolved_mentions") or []
        if not subjects:
            return report

        res = write_narrative(cur, source_table="communication_events",
                              source_id=event_id, subjects=subjects,
                              author_agent_id=author_agent_id, composed=False)
        report["linked"] = res.get("links_written", 0)

        # Stamp the event's own subject_guid from the primary subject. Only the
        # first 'subject' spec counts -- the rest are mentions and must not
        # overwrite it. Guarded by `subject_guid IS NULL` so a re-run never
        # rewrites identity already established.
        from scripts.lib.cio_narrative_subjects import resolve_subject

        primary = next((s for s in subjects if s.get("relationship") == "subject"), None)
        if primary:
            ref = resolve_subject(primary["entity_type"], primary["value"])
            if ref:
                report["subject_guid"] = ref["entity_guid"]
                cur.execute(
                    "UPDATE communication_events SET subject_guid = %s "
                    "WHERE event_id = %s AND subject_guid IS NULL",
                    (ref["entity_guid"], event_id))
        return report
    except Exception as exc:  # noqa: BLE001 - alerting must not fail on tagging
        report["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return report


__all__ = ["SCHEMA", "AUTHORITY", "MBI", "tag_text", "subjects_from_tag",
           "tag_outbound_event"]
