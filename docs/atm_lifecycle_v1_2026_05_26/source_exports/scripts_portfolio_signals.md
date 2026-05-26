# Source Export: scripts/portfolio_signals.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/portfolio_signals.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `4c6b5461c084156130e4e25e2fa1871e230698fcdb44748b8bc758744c146762` |
| **File Size** | 35295 bytes |

## Full Source

```py
"""
portfolio_signals.py — Rules-based action signal engine
Version: 3.0 | April 17, 2026

Generates EXIT / TRIM / WATCH / MONITOR / ADD / HOLD signals per ticker
(aggregated across accounts) based on John's mechanical rules framework.
NOT investment advice.

Reads config/thesis.json for thesis groups + targets.
All signal inputs from existing state files.

Signal types:
  EXIT    — Sell entire position (mandatory)
  TRIM    — Reduce position size
  WATCH   — Monitor closely, action pending trigger
  MONITOR — Rule triggered but position below size gate (not actionable at scale)
  ADD     — Increase position
  HOLD    — No action, on thesis or default

Rules (priority order — highest wins):
  1.  Concentration — EXIT >15% (downgraded to TRIM if thesis beta_exempt,
      floor = thesis min_allocation_pct). TRIM >12%.
  2.  Overbought RSI>70 + institutional selling → TRIM
  3.  Non-functional stop (>50% from stop) → WATCH (exempt from size gate)
  4.  Stop proximity danger (<5%) → WATCH (exempt from size gate)
  5.  Beta violation (>1.5, >3% weight, not thesis-exempt) → TRIM
  6.  Dividend gap close (yield >2.5%, favorable) → ADD
      Uses dividend_calendar yield as fallback when Finviz div_yield_pct unavailable.
      Relaxes analyst_rating check for thesis-group tickers.
  7.  Defense thesis hold → HOLD (exempt from size gate)
  8.  52-week low opportunity (<10% from low, favorable) → ADD
  9.  Insider conviction (boost existing signals) → modifier
  10. Golden Window Roth (NOTE only, not position signal)
  11. Earnings proximity (<7 days, downgrades TRIM/EXIT to WATCH)
  12. Watchlist thesis tag cross-reference (adds note)

Size gate (0.5% of portfolio MV):
  Rules 1,2,5,6,8 → MONITOR if position below gate.
  Rules 3,4,7 → fire regardless of size (risk/thesis rules).
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

CASH_SYMS = {"CASH", "--", "SNSXX", "SWVXX", "SPRXX", "VMFXX", "FDRXX"}

# Signal priority: lower number = higher priority
SIGNAL_PRIORITY = {"EXIT": 1, "TRIM": 2, "WATCH": 3, "MONITOR": 4, "ADD": 5, "HOLD": 6}

# Rules exempt from the size gate (fire at any position size)
SIZE_GATE_EXEMPT_RULES = {"R3", "R4", "R7"}


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def load_thesis_config() -> Dict[str, Dict]:
    """Load thesis group definitions from config/thesis.json."""
    return _load_json(CONFIG_DIR / "thesis.json")


def load_beta_overrides() -> Dict[str, Dict]:
    """Load manual beta overrides from config/manual_beta_overrides.json."""
    data = _load_json(CONFIG_DIR / "manual_beta_overrides.json")
    return {k: v for k, v in data.items() if k != "_comment" and isinstance(v, dict)}


def get_beta(ticker: str, enrichment: Dict, overrides: Dict) -> Tuple[Optional[float], str]:
    """Get beta for a ticker, checking Finviz first then manual overrides.
    Returns (beta_value, source) where source is 'finviz', 'manual', or 'none'."""
    enr = enrichment.get(ticker, {}) if isinstance(enrichment.get(ticker), dict) else {}
    finviz_beta = enr.get("beta")
    if finviz_beta is not None and not isinstance(finviz_beta, str):
        try:
            return (float(finviz_beta), "finviz")
        except (ValueError, TypeError):
            pass
    # Fallback to manual override
    override = overrides.get(ticker, {})
    manual_beta = override.get("beta")
    if manual_beta is not None:
        try:
            return (float(manual_beta), "manual")
        except (ValueError, TypeError):
            pass
    return (None, "none")


def _get_targets(thesis_config: Dict) -> Dict:
    """Extract targets section from thesis config with defaults."""
    t = thesis_config.get("targets", {})
    return {
        "annual_dividend_income": t.get("annual_dividend_income", 28000),
        "dividend_gap_trigger_yield_pct": t.get("dividend_gap_trigger_yield_pct", 2.5),
        "concentration_exit_pct": t.get("concentration_exit_pct", 15),
        "concentration_trim_pct": t.get("concentration_trim_pct", 12),
        "concentration_default_target_pct": t.get("concentration_default_target_pct", 10),
        "beta_target": t.get("beta_target", 0.5),
        "size_gate_pct": t.get("size_gate_pct", 0.5),
        "dividend_candidates": t.get("dividend_candidates", []),
    }


def _ticker_thesis_groups(ticker: str, thesis_config: Dict) -> List[Dict]:
    """Return all thesis groups a ticker belongs to."""
    groups = []
    for name, cfg in thesis_config.items():
        if name == "targets":
            continue
        if ticker in cfg.get("tickers", []):
            groups.append({"name": name, **cfg})
    return groups


def _is_beta_exempt(ticker: str, thesis_config: Dict) -> bool:
    """Check if ticker is in a thesis with beta_exempt: true."""
    for name, cfg in thesis_config.items():
        if name == "targets":
            continue
        if isinstance(cfg, dict) and ticker in cfg.get("tickers", []) and cfg.get("beta_exempt"):
            return True
    return False


def _get_thesis_concentration_floor(ticker: str, thesis_config: Dict) -> Optional[float]:
    """For beta_exempt thesis tickers, return the min_allocation_pct as concentration floor."""
    for name, cfg in thesis_config.items():
        if name == "targets":
            continue
        if (isinstance(cfg, dict) and ticker in cfg.get("tickers", [])
                and cfg.get("beta_exempt")):
            return cfg.get("min_allocation_pct")
    return None


def _parse_earnings_date(raw: Any) -> Optional[datetime]:
    """Try to parse earnings_date. Returns None if unparseable."""
    if not raw or not isinstance(raw, str):
        return None
    # Try common date formats
    for fmt in ("%Y-%m-%d", "%b %d", "%m/%d/%Y", "%m/%d"):
        try:
            d = datetime.strptime(raw.strip(), fmt)
            if d.year < 2000:
                d = d.replace(year=datetime.now().year)
            return d
        except ValueError:
            continue
    return None


def _watchlist_thesis_note(ticker: str, watchlist: Dict) -> str:
    """Get thesis tag from watchlist for a ticker."""
    entry = watchlist.get(ticker, {})
    if isinstance(entry, dict):
        thesis = entry.get("thesis", "")
        intent = entry.get("target_intent", "")
        if thesis:
            return f"Watchlist: {thesis[:60]}" + (f" ({intent})" if intent else "")
    return ""


def generate_action_signals(
    holdings: Dict,
    enrichment: Dict,
    risk: Dict,
    retirement: Dict,
    dividends: Dict,
    watchlist: Dict,
) -> List[Dict]:
    """
    Generate rules-based action signals for all non-cash positions.

    Aggregates same-ticker holdings across accounts before running rules.
    Returns ONE signal per ticker, sorted by priority (EXIT first, HOLD last).
    Positions without Finviz data still run concentration/stop/thesis rules.
    Positions below the size gate (0.5% of total MV) get MONITOR for
    trim/entry rules; risk/thesis rules fire at any size.
    """
    thesis_config = load_thesis_config()
    targets = _get_targets(thesis_config)
    positions = holdings.get("holdings", [])
    annual_div = dividends.get("total_annual", 0) or 0
    div_target = targets["annual_dividend_income"]
    div_gap = max(0, div_target - annual_div)
    div_yield_trigger = targets["dividend_gap_trigger_yield_pct"]
    conc_exit_pct = targets["concentration_exit_pct"]
    conc_trim_pct = targets["concentration_trim_pct"]
    conc_default_target = targets["concentration_default_target_pct"]
    size_gate_pct = targets["size_gate_pct"]
    today = datetime.now()

    # Total portfolio MV (including cash) for percentage denominators
    total_portfolio_mv = holdings.get("portfolio_totals", {}).get("total_value", 0) or 0
    if total_portfolio_mv <= 0:
        total_portfolio_mv = sum((p.get("market_value", 0) or 0) for p in positions)
    size_gate_mv = total_portfolio_mv * size_gate_pct / 100

    # Build dividend yield lookup from dividend_calendar as fallback
    div_cal_yields = {}
    for payer in dividends.get("payers", []):
        if isinstance(payer, dict) and payer.get("symbol"):
            div_cal_yields[payer["symbol"]] = payer.get("yield_pct", 0) or 0

    # Load manual beta overrides
    beta_overrides = load_beta_overrides()

    # Load earnings dates from yfinance enrichment
    earnings_data = _load_json(STATE_DIR / "earnings_dates.json")

    # Build risk position lookup (stop distances)
    risk_positions = risk.get("positions", {})
    risk_lookup = {}
    if isinstance(risk_positions, list):
        for rp in risk_positions:
            if isinstance(rp, dict) and rp.get("symbol"):
                key = f"{rp['symbol']}_{rp.get('account', '')}"
                risk_lookup[key] = rp
    elif isinstance(risk_positions, dict):
        for sym, rp in risk_positions.items():
            if isinstance(rp, dict):
                risk_lookup[sym] = rp

    # ── Step 1: Aggregate holdings by ticker ────────────────────
    ticker_agg: Dict[str, Dict] = {}
    for pos in positions:
        sym = pos.get("symbol", "")
        if not sym or sym in CASH_SYMS:
            continue
        mv = pos.get("market_value", 0) or 0
        if mv <= 0:
            continue
        acct = pos.get("account_display") or pos.get("account", "")

        if sym not in ticker_agg:
            ticker_agg[sym] = {
                "symbol": sym,
                "total_mv": 0,
                "total_pct": 0,
                "accounts": [],
            }
        ticker_agg[sym]["total_mv"] += mv
        ticker_agg[sym]["total_pct"] += pos.get("portfolio_pct", 0) or 0
        ticker_agg[sym]["accounts"].append({
            "account": acct,
            "market_value": mv,
            "portfolio_pct": pos.get("portfolio_pct", 0) or 0,
        })

    # ── Step 2: Run rules per aggregated ticker ─────────────────
    signals = []

    for sym, agg in ticker_agg.items():
        total_mv = agg["total_mv"]
        total_pct = agg["total_pct"]
        accounts = agg["accounts"]
        acct_context = ", ".join(
            f"{a['account']} (${a['market_value']:,.0f} / {a['portfolio_pct']:.1f}%)"
            for a in accounts
        )

        enr = enrichment.get(sym, {}) if isinstance(enrichment.get(sym), dict) else {}
        has_finviz = bool(enr.get("rsi") or enr.get("beta") or enr.get("perf_month_pct"))

        # Enrichment data (beta uses Finviz → manual override fallback)
        rsi = enr.get("rsi")
        beta, beta_source = get_beta(sym, enrichment, beta_overrides)
        inst_trans = enr.get("inst_trans_pct")
        insider_trans = enr.get("insider_trans_pct")
        sma200 = enr.get("sma200_pct")
        w52_high = enr.get("week52_high_pct")
        w52_low = enr.get("week52_low_pct")
        perf_m = enr.get("perf_month_pct")
        analyst_rating = enr.get("analyst_rating")
        # Earnings date from yfinance enrichment (preferred) or Finviz (fallback)
        earnings_raw = (earnings_data.get(sym, {}) or {}).get("earnings_date") or enr.get("earnings_date")
        div_yield = enr.get("div_yield_pct")
        vol_m = enr.get("volatility_m_pct")

        # Risk: use worst (closest) stop across accounts
        dist_pct = None
        stop_price = None
        is_protected = False
        for a in accounts:
            rk = f"{sym}_{a['account']}"
            rp = risk_lookup.get(rk) or risk_lookup.get(sym, {})
            if isinstance(rp, dict) and rp.get("dist_pct") is not None:
                if dist_pct is None or rp["dist_pct"] < dist_pct:
                    dist_pct = rp["dist_pct"]
                    stop_price = rp.get("stop_price")
                    is_protected = rp.get("protected", False)

        # Thesis groups
        thesis_groups = _ticker_thesis_groups(sym, thesis_config)
        thesis_names = [g["name"] for g in thesis_groups]
        beta_exempt = _is_beta_exempt(sym, thesis_config)

        # Watchlist
        wl_note = _watchlist_thesis_note(sym, watchlist)

        # Earnings proximity
        earnings_dt = _parse_earnings_date(earnings_raw)
        earnings_near = False
        earnings_days = None
        if earnings_dt:
            delta = (earnings_dt - today).days
            if 0 <= delta <= 7:
                earnings_near = True
                earnings_days = delta

        # ── Coverage gap: no Finviz data ──────────────────────
        # Still run concentration (R1), stop rules (R3/R4), and thesis (R7).
        if not has_finviz:
            signal = None
            rule = None
            note_parts = ["No Finviz enrichment data"]

            # R1 concentration (with thesis downgrade)
            conc_floor = _get_thesis_concentration_floor(sym, thesis_config)
            if total_pct > conc_exit_pct:
                if conc_floor is not None:
                    signal = "TRIM"
                    rule = "R1: Concentration >15% (thesis-downgraded)"
                    note_parts.append(f"Total {total_pct:.1f}% — thesis position, trim toward {conc_floor}% floor")
                else:
                    signal = "EXIT"
                    rule = "R1: Concentration >15%"
                    note_parts.append(f"Total {total_pct:.1f}% — mandatory trim to {conc_default_target}%")
            elif total_pct > conc_trim_pct:
                signal = "TRIM"
                rule = "R1: Concentration >12%"
                note_parts.append(f"Total {total_pct:.1f}% — reduce toward {conc_default_target}%")

            # R3/R4 stop rules still apply
            if dist_pct is not None and dist_pct >= 50:
                if signal is None or SIGNAL_PRIORITY["WATCH"] < SIGNAL_PRIORITY.get(signal, 99):
                    signal = "WATCH"
                    rule = "R3: Non-functional stop"
                    note_parts.append(f"Stop {dist_pct:.0f}% below price — review or remove")
            if dist_pct is not None and dist_pct < 5 and is_protected:
                if signal is None or SIGNAL_PRIORITY["WATCH"] < SIGNAL_PRIORITY.get(signal, 99):
                    signal = "WATCH"
                    rule = "R4: Stop proximity <5%"
                    note_parts.append(f"{dist_pct:.1f}% from stop — prepare exit if breached")

            # R7 thesis hold
            if thesis_groups and signal is None:
                signal = "HOLD"
                rule = "R7: Thesis position"
                note_parts.append(f"On thesis: {', '.join(thesis_names)}")

            # R12 watchlist cross-ref
            if wl_note:
                note_parts.append(wl_note)

            if signal is None:
                signal = "HOLD"
                rule = "Coverage gap"

            signals.append({
                "symbol": sym,
                "signal": signal,
                "priority": SIGNAL_PRIORITY.get(signal, 99),
                "rule": rule,
                "note": " | ".join(note_parts),
                "accounts_context": acct_context,
                "thesis_groups": thesis_names,
                "data_points": {
                    "market_value": total_mv, "portfolio_pct": total_pct,
                    "has_finviz": False, "dist_pct": dist_pct,
                    "stop_price": stop_price, "is_protected": is_protected,
                },
            })
            continue

        # ── Apply rules in priority order (on aggregated ticker) ──
        signal = None
        rule = None
        rule_id = None  # e.g. "R1", "R2" — for size gate exemption check
        note_parts = []
        size_below = total_mv < size_gate_mv

        # RULE 1: Concentration (on TOTAL ticker weight) — with thesis downgrade
        conc_floor = _get_thesis_concentration_floor(sym, thesis_config)
        if total_pct > conc_exit_pct:
            if conc_floor is not None:
                # Thesis-protected: downgrade EXIT → TRIM, floor = min_allocation_pct
                signal = "TRIM"
                rule = "R1: Concentration >15% (thesis-downgraded)"
                rule_id = "R1"
                note_parts.append(
                    f"Total {total_pct:.1f}% across {len(accounts)} account(s) — "
                    f"thesis position, trim toward {conc_floor}% floor (thesis min_allocation_pct)")
            else:
                signal = "EXIT"
                rule = "R1: Concentration >15%"
                rule_id = "R1"
                note_parts.append(f"Total {total_pct:.1f}% across {len(accounts)} account(s) — mandatory trim to {conc_default_target}%")
        elif total_pct > conc_trim_pct:
            signal = "TRIM"
            rule = "R1: Concentration >12%"
            rule_id = "R1"
            note_parts.append(f"Total {total_pct:.1f}% across {len(accounts)} account(s) — reduce toward {conc_default_target}%")

        # RULE 2: Overbought + institutional selling
        if rsi and rsi > 70 and inst_trans is not None and inst_trans < 0:
            if signal is None or SIGNAL_PRIORITY["TRIM"] < SIGNAL_PRIORITY.get(signal, 99):
                signal = "TRIM"
                rule = "R2: Overbought + inst selling"
                rule_id = "R2"
                note_parts.append(f"RSI {rsi:.0f} overbought, inst flow {inst_trans:+.1f}%")

        # RULE 3: Non-functional stop (>50% from stop) — exempt from size gate
        if dist_pct is not None and dist_pct >= 50:
            if signal is None or SIGNAL_PRIORITY["WATCH"] < SIGNAL_PRIORITY.get(signal, 99):
                signal = "WATCH"
                rule = "R3: Non-functional stop"
                rule_id = "R3"
                note_parts.append(f"Stop {dist_pct:.0f}% below price — review or remove")

        # RULE 4: Stop proximity danger (<5%) — exempt from size gate
        if dist_pct is not None and dist_pct < 5 and is_protected:
            if signal is None or SIGNAL_PRIORITY["WATCH"] < SIGNAL_PRIORITY.get(signal, 99):
                signal = "WATCH"
                rule = "R4: Stop proximity <5%"
                rule_id = "R4"
                note_parts.append(f"{dist_pct:.1f}% from stop at ${stop_price or 0:.2f} — prepare exit if breached")

        # RULE 5: Beta violation (>1.5, >3% weight, NOT thesis-exempt)
        if beta and beta > 1.5 and total_pct > 3:
            if beta_exempt:
                note_parts.append(f"Beta {beta:.2f} high but exempt under {', '.join(thesis_names)} thesis")
            elif signal is None or SIGNAL_PRIORITY["TRIM"] < SIGNAL_PRIORITY.get(signal, 99):
                signal = "TRIM"
                rule = "R5: Beta violation"
                rule_id = "R5"
                note_parts.append(f"Beta {beta:.2f} pulling portfolio above {targets['beta_target']} target ({total_pct:.1f}% weight)")

        # RULE 6: Dividend gap close — explicit whitelist from config/thesis.json
        # Only fires on tickers in targets.dividend_candidates (equity income, not bonds).
        # Uses dividend_calendar yield as fallback; relaxes analyst check for thesis tickers.
        div_candidates = targets.get("dividend_candidates", [])
        eff_yield = div_yield or div_cal_yields.get(sym)
        if (div_gap > 0 and sym in div_candidates
                and eff_yield and eff_yield > div_yield_trigger and signal is None):
            in_thesis = bool(thesis_groups)
            favorable = True if in_thesis else (analyst_rating in ("Strong Buy", "Buy", "Hold") if analyst_rating else True)
            yield_source = "Finviz" if div_yield else "dividend calendar"
            if favorable:
                signal = "ADD"
                rule = "R6: Dividend gap close"
                rule_id = "R6"
                note_parts.append(f"Yield {eff_yield:.1f}% ({yield_source}), div gap ${div_gap:,.0f}/yr — increase to close gap")

        # RULE 7: Thesis hold (default for thesis positions) — exempt from size gate
        if thesis_groups and signal is None:
            signal = "HOLD"
            rule = "R7: Thesis position"
            rule_id = "R7"
            note_parts.append(f"On thesis: {', '.join(thesis_names)}")

        # RULE 8: 52-week low opportunity (suppress if TRIM/EXIT active for this ticker)
        if w52_low is not None and w52_low < 10 and signal not in ("TRIM", "EXIT"):
            in_thesis = bool(thesis_groups)
            favorable = True if in_thesis else (analyst_rating in ("Strong Buy", "Buy", "Hold") if analyst_rating else True)
            in_thesis_or_wl = in_thesis or sym in watchlist
            if favorable and in_thesis_or_wl and signal in (None, "HOLD"):
                signal = "ADD"
                rule = "R8: 52-week low opportunity"
                rule_id = "R8"
                note_parts.append(f"{w52_low:.1f}% from 52-week low — favorable entry")

        # RULE 9: Insider conviction (modifier)
        if insider_trans is not None:
            if insider_trans > 5:
                note_parts.append(f"Insider buying +{insider_trans:.1f}% — conviction boost")
            elif insider_trans < -5:
                note_parts.append(f"Insider selling {insider_trans:.1f}% — caution")

        # RULE 11: Earnings proximity (downgrade TRIM/EXIT to WATCH)
        if earnings_near and signal in ("TRIM", "EXIT"):
            original = signal
            signal = "WATCH"
            rule = f"R11: Earnings in {earnings_days}d (was {original})"
            note_parts.append(f"Earnings in {earnings_days} days — wait for report before acting")

        # RULE 12: Watchlist thesis tag cross-reference
        if wl_note:
            note_parts.append(wl_note)

        # Default
        if signal is None:
            signal = "HOLD"
            rule = "Default"
            rule_id = None
            note_parts.append("No signal rule triggered")

        # ── Size gate: demote trim/entry rules to MONITOR for tiny positions ──
        size_gated = False
        if size_below and signal in ("EXIT", "TRIM", "ADD") and rule_id not in SIZE_GATE_EXEMPT_RULES:
            original_signal = signal
            signal = "MONITOR"
            size_gated = True
            note_parts.append(
                f"Position size ${total_mv:,.0f} ({total_pct:.1f}%) below "
                f"{size_gate_pct}% threshold (${size_gate_mv:,.0f}) — "
                f"not actionable at this scale (would be {original_signal})")

        signals.append({
            "symbol": sym,
            "signal": signal,
            "priority": SIGNAL_PRIORITY.get(signal, 99),
            "rule": rule,
            "note": " | ".join(note_parts),
            "accounts_context": acct_context,
            "thesis_groups": thesis_names,
            "size_below_threshold": size_gated,
            "data_points": {
                "market_value": total_mv,
                "portfolio_pct": total_pct,
                "has_finviz": True,
                "rsi": rsi, "beta": beta, "sma200_pct": sma200,
                "inst_trans_pct": inst_trans, "insider_trans_pct": insider_trans,
                "dist_pct": dist_pct, "stop_price": stop_price,
                "is_protected": is_protected, "perf_month_pct": perf_m,
                "week52_high_pct": w52_high, "week52_low_pct": w52_low,
                "div_yield_pct": div_yield, "volatility_m_pct": vol_m,
            },
        })

    # Sort by priority (EXIT first), then by portfolio_pct descending
    signals.sort(key=lambda s: (s["priority"], -(s["data_points"].get("portfolio_pct", 0))))
    return signals


def compute_coverage_summary(holdings: Dict, enrichment: Dict) -> Dict:
    """Compute Finviz + manual beta coverage stats across the portfolio.
    Uses portfolio_totals.total_value (incl cash) as canonical MV."""
    positions = holdings.get("holdings", [])
    beta_overrides = load_beta_overrides()
    # Canonical total MV including cash (matches CC scoped value)
    total_mv = holdings.get("portfolio_totals", {}).get("total_value", 0) or 0
    if total_mv <= 0:
        total_mv = sum((p.get("market_value", 0) or 0) for p in positions)

    total_count = 0
    finviz_count = 0
    finviz_mv = 0.0
    uncovered = []
    # Beta-specific coverage
    beta_finviz = 0
    beta_manual = 0
    beta_none = 0
    beta_mv_covered = 0.0
    seen_tickers = set()

    for pos in positions:
        sym = pos.get("symbol", "")
        if not sym or sym in CASH_SYMS:
            continue
        mv = pos.get("market_value", 0) or 0
        if mv <= 0:
            continue
        total_count += 1

        enr = enrichment.get(sym, {}) if isinstance(enrichment.get(sym), dict) else {}
        if enr.get("rsi") or enr.get("beta") or enr.get("perf_month_pct"):
            finviz_count += 1
            finviz_mv += mv
        else:
            if sym not in seen_tickers:
                uncovered.append(sym)

        # Beta coverage (deduplicated by ticker)
        if sym not in seen_tickers:
            seen_tickers.add(sym)
            b_val, b_src = get_beta(sym, enrichment, beta_overrides)
            if b_src == "finviz":
                beta_finviz += 1
                beta_mv_covered += mv
            elif b_src == "manual":
                beta_manual += 1
                beta_mv_covered += mv
            else:
                beta_none += 1

    beta_total_with = beta_finviz + beta_manual
    unique_tickers = len(seen_tickers)
    return {
        "positions_total": total_count,
        "positions_with_finviz": finviz_count,
        "pct_count": round(finviz_count / total_count * 100, 1) if total_count else 0,
        "mv_total": round(total_mv, 0),
        "mv_with_finviz": round(finviz_mv, 0),
        "pct_mv": round(finviz_mv / total_mv * 100, 1) if total_mv else 0,
        "uncovered_tickers": uncovered,
        "uncovered_note": (
            f"{len(uncovered)} positions without Finviz data ({', '.join(uncovered[:8])}"
            f"{'...' if len(uncovered) > 8 else ''}) excluded from position-level "
            "Finviz P&L attribution." if uncovered else "Full coverage."
        ),
        "beta_coverage": {
            "finviz": beta_finviz,
            "manual": beta_manual,
            "none": beta_none,
            "total_with_beta": beta_total_with,
            "total_tickers": unique_tickers,
            "pct_beta_coverage": round(beta_mv_covered / total_mv * 100, 1) if total_mv else 0,
        },
    }


def _derive_pl(positions: List[Dict], enrichment: Dict, pct_field: str,
               dollar_field: str) -> List[Dict]:
    """Shared logic for MTD and YTD position-level P&L derivation."""
    results = []
    for pos in positions:
        sym = pos.get("symbol", "")
        if not sym or sym in CASH_SYMS:
            continue
        mv = pos.get("market_value", 0) or 0
        if mv <= 0:
            continue
        enr = enrichment.get(sym, {}) if isinstance(enrichment.get(sym), dict) else {}
        raw_pct = enr.get(pct_field)
        if raw_pct is None:
            continue
        try:
            pct = float(raw_pct)
            start_val = mv / (1 + pct / 100)
            dollar_change = mv - start_val
        except (ValueError, ZeroDivisionError):
            continue
        results.append({
            "symbol": sym,
            "account": pos.get("account_display") or pos.get("account", ""),
            "market_value": mv,
            pct_field: pct,
            dollar_field: round(dollar_change, 2),
            "portfolio_pct": pos.get("portfolio_pct", 0) or 0,
        })
    results.sort(key=lambda r: r[dollar_field])
    return results


def compute_position_mtd_pl(holdings: Dict, enrichment: Dict,
                            perf_history: Dict) -> Dict:
    """
    Two-layer MTD P&L:
    1. Top-line total from performance_history.json (ground truth)
    2. Position-level attribution from Finviz perf_month_pct (subset)

    Returns dict with top_line, attribution list, and coverage info.
    """
    positions = holdings.get("holdings", [])
    attribution = _derive_pl(positions, enrichment, "perf_month_pct", "mtd_dollar_change")

    # Top-line from performance_history (ground truth)
    m1 = (perf_history.get("periods", {}).get("1M") or {})
    top_line_dollar = m1.get("change") or 0
    top_line_pct = m1.get("change_pct") or 0

    # Coverage — use canonical MV (including cash) to match CC
    covered_mv = sum(r["market_value"] for r in attribution)
    total_mv = holdings.get("portfolio_totals", {}).get("total_value", 0) or 0
    if total_mv <= 0:
        total_mv = sum((p.get("market_value", 0) or 0) for p in positions)
    noncash_count = len([p for p in positions if p.get("symbol") not in CASH_SYMS and (p.get("market_value",0) or 0) > 0])
    attr_total = sum(r["mtd_dollar_change"] for r in attribution)

    # Fidelity 401k account-level residual
    fidelity_residual = top_line_dollar - attr_total

    return {
        "top_line": {
            "dollar": round(top_line_dollar, 0),
            "pct": top_line_pct,
            "source": "performance_history.json periods.1M",
        },
        "attribution": attribution,
        "attribution_total": round(attr_total, 0),
        "fidelity_401k_residual": round(fidelity_residual, 0),
        "coverage": {
            "positions_covered": len(attribution),
            "positions_total": noncash_count,
            "mv_covered": round(covered_mv, 0),
            "mv_total": round(total_mv, 0),
            "pct_mv": round(covered_mv / total_mv * 100, 1) if total_mv else 0,
        },
    }


def compute_position_ytd_pl(holdings: Dict, enrichment: Dict,
                            perf_history: Dict) -> Dict:
    """Same two-layer approach for YTD."""
    positions = holdings.get("holdings", [])
    attribution = _derive_pl(positions, enrichment, "perf_ytd_pct", "ytd_dollar_change")

    ytd = (perf_history.get("periods", {}).get("YTD") or {})
    top_line_dollar = ytd.get("change") or 0
    top_line_pct = ytd.get("change_pct") or 0

    covered_mv = sum(r["market_value"] for r in attribution)
    total_mv = holdings.get("portfolio_totals", {}).get("total_value", 0) or 0
    if total_mv <= 0:
        total_mv = sum((p.get("market_value", 0) or 0) for p in positions)
    noncash_count = len([p for p in positions if p.get("symbol") not in CASH_SYMS and (p.get("market_value",0) or 0) > 0])
    attr_total = sum(r["ytd_dollar_change"] for r in attribution)
    fidelity_residual = top_line_dollar - attr_total

    return {
        "top_line": {
            "dollar": round(top_line_dollar, 0),
            "pct": top_line_pct,
            "source": "performance_history.json periods.YTD",
        },
        "attribution": attribution,
        "attribution_total": round(attr_total, 0),
        "fidelity_401k_residual": round(fidelity_residual, 0),
        "coverage": {
            "positions_covered": len(attribution),
            "positions_total": noncash_count,
            "mv_covered": round(covered_mv, 0),
            "mv_total": round(total_mv, 0),
            "pct_mv": round(covered_mv / total_mv * 100, 1) if total_mv else 0,
        },
    }


def golden_window_roth_note(retirement: Dict, perf: Dict) -> str:
    """
    Rule 10: Golden Window Roth advisory note (NOT a position signal).
    Returns a human-readable note for the Commander's Summary.
    """
    golden_days = retirement.get("key_dates", {}).get("days_to_golden", 0)
    trad_val = retirement.get("accounts", {}).get("traditional", 0) or 0
    roth_val = retirement.get("accounts", {}).get("roth", 0) or 0

    ytd_pct = (perf.get("periods", {}).get("YTD") or {}).get("change_pct", 0) or 0

    parts = []
    if ytd_pct < -10:
        parts.append(f"Market down {ytd_pct:+.1f}% YTD — favorable environment for Roth conversion at discount")
    elif ytd_pct < -5:
        parts.append(f"Market soft {ytd_pct:+.1f}% YTD — reasonable window for additional Roth conversion")
    else:
        parts.append(f"Market {ytd_pct:+.1f}% YTD — standard conversion pace appropriate")

    if golden_days > 0:
        years = golden_days / 365.25
        annual_needed = trad_val / years if years > 0 else 0
        parts.append(f"{golden_days:,} days to Golden Window — need ~${annual_needed:,.0f}/yr to zero Traditional IRA")

    parts.append(f"Traditional: ${trad_val:,.0f} | Roth: ${roth_val:,.0f}")

    return " | ".join(parts)


def generate_and_save_signals(project_root: str = ".") -> Path:
    """
    Run the full signals engine and save output to action_signals.json.
    Called by the daily pipeline orchestrator.
    Returns path to the saved file.
    """
    root = Path(project_root)
    state = root / "data" / "portfolios" / "state"

    holdings = _load_json(state / "holdings.json")
    enrichment = _load_json(state / "ticker_enrichment_cache.json")
    risk = _load_json(state / "risk_management.json")
    retirement = _load_json(state / "retirement_roadmap.json")
    dividends = _load_json(state / "dividend_calendar.json")
    watchlist = _load_json(state / "watchlist.json")
    perf = _load_json(state / "performance_history.json")

    signals = generate_action_signals(
        holdings, enrichment, risk, retirement, dividends, watchlist
    )
    coverage = compute_coverage_summary(holdings, enrichment)
    gw_note = golden_window_roth_note(retirement, perf)

    # Build compact output for CC consumption
    output = {
        "generated_at": datetime.now().isoformat(),
        "coverage": coverage,
        "golden_window_note": gw_note,
        "signals": [{
            "symbol": s["symbol"],
            "signal": s["signal"],
            "rule": s["rule"],
            "note": s["note"],
            "accounts_context": s.get("accounts_context", ""),
            "thesis_groups": s["thesis_groups"],
            "portfolio_pct": s["data_points"]["portfolio_pct"],
            "market_value": s["data_points"]["market_value"],
            "has_finviz": s["data_points"].get("has_finviz", True),
            "size_below_threshold": s.get("size_below_threshold", False),
        } for s in signals],
    }

    out_path = state / "action_signals.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"  [signals] Saved {len(signals)} signals to {out_path}")

    # Postgres dual-write: daily signal history (non-blocking)
    try:
        from db_adapter import save_signals_history
        _today = datetime.now().strftime("%Y-%m-%d")
        save_signals_history(output["signals"], _today)
    except Exception as _she:
        print(f"  [signals] Postgres history write failed (JSON saved OK): {_she}")

    return out_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate rules-based action signals")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    generate_and_save_signals(args.project_root)
```
