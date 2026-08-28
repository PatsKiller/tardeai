"""A script's documented invocation must be the one that works.

The evening packet's own docstring says:

    python3 scripts/aegis_evening_packet.py

That failed with `ModuleNotFoundError: No module named 'scripts'`, and only ran
with a `PYTHONPATH=<root>` prefix. The script put `scripts/` and `scripts/lib/`
on sys.path but not ROOT itself, while modules it pulls in import themselves
absolutely -- `canonical_store_registry` does
`from scripts.lib.product_availability import ...`, which needs `scripts` to be
an importable package.

It shipped that way because the wrapper was fixed instead of the script: the cron
entry carries the PYTHONPATH prefix. The system found this itself and reported it
in an evening scan -- and per the P9.0 census reconciliation, that report is the
only agent-originated sentence the operator receives. This is the defect it found.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/aegis_evening_packet.py"
MORNING = ROOT / "scripts/aegis_morning_brief_delivery.py"


def _clean_env() -> dict:
    """No PYTHONPATH. The point is that the script must not need one."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["TRADE_AI_CI"] = "1"
    return env


@pytest.mark.parametrize("args", [[], ["--prompt"], ["--json"]])
def test_every_documented_form_imports_without_a_pythonpath(args):
    """Exercises import only -- `--prompt` needs no data and cannot write.

    Checked on returncode directly, never through a pipe: a prior gate in this
    repo reported a false pass because `$?` was `tail`'s.
    """
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--help"],
        capture_output=True, text=True, cwd=str(ROOT), env=_clean_env(), timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert "ModuleNotFoundError" not in proc.stderr


def test_root_is_on_the_path_before_its_subdirectories():
    """ROOT must be present, not just scripts/ and scripts/lib/."""
    src = SCRIPT.read_text(encoding="utf-8")
    i = src.index("ROOT = Path(__file__)")
    block = src[i:i + 900]
    assert 'sys.path.insert(0, str(ROOT))' in block, "ROOT itself must be on sys.path"
    assert 'sys.path.insert(0, str(ROOT / "scripts"))' in block


def test_the_morning_brief_has_the_same_fix():
    """Same root cause, found while verifying the evening one.

    cio_operator_renderers imports `from scripts.lib.brief_semantic_dedupe`, so
    the canonical delivery path needs PROJECT_ROOT importable. The primary import
    sits in `except ImportError` whose fallback needs the same missing root, so
    the failure surfaced as a second, more confusing ModuleNotFoundError.
    """
    src = MORNING.read_text(encoding="utf-8")
    i = src.index("PROJECT_ROOT = Path(__file__)")
    block = src[i:i + 800]
    assert "sys.path.insert(0, str(PROJECT_ROOT))" in block


def test_the_absolute_import_that_forced_this_still_exists():
    """If canonical_store_registry stops importing itself absolutely, this fix is
    no longer load-bearing and the reason for it should be revisited rather than
    silently carried."""
    reg = ROOT / "scripts/lib/canonical_store_registry.py"
    assert "from scripts.lib." in reg.read_text(encoding="utf-8")
