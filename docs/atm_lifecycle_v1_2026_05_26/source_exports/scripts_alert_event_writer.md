# Source Export: scripts/alert_event_writer.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/alert_event_writer.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `7f6627d1d75bcd94736512e13f4a927e0129660ee9d78ff94b2ca83e8d4bd613` |
| **File Size** | 16462 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""alert_event_writer.py — Canonical alert event writer + parsers + data quality.

DB first, Telegram second.
Every Telegram alert should be stored as an alert_event before sending.

Usage:
    from alert_event_writer import save_alert_event, parse_stop_triggered_text, detect_data_integrity_issues
"""
import json, os, re, hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# ── DB connection ───────────────────────────────────────────────────

def _get_conn():
    import psycopg2
    pw = os.environ.get("DB_PASSWORD", "")
    if not pw:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _db_write(sql, params=None):
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        result = cur.fetchone() if cur.description else None
        conn.close()
        return result
    except Exception as e:
        print(f"[alert-writer] DB write error: {e}")
        try:
            conn.rollback()
            conn.close()
        except:
            pass
        return None


# ── Core save function ──────────────────────────────────────────────

def save_alert_event(
    alert_type: str,
    raw_text: str,
    symbol: str = None,
    severity: str = "info",
    source_script: str = None,
    price: float = None,
    stop_price: float = None,
    gap_pct: float = None,
    position_value: float = None,
    pnl: float = None,
    decision: str = None,
    confidence: float = None,
    parsed_payload: dict = None,
    data_quality_status: str = "valid",
    requires_agent_review: bool = False,
    telegram_message_id: str = None,
) -> Optional[int]:
    """Save alert event to DB. Returns alert_event id or None on failure.

    DB failure is non-fatal — caller should still send Telegram.
    """
    alert_uid = hashlib.sha256(
        f"{alert_type}:{symbol or ''}:{raw_text[:100]}:{datetime.now().strftime('%Y%m%d%H%M')}".encode()
    ).hexdigest()[:24]

    # Auto-detect data quality issues
    quality = detect_data_integrity_issues({
        "alert_type": alert_type,
        "symbol": symbol,
        "price": price,
        "stop_price": stop_price,
        "gap_pct": gap_pct,
        "position_value": position_value,
        "parsed_payload": parsed_payload or {},
    })
    if quality != "valid":
        data_quality_status = quality
        requires_agent_review = True

    try:
        result = _db_write("""
            INSERT INTO alert_events
                (alert_uid, alert_type, symbol, severity, source_script,
                 raw_text, parsed_payload, price, stop_price, gap_pct,
                 position_value, pnl, decision, confidence,
                 data_quality_status, requires_agent_review,
                 telegram_message_id, telegram_sent_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (alert_uid) DO UPDATE SET
                raw_text = EXCLUDED.raw_text,
                telegram_message_id = COALESCE(EXCLUDED.telegram_message_id, alert_events.telegram_message_id),
                telegram_sent_at = COALESCE(EXCLUDED.telegram_sent_at, alert_events.telegram_sent_at)
            RETURNING id
        """, (
            alert_uid, alert_type, symbol, severity, source_script,
            raw_text, json.dumps(parsed_payload or {}, default=str),
            price, stop_price, gap_pct,
            position_value, pnl, decision, confidence,
            data_quality_status, requires_agent_review,
            telegram_message_id, datetime.now() if telegram_message_id else None,
        ))
        alert_id = result[0] if result else None

        # Auto-create agent jobs for certain alert types
        if alert_id and requires_agent_review and symbol:
            jobs = create_agent_jobs_from_alert(alert_type, symbol, severity)
            if jobs:
                _db_write("UPDATE alert_events SET agent_jobs_created = %s WHERE id = %s",
                          (jobs, alert_id))

        # Also create a data_integrity alert if quality is bad
        if quality != "valid" and alert_type != "data_integrity":
            save_alert_event(
                alert_type="data_integrity",
                raw_text=f"Data quality issue detected in {alert_type} for {symbol}: {quality}",
                symbol=symbol,
                severity="warning",
                source_script=source_script,
                price=price,
                stop_price=stop_price,
                data_quality_status=quality,
                requires_agent_review=True,
                parsed_payload={"original_alert_type": alert_type, "issue": quality},
            )

        return alert_id

    except Exception as e:
        print(f"[alert-writer] Failed to save alert: {e}")
        return None


# ── Parsers ─────────────────────────────────────────────────────────

def parse_stop_triggered_text(text: str) -> dict:
    """Parse: STOP TRIGGERED: RTX @ $174.26 — stop was $180.71 | Max loss: $-29"""
    result = {"alert_type": "stop_triggered", "severity": "urgent"}
    m = re.search(r'STOP TRIGGERED[:\s]+(\w+)\s*@\s*\$?([\d,.]+)', text)
    if m:
        result["symbol"] = m.group(1)
        result["price"] = float(m.group(2).replace(",", ""))
    m2 = re.search(r'stop was \$?([\d,.]+)', text)
    if m2:
        result["stop_price"] = float(m2.group(1).replace(",", ""))
    m3 = re.search(r'Max loss[:\s]*\$?(-?[\d,.]+)', text)
    if m3:
        result["pnl"] = float(m3.group(1).replace(",", ""))
    if result.get("price") and result.get("stop_price"):
        result["gap_pct"] = round((result["price"] - result["stop_price"]) / result["stop_price"] * 100, 2)
    return result


def parse_stop_brief_text(text: str) -> dict:
    """Parse: Price: $174.26 | Stop: $180.71 | Gap: 3.6%"""
    result = {"alert_type": "stop_brief", "severity": "warning"}
    m_sym = re.search(r'STOP BRIEF\s*[—–-]\s*(\w+)', text)
    if m_sym:
        result["symbol"] = m_sym.group(1)
    m_price = re.search(r'Price:\s*\$?([\d,.]+)', text)
    if m_price:
        result["price"] = float(m_price.group(1).replace(",", ""))
    m_stop = re.search(r'Stop:\s*\$?([\d,.]+)', text)
    if m_stop:
        result["stop_price"] = float(m_stop.group(1).replace(",", ""))
    m_gap = re.search(r'Gap:\s*([\d.]+)%', text)
    if m_gap:
        result["gap_pct"] = float(m_gap.group(1))
    m_mv = re.search(r'Position:\s*\$?([\d,.]+)', text)
    if m_mv:
        result["position_value"] = float(m_mv.group(1).replace(",", ""))
    m_dec = re.search(r'Decision:\s*(\w+)', text)
    if m_dec:
        result["decision"] = m_dec.group(1)
    return result


def parse_staleness_alert_text(text: str) -> dict:
    """Parse: Portfolio data is 61h old."""
    result = {"alert_type": "data_staleness", "severity": "warning"}
    m = re.search(r'(\d+)h?\s*old', text)
    if m:
        result["parsed_payload"] = {"age_hours": int(m.group(1))}
    m2 = re.search(r'hash[=:\s]+(\w+)', text, re.IGNORECASE)
    if m2:
        result.setdefault("parsed_payload", {})["hash"] = m2.group(1)
    return result


def parse_portfolio_intelligence_text(text: str) -> dict:
    """Parse: SP500-D: -23.3% today on a $40,161 position."""
    result = {"alert_type": "portfolio_intelligence", "severity": "info"}
    # Major mover pattern
    m = re.search(r'(\S+):\s*([+-]?[\d.]+)%\s*today\s*on\s*a?\s*\$?([\d,.]+)', text)
    if m:
        result["symbol"] = m.group(1)
        result["parsed_payload"] = {
            "daily_change_pct": float(m.group(2)),
            "position_value": float(m.group(3).replace(",", "")),
        }
        result["position_value"] = float(m.group(3).replace(",", ""))
        if abs(float(m.group(2))) > 10:
            result["severity"] = "critical"
            result["data_quality_status"] = "unvalidated"
    return result


def parse_technical_signal_text(text: str) -> dict:
    """Parse: JEPI crossed BELOW SMA200 ($57.36) ($57,320)"""
    result = {"alert_type": "technical_signal", "severity": "info"}
    m = re.search(r'(\w+)\s+crossed\s+(ABOVE|BELOW)\s+(SMA\d+|50-day MA|200-day MA)', text, re.IGNORECASE)
    if m:
        result["symbol"] = m.group(1)
        result["parsed_payload"] = {
            "direction": m.group(2).upper(),
            "indicator": m.group(3),
        }
    # Indicator value
    m2 = re.search(r'\$(\d+\.\d{2})\)', text)
    if m2:
        result["parsed_payload"] = result.get("parsed_payload", {})
        result["parsed_payload"]["indicator_value"] = float(m2.group(1))
        result["price"] = float(m2.group(1))
    # Position value (comma-separated, > $1000)
    m3 = re.search(r'\$(\d{1,3}(?:,\d{3})+)\)', text)
    if m3:
        result["position_value"] = float(m3.group(1).replace(",", ""))
    # Severity for 200-day crosses
    if "SMA200" in text or "200-day" in text:
        result["severity"] = "warning"
    return result


# ── Data quality detection ──────────────────────────────────────────

def detect_data_integrity_issues(payload: dict) -> str:
    """Check for data integrity problems. Returns quality status string."""
    alert_type = payload.get("alert_type", "")
    price = payload.get("price")
    stop_price = payload.get("stop_price")
    pp = payload.get("parsed_payload", {})

    # 1. Zero price/stop in stop alerts
    if alert_type in ("stop_brief", "stop_triggered"):
        if price is not None and price == 0:
            return "invalid_zero_price_or_stop"
        if stop_price is not None and stop_price == 0:
            return "invalid_zero_price_or_stop"

    # 2. Extreme daily move (Fidelity scale anomaly candidate)
    daily_pct = pp.get("daily_change_pct")
    if daily_pct is not None and abs(daily_pct) > 10:
        symbol = payload.get("symbol", "")
        # Check if it's a Fidelity mapped fund
        fidelity_prefixes = ("SP500", "FID-", "TRP-", "VANG-", "SS-", "JPM-")
        if any(symbol.startswith(p) for p in fidelity_prefixes):
            return "fidelity_scale_anomaly"
        # Even non-Fidelity > 15% is suspicious
        if abs(daily_pct) > 15:
            return "unvalidated"

    # 3. Conflicting stop values (same symbol, recent window)
    # This would need DB lookup — handled at save time via agent review flag

    return "valid"


# ── Auto-escalation ────────────────────────────────────────────────

def create_agent_jobs_from_alert(alert_type: str, symbol: str, severity: str) -> list:
    """Create watchlist agent jobs triggered by an alert. Returns list of job IDs."""
    jobs = []
    ts = datetime.now().strftime("%Y%m%d%H%M%S")

    # Determine which agents to queue
    agents_needed = []

    if alert_type == "stop_triggered":
        agents_needed.append("risk_agent")
        # Check if symbol is in portfolio for Steph job
        if _symbol_in_portfolio(symbol):
            agents_needed.append("steph")
        # Check if taxable exposure
        if _has_taxable_exposure(symbol):
            agents_needed.append("tax_agent")

    elif alert_type == "data_integrity":
        agents_needed.append("risk_agent")

    elif alert_type in ("technical_signal",) and severity in ("warning", "critical"):
        if _symbol_in_portfolio(symbol) or _symbol_in_watchlist(symbol):
            agents_needed.append("risk_agent")

    elif alert_type == "recovery_watch":
        agents_needed.append("risk_agent")
        if _symbol_in_portfolio(symbol):
            agents_needed.append("steph")

    for agent in agents_needed:
        job_id = f"alert-{symbol.lower()}-{agent}-{ts}"
        result = _db_write("""
            INSERT INTO watchlist_agent_jobs
                (id, symbol, requested_agent, request_type, note, status, payload)
            VALUES (%s, %s, %s, %s, %s, 'queued', %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
        """, (
            job_id, symbol, agent, "research",
            f"Auto-triggered by {alert_type} alert",
            json.dumps({"triggered_by": alert_type, "severity": severity}),
        ))
        if result:
            jobs.append(job_id)
            # Log event
            _db_write("""
                INSERT INTO watchlist_events (event_type, symbol, agent, status, message)
                VALUES ('alert_escalation', %s, %s, 'queued', %s)
            """, (symbol, agent, f"Auto-queued from {alert_type} alert"))

    # Mark strategy card and maturity as needing iteration
    if alert_type in ("stop_triggered", "data_integrity"):
        _db_write("""
            UPDATE watchlist_strategy_cards SET needs_iteration = true, updated_at = now()
            WHERE symbol = %s
        """, (symbol,))
        _db_write("""
            UPDATE watchlist_analysis_maturity
            SET needs_iteration = true, iteration_reason = %s, updated_at = now()
            WHERE symbol = %s
        """, (f"Alert: {alert_type}", symbol))

    return jobs


def _symbol_in_portfolio(symbol: str) -> bool:
    try:
        h = json.loads((STATE_DIR / "holdings.json").read_text())
        return any(p.get("symbol") == symbol for p in h.get("holdings", []))
    except:
        return False


def _symbol_in_watchlist(symbol: str) -> bool:
    try:
        result = _db_write("SELECT 1 FROM watchlist_items WHERE symbol = %s AND status <> 'removed' LIMIT 1", (symbol,))
        return result is not None
    except:
        return False


def _has_taxable_exposure(symbol: str) -> bool:
    try:
        h = json.loads((STATE_DIR / "holdings.json").read_text())
        for p in h.get("holdings", []):
            if p.get("symbol") == symbol:
                aid = (p.get("account_id") or p.get("account") or "").lower()
                if "taxable" in aid or "individual" in aid:
                    return True
        return False
    except:
        return False


# ── Synthesis blocker ───────────────────────────────────────────────

def check_synthesis_blocked(symbol: str) -> dict:
    """Check data quality status for a symbol. Soft-block: warns and lowers confidence, not hard-block.

    Returns:
        warned: True if DQ issues exist (synthesis still proceeds with lower confidence)
        hard_blocked: True only if multiple critical conflicting alerts (rare)
    """
    try:
        conn = _get_conn()
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT alert_type, data_quality_status, severity, raw_text, created_at
            FROM alert_events
            WHERE symbol = %s
            AND data_quality_status NOT IN ('valid', 'unknown')
            AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC
            LIMIT 5
        """, (symbol,))
        issues = [dict(r) for r in cur.fetchall()]
        conn.close()

        # Hard block only for multiple critical conflicting alerts
        critical_count = sum(1 for i in issues if i.get("severity") == "critical")
        hard_blocked = critical_count >= 2

        return {
            "warned": len(issues) > 0,
            "hard_blocked": hard_blocked,
            "blocked": hard_blocked,  # backward compat
            "issues": issues,
            "issue_count": len(issues),
            "reason": issues[0]["data_quality_status"] if issues else None,
            "confidence_penalty": min(0.3, len(issues) * 0.1),
        }
    except Exception as e:
        return {"blocked": False, "blockers": [], "reason": None}
```
