"""Base class for discovery sources."""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class DiscoverySource(ABC):
    """Base class for candidate discovery sources."""

    source_key: str = "unknown"
    default_confidence: float = 0.5

    @abstractmethod
    def discover(self, conn, limit: int = 50) -> List[Dict[str, Any]]:
        """Return normalized candidate dicts."""
        ...

    def normalize_candidate(self, symbol: str, reason: str,
                            confidence: Optional[float] = None,
                            payload: Optional[dict] = None) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "source_key": self.source_key,
            "source_confidence": confidence or self.default_confidence,
            "reason": reason,
            "raw_payload": {},
            "normalized_payload": payload or {},
        }
