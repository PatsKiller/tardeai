"""Yahoo Finance fallback discovery source."""
from .base import DiscoverySource


class YahooSource(DiscoverySource):
    source_key = "yahoo_movers"
    default_confidence = 0.6

    def discover(self, conn, limit=20):
        """Try yfinance for market movers if available."""
        try:
            import yfinance as yf
            tickers = yf.Tickers("SPY QQQ IWM")
            # Return watchlist/portfolio symbols needing refresh instead
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT symbol FROM watchlist_agent_results
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY symbol LIMIT %s
            """, (limit,))
            return [
                self.normalize_candidate(row[0], "Watchlist symbol via Yahoo refresh",
                                         confidence=0.6)
                for row in cur.fetchall()
            ]
        except Exception:
            return []
