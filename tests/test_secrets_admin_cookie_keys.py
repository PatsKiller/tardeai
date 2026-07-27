"""FINVIZ_COOKIE key naming + write-format gates (no real SM / no host secrets).

After PR #211, set_secret rejects truncated cookies (len < 50 or missing .ASPXAUTH=).
These tests cover format rules via validate_finviz_cookie_value and key-name allowlists
without calling Bitwarden or mutating production .env.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "secrets"))

import secrets_admin  # noqa: E402
from resolve_secret import validate_finviz_cookie_value  # noqa: E402

# Synthetic placeholders only — never real session cookies
_TRUNCATED = "chartsTheme=dark;.ASPXAUTH=abc"  # len 30, historically invalid for Elite CSV
_VALID_SYNTHETIC = "chartsTheme=dark;.ASPXAUTH=" + ("x" * 60)  # len >= 50 + ASPXAUTH


def test_finviz_cookie_key_name_allowed():
    """FINVIZ_COOKIE must be a known / allowlisted secret key name (suffix + KNOWN)."""
    assert "FINVIZ_COOKIE" in secrets_admin.KNOWN
    assert secrets_admin.KEY_RE.match("FINVIZ_COOKIE")
    assert "FINVIZ_COOKIE".endswith(secrets_admin.SECRET_SUFFIXES)
    # Synthetic full-shape cookie passes the format gate used before SM upsert
    validate_finviz_cookie_value(_VALID_SYNTHETIC)


def test_finviz_cookie_rejects_truncated():
    """Truncated cookie (len 30) is rejected; error must not echo the secret value."""
    with pytest.raises(ValueError) as ei:
        validate_finviz_cookie_value(_TRUNCATED)
    msg = str(ei.value)
    assert "50" in msg or "too short" in msg.lower() or "short" in msg.lower()
    # Never echo the full cookie value into the exception
    assert _TRUNCATED not in msg
    assert "chartsTheme=dark;.ASPXAUTH=abc" not in msg


def test_finviz_cookie_rejects_missing_aspxauth():
    long_no_auth = "y" * 60
    with pytest.raises(ValueError) as ei:
        validate_finviz_cookie_value(long_no_auth)
    msg = str(ei.value)
    assert "ASPXAUTH" in msg
    assert long_no_auth not in msg


def test_finviz_cookie_accepts_min_shape():
    validate_finviz_cookie_value(_VALID_SYNTHETIC)


def test_set_secret_rejects_truncated_before_sm(monkeypatch):
    """set_secret must fail closed on short cookie without calling Bitwarden."""
    called = {"sm": 0}

    def _no_sm(*_a, **_k):
        called["sm"] += 1
        raise AssertionError("SM upsert must not run for rejected FINVIZ_COOKIE")

    monkeypatch.setattr(secrets_admin, "_sm_upsert", _no_sm)
    with pytest.raises(ValueError) as ei:
        secrets_admin.set_secret("FINVIZ_COOKIE", _TRUNCATED, actor="test")
    assert called["sm"] == 0
    msg = str(ei.value)
    assert "50" in msg or "short" in msg.lower() or "ASPXAUTH" in msg or "rejected" in msg.lower()
    assert _TRUNCATED not in msg
