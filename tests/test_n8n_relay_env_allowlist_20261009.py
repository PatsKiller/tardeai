"""B2-D2 (2026-10-09): the n8n run relay sees only its allowlisted environment, never a broker or provider key.

Hermetic: fake values in tmp paths, no bind, no systemd, no host env file is read.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import n8n_run_relay as R
from scripts import render_n8n_relay_env as RENDER
from scripts.lib import n8n_relay_env as E
from scripts.lib.secret_name_classes import classify_name, classified

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "config" / "systemd" / "user" / "tradeai-n8n-run-relay.service"
BEARER = "fake-bearer-" + "b" * 40
KEY = "fake-hmac-" + "k" * 40
PREVIOUS = "fake-prev-" + "p" * 40
FAKE_SECRET = "FAKEVALUE-must-never-print-0123456789"

# The shape of the full secrets env: broker, provider and other credential names next to the relay's own.
BROKER = [
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "SCHWAB_APP_KEY",
    "SCHWAB_APP_SECRET",
    "SCHWAB_LOGIN_PASSWORD",
    "SNAPTRADE_CONSUMER_KEY",
    "SNAPTRADE_USER_SECRET",
    "MOOMOO_OPEND_LOGIN_PWD_MD5",
    "BROKER_LIVE_ENABLED",
]
PROVIDER = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "deepseek_tradeai",
    "POLYGON_API_KEY",
    "FINNHUB_API_KEY",
    "FMP_API_KEY",
    "FINVIZ_COOKIE",
    "BRAVE_SEARCH_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CIO_BOT_TOKEN",
    "TWILIO_AUTH_TOKEN",
    "SMTP_PASSWORD",
    "SLACK_APP_TOKEN",
]
CREDENTIAL = [
    "DB_PASSWORD",
    "ADMIN_WRITE_TOKEN",
    "SHADOW_DSN",
    "LAB_DSN",
    "M2_AGENT_DSN",
    "N8N_ENCRYPTION_KEY_ESCROW",
    "TRADEAI_N8N_GATEWAY_HMAC_KEY",
]
PLAIN = ["DB_HOST", "LOCAL_LLM_MODEL", "TIMEZONE", "ENABLE_TELEGRAM", "RISK_GATE_H1_ENABLED"]


def full_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {name: FAKE_SECRET for name in BROKER + PROVIDER + CREDENTIAL + PLAIN}
    env.update(
        {
            "TRADEAI_N8N_RELAY_BEARER": BEARER,
            "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": KEY,
            "TRADEAI_STATE_ROOT": str(tmp_path),
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
            "SSH_AUTH_SOCK": str(tmp_path / "agent.sock"),
        }
    )
    env.update(extra)
    return env


def test_central_classes_cover_broker_provider_and_credential_names():
    for name in BROKER:
        assert classify_name(name) == "broker", name
    for name in PROVIDER:
        assert classify_name(name) == "provider", name
    for name in CREDENTIAL:
        assert classify_name(name) == "credential", name
    for name in PLAIN + ["HOME", "PATH", "PWD", "OLDPWD", "LOGNAME", "SSH_AUTH_SOCK", "INVOCATION_ID"]:
        assert classify_name(name) is None, name
    groups = classified(BROKER + PROVIDER + PLAIN)
    assert groups["broker"] == sorted(BROKER) and groups["provider"] == sorted(PROVIDER)


def test_the_allowlist_holds_the_relay_secrets_and_no_broker_or_provider_name():
    assert set(E.RELAY_REQUIRED_SECRET_NAMES) <= set(E.RELAY_SECRET_NAMES) <= E.RELAY_ALLOWED_NAMES
    assert set(E.RELAY_SECRET_NAMES) == {R.BEARER_ENV, R.BEARER_PREVIOUS_ENV, R.N8N_KEY_ENV}
    for name in E.RELAY_ALLOWED_NAMES:
        assert classify_name(name) in (None, "credential"), name
    assert not [n for n in E.RELAY_ALLOWED_NAMES if classify_name(n) == "credential" and n not in E.RELAY_SECRET_NAMES]


def test_every_environment_name_the_relay_and_its_imports_read_is_allowlisted():
    sources = [
        ROOT / "scripts" / "n8n_run_relay.py",
        ROOT / "scripts" / "lib" / "n8n_coordination_projection.py",
        ROOT / "scripts" / "lib" / "n8n_coordination_gateway.py",
    ]
    read = set()
    for path in sources:
        read |= set(re.findall(r"[\"'](TRADEAI_[A-Z0-9_]+|RELAY_[A-Z0-9_]+)[\"']", path.read_text()))
    assert read, "inventory found nothing; the regex is broken"
    assert read <= E.RELAY_ALLOWED_NAMES, sorted(read - E.RELAY_ALLOWED_NAMES)


def test_the_relay_never_spawns_so_no_child_needs_the_scrubbed_names():
    text = (ROOT / "scripts" / "n8n_run_relay.py").read_text()
    for token in ("import subprocess", "Popen", "os.system", "os.exec", "os.spawn", "os.fork"):
        assert token not in text, token


def test_scrub_keeps_only_allowlisted_names(tmp_path):
    env = full_env(tmp_path)
    dropped = E.scrub(env)
    assert set(env) <= E.RELAY_ALLOWED_NAMES
    assert {"TRADEAI_N8N_RELAY_BEARER", "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N", "HOME", "PATH"} <= set(env)
    assert set(BROKER + PROVIDER + CREDENTIAL + PLAIN + ["SSH_AUTH_SOCK"]) <= set(dropped)
    assert not [n for n in env if classify_name(n) in ("broker", "provider")]


def test_strict_fails_closed_naming_names_only(tmp_path):
    env = full_env(tmp_path, RELAY_STRICT_ENV="1")
    before = dict(env)
    report = E.enforce(env)
    assert report["ok"] is False and report["reason"] == "relay_forbidden_env"
    assert set(report["forbidden"]["broker"]) == set(BROKER)
    assert set(report["forbidden"]["provider"]) == set(PROVIDER)
    assert set(report["forbidden"]["credential"]) == set(CREDENTIAL)
    blob = json.dumps(report)
    assert FAKE_SECRET not in blob and BEARER not in blob and KEY not in blob
    assert env == before  # a refusal changes nothing


def test_strict_passes_with_only_the_rendered_names_and_scrubs_plumbing(tmp_path):
    env = {
        "TRADEAI_N8N_RELAY_BEARER": BEARER,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": KEY,
        "TRADEAI_STATE_ROOT": str(tmp_path),
        "RELAY_STRICT_ENV": "1",
        "HOME": str(tmp_path),
        "XDG_DATA_DIRS": "/usr/share",
        "MANAGERPID": "1",
    }
    report = E.enforce(env)
    assert report == {"ok": True, "strict": True, "forbidden": {}, "dropped_count": 2}
    assert "XDG_DATA_DIRS" not in env and "MANAGERPID" not in env


def test_non_strict_scrubs_and_the_relay_then_holds_no_broker_or_provider_name(tmp_path):
    env = full_env(tmp_path)
    report = E.enforce(env)
    assert report["ok"] is True and report["strict"] is False and report["forbidden"]["broker"]
    relay = R.Relay(environ=env, allowlist=frozenset({"n8n-lab-watchdog"}))
    assert not E.forbidden_names(relay.environ)
    assert not [n for n in relay.environ if classify_name(n) in ("broker", "provider")]
    assert relay.bearer == BEARER.encode() and relay.key == KEY.encode()


def test_relay_main_exits_3_under_strict_with_a_broker_key_and_prints_names_only(tmp_path):
    # Port 1 fails guard_bind (exit 2), so a regression that skipped the env check could never bind and hang.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "RELAY_STRICT_ENV": "1",
        "TRADEAI_N8N_RELAY_BEARER": BEARER,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": KEY,
        "TRADEAI_STATE_ROOT": str(tmp_path),
        "SCHWAB_APP_SECRET": FAKE_SECRET,
        "OPENAI_API_KEY": FAKE_SECRET,
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "n8n_run_relay.py"), "--host", "127.0.0.1", "--port", "1"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 3, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["forbidden"] == {"broker": ["SCHWAB_APP_SECRET"], "provider": ["OPENAI_API_KEY"]}
    assert FAKE_SECRET not in result.stdout + result.stderr
    assert BEARER not in result.stdout + result.stderr


def _unit() -> str:
    return UNIT.read_text()


def _directives(name: str) -> list[str]:
    return [line.split("=", 1)[1] for line in _unit().splitlines() if line.startswith(name + "=")]


def test_unit_loads_no_full_secrets_environment_file():
    files = _directives("EnvironmentFile")
    assert "-%t/tradeai/env" not in files and "%t/tradeai/env" not in files
    assert files == ["-%t/tradeai/n8n-relay-secrets.env", "-%h/.config/tradeai/n8n-relay.env"]
    assert "RELAY_STRICT_ENV=1" in _directives("Environment")
    assert "PassEnvironment" not in _unit()


def test_unit_renders_the_dedicated_file_before_start_from_the_served_tree():
    pre = _directives("ExecStartPre")
    assert len(pre) == 1
    assert "%h/trade-ai-releases/portfolio-server/CURRENT/scripts/render_n8n_relay_env.py" in pre[0]
    assert "--source %t/tradeai/env" in pre[0]
    assert "--out %t/tradeai/n8n-relay-secrets.env" in pre[0]
    assert not pre[0].startswith("-"), "a failed render must stop the start, not be ignored"


SOURCE = """# Bitwarden SM render — shell-sourceable only
ALPACA_API_KEY={v}
export OPENAI_API_KEY='{v} with space'
SCHWAB_APP_SECRET={v}
TRADEAI_N8N_GATEWAY_HMAC_KEY={v}
TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N={key}
TRADEAI_N8N_RELAY_BEARER={bearer}
TRADEAI_N8N_RELAY_BEARER_PREVIOUS='{prev}'
TELEGRAM_BOT_TOKEN={v}
DB_HOST=localhost
"""


def _source(tmp_path: Path, text: str | None = None) -> Path:
    path = tmp_path / "full.env"
    path.write_text(text if text is not None else SOURCE.format(v=FAKE_SECRET, key=KEY, bearer=BEARER, prev=PREVIOUS))
    return path


def _names(text: str) -> list[str]:
    return [line.split("=", 1)[0] for line in text.splitlines() if line and not line.startswith("#")]


def test_render_writes_only_allowlisted_names_0600_and_prints_no_value(tmp_path, capsys):
    out = tmp_path / "rt" / "tradeai" / "n8n-relay-secrets.env"
    code = RENDER.main(["--source", str(_source(tmp_path)), "--out", str(out)])
    printed = capsys.readouterr().out
    assert code == 0
    text = out.read_text()
    assert _names(text) == [
        "TRADEAI_N8N_RELAY_BEARER",
        "TRADEAI_N8N_RELAY_BEARER_PREVIOUS",
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N",
    ]
    assert set(_names(text)) <= set(E.RELAY_SECRET_NAMES)
    assert FAKE_SECRET not in text
    assert f"TRADEAI_N8N_RELAY_BEARER_PREVIOUS='{PREVIOUS}'" in text  # copied byte-for-byte
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    for value in (FAKE_SECRET, BEARER, KEY, PREVIOUS):
        assert value not in printed
    report = json.loads(printed)
    assert report["ok"] is True and report["names"] == _names(text)
    assert [p.name for p in out.parent.iterdir()] == [out.name]  # no temp file left behind


def test_render_refuses_without_a_required_name_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "out.env"
    src = _source(tmp_path, f"ALPACA_API_KEY={FAKE_SECRET}\nTRADEAI_N8N_RELAY_BEARER={BEARER}\n")
    assert RENDER.main(["--source", str(src), "--out", str(out)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["missing"] == ["TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N"] and not out.exists()


def test_render_refuses_a_missing_source_and_a_multiline_value(tmp_path, capsys):
    out = tmp_path / "out.env"
    assert RENDER.main(["--source", str(tmp_path / "absent.env"), "--out", str(out)]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "source_unreadable"
    src = _source(tmp_path, f"TRADEAI_N8N_RELAY_BEARER='{BEARER}\nrest'\nTRADEAI_N8N_GATEWAY_HMAC_KEY_N8N={KEY}\n")
    assert RENDER.main(["--source", str(src), "--out", str(out)]) == 2
    printed = capsys.readouterr().out
    assert json.loads(printed)["reason"] == "unsupported_value" and BEARER not in printed
    assert not out.exists()


def test_rendered_file_then_strict_relay_env_is_clean(tmp_path, capsys):
    out = tmp_path / "relay.env"
    assert RENDER.main(["--source", str(_source(tmp_path)), "--out", str(out)]) == 0
    capsys.readouterr()
    env = {"RELAY_STRICT_ENV": "1", "HOME": str(tmp_path), "TRADEAI_STATE_ROOT": str(tmp_path)}
    for line in out.read_text().splitlines():
        if line and not line.startswith("#"):
            name, _, raw = line.partition("=")
            env[name] = raw.strip("'")
    assert E.enforce(env)["ok"] is True
    relay = R.Relay(environ=env, allowlist=frozenset({"n8n-lab-watchdog"}))
    assert relay.bearer_previous == PREVIOUS.encode()


@pytest.mark.parametrize("name", BROKER + PROVIDER)
def test_no_broker_or_provider_name_survives_enforce(tmp_path, name):
    env = {"HOME": str(tmp_path), name: FAKE_SECRET}
    E.enforce(env)
    assert name not in env
