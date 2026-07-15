#!/usr/bin/env python3
"""Schwab HTTP access-token refresh — operator approval gate + refresh implementation."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SRC = (ROOT / "scripts" / "schwab_token_manager.py").read_text()


def test_refresh_http_gated_in_read_oauth_token():
    assert "elif not _http_refresh_approved():" in SRC
    assert "do NOT hand back a stale token for refresh" in SRC


def test_get_access_token_fails_closed_without_approval():
    assert "if not _http_refresh_approved():" in SRC
    assert "do NOT mark degraded — waiting for operator approval" in SRC


def test_refresh_access_token_uses_grant_type_refresh_token():
    block = SRC[SRC.index("def _refresh_access_token"):SRC.index("def reauth_url")]
    assert '"grant_type": "refresh_token"' in block
    assert "seed_token(account_key" in block
    assert "raise RuntimeError" not in block
    assert "NOT_PROVEN" not in block


def test_approve_and_revoke_use_typed_phrases():
    assert 'want = f"APPROVE SCHWAB HTTP REFRESH {today}"' in SRC
    assert 'confirm != "REVOKE SCHWAB HTTP REFRESH"' in SRC
    assert "schwab_http_refresh_approved" in SRC


def test_cli_exposes_approval_commands():
    assert '"approve-refresh-http"' in SRC
    assert '"revoke-refresh-http"' in SRC
    assert '"refresh-http-status"' in SRC


def test_approve_http_refresh_rejects_wrong_phrase():
    import schwab_token_manager as stm
    with mock.patch.object(stm, "_have_app_creds", return_value=True):
        res = stm.approve_http_refresh("WRONG PHRASE")
    assert res["ok"] is False
    assert "typed confirmation mismatch" in res["error"]


def test_revoke_http_refresh_rejects_wrong_phrase():
    import schwab_token_manager as stm
    res = stm.revoke_http_refresh("WRONG")
    assert res["ok"] is False


def test_http_refresh_approved_reads_system_controls():
    import schwab_token_manager as stm

    class _Cur:
        def execute(self, *a, **k):
            self._sql = a[0] if a else ""
        def fetchone(self):
            if "SELECT value FROM system_controls" in getattr(self, "_sql", ""):
                return ("true",)
            return None

    class _Conn:
        def cursor(self):
            return _Cur()

    with mock.patch.object(stm, "_conn", return_value=_Conn()):
        assert stm._http_refresh_approved() is True


def test_refresh_access_token_blocked_when_not_approved():
    import schwab_token_manager as stm
    with mock.patch.object(stm, "_http_refresh_approved", return_value=False):
        assert stm._refresh_access_token("schwab_taxable", "schwab", "live") is None


def test_refresh_access_token_persists_on_success():
    import schwab_token_manager as stm

    now = datetime.now(timezone.utc)
    rt_enc = "enc_rt"
    at_enc = "enc_at"

    class _Cur:
        def __init__(self):
            self.calls = []
        def execute(self, *a, **k):
            self.calls.append(a)
        def fetchone(self):
            return (at_enc, rt_enc, now - timedelta(minutes=20), now + timedelta(days=5), False)

    class _Conn:
        def __init__(self):
            self._cur = _Cur()
        def cursor(self):
            return self._cur
        def commit(self):
            pass

    fake_resp = mock.Mock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_in": 1800,
    }

    with mock.patch.object(stm, "_http_refresh_approved", return_value=True), \
         mock.patch.object(stm, "_have_app_creds", return_value=True), \
         mock.patch.object(stm, "_acquire_refresh_lock", return_value=True), \
         mock.patch.object(stm, "_release_refresh_lock"), \
         mock.patch.object(stm, "_conn", return_value=_Conn()), \
         mock.patch.object(stm, "_dec", side_effect=lambda x: {"enc_rt": "old_rt", "enc_at": "old_at"}.get(x, x)), \
         mock.patch.object(stm, "seed_token", return_value={"ok": True}) as seed, \
         mock.patch.object(stm, "_audit"), \
         mock.patch.object(stm, "RATE") as rate, \
         mock.patch.dict("os.environ", {"SCHWAB_APP_KEY": "k", "SCHWAB_APP_SECRET": "s"}), \
         mock.patch("requests.post", return_value=fake_resp):
        rate.acquire.return_value = True
        out = stm._refresh_access_token("schwab_taxable", "schwab", "live")

    assert out == "new_access"
    seed.assert_called_once()
    kwargs = seed.call_args[1]
    assert kwargs["refresh_token"] == "new_refresh"
    assert kwargs["access_token"] == "new_access"
    assert kwargs["rotated"] is True