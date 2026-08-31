#!/usr/bin/env python3
"""strategy_signal_sync.py — Sync GO/A+ scans into strategy_signals.

Bridges the gap between trade_ai_scans (screener output) and strategy_signals
(Strategy Desk input). Ensures GO/A+ decisions become actionable signals.

Usage:
    .venv/bin/python scripts/strategy_signal_sync.py --today
    .venv/bin/python scripts/strategy_signal_sync.py --run-label 0700
    .venv/bin/python scripts/strategy_signal_sync.py --date 2026-05-06
    .venv/bin/python scripts/strategy_signal_sync.py --symbols BDSX,BLZE
    .venv/bin/python scripts/strategy_signal_sync.py --dry-run --today
"""
import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("signal_sync")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def get_conn():
    import psycopg2
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
    )


def _get_strategy_signals_columns(conn):
    """Get actual column names in strategy_signals for schema-adaptive insert."""
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'strategy_signals'
        ORDER BY ordinal_position
    """)
    return {row[0] for row in cur.fetchall()}


def get_today_go_scans(conn, run_label=None, symbols=None, target_date=None, lookback_days=None):
    """Get GO/A+ scans from trade_ai_scans (today by default, or lookback window)."""
    cur = conn.cursor()
    if lookback_days:
        time_clause = "scanned_at > NOW() - (%s || ' days')::interval"
        time_params = [str(lookback_days)]
    else:
        date_clause = "CURRENT_DATE" if not target_date else f"'{target_date}'::date"
        time_clause = f"(scanned_at AT TIME ZONE 'America/New_York')::date = {date_clause}"
        time_params = []

    sql = f"""
        SELECT DISTINCT ON (symbol)
            id, symbol, score, grade, decision, rvol, float_m, gap_pct, price,
            catalyst, catalyst_verified, catalyst_confidence,
            critic_verdict, critic_confidence, critic_reasoning,
            sector, industry, country, sector_etf,
            source, screener_label, run_label, scanned_at,
            intelligence_readiness, change_pct,
            ticker_perf_1m, sector_perf_1m, vs_sector_pct,
            discovery_trace_id,
            route, route_actionability, route_strategy_id
        FROM trade_ai_scans
        WHERE decision IN ('GO', 'A+')
        AND {time_clause}
        {"AND run_label = %s" if run_label else ""}
        {"AND symbol = ANY(%s)" if symbols else ""}
        ORDER BY symbol, score DESC, scanned_at DESC
    """
    params = list(time_params)
    if run_label:
        params.append(run_label)
    if symbols:
        params.append(symbols)

    cur.execute(sql, params or None)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _load_strategy_configs() -> dict:
    """Load all strategy YAML configs from config/strategies/."""
    import yaml
    configs = {}
    strat_dir = PROJECT_ROOT / "config" / "strategies"
    if not strat_dir.exists():
        return configs
    for f in strat_dir.glob("*.yaml"):
        if f.name in ("shared_risk_rules.yaml", "recommendation_schema.yaml"):
            continue
        try:
            cfg = yaml.safe_load(f.read_text()) or {}
            sid = cfg.get("strategy_id")
            if sid:
                configs[sid] = cfg
        except Exception:
            pass
    return configs


def candidate_matches_strategy(scan: dict, cfg: dict) -> tuple:
    """Check if a scan candidate matches a strategy's YAML criteria.
    Returns (matches: bool, match_reasons: list, reject_reasons: list).
    """
    filters = cfg.get("screen_filters", {})
    if not filters:
        return False, [], ["no screen_filters defined"]
    match_reasons = []
    reject_reasons = []

    price = float(scan.get("price") or 0)
    rvol = float(scan.get("rvol") or 0)
    float_m = float(scan.get("float_m") or 0)
    gap = abs(float(scan.get("gap_pct") or 0))

    # Price range
    min_price = float(filters.get("min_price", 0))
    max_price = float(filters.get("max_price", 99999))
    if price < min_price:
        reject_reasons.append(f"price {price:.2f} < min {min_price}")
    elif price > max_price:
        reject_reasons.append(f"price {price:.2f} > max {max_price}")
    else:
        match_reasons.append(f"price {price:.2f} in [{min_price}-{max_price}]")

    # RVOL
    min_rvol = float(filters.get("min_rvol", 0))
    if min_rvol > 0 and rvol < min_rvol:
        reject_reasons.append(f"rvol {rvol:.1f} < min {min_rvol}")
    elif min_rvol > 0:
        match_reasons.append(f"rvol {rvol:.1f} >= {min_rvol}")

    # Float
    max_float = float(filters.get("max_float_m", 99999))
    if float_m > 0 and float_m > max_float:
        reject_reasons.append(f"float {float_m:.0f}M > max {max_float}M")
    elif float_m > 0:
        match_reasons.append(f"float {float_m:.0f}M <= {max_float}M")

    # Gap
    min_gap = float(filters.get("min_gap_pct", 0))
    if min_gap > 0 and gap < min_gap:
        reject_reasons.append(f"gap {gap:.1f}% < min {min_gap}%")
    elif min_gap > 0:
        match_reasons.append(f"gap {gap:.1f}% >= {min_gap}%")

    # Min score
    score = float(scan.get("score") or 0)
    min_score = float(filters.get("min_score", 0))
    if min_score > 0 and score < min_score:
        reject_reasons.append(f"score {score:.0f} < min {min_score}")
    elif min_score > 0:
        match_reasons.append(f"score {score:.0f} >= {min_score}")

    # Require no rejections AND at least 2 meaningful (non-trivial) match reasons.
    # A "meaningful" match is one where the filter actually constrains the candidate,
    # not just "price in [0-99999]" which passes everything.
    meaningful = [r for r in match_reasons if "99999" not in r and "5000" not in r]
    matches = len(reject_reasons) == 0 and len(meaningful) >= 2
    return matches, match_reasons, reject_reasons


def route_candidate_to_strategies(scan: dict, configs: dict) -> list:
    """Route a candidate to all matching strategies.
    Returns list of (strategy_id, match_reasons, reject_reasons) tuples.
    """
    # Route against ALL loaded strategy configs, not just day-scalp
    matches = []
    for sid, cfg in configs.items():
        if not cfg or sid.startswith('_'):
            continue
        ok, match_r, reject_r = candidate_matches_strategy(scan, cfg)
        if ok:
            matches.append((sid, match_r, reject_r))
    return matches


def infer_strategy_id(scan: dict) -> str:
    """Legacy single-strategy inference. Used as fallback when no YAML matches.

    P0-1: standard momentum_scalp is MICRO-float (<=20M) + VERIFIED catalyst — aligned to
    momentum_scalp.yaml. A large-float (>20M) verified name can NEVER become momentum_scalp;
    it routes to large_float_social_scout (manual review). Missing float ⇒ no momentum_scalp.
    """
    gap = abs(float(scan.get('gap_pct') or 0))
    price = float(scan.get('price') or 0)
    rvol = float(scan.get('rvol') or 0)
    _fm = scan.get('float_m')
    float_m = float(_fm) if _fm not in (None, '') else None
    cat_v = bool(scan.get('catalyst_verified', False))

    # Standard momentum_scalp: micro-float (<=20M) + verified catalyst + RVOL/gap/price (matches YAML).
    if (cat_v and float_m is not None and 0 < float_m <= 20.0
            and 1.0 <= price <= 25.0 and rvol >= 5.0 and gap >= 5.0):
        return 'momentum_scalp'

    # Large-float (>20M) verified momentum/social → scout (MANUAL REVIEW), NEVER momentum_scalp.
    if (cat_v and float_m is not None and float_m > 20.0
            and rvol >= 5.0 and 1.0 <= price <= 50.0):
        return 'large_float_social_scout'

    # gap_and_go: meaningful gap + volume
    if gap >= 5.0 and rvol >= 2.0 and 1.0 <= price <= 50.0:
        return 'gap_and_go'

    # earnings_catalyst: verified catalyst, any size
    if cat_v and rvol >= 1.5:
        return 'earnings_catalyst'

    # swing_breakout: catch-all for GO signals
    if rvol >= 1.5 and price >= 2.0:
        return 'swing_breakout'

    # Default to gap_and_go rather than momentum_scalp
    return 'gap_and_go'


def route_enforced_strategy(scan: dict, proposed_sid: str) -> tuple:
    """P0-6: durable route/actionability fields (when present on the scan) OVERRIDE loose
    YAML/fallback routing. Returns (allowed_strategy_id | None, reason).

    * route=momentum_scalp + actionability=GO  → may create momentum_scalp.
    * route=watch_only                          → no tradeable signal (None).
    * route=meme_squeeze_momentum / large_float_social_scout → must NOT create momentum_scalp;
      may create that route's own (manual-review) signal.
    * source includes social + catalyst_verified=false → never momentum_scalp.
    Missing route fields → strict YAML/fallback (proposed_sid unchanged).
    """
    route = (scan.get('route') or '').strip().lower()
    actionability = (scan.get('route_actionability') or '').strip().upper()
    source = str(scan.get('source') or '').lower()
    cat_v = bool(scan.get('catalyst_verified', False))
    scout_status = str(scan.get('scout_status') or '').strip().upper()

    # P0-6: a Social Scout is operator-awareness ONLY — it can never create a strategy signal. A
    # graduated GO has scout_status=NONE (the route policy suppresses the pill on GO), so this never
    # blocks a legitimate momentum_scalp/GO.
    if scout_status == 'SOCIAL_SCOUT':
        return None, "scout_status=SOCIAL_SCOUT_awareness_only_no_signal"

    # Social + unverified can never become momentum_scalp, regardless of other fields.
    if proposed_sid == 'momentum_scalp' and 'social' in source and not cat_v:
        return None, "social_unverified_blocked_from_momentum_scalp"

    if not route:
        return proposed_sid, "no_durable_route:strict_yaml_fallback"

    if proposed_sid == 'momentum_scalp':
        if route == 'momentum_scalp' and actionability == 'GO':
            return 'momentum_scalp', "route=momentum_scalp/GO"
        return None, f"route={route}/{actionability or '-'}_blocks_momentum_scalp"

    # Non-momentum proposed strategy:
    if route == 'watch_only':
        return None, "route=watch_only_advisory_no_signal"
    return proposed_sid, f"route={route}"


def find_trade_plan(conn, symbol: str, scan_time=None) -> dict:
    """Find the best trade plan for a symbol."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, entry_low, entry_high, stop_loss,
               target_1, target_2, shares, dollar_risk, risk_reward_1,
               generated_at
        FROM trade_plans
        WHERE symbol = %s
        AND NOT COALESCE(disqualified, false)
        ORDER BY generated_at DESC
        LIMIT 1
    """, [symbol])
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def validate_long_trade_plan(entry, stop, target) -> tuple:
    """Validate a long trade plan. Returns (valid, issues)."""
    issues = []
    if entry is None or entry <= 0:
        issues.append("entry missing or zero")
        return False, issues
    if stop is None:
        issues.append("stop_loss missing")
    elif stop >= entry:
        issues.append(f"stop_loss ${stop:.2f} >= entry ${entry:.2f} (inverted)")
    if target is None:
        issues.append("target_1 missing")
    elif target <= entry:
        issues.append(f"target_1 ${target:.2f} <= entry ${entry:.2f} (no upside)")
    return len(issues) == 0, issues


def build_setup_description(scan: dict, plan: dict) -> str:
    """Build human-readable setup description."""
    parts = []
    rvol = scan.get('rvol')
    if rvol:
        parts.append(f"RVOL {float(rvol):.1f}x")
    float_m = scan.get('float_m')
    if float_m:
        parts.append(f"Float {float(float_m):.0f}M")
    gap = scan.get('gap_pct')
    if gap:
        parts.append(f"Gap {float(gap):+.1f}%")
    if scan.get('catalyst_verified'):
        parts.append("Verified catalyst")
    elif scan.get('catalyst'):
        parts.append("Unverified catalyst")
    grade = scan.get('grade', '')
    score = scan.get('score', 0)
    if grade and score:
        parts.append(f"{grade} {score}pts")
    source = scan.get('source', '')
    if source:
        parts.append(f"Source {source}")
    return " | ".join(parts)


def insert_strategy_signal(conn, scan: dict, plan: dict, available_cols: set,
                           sync_run_id: str, dry_run=False, route_data: dict = None,
                           max_price_drift_pct: float = 3.0,
                           max_signal_drift_pct: float = 25.0) -> dict:
    """Insert or update a strategy_signal row. Returns status dict."""
    symbol = scan['symbol']
    strategy_id = scan.get('strategy_id') or infer_strategy_id(scan)
    cur = conn.cursor()

    # Check idempotency — existing signal for same symbol/strategy/date
    cur.execute("""
        SELECT id FROM strategy_signals
        WHERE symbol = %s AND strategy_id = %s
        AND fired_at::date = %s
        AND status IN ('active','pending','PENDING','ACTIVE')
        LIMIT 1
    """, [symbol, strategy_id, datetime.now(timezone.utc).strftime('%Y-%m-%d')])
    existing = cur.fetchone()

    if existing:
        return {"status": "skipped", "reason": "duplicate", "signal_id": existing[0]}

    # ── Live price re-pricing ──
    # The screener `price` is the DISCOVERY price (an intraday/premarket snapshot), not the
    # execution price. Micro-float momentum names routinely move 40-110% intraday, so the
    # discovery price drifts far more than 3% from the live quote as a matter of course — a
    # fixed 3% reject was dropping every GO signal (inserted: 0 → proposals: 0). The correct
    # behavior is to re-price the entry to the live quote, and only reject on a hard ceiling
    # that signals stale/corrupt data rather than a normal volatile fade. Fill-time drift is
    # still enforced downstream (momentum_scalp.yaml intraday_execution.max_price_drift_pct
    # and the paper fast path).
    price = float(scan.get('price') or 0)
    if price > 0:
        try:
            from market_quote_provider import get_best_quote
            live_q = get_best_quote(symbol)
            if live_q and live_q.get("last_price"):
                live_px = float(live_q["last_price"])
                if live_px > 0:
                    drift_pct = abs(live_px - price) / price * 100
                    if drift_pct > max_signal_drift_pct:
                        log.warning(
                            f"  {symbol}: screener price ${price:.2f} vs live ${live_px:.2f} "
                            f"({drift_pct:.1f}%) exceeds hard ceiling {max_signal_drift_pct:.0f}% — skipping signal"
                        )
                        return {"status": "skipped",
                                "reason": f"price_drift_{drift_pct:.1f}pct (screener=${price:.2f} live=${live_px:.2f})"}
                    if drift_pct > max_price_drift_pct:
                        log.info(
                            f"  {symbol}: screener ${price:.2f} vs live ${live_px:.2f} "
                            f"({drift_pct:.1f}%) — re-pricing entry to live quote"
                        )
                    # Use live price for signal entry.
                    price = live_px
        except Exception as e:
            log.warning(f"  {symbol}: live price check failed ({e}) — using screener price")

    # Get entry/stop/target from plan or scan price
    entry = price
    stop = None
    target = None
    shares = 0
    dollar_risk = 0
    rr = 0

    if plan:
        plan_entry = float(plan.get('entry_high') or plan.get('entry_low') or price)
        # If live price available and plan entry drifted, use live price as entry
        plan_drift = abs(price - plan_entry) / plan_entry * 100 if plan_entry > 0 else 0
        entry = price if plan_drift > 1.0 else plan_entry
        stop = float(plan['stop_loss']) if plan.get('stop_loss') else None
        target = float(plan['target_1']) if plan.get('target_1') else None
        shares = int(plan.get('shares') or 0)
        dollar_risk = float(plan.get('dollar_risk') or 0)
        rr = float(plan.get('risk_reward_1') or 0)
    else:
        # Generate basic plan from price — 2:1 minimum R:R
        atr_est = price * 0.05  # rough 5% ATR estimate
        stop = round(price - atr_est, 2)
        target = round(price + atr_est * 2.0, 2)  # 2:1 R:R minimum
        shares = max(1, int(2000 / price)) if price > 0 else 0
        dollar_risk = round(abs(price - stop) * shares, 2)
        rr = round((target - price) / (price - stop), 2) if price > stop else 0

    # Validate long trade plan
    valid, issues = validate_long_trade_plan(entry, stop, target)
    if not valid:
        log.warning(f"  {symbol}: invalid plan — {', '.join(issues)}")
        # Auto-fix inverted stop for long
        if stop is not None and stop >= entry:
            stop = round(entry - max(entry * 0.05, 0.20), 2)
            log.info(f"  {symbol}: auto-fixed stop to ${stop:.2f}")
        if target is not None and target <= entry:
            target = round(entry + (entry - stop) * 1.5, 2)
            log.info(f"  {symbol}: auto-fixed target to ${target:.2f}")
        # Re-validate
        valid, issues = validate_long_trade_plan(entry, stop, target)
        if not valid:
            return {"status": "skipped", "reason": f"invalid_plan: {', '.join(issues)}"}

    # Recalculate risk/reward after any fix
    if stop and target and entry:
        rr = round((target - entry) / (entry - stop), 2) if entry > stop else 0
        if shares == 0 and price > 0:
            shares = max(1, int(2000 / price))
        dollar_risk = round(abs(entry - stop) * shares, 2)

    if dry_run:
        return {
            "status": "dry_run",
            "symbol": symbol,
            "strategy_id": strategy_id,
            "entry": entry,
            "stop": stop,
            "target": target,
            "shares": shares,
            "dollar_risk": dollar_risk,
            "rr": rr,
        }

    # Build column/value pairs adaptively
    data = {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "signal_type": "GO",
        "signal_grade": scan.get('grade'),
        "signal_score": scan.get('score'),
        "price": price,
        "rvol": scan.get('rvol'),
        "float_m": scan.get('float_m'),
        "gap_pct": scan.get('gap_pct'),
        "catalyst": (scan.get('catalyst') or '')[:200],
        "catalyst_verified": scan.get('catalyst_verified', False),
        "setup_description": build_setup_description(scan, plan),
        "entry_low": float(plan.get('entry_low') or entry) if plan else entry,
        "entry_high": entry,
        "stop_loss": stop,
        "target_1": target,
        "target_2": float(plan.get('target_2')) if plan and plan.get('target_2') else None,
        "risk_reward": rr,
        "shares": shares,
        "dollar_risk": dollar_risk,
        "sector": scan.get('sector'),
        "intel_readiness": scan.get('intelligence_readiness'),
        "status": "active",
        "fired_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=8),
    }

    # Lineage columns (only if they exist in schema)
    lineage = {
        "source_table": "trade_ai_scans",
        "source_record_id": str(scan.get('id', '')),
        "scan_run_label": scan.get('run_label'),
        "screener_label": scan.get('screener_label'),
        "discovery_source": scan.get('source'),
        "discovery_trace_id": scan.get('discovery_trace_id'),  # P0-6: complete scan→signal→proposal chain
        "sync_created_by": "strategy_signal_sync",
        "sync_run_id": sync_run_id,
    }

    for k, v in lineage.items():
        if k in available_cols:
            data[k] = v

    # Route tracking columns
    if route_data:
        route_cols = {
            "route_match_reasons": json.dumps(route_data.get("route_match_reasons", [])),
            "route_reject_reasons": json.dumps(route_data.get("route_reject_reasons", [])),
        }
        for k, v in route_cols.items():
            if k in available_cols:
                data[k] = v

    # Filter to only existing columns
    insert_data = {k: v for k, v in data.items() if k in available_cols}

    cols_str = ", ".join(insert_data.keys())
    placeholders = ", ".join(["%s"] * len(insert_data))

    # NOTE: deliberately a plain INSERT. An `ON CONFLICT (strategy_id, symbol,
    # signal_type, fired_at) DO NOTHING` clause was added 2026-08-08 (f0446ff33)
    # naming a constraint that does not exist -- there is no unique index on those
    # four columns and none was ever migrated. Postgres rejects the whole statement,
    # not the row ("there is no unique or exclusion constraint matching the ON
    # CONFLICT specification"), so EVERY signal insert raised for 24 days and the
    # Strategy Desk went empty. Idempotency is already enforced above, on
    # (symbol, strategy_id, fired_at::date, active/pending) -- a strictly broader key
    # than that clause, which keyed on an exact fired_at timestamp that would
    # essentially never collide. Do not re-add the clause without first creating and
    # migrating the matching unique index.
    cur.execute(
        f"INSERT INTO strategy_signals ({cols_str}) VALUES ({placeholders}) "
        f"RETURNING id",
        list(insert_data.values())
    )
    row = cur.fetchone()
    if row is None:
        # Not reachable for a plain INSERT ... RETURNING (it raises rather than
        # returning no row), but the caller does result.get('status'), so never
        # return a bare None -- that would AttributeError into the generic handler
        # and be counted as an opaque error.
        conn.rollback()
        return {"status": "skipped", "reason": "insert_returned_no_row", "signal_id": None}
    signal_id = row[0]

    # Phase B-1c: also write to watchpool if strategy is watchpool-routed
    try:
        from strategy_watchpool import maybe_write_watchpool
        cfg = _load_strategy_configs().get(strategy_id, {})
        snapshot = {"price": float(scan.get("price") or 0), "rvol": float(scan.get("rvol") or 0),
                    "score": float(scan.get("score") or 0), "signal_id": signal_id}
        maybe_write_watchpool(strategy_id, symbol, scan.get("screener_id", "unknown"), snapshot, cfg)
    except Exception as _wp_err:
        log.warning(f"watchpool write non-fatal: {_wp_err}")

    return {"status": "inserted", "signal_id": signal_id, "symbol": symbol, "strategy_id": strategy_id}


def sync_strategy_signals(conn, run_label=None, symbols=None, target_date=None,
                          lookback_days=None, dry_run=False) -> dict:
    """Main sync function. Returns audit dict."""
    cur = conn.cursor()
    sync_run_id = f"sync_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    # Get available columns for schema-adaptive insert
    available_cols = _get_strategy_signals_columns(conn)

    # Count strategy_signals before
    cur.execute("""
        SELECT COUNT(*) FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
    """)
    signals_before = cur.fetchone()[0] or 0

    # Get GO/A+ scans
    scans = get_today_go_scans(
        conn, run_label=run_label, symbols=symbols, target_date=target_date,
        lookback_days=lookback_days,
    )
    go_count = sum(1 for s in scans if s.get('decision') == 'GO')
    aplus_count = sum(1 for s in scans if s.get('decision') == 'A+')

    log.info(f"Found {len(scans)} GO/A+ scans (GO={go_count}, A+={aplus_count})")
    log.info(f"strategy_signals before: {signals_before}")

    # Load strategy YAML configs for multi-strategy routing
    strategy_configs = _load_strategy_configs()
    log.info(f"Loaded {len(strategy_configs)} strategy configs: {list(strategy_configs.keys())}")

    inserted = 0
    updated = 0
    skipped = 0
    errors = 0
    invalid_plans = 0
    no_strategy_match = 0
    route_summary = {}
    details = []

    for scan in scans:
        symbol = scan['symbol']
        try:
            plan = find_trade_plan(conn, symbol)

            # Multi-strategy routing: evaluate against all strategy YAMLs
            routes = route_candidate_to_strategies(scan, strategy_configs)

            if not routes:
                # Fallback: use legacy single-strategy inference
                fallback_sid = infer_strategy_id(scan)
                routes = [(fallback_sid, ["fallback_inference"], [])]
                no_strategy_match += 1
                log.info(f"  {symbol}: no YAML match, fallback to {fallback_sid}")

            for strategy_id, match_reasons, reject_reasons in routes:
                # P0-6: durable route/actionability enforcement overrides loose YAML/fallback.
                allowed_sid, enforce_reason = route_enforced_strategy(scan, strategy_id)
                if allowed_sid is None:
                    log.info(f"  {symbol}: route-enforcement blocked {strategy_id} ({enforce_reason})")
                    continue
                strategy_id = allowed_sid
                match_reasons = list(match_reasons) + [f"route_enforced:{enforce_reason}"]

                # Override strategy_id for this insertion
                scan_copy = dict(scan)
                scan_copy['strategy_id'] = strategy_id

                # Store route reasons
                route_data = {
                    "route_match_reasons": match_reasons,
                    "route_reject_reasons": reject_reasons,
                }

                result = insert_strategy_signal(
                    conn, scan_copy, plan, available_cols, sync_run_id,
                    dry_run=dry_run, route_data=route_data,
                )

                status = result.get('status')
                if status == 'inserted':
                    inserted += 1
                    route_summary[strategy_id] = route_summary.get(strategy_id, 0) + 1
                    log.info(f"  {symbol}: inserted → {strategy_id} (signal #{result.get('signal_id')}) [{', '.join(match_reasons[:3])}]")
                elif status == 'skipped' and result.get('reason') == 'duplicate':
                    skipped += 1
                    log.info(f"  {symbol}: skipped {strategy_id} (already exists)")
                elif status == 'skipped':
                    if 'invalid_plan' in str(result.get('reason', '')):
                        invalid_plans += 1
                    else:
                        skipped += 1
                    log.warning(f"  {symbol}: skipped {strategy_id} — {result.get('reason')}")
                elif status == 'dry_run':
                    route_summary[strategy_id] = route_summary.get(strategy_id, 0) + 1
                    log.info(f"  [dry-run] {symbol}: would insert {strategy_id} entry=${result.get('entry'):.2f} stop=${result.get('stop'):.2f} target=${result.get('target'):.2f}")

                details.append(result)

        except Exception as e:
            errors += 1
            log.error(f"  {symbol}: error — {e}")
            details.append({"status": "error", "symbol": symbol, "error": str(e)})
            try:
                conn.rollback()
            except Exception:
                pass

    # Print routing summary
    log.info(f"\nStrategy routing summary:")
    for sid, cnt in sorted(route_summary.items(), key=lambda x: -x[1]):
        log.info(f"  {sid}: {cnt} signals")
    if no_strategy_match:
        log.info(f"  no_strategy_match (fallback): {no_strategy_match}")

    if not dry_run:
        try:
            conn.commit()
        except Exception as e:
            log.error(f"Commit failed: {e}")
            conn.rollback()

    # Count after
    cur.execute("""
        SELECT COUNT(*) FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
    """)
    signals_after = cur.fetchone()[0] or 0

    # Write audit
    # Third state: NO_GO_TODAY. Without it this audit reads OK whenever there are zero
    # GO/A+ scans, because `go>0 and after==0` is false -- so "the upstream produced
    # nothing" is indistinguishable from "everything worked". During the 2026-08
    # outage signal_flow_audit read OK on 08-28, 08-30 and 08-31 while the Strategy
    # Desk was empty, purely because discovery had also stopped. A green that only
    # means "nothing to do" is the same defect as the alarm this table exists to
    # corroborate, and it is why the audit did not contradict the green tick.
    #
    # The name is NOT new. session18_signal_flow_health.py:62 already emits
    # "NO_GO_TODAY" for exactly this condition, and writes to this same table. Coining
    # a second name (NO_INPUT) would have put two labels for one state into one column
    # -- the drift INTEGRATION_RULES.md exists to prevent. One canonical name per
    # concept; this adopts the one that already ships.
    scans_in = go_count + aplus_count
    if scans_in == 0:
        audit_status = "NO_GO_TODAY"
    elif signals_after == 0:
        audit_status = "CRITICAL"
    elif signals_after < scans_in * 0.5:
        audit_status = "WARN"
    else:
        audit_status = "OK"

    if not dry_run:
        try:
            cur.execute("""
                INSERT INTO signal_flow_audit
                    (run_label, run_date, source_component,
                     go_count, aplus_count,
                     strategy_signals_before, strategy_signals_after,
                     inserted_count, updated_count, skipped_count, error_count,
                     status, details)
                VALUES (%s, CURRENT_DATE, 'strategy_signal_sync',
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, [
                run_label or 'manual',
                go_count, aplus_count,
                signals_before, signals_after,
                inserted, updated, skipped, errors,
                audit_status,
                json.dumps({"details": [d.get('symbol', '?') + ':' + d.get('status', '?') for d in details]})
            ])
            conn.commit()
        except Exception as e:
            log.warning(f"Audit write failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

    result = {
        "go_count": go_count,
        "aplus_count": aplus_count,
        "strategy_signals_before": signals_before,
        "strategy_signals_after": signals_after,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "invalid_plans": invalid_plans,
        "errors": errors,
        "no_strategy_match": no_strategy_match,
        "route_summary": route_summary,
        "status": audit_status,
        "dry_run": dry_run,
        "sync_run_id": sync_run_id,
    }

    log.info(f"Sync complete: {json.dumps(result)}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Strategy signal sync — GO/A+ scans → strategy_signals")
    parser.add_argument("--today", action="store_true", help="Sync today's GO/A+ scans")
    parser.add_argument("--run-label", type=str, help="Filter by run label (0400, 0700, 0900, 1000)")
    parser.add_argument("--date", type=str, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be inserted")
    args = parser.parse_args()

    if not args.today and not args.run_label and not args.date and not args.symbols:
        print("Usage: --today or --run-label 0700 or --date 2026-05-06 or --symbols BDSX,BLZE")
        print("       Add --dry-run to preview without inserting")
        sys.exit(1)

    conn = get_conn()
    try:
        symbols = args.symbols.upper().split(',') if args.symbols else None
        result = sync_strategy_signals(
            conn,
            run_label=args.run_label,
            symbols=symbols,
            target_date=args.date,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
