#!/usr/bin/env python3
"""Provider (Slack/SMTP/Twilio/Meta WA) chokepoint ratchet must execute."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_provider_chokepoint.py"
BASELINE = ROOT / "config" / "provider_chokepoint_baseline.json"
ENFORCE = ROOT / "scripts" / "check_comms_gateway_enforcement.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_provider_checker_exists():
    assert CHECKER.is_file()
    assert BASELINE.is_file()


def test_provider_ratchet_holds():
    r = _run(CHECKER)
    assert r.returncode == 0, (
        "provider chokepoint ratchet failed:\n"
        f"stdout:\n{r.stdout[-3000:]}\nstderr:\n{r.stderr[-2000:]}"
    )


def test_provider_ratchet_goes_red_on_new_bypass(tmp_path):
    """Plant a Slack webhook caller outside allowlist; must fail as NEW bypass."""
    # Assemble without embedding the full forbidden string in this test file's
    # static text in a way the checker attributes to the test itself when we
    # only want the planted file to trip. The planted file is under scripts/.
    probe = ROOT / "scripts" / "_probe_provider_chokepoint_should_fail.py"
    try:
        frag = "SLACK_" + "WEBHOOK_" + "URL"
        probe.write_text(
            "import os, requests\n"
            f"url = os.environ.get('{frag}', '')\n"
            "requests.post(url, json={'text': 'x'})\n",
            encoding="utf-8",
        )
        r = _run(CHECKER)
        assert r.returncode != 0, "expected NEW slack bypass to fail the ratchet"
        assert "NEW" in (r.stdout + r.stderr)
    finally:
        if probe.exists():
            probe.unlink()


def test_comms_enforcement_wrapper_holds():
    r = _run(ENFORCE)
    assert r.returncode == 0, (
        "comms gateway enforcement failed:\n"
        f"stdout:\n{r.stdout[-3000:]}\nstderr:\n{r.stderr[-2000:]}"
    )
