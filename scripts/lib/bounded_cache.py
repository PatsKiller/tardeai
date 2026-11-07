"""LQ-20261107-202: a size cap for module-level dict caches keyed by request or symbol input."""
from __future__ import annotations

from typing import Any, MutableMapping


def cap_dict(cache: MutableMapping[Any, Any], max_entries: int) -> int:
    """Evict oldest-inserted entries until ``len(cache) <= max_entries``. Returns how many were evicted.

    Call under the cache's own lock, right after a write. A re-written key moves to the newest slot
    only if the caller pops it first; plain dicts keep first-insert order, which is enough for a cap.
    """
    evicted = 0
    while len(cache) > max_entries:
        try:
            cache.pop(next(iter(cache)))
        except (StopIteration, KeyError):
            break
        evicted += 1
    return evicted
