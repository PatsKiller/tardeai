"""portfolio_orchestrator.py — Trade AI v12 Portfolio Intelligence v1.2
Full pipeline: load → analyze → tax → rebalance → risk → charts → performance → AI → dashboard → report

Run modes:
  --run-type daily    : fast run, Haiku AI only, cached monthly analysis (DEFAULT)
  --run-type monthly  : full Sonnet AI analysis refresh (run 1st of each month)
  --run-type manual   : same as monthly, explicit trigger
"""
from __future__ import annotations
import argparse, json, sys, shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

def run_portfolio_pipeline(project_root, run_label="manual", generate_report=True, run_type="daily"):
    root = Path(project_root)
    date_str  = datetime.now().strftime("%Y-%m-%d")
    now_str   = datetime.now().strftime("%H:%M ET")
    state_dir = root/"data"/"portfolios"/"state"
    report_dir= root/"data"/"portfolios"/"reports"
    charts_dir= root/"data"/"portfolios"/"charts"
    for d in [report_dir, charts_dir, state_dir]: d.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root/"scripts"))

    from morning_command_digest import bundle_enabled, append_section, send_morning_command_bundle, fetch_hermes_movers
    _morning_bundle: Dict[str, str] | None = {} if bundle_enabled(run_type) else None
    if _morning_bundle is not None:
        print("  [morning-command] Daily bundle mode — deferring morning Telegram sections")

    # Load .env so API key is available throughout the pipeline
    import os
    if not os.getenv("ANTHROPIC_API_KEY",""):
        try:
            from dotenv import load_dotenv
            load_dotenv(root/".env")
            if os.getenv("ANTHROPIC_API_KEY",""):
                print("  [env] Loaded API key from .env")
        except Exception:
            pass

    # Auto-detect monthly run (1st of month or explicit)
    if run_type == "daily" and datetime.now().day == 1:
        run_type = "monthly"
        print(f"  [auto] 1st of month — upgrading to monthly deep analysis")

    print("="*60)
    print(f"  💼 Portfolio Intelligence v1.2  |  {run_type.upper()}")
    print(f"  {run_label}  |  {date_str}  |  {now_str}")
    print("="*60)

    # ── Stale-data check (before pipeline runs, checks PREVIOUS freshness) ───
    try:
        import os as _sd_os
        _sd_fp = state_dir / "_freshness.json"
        if _sd_fp.exists():
            _sd_fm = json.loads(_sd_fp.read_text())
            _sd_completed = datetime.fromisoformat(_sd_fm.get("completed_at", "2000-01-01"))
            _sd_now = datetime.now()
            _sd_age_h = (_sd_now - _sd_completed).total_seconds() / 3600
            # Schedule-aware threshold: markets are closed Sat/Sun, so a Fri→Mon gap is
            # expected, not a failure. Allow +24h for each weekend calendar date in the gap
            # so weekend idle doesn't page; a genuine multi-day outage still exceeds it.
            from datetime import timedelta as _sd_td
            _sd_wknd = 0
            _sd_cur = _sd_completed.date()
            while _sd_cur <= _sd_now.date():
                if _sd_cur.weekday() >= 5:  # Sat=5, Sun=6
                    _sd_wknd += 1
                _sd_cur += _sd_td(days=1)
            _sd_threshold = 26 + 24 * _sd_wknd
            if _sd_age_h > _sd_threshold:
                from db_adapter import notification_already_logged, save_notification_log_entry
                _sd_bucket = datetime.now().hour // 6
                _sd_dk = f"{date_str}:stale_data:telegram:bucket_{_sd_bucket}"
                if not notification_already_logged(_sd_dk):
                    _sd_msg = (
                        f"\u26a0\ufe0f DATA STALENESS ALERT\n\n"
                        f"Portfolio data is {_sd_age_h:.0f}h old.\n"
                        f"Last pipeline: {_sd_fm.get('completed_at', '?')[:16]}\n"
                        f"Hash: {_sd_fm.get('holdings_hash', '?')}\n\n"
                        f"Pipeline is running now to refresh."
                    )
                    _sd_ok = False
                    _sd_err = None
                    try:
                        from telegram_alert import send_telegram as _sd_tg
                        _sd_ok = _sd_tg(_sd_msg)
                    except Exception as _sd_te:
                        _sd_err = str(_sd_te)
                    save_notification_log_entry({
                        "notification_date": date_str,
                        "notification_type": "stale_data_alert",
                        "channel": "telegram",
                        "subject": "Data Staleness Alert",
                        "body_summary": f"Data is {_sd_age_h:.0f}h old. Pipeline running to refresh.",
                        "payload": {"age_hours": round(_sd_age_h, 1), "last_completed": _sd_fm.get("completed_at"), "holdings_hash": _sd_fm.get("holdings_hash")},
                        "status": "sent" if _sd_ok else "failed",
                        "dedupe_key": _sd_dk,
                        "sent_at": datetime.now().isoformat() if _sd_ok else None,
                        "error": _sd_err,
                    })
                    if _sd_ok:
                        print(f"  [stale-alert] \u26a0\ufe0f  Stale data alert sent ({_sd_age_h:.0f}h old)")
    except Exception:
        pass  # stale check is best-effort, never blocks pipeline

    # 1 — Load
    from portfolio_loader import load_all_portfolios, save_state
    from portfolio_repricer import reprice_portfolio
    print("\n[1/10] Loading portfolios...")
    portfolio = load_all_portfolios(str(root))
    portfolio = reprice_portfolio(portfolio, state_dir)
    # Compute cost basis from transaction history
    try:
        from collections import defaultdict as _dd
        journal   = portfolio.get("trade_journal", [])
        holdings  = portfolio.get("holdings", [])
        if journal and holdings:
            cb = _dd(lambda: {"cost": 0.0, "shares": 0.0})
            for tx in journal:
                act = tx.get("action","").upper()
                if act not in ("BUY","REINVEST","REINVEST SHARES","REINVEST DIVIDEND"):
                    continue
                sym   = tx.get("symbol","").upper()
                acct  = tx.get("account","")
                qty   = abs(tx.get("quantity",0) or 0)
                price = abs(tx.get("price",0) or 0)
                if sym and qty > 0 and price > 0:
                    cb[f"{acct}|{sym}"]["cost"]   += qty * price
                    cb[f"{acct}|{sym}"]["shares"]  += qty
            upd = 0
            for h in holdings:
                key = f"{h.get('account','')}|{h.get('symbol','').upper()}"
                if key in cb and cb[key]["cost"] > 0:
                    h["cost_basis"] = round(cb[key]["cost"], 2)
                    mv = h.get("market_value", 0) or 0
                    h["gain_loss"] = round(mv - h["cost_basis"], 2)
                    h["gain_loss_pct"] = round(
                        (mv - h["cost_basis"]) / h["cost_basis"] * 100, 2
                    ) if h["cost_basis"] > 0 else 0
                    upd += 1
            if upd:
                tc = sum(h.get("cost_basis",0) or 0 for h in holdings)
                tv = portfolio.get("portfolio_totals",{}).get("total_value",0)
                pt = portfolio.setdefault("portfolio_totals",{})
                pt["total_cost"]      = round(tc, 2)
                pt["total_gain"]      = round(tv - tc, 2)
                pt["total_gain_pct"]  = round((tv - tc) / tc * 100, 2) if tc > 0 else 0
                print(f"  [loader] Cost basis: {upd}/{len(holdings)} holdings computed")
    except Exception as _e:
        print(f"  [loader] Cost basis warning: {_e}")
    save_state(portfolio, str(root))
    totals = portfolio.get("portfolio_totals",{})
    acct_count = len(portfolio.get("account_summaries", {}))
    print(f"  ✅ {acct_count} accounts — ${totals.get('total_value',0):,.2f}")

    # 2 — Analytics
    from portfolio_analyzer import analyze_portfolio
    print("\n[2/10] Analytics...")
    analysis = analyze_portfolio(portfolio)
    fc = analysis.get("flag_count",{})
    print(f"  ✅ {sum(fc.values())} flags ({fc.get('CRITICAL',0)} crit · {fc.get('HIGH',0)} high)")

    # 3 — Tax
    from portfolio_tax import analyze_taxes
    print("\n[3/10] Tax analysis...")
    tax = analyze_taxes(portfolio, state_dir)
    print(f"  ✅ {len(tax.get('harvest_candidates',[]))} harvest candidates")

    # 4 — Rebalancing
    from portfolio_rebalancer import compute_rebalancing
    print("\n[4/10] Rebalancing...")
    rebalancing = compute_rebalancing(portfolio)
    print(f"  ✅ {rebalancing.get('order_count',0)} orders | ${rebalancing.get('total_to_rebalance',0):,.0f} net")

    # 4b — Trade Journal
    from portfolio_trade_journal import build_trade_journal
    try:
        journal = build_trade_journal(portfolio, state_dir)
        n_d = len(journal.get("day_trades",[])); n_s = len(journal.get("swing_trades",[]))
        n_c = len(journal.get("closed_trades",[]))
        print(f"  ✅ Journal: {n_c} closed | {n_d} day | {n_s} swing trades")
    except Exception as e:
        print(f"  [journal] {e}")
        journal = {}

    # 4d — Trade Performance Analysis (auto-detects new CSV)
    trade_analysis = {}
    try:
        from portfolio_trade_analysis import run_analysis as _run_ta
        trade_analysis = _run_ta(portfolio, state_dir)
        status = trade_analysis.get("status","")
        if status == "ok":
            tc = trade_analysis.get("trades_count", 0)
            pf = trade_analysis.get("stats",{}).get("profit_factor",0)
            wr = trade_analysis.get("stats",{}).get("win_rate",0)
            print(f"  [trade_analysis] ✅ {tc} trades | PF={pf:.2f}x | WR={wr*100:.0f}%")
        elif status == "cached":
            print(f"  [trade_analysis] ✅ Cached results (CSV unchanged)")
        elif status == "no_csv":
            print(f"  [trade_analysis] ℹ️  No trades CSV in input/ — drop trades.csv to enable")
        else:
            print(f"  [trade_analysis] ⚠️  {status}")
    except Exception as e:
        print(f"  [trade_analysis] ❌ {e}")
        trade_analysis = {}

    # 4c — Risk Management (stops)
    from portfolio_stops import compute_risk_metrics, check_stop_alerts, save_risk_state
    try:
        risk_mgmt = compute_risk_metrics(portfolio, state_dir)
        save_risk_state(risk_mgmt, state_dir)
        heat = risk_mgmt.get("portfolio_heat_pct",0)
        triggered = len(risk_mgmt.get("triggered",[]))
        print(f"  ✅ Risk: heat={heat:.1f}% | {risk_mgmt.get('stop_count',0)} stops | {triggered} triggered")
        # Check for stop alerts
        stop_alerts = check_stop_alerts(risk_mgmt)
        if stop_alerts:
            from portfolio_alerts import _send_telegram
            from db_adapter import notification_already_logged, save_notification_log_entry
            from datetime import date as _date
            for a in stop_alerts:
                _stop_dk = f"{_date.today()}:stop_alert:{a.get('symbol','unknown')}"
                if notification_already_logged(_stop_dk):
                    print(f"  [stops] Dedup: already sent today for {a.get('symbol','?')}")
                    continue
                _send_telegram(a["msg"], root)
                save_notification_log_entry({"dedupe_key": _stop_dk, "notification_type": "stop_alert", "channel": "telegram", "subject": f"Stop alert: {a.get('symbol','')}", "body_summary": a["msg"][:200], "status": "sent"})
                print(f"  [stops] Alert sent: {a['msg'][:60]}")
            # Generate decision briefs for danger-level positions
            danger_positions = risk_mgmt.get("danger", [])
            if not danger_positions:
                # Fallback: build from alerts
                danger_positions = [{"symbol": a["symbol"], "price": a.get("price", a.get("current_price", 0)), "stop_price": a.get("stop_price", a.get("stop", 0))} for a in stop_alerts]
            if danger_positions:
                try:
                    from stop_decision_brief import process_stop_alerts
                    briefs = process_stop_alerts(danger_positions, str(state_dir), str(root))
                    print(f"  [stop-brief] {len(briefs)} decision brief(s) generated and sent")
                except Exception as _sbe:
                    print(f"  [stop-brief] {_sbe}")
    except Exception as e:
        print(f"  [risk_mgmt] {e}")
        risk_mgmt = {}

    # 5 — Risk
    from portfolio_risk import analyze_risk
    print("\n[5/10] Risk analysis...")
    ta_state = root/"data"/"state.json"
    risk = analyze_risk(portfolio, str(ta_state) if ta_state.exists() else None)
    beta = risk.get("risk_metrics",{}).get("weighted_beta",0)
    print(f"  ✅ beta {beta:.2f} | {len(risk.get('high_risk_positions',[]))} high-risk")

    # 6 — Charts
    print("\n[6/10] Charts...")
    chart_paths = {}
    try:
        from portfolio_charts import generate_all_charts, compute_etf_ticker_exposure
        chart_paths = generate_all_charts(portfolio, analysis, rebalancing, charts_dir)
        analysis["etf_ticker_exposure"] = compute_etf_ticker_exposure(portfolio)
        print(f"  ✅ {len(chart_paths)} charts")
    except Exception as e:
        print(f"  [charts] {e}")

    # 7 — Performance tracking (snapshots)
    print("\n[7/10] Performance tracking...")
    performance = {}
    try:
        from portfolio_performance import track_performance
        performance = track_performance(portfolio, analysis, state_dir)
    except Exception as e:
        print(f"  [perf] {e}")

    # 8 — AI Analysis
    # Skip Sonnet on re-runs same day to avoid unnecessary API costs
    _ai_cache = state_dir / "ai_analysis_cache.json"
    _today    = datetime.now().strftime("%Y-%m-%d")
    ai_analysis = {}
    _ai_cached  = False
    if _ai_cache.exists() and run_type != "manual":
        try:
            _cached = json.loads(_ai_cache.read_text())
            if _cached.get("generated_at","")[:10] == _today:
                ai_analysis  = _cached
                _ai_cached   = True
                print(f"\n[8/10] AI analysis — ✅ using today\'s cached results (no Sonnet cost)")
        except Exception:
            pass
    if not _ai_cached:
        print(f"\n[8/10] AI analysis ({run_type})...")
    if not _ai_cached:
        ai_analysis = {}
        try:
            from portfolio_ai_analyst import run_ai_analysis
            ai_analysis = run_ai_analysis(
            portfolio, analysis, rebalancing, state_dir,
            force_refresh=(run_type in ("monthly","manual")),
            run_type=run_type,
        )
            ai_sections = len([k for k in ai_analysis if k not in ("generated_at","run_type")])
            print(f"  ✅ {ai_sections} AI sections")
            # Save daily cache
            try: _ai_cache.write_text(json.dumps(ai_analysis, indent=2, default=str))
            except Exception: pass
        except Exception as e:
            print(f"  [ai] {e}")

    # ── Portfolio News & Catalyst Intelligence ─────────────────────────────────
    portfolio_news = {}
    try:
        from portfolio_news import run_portfolio_news
        print("  [portfolio-news] Scanning portfolio holdings for news...")
        portfolio_news = run_portfolio_news(portfolio, state_dir, run_type=run_type, root=str(root))
    except Exception as e:
        print(f"  [portfolio-news] ❌ {e}")

    # ── Article Index persistence ────────────────────────────────────────────
    try:
        from db_adapter import save_article_index
        _news_path = state_dir / "portfolio_news.json"
        if _news_path.exists():
            _news_data = json.loads(_news_path.read_text())
            # Use all_scored (top 50, includes watchlist) for broader index; fall back to catalysts (top 20)
            _index_articles = _news_data.get("all_scored") or _news_data.get("catalysts", [])
            if _index_articles:
                save_article_index(_index_articles)
                print(f"  [article-index] ✅ {len(_index_articles)} articles indexed")
    except Exception as _aie:
        print(f"  [article-index] Persistence failed (pipeline continues): {_aie}")

    # ── Stage 7b-7g: New Intelligence Modules ─────────────────────────────────

    technical = {}
    try:
        from portfolio_technical import run_technical_analysis
        technical = run_technical_analysis(portfolio, root, state_dir)
        n = technical.get("analyzed_count", 0); sig = len(technical.get("signal_changes",[]))
        print(f"  [technical] ✅ {n} positions | score={technical.get('portfolio_score',0):.0f} | {sig} signals")
    except Exception as e:
        print(f"  [technical] ❌ {e}")

    # ── Supplemental Finviz enrichment for small positions ──────────────
    # Technical analysis only enriches positions > $1K. Enrich remaining
    # portfolio tickers so weekly reports, signals, and dashboards have
    # complete data (perf_week_pct, RSI, beta, etc.) for ALL positions.
    try:
        from finviz_enrichment import enrich_tickers as _enrich_supplemental
        _FIDELITY_PREFIXES = ("FID-", "SS-", "TRP-", "JPM-", "VANG-", "WM-", "AB-", "SP500-")
        _SKIP = {"CASH", "--", "SNSXX", "SWVXX", "SPRXX", "VMFXX", "FDRXX", "SRNE"}
        _existing = set()
        _ecache_path = state_dir / "ticker_enrichment_cache.json"
        if _ecache_path.exists():
            _existing = set(json.loads(_ecache_path.read_text()).keys())
        # Always include SPY for benchmark comparison
        _supplement = ["SPY"] if "SPY" not in _existing else []
        for _h in portfolio.get("holdings", []):
            _sym = (_h.get("symbol") or "").upper()
            if not _sym or _sym in _SKIP or _sym in _existing:
                continue
            if any(_sym.startswith(p) for p in _FIDELITY_PREFIXES):
                continue
            if "-" in _sym and len(_sym) > 5:
                continue
            _supplement.append(_sym)
        _supplement = list(set(_supplement))
        if _supplement:
            print(f"  [enrich-supplement] Fetching {len(_supplement)} small positions: {', '.join(_supplement[:8])}")
            _enrich_supplemental(_supplement, project_root=str(root), skip_fundamentals=True)
    except Exception as _e:
        print(f"  [enrich-supplement] {_e}")

    # ── Ticker Snapshot Daily (market intelligence persistence) ───────────────
    try:
        from db_adapter import save_ticker_snapshot_daily
        _ecache_path = state_dir / "ticker_enrichment_cache.json"
        if _ecache_path.exists():
            _ecache = json.loads(_ecache_path.read_text())
            save_ticker_snapshot_daily(date_str, _ecache)
            _snap_count = len([k for k in _ecache if not k.startswith("_") and isinstance(_ecache.get(k), dict)])
            print(f"  [ticker-snapshot] ✅ {_snap_count} tickers persisted to daily snapshot")
    except Exception as _tse:
        print(f"  [ticker-snapshot] Persistence failed (pipeline continues): {_tse}")

    # ── Analyst Consensus History ────────────────────────────────────────────
    try:
        from db_adapter import save_analyst_consensus_history
        _ecache_path2 = state_dir / "ticker_enrichment_cache.json"
        _qcache_path = state_dir / "finviz_quote_cache.json"
        if _ecache_path2.exists():
            _ec = json.loads(_ecache_path2.read_text())
            _qc = json.loads(_qcache_path.read_text()) if _qcache_path.exists() else {}
            save_analyst_consensus_history(date_str, _ec, _qc)
    except Exception as _ace:
        print(f"  [analyst-consensus] Persistence failed (pipeline continues): {_ace}")

    # ── Yahoo Analyst Targets History ────────────────────────────────────────
    try:
        import yfinance as _yf_targets
        from db_adapter import save_yahoo_analyst_targets_history
        # Use symbols from enrichment cache (already loaded above or re-read)
        _ecache_path3 = state_dir / "ticker_enrichment_cache.json"
        _target_syms = []
        if _ecache_path3.exists():
            _ec3 = json.loads(_ecache_path3.read_text())
            # Filter to likely stocks (skip ETF-like: no PE, no float, sector=Financial/ETF)
            _FIDELITY_PFX = ("FID-", "SS-", "TRP-", "JPM-", "VANG-", "WM-", "AB-", "SP500-")
            _ETF_INDUSTRIES = {"Exchange Traded Fund", ""}
            for _s, _d in _ec3.items():
                if not isinstance(_d, dict) or _s.startswith("_"):
                    continue
                if any(_s.startswith(p) for p in _FIDELITY_PFX):
                    continue
                if _d.get("industry") in _ETF_INDUSTRIES and _d.get("pe") is None:
                    continue
                _target_syms.append(_s)
        _targets_payload = []
        if _target_syms:
            # Batch fetch (yfinance supports batch via Tickers)
            for _sym in _target_syms[:50]:  # cap at 50 to limit API calls
                try:
                    _info = _yf_targets.Ticker(_sym).info
                    _tm = _info.get("targetMeanPrice")
                    if _tm is not None:
                        _targets_payload.append({
                            "symbol": _sym,
                            "current_price": _info.get("currentPrice"),
                            "target_mean_price": _tm,
                            "target_high_price": _info.get("targetHighPrice"),
                            "target_low_price": _info.get("targetLowPrice"),
                            "target_median_price": _info.get("targetMedianPrice"),
                            "recommendation_mean": _info.get("recommendationMean"),
                            "recommendation_key": _info.get("recommendationKey"),
                            "number_of_analyst_opinions": _info.get("numberOfAnalystOpinions"),
                        })
                except Exception:
                    pass
            if _targets_payload:
                save_yahoo_analyst_targets_history(date_str, _targets_payload)
                print(f"  [yahoo-targets] ✅ {len(_targets_payload)} symbols with analyst targets persisted")
            else:
                print(f"  [yahoo-targets] No analyst targets returned")
    except Exception as _yte:
        print(f"  [yahoo-targets] Failed (pipeline continues): {_yte}")

    # ── AI-Generated Watchlist Candidates ────────────────────────────────────
    try:
        from db_adapter import save_watchlist_item, _execute as _ai_wl_exec
        from datetime import timedelta as _td_wl

        # Get current held + active watchlist symbols to exclude
        _held_syms = set(
            (h.get("symbol") or "").upper()
            for h in portfolio.get("holdings", [])
            if (h.get("market_value") or 0) > 100
        )
        _active_wl = _ai_wl_exec(
            "SELECT symbol FROM watchlist_items WHERE status='active'", fetch="all"
        ) or []
        _exclude = _held_syms | set(r["symbol"] for r in _active_wl)
        # Cap total AI-generated active items at 5
        _current_ai_count = len([r for r in _active_wl if True])  # all active already counted
        _ai_active = _ai_wl_exec(
            "SELECT COUNT(*) AS cnt FROM watchlist_items WHERE source_type='ai_generated' AND status='active'", fetch="one"
        )
        _ai_active_count = (_ai_active or {}).get("cnt", 0)
        # Expire AI items past their expires_at date
        from db_adapter import expire_stale_ai_watchlist
        _expired_by_date = expire_stale_ai_watchlist()
        if _expired_by_date:
            _exp_syms = [r["symbol"] for r in _expired_by_date]
            print(f"  [ai-watchlist] Date-expired {len(_expired_by_date)} AI items: {', '.join(_exp_syms)}")
            _ai_active_count -= len(_expired_by_date)
        # Reconcile: if over cap, expire lowest-confidence excess items
        if _ai_active_count > 5:
            _ai_wl_exec(
                """UPDATE watchlist_items SET status = 'expired', updated_at = now()
                   WHERE id IN (
                       SELECT id FROM watchlist_items
                       WHERE source_type = 'ai_generated' AND status = 'active'
                       ORDER BY confidence ASC, created_at ASC
                       LIMIT %s
                   )""",
                (_ai_active_count - 5,)
            )
            _expired_n = _ai_active_count - 5
            _ai_active_count = 5
            print(f"  [ai-watchlist] Reconciled: expired {_expired_n} lowest-confidence AI items (cap=5)")
        _ai_slots = max(0, 5 - _ai_active_count)  # cap total AI items at 5

        # Find candidates: high upside, buy/strong_buy, 3+ analysts, not excluded
        _candidates = _ai_wl_exec(
            """SELECT y.symbol, y.current_price, y.target_mean_price,
                      round((y.target_mean_price - y.current_price) / y.current_price * 100, 1) AS upside_pct,
                      y.recommendation_key, y.number_of_analyst_opinions
               FROM yahoo_analyst_targets_history y
               WHERE y.snapshot_date = (SELECT MAX(snapshot_date) FROM yahoo_analyst_targets_history)
                 AND y.target_mean_price > 0 AND y.current_price > 0
                 AND (y.target_mean_price - y.current_price) / y.current_price > 0.25
                 AND y.number_of_analyst_opinions >= 3
                 AND y.recommendation_key IN ('strong_buy', 'buy')
               ORDER BY (y.target_mean_price - y.current_price) / y.current_price DESC
               LIMIT 10""",
            fetch="all"
        ) or []

        _ai_added = 0
        _exp_date = (datetime.now() + _td_wl(days=30)).strftime("%Y-%m-%d")
        _max_new = min(3, _ai_slots)  # at most 3 new per run, capped by total limit
        for _c in _candidates:
            if _c["symbol"] in _exclude:
                continue
            if _ai_added >= _max_new:
                break
            _upside = float(_c["upside_pct"])
            _conf = min(0.90, 0.60 + (_c["number_of_analyst_opinions"] / 50))
            save_watchlist_item({
                "symbol": _c["symbol"],
                "source_type": "ai_generated",
                "thesis": (
                    f"Analyst consensus: {_c['recommendation_key']} with "
                    f"{_c['number_of_analyst_opinions']} opinions. "
                    f"Mean target ${float(_c['target_mean_price']):.0f} "
                    f"({_upside:.0f}% upside from ${float(_c['current_price']):.2f})."
                ),
                "target_intent": "growth" if _upside > 100 else "speculative",
                "added_date": date_str,
                "added_by": "portfolio_agent",
                "confidence": round(_conf, 2),
                "status": "active",
                "notes": f"Auto-generated {date_str}. Expires {_exp_date}.",
                "data": {
                    "current_price": float(_c["current_price"]),
                    "target_mean_price": float(_c["target_mean_price"]),
                    "upside_pct": float(_upside),
                    "recommendation_key": _c["recommendation_key"],
                    "analyst_count": _c["number_of_analyst_opinions"],
                    "expires_at": _exp_date,
                    "generation_rule": "yahoo_high_upside_buy",
                },
            })
            _exclude.add(_c["symbol"])
            _ai_added += 1

        if _ai_added:
            print(f"  [ai-watchlist] ✅ {_ai_added} AI-generated watchlist candidates added")
    except Exception as _awle:
        print(f"  [ai-watchlist] Generation failed (pipeline continues): {_awle}")

    tech_chart_paths = {}
    try:
        from portfolio_technical_charts import generate_all_technical_charts
        tech_charts_dir = charts_dir / "technical"
        tech_chart_paths = generate_all_technical_charts(technical, tech_charts_dir)
        print(f"  [tech-charts] ✅ {len(tech_chart_paths)} charts generated")
    except Exception as e:
        print(f"  [tech-charts] ❌ {e}")

    options = {}
    try:
        from portfolio_options import scan_covered_calls
        options = scan_covered_calls(portfolio, technical.get("positions",{}), root, state_dir)
        print(f"  [options] ✅ {len(options.get('opportunities',[]))} CC opps | ${options.get('total_monthly_income',0):,.0f}/mo")
    except Exception as e:
        print(f"  [options] ❌ {e}")

    tax_projection = {}
    try:
        from portfolio_tax_projection import calculate_tax_projection
        tax_projection = calculate_tax_projection(state_dir=state_dir)
        print(f"  [tax] ✅ bracket={tax_projection.get('tax',{}).get('current_bracket','?')} | est=${tax_projection.get('tax',{}).get('total_est',0):,.0f}")
    except Exception as e:
        print(f"  [tax] ❌ {e}")

    stress = {}
    try:
        from portfolio_stress import run_stress_tests
        stress = run_stress_tests(portfolio, state_dir)
        print(f"  [stress] ✅ worst case: ${stress.get('worst_case_loss',0):,.0f}")
    except Exception as e:
        print(f"  [stress] ❌ {e}")

    retirement = {}
    try:
        from portfolio_retirement import build_retirement_roadmap
        retirement = build_retirement_roadmap(portfolio, state_dir)
        print(f"  [retirement] ✅ {retirement.get('key_dates',{}).get('days_to_golden',0)}d to Golden Window")
    except Exception as e:
        print(f"  [retirement] ❌ {e}")

    behavioral = {}
    try:
        from portfolio_behavioral import analyze_behavior
        behavioral = analyze_behavior(journal, state_dir)
        best = (behavioral.get("best_day") or {}).get("day","?")
        if behavioral.get("has_data"): print(f"  [behavioral] ✅ best day: {best}")
    except Exception as e:
        print(f"  [behavioral] ❌ {e}")

    dividend_calendar = {}
    try:
        from portfolio_dividend_calendar import build_dividend_calendar
        dividend_calendar = build_dividend_calendar(portfolio, root, state_dir)
        payers = len(dividend_calendar.get("payers",[]))
        annual = dividend_calendar.get("total_annual",0)
        alerts = len(dividend_calendar.get("ex_div_alerts",[]))
        print(f"  [dividends] ✅ {payers} payers | ${annual:,.0f}/yr | {alerts} ex-div alerts")
        # Dividend history dual-write (OpenClaw Phase A1)
        try:
            from db_adapter import save_dividend_history
            save_dividend_history(dividend_calendar.get("payers", []), date_str)
        except Exception as _dhe:
            print(f"  [dividend-history] Postgres write failed (pipeline continues): {_dhe}")
        # ── Dividend payer notification for current month ──
        try:
            from datetime import datetime as _ddt
            _cur_month = _ddt.now().month
            _monthly = dividend_calendar.get("monthly_summary", [])
            _this_month = next((m for m in _monthly if m.get("month") == _cur_month), None)
            if _this_month and _this_month.get("symbols"):
                _div_dk = f"{date_str}:dividend_payers:{_cur_month}"
                if not notification_already_logged(_div_dk):
                    _div_msg = (
                        f"\U0001f4b0 Dividend Payers This Month ({_this_month['month_name']})\n\n"
                        f"Expected: ${_this_month['total']:,.0f} from {_this_month['count']} positions\n"
                        f"Symbols: {', '.join(_this_month['symbols'][:10])}\n\n"
                        f"Annual income: ${dividend_calendar.get('total_annual', 0):,.0f}/yr"
                    )
                    if _morning_bundle is not None:
                        append_section(_morning_bundle, "dividends", _div_msg)
                    else:
                        try:
                            from telegram_alert import send_telegram as _div_tg
                            _div_tg(_div_msg)
                        except Exception:
                            pass
                    save_notification_log_entry({
                        "notification_date": date_str,
                        "notification_type": "dividend_alert",
                        "channel": "telegram",
                        "subject": f"Dividend Payers — {_this_month['month_name']}: ${_this_month['total']:,.0f}",
                        "body_summary": _div_msg[:300],
                        "status": "sent",
                        "dedupe_key": _div_dk,
                        "sent_at": _ddt.now().isoformat(),
                    })
                    print(f"  [dividends] Telegram: {_this_month['count']} payers, ${_this_month['total']:,.0f} this month")
        except Exception as _div_e:
            print(f"  [dividends] Telegram alert skipped: {_div_e}")
    except Exception as e:
        print(f"  [dividends] ❌ {e}")

    attribution = {}
    try:
        from portfolio_performance_attribution import compute_attribution, load_attribution
        cached_attr = load_attribution(state_dir)
        if (cached_attr.get("last_updated","")[:10] == datetime.now().strftime("%Y-%m-%d")
                and cached_attr.get("has_data")):
            attribution = cached_attr
            print("  [attribution] ✅ Cached attribution loaded")
        else:
            attribution = compute_attribution(portfolio, state_dir)
            alpha = attribution.get("alpha_annualized")
            astr = f"{alpha:+.1f}%" if alpha is not None else "N/A"
            print(f"  [attribution] ✅ Alpha: {astr}")
    except Exception as e:
        print(f"  [attribution] ❌ {e}")

    correlation = {}
    try:
        from portfolio_correlation import compute_correlation
        correlation = compute_correlation(portfolio, state_dir)
        dp = correlation.get("defense_cluster_pct",0)
        rs = correlation.get("rate_sensitivity",0)
        print(f"  [correlation] ✅ Defense: {dp:.1f}% | Rate sensitivity: {rs:.2f}")
    except Exception as e:
        print(f"  [correlation] ❌ {e}")

    watchlist = {}
    try:
        from portfolio_watchlist import build_watchlist_intelligence
        watchlist = build_watchlist_intelligence(
            portfolio, technical.get("positions",{}), state_dir)
        wn = watchlist.get("total_watchlist",0)
        wo = len(watchlist.get("sizing_opportunities",[]))
        print(f"  [watchlist] ✅ {wn} watchlist items | {wo} sizing opportunities")
    except Exception as e:
        print(f"  [watchlist] ❌ {e}")

    perf_history = {}
    try:
        from portfolio_performance_history import compute_period_returns
        perf_history = compute_period_returns(portfolio, state_dir)
        periods = perf_history.get("periods", {})
        avail = [p for p,d in periods.items() if d.get("change_pct") is not None]
        snaps = perf_history.get("snapshot_count", 0)
        build = perf_history.get("building", [])
        recon = perf_history.get("reconstructed", [])
        print(f"  [perf-history] ✅ {len(avail)} periods available | {snaps} snapshots"
              + (f" | reconstructed: {','.join(recon)}" if recon else "")
              + (f" | building: {','.join(build)}" if build else ""))
        # Save for Command Center (reads performance_history.json)
        ph_path = state_dir / "performance_history.json"
        import json as _json
        ph_path.write_text(_json.dumps(perf_history, indent=2))
    except Exception as e:
        print(f"  [perf-history] ❌ {e}")

    # 9 — Dashboard
    from portfolio_dashboard import generate_portfolio_dashboard
    print("\n[9/10] Dashboard...")
    dash_path = report_dir/f"portfolio_dashboard_{date_str}_{run_label}.html"
    live_dash  = report_dir/"portfolio_live.html"
    # Reliably get API key: env var → dotenv → direct .env file parse
    import os as _os
    _api_key = _os.getenv("ANTHROPIC_API_KEY","").strip()
    if not _api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv(root/".env", override=True)
            _api_key = _os.getenv("ANTHROPIC_API_KEY","").strip()
        except Exception:
            pass
    if not _api_key:
        # Direct parse of .env file as last resort
        _env_file = root / ".env"
        if _env_file.exists():
            for _line in _env_file.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if _line.startswith("ANTHROPIC_API_KEY"):
                    _api_key = _line.split("=", 1)[-1].strip().strip("\"'")
                    break
    if _api_key:
        print(f"  [dashboard] API key loaded — AI buttons will work in browser")
    else:
        print(f"  [dashboard] WARNING: API key not found — AI buttons will show error")
    generate_portfolio_dashboard(
        portfolio, analysis, tax, rebalancing, risk, dash_path,
        performance=performance, ai_analysis=ai_analysis,
        api_key=_api_key, journal=journal,
        risk_mgmt=risk_mgmt,
        options=options,
        technical=technical,
        tax_projection=tax_projection,
        stress=stress,
        retirement=retirement,
        behavioral=behavioral,
        perf_history=perf_history,
        dividend_calendar=dividend_calendar,
        attribution=attribution,
        correlation=correlation,
        watchlist=watchlist,
        trade_analysis=trade_analysis
    )
    shutil.copy(dash_path, live_dash)
    # Also copy to project-root reports/ where portfolio_server.py serves from
    server_live = root / "reports" / "portfolio_live.html"
    server_live.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(dash_path, server_live)
    # Sync enrichment cache to portfolios/state for server serving
    enrich_src = root / 'data' / 'state' / 'ticker_enrichment_cache.json'
    enrich_dst = root / 'data' / 'portfolios' / 'state' / 'ticker_enrichment_cache.json'
    if enrich_src.exists():
        shutil.copy2(enrich_src, enrich_dst)
    print(f"  ✅ {dash_path.name}")

    # 10 — DOCX Brief
    if generate_report:
        from portfolio_report import generate_portfolio_brief
        print("\n[10/10] Intelligence brief...")
        docx_path = report_dir/f"portfolio_brief_{date_str}_{run_label}.docx"
        generate_portfolio_brief(
            portfolio, analysis, tax, rebalancing, risk, docx_path,
            chart_paths=chart_paths, performance=performance, ai_analysis=ai_analysis,
            technical=technical, stress=stress, retirement=retirement,
            tax_projection=tax_projection, tech_chart_paths=tech_chart_paths,
            perf_history=perf_history
        )
        print(f"  ✅ {docx_path.name}")
        # Postgres dual-write for intel_briefs (non-blocking)
        try:
            from db_adapter import save_intel_brief
            _wc = 0
            if docx_path.exists():
                _wc = docx_path.stat().st_size // 6  # rough word count estimate from file size
            save_intel_brief({
                "brief_date": date_str,
                "brief_type": run_type,
                "fund": "consolidated",
                "docx_path": str(docx_path),
                "word_count": _wc,
                "sections": list(ai_analysis.keys()) if ai_analysis else [],
                "triggers": {"run_label": run_label, "run_type": run_type},
            })
        except Exception as _ibe:
            print(f"  [intel-brief] Postgres write failed (DOCX saved OK): {_ibe}")
    else:
        print("\n[10/10] Report skipped")

    # ── Monthly Advisory: Dual-AI analysis (Opus + Sonnet) ──────────
    if run_type in ("monthly", "manual"):
        try:
            from monthly_advisory import run_monthly_advisory
            print("\n  [advisory] Running dual-AI monthly advisory...")
            advisory = run_monthly_advisory(
                portfolio, analysis, risk, perf_history,
                retirement, tax_projection, rebalancing, state_dir, root=str(root)
            )
        except Exception as e:
            print(f"  [advisory] ❌ {e}")

    print("\n"+"="*60)
    print(f"  ✅ Portfolio Intelligence v1.2 complete  [{run_type.upper()}]")
    print(f"  💼 ${totals.get('total_value',0):,.2f}  📈 +${totals.get('total_gain',0):,.2f} ({totals.get('total_gain_pct',0):.1f}%)")
    print(f"  💵 ${analysis.get('dividends',{}).get('total_annual_income',0):,.2f}/yr dividends")
    print(f"  ⚖️  ${rebalancing.get('total_to_rebalance',0):,.0f} net to rebalance")
    day_pnl = performance.get("day_pnl", 0)
    if day_pnl:
        sign = "+" if day_pnl >= 0 else ""
        print(f"  📅 Today: {sign}${abs(day_pnl):,.0f}")
    print(f"  📊 {len(chart_paths)} charts  |  🌐 {live_dash}")

    # ── Stage 11: Telegram Alerts ─────────────────────────────────────────────
    from portfolio_alerts import (run_portfolio_alerts, send_technical_alerts,
                                    send_monthly_report_telegram, send_weekly_digest)
    print(f"\n[11/11] Portfolio alerts...")
    try:
        alert_counts = run_portfolio_alerts(portfolio, analysis, root, bundle=_morning_bundle)
        total_alerts = sum(alert_counts.values())
        print(f"  ✅ {total_alerts} alert(s) sent → Telegram")
    except Exception as e:
        print(f"  [alerts] Error: {e}")

    # Technical signal alerts
    if technical.get("signal_changes"):
        try:
            n_sig = send_technical_alerts(technical, root, bundle=_morning_bundle)
            if n_sig: print(f"  [alerts] ✅ {n_sig} technical signals sent → Telegram")
        except Exception as e:
            print(f"  [alerts] Technical alerts error: {e}")

    # Monthly: send PDF + DOCX to Telegram
    if run_type == "monthly" and generate_report:
        try:
            docx_path = report_dir/f"portfolio_brief_{date_str}_{run_label}.docx"
            if docx_path.exists():
                send_monthly_report_telegram(docx_path, portfolio, ai_analysis or {},
                                             technical, root)
        except Exception as e:
            print(f"  [alerts] Monthly report delivery error: {e}")

    # Weekly: send digest
    if run_type == "weekly":
        try:
            send_weekly_digest(portfolio, journal, technical, root)
        except Exception as e:
            print(f"  [alerts] Weekly digest error: {e}")

    # ── Snapshot Index (for CC account-level performance) ───
    try:
        snap_dir = state_dir / "snapshots"
        if snap_dir.exists():
            import json as _json
            snaps = sorted(snap_dir.glob("*.json"))
            idx = []
            for sf in snaps:
                try:
                    sd = _json.loads(sf.read_text())
                    entry = {"date": sf.stem}
                    for k, v in (sd.get("accounts") or {}).items():
                        if isinstance(v, dict):
                            entry[k] = v.get("total_value", v.get("value", 0)) or 0
                    if len(entry) > 1: idx.append(entry)
                except: pass
            (state_dir / "snapshot_index.json").write_text(_json.dumps(idx))
            print(f"  [snapshots] Index: {len(idx)} entries")
    except Exception as e:
        print(f"  [snapshots] Index error: {e}")

    # ── Earnings Dates (yfinance, refresh weekly) ───────────
    try:
        from earnings_date_enrichment import refresh_earnings_dates
        ed_path = state_dir / "earnings_dates.json"
        # Refresh if file is >3 days old or missing
        stale = True
        if ed_path.exists():
            age_h = (datetime.now() - datetime.fromtimestamp(ed_path.stat().st_mtime)).total_seconds() / 3600
            stale = age_h > 72  # 3 days
        if stale or run_type in ("weekly", "monthly"):
            refresh_earnings_dates(project_root)
        else:
            print(f"  [earnings] Fresh ({age_h:.0f}h old) — skipping refresh")
    except Exception as e:
        print(f"  [earnings] Error refreshing earnings dates: {e}")

    # ── Fidelity 401k period returns (yfinance via real fund tickers) ──
    try:
        import yfinance as _yf
        _overrides = json.load(open(root / "config" / "manual_beta_overrides.json")) if (root / "config" / "manual_beta_overrides.json").exists() else {}
        _ph = json.load(open(state_dir / "performance_history.json")) if (state_dir / "performance_history.json").exists() else {}
        _fid_pos = []
        _fid_total = 0
        for _h in portfolio.get("holdings", []):
            if "fidelity" in (_h.get("account","")).lower():
                _sym = _h.get("symbol","")
                _mv = _h.get("market_value", 0) or 0
                if _mv > 0 and _sym in _overrides and isinstance(_overrides[_sym], dict):
                    _fid_pos.append({"sym": _sym, "real": _overrides[_sym].get("real_ticker", _sym), "mv": _mv})
                    _fid_total += _mv
        if _fid_pos and _fid_total > 0:
            _period_days = {"1M": 22, "3M": 66, "6M": 132, "1Y": 252}
            _fund_returns = {}
            for _fp in _fid_pos:
                try:
                    _hist = _yf.Ticker(_fp["real"]).history(period="1y")
                    if _hist.empty or len(_hist) < 5: continue
                    _cur = _hist['Close'].iloc[-1]
                    _rets = {}
                    for _lbl, _days in _period_days.items():
                        _start = _hist['Close'].iloc[-_days] if len(_hist) > _days else _hist['Close'].iloc[0]
                        if len(_hist) > _days * 0.8:
                            _rets[_lbl] = ((_cur / _start) - 1) * 100
                    # YTD
                    _jan = _hist[_hist.index >= "2026-01-01"]
                    if not _jan.empty:
                        _rets["YTD"] = ((_cur / _jan['Close'].iloc[0]) - 1) * 100
                    _fund_returns[_fp["sym"]] = {"rets": _rets, "wt": _fp["mv"] / _fid_total}
                except: pass
            # Weighted average
            _fid_acct = _ph.setdefault("accounts", {}).setdefault("fidelity_401k", {})
            _fid_acct["current_value"] = _fid_total
            _fid_periods = _fid_acct.setdefault("periods", {})
            for _lbl in list(_period_days.keys()) + ["YTD"]:
                _tw, _twr = 0, 0
                for _fr in _fund_returns.values():
                    _r = _fr["rets"].get(_lbl)
                    if _r is not None:
                        _twr += _r * _fr["wt"]; _tw += _fr["wt"]
                if _tw > 0.5:
                    _pct = round(_twr / _tw, 2)
                    _fid_periods[_lbl] = {"change_pct": _pct, "change": round(_fid_total * _pct / 100, 2), "source": "yfinance-weighted"}
            # Also derive 1D/1W from snapshot index
            _snap_idx = json.load(open(state_dir / "snapshot_index.json")) if (state_dir / "snapshot_index.json").exists() else []
            if _snap_idx:
                _snaps = sorted(_snap_idx, key=lambda s: s["date"])
                for _lbl, _days in [("1D", 1), ("1W", 7)]:
                    _target = (datetime.now() - timedelta(days=_days)).strftime("%Y-%m-%d")
                    _best = None
                    for _s in _snaps:
                        if _s["date"] <= _target: _best = _s
                    if _best and _best.get("fidelity_401k"):
                        _start = _best["fidelity_401k"]
                        _chg = _fid_total - _start
                        _fid_periods[_lbl] = {"change_pct": round((_chg/_start)*100, 2) if _start > 0 else 0, "change": round(_chg, 2), "source": "snapshot-derived"}
            print(f"  [fidelity-perf] Updated {len([k for k,v in _fid_periods.items() if isinstance(v,dict)])} periods from {len(_fund_returns)} funds")
        else:
            print(f"  [fidelity-perf] No Fidelity positions with real ticker mappings")
        # 1D: canonical market day from holdings (matches header TODAY)
        try:
            from portfolio_snapshot_sanity import account_market_days, apply_market_day_1d, portfolio_market_day
            _ph = apply_market_day_1d(_ph, portfolio)
            for _ak, _md in account_market_days(portfolio).items():
                _acct = _ph.setdefault("accounts", {}).setdefault(_ak, {})
                _acct.setdefault("periods", {})["1D"] = _md
                if not _acct.get("current_value"):
                    _acct["current_value"] = _md.get("end_value")
            _md_top = portfolio_market_day(portfolio)
            if _md_top:
                _ph.setdefault("periods", {})["1D"] = _md_top
        except Exception as _mde:
            print(f"  [perf] market_day 1D overlay failed: {_mde}")

        # Recompute portfolio-level from all accounts with sanity filter
        # (runs unconditionally — even if Fidelity block above was skipped)
        _MAX = {"1D":15,"1W":30,"1M":50,"3M":80,"6M":100,"YTD":150,"1Y":200}
        _total_current = sum(a.get("current_value",0) for a in _ph.get("accounts",{}).values() if isinstance(a,dict))
        for _lbl in ["1W","1M","3M","6M","YTD","1Y"]:
            _tc, _ts, _n = 0, 0, 0
            for _ak, _av in _ph.get("accounts",{}).items():
                if not isinstance(_av, dict): continue
                _p = (_av.get("periods") or {}).get(_lbl)
                if not isinstance(_p, dict): continue
                _pct = _p.get("change_pct")
                _chg = _p.get("change")
                _cv = _av.get("current_value", 0)
                if _pct is not None and abs(_pct) > _MAX.get(_lbl, 200): continue
                if _chg is not None:
                    _tc += _chg; _ts += _cv - _chg; _n += 1
                elif _pct is not None and _cv > 0:
                    _st = _cv / (1 + _pct/100); _tc += _cv - _st; _ts += _st; _n += 1
            if _n >= 1 and _ts > 0:
                _ph.setdefault("periods",{})[_lbl] = {"change_pct": round((_tc/_ts)*100, 2), "change": round(_tc, 2), "source": "account-aggregated"}
        # Never overwrite market_day 1D with account-aggregated snapshot delta
        try:
            from portfolio_snapshot_sanity import portfolio_market_day
            _md_final = portfolio_market_day(portfolio)
            if _md_final:
                _ph.setdefault("periods", {})["1D"] = _md_final
        except Exception:
            pass
        json.dump(_ph, open(state_dir / "performance_history.json", "w"), indent=2, default=str)
        perf_history = _ph  # update for dashboard rebuild below
    except Exception as e:
        print(f"  [fidelity-perf] Error: {e}")

    # Postgres dual-write for performance_daily (non-blocking, JSON already saved above)
    try:
        from db_adapter import save_performance_daily
        _perf_src = perf_history if perf_history else (json.load(open(state_dir / "performance_history.json")) if (state_dir / "performance_history.json").exists() else {})
        if _perf_src and _perf_src.get("current_value"):
            # Pre-clean numpy types via JSON round-trip before JSONB insert
            save_performance_daily(json.loads(json.dumps(_perf_src, default=str)))
    except Exception as _pde:
        print(f"  [perf-daily] Postgres write failed (JSON saved OK): {_pde}")

    # ── Rebuild dashboard with corrected performance data ──────────
    try:
        print("  [dashboard-refresh] Rebuilding with account-aggregated periods...")
        generate_portfolio_dashboard(
            portfolio, analysis, tax, rebalancing, risk, dash_path,
            performance=performance, ai_analysis=ai_analysis,
            api_key=_api_key, journal=journal,
            risk_mgmt=risk_mgmt,
            options=options,
            technical=technical,
            tax_projection=tax_projection,
            stress=stress,
            retirement=retirement,
            behavioral=behavioral,
            perf_history=perf_history,
            dividend_calendar=dividend_calendar,
            attribution=attribution,
            correlation=correlation,
            watchlist=watchlist,
            trade_analysis=trade_analysis
        )
        shutil.copy(dash_path, live_dash)
        shutil.copy(dash_path, server_live)
        print("  [dashboard-refresh] ✅ Live report updated with correct YTD")
    except Exception as e:
        print(f"  [dashboard-refresh] ❌ {e}")

    # ── Action Signals (rules engine v3) ────────────────────
    try:
        from portfolio_signals import generate_and_save_signals
        generate_and_save_signals(project_root)
    except Exception as e:
        print(f"  [signals] Error generating signals: {e}")

    # ── Freshness Manifest (Phase 0) ─────────────────────────────────────────
    try:
        import time as _time, hashlib as _hl
        _pipeline_end = datetime.now()
        _pipeline_start = datetime.strptime(f"{date_str} {now_str}", "%Y-%m-%d %H:%M ET")
        _duration = (_pipeline_end - _pipeline_start).total_seconds()
        # Holdings hash: deterministic signature of portfolio composition
        _h_tuples = sorted(
            (h.get("symbol",""), h.get("account",""), round(h.get("shares",0) or 0, 4))
            for h in portfolio.get("holdings", [])
            if (h.get("market_value") or 0) > 100
        )
        _holdings_hash = _hl.md5(str(_h_tuples).encode()).hexdigest()[:12]
        _freshness = {
            "run_id": _pipeline_end.strftime("%Y%m%d-%H%M%S"),
            "completed_at": _pipeline_end.isoformat(),
            "holdings_as_of": portfolio.get("as_of", date_str),
            "holdings_repriced": portfolio.get("last_repriced", ""),
            "holdings_hash": _holdings_hash,
            "steps_completed": 10,
            "pipeline_duration_seconds": round(_duration, 1),
            "run_type": run_type,
            "status": "fresh",
        }
        _freshness_path = state_dir / "_freshness.json"
        _freshness_path.write_text(json.dumps(_freshness, indent=2))
        print(f"  [freshness] ✅ Manifest written ({_freshness['run_id']}, hash={_holdings_hash})")
    except Exception as _fe:
        print(f"  [freshness] Warning: manifest write failed: {_fe}")

    # ── Price DB sync — persist all today's prices to PostgreSQL ────────────
    try:
        from price_db_sync import sync_daily_prices
        sync_daily_prices()
    except Exception as _pdb_e:
        print(f"  [price-db] Warning: {_pdb_e}")

    # ── Advisor Observations (OpenClaw Phase A1) ─────────────────────────────
    try:
        from db_adapter import save_advisor_observations
        _obs = []
        _today = date_str
        _h_hash = _freshness.get("holdings_hash", "") if '_freshness' in dir() else ""

        # Category: performance
        _totals = portfolio.get("portfolio_totals", {})
        _tv = _totals.get("total_value", 0)
        _ph = perf_history if perf_history else {}
        _periods = _ph.get("periods", {})
        if _tv > 0:
            _ytd = _periods.get("YTD", {}).get("change_pct")
            _1w = _periods.get("1W", {}).get("change_pct")
            _obs.append({
                "observation_date": _today, "symbol": None, "category": "performance",
                "observation": f"Portfolio at ${_tv:,.0f}" + (f" | YTD {_ytd:+.1f}%" if _ytd else "") + (f" | 1W {_1w:+.1f}%" if _1w else ""),
                "evidence": {"total_value": _tv, "ytd_pct": _ytd, "1w_pct": _1w},
                "source": "pipeline:performance_daily", "freshness_hash": _h_hash,
            })

        # Category: dividend
        if dividend_calendar and dividend_calendar.get("payers"):
            _div_total = dividend_calendar.get("total_annual", 0)
            _div_count = len(dividend_calendar.get("payers", []))
            _obs.append({
                "observation_date": _today, "symbol": None, "category": "dividend",
                "observation": f"Portfolio dividend income: ${_div_total:,.0f}/yr from {_div_count} payers",
                "evidence": {"total_annual": _div_total, "payer_count": _div_count},
                "source": "pipeline:dividend_calendar", "freshness_hash": _h_hash,
            })

        # Category: concentration (top position)
        _signals_path = state_dir / "action_signals.json"
        if _signals_path.exists():
            try:
                _sigs = json.loads(_signals_path.read_text()).get("signals", [])
                _trims = [s for s in _sigs if s.get("signal") in ("TRIM", "WATCH") and s.get("portfolio_pct", 0) > 12]
                for _t in _trims[:3]:
                    _obs.append({
                        "observation_date": _today, "symbol": _t["symbol"], "category": "concentration",
                        "observation": f"{_t['symbol']} is {_t['portfolio_pct']:.1f}% of portfolio — signal: {_t['signal']}",
                        "evidence": {"portfolio_pct": _t["portfolio_pct"], "signal": _t["signal"], "rule": _t.get("rule","")},
                        "source": "pipeline:action_signals", "freshness_hash": _h_hash,
                    })
                _adds = [s for s in _sigs if s.get("signal") == "ADD"]
                if _adds:
                    _obs.append({
                        "observation_date": _today, "symbol": None, "category": "signal",
                        "observation": f"{len(_adds)} positions have ADD signal: {', '.join(s['symbol'] for s in _adds[:5])}",
                        "evidence": {"add_count": len(_adds), "symbols": [s["symbol"] for s in _adds]},
                        "source": "pipeline:action_signals", "freshness_hash": _h_hash,
                    })
            except Exception:
                pass

        # Category: risk
        _risk_path = state_dir / "risk_management.json"
        if _risk_path.exists():
            try:
                _rm = json.loads(_risk_path.read_text())
                _heat = _rm.get("portfolio_heat_pct", 0)
                _triggered = len(_rm.get("triggered", []))
                _danger = len(_rm.get("danger", []))
                if _heat > 0 or _triggered > 0 or _danger > 0:
                    _obs.append({
                        "observation_date": _today, "symbol": None, "category": "risk",
                        "observation": f"Portfolio heat: {_heat:.1f}% | {_triggered} stops triggered | {_danger} in danger zone",
                        "evidence": {"heat_pct": _heat, "triggered": _triggered, "danger": _danger},
                        "source": "pipeline:risk_management", "freshness_hash": _h_hash,
                    })
            except Exception:
                pass

        # Category: freshness
        _age = _freshness.get("pipeline_duration_seconds", 0) if '_freshness' in dir() else 0
        _obs.append({
            "observation_date": _today, "symbol": None, "category": "freshness",
            "observation": f"Pipeline completed successfully in {_age:.0f}s",
            "evidence": {"duration_seconds": _age, "run_type": run_type, "holdings_hash": _h_hash},
            "source": "pipeline:freshness_manifest", "freshness_hash": _h_hash,
        })

        # ── Expire stale escalations (date-based) ────────────────────
        try:
            from db_adapter import expire_stale_escalations
            _expired_escs = expire_stale_escalations()
            if _expired_escs:
                _exp_rules = [f"{r.get('symbol') or '*'}:{r['trigger_rule']}" for r in _expired_escs]
                print(f"  [advisor] Expired {len(_expired_escs)} stale escalations: {', '.join(_exp_rules)}")
        except Exception as _e_exp:
            print(f"  [advisor] escalation expiry check failed: {_e_exp}")

        # ── Expire stale recommendation drafts (date-based) ───────────
        try:
            from db_adapter import expire_stale_drafts
            _expired_drafts = expire_stale_drafts()
            if _expired_drafts:
                _exp_actions = [f"{r.get('symbol') or '*'}:{r['action']}" for r in _expired_drafts]
                print(f"  [advisor] Expired {len(_expired_drafts)} stale drafts: {', '.join(_exp_actions)}")
        except Exception as _e_dexp:
            print(f"  [advisor] draft expiry check failed: {_e_dexp}")

        if _obs:
            save_advisor_observations(_obs)
            print(f"  [advisor] ✅ {len(_obs)} observations written")

            # ── Escalation scoring (Phase A2-supervisory) ────────────────
            try:
                from db_adapter import save_escalations, _execute
                from datetime import timedelta
                _escalations = []
                _exp_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

                # Get observation IDs for today (for FK linkage)
                _obs_rows = _execute(
                    "SELECT id, symbol, category, evidence FROM advisor_observations WHERE observation_date = %s",
                    (_today,), fetch="all"
                ) or []
                _obs_map = {(r["symbol"] or "", r["category"]): r for r in _obs_rows}

                # Rule 1: concentration_above_15
                for _o in _obs:
                    if _o["category"] == "concentration":
                        _pct = (_o.get("evidence") or {}).get("portfolio_pct", 0)
                        _sym = _o.get("symbol") or ""
                        _obs_ref = _obs_map.get((_sym, "concentration"), {})
                        if _pct >= 20:
                            _escalations.append({
                                "observation_id": _obs_ref.get("id"),
                                "symbol": _sym, "severity": 1, "category": "concentration",
                                "trigger_rule": "concentration_above_20",
                                "summary": f"{_sym} concentration at {_pct:.1f}% exceeds 20% threshold",
                                "evidence": {"portfolio_pct": _pct},
                                "expires_at": _exp_date,
                            })
                        elif _pct >= 15:
                            _escalations.append({
                                "observation_id": _obs_ref.get("id"),
                                "symbol": _sym, "severity": 2, "category": "concentration",
                                "trigger_rule": "concentration_above_15",
                                "summary": f"{_sym} concentration at {_pct:.1f}% exceeds 15% threshold",
                                "evidence": {"portfolio_pct": _pct},
                                "expires_at": _exp_date,
                            })

                # Rule 3: signal_add_present
                for _o in _obs:
                    if _o["category"] == "signal" and (_o.get("evidence") or {}).get("add_count", 0) > 0:
                        _obs_ref = _obs_map.get(("", "signal"), {})
                        _add_count = _o["evidence"]["add_count"]
                        _escalations.append({
                            "observation_id": _obs_ref.get("id"),
                            "symbol": None, "severity": 3, "category": "signal",
                            "trigger_rule": "signal_add_present",
                            "summary": f"{_add_count} ADD signals present in today's signal set",
                            "evidence": _o.get("evidence", {}),
                            "expires_at": _exp_date,
                        })

                # Rule 4: stop_triggered_present
                for _o in _obs:
                    if _o["category"] == "risk" and (_o.get("evidence") or {}).get("triggered", 0) > 0:
                        _obs_ref = _obs_map.get(("", "risk"), {})
                        _trig = _o["evidence"]["triggered"]
                        _escalations.append({
                            "observation_id": _obs_ref.get("id"),
                            "symbol": None, "severity": 1, "category": "risk",
                            "trigger_rule": "stop_triggered_present",
                            "summary": f"{_trig} stop(s) currently triggered",
                            "evidence": _o.get("evidence", {}),
                            "expires_at": _exp_date,
                        })

                # Rule 5: data_stale_24h (check freshness)
                if '_freshness' in dir():
                    _completed = datetime.fromisoformat(_freshness.get("completed_at", "2000-01-01"))
                    _age_h = (datetime.now() - _completed).total_seconds() / 3600
                    if _age_h > 24:
                        _obs_ref = _obs_map.get(("", "freshness"), {})
                        _escalations.append({
                            "observation_id": _obs_ref.get("id"),
                            "symbol": None, "severity": 2, "category": "freshness",
                            "trigger_rule": "data_stale_24h",
                            "summary": f"Portfolio data freshness exceeds 24h threshold ({_age_h:.0f}h old)",
                            "evidence": {"age_hours": round(_age_h, 1)},
                            "expires_at": _exp_date,
                        })

                if _escalations:
                    save_escalations(_escalations)
                    print(f"  [advisor] ✅ {len(_escalations)} escalations queued")

                # ── Dashboard-only notifications for severity 3 escalations ──
                try:
                    from db_adapter import notification_already_logged, save_notification_log_entry
                    _s3 = [e for e in _escalations if e.get("severity") == 3]
                    # Look up actual escalation row ids from DB (save_escalations doesn't return them)
                    from db_adapter import get_escalations_by_date_severity
                    _s3_db = get_escalations_by_date_severity(_today, 3)
                    _s3_id_map = {r["trigger_rule"]: r["id"] for r in _s3_db}
                    _dash_logged = 0
                    for _e3 in _s3:
                        _dk3 = f"{_today}:info:dashboard:s3_{_e3['trigger_rule']}"
                        if notification_already_logged(_dk3):
                            continue
                        _esc_id = _s3_id_map.get(_e3["trigger_rule"])
                        save_notification_log_entry({
                            "notification_date": _today,
                            "notification_type": "info",
                            "channel": "dashboard",
                            "subject": _e3["trigger_rule"].replace("_", " ").title(),
                            "body_summary": _e3["summary"],
                            "escalation_ids": [_esc_id] if _esc_id else None,
                            "payload": {"severity": 3, "category": _e3.get("category"), "evidence": _e3.get("evidence")},
                            "status": "sent",
                            "dedupe_key": _dk3,
                            "sent_at": datetime.now().isoformat(),
                        })
                        _dash_logged += 1
                    if _dash_logged:
                        print(f"  [notifications] {_dash_logged} severity-3 dashboard notification(s) logged")
                except Exception as _dn_e:
                    print(f"  [notifications] dashboard logging failed: {_dn_e}")

            except Exception as _esc_e:
                print(f"  [advisor] Escalation scoring failed (pipeline continues): {_esc_e}")

            # ── Recommendation Drafts (from severity 1-2 escalations) ────
            try:
                from db_adapter import save_advisor_recommendations, _execute as _rec_exec
                from datetime import timedelta as _td_rec
                _rec_exp = (datetime.now() + _td_rec(days=14)).strftime("%Y-%m-%d")
                _drafts = []

                # Get today's severity 1-2 escalations with IDs
                _esc_rows = _rec_exec(
                    "SELECT id, symbol, severity, category, trigger_rule, summary, evidence FROM escalation_queue WHERE created_at::date = %s AND severity <= 2",
                    (_today,), fetch="all"
                ) or []

                # Get Yahoo analyst targets for context
                _yahoo_ctx = {}
                _yahoo_rows = _rec_exec(
                    "SELECT symbol, current_price, target_mean_price, recommendation_key, number_of_analyst_opinions FROM yahoo_analyst_targets_history WHERE snapshot_date = %s",
                    (_today,), fetch="all"
                ) or []
                for _yr in _yahoo_rows:
                    _yahoo_ctx[_yr["symbol"]] = _yr

                # Pre-fetch article context for all symbols (last 7 days)
                _article_ctx = {}
                try:
                    _art_rows = _rec_exec(
                        """SELECT portfolio_symbol, COUNT(*) AS cnt,
                           COUNT(*) FILTER (WHERE llm_category='analyst') AS analyst_cnt,
                           MAX(published_at) AS most_recent,
                           array_agg(DISTINCT llm_category) FILTER (WHERE llm_category IS NOT NULL) AS categories
                           FROM article_index
                           WHERE published_at >= now() - interval '7 days' AND portfolio_symbol IS NOT NULL AND portfolio_symbol != ''
                           GROUP BY portfolio_symbol""",
                        fetch="all"
                    ) or []
                    for _ar in _art_rows:
                        _article_ctx[_ar["portfolio_symbol"]] = _ar
                except Exception:
                    pass

                # Also get top 3 article titles per symbol for evidence
                _article_titles = {}
                try:
                    _title_rows = _rec_exec(
                        """SELECT DISTINCT ON (portfolio_symbol, title) portfolio_symbol, title, source, llm_category, published_at
                           FROM article_index
                           WHERE published_at >= now() - interval '7 days' AND portfolio_symbol IS NOT NULL AND portfolio_symbol != ''
                           ORDER BY portfolio_symbol, title, published_at DESC""",
                        fetch="all"
                    ) or []
                    for _tr in _title_rows:
                        _sym_key = _tr["portfolio_symbol"]
                        if _sym_key not in _article_titles:
                            _article_titles[_sym_key] = []
                        if len(_article_titles[_sym_key]) < 3:
                            _article_titles[_sym_key].append({"title": _tr["title"], "source": _tr["source"], "category": _tr["llm_category"]})
                except Exception:
                    pass

                for _esc in _esc_rows:
                    _esc_sym = _esc.get("symbol") or ""
                    _trigger = _esc["trigger_rule"]
                    _sev = _esc["severity"]

                    # Map trigger -> action type
                    if _trigger in ("concentration_above_15", "concentration_above_20"):
                        _action = "ALLOCATION_REVIEW"
                    elif _trigger == "stop_triggered_present":
                        _action = "STOP_REVIEW"
                    elif _trigger == "data_stale_24h":
                        _action = "DATA_FRESHNESS_REVIEW"
                    else:
                        continue

                    # Confidence
                    _conf = 0.90 if _sev == 1 else 0.80

                    # Build rationale
                    _rationale = _esc["summary"] + "."
                    _yahoo_info = _yahoo_ctx.get(_esc_sym)
                    if _yahoo_info and _yahoo_info.get("target_mean_price"):
                        _rationale += (
                            f" Yahoo analyst context: {_yahoo_info['number_of_analyst_opinions']} analysts, "
                            f"mean target ${_yahoo_info['target_mean_price']:.0f}, "
                            f"consensus: {_yahoo_info['recommendation_key']}."
                        )
                    # Article context (optional, non-blocking)
                    _art_info = _article_ctx.get(_esc_sym)
                    if _art_info and _art_info.get("cnt", 0) > 0:
                        _art_cats = [c for c in (_art_info.get("categories") or []) if c and c != "noise"]
                        if _art_cats:
                            _rationale += f" Recent coverage includes {', '.join(_art_cats[:3])} articles ({_art_info['cnt']} in 7d)."
                        else:
                            _rationale += f" Recent catalyst coverage active ({_art_info['cnt']} articles in 7d)."
                    _rationale += f" Pending review (severity {_sev})."

                    # Evidence
                    _evidence = {
                        "trigger_rule": _trigger,
                        "severity": _sev,
                        "escalation_summary": _esc["summary"],
                    }
                    if _yahoo_info:
                        _evidence["yahoo_analyst"] = {
                            "current_price": _yahoo_info.get("current_price"),
                            "target_mean_price": _yahoo_info.get("target_mean_price"),
                            "recommendation_key": _yahoo_info.get("recommendation_key"),
                            "number_of_analyst_opinions": _yahoo_info.get("number_of_analyst_opinions"),
                        }
                    if _art_info:
                        _evidence["article_context"] = {
                            "article_count_7d": _art_info.get("cnt", 0),
                            "analyst_article_count": _art_info.get("analyst_cnt", 0),
                            "categories": _art_info.get("categories"),
                            "most_recent_article_at": str(_art_info.get("most_recent", ""))[:19],
                            "top_titles": _article_titles.get(_esc_sym, []),
                        }

                    _dedupe = f"{_today}:{_esc_sym or 'portfolio'}:{_action}:{_trigger}"
                    _drafts.append({
                        "recommendation_date": _today,
                        "symbol": _esc_sym or None,
                        "action": _action,
                        "rationale": _rationale,
                        "confidence": _conf,
                        "model": "rule",
                        "escalation_ids": [_esc["id"]],
                        "observation_ids": None,
                        "evidence_summary": _evidence,
                        "status": "draft",
                        "expires_at": _rec_exp,
                        "dedupe_key": _dedupe,
                    })

                if _drafts:
                    save_advisor_recommendations(_drafts)
                    print(f"  [advisor] ✅ {len(_drafts)} recommendation drafts created")
            except Exception as _rde:
                print(f"  [advisor] Recommendation drafts failed (pipeline continues): {_rde}")

    except Exception as _aoe:
        print(f"  [advisor] Observations write failed (pipeline continues): {_aoe}")

    # ── Action Queue: queue threshold-qualifying drafts for human review ────
    # Thresholds per plan: severity 1 >= 0.90 (urgent), severity 2 >= 0.85 (normal)
    try:
        from db_adapter import action_queue_already_exists, save_action_queue_entry, get_escalations_by_date_severity
        _s1_rules = set(e["trigger_rule"] for e in get_escalations_by_date_severity(date_str, 1))
        _s2_rules = set(e["trigger_rule"] for e in get_escalations_by_date_severity(date_str, 2))
        from db_adapter import get_high_confidence_drafts
        # Fetch all drafts (threshold applied below per severity)
        _today_drafts = get_high_confidence_drafts(date_str, 0.0)
        _aq_queued = 0
        for _d in _today_drafts:
            _conf = float(_d["confidence"])
            _action = _d["action"].upper()
            # Classify by linked escalation severity
            _is_s1 = _action in ("STOP_REVIEW",) or any(r in _action.lower().replace("_", "") for r in _s1_rules)
            _is_s2 = _action in ("ALLOCATION_REVIEW",) or any(r in _action.lower().replace("_", "") for r in _s2_rules)
            # Apply threshold gate
            if _is_s1 and _conf >= 0.90:
                _urgency = "urgent"
            elif _is_s2 and _conf >= 0.85:
                _urgency = "normal"
            else:
                continue  # below threshold — stays as draft only
            _sym = _d["symbol"] or "portfolio"
            _dk = f"{date_str}:{_sym}:{_d['action']}:rec_{_d['id']}"
            if action_queue_already_exists(_dk):
                continue
            save_action_queue_entry({
                "recommendation_id": _d["id"],
                "symbol": _d["symbol"],
                "action": _d["action"],
                "rationale": (_d["rationale"] or "")[:500],
                "confidence": _conf,
                "urgency": _urgency,
                "status": "pending",
                "expires_at": str(_d["expires_at"]) if _d.get("expires_at") else None,
                "dedupe_key": _dk,
            })
            _aq_queued += 1
        if _aq_queued:
            print(f"  [action-queue] {_aq_queued} draft(s) queued for review")
    except Exception as _aqe:
        print(f"  [action-queue] Queue failed (pipeline continues): {_aqe}")

    # ── High-confidence draft Telegram alerts (>= 0.90) ────────────────────
    try:
        from db_adapter import notification_already_logged, save_notification_log_entry, get_high_confidence_drafts
        _hc_drafts = get_high_confidence_drafts(date_str, 0.90)
        _hc_sent = 0
        for _hc in _hc_drafts:
            # Dedup by symbol + action + date (not recommendation ID)
            # Prevents the same draft from firing daily when unresolved.
            _hc_sym = _hc["symbol"] or "Portfolio"
            _hc_dk = f"{date_str}:draft_alert:telegram:{_hc_sym}_{_hc.get('action', 'review')}"
            if notification_already_logged(_hc_dk):
                continue
            _hc_msg = (
                f"\U0001f4cb DRAFT PENDING REVIEW\n\n"
                f"{_hc_sym}: {_hc['action'].replace('_',' ')}\n"
                f"Confidence: {_hc['confidence']}\n\n"
                f"{(_hc['rationale'] or '')[:200]}\n\n"
                f"Status: Draft only \u2014 not actioned, not approved."
            )
            _hc_ok = False
            _hc_err = None
            if _morning_bundle is not None:
                append_section(_morning_bundle, "drafts", _hc_msg)
                _hc_ok = True
            else:
                try:
                    from telegram_alert import send_telegram as _hc_tg
                    _hc_ok = _hc_tg(_hc_msg)
                except Exception as _hc_tge:
                    _hc_err = str(_hc_tge)
            save_notification_log_entry({
                "notification_date": date_str,
                "notification_type": "draft_alert",
                "channel": "telegram",
                "subject": f"{_hc_sym}: {_hc['action'].replace('_',' ')}",
                "body_summary": (_hc["rationale"] or "")[:200],
                "recommendation_ids": [_hc["id"]],
                "payload": {"confidence": float(_hc["confidence"]), "action": _hc["action"], "symbol": _hc["symbol"]},
                "status": "sent" if _hc_ok else "failed",
                "dedupe_key": _hc_dk,
                "sent_at": datetime.now().isoformat() if _hc_ok else None,
                "error": _hc_err,
            })
            _hc_sent += 1
            _status = "\u2705" if _hc_ok else "\u274c"
            print(f"  [notifications] {_status} Draft alert: {_hc_sym} {_hc['action']} (conf={_hc['confidence']})")
        if _hc_sent:
            print(f"  [notifications] {_hc_sent} high-confidence draft alert(s) sent")
    except Exception as _hce:
        print(f"  [notifications] High-confidence draft alerts failed: {_hce}")

    # ── Ollama Daily Summary Enrichment (Phase A2-enrichment) ────────────────
    try:
        import re as _re, urllib.request as _ur
        # Gather today's observations and escalations for prompt
        _obs_today = _execute(
            "SELECT category, symbol, observation FROM advisor_observations WHERE observation_date = %s ORDER BY category",
            (date_str,), fetch="all"
        ) if '_execute' not in dir() else None
        if _obs_today is None:
            from db_adapter import _execute as _ex2
            _obs_today = _ex2(
                "SELECT category, symbol, observation FROM advisor_observations WHERE observation_date = %s ORDER BY category",
                (date_str,), fetch="all"
            ) or []
        _esc_today = []
        try:
            from db_adapter import _execute as _ex3
            _esc_today = _ex3(
                "SELECT severity, symbol, trigger_rule, summary FROM escalation_queue WHERE created_at::date = %s ORDER BY severity",
                (date_str,), fetch="all"
            ) or []
        except Exception:
            pass

        if _obs_today:
            # Format prompt
            _obs_lines = "\n".join(f"- [{r['category']}] {r['observation']}" for r in _obs_today)
            _esc_lines = "\n".join(f"- [severity {r['severity']}] {r['summary']}" for r in _esc_today) if _esc_today else "None"
            _prompt = (
                "/no_think\n"
                "You are a portfolio surveillance system. Summarize today's findings factually.\n\n"
                f"TODAY'S OBSERVATIONS:\n{_obs_lines}\n\n"
                f"TODAY'S ESCALATIONS:\n{_esc_lines}\n\n"
                "RULES:\n"
                "- State WHAT IS, never WHAT SHOULD BE\n"
                "- No recommendations, no 'should', 'consider', 'buy', 'sell'\n"
                "- Order by importance (severity 1 first)\n"
                "- Include key numbers\n"
                "- Maximum 3 sentences\n\n"
                "SUMMARY:"
            )
            # Call Ollama (think=False disables qwen3 thinking mode)
            from local_llm_config import get_local_llm_model, get_local_llm_base_url
            _orch_model = get_local_llm_model()
            _orch_base = get_local_llm_base_url().rstrip("/")
            _payload = json.dumps({"model": _orch_model, "stream": False,
                                   "messages": [{"role": "user", "content": _prompt}],
                                   "think": False,
                                   "options": {"temperature": 0.3, "num_predict": 200}}).encode()
            _req = _ur.Request(f"{_orch_base}/api/chat", data=_payload,
                               headers={"Content-Type": "application/json"})
            _resp = _ur.urlopen(_req, timeout=30)
            _result = json.loads(_resp.read().decode())
            _summary = _result.get("message", {}).get("content", "").strip()
            # Strip think tags
            _summary = _re.sub(r"<think>.*?</think>", "", _summary, flags=_re.DOTALL).strip()
            # Validate: reject if advisory language found (as imperatives, not signal labels)
            _BANNED = ["you should", "consider ", "recommend", "i suggest", "rotate into", "trim now", "add to your"]
            _is_valid = not any(b in _summary.lower() for b in _BANNED) and len(_summary) > 20
            if _is_valid:
                from db_adapter import save_advisor_observations
                save_advisor_observations([{
                    "observation_date": date_str,
                    "symbol": "",
                    "category": "daily_summary",
                    "observation": _summary[:500],
                    "evidence": {"observation_count": len(_obs_today), "escalation_count": len(_esc_today),
                                 "model": _orch_model, "prompt_tokens": len(_prompt.split())},
                    "source": "ollama:enrichment",
                    "confidence": 0.85,
                    "model": f"ollama:{_orch_model}",
                    "freshness_hash": _freshness.get("holdings_hash", "") if '_freshness' in dir() else "",
                }])
                print(f"  [enrichment] ✅ Daily summary written ({len(_summary)} chars)")
            else:
                print(f"  [enrichment] ⚠️  Summary rejected (banned language or too short)")
    except Exception as _enr_e:
        print(f"  [enrichment] Skipped ({_enr_e})")

    # ── Urgent Telegram Notifications (severity 1 escalations) ───────────────
    try:
        from db_adapter import notification_already_logged, save_notification_log_entry, get_escalations_by_date_severity
        _s1_escalations = get_escalations_by_date_severity(date_str, 1)
        _notif_sent = 0
        for _s1 in _s1_escalations:
            # Dedup by symbol + trigger_rule + date (not escalation ID)
            # This prevents the same stop condition from firing a new alert
            # every day when the underlying issue hasn't been resolved.
            _s1_sym = _s1.get("symbol", "unknown")
            _s1_rule = _s1.get("trigger_rule", "unknown")
            _dk = f"{date_str}:urgent_alert:telegram:{_s1_sym}_{_s1_rule}"
            if notification_already_logged(_dk):
                continue
            # Build message
            _age_h = 0
            if '_freshness' in dir() and _freshness.get("completed_at"):
                try:
                    _age_h = round((datetime.now() - datetime.fromisoformat(_freshness["completed_at"])).total_seconds() / 3600, 1)
                except Exception:
                    pass
            _msg = (
                f"\U0001f6a8 {_s1['trigger_rule'].upper().replace('_',' ')}\n\n"
                f"{_s1['summary']}\n\n"
                f"Severity: 1 (urgent)\n"
                f"Data freshness: {_age_h}h"
            )
            # Send (or defer to morning bundle)
            _send_ok = False
            _send_err = None
            if _morning_bundle is not None:
                append_section(_morning_bundle, "stops", _msg)
                _send_ok = True
            else:
                try:
                    from telegram_alert import send_telegram as _tg_send
                    _send_ok = _tg_send(_msg)
                except Exception as _tge:
                    _send_err = str(_tge)
            # Log
            save_notification_log_entry({
                "notification_date": date_str,
                "notification_type": "urgent_alert",
                "channel": "telegram",
                "subject": _s1["trigger_rule"].replace("_", " ").title(),
                "body_summary": _s1["summary"],
                "escalation_ids": [_s1["id"]],
                "payload": {"telegram_text": _msg, "freshness_hash": _freshness.get("holdings_hash", "") if '_freshness' in dir() else ""},
                "status": "sent" if _send_ok else "failed",
                "dedupe_key": _dk,
                "sent_at": datetime.now().isoformat() if _send_ok else None,
                "error": _send_err,
            })
            if _send_ok:
                _notif_sent += 1
            if _notif_sent >= 2:  # rate cap
                break
        if _notif_sent:
            print(f"  [notifications] \u2705 {_notif_sent} urgent alert(s) sent via Telegram")
    except Exception as _ne:
        print(f"  [notifications] Failed (pipeline continues): {_ne}")

    # ── Morning Command bundle (single Telegram replaces 09:28 burst) ─────────
    if _morning_bundle:
        try:
            _hm = fetch_hermes_movers()
            if _hm:
                append_section(_morning_bundle, "hermes", _hm)
            send_morning_command_bundle(_morning_bundle, root)
        except Exception as _mce:
            print(f"  [morning-command] Bundle send failed: {_mce}")

    # ── Gmail Daily Digest ───────────────────────────────────────────────────
    try:
        from db_adapter import notification_already_logged, save_notification_log_entry, _execute as _digest_exec
        _digest_dk = f"{date_str}:daily_digest:gmail:daily"
        if not notification_already_logged(_digest_dk):
            # Gather digest content
            _d_summary = (_digest_exec(
                "SELECT observation FROM advisor_observations WHERE observation_date=%s AND category='daily_summary' LIMIT 1",
                (date_str,), fetch="one"
            ) or {}).get("observation", "No daily summary available.")

            _d_escs = _digest_exec(
                "SELECT severity, symbol, summary FROM escalation_queue WHERE created_at::date=%s ORDER BY severity",
                (date_str,), fetch="all"
            ) or []

            _d_drafts = _digest_exec(
                "SELECT symbol, action, confidence, rationale FROM advisor_recommendations WHERE recommendation_date=%s",
                (date_str,), fetch="all"
            ) or []

            _d_ai_wl = _digest_exec(
                "SELECT symbol, confidence FROM watchlist_items WHERE source_type='ai_generated' AND status='active'",
                fetch="all"
            ) or []

            # Portfolio value
            _d_tv = portfolio.get("portfolio_totals", {}).get("total_value", 0)
            _d_periods = perf_history.get("periods", {}) if perf_history else {}

            # Build HTML body
            _subject = f"[OpenClaw] Daily Portfolio Digest \u2014 {date_str}"
            _sections = []
            _sections.append(f"<h3>\U0001f4ca Daily Summary</h3><p>{_d_summary.replace(chr(10), '<br>')}</p>")

            if _d_escs:
                _esc_lines = "".join(f"<li>[S{e['severity']}] {e.get('symbol') or 'Portfolio'}: {e['summary']}</li>" for e in _d_escs)
                _sections.append(f"<h3>\u26a1 Escalations ({len(_d_escs)} pending)</h3><ul>{_esc_lines}</ul>")

            if _d_drafts:
                _draft_lines = "".join(
                    f"<li><b>{d['action']}</b>{' for ' + d['symbol'] if d.get('symbol') else ''} "
                    f"(conf {float(d['confidence']):.0%}) &mdash; <i>Draft pending review</i></li>"
                    for d in _d_drafts
                )
                _sections.append(f"<h3>\U0001f4cb Recommendation Drafts ({len(_d_drafts)} pending review)</h3><ul>{_draft_lines}</ul>")

            if _d_ai_wl:
                _wl_syms = ", ".join(f"{w['symbol']} ({float(w['confidence']):.0%})" for w in _d_ai_wl[:5])
                _sections.append(f"<h3>\U0001f441 AI Watchlist</h3><p>{len(_d_ai_wl)} active: {_wl_syms}</p>")

            _ytd = _d_periods.get("YTD", {}).get("change_pct")
            _1w = _d_periods.get("1W", {}).get("change_pct")
            _perf_line = f"${_d_tv:,.0f}"
            if _ytd is not None: _perf_line += f" | YTD {_ytd:+.1f}%"
            if _1w is not None: _perf_line += f" | 1W {_1w:+.1f}%"
            _sections.append(f"<h3>\U0001f4c8 Portfolio</h3><p>{_perf_line}</p>")

            _h_hash = _freshness.get("holdings_hash", "") if '_freshness' in dir() else ""
            _sections.append(f"<hr><p style='font-size:11px;color:#888'>Data freshness: pipeline just completed | Hash: {_h_hash}</p>")

            _body_html = f"<div style='font-family:sans-serif;max-width:600px'>" + "".join(_sections) + "</div>"

            # Send via gog (set keyring password for non-interactive)
            import subprocess as _sp
            _gog_env = dict(os.environ)
            _kr_path = Path.home() / ".openclaw" / "credentials" / "gog_keyring_password"
            if _kr_path.exists():
                _gog_env["GOG_KEYRING_PASSWORD"] = _kr_path.read_text().strip()
            _gog_bin = str(Path.home() / ".local" / "bin" / "gog")
            _send_result = _sp.run(
                [_gog_bin, "gmail", "send",
                 "-a", "john@jwwhiting.com",
                 "--to", "john@jwwhiting.com",
                 "--subject", _subject,
                 "--body-html", _body_html],
                capture_output=True, text=True, timeout=30,
                env=_gog_env
            )
            _send_ok = _send_result.returncode == 0
            _send_err = _send_result.stderr.strip() if not _send_ok else None

            save_notification_log_entry({
                "notification_date": date_str,
                "notification_type": "daily_digest",
                "channel": "gmail",
                "subject": _subject,
                "body_summary": _d_summary[:200],
                "escalation_ids": [e["id"] for e in _d_escs] if _d_escs and _d_escs[0].get("id") else None,
                "payload": {"subject": _subject, "body_html_length": len(_body_html), "sections": len(_sections), "freshness_hash": _h_hash},
                "status": "sent" if _send_ok else "failed",
                "dedupe_key": _digest_dk,
                "sent_at": datetime.now().isoformat() if _send_ok else None,
                "error": _send_err,
            })
            if _send_ok:
                print(f"  [notifications] \u2705 Daily digest sent via Gmail")
            else:
                print(f"  [notifications] \u26a0\ufe0f  Gmail digest failed: {_send_err}")
    except Exception as _gde:
        print(f"  [notifications] Gmail digest failed (pipeline continues): {_gde}")

    print("="*60)

    return dict(portfolio=portfolio, analysis=analysis, tax=tax, rebalancing=rebalancing,
                risk=risk, chart_paths=chart_paths, performance=performance, ai_analysis=ai_analysis)

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Portfolio Intelligence v1.2")
    p.add_argument("--project-root", default=".")
    p.add_argument("--run-label",    default="manual")
    p.add_argument("--run-type",     default="daily", choices=["daily","monthly","manual"])
    p.add_argument("--no-report",    action="store_true")
    args = p.parse_args()
    try:
        run_portfolio_pipeline(Path(args.project_root), args.run_label, not args.no_report, args.run_type)
    except Exception as e:
        print(f"\n❌ {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
