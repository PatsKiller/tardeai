"""CIO operator product — unit + contract tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_action_links import (
    mint_action_token,
    reject_lan_url,
    verify_action_token,
    build_signed_action_url,
)
from scripts.lib.cio_alex_telegram import decision_dedupe_key, format_cio_message
from scripts.lib.cio_delivery_mode import classify_delivery_mode
from scripts.lib.cio_go_handler import handle_cio_go
from scripts.lib.cio_holdings_delta import diff_holdings
from scripts.lib.cio_nightly_reflection import reflect
from scripts.lib.cio_operator_acceptance import run_acceptance
from scripts.lib.cio_production_case import open_case_from_decision, score_case_darwin
from scripts.lib.cio_symbol_research import retrieve_symbol_research
from scripts.lib.cio_telegram_keyboard import build_decision_inline_keyboard
from scripts.notification_url_builder import get_public_base_url


def test_interdict_vs_cio_only_live():
    assert classify_delivery_mode({"CIO_TELEGRAM_INTERDICT": "1"})["CIO_DELIVERY_MODE"] == "INTERDICTED"
    rec = classify_delivery_mode({
        "CIO_TELEGRAM_INTERDICT": "0",
        "ENABLE_TELEGRAM": "1",
        "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY": "1",
        "TELEGRAM_CIO_BOT_TOKEN": "t",
        "TELEGRAM_CIO_CHAT_IDS": "1",
    })
    assert rec["CIO_DELIVERY_MODE"] == "CIO_ONLY_LIVE"


def test_inline_keyboard_and_tailscale():
    kb = build_decision_inline_keyboard(
        {"decision_id": "dec_t", "symbol": "SCHD", "decision_input_digest": "i", "decision_evidence_digest": "e"},
        key=b"unit-key",
    )
    urls = [c["url"] for r in kb["inline_keyboard"] for c in r]
    assert all(u.startswith("https://") for u in urls)
    assert all(not reject_lan_url(u) for u in urls)
    assert any("/v3/go/cio/decision/dec_t/action/ack" in u for u in urls)


def test_signed_token_expiry_and_mismatch():
    tok = mint_action_token(decision_id="dec_z", action="ack", key=b"k", now=1_000_000, ttl_sec=10)
    assert verify_action_token(tok, key=b"k", now=1_000_005)["ok"] is True
    assert verify_action_token(tok, key=b"k", now=1_000_020)["ok"] is False
    assert verify_action_token(tok, expected_action="defer", key=b"k", now=1_000_005)["ok"] is False


def test_digest_change_new_dedupe_key():
    d = {"decision_id": "dec_1", "action": "TRIM", "decision_input_digest": "a",
         "decision_evidence_digest": "b", "recommended_delta_usd": -10}
    assert decision_dedupe_key(d) != decision_dedupe_key(dict(d, decision_evidence_digest="c"))


def test_lan_url_rejected():
    assert reject_lan_url("http://127.0.0.1:7777/v3/cio")
    assert reject_lan_url("https://ms01-openclaw.tail163d14.ts.net:7777/x")
    assert not reject_lan_url("https://ms01-openclaw.tail163d14.ts.net/v3/cio")


def test_get_does_not_mutate(tmp_path, monkeypatch):
    tok = mint_action_token(decision_id="dec_n", action="ack", key=b"k")
    # handler uses default key file; inject via env
    monkeypatch.setenv("CIO_ACTION_LINK_KEY", "k")
    status, _, body = handle_cio_go(
        "GET", "/v3/go/cio/decision/dec_n/action/ack", {"t": [tok]}, None,
    )
    assert status == 200
    assert b"Unsigned GET did not change anything" in body


def test_new_position_vs_transfer():
    opened = diff_holdings([], [{"symbol": "NEW", "account": "ira", "market_value": 900, "shares": 2}])
    assert opened[0]["event"] == "POSITION_OPENED"
    xfer = diff_holdings(
        [{"symbol": "OLD", "account": "ira", "market_value": 100, "shares": 1}],
        [{"symbol": "OLD", "account": "roth", "market_value": 100, "shares": 1}],
    )
    assert xfer[0]["event"] == "ACCOUNT_TRANSFER_DETECTED"
    assert xfer[0]["purchase_claimed"] is False


def test_hold_cash_and_symbol_research(tmp_path):
    pkt = retrieve_symbol_research("SCHG")
    assert pkt["creates_trade_authority"] is False
    assert pkt["memory_consulted"] is True
    assert any("NAV" in i["fact"] or i["status"] == "UNAVAILABLE" for i in pkt["items"])
    assert not any(i.get("status") == "OOS_SUPPORTED" and "r8" in i["source"] for i in pkt["items"])


def test_case_darwin_and_reflection(tmp_path):
    from scripts.lib import cio_production_case as cs
    cs.DEFAULT_PATH = tmp_path / "cases.jsonl"
    rec = open_case_from_decision({"decision_id": "dec_c", "symbol": "V", "why_now": "test hold signal"})
    assert rec["case_id"]
    sc = score_case_darwin({"auto_promoted": True})
    assert sc["score"] == 0
    out = reflect(cases_path=cs.DEFAULT_PATH, out_path=tmp_path / "ref.json")
    assert out["auto_promotions"] == 0
    assert out["mutates_production"] is False


def test_plaintext_actions_removed():
    body = format_cio_message({"decision_id": "dec_p", "symbol": "SCHD", "action": "Trim",
                               "why_now": "concentration above fire line for SCHD"})
    assert "Alex · CIO NOW" in body
    assert "ACK · DEFER" not in body


def test_cop_acceptance_profile():
    rep = run_acceptance()
    assert rep["overall"] == "PASS", json.dumps(rep, indent=2)
    assert not rep["failed"]
