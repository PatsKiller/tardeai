"""Secrets modal must accept *_COOKIE keys (FINVIZ_COOKIE, etc.)."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import secrets_admin


def test_finviz_cookie_key_name_allowed():
    # Must not raise suffix error; use a throwaway value and restore .env after.
    env_path = PROJECT_ROOT / ".env"
    before = env_path.read_text() if env_path.exists() else ""
    try:
        res = secrets_admin.set_secret("FINVIZ_COOKIE", "chartsTheme=dark;.ASPXAUTH=abc")
        assert res["ok"] is True
        assert res["key"] == "FINVIZ_COOKIE"
        line = [l for l in env_path.read_text().splitlines() if l.startswith("FINVIZ_COOKIE=")][0]
        assert line.startswith("FINVIZ_COOKIE='") and line.endswith("'")
    finally:
        env_path.write_text(before)