"""GO alerts reach the operator: they bypass the legacy digest router. Offline: send_telegram faked.

2026-09-14 12:15 ET: ARMP (A+) and ELMT qualified; telegram_alert_router filed both as P1_DIGEST
("Suppressed"), send_telegram returned True, and the ledger recorded them as sent.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import screener_go_alerts as g  # noqa: E402
from lib.scalp_go_criteria import FALLBACK  # noqa: E402

COVERS = ["scripts/screener_go_alerts.py"]

GOOD = {"symbol": "ARMP", "run_label": "0900", "scanned_at": "2026-09-14T14:08:00", "score": 51, "grade": "A+",
        "decision": "GO", "rvol": 19.4, "price": 6.14, "change_pct": 15.8, "gap_pct": 15.8, "float_m": 11.6,
        "volume": 2_254_990, "catalyst": "FDA Breakthrough Therapy", "catalyst_verified": True,
        "disqualified": False, "source": "screener"}


def test_main_sends_with_the_router_bypassed_and_records_only_real_sends(monkeypatch, tmp_path):
    calls = []
    fake = types.ModuleType("telegram_alert")

    def send_telegram(msg, bypass_router=False, message_class="operator_alert", **kw):
        calls.append({"bypass_router": bypass_router, "message_class": message_class, "msg": msg})
        return True
    fake.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(g, "_db_rows", lambda session: [GOOD])
    monkeypatch.setattr(g, "load_criteria", lambda: FALLBACK)
    monkeypatch.setattr(g, "LEDGER", tmp_path / "sent.json")
    monkeypatch.setattr(g, "RECEIPT", tmp_path / "receipt.json")
    monkeypatch.setattr(sys, "argv", ["screener_go_alerts.py", "--send", "--session", "2026-09-14"])
    assert g.main() == 0
    assert calls and calls[0]["bypass_router"] is True
    assert "2026-09-14:ARMP" in (tmp_path / "sent.json").read_text()


def test_a_failed_send_is_not_recorded(monkeypatch, tmp_path):
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda msg, **kw: False
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(g, "_db_rows", lambda session: [GOOD])
    monkeypatch.setattr(g, "load_criteria", lambda: FALLBACK)
    monkeypatch.setattr(g, "LEDGER", tmp_path / "sent.json")
    monkeypatch.setattr(g, "RECEIPT", tmp_path / "receipt.json")
    monkeypatch.setattr(sys, "argv", ["screener_go_alerts.py", "--send", "--session", "2026-09-14"])
    g.main()
    assert "ARMP" not in (tmp_path / "sent.json").read_text()
