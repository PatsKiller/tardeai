"""Alerts read the Command Center, not their own sources (operator rule 2026-10-05).

  "All of the alerts — the source of truth should be the Command Center for all data. If data needs
   to be refreshed, it's refreshed with the data broker in the Command Center and then spawned out.
   Each individual process should not be going out looking for its own data sources."

The 16:15 material-change digest priced NVDA $233.95 '26h' from watchlist_items while the broker
had $238.98 at 16:00, and printed 'HOLD-OFF (quote is 65.9h old)' next to a 38-minute quote. The
16:20 VCIG entry alert called BUY READY on a strategy card rewritten to the current price
(zone $0.91–$0.91, stop 44 % below, −41.8 % day), unreviewed, in green.

Static guard (ratchet) + behaviour. Fakes only: no DB, no network, no Telegram.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import alert_quotes as aq  # noqa: E402
from lib import alert_source_scan as scan  # noqa: E402
from lib import cio_entry_state as ces  # noqa: E402

# ── static guard: ratchet on producers that call a provider directly ────────────────────────────

#: Producers that still call a market-data provider themselves (2026-10-05 inventory,
#: docs/architecture/ALERT_DATA_SOURCES_2026-10-05.md). This list may only SHRINK: a new producer
#: must read through lib.alert_quotes / lib.data_broker / the CC API; migrating one removes it here.
BYPASS_ALLOWLIST = {
    "scripts/active_trader/momentum_alerts.py": "moomoo L2/tape (no broker projection for L2 yet)",
    "scripts/finviz_ingestion.py": "Finviz ingestion writer (feeds the CC store)",
    "scripts/health_agent.py": "yfinance reachability check",
    "scripts/incubator_proposal_promoter.py": "get_best_quote waterfall",
    "scripts/open_trade_monitor.py": "Alpaca data API",
    "scripts/phase3_lookthrough_fetcher.py": "yfinance holdings look-through",
    "scripts/portfolio_alerts.py": "yfinance",
    "scripts/portfolio_orchestrator.py": "yfinance",
    "scripts/portfolio_technical.py": "Finviz",
    "scripts/portfolio_weekly_report.py": "Finviz",
    "scripts/previously_traded_watchlist.py": "yfinance",
    "scripts/process_watchlist_agent_jobs.py": "yfinance",
    "scripts/pullback_macd_screener.py": "yfinance",
    "scripts/run_proactive_quote_refresh.py": "get_best_quote waterfall (quote refresh job)",
    "scripts/scalp_critic_agent.py": "yfinance",
    "scripts/social_scalp_scanner.py": "Finviz",
    "scripts/technicals_gap_backfill.py": "yfinance backfill",
    "scripts/trade_ai_orchestrator.py": "yfinance",
    "scripts/watchlist_entry_planner.py": "yfinance + Alpaca bars",
}

#: Fixed on 2026-10-05: must stay clean, directly and one import down.
FIXED = ("scripts/notify_material_change.py", "scripts/cio_entry_state_runner.py")


def _direct_bypass() -> dict[str, list[str]]:
    out = {}
    for r in scan.inventory():
        if r["providers"] and r["file"] not in scan.NOT_A_DATA_READ:
            out[r["file"]] = r["providers"]
    return out


def test_no_new_producer_fetches_its_own_data():
    new = {f: p for f, p in _direct_bypass().items() if f not in BYPASS_ALLOWLIST}
    assert not new, ("these alert producers call a provider directly; read through lib.alert_quotes / "
                     f"lib.data_broker / the Command Center API instead: {new}")


def test_allowlist_only_shrinks():
    gone = sorted(set(BYPASS_ALLOWLIST) - set(_direct_bypass()))
    assert not gone, f"migrated off direct providers — remove from BYPASS_ALLOWLIST: {gone}"


def test_fixed_producers_read_the_command_center():
    for f in FIXED:
        text = (ROOT / f).read_text(encoding="utf-8")
        c = scan.classify_text(text)
        assert c["providers"] == [] and c["class"] == "broker", (f, c)
        assert scan.imported_providers(text) == [], (f, scan.imported_providers(text))
    mc = (ROOT / "scripts/notify_material_change.py").read_text(encoding="utf-8")
    assert "SELECT price, change_pct, EXTRACT(EPOCH FROM (now() - last_enriched_at))" not in mc
    runner = (ROOT / "scripts/cio_entry_state_runner.py").read_text(encoding="utf-8")
    assert "FROM watchlist_items WHERE upper(symbol) = ANY(%s) AND price IS NOT NULL" not in runner
    opts = (ROOT / "scripts/lib/buy_ready_options_alternatives.py").read_text(encoding="utf-8")
    assert "schwab_transport.get_option_chain(" not in opts and "cc_option_chain" in opts


# ── broker quotes ───────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 5, 20, 15, tzinfo=timezone.utc)   # 16:15 ET, session closed


def test_freshness_contract_comes_from_the_registry():
    c = aq.freshness_contract()
    assert c == {"open_h": 0.25, "closed_h": 72.0}
    assert aq.stale_after_h(datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc), c) == 0.25   # 11:00 ET
    assert aq.stale_after_h(NOW, c) == 72.0


class _Cur:
    description = None

    def execute(self, *_a, **_k):
        raise AssertionError("broker_quotes must go through the injected price_batch")


def test_broker_quotes_refreshes_only_stale_names_through_the_broker():
    calls = []

    def batch(q, syms, max_age_hours, skip_live):
        calls.append((tuple(syms), skip_live))
        if skip_live:
            return {"NVDA": {"price": 238.98, "chg_pct": 1.2, "as_of": "2026-10-05T20:00:36+00:00", "source": "data_broker.market_quotes:alpaca"},
                    "OLD": {"price": 5.0, "chg_pct": None, "as_of": "2026-09-30T20:00:00+00:00", "source": "x"}}
        return {"OLD": {"price": 5.1, "chg_pct": 0.5, "as_of": "2026-10-05T20:14:00+00:00", "source": "data_broker.market_quote:get_best_quote"}}

    out = aq.broker_quotes(_Cur(), ["nvda", "OLD", "MISSING"], refresh=True, now=NOW, price_batch=batch,
                           contract={"open_h": 0.25, "closed_h": 72.0})
    assert out["NVDA"]["price"] == 238.98 and out["NVDA"]["fresh"] and out["NVDA"]["age_h"] == pytest.approx(0.24, abs=0.01)
    assert out["OLD"]["price"] == 5.1 and out["OLD"]["fresh"]
    assert "MISSING" not in out                       # no guess
    assert calls[0][1] is True and calls[1] == (("MISSING", "OLD"), False)   # refresh = broker waterfall, stale only


# ── material-change digest ──────────────────────────────────────────────────────────────────────

def _mc():
    import notify_material_change as mc
    return mc


def test_stance_never_contradicts_the_quote_shown():
    mc = _mc()
    info = {"price": 189.44, "quote_age_h": 0.6,
            "entry_state": {"state": "BLOCKED", "reasons": ["quote is 64.3h old"], "age_h": 7.2}}
    s = mc.stance_short(info)
    assert "64.3h" not in s and "re-check due" in s and "set 7.2h ago" in s
    info2 = {"price": 169.95, "quote_age_h": 0.6,
             "entry_state": {"state": "BLOCKED", "reasons": ["plan R:R 1.74 is below 2.0"], "age_h": 20 * 24}}
    assert mc.stance_short(info2) == "CIO hold off (plan R:R 1.74 is below 2.0) · set 20.0d ago"


def test_digest_line_is_one_concise_line():
    mc = _mc()
    c = {"symbol": "PLTR", "kind": "news_burst", "magnitude": 22, "change_guid": "g"}
    info = {"price": 189.44, "change_pct": 2.31, "quote_age_h": 0.6,
            "entry_state": {"state": "BLOCKED", "reasons": ["quote is 64.3h old"], "age_h": 7.2}}
    line = mc.digest_line(c, info, {"state": "MOVE", "held": False})
    assert line == ("• PLTR $189.44 (+2.3%) · unusual news volume (22× normal) · "
                    "CIO hold off — re-check due (judged on an older quote) · set 7.2h ago · ▶ watch")
    assert "superseded" not in line and "\n" not in line


def test_digest_caps_each_section_and_the_not_shown_list():
    mc = _mc()
    rows = []
    for i in range(12):
        rows.append(({"symbol": f"S{i}", "kind": "news_burst", "magnitude": i, "change_guid": f"g{i}"},
                     {"price": 10.0, "quote_age_h": 0.2}, {"route": mc.ROUTE_DIGEST, "state": "MOVE", "held": False}))
    for i in range(11):
        rows.append(({"symbol": f"H{i}", "kind": "news_burst", "magnitude": 1, "change_guid": f"h{i}"},
                     {}, {"route": mc.ROUTE_CC, "state": "STALE_QUOTE", "why": "no price"}))
    blocks = mc.digest_blocks(rows, now=NOW)
    text = "\n".join(b["text"] for b in blocks)
    assert text.count("• S") == mc.DIGEST_PER_SECTION and "+4 more in Command Center" in text
    assert "• S11 " in text and "• S0 " not in text           # biggest moves first
    assert "11 names with no live price or no plan" in text and "+3 more" in text
    assert "Finviz" not in text and "Yahoo" not in text


def test_digest_sends_with_no_per_symbol_link_footer(monkeypatch):
    mc = _mc()
    from lib import comms_editor as ce
    seen = []

    def fake_deliver(message, *, subject_key, rich=None):
        seen.append(ce._resolve_primary_symbols(None))
        return True, {}

    monkeypatch.setattr(mc, "deliver_notice", fake_deliver)
    monkeypatch.setattr(mc, "_mark", lambda cur, guids, outcome: len(guids))
    monkeypatch.setattr(mc, "_note", lambda *a, **k: None)

    class Conn:
        def commit(self):
            pass
    entries = [({"symbol": "AXTI", "kind": "news_burst", "magnitude": 4, "change_guid": "g"},
                {"price": 86.62, "quote_age_h": 0.3}, {"route": mc.ROUTE_DIGEST, "state": "MOVE", "held": False})]
    result: dict = {}
    mc.run_digest(None, Conn(), entries, apply=True, result=result)
    assert seen == [[]] and result["rows_produced"] == 1
    assert ce._resolve_primary_symbols(None) in (None, [])     # reset after the send


def test_watch_context_prices_from_the_broker(monkeypatch):
    mc = _mc()
    monkeypatch.setattr(mc, "_broker_quote", lambda cur, sym: {"price": 238.98, "chg_pct": 1.2, "age_h": 0.25,
                                                              "source": "data_broker.market_quotes:alpaca"})
    monkeypatch.setattr(mc, "holding_for", lambda sym: None)

    class Cur:
        connection = None

        def execute(self, sql, params=None):
            assert "last_enriched_at" not in sql, "price must not come from watchlist_items"
            self.r = None

        def fetchone(self):
            return None
    out: dict = {}
    mc._ENRICHMENT = {}
    try:
        mc._watch_context(Cur(), {"symbol": "NVDA"}, out)
    except Exception as exc:  # noqa: BLE001 — later lookups may need real tables; the price must be set first
        assert "price" in out, exc
    assert out["price"] == 238.98 and out["quote_source"].startswith("data_broker.")


# ── CIO entry alert ─────────────────────────────────────────────────────────────────────────────

TODAY = date(2026, 10, 5)


def _vcig(**kw):
    e = {"symbol": "VCIG", "price": 0.91, "quote_age_h": 0.3, "entry_low": 0.91, "entry_high": 0.91,
         "stop": 0.51, "target": 1.88, "plan_source": "strategy_card", "plan_age_h": 0.3,
         "plan_after_move": False, "change_pct": -41.8, "cio_action": None}
    e.update(kw)
    return e


def test_vcig_is_not_buy_ready():
    r = ces.evaluate(_vcig(), today=TODAY)
    assert r["state"] == "BLOCKED"
    text = " | ".join(r["reasons"])
    assert "plan follows the quote" in text and "stop is 44% below entry" in text and "moved -41.8% today" in text


@pytest.mark.parametrize("kw,needle", [
    ({"change_pct": -2.0, "stop": 0.85, "target": 1.2}, "plan follows the quote"),
    ({"entry_low": 0.88, "entry_high": 0.95, "change_pct": 1.0}, "stop is"),
    ({"entry_low": 0.88, "entry_high": 0.95, "stop": 0.84, "target": 1.4, "change_pct": -20.0}, "re-plan"),
    ({"entry_low": 0.88, "entry_high": 0.95, "stop": 0.84, "target": 1.4, "change_pct": 0.5,
      "plan_age_h": 9 * 24}, "plan is 9 days old"),
])
def test_each_plan_sanity_rule(kw, needle):
    r = ces.evaluate(_vcig(**kw), today=TODAY)
    assert r["state"] == "BLOCKED" and any(needle in x for x in r["reasons"]), r["reasons"]


def test_a_real_plan_still_reaches_buy_ready():
    r = ces.evaluate(_vcig(entry_low=0.88, entry_high=0.95, stop=0.84, target=1.4, change_pct=0.5,
                           plan_age_h=5.0), today=TODAY)
    assert r["state"] == "BUY_READY"
    r2 = ces.evaluate(_vcig(entry_low=0.88, entry_high=0.95, stop=0.84, target=1.4, change_pct=-20.0,
                            plan_after_move=True, plan_source="entry_plan"), today=TODAY)
    assert r2["state"] == "BUY_READY"           # re-planned after the move


def test_unreviewed_buy_ready_is_not_green():
    from lib.telegram_rich import cio_entry_alert
    base = {"symbol": "VCIG", "state": "BUY_READY", "cio_stance": "HUMAN REVIEW", "price": 0.91,
            "entry_low": 0.88, "entry_high": 0.95, "stop": 0.84, "target": 1.4, "held": False}
    assert cio_entry_alert(base).marker != "🟢"
    assert cio_entry_alert({**base, "cio_review_id": "rv-1"}).marker == "🟢"


def test_entry_options_chain_comes_from_the_command_center(tmp_path):
    from lib import buy_ready_options_alternatives as bro
    seen = []
    out = bro.live_alternatives({"symbol": "SPCX", "price": 167.0}, held=False, cache_dir=tmp_path,
                                chain_fetcher=lambda sym, n: seen.append((sym, n)) or {"status": "ok", "expirations": []})
    assert seen == [("SPCX", 40)] and "command_center" in str(out.get("chain_source") or out)


def test_hold_off_is_not_a_ticker():
    from lib import comms_editor as ce
    assert "OFF" in ce._AMBIGUOUS_WORDS
