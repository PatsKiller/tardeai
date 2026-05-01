#!/usr/bin/env python3
"""event_detector.py — Level 3 autonomous agent event triggering (10 event types).

Polls the database every 15 minutes for actionable events:
  1. SEC_INSIDER_BUY   — Form 4 purchase filings (24h)           → Maria, Risk    [urgent]
  2. RSI_EXTREME       — holdings RSI <25 or >75                  → Risk           [normal]
  3. FRED_RATE_CHANGE  — DFF moved >0.25%                        → all agents     [urgent]
  4. DIVIDEND_CUT      — yield dropped >20% vs prior             → Steph, Tax     [urgent]
  5. EARNINGS_BEAT     — EPS beat >10% in last 24h               → Maria, Steph   [normal]
  6. STOP_TRIGGERED    — price ≤ stop for holdings               → Risk, Steph    [urgent]
  7. IRMAA_THRESHOLD   — projected MAGI > $103K                  → Alex, Tax      [urgent]
  8. INCOME_FLOOR_RISK — single position >20% of $55K income     → Steph, Alex    [urgent]
  9. MARKET_REGIME_CHANGE — VIX crosses 25 or 30                 → Risk, Maria    [urgent]
 10. PORTFOLIO_FRESH_NEEDED — holdings not analyzed >48h          → Risk, Steph    [normal]

Usage:
    python3 scripts/event_detector.py          # Run once, check all events
    python3 scripts/event_detector.py --dry-run  # Check without inserting

Cron: */15 * * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/event_detector.py >> logs/event_detector.log 2>&1
"""

import json
import os
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
COOLDOWN_HOURS = 4

# ── Helpers ──────────────────────────────────────────────────────────────

def _env(key: str) -> str:
    """Read a key from .env file."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return os.environ.get(key, "")
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(key, "")


def _get_conn():
    """Connect to trade_ai PostgreSQL database."""
    import psycopg2
    return psycopg2.connect(
        host="localhost",
        dbname="trade_ai",
        user="trade_ai",
        password=_env("DB_PASSWORD"),
    )


def _log(msg: str):
    """Log with timestamp to stdout (cron captures to log file)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _already_fired(conn, event_type: str, symbol: str = None, cooldown_hours: int = None) -> bool:
    """Check if this event was already fired within the cooldown window."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cutoff = datetime.now() - timedelta(hours=cooldown_hours or COOLDOWN_HOURS)
    if symbol:
        cur.execute(
            "SELECT id FROM agent_event_queue WHERE event_type=%s AND symbol=%s AND created_at > %s LIMIT 1",
            (event_type, symbol, cutoff),
        )
    else:
        cur.execute(
            "SELECT id FROM agent_event_queue WHERE event_type=%s AND symbol IS NULL AND created_at > %s LIMIT 1",
            (event_type, cutoff),
        )
    return cur.fetchone() is not None


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict on failure."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _fire_event(conn, event_type: str, symbol: str, trigger_data: dict,
                agents: list, priority: str = "normal", dry_run: bool = False,
                cooldown_hours: int = None) -> bool:
    """Insert an event into agent_event_queue. Returns True if inserted."""
    if _already_fired(conn, event_type, symbol, cooldown_hours):
        _log(f"  SKIP {event_type} {symbol or ''} — fired within {cooldown_hours or COOLDOWN_HOURS}h cooldown")
        return False

    if dry_run:
        _log(f"  DRY-RUN {event_type} {symbol or ''} → {agents} [{priority}]")
        return True

    cur = conn.cursor()
    cur.execute(
        """INSERT INTO agent_event_queue (event_type, symbol, trigger_data, agents_to_notify, priority)
           VALUES (%s, %s, %s, %s, %s)""",
        (event_type, symbol, json.dumps(trigger_data, default=str),
         agents, priority),
    )
    conn.commit()
    _log(f"  FIRED {event_type} {symbol or ''} → {agents} [{priority}]")
    return True


# ── Event Detectors ──────────────────────────────────────────────────────

def check_sec_insider_buy(conn, dry_run: bool = False) -> int:
    """SEC_INSIDER_BUY: any new Form 4 with transaction_type containing 'P' (Purchase) in last 24h."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cutoff = datetime.now() - timedelta(hours=24)
    cur.execute(
        """SELECT symbol, filer_name, filer_relation, transaction_type,
                  shares, price, total_value, filing_date
           FROM sec_form4
           WHERE created_at > %s
             AND (transaction_type ILIKE '%%P%%' OR transaction_type ILIKE '%%purchase%%'
                  OR transaction_type ILIKE '%%buy%%')
           ORDER BY created_at DESC""",
        (cutoff,),
    )
    rows = cur.fetchall()
    fired = 0

    for row in rows:
        sym = row.get("symbol", "")
        if not sym:
            continue
        trigger_data = {
            "filer_name": row.get("filer_name", ""),
            "filer_relation": row.get("filer_relation", ""),
            "shares": float(row.get("shares", 0)),
            "price": float(row.get("price", 0)),
            "total_value": float(row.get("total_value", 0)),
            "filing_date": str(row.get("filing_date", "")),
            "source": "sec_form4",
        }
        if _fire_event(conn, "SEC_INSIDER_BUY", sym, trigger_data,
                       ["Maria", "Risk"], priority="urgent", dry_run=dry_run):
            fired += 1

    _log(f"SEC_INSIDER_BUY: {len(rows)} purchase filings in 24h, fired {fired} events")
    return fired


def check_rsi_extreme(conn, dry_run: bool = False) -> int:
    """RSI_EXTREME: any symbol in holdings with RSI <25 or >75."""
    # Load holdings symbols
    holdings_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    if not holdings_path.exists():
        _log("RSI_EXTREME: holdings.json not found — skipping")
        return 0

    holdings = json.loads(holdings_path.read_text())
    held_symbols = set()
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        if sym and not h.get("is_cash"):
            held_symbols.add(sym)

    if not held_symbols:
        _log("RSI_EXTREME: no holdings found — skipping")
        return 0

    # Get RSI from enrichment cache (JSON file, not DB)
    enrich_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "ticker_enrichment_cache.json"
    enrichment = {}
    if enrich_path.exists():
        try:
            enrichment = json.loads(enrich_path.read_text())
        except Exception:
            pass

    # Also check technical_snapshot.json
    tech_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "technical_snapshot.json"
    tech = {}
    if tech_path.exists():
        try:
            tech = json.loads(tech_path.read_text())
        except Exception:
            pass

    fired = 0
    for sym in held_symbols:
        rsi = None

        # Try enrichment cache first
        ec = enrichment.get(sym)
        if isinstance(ec, dict) and ec.get("rsi") is not None:
            rsi = float(ec["rsi"])

        # Fallback to technical snapshot
        if rsi is None:
            tc = tech.get(sym)
            if isinstance(tc, dict) and tc.get("rsi") is not None:
                rsi = float(tc["rsi"])

        if rsi is None:
            continue

        if rsi < 25 or rsi > 75:
            direction = "oversold" if rsi < 25 else "overbought"
            trigger_data = {
                "rsi": round(rsi, 1),
                "direction": direction,
                "threshold": 25 if rsi < 25 else 75,
                "source": "enrichment_cache",
            }
            if _fire_event(conn, "RSI_EXTREME", sym, trigger_data,
                           ["Risk"], priority="normal", dry_run=dry_run):
                fired += 1

    _log(f"RSI_EXTREME: checked {len(held_symbols)} holdings, fired {fired} events")
    return fired


def check_fred_rate_change(conn, dry_run: bool = False) -> int:
    """FRED_RATE_CHANGE: DFF (Fed Funds Rate) changed >0.25% vs previous observation."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(
        """SELECT observation_date, value
           FROM fred_economic_series
           WHERE series_id = 'DFF'
           ORDER BY observation_date DESC
           LIMIT 2"""
    )
    rows = cur.fetchall()

    if len(rows) < 2:
        _log("FRED_RATE_CHANGE: insufficient DFF data (need 2+ observations) — skipping")
        return 0

    current = float(rows[0].get("value", 0))
    previous = float(rows[1].get("value", 0))
    change = abs(current - previous)

    _log(f"FRED_RATE_CHANGE: DFF current={current:.2f}%, previous={previous:.2f}%, change={change:.2f}%")

    if change >= 0.25:
        trigger_data = {
            "series_id": "DFF",
            "current_rate": current,
            "previous_rate": previous,
            "change_pct": round(change, 3),
            "direction": "up" if current > previous else "down",
            "current_date": str(rows[0].get("observation_date", "")),
            "previous_date": str(rows[1].get("observation_date", "")),
            "source": "fred_economic_series",
        }
        if _fire_event(conn, "FRED_RATE_CHANGE", None, trigger_data,
                       ["Maria", "Steph", "Risk"], priority="urgent", dry_run=dry_run):
            return 1

    return 0


# ── New Event Detectors (4–10) ────────────────────────────────────────────

def check_dividend_cut(conn, dry_run: bool = False) -> int:
    """DIVIDEND_CUT: yield dropped >20% vs prior for any dividend payer."""
    dc = _load_json(STATE_DIR / "dividend_calendar.json")
    payers = dc.get("payers", [])
    if not payers:
        _log("DIVIDEND_CUT: no payers in dividend_calendar — skipping")
        return 0

    # Check DB for prior yield snapshots
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    fired = 0
    for p in payers:
        sym = p.get("symbol", "")
        current_yield = p.get("yield_pct", 0)
        if not sym or not current_yield:
            continue

        # Look for a prior yield in income_asset_profiles or agent_intelligence_rules
        cur.execute(
            """SELECT config->>'yield_pct' as prior_yield
               FROM agent_intelligence_rules
               WHERE rule_type='dividend_yield_snapshot' AND rule_key=%s
               LIMIT 1""",
            (sym,),
        )
        row = cur.fetchone()
        if not row or not row.get("prior_yield"):
            # No prior snapshot — store current as baseline, don't fire
            try:
                cur.execute(
                    """INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                       VALUES ('dividend_yield_snapshot', %s, %s, 'event_detector', NOW())
                       ON CONFLICT (rule_type, rule_key) DO UPDATE SET config=EXCLUDED.config, updated_at=NOW()""",
                    (sym, json.dumps({"yield_pct": current_yield, "snapshot_date": str(date.today())})),
                )
                conn.commit()
            except Exception:
                conn.rollback()
            continue

        prior_yield = float(row["prior_yield"])
        if prior_yield <= 0:
            continue

        drop_pct = ((prior_yield - current_yield) / prior_yield) * 100
        if drop_pct > 20:
            trigger_data = {
                "current_yield": round(current_yield, 2),
                "prior_yield": round(prior_yield, 2),
                "drop_pct": round(drop_pct, 1),
                "annual_income": p.get("annual_income", 0),
                "source": "dividend_calendar",
            }
            if _fire_event(conn, "DIVIDEND_CUT", sym, trigger_data,
                           ["Steph", "Tax"], priority="urgent", dry_run=dry_run):
                fired += 1
        else:
            # Update snapshot with current yield
            try:
                cur.execute(
                    """UPDATE agent_intelligence_rules
                       SET config = %s, updated_at = NOW()
                       WHERE rule_type='dividend_yield_snapshot' AND rule_key=%s""",
                    (json.dumps({"yield_pct": current_yield, "snapshot_date": str(date.today())}), sym),
                )
                conn.commit()
            except Exception:
                conn.rollback()

    _log(f"DIVIDEND_CUT: checked {len(payers)} payers, fired {fired} events")
    return fired


def check_earnings_beat(conn, dry_run: bool = False) -> int:
    """EARNINGS_BEAT: EPS beat >10% for any symbol updated in last 24h."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cutoff = datetime.now() - timedelta(hours=24)

    # Get reported EPS (metric_name='EPS') fetched recently
    cur.execute(
        """SELECT f1.symbol, f1.metric_value as reported_eps, f1.fetched_at
           FROM fundamental_data f1
           WHERE f1.metric_name = 'EPS' AND f1.fetched_at > %s""",
        (cutoff,),
    )
    recent = cur.fetchall()
    if not recent:
        _log("EARNINGS_BEAT: no recent EPS data in 24h — skipping")
        return 0

    # Get estimated EPS from a prior fetch for same symbols
    fired = 0
    for row in recent:
        sym = row["symbol"]
        reported = float(row["reported_eps"] or 0)
        if reported <= 0:
            continue

        # Look for an older EPS record or an estimate
        cur.execute(
            """SELECT metric_value FROM fundamental_data
               WHERE symbol=%s AND metric_name IN ('EPS', 'EstimatedEPS', 'EPSEstimate')
               AND fetched_at < %s
               ORDER BY fetched_at DESC LIMIT 1""",
            (sym, row["fetched_at"]),
        )
        prior = cur.fetchone()
        if not prior or not prior.get("metric_value"):
            continue

        estimated = float(prior["metric_value"] or 0)
        if estimated <= 0:
            continue

        beat_pct = ((reported - estimated) / abs(estimated)) * 100
        if beat_pct > 10:
            trigger_data = {
                "reported_eps": reported,
                "estimated_eps": estimated,
                "beat_pct": round(beat_pct, 1),
                "fetched_at": str(row["fetched_at"]),
                "source": "fundamental_data",
            }
            if _fire_event(conn, "EARNINGS_BEAT", sym, trigger_data,
                           ["Maria", "Steph"], priority="normal", dry_run=dry_run):
                fired += 1

    _log(f"EARNINGS_BEAT: checked {len(recent)} recent EPS records, fired {fired} events")
    return fired


def check_stop_triggered(conn, dry_run: bool = False) -> int:
    """STOP_TRIGGERED: current price ≤ stop_price for any position with a stop."""
    rm = _load_json(STATE_DIR / "risk_management.json")
    holdings = _load_json(STATE_DIR / "holdings.json")

    # Build price map from holdings
    price_map = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        if sym and h.get("price", 0) > 0:
            price_map[sym] = h["price"]

    # Also try enrichment cache
    enrich = _load_json(STATE_DIR / "ticker_enrichment_cache.json")
    for sym, ec in enrich.items():
        if isinstance(ec, dict) and sym not in price_map and ec.get("price", 0) > 0:
            price_map[sym] = ec["price"]

    fired = 0
    for p in rm.get("positions", []):
        sym = p.get("symbol", "")
        stop = p.get("stop_price")
        if not sym or not stop:
            continue
        current = price_map.get(sym, p.get("price", p.get("current_price", 0)))
        if current <= 0:
            continue
        if current <= float(stop):
            trigger_data = {
                "current_price": round(current, 2),
                "stop_price": float(stop),
                "distance_pct": round(((current - float(stop)) / current) * 100, 2),
                "account": p.get("account", ""),
                "source": "risk_management + holdings",
            }
            if _fire_event(conn, "STOP_TRIGGERED", sym, trigger_data,
                           ["Risk", "Steph"], priority="urgent", dry_run=dry_run):
                fired += 1

    checked = len([p for p in rm.get("positions", []) if p.get("stop_price")])
    _log(f"STOP_TRIGGERED: checked {checked} positions with stops, fired {fired} events")
    return fired


def check_irmaa_threshold(conn, dry_run: bool = False) -> int:
    """IRMAA_THRESHOLD: projected MAGI > $103K (MFS Tier 1). 24h cooldown."""
    ps = _load_json(STATE_DIR / "personal_situation.json")
    fields = ps.get("fields", {})

    ssdi = fields.get("ssdi_annual", {}).get("current", 0)
    sched_c = fields.get("schedule_c_gross", {}).get("current", 0)
    se_ded = fields.get("se_tax_deduction", {}).get("current", 0)
    roth_ytd = fields.get("roth_conversion_ytd_2026", {}).get("current", 0)

    projected_magi = ssdi + sched_c - se_ded + roth_ytd
    threshold = 103000

    _log(f"IRMAA_THRESHOLD: MAGI={projected_magi:.0f} (SSDI {ssdi} + SchedC {sched_c} - SE {se_ded} + Roth {roth_ytd}) vs ${threshold:,}")

    if projected_magi > threshold:
        trigger_data = {
            "projected_magi": round(projected_magi),
            "threshold": threshold,
            "over_by": round(projected_magi - threshold),
            "components": {"ssdi": ssdi, "sched_c": sched_c, "se_deduction": se_ded, "roth_ytd": roth_ytd},
            "source": "personal_situation.json",
        }
        if _fire_event(conn, "IRMAA_THRESHOLD", None, trigger_data,
                       ["Alex", "Tax"], priority="urgent", dry_run=dry_run,
                       cooldown_hours=24):
            return 1
    return 0


def check_income_floor_risk(conn, dry_run: bool = False) -> int:
    """INCOME_FLOOR_RISK: any single position >20% of $55K income target. 24h cooldown."""
    dc = _load_json(STATE_DIR / "dividend_calendar.json")
    payers = dc.get("payers", [])
    total_income = dc.get("total_annual", 0) or sum(p.get("annual_income", 0) for p in payers)
    target = 55000
    floor = target * 0.20  # $11,000

    fired = 0
    for p in payers:
        sym = p.get("symbol", "")
        income = p.get("annual_income", 0)
        if not sym or income <= 0:
            continue
        if income > floor:
            pct_of_target = round((income / target) * 100, 1)
            trigger_data = {
                "annual_income": round(income, 2),
                "pct_of_target": pct_of_target,
                "floor_threshold": floor,
                "total_portfolio_income": round(total_income, 2),
                "yield_pct": p.get("yield_pct", 0),
                "source": "dividend_calendar",
            }
            if _fire_event(conn, "INCOME_FLOOR_RISK", sym, trigger_data,
                           ["Steph", "Alex"], priority="urgent", dry_run=dry_run,
                           cooldown_hours=24):
                fired += 1

    _log(f"INCOME_FLOOR_RISK: checked {len(payers)} payers vs ${floor:,.0f} floor, fired {fired} events")
    return fired


def check_market_regime_change(conn, dry_run: bool = False) -> int:
    """MARKET_REGIME_CHANGE: VIX crosses above 25 or 30. 6h cooldown."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(
        """SELECT observation_date, value
           FROM fred_economic_series
           WHERE series_id = 'VIXCLS'
           ORDER BY observation_date DESC
           LIMIT 1"""
    )
    row = cur.fetchone()
    if not row:
        _log("MARKET_REGIME_CHANGE: no VIXCLS data — skipping")
        return 0

    vix = float(row.get("value", 0))
    _log(f"MARKET_REGIME_CHANGE: VIX={vix:.2f}")

    fired = 0
    for threshold in [25, 30]:
        if vix >= threshold:
            regime = "high_volatility" if threshold == 25 else "extreme_volatility"
            trigger_data = {
                "vix": round(vix, 2),
                "threshold_crossed": threshold,
                "regime": regime,
                "observation_date": str(row.get("observation_date", "")),
                "source": "fred_economic_series/VIXCLS",
            }
            # Use a distinct event key per threshold so both can fire
            event_sym = f"VIX_{threshold}"
            if _fire_event(conn, "MARKET_REGIME_CHANGE", event_sym, trigger_data,
                           ["Risk", "Maria"], priority="urgent", dry_run=dry_run,
                           cooldown_hours=6):
                fired += 1

    return fired


def check_portfolio_fresh_needed(conn, dry_run: bool = False) -> int:
    """PORTFOLIO_FRESH_NEEDED: holdings not analyzed by any agent in >48h. Max 3 per run."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    holdings = _load_json(STATE_DIR / "holdings.json")
    held = set()
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        if sym and not h.get("is_cash"):
            held.add(sym)

    if not held:
        _log("PORTFOLIO_FRESH_NEEDED: no holdings — skipping")
        return 0

    # Get latest analysis time per symbol
    cur.execute(
        """SELECT symbol, MAX(created_at) as last_analysis
           FROM watchlist_agent_results
           GROUP BY symbol"""
    )
    analysis_times = {r["symbol"]: r["last_analysis"] for r in cur.fetchall()}

    cutoff = datetime.now() - timedelta(hours=48)
    stale = []
    for sym in held:
        last = analysis_times.get(sym)
        if last is None:
            stale.append((sym, None))
        elif last.replace(tzinfo=None) < cutoff:
            stale.append((sym, last))

    # Sort: never-analyzed first, then oldest
    stale.sort(key=lambda x: x[1] or datetime.min)

    fired = 0
    for sym, last in stale[:3]:  # Max 3 per run
        hours_stale = ((datetime.now() - last.replace(tzinfo=None)).total_seconds() / 3600) if last else None
        trigger_data = {
            "last_analysis": str(last)[:19] if last else "never",
            "hours_since": round(hours_stale, 1) if hours_stale else None,
            "source": "watchlist_agent_results",
        }
        if _fire_event(conn, "PORTFOLIO_FRESH_NEEDED", sym, trigger_data,
                       ["Risk", "Steph"], priority="normal", dry_run=dry_run):
            fired += 1

    _log(f"PORTFOLIO_FRESH_NEEDED: {len(stale)} stale of {len(held)} holdings, fired {fired} events (max 3)")
    return fired


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv

    _log("=" * 60)
    _log(f"Event Detector — Level 3 Autonomous Agent Triggering")
    _log(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    _log("=" * 60)

    # Ensure logs directory exists
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)

    try:
        conn = _get_conn()
    except Exception as e:
        _log(f"FATAL: Cannot connect to database: {e}")
        sys.exit(1)

    total_fired = 0
    checks = [
        ("SEC_INSIDER_BUY",       check_sec_insider_buy),
        ("RSI_EXTREME",           check_rsi_extreme),
        ("FRED_RATE_CHANGE",      check_fred_rate_change),
        ("DIVIDEND_CUT",          check_dividend_cut),
        ("EARNINGS_BEAT",         check_earnings_beat),
        ("STOP_TRIGGERED",        check_stop_triggered),
        ("IRMAA_THRESHOLD",       check_irmaa_threshold),
        ("INCOME_FLOOR_RISK",     check_income_floor_risk),
        ("MARKET_REGIME_CHANGE",  check_market_regime_change),
        ("PORTFOLIO_FRESH_NEEDED", check_portfolio_fresh_needed),
    ]

    for name, fn in checks:
        try:
            total_fired += fn(conn, dry_run)
        except Exception as e:
            _log(f"ERROR in {name} check: {e}")

    conn.close()

    _log(f"Checked {len(checks)} event types. Fired: {total_fired} events.")
    _log("")


if __name__ == "__main__":
    main()
