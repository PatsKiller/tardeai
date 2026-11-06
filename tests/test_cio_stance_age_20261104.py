"""FQ-098: a stale CIO stance is named stale with its evidence date and never rendered as current advice.

The behaviour lives in TypeScript, so this gate test RUNS the TypeScript test with node rather than mirroring the
logic in Python — a copy would prove the copy. Registered as the CI gate's file because the shard runner executes
gate files with pytest and cannot collect a `.ts` file.

Hermetic: node with `--experimental-strip-types`, no browser, no network, no data.

ANCHOR: CIO_STANCE_AGE_20261104
"""
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEST_FILE = REPO / "apps/command-center-v3/src/lib/cioStanceAge.test.ts"


def test_the_typescript_stance_test_passes():
    node = shutil.which("node")
    assert node, "node is not on PATH: the stance behaviour cannot be verified (a skip would silently pass the gate)"
    assert TEST_FILE.is_file(), f"the stance test is missing: {TEST_FILE}"
    proc = subprocess.run(
        [node, "--experimental-strip-types", str(TEST_FILE)],
        capture_output=True, text=True, timeout=120, cwd=str(REPO),
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
    )
    assert proc.returncode == 0, f"the stance test failed:\n{proc.stdout}\n{proc.stderr}"
