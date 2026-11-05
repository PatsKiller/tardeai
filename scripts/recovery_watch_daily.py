"""
recovery_watch_daily.py — Daily stopped-out detection + analyst re-entry review.

Run daily after the portfolio pipeline completes.
Entry point: main()

Flow:
1. Detect new stop-outs from risk_management.json (TRIGGERED status)
2. Classify each event: true_stop_out vs relist_no_exit vs market_reconnection
3. Auto-create stopped_out_watch records (deduped by symbol+account+date)
4. Detect relist events for symbols that reappear without a confirmed exit
5. Review all active watch items using available data
6. Update verdict/confidence/summary (relists → patience scoring, not penalties)
7. Escalate to Maria or Steph when criteria met
8. Send Telegram notification for escalations
9. Log to notification_log for audit

Re-entry Classification (2026-05-11):
  - explicit_stop_out: confirmed decision to exit / abandon / price exceeded tolerance
  - relisted_without_stop_out: vehicle reappeared without us exiting — market behavior, not failure
  - market_reconnection_event: relisting is a market cycle event, not a strategy failure
  When explicit_stop_out = false:
    - Do not downgrade confidence in the pricing model
    - Relisted vehicles contribute to patience_score, not penalties
    - Aggressiveness reduced only on confirmed stop-outs
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env for DB credentials
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _db():
    """Get DB helpers."""
    from db_adapter import _execute, USE_DB
    return _execute, USE_DB


def _db_query(sql, params=None, fetch="all"):
    _execute, USE_DB = _db()
    if not USE_DB:
        return None
    return _execute(sql, params, fetch=fetch)


def _db_write(sql, params=None):
    _execute, USE_DB = _db()
    if not USE_DB:
        return None
    from db_adapter import _get_conn
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params)
    conn.commit()
    try:
        return dict(cur.fetchone()) if cur.description else None
    except Exception:
        return None


# ── Step 1: Detect new stop-outs ─────────────────────────────────────────

def detect_new_stopouts() -> list[dict]:
    """Find triggered positions not yet in stopped_out_watch.

    Classifies each event as:
      - true_stop_out: explicit decision to exit, price breached stop
      - relist_no_exit: symbol reappeared, we never exited
      - market_reconnection: auction/market mechanics, not our strategy
      - unclassified: needs manual review
    """
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    h = _load_json(STATE_DIR / "holdings.json") or {}

    # Build holdings price map
    price_map = {}
    for pos in h.get("holdings", []):
        s = pos.get("symbol", "")
        if s and s not in price_map:
            price_map[s] = {"price": pos.get("price", 0), "shares": pos.get("shares", 0),
                            "market_value": pos.get("market_value", 0), "name": pos.get("name", ""),
                            "account": pos.get("account", "")}

    triggered = []
    for p in rm.get("positions", []):
        if p.get("status") != "TRIGGERED":
            continue
        sym = p.get("symbol", "")
        acct = p.get("account", "")
        live = price_map.get(sym, {})
        current_price = live.get("price") or p.get("price") or 0
        stop_price = p.get("stop_price", 0)

        # Check if already in stopped_out_watch (dedup)
        existing = _db_query(
            "SELECT id, exit_type, explicit_stop_out FROM stopped_out_watch WHERE symbol = %s AND account = %s AND is_active = true",
            (sym, acct), fetch="one"
        )
        if existing:
            continue

        # ── Classify the exit event ──
        exit_classification = _classify_exit_event(sym, acct, current_price, stop_price, live, p)

        triggered.append({
            "symbol": sym,
            "account": acct or live.get("account", ""),
            "exit_price": current_price,
            "stop_price": stop_price,
            "shares": live.get("shares", 0),
            "market_value": live.get("market_value", 0),
            "name": live.get("name", ""),
            **exit_classification,
        })

    return triggered


def _classify_exit_event(sym, acct, current_price, stop_price, live_data, risk_data) -> dict:
    """Classify whether this is a true stop-out or a relist/market reconnection.

    Returns dict with: exit_type, explicit_stop_out, relisted_without_stop_out,
                       market_reconnection_event
    """
    # Check for prior closed watch records — if the symbol was watched before
    # and came back, it's likely a relist
    prior_watches = _db_query(
        """SELECT id, exit_type, stopped_out_at, analyst_verdict
           FROM stopped_out_watch
           WHERE symbol = %s AND account = %s AND is_active = false
           ORDER BY stopped_out_at DESC LIMIT 3""",
        (sym, acct)
    ) or []

    # Check if we still hold the position (relist indicator)
    still_holding = live_data.get("shares", 0) > 0

    # Check the risk_management trigger reason
    trigger_reason = risk_data.get("trigger_reason", "")
    trigger_type = risk_data.get("trigger_type", "")

    # ── Decision tree ──

    # If we still hold shares, this is NOT a true stop-out
    if still_holding and current_price > 0:
        return {
            "exit_type": "relist_no_exit",
            "explicit_stop_out": False,
            "relisted_without_stop_out": True,
            "market_reconnection_event": True,
        }

    # If the trigger was explicitly mechanical and price breached stop
    if current_price > 0 and stop_price > 0 and current_price <= stop_price:
        return {
            "exit_type": "true_stop_out",
            "explicit_stop_out": True,
            "relisted_without_stop_out": False,
            "market_reconnection_event": False,
        }

    # If price is above stop but status is TRIGGERED, likely a relist scenario
    if current_price > 0 and stop_price > 0 and current_price > stop_price:
        return {
            "exit_type": "relist_no_exit",
            "explicit_stop_out": False,
            "relisted_without_stop_out": True,
            "market_reconnection_event": True,
        }

    # If we had prior watches on this symbol, it's a recurring market event
    if prior_watches:
        return {
            "exit_type": "market_reconnection",
            "explicit_stop_out": False,
            "relisted_without_stop_out": True,
            "market_reconnection_event": True,
        }

    # Default: unclassified — needs manual review
    return {
        "exit_type": "unclassified",
        "explicit_stop_out": False,
        "relisted_without_stop_out": False,
        "market_reconnection_event": False,
    }


def create_watch_records(new_stopouts: list[dict]) -> dict:
    """Insert new stopped_out_watch records with exit classification.

    Returns `{created, attempted, failed, ok, error}`. A row whose insert fails is counted and reported: the caller
    must not treat "the function returned" as "the inserts worked" (FQ-117 R1).
    """
    created = 0
    failed = 0
    first_error = None
    for s in new_stopouts:
        exit_type = s.get("exit_type", "unclassified")
        explicit_stop = s.get("explicit_stop_out", False)
        relisted = s.get("relisted_without_stop_out", False)
        market_recon = s.get("market_reconnection_event", False)

        # Set initial verdict based on classification
        if relisted or market_recon:
            initial_verdict = "market_relist_monitor"
            initial_confidence = 0.50
            summary_suffix = "Classified as market relist — no stop-out confirmed. Patience mode active."
        else:
            initial_verdict = "wait_monitor"
            initial_confidence = 0.50
            summary_suffix = "Auto-detected from TRIGGERED status. Initial verdict: wait_monitor pending analyst review."

        try:
            _db_write(
                """INSERT INTO stopped_out_watch
                   (symbol, account, stopped_out_at, exit_price, stop_price, reason,
                    status, analyst_verdict, analyst_confidence, analyst_summary,
                    detection_source, auto_created, next_review_at, is_active,
                    explicit_stop_out, relisted_without_stop_out, market_reconnection_event,
                    exit_type, patience_score, relist_count, first_seen_at)
                   VALUES (%s, %s, %s, %s, %s, 'mechanical', 'active', %s, %s,
                           %s, 'risk_management_triggered', true, CURRENT_DATE + 1, true,
                           %s, %s, %s, %s, %s, %s, NOW())
                   ON CONFLICT (symbol, account, stopped_out_at) DO NOTHING""",
                (s["symbol"], s["account"], date.today(), s["exit_price"], s["stop_price"],
                 initial_verdict, initial_confidence,
                 f'{s["symbol"]} at ${s["exit_price"]:.2f} (stop ${s["stop_price"]:.2f}). {summary_suffix}',
                 explicit_stop, relisted, market_recon, exit_type,
                 0.0 if explicit_stop else 0.50,  # relists start with patience credit
                 1 if relisted else 0,
                 )
            )
            created += 1
            if relisted or market_recon:
                print(f"    {s['symbol']}: classified as {exit_type} (not a true stop-out)")
        except Exception as e:
            failed += 1
            first_error = first_error or f"{type(e).__name__}: {e}"
            print(f"  [recovery] Failed to create watch for {s['symbol']}: {e}")
    return {"created": created, "attempted": len(new_stopouts), "failed": failed,
            "ok": failed == 0, "error": first_error}


# ── Step 1b: Detect relist events ───────────────────────────────────────

def detect_relist_events() -> int:
    """Detect symbols that reappear in holdings/auction after being watched.

    When a watched symbol reappears without an explicit exit, log a relist event
    and update the watch record to reflect market reconnection behavior.
    """
    # Get active watch items
    items = _db_query(
        """SELECT id, symbol, account, exit_price, stop_price, exit_type,
                  explicit_stop_out, relist_count, patience_score
           FROM stopped_out_watch WHERE is_active = true AND status = 'active'""",
        fetch="all"
    ) or []
    if not items:
        return 0

    h = _load_json(STATE_DIR / "holdings.json") or {}
    held_symbols = {pos.get("symbol") for pos in h.get("holdings", []) if pos.get("symbol")}

    relist_count = 0
    for item in items:
        sym = item["symbol"]

        # If symbol is back in holdings but was marked as a stop-out, it's a relist
        if sym in held_symbols and item.get("explicit_stop_out"):
            # Reclassify: this wasn't a true stop-out after all
            _db_write(
                """UPDATE stopped_out_watch SET
                          exit_type = 'relist_no_exit',
                          explicit_stop_out = false,
                          relisted_without_stop_out = true,
                          market_reconnection_event = true,
                          relist_count = COALESCE(relist_count, 0) + 1,
                          last_relist_at = NOW(),
                          patience_score = LEAST(COALESCE(patience_score, 0) + 0.10, 1.00),
                          analyst_verdict = 'market_relist_monitor',
                          updated_at = NOW()
                   WHERE id = %s""",
                (item["id"],)
            )

            # Log the relist event
            _db_write(
                """INSERT INTO stopped_out_relist_events
                   (watch_id, symbol, account, relist_date, price_at_relist,
                    classified_as, relist_reason)
                   VALUES (%s, %s, %s, CURRENT_DATE, %s, 'market_reconnection', 'symbol_reappeared_in_holdings')
                   ON CONFLICT (watch_id, relist_date) DO NOTHING""",
                (item["id"], sym, item.get("account"),
                 item.get("exit_price"))
            )

            _db_write(
                """INSERT INTO stopped_out_watch_history
                   (watch_id, symbol, changed_by, old_verdict, new_verdict, summary)
                   VALUES (%s, %s, 'aegis', %s, 'market_relist_monitor',
                           'Reclassified: symbol reappeared in holdings without confirmed exit. Market reconnection, not strategy failure.')""",
                (item["id"], sym, item.get("exit_type", "true_stop_out"))
            )
            relist_count += 1
            print(f"    {sym}: relist detected — reclassified from stop-out to market_reconnection")

        # If not a true stop-out and symbol is still around, bump patience score
        elif sym in held_symbols and not item.get("explicit_stop_out"):
            current_patience = float(item.get("patience_score") or 0)
            new_patience = min(current_patience + 0.05, 1.00)
            _db_write(
                """UPDATE stopped_out_watch SET
                          patience_score = %s,
                          last_relist_at = NOW(),
                          updated_at = NOW()
                   WHERE id = %s""",
                (new_patience, item["id"])
            )

    return relist_count


# ── Step 2: Daily analyst review ─────────────────────────────────────────

def review_active_items() -> list[dict]:
    """Review all active watch items and update verdicts."""
    items = _db_query(
        """SELECT id, symbol, account, stopped_out_at, exit_price, stop_price,
                  analyst_verdict, analyst_confidence, analyst_summary, is_active,
                  explicit_stop_out, relisted_without_stop_out, market_reconnection_event,
                  exit_type, patience_score, relist_count
           FROM stopped_out_watch WHERE is_active = true AND status = 'active'
           ORDER BY stopped_out_at DESC""",
        fetch="all"
    ) or []

    if not items:
        return []

    # Load enrichment data
    h = _load_json(STATE_DIR / "holdings.json") or {}
    ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    news = _load_json(STATE_DIR / "portfolio_news.json") or {}

    price_map = {}
    for pos in h.get("holdings", []):
        s = pos.get("symbol", "")
        if s:
            price_map[s] = {"price": pos.get("price", 0), "market_value": pos.get("market_value", 0)}
    for s, td in ts.items():
        if isinstance(td, dict):
            if s in price_map:
                price_map[s].update({"rsi": td.get("rsi"), "sma50_pct": td.get("sma50_pct"),
                                     "sma200_pct": td.get("sma200_pct"), "beta": td.get("beta"),
                                     "perf_week": td.get("perf_week")})
            else:
                price_map[s] = {"price": td.get("price"), "rsi": td.get("rsi"),
                                "sma200_pct": td.get("sma200_pct")}

    # News context
    articles = news.get("all_scored") or news.get("catalysts") or []
    article_counts = {}
    for a in articles:
        sym = a.get("portfolio_symbol", "")
        article_counts[sym] = article_counts.get(sym, 0) + 1

    reviewed = []
    for item in items:
        sym = item["symbol"]
        exit_price = float(item.get("exit_price") or 0)
        stop_price = float(item.get("stop_price") or 0)
        live = price_map.get(sym, {})
        current_price = float(live.get("price") or 0)
        rsi = live.get("rsi")
        sma200 = live.get("sma200_pct")
        days_since = (date.today() - item["stopped_out_at"]).days if item.get("stopped_out_at") else 0
        recovery_pct = ((current_price - exit_price) / exit_price * 100) if exit_price > 0 and current_price > 0 else 0
        news_count = article_counts.get(sym, 0)

        # Fetch journal history for this symbol
        journal_ctx = _get_journal_context(sym)

        # Build exit classification context
        exit_ctx = {
            "explicit_stop_out": item.get("explicit_stop_out", False),
            "relisted_without_stop_out": item.get("relisted_without_stop_out", False),
            "market_reconnection_event": item.get("market_reconnection_event", False),
            "exit_type": item.get("exit_type", "unclassified"),
            "patience_score": float(item.get("patience_score") or 0),
            "relist_count": item.get("relist_count", 0),
        }

        # Compute verdict based on available signals + journal history + exit classification
        verdict, confidence, summary, trigger, invalidation = _compute_verdict(
            sym, exit_price, stop_price, current_price, rsi, sma200,
            days_since, recovery_pct, news_count, journal_ctx, exit_ctx
        )

        old_verdict = item.get("analyst_verdict")
        evidence = {
            "current_price": current_price, "exit_price": exit_price,
            "recovery_pct": round(recovery_pct, 1), "rsi": rsi,
            "journal_history": journal_ctx,
            "exit_classification": exit_ctx,
            "sma200_pct": sma200, "days_since_stop": days_since,
            "news_count_7d": news_count, "reviewed_at": datetime.now().isoformat(),
        }

        _db_write(
            """UPDATE stopped_out_watch SET
                      analyst_verdict = %s, analyst_confidence = %s,
                      analyst_summary = %s, reentry_trigger = %s, invalidated_if = %s,
                      evidence_payload = %s, last_reviewed_at = NOW(),
                      next_review_at = CURRENT_DATE + 1, updated_at = NOW()
               WHERE id = %s""",
            (verdict, confidence, summary, trigger, invalidation,
             json.dumps(evidence), item["id"])
        )

        # Log history if verdict changed
        if old_verdict != verdict:
            _db_write(
                """INSERT INTO stopped_out_watch_history
                   (watch_id, symbol, changed_by, old_verdict, new_verdict, summary, evidence)
                   VALUES (%s, %s, 'aegis', %s, %s, %s, %s)""",
                (item["id"], sym, old_verdict, verdict, summary, json.dumps(evidence))
            )

        reviewed.append({"id": item["id"], "symbol": sym, "verdict": verdict,
                        "confidence": confidence, "old_verdict": old_verdict})

    return reviewed


def _get_journal_context(sym: str) -> dict:
    """Pull journal review history for a symbol to inform recovery decisions."""
    rows = _db_query(
        """SELECT setup_name, timeframe, well_executed, followed_plan,
                  execution_quality_score, emotion_before, mistake_tags
           FROM journal_trade_reviews WHERE symbol = %s ORDER BY closed_date DESC LIMIT 5""",
        (sym,)
    ) or []
    if not rows:
        return {"has_history": False}
    total = len(rows)
    well_exec = sum(1 for r in rows if r.get("well_executed"))
    plan_follow = sum(1 for r in rows if r.get("followed_plan"))
    avg_exec = sum(r.get("execution_quality_score") or 0 for r in rows if r.get("execution_quality_score")) / max(1, sum(1 for r in rows if r.get("execution_quality_score")))
    setups = list(set(r.get("setup_name") for r in rows if r.get("setup_name")))
    mistakes = []
    for r in rows:
        for t in (r.get("mistake_tags") or []):
            if t not in mistakes:
                mistakes.append(t)
    return {
        "has_history": True,
        "review_count": total,
        "well_executed_rate": well_exec / total if total else 0,
        "plan_follow_rate": plan_follow / total if total else 0,
        "avg_execution": round(avg_exec, 1),
        "setups_used": setups,
        "common_mistakes": mistakes[:3],
        "last_emotion": rows[0].get("emotion_before") if rows else None,
    }


def _compute_verdict(sym, exit_price, stop_price, current_price, rsi, sma200,
                     days_since, recovery_pct, news_count, journal_ctx=None,
                     exit_ctx=None):
    """Rule-based verdict computation using available signals + exit classification.

    Key principle: when explicit_stop_out = false (relist / market reconnection),
    do NOT downgrade confidence or treat as a failed position. Relisted vehicles
    contribute to patience scoring, not penalties.
    """
    ec = exit_ctx or {}
    is_true_stopout = ec.get("explicit_stop_out", True)  # default conservative
    is_relist = ec.get("relisted_without_stop_out", False)
    is_market_recon = ec.get("market_reconnection_event", False)
    patience = ec.get("patience_score", 0)
    relist_count = ec.get("relist_count", 0)

    # Default
    verdict = "wait_monitor"
    confidence = 0.50
    reasons = []

    # ── Relist / market reconnection path (NOT a failure) ──
    if is_relist or is_market_recon:
        verdict = "market_relist_monitor"
        confidence = 0.55
        reasons.append(f"Relisted — No Stop-Out. Market reconnection event (relist #{relist_count}).")
        reasons.append("Price discovery continuing; not a strategy failure.")

        if current_price > 0 and stop_price > 0:
            if current_price > stop_price:
                reasons.append(f"Price ${current_price:.2f} above original stop ${stop_price:.2f} — position intact.")
                verdict = "reentry_candidate"
                confidence = 0.70 + min(patience * 0.10, 0.15)  # patience bonus
            elif current_price > exit_price:
                reasons.append(f"Price ${current_price:.2f} recovering above exit ${exit_price:.2f}.")
                confidence = 0.60

        # RSI in relist context — constructive only, no penalties
        if rsi is not None:
            if rsi > 50:
                reasons.append(f"RSI {rsi:.0f} — momentum supportive in relist context.")
                confidence = min(confidence + 0.05, 0.85)
            elif rsi < 30:
                reasons.append(f"RSI {rsi:.0f} — oversold during relist cycle, potential opportunity.")

        if sma200 is not None and sma200 > 0:
            reasons.append(f"Above SMA200 (+{sma200:.1f}%) — trend intact despite relist.")

        # Patience bonus: relists without stop-out build patience score
        if patience > 0:
            reasons.append(f"Patience score: {patience:.2f} — sustained engagement without exit.")

        # Time decay is softer for relists — they're market events
        if days_since > 45 and verdict == "market_relist_monitor":
            reasons.append(f"{days_since} days since initial flag — extended monitoring, but no penalty for market behavior.")
        # Only close relist watches after much longer (90+ days)
        if days_since > 90 and verdict == "market_relist_monitor":
            reasons.append(f"{days_since} days — consider consolidating this relist watch.")
            verdict = "wait_monitor"

    else:
        # ── True stop-out path (original logic, penalties apply) ──
        # Price recovery signals
        if current_price > 0 and stop_price > 0:
            if current_price > stop_price:
                reasons.append(f"Price ${current_price:.2f} has recovered above stop ${stop_price:.2f}")
                verdict = "reentry_candidate"
                confidence = 0.70
            elif recovery_pct > 5:
                reasons.append(f"Price recovering: +{recovery_pct:.1f}% from exit")
                confidence = 0.55
            elif recovery_pct < -10:
                reasons.append(f"Continued decline: {recovery_pct:.1f}% from exit. Thesis may be damaged.")
                verdict = "do_not_reenter"
                confidence = 0.65

        # RSI signals
        if rsi is not None:
            if rsi < 30:
                reasons.append(f"RSI {rsi:.0f} — oversold, possible reversal setup")
                if verdict == "wait_monitor":
                    confidence = max(confidence, 0.55)
            elif rsi > 60 and current_price > stop_price:
                reasons.append(f"RSI {rsi:.0f} — momentum recovering")
                if verdict == "reentry_candidate":
                    confidence = min(confidence + 0.10, 0.85)
            elif rsi > 70:
                reasons.append(f"RSI {rsi:.0f} — overbought after recovery, wait for pullback")

        # SMA200 signals
        if sma200 is not None:
            if sma200 > 0:
                reasons.append(f"Above SMA200 (+{sma200:.1f}%) — constructive")
            else:
                reasons.append(f"Below SMA200 ({sma200:.1f}%) — weak trend")

        # Time decay — only for true stop-outs
        if days_since > 30 and verdict == "wait_monitor":
            reasons.append(f"{days_since} days since stop — consider closing watch if no recovery")
            confidence = max(confidence, 0.55)
        if days_since > 60 and verdict != "reentry_candidate":
            reasons.append(f"{days_since} days with no recovery signal — thesis likely broken")
            verdict = "do_not_reenter"
            confidence = 0.70

    # News activity (applies to both paths)
    if news_count > 5:
        reasons.append(f"{news_count} articles in recent coverage — active news flow")

    # Journal history context (applies to both paths)
    jc = journal_ctx or {}
    if jc.get("has_history"):
        rc = jc["review_count"]
        we_rate = jc.get("well_executed_rate", 0)
        setups = jc.get("setups_used", [])
        mistakes = jc.get("common_mistakes", [])
        if we_rate >= 0.7:
            reasons.append(f"Journal history ({rc} reviews): {we_rate*100:.0f}% well-executed — good execution track record on {sym}.")
            if verdict == "reentry_candidate":
                confidence = min(confidence + 0.05, 0.85)
        elif we_rate < 0.5 and rc >= 2 and is_true_stopout:
            # Only penalize execution history on true stop-outs
            reasons.append(f"Journal history ({rc} reviews): only {we_rate*100:.0f}% well-executed — caution, past execution on {sym} was weak.")
            confidence = max(confidence - 0.05, 0.40)
        if mistakes and is_true_stopout:
            reasons.append(f"Past mistakes on {sym}: {', '.join(mistakes[:2])}.")
        if setups:
            reasons.append(f"Previously traded as: {', '.join(setups[:2])}.")

    # Build summary
    if not reasons:
        if is_relist:
            reasons.append(f"Monitoring {sym} — relisted without stop-out. Price discovery continuing.")
        else:
            reasons.append(f"Monitoring {sym} post stop-out. No strong signals yet.")

    summary = " ".join(reasons)

    # Build trigger/invalidation — specific and actionable
    if verdict == "reentry_candidate":
        trigger = f"Re-enter when: {sym} closes above ${stop_price:.2f} on above-average volume with RSI > 50. Confirm with 2-day hold above stop level."
        invalidation = f"Do NOT re-enter if: price drops below ${exit_price:.2f}, or sector/thesis fundamentally changes, or portfolio heat exceeds 7%."
    elif verdict == "do_not_reenter":
        trigger = f"Reconsider only if: major positive catalyst (earnings beat, M&A, sector rotation), AND price recovers above ${stop_price:.2f}. Otherwise this name is closed."
        invalidation = f"Current assessment: avoid {sym}. Thesis appears damaged. Capital better deployed elsewhere."
    elif verdict == "market_relist_monitor":
        trigger = f"Continue monitoring: {sym} is a market relist, not a failed position. Watch for price stability above ${stop_price:.2f} and volume normalization."
        invalidation = f"Reclassify as true stop-out if: explicit exit decision is made, or price drops below ${exit_price * 0.85:.2f} (15% below exit), or confirmed thesis break."
    else:
        rsi_note = f" RSI is {rsi:.0f}" if rsi is not None else ""
        trigger = f"Watch for: {sym} to recover above ${stop_price:.2f} with volume confirmation.{rsi_note}. Check daily until verdict changes."
        invalidation = f"Close watch if: price falls below ${exit_price * 0.9:.2f} (10% below exit), or {days_since + 30}+ days pass with no recovery signal."

    return verdict, round(confidence, 2), summary, trigger, invalidation


# ── Step 3: Escalation + notification ────────────────────────────────────

def _route_escalation(item: dict) -> str:
    """Route escalation: Maria for simple re-entry, Steph for complex/thesis cases.

    Steph gets:
    - Items where thesis may be damaged (keyword signals in summary)
    - Items with high market value (>$5K freed capital)
    - Items where the stop was discretionary or news-driven
    - Items with multiple prior verdict changes (complex history)

    Maria gets:
    - Straightforward mechanical stop-outs with clear technical re-entry
    - Lower-complexity re-entry candidates
    """
    summary = (item.get("summary") or "").lower()
    confidence = item.get("confidence", 0)

    # Steph indicators: thesis damage, complexity, discretionary
    steph_signals = ["thesis", "broken", "damaged", "discretionary", "news-driven",
                     "fundamental", "regime", "sector rotation", "complex"]
    steph_score = sum(1 for s in steph_signals if s in summary)

    if steph_score >= 2:
        return "steph"
    if confidence >= 0.80:
        return "steph"  # Very high confidence = needs senior review

    return "maria"


def check_and_escalate(reviewed: list[dict]) -> list[dict]:
    """Escalate high-confidence reentry candidates to Maria/Steph."""
    escalated = []

    for r in reviewed:
        if r["verdict"] != "reentry_candidate" or r["confidence"] < 0.65:
            continue

        # Check if already escalated recently
        item = _db_query(
            "SELECT id, symbol, escalated_to, escalated_at FROM stopped_out_watch WHERE id = %s",
            (r["id"],), fetch="one"
        )
        if not item:
            continue

        # Don't re-escalate if already escalated in last 3 days
        if item.get("escalated_at"):
            esc_at = item["escalated_at"]
            if hasattr(esc_at, 'date') and (date.today() - esc_at.date()).days < 3:
                continue

        # Route: Maria for straightforward re-entry, Steph for complex/thesis-damage cases
        escalate_to = _route_escalation(r)
        # Include exit classification in escalation reason
        exit_note = ""
        full_item_check = _db_query(
            "SELECT exit_type, explicit_stop_out, relisted_without_stop_out FROM stopped_out_watch WHERE id = %s",
            (r["id"],), fetch="one"
        ) or {}
        if full_item_check.get("relisted_without_stop_out"):
            exit_note = " [Relisted — No Stop-Out]"
        elif full_item_check.get("explicit_stop_out"):
            exit_note = " after stop-out"
        else:
            exit_note = " after stop-out"
        reason = f"{r['symbol']} is a re-entry candidate ({r['confidence']*100:.0f}% confidence){exit_note}. Routed to {escalate_to} for review."

        _db_write(
            """UPDATE stopped_out_watch SET escalated_to = %s, escalated_at = NOW(),
                      escalation_reason = %s, updated_at = NOW()
               WHERE id = %s""",
            (escalate_to, reason, r["id"])
        )

        _db_write(
            """INSERT INTO stopped_out_watch_history
               (watch_id, symbol, changed_by, old_verdict, new_verdict, summary)
               VALUES (%s, %s, 'aegis', %s, %s, %s)""",
            (r["id"], r["symbol"], r.get("old_verdict"), r["verdict"],
             f"Auto-escalated to {escalate_to}: {reason}")
        )

        # Get full item details for richer notification
        full_item = _db_query(
            "SELECT analyst_summary, reentry_trigger, invalidated_if, temp_allocation_verdict FROM stopped_out_watch WHERE id = %s",
            (r["id"],), fetch="one"
        ) or {}
        escalated.append({"symbol": r["symbol"], "verdict": r["verdict"],
                         "confidence": r["confidence"], "escalated_to": escalate_to,
                         "reason": reason,
                         "summary": full_item.get("analyst_summary", ""),
                         "trigger": full_item.get("reentry_trigger", ""),
                         "invalidation": full_item.get("invalidated_if", ""),
                         "allocation": full_item.get("temp_allocation_verdict", "")})

    return escalated


def send_notifications(escalated: list[dict]) -> dict:
    """Send Telegram + log notification for each escalation. Reports delivery failures (FQ-117 R1)."""
    sent = 0
    failed = 0
    first_error = None
    if not escalated:
        return {"sent": 0, "failed": 0, "ok": True, "error": None}

    from db_adapter import save_notification_log_entry

    for e in escalated:
        # Notification log entry
        # Richer notification body
        body_parts = [
            f"{e['symbol']} recovery watch escalated to {e['escalated_to'].title()}.",
            f"Verdict: {e['verdict'].replace('_',' ').title()} ({e['confidence']*100:.0f}% confidence).",
        ]
        if e.get("summary"):
            body_parts.append(f"Analyst: {e['summary'][:120]}")
        if e.get("trigger"):
            body_parts.append(f"Trigger: {e['trigger'][:100]}")
        body_parts.append("Next step: review at /v3/risk")
        body_text = " ".join(body_parts)

        try:
            save_notification_log_entry({
                "notification_date": date.today(),
                "notification_type": "recovery_escalation",
                "channel": "dashboard",
                "subject": f"[Recovery Watch] {e['verdict'].replace('_',' ').title()} — {e['symbol']} → {e['escalated_to'].title()}",
                "body_summary": body_text,
                "recommendation_ids": None,
                "escalation_ids": None,
                "observation_ids": None,
                "payload": json.dumps(e),
                "status": "sent",
                "dedupe_key": f"recovery_esc_{e['symbol']}_{date.today()}",
                "sent_at": datetime.now(),
                "error": None,
            })
        except Exception as ex:
            print(f"  [recovery] notification_log failed: {ex}")

        # Telegram — richer notification
        try:
            from telegram_alert import send_telegram
            lines = [
                "*Recovery Watch Escalation*",
                f"Symbol: *{e['symbol']}*",
                f"Verdict: {e['verdict'].replace('_', ' ').title()} ({e['confidence']*100:.0f}%)",
                f"Escalated to: *{e['escalated_to'].title()}*",
                f"Reason: {e.get('reason', 'N/A')}",
            ]
            if e.get("summary"):
                lines.append(f"Summary: {e['summary'][:150]}")
            if e.get("trigger"):
                lines.append(f"Re-entry trigger: {e['trigger'][:100]}")
            if e.get("invalidation"):
                lines.append(f"Invalidated if: {e['invalidation'][:100]}")
            if e.get("allocation"):
                lines.append(f"Capital: {e['allocation'].replace('_', ' ')}")
            lines.append("Review at: /v3/risk")
            send_telegram("\n".join(lines), priority="P2", producer="recovery_watch_daily")
            sent += 1
        except Exception as ex:
            failed += 1
            first_error = first_error or f"{type(ex).__name__}: {ex}"
            print(f"  [recovery] Telegram send failed: {ex}")
    return {"sent": sent, "failed": failed, "ok": failed == 0, "error": first_error}


# ── Step 4: Stop placement confirmation scan ────────────────────────────

def scan_unconfirmed_stops() -> list[dict]:
    """Find positions without confirmed stops, upsert into stop_confirmations, send reminders."""
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    h = _load_json(STATE_DIR / "holdings.json") or {}
    price_map = {}
    for pos in h.get("holdings", []):
        s = pos.get("symbol", "")
        if s:
            price_map[s] = {"market_value": pos.get("market_value", 0), "portfolio_pct": pos.get("portfolio_pct", 0)}

    reminders = []
    for p in rm.get("positions", []):
        if p.get("status") != "NO STOP":
            continue
        sym = p.get("symbol", "")
        acct = p.get("account", "")
        live = price_map.get(sym, {})
        mv = live.get("market_value") or p.get("market_value", 0)
        pct = live.get("portfolio_pct", 0)

        # Skip tiny positions and 401k funds (can't set stops on mutual funds)
        if mv < 500 or acct == "fidelity_401k":
            continue

        # Upsert into stop_confirmations
        existing = _db_query(
            "SELECT id, stop_status, last_reminder_at, reminder_count FROM stop_confirmations WHERE symbol = %s AND account = %s",
            (sym, acct), fetch="one"
        )
        if existing:
            # Already tracked — check if reminder needed (>24h since last)
            last = existing.get("last_reminder_at")
            if last and hasattr(last, 'date') and (date.today() - last.date()).days < 1:
                continue
            if existing.get("stop_status") in ("confirmed", "intentional_no_stop"):
                continue
            _db_write(
                "UPDATE stop_confirmations SET last_reminder_at = NOW(), reminder_count = reminder_count + 1, market_value = %s, position_pct = %s, updated_at = NOW() WHERE id = %s",
                (mv, pct, existing["id"])
            )
            reminders.append({"symbol": sym, "account": acct, "market_value": mv, "pct": pct, "reminder_num": (existing.get("reminder_count") or 0) + 1})
        else:
            _db_write(
                """INSERT INTO stop_confirmations (symbol, account, stop_status, market_value, position_pct, last_reminder_at, reminder_count)
                   VALUES (%s, %s, 'unconfirmed', %s, %s, NOW(), 1)
                   ON CONFLICT (symbol, account) DO NOTHING""",
                (sym, acct, mv, pct)
            )
            reminders.append({"symbol": sym, "account": acct, "market_value": mv, "pct": pct, "reminder_num": 1})

    return reminders


def send_stop_reminders(reminders: list[dict]) -> dict:
    """Send Telegram reminder for unconfirmed stops. Reports delivery failures (FQ-117 R1).

    The report is built from what actually left the host, not from what was attempted: a Telegram
    send that raises counts as failed and makes `ok` False, and the audit row it leaves behind says
    so too. Otherwise the run receipt would certify that the operator was paged when nothing went
    out — the exact class of defect this lane exists to make impossible (review F1 on #2674).
    """
    if not reminders:
        return {"sent": 0, "failed": 0, "ok": True, "error": None}
    try:
        from telegram_alert import send_telegram
        from db_adapter import save_notification_log_entry
    except ImportError as exc:
        return {"sent": 0, "failed": len(reminders), "ok": False,
                "error": f"notification transport unavailable: {type(exc).__name__}: {exc}"}

    total_unprotected = sum(r['market_value'] for r in reminders)
    lines = [f"*Stop Placement Reminder*\n{len(reminders)} position(s) without confirmed stops (${total_unprotected:,.0f} total exposure):\n"]
    for r in reminders[:8]:
        lines.append(f"• *{r['symbol']}* — ${r['market_value']:,.0f} ({r['pct']:.1f}%) — reminder #{r['reminder_num']}")
    lines.append("\nReply: yes SYMBOL / no / intentional SYMBOL")
    lines.append("Or review at /v3/risk")
    msg = "\n".join(lines)

    sent = 0
    failed = 0
    first_error = None
    try:
        send_telegram(msg, priority="P1", dedupe_minutes=0, producer="recovery_watch_daily")
        sent = len(reminders)
    except Exception as ex:
        failed = len(reminders)
        first_error = f"{type(ex).__name__}: {ex}"[:300]
        print(f"  [recovery] Stop reminder Telegram failed: {ex}")

    try:
        save_notification_log_entry({
            "notification_date": date.today(),
            "notification_type": "stop_confirmation_reminder",
            "channel": "telegram",
            "subject": f"[Stop Reminder] {len(reminders)} position{'s' if len(reminders) != 1 else ''} need stop confirmation — ${total_unprotected:,.0f} exposure",
            "body_summary": msg[:500],
            "recommendation_ids": None, "escalation_ids": None, "observation_ids": None,
            "payload": json.dumps(reminders[:10], default=str),
            "status": "sent" if sent else "failed", "dedupe_key": f"stop_remind_{date.today()}",
            "sent_at": datetime.now(), "error": None if sent else first_error,
        })
    except Exception as ex:
        # The page went out (or did not) — either way the audit row is now a second failure, and a
        # delivered page with no audit row is still not a clean run.
        failed = failed or 1
        first_error = first_error or f"{type(ex).__name__}: {ex}"[:300]
        print(f"  [recovery] Stop reminder notification_log failed: {ex}")
    return {"sent": sent, "failed": failed, "ok": failed == 0, "error": first_error}


# ── Step 5: Post-stop temporary allocation advisor ───────────────────────

def compute_temp_allocations():
    """For each active stopped-out watch item, recommend where freed capital should sit."""
    items = _db_query(
        """SELECT id, symbol, exit_price, stop_price, analyst_verdict, analyst_confidence,
                  temp_allocation_verdict
           FROM stopped_out_watch WHERE is_active = true AND status = 'active'""",
        fetch="all"
    ) or []
    if not items:
        return 0

    # Get market context
    fresh = _load_json(STATE_DIR / "_freshness.json") or {}
    h = _load_json(STATE_DIR / "holdings.json") or {}
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    wl = _load_json(STATE_DIR / "watchlist.json") or {}

    total_value = sum(p.get("market_value", 0) for p in h.get("holdings", []))
    cash = sum(p.get("market_value", 0) for p in h.get("holdings", []) if p.get("is_cash"))
    cash_pct = (cash / total_value * 100) if total_value > 0 else 0
    heat_pct = rm.get("portfolio_heat_pct", 0)
    watchlist_count = len(wl)
    unprotected_count = len([p for p in rm.get("positions", []) if p.get("status") == "NO STOP"])

    updated = 0
    for item in items:
        sym = item["symbol"]
        exit_price = float(item.get("exit_price") or 0)
        freed_capital = exit_price * 1  # approximate, shares may vary
        verdict = item.get("analyst_verdict", "wait_monitor")

        # Compute allocation recommendation
        alloc_verdict, alloc_conf, alloc_reason, alloc_target, alloc_until, alloc_trigger = _compute_allocation(
            sym, verdict, float(item.get("analyst_confidence") or 0.5),
            cash_pct, heat_pct, watchlist_count, unprotected_count
        )

        _db_write(
            """UPDATE stopped_out_watch SET
                      temp_allocation_verdict = %s, temp_allocation_confidence = %s,
                      temp_allocation_reason = %s, temp_allocation_target = %s,
                      temp_allocation_until = %s, temp_allocation_exit_trigger = %s,
                      updated_at = NOW()
               WHERE id = %s""",
            (alloc_verdict, alloc_conf, alloc_reason, alloc_target, alloc_until, alloc_trigger, item["id"])
        )
        updated += 1

    return updated


def _compute_allocation(sym, analyst_verdict, analyst_conf, cash_pct, heat_pct, wl_count, unprotected):
    """Rule-based temporary allocation recommendation with deep rationale."""

    # Load regime context
    fresh = _load_json(STATE_DIR / "_freshness.json") or {}
    overview_data = _load_json(STATE_DIR / "holdings.json") or {}
    total_positions = len([p for p in overview_data.get("holdings", []) if not p.get("is_cash") and (p.get("market_value") or 0) > 50])

    # Determine market regime
    regime = "neutral"
    try:
        tai_runs = sorted((STATE_DIR / "data" / "runs").glob("*/state.json"), reverse=True)[:1] if (STATE_DIR / "data" / "runs").exists() else []
    except Exception:
        tai_runs = []

    verdict = "stay_cash"
    confidence = 0.60
    reasons = []
    target = "Cash"
    until = "Until re-entry signal or next rebalance review"
    trigger = "Re-entry candidate confirmed or new high-conviction opportunity"

    # ── Re-entry candidate path ──
    if analyst_verdict == "reentry_candidate" and analyst_conf >= 0.65:
        verdict = "hold_for_reentry"
        confidence = 0.70
        target = f"Cash earmarked for {sym} re-entry"
        reasons.append(f"{sym} is a re-entry candidate ({analyst_conf*100:.0f}% confidence). Technical repair signals detected.")
        reasons.append("Hold freed capital ready — deploying elsewhere would forfeit the re-entry opportunity.")
        if heat_pct > 5:
            reasons.append(f"Portfolio heat is elevated ({heat_pct:.1f}%), but re-entry conviction overrides the cash preference.")
        until = "Until re-entry trigger price confirms with volume, or analyst verdict downgrades to wait_monitor"
        trigger = f"{sym} re-entry trigger price confirmed with above-average volume and RSI crossing 50"
        confidence = min(0.80, analyst_conf + 0.05)

    # ── Do not re-enter path ──
    elif analyst_verdict == "do_not_reenter":
        if cash_pct > 5 and heat_pct < 4:
            verdict = "treasury_ballast"
            confidence = 0.65
            target = "BND, SGOV, or short-term treasury ETF"
            reasons.append(f"{sym} thesis is broken — permanent exit.")
            reasons.append(f"Cash is already {cash_pct:.1f}% of portfolio. Excess cash earns nothing — deploy to treasury/bond for yield.")
            reasons.append("Short-duration treasuries maintain liquidity and hedge equity volatility.")
            until = "Until next rebalance review or new high-conviction opportunity emerges from watchlist/Trade AI"
            trigger = "Rebalance pipeline identifies a better allocation target, or watchlist candidate hits GO signal"
        elif wl_count > 3 and heat_pct < 5:
            verdict = "rotate_existing_conviction"
            confidence = 0.55
            target = "Top watchlist candidate or existing underweight conviction position"
            reasons.append(f"{sym} exited permanently. {wl_count} watchlist candidates available for rotation.")
            reasons.append("Rotation preferred over idle cash when risk posture is manageable.")
            reasons.append("Select from highest-confidence watchlist names or existing positions below target weight.")
            until = "Until capital is deployed to selected rotation target"
            trigger = "Watchlist candidate reaches GO or analyst marks re-entry candidate with confidence >= 70%"
        elif heat_pct > 5:
            verdict = "stay_cash"
            confidence = 0.70
            target = "Cash"
            reasons.append(f"{sym} thesis is broken. Portfolio heat at {heat_pct:.1f}% — risk is elevated.")
            reasons.append("Stay in cash to reduce overall portfolio risk before deploying elsewhere.")
            reasons.append("Do not rotate into new names while heat is above 5% threshold.")
        else:
            verdict = "stay_cash"
            confidence = 0.60
            target = "Cash"
            reasons.append(f"{sym} thesis broken. No high-conviction alternatives available right now.")
            reasons.append("Cash is the correct default when no better opportunity is clear.")

    # ── Wait/monitor path ──
    elif analyst_verdict == "wait_monitor":
        if heat_pct > 5:
            verdict = "stay_cash"
            confidence = 0.65
            target = "Cash"
            reasons.append(f"Portfolio heat at {heat_pct:.1f}%. {sym} verdict is wait/monitor — no conviction for re-entry yet.")
            reasons.append("Elevated heat means the priority is risk reduction, not deployment.")
            reasons.append(f"{unprotected} position(s) without stops — capital should stay defensive.")
        elif unprotected > 5:
            verdict = "stay_cash"
            confidence = 0.60
            target = "Cash"
            reasons.append(f"{unprotected} positions without confirmed stops. Overall risk posture is weak.")
            reasons.append(f"{sym} in wait/monitor — no urgency to deploy. Stay defensive.")
        elif cash_pct < 2:
            verdict = "stay_cash"
            confidence = 0.55
            target = "Cash"
            reasons.append(f"Cash is only {cash_pct:.1f}% of portfolio — below comfortable buffer level.")
            reasons.append(f"Retaining {sym} freed capital as cash reserve improves liquidity posture.")
        else:
            verdict = "cash_equivalent"
            confidence = 0.55
            target = "Money market fund or ultra-short bond (SGOV, BIL)"
            reasons.append(f"{sym} monitoring continues — no strong recovery or breakdown signal.")
            reasons.append("Park in cash-equivalent for modest yield (~5% annualized) while maintaining instant liquidity.")
            reasons.append("This is a temporary holding — will reallocate when verdict changes.")
            until = "Until {sym} verdict changes to reentry_candidate or do_not_reenter"
            trigger = f"{sym} shows technical repair above stop level, or further breakdown below exit price"

    if not reasons:
        reasons.append(f"Default: keep freed capital from {sym} in cash pending further analyst review.")

    reason = " ".join(reasons)
    return verdict, round(confidence, 2), reason, target, until, trigger


# ── Main entry point ─────────────────────────────────────────────────────

def _recovery_state_pass():
    """Piece B: evaluate every open recovery case at 07:30 too, through the SAME entry point the 20-minute
    lane uses. The store belongs to piece A; an absent store is reported, never rendered as zero cases."""
    try:
        from lib import recovery_state as R
    except ImportError:
        try:
            from scripts.lib import recovery_state as R
        except ImportError:
            print("  Recovery state machine: module absent (piece B not on this build)")
            return {"store": "module_absent", "considered": 0, "changed": 0}
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
    except Exception:
        conn = None
    store = R.store_accessor(conn, None)
    if store is None:
        print("  Recovery state machine: store absent (piece A not on this build) — nothing evaluated")
        return {"store": "absent", "considered": 0, "changed": 0}

    def snapshot_for(case):
        row = _db_query("SELECT * FROM market_quotes WHERE upper(symbol)=%s ORDER BY fetched_at DESC LIMIT 1",
                        (str(case.get("symbol") or "").upper(),), fetch="one")
        if not row:
            return None
        def _f(key):
            try:
                value = row.get(key)
                return float(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                return None
        close = _f("price") if _f("price") is not None else _f("close")
        if close is None:
            return None
        snap = {"close": close, "fetched_at": row.get("fetched_at")}
        for field, keys in (("rsi", ("rsi", "rsi_14")), ("rsi_prev", ("rsi_prev",)),
                            ("sma20", ("sma20", "sma_20")), ("macd_up_sessions", ("macd_up_sessions",)),
                            ("stop_level", ("stop_level",)), ("entry_high", ("entry_high",))):
            for key in keys:
                value = _f(key)
                if value is not None:
                    snap[field] = value
                    break
        return snap

    out = R.run_pass(store, snapshot_for, dry_run=False)
    print(f"  Recovery state machine: {out.get('considered', 0)} cases, {out.get('changed', 0)} state changes")
    return out


RECEIPT_SCHEMA = "RecoveryWatchRunReceipt@v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def receipt_dir() -> Path:
    """Where run receipts live. RECOVERY_WATCH_RECEIPT_DIR exists for tests and for a caller that wants them
    somewhere else; it never changes what the run does."""
    override = os.environ.get("RECOVERY_WATCH_RECEIPT_DIR")
    return Path(override) if override else PROJECT_ROOT / "data" / "runtime" / "recovery_watch_receipts"


def source_identity(script: Path | None = None) -> dict:
    """The concrete code this invocation is running, recorded without asking CURRENT what it was.

    CURRENT is a pointer *now*; it cannot prove what an earlier run executed. The script's own digest always
    works, a release directory name (`<40-hex>-<label>`) binds it to a served tree when it runs from one, and
    git HEAD is recorded when a checkout is available. Anything unavailable stays None — never guessed.
    """
    path = Path(script or __file__).resolve()
    out: dict = {"script": str(path), "script_sha256": None, "release_sha": None, "git_head": None}
    try:
        out["script_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        pass
    for parent in path.parents:
        match = re.fullmatch(r"([0-9a-f]{40})-.+", parent.name or "")
        if match:
            out["release_sha"] = match.group(1)
            break
    try:
        # Read-only, fixed argv, no shell: the only thing this can run is `git rev-parse HEAD`.
        # ruff anchors S607 at the executable argument, so the suppression sits on that line, not the call.
        head = subprocess.run(  # noqa: S603
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True, text=True, timeout=5,
        )
        if head.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}\s*", head.stdout or ""):
            out["git_head"] = head.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def write_run_receipt(payload: dict, directory: Path | None = None) -> Path:
    """Write one receipt atomically and return its path. Never partial: a crash leaves no half-written file."""
    directory = Path(directory) if directory else receipt_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{payload['started_at'].replace(':', '').replace('-', '')}-{payload['invocation_id']}.json"
    temporary = target.with_suffix(".json.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    # Fsync the DIRECTORY too: fsyncing the file proves the bytes, not that the name was published.
    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError as exc:
        # Never silent: the receipt must not claim a durability it did not get (review F3 on #2674).
        print(f"  [recovery] receipt directory fsync skipped (cannot open {directory}): {exc}", file=sys.stderr)
        return target
    try:
        os.fsync(dir_fd)
    except OSError as exc:
        print(f"  [recovery] receipt directory fsync failed: {exc}", file=sys.stderr)
    finally:
        os.close(dir_fd)
    return target


def _summarise(result) -> object:
    if isinstance(result, (int, float, str, bool)) or result is None:
        return result if not isinstance(result, str) else result[:200]
    if isinstance(result, (list, tuple)):
        return {"count": len(result)}
    if isinstance(result, dict):
        return {k: result[k] for k in list(result)[:8]}
    return str(result)[:200]


class StepFailed(RuntimeError):
    """A step returned normally but reported that its own work failed.

    cx-openai-2's R1 on #2674: `create_watch_records` catches a failed insert and returns a count, so treating
    "the function returned" as success certified a failed mutation as ok. A step now says what happened; a normal
    return that reports failure is a failure.
    """


def _step_failure(result) -> str | None:
    """What a step's own return value says about failure. `None` means "it really worked"."""
    if isinstance(result, dict):
        if result.get("ok") is False:
            return str(result.get("error") or "step reported failure")[:300]
        failed = result.get("failed")
        if isinstance(failed, int) and failed > 0:
            return f"{failed} operation(s) failed" + (f": {result.get('error')}" if result.get("error") else "")
    return None


def _run_step(steps: list, name: str, fn, *args, **kwargs):
    """Run one step and record what actually happened, then propagate any failure.

    Two failure shapes, both recorded and both fatal: an exception, and a normal return whose own report says the
    work failed. Exit 0 is not evidence of work (AGENTS rule 8).
    """
    started = _utc_now()
    try:
        result = fn(*args, **kwargs)
    except BaseException as exc:  # recorded before it propagates
        steps.append({"name": name, "outcome": "failed", "started_at": _iso(started),
                      "finished_at": _iso(_utc_now()), "error": f"{type(exc).__name__}: {exc}"[:500]})
        raise
    failure = _step_failure(result)
    if failure:
        steps.append({"name": name, "outcome": "failed", "started_at": _iso(started),
                      "finished_at": _iso(_utc_now()), "error": failure, "output": _summarise(result)})
        raise StepFailed(f"{name}: {failure}")
    steps.append({"name": name, "outcome": "ok", "started_at": _iso(started),
                  "finished_at": _iso(_utc_now()), "output": _summarise(result)})
    return result


def _run(started: datetime, invocation_id: str, steps: list):
    print(f"[recovery_watch_daily] Starting — {_iso(started)} (invocation {invocation_id})")

    # Step 1: Detect new stop-outs (with exit classification)
    new_stopouts = _run_step(steps, "detect_new_stopouts", detect_new_stopouts)
    created = _run_step(steps, "create_watch_records", create_watch_records, new_stopouts)
    true_stops = sum(1 for s in new_stopouts if s.get("explicit_stop_out"))
    relists = sum(1 for s in new_stopouts if s.get("relisted_without_stop_out"))
    print(f"  New events detected: {len(new_stopouts)} (true stop-outs: {true_stops}, relists: {relists}), "
          f"records created: {created['created'] if isinstance(created, dict) else created}")

    # Step 1b: Detect relist events for existing watch items
    relist_events = _run_step(steps, "detect_relist_events", detect_relist_events)
    if relist_events:
        print(f"  Relist events detected and reclassified: {relist_events}")

    # Step 2: Review all active items (with exit classification context)
    reviewed = _run_step(steps, "review_active_items", review_active_items)
    print(f"  Active items reviewed: {len(reviewed)}")
    for r in reviewed:
        change = f" (was {r['old_verdict']})" if r['old_verdict'] != r['verdict'] else ""
        print(f"    {r['symbol']}: {r['verdict']} ({r['confidence']*100:.0f}%){change}")

    # Step 3: Escalate + notify
    escalated = _run_step(steps, "check_and_escalate", check_and_escalate, reviewed)
    print(f"  Escalations: {len(escalated)}")
    _run_step(steps, "send_notifications", send_notifications, escalated)

    # Step 4 (piece B): the recovery state machine, same entry point as the 20-minute lane.
    try:
        _recovery_state_pass()
    except Exception as error:  # noqa: BLE001 — never break the daily review over the recovery pass
        print(f"  Recovery state machine error: {str(error)[:200]}")

    # Step 4: Process any Telegram replies first
    try:
        from telegram_reply_processor import process_replies
    except ImportError as e:
        # Optional step: only *unavailability* is a skip. A step that ran and failed keeps the single
        # `failed` row _run_step already wrote — appending a contradictory `skipped` row for the same
        # step told a reader both things at once (review F2 on #2674).
        steps.append({"name": "process_telegram_replies", "outcome": "skipped", "error": str(e)[:500],
                      "started_at": _iso(_utc_now()), "finished_at": _iso(_utc_now())})
        print(f"  Telegram reply processing skipped: {e}")
    else:
        try:
            reply_count = _run_step(steps, "process_telegram_replies", process_replies)
            print(f"  Telegram replies processed: {reply_count}")
        except Exception as e:
            # The step is optional, so the run continues; the receipt still says one step failed.
            print(f"  Telegram reply processing failed (optional step, run continues): {e}")

    # Step 5: Stop confirmation scan (after processing replies)
    reminders = _run_step(steps, "scan_unconfirmed_stops", scan_unconfirmed_stops)
    print(f"  Stop reminders: {len(reminders)}")
    _run_step(steps, "send_stop_reminders", send_stop_reminders, reminders)

    # Step 5: Temp allocation recommendations
    alloc_updated = _run_step(steps, "compute_temp_allocations", compute_temp_allocations)
    print(f"  Temp allocation recommendations updated: {alloc_updated}")

    print(f"[recovery_watch_daily] Complete — {_iso(_utc_now())}")
    return {"new_stopouts": len(new_stopouts), "true_stopouts": true_stops,
            "relists_detected": relists, "relist_reclassifications": relist_events,
            "created": created, "reviewed": len(reviewed), "escalated": len(escalated),
            "stop_reminders": len(reminders), "alloc_updated": alloc_updated}


def _log_reconciliation() -> dict:
    """The two log names, measured rather than assumed (FQ-117).

    The installed unit writes `logs/recovery-watch.log` (hyphen); an older crontab line wrote
    `logs/recovery_watch.log` (underscore) and is retired in the live crontab but still present, commented, in
    `config/crontab_backup.txt`. Consumers (lane registry output_signal, api_v2) read the hyphen file. Recording
    both here means a reader never has to trust a name: whichever exists is listed with its clock and size.
    """
    out = {}
    for name in ("recovery-watch.log", "recovery_watch.log"):
        path = PROJECT_ROOT / "logs" / name
        try:
            stat = path.stat()
            out[name] = {"present": True, "bytes": stat.st_size,
                         "mtime": _iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc))}
        except OSError:
            out[name] = {"present": False}
    return out


def main():
    """Run the lane and always leave a receipt — including when it dies mid-run.

    cx-openai-2's R2 on #2674: the receipt used to be written after all the work, so a crash left no evidence and a
    write failure left the workload running unrecorded. The invocation is now durable BEFORE any mutable work: if it
    cannot be recorded, the lane does not run. The same file is finalised afterwards, so a hard kill leaves the
    started record with `outcome: "incomplete"` — evidence that a run began and never reported.
    """
    started = _utc_now()
    invocation_id = uuid.uuid4().hex
    steps: list[dict] = []
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "invocation_id": invocation_id,
        "started_at": _iso(started),
        "finished_at": None,
        "source": source_identity(),
        "steps": steps,
        "outcome": "incomplete",
        "error": None,
        "summary": None,
        "exit_code": None,
        "logs": _log_reconciliation(),
    }
    try:
        path = write_run_receipt(receipt)
    except OSError as exc:  # no durable start record -> no mutable work
        print(f"[recovery_watch_daily] refusing to run: run receipt cannot be written: {exc}", file=sys.stderr)
        raise RuntimeError(f"run receipt not writable: {exc}") from exc
    print(f"  Run receipt (started): {path}")

    summary = None
    error = None
    try:
        summary = _run(started, invocation_id, steps)
        return summary
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        receipt.update(
            finished_at=_iso(_utc_now()),
            steps=steps,
            outcome="failed" if error else "ok",
            error=error,
            summary=summary,
            exit_code=1 if error else 0,
            logs=_log_reconciliation(),
        )
        try:
            write_run_receipt(receipt)
        except OSError as exc:  # the started record stays; say why it could not be finalised
            print(f"  Run receipt NOT finalised: {exc}", file=sys.stderr)


def latest_receipt(directory: Path | None = None) -> dict | None:
    """The newest run receipt, parsed; None when the lane has never run.

    Read-only: never writes, never creates the directory, never runs the lane. It exists so a caller (operator,
    monitor, the 2026-11-05 recovery measurement) can answer "did the last run do useful work" from the durable
    record instead of inferring it from a log file's mtime — the gap the measurement named: "log Complete ≠
    useful-work receipt".
    """
    folder = Path(directory) if directory else receipt_dir()
    try:
        files = sorted(folder.glob("*.json"), key=lambda f: f.stat().st_mtime)
    except OSError:
        return None
    for path in reversed(files):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a torn file is skipped, never guessed at
        if isinstance(doc, dict) and doc.get("schema") == RECEIPT_SCHEMA:
            doc["_path"] = str(path)
            return doc
    return None


def source_binding(record: dict | None) -> dict:
    """Bind a recorded run to the code that actually executed it — or say honestly that it cannot be bound.

    A receipt written from ``portfolio-server/CURRENT`` records the script's sha256, the release directory's
    40-hex name and git HEAD (``source_identity``). A later release replaces that tree, so the question a reader
    has is not "what is CURRENT now" but "what did THIS run execute". This answers it by re-hashing the recorded
    path: equal means the same bytes are still there (``bound``), different means a later release replaced them
    (``changed``, with both digests), missing means the tree is gone (``absent``). A record with no digest at all —
    any run from before the receipt existed — is ``unknown``, and is never guessed.
    """
    src = dict((record or {}).get("source") or {})
    out = {"state": "unknown", "release_sha": src.get("release_sha"), "git_head": src.get("git_head"),
           "script": src.get("script"), "script_sha256": src.get("script_sha256"),
           "observed_sha256": None, "detail": "no source digest was recorded, so the executed code cannot be bound"}
    path = Path(str(src.get("script") or "")) if src.get("script") else None
    if path is None or not src.get("script_sha256"):
        return out
    try:
        out["observed_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        out.update(state="absent", detail="the recorded script path no longer exists; the release that ran is gone")
        return out
    if out["observed_sha256"] == src.get("script_sha256"):
        out.update(state="bound", detail="the recorded script is still the file at that path, byte for byte")
    else:
        out.update(state="changed",
                   detail="a later release replaced the script at that path; the recorded digest is the one that ran")
    return out


def receipt_status(directory: Path | None = None) -> dict:
    """A bounded verdict on the last run: outcome, failed steps, what it produced, and the code that ran it."""
    doc = latest_receipt(directory)
    if doc is None:
        return {"schema": "RecoveryWatchStatus@v1", "receipt": None, "ran": False, "useful_work_verified": False,
                "detail": "no run receipt found; the lane has not run, or its receipts are elsewhere"}
    steps = [s for s in doc.get("steps") or [] if isinstance(s, dict)]
    # The runner records `outcome`; synthetic rows and callers may use `ok`. Read both, or a real
    # receipt with a failed step is certified "useful" — the same lie in the reporting layer.
    failed = [str(s.get("name")) for s in steps
              if s.get("ok") is False or s.get("outcome") in ("failed", "error")
              or (isinstance(s.get("failed"), int) and s["failed"] > 0)]
    summary = doc.get("summary") or {}
    useful = bool(summary) and doc.get("outcome") == "ok" and not failed
    return {
        "schema": "RecoveryWatchStatus@v1",
        "receipt": doc.get("_path"),
        "ran": True,
        "invocation_id": doc.get("invocation_id"),
        "started_at": doc.get("started_at"),
        "finished_at": doc.get("finished_at"),
        "outcome": doc.get("outcome"),
        "steps_ok": len(steps) - len(failed),
        "steps_failed": failed,
        "summary": summary,
        "source": doc.get("source"),
        "source_binding": source_binding(doc),
        "logs": doc.get("logs"),
        "useful_work_verified": useful,
        "detail": ("the last run finished and every step reported ok"
                   if useful else
                   f"the last run is {doc.get('outcome')!r}"
                   + (f" with failed steps: {', '.join(failed)}" if failed else "")),
    }


if __name__ == "__main__":
    if "--receipt-status" in sys.argv[1:]:
        status = receipt_status()
        print(json.dumps(status, indent=1, sort_keys=True, default=str))
        raise SystemExit(0 if status.get("useful_work_verified") else 3)
    main()
