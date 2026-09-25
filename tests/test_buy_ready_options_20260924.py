"""BUY_READY institutional packet — options alternatives, portfolio facts, CIO review.

M5 2026-09-24 (operator: "build options"). The V BUY_READY page (10:20 ET) had
no options alternative (the engine skipped held names, never built debit
verticals, capped LEAPS at 60 DTE, and the packet borrowed a wrong-class covered
call's structure), no portfolio context (``ATTACH_WHEN_AVAILABLE``), a dollar
"capital hint" the MBI_BEHAVIOR=0 rail forbids, and nothing answered "Confirm or
refute" (the wake carried ``symbol`` where the reactive cycle reads ``symbols``).

No broker, DB or LLM calls: the chain is synthetic (Black-Scholes priced), the
liquidity/earnings gates and the model are injected, and the review response is
recorded.
"""
from __future__ import annotations

import json
import math
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import buy_ready_cio_review as rv  # noqa: E402
from lib import buy_ready_options_alternatives as boa  # noqa: E402
from lib import buy_ready_portfolio_facts as bpf  # noqa: E402
from lib import cio_options_fluency as fl  # noqa: E402

BEHAVIOR_FIELDS = ("recommended_delta_usd", "size_usd", "shares", "qty", "order",
                   "stop", "limit", "target_weight_pct", "trade", "execution")
V_PLAN = {"symbol": "V", "price": 367.53, "entry_low": 364.50, "entry_high": 369.00,
          "stop": 357.50, "target": 410.00}
V_RESULT = {**V_PLAN, "state": "BUY_READY", "rr": 3.57, "plan_source": "reentry_desk",
            "distance_pct": 0.0, "held": True, "market_cap_label": "MEGA", "atr": 5.2}
NOW = datetime(2026, 9, 24, 14, 20, tzinfo=timezone.utc)


# ── synthetic chain ──────────────────────────────────────────────────────────

def _bs(spot, k, iv, dte, right, r=0.04):
    t = dte / 365.0
    d1 = (math.log(spot / k) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    if right == "call":
        return spot * n(d1) - k * math.exp(-r * t) * n(d2), n(d1)
    return k * math.exp(-r * t) * n(-d2) - spot * n(-d1), n(d1) - 1


def v_chain(spot=367.53, iv=0.22, dtes=(30, 57, 85, 113, 302, 484)):
    exps = []
    for dte in dtes:
        rows = []
        for k in list(range(250, 300, 10)) + list(range(300, 435, 5)):
            for right in ("call", "put"):
                px, delta = _bs(spot, float(k), iv, dte, right)
                px = max(px, 0.05)
                half = max(0.05, px * 0.01)
                rows.append({"exp": f"D{dte}", "strike": float(k), "side": right, "bid": round(px - half, 2),
                             "ask": round(px + half, 2), "last": round(px, 2), "iv": iv * 100,
                             "delta": round(delta, 3), "oi": 900, "volume": 120, "dte": dte})
        exps.append({"exp": f"D{dte}", "dte": dte, "strikes": rows})
    return {"status": "ok", "symbol": "V", "underlying_price": spot, "expirations": exps}


def _liq_ok(c):
    bid, ask = float(c.get("bid") or 0), float(c.get("ask") or 0)
    mid = (bid + ask) / 2 if ask else 0
    return {"pass": True, "bid_ask_spread_pct": round(100 * (ask - bid) / mid, 2) if mid else None, "issues": []}


def _no_earnings(sym, *, dte, strategy):
    return {"in_blackout": False, "symbol": sym, "strategy": strategy}


def v_alternatives(held=True, **kw):
    out = boa.build_alternatives(V_PLAN, v_chain(), held=held, liquidity_fn=_liq_ok, blackout_fn=_no_earnings,
                                 chain_source="fixture", chain_as_of="2026-09-24T14:20:00+00:00", **kw)
    out["iv_context"] = boa.iv_context(22.0, [20.0, 21.5, 23.0], proxy_rank=24.5)
    return out


# ── portfolio fixture ────────────────────────────────────────────────────────

@pytest.fixture
def book(tmp_path):
    holdings = {"as_of": "2026-09-24", "holdings": [
        {"symbol": "V", "account": "schwab_roth", "shares": 130.2689, "market_value": 47936.35},
        {"symbol": "V", "account": "schwab_rollover_ira", "shares": 0.7963, "market_value": 293.02},
        {"symbol": "MCD", "account": "schwab_rollover_ira", "shares": 300, "market_value": 114271.63},
        {"symbol": "CASH", "account": "schwab_taxable", "is_cash": True, "market_value": 1099039.0},
    ]}
    corr = {"symbols_analyzed": ["MCD", "V", "WMT"], "total_value": 278905.0, "last_updated": "2026-09-24 07:41",
            "sector_exposure": {"Other": 82.8, "Financials": 17.2},
            "correlation_matrix": {"V": {"MCD": 0.379, "V": 1.0, "WMT": 0.21}}}
    ips = {"constraints": {"max_single_position_pct": 8.0, "max_sector_concentration_pct": 25.0}}
    mon = {"monitored_at": "2026-09-24T19:40:00Z", "book_greeks": {"leg_count": 0, "net_delta_shares": 0.0,
                                                                 "net_delta_notional": 0.0, "by_underlying": {}}}
    paths = {}
    for name, obj in (("holdings", holdings), ("correlation", corr), ("ips", ips), ("options_monitor", mon)):
        f = tmp_path / f"{name}.json"
        f.write_text(json.dumps(obj))
        paths[name] = f
    return paths


def v_packet(book, review=None, alternatives=None):
    port = bpf.build_portfolio_facts("V", paths=book)
    return fl.build_buy_ready_packet(
        V_RESULT, {"held": True, "plan_source": "reentry_desk"}, desk={"by_symbol": {}}, goals=[],
        enrichment={"sector": "Financial Services", "pe": 32.1},
        alternatives=alternatives if alternatives is not None else v_alternatives(), portfolio=port,
        cio_review=review)


RECORDED_REVIEW = {
    "verdict": "MODIFY",
    "reason": "Setup valid at 367.53 but this is an ADD to a held name at 29.68% of invested capital.",
    "scores": {k: {"score": 6, "evidence": "from supplied facts"} for k in rv.SCORE_KEYS},
    "equity_view": "Stop 357.5 sits inside normal range; worst-case R:R 3.57, 4.23 at the quote.",
    "options_view": "Prefer the debit call vertical: capped at the 410 target, lower capital per contract.",
    "portfolio_view": "Held 131.07 shares already; 3.82% of book vs the 8% IPS limit, 29.68% of invested.",
    "modifications": ["wait for the zone low 364.5", "prefer the debit call vertical over stock"],
    "unknowns": ["IV percentile unavailable (3 history rows)"],
}


# ── 1. wake subject binding ──────────────────────────────────────────────────

def test_wake_symbols_accepts_plural_and_the_singular_the_runner_used_to_send():
    import cio_reactive_cycle as rc
    assert rc.wake_symbols({"symbols": ["V"]}) == ["V"]
    assert rc.wake_symbols({"symbol": "V"}) == ["V"]  # the 09-24 V wake shape
    assert rc.wake_symbols({"symbols": [], "symbol": None}) == []
    assert rc.wake_symbols(None) == []


def test_runner_emits_symbols_plural_on_the_bus(monkeypatch):
    import cio_entry_state_runner as runner
    emitted = {}

    class Bus:
        def emit(self, et, payload, **kw):
            emitted.update(payload)

    monkeypatch.setitem(sys.modules, "scripts.lib.cio_event_bus", types.SimpleNamespace(CIOEventBus=Bus))
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_telegram_transport",
                        types.SimpleNamespace(send_cio_message=lambda *a, **k: {"delivered": True}))
    monkeypatch.setattr(runner, "operator_send", lambda *a, **k: {"operator": True})
    monkeypatch.setattr(runner, "stamp_cio_stance", lambda text, syms, only_conflicts=False: text)
    monkeypatch.setattr(runner.ces, "render_operator", lambda r, e: "page")
    monkeypatch.setattr(runner.ces, "render_cio", lambda r, e: "cio")
    runner.send_alerts({**V_RESULT, "market_cap_label": "MEGA"}, {})
    assert emitted["symbols"] == ["V"] and emitted["symbol"] == "V"


# ── 2. directional alternatives ──────────────────────────────────────────────

def test_a_held_name_gets_directional_alternatives_and_no_csp():
    out = v_alternatives(held=True)
    strategies = [a["strategy"] for a in out["alternatives"]]
    assert {"long_call", "debit_call_vertical", "leaps_call"} <= set(strategies)
    assert "cash_secured_put" not in strategies
    assert any(s["strategy"] == "cash_secured_put" and s["reason"].startswith("HELD_NAME") for s in out["skipped"])
    assert out["status"] == "OK"
    assert [a["rank"] for a in out["alternatives"]] == list(range(1, len(strategies) + 1))
    for a in out["alternatives"]:
        assert a["why_this_strike"] and a["why_this_expiry"]
        assert isinstance(a["neighbours_rejected"], list)
    assert any(a["neighbours_rejected"] for a in out["alternatives"])


def test_a_new_name_also_gets_a_cash_secured_put_below_the_zone():
    out = v_alternatives(held=False)
    csp = next(a for a in out["alternatives"] if a["strategy"] == "cash_secured_put")
    assert csp["legs"][0]["strike"] <= V_PLAN["entry_low"]
    assert 30 <= csp["legs"][0]["dte"] <= 60


def test_long_call_is_inside_its_delta_and_dte_bands():
    lc = next(a for a in v_alternatives()["alternatives"] if a["strategy"] == "long_call")
    leg = lc["legs"][0]
    assert 0.60 <= leg["delta"] <= 0.70 and 45 <= leg["dte"] <= 120


def test_debit_vertical_short_leg_is_the_strike_nearest_the_plan_target():
    dv = next(a for a in v_alternatives()["alternatives"] if a["strategy"] == "debit_call_vertical")
    long_leg, short_leg = dv["legs"]
    assert short_leg["strike"] == 410.0 and long_leg["strike"] < short_leg["strike"]
    pc = dv["per_contract"]
    assert pc["max_loss"] == pc["capital"] and pc["max_gain"] > 0
    assert pc["breakeven"] == pytest.approx(long_leg["strike"] + pc["capital"] / 100, abs=0.01)


def test_leaps_are_generated_past_the_engines_60_day_cap():
    lp = next(a for a in v_alternatives()["alternatives"] if a["strategy"] == "leaps_call")
    leg = lp["legs"][0]
    assert 270 <= leg["dte"] <= 540 and leg["delta"] >= 0.75
    import options_engine
    assert options_engine.MAX_DTE == 60  # the engine's own cap is untouched


def test_illiquid_contracts_are_disqualified_not_ranked_first():
    out = boa.build_alternatives(V_PLAN, v_chain(), held=True,
                                 liquidity_fn=lambda c: {"pass": False, "issues": ["OI 3 < 50"]},
                                 blackout_fn=_no_earnings)
    assert out["status"] == "NONE_QUALIFIED"
    assert all(not a["qualified"] and a["disqualified_by"][0].startswith("LIQUIDITY") for a in out["alternatives"])


def test_an_earnings_blackout_disqualifies_the_structure():
    out = boa.build_alternatives(V_PLAN, v_chain(), held=True, liquidity_fn=_liq_ok,
                                 blackout_fn=lambda s, dte, strategy: {"in_blackout": True, "reason": "earnings 10-28"})
    assert all("EARNINGS_BLACKOUT" in " ".join(a["disqualified_by"]) for a in out["alternatives"])


def test_a_breakeven_above_the_target_is_disqualified():
    plan = {**V_PLAN, "target": 372.0}
    out = boa.build_alternatives(plan, v_chain(), held=True, liquidity_fn=_liq_ok, blackout_fn=_no_earnings)
    lc = next(a for a in out["alternatives"] if a["strategy"] == "long_call")
    assert any(d.startswith("BREAKEVEN_AT_OR_ABOVE_TARGET") for d in lc["disqualified_by"])


def test_no_chain_is_reported_not_invented():
    out = boa.build_alternatives(V_PLAN, {"status": "error", "error": "token expired"}, held=True)
    assert out["status"] == "NO_CHAIN" and out["alternatives"] == []
    assert out["stock_per_share"]["max_loss_to_plan_stop"] == pytest.approx(10.03, abs=0.01)


def test_iv_context_labels_a_proxy_and_needs_history_for_percentile():
    thin = boa.iv_context(22.0, [20.0, 21.0, 23.0], proxy_rank=24.5)
    assert thin["iv_rank_source"] == "proxy" and thin["iv_percentile"] is None and thin["history_rows"] == 3
    full = boa.iv_context(22.0, [18.0 + 0.2 * i for i in range(30)])
    assert full["iv_rank_source"] == "history" and full["iv_percentile"] is not None


# ── 3. packet: no borrowed structure, per-unit only, no sizing ───────────────

def test_the_packet_never_borrows_a_wrong_class_covered_calls_structure(book):
    desk = {"by_symbol": {"V": [{"strategy": "covered_call", "strike": 390, "iv_rank": 24.5, "dte": 29}]}}
    port = bpf.build_portfolio_facts("V", paths=book)
    pkt = fl.build_buy_ready_packet(V_RESULT, {"held": True}, desk=desk, goals=[], enrichment={},
                                    alternatives=None, portfolio=port)
    assert pkt["options_alt"]["reason"] == "WRONG_STRATEGY_CLASS"
    assert pkt["structure_indicators"]["iv_rank"] is None
    assert pkt["structure_indicators"]["dte"] is None


def _walk_keys(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + (k,)
            yield from _walk_keys(v, path + (k,))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v, path)


def test_the_packet_carries_no_sizing_keys_and_no_dollar_capital_hint(book):
    pkt = v_packet(book, review={"status": "OK", "agent": "alex", "review": RECORDED_REVIEW})
    offenders = [p for p in _walk_keys(pkt) if p[-1] in BEHAVIOR_FIELDS
                 # the plan's own price level, not an instruction: equity.stop
                 and p not in (("equity", "stop"),)]
    assert offenders == []
    blob = json.dumps(pkt, default=str)
    for banned in ("illustrative_100_shares", "shares_hint", "contracts_hint", "size_basis"):
        assert banned not in blob
    text = "\n".join(fl.format_buy_ready_packet_lines(pkt, for_cio=False))
    assert "capital hint" not in text.lower()
    assert "Per unit — stock:" in text and "/contract" in text


def test_portfolio_facts_flag_an_add_and_label_the_correlation_subset(book):
    port = bpf.build_portfolio_facts("V", paths=book)
    assert port["held"] and port["held_units_total"] == pytest.approx(131.0652, abs=1e-3)
    assert port["pct_of_total_book"] == pytest.approx(3.82, abs=0.01)
    assert port["pct_of_invested_capital"] == pytest.approx(29.68, abs=0.01)
    assert "ADD_RAISES_CONCENTRATION" in port["flags"]
    assert "ABOVE_IPS_SINGLE_NAME_LIMIT_OF_INVESTED_CAPITAL" in port["flags"]
    assert "AT_OR_ABOVE_IPS_SINGLE_NAME_LIMIT" not in port["flags"]  # 3.82% < 8% of the whole book
    assert port["correlations"]["coverage"].startswith("subset: 3 symbols")
    assert port["options_book"]["leg_count"] == 0
    assert "UNVERIFIED" in port["cash_state"]


def test_the_house_verdict_names_the_add_and_the_book_share(book):
    pkt = v_packet(book)
    assert "ADD to an existing position" in pkt["cio_verdict"]["rationale"]
    assert "3.8% of book" in pkt["cio_verdict"]["rationale"]


# ── 4. CIO review: prompt, validation, modes ─────────────────────────────────

def test_the_review_prompt_is_the_plan_prompt_verbatim_plus_supplied_facts(book):
    facts = rv.build_facts(v_packet(book))
    prompt = rv.render_prompt(facts)
    assert prompt.startswith("ROLE: You are the Trade-AI CIO reviewing ONE BUY_READY entry packet for V.")
    assert "You NEVER size, order," in prompt and "SUPPLIED FACTS:" in prompt
    assert facts["portfolio"]["concentration_limit_pct"] == 8.0
    assert facts["options_alternatives"] and facts["options_alternatives"][0]["why_this_strike"]


def test_dry_mode_makes_no_model_call(book):
    def boom(_prompt):
        raise AssertionError("model called in dry mode")
    out = rv.review_packet(v_packet(book), llm_fn=boom, review_mode="dry", now=NOW)
    assert out["status"] == "DRY_RUN" and out["facts"]["symbol"] == "V"


def test_a_recorded_valid_review_passes(book):
    out = rv.review_packet(v_packet(book), llm_fn=lambda p: {"response": json.dumps(RECORDED_REVIEW),
                                                             "model_used": "fixture"},
                           review_mode="live", now=NOW)
    assert out["status"] == "OK", out.get("errors")
    row = rv.decision_row(out, now=NOW)
    assert row[0] == "cio-entry-review-v-20260924142000" and row[2] == "MODIFY"
    assert "'entry_review'" in rv.INSERT_SQL


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r.update(verdict="BUY"), "verdict must be"),
    (lambda r: r["scores"].pop("edge"), "score edge"),
    (lambda r: r.update(qty=100), "sizing/behaviour keys"),
    (lambda r: r.update(options_view="Buy 100 shares now and 2 contracts."), "sizing/quantity language"),
    (lambda r: r.update(equity_view="Upside to 455.25 by year end."), "not traceable"),
])
def test_invalid_reviews_are_refused(book, mutate, needle):
    bad = json.loads(json.dumps(RECORDED_REVIEW))
    mutate(bad)
    out = rv.review_packet(v_packet(book), llm_fn=lambda p: {"response": json.dumps(bad)},
                           review_mode="live", now=NOW)
    assert out["status"] == "INVALID"
    assert any(needle in e for e in out["errors"]), out["errors"]


def test_a_slow_model_leaves_the_review_pending(book):
    import time
    out = rv.review_packet(v_packet(book), llm_fn=lambda p: time.sleep(2) or {"response": "{}"},
                           review_mode="live", timeout_s=0.2, now=NOW)
    assert out["status"] == "PENDING"


# ── 5. renders (golden) and the runner's dry path ────────────────────────────

GOLDEN = ROOT / "tests" / "fixtures" / "buy_ready_v_golden_20260924.txt"


def _golden_render(book):
    from lib import cio_entry_state as ces
    port = bpf.build_portfolio_facts("V", paths=book)
    ev = {"held": True, "plan_source": "reentry_desk", "market_cap_label": {"code": "MEGA", "text": "Mega cap · $675.0B"},
          "options_alternatives": v_alternatives(), "portfolio_facts": port,
          "cio_review": {"status": "OK", "agent": "alex", "review": RECORDED_REVIEW}}
    import contextlib
    import importlib
    import unittest.mock as um
    # cio_entry_state imports scripts.lib.cio_options_fluency; tests import lib.… —
    # two module objects, so pin the house-file loaders on both.
    mods = [fl, importlib.import_module("scripts.lib.cio_options_fluency")]
    with contextlib.ExitStack() as stack:
        for m in mods:
            stack.enter_context(um.patch.object(m, "load_enrichment_row",
                                                lambda s: {"sector": "Financial Services", "pe": 32.1}))
            stack.enter_context(um.patch.object(m, "load_options_desk_summary", lambda path=None: {"by_symbol": {}}))
            stack.enter_context(um.patch.object(m, "load_cio_goals", lambda path=None: []))
        page = ces.render_operator(V_RESULT, ev)
        cio = ces.render_cio(V_RESULT, ev)
    return "=== operator page ===\n" + page + "\n=== CIO desk ===\n" + cio + "\n"


def test_golden_v_page_and_cio_message(book):
    text = _golden_render(book)
    assert "Advisory only. No order is created; you choose and execute through your broker (2FA)." in text
    assert "Options alternatives (per contract, ranked):" in text
    assert "CIO review (alex): MODIFY" in text
    assert "Book: already held" in text
    assert GOLDEN.read_text(encoding="utf-8") == text


def test_runner_dry_path_builds_the_packet_without_a_model_or_broker_call(book, monkeypatch):
    import cio_entry_state_runner as runner
    from lib import buy_ready_options_alternatives as live
    monkeypatch.setattr(live, "live_alternatives", lambda plan, held, proxy_iv_rank=None: v_alternatives(held=held))
    monkeypatch.setattr(bpf, "build_portfolio_facts", lambda sym: {"status": "OK", "held": True, "flags": []})
    monkeypatch.setattr(rv, "_default_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))
    ev = {}
    review = runner.prepare_packet_inputs(V_RESULT, ev, apply=False)
    assert review["status"] == "DRY_RUN"
    assert ev["options_alternatives"]["status"] == "OK"


def test_expired_pending_reviews_are_dropped_not_retried(tmp_path, monkeypatch):
    import cio_entry_state_runner as runner
    ledger = tmp_path / "pending.jsonl"
    ledger.write_text(json.dumps({"symbol": "V", "state": "BUY_READY", "queued_at": "2026-09-24T10:00:00+00:00",
                                  "result": V_RESULT, "status": "PENDING"}) + "\n")
    monkeypatch.setattr(runner, "REVIEW_PENDING", ledger)
    monkeypatch.setattr(runner, "prepare_packet_inputs",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("retried an expired review")))
    out = runner.follow_up_pending_reviews(cur=None, evidence={})
    assert out == [{"symbol": "V", "follow_up": "expired"}]
    assert ledger.read_text() == ""


def test_a_liquid_neighbour_beats_a_closer_but_illiquid_strike():
    """Live V 2026-09-24: the 410 short leg had a 29% spread and the chosen LEAPS strike
    0 OI; the picker must take the nearest strike that passes the liquidity gate."""
    def liq(c):
        bad = (c.get("right") == "call" and float(c.get("strike")) == 410.0)
        return {"pass": not bad, "bid_ask_spread_pct": 29.2 if bad else 1.0,
                "issues": ["spread 29.2% > 12.0%"] if bad else []}
    out = boa.build_alternatives(V_PLAN, v_chain(), held=True, liquidity_fn=liq, blackout_fn=_no_earnings)
    dv = next(a for a in out["alternatives"] if a["strategy"] == "debit_call_vertical")
    assert dv["legs"][1]["strike"] in (405.0, 415.0) and dv["qualified"]
