"""Telegram decision cards (operator 2026-10-08: "the ticker becomes the focus") — layout + routing equivalence.

The card layout must not change how an alert is ROUTED: operator_alert_policy_v2 (type/severity), the daily-budget
exemption, and the Communications category all read the text. Every shape below is rendered both ways (cards off =
the previous layout, cards on = the new one) and must route identically. Fakes only: nothing is sent.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import telegram_cards as tc  # noqa: E402
from scripts.lib import telegram_rich as tr  # noqa: E402
from scripts.lib.comms import classify as cl  # noqa: E402
import operator_alert_policy_v2 as policy  # noqa: E402
import telegram_alert_router as router  # noqa: E402

BASE = {"symbol": "SWMR", "price": 14.04, "entry_low": 13.90, "entry_high": 14.50, "stop": 12.80, "target": 22.00,
        "rr_at_current_price": 6.45, "company": "Swarmer Inc.", "sector": "Technology",
        "industry": "Software Infrastructure", "cio_stance": "HUMAN_REVIEW",
        "options_reasons": ["PE MISSING — thesis PE not on house file", "Options chain unavailable"]}
ENTRY_SHAPES = {
    "ready_unreviewed": {**BASE, "state": "BUY_READY", "held": False},
    "ready_reviewed": {**BASE, "state": "BUY_READY", "held": False, "cio_review_id": "r1"},
    "near": {**BASE, "state": "NEAR_ENTRY", "held": False},
    "held": {**BASE, "state": "BUY_READY", "held": True},
    "blocked": {**BASE, "state": "BLOCKED", "held": False, "first_hard_block": "Earnings in 2 days"},
}


def _render(item, monkeypatch, cards: bool):
    monkeypatch.setattr(tc, "enabled", lambda family: cards)
    return tr.cio_entry_alert(dict(item)).render()


def _route(text: str):
    ev = policy.classify_legacy_message(text)
    return (ev.alert_type, ev.severity, bool(router._OPS_EXEMPT_PATTERN.search(text)),
            cl.classify(body=text)["category"])


@pytest.mark.parametrize("shape", list(ENTRY_SHAPES))
def test_entry_card_routes_like_the_old_layout(shape, monkeypatch):
    old = _render(ENTRY_SHAPES[shape], monkeypatch, False)["text"]
    new = _render(ENTRY_SHAPES[shape], monkeypatch, True)["text"]
    assert old != new
    assert _route(new) == _route(old), shape
    assert "SWMR" in cl.symbols_in(new)


def test_entry_card_layout(monkeypatch):
    out = _render(ENTRY_SHAPES["ready_unreviewed"], monkeypatch, True)
    plain = re.sub(r"<[^>]+>", "", out["text"])
    lines = [l for l in plain.splitlines() if l.strip()]
    assert lines[0] == "🟡 HIGH CONVICTION ENTRY" and lines[1] == "$SWMR"          # what, then the ticker alone
    for label in ("STATUS", "ACTION REQUIRED", "ENTRY", "STOP", "TARGET", "COMPANY", "CIO VERDICT"):
        assert any(l.endswith(label) for l in lines), label
    assert "Zone: $13.90 - $14.50" in plain and "R:R 6.45" in plain and "Software Infrastructure" in plain
    assert "PE MISSING" in plain and "What kills the idea" in plain and "TTL: 4 days" in plain
    assert [b["text"] for b in out["reply_markup"]["inline_keyboard"][0]] == ["Open Research", "Open Trading View",
                                                                              "Review Position"]
    assert "nothing executed" in out["text"] and len(out["text"]) <= tr.MAX_TEXT and out["parse_mode"] == "HTML"


def test_green_only_when_the_cio_reviewed_it(monkeypatch):
    assert _render(ENTRY_SHAPES["ready_unreviewed"], monkeypatch, True)["text"].startswith("🟡")
    assert _render(ENTRY_SHAPES["ready_reviewed"], monkeypatch, True)["text"].startswith("🟢")
    assert "ENTRY BLOCKED" in _render(ENTRY_SHAPES["blocked"], monkeypatch, True)["text"]
    assert "ADD-ON ENTRY" in _render(ENTRY_SHAPES["held"], monkeypatch, True)["text"]


def test_a_card_failure_falls_back_to_the_old_layout(monkeypatch):
    monkeypatch.setattr(tc, "enabled", lambda family: True)
    monkeypatch.setattr(tc, "entry_card", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "CIO ENTRY ALERT" in tr.cio_entry_alert(dict(ENTRY_SHAPES["near"])).render()["text"]


# ── stop health ─────────────────────────────────────────────────────────────

def _old_stop(batch):
    """The previous stop_health_check text, verbatim shape."""
    if len(batch) == 1:
        sev, cond, sym, acct, line = batch[0]
        return f"{'🚨' if sev == 'urgent' else '⚠️'} STOP HEALTH — {cond}: *{sym}* ({acct})\n{line}"
    n_urgent = sum(1 for b in batch if b[0] == "urgent")
    head = f"{'🚨' if n_urgent else '⚠️'} STOP HEALTH — {len(batch)} alert(s)"
    if n_urgent and n_urgent < len(batch):
        head += f" ({n_urgent} urgent)"
    return head + "\n\n" + "\n\n".join(f"{'🚨' if s == 'urgent' else '⚠️'} {c}: *{y}* ({a})\n{l}" for s, c, y, a, l in batch)


STOP_SHAPES = {
    "orphaned": [("urgent", "ORPHANED", "DT", "schwab_rollover_ira", "stop with no matching holding (#1) — cancel it.")],
    "near": [("warning", "NEAR_TRIGGER", "CDW", "tradeai_automated", "price within 1.2% of stop $120 — about to fire.")],
    "triggered": [("urgent", "TRIGGERED", "PFLT", "schwab_taxable", "stop FILLED (#9) — position may be flat; review.")],
    "batch_mixed": [("urgent", "ORPHANED", "DT", "a", "x"), ("warning", "NEAR_TRIGGER", "SPCX", "b", "y"),
                    ("warning", "NEAR_TRIGGER", "SPCX", "c", "z")],
    "batch_warning": [("warning", "NEAR_TRIGGER", "DT", "a", "x"), ("warning", "NEAR_TRIGGER", "PFLT", "b", "y")],
}


@pytest.mark.parametrize("shape", list(STOP_SHAPES))
def test_stop_card_routes_like_the_old_layout(shape):
    batch = STOP_SHAPES[shape]
    old = _old_stop(batch)
    new = tc.stop_health_card([{"symbol": y, "account": a, "condition": c, "severity": s, "line": l}
                               for s, c, y, a, l in batch])
    got, was = _route(new["text"]), _route(old)
    if shape == "batch_warning":
        # Deliberate correction: the old two-line batch never put STOP and NEAR on one line, so a warning-only batch
        # routed as job_telemetry (OPS digest). The card says "STOP HEALTH — NEAR TRIGGER", so it is stop_warning
        # (RISK digest). Same channel (digest), right bucket.
        assert (was[0], got[0]) == ("job_telemetry", "stop_warning")
        assert got[2:] == was[2:]                     # same budget exemption, same Communications category
    else:
        assert got == was, shape
    assert set(new["symbols"]) == {b[2] for b in batch}


def test_stop_card_layout():
    out = tc.stop_health_card([{"symbol": "DT", "account": "schwab_rollover_ira", "condition": "ORPHANED",
                                "severity": "urgent", "line": "stop with no matching holding"}])
    plain = re.sub(r"<[^>]+>", "", out["text"])
    lines = [l for l in plain.splitlines() if l.strip()]
    assert lines[0] == "🚨 CRITICAL STOP ALERT" and lines[1] == "$DT"
    assert "STOP HEALTH — ORPHANED" in plain and "Urgent alerts: 1" in plain and "Total alerts: 1" in plain
    assert "Review stop placement immediately" in plain and "TTL:" in plain
    assert [b["text"] for b in out["reply_markup"]["inline_keyboard"][0]] == ["Open Position", "Check Stops"]


def test_topic_keys_differ_per_symbol_for_card_headers(monkeypatch):
    a = _render(ENTRY_SHAPES["near"], monkeypatch, True)["text"]
    b = a.replace("SWMR", "TDG")
    assert cl.topic_key("reward", a) != cl.topic_key("reward", b)


def test_producers_are_wired():
    assert "telegram_cards" in (ROOT / "scripts" / "lib" / "telegram_rich.py").read_text()
    sh = (ROOT / "scripts" / "stop_health_check.py").read_text()
    assert "stop_health_card(" in sh and '_send_telegram(card["text"]' in sh
    assert set(tc.ENTRY_HEADERS) <= set(re.findall(r"[A-Z][A-Z -]+[A-Z]", (ROOT / "scripts" / "telegram_alert_router.py").read_text()))


# ── Command Center decision layout (operator 2026-10-08) ────────────────────

def test_command_center_decision_layout_is_wired():
    src = ROOT / "apps/command-center-v3/src"
    parts = (src / "components/decision/DecisionParts.tsx").read_text()
    for fam, tone in (("critical", "danger"), ("high", "warning"), ("medium", "info"), ("opportunity", "success"),
                      ("security", "ai")):
        assert f"{fam}: '{tone}'" in parts                                  # strict colour discipline, tokens only
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", parts)
    home = (src / "pages/HomeHub.tsx").read_text()
    assert home.index("<HomeDecision") < home.index("market-posture strip")   # decisions before everything else
    assert '<Collapsible title="More metrics"' in home
    hd = (src / "components/decision/HomeDecision.tsx").read_text()
    assert hd.index("<RequiresAttention") < hd.index("<BestOpportunities") < hd.index("<TopRisks")
    comms = (src / "pages/CommunicationsHub.tsx").read_text()
    assert "<BoardCards" in comms and "<FeedCard" in comms and "scores P·C·R·Rw·T" not in comms
    assert "BigNumberCard" in (src / "components/watch/WatchDecisionParts.tsx").read_text()
