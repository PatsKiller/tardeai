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


def test_primary_symbols_survive_dual_import(tmp_path):
    """Cron dual-import: set via scripts.lib, edit via lib — no TROW/HODO bleed.

    Live 2026-09-22 pin 857931d41: converse set primary on scripts.lib.comms_editor
    while deliver_text loaded lib.comms_editor — ContextVars diverged and the
    footer still showed ``S:… TROW:… HODO:…``.
    """
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    scripts_dir = str(root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    # Re-import lib.* as a second module object (cron path). Keep scripts.lib.
    sys.modules.pop("lib.comms_editor", None)
    sys.modules.pop(ce._PRIMARY_BUCKET_KEY, None)

    import lib.comms_editor as lib_ce  # type: ignore  # noqa: PLC0415
    scripts_ce = ce

    assert lib_ce is not scripts_ce, "precondition: dual import must produce two modules"

    HODO_GUID = "dc347eda-aaaa-bbbb-cccc-dddddddddddd"

    def resolve(text: str):
        out = []
        for sym, guid in (("S", S_GUID), ("TROW", TROW_GUID), ("HODO", HODO_GUID)):
            if sym in text:
                out.append({"symbol": sym, "guid": guid})
        return out

    body = (
        "*S*\nPrice $19.84 close Sep 04 STALE\n"
        "Earlier you also looked at TROW and HODO.\n"
        "READ_ONLY_ADVISORY"
    )
    tok = scripts_ce.set_primary_symbols(["S"])
    try:
        d = lib_ce.edit(
            body,
            chat_id="1",
            now=NOW,
            ledger=lib_ce.DuplicateLedger(tmp_path / "ledger_dual.json"),
            resolve=resolve,
            editor_mode="live",
            primary_symbols=None,  # must read shared bucket
        )
    finally:
        scripts_ce.reset_primary_symbols(tok)
        sys.modules.pop(ce._PRIMARY_BUCKET_KEY, None)

    footer = d.text.split("\n\n")[-1]
    assert "TROW" not in footer
    assert "HODO" not in footer
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


def test_dossier_does_not_prompt_say_research():
    """format_dossier no longer tells the operator to type research X."""
    import scripts.lib.subject_dossier as sd

    dossier = {
        "S": {
            "symbol": "S",
            "profile": {"sector": "Technology", "industry": "Software"},
            "agents": [],
            "synthesis": None,
            "thesis": {},
            "research": [],
            "analyst": None,
            "catalysts": [],
            "news": [],
            "sector": None,
            "industry": None,
            "iv": None,
            "dividends": None,
            "held": {},
        }
    }
    text = sd.format_dossier(["S"], dossier, prices={"S": 19.84})
    assert "🔵 Looked up outside Trade-AI: nothing for these lines" in text
    assert "say 'research S'" not in text
    assert "desk queues research when house coverage is thin" in text


def test_hollow_s_subject_brief_opens_pending_followup(tmp_path, monkeypatch):
    """Non-buy analyst ask with no house research → answer-now + PENDING_PATH.

    Soft path still queues Hermes with a pending the fulfill loop can join.
    Buy/perspective asks are covered by test_buy_perspective_leads_with_pending.
    """
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_SUBJECT_FLASH", "0")
    monkeypatch.setenv("CIO_OPERATOR_FREEFORM_FLASH", "0")
    monkeypatch.setenv("CIO_SUBJECT_DOSSIER", "0")  # keep reply short; dossier covered separately
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "OPERATOR_GAP_REQUESTS_PATH", tmp_path / "gap_requests.jsonl")
    desk._RESEARCH_GAP_ENQUEUED.clear()

    enq_calls: list[dict] = []

    def fake_enqueue(**kwargs):
        enq_calls.append(kwargs)
        return {"ok": True, "emitted": 1, "plan_id": "plan_s_hollow"}

    monkeypatch.setattr(desk, "_enqueue_hermes_research", fake_enqueue)
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"registered": 0})
    monkeypatch.setattr(desk, "_emit_telegram_desk_payload", lambda *a, **k: None)
    monkeypatch.setattr(desk, "_gap_resolver_enabled", lambda: False)
    monkeypatch.setattr(desk, "subject_research", lambda *a, **k: [])
    monkeypatch.setattr(desk, "subject_analyst_view", lambda syms: [{
        "symbol": "S",
        "rating": "Hold",
        "target_mean": 22.0,
        "target_low": 18.0,
        "target_high": 28.0,
        "n_analysts": 4,
        "as_of": "2026-08-01",
        "age_days": 52,
        "stale": True,
    }])
    monkeypatch.setattr(desk, "subject_price_facts", lambda syms: {
        "S": {
            "close": 19.84,
            "price_date": "2026-09-04",
            "change_30d_pct": -10.8,
            "start_close": 22.25,
            "start_date": "2026-08-05",
            "age_hours": 432.0,
            "stale": True,
        }
    })
    monkeypatch.setattr(desk, "_subject_levels", lambda syms: ({}, None, None))
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: {
        "intent": "analyst_view",
        "needs": ["analyst_view"],
        "symbols": ["S"],
        "text": text,
    })

    out = desk.handle_operator_desk_question(
        "what is the analyst target on S?",
        chat_id="42",
        message_id="9",
    )

    text = out.get("text") or ""
    assert out["kind"] == "answered"
    assert out.get("research_queued") is True
    assert out.get("pending_id")
    assert "say 'research S'" not in text
    assert f"Pending `{out['pending_id']}`" in text or f"Pending: `{out['pending_id']}`" in text
    assert "≈" in text, "pending ack must show an ETA the operator can see"
    assert "House research for S is queued" in text or "queued" in text.lower()
    assert "19.84" in text
    assert "STALE" in text  # Sep 04 close must not read as fresh
    assert enq_calls and enq_calls[0]["symbols"] == ["S"]

    rows = [
        __import__("json").loads(line)
        for line in desk.PENDING_PATH.read_text().splitlines()
        if line.strip()
    ]
    assert rows, "soft research enqueue must open PENDING_PATH for Hermes join-back"
    assert rows[-1]["status"] == "open"
    assert rows[-1]["pending_id"] == out["pending_id"]
    assert rows[-1].get("kind") == "soft_research_queue"
    assert rows[-1]["intent"]["symbols"] == ["S"]
    assert rows[-1].get("eta_seconds") == 1800


def test_buy_perspective_leads_with_pending_not_hollow_essay(tmp_path, monkeypatch):
    """Operator paste shape: buy/perspective + thin/stale house → research-first.

    BEFORE (live 857931d41): DeepSeek reword of Sep-04 $19.84 STALE + dossier +
    queue footnote. AFTER: deferred pending-first, no hollow essay, no price narration.
    """
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_SUBJECT_FLASH", "0")
    monkeypatch.setenv("CIO_OPERATOR_FREEFORM_FLASH", "0")
    monkeypatch.setenv("CIO_SUBJECT_DOSSIER", "0")
    monkeypatch.setenv("CIO_OPERATOR_RESEARCH_ANSWER_NOW", "1")
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "OPERATOR_GAP_REQUESTS_PATH", tmp_path / "gap_requests.jsonl")
    desk._RESEARCH_GAP_ENQUEUED.clear()

    enq_calls: list[dict] = []

    def fake_enqueue(**kwargs):
        enq_calls.append(kwargs)
        return {"ok": True, "emitted": 1, "plan_id": "plan_s_buy", "ack": "House research for S is queued"}

    monkeypatch.setattr(desk, "_enqueue_hermes_research", fake_enqueue)
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"registered": 1})
    monkeypatch.setattr(desk, "_emit_telegram_desk_payload", lambda *a, **k: None)
    monkeypatch.setattr(desk, "_gap_resolver_enabled", lambda: False)
    monkeypatch.setattr(desk, "subject_research", lambda *a, **k: [])
    monkeypatch.setattr(desk, "subject_analyst_view", lambda syms: [])
    monkeypatch.setattr(desk, "subject_price_facts", lambda syms: {
        "S": {
            "close": 19.84,
            "price_date": "2026-09-04",
            "change_30d_pct": -10.8,
            "start_close": 22.25,
            "start_date": "2026-08-05",
            "age_hours": 432.0,
            "stale": True,
        }
    })
    monkeypatch.setattr(desk, "_subject_levels", lambda syms: ({}, None, None))
    ask = "im thinking of buying S give me the perspective"
    monkeypatch.setattr(desk, "analyze_operator_intent", lambda text: {
        "intent": "analyst_view",
        "needs": ["analyst_view", "research"],
        "symbols": ["S"],
        "text": text,
        "answerable": True,
    })

    out = desk.handle_operator_desk_question(ask, chat_id="42", message_id="17")
    text = out.get("text") or ""

    assert out["kind"] == "deferred"
    assert out.get("research_queued") is True
    assert out.get("pending_id")
    assert out.get("reply_source") == "buy_perspective_research_first"
    assert "Research first" in text
    assert "hollow" in text.lower() or "will not invent" in text.lower()
    assert "Pending:" in text and out["pending_id"] in text
    assert "≈" in text or "min" in text
    # Must NOT lead with hollow price essay / DeepSeek reword
    assert "19.84" not in text
    assert "DeepSeek" not in text
    assert "say 'research S'" not in text
    assert enq_calls and enq_calls[0]["symbols"] == ["S"]

    rows = [
        __import__("json").loads(line)
        for line in desk.PENDING_PATH.read_text().splitlines()
        if line.strip()
    ]
    assert rows[-1].get("kind") == "buy_perspective_research_first"
    assert rows[-1].get("eta_seconds") == 1800


def test_buy_perspective_intent_adds_research_need(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setattr(desk, "_known_symbols", lambda ttl_s=0: frozenset())
    reg = _registry("S")
    monkeypatch.setattr(osr, "_registry_doc", lambda registry=None: reg if registry is None else registry)
    monkeypatch.setattr(osr, "_identity", lambda doc, sym: {
        "guid": f"guid-{sym}", "issuer_guid": f"issuer-{sym}", "identity_status": "CONFIRMED",
    } if sym in (doc.get("by_symbol") or {}) else {})

    intent = desk.analyze_operator_intent("im thinking of buying S give me the perspective")
    assert intent["symbols"] == ["S"]
    assert "research" in intent["needs"]
    assert "analyst_view" in intent["needs"]
    assert desk.is_buy_perspective_ask(intent["text"] if "text" in intent else
                                       "im thinking of buying S give me the perspective")



def test_subject_gather_emits_soft_missing_research_without_blocking(monkeypatch):
    """analyst_view-only subject brief gets a soft hermes gap, not a blocking one."""
    monkeypatch.setattr(desk, "subject_research", lambda *a, **k: [])
    monkeypatch.setattr(desk, "subject_analyst_view", lambda syms: [{
        "symbol": "S", "rating": "Hold", "target_mean": 22.0, "as_of": "2026-08-01",
        "age_days": 52, "stale": True, "n_analysts": 1, "target_low": 18, "target_high": 28,
    }])
    monkeypatch.setattr(desk, "subject_price_facts", lambda syms: {
        # Fresh-enough close so quote staleness does not become a blocking gap.
        "S": {"close": 19.84, "price_date": "2026-09-22", "age_hours": 2.0, "stale": False},
    })
    monkeypatch.setattr(desk, "_subject_levels", lambda syms: ({}, None, None))
    monkeypatch.setattr(desk, "_attach_contract_findings", lambda *a, **k: None)

    intent = {
        "intent": "analyst_view",
        "needs": ["analyst_view"],
        "symbols": ["S"],
        # Non-buy wording — buy/perspective makes hermes+stale blocking (Option B).
        "text": "what is the analyst target on S?",
    }
    ev = desk._gather_tradeai_evidence_core(intent)
    soft = [g for g in (ev.get("gaps") or []) if g.get("domain") == "hermes_research"]
    assert soft and soft[0]["gap_type"] == "missing_research"
    assert soft[0]["symbol"] == "S"
    assert not any(g.get("domain") == "hermes_research" for g in (ev.get("blocking_gaps") or []))
    assert ev.get("complete") is True
    assert "S" in (ev.get("available") or {}).get("subject_symbols", [])