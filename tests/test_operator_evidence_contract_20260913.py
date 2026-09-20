"""Operator evidence contract, house-research-first for themes, and the model boundary.

2026-09-13 18:56. The operator asked what sectors to concentrate on into Q3/Q4
given September seasonality and the midterm cycle. The reply came from DeepSeek's
general knowledge and said "your actual holdings, weights, and cash are not
available in my current facts (cash_pct, buying_power, holdings_for_symbols all
empty)". The CIO snapshot at that moment carried total_cash $710,933 (56% of
$1.268M), sector weights, the investment policy, risk, rotation ladders and 2,088
promoted research rows.

Offline: the snapshot is tests/fixtures/cio_snapshot_shape_20260913_1856.json --
the LIVE snapshot's 18 domain keys and payload shapes, money rounded, trimmed; the
DB is a fake db_query; the model is a fake module in sys.modules. No provider,
no database, no Telegram, no host data/ writes.
"""

from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import lib.cio_operator_desk_loop as desk  # noqa: E402
import lib.operator_evidence_contract as contract  # noqa: E402
from lib.data_broker import subject_research as sr  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "cio_snapshot_shape_20260913_1856.json"
CONTRACT = ROOT / "config" / "operator_evidence_contract.json"

#: A paraphrase of the 18:56 question (the exact text is in the Telegram log, not the repo).
Q_1856 = ("How does the market normally perform in September, and with the midterm election cycle "
          "what sectors should I concentrate on going into Q3 and Q4?")

#: The live snapshot's domain keys, copied 2026-09-13T23:14:55Z.
LIVE_DOMAINS = [
    "portfolio", "risk", "watch", "watch_intelligence", "rotation", "income", "reconciliation",
    "hermes_research", "investment_policy", "model_portfolio", "cost_basis", "transactions", "sectors",
    "holdings_detail", "cash_buying_power", "retirement", "reentry", "reentry_decision_desk",
]

RESEARCH_ROWS = [
    {"id": 1, "created_at": "2026-09-12T14:00:00+00:00", "symbol": None, "research_type": "topic_research",
     "topic": "Midterm election year sector playbook", "summary": "Defense and industrials led Q4 in the last three midterm years; Trade-AI book is 6.8% industrials.",
     "thesis": None, "gics_sector": "Industrials", "category_sector": None, "status": "promoted", "keyword_hits": 3},
    {"id": 2, "created_at": "2026-09-10T09:00:00+00:00", "symbol": None, "research_type": "topic_research",
     "topic": "Healthcare AI applications", "summary": "The research crawler returned seven sources, none of which address the topic.",
     "thesis": None, "gics_sector": "Healthcare", "category_sector": None, "status": "promoted", "keyword_hits": 2},
    {"id": 3, "created_at": "2026-09-08T09:00:00+00:00", "symbol": None, "research_type": "topic_research",
     "topic": "September seasonality and Q4 sector rotation", "summary": "Semis and software historically recover into Q4 after September weakness.",
     "thesis": None, "gics_sector": "Technology", "category_sector": None, "status": "promoted", "keyword_hits": 2},
]

#: Routing fixture, not a credential: passed into desk calls and asserted back
#: out unchanged, so its identity is irrelevant. tg_chat_ids.chat_ids() is not
#: used -- it reads TELEGRAM_CHAT_ID from the environment and returns a LIST,
#: which would break these equality assertions and make an offline test depend
#: on the host.
OPERATOR_CHAT = "6993102664"  # hardcode-ok: routing fixture, not a credential


def _snap() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeDB:
    def __init__(self, rows=None, exc=None):
        self.rows, self.exc, self.calls = rows or [], exc, []

    def __call__(self, sql, params=None, fetch="all"):
        self.calls.append((sql, params, fetch))
        if self.exc:
            raise self.exc
        return copy.deepcopy(self.rows)


def _patch_snapshot(monkeypatch, snap):
    import importlib
    for name in ("lib.data_broker.cio_portfolio", "scripts.lib.data_broker.cio_portfolio"):
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        monkeypatch.setattr(mod, "get_cio_snapshot", lambda max_age_s=60, _s=snap: copy.deepcopy(_s))


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_OPERATOR_FREEFORM_FLASH", "0")
    monkeypatch.setenv("CIO_REENTRY_FLASH", "0")
    monkeypatch.delenv("GAP_RESOLVER_LIVE", raising=False)
    monkeypatch.setattr(desk, "_known_symbols", lambda ttl_s=0: frozenset({"SCHG", "NOC", "RTX"}))
    monkeypatch.setattr(desk, "_held_positions_map", lambda: {})
    monkeypatch.setattr(desk, "PENDING_PATH", tmp_path / "pending.jsonl")
    monkeypatch.setattr(desk, "_register_gaps", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(desk, "_enqueue_hermes_research", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(desk, "_thematic_research_status",
                        lambda q: "Trade-AI holds no research on this topic yet. (Gap resolver is in dry-run — nothing was queued.)")
    db = FakeDB(RESEARCH_ROWS)
    monkeypatch.setattr(desk, "_research_db_query", db)
    _patch_snapshot(monkeypatch, _snap())
    return db


# ── 1. the contract claims every live domain and projection ─────────────────


def test_fixture_has_exactly_the_live_domain_keys():
    assert sorted(_snap()["domains"]) == sorted(LIVE_DOMAINS)


def test_contract_claims_every_live_domain_and_every_catalog_projection():
    from lib.data_broker.catalog import PROJECTIONS
    doc = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert doc["schema"] == contract.SCHEMA
    ids = [p["id"] for p in PROJECTIONS]
    assert len(ids) == 23
    cov = contract.coverage(doc, LIVE_DOMAINS, ids)
    assert cov["unclaimed_domains"] == [], cov
    assert cov["unclaimed_projections"] == [], cov
    assert cov["claimed_but_not_live_domains"] == [], cov
    assert cov["claimed_but_not_live_projections"] == [], cov
    assert cov["excused_and_claimed"] == [], cov
    assert set(cov["intents"]) >= {"reentry", "portfolio", "cash", "risk", "research", "analyst",
                                   "freeform", "meta_system", "attention"}
    assert sorted(doc["snapshot_domains_observed"]["domains"]) == sorted(LIVE_DOMAINS)
    for reason in doc["never_needed"]["domains"].values():
        assert len(reason) > 30


def test_negative_control_an_unclaimed_domain_is_reported():
    doc = json.loads(CONTRACT.read_text(encoding="utf-8"))
    cov = contract.coverage(doc, LIVE_DOMAINS + ["brand_new_domain"], [])
    assert cov["unclaimed_domains"] == ["brand_new_domain"]


# ── 2. the 18:56 snapshot -> facts populated, zero findings ──────────────────


def _freeform_evidence(text=Q_1856):
    intent = desk.analyze_operator_intent(text)
    intent.setdefault("text", text)
    return intent, desk.gather_tradeai_evidence(intent)


def test_1856_snapshot_populates_every_contract_fact_with_zero_findings(_offline):
    intent, ev = _freeform_evidence()
    assert intent["intent"] == "freeform" and intent["symbols"] == []
    f = ev["available"]["freeform_context"]
    assert f["cash"]["total_cash"] == 710933 and f["cash"]["cash_pct"] == 56.1
    assert f["cash"]["by_account"][0] == {"account": "schwab_rollover_ira", "cash": 661748}
    assert f["sector_exposure"][0] == {"sector": "Industrials", "weight_pct": 6.77, "value": 85865,
                                       "symbols": ["NOC", "RTX", "SPCX", "BAH", "XLI", "XAR"]}
    assert f["investment_policy"]["risk_level"] == "MODERATE_AGGRESSIVE"
    assert f["investment_policy"]["max_single_position_pct"] == 8.0
    assert f["model_portfolio"]["cash_target_pct"] == 5.0
    assert f["rotation"]["sectors_total"] == 13 and f["rotation"]["ladder_state"] == "UNMEASURED"
    assert f["risk"]["stops_active"] == 26
    assert ev["contract_findings"] == []
    assert not [g for g in ev["gaps"] if g.get("gap_type") == "contract"]


def test_desk_path_cash_question_reads_total_cash_not_the_keys_that_never_existed(_offline):
    intent = desk.analyze_operator_intent("how much cash do I have right now")
    assert "cash" in intent["needs"] and intent["intent"] != "freeform", intent
    ev = desk.gather_tradeai_evidence(intent)
    assert ev["available"]["book_facts"]["cash"]["total_cash"] == 710933
    assert "cash=$710,933 (56.1% of book)" in ev["available"]["book"]
    assert "None" not in ev["available"]["book"]
    assert ev["contract_findings"] == []


def test_attention_turn_carries_office_state_with_zero_findings(_offline):
    intent = desk.analyze_operator_intent("what should I be paying attention to")
    assert intent["intent"] == "attention"
    ev = desk.gather_tradeai_evidence(intent)
    office = ev["available"]["office_state"]
    assert office["reentry_counts"]["total"] == 106
    assert office["reconciliation"]["inconsistencies"] == ["HOLDINGS_SOURCE_STALE", "RESEARCH_PENDING"]
    assert office["recent_closed_trades"]["closed_trades_total"] == 121
    assert ev["contract_findings"] == []


# ── 3. a builder that drops a field is caught ────────────────────────────────


def test_a_builder_that_drops_model_portfolio_raises_missing_fact(monkeypatch):
    monkeypatch.setattr(desk, "_model_portfolio_facts", lambda snap: None)
    _, ev = _freeform_evidence()
    codes = {(x["code"], x["fact"]) for x in ev["contract_findings"]}
    assert ("MISSING_FACT", "available.freeform_context.model_portfolio.cash_target_pct") in codes
    gap = [g for g in ev["gaps"] if g.get("gap_type") == "contract"]
    assert gap and gap[0]["reason"].startswith("facts were available but not assembled")
    assert ev["available"]["freeform_context"]["contract_findings"][0]["domain"] == "model_portfolio"


def test_the_1856_shape_cash_none_is_a_false_empty_claim(monkeypatch):
    """facts['cash'] = None while the store had $710,933: exactly what the model read as 'empty'."""
    monkeypatch.setattr(desk, "_cash_facts", lambda snap, tv: None)
    _, ev = _freeform_evidence()
    hits = [x for x in ev["contract_findings"] if x["domain"] == "cash_buying_power"]
    assert hits and {h["code"] for h in hits} == {"FALSE_EMPTY_CLAIM"}, hits
    assert hits[0]["store_has"] == "710933"
    out = desk._format_freeform_failsoft(ev["available"]["freeform_context"], ev["gaps"])
    assert "Facts available but not assembled" in out and "cash_buying_power" in out


def test_negative_control_no_finding_when_the_store_lacks_it_too():
    snap = _snap()
    snap["domains"]["cash_buying_power"]["quality_state"] = "DATA_UNAVAILABLE"
    ev = {"available": {"freeform_context": {"cash": None}}}
    got = contract.check({"intent": "freeform"}, ev, snap)
    assert not [x for x in got if x["domain"] == "cash_buying_power"]


def test_checker_is_pure_and_quiet_without_a_snapshot():
    assert contract.check({"intent": "freeform"}, {}, {}) == []
    assert contract.check({"intent": "meta_system"}, {}, _snap()) == []


def test_kinds_for_intent_mirrors_gather_routing():
    assert contract.kinds_for_intent({"intent": "freeform", "needs": ["portfolio"]}) == ["freeform"]
    assert contract.kinds_for_intent({"intent": "attention", "needs": ["portfolio", "cash"]}) == ["attention", "cash", "portfolio"]
    assert contract.kinds_for_intent({"intent": "reentry", "needs": ["reentry_ready"]}) == ["reentry"]


# ── 4. thematic research from the house first ────────────────────────────────


def test_salient_keywords_for_the_1856_question():
    assert sr.salient_keywords(Q_1856) == ["september", "midterm", "election", "cycle", "sector", "q3", "q4"]


def test_search_research_is_read_only_promoted_bounded_and_binds_every_placeholder():
    db = FakeDB(RESEARCH_ROWS)
    res = sr.search_research(db, ["september", "midterm", "sector"], limit=50)
    sql, params, fetch = db.calls[0]
    assert fetch == "all"
    assert sql.lstrip().upper().startswith("SELECT") and "status = 'promoted'" in sql
    import re as _re
    for verb in ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER"):
        assert not _re.search(rf"\b{verb}\b", sql.upper()), verb  # word match: updated_at is a column
    assert sql.count("%s") == len(params)
    assert params[-1] == 20, "limit is clamped"
    assert params[-2] == 2, "three keywords need two hits"
    assert "%september%" in params
    assert res["n"] == 3 and res["as_of"].startswith("2026-09-12") and res["provider_calls"] == 0


def test_search_research_degrades_to_empty_on_a_broken_read():
    res = sr.search_research(FakeDB(exc=RuntimeError("db down")), ["september"])
    assert res["ok"] is False and res["items"] == [] and "db down" in res["error"]
    assert sr.search_research(FakeDB(), [])["items"] == []


def test_thematic_question_gets_research_on_topic_before_the_model(_offline):
    _, ev = _freeform_evidence()
    f = ev["available"]["freeform_context"]
    topics = [i["topic"] for i in f["research_on_topic"]["items"]]
    assert topics == ["Midterm election year sector playbook", "September seasonality and Q4 sector rotation"]
    assert "Healthcare AI applications" not in topics, "a crawler-failure note is not research"
    assert f["research_on_topic"]["as_of"].startswith("2026-09-12")
    assert "no research" not in f["research_status"].lower()
    assert f["research_status"].startswith("Trade-AI research on file for this topic: 2 promoted row(s)")
    assert not any(g.get("field") == "topic" for g in ev["gaps"])
    assert _offline.calls, "the broker read path was used"


def test_negative_control_no_rows_means_research_status_says_none(monkeypatch):
    monkeypatch.setattr(desk, "_research_db_query", FakeDB([]))
    _, ev = _freeform_evidence()
    f = ev["available"]["freeform_context"]
    assert "research_on_topic" not in f
    assert f["research_status"].startswith("Trade-AI holds no research on this topic yet")


# ── 5. the model boundary ────────────────────────────────────────────────────


def _facts():
    _, ev = _freeform_evidence()
    return ev["available"]["freeform_context"]


def test_validator_rejects_the_1856_false_empty_sentence(_offline):
    reply = ("Your actual holdings, weights, and cash are not available in my current facts "
             "(cash_pct, buying_power, holdings_for_symbols all empty).\nREAD_ONLY_ADVISORY")
    assert desk._validate_freeform_reply(reply, _facts()).startswith("false_empty_claim:")


def test_validator_rejects_cash_is_empty_while_facts_carry_cash(_offline):
    assert desk._validate_freeform_reply("Cash is empty right now.", _facts()) == "false_empty_claim:cash"


def test_negative_control_cash_unavailable_is_accepted_when_facts_lack_cash(_offline):
    f = _facts()
    f["cash"] = None
    assert desk._validate_freeform_reply("Cash is unavailable right now.", f) is None


def test_validator_rejects_unlabelled_seasonality(_offline):
    reply = "September is historically the weakest month and midterm years rally into Q4.\nREAD_ONLY_ADVISORY"
    assert desk._validate_freeform_reply(reply, _facts()) == "unlabelled_model_knowledge"


def test_validator_accepts_labelled_seasonality_with_its_own_numbers(_offline):
    reply = ("General market history (model knowledge, not Trade-AI data): September has averaged about -0.7% "
             "since 1950 and midterm years have tended to rally into Q4.\n\n"
             "Trade-AI: cash $710,933 (56.1%); Industrials 6.77%.\nREAD_ONLY_ADVISORY")
    assert desk._validate_freeform_reply(reply, _facts()) is None


def test_validator_rejects_an_invented_cash_number_and_accepts_rounded_real_ones(_offline):
    f = _facts()
    assert desk._validate_freeform_reply("You hold $500,000 in cash.", f) == "unsourced_number:$500,000"
    assert desk._validate_freeform_reply("Industrials are 9.5% of the book.", f) == "unsourced_number:9.5%"
    assert desk._validate_freeform_reply("You hold about $711K in cash (56%), book $1.27M.", f) is None


def test_rejected_model_reply_falls_back_to_the_deterministic_reply(monkeypatch):
    calls = []
    fake = types.ModuleType("scripts.lib.cio_plan_enrichment")
    fake.load_llm_policy = lambda: {}

    def call_governed_llm(messages, policy, use_pro=False, task_type=None):
        calls.append(messages)
        return {"ok": True, "model": "fake-flash",
                "content": "Your cash and holdings are not available (all empty). September is historically weak."}
    fake.call_governed_llm = call_governed_llm
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_plan_enrichment", fake)
    monkeypatch.setenv("CIO_OPERATOR_FREEFORM_FLASH", "1")
    f = _facts()
    out = desk.answer_freeform_with_flash(Q_1856, f, [])
    assert calls, "the fake model was called -- no real provider"
    assert out["source"] == "freeform_failsoft" and out["flash_error"].startswith("rejected:false_empty_claim")
    assert "$710,933" in out["text"] and "Industrials 6.77%" in out["text"]
    user = calls[0][1]["content"]
    assert '"total_cash": 710933' in user and "research_on_topic" in user
    assert "Midterm election year sector playbook" in user


# ── 6. the fail-soft reply and the 18:56 replay ──────────────────────────────


def test_failsoft_renders_sectors_policy_rotation_and_research(_offline):
    out = desk._format_freeform_failsoft(_facts(), [])
    when = _snap()["domains"]["rotation"]["data"]["computed_at"][:16].replace("T", " ")
    for needle in ("Cash: $710,933 (56.1% of book)", "largest schwab_rollover_ira $661,748",
                   "Sectors: Industrials 6.77%", "Policy: MODERATE_AGGRESSIVE · max single 8.0%",
                   "Model portfolio: equity target 75.0% vs actual 43.9%",
                   f"Rotation ladder (computed {when}): 13 sectors, none measured",
                   "House research on this topic", "Midterm election year sector playbook",
                   "Trade-AI research on file for this topic"):
        assert needle in out, needle


def test_failsoft_renders_a_measured_rotation_top3(monkeypatch):
    snap = _snap()
    for i, row in enumerate(snap["domains"]["rotation"]["data"]["sectors"]):
        row.update({"data_quality": 1, "rs_raw": 1.0 + i, "return_1m": 0.01 * i, "rs_score": 40 + i})
    _patch_snapshot(monkeypatch, snap)
    _, ev = _freeform_evidence()
    rot = ev["available"]["freeform_context"]["rotation"]
    assert rot["ladder_state"] == "MEASURED" and [r["etf"] for r in rot["top3"]] == ["IBB", "SMH", "XLP"]
    out = desk._format_freeform_failsoft(ev["available"]["freeform_context"], [])
    assert "top 3 by relative strength — Biotech (IBB) RS 52 · Semiconductors (SMH) RS 51 · Consumer Staples (XLP) RS 50" in out


def test_replay_1856_full_turn_answers_from_house_facts(_offline):
    res = desk.handle_operator_desk_question(Q_1856, chat_id=OPERATOR_CHAT, message_id="1856")
    assert res["kind"] == "answered", res
    txt = res["text"]
    for needle in ("$710,933", "56.1% of book", "Industrials 6.77%", "MODERATE_AGGRESSIVE",
                   "Rotation ladder", "Midterm election year sector playbook", "Sources: "):
        assert needle in txt, needle
    low = txt.lower()
    assert "empty" not in low and "not available" not in low
    assert txt.rstrip().endswith("READ_ONLY_ADVISORY")


# ── 7. a follow-up promise needs an open pending row with an ETA ─────────────
# Agent D replay 2026-09-13: the base research_status could say "research queued …
# ≈ N min, I will follow up" with no pending row behind it -- a promise no
# fulfiller would ever keep.

_ORIG_STATUS = desk.__dict__["_thematic_research_status"]
PROMISE = "Trade-AI holds no research on this topic yet; research queued via hermes_research — ≈ 30 min, I will follow up."
WITHDRAWN = "Nothing was queued; no automatic follow-up will come."


def test_thematic_research_status_never_promises_and_calls_no_resolver(monkeypatch):
    called = []
    fake = types.ModuleType("scripts.lib.gap_resolver")
    fake.resolve = lambda *a, **k: called.append(1)
    fake.DataGap = lambda **k: k
    monkeypatch.setitem(sys.modules, "scripts.lib.gap_resolver", fake)
    line = _ORIG_STATUS(Q_1856)
    assert called == [], "the evidence gather must not run the resolver (it enqueues from a read step)"
    assert "nothing was queued" in line
    assert "follow up" not in line.lower() and "≈" not in line


def test_full_turn_promise_without_a_pending_row_is_withdrawn(monkeypatch):
    monkeypatch.setattr(desk, "_research_db_query", FakeDB([]))
    monkeypatch.setattr(desk, "_thematic_research_status", lambda q: PROMISE)
    res = desk.handle_operator_desk_question(Q_1856, chat_id=OPERATOR_CHAT, message_id="1857")
    rows = [r for r in desk._read_jsonl(desk.PENDING_PATH) if r.get("chat_id") == OPERATOR_CHAT]
    assert rows == [], "no pending row was opened for this turn"
    txt = res["text"]
    assert "follow up" not in txt.lower() and "≈ 30 min" not in txt, txt
    assert WITHDRAWN in txt


def test_negative_control_the_promise_stands_only_with_an_open_pending_row_with_eta():
    text = f"• {PROMISE}\nREAD_ONLY_ADVISORY"
    kept = desk._drop_unbacked_follow_up(text, {"pending_id": "opr_x", "status": "open", "chat_id": "1", "eta_seconds": 1800})
    assert kept == text
    no_eta = desk._drop_unbacked_follow_up(text, {"pending_id": "opr_x", "status": "open", "chat_id": "1"})
    assert "follow up" not in no_eta.lower() and "≈ 30 min" not in no_eta
    none = desk._drop_unbacked_follow_up(text, None)
    assert "follow up" not in none.lower() and WITHDRAWN in none
    assert none.rstrip().endswith("READ_ONLY_ADVISORY")


def test_soft_queue_line_backed_by_a_pending_row_survives_without_eta():
    text = "Answer.\n_Queued Trade-AI research for SCHG · Pending `opr_x`_\nREAD_ONLY_ADVISORY"
    assert desk._drop_unbacked_follow_up(text, {"pending_id": "opr_x", "status": "open"}) == text


def test_model_written_follow_up_is_also_withdrawn_without_a_pending_row():
    text = "Sectors look balanced. I'll get back to you with research shortly.\nREAD_ONLY_ADVISORY"
    out = desk._drop_unbacked_follow_up(text, None)
    assert "get back to you" not in out and WITHDRAWN in out
