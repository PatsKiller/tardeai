"""M5 audit 2026-09-23, Module 4d: every scheduled recommendation sender passes the
CIO stance gate; document captions pass the Communications Editor; the editor's
failure policy is an operator switch (default unchanged: open).

Offline: CIO reads are a fake query, Telegram is a fake poster, nothing is sent.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import lib.publisher_stance_gate as PSG
import scripts.lib.comms_editor as ce
import scripts.telegram_transport as tt

ROOT = Path(__file__).resolve().parent.parent

# symbol -> CIO action (None = no row on file)
STANCES = {"NOC": "BUY", "AXTI": "AVOID", "WLY": "HOLD", "FSM": "RESEARCH_MORE", "TDG": "SELL"}


def fake_query(stances=STANCES, reachable=True):
    calls: list[tuple[str, object]] = []

    def q(sql, params=None, fetch="all"):
        calls.append((sql, params))
        if not reachable:
            raise ConnectionError("db down")
        if sql.strip().upper().startswith("SELECT 1"):
            return [{"ok": 1}]
        sym = params[0][0]
        act = stances.get(sym)
        return [] if act is None else [{"symbol": sym, "action": act, "created_at": "2026-09-23 07:57:47"}]
    q.calls = calls
    return q


@pytest.fixture
def cio(monkeypatch):
    q = fake_query()
    monkeypatch.setattr(PSG, "default_db_query", lambda: q)
    return q


# ── the shared helper ───────────────────────────────────────────────────────


def test_digest_gate_splits_allowed_watch_and_held(cio):
    g = PSG.gate_bullish_symbols(["NOC", "AXTI", "WLY", "FSM", "ZZZZ", "noc"], source="t")
    assert g.allowed == ["NOC"]
    assert g.watch == ["WLY", "FSM"]
    assert g.held == ["AXTI", "ZZZZ"]
    line = g.held_line()
    assert line.startswith("⏸ Held for CIO review (2)")
    assert "AXTI (CIO AVOID)" in line and "ZZZZ (no CIO stance)" in line
    assert g.stance_notes() == [
        "[CIO Stance: WLY HOLD — shown as WATCH]",
        "[CIO Stance: FSM RESEARCH_MORE — shown as WATCH]",
    ]


def test_unreachable_store_holds_as_unavailable_not_missing(monkeypatch):
    q = fake_query(reachable=False)
    monkeypatch.setattr(PSG, "default_db_query", lambda: q)
    g = PSG.gate_bullish_symbols(["NOC"], source="t")
    assert g.held == ["NOC"] and g.outcomes["NOC"].held_reason == PSG.HELD_UNAVAILABLE
    assert "CIO store unreachable" in g.held_line()
    c = PSG.gate_card("GO NOC", "NOC", source="t")
    assert not c.send and c.held_reason == PSG.HELD_UNAVAILABLE


def test_card_hold_soft_and_pass(cio):
    held = PSG.gate_card("🔥 BUY AXTI", "AXTI", source="t")
    assert not held.send and held.held_reason == "cio_stance_conflict"
    missing = PSG.gate_card("🔥 BUY ZZZZ", "ZZZZ", source="t")
    assert not missing.send and missing.held_reason == "cio_decision_missing"
    soft = PSG.gate_card("Decision: BUY\nWLY entry zone", "WLY", source="t")
    assert soft.send and "Decision: WATCH" in soft.text and "[CIO Stance: HOLD" in soft.text
    ok = PSG.gate_card("🔥 BUY NOC", "NOC", source="t")
    assert ok.send and ok.text == "🔥 BUY NOC"


def test_card_soft_without_a_demotable_verb_says_watch_up_front(cio):
    soft = PSG.gate_card("🟢 READY *ENTRY ALERT — WLY*\nproposal advice: *BUY*", "WLY", source="t")
    assert soft.send
    assert "WATCH" in soft.text and "CIO" in soft.text


def test_stamp_never_holds_and_can_skip_the_runners_own_rows(cio):
    out = PSG.stamp_symbols("page", ["AXTI", "NOC"], exclude_decision_prefix="cio-entry-", note="n")
    assert out.splitlines()[0] == "page"
    assert "[CIO Stance: AXTI AVOID ⚠️ conflicts — n]" in out
    assert "[CIO Stance: NOC BUY — n]" in out
    sqls = [s for s, _ in cio.calls if "cio_decisions" in s]
    assert all("NOT LIKE" in s for s in sqls)
    only = PSG.stamp_symbols("digest", ["AXTI", "NOC"], only_conflicts=True)
    assert "AXTI" in only and "NOC" not in only


# ── senders ─────────────────────────────────────────────────────────────────


def test_morning_digest_drops_held_go_names_and_moves_soft_ones_to_watch(cio):
    import morning_digest as md

    go = [{"symbol": s, "score": 30} for s in ("NOC", "AXTI", "WLY")]
    allowed, watch, held_line = md._gate_go(go)
    assert [t["symbol"] for t in allowed] == ["NOC"]
    assert [t["symbol"] for t in watch] == ["WLY"]
    assert "AXTI" in held_line


def test_morning_preopen_brief_never_goes_silent_for_one_held_name(cio, monkeypatch):
    import morning_digest as md

    run = {"scored_tickers": [{"symbol": "AXTI", "decision": "GO", "score": 40}],
           "market_snapshot": {"spy_change_pct": 0.2, "vix": 15}}
    monkeypatch.setattr(md, "_load_latest_run", lambda root: run)
    monkeypatch.setattr(md, "_load_ticker_memory", lambda root: {})
    monkeypatch.setattr(md, "_ollama_narrative", lambda *a, **k: "")
    msg = md.build_preopen_brief()
    assert "No GO tickers" in msg and "Held for CIO review (1): AXTI (CIO AVOID)" in msg


def test_overnight_reenter_list_is_gated(cio):
    import overnight_digest_telegram as od

    d = {"recovery_verdicts": [
        {"symbol": "NOC", "reentry_signal": "RE_ENTER"},
        {"symbol": "TDG", "reentry_signal": "BUY"},
        {"symbol": "FSM", "reentry_signal": "RE_ENTER"},
    ]}
    msg = od.compose_message(d)
    assert "Re-enter signals: NOC" in msg
    assert "TDG (CIO SELL)" in msg
    assert "👀 Watch: FSM" in msg


def test_entry_planner_alert_holds_and_rewrites(cio, monkeypatch):
    import telegram_alert
    import watchlist_entry_planner as wep

    sent = []
    monkeypatch.setattr(telegram_alert, "send_telegram", lambda text, **kw: sent.append(text) or True)
    monkeypatch.setenv("TELEGRAM_RICH_ALERTS", "0")
    plan = {"setup_type": "pullback", "entry_zone_low": 1, "entry_zone_high": 2, "limit_price": 1.5,
            "stop_price": 1, "target_price": 3, "risk_reward": 2, "proposal": {"tag": "BUY"}}
    assert wep._alert("AXTI", plan, "ready", 1.5) is False
    assert sent == []
    assert wep._alert("WLY", plan, "ready", 1.5) is True
    assert "WATCH" in sent[-1] and "[CIO Stance:" in sent[-1]
    assert wep._alert("NOC", plan, "ready", 1.5) is True and "[CIO Stance:" not in sent[-1]


def test_entry_state_runner_stamps_instead_of_gating(cio):
    import cio_entry_state_runner as runner

    out = runner.stamp_cio_stance("CIO entry — AXTI BUY READY", ["AXTI"])
    assert out.startswith("CIO entry — AXTI BUY READY")
    assert "AXTI AVOID ⚠️ conflicts" in out and "not gated" in out


def test_smart_alert_agent_conflict_and_analyst_ratings_are_stamped_not_held(cio):
    import portfolio_alerts as pa

    msg = pa.format_analyst_message([
        {"symbol": "AXTI", "consensus": "STRONG BUY", "buy": 5},
        {"symbol": "NOC", "consensus": "BUY", "buy": 3},
    ])
    assert "<b>AXTI</b>" in msg and "<b>NOC</b>" in msg
    assert "AXTI AVOID ⚠️ conflicts" in msg and "[CIO Stance: NOC" not in msg


def _calls_before(path: Path, gate_name: str, send_name: str) -> bool:
    """The gate call appears before the send call inside the same function."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        order = [n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                 for n in ast.walk(fn) if isinstance(n, ast.Call)]
        if gate_name in order and send_name in order:
            lines = {}
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    name = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                    lines.setdefault(name, n.lineno)
            return lines[gate_name] < lines[send_name]
    return False


def test_incubator_promoter_gates_before_it_sends():
    assert _calls_before(ROOT / "scripts" / "incubator_proposal_promoter.py", "gate_card", "send_telegram")


# ── transport: editor failure policy + captions ─────────────────────────────


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMS_EDITOR_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("COMMS_EDITOR_RECEIPTS", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setattr(tt, "_interdicted", lambda: False)
    sent = []

    def post(url, payload):
        sent.append(payload)
        return {"ok": True, "status_code": 200, "response": {"ok": True, "result": {"message_id": len(sent)}}}
    return sent, post


def _broken_editor():
    def boom(*a, **k):
        raise RuntimeError("editor crashed")
    return SimpleNamespace(mode=lambda: "live", edit=boom, default_db_query=None)


def test_fail_mode_defaults_to_open(monkeypatch):
    monkeypatch.delenv("COMMS_EDITOR_FAIL_MODE", raising=False)
    assert tt.editor_fail_mode() == "open"
    monkeypatch.setenv("COMMS_EDITOR_FAIL_MODE", "nonsense")
    assert tt.editor_fail_mode() == "open"


def test_fail_mode_reads_the_host_file(tmp_path, monkeypatch):
    monkeypatch.delenv("COMMS_EDITOR_FAIL_MODE", raising=False)
    f = tmp_path / "fail_mode"
    f.write_text("closed_for_investment\n")
    monkeypatch.setenv("COMMS_EDITOR_FAIL_MODE_FILE", str(f))
    assert tt.editor_fail_mode() == "closed_for_investment"


def test_open_sends_the_original_when_the_editor_crashes(transport, monkeypatch):
    sent, post = transport
    monkeypatch.setenv("COMMS_EDITOR_FAIL_MODE", "open")
    monkeypatch.setattr(tt, "_comms_editor", _broken_editor)
    r = tt.deliver_text(token="t", chat_id="42", text="🔥 GO: AXTI", post=post)
    assert r["ok"] and sent[0]["text"] == "🔥 GO: AXTI"


def test_closed_for_investment_holds_bullish_text_only(transport, monkeypatch):
    sent, post = transport
    monkeypatch.setenv("COMMS_EDITOR_FAIL_MODE", "closed_for_investment")
    monkeypatch.setattr(tt, "_comms_editor", _broken_editor)
    held = tt.deliver_text(token="t", chat_id="42", text="🔥 <b>GO:</b> AXTI", post=post)
    assert held["suppressed"] == tt.EDITOR_UNAVAILABLE_HELD and sent == []
    stop = tt.deliver_text(token="t", chat_id="42", text="⚠️ STOP WARNING AXTI — SELL at stop", post=post)
    assert stop["ok"] and sent[-1]["text"].startswith("⚠️ STOP WARNING")
    plain = tt.deliver_text(token="t", chat_id="42", text="Backup finished", post=post)
    assert plain["ok"] and sent[-1]["text"] == "Backup finished"


class _Resp:
    ok = True
    status_code = 200

    def json(self):
        return {"ok": True, "result": {"message_id": 7}}


@pytest.fixture
def doc(tmp_path, monkeypatch):
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-1.4")
    posted = []

    def fake_post(url, data=None, files=None, timeout=None):
        posted.append(dict(data))
        return _Resp()
    monkeypatch.setattr(tt.requests, "post", fake_post)
    monkeypatch.setattr(tt, "_interdicted", lambda: False)
    monkeypatch.setenv("COMMS_EDITOR_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("COMMS_EDITOR_RECEIPTS", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setattr(ce, "subjects", lambda text, resolve=None: [])
    monkeypatch.setattr(ce, "default_db_query", lambda sql, params=None, fetch="all": [])
    monkeypatch.setattr(tt, "_comms_editor", lambda: ce)
    return f, posted


def test_caption_unchanged_when_editor_off(doc, monkeypatch):
    f, posted = doc
    monkeypatch.setenv("COMMS_EDITOR_MODE", "off")
    tt.send_document(token="t", chat_id="42", file_path=str(f), caption="*Monthly* report")
    assert posted[0]["caption"] == "*Monthly* report" and "parse_mode" not in posted[0]


def test_caption_passes_the_editor_in_live_mode(doc, monkeypatch):
    f, posted = doc
    monkeypatch.setenv("COMMS_EDITOR_MODE", "live")
    r = tt.send_document(token="t", chat_id="42", file_path=str(f), caption="*Monthly* report")
    assert posted[0]["parse_mode"] == "HTML" and "<b>Monthly</b>" in posted[0]["caption"]
    assert "comms_editor" in r


def test_held_caption_still_delivers_the_document(doc, monkeypatch):
    f, posted = doc
    monkeypatch.setenv("COMMS_EDITOR_MODE", "live")
    tt.send_document(token="t", chat_id="42", file_path=str(f), caption="*Monthly* report")
    tt.send_document(token="t", chat_id="42", file_path=str(f), caption="*Monthly* report")
    assert len(posted) == 2
    assert posted[1]["caption"].startswith("Caption held by the Communications Editor (duplicate)")
