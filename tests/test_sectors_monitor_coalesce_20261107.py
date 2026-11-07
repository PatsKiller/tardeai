"""ANCHOR: SECTORS_MONITOR_COALESCE_20261107 — LQ-20261107-312.

Measured on the served release 2026-11-07T21:40Z: one navigation of /v3/sectors issued two
GETs to /api/v2/sectors/monitor with the same millisecond cache-buster (requests #23 and #25
of that load). The route takes 4-7 s per call, so the page computed the read model twice.

Two independent fixes, each asserted here:

1. Server — the route joins the single-flight allowlist (scripts/lib/request_coalesce.py), so
   two identical concurrent GETs share one computation. This is what covers a second tab, a
   retry and a headless validator, not only the one page we measured.
2. Frontend — the page hands its payload to the board it renders
   (src/pages/SectorsHub.tsx -> ActionableSectorDecisionBoard), so the second request is not
   issued at all. The board's decision is a pure function with its own test
   (src/lib/sectorMonitorSource.test.ts); the wiring is asserted here because the Python suite
   is the only place both sides of the contract are visible.

Hermetic: no server, no browser, no database, no network.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from scripts.lib import request_coalesce as rc

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "command-center-v3" / "src"
ROUTE = "/api/v2/sectors/monitor"


def test_the_route_is_on_the_single_flight_allowlist():
    assert ROUTE in rc.DEFAULT_COALESCE_PATHS


def test_the_browser_cache_buster_does_not_split_the_key():
    """The two requests we measured differed only by the `_=` stamp; they must share a key."""
    saved = rc.COALESCE_PATHS
    rc.COALESCE_PATHS = frozenset(rc.DEFAULT_COALESCE_PATHS)
    try:
        plain = rc.request_key(ROUTE, {})
        stamped = rc.request_key(ROUTE, {"_": "1794087612518"})
        other_stamp = rc.request_key(ROUTE, {"_": "1794087612599"})
        assert plain is not None
        assert stamped == plain == other_stamp
        # A real parameter still separates the computation.
        assert rc.request_key(ROUTE, {"horizon": "M"}) != plain
    finally:
        rc.COALESCE_PATHS = saved


def test_two_concurrent_reads_compute_once():
    saved = rc.COALESCE_PATHS
    rc.COALESCE_PATHS = frozenset(rc.DEFAULT_COALESCE_PATHS)
    try:
        key = rc.request_key(ROUTE, {"_": "1794087612518"})
        assert key is not None
        co = rc.Coalescer(ttl=0.5, wait_s=5)
        calls: list[int] = []
        seen: list[int] = []

        def slow() -> int:
            calls.append(1)
            time.sleep(0.25)
            return 200

        def one() -> None:
            seen.append(rc.coalesce_get(ROUTE, {"_": "1794087612518"}, slow, coalescer=co))

        threads = [threading.Thread(target=one) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert calls == [1], "four concurrent identical GETs must compute the read model once"
        assert seen == [200, 200, 200, 200]
        assert co.stats["computed"] == 1
    finally:
        rc.COALESCE_PATHS = saved


def test_the_frontend_requests_the_exact_allowlisted_path():
    """A rename on either side would silently take the route off the allowlist again."""
    for rel in ("pages/SectorsHub.tsx", "components/rotation/ActionableSectorDecisionBoard.tsx"):
        source = (APP / rel).read_text()
        assert f"'{ROUTE}'" in source, f"{rel} no longer requests {ROUTE}"
        assert ROUTE in rc.DEFAULT_COALESCE_PATHS


def test_the_page_hands_its_payload_to_the_board():
    """The dedupe is the wiring: the hub passes its own read, and the board stands down."""
    hub = (APP / "pages" / "SectorsHub.tsx").read_text()
    assert "monitor={data}" in hub, "SectorsHub must pass its monitor payload to the brief"
    assert "onRefreshMonitor={refetch}" in hub, "the brief must refresh the page's own fetch"

    board = (APP / "components" / "rotation" / "ActionableSectorDecisionBoard.tsx").read_text()
    assert "shouldFetchSectorMonitor(monitor)" in board, (
        "the board must gate its own fetch on whether it was handed a payload"
    )
    assert "sectorMonitorPayload(monitor, ownMonitor)" in board, (
        "the board must render the supplied payload, not only its own fetch"
    )
