"""FQ-088 (HQ-04): Home consumes the list as-of and each row's quote age; a stale or missing quote is never current.

The behaviour lives in TypeScript, so this gate RUNS that test with node instead of mirroring it in Python — a copy
would prove the copy. Registered as the CI gate's file because the shard runner executes gate files with pytest and
cannot collect a `.mjs` file.

Hermetic: node with --experimental-strip-types, no browser, no network, no data.

ANCHOR: OPPORTUNITY_QUOTE_AGE_20261104
"""
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEST_FILE = REPO / "apps/command-center-v3/src/lib/opportunityQuoteAge.test.mjs"


def test_the_typescript_quote_age_test_passes():
    node = shutil.which("node")
    assert node, "node is not on PATH: the quote-age behaviour cannot be verified (a skip would pass the gate silently)"
    assert TEST_FILE.is_file(), f"the quote-age test is missing: {TEST_FILE}"
    proc = subprocess.run(
        [node, "--experimental-strip-types", str(TEST_FILE)],
        capture_output=True, text=True, timeout=180, cwd=str(REPO),
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
    )
    assert proc.returncode == 0, f"the quote-age test failed:\n{proc.stdout}\n{proc.stderr}"
