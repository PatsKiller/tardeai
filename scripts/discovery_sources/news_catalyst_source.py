"""News catalyst fallback discovery source."""
from .base import DiscoverySource


class NewsCatalystSource(DiscoverySource):
    source_key = "news_catalyst"
    default_confidence = 0.5

    def discover(self, conn, limit=30):
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, COUNT(*) as cnt, MAX(relevance_score) as max_rel
            FROM news_articles
            WHERE created_at > NOW() - INTERVAL '48 hours'
            AND relevance_score >= 0.5 AND symbol IS NOT NULL
            AND LENGTH(symbol) BETWEEN 1 AND 6
            GROUP BY symbol ORDER BY cnt DESC, max_rel DESC LIMIT %s
        """, (limit,))
        return [
            self.normalize_candidate(
                row[0],
                f"{row[1]} articles in 48h, max relevance {float(row[2] or 0):.2f}",
                payload={"article_count": row[1], "max_relevance": float(row[2] or 0)}
            )
            for row in cur.fetchall()
        ]
