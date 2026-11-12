"""A failed Finviz health CHECK is not an expired cookie (LQ-20261107-2220 / LQ-2209).

ANCHOR: FINVIZ_CHECK_FAILED_LQ2220_20261112

2026-11-12 01:34 ET: the credential-health probe raised, api_v2 returned status `check_failed` with
the hardcoded message "Finviz Elite cookie expired", and the alert module mapped check_failed to
`expired`, sending "COOKIE AND TOKEN FAILING" while data_source_health was healthy with 1854 rows.
A check that errored knows nothing about the cookie. Synthetic fixtures only; no network, no DB.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import finviz_cookie_alert as fca  # noqa: E402

FI = "fi-number@example.invalid"


class _Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, channel, *, body, subject, to, subject_key):
        self.calls.append({"channel": channel, "body": body, "subject": subject})
        return {"ok": True, "delivered": True, "gateway_mode": "shadow"}


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.delenv(fca.DISABLE_ENV, raising=False)
    monkeypatch.delenv(fca.STATE_ENV, raising=False)


def _cf(source_status="healthy", cls="TimeoutError", **over):
    doc = {"ok": False, "status": "check_failed", "cookie_status": "unknown", "severity": "amber",
           "error_class": cls, "source_status": source_status, "detail": "probe errored"}
    doc.update(over)
    return doc


def _run(health, tmp_path, send, minute=0):
    return fca.maybe_alert(health, state_path=tmp_path / "s.json", gateways=[FI], send=send,
                           now=datetime(2026, 11, 12, 6, minute, tzinfo=timezone.utc))


def _state(tmp_path):
    return json.loads((tmp_path / "s.json").read_text())


def test_check_failed_is_unknown_not_expired():
    assert fca.cookie_state({"status": "check_failed", "cookie_status": "unknown"}) == "unknown"
    assert fca.cookie_state({"status": "check_failed"}) == "unknown"


def test_a_single_check_failed_sends_nothing_and_records_class_and_time(tmp_path):
    send = _Fake()
    out = _run(_cf(), tmp_path, send)
    assert out["alerted"] is False and send.calls == []
    st = _state(tmp_path)
    assert st["last_check_failed_class"] == "TimeoutError"
    assert st["last_check_failed_at"].startswith("2026-11-12T06:00")
    assert st["check_failed_consecutive"] == 1


def test_n_consecutive_with_a_healthy_source_still_sends_nothing(tmp_path):
    send = _Fake()
    for m in range(fca.check_failed_threshold() + 3):
        _run(_cf("healthy"), tmp_path, send, m)
    assert send.calls == []
    assert _state(tmp_path)["check_failed_consecutive"] == fca.check_failed_threshold() + 3


def test_n_consecutive_with_an_unreadable_source_status_sends_nothing(tmp_path):
    send = _Fake()
    for m in range(fca.check_failed_threshold() + 1):
        _run(_cf(None), tmp_path, send, m)
    assert send.calls == []


def test_n_consecutive_and_source_failing_sends_once_and_never_says_cookie_expired(tmp_path):
    send = _Fake()
    n = fca.check_failed_threshold()
    for m in range(n - 1):
        _run(_cf("error"), tmp_path, send, m)
    assert send.calls == []
    out = _run(_cf("error"), tmp_path, send, n)
    assert out["alerted"] is True and len(send.calls) == 2  # telegram + one text
    for c in send.calls:
        low = c["body"].lower()
        assert "cookie expired" not in low and "cookie and token failing" not in low
        assert "check" in low and "TimeoutError" in c["body"]
    _run(_cf("error"), tmp_path, send, n + 1)
    assert len(send.calls) == 2  # once per ET day


def test_a_non_failed_verdict_resets_the_consecutive_count(tmp_path):
    send = _Fake()
    _run(_cf("error"), tmp_path, send, 0)
    _run(_cf("error"), tmp_path, send, 1)
    fca.maybe_alert({"status": "ok", "cookie_status": "ok"}, state_path=tmp_path / "s.json",
                    gateways=[FI], send=send, now=datetime(2026, 11, 12, 6, 2, tzinfo=timezone.utc))
    assert _state(tmp_path)["check_failed_consecutive"] == 0


def test_real_expired_cookie_still_alerts(tmp_path):
    send = _Fake()
    out = _run({"status": "expired", "cookie_status": "expired", "ok": False}, tmp_path, send)
    assert out["alerted"] is True and len(send.calls) == 2


def _api_source():
    return (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")


def _except_branch():
    src = _api_source()
    start = src.index("def _finviz_credential_health_live")
    end = src.index("def _schwab_reauth_url")
    body = src[start:end]
    return body[body.rindex("except Exception as e:"):]


def test_api_check_failed_message_is_unknown_with_exception_class():
    br = _except_branch()
    assert "cookie expired" not in br.lower()
    assert "UNKNOWN" in br and "type(e).__name__" in br
    assert '"error_class"' in br and '"source_status"' in br


def test_api_check_failed_is_amber_not_red():
    br = _except_branch()
    assert '"severity": "amber"' in br and '"severity": "red"' not in br


def test_threshold_is_config_driven_and_at_least_two():
    cfg = json.loads((ROOT / "config" / "finviz_cookie_alert.json").read_text())
    assert cfg["check_failed_consecutive_min"] >= 2
    assert fca.check_failed_threshold() == cfg["check_failed_consecutive_min"]
