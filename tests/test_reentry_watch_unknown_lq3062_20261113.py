"""LQ-20261113-3062 (review 3051 A3): the Re-Entry rotation workspace shows a watchlist 503 as UNKNOWN with its
retry hint, never as an empty watch row.

/api/v2/watchlist/items is a StaleServe route; its first read after a night is HTTP 503 ``build_deferred`` with
``retry_after_sec``. ReEntryRotationWorkspace.tsx read that body with a raw fetch and no status check, found no
``items``, wrote nothing and rendered ``watchMap[symbol] ?? {}``: empty, no retry. The read now goes through
``reentryWatchFetch.ts``, which turns any non-OK answer into an UNKNOWN entry naming the chunk's symbols, the HTTP
status, the server's reason and its retry hint; the page shows a WATCHLIST DATA UNKNOWN banner and retries.

This gate RUNS the TypeScript test with node (a Python copy of the logic would prove the copy) and pins the
component's wiring. The rendered behaviour is pinned in Chromium by
``apps/command-center-v3/src/components/reentry/reentryWatchUnknown.browser.test.mjs`` (needs node_modules).
Hermetic: synthetic responses, no browser here, no network, no data.
"""
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIR = REPO / "apps/command-center-v3/src/components/reentry"
TEST_FILE = DIR / "reentryWatchFetch.test.ts"
COMPONENT = DIR / "ReEntryRotationWorkspace.tsx"


def test_the_typescript_503_unknown_test_passes():
    node = shutil.which("node")
    assert node, "node is not on PATH: the 503 -> UNKNOWN behaviour cannot be verified (a skip would pass silently)"
    assert TEST_FILE.is_file(), f"the 503 -> UNKNOWN test is missing: {TEST_FILE}"
    proc = subprocess.run(
        [node, "--experimental-strip-types", str(TEST_FILE)],
        capture_output=True, text=True, timeout=120, cwd=str(REPO),
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
    )
    assert proc.returncode == 0, f"the 503 -> UNKNOWN test failed:\n{proc.stdout}\n{proc.stderr}"
    assert "[PASS] carries HTTP 503" in proc.stdout and "0 failed" in proc.stdout


def test_the_workspace_no_longer_reads_the_watchlist_with_a_raw_unchecked_fetch():
    src = COMPONENT.read_text()
    assert "fetch(`/api/v2/watchlist/items" not in src, "the raw watchlist fetch (no status check) is back"
    assert re.search(r"import \{[^}]*\bloadWatchMap\b[^}]*\} from './reentryWatchFetch'", src)
    assert "loadWatchMap(" in src


def test_the_workspace_renders_the_unknown_banner_and_retries_on_the_hint():
    src = COMPONENT.read_text()
    assert 'data-testid="reentry-watch-unknown"' in src and "WATCHLIST DATA UNKNOWN" in src
    assert "watchUnknownMessage(" in src
    assert "retryDelaySec(" in src and "window.setTimeout(" in src and "MAX_RETRIES" in src
    assert "watchUnknown: watchUnknownSet.has(" in src            # both rotation sides are marked UNKNOWN
