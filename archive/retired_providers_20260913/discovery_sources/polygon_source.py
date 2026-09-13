"""Polygon.io fallback discovery source."""
import os
from .base import DiscoverySource


class PolygonSource(DiscoverySource):
    source_key = "polygon"
    default_confidence = 0.6

    def discover(self, conn, limit=20):
        """Try Polygon market movers if API key exists."""
        api_key = os.getenv("POLYGON_API_KEY", "")
        if not api_key:
            return []
        try:
            import urllib.request, json
            url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers?apiKey={api_key}"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                return [
                    self.normalize_candidate(
                        t["ticker"], f"Polygon gainer, change={t.get('todaysChangePerc', 0):.1f}%",
                        payload={"change_pct": t.get("todaysChangePerc", 0)}
                    )
                    for t in data.get("tickers", [])[:limit]
                ]
        except Exception:
            return []
