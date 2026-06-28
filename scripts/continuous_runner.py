"""continuous_runner.py  -- Trade AI v12 Advanced Continuous Runner.

Schedule (weekdays):
  4:00 AM            ' Full run (use launcher/run_0400.bat instead)
  5:00 AM            ' Full run (use launcher/run_0500.bat instead)
  6:00 --9:00 AM       ' Every 15 min, Full anchors at 6:00, 7:00, 8:00
  9:00 --10:00 AM      ' Every 10 min (market open  -- highest frequency)
  10:00 --11:00 AM     ' Every 15 min
  Self-terminates at 11:00 AM

Modes:
  LIVE    -- Fast cycle: Finviz + scoring (no LLM), alert on significant changes only
  FULL    -- Complete pipeline: LLM, PDF, DOCX, trade plans, all alerts

LLM credit management:
  Haiku   -- Runs ONLY when:
            (a) Ticker passes pre-score filter (score       8)
            (b) Catalyst fingerprints have CHANGED since last Haiku call
            (c) No more than once per ticker per 30 minutes (rate gate)
  Sonnet  -- Runs ONLY when:
            (a) Score       48 (A+)
            (b) Ticker has not had a plan generated today
            (c) Score increased by 5+ points since last plan OR new high-impact catalyst

Alert triggers (LIVE mode  -- suppressed otherwise):
  NEW_GO          : Ticker entered GO tier
  HALT            : Halt detected
  RVOL_5X / 8X   : RVOL threshold crossed for first time this session
  SCORE_JUMP      : Score jumped       10 points since last cycle
"""
from __future__ import annotations

import argparse, json, os, sys, time, subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Set
from dotenv import load_dotenv


# "   "    Schedule config "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   

SCHEDULE = [
    # (start_hhmm, end_hhmm, interval_minutes, is_full_at_start)
    ("03:00", "04:00", 30, True),   # deep pre-market: 30-min cycles (Ollama catalyst prep)
    ("04:00", "06:00", 30, True),   # early pre-market: 30-min LIVE cycles
    ("06:00", "09:00", 15, True),   # pre-market: 15-min cycles, full at :00
    ("09:00", "10:00", 10, True),   # market open: 10-min cycles
    ("10:00", "11:00", 15, True),   # first-hour wind-down
    ("11:30", "12:15", 15, True),   # midday: post-morning momentum continuation
    ("13:30", "14:15", 15, True),   # afternoon: pre-close setups forming
    ("15:15", "16:00", 15, True),   # final window: last 45min entry window
    ("16:15", "20:00", 30, False),  # after-hours: swing prep (Schwab-validated quotes)
]

# Digest trigger times (HH:MM)
DIGEST_PREMARKET_TIME = "06:55"   # Pre-market digest
DIGEST_PREOPEN_TIME   = "09:25"   # Pre-open brief

# Windows within which a Full run fires at the top of every hour
ANCHOR_WINDOW_MIN = 7  # fire FULL if within this many min of an anchor
HOURLY_FULL_ANCHORS = {"04:00", "05:00", "06:00", "07:00", "08:00", "09:00", "10:00",
                        "12:00", "14:00", "15:30"}

# Alert thresholds
SCORE_JUMP_THRESHOLD  = 10
RVOL_5X_THRESHOLD     = 5.0
RVOL_8X_THRESHOLD     = 8.0


def classify_social_injection(row: dict) -> dict:
    """P0-4: route-aware decision for injecting a scalp_scan_results row into live scoring.

    Returns {injectable, tradeable, strategy_id?, manual_review_required, large_float, reason}.
    Pure/testable. Missing route fields → safe fallback (NOT injected as tradeable), never GO.
    """
    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    route = str(row.get("route") or "").strip().lower()
    actionability = str(row.get("route_actionability") or "").strip().upper()
    route_sid = str(row.get("route_strategy_id") or "").strip().lower()
    decision = str(row.get("decision") or "").strip().upper()
    cat_v = bool(row.get("catalyst_verified"))
    rvol = _num(row.get("rvol"))
    float_m = _num(row.get("float_m") if row.get("float_m") is not None else row.get("float_mm"))
    price = _num(row.get("price"))

    if not route:
        return {"injectable": False, "tradeable": False, "reason": "no_durable_route_fields"}

    # Standard micro-cap momentum scalp — every condition must hold.
    if (decision == "GO" and route == "momentum_scalp" and actionability == "GO"
            and route_sid == "momentum_scalp" and cat_v
            and rvol is not None and rvol >= 5.0
            and float_m is not None and float_m <= 20.0
            and price is not None and price <= 25.0):
        return {"injectable": True, "tradeable": True, "strategy_id": "momentum_scalp",
                "manual_review_required": False, "large_float": False, "reason": "verified_microcap_GO"}

    # Large-float scout / meme squeeze — injected as labelled MANUAL-REVIEW scout, NOT tradeable.
    if route in ("large_float_social_scout", "meme_squeeze_momentum"):
        return {"injectable": True, "tradeable": False, "strategy_id": route,
                "manual_review_required": True, "large_float": True,
                "reason": "large_float_scout_manual_review"}

    # watch_only / WAIT / WATCH / portfolio / reject — not injected into the live tradeable path.
    return {"injectable": False, "tradeable": False,
            "reason": f"route={route}/{actionability or '-'}_not_tradeable"}


# LLM rate gates
LLM_HAIKU_COOLDOWN_MIN  = 30   # min minutes between Haiku calls per ticker
LLM_SONNET_COOLDOWN_MIN = 120  # min minutes between Sonnet plans per ticker


# "   "    State tracker "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   

class CycleState:
    def __init__(self):
        self.prev_go:        Set[str]         = set()
        self.prev_rvol:      Dict[str, float] = {}
        self.prev_score:     Dict[str, int]   = {}
        self.halted_seen:    Set[str]         = set()
        self.rvol5x_seen:    Set[str]         = set()
        self.rvol8x_seen:    Set[str]         = set()
        self.haiku_last:     Dict[str, datetime] = {}
        self.sonnet_last:    Dict[str, datetime] = {}
        self.sonnet_plans:   Set[str]         = set()   # tickers with plans today
        self.cat_fingerprints: Dict[str, Set[str]] = {}

    def needs_haiku(self, sym: str, cat_fingerprints: Set[str]) -> bool:
        """Return True if Haiku should re-evaluate this ticker."""
        now = datetime.now()
        last = self.haiku_last.get(sym)
        # Cooldown not expired
        if last and (now - last).total_seconds() / 60 < LLM_HAIKU_COOLDOWN_MIN:
            return False
        # Catalyst fingerprints unchanged
        prev_fps = self.cat_fingerprints.get(sym, set())
        if prev_fps and not (cat_fingerprints - prev_fps):
            return False
        return True

    def needs_sonnet(self, sym: str, score: int, cat_fingerprints: Set[str]) -> bool:
        """Return True if Sonnet should generate/refresh a trade plan."""
        if score < 48:
            return False
        now = datetime.now()
        last = self.sonnet_last.get(sym)
        if last and (now - last).total_seconds() / 60 < LLM_SONNET_COOLDOWN_MIN:
            return False
        prev_score = self.prev_score.get(sym, 0)
        score_jumped = (score - prev_score) >= 5
        new_hi_cat = bool(cat_fingerprints - self.cat_fingerprints.get(sym, set()))
        return sym not in self.sonnet_plans or score_jumped or new_hi_cat

    def record_haiku(self, sym: str, fingerprints: Set[str]):
        self.haiku_last[sym]       = datetime.now()
        self.cat_fingerprints[sym] = fingerprints

    def record_sonnet(self, sym: str):
        self.sonnet_last[sym] = datetime.now()
        self.sonnet_plans.add(sym)

    def detect_triggers(self, scored: List[Dict], halt_data: Dict) -> List[Dict]:
        triggers = []
        go_now = {t["symbol"] for t in scored if t.get("decision") == "GO"}

        for sym in go_now - self.prev_go:
            t = next((x for x in scored if x["symbol"] == sym), {})
            triggers.append({"type": "NEW_GO", "symbol": sym, "score": t.get("score",0),
                             "rvol": t.get("relative_volume",0),
                             "cat": (t.get("top_catalyst") or {}).get("title","")[:60]})

        for h in halt_data.get("halted_tickers", []):
            if h["symbol"] not in self.halted_seen:
                self.halted_seen.add(h["symbol"])
                triggers.append({"type": "HALT", "symbol": h["symbol"],
                                 "reason": h.get("reason_text","")})

        for r in halt_data.get("resumed_tickers", []):
            self.halted_seen.discard(r["symbol"])
            triggers.append({"type": "RESUMED", "symbol": r["symbol"]})

        for t in scored:
            sym  = t["symbol"]
            rvol = t.get("relative_volume", 0) or 0
            _cat = (t.get("top_catalyst") or {}).get("title", "")[:55]
            _dec = t.get("decision", "")
            _sc  = t.get("score", 0)
            # Only send RVOL/score alerts for GO — suppress WAIT/AVOID noise
            _actionable = _dec == "GO"
            if rvol >= RVOL_8X_THRESHOLD and sym not in self.rvol8x_seen:
                self.rvol8x_seen.add(sym)
                if _actionable:
                    triggers.append({"type": "RVOL_8X", "symbol": sym, "rvol": rvol,
                                     "cat": _cat, "decision": _dec, "score": _sc})
            elif rvol >= RVOL_5X_THRESHOLD and sym not in self.rvol5x_seen:
                self.rvol5x_seen.add(sym)
                if _actionable:
                    triggers.append({"type": "RVOL_5X", "symbol": sym, "rvol": rvol,
                                     "cat": _cat, "decision": _dec, "score": _sc})

            prev  = self.prev_score.get(sym, 0)
            delta = t.get("score", 0) - prev
            if prev > 0 and delta >= SCORE_JUMP_THRESHOLD and _actionable:
                triggers.append({"type": "SCORE_JUMP", "symbol": sym,
                                 "score": t.get("score",0), "prev": prev, "delta": delta,
                                 "decision": t.get("decision","")})

        return triggers

    def update(self, scored: List[Dict]):
        self.prev_go    = {t["symbol"] for t in scored if t.get("decision") == "GO"}
        self.prev_rvol  = {t["symbol"]: t.get("relative_volume",0) or 0 for t in scored}
        self.prev_score = {t["symbol"]: t.get("score",0) for t in scored}
        self.last_scored = scored  # Keep for news-triggered re-critique


# "   "    Alert builder "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   

def _build_live_alert(triggers: List[Dict], time_str: str, market: Dict) -> str:
    spy = market.get("indices",{}).get("SPY",{}).get("change_percent",0)
    vix = market.get("vix",{}).get("price",0)
    b   = market.get("breadth_label","?")
    lines = [f"\u26a1 *Trade AI LIVE [{time_str}]*", f"SPY {spy:+.2f}%  VIX {vix:.1f}  {b}", ""]
    for t in triggers:
        if t["type"] == "NEW_GO":
            sym = t["symbol"]
            _cat = t.get("cat", "")
            _sc = t["score"]; _rv = t.get("rvol",0)

            # Inline Scalp Critic check
            critic_line = ""
            _verdict = ""
            try:
                from scalp_critic_agent import check_danger_flags, validate_catalyst, llm_critique, industry_fallback
                _ticker = {"symbol": sym, "catalyst": _cat, "decision": "GO",
                           "price": 0, "relative_volume": _rv, "float_m": 0}
                _flags = check_danger_flags(sym, _ticker)
                _cv, _cs, _ = validate_catalyst(sym, sym, _cat)
                _ind = industry_fallback(sym) or ""
                _crit = llm_critique(_ticker, _flags, _cv, _cs, _ind)
                _verdict = _crit.get("verdict", "?")
                _reasoning = _crit.get("reasoning", "")[:60]
                if _verdict == "BLOCK":
                    critic_line = f"\n  \U0001f6ab Critic: *BLOCK* — _{_reasoning}_"
                elif _verdict == "DOWNGRADE":
                    critic_line = f"\n  \u26a0\ufe0f Critic: *DOWNGRADE* — _{_reasoning}_"
                elif _verdict == "CONFIRM":
                    critic_line = f"\n  \u2705 Critic: CONFIRM"
            except Exception:
                pass

            # Quick social sentiment
            social_line = ""
            try:
                from social_scalp_scanner import get_social_sentiment
                _sent = get_social_sentiment(sym)
                if _sent and _sent.get("label"):
                    social_line = f"\n  \U0001f4ca Social: {_sent['label']}"
            except Exception:
                pass

            # Ollama one-liner
            ai_line = ""
            try:
                import sys as _sys, re as _re
                from scoring import _ollama_serialized
                _p = f"/no_think\nOne sentence why {sym} is a scalp GO. Score={_sc} RVOL={_rv:.1f}x. Max 12 words."
                _r = _ollama_serialized(_p, num_predict=50, timeout=20)
                _r = _re.sub(r"<think>.*?</think>", "", _r, flags=_re.DOTALL).strip()
                if _r: ai_line = "\n  \U0001f916 _" + _r[:80] + "_"
            except Exception: pass

            lines.append(f"\U0001f3af *NEW GO* \u2014 *{sym}* score={_sc} RVOL {_rv:.1f}x\n  _{_cat}_" + critic_line + social_line + ai_line)

            # Live WS broadcast — non-fatal
            try:
                from scalp_ws_client import broadcast_scalp_update
                broadcast_scalp_update({
                    "symbol": sym,
                    "grade": t.get("grade", ""),
                    "score": _sc,
                    "decision": "GO",
                    "change_percent": str(t.get("change_pct", "")),
                    "rvol": _rv,
                    "critic_verdict": _verdict,
                    "catalyst_verified": True,
                    "source": "continuous",
                })
            except Exception:
                pass

        elif t["type"] == "HALT":
            lines.append(f"\U0001f6a8 *HALT* \u2014 *{t['symbol']}*  {t.get('reason','')}")
        elif t["type"] == "RESUMED":
            lines.append(f"\u2705 *RESUMED* \u2014 *{t['symbol']}*")
        elif t["type"] == "RVOL_8X":
            _rl = f"\U0001f680 *RVOL 8x* \u2014 *{t['symbol']}*  {t['rvol']:.1f}x"
            if t.get("decision"): _rl += f"  [{t['decision']}]"
            if t.get("cat"): _rl += f"\n  _{t['cat']}_"
            lines.append(_rl)
        elif t["type"] == "RVOL_5X":
            _rl = f"\U0001f680 *RVOL 5x* \u2014 *{t['symbol']}*  {t['rvol']:.1f}x"
            if t.get("decision"): _rl += f"  [{t['decision']}]"
            if t.get("cat"): _rl += f"\n  _{t['cat']}_"
            lines.append(_rl)
        elif t["type"] == "SCORE_JUMP":
            lines.append(f"\U0001f4c8 *+{t['delta']}pts* \u2014 *{t['symbol']}*  {t['prev']}\u2192{t['score']} ({t['decision']})")
    return "\n".join(lines)


# "   "    Live cycle "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   

def run_live_cycle(root: Path, run_label: str, date_str: str,
                   state: CycleState, time_str: str,
                   _timeout: int = 600) -> None:  # 10 min max per live cycle
    sys.path.insert(0, str(root / "scripts"))

    try:
        from finviz_ingestion import load_live_candidates
        out = root / os.getenv("REPORT_OUTPUT_DIR","reports") / date_str / run_label
        out.mkdir(parents=True, exist_ok=True)
        live = load_live_candidates(root, run_label, date_str, out)
        tickers = live["dataframe"].to_dict(orient="records")
        if not tickers: return
        print(f"  [live] {len(tickers)} tickers")
    except Exception as e:
        print(f"  [live] ingestion error: {e}"); return

    # Inject social/news candidates from scalp_scan_results — P0-4: ROUTE-AWARE (not score-only).
    # Only verified micro-cap GO names enter the live scoring path as tradeable momentum_scalp;
    # large-float scouts enter as labelled manual-review (not tradeable); social-only/watch names
    # are NOT injected into live scoring (they remain on dashboards/watchlists elsewhere).
    try:
        from db_adapter import _execute
        _existing_syms = {t.get("symbol","") for t in tickers}
        _social = _execute("""
            SELECT DISTINCT ON (symbol)
                symbol, score, rvol, price, change_pct, gap_pct, float_mm AS float_m,
                sector, industry, country, sources, decision,
                route, route_actionability, route_strategy_id, route_reason_codes,
                discovery_trace_id, catalyst_verified
            FROM scalp_scan_results
            WHERE scanned_at > NOW() - INTERVAL '4 hours'
            ORDER BY symbol, scanned_at DESC
        """) or []
        _injected = 0
        _scouts = 0
        for sr in _social:
            sym = sr.get("symbol","")
            if sym in _existing_syms:
                continue
            inj = classify_social_injection(sr)
            if not inj.get("injectable"):
                continue  # social-only / watch / WAIT — not injected into live scoring as tradeable
            tickers.append({
                "symbol": sym,
                "price": float(sr.get("price") or 0),
                "change_percent": float(sr.get("change_pct") or 0),
                "gap_percent": float(sr.get("gap_pct") or 0),
                "relative_volume": float(sr.get("rvol") or 0),
                "float_m": float(sr.get("float_m") or 0),
                "float_shares": float(sr.get("float_m") or 0),
                "sector": sr.get("sector") or "",
                "industry": sr.get("industry") or "",
                "country": sr.get("country") or "",
                "volume": 0, "avg_volume": 0,
                "source_count": 1,
                "source_lists": ",".join(sr.get("sources") or []),
                "run_window": run_label,
                "_source": "social",
                # Durable route/lineage labels carried into scoring + downstream signal sync.
                "discovery_trace_id": sr.get("discovery_trace_id"),
                "route": sr.get("route"),
                "route_actionability": sr.get("route_actionability"),
                "route_strategy_id": sr.get("route_strategy_id"),
                "route_reason_codes": sr.get("route_reason_codes"),
                "catalyst_verified": bool(sr.get("catalyst_verified")),
                "tradeable_scalp": inj["tradeable"],
                "manual_review_required": inj.get("manual_review_required", False),
                "large_float": inj.get("large_float", False),
            })
            _existing_syms.add(sym)
            _injected += 1
            if inj.get("manual_review_required"):
                _scouts += 1
        if _injected:
            print(f"  [live] +{_injected} route-aware social candidates injected "
                  f"({_scouts} large-float scouts / manual-review)")
    except Exception as e:
        print(f"  [live] social inject warning: {e}")

    market: Dict = {}
    try:
        from market_context import get_market_snapshot
        market = get_market_snapshot()
    except Exception as e:
        print(f"  [live] market error: {e}")

    enrichments: Dict = {}
    try:
        from catalyst_cache import get_bulk, set_bulk
        from catalyst_enrichment import enrich_ticker
        from scoring import filter_candidates
        cand_syms, tickers = filter_candidates(tickers, str(root), 8)
        cached, miss = get_bulk(cand_syms, str(root), date_str, 20)
        enrichments.update(cached)
        fresh = {}
        for sym in miss:
            row = next((t for t in tickers if t.get("symbol","").upper() == sym), {})
            fps = set(row.get("catalyst_fingerprints",[]))
            if state.needs_haiku(sym, fps):
                try:
                    fresh[sym] = enrich_ticker(sym, row.get("company",""))
                    state.record_haiku(sym, fps)
                except Exception:
                    pass
        if fresh: set_bulk(fresh, str(root), date_str)
        enrichments.update(fresh)
        print(f"  [live] catalysts: {len(cached)} cached  {len(fresh)} fresh")
    except Exception as e:
        print(f"  [live] catalyst error: {e}")

    try:
        from scoring import score_all, filter_candidates
        from short_interest import enrich_short_interest, apply_squeeze_bonus_to_scores
        enrich_short_interest(tickers)
        sm = market.get("sectors",[])
        for t in tickers:
            sm_map = {"Technology":"XLK","Financials":"XLF","Energy":"XLE","Healthcare":"XLV",
                      "Consumer Disc.":"XLY","Industrials":"XLI","Consumer Stapl.":"XLP",
                      "Utilities":"XLU","Real Estate":"XLRE","Materials":"XLB","Comm. Services":"XLC"}
            etf = sm_map.get(t.get("sector",""),"")
            ranked = sorted(sm, key=lambda s:s.get("change_percent",0), reverse=True)
            top3 = {s["symbol"] for s in ranked[:3]}
            t["sector_momentum_score"] = 5 if etf in top3 else 0
        scored = score_all(tickers, enrichments, str(root), use_llm=False)
        scored = apply_squeeze_bonus_to_scores(scored)
        go_c = sum(1 for t in scored if t.get("decision")=="GO")
        print(f"  [live] GO={go_c} scored={len(scored)}")
        # PRESERVE FULL RUN SCORES: if live rescore drops GO to 0, restore
        # decisions from live_run_state.json written by full run orchestrator
        if go_c == 0:
            import json as _json
            _state_path = root / "data" / "live_run_state.json"
            if _state_path.exists():
                try:
                    _rs = _json.loads(_state_path.read_text())
                    # Only restore if same date and run label
                    if _rs.get("date") == date_str and _rs.get("run_label") == run_label:
                        _full = {t["symbol"]: t.get("decision","NO GO") for t in _rs.get("tickers",[])}
                        if _full:
                            for t in scored:
                                sym = t.get("symbol","")
                                if sym in _full:
                                    t["decision"] = _full[sym]
                            go_c = sum(1 for t in scored if t.get("decision")=="GO")
                            print(f"  [live] restored full-run decisions: GO={go_c}")
                except Exception as _e:
                    print(f"  [live] restore warning: {_e}")
    except Exception as e:
        print(f"  [live] scoring error: {e}"); return

    halt_data: Dict = {}
    try:
        from halt_detector import detect_halts
        halt_data = detect_halts(scored, enrichments)
        if halt_data.get("halt_count",0):
            print(f"  [live]          HALTED: {[h['symbol'] for h in halt_data.get('halted_tickers',[])]}")
    except Exception as e:
        print(f"  [live] halt error: {e}")

    triggers = state.detect_triggers(scored, halt_data)
    state.update(scored)

    # Write live scores so API/command center stays in sync
    try:
        import json as _json
        _live_state = {
            "date": date_str, "run_label": run_label, "time": time_str,
            "tickers": [{
                "symbol": t.get("symbol",""), "score": t.get("score",0),
                "decision": t.get("decision",""), "relative_volume": t.get("relative_volume",0),
                "catalyst": (t.get("top_catalyst") or {}).get("title","")[:80],
                "catalyst_verified": t.get("catalyst_verified"),
                "industry": t.get("industry",""), "sector": t.get("sector",""),
            } for t in scored if t.get("decision") in ("GO","WAIT")]
        }
        (root / "data" / "live_run_state.json").write_text(_json.dumps(_live_state, indent=2))
    except Exception as _e:
        print(f"  [live] state write error: {_e}")

    # Persist GO/WAIT tickers to trade_ai_scans DB
    try:
        from db_adapter import _execute
        _run_id = f"{date_str}_{run_label}_live_{time_str.replace(':','')}"
        _go_wait = [t for t in scored if t.get("decision") in ("GO", "WAIT")]
        for t in _go_wait:
            _execute("""
                INSERT INTO trade_ai_scans (
                    run_id, run_date, run_label, run_type, symbol, score, grade, decision,
                    rvol, price, change_pct, gap_pct, float_m,
                    catalyst, catalyst_verified, catalyst_confidence,
                    disqualified, sector, industry, country, source, pillar_breakdown
                ) VALUES (
                    %s, %s, %s, 'live', %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (symbol, run_date) DO UPDATE SET
                    run_id = EXCLUDED.run_id, run_label = EXCLUDED.run_label, run_type = EXCLUDED.run_type,
                    score = EXCLUDED.score, grade = EXCLUDED.grade, decision = EXCLUDED.decision,
                    rvol = EXCLUDED.rvol, price = EXCLUDED.price, change_pct = EXCLUDED.change_pct,
                    gap_pct = EXCLUDED.gap_pct, float_m = EXCLUDED.float_m, catalyst = EXCLUDED.catalyst,
                    catalyst_verified = EXCLUDED.catalyst_verified, catalyst_confidence = EXCLUDED.catalyst_confidence,
                    disqualified = EXCLUDED.disqualified, sector = EXCLUDED.sector, industry = EXCLUDED.industry,
                    country = EXCLUDED.country, source = EXCLUDED.source, pillar_breakdown = EXCLUDED.pillar_breakdown,
                    scanned_at = now()
            """, (
                _run_id, date_str, run_label, t.get("symbol",""),
                t.get("score",0), t.get("grade",""), t.get("decision",""),
                t.get("relative_volume"), t.get("price"),
                t.get("change_percent"), t.get("gap_percent"), t.get("float_m"),
                (t.get("top_catalyst") or {}).get("title","")[:200],
                t.get("catalyst_verified"), t.get("catalyst_confidence"),
                t.get("disqualified", False),
                t.get("sector",""), t.get("industry",""), t.get("country",""),
                t.get("_source", "screener"),
                json.dumps(t.get("pillar_breakdown") or {}),
            ))
        if _go_wait:
            print(f"  [live] {len(_go_wait)} tickers → trade_ai_scans")
    except Exception as _e:
        print(f"  [live] db persist error: {_e}")

    if triggers:
        print(f"  [live] {len(triggers)} trigger(s): {[t['type'] for t in triggers]}")
        msg = _build_live_alert(triggers, time_str, market)
        try:
            from alerting import send_whatsapp, send_slack
            send_whatsapp(msg); send_slack(msg)
        except Exception: pass
        try:
            from telegram_alert import send_telegram
            send_telegram(msg)
        except Exception: pass
    else:
        print(f"  [live] no changes  -- alerts suppressed")

    # Refresh dashboard (no PDF/DOCX)
    try:
        from html_dashboard import generate_html_dashboard
        from delta_tracker import compute_delta, save_state, load_state
        from economic_calendar import get_calendar
        from options_flow import get_options_summary
        delta = compute_delta(scored, date_str, run_label, str(root))
        cal   = get_calendar(scored)
        html  = generate_html_dashboard(scored, market, delta, cal, {}, {}, out, run_label, date_str)
        save_state(delta.get("updated_state",{}), str(root))
        print(f"  [live] dashboard refreshed: {Path(html).name}")
        # Also update dashboard_live.html so the main URL stays current
        import shutil as _shutil
        _live = root / "reports" / "dashboard_live.html"
        _shutil.copy2(html, str(_live))
    except Exception as e:
        print(f"  [live] dashboard error: {e}")


# "   "    Full cycle "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   

def run_full_cycle(root: Path, run_label: str, date_str: str) -> None:
    cmd = [sys.executable, str(root/"scripts"/"trade_ai_orchestrator.py"),
           "--run-label", run_label, "--date", date_str, "--skip-market-check",
           "--allow-underfilled"]
    print(f"  [FULL] Launching complete pipeline...")
    try:
        subprocess.run(cmd, env=os.environ.copy(), timeout=2700)  # 45 min hard limit
    except subprocess.TimeoutExpired:
        print(f"  [FULL]            Pipeline timed out after 45 min  -- killing and continuing")
    except Exception as e:
        print(f"  [FULL]            Pipeline error: {e}")


# ─── News-triggered re-critique ───────────────────────────────────────────────

def _check_news_and_recritique(root: Path, state, date_str: str) -> None:
    """Check GO/WAIT tickers for new breaking news. If found, re-run Scalp Critic
    and Telegram only if verdict changes. Called after each live cycle."""
    from trade_ai_news_monitor import check_significant_news, re_critique_ticker, send_verdict_change_telegram, is_market_hours

    if not is_market_hours():
        return

    # Get active tickers from state
    scored = state.last_scored if hasattr(state, 'last_scored') else []
    if not scored:
        return

    active = [t for t in scored if t.get("decision") in ("GO", "WAIT")]
    if not active:
        return

    # Track last news check time per ticker in state
    if not hasattr(state, '_news_check_times'):
        state._news_check_times = {}

    now_ts = time.time()
    changes = []

    for t in active:
        sym = t.get("symbol", "")
        if not sym:
            continue

        # Skip if checked < 14 min ago
        last = state._news_check_times.get(sym, 0)
        if (now_ts - last) < 840:  # 14 min
            continue

        state._news_check_times[sym] = now_ts
        news = check_significant_news(sym, since_minutes=16)

        if not news:
            continue

        print(f"  [news] {sym}: new headline — {news[0]['headline'][:60]}")
        result = re_critique_ticker(sym, news[0]['headline'])

        if result.get('verdict_changed'):
            print(f"  [news] {sym}: VERDICT CHANGED → {result['new_verdict']}")
            changes.append(result)

    if changes:
        send_verdict_change_telegram(changes)
        print(f"  [news] {len(changes)} verdict change(s) — Telegram sent")


# "   "    Schedule helpers "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "

def _hm_to_min(hm: str) -> int:
    h, m = hm.split(":")
    return int(h)*60 + int(m)

def _now_hm() -> str:
    return datetime.now().strftime("%H:%M")

def _now_min() -> int:
    n = datetime.now()
    return n.hour*60 + n.minute

def _best_run_label(now: datetime) -> str:
    h = now.hour
    if h < 7:  return "0400"
    if h < 9:  return "0700"
    if h < 10: return "0900"
    return "1000"

def _current_interval() -> int:
    """Return the current cycle interval in minutes based on time of day."""
    m = _now_min()
    for start, end, interval, _ in SCHEDULE:
        if _hm_to_min(start) <= m < _hm_to_min(end):
            return interval
    return 15


# "   "    Main loop "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--test", action="store_true", help="Run one live cycle immediately")
    args = ap.parse_args()

    root = Path(args.project_root).resolve()
    if (root/".env").exists(): load_dotenv(root/".env")
    if str(root/"scripts") not in sys.path: sys.path.insert(0, str(root/"scripts"))

    state = CycleState()

    # Write to log file so we can diagnose issues
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"continuous_{datetime.now().strftime('%Y%m%d')}.log"
    import sys as _sys
    class _Tee:
        def __init__(self, *files): self.files = files
        def write(self, obj):
            for f in self.files:
                try: f.write(obj); f.flush()
                except: pass
        def flush(self):
            for f in self.files:
                try: f.flush()
                except: pass
    _logfile = open(log_path, "a", encoding="utf-8")
    _sys.stdout = _Tee(_sys.__stdout__, _logfile)
    _sys.stderr = _Tee(_sys.__stderr__, _logfile)

    if args.test:
        now  = datetime.now()
        date = now.strftime("%Y-%m-%d")
        lbl  = _best_run_label(now)
        print(f"[TEST] Single live cycle  -- {_now_hm()}  run_label={lbl}")
        run_live_cycle(root, lbl, date, state, _now_hm())
        return 0

    # Find end time (last schedule window end)
    end_hm  = SCHEDULE[-1][1]
    end_min = _hm_to_min(end_hm)
    start_min = _hm_to_min(SCHEDULE[0][0])

    print(f"\n{'='*60}")
    print(f"  Trade AI v12  -- Advanced Continuous Runner")
    print(f"  Schedule: 4 --6 AM (30min)   * 6 --9 AM (15min)   * 9 --10 AM (10min)   * 10 --11 AM (15min)")
    print(f"  Startup FULL run: fires immediately on launch")
    print(f"  Full anchors at: {', '.join(sorted(HOURLY_FULL_ANCHORS))}")
    print(f"  Self-terminates at {end_hm}")
    print(f"{'='*60}\n")

    # "   "    Startup: run FULL pipeline immediately on launch "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   "   
    # Ensures 4AM run fires even if Task Scheduler was late or machine slept.
    _startup_now   = datetime.now()
    _startup_label = _best_run_label(_startup_now)
    _startup_date  = _startup_now.strftime("%Y-%m-%d")
    print(f"\n[STARTUP] {_startup_now.strftime('%H:%M:%S')}  -- immediate FULL run (label={_startup_label})")
    try:
        run_full_cycle(root, _startup_label, _startup_date)
        print(f"[STARTUP] Complete")
    except Exception as _e:
        import traceback as _tb
        print(f"[STARTUP] ERROR: {_e}")
        _tb.print_exc()

    cycle = 0
    _anchors_fired_today = set()   # tracks which anchors ran today
    _anchor_last_date = ""
    while True:
        now      = datetime.now()
        now_min  = _hm_to_min(f"{now.hour:02d}:{now.minute:02d}")
        date_str = now.strftime("%Y-%m-%d")
        time_str = _now_hm()

        # Hard safety net  -- force exit if past 11:30 AM no matter what
        if now_min >= _hm_to_min("11:30"):
            print(f"[{time_str}] Hard cutoff 11:30 AM  -- forcing shutdown.")
            break

        if now_min >= end_min:
            print(f"[{time_str}] Reached end time ({end_hm})  -- shutting down.")
            break

        if now_min < start_min:
            wait = start_min - now_min
            print(f"[{time_str}] Before window start ({SCHEDULE[0][0]})  -- waiting {wait} min...")
            time.sleep(wait * 60)
            continue

        cycle += 1
        run_label = _best_run_label(now)
        interval  = _current_interval()

        # Window-based anchor check: fires FULL within ANCHOR_WINDOW_MIN of each hour
        _today = date_str
        if _today != _anchor_last_date:
            _anchors_fired_today.clear()
            _anchor_last_date = _today
        _now_m = now.hour * 60 + now.minute
        _hit_anchor = next(
            (a for a in sorted(HOURLY_FULL_ANCHORS)
             if a not in _anchors_fired_today
             and abs(_now_m - (int(a[:2])*60 + int(a[3:]))) <= ANCHOR_WINDOW_MIN),
            None)
        is_full = _hit_anchor is not None
        if is_full:
            _anchors_fired_today.add(_hit_anchor)
        mode    = "FULL" if is_full else "LIVE"
        print(f"\n[{time_str}] {mode} cycle #{cycle}  label={run_label}  interval={interval}min")

        try:
            if is_full:
                run_full_cycle(root, run_label, date_str)
            else:
                run_live_cycle(root, run_label, date_str, state, time_str)
        except Exception as e:
            import traceback
            print(f"  [ERROR] {e}")
            traceback.print_exc()

        # Digest triggers (6:55 AM premarket, 9:25 AM preopen)
        _now = datetime.now()
        _date = _now.strftime("%Y-%m-%d")
        _hhmm = _now.strftime("%H:%M")
        for _dtime, _dtype in [("06:55","premarket"),("09:25","preopen")]:
            _dkey = f"{_date}_{_dtype}"
            _th, _tm = map(int, _dtime.split(":"))
            _nh, _nm = _now.hour, _now.minute
            if abs((_nh*60+_nm) - (_th*60+_tm)) <= 2:
                if not hasattr(run_live_cycle, f"_digest_{_dkey}"):
                    setattr(run_live_cycle, f"_digest_{_dkey}", True)
                    try:
                        import subprocess as _sp
                        _sp.Popen([sys.executable,"scripts/morning_digest.py",
                                   f"--type={_dtype}","--project-root=."],
                                  stdout=open("logs/digest.log","a"),
                                  stderr=subprocess.STDOUT)
                        print(f"  [runner] {_dtype} digest fired")
                    except Exception as _e:
                        print(f"  [runner] digest error: {_e}")
        # News-triggered re-critique on active tickers
        try:
            _check_news_and_recritique(root, state, date_str)
        except Exception as _ne:
            print(f"  [runner] news check error (non-fatal): {_ne}")

        # Sleep until next interval boundary
        elapsed = (datetime.now() - now).total_seconds()
        sleep   = max(10, interval * 60 - elapsed)
        nxt     = (datetime.now() + timedelta(seconds=sleep)).strftime("%H:%M")
        print(f"     ' Next cycle at {nxt}  (sleep {int(sleep)}s)")
        time.sleep(sleep)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
