"""n8n program 0.4f (2026-11-06): the dead-man's alert env file is provisioned least-privilege.

ANCHOR: N8N_HOST_ALERT_ENV_20261106

Hermetic: every path is under tmp_path; nothing reads the real runtime env.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))

import n8n_host_alert_env as hae  # noqa: E402

UNITS = ROOT / "docs" / "ops" / "packets" / "n8n-platform-hardening-20261022" / "units"
SRC = "OTHER_KEY=o\nexport TELEGRAM_BOT_TOKEN='tokv'\nTELEGRAM_CHAT_ID=chatv\nDATABASE_URL=dbv\n"


def _write(p: Path, text: str, mode: int = 0o600) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    os.chmod(p, mode)
    return p


def test_the_units_read_the_default_target():
    unit = (UNITS / "tradeai-n8n-host-deadman.service.proposed").read_text(encoding="utf-8")
    assert "EnvironmentFile=-%h/.config/tradeai/n8n/host-alert.env" in unit
    assert hae.DEFAULT_TARGET == Path.home() / ".config" / "tradeai" / "n8n" / "host-alert.env"


def test_write_copies_only_the_two_keys_at_0600_and_never_prints_a_value(tmp_path):
    src = _write(tmp_path / "env", SRC)
    tgt = tmp_path / "cfg" / "n8n" / "host-alert.env"
    out = hae.write(src, tgt)
    assert out["ok"] and out["written"]
    assert tgt.read_text() == "TELEGRAM_BOT_TOKEN=tokv\nTELEGRAM_CHAT_ID=chatv\n"
    assert stat.S_IMODE(tgt.stat().st_mode) == 0o600
    assert stat.S_IMODE(tgt.parent.stat().st_mode) == 0o700
    blob = json.dumps(out)
    assert "tokv" not in blob and "chatv" not in blob and "dbv" not in blob
    assert hae.target_problems(tgt) == []
    again = hae.write(src, tgt)
    assert again["ok"] and not again["written"]


def test_write_never_overwrites_a_different_file(tmp_path):
    src = _write(tmp_path / "env", SRC)
    tgt = _write(tmp_path / "host-alert.env", "TELEGRAM_BOT_TOKEN=x\nTELEGRAM_CHAT_ID=y\n")
    out = hae.write(src, tgt)
    assert out["ok"] is False and tgt.read_text() == "TELEGRAM_BOT_TOKEN=x\nTELEGRAM_CHAT_ID=y\n"


def test_write_refuses_a_source_missing_a_key(tmp_path):
    src = _write(tmp_path / "env", "TELEGRAM_BOT_TOKEN=t\n")
    tgt = tmp_path / "host-alert.env"
    out = hae.write(src, tgt)
    assert out["ok"] is False and "TELEGRAM_CHAT_ID" in out["error"] and not tgt.exists()
    assert hae.write(tmp_path / "nope", tgt)["ok"] is False and not tgt.exists()


def test_dry_run_writes_nothing_and_reports_names_only(tmp_path):
    src = _write(tmp_path / "env", SRC)
    tgt = tmp_path / "cfg" / "host-alert.env"
    out = hae.check(src, tgt)
    assert out["ok"] is False and out["would_write"] is True
    assert out["source_has"] == {"TELEGRAM_BOT_TOKEN": True, "TELEGRAM_CHAT_ID": True}
    assert not tgt.exists() and not tgt.parent.exists()
    assert "tokv" not in json.dumps(out)


def test_target_problems(tmp_path):
    good = "TELEGRAM_BOT_TOKEN=a\nTELEGRAM_CHAT_ID=b\n"
    d = tmp_path / "d"
    d.mkdir(mode=0o700)
    os.chmod(d, 0o700)
    assert hae.target_problems(d / "nope")[0].startswith("alert env file missing")
    assert any("mode" in p for p in hae.target_problems(_write(d / "loose.env", good, 0o644)))
    assert any("DATABASE_URL" in p for p in hae.target_problems(_write(d / "extra.env", good + "DATABASE_URL=c\n")))
    assert any("TELEGRAM_CHAT_ID" in p for p in hae.target_problems(_write(d / "short.env", "TELEGRAM_BOT_TOKEN=a\n")))
    assert hae.target_problems(_write(d / "good.env", good)) == []
    os.chmod(d, 0o755)
    assert any("directory" in p for p in hae.target_problems(d / "good.env"))


def test_main_exit_codes(tmp_path):
    src = _write(tmp_path / "env", SRC)
    tgt = tmp_path / "c" / "host-alert.env"
    assert hae.main(["--source", str(src), "--target", str(tgt)]) == 1 and not tgt.exists()
    assert hae.main(["--source", str(src), "--target", str(tgt), "--write"]) == 0
    assert hae.main(["--source", str(src), "--target", str(tgt)]) == 0


def test_this_file_is_registered_in_a_ci_gate():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lib import ci_gates  # noqa: PLC0415 -- needs ROOT on sys.path first

    assert "tests/test_n8n_host_alert_env_20261106.py" in ci_gates.registry_text(ROOT)
