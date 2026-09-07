#!/usr/bin/env python3
"""
Hermes Staging Ingestion Script — Trade AI v12

Controlled write path for Hermes research/intelligence into hermes_* staging tables.
Defaults to --dry-run. Requires --apply for committed writes.
Writes ONLY to hermes_* tables. Rejects production table targets.

Usage:
    python scripts/hermes_staging_ingest.py --input <path.json> --table <hermes_table> [--dry-run|--apply]
    cat payload.json | python scripts/hermes_staging_ingest.py --table hermes_memory_events [--apply]
"""

import argparse
import json
import os
import sys
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

ALLOWED_TABLES = {
    "hermes_research_intelligence",
    "hermes_validation_findings",
    "hermes_alerts",
    "hermes_embedding_queue",
    "hermes_memory_events",
}

# hermes_promotion_audit is NOT writable via this script

FORBIDDEN_KEYWORDS = [
    "place_order", "submit_order", "cancel_order",
    "paper_trade_proposals", "paper_trades",
    "trade_journal", "journal_entries", "execute_trade",
    "approve_proposal", "reject_proposal", "expire_proposal",
    "mutate_proposal", "mutate_trade", "mutate_journal",
    "buy now", "sell now", "rebalance automatically",
    "change stop", "modify trade", "update journal",
]

FORBIDDEN_EXTERNAL_CLAIMS = [
    "according to latest web", "i searched", "live market",
    "real-time quote", "current price is $",
]

REQUIRED_COLUMNS = {
    "hermes_research_intelligence": [
        "hermes_agent_name", "research_type", "topic", "summary",
        "freshness_date", "model_used",
    ],
    "hermes_validation_findings": [
        "hermes_agent_name", "finding_type", "severity", "description",
    ],
    "hermes_alerts": [
        "hermes_agent_name", "alert_type", "severity", "title", "description",
    ],
    "hermes_embedding_queue": [
        "source_research_id", "title", "content",
    ],
    "hermes_memory_events": [
        "hermes_agent_name", "event_type", "topic", "content",
    ],
}

# Columns that may appear in payloads (superset across all tables)
KNOWN_COLUMNS = {
    "hermes_agent_name", "research_type", "symbol", "related_trade_id", "trade_instance_id",
    "related_proposal_id", "topic", "summary", "thesis", "thesis_type",
    "evidence_json", "confidence_score", "freshness_date", "source_urls_json",
    "model_used", "prompt_hash", "context_type_used", "status", "quality_score",
    "tags", "strategy_tags", "agent_tags",
    "finding_type", "severity", "affected_table", "affected_id",
    "description", "recommended_action", "auto_fixable",
    "alert_type", "title", "related_research_id", "related_finding_id",
    "source_research_id", "content", "source_type_target",
    "event_type", "metadata_json", "expires_at",
    "source",  # must be 'hermes'
}


def get_db_connection():
    """Connect to Trade AI database using .env credentials."""
    try:
        import psycopg2
    except ImportError:
        # Fall back to subprocess psql
        return None

    # Credentials come from the canonical loader, NOT from a path relative to this
    # file. `os.path.dirname(__file__)/../.env` resolves inside whatever tree the
    # code happens to be running from — and a RELEASE has no .env, because secrets
    # are deliberately not deployed. So every scheduled run from a release died
    # here with "DB_PASSWORD not found in .env" while the credential sat in the
    # environment and on disk.
    #
    # This was invisible for the lane's entire life: an outer DeepSeek peak guard
    # skipped the run before it ever reached a database. Fixing that guard on
    # 2026-09-06 exposed this on the very next timer fire (01:35:53).
    #
    # env_bootstrap is the house loader — tmpfs SM render first, disk .env second.
    db_pass = os.environ.get("DB_PASSWORD")
    if not db_pass:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
            from env_bootstrap import load_env  # noqa: PLC0415
            load_env()
            db_pass = os.environ.get("DB_PASSWORD")
        except Exception as exc:                       # loader absent or unreadable
            print(f"WARN: env_bootstrap unavailable ({type(exc).__name__})", file=sys.stderr)
    if not db_pass:
        print("ERROR: DB_PASSWORD not resolvable (env, tmpfs render, or .env)",
              file=sys.stderr)
        sys.exit(1)

    return psycopg2.connect(
        host='localhost', dbname='trade_ai',
        user='trade_ai', password=db_pass
    )


def validate_payload(payload, table):
    """Validate payload against schema rules. Returns (ok, errors)."""
    errors = []

    # 1. Source must be 'hermes'
    source = payload.get("source", "hermes")
    if source != "hermes":
        errors.append(f"REJECTED: source='{source}' — must be 'hermes'")

    # 2. Required columns
    for col in REQUIRED_COLUMNS.get(table, []):
        if col not in payload or payload[col] is None or payload[col] == "":
            errors.append(f"MISSING required column: {col}")

    # 3. Check for forbidden mutation language in text fields
    text_fields = " ".join(str(v) for v in payload.values() if isinstance(v, str))
    for kw in FORBIDDEN_KEYWORDS:
        if kw.lower() in text_fields.lower():
            errors.append(f"REJECTED: forbidden keyword '{kw}' found in payload text")

    # 4. Confidence score range
    cs = payload.get("confidence_score")
    if cs is not None:
        try:
            cs = float(cs)
            if cs < 0 or cs > 1:
                errors.append(f"confidence_score {cs} out of range [0, 1]")
        except (ValueError, TypeError):
            errors.append(f"confidence_score '{cs}' is not numeric")

    # 5. External unsupported claims
    for claim in FORBIDDEN_EXTERNAL_CLAIMS:
        if claim.lower() in text_fields.lower():
            errors.append(f"REJECTED: unsupported external claim '{claim}' found")

    # 6. Evidence depth (for research_intelligence)
    if table == "hermes_research_intelligence":
        ej = payload.get("evidence_json")
        if isinstance(ej, dict):
            substantive = [k for k in ej.keys() if k not in ("limitations", "source_views", "challenge_points")]
            if len(substantive) < 2:
                errors.append(f"evidence_json has only {len(substantive)} substantive keys (need >= 2)")

        # Limitations required
        lims = ej.get("limitations") if isinstance(ej, dict) else payload.get("limitations")
        if not lims or (isinstance(lims, list) and len(lims) == 0):
            errors.append("limitations array is empty or missing")

        # High confidence without enough evidence
        if cs is not None and float(cs) > 0.85:
            if isinstance(ej, dict) and len([k for k in ej.keys() if k not in ("limitations", "source_views", "challenge_points")]) < 3:
                errors.append(f"confidence_score {cs} > 0.85 but fewer than 3 evidence references")

        # Challenge points should be findings, not questions
        cps = ej.get("challenge_points") if isinstance(ej, dict) else payload.get("challenge_points")
        if isinstance(cps, list):
            question_starters = ["analyze ", "evaluate ", "assess ", "determine ", "consider "]
            for cp in cps:
                if isinstance(cp, str):
                    lower = cp.lower().strip().lstrip("*-•")
                    if any(lower.startswith(q) for q in question_starters):
                        errors.append(f"challenge_point is a question, not a finding: '{cp[:60]}...'")
                        break  # one is enough to flag

        # Source views validation
        sv = ej.get("source_views") if isinstance(ej, dict) else payload.get("source_views")
        if not sv or (isinstance(sv, list) and len(sv) == 0):
            errors.append("source_views is empty or missing")

    # 7. Secrets/credentials check
    for secret_kw in ["api_key", "password", "token", "cookie", "chat_id", "account_number", "ssn"]:
        if secret_kw in text_fields.lower():
            # Only flag if it looks like an actual value, not a discussion
            import re
            if re.search(rf'{secret_kw}\s*[=:]\s*\S+', text_fields.lower()):
                errors.append(f"REJECTED: possible credential leak: '{secret_kw}'")

    return len(errors) == 0, errors


def build_insert(table, payload):
    """Build parameterized INSERT statement. Forces source='hermes'."""
    payload["source"] = "hermes"
    payload.setdefault("status", "staged")
    payload["created_at"] = datetime.now(timezone.utc).isoformat()

    # Filter to known columns only
    cols = []
    vals = []
    placeholders = []
    for k, v in payload.items():
        if k in KNOWN_COLUMNS or k in ("source", "status", "created_at"):
            cols.append(k)
            # Convert dicts/lists to JSON strings for JSONB columns
            if isinstance(v, (dict, list)):
                vals.append(json.dumps(v))
            else:
                vals.append(v)
            placeholders.append("%s")

    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(placeholders)}) RETURNING id, created_at, status"
    return sql, vals


def main():
    parser = argparse.ArgumentParser(description="Hermes staging table ingestion")
    parser.add_argument("--input", "-i", help="Path to JSON payload file (or use stdin)")
    parser.add_argument("--table", "-t", required=True, help="Target hermes_* table")
    parser.add_argument("--apply", action="store_true", help="Commit the write (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Validate only (default)")
    args = parser.parse_args()

    # If --apply is set, disable dry-run
    dry_run = not args.apply

    # 1. Validate table name
    if args.table not in ALLOWED_TABLES:
        print(f"REJECTED: table '{args.table}' not in allowed list: {sorted(ALLOWED_TABLES)}")
        sys.exit(1)

    # 2. Reject production table names
    if not args.table.startswith("hermes_"):
        print(f"REJECTED: table '{args.table}' is not a hermes_* table")
        sys.exit(1)

    # 3. Read payload
    if args.input:
        with open(args.input) as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    print(f"{'[DRY-RUN]' if dry_run else '[APPLY]'} Target: {args.table}")
    print(f"  Payload keys: {sorted(payload.keys())}")

    # 4. Validate
    ok, errors = validate_payload(payload, args.table)
    if not ok:
        print(f"\n  VALIDATION FAILED ({len(errors)} error(s)):")
        for e in errors:
            print(f"    - {e}")
        sys.exit(1)
    print("  Validation: PASSED")

    # 5. Build SQL
    sql, vals = build_insert(args.table, payload)
    print(f"  SQL: {sql[:120]}...")
    print(f"  Values: {len(vals)} parameters")

    if dry_run:
        print("\n  DRY-RUN: No database write performed.")
        print("  Use --apply to commit.")
        sys.exit(0)

    # 6. Apply
    conn = get_db_connection()
    if conn is None:
        print("ERROR: psycopg2 not available and no fallback implemented", file=sys.stderr)
        sys.exit(1)

    try:
        cur = conn.cursor()
        cur.execute(sql, vals)
        result = cur.fetchone()
        conn.commit()
        row_id, created_at, status = result
        print(f"\n  COMMITTED: id={row_id}, created_at={created_at}, status={status}")
        print(f"  Table: {args.table}")
        print(f"  Source: hermes (enforced)")
    except Exception as e:
        conn.rollback()
        print(f"\n  ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
