"""Phase R2 — DecisionPayload@v1 on remaining operator-visible producers.

Flag AGENT_DECISION_PAYLOAD default 0. OFF = no file write (parity).
ON = valid DecisionPayload@v1 on reentry / watch / advisory / telegram.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.agent_decision_payload import (  # noqa: E402
    PAYLOAD_SCHEMA,
    VALID_ORIGINS,
    VALID_SURFACES,
    build_decision_payload,
    count_decision_payloads,
    emit_advisory_opinion_payload,
    emit_decision_payload,
    emit_holdings_health_payload,
    emit_opportunity_promote_payload,
    emit_reentry_operator_payloads,
    emit_telegram_decision_payload,
    emit_watch_alert_payload,
    payload_from_advisory_opinion,
    payload_from_holdings_health,
    payload_from_reentry_row,
    payload_from_watch_alert,
    ticker_or_unavailable,
)
from scripts.lib.agent_feature_flags import DEFAULT_FLAGS, load_feature_flags  # noqa: E402


def _flags(**kw):
    base = load_feature_flags({})
    base.update(kw)
    return base


def _on():
    return _flags(AGENT_DECISION_PAYLOAD=1)


def _off():
    return _flags(AGENT_DECISION_PAYLOAD=0)


def _ready_row(symbol="UBER", state="READY TO REVIEW"):
    return {
        "symbol": symbol,
        "intel": {"state": state, "action": "Review re-entry now"},
        "advisory": {"action": "Tactical Re-Entry / Buy Limit", "advisory_only": True},
        "gates": [
            {"id": "zone", "pass": True, "label": "Inside entry zone"},
            {"id": "rsi", "pass": True, "label": "RSI 40-70"},
        ],
        "plan_as_of": "2026-08-21",
    }


# ── ticker hygiene ──────────────────────────────────────────────────────────


def test_ticker_or_unavailable_cash_and_membership():
    assert ticker_or_unavailable("CASH") == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable("cash") == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable("REENTRY") == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable("RE-ENTRY") == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable("WATCH") == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable("PORTFOLIO") == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable("BOOK") == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable("ALLOCATION") == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable(None) == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable("") == "DATA_UNAVAILABLE"
    assert ticker_or_unavailable("  ") == "DATA_UNAVAILABLE"


def test_ticker_or_unavailable_preserves_real_tickers():
    assert ticker_or_unavailable("UBER") == "UBER"
    assert ticker_or_unavailable("uber") == "UBER"
    assert ticker_or_unavailable("BRK.B") == "BRK.B"
    assert ticker_or_unavailable("BF-B") == "BF-B"
    assert ticker_or_unavailable("GOOGL") == "GOOGL"


def test_build_payload_never_emits_cash_ticker():
    pl = build_decision_payload(
        decision_id="dec_cash",
        wake_id="wake_x",
        symbol="CASH",
        surface="material_scan",
        current_action="HOLD_CASH",
    )
    assert pl["schema"] == PAYLOAD_SCHEMA
    assert pl["symbol"] == "DATA_UNAVAILABLE"
    assert pl.get("data_unavailable") is True
    assert pl["surface"] in VALID_SURFACES


def test_flag_default_still_off():
    assert DEFAULT_FLAGS.get("AGENT_DECISION_PAYLOAD") == 0
    assert load_feature_flags({})["AGENT_DECISION_PAYLOAD"] == 0


# ── flag OFF → no file write ────────────────────────────────────────────────


def test_flag_off_reentry_no_write(tmp_path):
    tp = tmp_path / "traces.jsonl"
    out = emit_reentry_operator_payloads(
        [_ready_row()],
        flags=_off(),
        path=tp,
    )
    assert out["emitted"] == 0
    assert out["enabled"] is False
    assert not tp.exists()


def test_flag_off_watch_no_write(tmp_path):
    tp = tmp_path / "traces.jsonl"
    out = emit_watch_alert_payload(
        {"id": 1, "symbol": "NVDA", "condition_type": "price_cross_above"},
        flags=_off(),
        path=tp,
    )
    assert out["emitted"] is False
    assert not tp.exists()


def test_flag_off_advisory_no_write(tmp_path):
    tp = tmp_path / "traces.jsonl"
    out = emit_advisory_opinion_payload(
        {"symbol": "SCHD", "verdict": "TRIM", "advisory_row_hash": "h1"},
        {"verdict": "TRIM", "conviction": 70, "cache_hit": False},
        flags=_off(),
        path=tp,
    )
    assert out["emitted"] is False
    assert not tp.exists()


def test_flag_off_telegram_no_write(tmp_path):
    tp = tmp_path / "traces.jsonl"
    out = emit_telegram_decision_payload(
        symbol="ANET",
        action="READY",
        surface="reentry",
        flags=_off(),
        path=tp,
    )
    assert out["emitted"] is False
    assert not tp.exists()


# ── flag ON → valid DecisionPayload@v1 ──────────────────────────────────────


def test_flag_on_reentry_valid_payload(tmp_path):
    tp = tmp_path / "traces.jsonl"
    out = emit_reentry_operator_payloads(
        [
            _ready_row("UBER", "READY TO REVIEW"),
            _ready_row("ANET", "NEAR ENTRY"),
            _ready_row("WAITX", "WAIT"),  # skipped — not READY/NEAR
            {"symbol": "CASH", "intel": {"state": "READY TO REVIEW", "action": "x"},
             "advisory": {"action": "nope"}},  # skipped — membership label
        ],
        flags=_on(),
        path=tp,
        wake_id="wake_reentry_test",
    )
    assert out["enabled"] is True
    assert out["attempted"] == 2
    assert out["emitted"] == 2
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    assert len(rows) == 2
    for row in rows:
        dec = row["decision"]
        assert dec["schema"] == PAYLOAD_SCHEMA
        assert dec["surface"] == "reentry"
        assert dec["surface"] in VALID_SURFACES
        assert dec["symbol"] in {"UBER", "ANET"}
        assert dec["symbol"] != "CASH"
        assert dec["authority"] == "READ_ONLY_ADVISORY"
        assert dec["financial_action"] is False
        assert dec["decision_origin"] in VALID_ORIGINS
        assert row["status"] == "completed"
        assert "chain_of_thought" not in json.dumps(row)
    actions = {r["decision"]["current_action"] for r in rows}
    assert "READY" in actions
    assert "NEAR" in actions


def test_reentry_skips_unchanged_reemission(tmp_path):
    tp = tmp_path / "traces.jsonl"
    fp = tmp_path / "fp.json"
    rows = [_ready_row("UBER", "READY TO REVIEW")]
    first = emit_reentry_operator_payloads(
        rows, flags=_on(), path=tp, fingerprint_path=fp, heartbeat_hours=4,
    )
    second = emit_reentry_operator_payloads(
        rows, flags=_on(), path=tp, fingerprint_path=fp, heartbeat_hours=4,
    )
    assert first["emitted"] == 1
    assert second["emitted"] == 0
    assert second["skipped_unchanged"] == 1


def test_holdings_and_opportunity_surfaces(tmp_path):
    tp = tmp_path / "traces.jsonl"
    assert "holdings" in VALID_SURFACES
    h = emit_holdings_health_payload(
        {"symbol": "SCHD", "action": "HOLD", "health": "STABLE", "confidence": 0.7},
        flags=_on(), path=tp,
    )
    assert h["emitted"] is True
    o = emit_opportunity_promote_payload(
        symbol="RKLB", status="PROMOTED", source="cio", flags=_on(), path=tp,
    )
    assert o["emitted"] is True
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    surfs = {r["decision"]["surface"] for r in rows}
    assert surfs == {"holdings", "opportunity"}


def test_flag_on_watch_valid_payload(tmp_path):
    tp = tmp_path / "traces.jsonl"
    out = emit_watch_alert_payload(
        {"id": 42, "symbol": "nvda", "condition_type": "price_cross_above", "threshold": 100},
        flags=_on(),
        path=tp,
        message="🔔 NVDA · price cross above 100",
        wake_id="wake_watch_test",
    )
    assert out["emitted"] is True
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    dec = rows[0]["decision"]
    assert dec["schema"] == PAYLOAD_SCHEMA
    assert dec["surface"] == "watch"
    assert dec["surface"] in VALID_SURFACES
    assert dec["symbol"] == "NVDA"
    assert dec["current_action"] == "PRICE_CROSS_ABOVE"


def test_flag_on_advisory_valid_payload(tmp_path):
    tp = tmp_path / "traces.jsonl"
    out = emit_advisory_opinion_payload(
        {"symbol": "SCHD", "verdict": "TRIM", "advisory_row_hash": "h_schd", "row_class": "holding"},
        {"verdict": "TRIM", "conviction": 72, "cache_hit": False, "evidence_cited": ["price_action"]},
        flags=_on(),
        path=tp,
        wake_id="wake_adv_test",
    )
    assert out["emitted"] is True
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    dec = rows[0]["decision"]
    assert dec["schema"] == PAYLOAD_SCHEMA
    assert dec["surface"] == "advisory"
    assert dec["symbol"] == "SCHD"
    assert dec["current_action"] == "TRIM"
    assert dec["confidence"] == 7.2  # 0-100 scaled to 0-10


def test_advisory_cache_hit_skipped(tmp_path):
    tp = tmp_path / "traces.jsonl"
    out = emit_advisory_opinion_payload(
        {"symbol": "SCHD", "verdict": "HOLD"},
        {"verdict": "HOLD", "conviction": 50, "cache_hit": True},
        flags=_on(),
        path=tp,
    )
    assert out["emitted"] is False
    assert out.get("error") == "cache_hit_skip"
    assert not tp.exists()


def test_synthesized_origin_allowed_but_marked(tmp_path):
    tp = tmp_path / "traces.jsonl"
    pl = build_decision_payload(
        decision_id="dec_syn",
        wake_id="wake_syn",
        symbol="UBER",
        surface="advisory",
        current_action="HOLD",
        decision_origin="SYNTHESIZED",
    )
    assert pl["decision_origin"] == "SYNTHESIZED"
    assert pl["decision_origin"] in VALID_ORIGINS
    res = emit_decision_payload(pl, flags=_on(), path=tp)
    assert res["emitted"] is True
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    assert rows[0]["decision"]["decision_origin"] == "SYNTHESIZED"
    assert rows[0]["learning"]["synthesized"] is True
    assert rows[0]["learning"]["auto_promoted"] is False
    cov = count_decision_payloads(tp)
    assert cov["with_decision_payload_v1"] == 1
    assert cov["synthesized"] == 1
    assert cov["with_decision_payload_v1_non_synth"] == 0


def test_payload_mappers_surfaces():
    re_pl = payload_from_reentry_row(_ready_row(), wake_id="w1")
    assert re_pl["surface"] == "reentry"
    assert re_pl["symbol"] == "UBER"
    assert re_pl["current_action"] == "READY"
    w_pl = payload_from_watch_alert(
        {"id": 1, "symbol": "AMD", "condition_type": "rsi_below"},
        wake_id="w2",
    )
    assert w_pl["surface"] == "watch"
    assert w_pl["symbol"] == "AMD"
    a_pl = payload_from_advisory_opinion(
        {"symbol": "CASH", "verdict": "ADD", "row_class": "allocation"},
        {"verdict": "ADD", "conviction": 40},
        wake_id="w3",
    )
    assert a_pl["surface"] == "advisory"
    assert a_pl["symbol"] == "DATA_UNAVAILABLE"
    assert a_pl.get("data_unavailable") is True


# ── monkeypatch producers with tmp_path traces ──────────────────────────────


def test_reentry_producer_hook_monkeypatch(tmp_path, monkeypatch):
    from scripts.lib.data_broker import reentry_decision_desk as rdd

    tp = tmp_path / "traces.jsonl"
    captured: list = []

    def hooked(rows):
        captured.append(rows)
        return emit_reentry_operator_payloads(rows, flags=_on(), path=tp, wake_id="wake_hook")

    monkeypatch.setattr(rdd, "_emit_ready_near_payloads", hooked)
    rdd._emit_ready_near_payloads([_ready_row("CSCO")])
    assert captured and captured[0][0]["symbol"] == "CSCO"
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    assert rows[0]["decision"]["schema"] == PAYLOAD_SCHEMA
    assert rows[0]["decision"]["surface"] == "reentry"
    assert rows[0]["decision"]["symbol"] == "CSCO"
    src = (ROOT / "scripts/lib/data_broker/reentry_decision_desk.py").read_text(encoding="utf-8")
    assert "_emit_ready_near_payloads" in src
    assert "emit_reentry_operator_payloads" in src


def test_watch_producer_eval_monkeypatch(tmp_path, monkeypatch):
    import watch_alerts_eval as wae

    tp = tmp_path / "traces.jsonl"
    fired: list = []

    def hooked(alert, message=None):
        fired.append(alert)
        return emit_watch_alert_payload(
            alert, message=message, flags=_on(), path=tp, wake_id="wake_w",
        )

    monkeypatch.setattr(wae, "_emit_watch_alert_payload", hooked)

    def ex(sql, params=None, fetch="one"):
        s = (sql or "").lower()
        if "alert_events" in s and "select 1" in s:
            return None
        if "market_quotes" in s:
            return {"price": 150.0}
        return None

    alerts = [{
        "id": 7,
        "symbol": "NVDA",
        "condition_type": "price_cross_above",
        "threshold": 100.0,
        "recurring": True,
        "last_fired_at": None,
    }]
    lines, ids = wae._evaluate_single_condition_alerts(ex, alerts, "2026-08-21")
    assert ids == [7]
    assert fired and fired[0]["symbol"] == "NVDA"
    assert tp.exists()
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    assert rows[0]["decision"]["surface"] == "watch"
    assert rows[0]["decision"]["symbol"] == "NVDA"
    assert rows[0]["decision"]["schema"] == PAYLOAD_SCHEMA


def test_watch_producer_flag_off_eval_no_write(tmp_path, monkeypatch):
    import watch_alerts_eval as wae

    tp = tmp_path / "traces.jsonl"

    def hooked(alert, message=None):
        return emit_watch_alert_payload(alert, message=message, flags=_off(), path=tp)

    monkeypatch.setattr(wae, "_emit_watch_alert_payload", hooked)

    def ex(sql, params=None, fetch="one"):
        s = (sql or "").lower()
        if "select 1" in s:
            return None
        if "market_quotes" in s:
            return {"price": 12.0}
        return None

    alerts = [{
        "id": 9,
        "symbol": "AMD",
        "condition_type": "price_cross_below",
        "threshold": 20.0,
        "recurring": True,
        "last_fired_at": None,
    }]
    wae._evaluate_single_condition_alerts(ex, alerts, "2026-08-21")
    assert not tp.exists()


def test_advisory_producer_hook_monkeypatch(tmp_path, monkeypatch):
    from lib.advisory import advisory_opinion_engine as aoe

    tp = tmp_path / "traces.jsonl"

    def hooked(row, opinion):
        return emit_advisory_opinion_payload(row, opinion, flags=_on(), path=tp, wake_id="wake_ao")

    monkeypatch.setattr(aoe, "_emit_advisory_decision_payload", hooked)
    row = {"symbol": "FATN", "verdict": "WAIT", "advisory_row_hash": "h_fatn"}
    opinion = {"verdict": "WAIT", "conviction": 55, "cache_hit": False}
    aoe._emit_advisory_decision_payload(row, opinion)
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    assert rows[0]["decision"]["surface"] == "advisory"
    assert rows[0]["decision"]["symbol"] == "FATN"
    src = (ROOT / "scripts/lib/advisory/advisory_opinion_engine.py").read_text(encoding="utf-8")
    assert "_emit_advisory_decision_payload" in src


def test_telegram_reentry_reply_hook_monkeypatch(tmp_path, monkeypatch):
    from scripts.lib import cio_telegram_converse as tg

    tp = tmp_path / "traces.jsonl"

    def hooked(ready, near):
        return emit_telegram_decision_payload(
            symbol=ready[0] if ready else None,
            action="READY" if ready else "NEAR",
            surface="reentry",
            origin="OPERATOR_ASK",
            flags=_on(),
            path=tp,
            wake_id="wake_tg",
        )

    monkeypatch.setattr(tg, "_emit_reentry_reply_payload", hooked)
    tg._emit_reentry_reply_payload(["IRDM"], ["AXTI"])
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    dec = rows[0]["decision"]
    assert dec["schema"] == PAYLOAD_SCHEMA
    assert dec["surface"] == "reentry"
    assert dec["symbol"] == "IRDM"
    assert dec["decision_origin"] == "OPERATOR_ASK"
    src = (ROOT / "scripts/lib/cio_telegram_converse.py").read_text(encoding="utf-8")
    assert "_emit_reentry_reply_payload" in src
    desk_src = (ROOT / "scripts/lib/cio_operator_desk_loop.py").read_text(encoding="utf-8")
    assert "_emit_telegram_desk_payload" in desk_src


def test_telegram_desk_reentry_intent_monkeypatch(tmp_path, monkeypatch):
    from scripts.lib import cio_operator_desk_loop as desk

    tp = tmp_path / "traces.jsonl"
    seen: list = []

    def hooked(intent, result):
        seen.append((intent, result))
        if result.get("kind") != "answered":
            return
        if str((intent or {}).get("intent") or "") != "reentry":
            return
        emit_telegram_decision_payload(
            symbol=(intent.get("symbols") or [None])[0],
            action="ADVISORY_REPLY",
            surface="reentry",
            origin="OPERATOR_ASK",
            flags=_on(),
            path=tp,
        )

    monkeypatch.setattr(desk, "_emit_telegram_desk_payload", hooked)
    desk._emit_telegram_desk_payload(
        {"intent": "reentry", "symbols": ["ADBE"]},
        {"kind": "answered", "reply_source": "tradeai_deterministic"},
    )
    desk._emit_telegram_desk_payload(
        {"intent": "meta_system", "symbols": []},
        {"kind": "answered"},
    )
    assert len(seen) == 2
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["decision"]["symbol"] == "ADBE"
    assert rows[0]["decision"]["decision_origin"] == "OPERATOR_ASK"
