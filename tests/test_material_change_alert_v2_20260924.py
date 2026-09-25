"""MaterialChangeNotice@v2 — the 2026-09-24 maturity review, made executable.

The operator pasted a live notice (ROL, LTRN, KLXE, RCL, EXPE) and asked whether it
should have been sent. It should not have paged at all: none of the five was held,
none was a fresh BUY READY, two quotes were 30.7h and 112.6h old, and RCL / EXPE read
"don't buy — blocked" beside "CIO decision: Buy Ready". Tracing it found three
delivery defects under the wording:

  B1  one name's thesis ("RCL paper proposal for …") matched a dashboard-only router
      rule and held the whole eight-name batch for 179 runs;
  B2  a chunk the comms editor HELD was still marked SENT (09-24 12:22);
  B3  the idempotency key was the first row's subject, so unrelated later batches
      reused a 09-14 event id.

Operator decisions (2026-09-24): page only a HELD name (stop / target hit, material
move) or a watchlist name the CIO rates BUY_READY on a fresh quote; everything else
in one daily digest; stale quotes and inactive-strategy-no-plan names to the Command
Center only; a watchlist name through its plan stop is "PLAN INVALIDATED — re-plan or
drop", never "STOP BREACHED".

No database, no network, no Telegram.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import notify_material_change as m  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "material_change_20260924.json").read_text(encoding="utf-8"))
CHANGES = {c["symbol"]: c for c in FIXTURE["changes"]}
CTX = FIXTURE["ctx"]
CC = "https://cc.example"


def _info(sym: str) -> dict:
    return CTX[CHANGES[sym]["change_guid"]]


def _route(sym: str) -> dict:
    return m.classify(CHANGES[sym], _info(sym))


def _entries() -> list:
    return [
        (dict(c, guids=[c["change_guid"]]), CTX[c["change_guid"]], m.classify(c, CTX[c["change_guid"]]))
        for c in FIXTURE["changes"]
    ]


@pytest.fixture(autouse=True)
def _fixed_cc_base(monkeypatch):
    """Command Center links are host config; pin them so the golden text is stable."""
    for name in ("scripts.lib.telegram_rich", "lib.telegram_rich"):
        mod = sys.modules.get(name)
        if mod is None:
            try:
                mod = __import__(name, fromlist=["cc_base"])
            except ImportError:
                continue
        monkeypatch.setattr(mod, "cc_base", lambda: CC)


# ── eligibility: the pasted notice would not have paged ─────────────────────


def test_the_pasted_notice_routes_to_digest_and_command_center_not_a_page():
    routes = {s: (_route(s)["route"], _route(s)["state"]) for s in ("ROL", "LTRN", "KLXE", "RCL", "EXPE")}
    assert routes == {
        "ROL": (m.ROUTE_DIGEST, "PLAN_INVALIDATED"),
        "LTRN": (m.ROUTE_CC, "STALE_QUOTE"),
        "KLXE": (m.ROUTE_CC, "STALE_QUOTE"),
        "RCL": (m.ROUTE_DIGEST, "PLAN_INVALIDATED"),
        "EXPE": (m.ROUTE_DIGEST, "PLAN_INVALIDATED"),
    }
    assert m.render([CHANGES[s] for s in routes], CTX) == "", "none of the five may page"


def test_a_held_name_through_its_stop_pages_as_stop_hit():
    r = _route("MDT")
    assert r["route"] == m.ROUTE_PAGE and r["state"] == "STOP_HIT"


def test_a_watchlist_stop_is_plan_invalidated_never_stop_breached():
    text = "\n".join(ch["text"] for ch in m.split_digest(m.digest_blocks(_entries())))
    assert "PLAN INVALIDATED (watchlist, not held) — re-plan or drop" in text
    assert "STOP BREACHED" not in text and "STOP HIT" not in text


def test_a_stale_quote_never_reports_a_target_or_stop():
    """KLXE printed TARGET REACHED on a 112.6h-old quote."""
    r = _route("KLXE")
    assert r["route"] == m.ROUTE_CC and not r["levels"]["hit_target"] and not r["levels"]["hit_stop"]


def test_inactive_strategy_with_no_plan_is_command_center_only():
    info = {"price": 5.0, "quote_age_h": 0.2, "strategy_inactive": True}
    r = m.classify(dict(CHANGES["ROL"]), info)
    assert r["route"] == m.ROUTE_CC and r["state"] == "NO_PLAN"


def test_a_held_stale_quote_goes_to_the_digest_not_the_command_center():
    """You own it: it is never hidden, but a stale quote cannot confirm a stop."""
    info = dict(_info("MDT"), quote_age_h=30.0)
    r = m.classify(CHANGES["MDT"], info)
    assert r["route"] == m.ROUTE_DIGEST and r["state"] == "STALE_QUOTE"


def test_freshness_uses_the_cio_entry_checks_own_bar():
    from scripts.lib.cio_entry_state import MAX_QUOTE_AGE_H

    assert m.max_quote_age_h() == float(MAX_QUOTE_AGE_H)
    assert m.quote_is_fresh({"price": 1.0, "quote_age_h": MAX_QUOTE_AGE_H})
    assert not m.quote_is_fresh({"price": 1.0, "quote_age_h": MAX_QUOTE_AGE_H + 0.1})
    assert not m.quote_is_fresh({"price": 1.0})


# ── consistency: one CIO verdict ────────────────────────────────────────────


@pytest.mark.parametrize("sym", ["RCL", "EXPE"])
def test_one_cio_verdict_never_dont_buy_beside_buy_ready(sym):
    route = _route(sym)
    line = m.digest_line(dict(CHANGES[sym], guids=[]), _info(sym), route)
    assert line.count("CIO:") == 1
    assert "HOLD-OFF (price is at or below the plan stop)" in line
    assert "BUY READY (2026-09-22) superseded by the entry check" in line
    assert "don't buy" not in line.lower() and "CIO decision:" not in line


def test_entry_class_decisions_are_excluded_like_the_runner_does():
    src = (ROOT / "scripts" / "notify_material_change.py").read_text(encoding="utf-8")
    assert "action_class IS DISTINCT FROM 'entry'" in src
    runner = (ROOT / "scripts" / "cio_entry_state_runner.py").read_text(encoding="utf-8")
    assert "action_class <> 'entry'" in runner


def test_plan_source_matches_the_runner_entry_plan_first():
    src = (ROOT / "scripts" / "notify_material_change.py").read_text(encoding="utf-8")
    body = src.split("def _watch_context(", 1)[1].split("\ndef ", 1)[0]
    assert body.index("FROM watchlist_entry_plans") < body.index("FROM watchlist_strategy_cards")
    assert "interval '7 days'" in body


def test_an_old_entry_check_says_how_old_it_is():
    """Replay 2026-09-24: a 32m quote beside 'HOLD-OFF (quote is 16.7h old)' from last night's check."""
    text = m.cio_verdict({"entry_state": {"state": "BLOCKED", "reasons": ["quote is 16.7h old"], "age_h": 16.9}})[
        "text"
    ]
    assert text == "HOLD-OFF (quote is 16.7h old) [state set 17h ago]"
    fresh = m.cio_verdict({"entry_state": {"state": "BLOCKED", "reasons": ["x"], "age_h": 0.5}})["text"]
    assert "state set" not in fresh


def test_near_entry_distance_is_never_signed_wrong():
    """PSQL printed "price is -2.2% above the entry"."""
    text = m.cio_verdict({"entry_state": {"state": "ENTRY_NEAR", "distance_pct": -2.2}})["text"]
    assert text == "NEAR ENTRY (2.2% away)"


# ── golden snapshots ────────────────────────────────────────────────────────

GOLDEN_PAGE = """🚨 STOP HIT — MDT (held, 120 sh)
$78.10 · quote 3m · -6.1% (3.4× its normal daily move) · stop $78.50
CIO: TRIM REVIEW (2026-09-23) · no news explains the move
▶ Action: review exit — price is through your plan stop
Material change · Advisory only. No position action taken or implied."""

GOLDEN_DIGEST = f"""📋 Material change — daily digest · Thu 24 Sep · 16:15 ET

⛔ PLAN INVALIDATED (watchlist, not held) — re-plan or drop
  ROL $30.24 (15m) · -4.2% (3.1× its normal daily move) · stop $31.57 · CIO: no stance on file
  RCL $233.72 (15m) · -5.0% (3.0× its normal daily move) · stop $238.08 · CIO: HOLD-OFF (price is at or below the plan stop) · decision BUY READY (2026-09-22) superseded by the entry check
  EXPE $258.13 (15m) · -7.0% (3.0× its normal daily move) · stop $260.84 · CIO: HOLD-OFF (price is at or below the plan stop) · decision BUY READY (2026-09-22) superseded by the entry check

🔕 Not shown: LTRN (quote 31h old), KLXE (quote 4.7d old) → Command Center
Details → Command Center {CC}/v3/watch/intelligence · Advisory only."""


def test_golden_page_for_a_held_stop_hit():
    assert m.render([CHANGES["MDT"]], CTX) == GOLDEN_PAGE


def test_golden_digest_for_the_pasted_notice():
    now = datetime(2026, 9, 24, 20, 15, tzinfo=timezone.utc)
    chunks = m.split_digest(m.digest_blocks([e for e in _entries() if e[0]["symbol"] != "MDT"], now=now))
    assert len(chunks) == 1
    assert chunks[0]["text"] == GOLDEN_DIGEST
    assert sorted(chunks[0]["guids"]) == sorted(
        CHANGES[s]["change_guid"] for s in ("ROL", "RCL", "EXPE", "LTRN", "KLXE")
    )


def test_the_rich_page_has_one_link_and_one_footer():
    text = m.render_rich([CHANGES["MDT"]], CTX)["text"]
    assert text.splitlines()[0] == "<b>🚨 STOP HIT — MDT (held, 120 sh)</b>"
    assert text.count("<a href=") == 1 and f"{CC}/v3/watch/intelligence/MDT" in text
    assert text.count("Advisory only") == 1
    for noise in ("finviz.com/quote", "finance.yahoo.com", "Sector:", "Thesis", "found by"):
        assert noise not in text


def test_a_page_is_at_most_four_lines_plus_the_footer():
    lines = m.render([CHANGES["MDT"]], CTX).splitlines()
    assert len(lines) <= 5 and len("\n".join(lines)) <= m.MAX_MESSAGE_CHARS


# ── length: digest splits only on ticker boundaries ─────────────────────────


def test_the_digest_splits_on_ticker_boundaries_and_keeps_every_guid():
    base = _entries()[0]
    many = []
    for i in range(60):
        c = dict(base[0], symbol=f"T{i:02d}", change_guid=f"g-{i}", guids=[f"g-{i}"])
        many.append((c, base[1], base[2]))
    chunks = m.split_digest(m.digest_blocks(many), limit=900)
    assert len(chunks) > 1
    for ch in chunks:
        assert len(ch["text"]) <= 900
        assert ch["text"].rstrip().endswith("Advisory only.")
        for ln in ch["text"].splitlines():
            if ln.startswith("  T"):
                assert ln.split()[0] in {f"T{i:02d}" for i in range(60)}  # never a cut line
    assert sorted(g for ch in chunks for g in ch["guids"]) == sorted(f"g-{i}" for i in range(60))


# ── B1: one name's prose cannot suppress another ────────────────────────────


class _Cur:
    def __init__(self):
        self.stamped: list[list[str]] = []
        self.noted: list[tuple] = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        if "notified_at = now()" in sql:
            self.stamped.append(list(params[1]))
            self.rowcount = len(params[1])
        elif "SET notify_outcome" in sql:
            self.noted.append((params[0], list(params[1])))


class _Conn:
    def commit(self):
        pass


def _page_entries(*syms):
    out = []
    for s in syms:
        c = dict(CHANGES["MDT"], symbol=s, change_guid=f"g-{s}", guids=[f"g-{s}"])
        info = dict(_info("MDT"))
        out.append((c, info, m.classify(c, info)))
    return out


def test_each_page_is_routed_and_sent_on_its_own(monkeypatch):
    sent = []
    monkeypatch.setattr(m, "deliver_notice", lambda msg, **kw: (sent.append(msg) or True, {}))
    monkeypatch.setattr(m, "capture_agent_turns", lambda *a, **k: 0)
    entries = _page_entries("AAA", "BBB")
    entries[0][1]["narrative"] = ["AAA paper proposal for dividend_growth_compounder is on watch."]
    cur, result = _Cur(), {}
    m.run_pages(cur, _Conn(), entries, apply=True, result=result)
    assert len(sent) == 2, "one message per page"
    assert result["page_outcomes"] == {"AAA": "SENT", "BBB": "SENT"}
    assert cur.stamped == [["g-AAA"], ["g-BBB"]]


def test_a_suppressed_page_does_not_hold_the_others(monkeypatch):
    sent = []
    monkeypatch.setattr(m, "route_check", lambda msg: "WOULD_SUPPRESS" if "AAA" in msg else "WILL_SEND")
    monkeypatch.setattr(m, "deliver_notice", lambda msg, **kw: (sent.append(msg) or True, {}))
    monkeypatch.setattr(m, "capture_agent_turns", lambda *a, **k: 0)
    cur, result = _Cur(), {}
    m.run_pages(cur, _Conn(), _page_entries("AAA", "BBB"), apply=True, result=result)
    assert result["page_outcomes"] == {"AAA": "WOULD_SUPPRESS", "BBB": "SENT"}
    assert cur.stamped == [["g-BBB"]] and ("WOULD_SUPPRESS", ["g-AAA"]) in cur.noted


# ── B2: held by the editor is not delivered ─────────────────────────────────


def test_an_editor_hold_is_recorded_by_the_raw_sender(monkeypatch):
    import telegram_alert as ta

    calls = {"n": 0}

    def fake_send_message(**kw):
        calls["n"] += 1
        if calls["n"] == 2:
            return {"ok": True, "message_id": None, "suppressed": "cio_disagreement:B"}
        return {"ok": True, "message_id": 100 + calls["n"]}

    monkeypatch.setattr(ta, "send_message", fake_send_message)
    monkeypatch.setattr(ta, "_token", lambda: "t")
    monkeypatch.setattr(ta, "_smart_split", lambda text, limit: ["one", "two"])
    monkeypatch.setitem(sys.modules, "report_capture", types.SimpleNamespace(capture=lambda *a, **k: None))
    out = ta._raw_send_telegram_result("body", chat_ids=["c1"])
    assert out["ok"] is True, "ok is unchanged for every existing caller"
    assert out["held"] == [{"chat_id": "c1", "chunk": 1, "reason": "cio_disagreement:B"}]
    assert ta.last_held_chunks() == out["held"]


def test_the_held_record_is_shared_across_both_import_paths(monkeypatch):
    import telegram_alert as a

    a._held_bucket()["held"] = [{"chat_id": "c", "chunk": 0, "reason": "duplicate"}]
    try:
        from scripts import telegram_alert as b
    except ImportError:
        pytest.skip("scripts package import unavailable")
    assert b.last_held_chunks() == a.last_held_chunks()
    a._held_bucket()["held"] = []


def test_legacy_delivery_with_a_held_chunk_is_not_delivered(monkeypatch):
    monkeypatch.delenv(m.GATEWAY_NOTICE_FLAG, raising=False)
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda msg, **kw: True
    fake.last_held_chunks = lambda: [{"chat_id": "c", "chunk": 0, "reason": "cio_decision_missing:S"}]
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    accepted, report = m.deliver_notice("x", subject_key="k")
    assert accepted is False and report["held"]


def test_gateway_delivery_with_a_held_chunk_is_not_delivered(monkeypatch):
    from scripts.lib.comms import channel_adapters as ca

    monkeypatch.setenv(m.GATEWAY_NOTICE_FLAG, "1")
    monkeypatch.setattr(
        ca,
        "send_via_gateway",
        lambda ch, **kw: {"delivered": True, "provider_coordinates": {"held": [{"chunk": 1, "reason": "duplicate"}]}},
    )
    accepted, report = m.deliver_notice("x", subject_key="k")
    assert accepted is False and report["held"] == [{"chunk": 1, "reason": "duplicate"}]


def test_the_gateway_adapter_carries_held_chunks_in_its_coordinates():
    src = (ROOT / "scripts" / "lib" / "comms" / "channel_adapters.py").read_text(encoding="utf-8")
    body = src.split("def _provider_send_telegram(", 1)[1].split("\ndef ", 1)[0]
    assert '"held": list(result.get("held") or [])' in body


def test_a_held_page_stays_pending_and_counts_its_retries(monkeypatch):
    monkeypatch.setattr(m, "deliver_notice", lambda msg, **kw: (False, {"held": [{"reason": "cio_disagreement:B"}]}))
    cur, result = _Cur(), {}
    m.run_pages(cur, _Conn(), _page_entries("AAA"), apply=True, result=result)
    assert cur.stamped == [], "a held page must not consume its change"
    assert cur.noted[0][0].startswith("HELD_BY_EDITOR:1:cio_disagreement:B")


def test_a_page_held_too_often_falls_to_the_digest(monkeypatch):
    monkeypatch.setattr(m, "context", lambda cur, row: dict(_info("MDT")))
    row = dict(CHANGES["MDT"], notify_outcome=f"HELD_BY_EDITOR:{m.MAX_HOLD_RETRIES}:duplicate")
    ((_c, _i, route),) = m.route_all(object(), [row])
    assert route["route"] == m.ROUTE_DIGEST and route["state"] == "HELD_NEWS"


# ── B3 / B4: idempotency and ordering ───────────────────────────────────────


def test_the_notice_key_is_the_set_of_changes_it_announces():
    assert m.notice_key(["a", "b"]) == m.notice_key(["b", "a"])
    assert m.notice_key(["a", "b"]) != m.notice_key(["a"])
    assert m.notice_key(["a"]) != m.notice_key(["c"])


def test_held_names_page_before_bigger_watchlist_moves():
    rows = [dict(CHANGES["RCL"], magnitude=9.0, precedence=40), dict(CHANGES["MDT"], magnitude=3.4, precedence=80)]
    assert [r["symbol"] for r in m.dedupe_by_symbol(rows)] == ["MDT", "RCL"]


def test_a_collapsed_name_consumes_every_row_it_stands_for():
    a = dict(CHANGES["MDT"], change_guid="g1", magnitude=3.4)
    b = dict(CHANGES["MDT"], change_guid="g2", magnitude=5.0)
    (one,) = m.dedupe_by_symbol([a, b])
    assert sorted(one["guids"]) == ["g1", "g2"] and one["change_guid"] == "g2"


# ── the router recognises the notice first ──────────────────────────────────


def test_the_router_pages_the_page_and_the_digest():
    from telegram_alert_router import classify_alert, should_send_telegram

    page = m.render([CHANGES["MDT"]], CTX)
    digest = m.split_digest(m.digest_blocks(_entries()))[0]["text"]
    for text in (page, digest):
        assert classify_alert(text) == "P0_INTERRUPT" and should_send_telegram(text)


def test_content_after_the_marker_cannot_reroute_it():
    from telegram_alert_router import should_send_telegram

    msg = m.render(
        [CHANGES["MDT"]],
        {
            CHANGES["MDT"]["change_guid"]: dict(
                _info("MDT"), headline="Device approved by the FDA; paper proposal on watch", headline_kind="catalyst"
            )
        },
    )
    assert should_send_telegram(msg)


def test_it_stays_advisory():
    page = m.render([CHANGES["MDT"]], CTX).lower()
    for banned in ("sell now", "buy now", "place order", "shares to buy", "position size"):
        assert banned not in page
    assert m.AUTHORITY == "READ_ONLY_ADVISORY"
