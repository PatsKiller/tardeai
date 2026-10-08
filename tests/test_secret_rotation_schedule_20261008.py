"""Weekly key rotation schedule (observability gaps PR, 2026-10-08; ADR_COORDINATION_SECRETS, ACCEPTED).

config/secret_registry.yaml lists TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N and TRADEAI_N8N_RELAY_BEARER as
self_minted with max_age_days 7; scripts/secrets/rotation_daemon.py is what the ADR names as the weekly
rotation driver and NOTHING schedules it (operator cron grant: see
docs/implementation/n8n-parallel/proposals/key-rotation-schedule-20261008.md). This pins: the two
registry entries parse; the daemon's due-selection picks a 7-day key at day 8 and not at day 6; the
dry-run writes no state and sends nothing; the daemon never mints or writes a secret itself. Hermetic:
tmp registry + tmp state, --now injected.

COVERS = ["scripts/secrets/rotation_daemon.py", "config/secret_registry.yaml"]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

import rotation_daemon as RD  # noqa: E402

KEYS = ("TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N", "TRADEAI_N8N_RELAY_BEARER")
NOW = datetime(2026, 10, 16, 9, 30, tzinfo=timezone.utc)


def _registry(tmp_path: Path, max_age: int = 7) -> Path:
    doc = {
        "defaults": {"max_age_days": 90},
        "secrets": {
            "WEEKLY_KEY": {
                "class": "self_minted",
                "max_age_days": max_age,
                "restart_targets": ["tradeai-n8n-run-relay"],
            },
            "VENDOR_KEY": {"class": "vendor_manual", "max_age_days": 90, "vendor_url": "https://example.invalid/keys"},
            "BWS_ACCESS_TOKEN": {"class": "self_minted", "max_age_days": 1},
        },
    }
    p = tmp_path / "secret_registry.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def _state(tmp_path: Path, rotated_days_ago: float, name="WEEKLY_KEY") -> Path:
    p = tmp_path / "rotation_daemon_state.json"
    p.write_text(json.dumps({name: {"last_rotated_at": (NOW - timedelta(days=rotated_days_ago)).isoformat()}}))
    return p


def test_the_two_registry_entries_parse_as_weekly_self_minted_keys_with_the_relay_as_a_restart_target():
    secrets = RD.load_registry(ROOT / "config" / "secret_registry.yaml")
    for name in KEYS:
        e = secrets[name]
        assert e["class"] == "self_minted" and int(e["max_age_days"]) == 7, name
        assert "tradeai-n8n-run-relay" in e["restart_targets"], name
    assert "tradeai-n8n-coordination-gateway" in secrets[KEYS[0]]["restart_targets"]
    # both are due in a dry-run over the real registry against an EMPTY state (never rotated = age 999)
    due = {r["name"]: r for r in RD.select_due(secrets, {}, NOW)}
    assert all(due[k]["action"] == RD.ACTION_NAG_SELF_MINTED and due[k]["age_days"] == 999 for k in KEYS)


def test_due_selection_picks_a_seven_day_key_at_day_eight_and_not_at_day_six(tmp_path):
    secrets = RD.load_registry(_registry(tmp_path))
    day8 = RD.select_due(secrets, RD.load_state(_state(tmp_path, 8)), NOW)
    assert [(r["name"], r["age_days"], r["max_age_days"]) for r in day8 if r["name"] == "WEEKLY_KEY"] == [
        ("WEEKLY_KEY", 8, 7)
    ]
    weekly = next(r for r in day8 if r["name"] == "WEEKLY_KEY")
    assert (
        weekly["action"] == RD.ACTION_NAG_SELF_MINTED
        and weekly["command"] == "scripts/secrets/rotate.py WEEKLY_KEY --generate"
    )
    assert weekly["restart_targets"] == ["tradeai-n8n-run-relay"]
    assert "WEEKLY_KEY" not in {r["name"] for r in RD.select_due(secrets, RD.load_state(_state(tmp_path, 6)), NOW)}
    assert "WEEKLY_KEY" in {
        r["name"] for r in RD.select_due(secrets, RD.load_state(_state(tmp_path, 7)), NOW)
    }  # day 7 = due
    assert "BWS_ACCESS_TOKEN" not in {r["name"] for r in day8}  # Rule 1
    vendor = next(r for r in day8 if r["name"] == "VENDOR_KEY")
    assert (
        vendor["action"] == RD.ACTION_NAG_VENDOR
        and vendor["vendor_url"].startswith("https://")
        and vendor["nag_suppressed"] is False
    )


def test_the_vendor_nag_is_suppressed_for_three_days_but_the_self_minted_nag_is_not(tmp_path):
    secrets = RD.load_registry(_registry(tmp_path))
    st = {"VENDOR_KEY": {"last_nag_at": (NOW - timedelta(days=1)).isoformat()}}
    due = {r["name"]: r for r in RD.select_due(secrets, st, NOW)}
    assert due["VENDOR_KEY"]["nag_suppressed"] is True and "VENDOR_KEY" not in " ".join(
        RD.nag_lines(list(due.values()))
    )
    assert "WEEKLY_KEY" in " ".join(RD.nag_lines(list(due.values())))


def test_dry_run_prints_the_selection_and_writes_no_state_and_sends_nothing(tmp_path, capsys, monkeypatch):
    reg = _registry(tmp_path)
    st = _state(tmp_path, 8)
    before = st.read_text()
    monkeypatch.setitem(sys.modules, "telegram_alert", None)  # an import would raise: the dry-run must not reach it
    rc = RD.main(["--dry-run", "--registry", str(reg), "--state", str(st), "--now", NOW.isoformat()])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["mode"] == "dry-run" and out["state_written"] is False and out["would_send_telegram"] is True
    assert out["considered"] == 2 and {r["name"] for r in out["due"]} == {"WEEKLY_KEY", "VENDOR_KEY"}
    assert st.read_text() == before
    assert RD.main(["--dry-run", "--registry", str(reg), "--state", str(st), "--now", "not-a-date"]) == 2


def test_the_daemon_only_nags_for_self_minted_keys_it_never_mints_or_writes_a_secret():
    src = (ROOT / "scripts" / "secrets" / "rotation_daemon.py").read_text(encoding="utf-8")
    for forbidden in ("secrets_admin", "set_secret", "bws ", "render_env", "staged_restart", "subprocess"):
        assert forbidden not in src, forbidden
    assert RD.ACTION_NAG_SELF_MINTED == "nag_self_minted_run_rotate_py_generate"
