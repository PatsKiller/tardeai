"""The gog broker must refuse an unapproved caller and never leak the secret.

Context: gog's credential lives at ~/.openclaw/credentials/gog_keyring_password.
Cursor's read guard blocks every path matching *credentials* (fail-closed), which
is why Cursor cannot publish to Drive. The broker sources the secret from Bitwarden
instead, so no agent reads that path.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BROKER = ROOT / "scripts" / "gog_broker.sh"
ALLOWLIST = ROOT / "config" / "gog_approved_agents.txt"


def _run(env_extra):
    """Run the broker with a deterministic environment.

    BW_BIN and GOG_BIN default to /bin/true so the test does not depend on
    Bitwarden or gog being installed. CI has neither, and without this the broker
    exits at the binary check before reaching the stage under test -- which is
    exactly how this file first failed in CI while passing locally.
    """
    env = dict(os.environ)
    env.setdefault("BW_BIN", "/bin/true")
    env.setdefault("GOG_BIN", "/bin/true")
    env.update({"BW_BIN": "/bin/true", "GOG_BIN": "/bin/true"})
    env.update(env_extra)
    return subprocess.run(["bash", str(BROKER), "drive", "files", "list"],
                          capture_output=True, text=True, env=env)


def test_broker_and_allowlist_exist():
    assert BROKER.is_file() and os.access(BROKER, os.X_OK)
    assert ALLOWLIST.is_file()


@pytest.mark.parametrize("agent", ["rogue-agent", "Cursor", "ursor", "grok-evil"])
def test_unapproved_agent_is_refused_ON_APPROVAL(agent):
    """Must fail *on approval*, naming the reason -- not merely fail.

    "ursor" and "grok-evil" are the cases that pin EXACT-line matching: a
    substring match (grep -qF instead of -qxF) would approve both off "cursor" and
    "grok". That mutation survived until these ids were added.

    An earlier version asserted only returncode != 0. Deleting the approval check
    outright still passed it, because an unapproved caller then fell through to the
    BW_SESSION check and failed there instead. The mutation survived. Assert the
    specific refusal, or the test cannot tell a guard from its absence.
    """
    r = _run({"TRADEAI_AGENT": agent, "BW_SESSION": "", "GOG_BIN": "/bin/true"})
    assert r.returncode != 0
    assert "not approved" in r.stderr, (
        f"expected refusal on approval for {agent!r}, got: {r.stderr.strip()[:200]}"
    )


def test_missing_agent_id_is_refused_by_name():
    r = _run({"TRADEAI_AGENT": "", "BW_SESSION": "", "GOG_BIN": "/bin/true"})
    assert r.returncode != 0
    assert "TRADEAI_AGENT is not set" in r.stderr


def test_approved_agent_gets_past_approval_and_stops_at_the_vault():
    """Positive control: an approved id must fail LATER, on the vault, not on approval.

    Without this the refusal test would pass even if the broker refused everyone.
    """
    r = _run({"TRADEAI_AGENT": "cursor", "BW_SESSION": ""})
    assert r.returncode != 0
    assert "not approved" not in r.stderr
    assert "BW_SESSION" in r.stderr


def test_broker_never_reads_the_operator_only_credentials_path():
    src = BROKER.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert ".openclaw" not in code, (
        "the broker must not read ~/.openclaw/credentials/* -- that path is "
        "operator-only and is exactly what the read guard refuses"
    )


def test_secret_is_never_echoed():
    src = BROKER.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    for bad in ("echo $secret", 'echo "$secret"', "echo $GOG_KEYRING_PASSWORD",
                'echo "$GOG_KEYRING_PASSWORD"'):
        assert bad not in code
