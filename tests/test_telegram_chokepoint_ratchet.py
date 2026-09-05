"""The Telegram chokepoint ratchet must actually execute.

`scripts/check_telegram_chokepoint.py` is a well-built behavioural guard: it
looks for the BEHAVIOUR of bypassing the transport -- raw endpoints, HTTP aimed
at Telegram, a producer selecting the chat id or reading the bot token itself --
rather than one spelling. Its own docstring records why: an earlier guard matched
only a literal URL, and thirty-nine producers walked through it while looking
centralized.

It was invoked by NOTHING. `ai_local_acceptance.sh` names it in a `case`
statement that classifies changed paths -- that is a filename in a pattern list,
not an execution. So the ratchet could not ratchet: a new bypass added today
would have been caught by no one.

This test runs it inside the only required context on `main`, so a NEW bypass
fails the build while the 133 inherited violations stay declared debt that can
only shrink.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_telegram_chokepoint.py"
BASELINE = ROOT / "config" / "telegram_chokepoint_baseline.json"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)


def test_the_checker_exists_and_is_runnable():
    assert CHECKER.is_file(), "the chokepoint checker is missing"
    assert BASELINE.is_file(), "the ratchet baseline is missing"


def test_the_ratchet_holds_on_this_tree():
    """Exit code checked for 0 exactly -- not merely 'not a crash'.

    A non-zero here means a bypass was added without declaring it.
    """
    r = _run()
    assert r.returncode == 0, (
        "telegram chokepoint ratchet failed:\n"
        f"stdout:\n{r.stdout[-3000:]}\nstderr:\n{r.stderr[-2000:]}")


def test_the_ratchet_reports_debt_or_explicit_zero():
    """While debt remains, the guard must print a violation count.

    After the bypass cohort migrations emptied the baseline, an explicit
    ``pass: zero bypasses`` line is the honest clean signal — still distinct
    from a silent vacuous pass.
    """
    r = _run()
    out = (r.stdout + r.stderr).lower()
    assert ("violation" in out) or ("zero bypasses" in out), (
        "the ratchet must state outstanding debt or an explicit zero-bypass pass"
    )


def test_the_checker_can_go_red(tmp_path):
    """Guard the guard: a NEW undeclared bypass must fail the build.

    Without this the ratchet could be vacuous -- passing because it finds
    nothing rather than because nothing new was added.
    """
    # The probe is ASSEMBLED FROM FRAGMENTS. Written literally, this test file
    # would itself contain the offending endpoint -- and the checker scans the
    # whole tree, so the guard correctly flagged the test as a new bypass. The
    # test must plant the pattern without carrying it.
    host = "api" + "." + "telegram" + "." + "org"
    probe = (
        "import requests, os\n"
        "def send():\n"
        "    tok = os.environ['TELEGRAM_" + "BOT_TOKEN']\n"
        "    cid = os.environ['TELEGRAM_" + "CHAT_ID']\n"
        f"    return requests.post(f'https://{host}/bot{{tok}}/sendMessage',\n"
        "                         json={'chat_id': cid, 'text': 'probe'})\n"
    )
    planted = ROOT / "scripts" / "_pytest_chokepoint_probe.py"
    planted.write_text(probe, encoding="utf-8")
    try:
        r = _run()
        assert r.returncode != 0, (
            "a new undeclared bypass did NOT fail the ratchet -- the guard is vacuous\n"
            f"stdout:\n{r.stdout[-2000:]}")
    finally:
        planted.unlink(missing_ok=True)
