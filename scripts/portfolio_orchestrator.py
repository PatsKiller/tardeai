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
            for a in stop_alerts:
                _send_telegram(a["msg"], root)
                print(f"  [stops] Alert sent: {a['msg'][:60]}")
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
        alert_counts = run_portfolio_alerts(portfolio, analysis, root)
        total_alerts = sum(alert_counts.values())
        print(f"  ✅ {total_alerts} alert(s) sent → Telegram")
    except Exception as e:
        print(f"  [alerts] Error: {e}")

    # Technical signal alerts
    if technical.get("signal_changes"):
        try:
            n_sig = send_technical_alerts(technical, root)
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
        # Recompute portfolio-level from all accounts with sanity filter
        # (runs unconditionally — even if Fidelity block above was skipped)
        _MAX = {"1D":15,"1W":30,"1M":50,"3M":80,"6M":100,"YTD":150,"1Y":200}
        _total_current = sum(a.get("current_value",0) for a in _ph.get("accounts",{}).values() if isinstance(a,dict))
        for _lbl in ["1D","1W","1M","3M","6M","YTD","1Y"]:
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
        json.dump(_ph, open(state_dir / "performance_history.json", "w"), indent=2, default=str)
        perf_history = _ph  # update for dashboard rebuild below
    except Exception as e:
        print(f"  [fidelity-perf] Error: {e}")

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
