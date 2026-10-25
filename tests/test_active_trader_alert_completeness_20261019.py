"""Telegram alerts that shipped with blank / UNKNOWN fields (operator 2026-10-19).

Fixtures are modelled on the real messages: FOXA / GRMN swing entry alerts (2026-10-15), BETR fast-loop
APPROACHING (2026-10-19 10:38, a same-day WAIT scan at 09:01 yet "NO_SAME_DAY_SCAN"), NCPL STAND DOWN
(2026-10-16 10:15, "last n/a · entry n/a" + "L2 moomoo 0 lv: bid/ask n/a").

Hermetic: every database is a fake cursor, every sender a capture list, the journal a tmp dir. No
network, no Telegram, no broker.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import entry_alert_context as eac  # noqa: E402
from lib import momentum_setup_evidence as mse  # noqa: E402
from lib.scanner_candidate_projection import AT_CONTRACT, build_candidate_projection  # noqa: E402

ET = ZoneInfo("America/New_York")


# ── fakes ─────────────────────────────────────────────────────────────────────


class FakeCur:
    """Routes SQL to canned rows by substring (first match wins). Records every statement."""

    def __init__(self, routes, log=None):
        self.routes = routes
        self.log = log if log is not None else []
        self._rows = []
        self.description = [("id",)]

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        self._rows = []
        for needle, rows in self.routes:
            if needle in sql:
                self._rows = list(rows(params) if callable(rows) else rows)
                break

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass


class FakeConn:
    def __init__(self, routes, log=None):
        self.routes = routes
        self.log = log if log is not None else []
        self.closed = 0

    def cursor(self):
        return FakeCur(self.routes, self.log)

    def commit(self):
        pass

    def rollback(self):
        pass


def _capture_telegram(monkeypatch):
    sent = []
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = lambda text, **kw: sent.append({"text": text, **kw}) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    return sent


def _plain(text):
    import html
    import re

    return html.unescape(re.sub(r"<[^>]+>", "", text or ""))


# ── FIX 1 — swing entry alerts carry identity, catalyst and the CIO decision ───────────────

FOXA_PLAN = {
    "setup_type": "pullback_to_support", "entry_zone_low": 58.1, "entry_zone_high": 59.0, "limit_price": 58.6,
    "stop_price": 56.4, "target_price": 65.0, "risk_reward": 2.4, "confidence": 0.72, "urgency": "near_entry",
    "entry_thesis": "Pullback into the 50-day after the Tubi print; buyers defended 58 twice.",
    "invalidation": "Daily close below 56.40", "proposal": {"tag": "NEEDS_CONFIRMATION", "sizing_rationale": "half size"},
}
GRMN_PLAN = {
    "setup_type": "breakout_retest", "entry_zone_low": 234.0, "entry_zone_high": 238.0, "limit_price": 236.0,
    "stop_price": 228.5, "target_price": 255.0, "risk_reward": 2.5, "confidence": 0.78, "urgency": "ready",
    "entry_thesis": "Retest of the August breakout level holding on light volume.",
    "invalidation": "Close below 228.50", "proposal": {"tag": "READY", "sizing_rationale": "full size"},
}
CREATED = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)


def _context_routes(with_data=True):
    if not with_data:
        return [("symbol_profiles", []), ("watchlist_strategy_cards", []), ("cio_decisions", [])]
    return [
        ("symbol_profiles", lambda p: [r for r in [
            ("FOXA", "Fox Corporation — news, sports and entertainment (FOX News, FOX Sports, Tubi).",
             "Communication Services", "Entertainment"),
            ("GRMN", "Garmin Ltd. — GPS-enabled wearables, marine, aviation and auto devices.",
             "Technology", "Scientific & Technical Instruments"),
        ] if r[0] in p[0]]),
        ("watchlist_strategy_cards", lambda p: [r for r in [
            ("FOXA", "Fiscal Q1 earnings 2026-11-03; Tubi revenue growth +27% y/y"),
            ("GRMN", "Q3 earnings 2026-10-29; fitness segment guidance raised"),
        ] if r[0] in p[0]]),
        ("cio_decisions", lambda p: [r for r in [
            ("FOXA", "HOLD", "cio-daily-foxa-20261015", "daily_decision", CREATED),
            ("GRMN", "BUY", "cio-entry-review-grmn-20261015140000", "entry_review", CREATED),
        ] if r[0] in p[0]]),
    ]


@pytest.fixture
def planner(monkeypatch):
    import watchlist_entry_planner as wep

    monkeypatch.setenv("TELEGRAM_RICH_ALERTS", "1")
    monkeypatch.setattr(wep, "_held", lambda sym: False)
    import lib.publisher_stance_gate as psg

    monkeypatch.setattr(psg, "gate_card", lambda body, sym, source=None: types.SimpleNamespace(
        send=True, text=body, held_reason=None))
    return wep


@pytest.mark.parametrize("sym,plan,urg,price", [("FOXA", FOXA_PLAN, "near_entry", 59.40),
                                                ("GRMN", GRMN_PLAN, "ready", 236.20)])
def test_fix1_planner_entry_alert_names_company_catalyst_and_cio(planner, monkeypatch, sym, plan, urg, price):
    sent = _capture_telegram(monkeypatch)
    monkeypatch.setattr(planner, "_alert_context",
                        lambda s: eac.entry_alert_context(FakeCur(_context_routes()), s), raising=False)
    assert planner._alert(sym, dict(plan), urg, price) is True
    text = _plain(sent[0]["text"])
    assert "identity data unavailable" not in text
    assert "Catalyst: unavailable" not in text and "Unavailable — research gap" not in text
    assert "CIO review: unreviewed" not in text and "Review: UNREVIEWED" not in text
    if sym == "FOXA":
        assert "Fox Corporation" in text and "Entertainment" in text
        assert "Tubi revenue growth" in text
        assert "HOLD" in text and "cio-daily-foxa-20261015" in text
    else:
        assert "Garmin Ltd." in text
        assert "Q3 earnings 2026-10-29" in text
        assert "cio-entry-review-grmn-20261015140000" in text and "REVIEWED" in text


def test_fix1_absent_facts_stay_honestly_unavailable(planner, monkeypatch):
    sent = _capture_telegram(monkeypatch)
    monkeypatch.setattr(planner, "_alert_context",
                        lambda s: eac.entry_alert_context(FakeCur(_context_routes(False)), s), raising=False)
    assert planner._alert("FOXA", dict(FOXA_PLAN), "near_entry", 59.40) is True
    text = _plain(sent[0]["text"])
    assert "FOXA · identity data unavailable" in text
    assert "unavailable" in text.lower()      # catalyst stays an honest "unavailable"
    assert "UNREVIEWED" in text or "unreviewed" in text


def test_fix1_non_review_decision_never_turns_a_ready_card_green():
    """Only an entry_review row is a review of the entry (VCIG rule 2026-10-05)."""
    hold = eac.cio_review_fields({"action": "HOLD", "decision_id": "d1", "action_class": "daily_decision"})
    assert "cio_review_id" not in hold and hold["cio_decision_id"] == "d1"
    review = eac.cio_review_fields({"action": "BUY", "decision_id": "d2", "action_class": "entry_review"})
    assert review["cio_review_id"] == "d2" and review["cio_review_status"] == "REVIEWED"
    assert eac.cio_review_fields(None) == {}


# ── FIX 2 + FIX 5 — the conflict rule and the momentum-evidence appendix ──────────────────

BETR_NOW = datetime(2026, 10, 19, 14, 38, 30, tzinfo=timezone.utc)   # 10:38:30 ET
BETR_SCAN = {
    "symbol": "BETR", "price": 4.21, "float_m": 7.04, "rvol": 6.3, "gap_pct": 14.2, "decision": "WAIT",
    "run_id": "2026-10-19::0900", "observed_at": "2026-10-19T13:01:00+00:00",
    "catalyst": "BETR announces state approval for online sportsbook expansion",
    "catalyst_source": "globenewswire", "catalyst_verified": True, "catalyst_at": "2026-10-19T12:30:00+00:00",
}
BETR_MSG = ("ACTIVE TRADER · SCALP ALERT\n🔵 APPROACHING · BETR · about to fire — trigger above 4.31, now 4.29\n"
            "ADVISORY ONLY — NOT AN ORDER. Your decision, your broker.\n"
            "last 4.29 · entry 4.32 · stop 4.18 · R 0.14\ncatalyst: BETR announces state approval · globenewswire")


def _at_row(verdict, hhmm, kind="APPROACHING", sym="BETR"):
    h, m = (int(x) for x in hhmm.split(":"))
    ts = datetime(2026, 10, 19, h, m, tzinfo=ET).timestamp()
    return {"contract": AT_CONTRACT, "ts_epoch": ts, "verdict": verdict, "kind": kind, "sent": verdict == "ALERT",
            "candidate": {"symbol": sym, "session_date": "2026-10-19", "last": 4.29, "source": "fast"}}


def _betr_journal():
    return [_at_row("VETO", t) for t in ("10:33", "10:34", "10:35", "10:36")] + [_at_row("ALERT", "10:38")]


def _snapshot(journal, tickers=(BETR_SCAN,)):
    cache = {"run_id": "2026-10-19::0900", "latest_run_timestamp": BETR_SCAN["observed_at"], "tickers": list(tickers)}
    return build_candidate_projection(cache, journal, now=BETR_NOW)


def _enrich(snapshot):
    return mse.enrich_active_trader_notification(
        BETR_MSG, message_class="active_trader_scalp_alert", primary_symbols=["BETR"],
        snapshot_loader=lambda: snapshot, now=BETR_NOW)


def test_fix2_later_alert_after_earlier_vetoes_is_not_a_conflict():
    snap = _snapshot(_betr_journal())
    row = next(c for c in snap["candidates"] if c["symbol"] == "BETR")
    assert "ACTIVE_TRADER_VERDICT_CONFLICT" not in row["conflicts"]
    assert row["active_trader"]["latest_verdict"] == "ALERT"
    found = mse.same_symbol_evidence("BETR", snap, now=BETR_NOW)
    assert found["status"] == "CURRENT" and found["source"] == "trade_ai"


def test_fix2_betr_message_carries_trade_ai_evidence_not_unknown():
    out = _enrich(_snapshot(_betr_journal()))
    assert "current same-symbol evidence unavailable" not in out
    assert f"{mse.MARKER}:" in out and "source facts · TRADEAI" in out


def test_fix2_internal_at_conflict_falls_back_to_trade_ai_for_display_only():
    # A genuine same-instant ALERT/VETO pair is still a conflict...
    tie = [_at_row("VETO", "10:38"), _at_row("ALERT", "10:38")]
    snap = _snapshot(tie)
    row = next(c for c in snap["candidates"] if c["symbol"] == "BETR")
    assert row["conflicts"] == ["ACTIVE_TRADER_VERDICT_CONFLICT"]
    # ...the gate's view is unchanged (premarket_watch.momentum_gate reads the default)...
    assert mse.same_symbol_evidence("BETR", snap, now=BETR_NOW)["status"] == "CONFLICT"
    # ...but the alert shows the Trade-AI evidence instead of giving up.
    out = _enrich(snap)
    assert "source facts · TRADEAI" in out and "evidence unavailable" not in out


def test_fix5_unstamped_active_trader_only_evidence_block_is_dropped():
    snap = _snapshot([_at_row("ALERT", "10:38")], tickers=())
    found = mse.same_symbol_evidence("BETR", snap, now=BETR_NOW)
    assert found["source"] == "active_trader"            # precondition: the 0/5 false positive
    out = _enrich(snap)
    assert out == BETR_MSG
    assert "0/5" not in out and "UNKNOWN" not in out


def test_fix5_no_evidence_omits_the_unknown_line():
    assert _enrich(None) == BETR_MSG
    assert _enrich({"candidates": []}) == BETR_MSG


def test_fix5_trade_ai_block_with_passed_rows_stays():
    out = _enrich(_snapshot([]))
    assert "source facts · TRADEAI" in out and "Driven by: " in out and "✓" in out


def test_fix5_formatter_and_gate_semantics_unchanged():
    # premarket_watch prints format_notification_evidence directly; its UNKNOWN wording is untouched.
    assert mse.format_notification_evidence(None).endswith("UNKNOWN — current same-symbol evidence unavailable")


# ── FIX 3 — fast-loop alerts carry the 5-minute pass's values ─────────────────────────────

BETR_EPOCH = datetime(2026, 10, 19, 10, 38, 5, tzinfo=ET).timestamp()


def _fast_ticker(monkeypatch, tmp_path, conn_fn):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path))
    from active_trader import fast_trigger_loop as ftl
    from active_trader import momentum_alerts as ma

    monkeypatch.setattr(ftl, "store", types.SimpleNamespace(
        bars=lambda *a, **k: {"status": "ok", "closed": [], "forming": None},
        quote=lambda *a, **k: (4.29, BETR_EPOCH - 1),
        book=lambda *a, **k: None, tape=lambda *a, **k: []))
    monkeypatch.setattr(ftl, "step", lambda sym, *a, **k: [ma.Candidate(
        symbol=sym, lane="FAST", ign=0.0, fsm_state="ARMED", last=4.29, quote_ts_epoch=BETR_EPOCH - 1,
        session_date="2026-10-19", kind_hint=ma.APPROACHING, source="fast", entry_ref=4.32, stop_ref=4.18,
        break_level=4.31)])
    seen = []
    monkeypatch.setattr(ma, "evaluate_pass", lambda cands, **kw: seen.extend(cands) or [])
    tick = ftl.ticker({}, conn_fn=conn_fn)
    return tick, seen, ma


def _scan_routes():
    scan = {"symbol": "BETR", "decision": "WAIT", "not_tradeable": False,
            "scanned_at": datetime(2026, 10, 19, 9, 1, tzinfo=ET), "price": 4.21, "float_m": 7.04, "rvol": 6.3,
            "gap_pct": 14.2, "change_pct": 9.0, "catalyst": BETR_SCAN["catalyst"], "catalyst_verified": True,
            "catalyst_source": "globenewswire", "catalyst_url": None, "catalyst_at": None}
    return [
        ("FROM trade_ai_scans", lambda p: [scan] if p and p[0] == "2026-10-19" else []),
        ("FROM scalp_ignition_events", lambda p: [("BETR", 5.4, "bull_flag", "Bull flag", None)]
         if p and p[0] == "2026-10-19" else []),
        ("FROM scalp_scan_results", [(7.04,)]),
    ]


def test_fix3_betr_fast_alert_carries_same_day_scan_rvol_setup_and_float(monkeypatch, tmp_path):
    tick, seen, ma = _fast_ticker(monkeypatch, tmp_path, lambda: FakeConn(_scan_routes()))
    tick(BETR_EPOCH, ["BETR"])
    c = seen[0]
    assert (c.trade_ai or {}).get("decision") == "WAIT"
    assert c.rvol == 5.4 and c.setup_label == "Bull flag" and c.float_mm == 7.04
    _, body = ma.build_message(c, ma.APPROACHING, {"source": "moomoo", "levels": 0}, {}, {})
    assert "NO_SAME_DAY_SCAN" not in body
    assert "Trade-AI today: WAIT 09:01" in body
    assert "float 7.0M · RVOL 5.4x · setup Bull flag" in body


def test_fix3_journal_pass5_values_win_and_stale_days_are_ignored(monkeypatch, tmp_path):
    day_ts = datetime(2026, 10, 19, 10, 30, tzinfo=ET).timestamp()
    old_ts = datetime(2026, 10, 16, 10, 30, tzinfo=ET).timestamp()
    rows = [
        {"contract": AT_CONTRACT, "ts_epoch": old_ts, "source": "pass5", "kind": "ARMED", "verdict": "ALERT",
         "candidate": {"symbol": "BETR", "session_date": "2026-10-16", "rvol": 99.0, "float_mm": 99.0,
                       "setup_label": "OLD", "trade_ai": {"decision": "GO", "scanned_at": "2026-10-16T09:00:00"}}},
        {"contract": AT_CONTRACT, "ts_epoch": day_ts, "source": "pass5", "kind": "ARMED", "verdict": "VETO",
         "candidate": {"symbol": "BETR", "session_date": "2026-10-19", "rvol": 4.8, "float_mm": 7.04,
                       "setup_label": "ABCD pattern",
                       "trade_ai": {"decision": "WAIT", "scanned_at": "2026-10-19T09:01:00-04:00"}}},
    ]
    (tmp_path / "momentum_alerts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    tick, seen, _ = _fast_ticker(monkeypatch, tmp_path, None)
    tick(BETR_EPOCH, ["BETR"])
    c = seen[0]
    assert c.rvol == 4.8 and c.setup_label == "ABCD pattern" and c.float_mm == 7.04
    assert c.trade_ai["decision"] == "WAIT"


def test_fix3_no_same_day_scan_stays_explicit(monkeypatch, tmp_path):
    tick, seen, ma = _fast_ticker(monkeypatch, tmp_path, lambda: FakeConn([]))
    tick(BETR_EPOCH, ["BETR"])
    assert seen[0].trade_ai is None
    assert ma.trade_ai_line(seen[0].trade_ai) == "Trade-AI: NO_SAME_DAY_SCAN · verdict not attached"


# ── FIX 4 — STAND DOWN: levels filled, no all-n/a lines ───────────────────────────────────

NCPL_NOW = datetime(2026, 10, 16, 10, 15, 15, tzinfo=ET).timestamp()


def _stand_down(info, state):
    from active_trader import momentum_alert_pass as map_
    from active_trader import momentum_alerts as ma

    throttle = {"last": {"NCPL:ARMED:leg:2.1400": NCPL_NOW - 600}}
    tai = {"NCPL": {"decision": "WAIT", "scanned_at": "2026-10-16T09:35:00-04:00",
                    "catalyst": "NCPL signs AI data-center LOI"}}
    cands = map_.stand_down_candidates(throttle, {"NCPL": state}, {"NCPL": info}, set(), now=NCPL_NOW,
                                       cfg=ma.AlertConfig(), day="2026-10-16",
                                       trig_cfg={"entry_offset": 0.01, "stop_offset": 0.01},
                                       prices={"NCPL": 2.05}, trade_ai=tai)
    assert len(cands) == 1
    c = cands[0]
    l2 = ma.l2_evidence(None, now=NCPL_NOW, cfg=ma.AlertConfig(), source="moomoo")
    title, body = ma.build_message(c, ma.STAND_DOWN, l2, {}, {"quote_age_s": None})
    return c, title, body


def test_fix4_stale_stand_down_states_last_entry_stop_and_trade_ai():
    info = {"state": "ARMED", "leg_high": 2.14, "prev_high": 2.12, "pullback_low": 2.0, "armed_bars": 40}
    c, title, body = _stand_down(info, "ARMED")
    assert "STAND DOWN · NCPL" in title
    assert c.last == 2.05 and c.entry_ref == 2.13 and c.stop_ref == 1.99
    assert "last 2.05 · entry 2.13 · stop 1.99" in body
    assert "L2 " not in body and "bid/ask" not in body
    assert "Trade-AI today: WAIT 09:35" in body
    assert "NO_SAME_DAY_SCAN" not in body


def test_fix4_broken_down_stand_down_prints_no_all_na_line():
    info = {"state": "IDLE", "leg_high": None, "prev_high": 2.08, "pullback_low": None, "armed_bars": 0}
    _, _, body = _stand_down(info, "PULLBACK")
    assert "last 2.05" in body
    for line in body.splitlines():
        assert "n/a" not in line or line.startswith("catalyst:"), line
    assert "L2 " not in body


def test_fix4_other_kinds_keep_their_l2_line():
    from active_trader import momentum_alerts as ma

    c = ma.Candidate(symbol="NCPL", lane="A", ign=1.0, fsm_state="ARMED", last=2.1, session_date="2026-10-16")
    _, body = ma.build_message(c, ma.ARMED, {"source": "moomoo", "levels": 0}, {}, {})
    assert "L2 moomoo 0 lv" in body


# ── FIX 6 — swing entry alerts have ONE sender (cio_entry_state_runner) ──────────────────

LLM_PLAN = json.dumps({**{k: v for k, v in FOXA_PLAN.items() if k != "urgency"}, "urgency": "ready",
                       "proposal": {"tag": "READY", "sizing_rationale": "half size"}})


@pytest.fixture
def flag(monkeypatch, tmp_path):
    path = tmp_path / "swing_entry_alerts.yaml"

    def set_(on):
        path.write_text(f"single_sender: {'true' if on else 'false'}\n")
        monkeypatch.setenv("SWING_ENTRY_ALERTS_CONFIG", str(path))
    return set_


def _planner_fakes(monkeypatch, wep, inserts):
    llm = types.ModuleType("llm_lane")
    llm.available = lambda name: True
    llm.generate = lambda prompt, **kw: LLM_PLAN
    monkeypatch.setitem(sys.modules, "llm_lane", llm)

    def insert(params):
        inserts.append(params)
        return [(4242,)]

    routes = [("INSERT INTO watchlist_entry_plans", insert), ("SELECT 1 FROM watchlist_entry_plans", []),
              ("SELECT 1", [(1,)])]
    conn = FakeConn(routes)
    dba = types.ModuleType("db_adapter")
    dba._get_conn = lambda: conn
    dba.close_thread_conn = lambda: None
    monkeypatch.setitem(sys.modules, "db_adapter", dba)
    monkeypatch.setattr(wep, "_candidates", lambda *a, **k: [
        {"symbol": "FOXA", "hermes_composite_score": 81, "hermes_rank": 12, "trend": "up"}])
    monkeypatch.setattr(wep, "_bars", lambda sym: [{"c": 58.6}] * 60)
    monkeypatch.setattr(wep, "_tech", lambda bars: {"price": 58.6, "rsi": 44.0, "atr": 1.2, "swing_high": 62.0,
                                                    "swing_low": 56.0, "sma50": 57.5})
    monkeypatch.setattr(wep, "_analyst", lambda cur, sym: {})
    monkeypatch.setattr(wep, "PROMPT_V1", "plan {symbol}")
    monkeypatch.setattr(wep, "_alert_context",
                        lambda s: eac.entry_alert_context(FakeCur(_context_routes()), s), raising=False)


def test_fix6a_planner_persists_plan_and_sends_nothing(planner, monkeypatch, flag):
    flag(True)
    sent = _capture_telegram(monkeypatch)
    inserts = []
    _planner_fakes(monkeypatch, planner, inserts)
    res = planner.run(lane="grok")
    assert res["planned"] == 1 and len(inserts) == 1
    stored = json.loads(inserts[0][1])
    assert stored["alert_eligible"] is True and inserts[0][9] == "ready"
    assert sent == [] and res["alerts"] == 0
    assert res.get("alerts_handed_to") == "cio_entry_state_runner"


def test_fix6d_flag_off_restores_planner_sender(planner, monkeypatch, flag):
    flag(False)
    sent = _capture_telegram(monkeypatch)
    _planner_fakes(monkeypatch, planner, [])
    res = planner.run(lane="grok")
    assert res["alerts"] == 1 and len(sent) == 1
    assert "Fox Corporation" in _plain(sent[0]["text"])


def _runner_routes(planner_symbols):
    plan_row = ("FOXA", 58.1, 59.0, 56.4, 65.0, CREATED)
    return [
        ("FROM watchlist_items WHERE status='active'", [("AAPL",)]),
        ("plan->>'alert_eligible'", [(s,) for s in planner_symbols]),
        ("FROM watchlist_entry_plans", lambda p: [plan_row] if "FOXA" in p[0] else []),
        ("ideal_entry, add_zone_low", lambda p: [("FOXA", None, None, None, None, None,
                                                  "Fiscal Q1 earnings 2026-11-03; Tubi revenue growth +27% y/y", 5.0)]
         if "FOXA" in p[0] else []),
        *_context_routes()[:1],
        *_context_routes()[1:],
        ("decision_packets", []),
    ]


@pytest.fixture
def runner(monkeypatch):
    import cio_entry_state_runner as cesr
    import lib.alert_quotes as aq

    monkeypatch.setattr(cesr, "_load_json", lambda path, default: default)
    # The FOXA plan fixture is CREATED 2026-10-15; pin the plan-age clock to two hours later so the 7-day plan
    # limit (cio_entry_state.PLAN_MAX_AGE_H) is judged against the fixture day, not the CI wall clock
    # (it went red on 2026-10-22, exactly 7 days on).
    monkeypatch.setattr(cesr, "_age_h", lambda ts: None if ts is None else
                        (CREATED.timestamp() + 7200 - ts.timestamp()) / 3600.0)
    monkeypatch.setattr(aq, "broker_quotes", lambda cur, syms: {
        s: {"price": 58.55, "age_h": 0.05, "chg_pct": -0.6} for s in syms if s == "FOXA"})
    return cesr


def test_fix6b_runner_picks_up_planner_plan_and_sends_one_complete_message(runner, monkeypatch, flag):
    flag(True)
    ev = runner.gather(FakeCur(_runner_routes(["FOXA"])))
    assert "FOXA" in ev
    e = ev["FOXA"]
    assert e["plan_source"] == "entry_plan"
    assert e["company"].startswith("Fox Corporation") and e["sector"] == "Communication Services"
    assert e["cio_action"] == "HOLD" and e["cio_decision_id"] == "cio-daily-foxa-20261015"
    from lib import cio_entry_state as ces

    result = ces.evaluate(e)
    assert result["state"] == "BUY_READY", result["reasons"]
    sends = []
    monkeypatch.setattr(runner, "operator_send", lambda payload, primary_symbols=None: sends.append(payload)
                        or {"operator": True})
    digest = types.ModuleType("scripts.lib.advice_digest")
    digest.hold = lambda key: True
    monkeypatch.setitem(sys.modules, "scripts.lib.advice_digest", digest)
    bus = types.ModuleType("scripts.lib.cio_event_bus")
    bus.CIOEventBus = lambda: types.SimpleNamespace(emit=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_event_bus", bus)
    monkeypatch.setattr(runner, "stamp_cio_stance", lambda text, syms, only_conflicts=False: text)
    runner.send_alerts(result, e)
    assert len(sends) == 1
    text = _plain(sends[0]["text"])
    assert "Fox Corporation" in text and "identity data unavailable" not in text
    assert "Tubi revenue growth" in text
    assert "cio-daily-foxa-20261015" in text and "CIO review: unreviewed" not in text


def test_fix6c_no_duplicate_between_planner_and_runner(planner, runner, monkeypatch, flag):
    flag(True)
    sent = _capture_telegram(monkeypatch)
    _planner_fakes(monkeypatch, planner, [])
    planner.run(lane="grok")
    assert sent == []                                   # the planner no longer pages
    from lib import cio_entry_state as ces

    e = runner.gather(FakeCur(_runner_routes(["FOXA"])))["FOXA"]
    result = ces.evaluate(e)
    first = runner.alert_worthy([result], {}, set(), set())
    assert [r["symbol"] for r in first] == ["FOXA"]
    again = runner.alert_worthy([result], {"FOXA": "BUY_READY"}, {ces.transition_key(result)}, set())
    assert again == []                                  # the runner's existing per-symbol/state/day dedupe


def test_fix6d_flag_off_runner_does_not_widen_its_universe(runner, flag):
    flag(False)
    ev = runner.gather(FakeCur(_runner_routes(["FOXA"])))
    assert "FOXA" not in ev
