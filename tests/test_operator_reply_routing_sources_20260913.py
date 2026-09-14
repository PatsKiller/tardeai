"""Every operator reply says where its content came from -- enforced at ONE chokepoint.

Operator, verbatim, 2026-09-13 18:58 and 19:05:

    "it needs to quote the source ... whatever elements it returns it needs to
    give the elements like you're saying that it couldn't find it local so it
    went to DeepSeek -- but it should have been able to find it local"

    "the routing should be internal Command Center first and when it has to go
    out for other stuff it needs to let us know; this needs to be wired and
    fixed tight"

The base fix (ffc795f3c) put a Sources footer on the desk loop's answered
branch. The desk loop is one of many reply paths; attention, the re-entry
interceptor, decision threads, deferred / no-coverage / unanswerable desk
replies, the rate-limit and empty fail-softs, and the pending follow-up /
retraction sends all reached the operator with no Sources line. The routing
map is docs/OPERATOR_REPLY_ROUTING.md; one test below per row.

Offline: every send is injected and captured, the event bus and wake store are
replaced, desk rows / snapshot / pending ledger are fixtures, no model is called.
"""

from __future__ import annotations

import ast
import importlib
import itertools
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.cio_converse_core as core  # noqa: E402
import scripts.lib.cio_operator_desk_loop as desk  # noqa: E402
from scripts.lib import reply_provenance as rp  # noqa: E402

COVERS = [
    "scripts/lib/cio_converse_core.py",
    "scripts/lib/cio_operator_desk_loop.py",
    "scripts/lib/reply_provenance.py",
]

CHAT = "6993102664"
_mid = itertools.count(70000)

SCHG_ROW = {
    "symbol": "SCHG", "held": True, "price": 35.155,
    "price_as_of": "2026-09-11T23:34:15-04:00", "price_age_h": 43.3,
    "price_source": "data_broker.market_quotes:alpaca",
    "entry_low": 34.55, "entry_high": 34.85, "stop": 34.35, "target": 36.4,
    "resistance": {"state": "BELOW", "level": 35.855}, "rr": 1.55, "rsi": 49.38,
    "sma_20": 35.39, "sma_50": 34.89,
    "gates": [{"id": "zone", "pass": False, "value": "+0.9% vs zone"}],
    "advisory": {"date": "2026-09-13", "action": "Monitor / No Action"},
    "intel": {"state": "NEAR ENTRY"},
}
ADBE_ROW = {**SCHG_ROW, "symbol": "ADBE", "held": False, "price": 252.32, "entry_low": 248.85,
            "entry_high": 252.0, "intel": {"state": "READY TO REVIEW"},
            "advisory": {"date": "2026-09-13", "action": "Buy-limit in zone"}}
DESK_AS_OF = "2026-09-13T22:52:35"
DESK_PATH = Path("/x/data/runtime/reentry_decision_desk_latest.json")

SNAP = {"domains": {
    "portfolio": {"total_value": 1268140.59, "holdings_count": 30, "as_of": "2026-09-13T08:00:24-04:00"},
    "cash_buying_power": {"quality_state": "PARTIAL", "data": {
        "total_cash": 710933.07, "total_buying_power_estimate": 710933.07, "cash_positions": [],
        "source": "derived_from_holdings", "as_of": "2026-09-13T08:00:24-04:00"}},
    "sectors": {"state": "AVAILABLE", "total_value": 1268140.59, "sectors": [
        {"sector": "Industrials", "value": 85864.86, "weight_pct": 6.77, "symbols": ["NOC"]}]},
    "investment_policy": {"status": "ACTIVE", "risk_level": "MODERATE_AGGRESSIVE",
                          "primary_objective": "Long-term growth", "max_single_position_pct": 8},
    "holdings_detail": {"positions": []},
}}


def _both(monkeypatch, modname: str, attr: str, value) -> None:
    """Patch an attribute under BOTH module spellings (scripts.lib.* and lib.*):
    the converse core imports scripts.lib.*, older desk tests import lib.*, and they
    are distinct module objects -- patching one leaves the other reading live files."""
    for name in (f"scripts.lib.{modname}", f"lib.{modname}"):
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, value)


class _Bus:
    emitted: list[tuple[str, dict]] = []

    def emit(self, event_type, payload, source=None, priority=None):
        _Bus.emitted.append((event_type, payload))
        return {"event_id": f"evt_{len(_Bus.emitted)}"}


class _Sender:
    def __init__(self):
        self.sent: list[tuple[str, str, object]] = []

    def __call__(self, chat_id, text, reply_to=None):
        self.sent.append((chat_id, text, reply_to))
        return {"ok": True, "message_id": 900 + len(self.sent)}


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    for k, v in {"CIO_OPERATOR_INTENT_FLASH": "0", "CIO_REENTRY_FLASH": "0", "CIO_FREEFORM_FLASH": "0",
                 "CIO_GAP_RESOLVER": "0", "CIO_OPERATOR_FREEFORM_QUEUE": "0"}.items():
        monkeypatch.setenv(k, v)
    _both(monkeypatch, "cio_operator_desk_loop", "_known_symbols", lambda ttl_s=0: frozenset({"SCHG", "ADBE", "NOC"}))
    _both(monkeypatch, "cio_operator_desk_loop", "_held_positions_map", lambda: {})
    _both(monkeypatch, "cio_operator_desk_loop", "PENDING_PATH", tmp_path / "cio_operator_pending_replies.jsonl")
    _both(monkeypatch, "cio_operator_desk_loop", "_register_gaps", lambda *a, **k: {"ok": True})
    _both(monkeypatch, "cio_operator_desk_loop", "_enqueue_hermes_research", lambda *a, **k: {"ok": True})
    _both(monkeypatch, "cio_operator_desk_loop", "_emit_telegram_desk_payload", lambda *a, **k: None)
    _both(monkeypatch, "cio_operator_desk_loop", "_thematic_research_status",
          lambda q: "Trade-AI holds no research on this topic yet.")
    rows = lambda: ([SCHG_ROW, ADBE_ROW], DESK_AS_OF, DESK_PATH)  # noqa: E731
    _both(monkeypatch, "cio_telegram_converse", "load_reentry_desk_rows", rows)
    _both(monkeypatch, "cio_telegram_converse", "_emit_reentry_reply_payload", lambda *a, **k: None)
    _both(monkeypatch, "cio_operator_feedback_loop", "ingest_operator_feedback", lambda *a, **k: None)
    import scripts.lib.data_broker.cio_portfolio as cp
    monkeypatch.setattr(cp, "get_cio_snapshot", lambda max_age_s=60: SNAP)
    import scripts.lib.cio_event_bus as bus
    _Bus.emitted = []
    monkeypatch.setattr(bus, "CIOEventBus", _Bus)
    monkeypatch.setattr(core, "enqueue_operator_wake_channel", lambda **k: "wake_test")
    monkeypatch.setattr(core, "record_decision_thread_note", lambda *a, **k: None)
    monkeypatch.setattr(core, "_PATHS", {"dedup_path": tmp_path / "dedup.jsonl", "msg_map_path": tmp_path / "map.jsonl",
                                          "rate_path": tmp_path / "cio_telegram_rate.jsonl"}, raising=False)


def _ask(text: str, *, channel: str = "telegram", reply_to_text: str | None = None) -> tuple[dict, str]:
    sender = _Sender()
    out = core.process_operator_message(
        channel=channel, chat_id=CHAT, message_id=str(next(_mid)), text=text,
        reply_to_message_id="35" if reply_to_text else None, reply_to_text=reply_to_text,
        allowlist={CHAT}, converse_on=True, dry_run=False, send_fn=sender, **core._PATHS,
    )
    assert len(sender.sent) == 1, f"exactly one send per turn, got {len(sender.sent)}"
    return out, sender.sent[0][1]


def _assert_contract(text: str, *, outside_expected: bool) -> list[str]:
    lines = text.rstrip().split("\n")
    assert rp.AUTHORITY_TAIL_RE.match(lines[-1]), f"authority tail must be last: {lines[-1]!r}"
    src = [ln for ln in lines if ln.startswith("Sources:")]
    assert len(src) == 1, f"exactly one Sources line, got {src}"
    outside = [ln for ln in lines if ln.startswith("Went outside:")]
    assert bool(outside) is outside_expected, outside
    tails = [ln for ln in lines if rp.AUTHORITY_TAIL_RE.match(ln)]
    assert len(tails) == 1, f"exactly one authority tail, got {tails}"
    assert lines.index(src[0]) < len(lines) - 1
    return lines


def _receipt(out: dict, *, house_only: bool) -> dict:
    prov = out["reply_provenance"]
    for key in ("stores_read", "went_outside", "model", "sources_line_present"):
        assert key in prov, key
    assert prov["sources_line_present"] is True
    if house_only:
        assert prov["went_outside"] == [], prov["went_outside"]
    return prov


# ── path rows ────────────────────────────────────────────────────────────────


def test_attention_reply_cites_the_office_scan_and_says_no_office_state_was_loaded():
    out, txt = _ask("Why haven't you told me anything today?")
    assert out["kind"] == "attention"
    lines = _assert_contract(txt, outside_expected=False)
    src = next(ln for ln in lines if ln.startswith("Sources:"))
    assert "office situation scan" in src and "no office state loaded" in src
    _receipt(out, house_only=True)


def test_reentry_interceptor_reply_cites_the_desk_file_and_its_computed_time():
    out, txt = _ask("what's ready to buy back right now")
    assert out["kind"] == "reentry_facts"
    lines = _assert_contract(txt, outside_expected=False)
    src = next(ln for ln in lines if ln.startswith("Sources:"))
    assert "reentry_decision_desk_latest.json · computed 2026-09-13 22:52" in src
    prov = _receipt(out, house_only=True)
    assert prov["model"] is None


def test_reentry_interceptor_with_flash_polish_names_the_model_and_goes_outside(monkeypatch):
    _both(monkeypatch, "cio_telegram_converse", "_reentry_flash_enabled", lambda: True)
    _both(monkeypatch, "cio_telegram_converse", "curate_reentry_reply_with_flash",
          lambda **k: {"ok": True, "text": "*ADBE* ready\nREAD_ONLY_ADVISORY", "source": "deepseek_flash",
                       "model": "deepseek-v4-flash"})
    out, txt = _ask("what's ready to buy back right now")
    lines = _assert_contract(txt, outside_expected=True)
    src = next(ln for ln in lines if ln.startswith("Sources:"))
    assert "deepseek-v4-flash — wording only" in src
    assert "deepseek-v4-flash" in next(ln for ln in lines if ln.startswith("Went outside:"))
    assert out["reply_provenance"]["model"] == "deepseek-v4-flash"


def test_decision_thread_reply_cites_catalog_disposition_and_capital_plan(monkeypatch):
    monkeypatch.setattr(core, "load_decision_thread_context", lambda did: {
        "decision_id": did, "symbol": "SCHD", "stance": "Trim", "disposition": "REJECT",
        "disposition_at": "2026-09-13T17:02:00Z", "why_now": "concentration above fire", "action_label": "STALE"})
    out, txt = _ask("i rejected this, it is a staple anchor", reply_to_text="MY CALL\nDecision: dec_5866156741de9046")
    assert out["kind"] == "decision_thread"
    lines = _assert_contract(txt, outside_expected=False)
    src = next(ln for ln in lines if ln.startswith("Sources:"))
    assert "decision catalog · dec_5866156741de9046 · SCHD" in src
    assert "operator dispositions · recorded 2026-09-13 17:02" in src
    assert "capital plan (position_decisions)" in src
    _receipt(out, house_only=True)


def test_desk_symbol_answer_cites_the_desk_once_and_stays_house_only():
    out, txt = _ask("Is now a good time to get back into schg")
    assert out["kind"] == "operator_desk" and out["desk_kind"] == "answered"
    assert "SCHG — re-entry check" in txt and "ADBE" not in txt
    lines = _assert_contract(txt, outside_expected=False)
    src = next(ln for ln in lines if ln.startswith("Sources:"))
    assert "re-entry desk · computed 2026-09-13 22:52" in src
    _receipt(out, house_only=True)


def test_desk_freeform_failsoft_cites_the_snapshot_and_stays_house_only():
    out, txt = _ask("what sectors should I concentrate on going into Q4")
    assert out["desk_kind"] == "answered"
    lines = _assert_contract(txt, outside_expected=False)
    assert "CIO snapshot (cash, sector_exposure" in next(ln for ln in lines if ln.startswith("Sources:"))
    _receipt(out, house_only=True)


def test_desk_freeform_written_by_flash_names_model_role_and_went_outside(monkeypatch):
    """The 18:56 sector reply: DeepSeek prose. The base footer only recognised
    source == 'deepseek_flash'; the freeform path returns 'freeform_flash', so the
    model was never named. Now it is -- in Sources AND in Went outside."""
    _both(monkeypatch, "cio_operator_desk_loop", "answer_freeform_with_flash", lambda q, ctx, gaps: {
        "ok": True, "text": "General market history (model knowledge, not Trade-AI data): September is weak.\n"
                            "Cash 710,933.\nREAD_ONLY_ADVISORY",
        "source": "freeform_flash", "model": "deepseek-v4-flash"})
    out, txt = _ask("How does the market normally perform in September and what sectors should I concentrate on")
    lines = _assert_contract(txt, outside_expected=True)
    src = next(ln for ln in lines if ln.startswith("Sources:"))
    assert "CIO snapshot" in src and "deepseek-v4-flash — general knowledge where labelled" in src
    outside = next(ln for ln in lines if ln.startswith("Went outside:"))
    assert "deepseek-v4-flash — general knowledge where labelled" in outside
    prov = out["reply_provenance"]
    assert prov["model"] == "deepseek-v4-flash" and prov["went_outside"]


def test_desk_meta_system_reply_cites_the_llm_policy():
    out, txt = _ask("which LLM model are you using")
    assert out["desk_kind"] == "answered"
    lines = _assert_contract(txt, outside_expected=False)
    assert "cio_llm_policy" in next(ln for ln in lines if ln.startswith("Sources:"))
    _receipt(out, house_only=True)


def test_desk_unclear_or_unmapped_text_still_carries_the_contract():
    out, txt = _ask("zxqv plorb")
    assert out["kind"] == "operator_desk"
    _assert_contract(txt, outside_expected=bool(out["reply_provenance"]["went_outside"]))
    assert out["reply_provenance"]["sources_line_present"] is True


def test_desk_deferred_with_hermes_queue_declares_going_outside(monkeypatch):
    """NOC is not on the re-entry desk: blocking gap, resolver off -> pending + Hermes."""
    _both(monkeypatch, "cio_operator_desk_loop", "is_answerable", lambda intent: (True, ""))
    _both(monkeypatch, "cio_operator_desk_loop", "gather_tradeai_evidence", lambda intent: {
        "complete": False, "available": {}, "sources": [str(DESK_PATH)],
        "gaps": [{"domain": "hermes_research", "symbol": "NOC", "field": "research"}],
        "blocking_gaps": [{"domain": "hermes_research", "symbol": "NOC", "field": "research"}]})
    out, txt = _ask("what does our research say about NOC")
    assert out["desk_kind"] == "deferred"
    lines = _assert_contract(txt, outside_expected=True)
    assert "re-entry desk" in next(ln for ln in lines if ln.startswith("Sources:"))
    assert "hermes_research queue" in next(ln for ln in lines if ln.startswith("Went outside:"))


def test_desk_deferred_by_gap_resolver_queue_declares_the_vector_and_eta(monkeypatch):
    monkeypatch.setenv("CIO_GAP_RESOLVER", "1")
    _both(monkeypatch, "cio_operator_desk_loop", "_resolve_blocking_gaps", lambda *a, **k: {
        "answered": [], "queued": [{"vector": "hermes_research"}], "denied": [], "errors": [],
        "eta_seconds": 1800, "eta_text": "≈ 30 min",
        "receipt": {"answered": [], "queued": ["reentry_decision_desk:NOC:hermes_research"], "denied": [],
                    "attempts": 2, "errors": [], "eta_seconds": 1800}})
    out, txt = _ask("get back into NOC?")
    assert out["desk_kind"] == "deferred"
    lines = _assert_contract(txt, outside_expected=True)
    outside = next(ln for ln in lines if ln.startswith("Went outside:"))
    assert "hermes_research" in outside and "NOC" in outside and "30 min" in outside


def test_desk_no_coverage_declares_the_resolver_tried_and_found_nothing(monkeypatch):
    monkeypatch.setenv("CIO_GAP_RESOLVER", "1")
    _both(monkeypatch, "cio_operator_desk_loop", "_resolve_blocking_gaps", lambda *a, **k: {
        "answered": [], "queued": [], "errors": [], "eta_seconds": None, "eta_text": None,
        "denied": [{"subject": "NOC", "domain": "reentry_decision_desk", "attempts": [
            {"vector": "governed_search", "outcome": "budget_denied"}]}],
        "receipt": {"answered": [], "queued": [], "denied": ["reentry_decision_desk:NOC"], "attempts": 1,
                    "errors": [], "eta_seconds": None}})
    out, txt = _ask("get back into NOC?")
    assert out["desk_kind"] == "no_coverage"
    lines = _assert_contract(txt, outside_expected=True)
    assert "every declared vector denied or empty" in next(ln for ln in lines if ln.startswith("Went outside:"))


def test_desk_answered_by_gap_resolver_vector_declares_that_vector(monkeypatch):
    monkeypatch.setenv("CIO_GAP_RESOLVER", "1")
    _both(monkeypatch, "cio_operator_desk_loop", "_resolve_blocking_gaps", lambda *a, **k: {
        "answered": [{"subject": "NOC", "domain": "reentry_decision_desk", "vector": "backup_provider",
                      "source": "backup_provider:yfinance", "answer": {"price": 500.0}, "model": None}],
        "queued": [], "denied": [], "errors": [], "eta_seconds": None, "eta_text": None,
        "receipt": {"answered": ["reentry_decision_desk:NOC:backup_provider"], "queued": [], "denied": [],
                    "attempts": 1, "errors": [], "eta_seconds": None}})
    out, txt = _ask("get back into NOC?")
    assert out["reply_source"] == "gap_resolver:backup_provider"
    lines = _assert_contract(txt, outside_expected=True)
    assert "backup_provider" in next(ln for ln in lines if ln.startswith("Went outside:"))


def test_desk_unanswerable_refusal_is_sent_not_replaced_by_a_false_queued_line(monkeypatch):
    """handle_operator_desk_question puts the refusal in reply_preview; the core read
    only `text` and sent 'Queued a pull if needed' -- a promise nothing kept."""
    spacex = {"intent": "market", "symbols": [], "needs": ["analyst_view", "reentry_ready"],
              "text": "outlook for SpaceX"}
    _both(monkeypatch, "cio_operator_desk_loop", "analyze_operator_intent", lambda text: dict(spacex))
    _both(monkeypatch, "cio_operator_desk_loop", "gather_tradeai_evidence", lambda intent: {
        "complete": False, "available": {}, "sources": [], "gaps": [],
        "blocking_gaps": [{"domain": "hermes_research", "symbol": None}]})
    out, txt = _ask("what's the outlook for SpaceX")
    assert out["desk_kind"] == "unanswerable"
    assert "can't answer that from Trade-AI" in txt and "Queued a pull" not in txt
    lines = _assert_contract(txt, outside_expected=False)
    assert "none — no Command Center store was read" in next(ln for ln in lines if ln.startswith("Sources:"))


def test_empty_desk_failsoft_declares_it_read_nothing(monkeypatch):
    monkeypatch.setattr(core, "handle_operator_desk_question",
                        lambda *a, **k: {"text": "", "sources": [], "kind": "answered", "intent": {}})
    out, txt = _ask("anything at all")
    assert out["reply_provenance"]["kind"] == "failsoft_empty"
    assert "Queued a pull" not in txt
    _assert_contract(txt, outside_expected=False)


def test_rate_limited_failsoft_cites_the_rate_ledger(monkeypatch):
    monkeypatch.setattr(core, "rate_limit_ok", lambda *a, **k: False)
    out, txt = _ask("what's my cash")
    assert out["reason"] == "rate_limited"
    lines = _assert_contract(txt, outside_expected=False)
    assert "cio_telegram_rate.jsonl" in next(ln for ln in lines if ln.startswith("Sources:"))


def test_whatsapp_reply_carries_the_contract_in_plain_text():
    out, txt = _ask("Is now a good time to get back into schg", channel="whatsapp")
    _assert_contract(txt, outside_expected=False)
    assert "*" not in txt and "`" not in txt


# ── pending follow-up / retraction (cio_telegram_bot loop, not the converse core) ──


def _pending_row(pid: str) -> dict:
    return {"pending_id": pid, "status": "open", "ts": "2026-09-13T20:00:00Z", "chat_id": CHAT,
            "message_id": "42", "channel": "telegram", "operator_text": "get back into schg",
            "intent": {"intent": "reentry", "symbols": ["SCHG"], "needs": ["reentry_ready"]}}


def test_pending_follow_up_cites_the_ledger_and_the_evidence(monkeypatch):
    desk._append_jsonl(desk.PENDING_PATH, _pending_row("opr_follow"))
    ev = {"complete": True, "sources": [str(DESK_PATH)], "gaps": [], "blocking_gaps": [],
          "available": {"reentry_as_of": DESK_AS_OF, "reentry_card": "card"}}
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: ev)
    monkeypatch.setattr(desk, "_curate_from_evidence", lambda t, e: {
        "text": "SCHG — re-entry check\nREAD_ONLY_ADVISORY", "source": "tradeai_deterministic"})
    sender = _Sender()
    res = desk.try_fulfill_pending_replies(sender)
    assert res["fulfilled"] == 1
    lines = _assert_contract(sender.sent[0][1], outside_expected=False)
    src = next(ln for ln in lines if ln.startswith("Sources:"))
    assert "cio_operator_pending_replies.jsonl · opened 2026-09-13 20:00" in src
    assert "re-entry desk · computed 2026-09-13 22:52" in src


def test_pending_retraction_cites_the_ledger(monkeypatch):
    desk._append_jsonl(desk.PENDING_PATH, _pending_row("opr_close"))
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: {
        "complete": False, "sources": [], "available": {}, "gaps": [], "blocking_gaps": []})
    monkeypatch.setattr(desk, "PENDING_EXPIRY_HOURS", 0.0)
    sender = _Sender()
    res = desk.try_fulfill_pending_replies(sender)
    assert res["expired"] == 1
    lines = _assert_contract(sender.sent[0][1], outside_expected=False)
    assert "cio_operator_pending_replies.jsonl" in next(ln for ln in lines if ln.startswith("Sources:"))


def test_negative_control_pending_retraction_without_the_chokepoint_has_no_sources(monkeypatch):
    desk._append_jsonl(desk.PENDING_PATH, _pending_row("opr_neg"))
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: {
        "complete": False, "sources": [], "available": {}, "gaps": [], "blocking_gaps": []})
    monkeypatch.setattr(desk, "PENDING_EXPIRY_HOURS", 0.0)
    monkeypatch.setattr(desk, "_finalize_operator_reply", lambda t, p: (t, p))
    sender = _Sender()
    desk.try_fulfill_pending_replies(sender)
    assert "Sources:" not in sender.sent[0][1]


# ── the receipt ──────────────────────────────────────────────────────────────


def test_operator_message_event_carries_reply_provenance_with_the_monitor_field_names():
    out, txt = _ask("Is now a good time to get back into schg")
    events = [p for t, p in _Bus.emitted if t == "operator.message"]
    assert len(events) == 1
    prov = events[0]["reply_provenance"]
    assert set(("stores_read", "went_outside", "model", "sources_line_present")) <= set(prov)
    assert prov["sources_line_present"] is True and prov["went_outside"] == []
    assert any("re-entry desk" in s for s in prov["stores_read"])
    assert prov == out["reply_provenance"]
    json.dumps(prov)  # the bus serialises it


# ── the chokepoint is the only way out ───────────────────────────────────────


def test_negative_control_removing_the_chokepoint_lets_a_reply_go_without_sources(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(core, "finalize_operator_reply", lambda t, p: (t, p))
        _out, txt = _ask("Why haven't you told me anything today?")
        assert "Sources:" not in txt, "without the chokepoint the attention path sends no Sources line"
    _out, txt = _ask("Why haven't you told me anything today?")
    assert "Sources:" in txt, "restored: the same path cites its source again"


def test_every_send_in_the_converse_core_goes_through_the_chokepoint():
    """Static: in process_operator_message every `_send(...)` sends `final_reply`
    (built only by `_prepare_reply`) except the two command branches (`cmd_reply`),
    and `finalize_operator_reply` is called in exactly one place."""
    src = Path(core.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "process_operator_message")
    send_args: list[str] = []
    final_sources: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_send":
            arg = node.args[0]
            send_args.append(arg.id if isinstance(arg, ast.Name) else ast.dump(arg))
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "final_reply" for t in node.targets):
            v = node.value
            final_sources.append(v.func.id if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) else ast.dump(v))
    assert send_args and set(send_args) <= {"final_reply", "cmd_reply"}, send_args
    assert send_args.count("cmd_reply") == 2, "only slash + ack send command output"
    assert final_sources and set(final_sources) == {"_prepare_reply"}, final_sources
    assert src.count("finalize_operator_reply(") == 1


# ── the interceptor (base fix) ───────────────────────────────────────────────


@pytest.mark.parametrize("text", ["Is now a good time to get back into schg", "re-enter schg?", "can I re-enter SCHG"])
def test_reentry_interceptor_steps_aside_when_a_known_symbol_is_named(text):
    out, txt = _ask(text)
    assert out["kind"] == "operator_desk", out["kind"]
    assert "SCHG — re-entry check" in txt


@pytest.mark.parametrize("text", ["what's ready to buy back", "what can I re-enter"])
def test_reentry_interceptor_still_fires_for_book_wide_questions(text):
    out, _txt = _ask(text)
    assert out["kind"] == "reentry_facts"


# ── the chokepoint unit ──────────────────────────────────────────────────────


def test_finalize_keeps_an_existing_desk_sources_line_and_does_not_duplicate_it():
    body = "Answer.\nSources: re-entry desk · computed 2026-09-13 22:52 | re-entry desk\nREAD_ONLY_ADVISORY"
    final, prov = rp.finalize_operator_reply(body, rp.ReplyProvenance(kind="t", stores_read=["re-entry desk"]))
    lines = final.split("\n")
    assert lines == ["Answer.", rp.origin_line(["re-entry desk"], [], None),
                     "Sources: re-entry desk · computed 2026-09-13 22:52", "READ_ONLY_ADVISORY"]
    assert prov.stores_read == ["re-entry desk · computed 2026-09-13 22:52"]


def test_finalize_adds_the_default_tail_and_says_none_when_nothing_was_read():
    final, prov = rp.finalize_operator_reply("Hello", rp.ReplyProvenance(kind="t"))
    assert final.split("\n") == ["Hello", rp.origin_line([], [], None),
                                 "Sources: none — no Command Center store was read for this reply",
                                 rp.DEFAULT_TAIL]
    assert prov.sources_line_present and prov.authority_tail_present and prov.went_outside == []


def test_finalize_leaves_a_body_line_that_merely_mentions_the_authority():
    body = "• Authority: **READ_ONLY_ADVISORY** — no orders / stops / 2FA from chat\nREAD_ONLY_ADVISORY"
    final, _ = rp.finalize_operator_reply(body, rp.ReplyProvenance(kind="t", stores_read=["x"]))
    assert final.split("\n")[0].startswith("• Authority:") and final.endswith("\nREAD_ONLY_ADVISORY")


def test_desk_loop_still_exports_the_footer_under_its_old_name():
    assert desk._with_sources_footer is rp.with_sources_footer


# ── two base-footer defects found by Agent D replaying the SCHG question ─────


def _schg_card() -> str:
    from scripts.lib.cio_telegram_converse import format_reentry_symbol_reply
    return format_reentry_symbol_reply(SCHG_ROW, holding=None, computed_at=DESK_AS_OF)


def _schg_evidence(card: str) -> dict:
    """What gather_tradeai_evidence hands the footer for "get back into schg": the
    desk path in `sources` AND the symbol card in `available` -- two routes to one store."""
    return {"sources": [str(DESK_PATH)],
            "available": {"reentry_as_of": DESK_AS_OF, "reentry_card": "book", "reentry_symbol_cards": {"SCHG": card}}}


def test_schg_card_footer_is_exact_one_tail_one_desk_label():
    card = _schg_card()
    assert card.endswith("\nNo orders/stops from chat · READ_ONLY_ADVISORY")
    out = rp.with_sources_footer(card, _schg_evidence(card), {"source": "tradeai_deterministic", "model": None})
    expected_footer = ("Sources: re-entry desk · computed 2026-09-13 22:52\n"
                       "No orders/stops from chat · READ_ONLY_ADVISORY")
    assert out == card.rsplit("\n", 1)[0] + "\n" + expected_footer
    assert "No orders/stops from chat ·" not in out.split("\n"), "no orphaned half of the tail"
    assert out.count("READ_ONLY_ADVISORY") == 1


def test_negative_control_the_base_footer_orphaned_half_the_tail_and_doubled_the_label():
    """The base (ffc795f3c) algorithm, reproduced: token-strip then re-append, and a
    seen-set keyed on the rendered label."""
    card = _schg_card()
    labels, seen = [], set()
    for lab in ("re-entry desk · computed 2026-09-13 22:52", "re-entry desk"):
        if lab not in seen:
            seen.add(lab)
            labels.append(lab)
    footer = "Sources: " + " · ".join(labels)
    body = card.rstrip()
    head = body[: -len("READ_ONLY_ADVISORY")].rstrip()
    old = f"{head}\n{footer}\n{body[body.rfind(chr(10)) + 1:]}"
    lines = old.split("\n")
    assert lines[-3] == "No orders/stops from chat ·"
    assert lines[-2] == "Sources: re-entry desk · computed 2026-09-13 22:52 · re-entry desk"


def test_schg_turn_sent_to_the_operator_ends_with_the_exact_footer():
    _out, txt = _ask("Is now a good time to get back into schg")
    lines = txt.split("\n")
    # 2026-09-14: the Origin pill line sits above Sources, and a stock question now
    # reads the dossier stores too; the desk label still leads and appears once.
    assert lines[-1] == "No orders/stops from chat · READ_ONLY_ADVISORY", lines[-4:]
    assert lines[-2].startswith("Sources: re-entry desk · computed 2026-09-13 22:52"), lines[-4:]
    assert lines[-3].startswith("Origin: 🟢 Trade-AI data"), lines[-4:]
    assert "No orders/stops from chat ·" not in lines
    assert lines[-2].count("re-entry desk") == 1
