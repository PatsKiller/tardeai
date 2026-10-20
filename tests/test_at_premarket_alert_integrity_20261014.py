"""Active Trader premarket alert integrity (operator 2026-10-14, GLND 08:30 / 09:05 ET).

"Who is actually writing this? Why does this even fire without validated momentum?" Three defects:

1. Evidence gate — premarket_watch sent normal heads-ups while same-symbol momentum evidence was UNKNOWN
   or conflicted. The sender now asks the evidence library and, without VALIDATED evidence, sends an
   explicit UNVALIDATED heads-up (config `evidence_gate: downgrade`) or journals only (`hold`).
2. RMAX leak — the CIO stance chrome "RE-ENTER" normalised to "RE ENTER", progressive-prefix narrowed to
   "RE", matched only "RE/MAX HLDGS" and bound RMAX links + an RMAX id to a GLND alert.
3. CIO line contradiction — 82/100 RE-ENTER (previous session's curator run) vs 62/100 WATCH (09:00
   rescore): a legitimate rescore with no age shown. The line now carries its as-of time.

Fakes only: no OpenD, no database, no Telegram, no live token store, no served files.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from active_trader import momentum_alerts as ma  # noqa: E402
from active_trader import premarket_watch as pw  # noqa: E402
from scripts.lib import comms_editor as ce  # noqa: E402
from scripts.lib import company_name_index as C  # noqa: E402
from scripts.lib import momentum_setup_evidence as mse  # noqa: E402
from scripts.lib import operator_subject_resolver as osr  # noqa: E402
from scripts.lib import opportunity_alert as oa  # noqa: E402
from scripts.lib.scanner_candidate_projection import build_candidate_projection  # noqa: E402

ET = pw.ET
DAY = "2026-10-14"
NOW = datetime(2026, 10, 14, 8, 30, 5, tzinfo=ET).timestamp()
NOW_DT = datetime.fromtimestamp(NOW, timezone.utc)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    monkeypatch.setenv("COMMS_EDITOR_LEDGER", str(tmp_path / "ledger.json"))
    return tmp_path / "at"


# ── fixtures ────────────────────────────────────────────────────────────────

def _bars(n=61, start=(7, 29), base=3.6, step=0.01, vol=380_000):
    out = []
    h, m = start
    for i in range(n):
        mm = m + i
        hh, mm = h + mm // 60, mm % 60
        c = base + step * i
        out.append({"time_key": f"{DAY} {hh:02d}:{mm:02d}:00", "open": c, "high": c + 0.02, "low": c - 0.02,
                    "close": c, "volume": vol})
    return out


class FakeData:
    def __init__(self):
        self.bar_calls = []

    def snapshot(self, syms):
        return {s: {"prev_close": 2.31} for s in syms}

    def bars(self, sym):
        self.bar_calls.append(sym)
        return _bars()

    def book(self, sym, now):
        return {"bids": [(4.19 - i * 0.01, 9000) for i in range(10)],
                "asks": [(4.20 + i * 0.01, 3000) for i in range(10)], "ts_epoch": now - 2}

    def tape(self, sym):
        return [{"ts_epoch": NOW - 5, "price": 4.2, "volume": 100, "direction": "BUY"}] * 20


def _evidence(passed: int) -> dict:
    """A CURRENT MomentumSetupEvidence for GLND from the library itself, proving `passed` facts."""
    row = {"symbol": "GLND", "price": 4.2, "float_m": 8, "rvol": 6, "gap_pct": 70,
           "catalyst": "Fixture filing", "catalyst_source": "fixture-news",
           "catalyst_url": "https://news.example/glnd", "catalyst_verified": True,
           "catalyst_verification_method": "PRIMARY_PUBLICATION",
           "catalyst_at": "2026-10-14T11:00:00+00:00", "observed_at": "2026-10-14T12:25:00+00:00",
           "run_id": f"{DAY}::0700"}
    drop = ["catalyst_verified", "rvol", "gap_pct", "float_m", "price"][: 5 - passed]
    for key in drop:
        row.pop(key, None)
    ev = mse.build_setup_evidence(row, now=NOW_DT, source_name="TRADE_AI")
    assert ev["passed_count"] == passed and ev["source_observation_state"] == "CURRENT_SESSION"
    return ev


def _snapshot(*, evidence=None, conflicts=(), session=DAY, extra=()):
    obs = [] if evidence is None else [{"observed_at": "2026-10-14T12:25:00+00:00", "setup_evidence": evidence,
                                        "freshness": "NOT_MEASURED"}]
    cand = {"symbol": "GLND", "session_date": session, "conflicts": list(conflicts),
            "trade_ai": {"observations": obs}, "active_trader": {"observations": []}}
    return {"candidates": [cand, *extra]}


_RUNS = iter(range(10_000))


def _run(cfg, snapshot, *, send=True):
    """One pass with its own throttle file (a second pass in one test is not a COOLDOWN)."""
    got = []

    def send_fn(**k):
        got.append({**k, "primary": ce._resolve_primary_symbols(None)})
        return {"sent": True}

    rows = pw.evaluate([{"symbol": "GLND", "float_mm": 27.5}], data=FakeData(), cfg=cfg, now=NOW, day=DAY,
                       as_of_hm="08:30", live_book=True, persist=True, send_fn=send_fn if send else None,
                       evidence_loader=lambda: snapshot,
                       throttle_path=ma.journal_dir() / f"throttle-{next(_RUNS)}.json")
    return rows[0], got


# ── 1. evidence gate ────────────────────────────────────────────────────────

def test_root_cause_premarket_watch_conflicts_with_itself():
    """The 08:30 conflict was the watch's own history: a VETO pass then an ALERT pass for the same
    symbol-session was ACTIVE_TRADER_VERDICT_CONFLICT in the shared projection.

    Operator 2026-10-19 (BETR): a source's conflict is judged on its LATEST verdict only, so this history
    is no longer a conflict. The gate outcome is unchanged: the watch's own observation proves no fact
    (0 passed), so the heads-up is still UNVALIDATED."""
    def row(verdict, minute):
        return {"contract": ma.CONTRACT, "kind": pw.PREMARKET_WATCH, "verdict": verdict,
                "ts_epoch": datetime(2026, 10, 14, 6, minute, tzinfo=ET).timestamp(),
                "candidate": {"symbol": "GLND", "session_date": DAY, "last": 3.9, "float_mm": 27.5}}
    snap = build_candidate_projection({"tickers": []}, [row("VETO", 35), row("ALERT", 40), row("VETO", 45)],
                                      now=NOW_DT)
    found = mse.same_symbol_evidence("GLND", snap, now=NOW_DT)
    assert found["conflicts"] == [] and found["status"] in ("CURRENT", "UNKNOWN")
    assert not found["passed_count"]
    gate = pw.momentum_gate("GLND", snap, cfg=pw.PremarketConfig(mode="send"), now=NOW)
    assert gate["result"] == pw.UNVALIDATED
    # A same-instant VETO/ALERT pair is still a conflict, and the gate still sees CONFLICT.
    tie = build_candidate_projection({"tickers": []}, [row("VETO", 45), row("ALERT", 45)], now=NOW_DT)
    found = mse.same_symbol_evidence("GLND", tie, now=NOW_DT)
    assert found["status"] == "CONFLICT" and found["conflicts"] == ["ACTIVE_TRADER_VERDICT_CONFLICT"]
    assert found["evidence"] is None


def test_gate_states():
    cfg = pw.PremarketConfig(mode="send")
    assert pw.momentum_gate("GLND", None, cfg=cfg, now=NOW)["status"] == "SNAPSHOT_UNAVAILABLE"
    c = pw.momentum_gate("GLND", _snapshot(evidence=_evidence(5), conflicts=["ACTIVE_TRADER_VERDICT_CONFLICT"]),
                         cfg=cfg, now=NOW)
    assert (c["result"], c["status"], c["conflicts"]) == (pw.UNVALIDATED, "CONFLICT", ["ACTIVE_TRADER_VERDICT_CONFLICT"])
    assert pw.momentum_gate("GLND", _snapshot(), cfg=cfg, now=NOW)["status"] == "UNKNOWN"
    partial = pw.momentum_gate("GLND", _snapshot(evidence=_evidence(3)), cfg=cfg, now=NOW)
    assert (partial["result"], partial["status"], partial["passed_count"]) == (pw.UNVALIDATED, "CURRENT", 3)
    full = pw.momentum_gate("GLND", _snapshot(evidence=_evidence(5)), cfg=cfg, now=NOW)
    assert full["result"] == pw.VALIDATED


def test_threshold_is_config_not_code():
    snap = _snapshot(evidence=_evidence(3))
    assert pw.momentum_gate("GLND", snap, cfg=pw.PremarketConfig(evidence_min_passed=3), now=NOW)["result"] == pw.VALIDATED
    assert pw.momentum_gate("GLND", snap, cfg=pw.PremarketConfig(evidence_min_passed=4), now=NOW)["result"] == pw.UNVALIDATED
    cfg = pw.PremarketConfig.from_mapping({"mode": "send", "evidence_gate": "hold", "evidence_min_passed": 2})
    assert (cfg.evidence_gate, cfg.evidence_min_passed) == ("hold", 2)
    with pytest.raises(ValueError):
        pw.PremarketConfig.from_mapping({"evidence_gate": "silent"})
    served = pw.load_config(ROOT / "config" / "scalp_signal_engine.yaml")
    assert served.evidence_gate == "downgrade" and served.evidence_min_passed == 5


def test_yesterdays_candidate_does_not_make_today_ambiguous():
    old = {"symbol": "GLND", "session_date": "2026-10-13", "conflicts": ["ACTIVE_TRADER_VERDICT_CONFLICT"],
           "trade_ai": {"observations": []}, "active_trader": {"observations": []}}
    found = mse.same_symbol_evidence("GLND", _snapshot(evidence=_evidence(5), extra=[old]), now=NOW_DT)
    assert found["status"] == "CURRENT" and found["passed_count"] == 5


def test_downgrade_sends_an_explicit_unvalidated_heads_up(_isolated):
    r, got = _run(pw.PremarketConfig(mode="send"),
                  _snapshot(evidence=_evidence(5), conflicts=["ACTIVE_TRADER_VERDICT_CONFLICT"]))
    assert r["verdict"] == ma.ALERT and r["sent"] is True and len(got) == 1
    text = got[0]["title"] + "\n" + got[0]["body"]
    lines = text.splitlines()
    assert lines[0] == ma.AT_SCALP_ALERT_HEADER and "UNVALIDATED heads-up" in lines[1]
    assert "levels for the open" not in text
    assert lines[3].startswith(mse.UNVALIDATED_MARK) and "CONFLICTED (ACTIVE_TRADER_VERDICT_CONFLICT)" in lines[3]
    assert mse.MARKER in text                     # the transport therefore adds no second footer
    assert ce.is_active_trader_scalp_alert(text)  # still the exempt AT class at the comms editor
    assert mse.enrich_active_trader_notification(text, message_class="active_trader_scalp_alert",
                                                 primary_symbols=["GLND"], snapshot_loader=lambda: None) == text
    j = json.loads((_isolated / "momentum_alerts.jsonl").read_text().splitlines()[-1])
    assert j["momentum_evidence"]["result"] == pw.UNVALIDATED and j["momentum_evidence"]["status"] == "CONFLICT"
    assert "evidence" not in j["momentum_evidence"]


def test_validated_evidence_keeps_the_normal_heads_up():
    r, got = _run(pw.PremarketConfig(mode="send"), _snapshot(evidence=_evidence(5)))
    text = got[0]["title"] + "\n" + got[0]["body"]
    assert "levels for the open" in text and mse.UNVALIDATED_MARK not in text and "UNVALIDATED" not in text
    assert r["momentum_evidence"]["result"] == pw.VALIDATED


def test_hold_journals_and_never_sends(_isolated):
    r, got = _run(pw.PremarketConfig(mode="send", evidence_gate="hold"), _snapshot())
    assert got == [] and r["sent"] is False
    assert r["verdict"] == ma.VETO and r["veto_reasons"] == ["MOMENTUM_EVIDENCE_UNKNOWN"]
    assert json.loads((_isolated / "momentum_alerts.jsonl").read_text())["momentum_evidence"]["gate"] == "hold"


def test_off_is_the_old_path_and_missing_loader_fails_closed():
    r, got = _run(pw.PremarketConfig(mode="send", evidence_gate="off"), None)
    assert "momentum_evidence" not in r and "levels for the open" in got[0]["title"]
    rows = pw.evaluate([{"symbol": "GLND", "float_mm": 27.5}], data=FakeData(), cfg=pw.PremarketConfig(mode="send"),
                       now=NOW, day=DAY, as_of_hm="08:30", live_book=True, persist=False,
                       send_fn=lambda **k: {"sent": True}, throttle_path=ma.journal_dir() / "fresh.json")
    assert rows[0]["momentum_evidence"]["status"] == "SNAPSHOT_UNAVAILABLE"
    assert "UNVALIDATED" in rows[0]["message"]["title"]


def test_loader_errors_fail_closed_and_load_once():
    calls = []

    def boom():
        calls.append(1)
        raise OSError("unreadable")
    uni = [{"symbol": "GLND", "float_mm": 27.5}, {"symbol": "TCRT", "float_mm": 2.4}]
    rows = pw.evaluate(uni, data=FakeData(), cfg=pw.PremarketConfig(mode="send"), now=NOW, day=DAY,
                       as_of_hm="08:30", live_book=True, persist=False, send_fn=lambda **k: {"sent": True},
                       evidence_loader=boom)
    assert [r["momentum_evidence"]["result"] for r in rows] == [pw.UNVALIDATED, pw.UNVALIDATED]
    assert calls == [1]


def test_cio_line_is_not_added_to_an_unvalidated_alert(tmp_path):
    p = _projection(tmp_path, "2026-10-14T13:00:13+00:00")
    _, got = _run(pw.PremarketConfig(mode="send"), _snapshot())
    text = got[0]["title"] + "\n" + got[0]["body"]
    now = datetime(2026, 10, 14, 13, 5, tzinfo=timezone.utc)
    assert oa.enrich(text, message_class="active_trader_scalp_alert", projection_path=p, now=now) == text
    _, ok = _run(pw.PremarketConfig(mode="send", evidence_gate="off"), None)
    normal = ok[0]["title"] + "\n" + ok[0]["body"]
    assert oa.MARK in oa.enrich(normal, message_class="active_trader_scalp_alert", projection_path=p, now=now)


def test_send_binds_the_alert_symbol_as_primary_and_restores_context():
    _, got = _run(pw.PremarketConfig(mode="send"), _snapshot())
    assert got[0]["primary"] == ["GLND"]
    assert ce._resolve_primary_symbols(None) is None


# ── 2. RMAX leak ────────────────────────────────────────────────────────────

FEED = {
    "RMAX": {"description": "RE/MAX HLDGS INC A"},
    "GLND": {"description": "GLADSTONE LAND FIXTURE CORP"},
    "NSC": {"description": "NORFOLK SOUTHN CORP"},
}
GUIDS = {"GLND": "ed3be018-0000-4000-8000-000000000001", "RMAX": "79a76ac5-0000-4000-8000-000000000002"}

MSG_0830 = "\n".join([
    "ACTIVE TRADER · SCALP ALERT",
    "🔵 PREMARKET · GLND · gapping +73.2% — levels for the open",
    "ADVISORY ONLY — NOT AN ORDER. Your decision, your broker.",
    "last 4.00 · prev close 2.31 · as of 08:30 ET",
    "PM high 4.15 (07:55) = break level · PM VWAP 3.52 = stop reference",
    "L2 moomoo 10 lv: bid/ask 2.82x · spread 25 bps",
    "Heads-up only: wait for the open; the regular engine confirms after 09:30.",
    "",
    "🧭 Conviction CIO swing view (not this scalp): 82/100 · #8 of 1,375 · R:R 5.5x · RE-ENTER — "
    '<a href="https://cc.example/v3/watch?tab=opportunities&amp;opp=GLND">Open in Command Center</a>',
])


@pytest.fixture()
def feed(monkeypatch):
    monkeypatch.setattr(C, "_instruments", lambda: FEED)
    monkeypatch.setattr(C, "_house_names", lambda: [])
    monkeypatch.setattr(osr, "_identity", lambda doc, s: {"guid": GUIDS[s]} if s in GUIDS else {})
    C.refresh()
    yield
    C.refresh()


def test_short_narrowed_prefix_never_binds_an_issuer(feed):
    assert C.resolve_name("RE-ENTER") is None
    assert C.resolve_name("RE ENTER") is None
    assert C.resolve_name("Norfolk Southern")["symbol"] == "NSC"     # narrowing itself still works
    assert C.resolve_name("RE/MAX")["symbol"] == "RMAX"              # the real name still resolves


def test_0830_glnd_message_carries_no_rmax_chrome(feed, tmp_path):
    d = ce.edit(MSG_0830, chat_id="1", now=NOW_DT, ledger=ce.DuplicateLedger(tmp_path / "l.json"),
                resolve=lambda t: osr.resolve_subjects(t, book=[], registry={}), editor_mode="shadow")
    assert "RMAX" not in d.text and "79a76ac5" not in d.text
    assert "GLND:ed3be018" in d.text and "GLND in Command Center" in d.text
    assert [s["symbol"] for s in d.subjects] == ["GLND"]


# ── 3. CIO line as-of ───────────────────────────────────────────────────────

def _projection(tmp_path, as_of, *, item_as_of=None, conviction=61.5, rank=694, stance="WATCH"):
    item = {"symbol": "GLND", "conviction": conviction, "rank": rank, "stance": stance,
            "risk_reward": {"rr": 5.5}, "upside_pct": None}
    if item_as_of:
        item["as_of"] = item_as_of
    p = tmp_path / f"proj-{abs(hash(as_of))}.json"
    p.write_text(json.dumps({"as_of": as_of, "items": {"GLND": item}}))
    return p


def test_cio_line_shows_when_it_was_scored(tmp_path):
    before = _projection(tmp_path, "2026-10-13T20:30:10+00:00", conviction=82.9, rank=8, stance="RE_ENTER")
    after = _projection(tmp_path, "2026-10-14T13:00:13+00:00", item_as_of="2026-10-14T13:00:12+00:00")
    msg = MSG_0830.split("\n\n")[0]
    a = oa.enrich(msg, message_class="active_trader_scalp_alert", projection_path=before,
                  now=datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc))
    b = oa.enrich(msg, message_class="active_trader_scalp_alert", projection_path=after,
                  now=datetime(2026, 10, 14, 13, 5, tzinfo=timezone.utc))
    assert "83/100" in a and "RE-ENTER · as of 10-13 16:30 ET" in a
    assert "62/100" in b and "WATCH · as of 10-14 09:00 ET" in b


def test_line_without_a_parseable_time_shows_no_invented_time():
    line = oa.line_for({"symbol": "GLND", "conviction": 60, "stance": "WATCH"}, 10, "https://cc.example",
                       as_of="not-a-time")
    assert "as of" not in line
