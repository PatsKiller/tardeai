"""Incubator fallback discovery source."""
from .base import DiscoverySource


class IncubatorSource(DiscoverySource):
    source_key = "incubator"
    default_confidence = 0.7

    def discover(self, conn, limit=50):
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, latest_score, strategy_id, status
            FROM incubator_universe WHERE status='ACTIVE'
            ORDER BY latest_score DESC NULLS LAST LIMIT %s
        """, (limit,))
        return [
            self.normalize_candidate(
                row[0],
                f"Active incubator, score={row[1]}, strategy={row[2]}",
                payload={"score": float(row[1]) if row[1] else 0, "strategy": row[2]}
            )
            for row in cur.fetchall()
        ]
