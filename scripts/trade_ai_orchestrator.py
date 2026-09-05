"""trade_ai_orchestrator.py — Trade AI v12 master pipeline.

v12 adds 5 new stages over v11:
  - Short interest enrichment (squeeze flags from Finviz data)
  - Squeeze bonus applied to scoring
  - Halt detection (NASDAQ feed + Polygon + catalyst news)
  - Trade plan generation (Claude Sonnet, A+ tickers only)
  - Telegram alerts (alongside WhatsApp)

v12.1 additions (Finviz API + social sentiment):
  - Finviz news_export.ashx as catalyst source 6 (token auth, no cookie expiry)
  - Yahoo Finance RSS/JSON as catalyst source 7 (no key required)
  - Social sentiment stage 12b: Reddit WSB/stocks + StockTwits (no keys needed)
  - social_data wired into dashboard, run_summary, and alerts

Full 23-stage pipeline:
  0  Market open check
  1  Weekly hygiene
  2  Finviz ingestion
  3  Market context        (SPY/QQQ/IWM, 11 sectors, VIX)
  4  Economic calendar     (Fed, CPI, earnings via FMP)
  5  Catalyst enrichment   (7 sources: Finnhub/NewsAPI/Polygon/FMP/AlphaV/Finviz/Yahoo)
  6  Options flow          (Polygon)
  7  Short interest        ★ v12 — squeeze flags from Finviz short float %
  8  Sector momentum       (inject sector_momentum_score)
  9  Trend engine          (trend arrows)
  10 Scoring               (6 pillars, max 55)
  11 Squeeze bonus         ★ v12 — apply short interest catalyst bonus
  12 Halt detection        ★ v12 — NASDAQ + Polygon + catalyst scan
  12b Social sentiment     ★ v12.1 — Reddit WSB/stocks + StockTwits
  13 Delta tracking        (state.json, consecutive GO days)
  14 Trade plans           ★ v12 — Sonnet A+ trade plans
  15 HTML dashboard        (auto-refresh 60s, TOS export, trade plan cards, social badges)
  16 PDF generation
  17 Word document
  18 TOS export
  19 Save state
  20 Run summary           (includes social_tickers_scanned, social_bullish_count)
  21 Alerts (WhatsApp + Telegram + Email + Slack)  ★ v12
"""
from __future__ import annotations
import argparse, json, os, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:  # CI hardening image has no python-dotenv; .env is optional
    def load_dotenv(*_a, **_k):
        return False

# NEW: Dashboard generator for single persistent file
try:
    from dashboard_copier import create_persistent_dashboard
    _HAS_DASHBOARD_COPIER = True
except ImportError:
    _HAS_DASHBOARD_COPIER = False

import sys

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass
# Force UTF-8 output so emojis work when piped to log files on Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    import exchange_calendars as xcals
    _HAS_XCAL = True
except Exception:
    _HAS_XCAL = False


def _market_open(date_str: str) -> bool:
    if _HAS_XCAL:
        try:
            return xcals.get_calendar("XNYS").is_session(date_str)
        except Exception:
            pass
    return datetime.fromisoformat(date_str).weekday() < 5

def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

# Stage errors accumulate so a failure summary can name what broke — not just
# an exit code. Health-recovery success rows already carry `rc=` /
# `rate_limit_hits=`; failing runs historically stored only `{"errors": "2"}`.
_STAGE_ERRORS: list[dict] = []


def _ok(s, m):   print(f"  \u2705  {s:<24}  {m}")
def _err(s, m):
    _STAGE_ERRORS.append({"stage": s, "error": str(m)[:300]})
    print(f"  \u274c  {s:<24}  {m}")
def _skip(s, m): print(f"  \u23ed\ufe0f  {s:<24}  {m}")


def _count_rate_limit_hits(root: Path, hours: int = 2) -> int:
    """Same sensor the health-recovery success note already quotes.

    Failing runs used to leave this off the summary entirely, so a
    yfinance-rate-limit death looked identical to an argparse exit.
    """
    import re
    n = 0
    cutoff = datetime.now().timestamp() - hours * 3600
    for name in ("screener_pm.log", "portfolio_orchestrator.log", "trade_ai_orchestrator.log"):
        p = root / "logs" / name
        try:
            if not p.is_file() or p.stat().st_mtime < cutoff:
                continue
            text = p.read_text(errors="ignore")[-400_000:]
            n += len(re.findall(r"Too Many Requests|Rate limited", text, re.I))
        except Exception:
            continue
    return n


def format_failure_diagnostic(
    *,
    rc: str,
    rate_limit_hits: int,
    reasons=None,
    symbols: int = 0,
    stage_errors: int | None = None,
    extra: str = "",
) -> str:
    """Match the health-recovery success note shape: `rc=...; rate_limit_hits=...`.

    PipelineRun.run_fail stores SystemExit's string in summary.errors — so the
    failure path must put the diagnostic HERE, or the row stays opaque.
    """
    parts = [f"rc={rc}", f"rate_limit_hits={rate_limit_hits}", f"symbols={symbols}"]
    if reasons is not None:
        parts.append(f"reasons={list(reasons)}")
    if stage_errors is None:
        stage_errors = len(_STAGE_ERRORS)
    parts.append(f"stage_errors={stage_errors}")
    if extra:
        parts.append(extra)
    return "; ".join(parts)


def write_failure_run_summary(output_dir: Path, payload: dict) -> Path:
    """Failure must reach a surface, not just a log line / pipeline_runs.errors."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "run_summary.json"
    doc = dict(payload)
    doc.setdefault("status", "FAILED")
    doc.setdefault("generated_at", datetime.now().isoformat(timespec="seconds"))
    path.write_text(json.dumps(doc, indent=2, default=str))
    return path


def _inject_sector_scores(tickers, sectors):
    if not sectors:
        return
    ranked = sorted(sectors, key=lambda s: s.get("change_percent", 0), reverse=True)
    top3 = {s["symbol"] for s in ranked[:3]}
    top6 = {s["symbol"] for s in ranked[:6]}
    sector_name_map = {
        "Technology": "XLK", "Financials": "XLF", "Energy": "XLE",
        "Healthcare": "XLV", "Consumer Disc.": "XLY", "Industrials": "XLI",
        "Consumer Stapl.": "XLP", "Utilities": "XLU", "Real Estate": "XLRE",
        "Materials": "XLB", "Comm. Services": "XLC",
    }
    # Smooth percentile pillar (2026-06-11): the old 5/3/1/0 cliff meant a 4th-ranked sector scored like a
    # laggard. Now: 0-5 scaled by the sector's percentile rank among the 11 ETFs (top=5.0, median~2.5).
    etf_rank = {s["symbol"]: idx for idx, s in enumerate(ranked)}
    n_sec = max(1, len(ranked) - 1)
    for t in tickers:
        etf = sector_name_map.get(t.get("sector", ""), "")
        if etf in etf_rank:
            pct = 1.0 - (etf_rank[etf] / n_sec)
            t["sector_momentum_score"] = round(5 * pct, 1)
        else:
            t["sector_momentum_score"] = 1   # unknown sector: small neutral credit, not zero


def run_pipeline(root, run_label, date_str, use_llm=True, send_alerts=True, skip_market_check=False, institutional=False, min_symbols=40, allow_underfilled=False):
    _STAGE_ERRORS.clear()
    print(f"\n{'='*66}")
    print(f"  \u26a1 Trade AI v12  |  Run {run_label}  |  {date_str}")
    print(f"{'='*66}\n")
    # Resolve caller's argparse.Namespace (only set when called from main())
    try:
        _caller_args = args  # noqa: F821 \u2014 caller scope
    except NameError:
        _caller_args = None
    if not skip_market_check and not _market_open(date_str):
        print(f"  \u23f8  NYSE closed {date_str}. Use --skip-market-check to force.\n")
        return 0

    output_dir = _ensure(root / os.getenv("REPORT_OUTPUT_DIR","reports") / date_str / run_label)
    # Publish gate: RUN_FAILED / RUN_UNDERFILLED must not stamp dashboard/PDF/live
    # as a successful run (B3). allow_underfilled keeps the old continue-anyway path.
    _publish_artifacts = True
    _health_status = None
    _health_reasons = []

    # 1 Weekly hygiene
    try:
        from weekly_hygiene import clean_weekly, is_new_week
        if is_new_week(date_str):
            r = clean_weekly(root, date_str, keep_logs=True)
            _ok("weekly_hygiene", f"Archived {len(r.get('archived',[]))} paths")
        else:
            _skip("weekly_hygiene", "Not Monday")
    except Exception as exc:
        _err("weekly_hygiene", str(exc))

    # 2 Finviz ingestion
    try:
        from finviz_ingestion import load_live_candidates
        live    = load_live_candidates(root, run_label, date_str, output_dir)
        df      = live["dataframe"]
        if df.empty:
            _err("finviz_ingestion", "No tickers — continuing with cached data")
            # Fall back to cached tickers from last successful run
            _cache = root / "data" / "scored_tickers_latest.json"
            if _cache.exists():
                import json, time as _t
                _age_h = (_t.time() - _cache.stat().st_mtime) / 3600
                if _age_h > 2.5:
                    # Stale-cache guard (2026-06-11): a failed run silently fed the NEXT run hours-old data.
                    _err("finviz_ingestion", f"cache is {_age_h:.1f}h old (>2.5h) — refusing stale fallback")
                    tickers = []
                else:
                    tickers = json.loads(_cache.read_text())
                    try:
                        import sys as _sys_uc
                        _uc_lib = root / "scripts" / "lib"
                        if str(_uc_lib) not in _sys_uc.path:
                            _sys_uc.path.insert(0, str(_uc_lib))
                        from universe_coverage import inject_prime_setup_universe
                        from ross_catalog_universe import inject_ross_catalog_universe
                        inject_prime_setup_universe(tickers, root, limit=30, min_change_pct=5.0)
                        _rc = inject_ross_catalog_universe(tickers, root, date_str)
                        if _rc:
                            _ok("ross_catalog_universe", f"+{_rc} Ross catalog alias injects")
                    except Exception:
                        pass
                    _ok("finviz_ingestion", f"Using {len(tickers)} cached tickers from last run ({_age_h:.1f}h old)")
            else:
                _err("finviz_ingestion", "No cache available — skipping scoring")
                tickers = []
        else:
            tickers = df.to_dict(orient="records")
            try:
                import sys as _sys_uc
                _uc_lib = root / "scripts" / "lib"
                if str(_uc_lib) not in _sys_uc.path:
                    _sys_uc.path.insert(0, str(_uc_lib))
                from universe_coverage import inject_prime_setup_universe
                from ross_catalog_universe import inject_ross_catalog_universe
                _inj = inject_prime_setup_universe(tickers, root, limit=30, min_change_pct=5.0)
                if _inj:
                    _ok("universe_coverage", f"+{_inj} Finviz top-gainer injects")
                _rc = inject_ross_catalog_universe(tickers, root, date_str)
                if _rc:
                    _ok("ross_catalog_universe", f"+{_rc} Ross catalog alias injects")
            except Exception as _uc_exc:
                _err("universe_coverage", str(_uc_exc))
            _ok("finviz_ingestion", f"{len(tickers)} tickers  |  {len(live.get('downloads',[]))} screeners")
            # Save cache for next time
            try:
                import json
                (root / "data" / "scored_tickers_latest.json").write_text(json.dumps(tickers, default=str))
            except Exception:
                pass
    except Exception as exc:
        _err("finviz_ingestion", str(exc))
        tickers = []

    # 3 Market context
    market_snapshot: dict = {}
    try:
        from market_context import get_market_snapshot
        market_snapshot = get_market_snapshot()
        spy_pct = market_snapshot.get("indices",{}).get("SPY",{}).get("change_percent",0)
        vix     = market_snapshot.get("vix",{}).get("price",0)
        breadth = market_snapshot.get("breadth_label","?")
        leader  = market_snapshot.get("sector_leader",{}).get("symbol","?")
        laggard = market_snapshot.get("sector_laggard",{}).get("symbol","?")
        _ok("market_context", f"SPY {spy_pct:+.2f}%  VIX {vix:.1f}  {breadth}  ▲{leader}  ▼{laggard}")
    except Exception as exc:
        _err("market_context", f"{exc}  — continuing without market data")

    # 4 Economic calendar
    calendar: dict = {}
    try:
        from economic_calendar import get_calendar
        calendar = get_calendar(scored_tickers=tickers)
        _ok("economic_calendar",
            f"{len(calendar.get('high_impact_events',[]))} hi-impact  |  "
            f"{len(calendar.get('earnings',[]))} earnings  |  "
            f"watchlist: {calendar.get('watchlist_earnings',[])}")
    except Exception as exc:
        _err("economic_calendar", f"{exc}  — continuing")

    # 2.5 Finviz enrichment — float, RVOL, RSI, SMA for all tickers
    fv_enriched = {}
    if use_llm:
        try:
            from finviz_enrichment import enrich_tickers
            syms = [t.get("symbol","") for t in tickers if t.get("symbol")]
            fv_enriched = enrich_tickers(syms, project_root=str(root),
                                         skip_fundamentals=True)
            # Inject float + RVOL into tickers (critical for scoring)
            updated = 0
            for t in tickers:
                sym = t.get("symbol","")
                e = fv_enriched.get(sym, {})
                if e.get("float_m"):
                    t["float_m"] = e["float_m"]
                    updated += 1
                if e.get("rvol"):
                    t["relative_volume"] = e["rvol"]
                # Also inject RSI/SMA for technical context
                for field in ["rsi","sma20_pct","sma50_pct","sma200_pct",
                               "beta","atr","trend","rsi_status",
                               "short_float_pct","perf_week_pct"]:
                    if e.get(field) is not None:
                        t[field] = e[field]
            _ok("finviz_enrichment",
                f"{len(fv_enriched)} enriched | {updated} float/RVOL updated")
        except Exception as exc:
            _err("finviz_enrichment", f"{exc} — continuing without enrichment")

    # 5 Catalyst enrichment — two-pass (pre-score filter first)
    enrichments: dict = {}
    try:
        from catalyst_enrichment import enrich_all
        from scoring import filter_candidates

        # Pass 1: pre-score all tickers with no API calls
        candidate_syms, tickers = filter_candidates(
            tickers, project_root=str(root), min_pre_score=5
        )
        _ok("pre_score_filter",
            f"{len(candidate_syms)} candidates from {len(tickers)} tickers "
            f"(skipping {len(tickers)-len(candidate_syms)} low-scorers)")

        # Pass 2: enrich only candidates
        candidate_rows = [t for t in tickers if t.get("symbol","").upper() in set(candidate_syms)]
        enrichments = enrich_all(candidate_rows)
        _ok("catalyst_enrichment",
            f"{sum(e.get('catalyst_count',0) for e in enrichments.values())} articles  |  "
            f"{sum(1 for e in enrichments.values() if e.get('has_fresh_catalyst'))} fresh  |  "
            f"{len(candidate_syms)} tickers enriched (not {len(tickers)})")
    except Exception as exc:
        _err("catalyst_enrichment", f"{exc}  — continuing")

    # 6 Catalyst intelligence — Ollama classification + memory (pre-market full runs only)
    catalyst_intel: dict = {}
    if use_llm and enrichments:
        try:
            from catalyst_intelligence import analyze_all_catalysts
            catalyst_intel = analyze_all_catalysts(
                candidate_rows, enrichments, project_root=str(root)
            )
            # Merge Ollama flags back into enrichments
            for sym, intel in catalyst_intel.items():
                if sym in enrichments and intel.get("ollama_ok"):
                    enrichments[sym]["ollama_flag"] = intel.get("ollama_flag", "NEUTRAL")
                    enrichments[sym]["ollama_risk"] = intel.get("ollama_risk", "")
                    enrichments[sym]["ollama_summary"] = intel.get("ollama_summary", "")
                    enrichments[sym]["catalyst_type"] = intel.get("catalyst_type", "other")
                    # Override catalyst score if Ollama scored it
                    if intel.get("ollama_catalyst_score") is not None:
                        enrichments[sym]["ollama_catalyst_score"] = intel["ollama_catalyst_score"]
            traps = sum(1 for i in catalyst_intel.values() if i.get("ollama_flag") in ("TRAP","DILUTION"))
            go_signals = sum(1 for i in catalyst_intel.values() if i.get("ollama_flag") == "GO")
            _ok("catalyst_intel",
                f"{len(catalyst_intel)} analyzed  |  {go_signals} GO signals  |  {traps} traps flagged")
        except Exception as exc:
            _err("catalyst_intel", f"{exc}  — continuing without Ollama analysis")

    # 6b Options flow — moved to after scoring (see stage 11b below)
    options_flow: dict = {}
    options_summary: dict = {}

    # 7 Short interest (v12)
    short_summary: dict = {}
    try:
        from short_interest import enrich_short_interest
        tickers, short_summary = enrich_short_interest(tickers)
        _ok("short_interest",
            f"{short_summary.get('high_squeeze_count',0)} high-squeeze  |  "
            f"{short_summary.get('moderate_squeeze_count',0)} moderate  |  "
            f"top: {[s['symbol'] for s in short_summary.get('top_squeezers',[])[:3]]}")
    except Exception as exc:
        _err("short_interest", f"{exc}  — continuing without squeeze data")

    # 8 Sector momentum injection
    try:
        _inject_sector_scores(tickers, market_snapshot.get("sectors", []))
        _ok("sector_momentum", f"{sum(1 for t in tickers if t.get('sector_momentum_score',0)>0)} tickers scored")
    except Exception as exc:
        _err("sector_momentum", str(exc))

    # Load state for trend engine
    state: dict = {}
    try:
        from delta_tracker import load_state
        state = load_state(project_root=str(root))
    except Exception:
        pass

    # 9 Trend engine
    try:
        from trend_engine import enrich_all_trends
    except Exception:
        pass

    # 10 Scoring
    scored: list = []
    try:
        from scoring import score_all
        scored     = score_all(tickers, enrichments, project_root=str(root), use_llm=use_llm)
        go_count   = sum(1 for t in scored if t.get("decision") == "GO")
        wait_count = sum(1 for t in scored if t.get("decision") == "WAIT")
        _ok("scoring", f"GO={go_count}  WAIT={wait_count}  AVOID={len(scored)-go_count-wait_count}  {'[LLM ON]' if use_llm else '[LLM OFF]'}")
    except Exception as exc:
        _err("scoring", str(exc)); traceback.print_exc(); return 1

    # 10a Scalp Critic — agent review of scored results
    # Gate critic with --no-llm flag (critic uses LLM but was not gated)
    # Also enforce 120s timeout to prevent blocking the entire pipeline
    critic_summary: dict = {}
    if not use_llm:
        _skip("scalp_critic", "--no-llm flag set — skipping LLM critic")
    else:
        import threading
        _critic_result = [None]
        _critic_error = [None]
        def _run_critic():
            try:
                from scalp_critic_agent import critique_scored_tickers
                _critic_result[0] = critique_scored_tickers(scored, only_go_wait=True, max_tickers=10)
            except Exception as e:
                _critic_error[0] = e
        _ct = threading.Thread(target=_run_critic, daemon=True)
        _ct.start()
        _ct.join(timeout=120)  # Hard 120s cap — never block pipeline longer
        if _ct.is_alive():
            _err("scalp_critic", "TIMEOUT after 120s — continuing without critique (LLM bottleneck)")
        elif _critic_error[0]:
            _err("scalp_critic", f"{_critic_error[0]} — continuing without critique")
        elif _critic_result[0]:
            critic_summary = _critic_result[0]
            blocked = critic_summary.get('blocked', 0)
            downgraded = critic_summary.get('downgraded', 0)
            confirmed = critic_summary.get('confirmed', 0)
            _ok("scalp_critic",
                f"Confirmed={confirmed}  Blocked={blocked}  Downgraded={downgraded}  "
                f"Changes={len(critic_summary.get('changes', []))}")
            if blocked or downgraded:
                try:
                    from scalp_critic_agent import send_telegram_summary
                    send_telegram_summary(critic_summary)
                except Exception:
                    pass
        # Recount after critic overrides
        go_count   = sum(1 for t in scored if t.get("decision") == "GO")
        wait_count = sum(1 for t in scored if t.get("decision") == "WAIT")
        _ok("scoring_post_critic", f"GO={go_count}  WAIT={wait_count}  (after critic review)")

    # 10a-ws: Broadcast scored tickers to live WS feed — non-fatal
    try:
        from scalp_ws_client import broadcast_scalp_update
        _fv_backfilled = 0
        for t in scored:
            if t.get("decision") in ("GO", "WAIT"):
                # RVOL is stored under 'relative_volume' (set from finviz enrich at line ~231); read that first.
                _rv = t.get("relative_volume") or t.get("rvol") or 0
                _chg = t.get("change_pct") or t.get("change_percent") or t.get("change") or ""
                # Backfill from finviz quote.ashx (live) when the screener didn't supply RVOL — scalp's
                # 5x+ RVOL gate is unverifiable otherwise. Only for GO/WAIT candidates (small set).
                if not _rv and _fv_backfilled < 25:
                    try:
                        from external_market_data_ingest import _finviz_quote
                        _fq = _finviz_quote(t.get("symbol", ""))
                        if _fq.get("rvol"):
                            _rv = float(_fq["rvol"]); _fv_backfilled += 1
                            if not _chg and _fq.get("price") and _fq.get("prev"):
                                _chg = round((float(_fq["price"]) - float(_fq["prev"])) / float(_fq["prev"]) * 100, 2)
                    except Exception:
                        pass
                broadcast_scalp_update({
                    "symbol": t.get("symbol", ""),
                    "grade": t.get("grade", ""),
                    "score": t.get("score", 0),
                    "decision": t.get("decision", ""),
                    "change_percent": str(_chg),
                    "rvol": float(_rv or 0),
                    "catalyst_verified": bool(t.get("catalyst_verified")),
                    "critic_verdict": t.get("critic_verdict", ""),
                    "source": "screener",
                })
        if _fv_backfilled:
            print(f"  [ws] finviz RVOL backfill: {_fv_backfilled} signals")
    except Exception as e:
        print(f"  [ws] WS broadcast from orchestrator failed (non-fatal): {e}")

    # 10a-enrich: Multi-source enrichment for GO symbols — non-fatal
    try:
        from symbol_enrichment import enrich_symbol as _enrich
        from db_adapter import get_connection as _get_enrich_conn
        _enrich_conn = _get_enrich_conn()
        _prior_syms = set()
        try:
            _enrich_cur = _enrich_conn.cursor()
            _enrich_cur.execute("""SELECT DISTINCT symbol FROM trade_ai_scans
                          WHERE decision IN ('GO','WAIT') AND run_date = CURRENT_DATE - 1""")
            _prior_syms = {r[0] for r in _enrich_cur.fetchall()}
        except Exception:
            pass
        for t in scored:
            if t.get("decision") == "GO":
                _is_new = t["symbol"] not in _prior_syms
                if _is_new or t.get("score", 0) >= 55:
                    _enrich(t["symbol"], t.get("score", 0), _enrich_conn, force_full=_is_new)
        _enrich_conn.close()
    except Exception as e:
        _err("symbol_enrichment", f"{e}  — continuing without enrichment")

    # 10b Options flow — only on GO-tier tickers after scoring
    try:
        from options_flow import fetch_options_flow, get_options_summary
        go_syms_for_opts = [t["symbol"] for t in scored if t.get("decision") == "GO"][:15]
        if go_syms_for_opts:
            options_flow    = fetch_options_flow(go_syms_for_opts)
            options_summary = get_options_summary(options_flow)
            _ok("options_flow",
                f"{options_summary.get('total_sweeps',0)} sweeps  |  "
                f"{options_summary.get('bullish_count',0)}bull/{options_summary.get('bearish_count',0)}bear  |  "
                f"{options_summary.get('total_premium','$0')}  |  "
                f"{len(go_syms_for_opts)} GO tickers queried")
        else:
            _skip("options_flow", "No GO-tier tickers to query")
    except Exception as exc:
        _err("options_flow", f"{exc}  — continuing without options data")

    # 10c Options desk — portfolio proposals (CC/CSP/spreads) for GO tickers + run summary
    options_desk: dict = {}
    try:
        import options_engine as _oe
        import options_research_bridge as _orb
        _orb.run(apply=True, force=False)
        options_desk = _oe.build_options_desk_summary()
        for t in scored:
            ctx = _oe.options_context_for_symbol(t.get("symbol", ""), options_desk)
            if ctx:
                t["options_desk"] = ctx
        strat_n = options_desk.get("strategy_counts") or {}
        _ok("options_desk",
            f"{options_desk.get('proposal_count', 0)} ideas · "
            f"CC {strat_n.get('covered_call', 0)} · CSP {strat_n.get('cash_secured_put', 0)} · "
            f"spreads {strat_n.get('credit_spread', 0)}")
    except Exception as exc:
        _err("options_desk", f"{exc}  — continuing without desk context")

    # 11 Squeeze bonus (v12)
    try:
        from short_interest import enrich_short_interest, apply_squeeze_bonus_to_scores
        _, _ = enrich_short_interest(tickers, scored)   # sync to scored
        scored = apply_squeeze_bonus_to_scores(scored)
        bonused = sum(1 for t in scored if t.get("squeeze_applied"))
        _ok("squeeze_bonus", f"{bonused} tickers received catalyst boost")
    except Exception as exc:
        _err("squeeze_bonus", f"{exc}  — continuing")

    # Apply trend arrows
    try:
        from trend_engine import enrich_all_trends
        market_snapshot = enrich_all_trends(scored, market_snapshot, state)
        _ok("trend_engine",
            f"{sum(1 for t in scored if t.get('score_arrow')==chr(11014))} \u2b06  "
            f"{sum(1 for t in scored if t.get('rvol_arrow')==chr(128640))} RVOL\U0001f680")
    except Exception as exc:
        _err("trend_engine", f"{exc}  — continuing")

    # 12 Halt detection (v12)
    halt_data: dict = {}
    try:
        from halt_detector import detect_halts
        halt_data = detect_halts(scored, enrichments)
        h = halt_data.get("halt_count", 0)
        r = halt_data.get("resume_count", 0)
        _ok("halt_detector", f"{h} halted  |  {r} resumed")
        if h:
            syms = [x["symbol"] for x in halt_data.get("halted_tickers", [])]
            _ok("halt_detector", f"  Halted: {syms}")
    except Exception as exc:
        _err("halt_detector", f"{exc}  — continuing without halt data")

    # 12b Social sentiment (GO + WAIT tickers only)
    social_data: dict = {}
    try:
        from social_sentiment import get_social_sentiment_bulk
        qualified_syms = [t["symbol"] for t in scored if t.get("decision") in ("GO","WAIT")][:20]
        if qualified_syms:
            social_data = get_social_sentiment_bulk(qualified_syms, delay=0.3)
            # Attach to scored tickers
            for t in scored:
                t["social"] = social_data.get(t["symbol"], {})
            bullish_count = sum(1 for v in social_data.values() if v.get("sentiment_label","") in ("Bullish","Very Bullish"))
            _ok("social_sentiment",
                f"{len(social_data)} tickers scanned  |  {bullish_count} bullish sentiment")
        else:
            _skip("social_sentiment", "No GO/WAIT tickers to scan")
    except Exception as exc:
        _err("social_sentiment", f"{exc}  — continuing without social data")

    # 13 Delta tracking
    delta: dict = {"events":[],"new_tickers":[],"faded":[],"go_tickers":[],"updated_state":state}
    try:
        from delta_tracker import compute_delta
        delta = compute_delta(scored, date_str, run_label, project_root=str(root))
        ev_types = {}
        for e in delta["events"]:
            ev_types[e["event"]] = ev_types.get(e["event"],0) + 1
        _ok("delta_tracker",
            f"{len(delta['events'])} events  |  {len(delta['new_tickers'])} new  |  {len(delta['faded'])} faded")
    except Exception as exc:
        _err("delta_tracker", f"{exc}  — continuing")

    # 14 Trade plans (v12 — A+ only)
    trade_plans: dict = {}
    if use_llm:
        try:
            from trade_plan import generate_all_plans
            trade_plans = generate_all_plans(scored)
            # Attach to scored tickers
            for t in scored:
                t["trade_plan"] = trade_plans.get(t["symbol"])
            _ok("trade_plans", f"{len(trade_plans)} A+ plans generated")
        except Exception as exc:
            _err("trade_plans", f"{exc}  — continuing without trade plans")
    else:
        _skip("trade_plans", "--no-llm flag set")

    # 15 HTML dashboard — skipped on RUN_FAILED when publish is refused (B3)
    html_path: str | None = None
    pdf_path: str | None = None
    docx_path: str | None = None
    if not _publish_artifacts:
        _skip("html_dashboard", f"publish refused after {_health_status}")
        _skip("pdf_generator", f"publish refused after {_health_status}")
        _skip("docx_generator", f"publish refused after {_health_status}")
    else:
        try:
            from html_dashboard import generate_html_dashboard
            html_path = generate_html_dashboard(
                scored, market_snapshot, delta, calendar,
                options_flow, options_summary, output_dir, run_label, date_str,
                trade_plans=trade_plans, halt_data=halt_data,
                institutional=institutional,
            )
            _ok("html_dashboard", Path(html_path).name)
        except Exception as exc:
            _err("html_dashboard", str(exc))

        # 16 PDF
        if os.getenv("GENERATE_PDF","true").lower() == "true":
            try:
                from pdf_generator import generate_pdf
                pdf_path = generate_pdf(scored, delta, output_dir, run_label, date_str,
                                        market_snapshot=market_snapshot, calendar=calendar,
                                        options_summary=options_summary)
                _ok("pdf_generator", Path(pdf_path).name)
            except Exception as exc:
                _err("pdf_generator", str(exc))

    # 17 Word doc (also gated by publish refusal)
    if _publish_artifacts and os.getenv("GENERATE_DOCX","true").lower() == "true":
        try:
            from docx_generator import generate_docx
            docx_path = generate_docx(scored, delta, output_dir, run_label, date_str)
            _ok("docx_generator", Path(docx_path).name)
        except Exception as exc:
            _err("docx_generator", str(exc))

    # 18 TOS export
    tos_result: dict | None = None
    if os.getenv("GENERATE_TOS","true").lower() == "true":
        try:
            from tos_exporter import export_tos
            tos_result = export_tos(scored, output_dir, run_label, date_str, min_decision="WAIT")
            _ok("tos_exporter", f"{tos_result['ticker_count']} tickers")
        except Exception as exc:
            _err("tos_exporter", str(exc))

    # 18b. Persist to trade_ai_scans DB (historical record)
    try:
        from db_adapter import _execute
        import math as _math
        _run_id = f"{date_str}_{run_label}"
        _inserted = 0

        def _num(v):
            """Coerce to a float Postgres NUMERIC accepts; NaN/inf/non-castable -> None.
            Mirrors db_adapter._fit (918c7ff5): a single garbage value (e.g. an inf change_pct
            from a zero base) raised 'cannot convert infinity to numeric' and failed that row's
            INSERT — one '[db_adapter] SQL error:' line per bad ticker in screener_pm.log."""
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return f if _math.isfinite(f) else None
        # sector defense (2026-06-11): degraded runs (429 storms -> cached-ticker fallback) inserted
        # empty sectors (68% of some days). Resolve empties from the DB's latest known sector per symbol.
        _sector_map = {}
        try:
            from db_adapter import _get_conn as _sector_get_conn
            _empty_syms = [t.get("symbol") for t in scored if not (t.get("sector") or "").strip()]
            if _empty_syms:
                conn = _sector_get_conn()
                cur2 = conn.cursor()
                cur2.execute("""SELECT DISTINCT ON (symbol) symbol, sector FROM trade_ai_scans
                                WHERE symbol = ANY(%s) AND COALESCE(sector,'') <> ''
                                ORDER BY symbol, scanned_at DESC""", (_empty_syms,))
                _sector_map = dict(cur2.fetchall())
                for t in scored:
                    if not (t.get("sector") or "").strip() and t.get("symbol") in _sector_map:
                        t["sector"] = _sector_map[t.get("symbol")]
        except Exception:
            pass
        import sys as _sys_persist
        _lib = root / "scripts" / "lib"
        if str(_lib) not in _sys_persist.path:
            _sys_persist.path.insert(0, str(_lib))
        from scan_persist_extra import awareness_persist_values, awareness_persist_update_clause

        _awareness_update = awareness_persist_update_clause()
        for t in scored:
            sym = t.get("symbol", "")
            soc = social_data.get(sym, {}) if social_data else {}
            _aware = awareness_persist_values(t)
            _execute(f"""
                INSERT INTO trade_ai_scans (
                    run_id, run_date, run_label, run_type, symbol, score, grade, decision,
                    original_decision, rvol, price, change_pct, gap_pct, float_m,
                    catalyst, catalyst_verified, catalyst_confidence, catalyst_source,
                    critic_verdict, critic_confidence, critic_reasoning, decision_changed,
                    disqualified, disqualification_reason,
                    sector, industry, country, sector_etf,
                    ticker_perf_1m, sector_perf_1m, vs_sector_pct,
                    social_sentiment, social_score, social_reddit, social_stocktwits,
                    social_bullish_pct, social_wsb, source, screener_label, source_detail, pillar_breakdown,
                    volume,
                    awareness_status, setup_class, symbol_candidate, symbol_alias_confidence,
                    manual_review_required, operator_pill, operator_subtitle, operator_color_token,
                    not_validation_ready, not_tradeable
                ) VALUES (
                    %s, %s, %s, 'full', %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT (symbol, run_date) DO UPDATE SET
                    run_id = EXCLUDED.run_id, run_label = EXCLUDED.run_label, run_type = EXCLUDED.run_type,
                    score = EXCLUDED.score, grade = EXCLUDED.grade, decision = EXCLUDED.decision,
                    original_decision = EXCLUDED.original_decision, rvol = EXCLUDED.rvol, price = EXCLUDED.price,
                    change_pct = EXCLUDED.change_pct, gap_pct = EXCLUDED.gap_pct, float_m = EXCLUDED.float_m,
                    catalyst = EXCLUDED.catalyst, catalyst_verified = EXCLUDED.catalyst_verified,
                    catalyst_confidence = EXCLUDED.catalyst_confidence, catalyst_source = EXCLUDED.catalyst_source,
                    critic_verdict = EXCLUDED.critic_verdict, critic_confidence = EXCLUDED.critic_confidence,
                    critic_reasoning = EXCLUDED.critic_reasoning, decision_changed = EXCLUDED.decision_changed,
                    disqualified = EXCLUDED.disqualified, disqualification_reason = EXCLUDED.disqualification_reason,
                    sector = EXCLUDED.sector, industry = EXCLUDED.industry, country = EXCLUDED.country,
                    sector_etf = EXCLUDED.sector_etf, ticker_perf_1m = EXCLUDED.ticker_perf_1m,
                    sector_perf_1m = EXCLUDED.sector_perf_1m, vs_sector_pct = EXCLUDED.vs_sector_pct,
                    social_sentiment = EXCLUDED.social_sentiment, social_score = EXCLUDED.social_score,
                    social_reddit = EXCLUDED.social_reddit, social_stocktwits = EXCLUDED.social_stocktwits,
                    social_bullish_pct = EXCLUDED.social_bullish_pct, social_wsb = EXCLUDED.social_wsb,
                    source = EXCLUDED.source, screener_label = EXCLUDED.screener_label,
                    source_detail = EXCLUDED.source_detail, pillar_breakdown = EXCLUDED.pillar_breakdown,
                    volume = EXCLUDED.volume,
                    {_awareness_update},
                    scanned_at = now()
            """, (
                _run_id, date_str, run_label, sym,
                _num(t.get("score", 0)), t.get("grade", ""), t.get("decision", ""),
                t.get("original_decision"), _num(t.get("relative_volume")), _num(t.get("price")),
                _num(t.get("change_percent")), _num(t.get("gap_percent")), _num(t.get("float_m")),
                (t.get("top_catalyst") or {}).get("title", "")[:200],
                t.get("catalyst_verified"), _num(t.get("catalyst_confidence")),
                (t.get("top_catalyst") or {}).get("provider", ""),
                t.get("critic_verdict"), _num(t.get("critic_confidence")),
                (t.get("critic_reasoning") or "")[:500],
                t.get("decision_changed", False),
                t.get("disqualified", False), t.get("disqualification_reason", ""),
                t.get("sector", ""), t.get("industry", ""), t.get("country", ""),
                t.get("sector_etf", ""),
                _num(t.get("ticker_perf_1m")), _num(t.get("sector_perf_1m")), _num(t.get("vs_sector_pct")),
                soc.get("sentiment_label", ""), _num(soc.get("sentiment_score")),
                soc.get("reddit_mentions", 0), soc.get("stocktwits_messages", 0),
                _num(soc.get("stocktwits_bullish_pct")), soc.get("wsb_mentions", 0),
                "screener",
                t.get("screener_name") or t.get("primary_source_list"),
                t.get("source_lists"),
                json.dumps(t.get("pillar_breakdown") or {}),
                int(_num(t.get("volume")) or 0) or None,
                *_aware,
            ))
            _inserted += 1
        _ok("db_persist", f"{_inserted} rows → trade_ai_scans")
    except Exception as exc:
        _err("db_persist", str(exc))

    # 18b2 Run health recording
    _run_go = sum(1 for t in scored if t.get("decision") == "GO")
    _run_wait = sum(1 for t in scored if t.get("decision") == "WAIT")
    _run_nogo = len(scored) - _run_go - _run_wait
    try:
        from screener_run_health import record_screener_run_finish, get_conn as _health_conn
        _hconn = _health_conn()
        _health_stats = {
            "symbols_scanned": len(scored),
            "go_count": _run_go,
            "wait_count": _run_wait,
            "no_go_count": _run_nogo,
            "raw_rows": len(tickers),
            "normalized_rows": len(tickers),
            "deduped_symbols": len(scored),
            "expected_min_symbols": min_symbols,
            "target_symbols": 60,
            "source": "finviz",
            "screener_count": len(live.get("downloads", [])) if 'live' in dir() else 0,
            "has_cookie": bool(os.getenv("FINVIZ_COOKIE")),
        }
        _health_result = record_screener_run_finish(_hconn, run_label, _health_stats)
        _health_status = _health_result["status"]
        _health_reasons = _health_result["reason_codes"]
        _hconn.close()
        if _health_status == "RUN_HEALTHY":
            _ok("run_health", f"{_health_status} — {len(scored)} symbols scanned (min {min_symbols})")
        elif _health_status == "RUN_PARTIAL":
            _err("run_health", f"{_health_status} — {len(scored)} symbols (min {min_symbols}) — {_health_reasons}")
        else:
            _err("run_health", f"{_health_status} — {len(scored)} symbols (min {min_symbols}) — {_health_reasons}")
            if not allow_underfilled:
                # B3: a failure branch that only printed used to keep publishing
                # dashboard / PDF / dashboard_live as if the run succeeded.
                _publish_artifacts = False
                print(f"\n  ⚠️  Run is {_health_status}. Refusing to publish dashboard/PDF/live "
                      f"(use --allow-underfilled to proceed anyway).\n")
    except Exception as exc:
        _err("run_health", str(exc))

    # 18c Risk gate — annotate GO/WAIT tickers with prop desk governance (non-fatal)
    try:
        from risk_gate import RiskGate
        from db_adapter import _get_conn as _rg_get_conn
        _rg_conn = _rg_get_conn()
        _rg = RiskGate(_rg_conn)
        _rg_approved = 0
        _rg_rejected = 0
        for t in scored:
            if t.get("decision") not in ("GO", "WAIT"):
                continue
            _plan = t.get("trade_plan") or {}
            _rd = _rg.check(
                symbol=t.get("symbol", ""),
                strategy_id="momentum_scalp",
                trade_plan=_plan,
                account="taxable",
                mode="paper",
                action_context="discovery",
                extra={
                    "sector": t.get("sector"),
                    "source": t.get("source", "screener"),
                    "catalyst_verified": bool(t.get("catalyst_verified")),
                    "intel_readiness": t.get("intelligence_readiness", 0),
                    "vix": market_snapshot.get("vix"),
                }
            )
            t["risk_gate_result"] = _rd.result
            t["risk_gate_reason_codes"] = _rd.reason_codes
            if _rd.approved:
                _rg_approved += 1
            else:
                _rg_rejected += 1
        _ok("risk_gate", f"{_rg_approved} approved  {_rg_rejected} flagged  (discovery context)")
    except Exception as exc:
        _err("risk_gate", f"{exc}  — continuing without risk gate")

    # 18d Strategy signal sync — GO/A+ scans → strategy_signals (non-fatal)
    try:
        from strategy_signal_sync import sync_strategy_signals, get_conn as _sync_get_conn
        _sync_conn = _sync_get_conn()
        sync_result = sync_strategy_signals(_sync_conn, run_label=run_label, dry_run=False)
        _sync_conn.close()
        _sync_inserted = sync_result.get("inserted", 0)
        _sync_total = sync_result.get("strategy_signals_after", 0)
        _sync_go = sync_result.get("go_count", 0) + sync_result.get("aplus_count", 0)
        _sync_errors = sync_result.get("errors", 0)
        # errors MUST appear in the summary line. Between 2026-08-08 and 2026-08-31 every
        # insert raised (ON CONFLICT naming a non-existent constraint) and this line still
        # read "0 inserted  0 total" with a green tick -- a total outage was indistinguishable
        # from a quiet day in the one line a human reads.
        _sync_msg = f"{_sync_inserted} inserted  {_sync_total} total  ({_sync_go} GO/A+ scans)"
        if _sync_errors:
            _sync_msg += f"  {_sync_errors} ERRORS"
        # Zero-rows alert: GO/A+ scans arrived but nothing was written, or writes errored.
        if (_sync_go > 0 and _sync_total == 0) or _sync_errors:
            _err("strategy_signal_sync", _sync_msg)
            _alert_text = (f"⚠️ Signal flow warning: {_sync_go} GO/A+ scans, "
                           f"{_sync_inserted} inserted, {_sync_errors} errors — "
                           f"0 strategy_signals written. Strategy Desk will be empty.")
            try:
                # send_telegram, NOT send_alert. `send_alert` has never existed in
                # telegram_alert.py (git log -S "def send_alert" returns no commit), so this
                # alarm raised ImportError and printed to a log file 171 times while the
                # Strategy Desk sat empty for 24 days. An alarm that cannot raise is not an alarm.
                from telegram_alert import send_telegram
                _alert_ok = send_telegram(_alert_text)
                if not _alert_ok:
                    print(f"  ⚠️ ALERT NOT DELIVERED (send_telegram returned False): {_alert_text}")
            except Exception as _alert_exc:
                # Record WHY, and name the symbol. A bare `except Exception: print(...)` is what
                # laundered the ImportError into a log line nobody read.
                print(f"  ⚠️ ALERT NOT DELIVERED ({type(_alert_exc).__name__}: {_alert_exc}): {_alert_text}")
        else:
            _ok("strategy_signal_sync", _sync_msg)
    except Exception as exc:
        _err("strategy_signal_sync", f"{exc}  — continuing without signal sync")
        # Fallback: try subprocess
        try:
            import subprocess as _sp
            _sp.run(
                [str(root / ".venv/bin/python"), str(root / "scripts/strategy_signal_sync.py"),
                 "--run-label", run_label],
                timeout=180, cwd=str(root),
            )
        except Exception:
            pass

    # 18e Trade plan backfill — ensure proposal-worthy signals have plans (non-fatal)
    try:
        from backfill_trade_plans_for_signals import backfill_plans, get_conn as _plan_get_conn
        _plan_conn = _plan_get_conn()
        _plan_result = backfill_plans(_plan_conn, run_label=run_label)
        _plan_conn.close()
        _plan_updated = _plan_result.get("updated", 0)
        _plan_total = _plan_result.get("total", 0)
        _ok("trade_plan_backfill", f"{_plan_updated}/{_plan_total} signals got trade plans")
    except Exception as exc:
        _err("trade_plan_backfill", f"{exc}  — continuing without plan backfill")

    # 18e2 Rotation autopilot — autonomous watchlist + signal sync when IWM leads SPY (non-fatal)
    try:
        from rotation_autopilot import run_autopilot_tick
        _rot_result = run_autopilot_tick(
            force_bridge=True, run_label=run_label,
            trigger=f"orchestrator:{run_label}",
        )
        _bridge = _rot_result.get("bridge") or {}
        if _rot_result.get("rotation", {}).get("signal") != "small_cap_outperform":
            _skip("rotation_autopilot", "no IWM/SPY rotation signal")
        elif _rot_result.get("bridge_ran"):
            _wl = _bridge.get("watchlist_promoted", 0)
            _qi = _bridge.get("qualified_intel_added", 0)
            _ps = len(_bridge.get("proposal_symbols") or [])
            _ins = (_bridge.get("proposal_sync") or {}).get("sync_inserted", 0)
            _pc = int((_bridge.get("proposals") or {}).get("proposals_created") or 0)
            _ok("rotation_autopilot",
                f"{_wl} watchlist  {_qi} qualified  {_ps} proposal-tier  {_ins} signals  {_pc} proposals")
        else:
            _skip("rotation_autopilot", _rot_result.get("bridge_reason") or "throttled")
    except Exception as exc:
        _err("rotation_autopilot", f"{exc}  — continuing without rotation autopilot")

    # 18f Auto paper proposal generation (non-fatal)
    if not getattr(_caller_args, '_skip_auto_proposals', False):
        try:
            from auto_proposal_generator import run_auto_proposals, get_conn as _ap_get_conn
            # Only auto-propose on healthy/partial runs
            if len(scored) >= min_symbols or allow_underfilled:
                _ap_conn = _ap_get_conn()
                _ap_dry = getattr(_caller_args, '_auto_proposals_dry_run', False)
                _ap_result = run_auto_proposals(
                    _ap_conn, run_label=run_label,
                    min_score=40, limit=20, dry_run=_ap_dry,
                    execution_label="orchestrator",
                )
                _ap_conn.close()
                _ap_created = _ap_result.get("proposals_created", 0)
                _ap_skipped = _ap_result.get("proposals_skipped", 0)
                _ap_checked = _ap_result.get("signals_checked", 0)
                _ok("auto_proposals", f"{_ap_created} created  {_ap_skipped} skipped  ({_ap_checked} checked)")
            else:
                _skip("auto_proposals", f"Run underfilled ({len(scored)} < {min_symbols}) — skipping auto proposals")
        except Exception as exc:
            _err("auto_proposals", f"{exc}  — continuing without auto proposals")

    # 19 Save state
    try:
        from delta_tracker import save_state
        save_state(delta.get("updated_state",{}), project_root=str(root))
        _ok("state_save", "state.json updated")
    except Exception as exc:
        _err("state_save", str(exc))

    # 20 Run summary
    try:
        aplus_tickers = [t["symbol"] for t in scored if t.get("score",0) >= 48]
        # Social sentiment summary for run_summary.json
        social_bullish = sum(1 for v in social_data.values()
                             if v.get("sentiment_label","") in ("Bullish","Very Bullish"))
        social_wsb_spikes = [
            sym for sym, v in social_data.items()
            if v.get("wsb_mentions", 0) >= 3
        ]
        summary = {
            "version":           "12.0",
            "date":              date_str,
            "run_label":         run_label,
            # `generated_at` is naive and host-local: no offset, no Z. It cannot
            # be converted, and any surface that renders it must say so rather
            # than infer a zone from the host's TZ. Kept verbatim because
            # api_v2, db_adapter.save_run_summary, morning_digest,
            # trade_ai_news_monitor, hermes_tradeai_handshake and
            # heal_trade_ai_session_cache all read this key — changing its
            # meaning in place would silently move every one of them.
            "generated_at":      datetime.now().isoformat(timespec="seconds"),
            # The zoned stamp new readers should prefer. UTC, not
            # datetime.now().astimezone(): a tz-aware LOCAL stamp is still a
            # function of host config and breaks the moment the box moves or a
            # container runs UTC.
            "generated_at_utc":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "generated_at_tz":   "UTC",
            "ticker_count":      len(scored),
            "go_count":          sum(1 for t in scored if t.get("decision") == "GO"),
            "wait_count":        sum(1 for t in scored if t.get("decision") == "WAIT"),
            "aplus_count":       len(aplus_tickers),
            "trade_plans_count": len(trade_plans),
            "new_tickers":       delta.get("new_tickers", []),
            "faded_tickers":     delta.get("faded", []),
            "delta_events":      len(delta.get("events", [])),
            "top_ticker":        scored[0]["symbol"] if scored else None,
            "top_score":         scored[0]["score"]  if scored else None,
            "breadth":           market_snapshot.get("breadth_label"),
            "vix":               market_snapshot.get("vix",{}).get("price"),
            "options_sweeps":    options_summary.get("total_sweeps",0),
            "options_desk_count": options_desk.get("proposal_count", 0),
            "options_desk_strategies": options_desk.get("strategy_counts", {}),
            "high_squeeze":      short_summary.get("high_squeeze_count",0),
            "halted":            halt_data.get("halt_count",0),
            "resumed":           halt_data.get("resume_count",0),
            "social_tickers_scanned": len(social_data),
            "social_bullish_count":   social_bullish,
            "social_wsb_spikes":      social_wsb_spikes,
            "html_path":         html_path,
            "pdf_path":          pdf_path,
            "docx_path":         docx_path,
            "tos_path":          tos_result.get("tst_path") if tos_result else None,
            "llm_enabled":       use_llm,
        }
        from db_adapter import save_run_summary
        save_run_summary(summary, output_dir / "run_summary.json")
        _ok("run_summary", "run_summary.json saved")
        # Save full ticker decisions for live cycle preservation
        try:
            _decisions = [{"symbol": t.get("symbol",""), "decision": t.get("decision","NO GO"), "score": t.get("score",0)} for t in scored]
            _live_state = {"run_label": run_label, "date": date_str, "generated_at": summary["generated_at"], "tickers": _decisions}
            (root / "data" / "live_run_state.json").write_text(json.dumps(_live_state, indent=2))
        except Exception as _e:
            pass
    except Exception as exc:
        _err("run_summary", str(exc))

    # Copy dated dashboard to dashboard_live.html (persistent live view)
    # B3: RUN_FAILED must not refresh dashboard_live as a success surface.
    if html_path and _publish_artifacts:
        try:
            import shutil
            live_path = root / "reports" / "dashboard_live.html"
            shutil.copy2(html_path, live_path)
            _ok("persistent_dashboard", "dashboard_live.html updated")
        except Exception as exc:
            _err("persistent_dashboard", str(exc))
    elif not _publish_artifacts:
        _skip("persistent_dashboard", f"publish refused after {_health_status}")

    # 21 Alerts
    if not _publish_artifacts:
        _skip("alerting", f"publish refused after {_health_status}")
    elif send_alerts:
        try:
            from alerting import send_all_alerts
            send_all_alerts(
                scored, delta, run_label, date_str,
                attachments=[p for p in [pdf_path, docx_path] if p],
                market_snapshot=market_snapshot,
                options_summary=options_summary,
                halt_data=halt_data,
                trade_plans=trade_plans,
                short_summary=short_summary,
                social_data=social_data,
            )
            _ok("alerting", "WhatsApp + Telegram + Email + Slack")
        except Exception as exc:
            _err("alerting", str(exc))
    else:
        _skip("alerting", "--no-alerts flag set")

    # B2+B3 failure surface: when publish was refused, write the same diagnostic
    # fields the health-recovery SUCCESS path already carries, then exit non-zero
    # with that string so PipelineRun.run_fail does not store a bare "2".
    if not _publish_artifacts:
        _rl = _count_rate_limit_hits(Path(root))
        _diag = format_failure_diagnostic(
            rc=str(_health_status or "RUN_FAILED"),
            rate_limit_hits=_rl,
            reasons=_health_reasons,
            symbols=len(scored),
        )
        write_failure_run_summary(output_dir, {
            "version": "12.0",
            "date": date_str,
            "run_label": run_label,
            "status": "FAILED",
            "health_status": _health_status,
            "reason_codes": list(_health_reasons or []),
            "ticker_count": len(scored),
            "rate_limit_hits": _rl,
            "stage_errors": list(_STAGE_ERRORS),
            "diagnostic": _diag,
            "published_dashboard": False,
            "published_pdf": False,
            "published_dashboard_live": False,
        })
        print(f"\n{'='*66}")
        print(f"  \u274c v12 FAILED  |  {date_str} {run_label}")
        print(f"  {_diag}")
        print(f"  \U0001f4c1 Output: {output_dir}")
        print(f"{'='*66}\n")
        # Non-zero int keeps cron/monitoring honest; the string is what
        # PipelineRun records. Prefer the string via SystemExit in main().
        return _diag

    go_syms = [t["symbol"] for t in scored if t.get("decision") == "GO"][:5]
    print(f"\n{'='*66}")
    print(f"  \u2705 v12 complete  |  {date_str} {run_label}")
    if go_syms:
        print(f"  \U0001f3af GO: {' \u00b7 '.join(go_syms)}")
    if html_path:
        print(f"  \U0001f310 Dashboard: {Path(html_path).name}")
    dashboard_live = root / "reports" / "dashboard_live.html"
    if dashboard_live.exists():
        print(f"  \U0001f310 Live: {dashboard_live.name} (keep open in Chrome)")
    print(f"  \U0001f4c1 Output: {output_dir}")
    print(f"{'='*66}\n")
    return 0


def _parse():
    ap = argparse.ArgumentParser(description="Trade AI v12")
    ap.add_argument("--institutional", action="store_true",
                    help="Also generate institutional-grade dashboard variant")
    ap.add_argument("--macro-context", action="store_true",
                    help="Force macro regime commentary (auto-enabled on zero-GO days)")
    ap.add_argument("--run-label",         required=True,
                    choices=["0400","0700","0900","1000","1200","1400","1600","1730"])
    ap.add_argument("--date",              default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--project-root",      default=".")
    ap.add_argument("--skip-market-check", action="store_true")
    ap.add_argument("--no-llm",            action="store_true")
    ap.add_argument("--no-alerts",         action="store_true")
    ap.add_argument("--min-symbols",       type=int, default=40,
                    help="Minimum symbols for healthy run (default 40)")
    ap.add_argument("--allow-underfilled", action="store_true",
                    help="Allow pipeline to complete even if universe is underfilled")
    ap.add_argument("--skip-auto-proposals", action="store_true",
                    help="Skip auto paper proposal generation (stage 18f)")
    ap.add_argument("--auto-proposals-dry-run", action="store_true",
                    help="Dry-run auto proposals (preview only)")
    return ap.parse_args()

def main():
    args = _parse()
    root = Path(args.project_root).resolve()
    if (root / ".env").exists():
        load_dotenv(root / ".env")
    scripts_dir = root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return run_pipeline(root, args.run_label, args.date,
                        use_llm=not args.no_llm,
                        send_alerts=not args.no_alerts,
                        skip_market_check=args.skip_market_check,
                        institutional=args.institutional,
                        min_symbols=args.min_symbols,
                        allow_underfilled=args.allow_underfilled)


def _enrich_opaque_exit(code_or_msg, root: Path | None = None) -> str | int:
    """Turn a bare exit code into the diagnostic success-recovery already uses.

    Observed live: failed pipeline_runs rows with summary `{"errors": "2"}` —
    argparse/SystemExit code with no rc= / rate_limit_hits=. The health-recovery
    SUCCESS path already writes those fields; failing runs must too (B2).
    """
    if isinstance(code_or_msg, str) and "rc=" in code_or_msg:
        return code_or_msg
    root = root or Path(".")
    try:
        rl = _count_rate_limit_hits(root)
    except Exception:
        rl = -1
    if code_or_msg in (0, None):
        return code_or_msg
    rc_label = f"exit_{code_or_msg}" if not isinstance(code_or_msg, str) else code_or_msg
    return format_failure_diagnostic(
        rc=str(rc_label),
        rate_limit_hits=rl,
        reasons=None,
        symbols=0,
        stage_errors=len(_STAGE_ERRORS),
    )


if __name__ == "__main__":
    with PipelineRun("trade_ai_orchestrator") as _run:
        _root_guess = Path(".").resolve()
        try:
            _result = main()
        except SystemExit as _se:
            # argparse exits 2 before run_pipeline; enrich so the row is legible.
            _code = _se.code
            if _code in (0, None):
                raise
            raise SystemExit(_enrich_opaque_exit(_code, _root_guess)) from _se
        except Exception as _exc:
            _diag = format_failure_diagnostic(
                rc=type(_exc).__name__,
                rate_limit_hits=_count_rate_limit_hits(_root_guess),
                extra=f"error={str(_exc)[:200]}",
            )
            raise SystemExit(_diag) from _exc
        if _result in (0, None):
            raise SystemExit(0)
        # Non-zero / diagnostic string from run_pipeline (already formatted).
        raise SystemExit(_enrich_opaque_exit(_result, _root_guess))
