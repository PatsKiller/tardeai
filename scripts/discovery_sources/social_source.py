"""Social/scalp fallback discovery source."""
from .base import DiscoverySource


class SocialSource(DiscoverySource):
    source_key = "social_scalp"
    default_confidence = 0.4

    def discover(self, conn, limit=20):
        cur = conn.cursor()
        try:
            # ``CURRENT_DATE - 2`` excluded Friday's scans at the Monday 06:15 run
            # (the scanner's first Monday cycle is 06:00), so this source returned
            # 0 candidates every Monday -- the log shows every fifth run empty --
            # and the health ledger escalated "social_scalp failing" each week.
            # The window now reaches back to the most recent prior session that
            # has social scans, whatever the calendar did in between.
            cur.execute("""
                SELECT DISTINCT symbol FROM trade_ai_scans
                WHERE run_date >= LEAST(
                        CURRENT_DATE - 2,
                        COALESCE((SELECT max(run_date) FROM trade_ai_scans
                                  WHERE run_date < CURRENT_DATE AND source ILIKE '%%social%%'),
                                 CURRENT_DATE - 2))
                AND source ILIKE '%%social%%'
                AND symbol IS NOT NULL
                ORDER BY symbol LIMIT %s
            """, (limit,))
            return [
                self.normalize_candidate(row[0], "Recent social/scalp scan candidate")
                for row in cur.fetchall()
            ]
        except Exception as exc:
            # An error is not "no candidates": say so, so the health ledger's
            # "0 candidates" can be told apart from a broken query.
            print(f"  [discovery] social_scalp query failed: {type(exc).__name__}: {exc}")
            try:
                conn.rollback()
            except Exception:
                pass
            return []
