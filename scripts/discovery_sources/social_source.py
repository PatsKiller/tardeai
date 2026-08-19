"""Social/scalp fallback discovery source."""
from .base import DiscoverySource


class SocialSource(DiscoverySource):
    source_key = "social_scalp"
    default_confidence = 0.4

    def discover(self, conn, limit=20):
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT DISTINCT symbol FROM trade_ai_scans
                WHERE run_date >= CURRENT_DATE - 2
                AND source ILIKE '%%social%%'
                AND symbol IS NOT NULL
                ORDER BY symbol LIMIT %s
            """, (limit,))
            return [
                self.normalize_candidate(row[0], "Recent social/scalp scan candidate")
                for row in cur.fetchall()
            ]
        except Exception:
            return []
