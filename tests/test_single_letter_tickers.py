"""Single-letter ticker S: link isolation, extraction, research-gap auto-queue.

2026-09-22 operator brief: asking about ticker S bled TROW into footer links,
missed single-character extraction in some paths, and only prompted
``research S`` instead of enqueueing a research gap.
"""
from __future__ import annotations

from datetime import datetime, timezone

import scripts.lib.comms_editor as ce
import scripts.lib.cio_operator_desk_loop as desk
import scripts.lib.operator_subject_resolver as osr
from scripts.lib.telegram_rich import build_outbound_links, scope_primary_symbols


NOW = datetime(2026, 9, 22, 14, 0, tzinfo=timezone.utc)
S_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TROW_GUID = "11111111-2222-3333-4444-555555555555"


def _registry(*syms: str) -> dict:
    return {
        "by_symbol": {
            s: {
                "symbol": s,
                "issuer_guid": f"issuer-{s}",
                "security_guid": f"guid-{s}",
                "identity_status": "CONFIRMED",
            }
            for s in syms
        }
    }


def test_single_letter_link_builder_isolation(tmp_path, monkeypatch):
    """symbols=['S'] must not emit TROW / secondary residual URLs."""
    links = build_outbound_links(["S"])
    assert "/v3/watch/intelligence/S" in links
    assert "finviz.com/quote.ashx?t=S" in links
    assert "finance.yahoo.com/quote/S" in links
    assert "TROW" not in links
    assert scope_primary_symbols(["S", "S", " trow "]) == ["S", "TROW"]  # explicit input only
    assert "TROW" not in build_outbound_links(["S"])

    def resolve(text: str):
        out = []
        for sym, guid in (("S", S_GUID), ("TROW", TROW_GUID)):
            if sym in text:
                out.append({"symbol": sym, "guid": guid})
        return out

    body = (
        "*S*\nPrice $12.00\n"
        "Earlier you also looked at TROW.\n"
        "READ_ONLY_ADVISORY"
    )
    d = ce.edit(
        body,
        chat_id="1",
        now=NOW,
        ledger=ce.DuplicateLedger(tmp_path / "ledger.json"),
        resolve=resolve,
        editor_mode="live",
        primary_symbols=["S"],
    )
    assert "/v3/watch/intelligence/S" in d.text
    assert "finviz.com/quote.ashx?t=S" in d.text
    assert "TROW" not in d.text.split("\n\n")[-1] or "intelligence/TROW" not in d.text
    assert "intelligence/TROW" not in d.text
    assert "quote.ashx?t=TROW" not in d.text
    assert "primary_symbols_scoped" in d.changes


def test_single_letter_symbol_extraction(monkeypatch):
    """'is S a good investment' → primary_symbols=['S']; grammar does not bleed."""
    reg = _registry("S", "TROW", "C", "F", "IS")

    def fake_id(doc, sym):
        row = (doc.get("by_symbol") or {}).get(sym)
        if not row:
            return {}
        return {
            "guid": row["security_guid"],
            "issuer_guid": row["issuer_guid"],
            "identity_status": row["identity_status"],
        }

    monkeypatch.setattr(osr, "_identity", fake_id)

    subs = osr.resolve_subjects("is S a good investment", book=set(), registry=reg)
    assert osr.symbols_of(subs) == ["S"]

    assert osr.symbols_of(osr.resolve_subjects("$S looks cheap", book=set(), registry=reg)) == ["S"]
    assert osr.symbols_of(osr.resolve_subjects("this is a good investment", book=set(), registry=reg)) == []
    # Unknown bare single letter must not bind (grammatical / unvouched).
    assert osr.symbols_of(osr.resolve_subjects("grade Q outlook", book=set(), registry=reg)) == []

    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setattr(desk, "_known_symbols", lambda ttl_s=0: frozenset())
    monkeypatch.setattr(osr, "_registry_doc", lambda registry=None: reg if registry is None else registry)
    intent = desk.analyze_operator_intent("is S a good investment")
    assert intent["symbols"] == ["S"]


def test_research_gap_auto_trigger(monkeypatch):
    """Missing house research for S → enqueue once (not only a 'research S' prompt)."""
    calls: list[dict] = []

    def fake_enqueue(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "emitted": 1, "plan_id": "plan_test"}

    monkeypatch.setattr(desk, "_enqueue_hermes_research", fake_enqueue)
    desk._RESEARCH_GAP_ENQUEUED.clear()

    first = desk.enqueue_research_gap(
        symbols=["S"],
        chat_id="42",
        pending_id="opr_test_s",
        operator_text="is S a good investment",
    )
    second = desk.enqueue_research_gap(
        symbols=["S"],
        chat_id="42",
        pending_id="opr_test_s",
        operator_text="is S a good investment",
    )

    assert first["ok"] and first["emitted"] == 1
    assert first["ack"] == "House research for S is queued; fetching fresh quotes and levels."
    assert len(calls) == 1
    assert calls[0]["symbols"] == ["S"]
    assert second.get("deduped") is True
    assert second.get("emitted") == 0
    assert "say 'research S'" not in (first.get("ack") or "")
