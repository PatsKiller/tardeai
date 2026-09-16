"""The Communications Editor: HTML, GUIDs, no redundancy, CIO agreement, links, pills.

Offline: registry resolution, CIO decisions and the ledger are injected; no
Telegram call, no database, no model.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import scripts.lib.comms_editor as ce

NOW = datetime(2026, 9, 14, 11, 30, tzinfo=timezone.utc)


def _resolve(text):
    out = []
    for sym, guid in (("AXTI", "11111111-2222-3333-4444-555555555555"), ("IRDM", "99999999-2222-3333-4444-555555555555")):
        if sym in text:
            out.append({"symbol": sym, "guid": guid})
    return out


def _cio(rows):
    def q(sql, params=None, fetch="all"):
        return [r for r in rows if r["symbol"] in params[0]]
    return q


def test_markdown_becomes_escaped_html_and_identifiers_survive():
    out = ce.markdown_to_html("⚠️ *STOP WARNING*\nREAD_ONLY_ADVISORY · a<b & c · `cio_run_worker` · _note_")
    assert "<b>STOP WARNING</b>" in out
    assert "READ_ONLY_ADVISORY" in out and "<i>" in out and "<i>ONLY</i>" not in out
    assert "a&lt;b &amp; c" in out and "<code>cio_run_worker</code>" in out


def test_markdown_links_become_anchors_and_html_input_is_untouched():
    assert ce.markdown_to_html("[Open](https://x.ts.net/v3/watch/intelligence/AXTI)") == \
        '<a href="https://x.ts.net/v3/watch/intelligence/AXTI">Open</a>'
    already = "<b>Health Agent</b> 64/100"
    assert ce.markdown_to_html(already) == already


def test_fingerprint_ignores_times_ages_and_ids_but_not_content():
    a = "☀️ MORNING CIO BRIEF\nPrice $64.76 · as of 2026-09-14 07:15 (1h old)\nrun 3e234df9-96e0-4b1a-9c3e-1234567890ab"
    b = "☀️ MORNING CIO BRIEF\nPrice $64.76 · as of 2026-09-15 08:05 (3h old)\nrun 45faf8c8-b5a0-4b1a-9c3e-1234567890ab"
    c = a.replace("$64.76", "$66.10")
    assert ce.fingerprint(a) == ce.fingerprint(b)
    assert ce.fingerprint(a) != ce.fingerprint(c)


def test_same_content_to_the_same_chat_is_a_duplicate_inside_the_window(tmp_path):
    ledger = ce.DuplicateLedger(tmp_path / "ledger.json")
    first = ce.edit("☀️ MORNING CIO BRIEF\nNothing requires action today.", chat_id="1", now=NOW, ledger=ledger,
                    resolve=_resolve, editor_mode="live")
    assert first.send and first.duplicate_of is None
    ce.commit(first, chat_id="1", now=NOW, ledger=ledger, receipts=tmp_path / "r.jsonl")
    again = ce.edit("☀️ MORNING CIO BRIEF\nNothing requires action today.", chat_id="1",
                    now=NOW + timedelta(hours=9), ledger=ledger, resolve=_resolve, editor_mode="live")
    assert not again.send and again.duplicate_of == first.guid
    other_chat = ce.edit("☀️ MORNING CIO BRIEF\nNothing requires action today.", chat_id="2",
                         now=NOW + timedelta(hours=9), ledger=ledger, resolve=_resolve, editor_mode="live")
    assert other_chat.send
    next_day = ce.edit("☀️ MORNING CIO BRIEF\nNothing requires action today.", chat_id="1",
                       now=NOW + timedelta(hours=21), ledger=ledger, resolve=_resolve, editor_mode="live")
    assert next_day.send


def test_shadow_mode_never_records_so_it_cannot_suppress(tmp_path):
    ledger = ce.DuplicateLedger(tmp_path / "ledger.json")
    d = ce.edit("hello", chat_id="1", now=NOW, ledger=ledger, resolve=_resolve, editor_mode="shadow")
    ce.commit(d, chat_id="1", now=NOW, ledger=ledger, receipts=tmp_path / "r.jsonl")
    assert ce.edit("hello", chat_id="1", now=NOW, ledger=ledger, resolve=_resolve, editor_mode="shadow").send
    assert (tmp_path / "r.jsonl").read_text().count('"guid"') == 1


def test_every_message_gets_a_guid_and_subject_guids_on_the_footer(tmp_path):
    d = ce.edit("✅ GO *AXTI* — Scalp setup", chat_id="1", now=NOW, ledger=ce.DuplicateLedger(tmp_path / "l.json"),
                resolve=_resolve, editor_mode="live")
    assert d.guid and d.subjects == [{"symbol": "AXTI", "guid": "11111111-2222-3333-4444-555555555555"}]
    footer = d.text.split("\n")[-1]
    assert f"🆔 {d.guid[:8]}" in footer and "AXTI:11111111" in footer


def test_links_are_fully_qualified_tailscale_plus_finviz_and_yahoo(tmp_path, monkeypatch):
    monkeypatch.delenv("COMMAND_CENTER_BASE_URL", raising=False)
    monkeypatch.setenv("NOTIFICATION_PUBLIC_BASE_URL", "http://192.168.50.16:7777")  # LAN is refused
    d = ce.edit("AXTI update", chat_id="1", now=NOW, ledger=ce.DuplicateLedger(tmp_path / "l.json"),
                resolve=_resolve, editor_mode="live")
    assert 'href="https://ms01-openclaw.tail163d14.ts.net/v3/watch/intelligence/AXTI"' in d.text
    assert 'href="https://finviz.com/quote.ashx?t=AXTI"' in d.text
    assert 'href="https://finance.yahoo.com/quote/AXTI"' in d.text


def test_cio_disagreement_is_stated_on_the_message(tmp_path):
    q = _cio([{"symbol": "AXTI", "action": "RESEARCH_MORE", "created_at": "2026-09-13T17:08:53-04:00"},
              {"symbol": "IRDM", "action": "ADD_ON_PULLBACK", "created_at": "2026-09-13T17:00:00-04:00"}])
    d = ce.edit("[CIO DECISION] IRDM\nDecision: AVOID\nUrgency: NOW", chat_id="1", now=NOW,
                ledger=ce.DuplicateLedger(tmp_path / "l.json"), db_query=q, resolve=_resolve, editor_mode="live")
    assert d.cio_disagreements and d.cio_disagreements[0]["symbol"] == "IRDM"
    assert "CIO disagrees on IRDM" in d.text and "ADD_ON_PULLBACK" in d.text


def test_neutral_cio_research_more_does_not_contradict_a_neutral_message(tmp_path):
    q = _cio([{"symbol": "AXTI", "action": "RESEARCH_MORE", "created_at": "2026-09-13T17:08:53-04:00"}])
    d = ce.edit("AXTI news volume 8x normal", chat_id="1", now=NOW, ledger=ce.DuplicateLedger(tmp_path / "l.json"),
                db_query=q, resolve=_resolve, editor_mode="live")
    assert d.cio_disagreements == []


def test_invalid_operator_product_is_held(tmp_path):
    d = ce.edit("[CIO DECISION] AXTI\nCompleteness: 3 of 5 fields unpopulated · OPERATOR_PRODUCT_INVALID", chat_id="1",
                now=NOW, ledger=ce.DuplicateLedger(tmp_path / "l.json"), resolve=_resolve, editor_mode="live")
    assert not d.send and d.held_reason == "operator_product_invalid"


def test_pills_name_the_origin(tmp_path):
    assert ce.pills_for("Sources: re-entry desk") == [ce.PILL_HOUSE]
    assert ce.pills_for("General market history (model knowledge, not Trade-AI data)") == [ce.PILL_HOUSE, ce.PILL_MODEL]
    assert ce.pills_for("Went outside: governed_search") == [ce.PILL_HOUSE, ce.PILL_OUTSIDE]
    assert ce.pills_for("🔵 Outside: nothing was looked up outside Trade-AI") == [ce.PILL_HOUSE]


def test_mode_defaults_off_and_rejects_unknown(monkeypatch, tmp_path):
    monkeypatch.delenv("COMMS_EDITOR_MODE", raising=False)
    # The host mode file (~/.config/tradeai/comms_editor_mode, "shadow" since 2026-09-14) must not leak in.
    monkeypatch.setenv("COMMS_EDITOR_MODE_FILE", str(tmp_path / "absent_mode_file"))
    assert ce.mode() == "off"
    monkeypatch.setenv("COMMS_EDITOR_MODE", "LIVE")
    assert ce.mode() == "live"
    monkeypatch.setenv("COMMS_EDITOR_MODE", "yolo")
    assert ce.mode() == "off"


def test_receipt_never_carries_the_message_text(tmp_path):
    d = ce.edit("secret-ish body AXTI", chat_id="1", now=NOW, ledger=ce.DuplicateLedger(tmp_path / "l.json"),
                resolve=_resolve, editor_mode="shadow")
    assert "text" not in d.receipt() and d.receipt()["chat"] != "1"
