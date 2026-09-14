"""Rich Telegram layouts reach the wire: GO alerts, entry alerts, material-change notices.

Operator 2026-09-14: "no emphasis in links on everything that can go back to the command center or to
the source ... install the bot API and let's make this happen." The layouts existed in telegram_rich but
no producer used them, and the transport could not carry link_preview_options (the chart on top).

Offline: every send is faked. No network, no database, no Telegram.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CHART = "charts2-node.finviz.com/chart.ashx"


def _fresh_transport():
    """A private copy: tests/conftest.py replaces send paths on the shared module."""
    spec = importlib.util.spec_from_file_location("tt_rich_wiring", ROOT / "scripts" / "telegram_transport.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── transport ────────────────────────────────────────────────────────────────

def test_payload_carries_link_preview_options():
    tt = _fresh_transport()
    lpo = {"url": "https://charts2-node.finviz.com/chart.ashx?t=AXTI", "prefer_large_media": True}
    payload = tt._base_payload("1", "x", thread_id=None, reply_markup=None, parse_mode="HTML",
                               link_preview_options=lpo)
    assert payload["link_preview_options"] == lpo
    assert "link_preview_options" not in tt._base_payload("1", "x", thread_id=None, reply_markup=None,
                                                          parse_mode=None)


def test_refused_html_is_resent_readable_not_with_tags(monkeypatch):
    tt = _fresh_transport()
    monkeypatch.setattr(tt, "_interdicted", lambda: False)
    posted = []

    def post(url, payload):
        posted.append(payload)
        return {"ok": len(posted) > 1, "status_code": 200 if len(posted) > 1 else 400,
                "response": {"result": {"message_id": 7}}}
    html_text = '<b><a href="https://h.example/v3/watch/intelligence/AXTI">AXTI</a></b> &amp; <i>chart</i>'
    res = tt._deliver_text_raw(token="t", chat_id="1", text=html_text, parse_mode="HTML", post=post,
                               link_preview_options={"is_disabled": True})
    assert res["ok"] and res["plain_fallback"]
    plain = posted[1]["text"]
    assert "<" not in plain and "AXTI (https://h.example/v3/watch/intelligence/AXTI) & chart" == plain
    assert posted[0]["link_preview_options"] == {"is_disabled": True}


def test_send_telegram_threads_the_preview_to_the_legacy_sender(monkeypatch):
    import telegram_alert as ta

    seen = {}
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_comms_gateway_owns", lambda mc: False)
    monkeypatch.setattr(ta, "_best_effort_comms_publish", lambda *a, **k: None)

    def legacy(message, bypass_router, **kw):
        seen.update(kw, message=message, bypass_router=bypass_router)
        return True
    monkeypatch.setattr(ta, "_legacy_send", legacy)
    lpo = {"url": "https://charts2-node.finviz.com/chart.ashx?t=ARMP"}
    assert ta.send_telegram("<b>x</b>", bypass_router=True, link_preview_options=lpo)
    assert seen["link_preview_options"] == lpo and seen["bypass_router"] is True


def test_raw_send_puts_the_preview_on_the_first_part_only(monkeypatch):
    import telegram_alert as ta

    calls = []
    monkeypatch.setitem(sys.modules, "report_capture", types.SimpleNamespace(capture=lambda *a, **k: None))
    monkeypatch.setattr(ta, "_token", lambda: "t")
    monkeypatch.setattr(ta, "_smart_split", lambda m, n: ["part one", "part two"])
    monkeypatch.setattr(ta, "send_message", lambda **kw: calls.append(kw) or {"ok": True, "message_id": len(calls)})
    lpo = {"is_disabled": True}
    res = ta._raw_send_telegram_result("body", chat_ids=["1"], link_preview_options=lpo)
    assert res["ok"] and [c["link_preview_options"] for c in calls] == [lpo, None]


def test_gateway_provider_forwards_the_preview(monkeypatch):
    from scripts.lib.comms import channel_adapters as ca
    import scripts.telegram_alert as sta

    seen = {}
    monkeypatch.setattr(sta, "_raw_send_telegram_result",
                        lambda body, **kw: seen.update(kw) or {"ok": True, "message_ids": ["9"]})
    lpo = {"url": "https://charts2-node.finviz.com/chart.ashx?t=AOUT"}
    out = ca._provider_send_telegram(body="x", kwargs={"chat_ids": ["1"], "link_preview_options": lpo},
                                     mode="ACTIVE")
    assert out["ok"] and seen["link_preview_options"] == lpo


# ── GO alerts ────────────────────────────────────────────────────────────────

GOOD = {"symbol": "ARMP", "run_label": "0900", "scanned_at": "2026-09-14T14:08:00", "score": 51, "grade": "A+",
        "decision": "GO", "rvol": 19.4, "price": 6.14, "change_pct": 15.8, "gap_pct": 15.8, "float_m": 11.6,
        "volume": 2_254_990, "catalyst": "FDA Breakthrough Therapy & label", "catalyst_verified": True,
        "disqualified": False, "source": "screener"}


def _go_item():
    import screener_go_alerts as g
    from lib.scalp_go_criteria import FALLBACK

    return g, g.pick_alerts([GOOD], sent=set(), session="2026-09-14", criteria=FALLBACK)["alert"][0]


def test_go_alert_sends_the_rich_layout_with_buttons_and_chart(monkeypatch):
    monkeypatch.delenv("TELEGRAM_RICH_ALERTS", raising=False)
    g, item = _go_item()
    calls = []
    assert g._send_go(lambda text, **kw: calls.append((text, kw)) or True, item)
    text, kw = calls[0]
    assert kw["bypass_router"] is True
    assert "<b>" in text and "/v3/watch/intelligence/ARMP" in text and "&amp; label" in text
    assert CHART in kw["link_preview_options"]["url"]
    assert kw["reply_markup"]["inline_keyboard"][0][0]["url"].endswith("/v3/watch/intelligence/ARMP")
    assert "READ_ONLY_ADVISORY" in text


def test_go_alert_falls_back_to_plain_text_when_rich_is_off(monkeypatch):
    monkeypatch.setenv("TELEGRAM_RICH_ALERTS", "0")
    g, item = _go_item()
    calls = []
    g._send_go(lambda text, **kw: calls.append((text, kw)) or True, item)
    assert calls[0][0] == g.format_alert(item) and "reply_markup" not in calls[0][1]


# ── entry alerts ─────────────────────────────────────────────────────────────

def test_entry_alert_is_rich_and_keeps_the_entry_alert_words(monkeypatch):
    monkeypatch.delenv("TELEGRAM_RICH_ALERTS", raising=False)
    import watchlist_entry_planner as wep

    calls = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda text, **kw: calls.append((text, kw)) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    plan = {"setup_type": "pullback", "entry_zone_low": 11.8, "entry_zone_high": 12.4, "limit_price": 12.0,
            "stop_price": 10.9, "target_price": 15.5, "risk_reward": 3.2, "entry_thesis": "Holding the 20-day",
            "invalidation": "Close under 10.90", "proposal": {"tag": "NEEDS_CONFIRMATION"},
            "exit_ladder": {"steps": [{"label": "T1", "px": 13.5, "action": "take a third"}]}}
    assert wep._alert("AXTI", plan, "ready", 12.1)
    text, kw = calls[0]
    assert "ENTRY ALERT" in text and "/v3/watch/intelligence/AXTI" in text
    assert "Close under 10.90" in text and "T1 $13.5" in text and "nothing executed" in text
    assert CHART in kw["link_preview_options"]["url"] and kw["reply_markup"]


# ── material change ──────────────────────────────────────────────────────────

ROW = {"change_guid": "g-1", "symbol": "AOUT", "kind": "price_excursion", "magnitude": 15, "observed_value": 45,
       "universe_reason": "held", "evidence_json": {}, "precedence": 1}


def test_material_change_rich_says_the_same_things_with_links():
    import notify_material_change as mc

    ctx = {"g-1": {"narrative": ["Shares jumped 14.6% after Q2 sales beat <estimates> & guidance."],
                   "questions": ["What drove the margin move?"]}}
    plain = mc.render([ROW], ctx)
    rich = mc.render_rich([ROW], ctx)
    text = rich["text"]
    for phrase in ("15x its normal daily range", "you hold this", "open question: What drove the margin move?"):
        assert phrase in plain and phrase in text
    assert "&lt;estimates&gt; &amp; guidance" in text
    assert '<a href="' in text and "/v3/watch/intelligence/AOUT" in text
    assert CHART in rich["link_preview_options"]["url"]
    for banned in ("buy", "sell", "trim", "add to"):
        assert banned not in text.lower()


def test_material_change_notice_sends_rich_through_the_gateway(monkeypatch):
    import notify_material_change as mc
    from scripts.lib.comms import channel_adapters as ca

    seen = {}
    monkeypatch.setenv(mc.GATEWAY_NOTICE_FLAG, "1")
    monkeypatch.setattr(ca, "send_via_gateway", lambda ch, **kw: seen.update(kw) or {"delivered": True})
    rich = mc.render_rich([ROW], {})
    accepted, _ = mc.deliver_notice("plain", subject_key="s", rich=rich)
    assert accepted and seen["body"] == rich["text"]
    assert seen["reply_markup"] == rich["reply_markup"] and seen["link_preview_options"]
    assert seen["message_class"] == "ops"
