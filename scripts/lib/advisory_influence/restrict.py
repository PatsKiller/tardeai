"""Auto-restrict influence back to SHADOW. Never auto-promotes."""
from __future__ import annotations

from typing import Any


def should_restrict(metrics: dict[str, Any], *, max_conflicts: int = 3, max_violations: int = 0) -> bool:
    if int(metrics.get("authority_violations") or 0) > max_violations:
        return True
    if int(metrics.get("canonical_truth_overrides") or 0) > max_conflicts:
        return True
    return False
