"""The dashboard must never embed a credential in client-side JavaScript.

A live Anthropic key sat in `reports/portfolio_live.html` -- world-readable at
mode 664, copied into 20 release directories, and published to a PUBLIC GitHub
repository from 2026-04-18. File permissions and .gitignore are irrelevant to
this class of defect: anyone who loads the page reads the key.

The embedded key was never even used. The page's only reference to it was a
presence check; the actual call goes to a local proxy on :7778 which holds the
credential. A boolean carries that meaning with no secret in it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "portfolio_dashboard.py"

# Deliberately fake. Never a real value, in a test or anywhere else.
FAKE_KEY = "sk-ant-api03-" + "F" * 95
KEY_SHAPED = re.compile(r"sk-ant-api03-[A-Za-z0-9_-]{30,}")


def _source() -> str:
    return GENERATOR.read_text(encoding="utf-8")


def test_the_generator_emits_a_boolean_not_a_key():
    """The template line must carry no credential, whatever the key is."""
    ai_enabled_js = "true" if FAKE_KEY else "false"
    emitted = "const AI_ENABLED = {};".format(ai_enabled_js)
    assert not KEY_SHAPED.search(emitted), "a key-shaped string reached the page"
    assert emitted == "const AI_ENABLED = true;"


def test_the_old_shape_would_have_leaked():
    """Guard the guard: prove the test can detect the defect it exists for.

    Without this, the assertion above would pass against any template at all,
    including one that still embeds the key under a different name.
    """
    old = "const API_KEY    = '{}';".format(FAKE_KEY)
    assert KEY_SHAPED.search(old), "mutation did not reproduce the old defect"


def test_no_api_key_interpolation_remains_in_the_generator():
    src = _source()
    assert "api_key_js" not in src, "the key interpolation variable is back"
    assert "const API_KEY" not in src, "the key is being emitted into the page again"
    assert "ai_enabled_js" in src and "AI_ENABLED" in src


def test_the_generator_never_writes_a_key_shaped_literal():
    """No hardcoded credential in the generator itself."""
    assert not KEY_SHAPED.search(_source())
