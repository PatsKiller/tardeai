"""Active Trader Phase 1 alerts (operator-approved 2026-10-04): deterministic ARMED/TRIGGERED
decisions, fail-closed staleness, throttle, journal, scoring, replay on recorded data, and the
safety assertion that none of the new code can reach an order, a trade context or 2FA.

Temp paths and injected fetchers only: no OpenD, no database, no Telegram.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import momentum_alerts as ma  # noqa: E402
from active_trader import momentum_alert_pass as mp  # noqa: E402
from active_trader import momentum_alert_scoring as ms  # noqa: E402
from active_trader.momentum_alert_sources import exchange_time_to_epoch  # noqa: E402

NOW = 1_790_000_000.0
CFG = ma.AlertConfig()


@pytest.fixture(autouse=True)
def _journal_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    return tmp_path / "at"


def book(bid=(5.00, 5000), ask=(5.01, 2000), age=2.0, levels=10, at=NOW):
    return {"bids": [(bid[0] - i * 0.01, bid[1]) for i in range(levels)],
            "asks": [(ask[0] + i * 0.01, ask[1]) for i in range(levels)],
            "ts_epoch": at - age, "ts_source": "opend_server"}


def tape(n=30, buy_share=0.8, age=3.0, at=NOW):
    rows = []
    for i in range(n):
        rows.append({"ts_epoch": at - age - (n - i), "price": 5.0, "volume": 100,
                     "direction": "BUY" if i < n * buy_share else "SELL"})
    return rows


def cand(**kw):
    base = dict(symbol="ABCD", lane="BELOW", ign=40.0, fsm_state="IDLE", entry_ref=5.01, stop_ref=4.90,
                rvol=8.0, float_mm=6.0, last=5.01, quote_ts_epoch=NOW - 2, fire_ts_epoch=NOW - 30,
                session_date="2026-10-05")
    base.update(kw)
    return ma.Candidate(**base)


# ── evidence ──────────────────────────────────────────────────────────────────

def test_l2_evidence_measures_depth_and_spread():
    ev = ma.l2_evidence(book(), now=NOW, cfg=CFG, source="moomoo")
    assert ev["ok"] and ev["levels"] == 10
    assert ev["depth_ratio"] == 2.5 and ev["spread_bps"] == pytest.approx(20.0, abs=0.1)


@pytest.mark.parametrize("b,reason", [
    (None, "BOOK_MISSING"),
    (book(age=60), "BOOK_STALE"),
    ({"bids": [], "asks": [], "ts_epoch": NOW}, "BOOK_EMPTY"),
    (book(ask=(5.10, 2000)), "SPREAD_WIDE"),
])
def test_l2_evidence_fails_closed(b, reason):
    ev = ma.l2_evidence(b, now=NOW, cfg=CFG, source="moomoo")
    assert not ev["ok"] and reason in ev["reasons"]


def test_tape_evidence_buy_ratio_and_staleness():
    assert ma.tape_evidence(tape(), now=NOW, cfg=CFG, source="moomoo")["buy_ratio"] == 0.8
    assert "TAPE_STALE" in ma.tape_evidence(tape(age=120), now=NOW, cfg=CFG, source="m")["reasons"]
    assert "TAPE_THIN" in ma.tape_evidence(tape(n=5), now=NOW, cfg=CFG, source="m")["reasons"]
    assert "TAPE_MISSING" in ma.tape_evidence([], now=NOW, cfg=CFG, source="m")["reasons"]


# ── decisions ─────────────────────────────────────────────────────────────────

def test_alert_kind():
    assert ma.alert_kind(cand(), now=NOW, cfg=CFG) == ma.TRIGGERED
    assert ma.alert_kind(cand(fire_ts_epoch=NOW - 3600, fsm_state="ARMED"), now=NOW, cfg=CFG) == ma.ARMED
    assert ma.alert_kind(cand(fire_ts_epoch=None, lane="IGN_75"), now=NOW, cfg=CFG) == ma.ARMED
    assert ma.alert_kind(cand(fire_ts_epoch=None), now=NOW, cfg=CFG) is None


def _decide(c, b=None, t=None, kind=ma.TRIGGERED):
    l2 = ma.l2_evidence(b if b is not None else book(), now=NOW, cfg=CFG, source="moomoo")
    tp = ma.tape_evidence(t if t is not None else tape(), now=NOW, cfg=CFG, source="moomoo")
    return ma.decide(c, kind, l2, tp, now=NOW, cfg=CFG)


def test_triggered_alerts_only_with_all_confirmations():
    assert _decide(cand())["verdict"] == ma.ALERT


@pytest.mark.parametrize("kw,b,t,reason", [
    ({"quote_ts_epoch": NOW - 120}, None, None, "QUOTE_STALE"),
    ({"quote_ts_epoch": None}, None, None, "QUOTE_STALE"),
    ({}, book(bid=(5.00, 1000), ask=(5.01, 2000)), None, "L2_ASK_HEAVY"),
    ({}, None, tape(buy_share=0.3), "TAPE_SELLERS"),
    ({}, None, [], "TAPE_MISSING"),
    ({"stop_ref": None}, None, None, "NO_STOP_REF"),
    ({"stop_ref": 5.20}, None, None, "NO_STOP_REF"),
])
def test_triggered_vetoes_with_reason(kw, b, t, reason):
    d = _decide(cand(**kw), b, t)
    assert d["verdict"] == ma.VETO and reason in d["veto_reasons"]


def test_armed_needs_book_but_not_tape():
    c = cand(fire_ts_epoch=None, fsm_state="ARMED")
    assert _decide(c, t=[], kind=ma.ARMED)["verdict"] == ma.ALERT
    assert _decide(c, b=book(age=60), kind=ma.ARMED)["verdict"] == ma.VETO


# ── pass: journal, throttle, send gating ─────────────────────────────────────

def _pass(cands, cfg=CFG, sent=None, now=NOW, persist=True):
    calls = sent if sent is not None else []
    return ma.evaluate_pass(cands, cfg=cfg, now=now,
                            fetch_primary_book=lambda s: book(at=now), fetch_primary_tape=lambda s: tape(at=now),
                            fetch_compare_book=lambda s: None,
                            send_fn=lambda **kw: calls.append(kw) or {"sent": True}, persist=persist)


def test_shadow_mode_journals_and_never_sends(_journal_dir):
    calls = []
    rows = _pass([cand()], sent=calls)
    assert rows[0]["verdict"] == ma.ALERT and rows[0]["sent"] is False and calls == []
    lines = (_journal_dir / "momentum_alerts.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["contract"] == ma.CONTRACT
    assert "ADVISORY ONLY — NOT AN ORDER" in rows[0]["message"]["body"]


def test_send_mode_uses_own_alert_types_and_no_daily_dedupe():
    calls = []
    rows = _pass([cand()], cfg=ma.AlertConfig(mode="send"), sent=calls)
    assert rows[0]["sent"] is True
    assert calls[0]["alert_type"] == "at_scalp_triggered" and calls[0]["dedupe_scope"] == "none"
    assert calls[0]["tier"] == "ALERT"


def test_vetoes_are_journaled_not_sent(_journal_dir):
    calls = []
    _pass([cand(quote_ts_epoch=None)], cfg=ma.AlertConfig(mode="send"), sent=calls)
    row = json.loads((_journal_dir / "momentum_alerts.jsonl").read_text().splitlines()[0])
    assert row["verdict"] == ma.VETO and "QUOTE_STALE" in row["veto_reasons"] and calls == []


def test_cooldown_and_rate_limit():
    _pass([cand()])
    again = _pass([cand(quote_ts_epoch=NOW + 58, fire_ts_epoch=NOW + 30)], now=NOW + 60)
    assert again[0]["veto_reasons"] == ["COOLDOWN"]
    later = NOW + 7200
    cfg = ma.AlertConfig(max_alerts_per_hour=2, cooldown_s=0)
    fresh = [cand(symbol=s, quote_ts_epoch=later - 2, fire_ts_epoch=later - 30) for s in ("A1", "A2", "A3")]
    out = [r["verdict"] for r in _pass(fresh, cfg=cfg, now=later)]
    assert out == [ma.ALERT, ma.ALERT, ma.VETO]


def test_dry_run_persists_nothing(_journal_dir):
    _pass([cand()], persist=False)
    assert not (_journal_dir / "momentum_alerts.jsonl").exists()
    assert not (_journal_dir / "momentum_alerts_throttle.json").exists()


def test_config_rejects_unknown_mode():
    with pytest.raises(ValueError):
        ma.AlertConfig.from_mapping({"mode": "live"})
    assert ma.AlertConfig.from_mapping(None).mode == "shadow"


# ── bridge from the logger ────────────────────────────────────────────────────

class _Src:
    def quote(self, s): return 5.01, NOW - 2
    def book(self, s): return book()
    def tape(self, s): return tape()
    def close(self): pass


def test_bridge_builds_candidates_from_logger_pass():
    from datetime import datetime, timezone
    results = [{"symbol": "ABCD", "lane": "BELOW", "ign": 40.0, "rvol_tod": 9.0, "entry_ref": 5.0,
                "stop_ref": 4.9, "_tax": {"primary_setup_id": "s1", "primary_setup_label": "Bull flag"}},
               {"symbol": "QUIET", "lane": "BELOW", "ign": 10.0}]
    fires = [{"symbol": "ABCD", "fire_minute": 61, "entry": 5.01, "stop": 4.90,
              "fire_ts": datetime.fromtimestamp(NOW - 20, timezone.utc).isoformat()}]
    res = mp.run_from_logger(None, {}, results, fires, {"ABCD": "FIRED", "QUIET": "IDLE"},
                             day="2026-10-05", now=NOW, source=_Src())
    assert res == {"evaluated": 1, "mode": "shadow", "alerts": 1, "sent": 0, "vetoes": 0}


# ── scoring ───────────────────────────────────────────────────────────────────

def _bars(start, closes):
    from datetime import datetime, timezone
    return [{"t": datetime.fromtimestamp(start + 60 * i, timezone.utc).isoformat(),
             "h": c + 0.05, "l": c - 0.05, "c": c} for i, c in enumerate(closes)]


def test_score_row_windows():
    row = {"run_id": "r", "kind": ma.TRIGGERED, "verdict": ma.ALERT, "ts_epoch": NOW, "r_dollars": 0.11,
           "candidate": {"symbol": "ABCD", "entry_ref": 5.01, "session_date": "2026-10-05"}}
    bars = _bars(NOW - 120, [4.9, 4.95] + [5.0 + 0.02 * i for i in range(16)])
    s = ms.score_row(row, bars)
    assert s["status"] == "SCORED"
    assert s["windows"]["1m"]["bars"] == 1 and s["windows"]["15m"]["bars"] == 15
    assert s["windows"]["5m"]["mfe"] == pytest.approx(5.0 + 0.08 + 0.05 - 5.01)
    assert s["windows"]["5m"]["mfe_r"] == pytest.approx(round((5.13 - 5.01) / 0.11, 2))


def test_score_pending_waits_for_window_and_is_idempotent(_journal_dir):
    _pass([cand()])
    bars_fn = lambda s, d: _bars(NOW, [5.0 + 0.01 * i for i in range(20)])  # noqa: E731
    assert ms.score_pending(bars_fn, now=NOW + 60) == []
    first = ms.score_pending(bars_fn, now=NOW + 20 * 60)
    assert len(first) == 1 and first[0]["status"] == "SCORED"
    assert ms.score_pending(bars_fn, now=NOW + 30 * 60) == []
    summary = ms.precision_summary(first, window="15m", hit_r=1.0)
    assert summary["TRIGGERED:ALERT"]["n"] == 1


# ── replay on recorded data (2026-09-04..17, real TRIGGER fires + live moomoo books) ──

FIXTURE = ROOT / "tests" / "fixtures" / "active_trader" / "momentum_alert_replay_20260904_17.json"


def _replay_rows():
    return json.loads(FIXTURE.read_text())["rows"]


def _recorded_book(r):
    if r.get("bid_depth") is None:
        return None
    mid, sp = r["microprice"], r["spread_bps"] or 0.0
    half = mid * sp / 2e4
    return {"bids": [(mid - half, r["bid_depth"])], "asks": [(mid + half, r["ask_depth"])],
            "ts_epoch": r["book_epoch"], "ts_source": "recorded"}


def _replay(tape_fn):
    out = []
    for r in _replay_rows():
        c = ma.Candidate(symbol=r["symbol"], lane="TRIGGER", ign=r["ign"] or 0.0, fsm_state="FIRED",
                         setup_id=r["setup_id"], entry_ref=r["entry_ref"], stop_ref=r["stop_ref"],
                         rvol=r["rvol"], last=r["entry_ref"], quote_ts_epoch=r["fired_epoch"],
                         fire_ts_epoch=r["fired_epoch"], session_date=r["session_date"])
        now = r["fired_epoch"] + 5
        l2 = ma.l2_evidence(_recorded_book(r), now=now, cfg=CFG, source="moomoo")
        tp = ma.tape_evidence(tape_fn(r, now), now=now, cfg=CFG, source="moomoo")
        out.append((r, ma.decide(c, ma.TRIGGERED, l2, tp, now=now, cfg=CFG)))
    return out


def test_replay_fixture_is_real_recorded_data():
    rows = _replay_rows()
    assert len(rows) == 30 and len({r["symbol"] for r in rows}) == 16
    assert sum(1 for r in rows if r["bid_depth"] is not None) == 4
    assert all(r["lane"] == "TRIGGER" for r in rows)


def test_replay_without_tape_never_alerts():
    """Tape was not recorded before 2026-10-04, so every recorded fire must fail closed."""
    decisions = _replay(lambda r, now: [])
    assert all(d["verdict"] == ma.VETO for _, d in decisions)
    no_book = [d for r, d in decisions if r["bid_depth"] is None]
    assert len(no_book) == 26 and all("BOOK_MISSING" in d["veto_reasons"] for d in no_book)


def test_replay_with_buying_tape_is_decided_by_the_recorded_book():
    def buying(r, now):
        return [{"ts_epoch": now - 1 - i, "price": r["entry_ref"], "volume": 100, "direction": "BUY"}
                for i in range(30)][::-1]
    for r, d in _replay(buying):
        if r["bid_depth"] is None:
            assert "BOOK_MISSING" in d["veto_reasons"]
            continue
        ratio = r["bid_depth"] / r["ask_depth"] if r["ask_depth"] else None
        book_age = (r["fired_epoch"] + 5) - r["book_epoch"]
        if ratio is not None and ratio >= CFG.min_depth_ratio_triggered and (r["spread_bps"] or 0) <= CFG.max_spread_bps \
                and 0 <= book_age <= CFG.max_book_age_s \
                and r["stop_ref"] is not None and r["entry_ref"] > r["stop_ref"]:
            assert d["verdict"] == ma.ALERT, (r["symbol"], d)
        else:
            assert d["verdict"] == ma.VETO, (r["symbol"], d)


# ── safety: no order / trade context / 2FA anywhere in the new code ───────────

NEW_MODULES = ["momentum_alerts.py", "momentum_alert_pass.py", "momentum_alert_sources.py",
               "momentum_alert_scoring.py"]
FORBIDDEN = {"place_order", "modify_order", "cancel_order", "unlock_trade", "submit_order",
             "OpenSecTradeContext", "OpenUSTradeContext", "OpenTradeContextBase", "TrdEnv",
             "MoomooTradeReader", "execution_guard", "request_2fa", "verify_2fa", "TradingSessionGrant"}


@pytest.mark.parametrize("name", NEW_MODULES)
def test_new_modules_have_no_order_or_2fa_path(name):
    tree = ast.parse((ROOT / "scripts" / "active_trader" / name).read_text())
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
           {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
           {a.name.split(".")[-1] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in n.names} | \
           {(n.module or "").split(".")[-1] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not (used & FORBIDDEN), used & FORBIDDEN


def test_authority_block_is_read_only():
    assert ma.AUTHORITY == {"read_only": True, "order": False, "broker_write": False,
                            "two_factor": False, "financial_action": False}


def test_new_moomoo_reads_use_the_quote_context_only():
    src = (ROOT / "scripts" / "moomoo" / "client.py").read_text()
    seg = src[src.index("def get_ticker"):src.index("class MoomooTradeReader")]
    assert "_context()" in seg and "TradeContext" not in seg and "unlock" not in seg


def test_exchange_time_parsing():
    assert exchange_time_to_epoch("") is None and exchange_time_to_epoch("nan") is None
    assert exchange_time_to_epoch("2026-10-02 16:00:00") == pytest.approx(1790971200.0)   # 16:00 ET = 20:00 UTC
    assert exchange_time_to_epoch("2026-10-02 16:00:00.614") == pytest.approx(1790971200.614)
