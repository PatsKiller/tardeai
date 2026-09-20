"""AI Analyst cache freshness — aligned to the weekday-only producer.

`portfolio_orchestrator.py` (cron ``15 7 * * 1-5``) is the only scheduled
writer of ``ai_analysis_cache.json``. A 48h wall-clock SLA marks every
Sunday morning WARN against a healthy Friday 07:15 cache (≈48.3h). That is
a detector keyed on the wrong bound: the producer does not run on weekends.

72h covers Fri→Mon morning without papering over a missed Monday run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Mon-Fri producer; Fri 07:15 → Mon 07:15 ≈ 72h.
AI_ANALYST_STALE_AFTER_HOURS = 72


def ai_analyst_is_stale(
    generated_at: Any,
    *,
    now: datetime | None = None,
    stale_after_hours: float = AI_ANALYST_STALE_AFTER_HOURS,
) -> bool:
    """Return True when ``generated_at`` is missing or older than the SLA."""
    if not generated_at:
        return True
    try:
        gen_dt = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except Exception:
        return True
    clock = now or datetime.now()
    if clock.tzinfo is not None:
        clock = clock.replace(tzinfo=None)
    return (clock - gen_dt).total_seconds() > float(stale_after_hours) * 3600
