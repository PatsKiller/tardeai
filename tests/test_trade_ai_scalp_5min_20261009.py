"""Trade-AI scalp scan every 5 min + one feed for Trade-AI and Active Trader (operator 2026-10-09: "these are scalps
should be every 5 minutes at least … same should be feeding both tradeai and also active trader"; "allow GO for 40+
with catalyst").

Runner GO promotion, shared AT universe feed, the 5-min lane (RTH gate, persisted alert memory, no dashboard/live-state
overwrite), enrichment without the LLM switch, the header scoped to the FULL run, and the AT fires strip.
Fakes only: no network, no LLM, no database.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import catalyst_exception as ce  # noqa: E402

ET = ZoneInfo("America/New_York")


def row(**k):
    base = {"symbol": "WFF", "decision": "MANUAL_REVIEW", "score": 44, "catalyst_verified": True,
            "setup_class": "momentum_runner", "not_tradeable": True, "manual_review_required": True}
    base.update(k)
    return base


def test_runner_with_catalyst_at_go_threshold_is_promoted():
    rows = [row(), row(symbol="LOW", score=39), row(symbol="NOCAT", catalyst_verified=False),
            row(symbol="VIVK", setup_class="squeeze", score=49), row(symbol="MI", setup_class="micro_float_runner"),
            row(symbol="INJ", setup_class="unenriched_inject"), row(symbol="HR", setup_class="high_rvol_runner", score=40)]
    n = ce.promote_catalyst_go(rows, 40)
    by = {r["symbol"]: r for r in rows}
    assert n == 2
    assert by["WFF"]["decision"] == "GO" and by["WFF"]["not_tradeable"] is False and by["WFF"]["catalyst_go_promoted"]
    assert by["HR"]["decision"] == "GO"
    for s in ("LOW", "NOCAT", "VIVK", "MI", "INJ"):
        assert by[s]["decision"] == "MANUAL_REVIEW", s


def test_vix_add_on_raises_the_promotion_bar(monkeypatch):
    import scoring

    monkeypatch.setattr(scoring, "_vix_now", lambda: 28.0)
    assert scoring._effective_go_min({"decision_rules": {"GO": {"min_score": 40}}}) == 45
    monkeypatch.setattr(scoring, "_vix_now", lambda: None)
    assert scoring._effective_go_min({"decision_rules": {"GO": {"min_score": 40}}}) == 40


def test_policy_is_configured_and_wired():
    import yaml

    w = yaml.safe_load((ROOT / "assets/weights.yaml").read_text(encoding="utf-8"))
    assert w["decision_rules"]["GO"]["catalyst_runner_go"] is True
    src = (ROOT / "scripts/scoring.py").read_text(encoding="utf-8")
    assert "promote_catalyst_go(results, _go_min)" in src


class Cur:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.results.pop(0)


def test_shared_feed_adds_screener_and_trade_ai_names():
    import scalp_shadow_logger as L

    u = {"shared_feeds": {"enabled": True, "screener_ids": ["prime_setups"], "screener_max_age_min": 30,
                          "trade_ai_decisions": ["GO", "MANUAL_REVIEW"], "trade_ai_exclude_setup_classes": ["unenriched_inject"]}}
    cur = Cur([[("VIVK",), ("XNDU",)], [("ACB", 64.4, 4.4), ("VIVK", 0.6, 5.5)]])
    rows = L.shared_feed_rows(cur, u, {"XNDU"})
    assert rows == [("VIVK", None, None, "shared:finviz_screener", False), ("ACB", 64.4, 4.4, "shared:trade_ai", False)]
    assert "screener_symbol_membership" in cur.calls[0][0] and "trade_ai_scans" in cur.calls[1][0]
    assert L.shared_feed_rows(Cur([]), {"shared_feeds": {"enabled": False}}, set()) == []


def test_shared_feed_never_raises():
    import scalp_shadow_logger as L

    class Boom:
        connection = None

        def execute(self, *a):
            raise RuntimeError("no table")
    assert L.shared_feed_rows(Boom(), {"shared_feeds": {"enabled": True, "screener_ids": ["x"]}}, set()) == []


def test_cycle_state_round_trip():
    from continuous_runner import CycleState

    st = CycleState()
    st.prev_go = {"WFF"}
    st.prev_score = {"WFF": 44}
    st.haiku_last = {"WFF": datetime(2026, 10, 9, 10, 0)}
    st.cat_fingerprints = {"WFF": {"a", "b"}}
    back = CycleState.from_dict(json.loads(json.dumps(st.to_dict())))
    assert back.prev_go == {"WFF"} and back.prev_score == {"WFF": 44}
    assert back.haiku_last["WFF"] == datetime(2026, 10, 9, 10, 0) and back.cat_fingerprints["WFF"] == {"a", "b"}


def test_scalp_lane_rth_gate_and_daily_state(tmp_path, monkeypatch):
    import run_trade_ai_scalp_live as r

    assert r.in_rth(datetime(2026, 10, 9, 9, 30, tzinfo=ET)) and r.in_rth(datetime(2026, 10, 9, 15, 59, tzinfo=ET))
    assert not r.in_rth(datetime(2026, 10, 9, 9, 29, tzinfo=ET)) and not r.in_rth(datetime(2026, 10, 9, 16, 0, tzinfo=ET))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    from continuous_runner import CycleState

    st = CycleState()
    st.prev_go = {"WFF"}
    r.save_state("2026-10-09", st)
    assert r.load_state("2026-10-09").prev_go == {"WFF"}          # same day: GO memory kept (no re-alert)
    assert r.load_state("2026-10-10").prev_go == set()            # new day: fresh


def test_scalp_lane_runs_one_quiet_cycle(monkeypatch, tmp_path):
    import continuous_runner as cr
    import run_trade_ai_scalp_live as r

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    seen = {}
    monkeypatch.setattr(cr, "run_live_cycle", lambda root, label, day, st, t, **k: seen.update(label=label, **k))
    assert r.main(["--force"]) == 0
    assert seen == {"label": "scalp", "publish_dashboard": False}


def test_live_cycle_publish_flag_guards_dashboard_and_live_state():
    src = (ROOT / "scripts/continuous_runner.py").read_text(encoding="utf-8")
    assert "publish_dashboard: bool = True" in src
    assert "if publish_dashboard:   # the scalp lane's subset" in src
    assert "if not publish_dashboard:\n        return" in src


def test_scalp_window_and_enrichment_without_llm():
    import yaml

    sc = yaml.safe_load((ROOT / "assets/screeners.yaml").read_text(encoding="utf-8"))
    assert set(sc["run_windows"]["scalp"]["active_screeners"]) >= {"prime_setups", "watchlist_setups"}
    orch = (ROOT / "scripts/trade_ai_orchestrator.py").read_text(encoding="utf-8")
    assert 'if use_llm or os.getenv("TRADEAI_ENRICH_WITHOUT_LLM", "1").strip() != "0":' in orch
    cfg = yaml.safe_load((ROOT / "config/scalp_signal_engine.yaml").read_text(encoding="utf-8"))
    assert cfg["universe"]["shared_feeds"]["enabled"] is True


def test_header_counts_the_full_run_and_strip_is_wired():
    api = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    assert '_full_rows = [t for t in _current_run_tickers if str(t.get("run_type") or "").lower() == "full"]' in api
    hub = (ROOT / "apps/command-center-v3/src/pages/TradingHub.tsx").read_text(encoding="utf-8")
    assert "<ActiveTraderFiresStrip tradeAiTickers={tickers} />" in hub
    strip = (ROOT / "apps/command-center-v3/src/components/tradeai/ActiveTraderFiresStrip.tsx").read_text(encoding="utf-8")
    assert "/api/v3/active-trader/alerts" in strip and 'data-testid="at-fires-strip"' in strip


def test_scalp_projection_feeds_active_trader_while_fresh(tmp_path, monkeypatch):
    import run_trade_ai_scalp_live as r
    import scalp_shadow_logger as L

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    n = r.write_projection([{"symbol": "wff", "decision": "GO", "score": 44, "float_m": 12.0, "price": 3.1},
                            {"symbol": "INJ", "decision": "MANUAL_REVIEW", "setup_class": "unenriched_inject"}],
                           datetime.now(ET))
    assert n == 2
    sf = {"scalp_projection_path": str(r.projection_path()), "scalp_projection_max_age_min": 15,
          "trade_ai_exclude_setup_classes": ["unenriched_inject"]}
    assert L.scalp_projection_rows(sf) == [("WFF", 12.0, 3.1, "shared:trade_ai_scalp", False)]
    d = json.loads(r.projection_path().read_text())
    d["as_of"] = "2026-10-09T09:00:00-04:00"                      # stale → ignored
    r.projection_path().write_text(json.dumps(d))
    assert L.scalp_projection_rows(sf) == []
    assert L.scalp_projection_rows({}) == []
