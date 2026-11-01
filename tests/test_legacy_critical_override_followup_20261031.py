"""Follow-up to #2350 (2026-10-31 round-2 adversarial review, non-blocking findings 1-3).

1. A zero count ("0 unprotected positions") is telemetry and never pages; a nonzero count still does.
2. When the override's P1 intent is deduped or not delivered, the message is archived to the digest instead of
   vanishing from both the phone and the digest.
3. At most ``burst_max_pages`` override pages per ``burst_window_seconds`` across subjects; the rest are digested.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import telegram_alert as ta  # noqa: E402
import telegram_alert_router as router  # noqa: E402

ZERO = "Stop coverage report: 0 unprotected positions"
TWO = "Stop coverage report: 2 unprotected positions"


def _flap(sym: str) -> str:
    return f"[holdings-change] {sym} closed 1000→0 sh — protective-stop band recheck recommended"


@pytest.fixture
def harness(monkeypatch, tmp_path):
    sent: list[str] = []
    archived: list[tuple] = []
    state = {"ok": True}
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(tmp_path / "dedupe.jsonl"))
    monkeypatch.setenv("TRADEAI_INTENT_RECEIPTS_PATH", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setattr(router, "_intent_sent", {})
    monkeypatch.setattr(ta, "_token", lambda: "synthetic")
    monkeypatch.setattr(ta, "_chat_ids", lambda: ["1"])
    monkeypatch.setattr(
        ta,
        "_raw_send_telegram_result",
        lambda m, t, **kw: (sent.append(m) if state["ok"] else None) or {"ok": state["ok"]},
    )
    monkeypatch.setattr(router, "_record_budget_send", lambda: None, raising=False)
    import report_capture

    monkeypatch.setattr(report_capture, "archive_message", lambda m, **k: archived.append((m, k.get("reason"))))
    return {"sent": sent, "archived": archived, "state": state}


def test_zero_unprotected_is_telemetry_but_nonzero_pages(harness):
    assert ta._legacy_send(ZERO, False) is False
    assert harness["sent"] == []
    assert ta._legacy_send(TWO, False) is True
    assert harness["sent"] == [TWO]


def test_not_delivered_override_is_archived_to_the_digest(harness):
    harness["state"]["ok"] = False
    assert ta._legacy_send(_flap("SYMA"), False) is False
    assert harness["sent"] == []
    assert harness["archived"] and harness["archived"][0][0] == _flap("SYMA")
    assert "override_not_delivered" in str(harness["archived"][0][1])


def test_deduped_override_is_archived_not_lost(harness, monkeypatch):
    assert ta._legacy_send(_flap("SYMA"), False) is True
    # Same body again with the subject window cleared: the P1 intent's exact-body dedupe refuses it.
    monkeypatch.setattr(router, "_durable_recently_sent", lambda key, ttl: False)
    harness["archived"].clear()
    assert ta._legacy_send(_flap("SYMA"), False) is False
    assert harness["sent"] == [_flap("SYMA")]
    assert any(m == _flap("SYMA") for m, _ in harness["archived"])


def test_burst_cap_digests_the_rest_of_a_sync_burst(harness):
    cfg_max = int(ta._override_config().get("burst_max_pages"))
    names = [f"SYM{c}" for c in "ABCDE"]
    results = [ta._legacy_send(_flap(n), False) for n in names]
    assert sum(results) == cfg_max < len(names)
    assert len(harness["sent"]) == cfg_max
    held = [n for n, ok in zip(names, results) if not ok]
    assert all(any(m == _flap(n) for m, _ in harness["archived"]) for n in held)
