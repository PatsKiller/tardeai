"""Follow-up to #2365 (2026-10-31 round-3 review, LOW findings a-c).

a. The burst cap was severity-blind: a stop that crossed or fired could be digested behind three sync messages.
   ``burst_exempt_first_line`` lines are never capped.
b. A burst-held message never claimed its subject window, so its own reversal ("opened 0→1000" after a digested
   "closed 1000→0") paged alone. A burst-held message now claims the subject window.
c. Burst-held messages are archived to the digest with reason ``<level>:burst_held``.
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


def _closed(sym: str) -> str:
    return f"[holdings-change] {sym} closed 1000→0 sh — protective-stop band recheck recommended"


def _opened(sym: str) -> str:
    return f"[holdings-change] {sym} opened 0→1000 sh — protective-stop band recheck recommended"


CROSSED = "SYMX stop crossed — review now"


@pytest.fixture
def harness(monkeypatch, tmp_path):
    sent: list[str] = []
    archived: list[tuple] = []
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(tmp_path / "dedupe.jsonl"))
    monkeypatch.setenv("TRADEAI_INTENT_RECEIPTS_PATH", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setattr(router, "_intent_sent", {})
    monkeypatch.setattr(ta, "_token", lambda: "synthetic")
    monkeypatch.setattr(ta, "_chat_ids", lambda: ["1"])
    monkeypatch.setattr(ta, "_raw_send_telegram_result", lambda m, t, **kw: sent.append(m) or {"ok": True})
    monkeypatch.setattr(router, "_record_budget_send", lambda: None, raising=False)
    import report_capture

    monkeypatch.setattr(report_capture, "archive_message", lambda m, **k: archived.append((m, k.get("reason"))))
    return {"sent": sent, "archived": archived}


def _fill_burst(n: int) -> None:
    for i in range(n):
        assert ta._legacy_send(_closed(f"SYM{chr(65 + i)}"), False) is True


def test_a_stop_crossed_is_never_burst_capped(harness):
    cap = int(ta._override_config()["burst_max_pages"])
    _fill_burst(cap)
    assert ta._legacy_send(CROSSED, False) is True
    assert harness["sent"][-1] == CROSSED


def test_b_burst_held_message_claims_its_subject_so_the_reversal_cannot_page_alone(harness, monkeypatch):
    cap = int(ta._override_config()["burst_max_pages"])
    _fill_burst(cap)
    assert ta._legacy_send(_closed("SYMZ"), False) is False  # held by the burst cap
    # Seven minutes later (the 10-30 11:07 reversal): the 60 s burst window has passed, the subject window has not.
    real = router._durable_recently_sent
    monkeypatch.setattr(
        router,
        "_durable_recently_sent",
        lambda key, ttl: False if key.startswith("legacy_critical_burst:") else real(key, ttl),
    )
    assert ta._legacy_send(_opened("SYMZ"), False) is False  # its reversal stays held: subject window claimed
    assert _opened("SYMZ") not in harness["sent"]


def test_c_burst_held_is_archived_with_reason(harness):
    cap = int(ta._override_config()["burst_max_pages"])
    _fill_burst(cap)
    assert ta._legacy_send(_closed("SYMZ"), False) is False
    reasons = [r for m, r in harness["archived"] if m == _closed("SYMZ")]
    assert reasons and all(str(r).endswith(":burst_held") for r in reasons)
    assert reasons[0] == "P1_DIGEST:burst_held"
