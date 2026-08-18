"""Run a callable with a hard wall-clock bound.

ThreadPoolExecutor context-manager shutdown(wait=True) is load-bearing-wrong:
a 3s timeout followed by waiting for a hung worker is how /api/v3/agent-maturity
still blocked the desk for 8s+. Always shutdown(wait=False).
"""
from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def run_bounded(fn: Callable[..., T], *args: Any, timeout_s: float = 3.0, **kwargs: Any) -> T:
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, *args, **kwargs).result(timeout=timeout_s)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
