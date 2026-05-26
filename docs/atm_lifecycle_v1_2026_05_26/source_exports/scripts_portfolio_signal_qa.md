# Source Export: scripts/portfolio_signal_qa.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/portfolio_signal_qa.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `0ab64be54436230a087d019271bd273ba7289b29225dbe652e4e60a95784b0eb` |
| **File Size** | 8302 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""
portfolio_signal_qa.py — Aggregate signals by strategy group for portfolio QA.

Loads recent fused_signals, groups by strategy_type, detects concentration of
high-severity signals in same group and income-risk signal clusters.
Writes to signal_clusters and portfolio_intelligence_events.

CLI: python3 scripts/portfolio_signal_qa.py [--json]
"""
import json, os, sys
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# Thresholds
HIGH_SEVERITY_CONCENTRATION_MIN = 3   # signals in same group to flag
INCOME_RISK_KEYWORDS = ["dividend_cut", "dividend_risk", "income_threat", "yield_decline"]
LOOKBACK_DAYS = 7


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _severity_rank(sev: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get((sev or "").lower(), 0)


def run(as_json: bool = False):
    conn = _get_conn()
    cur = conn.cursor()

    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    today = date.today()

    # Load recent fused_signals
    cur.execute("""
        SELECT id, symbol, strategy_type, fused_score, severity, direction,
               confidence, portfolio_impact_pct, reason_codes, created_at
        FROM fused_signals
        WHERE created_at >= %s
        ORDER BY created_at DESC
    """, (cutoff,))
    rows = cur.fetchall()

    # Group by strategy_type
    groups = defaultdict(list)
    for row in rows:
        sid, symbol, stype, fused_score, severity, direction, confidence, impact_pct, reason_codes, created_at = row
        stype = stype or "unclassified"
        groups[stype].append({
            "id": sid, "symbol": symbol, "strategy_type": stype,
            "fused_score": float(fused_score or 0), "severity": severity or "low",
            "direction": direction, "confidence": float(confidence or 0),
            "impact_pct": float(impact_pct or 0),
            "reason_codes": reason_codes or [],
        })

    clusters_created = []
    events_created = []

    for strategy_type, signals in groups.items():
        # ── Check 1: High-severity concentration ─────────────────────────
        high_sev = [s for s in signals if _severity_rank(s["severity"]) >= 3]
        if len(high_sev) >= HIGH_SEVERITY_CONCENTRATION_MIN:
            symbols_involved = list(set(s["symbol"] for s in high_sev))
            avg_sev = sum(_severity_rank(s["severity"]) for s in high_sev) / len(high_sev)
            directions = [s["direction"] for s in high_sev if s["direction"]]
            dominant = max(set(directions), key=directions.count) if directions else "mixed"
            total_impact = sum(s["impact_pct"] for s in high_sev)

            cur.execute("""
                INSERT INTO signal_clusters
                    (cluster_date, strategy_type, group_id, cluster_type,
                     symbols_involved, signal_count, avg_severity,
                     dominant_direction, portfolio_impact, requires_action, summary)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                today, strategy_type, f"{strategy_type}_concentration",
                "high_severity_concentration",
                symbols_involved, len(high_sev), round(avg_sev, 2),
                dominant, round(total_impact, 2), True,
                f"{len(high_sev)} high/critical signals in {strategy_type}: {', '.join(symbols_involved[:5])}"
            ))
            cluster_id = cur.fetchone()[0]
            clusters_created.append({
                "cluster_id": cluster_id,
                "type": "high_severity_concentration",
                "strategy_type": strategy_type,
                "signal_count": len(high_sev),
                "symbols": symbols_involved,
            })

            # Also write a portfolio_intelligence_event
            cur.execute("""
                INSERT INTO portfolio_intelligence_events
                    (symbol, strategy_type, event_type, severity, source,
                     impact_score, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                symbols_involved[0] if len(symbols_involved) == 1 else None,
                strategy_type, "signal_concentration", "high",
                "portfolio_signal_qa",
                round(total_impact, 2),
                json.dumps({
                    "cluster_id": cluster_id,
                    "signal_count": len(high_sev),
                    "symbols": symbols_involved,
                    "dominant_direction": dominant,
                }),
            ))
            events_created.append(cur.fetchone()[0])

        # ── Check 2: Income-risk signal clusters ─────────────────────────
        income_risk = [
            s for s in signals
            if any(kw in rc for rc in (s["reason_codes"] or []) for kw in INCOME_RISK_KEYWORDS)
        ]
        if len(income_risk) >= 2:
            symbols_involved = list(set(s["symbol"] for s in income_risk))
            avg_sev = sum(_severity_rank(s["severity"]) for s in income_risk) / len(income_risk)
            total_impact = sum(s["impact_pct"] for s in income_risk)

            cur.execute("""
                INSERT INTO signal_clusters
                    (cluster_date, strategy_type, group_id, cluster_type,
                     symbols_involved, signal_count, avg_severity,
                     dominant_direction, portfolio_impact, requires_action, summary)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                today, strategy_type, f"{strategy_type}_income_risk",
                "income_risk_cluster",
                symbols_involved, len(income_risk), round(avg_sev, 2),
                "negative", round(total_impact, 2), True,
                f"Income-risk cluster in {strategy_type}: {', '.join(symbols_involved[:5])}"
            ))
            cluster_id = cur.fetchone()[0]
            clusters_created.append({
                "cluster_id": cluster_id,
                "type": "income_risk_cluster",
                "strategy_type": strategy_type,
                "signal_count": len(income_risk),
                "symbols": symbols_involved,
            })

            cur.execute("""
                INSERT INTO portfolio_intelligence_events
                    (symbol, strategy_type, event_type, severity, source,
                     impact_score, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                None, strategy_type, "income_risk_cluster", "high",
                "portfolio_signal_qa",
                round(total_impact, 2),
                json.dumps({
                    "cluster_id": cluster_id,
                    "signal_count": len(income_risk),
                    "symbols": symbols_involved,
                }),
            ))
            events_created.append(cur.fetchone()[0])

    conn.commit()
    cur.close()
    conn.close()

    if as_json:
        print(json.dumps({
            "signals_analyzed": len(rows),
            "strategy_groups": len(groups),
            "clusters_created": clusters_created,
            "events_created": len(events_created),
        }, default=str))
    else:
        print(f"[portfolio_signal_qa] Analyzed {len(rows)} fused_signals across {len(groups)} strategy groups.")
        print(f"[portfolio_signal_qa] Created {len(clusters_created)} signal clusters, {len(events_created)} intelligence events.")
        for c in clusters_created:
            print(f"  {c['type']:<30} | {c['strategy_type']:<15} | {c['signal_count']} signals | {', '.join(c['symbols'][:3])}")


if __name__ == "__main__":
    run(as_json="--json" in sys.argv)
```
