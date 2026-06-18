"""
seed_intelligence_entities.py — One-time bootstrap of intelligence_entities table.
Reads existing data from multiple sources and creates IER records.
Idempotent (uses upsert_entity which handles ON CONFLICT).
"""
import os, sys, json, psycopg2
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from scripts.intelligence_entity_manager import upsert_entity, SUBJECT_ENTITIES, SUBJECT_DISPLAY_NAMES

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    port=int(os.getenv('DB_PORT', 5432)),
    dbname=os.getenv('DB_NAME', 'trade_ai'),
    user=os.getenv('DB_USER', 'trade_ai'),
    password=os.getenv('DB_PASSWORD', '')
)
cur = conn.cursor()

print("=== Seeding Intelligence Entities ===\n")

# ── 1. SEED SUBJECT ENTITIES ──────────────────────────────

print("1. Creating subject entities...")

subject_seeds = {
    'SSDI': {
        'john_impact': 'Income limit $45,600/yr. Any Schedule C increase above safe threshold needs explicit warning.',
        'john_risk_level': 'high',
        'john_action_needed': 'Recertify disability twice per year. Monitor Schedule C income.',
        'tags': ['disability', 'income_limit', 'annual_recertification'],
        'description': 'SSDI rules, income thresholds, trial work period, substantial gainful activity limits.',
    },
    'IRMAA': {
        'john_impact': 'MFS threshold: $103,000 MAGI. Current room ~$66,883. Any Roth conversion or IRA distribution must stay below.',
        'john_risk_level': 'critical',
        'john_action_needed': 'Check MAGI before any Roth conversion or large IRA distribution.',
        'tags': ['medicare', 'surcharge', 'magi_limit', 'mfs'],
        'description': 'Medicare Income-Related Monthly Adjustment Amount. MFS threshold $103K.',
    },
    'Roth_Conversion': {
        'john_impact': 'Sweet spot: $35K-$50K/yr. $35K done in 2026. Room: ~$66,883. 22% ceiling: $94,300 MFS.',
        'john_risk_level': 'medium',
        'john_action_needed': 'Plan 2026 final conversion amount. Monitor MAGI through year-end.',
        'tags': ['roth', 'tax_planning', 'conversion', 'golden_window'],
        'description': 'Roth IRA conversion strategy. Annual sweet spot fills 12% bracket optimally.',
    },
    'Golden_Window': {
        'john_impact': 'Ages 68.5-73 (2036-2040). Disability stops, before RMDs begin. Convert aggressively during this period.',
        'john_risk_level': 'low',
        'john_action_needed': 'Every decision should optimize toward this window.',
        'tags': ['roth', 'planning_horizon', 'rmds', 'disability'],
        'description': 'Optimal Roth conversion window ages 68.5-73 when disability income stops and RMDs have not started.',
    },
    'Disability_Trust': {
        'john_impact': 'Medicaid 5-year lookback on any trust transfers. Consult attorney before any trust action.',
        'john_risk_level': 'high',
        'john_action_needed': 'No action without elder law attorney review.',
        'tags': ['disability', 'trust', 'medicaid', 'estate'],
        'description': 'Special Needs Trust planning considerations. Medicaid lookback rules.',
    },
    '401k_Loan': {
        'john_impact': 'Outstanding ~$21,735. Deadline ~634 days from April 2026. Omnicom employment terminated Feb 28 2026.',
        'john_risk_level': 'critical',
        'john_action_needed': 'Resolve before deadline. Options: pay off or plan rollover strategy.',
        'tags': ['401k', 'loan', 'deadline', 'omnicom'],
        'description': 'Outstanding 401k loan from Omnicom. Must be resolved before separation deadline.',
    },
    'Omnicom_Rollover': {
        'john_impact': 'COMPLETE 2026-06-18: rolled into a NEW Fidelity Rollover IRA #***199 (~$568K, 100% cash) — earlier than the planned 2027 and held at Fidelity, NOT consolidated into Schwab. Traditional-IRA pool now split across two custodians.',
        'john_risk_level': 'medium',
        'john_action_needed': 'Decide: keep at Fidelity or transfer to Schwab to consolidate for Roth conversions. Deploy the ~$568K cash. Confirm 401k loan tax treatment.',
        'tags': ['401k', 'rollover', 'fidelity', 'omnicom', 'complete'],
        'description': 'Omnicom 401k rolled over to Fidelity Rollover IRA #***199, complete 2026-06-18.',
    },
    'Medicaid_Lookback': {
        'john_impact': 'Any IRA distribution >$50K needs lookback analysis. Trust transfers subject to 5-year lookback.',
        'john_risk_level': 'high',
        'john_action_needed': 'Check before any large distribution or asset transfer.',
        'tags': ['medicaid', 'lookback', 'disability', 'distributions'],
        'description': 'Medicaid 5-year lookback rules. Applies to IRA distributions and asset transfers.',
    },
    'Private_Disability': {
        'john_impact': 'Continues until age 68.5. Recertify 2x/year. Do not jeopardize.',
        'john_risk_level': 'critical',
        'john_action_needed': 'Recertify on schedule. Income must not exceed SSDI limits.',
        'tags': ['disability', 'income', 'insurance', 'recertification'],
        'description': 'Private disability insurance continuing until age 68.5. Recertify twice per year.',
    },
    'MFS_Filing': {
        'john_impact': 'Married Filing Separately. Lower brackets, lower IRMAA thresholds. 22% ceiling $94,300.',
        'john_risk_level': 'medium',
        'john_action_needed': 'Verify MFS status annually. Check lived-apart rule for Roth IRA eligibility.',
        'tags': ['filing_status', 'tax', 'mfs', 'brackets'],
        'description': 'MFS filing status rules. Affects Roth, IRMAA thresholds, bracket calculations.',
    },
    'Schedule_C': {
        'john_impact': '~$20K/yr gross. Counts toward MAGI. SE tax applies. Monitor toward SSDI income limit.',
        'john_risk_level': 'medium',
        'john_action_needed': 'Track year-to-date. Ensure SSDI + Schedule_C stays below safe threshold.',
        'tags': ['self_employment', 'income', 'magi', 'ssdi_limit'],
        'description': 'Schedule C self-employment income ~$20K/yr gross. Impacts SSDI and MAGI.',
    },
    'Medicare': {
        'john_impact': 'Part B premium affected by IRMAA. Currently on private disability insurance until 68.5.',
        'john_risk_level': 'medium',
        'john_action_needed': 'Plan Medicare enrollment timeline. Coordinate with disability income cutoff.',
        'tags': ['medicare', 'insurance', 'disability', 'part_b'],
        'description': 'Medicare Part A/B/D rules and enrollment timeline.',
    },
}

for entity_id, context in subject_seeds.items():
    result = upsert_entity(conn, entity_id, 'subject', context, source='seed')
    print(f"  {entity_id}: {'OK' if result else 'FAILED'}")

# ── 2. PULL EXISTING GOV RESEARCH ─────────────────────────

print("\n2. Pulling gov research cache into subject entities...")
cur.execute("""
    SELECT rule_type, rule_key, config, created_at
    FROM agent_intelligence_rules
    WHERE rule_type IN ('ssa_thresholds','irmaa_thresholds',
                        'medicaid_ny_rules','roth_ira_rules')
    ORDER BY created_at DESC
""")
gov_rows = cur.fetchall()
entity_map = {
    'ssa_thresholds': 'SSDI',
    'irmaa_thresholds': 'IRMAA',
    'medicaid_ny_rules': 'Medicaid_Lookback',
    'roth_ira_rules': 'Roth_Conversion',
}
for row in gov_rows:
    rule_type, rule_key, config, created_at = row
    entity_id = entity_map.get(rule_type)
    if entity_id and config:
        val = config if isinstance(config, dict) else {}
        upsert_entity(conn, entity_id, 'subject', {
            'current_thresholds': val,
            'thresholds_updated': created_at,
            'thresholds_source': 'agent_intelligence_rules',
        }, source='gov_research_sync')
        print(f"  Synced {rule_type} -> {entity_id}")

# ── 3. SEED ACTIVE MARKET ENTITIES ──────────────────────

print("\n3. Seeding active market entities from watchlist_symbol_master...")
cur.execute("""
    SELECT symbol, strategy_type, latest_price
    FROM watchlist_symbol_master
    WHERE in_ai_watchlist = true OR in_portfolio = true OR in_personal_watchlist = true
    ORDER BY symbol
""")
wl_rows = cur.fetchall()
for row in wl_rows:
    symbol, strategy_type, price = row
    fields = {'strategy_type': strategy_type or 'unknown'}
    if price:
        fields['current_price'] = float(price)
        fields['price_updated_at'] = datetime.now(timezone.utc)
    upsert_entity(conn, symbol, 'market', fields, source='watchlist_sync')
print(f"  Seeded {len(wl_rows)} watchlist symbols")

# ── 4. SYNC RECENT TRADE_AI_SCANS ────────────────────────

print("\n4. Syncing recent trade_ai_scans results...")
cur.execute("""
    SELECT DISTINCT ON (symbol)
        symbol, score, decision, price, rvol, float_m,
        gap_pct, change_pct, sector, industry,
        social_reddit, social_stocktwits, social_sentiment,
        mention_count, social_sources, source, screener_label,
        catalyst, catalyst_verified, scanned_at
    FROM trade_ai_scans
    WHERE scanned_at > NOW() - INTERVAL '3 days'
    AND disqualified = false
    ORDER BY symbol, scanned_at DESC
""")
scan_rows = cur.fetchall()
for row in scan_rows:
    (sym, score, decision, price, rvol, float_m, gap_pct, change_pct,
     sector, industry, reddit, stocktwits, sentiment, mentions,
     social_src, source, screener_label, catalyst, cat_verified, scanned_at) = row

    sources = []
    if source and 'screener' in str(source): sources.append('screener')
    if source and 'social' in str(source): sources.append('social')

    fields = {
        'screener_score': score,
        'screener_decision': decision,
        'screener_updated': scanned_at,
    }
    if screener_label: fields['screener_label'] = screener_label
    if price: fields['current_price'] = float(price)
    if rvol: fields['rvol'] = float(rvol)
    if float_m: fields['float_m'] = float(float_m)
    if sector: fields['sector'] = sector
    if catalyst: fields['catalyst'] = catalyst
    if cat_verified is not None: fields['catalyst_verified'] = cat_verified
    if mentions: fields['social_mentions'] = int(mentions)
    if sentiment: fields['social_sentiment'] = sentiment

    upsert_entity(conn, sym, 'market', fields, source='trade_ai_scans_sync')

print(f"  Synced {len(scan_rows)} scan results")

# ── 5. UPDATE RAG COVERAGE ────────────────────────────────

print("\n5. Updating RAG coverage counts...")
cur.execute("SELECT entity_id FROM intelligence_entities")
all_entities = [r[0] for r in cur.fetchall()]

updated_rag = 0
for entity_id in all_entities:
    cur.execute("""
        SELECT COUNT(*) FROM content_embeddings
        WHERE title ILIKE %s
    """, [f'%{entity_id}%'])
    count = cur.fetchone()[0]
    if count > 0:
        cur.execute("""
            UPDATE intelligence_entities
            SET rag_item_count = %s, rag_last_indexed = NOW()
            WHERE entity_id = %s
        """, [count, entity_id])
        updated_rag += 1

conn.commit()
print(f"  Updated RAG counts for {updated_rag} entities with coverage")

# ── 6. RECOMPUTE ALL SCORES ──────────────────────────────

print("\n6. Recomputing intelligence scores...")
from scripts.intelligence_entity_manager import _compute_intelligence_score
cur.execute("SELECT * FROM intelligence_entities")
cols = [d[0] for d in cur.description]
for row in cur.fetchall():
    record = dict(zip(cols, row))
    score, grade = _compute_intelligence_score(record, record['entity_type'])
    cur.execute("""
        UPDATE intelligence_entities
        SET intelligence_score = %s, intelligence_grade = %s
        WHERE entity_id = %s
    """, [score, grade, record['entity_id']])
conn.commit()

# ── FINAL REPORT ─────────────────────────────────────────

cur.execute("""
    SELECT entity_type, COUNT(*),
           ROUND(AVG(intelligence_score)::numeric, 1) as avg_score,
           COUNT(CASE WHEN intelligence_grade IN ('A+','A') THEN 1 END) as good
    FROM intelligence_entities
    GROUP BY entity_type
""")
print("\n=== SEED COMPLETE ===")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} entities | avg score: {row[2]} | A/A+ count: {row[3]}")

cur.execute("SELECT COUNT(*) FROM intelligence_entities")
print(f"  Total: {cur.fetchone()[0]} entities")

conn.close()
