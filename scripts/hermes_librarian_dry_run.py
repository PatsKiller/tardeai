#!/usr/bin/env python3
"""Hermes Librarian Dry-Run — read-only curation analysis.

Usage:
    python scripts/hermes_librarian_dry_run.py

Safety:
    - Read-only DB queries only
    - No DB writes, no embeddings, no promotions
    - File output only to docs/hermes/phase21_librarian_dryrun/
"""

import json

# --- .env autoload (no hardcoded secrets) ---
import os as _os
if not _os.getenv("DB_PASSWORD"):
    try:
        from pathlib import Path as _P
        for _l in (_P(__file__).resolve().parent.parent / ".env").read_text().splitlines():
            if _l.startswith("DB_PASSWORD="): _os.environ["DB_PASSWORD"] = _l.split("=",1)[1].strip()
    except Exception: pass
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# DB connection
import psycopg2

DB_PARAMS = {
    "host": "localhost",
    "dbname": "trade_ai",
    "user": "trade_ai",
    "password": os.environ.get("DB_PASSWORD", ""),
}

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "hermes" / "phase21_librarian_dryrun"
OUT_DIR.mkdir(parents=True, exist_ok=True)

STALE_DAYS = 90
LOW_CONFIDENCE = 0.3


def fetch_rows():
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, research_type, status, confidence_score,
               source_urls_json::text, evidence_json::text, summary, thesis,
               freshness_date, tags, created_at, topic
        FROM hermes_research_intelligence ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def fetch_cache():
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()
    cur.execute("SELECT section, metadata::text FROM llm_intelligence_cache WHERE section LIKE 'hermes_%'")
    result = {r[0]: json.loads(r[1]) for r in cur.fetchall()}
    cur.close()
    conn.close()
    return result


def run_checks(rows, cache):
    findings = []
    duplicates = []
    stale_weak = []
    backlog = []
    embed_candidates = []
    reject_candidates = []

    now = datetime.now(timezone.utc)
    seen_urls = {}
    seen_topics = {}

    for r in rows:
        rid = r["id"]
        symbol = r["symbol"] or "SYSTEM"
        rtype = r["research_type"]
        status = r["status"]
        conf = r["confidence_score"] or 0
        urls = json.loads(r["source_urls_json"]) if r["source_urls_json"] else []
        evidence = json.loads(r["evidence_json"]) if r["evidence_json"] else []
        summary = r["summary"] or ""
        thesis = r["thesis"] or ""
        freshness = r["freshness_date"]
        tags = r["tags"] or []
        topic = r["topic"] or ""

        row_findings = []

        # DUP-1: duplicate URL
        for url in urls:
            if url in seen_urls:
                f = {"check": "DUP-1", "severity": "medium", "row_id": rid, "symbol": symbol,
                     "detail": f"URL duplicate with row {seen_urls[url]}: {url[:80]}"}
                findings.append(f)
                row_findings.append(f)
                duplicates.append(f)
            else:
                seen_urls[url] = rid

        # DUP-1b: duplicate topic/symbol combo
        key = f"{symbol}:{rtype}"
        if key in seen_topics and rtype != "source_discovery":
            f = {"check": "DUP-1b", "severity": "info", "row_id": rid, "symbol": symbol,
                 "detail": f"Same symbol+type as row {seen_topics[key]}"}
            findings.append(f)
            row_findings.append(f)
        seen_topics.setdefault(key, rid)

        # STALE-1: stale source
        if freshness:
            age = (now.date() - freshness).days if hasattr(freshness, 'days') else (now.date() - freshness).days
            if age > STALE_DAYS:
                f = {"check": "STALE-1", "severity": "medium", "row_id": rid, "symbol": symbol,
                     "detail": f"Freshness date {freshness} is {age} days old"}
                findings.append(f)
                stale_weak.append(f)

        # QUAL-1: low confidence
        if conf < LOW_CONFIDENCE:
            f = {"check": "QUAL-1", "severity": "high", "row_id": rid, "symbol": symbol,
                 "detail": f"Confidence {conf} below threshold {LOW_CONFIDENCE}"}
            findings.append(f)
            stale_weak.append(f)

        # EVID-1: missing evidence
        if not evidence or evidence == []:
            f = {"check": "EVID-1", "severity": "medium", "row_id": rid, "symbol": symbol,
                 "detail": "Empty evidence_json"}
            findings.append(f)
            row_findings.append(f)

        # URL-1: missing URL for source_discovery
        if rtype == "source_discovery" and not urls:
            f = {"check": "URL-1", "severity": "high", "row_id": rid, "symbol": symbol,
                 "detail": "Source discovery row has no source URL"}
            findings.append(f)

        # VAGUE-1: vague summary
        vague_words = ["potentially", "possibly", "might", "could consider", "may want to"]
        if any(w in summary.lower() for w in vague_words) and not thesis:
            f = {"check": "VAGUE-1", "severity": "medium", "row_id": rid, "symbol": symbol,
                 "detail": "Summary contains vague language without supporting thesis"}
            findings.append(f)

        # Curation decisions
        # EMB-1: embedding candidate (high quality, unique, not yet embedded)
        section_key = f"hermes_{rtype}_{symbol}"
        already_in_cache = section_key in cache
        if status == "staged" and conf >= 0.45 and evidence and not already_in_cache:
            f = {"check": "EMB-1", "severity": "info", "row_id": rid, "symbol": symbol,
                 "detail": f"Staged, conf={conf}, has evidence, not in cache — embedding candidate"}
            embed_candidates.append(f)

        # REJ-1: rejection candidate
        if conf < LOW_CONFIDENCE and status == "staged":
            f = {"check": "REJ-1", "severity": "medium", "row_id": rid, "symbol": symbol,
                 "detail": f"Low confidence ({conf}), staged — candidate for rejection/archive"}
            reject_candidates.append(f)

        # BKL-1: backlog candidate (missing evidence or weak)
        if status == "staged" and (not evidence or evidence == [] or conf < 0.5):
            f = {"check": "BKL-1", "severity": "medium", "row_id": rid, "symbol": symbol,
                 "detail": f"Staged with weak evidence or low confidence — needs research"}
            backlog.append(f)

        # PRO-1: promotion review candidate
        if status == "staged" and conf >= 0.5 and evidence and len(evidence) > 0:
            f = {"check": "PRO-1", "severity": "info", "row_id": rid, "symbol": symbol,
                 "detail": f"Staged, conf={conf}, has evidence — promotion review candidate"}
            findings.append(f)

    return findings, duplicates, stale_weak, backlog, embed_candidates, reject_candidates


def main():
    print("Hermes Librarian Dry-Run")
    print("========================")
    print("Reading DB (read-only)...")

    rows = fetch_rows()
    cache = fetch_cache()

    print(f"Rows: {len(rows)}, Cache sections: {len(cache)}")

    findings, dups, stale, backlog, embeds, rejects = run_checks(rows, cache)

    # Write outputs
    for name, data in [
        ("librarian_findings.json", findings),
        ("duplicate_sources.json", dups),
        ("stale_or_weak_sources.json", stale),
        ("research_backlog_candidates.json", backlog),
        ("embedding_candidates_dryrun.json", embeds),
        ("rejected_or_archive_candidates.json", rejects),
    ]:
        (OUT_DIR / name).write_text(json.dumps(data, indent=2, default=str))

    # Summary
    summary = [
        "# Hermes Librarian Dry-Run Summary",
        "",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Rows reviewed:** {len(rows)}",
        f"**Cache sections:** {len(cache)}",
        "",
        "---",
        "",
        f"**Total findings:** {len(findings)}",
        f"**Duplicates:** {len(dups)}",
        f"**Stale/weak:** {len(stale)}",
        f"**Research backlog candidates:** {len(backlog)}",
        f"**Embedding candidates:** {len(embeds)}",
        f"**Rejection/archive candidates:** {len(rejects)}",
        "",
        "**DB writes: ZERO | Embeddings: ZERO | Promotions: ZERO**",
        "",
        "---",
        "",
    ]

    by_check = {}
    for f in findings:
        by_check.setdefault(f["check"], []).append(f)

    for check, items in sorted(by_check.items()):
        summary.append(f"## {check} ({len(items)} findings)")
        for item in items:
            summary.append(f"- Row {item['row_id']} ({item['symbol']}): {item['detail']}")
        summary.append("")

    (OUT_DIR / "dry_run_summary.md").write_text("\n".join(summary))

    print(f"\nFindings: {len(findings)}")
    print(f"Duplicates: {len(dups)}")
    print(f"Stale/weak: {len(stale)}")
    print(f"Backlog candidates: {len(backlog)}")
    print(f"Embedding candidates: {len(embeds)}")
    print(f"Rejection candidates: {len(rejects)}")
    print(f"\nOutput: {OUT_DIR}/")
    print("DB writes: 0 | Embeddings: 0 | Promotions: 0")


if __name__ == "__main__":
    main()
