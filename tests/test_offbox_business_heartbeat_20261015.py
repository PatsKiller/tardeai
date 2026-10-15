"""DD12 (third-party audit 2026-10-15): a business-output heartbeat SEPARATE from the alert-path dead-man.

scripts/offbox_deadman.py --config config/offbox_business_heartbeat.json evaluates business outputs (scalp cycles in
RTH, nightly n8n backup, weekly restore drill PASSED) and pings its own external check. Hermetic: tmp state root,
stub requester; the dry run is proven never to call the requester. No socket is opened."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import offbox_deadman as D  # noqa: E402

CFG = D.load_config(ROOT / "config" / "offbox_business_heartbeat.json")
ALERT_CFG = D.load_config()
URL = "https://ping.example.invalid/biz-0000-1111"
RTH = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)  # Thursday 11:00 ET
NIGHT = datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc)  # Thursday 22:00 ET


def _write(root: Path, rel: str, doc: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def _healthy(root: Path, now: datetime, **over) -> None:
    docs = {
        "data/runtime/trade_ai_scalp_live_last.json": {"last_ok_at": (now - timedelta(minutes=4)).isoformat()},
        "backups/n8n/n8n_lab_backup_last.json": {"as_of": (now - timedelta(hours=10)).isoformat(), "ok": True},
        "backups/n8n/n8n_lab_restore_drill_last.json": {
            "finished": (now - timedelta(days=3)).isoformat(),
            "ok": True,
            "state": "PASSED",
        },
    }
    for rel, doc in docs.items():
        _write(root, rel, {**doc, **over.get(rel, {})})


def _never(*_a, **_k):
    raise AssertionError("no network in a dry run")


def test_config_is_separate_from_the_alert_path_deadman():
    assert CFG["ping_url_env"] != ALERT_CFG.get("ping_url_env")
    assert CFG["receipt_rel"] != D.RECEIPT_REL
    assert {c["name"] for c in CFG["checks"]} == {
        "scalp_cycle_rth",
        "n8n_lab_backup_nightly",
        "n8n_lab_restore_drill_weekly",
    }


def test_healthy_business_output_pings_success(tmp_path):
    _healthy(tmp_path, RTH)
    calls = []
    r = D.run(
        live=True,
        env={CFG["ping_url_env"]: URL},
        now=RTH,
        cfg=CFG,
        root=tmp_path,
        requester=lambda *a: calls.append(a) or {"ok": True, "status": 200},
    )
    assert r["ok"] is True and r["request"]["kind"] == "success" and len(calls) == 1 and calls[0][0] == "GET"


def test_stalled_scalp_in_rth_fails_but_is_ignored_at_night(tmp_path):
    _healthy(
        tmp_path,
        RTH,
        **{"data/runtime/trade_ai_scalp_live_last.json": {"last_ok_at": (RTH - timedelta(minutes=40)).isoformat()}},
    )
    rows = {c["name"]: c for c in D.evaluate(tmp_path, RTH, CFG)}
    assert rows["scalp_cycle_rth"]["ok"] is False and rows["scalp_cycle_rth"]["reason"].startswith("stale:")
    rows = {c["name"]: c for c in D.evaluate(tmp_path, NIGHT, CFG)}
    assert rows["scalp_cycle_rth"] == {
        "name": "scalp_cycle_rth",
        "ok": True,
        "reason": "outside_window",
        "age_min": None,
    }


def test_failed_restore_drill_fails_the_business_heartbeat_with_a_fail_ping(tmp_path):
    _healthy(tmp_path, RTH, **{"backups/n8n/n8n_lab_restore_drill_last.json": {"ok": False, "state": "FAILED"}})
    sent = []
    r = D.run(
        live=True,
        env={CFG["ping_url_env"]: URL},
        now=RTH,
        cfg=CFG,
        root=tmp_path,
        requester=lambda m, u, b, t: sent.append((m, u, b)) or {"ok": True, "status": 200},
    )
    assert r["request"]["kind"] == "fail" and sent[0][0] == "POST" and sent[0][1].endswith("/fail")
    body = sent[0][2].decode()
    assert "business-output heartbeat" in body and "n8n_lab_restore_drill_weekly" in body


def test_status_field_state_failed_is_caught_even_if_ok_missing(tmp_path):
    cfg = {
        **CFG,
        "checks": [dict(c, require_ok=False) for c in CFG["checks"] if c["name"] == "n8n_lab_restore_drill_weekly"],
    }
    _healthy(tmp_path, RTH, **{"backups/n8n/n8n_lab_restore_drill_last.json": {"state": "FAILED"}})
    (row,) = D.evaluate(tmp_path, RTH, cfg)
    assert row["ok"] is False and row["reason"] == "status:FAILED"


def test_missing_backup_receipt_fails(tmp_path):
    _healthy(tmp_path, RTH)
    (tmp_path / "backups/n8n/n8n_lab_backup_last.json").unlink()
    rows = {c["name"]: c for c in D.evaluate(tmp_path, RTH, CFG)}
    assert rows["n8n_lab_backup_nightly"]["ok"] is False


def test_malformed_window_never_silences_a_check():
    assert D.in_window(RTH, {"start": "nonsense"}) is True
    assert D.in_window(RTH, {"days": ["sat"], "start": "00:00", "end": "23:59"}) is False


def test_dry_run_never_touches_the_network(tmp_path):
    _healthy(tmp_path, RTH)
    r = D.run(live=False, env={CFG["ping_url_env"]: URL}, now=RTH, cfg=CFG, root=tmp_path, requester=_never)
    assert r["outcome"] == {"status": "DRY_RUN", "network": False}


def test_main_live_writes_the_business_receipt_not_the_alert_path_one(tmp_path, monkeypatch, capsys):
    _healthy(tmp_path, datetime.now(timezone.utc))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.delenv(CFG["ping_url_env"], raising=False)
    rc = D.main(["--live", "--config", str(ROOT / "config" / "offbox_business_heartbeat.json")])
    assert rc == 1  # no URL configured -> NOT_CONFIGURED, no network
    assert (tmp_path / CFG["receipt_rel"]).exists() and not (tmp_path / D.RECEIPT_REL).exists()
    assert json.loads(capsys.readouterr().out)["outcome"]["status"] == "NOT_CONFIGURED"
