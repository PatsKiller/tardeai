"""Assertion failures never print os.environ (2026-10-20).

A failing `assert "DB_PASSWORD" not in os.environ` rendered the whole environment, live broker secrets included, into
a CI log. tests/conftest.py pytest_assertrepr_compare now explains any comparison with os.environ by name only.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANARY = "redaction-canary-7f3e9b1c-value"


def _run_failing(tmp_path, body: str) -> str:
    t = ROOT / "tests" / f"_tmp_env_redaction_{os.getpid()}_test.py"
    t.write_text("import os\n\ndef test_leak():\n" + body)
    try:
        # Minimal env: if redaction ever regresses, this test's own output must not carry real host secrets.
        keep = ("PATH", "HOME", "LANG", "TMPDIR", "VIRTUAL_ENV")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env.update(REDACTION_CANARY_SECRET=CANARY, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-vv", str(t)],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    finally:
        t.unlink()
    return r.stdout + r.stderr


def test_not_in_environ_failure_is_redacted(tmp_path):
    out = _run_failing(tmp_path, '    assert "REDACTION_CANARY_SECRET" not in os.environ\n')
    failed, redacted, leaked = "1 failed" in out, "os.environ contents redacted" in out, CANARY in out
    assert failed
    assert redacted
    assert not leaked


def test_in_environ_failure_is_redacted(tmp_path):
    out = _run_failing(tmp_path, '    assert "NO_SUCH_VAR_20261020" in os.environ\n')
    failed, leaked = "1 failed" in out, CANARY in out
    assert failed
    assert not leaked
