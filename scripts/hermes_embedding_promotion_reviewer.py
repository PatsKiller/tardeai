#!/usr/bin/env python3
"""Hermes Embedding/Promotion Reviewer — dry-run recommendation engine.

Produces recommendations only. Does NOT embed or promote.

Usage:
    python scripts/hermes_embedding_promotion_reviewer.py
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PR = Path(__file__).resolve().parent.parent
OUT = PR / "docs" / "hermes" / "embedding_promotion_reviews"
OUT.mkdir(parents=True, exist_ok=True)

def get_db():
    import psycopg2
    db_pass = [l.split("=",1)[1] for l in (PR/".env").read_text().splitlines() if l.startswith("DB_PASSWORD=")][0]
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)

def main():
    now = datetime.now(timezone.utc)
    ds = now.strftime("%Y-%m-%d")
    conn = get_db()
    cur = conn.cursor()

    # Get all staged rows not yet embedded or promoted
    cur.execute("""
        SELECT r.id, r.symbol, r.research_type, r.confidence_score, r.source_urls_json::text,
               r.evidence_json::text, r.status,
               CASE WHEN ce.id IS NOT NULL THEN true ELSE false END AS embedded,
               CASE WHEN pa.source_id IS NOT NULL THEN true ELSE false END AS promoted
        FROM hermes_research_intelligence r
        LEFT JOIN content_embeddings ce ON ce.source_type='hermes_research' AND ce.source_id=r.id
        LEFT JOIN hermes_promotion_audit pa ON pa.source_id=r.id
        WHERE r.status = 'staged' AND r.research_type != 'research_backlog'
        ORDER BY r.confidence_score DESC
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()

    embed_recs = []
    promote_recs = []
    rejected = []

    for rid, sym, rtype, conf, urls_j, ev_j, status, embedded, promoted in rows:
        urls = json.loads(urls_j) if urls_j else []
        evidence = json.loads(ev_j) if ev_j else []
        conf = conf or 0

        # Embedding candidate: has evidence, not embedded, conf >= 0.45
        if not embedded and conf >= 0.45 and evidence:
            embed_recs.append({"id": rid, "symbol": sym, "type": rtype, "confidence": conf,
                              "has_url": bool(urls), "reason": "staged, has evidence, not embedded"})

        # Promotion candidate: conf >= 0.5, has evidence, not promoted
        if not promoted and conf >= 0.5 and evidence:
            promote_recs.append({"id": rid, "symbol": sym, "type": rtype, "confidence": conf,
                                "has_url": bool(urls), "reason": "staged, high conf, has evidence"})

        if conf < 0.3:
            rejected.append({"id": rid, "symbol": sym, "reason": f"confidence {conf} too low"})

    review = {
        "date": ds, "timestamp": now.isoformat(),
        "embedding_recommendations": embed_recs[:5],
        "promotion_recommendations": promote_recs[:5],
        "rejected": rejected,
        "total_staged_non_backlog": len(rows),
        "embeddings_created": 0, "promotions_created": 0,
    }

    (OUT / "latest_review.json").write_text(json.dumps(review, indent=2))
    lines = [f"# Embedding/Promotion Review — {ds}", "",
             f"Embedding candidates: {len(embed_recs)}", f"Promotion candidates: {len(promote_recs)}",
             f"Rejected: {len(rejected)}", "", "## Embedding Recommendations (top 5)", ""]
    for r in embed_recs[:5]:
        lines.append(f"- id={r['id']} {r['symbol'] or 'SYSTEM'} ({r['type']}) conf={r['confidence']}")
    lines += ["", "## Promotion Recommendations (top 5)", ""]
    for r in promote_recs[:5]:
        lines.append(f"- id={r['id']} {r['symbol'] or 'SYSTEM'} ({r['type']}) conf={r['confidence']}")
    lines += ["", "**Embeddings created: ZERO | Promotions created: ZERO | Recommendations only.**"]
    (OUT / f"{ds}_review.md").write_text("\n".join(lines))

    print(f"Embed recs: {len(embed_recs)}, Promote recs: {len(promote_recs)}, Rejected: {len(rejected)}")
    print("Embeddings: 0 | Promotions: 0 | Recommendations only")

if __name__ == "__main__":
    main()
