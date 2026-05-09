"""Finviz primary discovery source."""
from .base import DiscoverySource


class FinvizSource(DiscoverySource):
    source_key = "finviz"
    default_confidence = 0.9

    def discover(self, conn, limit=50):
        """Check Finviz health and return status (actual candidates come from screener runner)."""
        try:
            from finviz_health_check import check
            result = check()
            if result["status"] == "healthy" and result.get("row_count", 0) > 0:
                return [self.normalize_candidate(
                    "FINVIZ_OK", f"Finviz healthy, {result['row_count']} rows",
                    confidence=1.0,
                    payload={"row_count": result["row_count"], "status": "healthy"}
                )]
        except Exception:
            pass
        return []
