"""The operator's replies are measured after the fact, and the three litmus
questions of 2026-09-13 replay offline.

On 2026-09-13 the operator got, in order:
  * "Is now a good time to get back into schg"      -> the whole re-entry book
  * "How does the market normally perform in September ... what sectors ..."
        -> model prose claiming cash/holdings were "not available ... all empty"
           while the CIO snapshot carried total_cash 710,933 and sector weights
  * "What's the outlook for SpaceX ..."               -> a pending that could not close
and no reply named its sources.

Part 1 proves each rule of scripts/check_operator_answer_quality.py fires on an
injected row and stays silent on its negative control, that the alarm routes P0,
that a send failure does not advance state, and that the receipt is written.

Part 2 replays the three questions through handle_operator_desk_question with
LIVE-shaped fixtures (tests/fixtures/litmus_20260913/) and no sends, no model,
no DB. Assertions that depend on another agent's output are SKIPPED with a
reason while the field is absent and become ACTIVE once it is present:
    reply_provenance         Agent A
    contract_findings        Agent C
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_operator_answer_quality as oaq  # noqa: E402
import replay_operator_question as rq  # noqa: E402

# Declares to the C1 alarm gate that this file's send_telegram site is exercised.
COVERS = ["scripts/check_operator_answer_quality.py"]

NOW = datetime(2026, 9, 13, 23, 30, tzinfo=timezone.utc)
FIX = ROOT / "tests" / "fixtures" / "litmus_20260913"

#: Routing fixture, not a credential: passed into desk calls and asserted back
#: out unchanged, so its identity is irrelevant. tg_chat_ids.chat_ids() is not
#: used -- it reads TELEGRAM_CHAT_ID from the environment and returns a LIST,
#: which would break these equality assertions and make an offline test depend
#: on the host.
OPERATOR_CHAT = "6993102664"  # hardcode-ok: routing fixture, not a credential


def _ago(h: float) -> str:
    return (NOW - timedelta(hours=h)).isoformat()


def _schg_only(text: str) -> list[str]:
    return ["SCHG"] if "schg" in (text or "").lower() else []


def _turn(**kw) -> dict:
    base = {"ts": _ago(1), "chat_id": "c", "message_id": "1", "question": "q", "reply_source": None,
            "desk_kind": "answered", "pending_id": None, "provenance": None, "reply": "x\nSources: CIO snapshot"}
    base.update(kw)
    return base


def _rules(turns, **kw):
    return oaq.evaluate_turns(turns, extract=kw.pop("extract", _schg_only), **kw)


# ── the rules, each with its negative control ─────────────────────────────────


def test_no_sources_line_fires_and_a_reply_with_sources_does_not():
    f = _rules([_turn(message_id="1", reply="answer only"), _turn(message_id="2", reply="answer\nSources: re-entry desk")])
    assert [r["message_id"] for r in f["NO_SOURCES_LINE"]] == ["1"]


def test_went_outside_unstated_fires_and_a_stated_one_does_not():
    prov = {"stores_read": ["CIO snapshot"], "went_outside": ["brave"], "model": None, "sources_line_present": True}
    f = _rules([
        _turn(message_id="1", provenance=prov, reply="a\nSources: x"),
        _turn(message_id="2", provenance=prov, reply="a\nWent outside: brave\nSources: x"),
        _turn(message_id="3", provenance={**prov, "went_outside": []}, reply="a\nSources: x"),
    ])
    assert [r["message_id"] for r in f["WENT_OUTSIDE_UNSTATED"]] == ["1"]
    assert f["WENT_OUTSIDE_UNSTATED"][0]["went_outside"] == ["brave"]


_TODAYS_SEASONALITY_REPLY = (
    "Historically, September is the weakest month for US equities.\n\n"
    "That said, I can't give you position-specific concentration guidance — your actual holdings, weights, "
    "and cash are not available in my current facts (cash_pct, buying_power, and holdings_for_symbols are all empty). "
    "I also can't confirm your sector exposure.\n\nREAD_ONLY_ADVISORY"
)


def test_false_empty_claim_by_provenance_names_the_rule():
    prov = {"stores_read": ["get_cio_snapshot"], "went_outside": [], "model": "deepseek-v4-flash", "sources_line_present": False}
    f = _rules([_turn(reply=_TODAYS_SEASONALITY_REPLY, provenance=prov)])
    assert len(f["FALSE_EMPTY_CLAIM"]) == 1 and f["FALSE_EMPTY_CLAIM"][0]["rule"] == "provenance"


def test_false_empty_claim_by_snapshot_health_at_the_time():
    snap = json.loads((FIX / "snapshot.json").read_text())
    snap = {**snap, "collected_at": _ago(2)}
    f = _rules([_turn(ts=_ago(1), reply=_TODAYS_SEASONALITY_REPLY)], snapshot=snap, holdings={})
    assert f["FALSE_EMPTY_CLAIM"][0]["rule"] == "snapshot_health"


def test_a_snapshot_collected_after_the_turn_cannot_testify_and_store_health_decides():
    snap = {**json.loads((FIX / "snapshot.json").read_text()), "collected_at": _ago(0.1)}
    hold = {**json.loads((FIX / "holdings.json").read_text()), "generated_at": "2026-09-13 08:00:24 ET"}
    f = _rules([_turn(ts=_ago(1), reply=_TODAYS_SEASONALITY_REPLY)], snapshot=snap, holdings=hold)
    assert f["FALSE_EMPTY_CLAIM"][0]["rule"] == "store_health"


def test_negative_control_an_empty_claim_is_not_false_when_the_house_had_nothing():
    snap = {"collected_at": _ago(2), "domains": {"cash_buying_power": {"quality_state": "DATA_UNAVAILABLE", "data": {}},
                                                 "holdings_detail": {"state": "DATA_UNAVAILABLE"},
                                                 "sectors": {"state": "DATA_UNAVAILABLE"}}}
    f = _rules([_turn(ts=_ago(1), reply=_TODAYS_SEASONALITY_REPLY)], snapshot=snap, holdings={})
    assert f["FALSE_EMPTY_CLAIM"] == []


def test_negative_control_a_holdings_file_written_after_the_turn_cannot_testify():
    hold = {**json.loads((FIX / "holdings.json").read_text()), "generated_at": "2026-09-13 19:25:00 ET"}  # 23:25Z
    f = _rules([_turn(ts=_ago(2), reply=_TODAYS_SEASONALITY_REPLY)], snapshot=None, holdings=hold)
    assert f["FALSE_EMPTY_CLAIM"] == []


def test_negative_control_unavailable_about_something_else_is_not_a_domain_claim():
    f = _rules([_turn(reply="Analyst targets are not available for this name.\nSources: x")],
               snapshot=json.loads((FIX / "snapshot.json").read_text()) | {"collected_at": _ago(2)},
               holdings=json.loads((FIX / "holdings.json").read_text()))
    assert f["FALSE_EMPTY_CLAIM"] == []


def test_negative_control_a_gap_bullet_beside_a_sources_footer_is_not_a_claim():
    """Found by the litmus replay: the gap bullet and the footer naming 'cash'
    fused into one 'sentence' and fired. Each line stands alone."""
    txt = ("• Cash: pct=56.1 bp=710933.07\n• Gaps (DATA_UNAVAILABLE): book:topic\n"
           "Sources: CIO snapshot (cash, sector_exposure, risk, investment_policy, portfolio)\nREAD_ONLY_ADVISORY")
    assert oaq.empty_claims(txt) == []
    # positive control on the same shape: the claim on its own line still fires
    assert oaq.empty_claims(txt.replace("book:topic", "cash is empty"))[0]["domains"] == ["cash"]


_BOOK = "🎯 *Re-entry — purchase candidates*\n✅ *READY TO REVIEW* (3)\n👀 *NEAR ENTRY* (24) — top 5\nSources: re-entry desk"


def test_book_dump_for_a_named_symbol_fires_with_the_desk_extractor(monkeypatch):
    """Uses the desk's own _extract_symbols, with a known-symbol set injected."""
    import scripts.lib.cio_operator_desk_loop as desk
    monkeypatch.setattr(desk, "_known_symbols", lambda ttl_s=0: frozenset({"SCHG"}))
    f = oaq.evaluate_turns([_turn(question="Is now a good time to get back into schg", reply=_BOOK)],
                           extract=oaq.default_symbol_extractor())
    assert f["BOOK_DUMP_FOR_NAMED_SYMBOL"][0]["symbols"] == ["SCHG"]


def test_negative_control_the_book_is_the_answer_when_no_symbol_is_named():
    f = _rules([_turn(question="what is ready to buy back right now", reply=_BOOK)])
    assert f["BOOK_DUMP_FOR_NAMED_SYMBOL"] == []


def test_negative_control_a_symbol_card_is_not_a_book_dump():
    card = "🎯 *SCHG — re-entry check*\nzone $34.55–$34.85\nSources: re-entry desk"
    f = _rules([_turn(question="get back into schg", reply=card)])
    assert f["BOOK_DUMP_FOR_NAMED_SYMBOL"] == []


def test_pending_never_closed_fires_and_closed_or_young_ones_do_not():
    rows = [
        {"pending_id": "opr_old", "status": "open", "ts": _ago(7.7), "operator_text": "What's the outlook for SpaceX"},
        {"pending_id": "opr_done", "status": "open", "ts": _ago(5)},
        {"pending_id": "opr_done", "status": "fulfilled", "fulfilled_ts": _ago(4)},
        {"pending_id": "opr_expired", "status": "open", "ts": _ago(5)},
        {"pending_id": "opr_expired", "status": "expired", "expired_ts": _ago(3)},
        {"pending_id": "opr_young", "status": "open", "ts": _ago(1)},
    ]
    out = oaq.pending_never_closed(rows, now=NOW)
    assert [r["pending_id"] for r in out] == ["opr_old"]
    assert out[0]["age_hours"] == 7.7


def test_model_unlabelled_fires_from_provenance_and_from_reply_source():
    prov = {"stores_read": [], "went_outside": [], "model": "deepseek-v4-flash", "sources_line_present": True}
    f = _rules([
        _turn(message_id="1", provenance=prov, reply="September is weak.\nSources: x"),
        _turn(message_id="2", reply_source="freeform_flash", reply="September is weak.\nSources: x"),
    ])
    assert [(r["message_id"], r["rule"]) for r in f["MODEL_UNLABELLED"]] == [("1", "provenance"), ("2", "reply_source")]


def test_negative_control_labelled_model_prose_and_deterministic_replies_do_not_fire():
    prov = {"stores_read": [], "went_outside": [], "model": "deepseek-v4-flash", "sources_line_present": True}
    f = _rules([
        _turn(message_id="1", provenance=prov, reply="General market history (model knowledge, not Trade-AI data): ...\nSources: x"),
        _turn(message_id="2", reply_source="deepseek_flash", reply="Desk facts (Flash: wording only)\nSources: x"),
        _turn(message_id="3", reply_source="tradeai_deterministic", reply="card\nSources: x"),
    ])
    assert f["MODEL_UNLABELLED"] == []


def test_a_turn_with_no_reply_text_is_reported_not_silently_passed():
    f = _rules([_turn(reply=None)])
    assert len(f["REPLY_TEXT_UNAVAILABLE"]) == 1
    assert f["NO_SOURCES_LINE"] == [], "a text rule must not claim a result it could not compute"


# ── collect over injected ledgers: today's four turns reproduce the measurement ──


def _event(mid, text, ts, source, kind, pending=None, prov=None):
    payload = {"text": text, "chat_id": OPERATOR_CHAT, "message_id": mid, "channel": "telegram", "ts": ts,
               "reply_source": source, "desk_kind": kind, "pending_id": pending}
    if prov is not None:
        payload["reply_provenance"] = prov
    return {"event_id": f"evt-{mid}", "event_type": "operator.message", "timestamp": ts, "payload": payload}


def test_collect_reproduces_the_2026_09_13_incident_from_injected_ledgers(tmp_path, monkeypatch):
    # The migrated monitors resolve ONE shared alert_condition_state.json.
    # Without this redirect these suites share it with each other inside a
    # single pytest session, which is a cross-suite leakage path (observed
    # once as a spurious failure of the silence/recovery assertions).
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "alert_state.json"))
    import scripts.lib.cio_operator_desk_loop as desk
    monkeypatch.setattr(desk, "_known_symbols", lambda ttl_s=0: frozenset({"SCHG", "WMT"}))
    ev = tmp_path / "cio_events.jsonl"
    ev.write_text("\n".join(json.dumps(e) for e in [
        _event("51666", "What a analyst saying about Walmart right now is it a buy and what's the target",
               "2026-09-13T16:20:44+00:00", "tradeai_deterministic", "answered"),
        _event("51668", "What's the outlook for SpaceX in the next 3 months",
               "2026-09-13T16:32:36+00:00", "deferred_gap", "deferred", "opr_5bc20393b457"),
        _event("51679", "Is now a good time to get back into schg", "2026-09-13T22:51:06+00:00",
               "tradeai_deterministic", "answered"),
        _event("51681", "How does the market normally perform in September ... what sectors",
               "2026-09-13T22:56:24+00:00", "freeform_flash", "answered"),
        {"event_type": "cio.other", "payload": {}},
        _event("1", "an old question", "2026-09-11T10:00:00+00:00", "x", "answered"),
    ]) + "\n")
    pend = tmp_path / "pending.jsonl"
    pend.write_text(json.dumps({"pending_id": "opr_5bc20393b457", "status": "open", "ts": "2026-09-13T16:32:36+00:00",
                                "operator_text": "What's the outlook for SpaceX"}) + "\n")
    hold = tmp_path / "holdings.json"
    hold.write_text((FIX / "holdings.json").read_text())
    replies = {
        "51666": "Research on file (stop_curation):\n- WMT 2026-09-11 Grok stop R:R review\nREAD_ONLY_ADVISORY",
        "51668": "🧠 *Alex · Trade-AI pull queued*\nPending: `opr_5bc20393b457`\nREAD_ONLY_ADVISORY",
        "51679": _BOOK.replace("\nSources: re-entry desk", ""),
        "51681": _TODAYS_SEASONALITY_REPLY,
    }
    rep = oaq.collect(now=NOW, root=tmp_path, events_path=ev, pending_path=pend, holdings_path=hold,
                      snapshot={}, replies=replies)
    counts = {k: len(v) for k, v in rep["findings"].items()}
    assert rep["turns"] == 4 and rep["turns_with_reply"] == 4
    assert counts == {"NO_SOURCES_LINE": 4, "WENT_OUTSIDE_UNSTATED": 0, "FALSE_EMPTY_CLAIM": 1,
                      "BOOK_DUMP_FOR_NAMED_SYMBOL": 1, "PENDING_NEVER_CLOSED": 1, "RESEARCH_LANDED_UNSENT": 0,
                      "MODEL_UNLABELLED": 1, "REPLY_TEXT_UNAVAILABLE": 0,
                      # 2026-09-14: injected replies carry no delivery state, so none is undelivered.
                      "REPLY_NOT_DELIVERED": 0}
    assert rep["findings"]["FALSE_EMPTY_CLAIM"][0]["rule"] == "store_health"
    assert rep["findings"]["BOOK_DUMP_FOR_NAMED_SYMBOL"][0]["question"].startswith("Is now a good time to get back into schg")


def test_an_unreachable_reply_store_degrades_to_reply_text_unavailable(tmp_path):
    ev = tmp_path / "e.jsonl"
    ev.write_text(json.dumps(_event("9", "hello", _ago(1), "x", "answered")) + "\n")
    rep = oaq.collect(now=NOW, root=tmp_path, events_path=ev, pending_path=tmp_path / "none", snapshot={},
                      reply_loader=lambda since: ({}, "OperationalError: db down"))
    assert rep["reply_source_error"].startswith("OperationalError")
    assert len(rep["findings"]["REPLY_TEXT_UNAVAILABLE"]) == 1


def test_missing_ledgers_are_an_empty_report_not_a_crash(tmp_path):
    rep = oaq.collect(now=NOW, root=tmp_path, snapshot={}, replies={})
    assert rep["finding_count"] == 0 and rep["turns"] == 0


def test_receipt_is_written_every_run(tmp_path):
    rep = oaq.collect(now=NOW, root=tmp_path, snapshot={}, replies={})
    path = tmp_path / "runtime" / oaq.RECEIPT_NAME
    oaq._write_run_receipt(rep, receipt_path=path)
    doc = json.loads(path.read_text())
    assert doc["schema"] == oaq.SCHEMA and doc["finding_count"] == 0 and "ran_at" in doc


# ── the alarm ─────────────────────────────────────────────────────────────────


class _Captured:
    def __init__(self):
        self.sent = []

    def send_telegram(self, message, **kwargs):
        self.sent.append(message)
        return True


@pytest.fixture
def wired(monkeypatch, tmp_path):
    # The migrated monitors resolve ONE shared alert_condition_state.json.
    # Without this redirect these suites share it with each other inside a
    # single pytest session, which is a cross-suite leakage path (observed
    # once as a spurious failure of the silence/recovery assertions).
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "alert_state.json"))
    cap = _Captured()
    mod = type(sys)("telegram_alert")
    mod.send_telegram = cap.send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(oaq, "STATE_PATH", tmp_path / "state.json")
    return cap


def _report(**findings):
    f = {r: [] for r in oaq.RULES}
    f.update(findings)
    return {"schema": oaq.SCHEMA, "findings": f, "finding_count": sum(len(v) for v in f.values())}


_FEC = {"message_id": "51681", "question": "How does the market normally perform in September and normal",
        "rule": "snapshot_health", "domain": "cash", "evidence": "persisted CIO snapshot said AVAILABLE"}


def test_alarm_fires_in_operator_words_and_routes_as_an_interrupt(wired):
    oaq._alert(_report(FALSE_EMPTY_CLAIM=[_FEC],
                       BOOK_DUMP_FOR_NAMED_SYMBOL=[{"message_id": "51679", "question": "Is now a good time to get back into schg",
                                                    "symbols": ["SCHG"]}]))
    assert len(wired.sent) == 1
    body = wired.sent[0]
    assert body.startswith(oaq.SENTINEL), "the sentinel routes this, not the wording"
    assert "How does the market normally perform in September and normal" in body
    assert "[FALSE_EMPTY_CLAIM]" in body and "decided by snapshot_health" in body
    assert "asked about SCHG, got the book" in body
    assert "What will be done:" in body

    from telegram_alert_router import classify_alert

    assert classify_alert(body) == "P0_INTERRUPT"


def test_an_unchanged_finding_set_stays_silent(wired):
    rep = _report(FALSE_EMPTY_CLAIM=[_FEC])
    oaq._alert(rep)
    assert len(wired.sent) == 1
    wired.sent.clear()
    oaq._alert(rep)
    assert wired.sent == []


def test_recovery_is_reported_once(wired):
    oaq._alert(_report(FALSE_EMPTY_CLAIM=[_FEC]))
    wired.sent.clear()
    oaq._alert(_report())
    assert len(wired.sent) == 1 and "✅" in wired.sent[0] and wired.sent[0].startswith(oaq.SENTINEL)
    oaq._alert(_report())
    assert len(wired.sent) == 1


def test_a_send_failure_does_not_advance_state(monkeypatch, tmp_path, capsys):
    # The migrated monitors resolve ONE shared alert_condition_state.json.
    # Without this redirect these suites share it with each other inside a
    # single pytest session, which is a cross-suite leakage path (observed
    # once as a spurious failure of the silence/recovery assertions).
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "alert_state.json"))
    mod = type(sys)("telegram_alert")

    def _boom(message, **kwargs):
        raise RuntimeError("unreachable")

    mod.send_telegram = _boom
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(oaq, "STATE_PATH", tmp_path / "s.json")
    oaq._alert(_report(FALSE_EMPTY_CLAIM=[_FEC]))
    assert "FAILED to send" in capsys.readouterr().err
    assert not oaq.STATE_PATH.exists()


def test_dry_run_prints_the_alert_but_sends_nothing_and_writes_no_default_receipt(wired, monkeypatch, tmp_path, capsys):
    # The migrated monitors resolve ONE shared alert_condition_state.json.
    # Without this redirect these suites share it with each other inside a
    # single pytest session, which is a cross-suite leakage path (observed
    # once as a spurious failure of the silence/recovery assertions).
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "alert_state.json"))
    monkeypatch.setattr(oaq, "collect", lambda: _report(FALSE_EMPTY_CLAIM=[_FEC]) | {
        "data_root": str(tmp_path), "turns": 1, "turns_with_reply": 1, "turns_with_provenance": 0,
        "pending_rows": 0, "reply_source_error": None, "turn_index": []})
    monkeypatch.setattr(oaq, "data_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_operator_answer_quality.py", "--dry-run"])
    assert oaq.main() == 1
    out = capsys.readouterr().out
    assert "dry-run: alert body that WOULD be sent" in out and oaq.SENTINEL in out
    assert wired.sent == [] and not oaq.STATE_PATH.exists()
    assert not (tmp_path / "runtime" / oaq.RECEIPT_NAME).exists()


def test_a_scheduled_run_writes_the_receipt(wired, monkeypatch, tmp_path):
    # The migrated monitors resolve ONE shared alert_condition_state.json.
    # Without this redirect these suites share it with each other inside a
    # single pytest session, which is a cross-suite leakage path (observed
    # once as a spurious failure of the silence/recovery assertions).
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "alert_state.json"))
    monkeypatch.setattr(oaq, "collect", lambda: _report() | {
        "data_root": str(tmp_path), "turns": 0, "turns_with_reply": 0, "turns_with_provenance": 0,
        "pending_rows": 0, "reply_source_error": None, "turn_index": []})
    monkeypatch.setattr(oaq, "data_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_operator_answer_quality.py", "--alert"])
    assert oaq.main() == 0
    assert (tmp_path / "runtime" / oaq.RECEIPT_NAME).exists()


# ── the schedule is declared, not installed ───────────────────────────────────


def test_unit_files_exist_and_carry_the_required_settings():
    svc = (ROOT / "config/systemd/user/tradeai-operator-answer-quality.service").read_text()
    tmr = (ROOT / "config/systemd/user/tradeai-operator-answer-quality.timer").read_text()
    assert "scripts/check_operator_answer_quality.py --alert" in svc
    assert "SuccessExitStatus=0 1" in svc
    assert "WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild" in svc
    assert "OnCalendar=*-*-* *:22,52:00" in tmr
    assert "Persistent=true" in tmr


def test_lane_registry_declares_the_lane_with_a_durable_output_signal():
    reg = json.loads((ROOT / "config/lane_registry.json").read_text())
    lane = next(l for l in reg["lanes"] if l["lane_id"] == "operator-answer-quality-audit")
    assert lane["scheduler"] == {"kind": "systemd", "expression": "tradeai-operator-answer-quality.timer"}
    assert lane["output_signal"] == {"kind": "file_mtime", "path": f"data/runtime/{oaq.RECEIPT_NAME}"}
    assert lane["expected_cadence_hours"] == 0.5 and lane["state"] == "ACTIVE"


def test_expected_services_declares_the_timer():
    units = {u["unit"] for u in json.loads((ROOT / "config/expected_services.json").read_text())["units"]}
    assert "tradeai-operator-answer-quality.timer" in units


def test_the_monitor_declares_its_scheduler_for_the_dark_contract_gate():
    assert "tradeai-operator-answer-quality.timer" in oaq.SCHEDULED_ENTRYPOINT


# ── Part 2: litmus replay (offline, fixtures from LIVE shapes) ────────────────

_Q = {q["id"]: q["text"] for q in json.loads((FIX / "questions.json").read_text())["questions"]}


@pytest.fixture(scope="module")
def replays():
    snap = json.loads((FIX / "snapshot.json").read_text())
    desk = json.loads((FIX / "desk.json").read_text())
    hold = json.loads((FIX / "holdings.json").read_text())
    return {k: rq.replay(v, snapshot=snap, desk=desk, holdings=hold) for k, v in _Q.items()}


def test_fixtures_carry_the_live_domain_keys_and_no_secrets():
    snap = json.loads((FIX / "snapshot.json").read_text())
    for key in ("portfolio", "risk", "sectors", "investment_policy", "cash_buying_power", "holdings_detail"):
        assert key in snap["domains"], key
    assert snap["domains"]["cash_buying_power"]["data"]["total_cash"] > 0
    desk = json.loads((FIX / "desk.json").read_text())
    assert {r["symbol"] for r in desk["rows"]} >= {"SCHG"}
    assert any(all(g["pass"] for g in r["gates"]) for r in desk["rows"]), "one READY row"
    blob = "".join(p.read_text() for p in FIX.glob("*.json")).lower()
    for needle in ("password", "token", "api_key", "/home/johnclaw"):
        assert needle not in blob, needle


def test_litmus_schg_names_the_symbol_zone_gates_verdict_and_never_the_book(replays):
    r = replays["schg"]
    txt = r["reply"]
    assert r["kind"] == "answered" and r["intent"]["symbols"] == ["SCHG"]
    assert "SCHG" in txt
    assert "zone $34.55–$34.85" in txt
    assert "Gates:" in txt and "zone ✗" in txt and "not_held ✗" in txt
    assert "Verdict: *Monitor / No Action*" in txt
    assert "READY TO REVIEW" not in txt and "NEAR ENTRY (" not in txt and "ARKQ" not in txt
    assert r["pending_rows_written"] == 0


def test_litmus_schg_has_a_sources_line(replays):
    assert "Sources:" in replays["schg"]["reply"]


def test_litmus_seasonality_carries_house_facts_and_calls_nothing_empty(replays):
    r = replays["seasonality"]
    txt = r["reply"]
    assert r["kind"] == "answered" and r["intent"]["symbols"] == []
    assert "pct=56.1" in txt or "56.1%" in txt, "cash %"
    sectors = [s for s in ("Industrials 6.77%", "Financial Services 3.84%", "Technology 2.51%") if s in txt]
    assert len(sectors) >= 2, sectors
    assert "MODERATE_AGGRESSIVE" in txt, "policy risk level"
    # Research status, Agent C wording: either house research was found, or it says
    # plainly that none exists AND that nothing was queued (no unbacked follow-up).
    assert ("Trade-AI research on file for this topic" in txt
            or "Trade-AI holds no house research on this topic, and nothing was queued" in txt), "research status line"
    assert "I will follow up" not in txt, "no follow-up promise without a pending row"
    assert "Sources:" in txt
    assert oaq.empty_claims(txt) == [], "no 'not available'/'empty' claim about cash, holdings, sectors or weights"


def test_litmus_spacex_resolves_to_spcx_and_never_promises_without_an_eta(replays):
    """Corrected 2026-09-13: SpaceX is SPCX, which the book holds. It must resolve and
    be answered from house data, not refused and not given an empty promise."""
    r = replays["spacex"]
    assert r["intent"]["symbols"] == ["SPCX"], r["intent"]
    assert r["kind"] != "unanswerable", r["reply"]
    assert "I'll reply when it lands" not in r["reply"]
    if r["pending_id"]:
        assert "≈" in r["reply"], "a pending is only opened with an ETA the operator can see"


@pytest.mark.parametrize("qid", ["schg", "seasonality", "spacex"])
def test_litmus_reply_provenance_fields_agent_a(replays, qid):
    prov = replays[qid]["reply_provenance"]
    if prov is None:
        pytest.skip("reply_provenance absent on this branch — ACTIVE once Agent A's fields land")
    assert isinstance(prov.get("stores_read"), list)
    assert isinstance(prov.get("went_outside"), list)
    assert prov.get("model") is None or isinstance(prov.get("model"), str)
    assert isinstance(prov.get("sources_line_present"), bool)
    assert prov["sources_line_present"] == ("Sources:" in replays[qid]["reply"])
    if prov["went_outside"]:
        assert "Went outside:" in replays[qid]["reply"]


def test_litmus_seasonality_contract_findings_agent_c(replays):
    cf = replays["seasonality"]["contract_findings"]
    if cf is None:
        pytest.skip("evidence['contract_findings'] absent on this branch — ACTIVE once Agent C lands")
    kinds = {str(f.get("kind") or f.get("code") or f) for f in cf} if isinstance(cf, list) else set()
    assert "FALSE_EMPTY_CLAIM" not in kinds, "the replayed answer must not carry a false-empty claim"


def test_replay_restores_every_patch_and_writes_nothing_outside_its_temp_dir(replays):
    import scripts.lib.cio_operator_desk_loop as desk
    import scripts.lib.data_broker.cio_portfolio as cp
    assert desk.PENDING_PATH == ROOT / "data" / "cio" / "cio_operator_pending_replies.jsonl"
    assert getattr(cp.get_cio_snapshot, "__name__", "") == "get_cio_snapshot"
    assert desk._known_symbols.__name__ == "_known_symbols"
