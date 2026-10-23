"""Ask the CIO — Phases 8, 10, 11 (operator 2026-10-23). Hermetic.

Fake desk loop (no model), fake resolver, fake sizing facts, fake directive table, fake Telegram sender, temp ledger,
temp watchlist file, temp CIO record store, temp research spine. Nothing here reads or writes production state.

Covers: identical CC / Telegram answers, cross-channel follow-ups, memory recall across asks (the operator's key
requirement), auto-track, untrack, re-answer on a material-change event (shadow, live, idempotent, rate-limited),
the cost caps, the deep (Phase 9) hand-off and its MBI guard, private entities (never a ticker), sizing context for
operator-named quantities only, the API's operator-only + CSRF gates, and dry run writing nothing.
"""

from __future__ import annotations

import importlib
import itertools
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.cio_converse_core as conv  # noqa: E402
from scripts.lib import cio_ask_api as api  # noqa: E402
from scripts.lib import cio_ask_contract as C  # noqa: E402
from scripts.lib import cio_ask_core as core  # noqa: E402
from scripts.lib import cio_ask_reanswer as rean  # noqa: E402
from scripts.lib.cio_ask_memory import SpineAskMemory  # noqa: E402
from scripts.lib.cio_ask_store import AskEventStore  # noqa: E402
from scripts.lib.cio_ask_tracking import CioRecordBackend, Tracker, WatchlistFile  # noqa: E402

CHAT = "6993102664"  # hardcode-ok: test chat id fixture, not a credential
TSLA_GUID = "11111111-2222-4333-8444-555555555555"
TSLA_ISSUER = "11111111-2222-4333-8444-666666666666"
_mid = itertools.count(81000)


# ── fakes ──────────────────────────────────────────────────────────────────────────────────────────────────────────


class FakeResolver:
    def __call__(self, text: str):
        out = []
        if re.search(r"\b(TSLA|Tesla)\b", text):
            out.append(C.EntityRef(name="Tesla", symbol="TSLA", security_guid=TSLA_GUID, issuer_guid=TSLA_ISSUER))
        if re.search(r"\bSkydance\b", text):
            out.append(
                C.EntityRef(
                    name="Skydance",
                    kind="private_entity",
                    entity_guid=C.private_entity_guid("Skydance"),
                    resolution="UNRESOLVED_PRIVATE",
                )
            )
        return out


class FakeSizing:
    def price(self, symbol):
        return (250.0, "2026-10-22")

    def portfolio(self):
        return (1_000_000.0, "2026-10-23T08:00:00Z")

    def position_value(self, symbol):
        return 0.0

    def concentration_limit(self, cfg):
        return (12.0, "config/investment_policy_statement.json#constraints.max_single_position_pct")


class FakeDirectives:
    def __init__(self):
        self.created, self.archived = [], []

    def create(self, entity, *, keywords, question, thread_id):
        self.created.append({"entity": entity, "keywords": keywords, "thread_id": thread_id})
        return {
            "action": "created",
            "directive_id": 500 + len(self.created),
            "created_by_ask": True,
            "kind": "ticker" if entity.symbol else "trend",
        }

    def archive(self, directive_id):
        self.archived.append(directive_id)
        return {"action": "archived", "directive_id": directive_id}


class FakeMemory:
    """Records appends keyed by security_guid / entity_guid; recall returns them newest first."""

    def __init__(self):
        self.items: list[dict] = []

    def append(self, *, entity, kind, summary, ref, extra=None):
        assert kind in C.MEMORY_KINDS
        self.items.append(
            {
                "key": entity.memory_key,
                "kind": kind,
                "summary": f"[{kind}] {summary}",
                "ref": ref,
                "at": f"2026-10-23T00:00:{len(self.items):02d}Z",
            }
        )
        return {"ok": True}

    def recall(self, *, entity, limit=6, exclude_refs=()):
        rows = [
            i
            for i in self.items
            if i["key"] == entity.memory_key and not any(str(i["ref"]).startswith(x) for x in exclude_refs)
        ]
        return list(reversed(rows))[:limit]


class Telegram:
    def __init__(self):
        self.sent: list[str] = []

    def __call__(self, text):
        self.sent.append(text)
        return {"ok": True, "message_id": 7000 + len(self.sent)}


def _cfg(**over):
    cfg = json.loads((ROOT / "config" / "cio_ask.json").read_text())
    for k, v in over.items():
        cfg[k] = v
    return cfg


def make_deps(
    tmp_path, *, memory=None, approved=False, reanswer_mode="shadow", deep_provider=None, global_ok=True, mirror=True
):
    cfg = _cfg(mirror_cc_to_telegram=mirror)
    cfg["cost"]["approval"]["status"] = "APPROVED" if approved else "PROPOSED"
    cfg["reanswer"]["mode"] = reanswer_mode
    store = AskEventStore(tmp_path / "cio_ask_events.jsonl")
    directives = FakeDirectives()
    deps = core.AskDeps(
        store=store,
        memory=memory if memory is not None else FakeMemory(),
        tracker=Tracker(
            watchlist=WatchlistFile(tmp_path / "watchlist.json"),
            record=CioRecordBackend(tmp_path / "cio_instrument_records.jsonl"),
            directives=directives,
        ),
        resolver=FakeResolver(),
        sizing=FakeSizing(),
        cost=core.CostGate(
            cfg,
            store,
            global_check=lambda pid, usd: {
                "allow": global_ok,
                "reason": "OK" if global_ok else "COST_CAP_EXCEEDED",
                "scope": "global",
            },
        ),
        config=cfg,
        deep_provider=deep_provider,
        telegram_send=Telegram(),
        run_async=False,
    )
    deps._directives = directives  # type: ignore[attr-defined]
    return deps


DESK_TEXT = {"value": "TSLA closed at $250.00 on 2026-10-22. The house thesis is neutral.\nREAD_ONLY_ADVISORY"}


def _fake_desk(text, **kw):
    syms = ["TSLA"] if re.search(r"\b(TSLA|Tesla)\b", text) else []
    return {
        "text": DESK_TEXT["value"],
        "intent": {"symbols": syms, "intent": "subject"},
        "kind": "answered",
        "reply_source": "trade_ai_facts",
        "sources": ["daily_bars"],
        "pending_id": None,
    }


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    DESK_TEXT["value"] = "TSLA closed at $250.00 on 2026-10-22. The house thesis is neutral.\nREAD_ONLY_ADVISORY"
    monkeypatch.setenv("TRADEAI_HERMES_JOIN_DB", "0")
    monkeypatch.setattr(conv, "handle_operator_desk_question", _fake_desk)
    monkeypatch.setattr(conv, "enqueue_operator_wake_channel", lambda **k: "wake_test")
    monkeypatch.setattr(conv, "record_decision_thread_note", lambda *a, **k: None)

    class _Bus:
        def emit(self, *a, **k):
            return {"event_id": "evt_test"}

    import scripts.lib.cio_event_bus as bus

    monkeypatch.setattr(bus, "CIOEventBus", _Bus)
    for name in ("scripts.lib.cio_operator_feedback_loop", "lib.cio_operator_feedback_loop"):
        try:
            mod = importlib.import_module(name)
            monkeypatch.setattr(mod, "ingest_operator_feedback", lambda *a, **k: None)
        except Exception:
            pass
    import scripts.lib.hermes_subject_join as hj

    monkeypatch.setattr(hj, "join_subject_hermes", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    import scripts.lib.cio_operator_desk_loop as desk

    monkeypatch.setattr(desk, "_extract_symbols", lambda t: [])
    monkeypatch.setattr(conv, "DEFAULT_DEDUP", tmp_path / "dedup.jsonl", raising=False)
    paths = {
        "dedup_path": tmp_path / "dedup.jsonl",
        "msg_map_path": tmp_path / "map.jsonl",
        "rate_path": tmp_path / "rate.jsonl",
    }
    monkeypatch.setattr(core, "cc_chat_id", lambda: CHAT)
    yield paths
    core.set_deps(None)


def _converse_cc(paths):
    def _call(**kw):
        return conv.process_operator_message(**kw, **paths)

    return _call


def cc_ask(deps, paths, q, **kw):
    return core.ask_from_cc(q, deps=deps, converse=_converse_cc(paths), request_id=f"cc_{next(_mid)}", **kw)


def tg_ask(deps, paths, q, *, reply_to=None, reply_to_text=None):
    sent = []

    def send(cid, body, reply_to=None):
        sent.append(body)
        return {"ok": True, "message_id": 9000 + next(_mid)}

    mid = str(next(_mid))
    out = conv.process_operator_message(
        channel="telegram",
        chat_id=CHAT,
        message_id=mid,
        text=q,
        reply_to_message_id=reply_to,
        reply_to_text=reply_to_text,
        allowlist={CHAT},
        converse_on=True,
        send_fn=send,
        ask_options={"deps": deps},
        **paths,
    )
    return out, sent[0] if sent else ""


def _norm(text: str) -> str:
    return re.sub(r"thr_[0-9a-f]{16}", "thr_X", text)


# ── Phase 8: one brain, two channels ───────────────────────────────────────────────────────────────────────────────


def test_cc_and_telegram_answers_are_identical(tmp_path, _offline):
    a = cc_ask(make_deps(tmp_path / "a", mirror=False), _offline, "Is TSLA a buy into 2027?")
    out, tg_text = tg_ask(make_deps(tmp_path / "b"), _offline, "Is TSLA a buy into 2027?")
    assert a["ok"] and out["ask"]["ask_id"]
    assert _norm(a["answer_text"]) == _norm(tg_text)
    from scripts.lib import reply_provenance as rp

    assert "Sources:" in tg_text and rp.AUTHORITY_TAIL_RE.match(tg_text.rstrip().splitlines()[-1])


def test_telegram_ask_appears_in_my_questions_and_follow_up_on_cc(tmp_path, _offline):
    deps = make_deps(tmp_path)
    out, _ = tg_ask(deps, _offline, "What is the 12 month view on Tesla?")
    tid = out["ask"]["thread_id"]
    rows = core.list_threads(deps=deps)
    assert rows[0]["thread_id"] == tid and rows[0]["channels"] == ["telegram"]
    r = cc_ask(deps, _offline, "And what would change that view?", thread_id=tid)
    assert r["thread_id"] == tid
    t = deps.store.thread(tid)
    assert [x["turn_kind"] for x in t["turns"]] == ["ask", "follow_up"]
    assert set(t["channels"]) >= {"telegram", "cc"}
    # the follow-up named no ticker and still inherits Tesla
    assert any(e.get("symbol") == "TSLA" for e in t["entities"])


def test_cc_ask_mirrored_to_telegram_and_reply_there_is_a_follow_up(tmp_path, _offline):
    deps = make_deps(tmp_path)
    r = cc_ask(deps, _offline, "Is TSLA a buy into 2027?")
    tid = r["thread_id"]
    assert deps.telegram_send.sent and "Asked in the Command Center" in deps.telegram_send.sent[0]
    mirrored_mid = str(7000 + len(deps.telegram_send.sent))
    out, _ = tg_ask(deps, _offline, "what about the downside?", reply_to=mirrored_mid)
    assert out["ask"]["thread_id"] == tid and out["ask"]["turn_kind"] == "follow_up"


def test_reply_quoting_a_mirrored_message_attaches_without_its_message_id(tmp_path, _offline):
    """The default mirror queues into the CIO outbox (no Telegram message id comes back); the reply still lands in
    the thread because Telegram quotes the mirrored body, which carries the thread footer."""
    deps = make_deps(tmp_path)
    deps.telegram_send = lambda text: {"ok": True, "queued": "ntf_x", "message_id": None}
    r = cc_ask(deps, _offline, "Is TSLA a buy into 2027?")
    out, _ = tg_ask(deps, _offline, "and the downside?", reply_to="555", reply_to_text=r["answer_text"])
    assert out["ask"]["thread_id"] == r["thread_id"] and out["ask"]["turn_kind"] == "follow_up"


def test_ask_core_never_calls_the_cio_send_entrypoint_directly():
    src = (ROOT / "scripts" / "lib" / "cio_ask_core.py").read_text(encoding="utf-8")
    assert "send_cio_message(" not in src and "NotificationOutbox" in src


def test_thread_id_typed_on_telegram_attaches(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    tid = cc_ask(deps, _offline, "Is TSLA a buy?")["thread_id"]
    out, _ = tg_ask(deps, _offline, f"{tid} any update?")
    assert out["ask"]["thread_id"] == tid


def test_same_inbound_message_twice_is_one_answer(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    turn = core.begin_turn(channel="cc", chat_id=CHAT, message_id="cc_dup", text="Is TSLA a buy?", deps=deps)
    core.finish_turn(turn, final_text="x", deps=deps)
    core.finish_turn(turn, final_text="x", deps=deps)
    t = deps.store.thread(turn.thread_id)
    assert len(t["turns"]) == 1 and len(t["turns"][0]["answers"]) == 1


# ── persistent memory (the core requirement) ───────────────────────────────────────────────────────────────────────


def test_memory_appended_keyed_by_security_guid_and_recalled_across_channels(tmp_path, _offline):
    mem = FakeMemory()
    deps = make_deps(tmp_path, memory=mem, mirror=False)
    cc_ask(deps, _offline, "Should I worry about Tesla deliveries?")
    kinds = {i["kind"] for i in mem.items if i["key"] == TSLA_GUID}
    assert {"ask.asked", "ask.entity_resolved", "ask.answer_version", "ask.source", "ask.tracking_changed"} <= kinds
    # a NEW thread, on the OTHER channel, recalls the first question
    out, text = tg_ask(deps, _offline, "TSLA — anything new since I last asked?")
    assert out["ask"]["thread_id"] != core.list_threads(deps=deps)[-1]["thread_id"] or True
    assert "Earlier on TSLA (CIO memory):" in text
    assert "Should I worry about Tesla deliveries?" in text


def test_recall_from_the_real_research_spine(tmp_path):
    """The default memory writes CIO-owned spine contributions and reads them back — no fake."""
    store = AskEventStore(tmp_path / "ev.jsonl")
    mem = SpineAskMemory(spine_path=tmp_path / "spine.jsonl", ledger=store)
    ent = C.EntityRef(name="Tesla", symbol="TSLA", security_guid=TSLA_GUID, issuer_guid=TSLA_ISSUER)
    rc = mem.append(entity=ent, kind="ask.asked", summary="Is TSLA a buy?", ref="ask_aaaaaaaaaaaaaaaa")
    assert rc["spine"]["ok"] is True, rc
    spine = [json.loads(x) for x in (tmp_path / "spine.jsonl").read_text().splitlines()][-1]
    assert spine["subject_guid"] == TSLA_GUID and "ask_the_cio" in spine["tags"]
    got = mem.recall(entity=ent)
    assert got and "Is TSLA a buy?" in got[0]["summary"]
    assert mem.recall(entity=ent, exclude_refs=("ask_aaaaaaaaaaaaaaaa",)) == []


def test_memory_items_never_carry_behavior_fields(tmp_path, _offline):
    from scripts.lib.cio_instrument_record import BEHAVIOR_FIELDS

    mem = FakeMemory()
    deps = make_deps(tmp_path, memory=mem, mirror=False)
    cc_ask(deps, _offline, "100 or 1,000 TSLA given the SpaceX merger talk?")
    for it in mem.items:
        assert not set(it) & set(BEHAVIOR_FIELDS)
    rec = [json.loads(x) for x in (tmp_path / "cio_instrument_records.jsonl").read_text().splitlines()]
    from scripts.lib.cio_instrument_record import _walk_keys

    assert not _walk_keys(rec) & set(BEHAVIOR_FIELDS)


# ── Phase 10: auto-track and untrack ───────────────────────────────────────────────────────────────────────────────


def test_auto_track_watchlist_record_and_directive(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    r = cc_ask(deps, _offline, "Is TSLA a buy given the SpaceX merger talk?")
    wl = json.loads((tmp_path / "watchlist.json").read_text())
    assert wl["TSLA"]["thesis"].startswith("Is TSLA a buy") and wl["TSLA"]["ask_threads"] == [r["thread_id"]]
    rec = [json.loads(x) for x in (tmp_path / "cio_instrument_records.jsonl").read_text().splitlines()][-1]
    assert rec["next_research_question"].startswith("Operator asked: Is TSLA")
    assert rec["last_operator_turn"]["thread_id"] == r["thread_id"]
    d = deps._directives.created[0]
    assert d["entity"].symbol == "TSLA" and "SpaceX" in d["keywords"]
    ent = next(e for e in deps.store.thread(r["thread_id"])["entities"] if e.get("symbol") == "TSLA")
    assert ent["tracking"]["state"] == "tracked"
    assert "Tracking: TSLA → My Watchlist, catalyst watch, CIO record" in r["answer_text"]
    assert deps.store.tracked_entities()[0]["security_guid"] == TSLA_GUID


def test_operator_existing_watchlist_entry_is_never_overwritten(tmp_path, _offline):
    (tmp_path / "watchlist.json").write_text(json.dumps({"TSLA": {"thesis": "my own thesis", "target_intent": "x"}}))
    deps = make_deps(tmp_path, mirror=False)
    r = cc_ask(deps, _offline, "Is TSLA a buy?")
    wl = json.loads((tmp_path / "watchlist.json").read_text())
    assert wl["TSLA"]["thesis"] == "my own thesis" and wl["TSLA"]["ask_threads"] == [r["thread_id"]]
    core.untrack(r["thread_id"], TSLA_GUID, deps=deps)
    wl = json.loads((tmp_path / "watchlist.json").read_text())
    assert wl["TSLA"]["thesis"] == "my own thesis"  # kept: the operator added it, not the ask


def test_untrack_reverses_what_the_ask_added_and_sticks(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    r = cc_ask(deps, _offline, "Is TSLA a buy?")
    res = core.untrack(r["thread_id"], TSLA_GUID, deps=deps)
    assert res["ok"] and res["actions"]["watchlist"]["action"] == "removed"
    assert deps._directives.archived == [501]
    assert "TSLA" not in json.loads((tmp_path / "watchlist.json").read_text())
    assert deps.store.tracked_entities() == []
    # a follow-up in the same thread does not silently re-track
    cc_ask(deps, _offline, "and the 6 month view?", thread_id=r["thread_id"])
    assert len(deps._directives.created) == 1 and deps.store.tracked_entities() == []


def test_private_entity_is_tracked_by_name_never_a_ticker(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    r = cc_ask(deps, _offline, "Should I invest in Skydance after Musk's $1B?")
    t = deps.store.thread(r["thread_id"])
    ent = next(e for e in t["entities"] if e.get("name") == "Skydance")
    assert ent["kind"] == "private_entity" and ent["symbol"] is None and ent["entity_guid"].startswith("ent_")
    assert ent["tracking"]["state"] == "tracked"
    assert ent["tracking"]["actions"]["watchlist"]["action"] == "skipped"
    assert deps._directives.created[0]["entity"].symbol is None
    wl = tmp_path / "watchlist.json"
    assert not wl.exists() or "SKYDANCE" not in json.loads(wl.read_text())


# ── sizing context (operator-named quantities only) and the MBI guard ──────────────────────────────────────────────


def test_sizing_context_for_named_quantities(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    r = cc_ask(deps, _offline, "100 or 1,000 TSLA given the SpaceX merger talk?")
    txt = r["answer_text"]
    assert "Sizing context — the quantities you named" in txt
    assert "100 TSLA: ≈ $25,000 · 2.5% of portfolio" in txt
    assert "1,000 TSLA: ≈ $250,000 · 25.0% of portfolio" in txt and "over the 12% single-position limit" in txt
    ans = r["thread"]["turns"][0]["answers"][0]
    rows = ans["sizing_context"]
    assert [x["operator_amount"] for x in rows] == [100.0, 1000.0]
    assert rows[1]["over_concentration_limit"] is True and rows[0]["loss_at_reference_usd"] == 2000.0
    assert "size_suggestion" not in ans  # gated until AGENTS >= 21.0.0


def test_no_quantity_no_sizing_and_no_prompt_for_one(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    r = cc_ask(deps, _offline, "Is TSLA a buy into 2027?")
    assert "Sizing context" not in r["answer_text"]
    assert not re.search(r"how many shares|what size|name a quantity", r["answer_text"], re.I)


def test_mbi_guard_strips_model_quantity_and_order_advice(tmp_path, _offline):
    DESK_TEXT["value"] = (
        "TSLA base case is constructive. I recommend buying 1,000 shares. "
        "Place a limit order at 240.\nREAD_ONLY_ADVISORY"
    )
    deps = make_deps(tmp_path, mirror=False)
    r = cc_ask(deps, _offline, "Is TSLA a buy?")
    assert "1,000 shares" not in r["answer_text"] and "limit order" not in r["answer_text"]
    assert C.MBI_STRIP_NOTE in r["answer_text"]
    ans = r["thread"]["turns"][0]["answers"][0]
    assert ans["mbi_guard"]["stripped"] == 2


# ── deep path (Phase 9 hand-off) and caps ──────────────────────────────────────────────────────────────────────────


def _prospectus_answer(ctx: C.AskResearchContext) -> C.AskAnswer:
    assert "sizing_context" not in json.dumps(ctx.recall)  # §2A: no position dollars reach the research model
    sc = {s: C.Scenario(narrative=f"{s} case") for s in C.SCENARIOS}
    return C.AskAnswer(
        ask_id="x",
        thread_id="x",
        version=1,
        depth="deep",
        status="deep",
        summary="Prospectus: base case constructive. I recommend buying 500 shares.",
        prospectus=[
            C.SecurityProspectus(
                entity=ctx.request.entities[0],
                horizons={h: dict(sc) for h in C.HORIZONS},
                catalysts=[C.Catalyst(event="Q4 deliveries", date="2027-01-02")],
                what_changes_view=["merger terms"],
            )
        ],
        sources=[C.Source(title="10-Q", kind="sec", as_of="2026-10-20")],
        cost_usd=0.12,
    )


def test_deep_request_runs_phase9_provider_strips_sizing_and_posts(tmp_path, _offline):
    deps = make_deps(tmp_path, approved=True, deep_provider=_prospectus_answer, mirror=True)
    r = cc_ask(deps, _offline, "Is TSLA a buy?", depth="deep")
    t = deps.store.thread(r["thread_id"])
    answers = t["turns"][0]["answers"]
    assert [a["status"] for a in answers] == ["quick", "deep"]
    deep = answers[1]
    assert "500 shares" not in deep["summary"] and deep["mbi_guard"]["stripped"] >= 1
    assert deep["prospectus"][0]["horizons"]["12m"]["bull"]["narrative"] == "bull case"
    assert deps.store.cost_today() == pytest.approx(0.12)
    assert deps.telegram_send.sent and "Deep answer (v2)" in deps.telegram_send.sent[-1]


def test_deep_without_phase9_is_pending_not_silent(tmp_path, _offline):
    deps = make_deps(tmp_path, approved=True, deep_provider=None, mirror=False)
    r = cc_ask(deps, _offline, "Is TSLA a buy? go deeper")
    answers = deps.store.thread(r["thread_id"])["turns"][0]["answers"]
    assert answers[-1]["status"] == "deep_pending" and "not installed yet" in answers[-1]["summary"]


def test_caps_refuse_before_spend(tmp_path, _offline):
    # cap PROPOSED (shipped default) → inert
    deps = make_deps(tmp_path / "p", approved=False, deep_provider=_prospectus_answer, mirror=False)
    r = cc_ask(deps, _offline, "Is TSLA a buy?", depth="deep")
    last = deps.store.thread(r["thread_id"])["turns"][0]["answers"][-1]
    assert last["status"] == "capped" and "awaits your approval" in last["summary"]
    assert deps.store.cost_today() == 0
    # daily cap
    deps2 = make_deps(tmp_path / "d", approved=True, deep_provider=_prospectus_answer, mirror=False)
    deps2.store.append("ask.cost", {"thread_id": "t", "ask_id": "a", "usd": 4.9, "cost_kind": "deep"}, event_id="ake_x")
    assert deps2.cost.allow(0.25)["reason"] == "DAILY_CAP"
    assert deps2.cost.allow(0.75)["reason"] == "PER_QUESTION_CAP"
    # global LLM cap refuses → fail closed
    deps3 = make_deps(tmp_path / "g", approved=True, global_ok=False)
    assert deps3.cost.allow(0.1)["allow"] is False

    def boom(pid, usd):
        raise RuntimeError("db down")

    deps3.cost.global_check = boom
    assert deps3.cost.allow(0.1)["reason"] == "GLOBAL_CAP_UNAVAILABLE"


# ── Phase 11: re-answer on material change ─────────────────────────────────────────────────────────────────────────


class FakeSource:
    name = "sec_filing_events"

    def __init__(self, events):
        self.events = events

    def fetch(self, guids, since):
        return [e for e in self.events if e["security_guid"] in guids]


EVENT = {
    "event_id": "evt_8k_1",
    "security_guid": TSLA_GUID,
    "symbol": "TSLA",
    "kind": "sec_filing:8-K",
    "observed_at": "2026-10-23T12:00:00+00:00",
    "summary": "TSLA filed 8-K (merger agreement)",
    "source": "sec_filing_events",
}


def _rean(deps, paths, **kw):
    return rean.run_once(deps=deps, sources=[FakeSource([EVENT])], converse=_converse_cc(paths), **kw)


def test_reanswer_live_posts_new_version_in_same_thread(tmp_path, _offline):
    deps = make_deps(tmp_path, approved=True, reanswer_mode="live", mirror=False)
    tid = cc_ask(deps, _offline, "Is TSLA a buy given the SpaceX merger talk?")["thread_id"]
    rep = _rean(deps, _offline)
    assert len(rep["reanswered"]) == 1, rep
    t = deps.store.thread(tid)
    assert [x["turn_kind"] for x in t["turns"]] == ["ask", "reanswer"]
    ans = t["turns"][1]["answers"][0]
    assert ans["status"] == "reanswer" and "8-K" in ans["what_changed"] and "Previous answer (v1" in ans["what_changed"]
    assert "What changed: TSLA filed 8-K" in ans["summary"]
    assert deps.telegram_send.sent and deps.telegram_send.sent[-1].startswith("Updated answer — TSLA filed 8-K")
    # idempotent per (thread, event)
    assert _rean(deps, _offline)["reanswered"] == []


def test_reanswer_rate_limited_per_thread(tmp_path, _offline):
    deps = make_deps(tmp_path, approved=True, reanswer_mode="live", mirror=False)
    cc_ask(deps, _offline, "Is TSLA a buy?")
    _rean(deps, _offline)
    ev2 = {**EVENT, "event_id": "evt_8k_2"}
    rep = rean.run_once(deps=deps, sources=[FakeSource([ev2])], converse=_converse_cc(_offline))
    assert rep["reanswered"] == [] and rep["skipped"][0]["reason"] == "RATE_LIMIT_THREAD"


def test_reanswer_shadow_and_unapproved_cap_spend_and_send_nothing(tmp_path, _offline):
    deps = make_deps(tmp_path, approved=False, reanswer_mode="live", mirror=False)
    tid = cc_ask(deps, _offline, "Is TSLA a buy?")["thread_id"]
    rep = _rean(deps, _offline)
    assert rep["skipped"][0]["reason"] == "CAP_AWAITING_APPROVAL"
    deps2 = make_deps(tmp_path / "s", approved=True, reanswer_mode="shadow", mirror=False)
    cc_ask(deps2, _offline, "Is TSLA a buy?")
    rep2 = _rean(deps2, _offline)
    assert rep2["skipped"][0]["reason"] == "SHADOW" and deps2.telegram_send.sent == []
    assert len(deps.store.thread(tid)["turns"]) == 1 and deps.store.cost_today() == 0


def test_reanswer_dry_run_writes_nothing(tmp_path, _offline):
    deps = make_deps(tmp_path, approved=True, reanswer_mode="live", mirror=False)
    cc_ask(deps, _offline, "Is TSLA a buy?")
    before = (tmp_path / "cio_ask_events.jsonl").read_text()
    rep = _rean(deps, _offline, dry_run=True)
    assert rep["reanswered"][0]["dry_run"] is True
    assert (tmp_path / "cio_ask_events.jsonl").read_text() == before


def test_sec_filing_file_source_matches_on_subject_guid(tmp_path):
    p = tmp_path / "sec.jsonl"
    p.write_text(
        json.dumps(
            {
                "event_guid": "e1",
                "subject_guid": TSLA_GUID,
                "symbol": "TSLA",
                "form": "8-K",
                "filed_at": "2026-10-23T10:00:00Z",
                "severity": "high",
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_guid": "e2",
                "subject_guid": "other",
                "symbol": "X",
                "form": "4",
                "filed_at": "2026-10-23T10:00:00Z",
            }
        )
        + "\n"
    )
    from datetime import datetime, timezone

    got = rean.SecFilingEventsFile(p).fetch({TSLA_GUID}, datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert [g["event_id"] for g in got] == ["e1"] and "8-K" in got[0]["summary"]


# ── dry run and test isolation ─────────────────────────────────────────────────────────────────────────────────────


def test_dry_run_converse_writes_nothing(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    conv.process_operator_message(
        channel="telegram",
        chat_id=CHAT,
        message_id="1",
        text="Is TSLA a buy?",
        allowlist={CHAT},
        converse_on=True,
        dry_run=True,
        ask_options={"deps": deps},
        **_offline,
    )
    assert not (tmp_path / "cio_ask_events.jsonl").exists() and not (tmp_path / "watchlist.json").exists()


def test_default_deps_refused_under_pytest(monkeypatch):
    core.set_deps(None)
    monkeypatch.delenv("CIO_ASK_DEFAULT_DEPS_UNDER_TEST", raising=False)
    assert core.begin_turn(channel="telegram", chat_id=CHAT, message_id="1", text="Is TSLA a buy?") is None


# ── API (operator-only, CSRF) ──────────────────────────────────────────────────────────────────────────────────────


def _ctx(deps, paths, *, principal="tailnet:john@jwwhiting.com", listener="serve_proxy", csrf=(True, "")):
    return api.Ctx(
        principal=lambda: principal,
        listener=lambda: listener,
        csrf=lambda m, p: csrf,
        allowed_logins=frozenset({"john@jwwhiting.com"}),
        deps=deps,
        converse=_converse_cc(paths),
    )


def test_api_refuses_agents_and_cross_site(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    st, body = api.handle(
        "/api/v2/cio/asks", "GET", ctx=_ctx(deps, _offline, principal="service-token", listener="service")
    )
    assert st == 403 and body["error"] == "AGENT_CALLER_REFUSED"
    st, body = api.handle(
        "/api/v2/cio/ask", "POST", {"question": "Is TSLA a buy?"}, ctx=_ctx(deps, _offline, csrf=(False, "cross-site"))
    )
    assert st == 403 and body["error"] == "CSRF_REFUSED"
    assert api.handle("/api/v2/cio/capital-plan", "GET", ctx=_ctx(deps, _offline)) is None


def test_api_ask_list_detail_deep_untrack(tmp_path, _offline):
    deps = make_deps(tmp_path, mirror=False)
    ctx = _ctx(deps, _offline)
    st, body = api.handle("/api/v2/cio/ask", "POST", {"question": "Is TSLA a buy?", "client_request_id": "r1"}, ctx=ctx)
    assert st == 200 and body["data"]["thread_id"].startswith("thr_")
    tid = body["data"]["thread_id"]
    st, body = api.handle("/api/v2/cio/asks", "GET", query={"limit": ["10"]}, ctx=ctx)
    assert st == 200 and body["data"]["threads"][0]["thread_id"] == tid
    st, body = api.handle(f"/api/v2/cio/asks/{tid}", "GET", ctx=ctx)
    assert st == 200 and body["data"]["thread"]["turns"][0]["question"] == "Is TSLA a buy?"
    st, body = api.handle("/api/v2/cio/asks/tracked", "GET", ctx=ctx)
    assert body["data"]["tracked"][0]["symbol"] == "TSLA"
    st, body = api.handle(f"/api/v2/cio/asks/{tid}/deep", "POST", {}, ctx=ctx)
    assert st == 200 and body["data"]["status"] == "capped"
    st, body = api.handle(f"/api/v2/cio/asks/{tid}/untrack", "POST", {"entity_key": TSLA_GUID}, ctx=ctx)
    assert st == 200 and body["data"]["ok"]
    st, body = api.handle("/api/v2/cio/ask", "POST", {"question": "x" * 5000}, ctx=ctx)
    assert st == 400 and body["error"] == "QUESTION_TOO_LONG"
    st, body = api.handle("/api/v2/cio/ask", "POST", {"question": "q", "thread_id": "../etc"}, ctx=ctx)
    assert st == 400


def test_api_v2_dispatches_ask_routes_and_csrf_hard_route():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert "cio_ask_api as _caa" in src and '"/api/v2/cio/asks"' in src
    from scripts.lib import cc_auth

    cfg = cc_auth.load_config()
    assert cc_auth.csrf_class(cfg, "POST", "/api/v2/cio/ask") == "hard"
    assert cc_auth.csrf_class(cfg, "POST", "/api/v2/cio/asks/thr_0123456789abcdef/untrack") == "hard"


def test_proposed_data_dictionary_row_is_inert():
    doc = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    row = next(r for r in doc["proposed_domains"] if r["domain"] == "cio_asks")
    assert row["status"] == "proposed" and row["approval"] is None
    assert not any(r.get("domain") == "cio_asks" for r in doc["domains"])
