"""Phase 10 — CIO Telegram DRY canary.

Zero live Telegram. general_sends is measured (not `or True`).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

CANARY_LIB = ROOT / "scripts" / "lib" / "cio_telegram_canary.py"
CANARY_CLI = ROOT / "scripts" / "run_cio_telegram_canary.py"
TRANSPORT = ROOT / "scripts" / "lib" / "cio_telegram_transport.py"


@pytest.fixture
def canary_iso(tmp_path, monkeypatch):
    receipt = tmp_path / "cio_telegram_canary_receipt.json"
    dedupe = tmp_path / "dedupe.jsonl"
    monkeypatch.setenv("CIO_TELEGRAM_CANARY_RECEIPT_JSON", str(receipt))
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(dedupe))
    monkeypatch.delenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", raising=False)
    monkeypatch.delenv("CIO_TELEGRAM_CANARY_APPROVAL", raising=False)
    monkeypatch.delenv("CIO_TELEGRAM_CANARY_ENABLE", raising=False)
    monkeypatch.setenv("CIO_THESIS_TELEGRAM", "0")
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "1")
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "000000:FAKE_CIO_TOKEN_PHASE10")
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "11112222")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000000:GENERAL_MUST_NOT_USE")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999999")
    monkeypatch.setenv("BUILD_SHA", "c" * 40)
    return {"receipt": receipt, "dedupe": dedupe}


def _boom(*_a, **_k):
    raise AssertionError("network forbidden in dry canary")


def test_dry_run_creates_receipt_sent_false(canary_iso):
    from scripts.lib.cio_telegram_canary import run_canary

    out = run_canary(dry_run=True, receipt_path=canary_iso["receipt"])
    assert out["dry_run"] is True
    path = Path(out["receipt_path"])
    assert path.is_file()
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert rec["sent"] is False
    assert rec["dry_run"] is True
    assert rec["operator_approved"] is False
    assert rec["cio_chat_confirmed"] is False
    assert rec["duplicate"] is False
    assert rec["proof"] == "dry"
    assert rec["release_sha"] == "c" * 40
    assert rec["symbol"] == "SCHD"
    assert rec["action"] == "Trim"
    assert rec["would_send_path"]
    assert rec["chat_target_type"] == "cio"
    assert rec["duplicate_key"]
    assert rec["chat_target_type"] != "general"


def test_general_sends_measured_as_zero_not_assumed(canary_iso):
    from scripts.lib.cio_telegram_canary import run_canary, source_contains_or_true

    out = run_canary(dry_run=True, receipt_path=canary_iso["receipt"])
    rec = out["receipt"]
    meas = out["measurement"]
    assert meas["assumed"] is False
    assert meas["source"] == "counted_send_attempts"
    assert meas["general_sends"] == 0
    assert rec["general_sends"] == meas["general_sends"]
    assert rec["general_sends"] == 0
    assert meas["general_token_reads_for_send"] == 0
    assert meas["transport_reads_general_token"] is False
    # Not the v3 `or True` scoring hack
    assert source_contains_or_true(CANARY_LIB) == []
    assert source_contains_or_true(CANARY_CLI) == []


def test_dry_run_no_network(canary_iso, monkeypatch):
    import requests
    import urllib.request

    monkeypatch.setattr(requests, "post", _boom)
    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "request", _boom)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    from scripts.lib.cio_telegram_canary import run_canary

    out = run_canary(dry_run=True, receipt_path=canary_iso["receipt"])
    assert out["receipt"]["sent"] is False
    assert out["measurement"]["http_calls"] == 0
    assert out["measurement"]["send_message_calls"] == 0
    assert out["measurement"]["general_sends"] == 0


def test_cli_dry_run_default_writes_receipt(canary_iso, monkeypatch):
    from scripts import run_cio_telegram_canary as cli

    rc = cli.main(["--receipt-path", str(canary_iso["receipt"])])
    assert rc == 0
    rec = json.loads(canary_iso["receipt"].read_text(encoding="utf-8"))
    assert rec["sent"] is False
    assert rec["dry_run"] is True
    assert rec["proof"] == "dry"
    assert rec["general_sends"] == 0


def test_live_without_operator_flags_stays_dry(canary_iso, monkeypatch):
    from scripts.lib.cio_telegram_canary import run_canary

    # --live requested, but no AUTHORIZE / approval / enable
    monkeypatch.delenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", raising=False)
    out = run_canary(dry_run=False, want_live=True, receipt_path=canary_iso["receipt"])
    assert out["dry_run"] is True
    rec = out["receipt"]
    assert rec["sent"] is False
    assert rec["operator_approved"] is False
    assert rec["proof"] == "dry"
    assert rec["live_gate_reason"] in (
        "missing_authorize_p2",
        "pytest_interdict",
        "network_interdicted",
        "canary_enable_missing",
        "operator_approval_missing",
        "canary_approval_not_granted",
    )


def test_live_with_env_still_dry_under_pytest(canary_iso, monkeypatch):
    from scripts.lib.cio_alex_telegram import CANARY_APPROVAL_PHRASE
    from scripts.lib.cio_telegram_canary import run_canary

    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    monkeypatch.setenv("CIO_TELEGRAM_CANARY_ENABLE", "1")
    monkeypatch.setenv("CIO_TELEGRAM_CANARY_APPROVAL", CANARY_APPROVAL_PHRASE)
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    out = run_canary(dry_run=False, want_live=True, receipt_path=canary_iso["receipt"])
    assert out["dry_run"] is True
    assert out["receipt"]["sent"] is False
    assert out["receipt"]["proof"] == "dry"


def test_transport_does_not_read_general_token_for_send(canary_iso):
    from scripts.lib.cio_telegram_canary import (
        measure_send_credential_env_reads,
        transport_source_reads_general_token,
    )
    from scripts.lib import cio_telegram_transport as t

    assert transport_source_reads_general_token() is False
    reads = measure_send_credential_env_reads()
    assert reads["TELEGRAM_BOT_TOKEN"] == 0
    assert reads["TELEGRAM_CHAT_ID"] == 0
    assert t.cio_bot_token() != ""
    assert "GENERAL" not in t.cio_bot_token()
    assert "999999999" not in t.cio_chat_ids()


def test_schd_trim_package_is_real_shaped(canary_iso):
    from scripts.lib.cio_telegram_canary import run_canary, schd_trim_decision

    d = schd_trim_decision()
    assert d["symbol"] == "SCHD"
    assert str(d["action"]).lower() == "trim"
    assert float(d["delta_usd"]) < 0
    assert float(d["weight_pct"]) > 12.0
    out = run_canary(dry_run=True, receipt_path=canary_iso["receipt"], decision=d)
    body = (out.get("package") or {}).get("message_body") or ""
    assert "SCHD" in body
    assert "Alex · CIO call" in body
    assert out["evaluation"]["material"] is True
    assert out["evaluation"]["would_send"] is True
    assert out["receipt"]["chat_target_type"] == "cio"


def test_script_never_sets_authorize_p2():
    for p in (CANARY_LIB, CANARY_CLI):
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                continue
            if isinstance(node, ast.Assign):
                text = ast.get_source_segment(src, node) or ""
                if "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY" in text and "=" in text:
                    # Allowed as a name constant; forbidden to assign into os.environ
                    if "os.environ" in text or "setdefault" in text:
                        raise AssertionError(f"{p} must not set AUTHORIZE_P2: {text}")
            if isinstance(node, ast.Call):
                seg = ast.get_source_segment(src, node) or ""
                if "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY" in seg and (
                    "setdefault" in seg or "os.environ[" in seg
                ):
                    raise AssertionError(f"{p} must not set AUTHORIZE_P2: {seg}")


def test_no_or_true_in_canary_or_transport():
    for p in (CANARY_LIB, CANARY_CLI, TRANSPORT):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                for v in node.values:
                    if isinstance(v, ast.Constant) and v.value is True:
                        hits.append(node.lineno)
        assert hits == [], f"{p} contains `or True` at lines {hits}"
