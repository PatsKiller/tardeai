"""Identity tagging must be two-way, not discovery-only.

Audited 2026-09-06: research and news carried subject_guid/issuer_guid, and the
inbound path carried nothing —

    cio_telegram_bot.py             identity_registry=0  subject_guid=0
    telegram_callback_handler.py    identity_registry=0  subject_guid=0
    run_telegram_callback_poller.py identity_registry=0  subject_guid=0

— with inbound messages not stored at all, only a checkpoint of the last
update_id. Asking "Alex, what's the analyst target for Visa?" produced nothing
tagged, nothing persisted, nothing joinable to the research that would answer it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import inbound_identity_tagger as T  # noqa: E402

#: A registry stub — these tests must not depend on which symbols happen to be
#: minted, which is the test-isolation trap AGENTS.md records for resolve_entity.
REG = {
    "entities": {
        "s-v": {"ticker_alias": "V", "aliases": ["V"], "subject_guid": "s-v",
                "security_guid": "s-v", "issuer_guid": "i-v",
                "identity_status": "CONFIRMED"},
        "s-noc": {"ticker_alias": "NOC", "aliases": ["NOC"], "subject_guid": "s-noc",
                  "security_guid": "s-noc", "issuer_guid": "i-noc",
                  "identity_status": "CONFIRMED"},
    },
    # lookup_symbol resolves through `by_symbol`, not by scanning entities.
    "by_symbol": {"V": "s-v", "NOC": "s-noc"},
}


def _tag(text):
    return T.tag_inbound(text, registry=REG)


# ── the operator's actual question ─────────────────────────────────────────

def test_the_operators_question_resolves_and_carries_topics():
    r = _tag("Alex what is the analyst target for $V, latest support and resistance?")
    assert [x["symbol"] for x in r["resolved"]] == ["V"]
    assert r["resolved"][0]["issuer_guid"] == "i-v"
    assert "analyst_target" in r["topics"]
    assert "support_resistance" in r["topics"]


def test_a_bare_ticker_resolves_too():
    r = _tag("Hey Alex how is my NOC position doing and what is the downside risk?")
    assert [x["symbol"] for x in r["resolved"]] == ["NOC"]
    assert set(r["topics"]) >= {"position", "risk"}


# ── the honest gap ─────────────────────────────────────────────────────────

def test_an_unresolvable_name_is_recorded_as_a_gap_not_silently_dropped():
    """Superseded, deliberately: this test used to assert that "Visa" was
    UNRESOLVABLE, because the registry held ticker aliases only. That premise is
    now false — company names resolve through the broker instrument feed — and a
    test whose premise the fix invalidated must be rewritten, not deleted.

    What must still hold is the honest part: a name the FEED does not carry is
    recorded as a measured gap rather than dropped, because pretending the
    question had no subject makes coverage look better than it is.
    """
    r = _tag("Alex what about Nonesuch Holdings?")
    assert r["resolved"] == []
    assert "Nonesuch Holdings" in r["unresolved_mentions"]


def test_the_agent_name_is_not_a_company():
    for r in (_tag("Alex what is up"), _tag("Hey Maria and Steph")):
        assert not r["resolved"]
        for n in ("Alex", "Maria", "Steph", "Hey"):
            assert n not in r["unresolved_mentions"], f"{n} is not a company"


def test_common_uppercase_words_are_not_symbols():
    """Without a stoplist the first question containing CIO or ETF tags a
    security, and every tag after that is suspect."""
    r = _tag("CIO what ETF should I look AT and IS the RSI OK")
    assert r["resolved"] == []


# ── determinism ────────────────────────────────────────────────────────────

def test_no_model_runs_in_the_tagger():
    """Extraction is a regex, resolution is a lookup. A tag written here is
    always deterministic; ambiguity is the advisor's job and it writes CANDIDATE."""
    src = (ROOT / "scripts" / "lib" / "inbound_identity_tagger.py").read_text(encoding="utf-8")
    low = src.lower()
    for banned in ("openai", "anthropic", "deepseek", "grok", "generate_with_fallback"):
        assert banned not in low


def test_resolution_is_pure_and_persistence_is_explicit():
    """Superseded by design: the module now has persist(), so "writes nothing" is
    false. The invariant that must hold is narrower and more useful — TAGGING is
    pure, and the ONLY writer is persist(), which a caller must invoke on purpose.

    Resolution running as a side effect of a write would make it impossible to
    tag a question without storing it.
    """
    import ast, inspect

    src = (ROOT / "scripts" / "lib" / "inbound_identity_tagger.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    writers = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = ast.unparse(node)
            if "INSERT INTO" in body or "commit()" in body:
                writers.append(node.name)
    assert set(writers) <= {"persist", "persist_turn"}, (
        f"only the persist writers may write; found {writers}")

    # And tag_inbound must not reach a database at all.
    tag_src = inspect.getsource(T.tag_inbound)
    for banned in ("INSERT", "UPDATE ", "commit", "cursor("):
        assert banned not in tag_src


def test_the_same_issuer_is_not_tagged_twice():
    r = _tag("$V and V again")
    assert len(r["resolved"]) == 1


def test_empty_input_is_safe():
    for v in ("", None):
        r = T.tag_inbound(v, registry=REG)
        assert r["resolved"] == [] and r["topics"] == []


def test_output_is_advisory_and_carries_provenance():
    r = _tag("$V target")
    assert r["authority"] == "READ_ONLY_ADVISORY"
    assert r["financial_action"] is False
    assert r["schema"] == "InboundIdentityTag@v1"


# ── company names, resolved through the BROKER FEED ────────────────────────
#
# The operator's constraint: do not invent a ticker-to-name map. The name comes
# from the same authoritative record as the CUSIP. "Visa" resolving to V is a
# lookup against Schwab's instrument feed, not a table someone typed.

def _tag_named(text, monkeypatch):
    import lib.company_name_index as C
    monkeypatch.setattr(C, "_instruments", lambda: {
        "V": {"description": "VISA INC A", "identifiers": {"cusip": "92826C839"}},
        "NOC": {"description": "NORTHROP GRUMMAN COR", "identifiers": {"cusip": "666807102"}},
    })
    C.refresh()
    return T.tag_inbound(text, registry=REG)


def test_a_company_name_now_resolves_to_the_same_issuer_as_its_ticker(monkeypatch):
    """The point of the whole exercise: both spellings land on ONE issuer_guid."""
    by_name = _tag_named("Alex what is the analyst target for Visa?", monkeypatch)
    by_ticker = T.tag_inbound("Alex what is the analyst target for $V?", registry=REG)
    assert by_name["resolved"] and by_ticker["resolved"]
    assert by_name["resolved"][0]["issuer_guid"] == by_ticker["resolved"][0]["issuer_guid"]


def test_the_match_path_is_recorded(monkeypatch):
    """A consumer must be able to tell a deterministic ticker hit from a
    name lookup without re-deriving it."""
    r = _tag_named("What is the target for Visa?", monkeypatch)
    assert r["resolved"][0]["matched_via"] == "company_name"
    assert r["resolved"][0]["matched_text"] == "Visa"
    t = T.tag_inbound("target for $V", registry=REG)
    assert t["resolved"][0]["matched_via"] == "ticker"


def test_a_multiword_company_is_not_split(monkeypatch):
    r = _tag_named("Alex how is my Northrop Grumman position?", monkeypatch)
    assert [x["symbol"] for x in r["resolved"]] == ["NOC"]
    assert "position" in r["topics"]


def test_the_agent_name_is_peeled_off_a_run(monkeypatch):
    """'Alex what is the target for Northrop Grumman' must yield the company,
    not 'Alex'."""
    r = _tag_named("Alex what is the target for Northrop Grumman", monkeypatch)
    assert [x["symbol"] for x in r["resolved"]] == ["NOC"]
    assert not any("Alex" in m for m in r["unresolved_mentions"])


def test_an_unknown_company_is_still_a_measured_gap(monkeypatch):
    r = _tag_named("Alex what about Nonesuch Holdings?", monkeypatch)
    assert r["resolved"] == []
    assert "Nonesuch Holdings" in r["unresolved_mentions"]


# ── persistence: the loop only closes if it is written down ────────────────

class _Cur:
    def __init__(self): self.rows = []
    def execute(self, sql, params): self.rows.append(params)


class _Conn:
    def __init__(self): self._c = _Cur(); self.committed = False
    def cursor(self): return self._c
    def commit(self): self.committed = True


def test_each_resolved_entity_gets_its_own_row():
    conn = _Conn()
    tag = {"resolved": [{"symbol": "V", "subject_guid": "s-v", "issuer_guid": "i-v",
                         "identity_status": "CONFIRMED", "matched_via": "ticker",
                         "matched_text": "V"},
                        {"symbol": "NOC", "subject_guid": "s-noc", "issuer_guid": "i-noc",
                         "identity_status": "CONFIRMED", "matched_via": "ticker",
                         "matched_text": "NOC"}],
           "topics": ["risk"], "unresolved_mentions": []}
    assert T.persist_turn(tag, conn=conn, text="q", role="operator") == 2
    assert conn.committed


def test_an_unresolved_question_is_still_recorded():
    """One row with null guids. An unanswerable question is the measurement of
    what the spine cannot reach; dropping it makes coverage look better than it is."""
    conn = _Conn()
    tag = {"resolved": [], "topics": [], "unresolved_mentions": ["Nonesuch Holdings"]}
    assert T.persist_turn(tag, conn=conn, text="what about Nonesuch Holdings?",
                          role="operator") == 1
    params = conn._c.rows[0]
    assert None in params            # guids are null
    assert ["Nonesuch Holdings"] in params


def test_the_operators_words_are_kept_verbatim():
    conn = _Conn()
    q = "Alex what is the analyst target for Visa?"
    T.persist_turn({"resolved": [], "topics": [], "unresolved_mentions": []},
                   conn=conn, text=q, role="operator")
    assert q in conn._c.rows[0]


# ── the wiring: built-but-not-called is the failure mode of this whole system ─

def test_the_live_bot_actually_calls_the_tagger():
    """Until 2026-09-06 all three inbound paths had identity_registry=0. The
    module existing is not the same as the bot calling it — that gap is the
    single most repeated defect in this codebase."""
    src = (ROOT / "scripts" / "lib" / "cio_telegram_converse.py").read_text(encoding="utf-8")
    assert "_best_effort_capture_turn" in src
    fn = src.split("def process_telegram_message", 1)[1].split("\ndef ", 1)[0]
    assert "_best_effort_capture_turn" in fn, "the tagger is defined but never called"


def test_tagging_is_allowlist_gated():
    """Storing arbitrary inbound text is not something to do by accident."""
    src = (ROOT / "scripts" / "lib" / "cio_telegram_converse.py").read_text(encoding="utf-8")
    fn = src.split("def process_telegram_message", 1)[1].split("\ndef ", 1)[0]
    call = fn.split("_best_effort_capture_turn", 1)[0].rsplit("if ", 1)[-1]
    assert "allowlist_chat_ids" in call, "inbound tagging must be allowlist-gated"


def test_a_tagging_failure_cannot_cost_the_operator_their_answer():
    """The reply is the product; the tag is bookkeeping. A DB outage must not
    turn into silence on the operator's phone."""
    src = (ROOT / "scripts" / "lib" / "cio_telegram_converse.py").read_text(encoding="utf-8")
    fn = src.split("def _best_effort_capture_turn", 1)[1].split("\ndef ", 1)[0]
    assert "except Exception" in fn
    assert "raise" not in fn.replace("raises", "")


def test_the_failure_is_not_silent():
    """Best-effort must not mean invisible — a tagger that has been failing for a
    month with nobody told is the shape this codebase produces most often."""
    src = (ROOT / "scripts" / "lib" / "cio_telegram_converse.py").read_text(encoding="utf-8")
    fn = src.split("def _best_effort_capture_turn", 1)[1].split("\ndef ", 1)[0]
    assert "inbound-tag" in fn and "stderr" in fn


# ── the whole exchange, both halves, one thread ────────────────────────────

def test_a_sentence_initial_english_word_is_not_a_company():
    """The agent's OWN replies poisoned the corpus on the first four-turn test:

        "You are 3.2% below resistance"  -> YOU (Clear Secure)
        "On the weekly WMT support is"   -> ON  (ON Semiconductor)

    Both are real tickers, so a Walmart question got attached to two unrelated
    issuers. A lone capitalised English word in sentence position is punctuation,
    not a company."""
    for text in ("WMT support 78.40. You are 3.2% below resistance.",
                 "On the weekly WMT support is 71.90."):
        r = T.tag_inbound(text, registry=REG)
        assert all(x["symbol"] != "YOU" for x in r["resolved"])
        assert all(x["symbol"] != "ON" for x in r["resolved"])


def test_a_real_company_still_resolves_at_the_start_of_a_sentence():
    """The suppression must not cost a genuine mention: "Walmart is down today"
    is sentence-initial and still a company."""
    assert T.extract_name_mentions("Walmart is down today, what is support?") == ["Walmart"]


def test_a_midsentence_capital_is_still_a_candidate():
    assert "Visa" in T.extract_name_mentions("what is the target for Visa today")


def test_role_is_mandatory_and_constrained():
    """Without role the corpus is unreadable — an agent cannot tell its own words
    from the operator's and would learn from its own output."""
    conn = _Conn()
    tag = {"resolved": [], "topics": [], "unresolved_mentions": []}
    with pytest.raises(ValueError):
        T.persist_turn(tag, conn=conn, text="x", role="bot")
    assert T.persist_turn(tag, conn=conn, text="x", role="agent") == 1
    assert T.persist_turn(tag, conn=conn, text="x", role="operator") == 1


class _ThreadCur:
    def __init__(self, parent_thread): self._p = parent_thread; self.rows = []
    def execute(self, sql, params=None):
        self.rows.append((sql, params))
    def fetchone(self): return (self._p,) if self._p else None


class _ThreadConn:
    def __init__(self, parent_thread=None): self._c = _ThreadCur(parent_thread)
    def cursor(self): return self._c
    def commit(self): pass


def test_a_reply_inherits_its_parents_thread():
    """A five-message back-and-forth must be one WHERE clause, not a
    reconstruction."""
    conn = _ThreadConn(parent_thread="95001")
    assert T.thread_root(conn, chat_id="c", message_id=95003,
                         reply_to_message_id=95002) == "95001"


def test_a_message_replying_to_nothing_is_its_own_root():
    conn = _ThreadConn()
    assert T.thread_root(conn, chat_id="c", message_id=95001,
                         reply_to_message_id=None) == "95001"


def test_an_orphaned_reply_roots_on_its_parent_not_itself():
    """Parent missing (bot restarted, or it predates capture). Rooting on the
    parent still groups siblings that answer the same turn — better than a new
    thread per message."""
    conn = _ThreadConn(parent_thread=None)
    assert T.thread_root(conn, chat_id="c", message_id=95009,
                         reply_to_message_id=95002) == "95002"


def test_the_bot_captures_BOTH_halves():
    """A question without its answer loses what the agent actually said about the
    issuer — most of the value."""
    src = (ROOT / "scripts" / "lib" / "cio_telegram_converse.py").read_text(encoding="utf-8")
    assert 'role="operator"' in src, "the operator turn is not captured"
    assert 'role="agent"' in src, "the agent turn is not captured"


def test_the_agent_turn_is_captured_at_the_single_send_chokepoint():
    """Wiring it at each call site would miss whichever branch someone adds next."""
    src = (ROOT / "scripts" / "lib" / "cio_telegram_converse.py").read_text(encoding="utf-8")
    send = src.split("def _send(", 1)[1].split("\n    return process_operator_message", 1)[0]
    assert "_best_effort_capture_turn" in send
    assert 'role="agent"' in send
