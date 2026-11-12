"""Behaviour tests: an errored Finviz health check is UNKNOWN (amber, dismissible), a real expiry stays red (LQ-20261107-2228).

ANCHOR: FINVIZ_BANNER_UNKNOWN_LQ2228_20261112

Replaces the two source-text tests of LQ-2220 (test_api_check_failed_*, which grepped api_v2.py) with calls to
the real api_v2._finviz_credential_health_live, and pins the banner logic by feeding those real payloads through the
real TypeScript view module. Synthetic fixtures only; DB and validators are stubbed; no network, no secrets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import finviz_cookie_alert as fca  # noqa: E402


def _live(monkeypatch, *, cookie=None, token=None, cookie_probe=None, token_probe=None, row=None):
    """Call the real api_v2._finviz_credential_health_live with the DB and validators replaced by synthetic
    stubs (no network, no DB, no secrets). A probe that is a callable is used as is; an exception CLASS is raised."""
    import api_v2
    import secret_validators as sv

    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: {"status": "healthy", "last_error": None} if row is None else row)
    keys = {"FINVIZ_COOKIE": cookie, "FINVIZ_API_TOKEN": token}
    monkeypatch.setattr(sv, "_key", lambda name, *a, **k: keys.get(name))

    def _wrap(fn):
        def inner(*a, **k):
            if isinstance(fn, type) and issubclass(fn, BaseException):
                raise fn("probe blew up auth=SECRETVALUE123 more")
            return fn(*a, **k)
        return inner

    monkeypatch.setattr(sv, "_finviz_cookie", _wrap(cookie_probe or (lambda c: (True, "ok"))))
    monkeypatch.setattr(sv, "_finviz_token", _wrap(token_probe or (lambda t: (True, "ok"))))
    return api_v2._finviz_credential_health_live()


def test_errored_check_is_unknown_amber_with_the_exception_class(monkeypatch):
    out = _live(monkeypatch, cookie="c", cookie_probe=TimeoutError)
    assert out["status"] == "check_failed" and out["cookie_status"] == "unknown"
    assert out["severity"] == "amber"
    assert out["error_class"] == "TimeoutError" and out["source_status"] == "healthy"
    assert out["message"].startswith("UNKNOWN") and "TimeoutError" in out["message"]
    assert "cookie expired" not in out["message"].lower()
    assert out["show_banner"] is True


def test_errored_check_never_leaks_the_secret_shaped_text(monkeypatch):
    out = _live(monkeypatch, cookie="c", cookie_probe=TimeoutError)
    assert "SECRETVALUE123" not in json.dumps(out)


def test_errored_check_with_unreadable_source_status_keeps_it_null(monkeypatch):
    out = _live(monkeypatch, cookie="c", cookie_probe=ConnectionError, row={})
    assert out["error_class"] == "ConnectionError" and out["source_status"] is None


def test_real_expiry_is_still_red_expired_not_unknown(monkeypatch):
    out = _live(monkeypatch, cookie="c", cookie_probe=lambda c: (False, "login page or empty export - cookie expired"))
    assert out["status"] == "expired" and out["cookie_status"] == "expired"
    assert out["severity"] == "red" and out["ok"] is False
    assert out["message"] and not out["message"].startswith("UNKNOWN")


def test_missing_cookie_and_token_is_red_missing(monkeypatch):
    out = _live(monkeypatch)
    assert out["status"] == "missing" and out["severity"] == "red"


def _node():
    import shutil
    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="node not available")
def test_banner_view_of_the_real_payloads_end_to_end(monkeypatch, tmp_path):
    """Feed the REAL payloads api_v2 returns through the real TypeScript banner logic (node strips the types):
    an errored check is UNKNOWN (not severe, dismissible); a real expiry is severe and stays visible."""
    import subprocess

    errored = _live(monkeypatch, cookie="c", cookie_probe=TimeoutError)
    expired = _live(monkeypatch, cookie="c", cookie_probe=lambda c: (False, "HTTP 403"))
    script = tmp_path / "view.mjs"
    mod = (ROOT / "apps/command-center-v3/src/lib/finvizBannerView.ts").as_posix()
    script.write_text(
        "import { finvizBannerView as v } from %s\n" % json.dumps("file://" + mod)
        + "const d = JSON.parse(process.argv[2])\n"
        + "console.log(JSON.stringify({ e: v(d.errored, false), eD: v(d.errored, true), x: v(d.expired, false), xD: v(d.expired, true) }))\n",
        encoding="utf-8")
    r = subprocess.run(["node", str(script), json.dumps({"errored": errored, "expired": expired})],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["e"] == {"show": True, "unknown": True, "severe": False}
    assert got["eD"]["show"] is False  # dismissible: it is an unknown, not a confirmed failure
    assert got["x"]["severe"] is True and got["x"]["unknown"] is False
    assert got["xD"]["show"] is True  # a real expiry cannot be dismissed


def test_threshold_floor_of_two_holds_when_config_asks_for_less(monkeypatch):
    for low in (0, 1, -5):
        monkeypatch.setattr(fca, "_config", lambda low=low: {"check_failed_consecutive_min": low})
        assert fca.check_failed_threshold() == 2
