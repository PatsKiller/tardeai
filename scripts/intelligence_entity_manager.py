"""
intelligence_entity_manager.py
Trade AI v12 — Intelligence Entity Record Manager

Single write-back module for all pipelines. Every enrichment source
calls upsert_entity() after completing its work. Handles both
market entities (tickers/ETFs) and subject entities (SSDI/IRMAA/etc).

CALLING PATTERN:
    from scripts.intelligence_entity_manager import upsert_entity, get_entity

    # After finviz_enrichment runs:
    upsert_entity(conn, 'AMD', 'market', {
        'current_price': 170.20,
        'rvol': 2.3,
        'sector': 'Technology',
    }, source='finviz')

    # For a subject entity:
    upsert_entity(conn, 'SSDI', 'subject', {
        'current_thresholds': {'income_limit': 45600, 'sga': 1620},
        'john_impact': 'Income limit $45,600/yr',
    }, source='alex_gov_research')
"""

import logging
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────
# ENTITY TYPE INFERENCE
# ─────────────────────────────────────────────

SUBJECT_ENTITIES = {
    'SSDI', 'IRMAA', 'Roth_Conversion', 'Golden_Window', 'Disability_Trust',
    'Medicare', 'MFS_Filing', '401k_Loan', 'Medicaid_Lookback',
    'Omnicom_Rollover', 'Private_Disability', 'Schedule_C',
    'SSDI_RULES', 'IRMAA_RULES', 'ROTH_RULES', 'TRUST_RULES',
}

SUBJECT_DISPLAY_NAMES = {
    'SSDI': 'SSDI Benefits & Income Rules',
    'IRMAA': 'IRMAA Medicare Surcharge Thresholds',
    'Roth_Conversion': 'Roth IRA Conversion Strategy',
    'Golden_Window': 'Golden Window 2036-2040 (Ages 68.5-73)',
    'Disability_Trust': 'Special Needs Disability Trust Planning',
    'Medicare': 'Medicare Part A/B/D Rules',
    'MFS_Filing': 'Married Filing Separately Tax Rules',
    '401k_Loan': '401k Loan — Omnicom (Deadline ~634 days)',
    'Medicaid_Lookback': 'Medicaid 5-Year Lookback Rules',
    'Omnicom_Rollover': 'Omnicom 401k → Fidelity Rollover IRA (COMPLETE 2026-06-18)',
    'Private_Disability': 'Private Disability Insurance (to age 68.5)',
    'Schedule_C': 'Schedule C Business Income (~$20K/yr)',
}

SUBJECT_SUBTYPES = {
    'SSDI': 'disability', 'IRMAA': 'tax', 'Roth_Conversion': 'retirement',
    'Golden_Window': 'retirement', 'Disability_Trust': 'disability',
    'Medicare': 'disability', 'MFS_Filing': 'tax', '401k_Loan': 'planning',
    'Medicaid_Lookback': 'disability', 'Omnicom_Rollover': 'planning',
    'Private_Disability': 'disability', 'Schedule_C': 'tax',
}


def _infer_subtype(entity_id: str, entity_type: str) -> str:
    if entity_type == 'subject':
        return SUBJECT_SUBTYPES.get(entity_id, 'general')
    known_etfs = {'SPY', 'QQQ', 'SCHD', 'BND', 'VTI', 'GLD', 'IWM', 'EFA',
                  'CSWC', 'ARKG', 'XLF', 'XLE', 'SCHG', 'JEPI'}
    if entity_id in known_etfs:
        return 'etf'
    return 'equity'


def _compute_intelligence_score(record: dict, entity_type: str) -> tuple:
    """Compute composite intelligence_score (0-100) and grade."""
    score = 0.0

    if entity_type == 'market':
        # Price freshness (25 pts)
        if record.get('price_updated_at'):
            ts = record['price_updated_at']
            if hasattr(ts, 'timestamp'):
                age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            else:
                age_min = 9999
            if age_min < 15: score += 25
            elif age_min < 60: score += 15
            elif age_min < 240: score += 5

        # Technical confluence (20 pts)
        tier = record.get('confluence_tier', 'NONE') or 'NONE'
        score += {'STRONG': 20, 'MODERATE': 15, 'WEAK': 8, 'NONE': 0}.get(tier, 0)

        # Screener/pipeline presence (20 pts)
        sources = record.get('pipeline_sources') or []
        score += min(20, len(sources) * 7)

        # Agent analysis freshness (20 pts)
        if record.get('last_agent_analysis'):
            ts = record['last_agent_analysis']
            if hasattr(ts, 'timestamp'):
                age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
            else:
                age_days = 9999
            if age_days < 1: score += 20
            elif age_days < 7: score += 10
            elif age_days < 30: score += 5

        # RAG coverage (15 pts)
        rag = record.get('rag_item_count', 0) or 0
        score += min(15, rag * 3)

    else:  # subject
        # Threshold freshness (30 pts)
        if record.get('thresholds_updated'):
            ts = record['thresholds_updated']
            if hasattr(ts, 'timestamp'):
                age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
            else:
                age_days = 9999
            if age_days < 30: score += 30
            elif age_days < 90: score += 15
            elif age_days < 365: score += 5

        # Agent analysis freshness (25 pts)
        if record.get('last_agent_analysis'):
            ts = record['last_agent_analysis']
            if hasattr(ts, 'timestamp'):
                age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
            else:
                age_days = 9999
            if age_days < 7: score += 25
            elif age_days < 30: score += 15
            elif age_days < 90: score += 5

        # RAG coverage (25 pts)
        rag = record.get('rag_item_count', 0) or 0
        score += min(25, rag * 2.5)

        # John impact defined (20 pts)
        if record.get('john_impact'): score += 20

    score = min(100, max(0, score))

    if score >= 90: grade = 'A+'
    elif score >= 80: grade = 'A'
    elif score >= 65: grade = 'B'
    elif score >= 50: grade = 'C'
    else: grade = 'D'

    return round(score, 1), grade


# ─────────────────────────────────────────────
# CORE UPSERT FUNCTION
# ─────────────────────────────────────────────

def _dead_conn_msg(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in (
        "already closed", "interfaceerror", "ssl connection", "connection has been closed",
    ))


def _live_conn(conn):
    """Prefer a live handle; rebuild after idle/SSL death."""
    try:
        if conn is not None and not getattr(conn, "closed", 1):
            return conn
    except Exception:
        pass
    try:
        from db_adapter import ensure_conn
        return ensure_conn()
    except Exception:
        return conn


def upsert_entity(conn, entity_id: str, entity_type: str,
                  fields: dict, source: str = 'unknown', _retried: bool = False) -> bool:
    """
    Upsert an intelligence entity record.
    Only updates fields provided. Non-fatal — never raises.
    """
    conn = _live_conn(conn)
    try:
        cur = conn.cursor()

        # Check if entity exists
        cur.execute("SELECT entity_id FROM intelligence_entities WHERE entity_id = %s", [entity_id])
        existing = cur.fetchone()

        now = datetime.now(timezone.utc)

        if not existing:
            display_name = (SUBJECT_DISPLAY_NAMES.get(entity_id) or
                           fields.pop('display_name', None) or entity_id)
            subtype = fields.pop('entity_subtype', _infer_subtype(entity_id, entity_type))

            cur.execute("""
                INSERT INTO intelligence_entities
                    (entity_id, entity_type, entity_subtype, display_name,
                     active, created_at, last_enriched, signal_count)
                VALUES (%s, %s, %s, %s, true, %s, %s, 0)
                ON CONFLICT (entity_id) DO NOTHING
            """, [entity_id, entity_type, subtype, display_name, now, now])
            conn.commit()
            log.info(f"[IEM] Created new {entity_type} entity: {entity_id}")

        if not fields:
            return True

        # Always update last_enriched
        fields['last_enriched'] = now

        # Build SET clause dynamically
        set_parts = []
        values = []

        for col, val in fields.items():
            if col in ('entity_id', 'entity_type', 'created_at', 'display_name', 'entity_subtype'):
                continue

            if col == 'current_thresholds' and isinstance(val, dict):
                set_parts.append(f"{col} = %s::jsonb")
                values.append(json.dumps(val))
            elif col in ('tags', 'pipeline_sources', 'social_sources',
                         'confluence_badges') and isinstance(val, list):
                set_parts.append(f"{col} = %s::text[]")
                values.append(val)
            else:
                set_parts.append(f"{col} = %s")
                values.append(val)

        # Update pipeline_sources to include this source
        set_parts.append("""
            pipeline_sources = ARRAY(
                SELECT DISTINCT unnest(
                    COALESCE(pipeline_sources, '{}') || ARRAY[%s::text]
                )
            )
        """)
        values.append(source)

        # Increment signal_count
        set_parts.append("signal_count = COALESCE(signal_count, 0) + 1")

        values.append(entity_id)  # for WHERE clause

        cur.execute(f"""
            UPDATE intelligence_entities
            SET {', '.join(set_parts)}
            WHERE entity_id = %s
        """, values)

        # Recompute intelligence score
        cur.execute("SELECT * FROM intelligence_entities WHERE entity_id = %s", [entity_id])
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if row:
            record = dict(zip(cols, row))
            score, grade = _compute_intelligence_score(record, entity_type)
            cur.execute("""
                UPDATE intelligence_entities
                SET intelligence_score = %s, intelligence_grade = %s
                WHERE entity_id = %s
            """, [score, grade, entity_id])

        conn.commit()
        return True

    except Exception as e:
        log.error(f"[IEM] upsert_entity failed for {entity_id}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        if not _retried and _dead_conn_msg(e):
            try:
                from db_adapter import close_thread_conn, ensure_conn
                close_thread_conn()
                return upsert_entity(ensure_conn(), entity_id, entity_type, fields, source, _retried=True)
            except Exception as e2:
                log.error(f"[IEM] upsert_entity retry failed for {entity_id}: {e2}")
        return False


def get_entity(conn, entity_id: str) -> Optional[dict]:
    """Get complete intelligence entity record."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM intelligence_entities WHERE entity_id = %s", [entity_id])
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if row:
            return dict(zip(cols, row))
        return None
    except Exception as e:
        log.error(f"[IEM] get_entity failed for {entity_id}: {e}")
        return None


def get_entity_context_for_prompt(conn, entity_id: str) -> str:
    """
    Return formatted context block for injection into agent prompts.
    Non-fatal — returns empty string on any error.
    """
    try:
        record = get_entity(conn, entity_id)
        if not record:
            return ''

        entity_type = record.get('entity_type', 'market')
        lines = [f"\n=== INTELLIGENCE ENTITY: {entity_id} ==="]
        lines.append(f"Type: {entity_type} | Grade: {record.get('intelligence_grade','?')} "
                     f"({record.get('intelligence_score','?')}/100)")

        if entity_type == 'market':
            if record.get('current_price'):
                price_parts = [f"Price: ${float(record['current_price']):.2f}"]
                if record.get('change_pct'):
                    price_parts.append(f"Change: {float(record['change_pct']):+.1f}%")
                if record.get('rvol'):
                    price_parts.append(f"RVOL: {float(record['rvol']):.1f}x")
                if record.get('volatility_regime'):
                    price_parts.append(f"Vol: {record['volatility_regime']}")
                lines.append(" | ".join(price_parts))

            if record.get('confluence_tier') and record['confluence_tier'] != 'NONE':
                badges = record.get('confluence_badges') or []
                badge_str = ' '.join(badges) if badges else 'none'
                lines.append(f"Confluence: {record['confluence_tier']} "
                             f"({record.get('confluence_score',0)}/100) — {badge_str}")

            sources = record.get('pipeline_sources') or []
            if sources:
                lines.append(f"Surfaced by: {' + '.join(sources)}")

            if record.get('screener_decision'):
                lines.append(f"Trade AI: {record['screener_decision']} "
                             f"(score: {record.get('screener_score','?')})")

            if record.get('social_mentions') and record['social_mentions'] > 0:
                lines.append(f"Social: {record['social_mentions']} mentions")

            if record.get('previously_traded'):
                lines.append(f"Previously traded | Re-entry: {record.get('reentry_status','UNKNOWN')}")

            if record.get('catalyst'):
                lines.append(f"Catalyst: {record['catalyst']}"
                            + (" [VERIFIED]" if record.get('catalyst_verified') else ""))

        else:  # subject
            if record.get('current_thresholds'):
                thresholds = record['current_thresholds']
                if isinstance(thresholds, str):
                    thresholds = json.loads(thresholds)
                if isinstance(thresholds, dict):
                    thresh_parts = [f"{k}: {v}" for k, v in list(thresholds.items())[:4]]
                    lines.append("Thresholds: " + " | ".join(thresh_parts))

            if record.get('john_impact'):
                lines.append(f"John impact: {str(record['john_impact'])[:120]}")

            if record.get('john_risk_level'):
                lines.append(f"Risk level: {record['john_risk_level'].upper()}")

            if record.get('john_action_needed'):
                lines.append(f"Action needed: {record['john_action_needed']}")

        # Shared
        if record.get('last_agent_verdict'):
            lines.append(f"Last agent: {str(record['last_agent_verdict'])[:100]}")

        rag_count = record.get('rag_item_count', 0) or 0
        if rag_count > 0:
            lines.append(f"RAG: {rag_count} items")

        freshness = record.get('iris_freshness')
        if freshness in ('STALE', 'CRITICAL'):
            lines.append(f"Iris: {freshness} — {(record.get('iris_notes') or '')[:80]}")

        lines.append("=" * 40)
        return '\n'.join(lines)

    except Exception as e:
        log.error(f"[IEM] get_entity_context_for_prompt failed for {entity_id}: {e}")
        return ''


if __name__ == '__main__':
    import sys
    import psycopg2

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', 5432)),
        dbname=os.getenv('DB_NAME', 'trade_ai'),
        user=os.getenv('DB_USER', 'trade_ai'),
        password=os.getenv('DB_PASSWORD', '')
    )

    if len(sys.argv) > 1:
        entity_id = sys.argv[1]
        record = get_entity(conn, entity_id)
        if record:
            print(f"\nEntity: {entity_id}")
            print(f"Type: {record['entity_type']} | Grade: {record.get('intelligence_grade','?')} "
                  f"({record.get('intelligence_score','?')}/100)")
            print(get_entity_context_for_prompt(conn, entity_id))
        else:
            print(f"Entity {entity_id} not found")
    else:
        cur = conn.cursor()
        cur.execute("""
            SELECT entity_id, entity_type, entity_subtype,
                   intelligence_grade, intelligence_score, iris_freshness,
                   last_enriched
            FROM intelligence_entities
            ORDER BY intelligence_score DESC NULLS LAST
        """)
        rows = cur.fetchall()
        print(f"\n{'Entity':<25} {'Type':<10} {'Grade':<6} {'Score':<7} {'Freshness':<10}")
        print("-" * 65)
        for r in rows:
            print(f"{r[0]:<25} {r[1]:<10} {(r[3] or '?'):<6} {(r[4] or 0):<7.1f} "
                  f"{(r[5] or 'UNKNOWN'):<10}")
        print(f"\nTotal: {len(rows)} entities")

    conn.close()
