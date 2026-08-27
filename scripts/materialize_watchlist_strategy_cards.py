#!/usr/bin/env python3
"""materialize_watchlist_strategy_cards.py — Build fund-manager-grade strategy cards.

Combines: ticker_prices (DB), enrichment cache, stops, backtest, trade plans, agent results
into a single strategy card per symbol in watchlist_strategy_cards.

Usage:
    python3 scripts/materialize_watchlist_strategy_cards.py [--symbols JEPI SCHD] [--all] [--json]
"""
import json, os, re, sys, math
from datetime import datetime, date, timedelta
from pathlib import Path

import position_truth as pt

# Agent names as written to watchlist_agent_results.agent. Used to detect which
# agent a synthesis conflict refers to, since conflicts are free text naming the
# agent ("Steph narrative assumes..."). Sourced from the live distinct set
# 2026-07-20; a new agent missing here is only ever UNDER-suppressed, so this
# list failing open is visible on the card rather than silent.
KNOWN_AGENTS = frozenset({
    "maria", "steph", "risk_agent", "aegis", "alex", "iris", "tax_agent", "full_chain",
})

# A conflict entry only discards an agent when it says the agent contradicts
# GROUND TRUTH — held shares, position size, portfolio state — not merely that
# agents disagree with each other. Disagreement is the normal, useful case and
# accounts for ~79% of conflict entries; treating it as grounds for suppression
# blanked agent_rec on 1,025 symbols in a first attempt.
GROUND_TRUTH_CONTRADICTION = re.compile(
    r"ground truth"
    r"|contradict"
    r"|portfolio position block"
    r"|zero shares|0 shares|no position|not held"
    r"|misapplied|stale to this symbol"
    r"|hallucinat",
    re.I,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _load(f, default=None):
    p = STATE_DIR / f
    return json.loads(p.read_text()) if p.exists() else (default or {})


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def compute_support_resistance(conn, symbol: str) -> dict:
    """Compute support/resistance from recent price history in ticker_prices."""
    cur = conn.cursor()
    cur.execute("SELECT close_price FROM ticker_prices WHERE symbol=%s AND price_date >= CURRENT_DATE - 60 ORDER BY price_date", (symbol,))
    prices = [float(r[0]) for r in cur.fetchall()]
    cur.close()

    if len(prices) < 10:
        return {"support": None, "resistance": None, "latest": prices[-1] if prices else None}

    latest = prices[-1]
    low_20 = min(prices[-20:]) if len(prices) >= 20 else min(prices)
    high_20 = max(prices[-20:]) if len(prices) >= 20 else max(prices)
    low_50 = min(prices)
    high_50 = max(prices)

    # Support: recent 20-day low, resistance: recent 20-day high
    support = round(low_20, 2)
    resistance = round(high_20, 2)

    return {"support": support, "resistance": resistance, "latest": latest, "low_50": low_50, "high_50": high_50}


def ground_truth_blocks(sym: str, recommendation, holdings: dict) -> tuple:
    """(blocked, reason). Independent backstop to _discarded_agents.

    _discarded_agents only catches a hallucinated disposal rec when the
    SYNTHESIS explicitly describes the contradiction in prose the regex above
    matches — true for the 2026-07-20 BETA case, but not guaranteed on every
    run. This runs position_truth.is_recommendation_admissible against live
    holdings.json directly, so a TRIM/EXIT/SELL-class rec on an unheld symbol
    is blocked deterministically even when the synthesis never mentions it.
    """
    ownership = pt.ownership_from_holdings(sym, holdings)
    admissible, reason = pt.is_recommendation_admissible(
        ownership=ownership, recommendation=recommendation)
    return (not admissible), reason


def materialize(symbols: list[str] | None = None):
    conn = _get_conn()
    cur = conn.cursor()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get target symbols
    if symbols:
        target = symbols
    else:
        cur.execute("SELECT DISTINCT symbol FROM watchlist_items WHERE status <> 'removed'")
        target = [r["symbol"] for r in cur.fetchall()]

    enrichment = _load("ticker_enrichment_cache.json")
    rm = _load("risk_management.json")
    stops_by_sym = {p["symbol"]: p for p in rm.get("positions", []) if p.get("stop_price")}

    # Backtest data
    bt_raw = _load("backtest_summary.json")
    backtests = bt_raw if isinstance(bt_raw, dict) else {}

    # Trade plans
    tp_raw = _load("tos_trade_plans.json")
    trade_plans = {}
    if isinstance(tp_raw, dict):
        for sym, d in tp_raw.items():
            if isinstance(d, dict): trade_plans[sym] = d
    elif isinstance(tp_raw, list):
        for d in tp_raw:
            if isinstance(d, dict) and d.get("symbol"): trade_plans[d["symbol"]] = d

    # ── Agent results — THE SYNTHESIS IS THE AUTHORITY (2026-07-20) ───────────
    #
    # Two defects lived in the one line this replaces.
    #
    # 1. DISTINCT ON ... ORDER BY created_at DESC took whichever agent's job
    #    happened to finish LAST. For BETA that was steph, by 47 seconds over
    #    risk_agent. So `agent_rec` was never an agent view — it was a scheduling
    #    race, and re-running the agents in a different order changes the card.
    #
    # 2. It ignored the synthesis entirely. The CIO explicitly discarded steph's
    #    TRIM on BETA — "Steph narrative assumes existing 17.3% overweight
    #    position and $1.3M holding; directly contradicts PORTFOLIO POSITION
    #    ground truth of 0 shares and $0 value" — and this cron re-stamped that
    #    exact TRIM onto the card 74 minutes AFTER the rejection, then again
    #    every 30 minutes. The card ended up displaying the discarded value
    #    beside its own text saying the value had been discarded.
    #
    # A rejection that a downstream writer overwrites on a schedule is worse
    # than the original bad output: the correction can never hold. Operator
    # decision 2026-07-20: the synthesis wins.
    #
    # So: agents named as conflicted by the synthesis are excluded, and the most
    # recent SURVIVING agent result is used. Provenance is recorded because
    # "which agent said this" was never visible and the race above is only
    # findable if it is.
    cur.execute("""SELECT UPPER(symbol) AS symbol, recommendation, conflicts
                   FROM watchlist_final_synthesis""")
    _synth = {r["symbol"]: r for r in cur.fetchall()}

    def _discarded_agents(sym: str) -> set:
        """Agents the synthesis says contradict GROUND TRUTH, lowercased.

        The narrowness here is the whole point. A first attempt suppressed any
        agent merely NAMED in a conflict, which blanked agent_rec on 1,025
        symbols — because most conflicts are ordinary disagreement that names
        everyone ("Maria BUY vs Steph AVOID"). Measured on a 400-symbol sample:
        only ~21% assert a ground-truth contradiction at all. Agent disagreement
        is what the synthesis is FOR; resolving it is not the same as declaring
        a participant wrong, and suppressing debate would hide the disagreement
        signal the desk depends on.

        So two conditions must hold IN THE SAME conflict entry:
          1. the entry asserts a contradiction with ground truth / position data
          2. that entry names the agent

        Per-entry matching matters: joining the entries first would let a
        ground-truth marker in one entry suppress an agent named only in
        another. That is how the BETA case ("Steph narrative assumes existing
        17.3% overweight position ... directly contradicts PORTFOLIO POSITION
        ground truth of 0 shares") stays caught while "Maria BUY vs Steph AVOID"
        correctly does not.
        """
        row = _synth.get(sym.upper()) or {}
        conflicts = row.get("conflicts")
        if not conflicts:
            return set()
        entries = conflicts if isinstance(conflicts, (list, tuple)) else [conflicts]
        out = set()
        for entry in entries:
            text = str(entry).lower()
            if not GROUND_TRUTH_CONTRADICTION.search(text):
                continue          # ordinary disagreement — the synthesis resolves it
            out |= {a for a in KNOWN_AGENTS if a in text}
        return out

    cur.execute("""SELECT UPPER(symbol) AS symbol, agent, recommendation, confidence,
                          summary, created_at
                   FROM watchlist_agent_results
                   WHERE status = 'completed' AND recommendation IS NOT NULL
                   ORDER BY symbol, created_at DESC""")
    agent_results, _suppressed, _seen = {}, {}, set()
    for r in cur.fetchall():
        sym = r["symbol"]
        if sym in agent_results:
            continue                      # newest surviving wins
        agent = str(r.get("agent") or "").lower()
        if agent in _discarded_agents(sym):
            # Record ONCE per agent, not once per historical row. A first cut
            # appended every row and produced 53 entries for a single symbol,
            # because a fully-suppressed symbol never short-circuits the loop.
            key = (sym, agent)
            if key not in _seen:
                _seen.add(key)
                _suppressed.setdefault(sym, []).append(f"{agent}:{r.get('recommendation')}")
            continue                      # the synthesis discarded this one
        agent_results[sym] = r

    # ── Ground-truth gate (Stage A backstop, 2026-08-27) ──────────────────────
    # Runs regardless of whether the synthesis above caught anything: a
    # deterministic check against live holdings, independent of prose. See
    # ground_truth_blocks() and docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md
    # (Fix C2).
    holdings = _load("holdings.json")
    for sym, r in list(agent_results.items()):
        blocked, reason = ground_truth_blocks(sym, r.get("recommendation"), holdings)
        if not blocked:
            continue
        agent = str(r.get("agent") or "").lower()
        key = (sym, agent)
        if key not in _seen:
            _seen.add(key)
            _suppressed.setdefault(sym, []).append(
                f"{agent}:{r.get('recommendation')} [GROUND_TRUTH_GATE: {reason}]")
        del agent_results[sym]

    if _suppressed:
        print(f"  suppressed {sum(len(v) for v in _suppressed.values())} synthesis-discarded "
              f"agent rec(s) across {len(_suppressed)} symbol(s)")

    results = []
    for sym in target:
        e = enrichment.get(sym, {}) if isinstance(enrichment.get(sym), dict) else {}
        stop_data = stops_by_sym.get(sym, {})
        bt = backtests.get(sym, {}) if isinstance(backtests.get(sym), dict) else {}
        tp = trade_plans.get(sym, {})
        ar = agent_results.get(sym, {})

        # Price/support/resistance from DB
        sr = compute_support_resistance(conn, sym)
        latest_price = sr.get("latest")

        # If no DB price, try enrichment
        if not latest_price:
            latest_price = e.get("price")

        support = sr.get("support")
        resistance = sr.get("resistance")

        # Fallback: estimate support/resistance from enrichment 52-week range
        if not support and latest_price:
            w52_low_pct = e.get("week52_low_pct")  # % above 52-week low
            if w52_low_pct is not None:
                w52_low = latest_price / (1 + float(w52_low_pct) / 100)
                support = round(w52_low * 1.02, 2)  # slightly above 52-week low
        if not resistance and latest_price:
            w52_high_pct = e.get("week52_high_pct")  # % below 52-week high (negative)
            if w52_high_pct is not None:
                w52_high = latest_price / (1 + float(w52_high_pct) / 100)
                resistance = round(w52_high * 0.98, 2)  # slightly below 52-week high

        # Technical
        rsi = e.get("rsi")
        sma20 = e.get("sma20_pct")
        sma50 = e.get("sma50_pct")
        sma200 = e.get("sma200_pct")
        atr = e.get("atr")
        beta = e.get("beta")

        # Strategy type — from DB classification (no hard-coded ticker logic)
        sector = e.get("sector", "")
        company = str(e.get("company", ""))
        div_yield = e.get("dividend_yield_pct") or e.get("yield_pct")

        # Look up classification from DB
        cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE", (sym,))
        db_class = cur.fetchone()

        if db_class:
            # Map DB strategy_type to the simpler categories used by strategy_cards
            _type_map = {
                "dividend_growth_compounder": "income", "covered_call_income": "income",
                "high_yield_income_bdc": "income", "bond_income": "income",
                "reit_income": "income", "international_dividend": "income",
                "core_growth_compounder": "growth_etf", "core_index": "growth_etf",
                "defense_thesis": "defense_thesis",
                "speculative_growth": "speculative_growth",
                "swing_trade": "speculative_growth",
            }
            strategy_type = _type_map.get(db_class["strategy_type"], "core_holding")
        else:
            # No DB classification — mark as unclassified, do not infer
            strategy_type = "core_holding"
            print(f"  [strategy-cards] WARNING: {sym} has no DB classification — using default core_holding")

        # Compute entry/stop/target
        stop_loss = stop_data.get("stop_price")
        if not stop_loss and support and atr:
            stop_loss = round(support - float(atr), 2)
        elif not stop_loss and support:
            stop_loss = round(support * 0.97, 2)  # 3% below support

        ideal_entry = None
        if support and latest_price:
            if strategy_type == "income":
                ideal_entry = round(min(support * 1.02, latest_price * 0.98), 2)
            else:
                ideal_entry = round(support * 1.01, 2)

        target_price = None
        if resistance:
            target_price = round(resistance * 1.02, 2)

        risk_reward = None
        if ideal_entry and stop_loss and target_price and ideal_entry > stop_loss:
            reward = target_price - ideal_entry
            risk = ideal_entry - stop_loss
            risk_reward = round(reward / risk, 2) if risk > 0 else None

        # Account fit
        account_fit = "taxable"
        if strategy_type == "income":
            account_fit = "IRA (tax-deferred income)"
        elif strategy_type == "speculative_growth":
            account_fit = "Roth (tax-free growth)"

        # Thesis
        thesis = tp.get("thesis") or ar.get("summary") or f"{sym} — {strategy_type.replace('_', ' ')}"
        confidence = ar.get("confidence") or bt.get("backtest_score", 0) / 100 if bt.get("backtest_score") else 0.5
        needs_iter = not latest_price or not support or not ar.get("recommendation")

        tech_summary = f"RSI {rsi:.0f}" if rsi else ""
        if sma200 is not None: tech_summary += f" · SMA200 {sma200:+.1f}%"
        if atr: tech_summary += f" · ATR {atr:.2f}"
        if not tech_summary: tech_summary = "No technical data"

        # Upsert
        cur.execute("""
            INSERT INTO watchlist_strategy_cards (symbol, strategy_type, latest_price, support, resistance,
                ideal_entry, add_zone_low, add_zone_high, stop_loss, target_price, risk_reward,
                time_horizon, position_size_note, account_fit, thesis, catalyst_summary,
                technical_summary, risk_summary, confidence, needs_iteration, card, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT (symbol) DO UPDATE SET
                strategy_type=EXCLUDED.strategy_type, latest_price=EXCLUDED.latest_price,
                support=EXCLUDED.support, resistance=EXCLUDED.resistance,
                ideal_entry=EXCLUDED.ideal_entry, stop_loss=EXCLUDED.stop_loss,
                target_price=EXCLUDED.target_price, risk_reward=EXCLUDED.risk_reward,
                time_horizon=EXCLUDED.time_horizon, account_fit=EXCLUDED.account_fit,
                thesis=EXCLUDED.thesis, technical_summary=EXCLUDED.technical_summary,
                confidence=EXCLUDED.confidence, needs_iteration=EXCLUDED.needs_iteration,
                card=EXCLUDED.card, updated_at=now()
        """, (sym, strategy_type, latest_price, support, resistance,
              ideal_entry, support if support else None, resistance if resistance else None,
              stop_loss, target_price, risk_reward,
              "medium_term", "Standard position sizing", account_fit,
              thesis[:500] if thesis else None, None,
              tech_summary, None, confidence, needs_iter,
              json.dumps({"enrichment": {k: e.get(k) for k in ["rsi", "sma20_pct", "sma50_pct", "sma200_pct", "atr", "beta", "sector", "industry"]},
                          "backtest": bt, "trade_plan": tp, "agent_rec": ar.get("recommendation"),
                          # Provenance: which agent this came from, and what the
                          # synthesis suppressed. Without the first, "whichever job
                          # finished last" is invisible; without the second, a
                          # suppressed rec looks like it was never produced.
                          "agent_rec_agent": ar.get("agent"),
                          "agent_rec_suppressed": _suppressed.get(sym.upper()) or None,
                          "agent_rec_authority": "synthesis"})))

        results.append({"symbol": sym, "strategy_type": strategy_type, "latest_price": latest_price,
                        "support": support, "resistance": resistance, "stop_loss": stop_loss,
                        "target_price": target_price, "risk_reward": risk_reward, "needs_iteration": needs_iter})

    conn.commit()
    conn.close()
    print(f"[strategy-cards] Materialized {len(results)} cards")
    return results


if __name__ == "__main__":
    syms = None
    if "--symbols" in sys.argv:
        idx = sys.argv.index("--symbols")
        syms = [s.upper() for s in sys.argv[idx + 1:] if not s.startswith("-")]
    elif "--all" not in sys.argv:
        syms = None  # default: all active watchlist items

    results = materialize(syms)
    if "--json" in sys.argv:
        print(json.dumps(results, indent=2, default=str))
    else:
        for r in results[:10]:
            print(f"  {r['symbol']:>6} {r['strategy_type']:>16} price=${r['latest_price'] or '?':>8} sup=${r['support'] or '?':>8} res=${r['resistance'] or '?':>8} stop=${r['stop_loss'] or '?':>8} rr={r['risk_reward'] or '?'}")
